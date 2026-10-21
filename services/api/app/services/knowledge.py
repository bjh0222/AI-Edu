"""知识网络服务：概念 / 关系 / 图谱查询 / 教程知识提取 / 掌握状态。

设计原则（与产品要求一致）：
- 概念按规范化标题 + 别名去重，同一概念可服务多个领域与多个学习目标；
- 关系有明确语义与方向；有依据的教程关系自动写入并保留章节锚点，
  仅推测的关系标记为 proposed（待核实）；已撤销 / 已驳回的关系不被重新生成复活；
- 掌握状态只能来自真实任务证据（实践尝试 / 反馈），阅读与生成完成不算掌握。
"""
from __future__ import annotations

import difflib
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..learning.disciplines import PROFILES, get_profile
from ..llm.service import AIService, AIServiceError
from ..models import (
    Attempt,
    Concept,
    ConceptRelation,
    KnowledgeProposal,
    LearningGoal,
    PracticeTask,
    Tutorial,
    TutorialVersion,
)
from .utils import jdump, jload

# 关系类型白名单与展示语义（方向：from ——类型→ to）
RELATION_TYPES: dict[str, str] = {
    "prerequisite_of": "先修于",
    "part_of": "属于",
    "explains": "解释 / 支撑",
    "applied_in": "应用于",
    "contrasts_with": "相似 / 对比",
    "related": "相关联",
}

# 关系状态：proposed 待核实 / confirmed 已确认 / conflict 存在冲突 / rejected 已驳回 / revoked 已撤销
ACTIVE_RELATION_STATUSES = {"proposed", "confirmed", "conflict"}

_SECTION_REF = "tutorial_section"
_NORMALIZE_RE = re.compile(r"[\s\u3000·・、，。：:;；!！?？'\"()（）\[\]【】《》\-—_/\\]+")



def _norm_title(title: str) -> str:
    """规范化标题：小写、去空白与常见标点，用于概念去重与别名匹配。"""
    return _NORMALIZE_RE.sub("", (title or "").lower()).strip()


def _domain_name(key: str) -> str:
    """领域展示名：规范学科用 display_name；模型提议的扩展标签保持原 key，避免都显示成「通用学科」。"""
    if not key:
        return ""
    if key in PROFILES:
        return PROFILES[key].display_name
    return key.replace("_", " ").strip()



def _concept_norms(c: Concept) -> set[str]:
    norms = {_norm_title(c.title)}
    for alias in jload(c.aliases, []):
        norm = _norm_title(str(alias))
        if norm:
            norms.add(norm)
    return {n for n in norms if n}



def _goal(db: Session, goal_id: str) -> LearningGoal:
    goal = db.get(LearningGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})
    return goal



# ---------------------------------------------------------------- serialization

def _concept_dict(c: Concept) -> dict:
    return {
        "id": c.id,
        "domain_key": c.domain_key,
        "domain_keys": jload(c.domain_keys, [c.domain_key] if c.domain_key else []),
        "title": c.title,
        "definition": c.definition or "",
        "status": c.status,
        "aliases": jload(c.aliases, []),
        "goal_ids": jload(c.goal_ids, []),
        "source_refs": jload(c.source_refs, []),
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }



def _relation_dict(r: ConceptRelation) -> dict:
    return {
        "id": r.id,
        "from_concept_id": r.from_concept_id,
        "to_concept_id": r.to_concept_id,
        "relation_type": r.relation_type,
        "status": r.status,
        "rationale": r.rationale or "",
        "source_refs": jload(r.source_refs, []),
        "evidence_refs": jload(r.evidence_refs, []),
        "confidence": r.confidence,
        "origin": r.origin or "manual",
        "history": jload(r.history, []),
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }



def _proposal_dict(p: KnowledgeProposal) -> dict:
    return {
        "id": p.id,
        "proposal_type": p.proposal_type,
        "payload": jload(p.payload, {}),
        "rationale": p.rationale or "",
        "evidence_refs": jload(p.evidence_refs, []),
        "status": p.status,
        "reviewed_at": p.reviewed_at or "",
        "created_at": p.created_at,
    }



# ---------------------------------------------------------------- concept dedup

def find_concept_by_title(db: Session, title: str) -> Concept | None:
    norm = _norm_title(title)
    if not norm:
        return None
    active = db.query(Concept).filter(Concept.status == "active").all()
    # 第一层：规范化标题 / 别名精确匹配
    for concept in active:
        if norm in _concept_norms(concept):
            return concept
    # 第二层：模糊匹配（模型提取措辞漂移时避免重复建节点）。
    # 只接受高相似度（≥0.75）或明确的包含关系，避免误合并不同概念。
    best: tuple[float, Concept] | None = None
    for concept in active:
        for candidate_norm in _concept_norms(concept):
            ratio = difflib.SequenceMatcher(None, norm, candidate_norm).ratio()
            contained = len(norm) >= 4 and len(candidate_norm) >= 4 and (
                norm in candidate_norm or candidate_norm in norm
            )
            score = max(ratio, 0.76 if contained else 0.0)
            if score >= 0.75 and (best is None or score > best[0]):
                best = (score, concept)
    return best[1] if best else None



def find_or_create_concept(
    db: Session,
    title: str,
    definition: str = "",
    domain_keys: list[str] | None = None,
    source_ref: dict | None = None,
    goal_id: str | None = None,
    aliases: list[str] | None = None,
) -> Concept:
    """按规范化标题 / 别名查找概念；找不到才创建，绝不按标题重复建节点。"""
    clean_title = (title or "").strip()[:200]
    if not clean_title:
        raise HTTPException(status_code=422, detail={"code": "concept_title_required", "message": "概念名称不能为空"})
    clean_aliases = [a for a in (aliases or []) if a]
    concept = find_concept_by_title(db, clean_title)
    if concept is None:
        # 新概念自带的别名也可能命中已有概念（如英文名 ↔ 中文名）
        for alias in clean_aliases:
            concept = find_concept_by_title(db, alias)
            if concept is not None:
                break
    if concept is None:
        domains = [d for d in (domain_keys or []) if d]
        concept = Concept(
            title=clean_title,
            title_norm=_norm_title(clean_title),
            definition=definition or "",
            domain_key=(domains[0] if domains else "general"),
            domain_keys=jdump(domains or ["general"]),
            goal_ids=jdump([goal_id] if goal_id else []),
            source_refs=jdump([source_ref] if source_ref else []),
            aliases=jdump([a for a in (aliases or []) if a]),
        )
        db.add(concept)
        db.flush()
        return concept

    # 合并：补定义、并领域 / 别名 / 目标 / 来源，不去覆盖已有内容
    if definition and not concept.definition:
        concept.definition = definition
    if domain_keys:
        merged = jload(concept.domain_keys, [])
        if not merged and concept.domain_key:
            merged = [concept.domain_key]
        for d in domain_keys:
            if d and d not in merged:
                merged.append(d)
        concept.domain_keys = jdump(merged)
        if merged and concept.domain_key not in merged:
            concept.domain_key = merged[0]
    if goal_id:
        goals = jload(concept.goal_ids, [])
        if goal_id not in goals:
            goals.append(goal_id)
            concept.goal_ids = jdump(goals)
    if source_ref:
        refs = jload(concept.source_refs, [])
        if source_ref not in refs:
            refs.append(source_ref)
            concept.source_refs = jdump(refs[:40])
    if aliases:
        existing = jload(concept.aliases, [])
        for alias in aliases:
            if alias and alias != concept.title and alias not in existing:
                existing.append(alias)
        concept.aliases = jdump(existing[:20])
    db.flush()
    return concept



# ---------------------------------------------------------------- dedupe / merge

def merge_concept_into(db: Session, keeper: Concept, duplicate: Concept) -> Concept:
    """把 duplicate 合并进 keeper：定义 / 别名 / 领域 / 目标 / 来源并入，关系重指向。"""
    if keeper.id == duplicate.id:
        return keeper
    if not (keeper.definition or "").strip() and (duplicate.definition or "").strip():
        keeper.definition = duplicate.definition
    existing_aliases = {_norm_title(a) for a in jload(keeper.aliases, [])}
    keeper_norms = _concept_norms(keeper)
    for alias in _concept_norms(duplicate):
        if alias in keeper_norms or alias in existing_aliases:
            continue
        aliases = jload(keeper.aliases, [])
        aliases.append(alias)
        keeper.aliases = jdump(aliases[:20])
        existing_aliases.add(alias)
    for gid in jload(duplicate.goal_ids, []):
        goals = jload(keeper.goal_ids, [])
        if gid not in goals:
            goals.append(gid)
        keeper.goal_ids = jdump(goals)
    for d in jload(duplicate.domain_keys, []) or ([duplicate.domain_key] if duplicate.domain_key else []):
        merged = jload(keeper.domain_keys, [])
        if not merged and keeper.domain_key:
            merged = [keeper.domain_key]
        if d and d not in merged:
            merged.append(d)
        keeper.domain_keys = jdump(merged)
    if merged := jload(keeper.domain_keys, []):
        if keeper.domain_key not in merged:
            keeper.domain_key = merged[0]
    for ref in jload(duplicate.source_refs, []):
        refs = jload(keeper.source_refs, [])
        if ref not in refs:
            refs.append(ref)
        keeper.source_refs = jdump(refs[:40])

    relations = (
        db.query(ConceptRelation)
        .filter(
            (ConceptRelation.from_concept_id == duplicate.id)
            | (ConceptRelation.to_concept_id == duplicate.id)
        )
        .all()
    )
    for rel in relations:
        new_from = keeper.id if rel.from_concept_id == duplicate.id else rel.from_concept_id
        new_to = keeper.id if rel.to_concept_id == duplicate.id else rel.to_concept_id
        if new_from == new_to:
            db.delete(rel)  # 合并后成自环的关系直接删除
            continue
        equivalent = _relation_exists(db, new_from, new_to, rel.relation_type)
        if equivalent is not None and equivalent.id != rel.id:
            # 已有等价关系：并入依据后删除重复边
            if rel.rationale and not equivalent.rationale:
                equivalent.rationale = rel.rationale
            for ref in jload(rel.source_refs, []):
                refs = jload(equivalent.source_refs, [])
                if ref not in refs:
                    refs.append(ref)
                equivalent.source_refs = jdump(refs[:40])
            db.delete(rel)
        else:
            rel.from_concept_id = new_from
            rel.to_concept_id = new_to
    db.delete(duplicate)
    db.flush()
    return keeper



def dedupe_concepts(db: Session) -> dict:
    """全库模糊去重：相似概念合并到最早创建的概念上。返回合并统计。"""
    concepts = db.query(Concept).filter(Concept.status == "active").order_by(Concept.created_at.asc()).all()
    norm_to_concept: dict[str, Concept] = {}
    merged = 0
    kept_ids: set[str] = set()
    for concept in concepts:
        if concept.id in kept_ids:
            continue
        target: Concept | None = None
        for norm in _concept_norms(concept):
            if norm in norm_to_concept and norm_to_concept[norm].id != concept.id:
                target = norm_to_concept[norm]
                break
        if target is None:
            # 模糊匹配已有保留概念（包含关系视为强证据）
            best_score = 0.0
            for norm in _concept_norms(concept):
                for seen_norm, seen in norm_to_concept.items():
                    ratio = difflib.SequenceMatcher(None, norm, seen_norm).ratio()
                    contained = len(norm) >= 4 and len(seen_norm) >= 4 and (norm in seen_norm or seen_norm in norm)
                    score = max(ratio, 0.85 if contained else 0.0)
                    if score >= 0.8 and score > best_score:
                        best_score, target = score, seen
        if target is not None:
            merge_concept_into(db, target, concept)
            merged += 1
            # 合并后的别名也登记到索引，防止后续再建
            for norm in _concept_norms(target):
                norm_to_concept[norm] = target
        else:
            for norm in _concept_norms(concept):
                norm_to_concept.setdefault(norm, concept)
            kept_ids.add(concept.id)
    db.commit()
    remaining = db.query(Concept).filter(Concept.status == "active").count()
    return {"merged": merged, "remaining_concepts": remaining}



# ---------------------------------------------------------------- relation upsert

def _relation_exists(db: Session, from_id: str, to_id: str, relation_type: str) -> ConceptRelation | None:
    return (
        db.query(ConceptRelation)
        .filter(
            ConceptRelation.from_concept_id == from_id,
            ConceptRelation.to_concept_id == to_id,
            ConceptRelation.relation_type == relation_type,
        )
        .first()
    )



def upsert_relation(
    db: Session,
    from_concept_id: str,
    to_concept_id: str,
    relation_type: str,
    *,
    rationale: str = "",
    source_refs: list[dict] | None = None,
    origin: str = "manual",
    confidence: float = 0.5,
    confirm: bool = False,
) -> ConceptRelation | None:
    """幂等写入关系；已撤销 / 已驳回的关系不被自动复活。"""
    if relation_type not in RELATION_TYPES:
        relation_type = "related"
    if from_concept_id == to_concept_id:
        return None
    existing = _relation_exists(db, from_concept_id, to_concept_id, relation_type)
    if existing is not None:
        if existing.status in ("revoked", "rejected"):
            return None  # 用户明确处理过：不再自动恢复，需人工重新评估
        if rationale and not existing.rationale:
            existing.rationale = rationale
        for ref in source_refs or []:
            refs = jload(existing.source_refs, [])
            if ref not in refs:
                refs.append(ref)
            existing.source_refs = jdump(refs[:40])
        if confirm and existing.status == "proposed" and origin == "tutorial":
            existing.status = "confirmed"
            existing.history = jdump(
                jload(existing.history, []) + [{"action": "auto_confirm", "note": "教程明确解释，自动确认"}]
            )
        db.flush()
        return existing
    relation = ConceptRelation(
        from_concept_id=from_concept_id,
        to_concept_id=to_concept_id,
        relation_type=relation_type,
        status="confirmed" if confirm else "proposed",
        rationale=rationale or "",
        source_refs=jdump([r for r in (source_refs or []) if r]),
        confidence=max(0.0, min(1.0, float(confidence or 0.5))),
        origin=origin,
        history=jdump([{"action": "created", "note": f"来源：{origin}"}]),
    )
    db.add(relation)
    db.flush()
    return relation



# ---------------------------------------------------------------- extraction

def _tutorial_context(tutorial: Tutorial, version: TutorialVersion | None) -> dict:
    content = jload(version.content_json, {}) if version else {}
    outline = content.get("outline", [])
    sections = content.get("sections", [])
    brief_sections = []
    for s in sections:
        brief_sections.append(
            {
                "section_id": s.get("id", ""),
                "title": s.get("title", ""),
                "prerequisites": [str(p) for p in s.get("prerequisites", [])],
                "explanation_headings": [b.get("heading", "") for b in s.get("explanation", [])][:6],
                "steps": [st.get("text", "") for st in s.get("steps", [])][:5],
            }
        )
    return {
        "tutorial_title": tutorial.title,
        "outline": [{"section_id": o.get("id", ""), "title": o.get("title", ""), "summary": o.get("summary", "")} for o in outline],
        "sections": brief_sections,
    }



def extract_from_tutorial(
    db: Session, goal: LearningGoal, tutorial: Tutorial, version: TutorialVersion | None, ai: AIService,
    force: bool = False,
) -> dict:
    """教程生成 / 更新后提取结构化知识并持久化。失败不阻断教程主流程。

    幂等：同一教程版本默认只提取一次（版本 quality_report 打标）；force=True 可
    强制重提（此时靠概念去重与模糊合并避免重复节点）。"""
    context = _tutorial_context(tutorial, version)
    if not context["outline"] and not context["sections"]:
        return {"concepts": 0, "relations": 0, "skipped": "empty_content"}
    if version is not None and not force:
        report = jload(version.quality_report, {})
        if report.get("knowledge_extracted"):
            return {
                "concepts": 0,
                "relations": 0,
                "skipped": "already_extracted",
                "tutorial_id": tutorial.id,
                "goal_id": goal.id,
            }
    existing = [
        {"title": c.title, "definition": c.definition} for c in db.query(Concept).filter(Concept.status == "active").all()
    ]
    try:
        data = ai.knowledge_extract(goal, tutorial, context, existing)
    except AIServiceError:
        return {"concepts": 0, "relations": 0, "error": "llm_error"}

    extracted_titles: set[str] = set()
    title_to_section: dict[str, str] = {}
    added_concepts = 0
    for raw in data.get("concepts", [])[:30]:
        title = str(raw.get("title", "")).strip()
        if not title:
            continue
        section_id = str(raw.get("section_id", "") or "")
        domains = [goal.domain_key]
        # 只接受规范学科目录里的扩展领域，避免模型自造 xxx_yyy 标签把领域目录拆碎
        extra_domain = str(raw.get("domain_key", "") or "")
        if extra_domain in PROFILES and extra_domain != goal.domain_key:
            domains.append(extra_domain)
        source_ref = {
            "type": _SECTION_REF,
            "tutorial_id": tutorial.id,
            "section_id": section_id,
            "title": str(raw.get("section_title", "") or title)[:120],
        }
        find_or_create_concept(
            db,
            title,
            definition=str(raw.get("definition", "") or ""),
            domain_keys=domains,
            source_ref=source_ref,
            goal_id=goal.id,
            aliases=[str(a) for a in raw.get("aliases", []) if a],
        )
        extracted_titles.add(title)
        if section_id:
            title_to_section[title] = section_id
        added_concepts += 1

    added_relations = 0
    for raw in data.get("relations", [])[:60]:
        from_title = str(raw.get("from_title", "")).strip()
        to_title = str(raw.get("to_title", "")).strip()
        if not from_title or not to_title:
            continue
        # 端点必须能在概念中解析（本次提取或已有概念），否则丢弃该关系
        source_concept = find_concept_by_title(db, from_title)
        target_concept = find_concept_by_title(db, to_title)
        if source_concept is None or target_concept is None:
            continue
        section_id = str(raw.get("section_id", "") or title_to_section.get(from_title, ""))
        source_refs = [
            {
                "type": _SECTION_REF,
                "tutorial_id": tutorial.id,
                "section_id": section_id,
                "title": from_title,
            }
        ]
        relation_type = str(raw.get("relation_type", "related") or "related")
        if relation_type not in RELATION_TYPES:
            relation_type = "related"
        rationale = str(raw.get("rationale", "") or "")
        # 分级策略：教程明确解释（带章节锚点）自动确认；仅推测保持待核实
        confirmed = bool(section_id)
        relation = upsert_relation(
            db,
            source_concept.id,
            target_concept.id,
            relation_type,
            rationale=rationale,
            source_refs=source_refs,
            origin="tutorial",
            confidence=float(raw.get("confidence", 0.5) or 0.5),
            confirm=confirmed,
        )
        if relation is not None:
            added_relations += 1
    # 版本级打标：该版本已提取过，重复调用 / 页面刷新不会重复提取
    if version is not None:
        report = jload(version.quality_report, {})
        report["knowledge_extracted"] = True
        version.quality_report = jdump(report)
    db.commit()
    return {
        "concepts": added_concepts,
        "relations": added_relations,
        "tutorial_id": tutorial.id,
        "goal_id": goal.id,
    }



# ---------------------------------------------------------------- mastery (证据驱动)

def mastery_for_concept(db: Session, concept: Concept) -> dict:
    """掌握状态只由真实任务证据推导：尝试过 → 练习中；低辅助完成 → 已掌握；无 → 缺证据。"""
    anchors = [r for r in jload(concept.source_refs, []) if r.get("type") == _SECTION_REF]
    tutorial_ids = {str(r.get("tutorial_id", "")) for r in anchors if r.get("tutorial_id")}
    if not tutorial_ids:
        return {"status": "no_evidence", "basis": "尚无关联教程任务"}
    tasks = db.query(PracticeTask).filter(PracticeTask.tutorial_id.in_(tutorial_ids)).all() if tutorial_ids else []
    attempts: list[Attempt] = []
    basis: list[str] = []
    for task in tasks:
        rows = db.query(Attempt).filter(Attempt.task_id == task.id).order_by(Attempt.created_at.desc()).all()
        attempts.extend(rows)
    low_help = [a for a in attempts if a.help_level in ("A0", "A1")]
    if attempts and task_status_done(db, tutorial_ids) and low_help:
        status = "mastered"
        basis.append(f"存在 {len(low_help)} 次低辅助（A0/A1）实践尝试")
    elif attempts:
        status = "practicing"
        basis.append(f"存在 {len(attempts)} 次实践尝试，尚无低辅助独立完成记录")
    else:
        status = "no_evidence"
        basis.append("关联教程尚无实践尝试记录")
    if low_help:
        basis.append("注意：任务完成 ≠ 概念迁移能力，独立评估仍建议进行")
    return {"status": status, "basis": "；".join(basis)}



def task_status_done(db: Session, tutorial_ids: set[str]) -> bool:
    if not tutorial_ids:
        return False
    rows = db.query(PracticeTask).filter(PracticeTask.tutorial_id.in_(tutorial_ids), PracticeTask.status == "done").all()
    return bool(rows)



# ---------------------------------------------------------------- graph queries

def _goal_node_dict(g: LearningGoal) -> dict:
    return {
        "id": f"goal:{g.id}",
        "type": "goal",
        "title": g.title,
        "domain_key": g.domain_key,
        "domain_name": _domain_name(g.domain_key),
        "status": "archived" if g.archived else g.status,
        "ref_id": g.id,
    }



def graph(db: Session, *, domain: str | None = None, goal_id: str | None = None) -> dict:
    """构建图谱：节点（概念 / 学习目标）与有向边（有效关系）。

    - 全局：全部 active 概念 + 全部目标（已归档目标节点 status=archived）；
    - 领域：domain_keys 或目标领域命中该领域；
    - 目标：服务该目标的概念 + 该目标节点。
    撤销 / 驳回关系不进图；proposed 边保留但带待核实标记。
    """
    concepts = db.query(Concept).filter(Concept.status == "active").all()
    if domain:
        concepts = [
            c for c in concepts if domain in jload(c.domain_keys, []) or c.domain_key == domain
        ]
    if goal_id:
        _goal(db, goal_id)
        concepts = [c for c in concepts if goal_id in jload(c.goal_ids, [])]

    concept_ids = {c.id for c in concepts}
    relations = (
        db.query(ConceptRelation)
        .filter(ConceptRelation.status.in_(ACTIVE_RELATION_STATUSES))
        .order_by(ConceptRelation.created_at.asc())
        .all()
    )
    edges = []
    linked_concept_ids: set[str] = set()
    for r in relations:
        if r.from_concept_id in concept_ids and r.to_concept_id in concept_ids:
            edges.append(
                {
                    "id": r.id,
                    "source": r.from_concept_id,
                    "target": r.to_concept_id,
                    "relation_type": r.relation_type,
                    "status": r.status,
                    "rationale": r.rationale or "",
                    "confidence": r.confidence,
                }
            )
            linked_concept_ids.update({r.from_concept_id, r.to_concept_id})

    nodes = []
    for c in concepts:
        nodes.append(
            {
                "id": c.id,
                "type": "concept",
                "title": c.title,
                "domain_keys": jload(c.domain_keys, [c.domain_key] if c.domain_key else []),
                "domain_name": _domain_name(c.domain_key),
                "definition": (c.definition or "")[:200],
                "mastery": mastery_for_concept(db, c)["status"] if goal_id is None else _mastery_in_goal(db, c, goal_id),
                "degree": 0,
                "ref_id": c.id,
            }
        )

    # 目标节点：全局 / 领域范围下展示目标与概念的关联（目标 → 概念）
    # 已归档目标也保留（知识网络是学习记录），节点 status 标记 archived 由前端弱化。
    goals_query = db.query(LearningGoal)
    if domain:
        goals_query = goals_query.filter(LearningGoal.domain_key == domain)
    goals = goals_query.all() if goal_id is None else ([_goal(db, goal_id)] if goal_id else [])
    goal_edges = []
    goal_concept_map: dict[str, list[str]] = {}
    for c in concepts:
        for gid in jload(c.goal_ids, []):
            goal_concept_map.setdefault(gid, []).append(c.id)
    goal_ids_in_graph = set()
    for g in goals:
        covered = goal_concept_map.get(g.id, [])
        if not covered:
            continue  # 没有任何概念关联的目标不进图，避免空悬节点
        nodes.append(_goal_node_dict(g))
        goal_ids_in_graph.add(f"goal:{g.id}")
        for cid in covered:
            goal_edges.append(
                {
                    "id": f"ge:{g.id}:{cid}",
                    "source": f"goal:{g.id}",
                    "target": cid,
                    "relation_type": "goal_covers",
                    "status": "confirmed",
                    "rationale": "该学习目标的学习覆盖此概念",
                    "confidence": 1.0,
                }
            )

    degree: dict[str, int] = {}
    for e in edges + goal_edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1
    for n in nodes:
        n["degree"] = degree.get(n["id"], 0)

    if domain or goal_id:
        # 范围视图保持聚焦：过滤无关联的孤立节点；全局视图保留孤立概念（便于用户建立关系）
        nodes = [n for n in nodes if n["degree"] > 0 or n["type"] == "goal"]
    return {
        "scope": {"domain": domain or "", "goal_id": goal_id or ""},
        "nodes": nodes,
        "edges": edges,
        "goal_edges": goal_edges,
        "stats": {
            "concepts": sum(1 for n in nodes if n["type"] == "concept"),
            "goals": len(goal_ids_in_graph),
            "relations": len(edges),
        },
        "relation_types": RELATION_TYPES,
    }



def _mastery_in_goal(db: Session, concept: Concept, goal_id: str) -> str:
    """目标范围内：只统计属于该目标的教程锚点产生的证据。"""
    anchors = [
        r
        for r in jload(concept.source_refs, [])
        if r.get("type") == _SECTION_REF and str(r.get("tutorial_id", ""))
    ]
    if not anchors:
        return "no_evidence"
    tutorials = {
        str(r["tutorial_id"])
        for r in anchors
        if db.get(Tutorial, str(r["tutorial_id"])) is not None
        and db.get(Tutorial, str(r["tutorial_id"])).goal_id == goal_id
    }
    if not tutorials:
        return "no_evidence"
    tasks = db.query(PracticeTask).filter(PracticeTask.tutorial_id.in_(tutorials)).all()
    attempts: list[Attempt] = []
    for task in tasks:
        attempts.extend(db.query(Attempt).filter(Attempt.task_id == task.id).all())
    done = any(t.status == "done" for t in tasks)
    low_help = [a for a in attempts if a.help_level in ("A0", "A1")]
    if attempts and done and low_help:
        return "mastered"
    if attempts:
        return "practicing"
    return "no_evidence"



def nav(db: Session) -> dict:
    """侧边栏导航：领域 ← 用户学习目标动态归纳；不依赖硬编码目录。

    已归档目标保留在目录里（知识网络是学习记录，不应随归档消失），
    由前端弱化展示并标注「已归档」。
    """
    goals = db.query(LearningGoal).order_by(LearningGoal.created_at.asc()).all()
    all_concepts = db.query(Concept).filter(Concept.status == "active").all()
    domain_names: dict[str, str] = {}
    domain_goals: dict[str, list[dict]] = {}
    for g in goals:
        domain_names.setdefault(g.domain_key, _domain_name(g.domain_key))
        domain_goals.setdefault(g.domain_key, []).append(
            {
                "id": g.id,
                "title": g.title,
                "status": g.status,
                "archived": bool(g.archived),
                "concept_count": 0,
            }
        )
    for c in all_concepts:
        domains = jload(c.domain_keys, []) or ([c.domain_key] if c.domain_key else [])
        goal_ids = jload(c.goal_ids, [])
        for d in domains:
            # 只登记规范学科目录里的领域；模型早期自造的标签（如 python_csv）不进目录，数据仍保留
            if d not in PROFILES:
                continue
            domain_names.setdefault(d, _domain_name(d))
            domain_goals.setdefault(d, [])
        for gid in goal_ids:
            for items in domain_goals.values():
                for item in items:
                    if item["id"] == gid:
                        item["concept_count"] += 1
    domains = []
    for key, name in domain_names.items():
        items = domain_goals.get(key, [])
        concept_total = sum(1 for c in all_concepts if key in (jload(c.domain_keys, []) or [c.domain_key]))
        domains.append(
            {
                "key": key,
                "name": name,
                "concept_count": concept_total,
                "goals": sorted(items, key=lambda x: -x["concept_count"]),
            }
        )
    domains.sort(key=lambda d: (-(d["concept_count"] + len(d["goals"])), d["name"]))
    return {
        "domains": domains,
        "totals": {
            "concepts": len(all_concepts),
            "goals": len(goals),
            "relations": db.query(ConceptRelation).filter(ConceptRelation.status.in_(ACTIVE_RELATION_STATUSES)).count(),
        },
    }



def concept_detail(db: Session, concept_id: str) -> dict:
    concept = db.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(status_code=404, detail={"code": "concept_not_found", "message": "概念不存在"})
    relations = (
        db.query(ConceptRelation)
        .filter(
            (ConceptRelation.from_concept_id == concept.id) | (ConceptRelation.to_concept_id == concept.id),
        )
        .order_by(ConceptRelation.updated_at.desc())
        .all()
    )
    rel_items = []
    for r in relations:
        other_id = r.to_concept_id if r.from_concept_id == concept.id else r.from_concept_id
        other = db.get(Concept, other_id)
        direction = "out" if r.from_concept_id == concept.id else "in"
        rel_items.append(
            {
                **_relation_dict(r),
                "direction": direction,
                "other_concept_id": other_id,
                "other_title": other.title if other else "（已删除概念）",
            }
        )
    anchors = []
    for ref in jload(concept.source_refs, []):
        if ref.get("type") != _SECTION_REF:
            continue
        tutorial = db.get(Tutorial, str(ref.get("tutorial_id", "")))
        if tutorial is None:
            continue
        goal = db.get(LearningGoal, tutorial.goal_id)
        section_id = str(ref.get("section_id", "") or "")
        section_title = ""
        if tutorial.current_version_id:
            version = db.get(TutorialVersion, tutorial.current_version_id)
            if version:
                content = jload(version.content_json, {})
                for s in content.get("sections", []):
                    if s.get("id") == section_id:
                        section_title = s.get("title", "")
                        break
                if not section_title:
                    for o in content.get("outline", []):
                        if o.get("id") == section_id:
                            section_title = o.get("title", "")
                            break
        anchors.append(
            {
                "tutorial_id": tutorial.id,
                "tutorial_title": tutorial.title,
                "goal_id": tutorial.goal_id,
                "goal_title": goal.title if goal else "",
                "section_id": section_id,
                "section_title": section_title or ref.get("title", ""),
            }
        )
    goal_items = []
    for gid in jload(concept.goal_ids, []):
        g = db.get(LearningGoal, gid)
        if g is not None:
            goal_items.append({"id": g.id, "title": g.title, "status": g.status})
    return {
        **_concept_dict(concept),
        "relations": rel_items,
        "tutorial_anchors": anchors,
        "goals": goal_items,
        "mastery": mastery_for_concept(db, concept),
    }



# ---------------------------------------------------------------- CRUD / proposals

def list_knowledge(db: Session) -> dict:
    concepts = db.query(Concept).order_by(Concept.created_at.asc()).all()
    relations = db.query(ConceptRelation).order_by(ConceptRelation.created_at.asc()).all()
    proposals = (
        db.query(KnowledgeProposal)
        .order_by(KnowledgeProposal.created_at.desc())
        .all()
    )
    return {
        "concepts": [_concept_dict(c) for c in concepts],
        "relations": [_relation_dict(r) for r in relations],
        "proposals": [_proposal_dict(p) for p in proposals],
    }



def delete_concept(db: Session, concept_id: str) -> dict:
    """删除概念及其全部关系；清理引用该概念的待处理提议。不含级联，必须显式删边。"""
    concept = db.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(status_code=404, detail={"code": "concept_not_found", "message": "概念不存在"})
    relations = (
        db.query(ConceptRelation)
        .filter(
            (ConceptRelation.from_concept_id == concept.id) | (ConceptRelation.to_concept_id == concept.id)
        )
        .all()
    )
    for relation in relations:
        db.delete(relation)
    cleaned = 0
    title = concept.title
    for proposal in db.query(KnowledgeProposal).filter(KnowledgeProposal.status == "pending").all():
        payload = jload(proposal.payload, {})
        if title in (payload.get("title"), payload.get("from_title"), payload.get("to_title")):
            db.delete(proposal)
            cleaned += 1
    db.delete(concept)
    db.commit()
    return {
        "ok": True,
        "concept_id": concept_id,
        "title": title,
        "deleted_relations": len(relations),
        "deleted_proposals": cleaned,
    }


def clear_graph(db: Session) -> dict:
    """清空知识网络：删除全部概念、关系与知识提议；学习目标 / 教程 / 练习不受影响。"""
    relations = db.query(ConceptRelation).delete(synchronize_session=False)
    concepts = db.query(Concept).delete(synchronize_session=False)
    proposals = db.query(KnowledgeProposal).delete(synchronize_session=False)
    db.commit()
    return {
        "ok": True,
        "deleted_concepts": int(concepts or 0),
        "deleted_relations": int(relations or 0),
        "deleted_proposals": int(proposals or 0),
    }



def create_concept(db: Session, payload) -> dict:
    concept = find_or_create_concept(
        db,
        payload.title,
        definition=payload.definition,
        domain_keys=[payload.domain_key] if payload.domain_key else None,
        aliases=payload.aliases or None,
    )
    db.commit()
    return _concept_dict(concept)



def create_relation(db: Session, payload) -> dict:
    if db.get(Concept, payload.from_concept_id) is None or db.get(Concept, payload.to_concept_id) is None:
        raise HTTPException(status_code=404, detail={"code": "concept_not_found", "message": "概念不存在"})
    relation = upsert_relation(
        db,
        payload.from_concept_id,
        payload.to_concept_id,
        payload.relation_type,
        rationale=payload.rationale,
        origin="manual",
        confirm=True,  # 用户手动建立：视为已确认
    )
    if relation is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "relation_revoked", "message": "该关系此前已被撤销，请在详情面板中重新评估后再恢复"},
        )
    db.commit()
    return _relation_dict(relation)



def patch_relation(db: Session, relation_id: str, payload) -> dict:
    relation = db.get(ConceptRelation, relation_id)
    if relation is None:
        raise HTTPException(status_code=404, detail={"code": "relation_not_found", "message": "关系不存在"})
    allowed_status = {"proposed", "confirmed", "conflict", "rejected", "revoked"}
    history = jload(relation.history, [])
    for field in ("relation_type", "rationale"):
        value = getattr(payload, field, None)
        if value is not None:
            if field == "relation_type" and value not in RELATION_TYPES:
                raise HTTPException(status_code=422, detail={"code": "bad_relation_type", "message": "未知关系类型"})
            setattr(relation, field, value)
            history.append({"action": f"edit_{field}", "note": str(value)[:200]})
    new_status = getattr(payload, "status", None)
    if new_status:
        if new_status not in allowed_status:
            raise HTTPException(status_code=422, detail={"code": "bad_status", "message": "未知关系状态"})
        if new_status != relation.status:
            history.append({"action": "status", "note": f"{relation.status} → {new_status}"})
            relation.status = new_status
    relation.history = jdump(history)
    db.commit()
    return _relation_dict(relation)



def create_proposals(db: Session, goal_id: str, ai: AIService) -> list[dict]:
    goal = _goal(db, goal_id)
    concepts = db.query(Concept).all()
    concept_payload = [{"id": c.id, "title": c.title, "definition": c.definition} for c in concepts[:30]]
    attempts = (
        db.query(Attempt)
        .join(PracticeTask, Attempt.task_id == PracticeTask.id)
        .filter(PracticeTask.goal_id == goal.id)
        .order_by(Attempt.created_at.desc())
        .limit(5)
        .all()
    )
    try:
        data = ai.suggest_proposals(goal, concept_payload, {
            "attempts": [{"task": a.task_id, "help_level": a.help_level} for a in attempts],
        })
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc
    created = []
    for raw in data.get("proposals", []):
        p = KnowledgeProposal(
            proposal_type=str(raw.get("proposal_type", "relation")),
            payload=jdump(raw.get("payload", {})),
            rationale=str(raw.get("rationale", "")),
            status="pending",
        )
        db.add(p)
        created.append(p)
    db.commit()
    return [_proposal_dict(p) for p in created]



def review_proposal(db: Session, proposal_id: str, review) -> dict:
    proposal = db.get(KnowledgeProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail={"code": "proposal_not_found", "message": "提议不存在"})
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail={"code": "already_reviewed", "message": "该提议已处理"})

    payload = jload(proposal.payload, {})
    if review.payload:
        payload = {**payload, **review.payload}

    if review.action in ("confirm", "edit"):
        if proposal.proposal_type == "concept":
            find_or_create_concept(
                db,
                title=str(payload.get("title", "未命名概念")),
                definition=str(payload.get("definition", "")),
                domain_keys=[str(payload.get("domain_key", "general"))],
            )
        elif proposal.proposal_type == "relation":
            from_title = str(payload.get("from_title", ""))
            to_title = str(payload.get("to_title", ""))
            if from_title and to_title:
                c1 = find_or_create_concept(db, from_title)
                c2 = find_or_create_concept(db, to_title)
                upsert_relation(
                    db,
                    c1.id,
                    c2.id,
                    str(payload.get("relation_type", "related")),
                    rationale=proposal.rationale or "",
                    origin="ai_proposal",
                    confirm=True,  # 用户明确确认后入图
                )
        proposal.payload = jdump(payload)
        proposal.status = "confirmed" if review.action == "confirm" else "edited"
    else:
        proposal.status = "rejected"
    proposal.reviewed_at = "confirmed"
    db.commit()
    return _proposal_dict(proposal)
