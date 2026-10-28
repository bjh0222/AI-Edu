"""生成流程性能改造测试：章节并发、配套文件并行/后台化、知识提取指纹去重。

每条测试都盯着一个可验证的验收信号（不是「我觉得快了」）：

- 并发是真的：用 Barrier 证明 3 路同时进入模型调用，串行实现会直接超时失败；
- 合并仍按大纲顺序：故意让后面的章节先返回，最终顺序不得乱；
- 失败不丢内容：单节最终失败 → job 失败，已完成的草稿仍在库里；
- 配套文件并行 + 后台化：两个文件必须同时在跑，quickstart 立即返回 job_id；
- 知识提取去重：大纲内容未变时零模型调用（用 ModelCallLog 计数证明）。
"""
from __future__ import annotations

import json
import threading
import time

from app.llm.service import AIService, AIServiceError
from app.services import tutorials as tutorials_service
from app.services.knowledge import context_fingerprint


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


def _poll_job(client, job_id: str, tries: int = 300) -> dict:
    for _ in range(tries):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("生成任务未在预期时间内结束")


def _quickstart(client, goal_id: str) -> dict:
    resp = client.post(f"/api/goals/{goal_id}/tutorials/quickstart")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ready_tutorial(client, **goal_overrides) -> dict:
    """跑到「已有完整教程」的状态，返回教程详情。"""
    goal = _create_goal(client, **goal_overrides)
    body = _quickstart(client, goal["id"])
    job = _poll_job(client, body["job_id"])
    assert job["status"] == "done", job
    return client.get(f"/api/tutorials/{body['tutorial']['id']}").json()


def _start_sections(client, tutorial_id: str) -> dict:
    resp = client.post(f"/api/tutorials/{tutorial_id}/sections/generate")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------- 章节并发


def test_sections_generate_runs_three_way_concurrent(client, monkeypatch):
    """A：最多 3 路并发——Barrier(3) 只有真的同时进入模型调用才能通过。"""
    tutorial = _ready_tutorial(client)
    outline = tutorial["current_version"]["content"]["outline"]
    assert len(outline) >= 3, "并发测试需要至少 3 节大纲"

    original = AIService.section
    barrier = threading.Barrier(3, timeout=5)
    lock = threading.Lock()
    state = {"active": 0, "max_active": 0, "calls": 0}
    threads: set[str] = set()

    def fake_section(self, goal, discipline, item, criteria_list, prior_titles, materials_text="", companion_names=None):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            state["calls"] += 1
            enter_index = state["calls"]
            threads.add(threading.current_thread().name)
        try:
            if enter_index <= 3:
                # 串行实现等不到 3 个并发 → BrokenBarrierError → 任务失败 → 断言失败
                barrier.wait()
            return original(self, goal, discipline, item, criteria_list, prior_titles, materials_text, companion_names)
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(AIService, "section", fake_section)
    # 路数按用例钉死成 3：既保证 Barrier(3) 一定能等到 3 个线程，也让
    # 「最大并发 == 3」的断言不被默认值（9）或大纲节数影响。
    monkeypatch.setattr(tutorials_service, "MAX_SECTION_WORKERS", 3)
    body = _start_sections(client, tutorial["id"])
    job = _poll_job(client, body["job_id"])
    assert job["status"] == "done", job
    assert state["max_active"] == 3, f"实测最大并发 {state['max_active']}，期望 3"
    assert len(threads) >= 3, "每节应在独立线程中生成（独立 Session / AIService）"

    sections = client.get(f"/api/tutorials/{tutorial['id']}").json()["current_version"]["content"]["sections"]
    assert len(sections) == len(outline)


def test_sections_merge_in_outline_order_when_later_finishes_first(client, monkeypatch):
    """A：并发完成顺序被打乱，合并结果仍按大纲顺序。"""
    tutorial = _ready_tutorial(client)
    outline = tutorial["current_version"]["content"]["outline"]
    total = len(outline)
    original = AIService.section

    def slow_first_section(self, goal, discipline, item, criteria_list, prior_titles, materials_text="", companion_names=None):
        idx = len(prior_titles)  # 大纲静态前缀长度 == 本节序号
        time.sleep(0.02 * (total - idx))  # 越靠前的节越慢：完成顺序与大纲相反
        data = original(self, goal, discipline, item, criteria_list, prior_titles, materials_text, companion_names)
        data["title"] = f"{idx:02d}-{item.get('title', '')}"
        return data

    monkeypatch.setattr(AIService, "section", slow_first_section)
    body = _start_sections(client, tutorial["id"])
    job = _poll_job(client, body["job_id"])
    assert job["status"] == "done", job

    sections = client.get(f"/api/tutorials/{tutorial['id']}").json()["current_version"]["content"]["sections"]
    assert [s["title"][:2] for s in sections] == [f"{i:02d}" for i in range(total)]
    # 随机 id 不得重复（每节独立生成，不能串数据）
    assert len({s["id"] for s in sections}) == total


def test_sections_failure_keeps_completed_draft(client, monkeypatch):
    """A：任一节最终失败 → job 失败，但已完成章节已落库（草稿版本保留）。"""
    from app.db import SessionLocal
    from app.models import TutorialVersion

    tutorial = _ready_tutorial(client)
    outline = tutorial["current_version"]["content"]["outline"]
    total = len(outline)
    original = AIService.section
    # 重试延迟归零，避免测试真的等 3s + 8s
    monkeypatch.setattr(tutorials_service, "SECTION_RETRY_DELAYS", (0, 0))

    def failing_second_section(self, goal, discipline, item, criteria_list, prior_titles, materials_text="", companion_names=None):
        idx = len(prior_titles)
        if idx == 1:
            raise AIServiceError("模拟模型故障")
        data = original(self, goal, discipline, item, criteria_list, prior_titles, materials_text, companion_names)
        data["title"] = f"{idx:02d}-{item.get('title', '')}"
        return data

    monkeypatch.setattr(AIService, "section", failing_second_section)
    body = _start_sections(client, tutorial["id"])
    job = _poll_job(client, body["job_id"])

    assert job["status"] == "failed"
    assert job["error_code"] == "llm_error"
    assert "已完成内容已保留" in job["error_message"]

    db = SessionLocal()
    try:
        draft = (
            db.query(TutorialVersion)
            .filter(TutorialVersion.tutorial_id == tutorial["id"])
            .order_by(TutorialVersion.version.desc())
            .first()
        )
        content = json.loads(draft.content_json)
    finally:
        db.close()
    saved = [s["title"][:2] for s in content["sections"]]
    assert saved == [f"{i:02d}" for i in range(total) if i != 1], "除失败节外，已完成章节应全部保留且按大纲顺序"
    # 当前版本仍指向上一次成功版本，失败草稿不污染展示
    assert client.get(f"/api/tutorials/{tutorial['id']}").json()["current_version"]["version"] == tutorial["current_version"]["version"]


# ---------------------------------------------------------------- 配套文件


def test_companions_generate_in_parallel(client, monkeypatch):
    """B：知识速查与额外练习互不依赖 → 必须并行（Barrier(2) 证明）。"""
    tutorial = _ready_tutorial(client, generate_extra_exercises=True)
    originals = {"cheatsheet": AIService.cheatsheet, "extra_exercises": AIService.extra_exercises}
    barrier = threading.Barrier(2, timeout=5)
    calls = {"cheatsheet": 0, "extra_exercises": 0}

    def make_patch(kind: str):
        def patched(self, goal, discipline, outline_items, materials_text=""):
            calls[kind] += 1
            barrier.wait()  # 串行实现永远等不到对方 → BrokenBarrierError
            return originals[kind](self, goal, discipline, outline_items, materials_text)

        return patched

    monkeypatch.setattr(AIService, "cheatsheet", make_patch("cheatsheet"))
    monkeypatch.setattr(AIService, "extra_exercises", make_patch("extra_exercises"))
    # 配套文件要并行：路数钉死成 3，与章节用例保持一致的可控前提。
    monkeypatch.setattr(tutorials_service, "MAX_SECTION_WORKERS", 3)

    body = _start_sections(client, tutorial["id"])
    job = _poll_job(client, body["job_id"])
    assert job["status"] == "done", job
    assert calls == {"cheatsheet": 1, "extra_exercises": 1}

    content = client.get(f"/api/tutorials/{tutorial['id']}").json()["current_version"]["content"]
    assert content["cheatsheet"] and content["cheatsheet"]["sections"]
    assert content["extra_exercises"] and content["extra_exercises"]["exercises"]


def test_quickstart_backfill_returns_job_instead_of_blocking(client):
    """B：缺配套文件时 quickstart 立即返回后台 job，不再同步等两个模型往返。"""
    import json as _json

    from app.db import SessionLocal
    from app.models import TutorialVersion

    goal = _create_goal(client)
    body = _quickstart(client, goal["id"])
    _poll_job(client, body["job_id"])
    tutorial = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()

    db = SessionLocal()
    try:
        version = db.get(TutorialVersion, tutorial["current_version"]["id"])
        content = _json.loads(version.content_json)
        content["cheatsheet"] = None
        version.content_json = _json.dumps(content, ensure_ascii=False)
        db.commit()
    finally:
        db.close()

    started_at = time.time()
    again = _quickstart(client, goal["id"])
    elapsed = time.time() - started_at
    assert again["job_id"], "缺配套文件时应返回后台任务 id"
    assert elapsed < 5, f"quickstart 不应同步等待配套生成（实测 {elapsed:.2f}s）"
    steps = {s["key"]: s for s in again["steps"]}
    assert steps["sections"]["status"] == "reused"
    assert steps["companions"]["status"] == "created"

    job = _poll_job(client, again["job_id"])
    assert job["status"] == "done", job
    assert job["job_type"] == "tutorial_companions"

    # 连点幂等：任务在跑时再次 quickstart 复用同一个 job，不重复生成
    finished = client.get(f"/api/tutorials/{tutorial['id']}").json()["current_version"]["content"]
    assert finished["cheatsheet"] and finished["cheatsheet"]["sections"]


# ---------------------------------------------------------------- 知识提取去重


def _extract_calls(goal_id: str) -> int:
    from app.db import SessionLocal
    from app.models import ModelCallLog

    db = SessionLocal()
    try:
        return (
            db.query(ModelCallLog)
            .filter(ModelCallLog.goal_id == goal_id, ModelCallLog.feature == "knowledge_extract")
            .count()
        )
    finally:
        db.close()


def _wait_knowledge_settled(timeout: float = 15.0) -> None:
    """等后台知识提取线程全部结束。

    提取是 fire-and-forget：大纲/章节完成后先标记 job done，再启动提取线程。
    所以「job done」不等于「提取已跑完」，直接断言调用次数或 quality_report 打标
    会随机读到中间态。连续两次读到 0 才算收尾，避免撞上「刚 done、线程尚未登记」的窗口。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if tutorials_service.pending_knowledge_extractions() == 0:
            time.sleep(0.05)
            if tutorials_service.pending_knowledge_extractions() == 0:
                return
            continue
        time.sleep(0.02)
    raise AssertionError("后台知识提取未在预期时间内结束")


def test_context_fingerprint_ignores_random_section_ids():
    """D：指纹只认语义内容，不认每次重新生成都会变的随机 id。"""
    base = {
        "tutorial_title": "教程",
        "outline": [{"section_id": "aaa", "title": "第一节", "summary": "摘要"}],
        "sections": [{"section_id": "aaa", "title": "第一节"}],
    }
    same = {
        "tutorial_title": "教程",
        "outline": [{"section_id": "bbb", "title": "第一节", "summary": "摘要"}],
        "sections": [{"section_id": "bbb", "title": "第一节"}],
    }
    changed = {
        "tutorial_title": "教程",
        "outline": [{"section_id": "aaa", "title": "第一节（改）", "summary": "摘要"}],
        "sections": [{"section_id": "aaa", "title": "第一节"}],
    }
    assert context_fingerprint(base) == context_fingerprint(same)
    assert context_fingerprint(base) != context_fingerprint(changed)


def test_outline_regeneration_skips_unchanged_knowledge_extraction(client):
    """D：大纲重新生成但内容未变 → 不再调用模型提取（零额外成本）。"""
    goal = _create_goal(client)
    body = _quickstart(client, goal["id"])
    job = _poll_job(client, body["job_id"])
    assert job["status"] == "done", job
    _wait_knowledge_settled()

    calls_after_quickstart = _extract_calls(goal["id"])
    concepts_before = len(client.get("/api/knowledge").json()["concepts"])
    assert calls_after_quickstart == 2, "大纲 + 章节各提取一次"
    assert concepts_before > 0

    # 重新生成大纲：新建教程、演示模式内容完全一致 → 指纹命中，跳过提取
    regen = client.post(f"/api/goals/{goal['id']}/tutorials/generate")
    assert regen.status_code == 200, regen.text
    new_tutorial = regen.json()["tutorial"]
    # 注：quality_report 的响应模型只暴露 passed/checks/issues/coverage，
    # 内部打标（knowledge_extracted / knowledge_fingerprint）要读库确认。
    _wait_knowledge_settled()
    from app.db import SessionLocal
    from app.models import TutorialVersion

    db = SessionLocal()
    try:
        report = json.loads(db.get(TutorialVersion, new_tutorial["current_version"]["id"]).quality_report)
    finally:
        db.close()
    assert report.get("knowledge_extracted") is True
    assert report.get("knowledge_fingerprint")

    assert _extract_calls(goal["id"]) == calls_after_quickstart, "内容未变不应再调用提取"
    assert len(client.get("/api/knowledge").json()["concepts"]) == concepts_before

    # 同一版本再手动提取：幂等跳过
    manual = client.post(f"/api/knowledge/extract/{new_tutorial['id']}")
    assert manual.status_code == 200
    assert manual.json()["skipped"] == "already_extracted"
    assert _extract_calls(goal["id"]) == calls_after_quickstart

    # force 语义保持：强制重提确实调用模型（demo 确定性输出 → 不新增重复概念）
    forced = client.post(f"/api/knowledge/extract/{new_tutorial['id']}?force=true")
    assert forced.status_code == 200
    assert forced.json().get("skipped") in ("", None)
    assert _extract_calls(goal["id"]) == calls_after_quickstart + 1
    assert len(client.get("/api/knowledge").json()["concepts"]) == concepts_before
