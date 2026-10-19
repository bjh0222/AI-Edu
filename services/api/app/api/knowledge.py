"""知识网络路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm.service import AIService
from ..schemas import (
    ConceptCreate,
    ConceptOut,
    KnowledgeOut,
    ProposalOut,
    ProposalReview,
    RelationCreate,
    RelationOut,
    RelationPatch,
)
from ..services import knowledge as knowledge_service
from .deps import get_ai

router = APIRouter()


@router.get("/knowledge", response_model=KnowledgeOut, tags=["knowledge"])
def get_knowledge(db: Session = Depends(get_db)):
    return knowledge_service.list_knowledge(db)


@router.post("/knowledge/concepts", response_model=ConceptOut, tags=["knowledge"])
def create_concept(payload: ConceptCreate, db: Session = Depends(get_db)):
    return knowledge_service.create_concept(db, payload)


@router.post("/knowledge/relations", response_model=RelationOut, tags=["knowledge"])
def create_relation(payload: RelationCreate, db: Session = Depends(get_db)):
    return knowledge_service.create_relation(db, payload)


@router.patch("/knowledge/relations/{relation_id}", response_model=RelationOut, tags=["knowledge"])
def patch_relation(relation_id: str, payload: RelationPatch, db: Session = Depends(get_db)):
    return knowledge_service.patch_relation(db, relation_id, payload)


@router.post("/goals/{goal_id}/knowledge-proposals", response_model=list[ProposalOut], tags=["knowledge"])
def create_proposals(goal_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    return knowledge_service.create_proposals(db, goal_id, ai)


@router.post("/knowledge/proposals/{proposal_id}/review", response_model=ProposalOut, tags=["knowledge"])
def review_proposal(proposal_id: str, review: ProposalReview, db: Session = Depends(get_db)):
    return knowledge_service.review_proposal(db, proposal_id, review)
