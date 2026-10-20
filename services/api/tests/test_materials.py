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
    assert "摘录已截断" in context
    assert len(context) <= 700  # 总长度受 total_chars 约束

    # 未上传材料的目标注入为空串（保持原 prompt 行为不变）
    other = _create_goal(client, title="另一个目标")
    db = SessionLocal()
    try:
        assert materials_service.materials_context(db, other["id"]) == ""
    finally:
        db.close()


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
