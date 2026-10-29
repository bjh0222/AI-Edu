"""格式规范管理 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm.service import AIService
from ..schemas import FormatSpecIn, FormatSpecMatchIn, FormatSpecMatchOut, FormatSpecOut
from ..services import format_specs as format_specs_service
from .deps import get_ai

router = APIRouter(prefix="/format-specs", tags=["format-specs"])


@router.get("", response_model=list[FormatSpecOut])
def list_format_specs(db: Session = Depends(get_db)):
    return format_specs_service.list_specs(db)


@router.post("", response_model=FormatSpecOut)
def create_format_spec(payload: FormatSpecIn, db: Session = Depends(get_db)):
    return format_specs_service.create_spec(db, payload)


@router.post("/match", response_model=FormatSpecMatchOut)
def match_format_spec(
    payload: FormatSpecMatchIn,
    db: Session = Depends(get_db),
    ai: AIService = Depends(get_ai),
):
    result = format_specs_service.resolve_spec(
        db, payload.requirement, ai=ai, manual_spec_id=payload.manual_spec_id
    )
    spec = result.get("selected_spec")
    return {
        "source": result.get("source", ""),
        "note": result.get("note", ""),
        "spec": format_specs_service.spec_dict(spec) if spec is not None else None,
        "snapshot": result.get("snapshot", {}),
    }


@router.get("/{spec_id}", response_model=FormatSpecOut)
def get_format_spec(spec_id: str, db: Session = Depends(get_db)):
    return format_specs_service.get_spec(db, spec_id)


@router.put("/{spec_id}", response_model=FormatSpecOut)
def update_format_spec(spec_id: str, payload: FormatSpecIn, db: Session = Depends(get_db)):
    return format_specs_service.update_spec(db, spec_id, payload)


@router.post("/{spec_id}/duplicate", response_model=FormatSpecOut)
def duplicate_format_spec(spec_id: str, db: Session = Depends(get_db)):
    return format_specs_service.duplicate_spec(db, spec_id)


@router.post("/{spec_id}/default", response_model=FormatSpecOut)
def set_default_format_spec(spec_id: str, db: Session = Depends(get_db)):
    return format_specs_service.set_default(db, spec_id)


@router.delete("/{spec_id}")
def delete_format_spec(spec_id: str, db: Session = Depends(get_db)):
    return format_specs_service.delete_spec(db, spec_id)
