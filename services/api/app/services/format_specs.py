"""格式规范：持久化、默认规范唯一性、Skill 式匹配与任务快照。"""
from __future__ import annotations

import re
from copy import deepcopy
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import FormatSpec, LearningGoal
from ..services.utils import jdump, jload


SOURCE_LABELS = {
    "manual": "手动选择",
    "explicit": "用户指定",
    "keyword": "关键词匹配",
    "semantic": "语义匹配",
    "default": "默认规范",
    "none": "本次不使用特殊规范",
}

_BUILTINS = [
    {
        "name": "默认教程规范",
        "description": "适用于一般学习教程：解释清楚、循序渐进，具体交付物由当前任务决定。",
        "scene": "default_tutorial",
        "is_builtin": True,
        "is_default": True,
        "applicable_tasks": "概念解释、方法学习、工作流教程和一般学习任务。",
        "applicable_intents": ["解释", "学习", "掌握", "理解", "上手"],
        "excluded_intents": ["生成试卷", "出题", "整理试卷"],
        "target_reader": "当前学习目标中描述的读者。",
        "output_goal": "输出一份可独立阅读、可实践、内容克制的教程。",
        "content_structure": (
            "- 从当前任务和前置知识出发\n"
            "- 核心概念先直觉、再原理、后应用\n"
            "- 适当使用示例、练习和验证\n"
            "- 不强制所有学科套用同一种章节模板"
        ),
        "format_rules": "使用清晰的 Markdown 标题层级；段落、列表和代码块符合 Obsidian 阅读习惯。",
        "required_rules": "不编造事实；关键结论可验证；示例与当前任务直接相关。",
        "forbidden_rules": "不输出与当前任务无关的冗长说明；不把推断写成事实。",
        "suggested_rules": "优先讲透核心知识；必要处提醒常见错误。",
        "flexible_rules": "章节划分、示例数量和练习形式可根据学科调整。",
        "acceptance_criteria": "- 教程可独立阅读\n- 核心结论与任务目标对应\n- 无空章节和无关扩展",
        "custom_markdown": "",
    },
    {
        "name": "试卷生成规范",
        "description": "适用于模拟试卷、练习卷和阶段测验；约束试卷结构和交付范围。",
        "scene": "exam_paper",
        "is_builtin": True,
        "is_default": False,
        "applicable_tasks": "生成、编写、扩写或重组模拟试卷、练习卷、阶段测验、期中试卷和期末试卷。",
        "applicable_intents": ["生成试卷", "编写试卷", "出题", "扩写试卷", "重组试卷"],
        "excluded_scenarios": ["解释已有试题", "单独讲解知识点", "整理复习笔记", "总结课程内容"],
        "excluded_intents": ["解释试题", "讲解知识点", "整理笔记", "总结课程"],
        "trigger_keywords": [
            "模拟试卷",
            "试卷生成",
            "练习卷",
            "考试出题",
            "期中试卷",
            "期末试卷",
            "阶段测验",
            "模拟考试",
        ],
        "target_reader": "使用电脑阅读的学生。",
        "output_goal": "输出用户明确要求且可直接作答的试卷及配套内容，不输出无关教程或建议。",
        "deliverables": [
            {"name": "考向分析", "status": "on_request", "primary": True, "order": 1, "allow_override": True},
            {"name": "模拟试卷", "status": "required", "primary": True, "order": 2, "allow_override": False},
            {"name": "参考答案", "status": "required", "primary": True, "order": 3, "allow_override": True},
            {"name": "难题解析", "status": "required", "primary": True, "order": 4, "allow_override": True},
        ],
        "content_structure": (
            "# 试卷名称\n\n题量、每题分值和总分。\n\n"
            "## 第 I 部分：题型\n\n**1.**（分值）题干\n\n选项或作答空间"
        ),
        "format_rules": (
            "- 题号连续编号\n- 分值、题量和满分只在开头或题号旁出现\n"
            "- 同一题型格式和标点风格一致\n- 数学表达式风格统一"
        ),
        "required_rules": "题目必须在用户指定或合理推断的考试范围内；材料和任务信息不足时可合理补全。",
        "forbidden_rules": (
            "- 不输出冗长学习教程、泛化学习建议或无关说明\n"
            "- 不编造考试时间、考试范围、命题人或真题出处等具体事实\n"
            "- 试卷正文不包含关键过程、易错点、考点标签、难度说明或命题意图"
        ),
        "suggested_rules": "图表给出编号、标题和题干引用；无法生成原图时用可读文字或表格描述。",
        "flexible_rules": "题型、题量、分值、时长、难度、覆盖范围和答案解析默认服从本次任务要求。",
        "acceptance_criteria": (
            "- 可直接作答\n- 试卷结构完整且格式一致\n- 交付清单外无无关内容"
        ),
        "custom_markdown": "",
    },
]


def _normalize_status(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"required", "optional", "on_request", "forbidden"} else "optional"


def _normalize_deliverables(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    for idx, raw in enumerate(value):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        result.append({
            "name": name[:120],
            "description": str(raw.get("description", "")).strip(),
            "status": _normalize_status(raw.get("status")),
            "primary": bool(raw.get("primary", True)),
            "order": int(raw.get("order") or idx + 1),
            "allow_override": bool(raw.get("allow_override", True)),
        })
    return result


def spec_dict(spec: FormatSpec) -> dict:
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description or "",
        "scene": spec.scene or "",
        "is_builtin": bool(spec.is_builtin),
        "is_default": bool(spec.is_default),
        "version": int(spec.version or 1),
        "applicable_tasks": spec.applicable_tasks or "",
        "applicable_intents": jload(spec.applicable_intents, []),
        "excluded_scenarios": jload(spec.excluded_scenarios, []),
        "excluded_intents": jload(spec.excluded_intents, []),
        "trigger_keywords": jload(spec.trigger_keywords, []),
        "excluded_keywords": jload(spec.excluded_keywords, []),
        "allow_keyword_trigger": bool(spec.allow_keyword_trigger),
        "allow_semantic_recommendation": bool(spec.allow_semantic_recommendation),
        "allow_explicit_selection": bool(spec.allow_explicit_selection),
        "target_reader": spec.target_reader or "",
        "output_goal": spec.output_goal or "",
        "deliverables": jload(spec.deliverables, []),
        "content_structure": spec.content_structure or "",
        "format_rules": spec.format_rules or "",
        "required_rules": spec.required_rules or "",
        "forbidden_rules": spec.forbidden_rules or "",
        "suggested_rules": spec.suggested_rules or "",
        "flexible_rules": spec.flexible_rules or "",
        "acceptance_criteria": spec.acceptance_criteria or "",
        "reference_examples": spec.reference_examples or "",
        "custom_markdown": spec.custom_markdown or "",
        "created_at": spec.created_at,
        "updated_at": spec.updated_at,
    }


def _snapshot(spec: FormatSpec, task_overrides: list[str] | None = None) -> dict:
    data = spec_dict(spec)
    data["snapshot_version"] = f"v{spec.version}-{spec.updated_at or spec.created_at}"
    data["task_overrides"] = task_overrides or []
    return data


def _validate_payload(payload) -> None:
    if not str(payload.name or "").strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_format_spec", "message": "规范名称不能为空"},
        )
    if not str(payload.output_goal or "").strip() and not str(payload.description or "").strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_format_spec", "message": "请填写用途描述或输出目标"},
        )
    if not isinstance(payload.deliverables, list):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_format_spec", "message": "交付物清单必须是数组"},
        )
    names = [str(item.get("name", "")).strip() for item in payload.deliverables if isinstance(item, dict)]
    if len(names) != len(set(names)):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_format_spec", "message": "交付物名称不能重复"},
        )


def _apply_payload(spec: FormatSpec, payload, *, is_update: bool = False) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    if isinstance(payload, dict):
        payload = SimpleNamespace(**payload)
    _validate_payload(payload)
    spec.name = str(payload.name).strip()
    spec.description = str(payload.description or "").strip()
    spec.scene = str(payload.scene or "").strip()
    spec.applicable_tasks = str(payload.applicable_tasks or "").strip()
    spec.applicable_intents = jdump(payload.applicable_intents or [])
    spec.excluded_scenarios = jdump(payload.excluded_scenarios or [])
    spec.excluded_intents = jdump(payload.excluded_intents or [])
    spec.trigger_keywords = jdump(payload.trigger_keywords or [])
    spec.excluded_keywords = jdump(payload.excluded_keywords or [])
    spec.allow_keyword_trigger = bool(payload.allow_keyword_trigger)
    spec.allow_semantic_recommendation = bool(payload.allow_semantic_recommendation)
    spec.allow_explicit_selection = bool(payload.allow_explicit_selection)
    spec.target_reader = str(payload.target_reader or "").strip()
    spec.output_goal = str(payload.output_goal or "").strip()
    spec.deliverables = jdump(_normalize_deliverables(payload.deliverables))
    spec.content_structure = str(payload.content_structure or "")
    spec.format_rules = str(payload.format_rules or "")
    spec.required_rules = str(payload.required_rules or "")
    spec.forbidden_rules = str(payload.forbidden_rules or "")
    spec.suggested_rules = str(payload.suggested_rules or "")
    spec.flexible_rules = str(payload.flexible_rules or "")
    spec.acceptance_criteria = str(payload.acceptance_criteria or "")
    spec.reference_examples = str(payload.reference_examples or "")
    spec.custom_markdown = str(payload.custom_markdown or "")
    if is_update:
        spec.version = int(spec.version or 1) + 1


def _clear_default(db: Session, *, keep_id: str | None = None) -> None:
    query = db.query(FormatSpec).filter(FormatSpec.is_default.is_(True))
    if keep_id:
        query = query.filter(FormatSpec.id != keep_id)
    for item in query.all():
        item.is_default = False


def set_default(db: Session, spec_id: str) -> dict:
    spec = db.get(FormatSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail={"code": "format_spec_not_found", "message": "格式规范不存在"})
    _clear_default(db)
    db.commit()
    spec.is_default = True
    db.commit()
    db.refresh(spec)
    return spec_dict(spec)


def list_specs(db: Session) -> list[dict]:
    return [spec_dict(item) for item in db.query(FormatSpec).order_by(FormatSpec.is_default.desc(), FormatSpec.updated_at.desc()).all()]


def get_spec(db: Session, spec_id: str) -> dict:
    spec = db.get(FormatSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail={"code": "format_spec_not_found", "message": "格式规范不存在"})
    return spec_dict(spec)


def create_spec(db: Session, payload) -> dict:
    spec = FormatSpec(is_builtin=False, is_default=False, version=1)
    _apply_payload(spec, payload)
    if bool(getattr(payload, "is_default", False)):
        _clear_default(db)
        db.commit()
        spec.is_default = True
    db.add(spec)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "default_conflict", "message": "默认规范设置冲突，请刷新后重试"})
    db.refresh(spec)
    return spec_dict(spec)


def update_spec(db: Session, spec_id: str, payload) -> dict:
    spec = db.get(FormatSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail={"code": "format_spec_not_found", "message": "格式规范不存在"})
    was_default = spec.is_default
    _apply_payload(spec, payload, is_update=True)
    if bool(getattr(payload, "is_default", False)) and not spec.is_default:
        _clear_default(db, keep_id=spec.id)
        db.commit()
        spec.is_default = True
    elif was_default and not spec.is_default:
        fallback = (
            db.query(FormatSpec)
            .filter(FormatSpec.id != spec.id)
            .order_by(FormatSpec.is_builtin.desc(), FormatSpec.updated_at.desc())
            .first()
        )
        if fallback is not None:
            fallback.is_default = True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "default_conflict", "message": "默认规范设置冲突，请刷新后重试"})
    db.refresh(spec)
    return spec_dict(spec)


def duplicate_spec(db: Session, spec_id: str) -> dict:
    source = db.get(FormatSpec, spec_id)
    if source is None:
        raise HTTPException(status_code=404, detail={"code": "format_spec_not_found", "message": "格式规范不存在"})
    spec = FormatSpec(
        name=f"{source.name}（副本）",
        description=source.description,
        scene=source.scene,
        is_builtin=False,
        is_default=False,
        version=1,
        applicable_tasks=source.applicable_tasks,
        applicable_intents=source.applicable_intents,
        excluded_scenarios=source.excluded_scenarios,
        excluded_intents=source.excluded_intents,
        trigger_keywords=source.trigger_keywords,
        excluded_keywords=source.excluded_keywords,
        allow_keyword_trigger=source.allow_keyword_trigger,
        allow_semantic_recommendation=source.allow_semantic_recommendation,
        allow_explicit_selection=source.allow_explicit_selection,
        target_reader=source.target_reader,
        output_goal=source.output_goal,
        deliverables=source.deliverables,
        content_structure=source.content_structure,
        format_rules=source.format_rules,
        required_rules=source.required_rules,
        forbidden_rules=source.forbidden_rules,
        suggested_rules=source.suggested_rules,
        flexible_rules=source.flexible_rules,
        acceptance_criteria=source.acceptance_criteria,
        reference_examples=source.reference_examples,
        custom_markdown=source.custom_markdown,
    )
    db.add(spec)
    db.commit()
    db.refresh(spec)
    return spec_dict(spec)


def delete_spec(db: Session, spec_id: str) -> dict:
    spec = db.get(FormatSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail={"code": "format_spec_not_found", "message": "格式规范不存在"})
    remaining = db.query(FormatSpec).filter(FormatSpec.id != spec_id).count()
    if remaining == 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "last_format_spec", "message": "至少保留一份格式规范；可先创建或复制另一份再删除"},
        )
    was_default = spec.is_default
    name = spec.name
    db.delete(spec)
    db.flush()
    if was_default:
        fallback = (
            db.query(FormatSpec)
            .filter(FormatSpec.scene == "default_tutorial")
            .order_by(FormatSpec.is_builtin.desc(), FormatSpec.updated_at.desc())
            .first()
        )
        if fallback is None:
            fallback = db.query(FormatSpec).order_by(FormatSpec.is_builtin.desc(), FormatSpec.updated_at.desc()).first()
        if fallback is not None:
            fallback.is_default = True
    db.commit()
    return {"ok": True, "deleted": name}


def ensure_builtin_specs(db: Session) -> None:
    """首次启动写入两份内置规范；已有记录不会被覆盖。"""
    existing_scenes = {
        item.scene for item in db.query(FormatSpec).filter(FormatSpec.is_builtin.is_(True)).all()
    }
    changed = False
    for item in _BUILTINS:
        if item["scene"] in existing_scenes:
            continue
        spec = FormatSpec(
            name=item["name"],
            description=item["description"],
            scene=item["scene"],
            is_builtin=True,
            is_default=False,
            version=1,
            applicable_tasks=item["applicable_tasks"],
            applicable_intents=jdump(item["applicable_intents"]),
            excluded_scenarios=jdump(item.get("excluded_scenarios", [])),
            excluded_intents=jdump(item["excluded_intents"]),
            trigger_keywords=jdump(item.get("trigger_keywords", [])),
            excluded_keywords=jdump(item.get("excluded_keywords", [])),
            allow_keyword_trigger=True,
            allow_semantic_recommendation=True,
            allow_explicit_selection=True,
            target_reader=item["target_reader"],
            output_goal=item["output_goal"],
            deliverables=jdump(item.get("deliverables", [])),
            content_structure=item["content_structure"],
            format_rules=item["format_rules"],
            required_rules=item["required_rules"],
            forbidden_rules=item["forbidden_rules"],
            suggested_rules=item.get("suggested_rules", ""),
            flexible_rules=item.get("flexible_rules", ""),
            acceptance_criteria=item["acceptance_criteria"],
            custom_markdown=item.get("custom_markdown", ""),
        )
        db.add(spec)
        changed = True
    if changed:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    if not db.query(FormatSpec).filter(FormatSpec.is_default.is_(True)).first():
        fallback = (
            db.query(FormatSpec)
            .filter(FormatSpec.scene == "default_tutorial")
            .first()
            or db.query(FormatSpec).first()
        )
        if fallback is not None:
            fallback.is_default = True
            db.commit()


def _match_form(text: str) -> str:
    return re.sub(r"[\s，。、；：,.;:的了我你您请帮给一下]", "", str(text or "")).lower()


def _explicit_spec(db: Session, requirement: str, spec_id: str | None = None) -> tuple[str, dict]:
    if spec_id is not None:
        if spec_id == "":
            return "none", {"reason": "用户本次选择不使用特殊规范"}
        spec = db.get(FormatSpec, spec_id)
        if spec is None:
            names = [item.name for item in db.query(FormatSpec).order_by(FormatSpec.name).all()]
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "format_spec_not_found",
                    "message": f"指定的格式规范不存在。可用规范：{ '、'.join(names) }",
                },
            )
        if not spec.allow_explicit_selection:
            raise HTTPException(
                status_code=400,
                detail={"code": "format_spec_not_allowed", "message": f"「{spec.name}」不允许被明确指定"},
            )
        return "manual", {"reason": "用户在生成前明确选择"}

    lowered = str(requirement or "")
    specs = db.query(FormatSpec).order_by(FormatSpec.is_default.desc()).all()
    if re.search(r"不要使用.{0,20}(规范|模板)", lowered):
        return "none", {"reason": "用户明确排除特殊规范"}
    for spec in specs:
        if spec.allow_explicit_selection and _match_form(spec.name) in _match_form(lowered):
            return "explicit", {"reason": f"需求文本明确指定「{spec.name}」"}
    return "", {}


def _keyword_matches(spec: FormatSpec, requirement: str) -> tuple[bool, bool]:
    haystack = _match_form(requirement)
    if not spec.allow_keyword_trigger:
        return False, False
    included = any(_match_form(word) and _match_form(word) in haystack for word in jload(spec.trigger_keywords, []))
    excluded = any(_match_form(word) and _match_form(word) in haystack for word in jload(spec.excluded_keywords, []))
    return included, excluded


def _semantic_match(db: Session, ai, requirement: str, candidates: list[FormatSpec]) -> tuple[str, FormatSpec | None, dict]:
    if not candidates:
        return "", {}
    payloads = [{"id": item.id, "name": item.name, "description": item.description} for item in candidates]
    try:
        result = ai.format_spec_match(requirement, payloads)
        selected = next((item for item in candidates if item.id == result.get("format_spec_id")), None)
        if selected is None or not selected.allow_semantic_recommendation:
            return "", None, {}
        confidence = float(result.get("confidence") or 0)
        if confidence < 0.6:
            return "", {}
        return "semantic", selected, {
            "reason": str(result.get("reason") or "语义匹配"),
            "confidence": confidence,
        }
    except Exception:
        return "", None, {"reason": "语义识别失败，已回退默认规范"}


def resolve_spec(db: Session, requirement: str, ai=None, manual_spec_id: str | None = None) -> dict:
    """返回 selected_spec / snapshot / source / note；未选中时 selected_spec 为 None。"""
    explicit_source, explicit_note = _explicit_spec(db, requirement, manual_spec_id)
    if explicit_source:
        if explicit_source == "none":
            return {
                "selected_spec": None,
                "snapshot": {},
                "source": "none",
                "note": explicit_note["reason"],
            }
        spec_id = manual_spec_id
        if not spec_id:
            source, note = _explicit_spec(db, requirement, None)
            selected = None
            if source == "explicit":
                name = re.search(r"(?:使用|按|按照|采用)([^，。；\n]{1,30}?规范)", str(requirement))
                if name:
                    token = _match_form(name.group(1))
                    selected = next((item for item in db.query(FormatSpec).all() if _match_form(item.name) == token), None)
            if selected is None:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "format_spec_not_found", "message": "无法确定需求文本指定的格式规范"},
                )
            spec_id = selected.id
        spec = db.get(FormatSpec, spec_id)
        return {
            "selected_spec": spec,
            "snapshot": _snapshot(spec),
            "source": explicit_source,
            "note": explicit_note["reason"],
        }

    candidates: list[FormatSpec] = []
    notes: list[str] = []
    for spec in db.query(FormatSpec).all():
        included, excluded = _keyword_matches(spec, requirement)
        if excluded:
            notes.append(f"「{spec.name}」命中排除关键词")
            continue
        if included:
            candidates.append(spec)

    if len(candidates) == 1:
        spec = candidates[0]
        return {
            "selected_spec": spec,
            "snapshot": _snapshot(spec),
            "source": "keyword",
            "note": f"关键词命中「{spec.name}」",
        }

    if candidates:
        source, selected, note = _semantic_match(db, ai, requirement, candidates)
        if source:
            spec = selected
            return {
                "selected_spec": spec,
                "snapshot": _snapshot(spec),
                "source": source,
                "note": note.get("reason", ""),
            }
        notes.append(note.get("reason", "候选不唯一且语义识别不可用"))

    default = db.query(FormatSpec).filter(FormatSpec.is_default.is_(True)).first()
    if default is None:
        default = db.query(FormatSpec).order_by(FormatSpec.is_builtin.desc()).first()
    if default is None:
        return {"selected_spec": None, "snapshot": {}, "source": "default", "note": "暂无可用规范"}
    note = "；".join(notes) if notes else "未命中特殊规范"
    return {
        "selected_spec": default,
        "snapshot": _snapshot(default),
        "source": "default",
        "note": f"{note}，使用默认规范「{default.name}」",
    }


def bind_goal_spec(db: Session, goal: LearningGoal, requirement: str, ai=None, manual_spec_id: str | None = None) -> dict:
    """在大纲前绑定任务规范；已绑定则不重新匹配。"""
    if goal.format_spec_source and goal.format_spec_snapshot:
        return {
            "selected_spec": db.get(FormatSpec, goal.format_spec_id),
            "snapshot": jload(goal.format_spec_snapshot, {}),
            "source": goal.format_spec_source,
            "note": goal.format_spec_match_note or "",
        }
    resolved = resolve_spec(db, requirement, ai=ai, manual_spec_id=manual_spec_id)
    spec = resolved["selected_spec"]
    goal.format_spec_id = spec.id if spec is not None else ""
    goal.format_spec_source = resolved["source"]
    goal.format_spec_match_note = resolved["note"]
    goal.format_spec_snapshot = jdump(resolved["snapshot"])
    db.commit()
    return resolved


def apply_task_overrides(snapshot: dict, requirement: str) -> dict:
    """把本次明确要求转成快照内覆盖项；不修改已保存模板。"""
    result = deepcopy(snapshot or {})
    task_text = str(requirement or "")
    overrides: list[str] = []
    if re.search(r"不要[^。；\n]{0,10}答案", task_text):
        for item in result.get("deliverables", []):
            if "答案" in str(item.get("name", "")):
                item["status"] = "forbidden"
                overrides.append(f"本次不生成{item['name']}")
    if re.search(r"不要[^。；\n]{0,10}解析", task_text):
        for item in result.get("deliverables", []):
            if "解析" in str(item.get("name", "")):
                item["status"] = "forbidden"
                overrides.append(f"本次不生成{item['name']}")
    if re.search(r"只(?:输出|包括|保留|生成|交付)", task_text):
        mentioned = [
            item
            for item in result.get("deliverables", [])
            if str(item.get("name", "")) and str(item.get("name", "")) in task_text
        ]
        if mentioned:
            keep = {item["name"] for item in mentioned}
            for item in result.get("deliverables", []):
                if item["name"] not in keep and item.get("status") != "forbidden":
                    item["status"] = "forbidden"
            overrides.extend([f"本次只生成：{name}" for name in sorted(keep)])
    result["task_overrides"] = overrides
    return result


def delivery_contract_for_snapshot(snapshot: dict) -> dict | None:
    """把规范交付清单并入现有契约结构；普通教程规范不生成契约。"""
    deliverables = (snapshot or {}).get("deliverables") or []
    if not deliverables:
        return None
    ordered = sorted(
        [item for item in deliverables if str(item.get("status")) in {"required", "on_request"}],
        key=lambda item: int(item.get("order") or 0),
    )
    items = [str(item.get("name", "")).strip() for item in ordered]
    items = [item for item in items if item]
    if not items:
        return None
    forbidden_names = [
        str(item.get("name", "")) for item in deliverables if str(item.get("status")) == "forbidden"
    ]
    return {
        "items": items,
        "forbid_answers": any("答案" in name for name in forbidden_names),
        "exclusive": True,
        "suppress_companions": True,
        "source": "format_spec",
        "format_spec_id": snapshot.get("id", ""),
        "format_spec_version": snapshot.get("snapshot_version", ""),
        "forbidden_deliverables": forbidden_names,
        "task_overrides": snapshot.get("task_overrides") or [],
    }


def check_snapshot_delivery(snapshot: dict, content: dict) -> list[str]:
    """结构化交付物清单的确定性检查；语义验收仍由提示词和现有检查承担。"""
    titles = [str(item.get("title", "")) for item in content.get("outline", [])]
    titles += [str(item.get("title", "")) for item in content.get("sections", [])]
    issues: list[str] = []
    for item in (snapshot or {}).get("deliverables", []):
        name = str(item.get("name", "")).strip()
        status = str(item.get("status", ""))
        if not name:
            continue
        if status == "required" and not any(name in title for title in titles):
            issues.append(f"必需交付物未出现在结构中：{name}")
        if status == "forbidden" and any(name in title for title in titles):
            issues.append(f"禁止交付物出现在结构中：{name}")
    return issues
