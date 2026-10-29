"""教程重构 v2 测试：能力层级 / 额外练习开关 / 配套文件与双链 / 输出归一化。"""

import time

from app.learning.levels import normalize_level
from app.services.tutorials import _normalize_outline_items, _normalize_section_raw


def _create_goal(client, **overrides) -> dict:
    payload = {
        "title": "掌握命令行管道与重定向",
        "domain_key": "cs_it",
        "motivation": "能独立处理日志与数据流",
        "application_context": "分析服务器日志",
        "current_level": "会用 ls/cd 等基础命令",
        "time_budget": "共 10 小时",
    }
    payload.update(overrides)
    resp = client.post("/api/goals", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _poll_job(client, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("生成任务未在预期时间内结束")


def _quickstart(client, goal_id: str) -> dict:
    resp = client.post(f"/api/goals/{goal_id}/tutorials/quickstart")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------- 目标字段

def test_goal_capability_defaults_and_explicit(client):
    goal = _create_goal(client)
    assert goal["capability_level"] == "L2"  # 默认层级
    assert goal["generate_extra_exercises"] is False  # 默认关闭额外练习

    goal2 = _create_goal(
        client,
        title="用统计方法分析数据",
        domain_key="math_logic",
        capability_level="L1",
        generate_extra_exercises=True,
    )
    assert goal2["capability_level"] == "L1"
    assert goal2["generate_extra_exercises"] is True

    # 编辑：层级与开关可更新
    resp = client.patch(
        f"/api/goals/{goal2['id']}",
        json={"capability_level": "L3", "generate_extra_exercises": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["capability_level"] == "L3"
    assert body["generate_extra_exercises"] is False


def test_normalize_level_fallback():
    assert normalize_level(None) == "L2"
    assert normalize_level("") == "L2"
    assert normalize_level("l1") == "L1"
    assert normalize_level("L9") == "L2"
    assert normalize_level("L3") == "L3"


def test_criteria_differ_by_level(client):
    l1 = _create_goal(client, title="命令行 L1", capability_level="L1")
    l3 = _create_goal(client, title="命令行 L3", capability_level="L3")
    c1 = client.post(f"/api/goals/{l1['id']}/criteria").json()
    c3 = client.post(f"/api/goals/{l3['id']}/criteria").json()
    assert len(c1) >= 3 and len(c3) >= 3
    # L1 不要求迁移；L3 的迁移任务要求解释决策依据
    l1_text = " ".join(c["statement"] + c["rationale"] for c in c1)
    assert "L1" in l1_text
    l3_transfer = next(c for c in c3 if c["evidence_type"] == "transfer")
    assert "依据" in (l3_transfer["conditions"] + l3_transfer["pass_rule"])


# ---------------------------------------------------------------- 配套文件与双链

def test_quickstart_with_extra_exercises_and_wikilinks(client):
    goal = _create_goal(client, capability_level="L2", generate_extra_exercises=True)
    body = _quickstart(client, goal["id"])
    job = _poll_job(client, body["job_id"])
    assert job["status"] == "done", job

    tutorial = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()
    content = tutorial["current_version"]["content"]
    assert report_passed(tutorial)

    # v2 章节结构：content 内容块非空，含必要练习
    sections = content["sections"]
    assert len(sections) >= 3
    for s in sections:
        assert s.get("content"), s
        assert all(b.get("body", "").strip() for b in s["content"])
    assert any(s.get("exercises") for s in sections)

    # 配套文件都在内容里，且文件名一致
    cheat = content["cheatsheet"]
    extra = content["extra_exercises"]
    assert cheat and cheat["sections"] and cheat["filename"].endswith("知识速查")
    assert extra and extra["exercises"] and extra["filename"].endswith("额外练习")

    # 主教程导出：双链指向真实生成的文件名
    resp = client.get(f"/api/tutorials/{tutorial['id']}/export")
    assert resp.status_code == 200
    md = resp.text
    assert f"[[{cheat['filename']}]]" in md
    assert f"[[{extra['filename']}]]" in md
    assert not md.startswith("---")
    assert "ai_edu:" not in md

    # 配套文件可导出，文件名与双链一致（header 中文件名为 URL 编码）
    from urllib.parse import unquote

    r1 = client.get(f"/api/tutorials/{tutorial['id']}/export/cheatsheet")
    assert r1.status_code == 200
    assert cheat["filename"] + ".md" in unquote(r1.headers["content-disposition"])
    assert cheat["sections"][0]["heading"] in r1.text
    r2 = client.get(f"/api/tutorials/{tutorial['id']}/export/exercises")
    assert r2.status_code == 200
    assert extra["filename"] + ".md" in unquote(r2.headers["content-disposition"])
    assert "参考答案" in r2.text
    assert extra["exercises"][0]["task"] in r2.text
    # 速查文件回链主教程（主教程导出文件名 = {目标}-教程）
    assert f"[[{goal['title']}-教程]]" in r1.text


def test_quickstart_without_extra_exercises(client):
    goal = _create_goal(client, generate_extra_exercises=False)
    body = _quickstart(client, goal["id"])
    _poll_job(client, body["job_id"])

    tutorial = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()
    content = tutorial["current_version"]["content"]
    assert report_passed(tutorial)
    # 速查总生成；额外练习不生成
    assert content["cheatsheet"] and content["cheatsheet"]["sections"]
    assert not content.get("extra_exercises")

    r1 = client.get(f"/api/tutorials/{tutorial['id']}/export/cheatsheet")
    assert r1.status_code == 200
    r2 = client.get(f"/api/tutorials/{tutorial['id']}/export/exercises")
    assert r2.status_code == 404
    assert r2.json()["detail"]["code"] == "exercises_not_found"

    # 教程正文的必要练习不受开关影响
    sections = content["sections"]
    assert any(s.get("exercises") for s in sections)


# ---------------------------------------------------------------- 输出归一化（模型异常输出不崩溃）

def test_normalize_section_raw_handles_bad_model_output():
    raw = {
        "title": "章节",
        "purpose": None,
        "content_type": "not-a-type",  # 非法枚举 → mixed
        "content": [
            {"type": "magic", "title": "坏类型块", "body": "内容"},  # 非法类型 → text
            {"type": "text", "title": "", "body": "   "},  # 空 body → 丢弃
            "not-a-dict",  # 非法结构 → 丢弃
            {"type": "key_point", "title": "结论", "body": "X > 0"},
        ],
        "exercises": None,
        "common_errors": [{"error": ""}, {"error": "路径错误", "cause": "c", "diagnose": "d"}, "junk"],
        "sources": [{"title": "官方文档", "url": "https://example.com", "note": ""}],
        "mapping_criteria": "not-a-list",
        "key_takeaways": ["结论1", ""],
    }
    data = _normalize_section_raw(raw)
    assert data["content_type"] == "mixed"
    assert [b["type"] for b in data["content"]] == ["text", "key_point"]
    assert data["content"][0]["title"] == "坏类型块"
    assert data["exercises"] == []
    assert data["mapping_criteria"] == []
    assert len(data["common_errors"]) == 1
    assert data["common_errors"][0]["error"] == "路径错误"
    assert len(data["sources"]) == 1
    assert data["key_takeaways"] == ["结论1"]


def test_normalize_section_raw_defaults():
    data = _normalize_section_raw({"title": "只有标题"})
    assert data["content"] == []
    assert data["exercises"] == []
    assert data["common_errors"] == []
    assert data["sources"] == []
    assert data["mapping_criteria"] == []


def test_section_payload_does_not_require_mapping_criteria(monkeypatch):
    """章节提示词并不要求模型输出 mapping_criteria：缺这个字段不能判失败、更不能触发整章重试。

    章节落库时 mapping_criteria 一律由大纲的 criteria_ids 覆盖（tutorials.py 的章节写入处），
    所以这里同时验证：模型漏输出时退回大纲已声明的映射，不丢验收标准覆盖关系。
    """
    from app.llm.service import AIService

    ai = AIService(None)
    monkeypatch.setattr(type(ai), "is_demo", property(lambda self: False))
    required_seen: list[tuple] = []

    def fake_real_json(feature, system, user, required, goal=None):
        required_seen.append(required)
        # 模型严格按提示词输出：只有 title / content，没有 mapping_criteria
        return {
            "title": "管道的用法",
            "content": [{"type": "text", "title": "管道", "body": "把前一个命令的输出接到下一个"}],
        }

    monkeypatch.setattr(ai, "_real_json", fake_real_json)

    goal = type(
        "G",
        (),
        {
            "title": "掌握命令行管道",
            "motivation": "",
            "application_context": "",
            "current_level": "",
            "time_budget": "",
            "capability_level": "L2",
            "user_notes": "",
        },
    )()
    discipline = type("D", (), {"display_name": "计算机/命令行"})()
    item = {"title": "管道的用法", "criteria_ids": ["c1", "c2"]}

    data = ai.section(goal, discipline, item, [], [])

    assert "mapping_criteria" not in required_seen[0], "模型漏输出这项是可接受的，不能列为必填"
    assert data["mapping_criteria"] == ["c1", "c2"], "应退回大纲已声明的验收标准 id"


def test_section_retries_with_compression_hint_when_truncated(monkeypatch):
    """输出被长度上限截断时不能原样重发：要带「压缩篇幅」要求重试一次。

    原样重试几乎必然再次截断，会白烧 N 次完整模型往返（单章动辄上万 token）后才失败。
    """
    from app.llm.service import AIService, AIServiceError

    ai = AIService(None)
    monkeypatch.setattr(type(ai), "is_demo", property(lambda self: False))
    seen: list[str] = []

    def fake_real_json(feature, system, user, required, goal=None):
        seen.append(user)
        if len(seen) == 1:
            raise AIServiceError(
                "模型输出被截断（finish_reason=length）：单次输出超出上限，可重试或拆小章节"
            )
        return {
            "title": "管道的用法",
            "content": [{"type": "text", "title": "管道", "body": "把前一个命令的输出接到下一个"}],
        }

    monkeypatch.setattr(ai, "_real_json", fake_real_json)

    goal = type(
        "G",
        (),
        {
            "title": "掌握命令行管道",
            "motivation": "",
            "application_context": "",
            "current_level": "",
            "time_budget": "",
            "capability_level": "L2",
            "user_notes": "",
        },
    )()
    discipline = type("D", (), {"display_name": "计算机/命令行"})()
    item = {"title": "管道的用法", "criteria_ids": ["c1"]}

    data = ai.section(goal, discipline, item, [], [])

    assert len(seen) == 2, "截断后只应重试一次"
    assert "被截断" in seen[1], "第二次请求必须告诉模型上一稿被截断了"
    assert "12000 字以内" in seen[1], "必须给出明确的压缩目标"
    assert data["title"] == "管道的用法"


def test_normalize_outline_items():
    items = _normalize_outline_items(
        [
            {"title": "A", "purpose": "作用", "content_type": "concept", "summary": "s", "criteria_ids": ["c1"]},
            {"title": "B", "content_type": "weird"},  # 非法类型 → mixed；purpose 回退 summary
        ]
    )
    assert items[0]["purpose"] == "作用"
    assert items[0]["content_type"] == "concept"
    assert items[1]["content_type"] == "mixed"
    assert items[1]["purpose"] == ""
    assert all("id" in item and len(item["id"]) == 8 for item in items)


def test_quickstart_backfills_missing_companions(client):
    """已有章节的旧教程：开启选项后一键生成应补齐缺失的配套文件，且不重复生成正文。"""
    import json as _json

    from app.db import SessionLocal
    from app.models import TutorialVersion

    goal = _create_goal(client, generate_extra_exercises=False)
    body = _quickstart(client, goal["id"])
    _poll_job(client, body["job_id"])
    tutorial = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()
    assert tutorial["current_version"]["content"]["cheatsheet"]
    assert not tutorial["current_version"]["content"].get("extra_exercises")
    sections_before = tutorial["current_version"]["content"]["sections"]
    version_before = tutorial["current_version"]["version"]

    # 模拟旧数据：开启选项 + 抹掉已有速查
    resp = client.patch(f"/api/goals/{goal['id']}", json={"generate_extra_exercises": True})
    assert resp.status_code == 200
    db = SessionLocal()
    try:
        v = db.get(TutorialVersion, tutorial["current_version"]["id"])
        content = _json.loads(v.content_json)
        content["cheatsheet"] = None
        v.content_json = _json.dumps(content, ensure_ascii=False)
        db.commit()
    finally:
        db.close()

    again = _quickstart(client, goal["id"])
    steps = {s["key"]: s for s in again["steps"]}
    assert again["job_id"]  # 配套文件已后台化：立即返回 job_id，不再同步阻塞请求
    assert steps["sections"]["status"] == "reused"
    assert steps["companions"]["status"] == "created"
    assert "知识速查" in steps["companions"]["detail"]
    assert "额外练习" in steps["companions"]["detail"]

    job = _poll_job(client, again["job_id"])
    assert job["status"] == "done", job
    assert job["job_type"] == "tutorial_companions"

    tutorial2 = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()
    content2 = tutorial2["current_version"]["content"]
    assert tutorial2["current_version"]["version"] == version_before + 1
    assert content2["cheatsheet"] and content2["cheatsheet"]["sections"]
    assert content2["extra_exercises"] and content2["extra_exercises"]["exercises"]
    assert content2["sections"] == sections_before  # 正文未被重新生成

    # 再来一次：全部齐备 → reused，且不再提交后台任务
    third = _quickstart(client, goal["id"])
    steps3 = {s["key"]: s for s in third["steps"]}
    assert third["job_id"] is None
    assert steps3["companions"]["status"] == "reused"


# ---------------------------------------------------------------- helper


def report_passed(tutorial: dict) -> bool:
    return tutorial["current_version"]["quality_report"]["passed"] is True


# ---------------------------------------------------------------- 导出：无标签 + 双链有效

def _active_markdown(md: str) -> str:
    """去掉围栏代码块与行内代码，只保留会生效的 Markdown 文本。"""
    import re

    without_fences = re.sub(r"```.*?```", "", md, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", without_fences)


def _active_links(md: str) -> set[str]:
    import re

    targets = set()
    for token in re.findall(r"!?\[\[([^\[\]\n]+)\]\]", _active_markdown(md)):
        target = token.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            targets.add(target.removesuffix(".md"))
    return targets


def _active_tags(md: str) -> list[str]:
    import re

    return re.findall(
        r"(?<![\w#])#[A-Za-z0-9_\u4e00-\u9fff][\w\u4e00-\u9fff/-]*", _active_markdown(md)
    )


def test_export_has_no_obsidian_tags(client):
    """导出的教程与配套文件不应带会生效的 Obsidian 标签。"""
    goal = _create_goal(client, title="命令行标签检查", generate_extra_exercises=False)
    body = _quickstart(client, goal["id"])
    _poll_job(client, body["job_id"])

    tutorial_id = body["tutorial"]["id"]
    main = client.get(f"/api/tutorials/{tutorial_id}/export").text
    cheat = client.get(f"/api/tutorials/{tutorial_id}/export/cheatsheet").text

    assert _active_tags(main) == []
    assert _active_tags(cheat) == []
    assert not main.startswith("---")


def test_export_wikilinks_only_point_to_delivered_files(client):
    """主教程与配套文件里的双链必须指向本次实际交付的文件名。"""
    goal = _create_goal(client, title="命令行双链检查", generate_extra_exercises=True)
    body = _quickstart(client, goal["id"])
    _poll_job(client, body["job_id"])

    tutorial_id = body["tutorial"]["id"]
    tutorial = client.get(f"/api/tutorials/{tutorial_id}").json()
    content = tutorial["current_version"]["content"]
    cheat_name = content["cheatsheet"]["filename"]
    extra_name = content["extra_exercises"]["filename"]
    main_name = f"{goal['title']}-教程"

    main = client.get(f"/api/tutorials/{tutorial_id}/export").text
    cheat = client.get(f"/api/tutorials/{tutorial_id}/export/cheatsheet").text
    extra = client.get(f"/api/tutorials/{tutorial_id}/export/exercises").text

    assert _active_links(main) == {cheat_name, extra_name}
    assert _active_links(cheat) == {main_name}
    assert _active_links(extra) == {main_name}


def test_normalize_obsidian_syntax_keeps_examples_but_disables_them():
    from app.services.tutorials import normalize_obsidian_syntax

    md = "\n".join(
        [
            "# 标题不含标签",
            "正文引用配套文件：[[真实配套]]，占位链接 [[...]] 与示例 [[笔记名]]。",
            "分类： #命令行 #基础/管道",
            "行内代码 `[[示例]]` 与 `#标签` 保持原样。",
            "```powershell",
            "# 这是 PowerShell 注释，不是标签",
            "Get-ChildItem | Sort-Object",
            "```",
        ]
    )
    out = normalize_obsidian_syntax(md, {"真实配套"})
    assert "[[真实配套]]" in out
    assert "`[[...]]`" in out
    assert "`[[笔记名]]`" in out
    assert "`#命令行`" in out
    assert "`#基础/管道`" in out
    assert "`[[示例]]`" in out
    assert "# 这是 PowerShell 注释" in out

    active = _active_markdown(out)
    assert "[[真实配套]]" in active
    assert "[[" not in active.replace("[[真实配套]]", "")
    assert _active_tags(out) == []


def test_section_prompt_forbids_tags_and_guesses(client):
    """章节提示词必须注入禁标签规则与确切的配套文件名。"""
    from app.llm.prompts import WIKILINK_RULE, section

    class FakeGoal:
        title = "目标标题"
        motivation = "动机"
        application_context = "场景"
        current_level = "基础"
        time_budget = "共 10 小时"
        capability_level = "L2"
        generation_tier = "standard"
        generate_extra_exercises = True
        user_notes = ""

    class FakeDiscipline:
        display_name = "计算机科学与信息技术"

    system, user = section(
        FakeGoal(), FakeDiscipline(), {"title": "节", "content_type": "concept"},
        [], [], "", ["目标标题-知识速查", "目标标题-额外练习"],
    )
    assert "不要添加 Obsidian 笔记属性" in system
    assert "#标签" in system
    assert "[[目标标题-知识速查]]" in user
    assert "[[目标标题-额外练习]]" in user
    assert "[[...]]" in WIKILINK_RULE and "占位" in WIKILINK_RULE
