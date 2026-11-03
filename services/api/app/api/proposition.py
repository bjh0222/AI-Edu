# -*- coding: utf-8 -*-
"""命题知识库路由：母题 / 变式 / 命题规律 / 质量记录。

路由风格沿用 api/knowledge.py：裸 APIRouter()，路径里逐条写全模块名（不设 prefix），
避免与 format_specs.py 那种「prefix + 相对路径」两种风格混用导致 openapi 路径不一致。

一条重要的接口设计取舍：``PATCH /proposition/item-models/{id}`` 不在最初的任务清单里，
但**必须有**。extract_item_models 抽出的母题一律没有 solution_template（解法模板不能
凭空造，见 proposition.extract_item_models 的 docstring），而没有模板的母题无法产出
isomorph 变式。若不提供补录入口，整条「抽母题 → 机械求变式」的链路就是死的——
只能看不能用。补录必须由人做，这与「机械求解不编造答案」是同一条原则。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import (
    DesignPrincipleOut,
    DistillRequest,
    ExtractItemModelsRequest,
    InjectionPreviewOut,
    ItemInstanceOut,
    ItemModelListOut,
    ItemModelOut,
    ItemModelPatch,
    PrincipleListOut,
    PrincipleReview,
    QualityRecordListOut,
    VariationCreate,
)
from ..services import proposition as proposition_service

router = APIRouter()


# ------------------------------------------------------------------ 母题


@router.get("/proposition/item-models", response_model=ItemModelListOut, tags=["proposition"])
def list_item_models(
    domain: str = Query(default="", description="学科 key（空=全部）"),
    status: str = Query(default="", description="draft / confirmed / archived（空=全部）"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """母题列表。存在「同母题不同答案」证据的排在前面——那是最该先补录模板的一批。"""
    return proposition_service.list_item_models(db, domain_key=domain, status=status, limit=limit, offset=offset)


@router.post("/proposition/item-models/extract", response_model=list[ItemModelOut], tags=["proposition"])
def extract_item_models(payload: ExtractItemModelsRequest, db: Session = Depends(get_db)):
    """从一份卷子 Markdown 抽母题（radicals = exam_check 的定义式指纹）。

    重复抽取同一份卷子不会重复建档（按学科 + 定义式集合指纹去重）。抽出的母题
    ``status="draft"``、``solution_template=""``，需补录模板后才能产出同构变式。
    """
    return proposition_service.extract_item_models(
        db, payload.domain_key, payload.markdown, chapter=payload.chapter
    )


@router.get("/proposition/item-models/{item_model_id}", response_model=ItemModelOut, tags=["proposition"])
def get_item_model(item_model_id: str, db: Session = Depends(get_db)):
    """母题详情，附带它已产出的全部变式（变式↔母题关系只在这里体现）。"""
    return proposition_service.get_item_model(db, item_model_id)


@router.patch("/proposition/item-models/{item_model_id}", response_model=ItemModelOut, tags=["proposition"])
def patch_item_model(item_model_id: str, payload: ItemModelPatch, db: Session = Depends(get_db)):
    """补录母题的参数化解法（``solution_template`` / ``answer_expr``）与求解约定。

    这是让 isomorph 变式能机械求答案的唯一途径。提交前会用 sympy 在受控环境里
    **试解析一次**：语法不合法、含被禁语法元素或幂规模超限的模板直接 422 拒绝入库，
    避免把不可求解的模板存进去、等到生成变式时才失败。
    """
    return proposition_service.patch_item_model(db, item_model_id, payload)


@router.get("/proposition/item-instances", response_model=list[ItemInstanceOut], tags=["proposition"])
def list_item_instances(
    item_model_id: str = Query(default="", description="按母题过滤（空=全部）"),
    variation_type: str = Query(default="", description="isomorph / procedural / conceptual"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """变式实例列表。"""
    return proposition_service.list_instances(
        db, item_model_id=item_model_id, variation_type=variation_type, limit=limit, offset=offset
    )


@router.post(
    "/proposition/item-models/{item_model_id}/variations",
    response_model=ItemInstanceOut,
    tags=["proposition"],
)
def create_variation(item_model_id: str, payload: VariationCreate, db: Session = Depends(get_db)):
    """生成一个变式实例。

    - ``isomorph``：答案由母题模板代入 ``incidental_values`` **机械求解**
      （``verified_by="tool_symbolic"``）；求不出来返回 **409**，不产出未经验证的答案。
    - ``procedural`` / ``conceptual``：结构已变、母题模板不适用，答案留空、
      ``verified_by="none"``，需独立验证。
    """
    return proposition_service.make_variation(
        db, item_model_id, payload.incidental_values, variation_type=payload.variation_type
    )


# ------------------------------------------------------------------ 命题规律


@router.get("/proposition/principles/injection-preview", response_model=InjectionPreviewOut, tags=["proposition"])
def injection_preview(
    domain: str = Query(default="general", description="学科 key"),
    knowledge_points: str = Query(default="", description="逗号分隔的知识点（空=只按学科过滤）"),
    budget_chars: int = Query(default=1200, ge=0, le=20000),
    db: Session = Depends(get_db),
):
    """注入预览：核对哪些**已确认**规律会被注入、哪些被预算裁掉。

    ``proposed`` / ``rejected`` 一律不出现在文本里——未验证的经验不得影响交付。

    路径必须排在 ``/proposition/principles/{principle_id}/review`` 之前定义：FastAPI
    按注册顺序匹配，``injection-preview`` 会被 ``{principle_id}`` 段吞掉。
    """
    points = [k.strip() for k in knowledge_points.split(",") if k.strip()] if knowledge_points else None
    return proposition_service.preview_injection(db, domain, points, budget_chars)


@router.get("/proposition/principles", response_model=PrincipleListOut, tags=["proposition"])
def list_principles(
    domain: str = Query(default="", description="学科 key（空=全部）"),
    status: str = Query(default="", description="proposed / confirmed / rejected（空=全部）"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """命题规律列表，证据多的排前面。"""
    return proposition_service.list_principles(db, domain_key=domain, status=status, limit=limit, offset=offset)


@router.post("/proposition/principles/{principle_id}/review", response_model=DesignPrincipleOut, tags=["proposition"])
def review_principle(principle_id: str, payload: PrincipleReview, db: Session = Depends(get_db)):
    """三态流转 ``proposed → confirmed / rejected``。

    只有 ``confirmed`` 的规律会被注入提示词；``rejected`` 是终态，不会因再攒够证据复活。
    已处理过的规律返回 409。
    """
    return proposition_service.review_principle(db, principle_id, payload.action, rationale=payload.rationale)


@router.post("/proposition/distill", response_model=list[DesignPrincipleOut], tags=["proposition"])
def distill(payload: DistillRequest, db: Session = Depends(get_db)):
    """规则聚类（**确定性、零 token**）：按 (domain_key, code) 聚类 QualityRecord，
    同一缺陷累计出现 ≥ threshold 次 → 生成 ``proposed`` 候选规律。

    返回本次**新生成**的规律（已存在的聚类只更新证据数，不重复建档）。生成的
    statement 必然绑定具体 code、出现次数与示例 motif，不会是「要注意答案正确性」
    这类不可验证的空话。
    """
    return proposition_service.distill_principles(db, payload.domain_key, threshold=payload.threshold)


# ------------------------------------------------------------------ 质量记录


@router.get("/proposition/quality-records", response_model=QualityRecordListOut, tags=["proposition"])
def list_quality_records(
    domain: str = Query(default="", description="学科 key（空=全部）"),
    code: str = Query(default="", description="缺陷码：E017 / E018 / DEFECT"),
    tutorial_id: str = Query(default="", description="按教程过滤"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """质量记录列表（命题规律的冷启动素材）。

    由 tutorials 在试卷质量三层跑完后回流；重生成同一版本不会重复计数。
    """
    return proposition_service.list_quality_records(
        db, domain_key=domain, code=code, tutorial_id=tutorial_id, limit=limit, offset=offset
    )