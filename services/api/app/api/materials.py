"""参考资料 / 例题来源路由：上传、列表、删除、上限查询。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..schemas import MaterialLimitsOut, MaterialOut
from ..services import materials as materials_service
from ..services.materials import ALLOWED_EXTENSIONS, KIND_LABELS

router = APIRouter()


@router.get("/materials/limits", response_model=MaterialLimitsOut, tags=["materials"])
def material_limits():
    """前端用于「大小与类型校验」的参数，避免前后端上限不一致。"""
    return {
        "max_bytes": settings.material_max_bytes,
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        "kinds": [{"key": key, "label": label} for key, label in KIND_LABELS.items()],
    }


@router.get("/goals/{goal_id}/materials", response_model=list[MaterialOut], tags=["materials"])
def list_materials(goal_id: str, db: Session = Depends(get_db)):
    return materials_service.list_materials(db, goal_id)


@router.post("/goals/{goal_id}/materials", response_model=MaterialOut, tags=["materials"])
def upload_material(
    goal_id: str,
    file: UploadFile = File(..., description="参考资料 / 例题来源文件"),
    kind: str = Form("reference", description="reference（参考资料）或 example_source（例题来源）"),
    note: str = Form("", description="可选备注"),
    db: Session = Depends(get_db),
):
    """上传单个材料：校验类型 / 大小 → 落盘 data 目录 → 元数据与正文摘录入库。"""
    return materials_service.save_upload(db, goal_id, file, kind=kind, note=note)


@router.delete("/materials/{material_id}", tags=["materials"])
def delete_material(material_id: str, db: Session = Depends(get_db)):
    """删除材料：同时删除磁盘文件（失败不阻塞元数据删除）。"""
    return materials_service.delete_material(db, material_id)
