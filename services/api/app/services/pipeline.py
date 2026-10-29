"""一键生成教材：把「诊断 → 计划 → 验收标准（批量同意）→ 大纲 → 全部章节」串成一次点击。

设计要点：
- 幂等：已完成的阶段跳过并标记为 reused，已有章节时不再重复生成；
- 每一步都复用既有服务，单步失败会保留此前已完成的数据（服务内部各自提交）；
- 章节生成仍是后台任务，返回 job_id 供前端轮询进度与 token 消耗。
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..learning.generation_tiers import normalize_tier
from ..learning.teaching_profile import delivery_contract_for

from ..llm.service import AIService
from ..models import GenerationJob, GoalAssessment, LearningGoal
from ..services.utils import jdump, jload
from . import goals as goals_service
from . import format_specs as format_specs_service
from . import tutorials as tutorials_service


_MATH_HINTS = ("数学", "统计", "概率", "数据分析", "推导", "证明", "假设检验", "回归")
_CS_HINTS = ("代码", "编程", "python", "linux", "命令", "命令行", "api", "sql", "算法", "调试", "git", "grep", "awk", "日志", "shell", "bash")


def infer_domain_key(text: str) -> str:
    """一次性入口不再要求用户先选学科；按明确线索推断，未命中时用通用学科。"""
    lowered = text.lower()
    if any(word in lowered for word in _CS_HINTS):
        return "cs_it"
    if any(word in lowered for word in _MATH_HINTS):
        return "math_logic"
    return "interdisciplinary"


def _step(key: str, label: str, status: str, detail: str = "") -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail}


def _active_sections_job(db: Session, goal_id: str) -> GenerationJob | None:
    return (
        db.query(GenerationJob)
        .filter(
            GenerationJob.goal_id == goal_id,
            GenerationJob.job_type == "tutorial_sections",
            GenerationJob.status.in_(("queued", "running")),
        )
        .order_by(GenerationJob.created_at.desc())
        .first()
    )


def _usable_tutorial(tutorials: list[dict]) -> dict | None:
    for item in tutorials:
        content = (item.get("current_version") or {}).get("content") or {}
        if content.get("outline"):
            return item
    return None


_INITIAL_TASK_LABELS = {"diagnose": "价值诊断", "plan": "学习计划", "criteria": "验收标准"}


def _run_parallel_initial_tasks(goal_id: str, kinds: list[str]) -> None:
    """价值诊断 / 学习计划 / 验收标准互不依赖 → 并行生成。

    三者都只依赖 goal+学科+材料，彼此不引用输出（见 goals_service 各生成函数），
    串行时白白多等 2 次模型往返。与章节 / 配套任务同款模式：
    每个任务独立 Session + 独立 AIService（并发安全），SQLite 短事务尽快释放写锁。
    并行度由 tutorials_service.MAX_SECTION_WORKERS 统一控制（AIEDU_LLM_CONCURRENCY）：
    托管 API（默认 9 路）可全并行；单卡串行端点须设 AIEDU_LLM_CONCURRENCY=1 退化为顺序执行，防止排队超时。
    任一失败整体抛出（已成功的成果已各自落库，幂等：重试时按 reused 跳过）。
    注意：诊断结果可能在计划 / 标准生成完成后才判定「暂停」，暂停场景会多花 2 次调用——
    属于用罕见场景的小成本换取常见路径的提速。
    """
    from ..db import SessionLocal
    from ..models import LearningGoal

    def _run(kind: str) -> None:
        db = SessionLocal()
        try:
            if db.get(LearningGoal, goal_id) is None:
                raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})
            task_ai = AIService(db, goal_id=goal_id)
            if kind == "diagnose":
                goals_service.diagnose_goal(db, goal_id, task_ai)
            elif kind == "plan":
                goals_service.generate_plan(db, goal_id, task_ai)
            elif kind == "criteria":
                goals_service.generate_criteria(db, goal_id, task_ai)
            else:  # pragma: no cover
                raise ValueError(f"unknown initial task: {kind}")
            db.commit()  # 生成函数内部各自提交，这里兜底结束事务
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # 诊断 / 计划 / 验收标准互不依赖 → 缺哪个补哪个；并行度跟随章节并发上限
    # （串行端点下 max_workers=1 退化为顺序执行，避免排队把单次请求耗到超时）
    with ThreadPoolExecutor(
        max_workers=max(1, min(len(kinds), tutorials_service.MAX_SECTION_WORKERS)),
        thread_name_prefix="quickstart",
    ) as pool:
        futures = {pool.submit(_run, kind): kind for kind in kinds}
        failures: list[tuple[str, Exception]] = []
        for future in as_completed(futures):
            kind = futures[future]
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001  收齐全部结果后统一抛出，避免掩盖并发错误
                failures.append((kind, exc))
        if failures:
            first_kind, first_exc = failures[0]
            if isinstance(first_exc, HTTPException):
                raise first_exc  # 保留原始状态码与错误码（如 goal_not_found），不改写分类
            detail = "；".join(
                f"{_INITIAL_TASK_LABELS[kind]}生成失败：{str(exc)[:120]}" for kind, exc in failures
            )
            raise HTTPException(
                status_code=502, detail={"code": "llm_error", "message": detail}
            ) from first_exc  # 串联根因异常，保留排查链路


def quickstart(
    db: Session,
    goal_id: str,
    ai: AIService,
    pause_action: str | None = None,
    format_spec_id: str | None = None,
) -> dict:
    goal = db.get(LearningGoal, goal_id)
    if goal is None or goal.archived:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})

    steps: list[dict] = []

    # 大纲前选定并冻结规范：manual_spec_id=None 表示自动匹配，"" 表示本次不使用特殊规范。
    task_text = "\n".join([goal.application_context or "", goal.user_notes or ""]).strip()
    if format_spec_id is not None or not goal.format_spec_snapshot:
        resolved = format_specs_service.resolve_spec(
            db, task_text, ai=ai, manual_spec_id=format_spec_id
        )
        snapshot = format_specs_service.apply_task_overrides(resolved["snapshot"], task_text)
        goal.format_spec_id = resolved["selected_spec"].id if resolved["selected_spec"] is not None else ""
        goal.format_spec_source = resolved["source"]
        goal.format_spec_match_note = resolved["note"]
        goal.format_spec_snapshot = jdump(snapshot)
        db.commit()
    else:
        snapshot = jload(goal.format_spec_snapshot, {})
    spec_name = str((snapshot or {}).get("name", "")).strip()
    source_label = format_specs_service.SOURCE_LABELS.get(goal.format_spec_source, "默认规范")
    steps.append(
        _step(
            "format_spec",
            "格式规范",
            "created" if format_spec_id is not None or not goal.format_spec_snapshot else "reused",
            f"{spec_name or '本次不使用特殊规范'}（{source_label}）",
        )
    )

    # ①③④ 价值诊断 / 学习计划 / 验收标准：缺哪个补哪个，可并行的并行生成
    # （三者互不依赖；下方先查现状做幂等判断，再交给后台线程池并行补齐）
    assessment = (
        db.query(GoalAssessment)
        .filter(GoalAssessment.goal_id == goal.id)
        .order_by(GoalAssessment.created_at.desc())
        .first()
    )
    plan = goals_service.get_plan(db, goal.id)
    criteria = goals_service.list_criteria(db, goal.id)

    wanted = [
        kind
        for kind, need in (
            ("diagnose", assessment is None),
            ("plan", plan is None),
            ("criteria", not criteria),
        )
        if need
    ]
    if wanted:
        _run_parallel_initial_tasks(goal.id, wanted)
        db.commit()  # 结束当前只读事务，确保后续读到并行任务刚提交的数据
    created_steps = set(wanted)

    # ① 价值诊断（并行任务已完成或此前已存在）
    if assessment is None:
        assessment = (
            db.query(GoalAssessment)
            .filter(GoalAssessment.goal_id == goal.id)
            .order_by(GoalAssessment.created_at.desc())
            .first()
        )
    if "diagnose" in created_steps:
        steps.append(_step("diagnose", "价值诊断", "created", "已生成诊断与建议"))
    else:
        steps.append(_step("diagnose", "价值诊断", "reused", "沿用已有诊断"))

    # ② 用户决定：只有明显不值得推进才暂停；暂停后必须由用户选择续跑方式
    if assessment is not None:
        recommendation = assessment.recommendation or ""
        explicit_continue = assessment.user_decision in {"坚决执行", "采纳建议继续"}
        paused = not explicit_continue and (
            assessment.user_decision == "暂停"
            or bool(re.search(r"暂缓|不建议推进|不值得|无法推进", recommendation))
        )
        if paused:
            if pause_action == "proceed":
                goals_service.set_decision(db, goal.id, "坚决执行", "用户选择坚决执行")
                steps.append(_step("decision", "你的决定", "created", "已选择坚决执行"))
            elif pause_action == "adopt":
                goals_service.set_decision(db, goal.id, "采纳建议继续", "用户采纳 AI 建议后执行")
                advice = f"\n用户已采纳 AI 建议，请按此约束生成：{recommendation}"
                if advice not in (goal.user_notes or ""):
                    goal.user_notes = ((goal.user_notes or "") + advice).strip()
                    db.commit()
                steps.append(_step("decision", "你的决定", "created", "已采纳 AI 建议并继续"))
            else:
                if assessment.user_decision != "暂停":
                    goals_service.set_decision(db, goal.id, "暂停", "AI 判断当前需求不值得继续")
                steps.append(_step("decision", "你的决定", "created", "AI 已暂停生成"))
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "generation_paused",
                        "message": f"AI 判断当前需求不值得继续：{recommendation[:200]}",
                        "goal_id": goal.id,
                        "recommendation": recommendation,
                        "choices": [
                            {"key": "proceed", "label": "坚决执行"},
                            {"key": "adopt", "label": "采纳AI建议后立即执行"},
                            {"key": "revise", "label": "修改计划"},
                        ],
                    },
                )
        else:
            goals_service.set_decision(db, goal.id, "继续", "一键同意：按诊断建议推进")
            steps.append(_step("decision", "你的决定", "created", "已按建议选择「继续」"))
    else:
        steps.append(_step("decision", "你的决定", "reused", "无诊断结果"))
    # ③ 学习计划（并行任务已完成或此前已存在）
    plan = goals_service.get_plan(db, goal.id)
    if "plan" in created_steps:
        steps.append(_step("plan", "学习计划", "created", f"{len((plan or {}).get('steps', []))} 个阶段"))
    else:
        steps.append(_step("plan", "学习计划", "reused", f"沿用 v{(plan or {}).get('version', 1)}"))

    # ④ 验收标准 + 一键同意（并行任务已完成或此前已存在）
    criteria = goals_service.list_criteria(db, goal.id)
    generated_note = f"新生成 {len(criteria)} 条" if "criteria" in created_steps else f"沿用 {len(criteria)} 条"
    result = goals_service.confirm_all_criteria(db, goal.id)
    criteria = result["criteria"]
    steps.append(
        _step(
            "criteria",
            "验收标准（一键同意）",
            "created" if result["changed"] else "reused",
            f"{generated_note}，本次新确认 {result['changed']} 条，共 {result['confirmed']} 条已确认",
        )
    )

    # ⑤ 教程大纲
    tutorials = tutorials_service.list_tutorials(db, goal.id)
    tutorial = _usable_tutorial(tutorials)
    if tutorial is None:
        outline_result = tutorials_service.generate_outline(db, goal.id, ai)
        tutorial = outline_result["tutorial"]
        outline_note = f"{len(tutorial['current_version']['content']['outline'])} 节大纲"
        steps.append(_step("outline", "教程大纲", "created", outline_note))
    else:
        outline_note = f"{len(tutorial['current_version']['content']['outline'])} 节大纲"
        steps.append(_step("outline", "教程大纲", "reused", outline_note))

    # ⑥ 全部章节 + 配套文件
    content = (tutorial.get("current_version") or {}).get("content") or {}
    sections = content.get("sections") or []
    contract = (
        content.get("delivery_contract")
        or format_specs_service.delivery_contract_for_snapshot(snapshot)
        or delivery_contract_for(goal)
    )
    job_id: str | None = None
    if sections:
        steps.append(_step("sections", "全部章节", "reused", f"已生成 {len(sections)} 节"))
        # 章节已存在但缺配套文件（旧版本 / 后开启选项）时补齐：改为后台任务立即返回，
        # 同步生成会让「一键生成」白等 1-2 分钟（两个文件各一次模型往返）。
        missing = tutorials_service.companions_missing(db, tutorial["id"])
        if any(missing.values()):
            started = tutorials_service.start_companions(db, tutorial["id"], ai)
            job_id = started["job"].id
            labels = "、".join(
                label
                for key, label in (("cheatsheet", "知识速查"), ("extra_exercises", "额外练习"))
                if missing[key]
            )
            reused = bool(started.get("reused"))
            steps.append(
                _step(
                    "companions",
                    "配套文件",
                    "running" if reused else "created",
                    f"{'沿用进行中的后台任务' if reused else '已提交后台生成'}：{labels}",
                )
            )
        else:
            note = (
                "按画像硬性约束只交付清单内容，不生成配套文件"
                if contract
                else "知识速查与额外练习已齐备"
            )
            steps.append(_step("companions", "配套文件", "reused", note))
        tutorial = tutorials_service.get_tutorial(db, tutorial["id"])
    else:
        active = _active_sections_job(db, goal.id)
        if active is not None:
            job_id = active.id
            steps.append(_step("sections", "全部章节", "running", f"后台生成中（{active.progress}%）"))
        else:
            started = tutorials_service.start_sections(db, tutorial["id"], ai)
            job_id = started["job"].id
            steps.append(
                _step(
                    "sections",
                    "全部章节",
                    "created",
                    "已提交后台生成任务（按交付契约生成，不含配套文件）"
                    if contract
                    else "已提交后台生成任务（含知识速查与额外练习）",
                )
            )

    tutorial = tutorials_service.get_tutorial(db, tutorial["id"])
    return {
        "goal_id": goal.id,
        "steps": steps,
        "tutorial": tutorial,
        "job_id": job_id,
        "demo": ai.is_demo,
    }


def create_and_quickstart(db: Session, payload, ai: AIService) -> dict:
    """统一一次性入口：需求 + 挡位 → 创建目标并复用完整 quickstart 管线。"""
    requirement = payload.requirement.strip()
    title = payload.title.strip()
    if not title:
        first_line = next((line.strip() for line in requirement.splitlines() if line.strip()), "")
        title = first_line[:120] or "自定义学习需求"
    domain_key = payload.domain_key or infer_domain_key(f"{title}\n{requirement}")
    application_context = payload.application_context.strip() or requirement

    from ..schemas import GoalCreate

    goal = goals_service.create_goal(
        db,
        GoalCreate(
            title=title,
            domain_key=domain_key,
            motivation=payload.motivation.strip() or "完成用户提出的学习需求",
            application_context=application_context,
            current_level=payload.current_level.strip(),
            time_budget=payload.time_budget.strip(),
            hard_constraints=(payload.hard_constraints or "").strip(),
            capability_level=payload.capability_level,
            generate_extra_exercises=bool(payload.generate_extra_exercises),
            generation_tier=normalize_tier(payload.generation_tier),
            user_notes=requirement,
        ),
    )
    result = quickstart(db, goal["id"], ai, format_spec_id=getattr(payload, "format_spec_id", None))
    result["goal"] = goals_service.get_goal(db, goal["id"])
    return result
