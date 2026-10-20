"""上下文答疑服务。"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..llm.service import AIService, AIServiceError
from ..models import ChatMessage, LearningGoal, Tutorial
from . import goals as goals_service
from .utils import goal_dict, jload


def chat(db: Session, payload, ai: AIService) -> dict:
    goal = None
    context: dict = {}
    if payload.goal_id:
        goal = db.get(LearningGoal, payload.goal_id)
        if goal is None:
            raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})
        context["goal"] = goal_dict(goal)
        criteria = goals_service.confirmed_criteria(db, goal.id)
        context["criteria"] = [
            {"id": c["id"], "statement": c["statement"], "pass_rule": c["pass_rule"]} for c in criteria
        ]

    if payload.tutorial_id:
        tutorial = db.get(Tutorial, payload.tutorial_id)
        if tutorial:
            context["tutorial_title"] = tutorial.title
            if tutorial.current_version_id:
                from ..models import TutorialVersion

                version = db.get(TutorialVersion, tutorial.current_version_id)
                if version:
                    content = jload(version.content_json, {})
                    sections = content.get("sections", [])
                    context["sections"] = [s.get("title", "") for s in sections][:20]
                    if payload.section_id:
                        for s in sections:
                            if s.get("id") == payload.section_id:
                                context["section_title"] = s.get("title", "")
                                context["section_summary"] = s.get("goal_statement", "")
                                break

    chat_goal = goal or SimpleNamespace(
        title="学习答疑", motivation="", application_context="", current_level="", time_budget=""
    )
    # 让 token 日志 / 训练样本能关联到目标、教程与章节
    ai.goal_id = payload.goal_id
    ai.tutorial_id = payload.tutorial_id
    ai.section_id = payload.section_id
    try:
        data = ai.chat(chat_goal, payload.question, context)
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc

    user_msg = ChatMessage(
        goal_id=payload.goal_id,
        tutorial_id=payload.tutorial_id,
        section_id=payload.section_id,
        role="user",
        content=payload.question,
    )
    db.add(user_msg)
    assistant_msg = ChatMessage(
        goal_id=payload.goal_id,
        tutorial_id=payload.tutorial_id,
        section_id=payload.section_id,
        role="assistant",
        content=str(data.get("answer", "")),
    )
    db.add(assistant_msg)
    db.commit()
    return {
        "user": {"id": user_msg.id, "role": "user", "content": user_msg.content, "created_at": user_msg.created_at},
        "assistant": {
            "id": assistant_msg.id,
            "role": "assistant",
            "content": assistant_msg.content,
            "created_at": assistant_msg.created_at,
        },
        "demo": ai.is_demo,
    }
