"""知识网络路由：图谱 / 导航 / 概念详情 / 概念与关系 CRUD / 提议。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm.service import AIService
from ..schemas import (
    ConceptCreate,
    ConceptDetailOut,
    ConceptOut,
    ExtractionResult,
    GraphOut,
    KnowledgeOut,
    NavOut,
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


@router.get("/knowledge/nav", response_model=NavOut, tags=["knowledge"])
def get_nav(db: Session = Depends(get_db)):
    """侧边栏子目录：领域 ← 用户学习目标动态归纳。"""
    return knowledge_service.nav(db)


@router.get("/knowledge/graph", response_model=GraphOut, tags=["knowledge"])
def get_graph(
    domain: str = Query(default="", description="领域范围（领域 key）"),
    goal_id: str = Query(default="", description="学习目标范围"),
    db: Session = Depends(get_db),
):
    """图谱数据：全局 / 领域 / 学习目标三种范围。"""
    return knowledge_service.graph(db, domain=domain or None, goal_id=goal_id or None)


@router.get("/knowledge/concepts/{concept_id}", response_model=ConceptDetailOut, tags=["knowledge"])
def get_concept_detail(concept_id: str, db: Session = Depends(get_db)):
    return knowledge_service.concept_detail(db, concept_id)


@router.post("/knowledge/extract/{tutorial_id}", response_model=ExtractionResult, tags=["knowledge"])
def extract_from_tutorial(
    tutorial_id: str,
    force: bool = Query(default=False, description="同一教程版本默认只提取一次；true 强制重新提取"),
    db: Session = Depends(get_db),
    ai: AIService = Depends(get_ai),
):
    """对已有教程手动触发知识提取（补录 / 旧数据迁移入口）。"""
    from fastapi import HTTPException

    from ..models import LearningGoal, Tutorial, TutorialVersion

    tutorial = db.get(Tutorial, tutorial_id)
    if tutorial is None:
        raise HTTPException(status_code=404, detail={"code": "tutorial_not_found", "message": "教程不存在"})
    goal = db.get(LearningGoal, tutorial.goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})
    version = (
        db.get(TutorialVersion, tutorial.current_version_id) if tutorial.current_version_id else None
    )
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    ai.tutorial_id = tutorial.id
    return knowledge_service.extract_from_tutorial(db, goal, tutorial, version, ai, force=force)


@router.post("/knowledge/dedupe", tags=["knowledge"])
def dedupe(db: Session = Depends(get_db)):
    """全库模糊去重：把相似概念合并到最早创建的概念上（模型措辞漂移兜底）。"""
    return knowledge_service.dedupe_concepts(db)


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
