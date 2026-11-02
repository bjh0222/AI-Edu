"""参考资料 / 例题来源：上传、列表、删除、校验、文本抽取与 prompt 注入。"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.config import settings
from app.learning.disciplines import get_profile
from app.llm import prompts
from app.services import materials as materials_service


def _create_goal(client, title: str = "掌握命令行管道与重定向") -> dict:
    resp = client.post(
        "/api/goals",
        json={
            "title": title,
            "domain_key": "computer_cli",
            "motivation": "能独立处理日志与数据流",
            "application_context": "分析服务器日志",
            "current_level": "会用 ls/cd 等基础命令",
            "time_budget": "每天 30 分钟",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _upload(client, goal_id: str, name: str, content: bytes, kind: str = "reference", ctype: str = "text/plain"):
    return client.post(
        f"/api/goals/{goal_id}/materials",
        files={"file": (name, content, ctype)},
        data={"kind": kind, "note": "课程配套资料"},
    )


def _docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            "<w:document><w:body>"
            f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
            "</w:body></w:document>",
        )
    return buffer.getvalue()


def test_material_limits(client):
    resp = client.get("/api/materials/limits")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["max_bytes"] == settings.material_max_bytes
    assert ".pdf" in body["allowed_extensions"]
    assert ".docx" in body["allowed_extensions"]
    assert {item["key"] for item in body["kinds"]} == {"reference", "example_source"}


def test_upload_list_delete_text_material(client):
    goal = _create_goal(client)
    goal_id = goal["id"]

    resp = _upload(client, goal_id, "管道入门笔记.txt", "管道 | 把一个命令的输出交给下一个命令。".encode("utf-8"))
    assert resp.status_code == 200, resp.text
    material = resp.json()
    assert material["kind"] == "reference"
    assert material["filename"] == "管道入门笔记.txt"
    assert material["ext"] == ".txt"
    assert material["size"] > 0
    assert material["extract_status"] == "ok"
    assert material["char_count"] > 0
    assert "管道" in material["excerpt_preview"]

    # 文件确实落在 MATERIALS_DIR/{goal_id}/ 下
    stored = Path(settings.materials_dir) / goal_id / f"{material['id']}.txt"
    assert stored.exists(), f"文件未落盘：{stored}"

    listed = client.get(f"/api/goals/{goal_id}/materials").json()
    assert [m["id"] for m in listed] == [material["id"]]

    resp = client.delete(f"/api/materials/{material['id']}")
    assert resp.status_code == 200, resp.text
    assert client.get(f"/api/goals/{goal_id}/materials").json() == []
    assert not stored.exists(), "删除材料时未清理磁盘文件"


def test_upload_docx_extracts_text(client):
    goal = _create_goal(client)
    payload = _docx_bytes("重定向：把输出写入文件，并区分覆盖与追加。")
    resp = _upload(
        client,
        goal["id"],
        "重定向.docx",
        payload,
        ctype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert resp.status_code == 200, resp.text
    material = resp.json()
    assert material["ext"] == ".docx"
    assert material["extract_status"] == "ok"
    assert "重定向" in material["excerpt_preview"]


def test_upload_rejects_bad_type_and_kind(client):
    goal = _create_goal(client)
    resp = _upload(client, goal["id"], "virus.exe", b"MZ")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_file_type"

    resp = _upload(client, goal["id"], "notes.md", b"# hi", kind="unknown_kind")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "bad_material_kind"

    # 空文件同样拒绝
    resp = _upload(client, goal["id"], "empty.txt", b"")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "empty_file"


def test_upload_rejects_oversize(client, monkeypatch):
    goal = _create_goal(client)
    monkeypatch.setattr(settings, "material_max_bytes", 64)
    resp = _upload(client, goal["id"], "big.txt", b"x" * 200)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "file_too_large"
    assert client.get(f"/api/goals/{goal['id']}/materials").json() == []
    # 超限文件不应留下半成品
    goal_dir = Path(settings.materials_dir) / goal["id"]
    if goal_dir.exists():
        assert not list(goal_dir.glob("*.txt"))


def test_delete_missing_material(client):
    resp = client.delete("/api/materials/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "material_not_found"


def test_materials_context_truncates_and_labels(client):
    goal = _create_goal(client)
    goal_id = goal["id"]
    long_text = "管道过滤日志的步骤说明。" * 400  # 明显超过单份注入上限
    assert _upload(client, goal_id, "长资料.md", long_text.encode("utf-8"), kind="example_source").status_code == 200

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        context = materials_service.materials_context(db, goal_id, per_file_chars=100, total_chars=600)
    finally:
        db.close()

    assert "长资料.md" in context
    assert "例题来源" in context
    assert "材料内容未完整注入" in context
    assert len(context) <= 700  # 总长度受 total_chars 约束

    # 未上传材料的目标注入为空串（保持原 prompt 行为不变）
    other = _create_goal(client, title="另一个目标")
    db = SessionLocal()
    try:
        assert materials_service.materials_context(db, other["id"]) == ""
    finally:
        db.close()


def test_materials_context_injects_raw_text_file(client):
    """纯文本材料注入文件原文：完整进入 prompt，且不做空白归一化。"""
    from app.db import SessionLocal
    from app.models import GoalMaterial

    goal = _create_goal(client)
    goal_id = goal["id"]
    head = "开头标记：管道。\n\n\n\n行A。"
    tail = "".join(f"第{i}步：过滤日志。\n" for i in range(1400))  # 约 1.7 万字
    long_text = head + tail  # 超过旧 1.2 万字 prompt 上限
    assert _upload(client, goal_id, "全文笔记.txt", long_text.encode("utf-8")).status_code == 200

    db = SessionLocal()
    try:
        context = materials_service.materials_context(db, goal_id)
        row = db.query(GoalMaterial).filter(GoalMaterial.goal_id == goal_id).one()
    finally:
        db.close()

    assert "全文笔记.txt" in context
    assert "开头标记：管道。" in context
    assert "第1399步：过滤日志。" in context  # 默认完整注入，不再截到 1.2 万字
    assert "\n\n\n\n行A。" in context  # 文件原文逐字注入，未做归一化
    assert "原始全文" in context
    assert "材料内容未完整注入" not in context
    assert row.char_count == len(long_text.strip())  # 库内正文已自愈为文件原文（仅去首尾空白）


def test_materials_context_self_heals_truncated_excerpt(client):
    """旧数据正文被截断入库时，注入会重新读文件原文并回写补全。"""
    from app.db import SessionLocal
    from app.models import GoalMaterial

    goal = _create_goal(client)
    goal_id = goal["id"]
    full = "".join(f"知识点{i}。" for i in range(1000))  # 约 6500 字
    assert _upload(client, goal_id, "旧数据.md", full.encode("utf-8")).status_code == 200

    db = SessionLocal()
    try:
        row = db.query(GoalMaterial).filter(GoalMaterial.goal_id == goal_id).one()
        row.text_excerpt = full[:100]  # 模拟旧版本截断入库
        row.char_count = 100
        db.commit()

        context = materials_service.materials_context(db, goal_id)
        db.refresh(row)
    finally:
        db.close()

    assert "知识点999。" in context
    assert row.char_count == len(full)


def test_oversize_material_is_truncated_loudly_not_silently(client, monkeypatch):
    """回归：超长材料必须「截断且显式告知」，不得静默丢弃后半本。

    真实故障：extract_text 截到 MAX_EXCERPT_CHARS 却仍返回 status='ok'，
    前端显示「已抽取正文」，提示词也不标注 —— 45 万字的书只有前 20 万字可见，
    用户与模型都以为读了全本。对「原文忠实性」是致命伤。
    """
    from app.db import SessionLocal
    from app.models import GoalMaterial

    # 把上限调到很小的值，避免测试真的造 20 万字字符串
    monkeypatch.setattr(materials_service, "MAX_EXCERPT_CHARS", 500)

    goal = _create_goal(client)
    goal_id = goal["id"]
    full = "".join(f"第{i}段原文。" for i in range(400))  # 约 3200 字 > 500
    resp = _upload(client, goal_id, "哲学通论第一章.md", full.encode("utf-8"))
    assert resp.status_code == 200, resp.text

    material = resp.json()
    assert material["extract_status"] == "truncated"      # 不再是 ok
    assert material["char_count"] == 500                  # 实际入库字数
    assert material["source_char_count"] == len(full)     # 原文字数被如实记录

    db = SessionLocal()
    try:
        context = materials_service.materials_context(db, goal_id)
        row = db.query(GoalMaterial).filter(GoalMaterial.goal_id == goal_id).one()
        # 注入侧也必须遵守同一上限：这是「两条路径字数矛盾」的另一半
        assert row.char_count == 500
        assert len(row.text_excerpt) == 500
    finally:
        db.close()

    # 提示词必须显式声明不完整，并禁止模型编造缺失部分
    assert "已被截断" in context
    assert "后段内容不可见" in context
    assert "不得声称已通读全文" in context


def test_material_body_does_not_bypass_injection_cap(client, monkeypatch):
    """回归：注入路径不得绕过入库上限把整本书塞进 prompt。

    _material_body 曾直接 path.read_bytes() 读原文全量返回，与入库侧的
    text[:MAX_EXCERPT_CHARS] 相互矛盾：同一份材料库里 20 万字、提示词里 45 万字，
    足以撑爆上下文且毫无警告。两条路径必须共用 _cap_text。
    """
    from app.db import SessionLocal
    from app.models import GoalMaterial

    goal = _create_goal(client)
    goal_id = goal["id"]
    full = "".join(f"句子{i}。" for i in range(600))       # 先按默认上限正常入库
    assert _upload(client, goal_id, "长文.md", full.encode("utf-8")).status_code == 200

    db = SessionLocal()
    try:
        row = db.query(GoalMaterial).filter(GoalMaterial.goal_id == goal_id).one()
        assert row.extract_status == "ok"
        assert row.source_char_count == len(full)

        # 事后把上限调小，再取注入正文：必须按新上限截断，而不是返回文件全量
        monkeypatch.setattr(materials_service, "MAX_EXCERPT_CHARS", 300)
        body = materials_service._material_body(db, row)
        db.refresh(row)
        assert len(body) == 300, f"注入正文 {len(body)} 字，绕过了上限"
        assert row.extract_status == "truncated"
        assert row.char_count == 300
        assert row.source_char_count == len(full)
    finally:
        db.close()


def test_normal_size_material_still_reports_ok(client):
    """未超上限的材料不受影响：状态仍是 ok，source_char_count 与 char_count 相等。"""
    goal = _create_goal(client)
    goal_id = goal["id"]
    text = "第一章 导论\n\n" + "".join(f"正文{i}。" for i in range(50))
    resp = _upload(client, goal_id, "普通材料.md", text.encode("utf-8"))
    assert resp.status_code == 200, resp.text
    m = resp.json()
    assert m["extract_status"] == "ok"
    assert m["source_char_count"] == m["char_count"] > 0


def test_prompt_includes_materials_only_when_present(client):
    goal_obj = type(
        "G",
        (),
        {
            "title": "掌握命令行管道与重定向",
            "motivation": "处理日志",
            "application_context": "分析日志",
            "current_level": "基础",
            "time_budget": "每天 30 分钟",
        },
    )()
    profile = get_profile("computer_cli")

    _, user_without = prompts.diagnose(goal_obj, profile)
    assert "用户上传的参考资料" not in user_without

    _, user_with = prompts.diagnose(
        goal_obj, profile, "[材料 1] 笔记.txt（参考资料，1.0KB，正文已抽取）\n管道即数据流。"
    )
    assert "用户上传的参考资料" in user_with
    assert "笔记.txt" in user_with

    _, plan_user = prompts.plan(goal_obj, profile, "[材料 1] 例题.md（例题来源，2.0KB，正文已抽取）\n练习题")
    assert "例题.md" in plan_user
    _, outline_user = prompts.outline(goal_obj, profile, [], "材料占位")
    assert "材料占位" in outline_user
    _, section_user = prompts.section(goal_obj, profile, {"title": "第 1 节"}, [], [], "材料占位")
    assert "材料占位" in section_user


def test_diagnose_and_plan_work_with_materials(client):
    """上传材料后，诊断 / 计划仍按原接口行为返回（不改变接口契约）。"""
    goal = _create_goal(client)
    goal_id = goal["id"]
    assert _upload(client, goal_id, "日志样本.txt", b"ERROR 500 at 12:01").status_code == 200

    resp = client.post(f"/api/goals/{goal_id}/diagnose")
    assert resp.status_code == 200, resp.text
    assert resp.json()["recommendation"]

    resp = client.post(f"/api/goals/{goal_id}/plan")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["steps"]) >= 4


@pytest.fixture(autouse=True)
def _cleanup_materials_dir():
    yield
    root = Path(settings.materials_dir)
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            path.unlink() if path.is_file() else path.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass
def test_chapter_marker_normalizes_chinese_and_arabic_numerals():
    """章号必须归一化后再比：「第 1 章」与「第一章」要能匹配上。

    不归一的话按章注入会静默退化成一节材料都拿不到 —— 模型看不到任何正文，
    却不会报错，只会开始编。这是整个按章注入最容易失效的地方。
    """
    assert materials_service.chapter_marker("第一章 导论") == "1"
    assert materials_service.chapter_marker("第 1 章 线性方程组") == "1"
    assert materials_service.chapter_marker("第十二章") == "12"
    assert materials_service.chapter_marker("第二十三章 认识论") == "23"
    assert materials_service.chapter_marker("第十章") == "10"
    assert materials_service.chapter_marker("第一百章") == "100"
    # 无章号：文件名式的全书级材料 / 普通讲义
    assert materials_service.chapter_marker("前言") is None
    assert materials_service.chapter_marker("目录.md") is None
    assert materials_service.chapter_marker("") is None


def test_is_global_material_identifies_book_level_files():
    """全书级材料（目录 / 前言 / 索引）不按章过滤，每节都要注入。"""
    for name in ("目录.md", "前言.txt", "全书索引.md", "序言.md", "TOC.md", "contents.md"):
        assert materials_service.is_global_material(name), name
    for name in ("第一章.md", "第二章 存在论.md", "讲义.md", "论文.pdf"):
        assert not materials_service.is_global_material(name), name


def test_slice_chapter_extracts_one_chapter_from_single_file_book():
    """整本书存成一个 md 时，按内部章标题切出指定章。

    这样用户不必手工拆成 12 个文件；切出的片段自带章标题行，
    模型能确认自己读到的是哪一章，不会把上一章的结论当本章的。
    """
    book = (
        "《哲学通论》\n\n"
        "## 第一章 导论\n哲学是理论思维的前提批判。\n\n"
        "## 第二章 存在论\n存在是哲学的基本问题。\n\n"
        "## 第三章 认识论\n认识的界限需要澄清。\n"
    )
    first = materials_service.slice_chapter(book, "1")
    assert first.startswith("## 第一章 导论")
    assert "前提批判" in first
    assert "存在是哲学的基本问题" not in first    # 不含下一章

    second = materials_service.slice_chapter(book, "2")
    assert second.startswith("## 第二章 存在论")
    assert "前提批判" not in second

    # 中文章号也能命中（材料写「第二章」，大纲给的是归一化后的 "2"）
    assert materials_service.slice_chapter(book, "3").startswith("## 第三章")
    # 书里没有第 9 章 -> None，调用方据此判断「文件有章结构但不含本章」
    assert materials_service.slice_chapter(book, "9") is None
    # 没有章结构的讲义 -> None
    assert materials_service.slice_chapter("一份没有章节的讲义。\n第二段。\n", "1") is None


def test_chapter_marker_of_any_distinguishes_book_from_handout():
    """区分「整本书一个文件」与「单份无章节讲义」。

    前者必须切片或跳过，后者是全书级材料、每节都要注入。
    判错方向会把讲义整份过滤掉，模型拿不到任何材料。
    """
    assert materials_service.chapter_marker_of_any("## 第一章 导论\n内容") == "1"
    assert materials_service.chapter_marker_of_any("# 第一章\n内容") == "1"
    assert materials_service.chapter_marker_of_any("这是一份讲义。\n第二段。") is None
    assert materials_service.chapter_marker_of_any("") is None
    # 代码块里的 # 不是标题
    assert materials_service.chapter_marker_of_any("```md\n# 第一章 示例\n```") is None


def test_materials_context_injects_only_target_chapter(client):
    """按章注入：本节只拿到自己那一章 + 全书级材料，其它章只留一行清单。

    这是「分章上传 -> 每章只读自己那章」的核心保证。不切片时 40 万字的书
    按 0.70 token/字 换算是 28 万 token/节，单节直接超上下文窗口。
    """
    from app.db import SessionLocal
    from app.models import GoalMaterial

    goal = _create_goal(client)
    goal_id = goal["id"]
    files = {
        "目录.md": "《哲学通论》目录\n第一章 导论\n第二章 存在论\n第三章 认识论\n",
        "第一章.md": "## 第一章 导论\n" + "哲学是理论思维的前提批判。" * 300,
        "第二章.md": "## 第二章 存在论\n" + "存在是哲学的基本问题。" * 300,
        "第三章.md": "## 第三章 认识论\n" + "认识的界限需要澄清。" * 300,
    }
    for name, text in files.items():
        assert _upload(client, goal_id, name, text.encode("utf-8")).status_code == 200

    db = SessionLocal()
    try:
        full = materials_service.materials_context(db, goal_id)
        for chapter, own_kw, other_kw in [
            ("1", "前提批判", "存在是哲学的基本问题"),
            ("2", "存在是哲学的基本问题", "前提批判"),
            ("3", "认识的界限需要澄清", "前提批判"),
        ]:
            ctx = materials_service.materials_context(
                db, goal_id, chapter=chapter, all_chapters=["1", "2", "3"]
            )
            assert own_kw in ctx, f"第 {chapter} 章应含本章内容"
            assert other_kw not in ctx, f"第 {chapter} 章不得含其它章正文"
            assert "《哲学通论》目录" in ctx, "全书级材料应始终注入"
            assert "本次按章注入" in ctx, "必须显式声明按章注入"
            assert "不要引用或猜测其内容" in ctx
            # 按章注入必须显著小于全量
            assert len(ctx) < len(full) * 0.7, (len(ctx), len(full))
    finally:
        db.close()


def test_materials_context_global_only_excludes_all_chapter_bodies(client):
    """global_only：只注入全书级材料，一份章节正文都不给。

    用于阅读规范的「全书认知地图」与后置全书层 —— 需要全书骨架，不需要任何一章细节。
    """
    from app.db import SessionLocal

    goal = _create_goal(client)
    goal_id = goal["id"]
    _upload(client, goal_id, "目录.md", "《哲学通论》目录\n第一章 导论\n".encode("utf-8"))
    _upload(client, goal_id, "第一章.md", ("## 第一章 导论\n" + "哲学是前提批判。" * 200).encode("utf-8"))

    db = SessionLocal()
    try:
        ctx = materials_service.materials_context(db, goal_id, global_only=True)
    finally:
        db.close()

    assert "《哲学通论》目录" in ctx
    assert "哲学是前提批判。" not in ctx
    assert "未注入任何章节正文" in ctx
    assert "第一章.md" in ctx          # 清单里点名，避免模型以为材料不存在而编造


def test_materials_context_chapter_none_keeps_full_injection(client):
    """硬边界：不传 chapter / global_only 时行为与从前逐字一致。

    练习与试卷规范依赖全量注入，按章逻辑不得泄漏到它们身上。
    """
    from app.db import SessionLocal

    goal = _create_goal(client)
    goal_id = goal["id"]
    text = "## 第一章 导论\n" + "哲学是前提批判。" * 200
    _upload(client, goal_id, "第一章.md", text.encode("utf-8"))

    db = SessionLocal()
    try:
        default = materials_service.materials_context(db, goal_id)
        explicit_none = materials_service.materials_context(db, goal_id, chapter=None)
    finally:
        db.close()

    assert default == explicit_none
    assert "哲学是前提批判。" in default
    assert "本次按章注入" not in default

