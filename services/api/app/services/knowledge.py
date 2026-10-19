"""知识服务：概念 / 关系 / 提议。"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..llm.service import AIService, AIServiceError
from ..models import (
    AcceptanceCriterion,
    Attempt,
    Concept,
    ConceptRelation,
    KnowledgeProposal,
    LearningGoal,
    PracticeTask,
)
from .utils import jdump, jload


def _goal(db: Session, goal_id: str) -> LearningGoal:
    goal = db.get(LearningGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})
    return goal


def _concept_dict(c: Concept) -> dict:
    return {
        "id": c.id,
        "domain_key": c.domain_key,
        "title": c.title,
        "definition": c.definition or "",
        "status": c.status,
        "source_refs": jload(c.source_refs, []),
        "created_at": c.created_at,
    }


def _relation_dict(r: ConceptRelation) -> dict:
    return {
        "id": r.id,
        "from_concept_id": r.from_concept_id,
        "to_concept_id": r.to_concept_id,
        "relation_type": r.relation_type,
        "status": r.status,
        "rationale": r.rationale or "",
        "confidence": r.confidence,
        "created_at": r.created_at,
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


def create_concept(db: Session, payload) -> dict:
    concept = Concept(
        title=payload.title,
        definition=payload.definition,
        domain_key=payload.domain_key or "computer_cli",
        source_refs=jdump(payload.source_refs or []),
    )
    db.add(concept)
    db.commit()
    return _concept_dict(concept)


def create_relation(db: Session, payload) -> dict:
    if db.get(Concept, payload.from_concept_id) is None or db.get(Concept, payload.to_concept_id) is None:
        raise HTTPException(status_code=404, detail={"code": "concept_not_found", "message": "概念不存在"})
    relation = ConceptRelation(
        from_concept_id=payload.from_concept_id,
        to_concept_id=payload.to_concept_id,
        relation_type=payload.relation_type,
        rationale=payload.rationale,
        status="proposed",
    )
    db.add(relation)
    db.commit()
    return _relation_dict(relation)


def patch_relation(db: Session, relation_id: str, payload) -> dict:
    relation = db.get(ConceptRelation, relation_id)
    if relation is None:
        raise HTTPException(status_code=404, detail={"code": "relation_not_found", "message": "关系不存在"})
    for field in ("relation_type", "rationale", "status"):
        value = getattr(payload, field, None)
        if value is not None:
            setattr(relation, field, value)
    db.commit()
    return _relation_dict(relation)


def _find_or_create_concept(db: Session, title: str, definition: str, domain_key: str) -> Concept:
    concept = db.query(Concept).filter(Concept.title == title).first()
    if concept is None:
        concept = Concept(title=title, definition=definition, domain_key=domain_key)
        db.add(concept)
        db.flush()
    elif definition and not concept.definition:
        concept.definition = definition
    return concept


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
            _find_or_create_concept(
                db,
                title=str(payload.get("title", "未命名概念")),
                definition=str(payload.get("definition", "")),
                domain_key=str(payload.get("domain_key", "computer_cli")),
            )
        elif proposal.proposal_type == "relation":
            from_title = str(payload.get("from_title", ""))
            to_title = str(payload.get("to_title", ""))
            if from_title and to_title:
                c1 = _find_or_create_concept(db, from_title, "", "computer_cli")
                c2 = _find_or_create_concept(db, to_title, "", "computer_cli")
                exists = (
                    db.query(ConceptRelation)
                    .filter(
                        ConceptRelation.from_concept_id == c1.id,
                        ConceptRelation.to_concept_id == c2.id,
                        ConceptRelation.relation_type == str(payload.get("relation_type", "related")),
                    )
                    .first()
                )
                if exists is None:
                    db.add(
                        ConceptRelation(
                            from_concept_id=c1.id,
                            to_concept_id=c2.id,
                            relation_type=str(payload.get("relation_type", "related")),
                            status="confirmed",
                            rationale=proposal.rationale or "",
                        )
                    )
        proposal.payload = jdump(payload)
        proposal.status = "confirmed" if review.action == "confirm" else "edited"
    else:
        proposal.status = "rejected"
    proposal.reviewed_at = "confirmed"
    db.commit()
    return _proposal_dict(proposal)
