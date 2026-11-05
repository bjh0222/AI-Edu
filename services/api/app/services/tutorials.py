"""教程服务：大纲 → 分节生成 → 质量检查 → 版本管理。"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..model_settings import runtime_settings
from ..learning.disciplines import get_profile
from ..learning.engine import check_structure
from ..learning.generation_tiers import normalize_tier
from ..learning.levels import normalize_level
from ..learning.teaching_profile import (
    delivery_contract_for,
    goal_context_text,
    normalize_teaching_plan,
    parse_teaching_profile,
    task_requirement_text,
)
from ..llm.service import AIService, AIServiceError
from ..models import GenerationJob, ModelCallLog, Tutorial, TutorialVersion
from . import goals as goals_service
from . import exam_check as exam_check_service
from . import exam_verify as exam_verify_service
from . import proposition as proposition_service
from . import spec_check as spec_check_service
from . import format_specs as format_specs_service
from . import knowledge as knowledge_service
from . import synthesis as synthesis_service
from . import materials as materials_service
from .utils import (
    add_usage,
    align_section_titles,
    criterion_dict,
    jdump,
    jload,
    prune_foreign_section_blocks,
    prune_section_foreign_blocks,
    set_status_at_least,
    _norm_ws,
    safe_obsidian_filename as _safe_filename,
    token_usage_dict,
    tutorial_version_dict,
)

MAX_SECTIONS_HINT = 8  # 安全上限：防止异常输出撑爆成本；正常章节数由目标范围决定
# 交付契约（结构由代码/规范确定性给定，不是模型自由发挥）允许更多章：
# 「按材料分章，每章一份」时章节数等于材料的章数，截断会静默少交付几份成品。
# 交付/导读节数保险丝。阅读导读的节数由材料篇数决定（《毛选》单卷 30 篇 + 全书层 2 节），
# 24 会静默丢篇；64 仍足以拦住异常材料（几百个标题）把生成成本撑爆。
CONTRACT_MAX_SECTIONS = 64
# 章节并发生成上限：默认 9 路（deep 挡位最多 8 节，等于全并行，把「逐节排队」的尾巴消掉）。
# 注意：该值只在端点真能并发时才有意义——接 DeepSeek 等托管 API 可直接用默认值；
# 若换回单卡自建端点（按队列串行处理请求，单节约 385s），必须用
# AIEDU_LLM_CONCURRENCY=1 退化串行，否则第 2 个起的请求排队超过超时上限→重试再排队→永远追不上。
MAX_SECTION_WORKERS = max(1, int(os.environ.get("AIEDU_LLM_CONCURRENCY", "9")))

logger = logging.getLogger(__name__)
# 知识网络提取全局串行锁：提取已是后台锦上添花，串行化零性能损失；
# 避免大纲提取线程与章节 draft 提取线程并发「查-插」产生同名重复概念节点
_KNOWLEDGE_EXTRACTION_LOCK = threading.Lock()
# 后台提取的可观测性：_extract_knowledge_async 是 fire-and-forget，job 状态与 HTTP
# 响应都不反映它是否跑完。登记在途线程，测试和排障才能确定地等「后台提取全部结束」，
# 而不是靠 sleep 猜时间窗。
_PENDING_EXTRACTIONS: set[threading.Thread] = set()
_PENDING_EXTRACTIONS_LOCK = threading.Lock()


def pending_knowledge_extractions() -> int:
    """在途的知识提取线程数；0 表示后台提取已全部结束。"""
    with _PENDING_EXTRACTIONS_LOCK:
        return len(_PENDING_EXTRACTIONS)

VALID_CONTENT_TYPES = {"concept", "method", "tool", "fact", "application", "mixed"}


def _normalize_content_type(value) -> str:
    """模型返回的非法教学类型归一化为 mixed（不因非法枚举判定生成失败）。"""
    text = str(value or "").strip().lower()
    return text if text in VALID_CONTENT_TYPES else "mixed"


def _normalize_outline_items(raw_sections: list) -> list[dict]:
    """大纲条目归一化：补 purpose / content_type，非法枚举回退 mixed；非对象条目跳过。"""
    items = []
    for raw in raw_sections:
        if not isinstance(raw, dict):
            continue
        items.append({
            "id": uuid.uuid4().hex[:8],
            "title": str(raw.get("title", "未命名章节"))[:120],
            "purpose": str(raw.get("purpose", "") or raw.get("summary", "")),
            "content_type": _normalize_content_type(raw.get("content_type")),
            "summary": str(raw.get("summary", "")),
            "criteria_ids": _as_str_list(raw.get("criteria_ids")),
        })
    return items


def _contract_outline(contract: dict, criteria: list[dict]) -> list[dict]:
    """交付契约优先于模型大纲：清单即章节，一个交付物一章。

    「只包括 A/B/C」是对交付物组成的硬性规定。只把它写进提示词时，模型会认为
    「多写几章讲解」不算违反「不要输出答案」，于是照样交付一份教程；这里直接用规则
    定死结构，模型只负责把每一章写成那一项成品。
    """
    items = [str(item).strip() for item in (contract or {}).get("items") or []]
    items = [item for item in items if item][:CONTRACT_MAX_SECTIONS]
    criteria_ids = [str(c["id"]) for c in criteria or [] if isinstance(c, dict) and c.get("id")]
    return [
        {
            "id": uuid.uuid4().hex[:8],
            "title": item[:120],
            "purpose": f"本次交付物：{item}",
            "content_type": "application",
            "summary": "",
            # 交付物整体承载验收标准：契约模式下不再按章节拆验收点
            "criteria_ids": list(criteria_ids),
        }
        for item in items
    ]


def _as_str_list(value) -> list[str]:
    """把模型输出安全转成字符串列表：非列表（如字符串）整体丢弃，不按字符展开。"""
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()]


_MATH_DISPLAY_RE = re.compile(r"\\\[(.*?)\\\]", re.S)
_MATH_INLINE_RE = re.compile(r"\\\((.*?)\\\)", re.S)


def normalize_math_delimiters(markdown: str) -> str:
    r"""把 LaTeX 分隔符统一为 Obsidian / 常见 Markdown 渲染器都认识的 $ 与 $$。

    模型会混用 \(…\) 与 \[…\]：Obsidian 里反斜杠被 Markdown 转义吃掉，
    公式退化成裸文本（(X_1,X_2)、[ \begin{cases} … ]），多行公式还会被拆散成
    列表项。$…$ / $$…$$ 是各渲染器的公约数，所以在落库与导出两层确定性归一，
    不依赖模型自觉统一风格。代码围栏内的内容原样保留。
    """
    out: list[str] = []
    buf: list[str] = []
    fence: str | None = None

    def flush() -> None:
        if not buf:
            return
        text = "\n".join(buf)
        text = _MATH_DISPLAY_RE.sub(lambda m: f"$$" + m.group(1) + f"$$", text)
        text = _MATH_INLINE_RE.sub(lambda m: f"$" + m.group(1) + f"$", text)
        out.append(text)
        buf.clear()

    for line in str(markdown or "").splitlines():
        stripped = line.lstrip()
        if fence is None and (stripped.startswith("```") or stripped.startswith("~~~")):
            flush()
            fence = stripped[:3]
            out.append(line)
            continue
        if fence is not None:
            out.append(line)
            if stripped.startswith(fence):
                fence = None
            continue
        buf.append(line)
    flush()
    return "\n".join(out)


# 设计之初的固定栏目与练习册外壳元栏目：标题命中即整块剔除（落库与导出两层都拦）。
# 外壳类（使用说明/自检清单…）任何教学内容都不会以此为名 → 前缀命中即删；
# 栏目类（核心结论/常见错误…）概念性内容可能 legitimately 以它开头
# （如「缓冲溶液的常见错误辨析」）→ 只删「短标题」：标题本身就是在宣告栏目，
# 而不是在讲某个概念（判据：去掉标记后剩余不超过 6 字，如「常见错误诊断表」）。
# 外壳类用「包含」匹配：改名变体（使用说明与数据口径 / 章末自测清单）同样要删；
# 「做题方式」只用前缀匹配，避免误删「计算题做题方法」这类讲学科方法的标题。
_META_SHELL_CONTAINS = ("使用说明", "自检清单", "自测清单", "真的会了", "如何使用本教程")
_META_SHELL_STARTS = ("做题方式",)
_META_COLUMN_MARKERS = ("核心结论", "常见错误", "前置知识", "必要练习", "对应验收标准")
_META_COLUMN_TAIL = 6


def _is_meta_section_title(title: str) -> bool:
    """块标题是否是退役元栏目（含「自检清单：…」「常见错误诊断表」这类改名变体）。"""
    text = re.sub(r"^#{1,6}\s*", "", str(title or "")).strip()
    if not text:
        return False
    if text.startswith(_META_SHELL_STARTS) or any(m in text for m in _META_SHELL_CONTAINS):
        return True
    for marker in _META_COLUMN_MARKERS:
        if text == marker or text.startswith(marker + "：") or text.startswith(marker + ":"):
            return True
        if text.startswith(marker) and len(text) - len(marker) <= _META_COLUMN_TAIL:
            return True
    return False


_BODY_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _strip_meta_segments(body: str) -> str:
    """删掉正文里以退役元栏目为标题的整段（标题行到下一个同级/更高级标题为止）。

    模型会把「使用说明 / 章末自测清单」写进空标题块的 body 里自带小标题，
    只过滤块标题拦不住；这里按标题层级切段删除，段内表格与说明一并带走。
    """
    out: list[str] = []
    skip_level: int | None = None
    for line in str(body or "").splitlines():
        stripped = line.strip()
        match = _BODY_HEADING_RE.match(stripped) if stripped else None
        if match:
            level = len(match.group(1))
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if skip_level is None and _is_meta_section_title(match.group(2)):
                skip_level = level
                continue
        if skip_level is None:
            out.append(line)
    return "\n".join(out).strip("\n")


def _normalize_section_raw(raw: dict) -> dict:
    """章节输出归一化：非法内容块类型回退 text；空 body 块丢弃；缺失可选字段置空。"""
    raw_blocks = raw.get("content")
    content_blocks = []
    for block in raw_blocks if isinstance(raw_blocks, list) else []:
        if not isinstance(block, dict):
            continue
        body = str(block.get("body", "") or "").strip()
        if not body:
            continue
        btype = str(block.get("type", "text") or "text").strip().lower()
        if btype not in {
            "text", "key_point", "formula", "steps", "table", "example",
            "comparison", "method_summary", "diagram", "memory", "note",
        }:
            btype = "text"
        content_blocks.append({
            "type": btype,
            "title": str(block.get("title", "") or ""),
            # 落库前统一公式分隔符：历史版本里 \(…\) 风格在 Obsidian 不渲染
            "body": normalize_math_delimiters(_strip_meta_segments(body)),
        })
    raw_sources = raw.get("sources")
    sources = []
    for s in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title", "") or "").strip()
        if not title:
            continue
        sources.append({
            "title": title,
            "url": str(s.get("url", "") or ""),
            "note": str(s.get("note", "") or ""),
        })
    # 设计之初的四个固定栏目（核心结论/常见错误/前置知识/必要练习）已退役：
    # 模型即使按旧提示词输出也一律丢弃；元栏目块在落库前整块剔除。
    content_blocks = [b for b in content_blocks if not _is_meta_section_title(b["title"])]
    return {
        "title": str(raw.get("title", "") or "")[:120],
        "purpose": str(raw.get("purpose", "") or ""),
        "content_type": _normalize_content_type(raw.get("content_type")),
        "content": content_blocks,
        "key_takeaways": [],
        "common_errors": [],
        "prerequisite_refs": [],
        "exercises": [],
        "sources": sources,
        "mapping_criteria": [str(x) for x in raw.get("mapping_criteria", [])] if isinstance(raw.get("mapping_criteria"), list) else [],
    }


def _get_tutorial(db: Session, tutorial_id: str) -> Tutorial:
    tutorial = db.get(Tutorial, tutorial_id)
    if tutorial is None:
        raise HTTPException(status_code=404, detail={"code": "tutorial_not_found", "message": "教程不存在"})
    return tutorial


def _goal_for(db: Session, goal_id: str):
    from ..models import LearningGoal

    goal = db.get(LearningGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})
    return goal


def _current_version(db: Session, tutorial: Tutorial) -> TutorialVersion | None:
    if not tutorial.current_version_id:
        return None
    return db.get(TutorialVersion, tutorial.current_version_id)


def tutorial_tokens(db: Session, tutorial: Tutorial) -> dict:
    """教程累计 token：优先按调用日志汇总，旧数据回退到版本字段。"""
    usage = token_usage_dict()
    source = ""
    rows = db.query(ModelCallLog).filter(ModelCallLog.tutorial_id == tutorial.id).all()
    for row in rows:
        add_usage(usage, row.prompt_tokens, row.completion_tokens, row.total_tokens)
        if row.usage_source == "provider":
            source = "provider"
        elif row.usage_source == "estimated" and source != "provider":
            source = "estimated"
    if usage["calls"] == 0:
        versions = db.query(TutorialVersion).filter(TutorialVersion.tutorial_id == tutorial.id).all()
        for version in versions:
            add_usage(usage, version.prompt_tokens, version.completion_tokens, version.total_tokens)
            if version.usage_source == "provider":
                source = "provider"
            elif version.usage_source == "estimated" and source != "provider":
                source = "estimated"
    usage["usage_source"] = source
    return usage


def tutorial_dict(db: Session, tutorial: Tutorial) -> dict:
    version = _current_version(db, tutorial)
    count = db.query(TutorialVersion).filter(TutorialVersion.tutorial_id == tutorial.id).count()
    return {
        "id": tutorial.id,
        "goal_id": tutorial.goal_id,
        "plan_step_id": tutorial.plan_step_id,
        "title": tutorial.title,
        "status": tutorial.status,
        "current_version": tutorial_version_dict(version) if version else None,
        "delivery_status": getattr(tutorial, "delivery_status", "") or "",
        "delivery_path": getattr(tutorial, "delivery_path", "") or "",
        "delivery_version": int(getattr(tutorial, "delivery_version", 0) or 0),
        "history_count": count,
        "tokens": tutorial_tokens(db, tutorial),
    }


def list_tutorials(db: Session, goal_id: str) -> list[dict]:
    rows = (
        db.query(Tutorial)
        .filter(Tutorial.goal_id == goal_id)
        .order_by(Tutorial.created_at.desc())
        .all()
    )
    return [tutorial_dict(db, t) for t in rows]


def get_tutorial(db: Session, tutorial_id: str) -> dict:
    return tutorial_dict(db, _get_tutorial(db, tutorial_id))


def _criteria_list(db: Session, goal_id: str) -> list[dict]:
    confirmed = goals_service.confirmed_criteria(db, goal_id)
    if not confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "no_confirmed_criteria",
                "message": "尚无已确认的验收标准：请先设计并确认验收标准，再生成教程（先标准、后教程）。",
            },
        )
    return confirmed

def _reading_outline_from_materials(
    db: Session, goal_id: str, criteria: list[dict]
) -> list[dict] | None:
    """阅读教程规范：直接从材料名生成确定性大纲，**不调模型**。

    为什么必须绕开大纲模型（三个都是实测阻塞，不是理论担忧）：
    1. 节数上限：`MAX_SECTIONS_HINT = 8` 会硬截断 `raw_sections[:8]`。第一卷 18 篇
       + 3 个全书层 = 21 节，模型输出的后 13 节会被静默丢掉。
    2. 输出预算：大纲提示词写死「整份 JSON 控制在 1500 字以内」，而 21 节的最小
       JSON ≈ 4000 字符 → 必然被截断 → 整份 JSON 无法解析 → 本次生成作废。
    3. 材料预算：`generate_outline` 原本把**全部材料**塞进大纲调用
       （`materials_context(db, goal.id)`，无 chapter 参数）。整卷 218,552 字符
       ≈ 153,000 token，直接超上下文窗口。而大纲只需要篇名，274 字符就够。

    篇名逐字取自材料，既不用模型猜、也不会漏篇或改写篇名。这与试卷规范的
    `apply_chapter_split`（按材料章节定死交付物）是同一个思路。

    认不出篇目时返回 None，交回大纲模型（宁可退回全量注入，也不要静默产出错结构）。
    """
    from ..models import GoalMaterial

    rows = (
        db.query(GoalMaterial)
        .filter(GoalMaterial.goal_id == goal_id, GoalMaterial.status == "ready")
        .order_by(GoalMaterial.created_at.asc())
        .all()
    )
    names: list[str] = []
    for row in rows:
        stem = re.sub(r"\.[A-Za-z0-9]+$", "", str(row.filename or "")).strip()
        if stem and materials_service.chapter_marker(stem):
            names.append(stem)
    if not names:
        # 文件名里没有「第N章/篇」编号：先看是不是「整卷一个大文件」——
        # 从正文按篇标题定节（《毛选》卷文件 # 卷 → ## 时期 → ### 篇，篇级约 30 个）。
        # 只扫标题行，不把正文拉进 prompt；篇名逐字取自材料，不用模型猜。
        for row in rows:
            if materials_service.is_global_material(str(row.filename or "")):
                continue
            body = materials_service._material_body(db, row)
            titles = materials_service.piece_titles(body)
            if titles:
                names.extend(titles)
                break
    if not names:
        # 仍没有：退回从全书级材料（目录/前言）的标题提取
        names = format_specs_service.material_chapters(
            materials_service.materials_context(db, goal_id, global_only=True)
        )
    if not names:
        return None

    # 去重后按篇号排序：用户可能乱序上传，靠编号而不是上传顺序
    seen: set[str] = set()
    ordered: list[str] = []
    for name in sorted(
        names, key=lambda x: (int(materials_service.chapter_marker(x) or 0), x)
    ):
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name[:120])
    if not ordered:
        return None
    # 与契约模式同样的总量保险丝，避免异常材料撑爆生成成本
    ordered = ordered[:CONTRACT_MAX_SECTIONS]

    criteria_ids = [str(c["id"]) for c in criteria or [] if isinstance(c, dict) and c.get("id")]
    titles = (
        list(format_specs_service.READING_BOOK_LEVEL_HEAD)
        + ordered
        + list(format_specs_service.READING_BOOK_LEVEL_TAIL)
    )
    return [
        {
            "id": uuid.uuid4().hex[:8],
            "title": title,
            "purpose": f"阅读教程交付单元：{title}",
            "content_type": "application",
            "summary": "",
            # 全书层与章节层都承载全部验收标准：阅读规范不按节拆验收点
            "criteria_ids": list(criteria_ids),
        }
        for title in titles
    ]



def _save_outline_version(db: Session, goal, tutorial, content: dict, ai, *, job_id=None) -> dict:
    """把大纲落成一个 TutorialVersion，收尾 job 并触发知识网络后台提取。

    两条大纲路径共用（模型路径 / 阅读规范的确定性路径），避免两份落库逻辑漂移。
    """
    usage = dict(ai.usage_last)
    version = TutorialVersion(
        tutorial_id=tutorial.id,
        version=1,
        content_json=jdump(content),
        prompt_version="v1",
        model_provider="demo" if ai.is_demo else "openai-compatible",
        model_name="demo" if ai.is_demo else "configured",
        quality_report=jdump({}),
        source_refs=jdump(materials_service.materials_source_refs(db, goal.id)),
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        usage_source=usage.get("usage_source", ""),
    )
    db.add(version)
    db.flush()
    tutorial.current_version_id = version.id
    set_status_at_least(goal, "learning")
    # 教程生成即更新知识网络：改为后台线程执行，大纲响应不再多等 1 次模型往返
    # （失败不阻断教程交付；提取内部有指纹去重，重复触发不会重复烧钱）
    job = db.get(GenerationJob, job_id) if job_id else None
    if job is not None:
        job.status = "done"
        job.progress = 100
        job.stage = "大纲完成（知识网络后台更新中）"
        job.prompt_tokens = usage.get("prompt_tokens", 0)
        job.completion_tokens = usage.get("completion_tokens", 0)
        job.total_tokens = usage.get("total_tokens", 0)
        job.usage_source = usage.get("usage_source", "")
    db.commit()  # 先提交并结束本事务，后台提取线程才能读到刚写入的版本
    _extract_knowledge_async(goal.id, tutorial.id, version.id)
    return {"tutorial": tutorial_dict(db, tutorial), "job": job, "demo": ai.is_demo}


def generate_outline(db: Session, goal_id: str, ai: AIService) -> dict:
    goal = _goal_for(db, goal_id)
    criteria = _criteria_list(db, goal.id)
    profile = get_profile(goal.domain_key)
    snapshot = format_specs_service.active_snapshot(goal)
    authoritative_spec = format_specs_service.authoritative_snapshot(goal)
    if snapshot:
        # 任务文本含 hard_constraints：决定交付结构的要求通常写在硬性约束里
        requirement_text = task_requirement_text(goal)
        # 阅读教程规范不用 apply_chapter_split（它靠「单元检测卷」这类成品名词判定，
        # 导读任务永远不命中），所以不必为它把整本书拉进内存——那是 218,552 字符。
        materials_for_mode = (
            "" if format_specs_service.is_reading_guide(snapshot)
            else materials_service.materials_context(db, goal.id)
        )
        snapshot = format_specs_service.apply_task_overrides(snapshot, requirement_text)
        snapshot = format_specs_service.apply_chapter_split(
            snapshot, requirement_text, materials_for_mode
        )
        goal.format_spec_snapshot = jdump(snapshot)
        # 快照刚被改写（交付物可能已按章拆分）：教程标题与结构判定都要用最新快照
        authoritative_spec = format_specs_service.authoritative_spec_dict(snapshot)

    job = GenerationJob(goal_id=goal.id, job_type="tutorial_outline", status="running", progress=10, stage="生成大纲")
    db.add(job)
    db.commit()  # 先提交，避免在等待模型返回期间持有写锁

    tutorial_title = (
        f"{goal.title} · {authoritative_spec['name']}"
        if authoritative_spec
        else f"{goal.title} · 学习教程"
    )
    tutorial = Tutorial(goal_id=goal.id, title=tutorial_title, status="outline")
    db.add(tutorial)
    db.commit()  # 先落库，让本次调用的 token / 训练样本能关联到 tutorial_id
    ai.tutorial_id = tutorial.id
    # 选定规范后独占结构权限；未选规范时才使用旧画像契约。
    contract = format_specs_service.contract_for_goal(goal)

    # 阅读教程规范：大纲由材料名确定性生成，不调模型、不注入整本书。
    # 理由见 _reading_outline_from_materials 的三条实测阻塞（节数上限 8 / JSON 预算
    # 1500 字 / 大纲阶段无材料预算）。认不出篇目时 reading_outline 为 None，
    # 自动落回下面的模型路径，行为与从前一致。
    reading_outline = (
        _reading_outline_from_materials(db, goal.id, criteria)
        if format_specs_service.is_reading_guide(snapshot) else None
    )
    if reading_outline:
        teaching_plan = normalize_teaching_plan(
            {}, parse_teaching_profile(context_text=goal_context_text(goal))
        )
        content = {
            "format_spec": snapshot,
            "teaching_plan": teaching_plan,
            "outline": reading_outline,
            "sections": [],
        }
        if contract:
            content["delivery_contract"] = contract
        job = db.get(GenerationJob, job.id)
        if job is not None:
            job.stage = f"按材料确定性生成 {len(reading_outline)} 节大纲（未调大纲模型）"
        db.commit()
        return _save_outline_version(db, goal, tutorial, content, ai, job_id=job.id if job else None)

    # 走到这里说明没能确定性定出篇目（非阅读规范，或阅读规范认不出篇目）：
    # 阅读规范退而求其次也只注入全书级材料 + 篇名清单，避免把整本书塞进大纲调用。
    materials_text = materials_service.materials_for_planning(db, goal.id, snapshot)
    try:
        try:
            data = ai.outline(
                goal, profile, [{"id": c["id"], "statement": c["statement"]} for c in criteria], materials_text
            )
            raw_sections = data.get("sections")
            if not isinstance(raw_sections, list):
                raise AIServiceError("模型输出的章节大纲不是列表，请重试")
            outline = _normalize_outline_items(raw_sections[:MAX_SECTIONS_HINT])
            if not outline:
                raise AIServiceError("模型输出缺少有效章节大纲，请重试")
            teaching_plan = normalize_teaching_plan(
                data.get("teaching_plan"), parse_teaching_profile(context_text=goal_context_text(goal))
            )
            if contract:
                outline = _contract_outline(contract, criteria)
        except AIServiceError as exc:
            # 确定性兜底：格式规范模式下章节结构本就由交付契约定死（模型输出的
            # sections 会被丢弃），teaching_plan 也有基于画像硬约束的规则化兜底。
            # 此时一次偶发的模型失败（截断 / 限流 / 解析）不该让整条「一键生成」在
            # 前几步成功后报废；非规范模式下大纲是结构的唯一来源，保持原有失败语义。
            if contract is None:
                raise
            logger.warning(
                "大纲模型调用失败，回退交付契约结构（goal=%s）：%s", goal.id, str(exc)[:200]
            )
            job.stage = "大纲模型调用失败，按交付契约生成结构"
            db.commit()
            outline = _contract_outline(contract, criteria)
            teaching_plan = normalize_teaching_plan(
                {}, parse_teaching_profile(context_text=goal_context_text(goal))
            )
        content = {"format_spec": snapshot, "teaching_plan": teaching_plan, "outline": outline, "sections": []}
        if contract:
            content["delivery_contract"] = contract
        return _save_outline_version(db, goal, tutorial, content, ai, job_id=job.id)
    except AIServiceError as exc:
        job.status = "failed"
        job.error_code = "llm_error"
        job.error_message = str(exc)[:2000]  # 把根因（如模型请求超时）留给前端展示与排查
        db.commit()
        # 清理本次未产出任何版本的「空壳教程」，避免列表出现空教程
        try:
            has_version = (
                db.query(TutorialVersion).filter(TutorialVersion.tutorial_id == tutorial.id).count() > 0
            )
            if not has_version:
                db.delete(tutorial)
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc


def start_sections(db: Session, tutorial_id: str, ai: AIService) -> dict:
    """启动后台章节生成任务并立即返回（前端轮询 /generation-jobs/{id} 获取进度）。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    _criteria_list(db, goal.id)  # 校验：必须先有已确认验收标准
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_outline", "message": "教程尚无大纲"})
    content = jload(version.content_json, {"outline": [], "sections": []})
    if not content.get("outline"):
        raise HTTPException(status_code=409, detail={"code": "no_outline", "message": "教程尚无大纲"})

    # 幂等保护：同一目标已有排队 / 进行中的章节任务时直接复用。
    # 「一键生成自动续跑」与手动按钮并发提交时不会开出两路重复生成任务。
    active = (
        db.query(GenerationJob)
        .filter(
            GenerationJob.goal_id == goal.id,
            GenerationJob.job_type == "tutorial_sections",
            GenerationJob.status.in_(("queued", "running")),
        )
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    if active is not None:
        return {"tutorial": tutorial_dict(db, tutorial), "job": active, "demo": ai.is_demo, "reused": True}

    job = GenerationJob(goal_id=goal.id, job_type="tutorial_sections", status="queued", progress=0, stage="排队")
    db.add(job)
    db.commit()  # 释放写锁后再启动后台线程

    thread = threading.Thread(target=_sections_worker, args=(tutorial.id, job.id), daemon=True)
    thread.start()
    return {"tutorial": tutorial_dict(db, tutorial), "job": job, "demo": ai.is_demo}


def _companions_missing(content: dict, goal) -> dict:
    """配套文件缺口：知识速查总是需要；额外练习只在目标开启时需要。

    交付契约（「内容只包括…不要其它内容」）已把配套文件排除在外时，一律视为不缺。
    """
    if content.get("delivery_contract") or format_specs_service.suppress_legacy_companions(goal):
        return {"cheatsheet": False, "extra_exercises": False}
    return {
        "cheatsheet": not content.get("cheatsheet"),
        "extra_exercises": bool(goal.generate_extra_exercises) and not content.get("extra_exercises"),
    }


def companions_missing(db: Session, tutorial_id: str) -> dict:
    """只读检查（不调模型）：供「一键生成」判断要不要提交后台配套任务。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    content = jload(version.content_json, {}) if version is not None else {}
    if not (content.get("sections") or []):
        return {"cheatsheet": False, "extra_exercises": False}
    return _companions_missing(content, goal)


_COMPANION_LABELS = {"cheatsheet": "知识速查", "extra_exercises": "额外练习"}


def _companion_task(
    kind: str,
    *,
    tutorial_id: str,
    goal_id: str,
    job_id: str,
    outline: list,
    materials_text: str,
) -> tuple[str, dict, dict]:
    """单个配套文件的生成任务：独立 Session + 独立 AIService（并发安全）。"""
    from ..db import SessionLocal

    from ..models import LearningGoal

    db = SessionLocal()
    try:
        goal = db.get(LearningGoal, goal_id)
        if goal is None:
            raise AIServiceError("学习目标不存在")
        profile = get_profile(goal.domain_key)
        ai = AIService(db, goal_id=goal_id, tutorial_id=tutorial_id, job_id=job_id)
        if kind == "cheatsheet":
            payload = ai.cheatsheet(goal, profile, outline, materials_text)
        else:
            exercise_spec = format_specs_service.get_exercise_spec_dict(db)
            payload = ai.extra_exercises(goal, profile, outline, materials_text, exercise_spec)
        usage = dict(ai.usage_last)
        db.commit()  # 短事务：调用日志 / 训练样本尽快落库并释放写锁
        return kind, payload, usage
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _submit_companion_tasks(
    pool: ThreadPoolExecutor,
    *,
    tutorial_id: str,
    goal_id: str,
    job_id: str,
    outline: list,
    materials_text: str,
    want_cheatsheet: bool,
    want_extra: bool,
) -> dict:
    """把配套文件任务提交到给定线程池（复用池子 = 不抬高模型并发峰值），返回 future→kind。"""
    wanted = [kind for kind, flag in (("cheatsheet", want_cheatsheet), ("extra_exercises", want_extra)) if flag]
    return {
        pool.submit(
            _companion_task,
            kind,
            tutorial_id=tutorial_id,
            goal_id=goal_id,
            job_id=job_id,
            outline=outline,
            materials_text=materials_text,
        ): kind
        for kind in wanted
    }


def _collect_companion_results(futures: dict, *, goal_title: str) -> dict:
    """等待配套任务完成并合并结果；单个失败只留痕，不拖垮另一个。"""
    result: dict = {
        "cheatsheet": None,
        "extra_exercises": None,
        "usage": token_usage_dict(),
        "errors": [],
    }
    payloads: dict[str, dict] = {}
    for future in as_completed(futures):
        kind = futures[future]
        try:
            _, payload, usage = future.result()
        except Exception as exc:  # noqa: BLE001  单文件失败不影响另一个
            result["errors"].append(f"{_COMPANION_LABELS[kind]}生成失败：{str(exc)[:80]}")
            continue
        payloads[kind] = payload
        add_usage(
            result["usage"],
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
        if usage.get("usage_source") == "provider":
            result["usage"]["usage_source"] = "provider"
        elif usage.get("usage_source") == "estimated" and result["usage"]["usage_source"] != "provider":
            result["usage"]["usage_source"] = "estimated"

    if "cheatsheet" in payloads:
        result["cheatsheet"] = {
            "filename": f"{_safe_filename(goal_title)}-知识速查",
            **payloads["cheatsheet"],
        }
    if "extra_exercises" in payloads:
        result["extra_exercises"] = {
            "filename": f"{_safe_filename(goal_title)}-额外练习",
            **payloads["extra_exercises"],
        }
    return result


def _generate_companions(
    *,
    tutorial_id: str,
    goal_id: str,
    goal_title: str,
    job_id: str,
    outline: list,
    materials_text: str,
    want_cheatsheet: bool,
    want_extra: bool,
) -> dict:
    """知识速查与额外练习互不依赖 → 并行生成；单个失败只留痕，不拖垮另一个。"""
    wanted = [kind for kind, flag in (("cheatsheet", want_cheatsheet), ("extra_exercises", want_extra)) if flag]
    if not wanted:
        return {"cheatsheet": None, "extra_exercises": None, "usage": token_usage_dict(), "errors": []}

    with ThreadPoolExecutor(max_workers=len(wanted), thread_name_prefix="companion") as pool:
        futures = _submit_companion_tasks(
            pool,
            tutorial_id=tutorial_id,
            goal_id=goal_id,
            job_id=job_id,
            outline=outline,
            materials_text=materials_text,
            want_cheatsheet=want_cheatsheet,
            want_extra=want_extra,
        )
        return _collect_companion_results(futures, goal_title=goal_title)


def ensure_companions(db: Session, tutorial_id: str, ai: AIService, *, strict: bool = True) -> dict:
    """为已有章节的教程补齐配套文件：知识速查（总是）+ 独立额外练习（用户开启时）。

    用于「先有教程、后开启选项」或旧版本缺配套的场景；不重复生成已存在的文件。
    生成成功会落一个新版本（内容 = 原内容 + 配套文件）。
    strict=True 时任一文件失败抛 AIServiceError（同步调用方）；strict=False 只回传 errors。
    """
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {})
    sections = content.get("sections") or []
    if not sections:
        return {
            "changed": False,
            "cheatsheet": False,
            "extra_exercises": False,
            "errors": [],
            "tutorial": tutorial_dict(db, tutorial),
        }

    outline = content.get("outline", [])
    missing = _companions_missing(content, goal)
    if not any(missing.values()):
        return {
            "changed": False,
            "cheatsheet": False,
            "extra_exercises": False,
            "errors": [],
            "tutorial": tutorial_dict(db, tutorial),
        }

    materials_text = materials_service.materials_context(db, goal.id)
    ai.tutorial_id = tutorial.id
    result = _generate_companions(
        tutorial_id=tutorial.id,
        goal_id=goal.id,
        goal_title=goal.title,
        job_id=ai.job_id or "",
        outline=outline,
        materials_text=materials_text,
        want_cheatsheet=missing["cheatsheet"],
        want_extra=missing["extra_exercises"],
    )
    if strict and result["errors"]:
        raise AIServiceError("；".join(result["errors"]))

    changed = {
        "cheatsheet": result["cheatsheet"] is not None,
        "extra_exercises": result["extra_exercises"] is not None,
    }
    if not any(changed.values()):
        return {
            "changed": False,
            "cheatsheet": False,
            "extra_exercises": False,
            "errors": result["errors"],
            "tutorial": tutorial_dict(db, tutorial),
        }
    if result["cheatsheet"] is not None:
        content["cheatsheet"] = result["cheatsheet"]
    if result["extra_exercises"] is not None:
        content["extra_exercises"] = result["extra_exercises"]

    usage = result["usage"]
    new_version = TutorialVersion(
        tutorial_id=tutorial.id,
        version=version.version + 1,
        content_json=jdump(content),
        prompt_version="v1",
        model_provider="demo" if ai.is_demo else "openai-compatible",
        model_name="demo" if ai.is_demo else "configured",
        quality_report=version.quality_report,
        source_refs=version.source_refs,
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        total_tokens=usage["total_tokens"],
        usage_source=usage.get("usage_source", "") or ("estimated" if usage["total_tokens"] else ""),
    )
    db.add(new_version)
    db.flush()
    tutorial.current_version_id = new_version.id
    db.commit()
    return {
        "changed": True,
        "cheatsheet": changed["cheatsheet"],
        "extra_exercises": changed["extra_exercises"],
        "errors": result["errors"],
        "tutorial": tutorial_dict(db, tutorial),
    }


def start_companions(db: Session, tutorial_id: str, ai: AIService) -> dict:
    """后台补齐配套文件并立即返回 job（前端轮询 /generation-jobs/{id}）。

    「一键生成」在章节已存在时补齐配套文件，此前同步调用会让请求卡 1-2 分钟；
    这里改成与章节生成同构的后台任务，接口响应结构不变（仍返回 job_id）。
    """
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {})
    if not (content.get("sections") or []):
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无章节内容"})
    # 交付契约明确排除配套文件时直接拒绝，避免排一个什么都不做的后台任务
    if content.get("delivery_contract") or format_specs_service.suppress_legacy_companions(goal):
        raise HTTPException(
            status_code=409,
            detail={"code": "no_companions", "message": "本次交付按画像硬性约束只交付指定内容，不生成配套文件"},
        )

    active = (
        db.query(GenerationJob)
        .filter(
            GenerationJob.goal_id == goal.id,
            GenerationJob.job_type == "tutorial_companions",
            GenerationJob.status.in_(("queued", "running")),
        )
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    if active is not None:
        # 幂等：已有后台任务在跑就复用，避免连点产生重复生成与重复计费
        return {"tutorial": tutorial_dict(db, tutorial), "job": active, "demo": ai.is_demo, "reused": True}

    job = GenerationJob(
        goal_id=goal.id, job_type="tutorial_companions", status="queued", progress=0, stage="排队"
    )
    db.add(job)
    db.commit()  # 释放写锁后再启动后台线程

    thread = threading.Thread(target=_companions_worker, args=(tutorial.id, job.id), daemon=True)
    thread.start()
    return {"tutorial": tutorial_dict(db, tutorial), "job": job, "demo": ai.is_demo, "reused": False}


def _knowledge_extraction_worker(goal_id: str, tutorial_id: str, version_id: str) -> None:
    """后台线程：教程完成后的知识网络提取（独立会话 + 独立 AIService）。

    提取只服务知识图谱，不阻塞教程内容交付；挪到后台后，大纲响应与章节 job
    都不必再多等 1 次完整模型往返。失败只留痕不重试；提取内部有指纹去重，
    重复触发不会重复烧钱。
    """
    from ..db import SessionLocal
    from ..models import LearningGoal

    db = SessionLocal()
    try:
        goal = db.get(LearningGoal, goal_id)
        tutorial = db.get(Tutorial, tutorial_id)
        version = db.get(TutorialVersion, version_id) if version_id else None
        if goal is None or tutorial is None:
            return
        ai = AIService(db, goal_id=goal_id, tutorial_id=tutorial_id)
        with _KNOWLEDGE_EXTRACTION_LOCK:
            knowledge_service.extract_from_tutorial(db, goal, tutorial, version, ai)
        db.commit()
    except Exception:  # noqa: BLE001  提取失败不影响教程交付（原语义：失败只留痕不阻断）
        db.rollback()
        # 后台化后 job.stage 无法再承载失败原因，这里必须落服务日志留痕
        logger.warning(
            "知识网络提取失败（goal=%s tutorial=%s version=%s）",
            goal_id,
            tutorial_id,
            version_id,
            exc_info=True,
        )
    finally:
        with _PENDING_EXTRACTIONS_LOCK:
            _PENDING_EXTRACTIONS.discard(threading.current_thread())
        db.close()


def _extract_knowledge_async(goal_id: str, tutorial_id: str, version_id: str) -> None:
    thread = threading.Thread(
        target=_knowledge_extraction_worker,
        args=(goal_id, tutorial_id, version_id),
        name="knowledge-extract",
        daemon=True,
    )
    # 先登记再启动：调用方在 start() 返回后即可看到「还有后台提取在跑」
    with _PENDING_EXTRACTIONS_LOCK:
        _PENDING_EXTRACTIONS.add(thread)
    thread.start()


def _update_job(
    db: Session, job_id: str, *, progress: int | None = None, stage: str | None = None, status: str | None = None
) -> None:
    job = db.get(GenerationJob, job_id)
    if job is None:
        return
    if progress is not None:
        job.progress = progress
    if stage is not None:
        job.stage = stage
    if status is not None:
        job.status = status


def _fail_job(db: Session, job_id: str, code: str, message: str = "") -> None:
    try:
        db.rollback()
        job = db.get(GenerationJob, job_id)
        if job:
            job.status = "failed"
            job.error_code = code
            job.error_message = (message or "")[:2000]
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


SECTION_RETRY_DELAYS = (3, 8)


def _with_rule_check(section_data: dict, raw) -> dict:
    """保留生成阶段对画像硬约束的核验结果；未触发核验时不留空字段。"""
    check = raw.get("rule_check") if isinstance(raw, dict) else None
    if isinstance(check, dict) and check:
        section_data["rule_check"] = check
    return section_data


def _section_with_retry(
    db: Session,
    job_id: str,
    ai: AIService,
    goal,
    profile,
    item: dict,
    criteria: list[dict],
    prior_titles: list[str],
    materials_text: str,
    companion_names: list[str] | None = None,
) -> dict:
    """单节生成带重试。

    模型偶发超时 / 限流 / 输出被截断时自动重试，避免「一键生成」在最后一节整体失败。
    每次重试前把原因写进 job.stage 与 job.retry_count，失败后仍可从 error_message 看到根因。
    """
    attempts = len(SECTION_RETRY_DELAYS) + 1
    for attempt in range(1, attempts + 1):
        try:
            return ai.section(
                goal, profile, item, criteria, prior_titles, materials_text, companion_names
            )
        except AIServiceError as exc:
            if attempt >= attempts:
                raise
            job = db.get(GenerationJob, job_id)
            if job is not None:
                job.retry_count = (job.retry_count or 0) + 1
                job.stage = f"第 {attempt} 次重试（{str(exc)[:60]}）"
            db.commit()
            time.sleep(SECTION_RETRY_DELAYS[attempt - 1])
    raise AIServiceError("章节生成重试次数已用完")


def _reading_materials_by_section(db: Session, goal_id: str, content: dict) -> dict[str, str]:
    """为阅读规范的每一节复原「该节注入的材料原文」，供摘录溯源校验（Q001）做基准。

    阅读规范章节生成时材料是按章注入的，但生成完成后各节的 materials_text 已不在手上；
    这里用与 worker 完全一致的口径复原：节标题 → chapter_marker 提章号 → materials_context
    按章取。取不到就留空串，spec_check 对空材料会跳过 Q001（不指控），不产生假阳性。
    """
    out: dict[str, str] = {}
    for section in content.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title", "") or "")
        if not title:
            continue
        chapter = materials_service.chapter_marker(title)
        try:
            out[title] = materials_service.materials_context(
                db, goal_id, chapter=chapter,
            ) if chapter else materials_service.materials_context(db, goal_id, global_only=True)
        except Exception:  # noqa: BLE001  材料复原失败不该阻断校验，留空即可
            out[title] = ""
    return out


def _apply_exam_quality(
    db: Session, content: dict, quality: dict, goal, tutorial_id: str, job_id: str,
    *, verify_enabled: bool, version: int = 0,
) -> None:
    """试卷质量三层（L0 账目 / L1 盲解 / 跨卷重算）统一入口，就地改写 content 与 quality。

    把三层收敛到一个函数，是为了让**两个调用点**（后台 _sections_worker 全量生成、
    同步 regenerate_section 单节重写）用同一套顺序与同一套 quality 合并逻辑，
    避免各写一遍时漏掉「L1 改完答案后要重算跨卷」这类顺序依赖。

    content 会被就地改写（修复写回章节正文），quality 会被就地补 checks/issues/
    exam_check/exam_verify 并重算 passed。调用方负责随后落库 content_json 与 quality_report。

    L1 只在配置了真实模型且 verify_enabled 时跑；演示模式自动跳过（见 exam_verify）。
    """
    discipline = get_profile(goal.domain_key)
    summary = exam_verify_service.run_exam_quality(
        content,
        goal_id=goal.id,
        tutorial_id=tutorial_id,
        job_id=job_id,
        discipline=discipline,
        verify_enabled=verify_enabled,
    )
    checks, issues = exam_verify_service.quality_from_summary(summary)
    # checks 去重：exam_check 与 exam_verify 各自产出的检查项名不与 check_structure 冲突，
    # 但同一份 quality 里不能出现两条同名（重算场景），先剔除旧的 exam 检查项名。
    exam_names = set(exam_check_service.EXAM_CHECK_NAMES) | {"试卷答案盲解核验"}
    base_checks = [c for c in quality.get("checks", []) if c.get("name") not in exam_names]
    quality["checks"] = base_checks + checks
    # issues：结构检查的 issues 保留在前，exam 的追加在后
    base_issues = [i for i in quality.get("issues", []) if not str(i).startswith(("[E0", "[DEFECT]"))]
    quality["issues"] = base_issues + issues
    quality["passed"] = (
        all(bool(c.get("passed", True)) for c in quality["checks"]) and not quality["issues"]
    )
    quality["exam_check"] = summary.get("l0")
    l1 = summary.get("l1") or {}
    quality["exam_verify"] = l1 if l1.get("enabled") else None

    # ---- 规范专项校验（阅读摘录溯源 / 实践步骤与代码）----
    # 按 scene 分派：exam 类已在上面 run_exam_quality 里校验过，这里只补 reading_guide
    # 与 practical_tutorial。阅读规范需要材料原文做 Q001 逐字比对的基准。
    spec_summary = spec_check_service.check_sections(
        content,
        materials_by_section=(
            _reading_materials_by_section(db, goal.id, content)
            if spec_check_service.is_reading_content(content.get("format_spec"))
            else None
        ),
        domain_key=goal.domain_key,
    )
    if spec_summary.get("kind"):
        quality["spec_check"] = spec_summary
        spec_names = {"原文摘录溯源校验", "实践步骤与代码校验"}
        quality["checks"] = [
            c for c in quality["checks"] if c.get("name") not in spec_names
        ] + spec_check_service.quality_checks(spec_summary)
        quality["issues"] = quality["issues"] + spec_check_service.quality_issues(spec_summary)
        quality["passed"] = (
            all(bool(c.get("passed", True)) for c in quality["checks"]) and not quality["issues"]
        )

    # ---- 命题质量回流（P2 冷启动素材）----
    # 把 L0 跨卷冲突（E017/E018）+ L1 缺陷沉淀成 QualityRecord，供 distill_principles
    # 聚类成命题规律。fire-and-forget：回流失败不阻断教程交付（与知识提取同款约定）。
    # 去重键含 version，所以版本号必须传对——传固定值会让新版本的新缺陷被误判为重复。
    try:
        proposition_service.reflow_quality_records(
            db, goal, tutorial_id, version, summary.get("l0") or {}, l1,
        )
    except Exception as exc:  # noqa: BLE001  质量回流是增强环节，失败不阻断交付
        logger.warning("命题质量回流失败（tutorial=%s v%s）：%s", tutorial_id, version, exc)


def _merge_section_usage(results: dict[int, dict]) -> dict:
    """按大纲顺序汇总各节 usage（真实 provider usage 优先于估算）。"""
    usage = token_usage_dict()
    source = ""
    for idx in sorted(results):
        last = results[idx]["usage"]
        add_usage(
            usage,
            last.get("prompt_tokens"),
            last.get("completion_tokens"),
            last.get("total_tokens"),
        )
        if last.get("usage_source") == "provider":
            source = "provider"
        elif last.get("usage_source") == "estimated" and source != "provider":
            source = "estimated"
    usage["usage_source"] = source
    return usage

# ------------------------------------------------------------------ 阅读教程规范：两阶段生成
#
# 只有 scene == READING_GUIDE_SCENE 时启用。其它规范走原有的「一批全并行 + 全量注入材料」
# 路径，行为逐字不变（这是本次改动的硬边界，见 test_reading_guide_two_phase）。
#
# 为什么需要两阶段：阅读规范的全书层内容（思想背景 / 学术争鸣 / 总结）在语义上依赖各章
# 导读的产出，但章节是并行生成的、互相看不见对方正文（只拿到 prior_titles）。把它们塞进
# 同一批并行任务，必然复现练习规范「参考答案」章的故障：那一节没见过任何题目，只能幻觉，
# 实测仅产出 1196 字符却烧掉 11095 completion_tokens。
# 解法是把全书层挪到所有章节完成之后，喂给它各章概要（不是全书原文，成本极低）。

READING_CHAPTER_DIGEST_CHARS = 3000      # 单章概要喂给全书层的上限（章数少时的理想值）
READING_DIGEST_MIN_CHARS = 600           # 单章概要的下限：再低就只剩标题，失去整合价值
READING_DIGEST_TOTAL_CHARS = 60000       # 全部章概要合计上限（约 4.2 万 token；加规范后仍远低于窗口）
READING_PREFER_BLOCK_RE = re.compile(r"概要|概览|小结|导读")
# 概要段落的结束标记：遇到「深度导读 / 核心概念详解」这类明确进入细节的标题就停，
# 避免把深度层的大段内容也喂给全书层（既挤占预算，又让全书层陷进细节丢掉全局视角）。
READING_DIGEST_STOP_RE = re.compile(r"深度导读|核心概念|关键句段|论证结构|难点辨析|思想关联")
_HEADING_LINE_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$")


def _extract_summary_segment(body: str, limit: int) -> str:
    """从一整块 body 里抽出「概要」段落。

    阅读规范要求「一节只输出一个 content 块」，所以概要不是独立的块、而是 body 里的
    一个 `### 本章概要` 小标题段。只按块标题找会全部落空，退化成「从头截 300 字」，
    把深度导读的细节一起喂给后置全书层——既挤占 token 预算，又让全书层陷进细节、
    丢掉它本该有的全局视角。

    取法：定位标题含「概要」的小标题行，取到下一个**同级或更浅**标题、
    或命中 READING_DIGEST_STOP_RE 的标题、或 limit 为止。
    """
    lines = str(body or "").splitlines()
    start = None
    start_level = 0
    fence: str | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            fence = marker if fence is None else (None if stripped.startswith(fence) else fence)
            continue
        if fence is not None:
            continue
        match = _HEADING_LINE_RE.match(stripped)
        if not match:
            continue
        if start is None:
            heading_text = match.group(2)
            # 「深度导读」含「导读」会被 PREFER 误命中，必须排除
            if READING_PREFER_BLOCK_RE.search(heading_text) and not READING_DIGEST_STOP_RE.search(heading_text):
                start = idx + 1
                start_level = len(match.group(1))
            continue
        # 已经在概要段内：遇到同级/更浅标题，或深度层标题，就结束
        if len(match.group(1)) <= start_level or READING_DIGEST_STOP_RE.search(match.group(2)):
            end = idx
            break
    else:
        end = len(lines)

    if start is None:
        return ""
    segment = "\n".join(lines[start:end]).strip()
    if len(segment) > limit:
        segment = segment[:limit] + "\n…（本章概要已截断）"
    return segment


def _reading_piece_titles(db: Session, goal_id: str) -> list[str]:
    """材料无章号时的「篇」级标题清单（按篇切片的键来源）。

    只扫标题行（piece_titles 内部不读正文进 prompt），成本可忽略。
    全书级材料（目录/前言）不参与；第一份有篇结构的正文材料即为准。
    """
    from ..models import GoalMaterial

    rows = (
        db.query(GoalMaterial)
        .filter(GoalMaterial.goal_id == goal_id, GoalMaterial.status == "ready")
        .order_by(GoalMaterial.created_at.asc())
        .all()
    )
    for row in rows:
        if materials_service.is_global_material(str(row.filename or "")):
            continue
        titles = materials_service.piece_titles(materials_service._material_body(db, row))
        if titles:
            return titles
    return []


def _reading_chapters_of(outline: list[dict], piece_titles: list[str] | None = None) -> dict[int, str]:
    """大纲索引 -> 切片键（归一化章号，或**与材料篇名逐字匹配**的篇键）。

    章号来自节标题（材料章节名逐字进入大纲，所以标题里必然带「第 N 章」）。
    归一化是必须的：大纲写「第 1 章」而文件名写「第一章」，不归一就永远匹配不上，
    按章注入会静默退化成「一节材料都拿不到」。

    材料完全没有章号时（《毛选》卷文件：# 卷 → ## 时期 → ### 篇），键退为篇名 ——
    但**只有节标题命中材料篇名清单才算篇层**：全书层与杂散节不在清单里，
    仍归全书层（第二批吃各篇概要）。否则「任何无章号节都当篇」会把
    全书认知地图 / 杂散节也塞进第一批并给它们切不出材料。
    """
    pieces = {materials_service._norm_title(t) for t in (piece_titles or [])}
    result: dict[int, str] = {}
    for idx, item in enumerate(outline or []):
        title = str(item.get("title", "") or "")
        mark = materials_service.chapter_marker(title)
        if mark:
            result[idx] = mark
            continue
        norm = materials_service._norm_title(title)
        if norm and norm in pieces:
            result[idx] = f"piece::{norm}"
    return result


def _reading_phase_plan(outline: list[dict], piece_titles: list[str] | None = None) -> dict:
    """把大纲切成 章节层 / 全书层 两段，并给出章号映射。

    判据只看「节标题里有没有章号」，是确定性的，不依赖模型自觉：
      - 带章号的节 -> chapters（第一批并行，各吃自己那一章）
      - 其余全书级节（认知地图 / 阅读路线 / 思想背景 / 争鸣…）-> book_level
        （第二批，**最后**生成，吃各章概要）

    为什么全书层一律放最后、而不是按文档位置把开头的放前面：
    「全书认知地图 / 阅读路线」要写核心思想、思维导图、章节依赖，必须知道每章**实际**讲了什么。
    若与章节层同批并行，它们只能拿到目录名去猜，还会与章节层互相看不见 → 重演
    pipeline.md §4 那个故障（全书层说「第一章讲 X」，第一章实际讲 Y）。
    放最后、吃各章概要，既符合用户「最后生成全书层」的要求，也让它有真凭实据。
    生成顺序与文档顺序解耦：results 按 index 排序合并，全书认知地图仍排在导出文档最前。

    没有任何章号时（例如导读一篇论文、或材料没有章结构）返回 fallback=True：
    此时按章注入无从谈起，退回原有的全量注入 + 单批并行，不启用两阶段。
    """
    marks = _reading_chapters_of(outline, piece_titles)
    if not marks:
        return {"fallback": True, "chapters": [], "book_level": [], "marks": {}}
    chapter_idx = sorted(marks)
    book_level = [i for i in range(len(outline)) if i not in marks]
    return {
        "fallback": False,
        "chapters": chapter_idx,
        "book_level": book_level,
        "marks": marks,
    }


def _truncate_before_deep_dive(body: str, limit: int) -> str:
    """兜底截取：即使没有「概要」小标题，也必须在深度层标题前停下。

    _reading_digest 的第 3 级兜底原本是「从头截 N 字」。但模型漏写 `### 本章概要`
    时，这一截会把「深度导读 / 核心概念详解 / 关键句段解读」的大段细节全部吞进 digest：
    一是挤占后置全书层的 token 预算（细节动辄数千字），二是让本该有全局视角的
    全书层陷进细节里。所以在第一个深度层标题处切断，只保留它之前的内容。
    """
    text = str(body or "")
    fence: str | None = None
    for idx, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            fence = marker if fence is None else (None if stripped.startswith(fence) else fence)
            continue
        if fence is not None:
            continue
        match = _HEADING_LINE_RE.match(stripped)
        if match and READING_DIGEST_STOP_RE.search(match.group(2)):
            text = "\n".join(text.splitlines()[:idx])
            break
    text = text.strip()
    if not text:
        # 整块 body 第一个标题就是深度层（模型既没写概要小标题、也没有前置正文）：
        # 不能返回空串 —— digest_block 会因此整章跳过，全书层将完全不知道这一章存在，
        # 直接违背「思想完整性」。退回开头片段并显式标注不可靠，让全书层知道有缺口。
        head = str(body or "").strip()[: min(400, limit)]
        if not head.strip():
            return ""
        return head + "\n…（本章缺「本章概要」小节，以上为开头片段，不足以免凭此判断全章）"
    if len(text) > limit:
        text = text[:limit] + "\n…（本章概要已截断）"
    return text


def _reading_digest(section: dict, limit: int = READING_CHAPTER_DIGEST_CHARS) -> str:
    """从一章的成品里抽出「概要」，喂给后置全书层。

    三级取法，从最可靠到最兜底：
    1. 块标题就含「概要 / 小结 / 导读」-> 直接取该块（规范早期按块拆分的形态）；
    2. 一节一块时，概要是 body 里的 `### 本章概要` 小标题段 -> 按标题层级切段抽取；
    3. 两者都找不到 -> 从头截取（并在超限时标注截断）。

    第 2 级是必须的：阅读规范要求「一节只输出一个 content 块」，此时块标题等于章名
    （如「第一章 导论」），第 1 级必然落空。若直接跳到第 3 级「从头截 3000 字」，
    会把深度导读的大段细节一起喂进后置全书层 —— 既挤占 token 预算，又让本该有全局
    视角的那一节陷进细节里。
    """
    blocks = [b for b in (section.get("content") or []) if isinstance(b, dict)]
    if not blocks:
        return ""

    # 1. 块标题直接就是概要层
    # 必须排除 STOP：「深度导读」含「导读」二字，会被 PREFER 误命中，
    # 而它恰恰是细节层，喂进后置全书层会挤占预算并把全局视角拖进细节。
    def _is_summary_block(b: dict) -> bool:
        title = str(b.get("title", "") or "")
        return bool(READING_PREFER_BLOCK_RE.search(title)) and not READING_DIGEST_STOP_RE.search(title)

    preferred = [b for b in blocks if _is_summary_block(b)]
    if preferred:
        parts: list[str] = []
        used = 0
        for block in preferred:
            body = str(block.get("body", "") or "").strip()
            if not body:
                continue
            piece = body[:limit - used] if used + len(body) > limit else body
            if not piece.strip():
                break
            parts.append(piece)
            used += len(piece)
            if used >= limit:
                break
        if parts:
            return "\n\n".join(parts)

    # 2. 一节一块：在 body 里按小标题切出概要段
    collected: list[str] = []
    used = 0
    for block in blocks:
        body = str(block.get("body", "") or "")
        segment = _extract_summary_segment(body, limit - used)
        if not segment:
            continue
        collected.append(segment)
        used += len(segment)
        if used >= limit:
            break
    if collected:
        return "\n\n".join(collected)

    # 3. 兜底：模型没写概要小标题，从头取，但仍须在深度层标题前停下（否则吞入大段细节）
    fallback: list[str] = []
    used = 0
    for block in blocks:
        title = str(block.get("title", "") or "").strip()
        body = str(block.get("body", "") or "").strip()
        if not body:
            continue
        piece = _truncate_before_deep_dive(body, max(0, limit - used))
        if not piece.strip():
            continue
        piece = f"【{title}】\n{piece}" if title else piece
        fallback.append(piece)
        used += len(piece)
        if used >= limit:
            break
    return "\n\n".join(fallback)


def _reading_digest_block(outline: list[dict], results: dict[int, dict], indices: list[int]) -> str:
    """把各章概要拼成一个材料块，作为全书层的注入材料。

    这里刻意不注入全书原文：全书层的职责是「整合各章导读」，而各章导读本身就是
    从原文提炼出来的。换成全书原文是 28 万 token，直接超窗口。

    单章额度随章数自适应：章数多时压缩每章额度，**保证没有一章被整章丢弃**。
    曾用固定 3000 字/章 + 30000 字合计上限，18 章需要 54000 字，后 8 章被静默截掉，
    于是「核心概念索引」漏条目、「阅读路线」漏章节，而且没有任何提示。
    """
    # 自适应单章额度：章数越多每章越少，但不低于 READING_DIGEST_MIN_CHARS
    n = max(1, len(indices))
    per_chapter = max(
        READING_DIGEST_MIN_CHARS,
        min(READING_CHAPTER_DIGEST_CHARS, READING_DIGEST_TOTAL_CHARS // n),
    )
    chunks: list[str] = []
    total = 0
    for idx in indices:
        result = results.get(idx)
        if not result:
            continue
        section = result.get("section") or {}
        title = str(section.get("title") or (outline[idx].get("title", "") if idx < len(outline) else ""))
        digest = _reading_digest(section, limit=per_chapter)
        if not digest:
            continue
        piece = f"\n\n===== {title} =====\n{digest}"
        if total + len(piece) > READING_DIGEST_TOTAL_CHARS:
            chunks.append("\n\n（其余章节概要因长度上限未注入，不得声称已通读全书）")
            break
        chunks.append(piece)
        total += len(piece)
    if not chunks:
        return ""
    return (
        "【各章导读概要（由本次生成的章节层产出，供全书层整合；不是原著原文，"
        "不得据此编造原文未出现的内容）】" + "".join(chunks)
    )



def _generate_section_task(
    *,
    tutorial_id: str,
    goal_id: str,
    job_id: str,
    index: int,
    item: dict,
    criteria_dicts: list[dict],
    prior_titles: list[str],
    materials_text: str,
    outline_titles: list[str] | None = None,
    chapter: str | None = None,
    all_chapters: list[str] | None = None,
) -> dict:
    """并发生成的单节任务：独立 Session + 独立 AIService。

    SQLite 只允许单写者：每次调用只在「读上下文 → 写日志」这两处开短事务，
    等模型返回的整段时间不持有写锁。
    """
    from ..db import SessionLocal
    from ..models import LearningGoal

    db = SessionLocal()
    try:
        goal = db.get(LearningGoal, goal_id)
        if goal is None:
            raise AIServiceError("学习目标不存在")
        profile = get_profile(goal.domain_key)
        ai = AIService(db, goal_id=goal_id, tutorial_id=tutorial_id, job_id=job_id)
        section_id = uuid.uuid4().hex[:8]
        ai.section_id = section_id
        # 阅读教程规范章节层：本节只注入自己那一章 + 全书级材料（目录/前言）。
        # 全书层不经过这里——它在第二批由 worker 直接传 digest_block 作为 materials_text。
        # 其它规范 chapter 恒为 None，仍用传进来的全量 materials_text，行为不变。
        if chapter:
            if chapter.startswith("piece::"):
                materials_text = materials_service.materials_context(
                    db, goal_id, piece=chapter[len("piece::"):], all_chapters=all_chapters or [],
                    global_max_chars=materials_service.READING_GLOBAL_MAX_CHARS,
                )
            else:
                materials_text = materials_service.materials_context(
                    db, goal_id, chapter=chapter, all_chapters=all_chapters or [],
                    global_max_chars=materials_service.READING_GLOBAL_MAX_CHARS,
                )
        criteria_by_id = {c["id"]: c for c in criteria_dicts}
        mapped = [criteria_by_id[cid] for cid in item.get("criteria_ids", []) if cid in criteria_by_id]
        # 配套文件名在生成章节时已确定（见 _generate_companions），提前注入，避免模型猜错双链目标；
        # 交付契约模式下不生成配套文件，正文也就不该出现双链
        companion_names = [] if item.get("_deliverable") else [f"{_safe_filename(goal.title)}-知识速查"]
        if companion_names and bool(getattr(goal, "generate_extra_exercises", False)):
            companion_names.append(f"{_safe_filename(goal.title)}-额外练习")
        raw = _section_with_retry(
            db, job_id, ai, goal, profile, item, mapped or criteria_dicts, prior_titles,
            materials_text, companion_names,
        )
        usage = dict(ai.usage_last)
        db.commit()  # 短事务：调用日志 / 训练样本立即落库，尽快释放写锁
        section_data = _with_rule_check(_normalize_section_raw(raw), raw)
        # 确定性兜底：模型偶尔把整篇文档写进一节，先按大纲标题剔除其它章节的整块内容
        section_data = prune_section_foreign_blocks(section_data, outline_titles or [])
        # 阅读规范：模型把一章拆成多块时合并回单块，避免渲染层级错位（见函数 docstring）
        if format_specs_service.is_reading_guide(jload(goal.format_spec_snapshot or "", {})):
            section_data = _merge_reading_section_blocks(section_data)
        if format_specs_service.authoritative_snapshot(goal):
            section_data["title"] = item.get("title", "") or section_data.get("title", "")
        # 交付物章节统一用契约里的名称，避免模型把标题写成「目标：三项」
        section_data["title"] = (
            item.get("title", "")
            if item.get("_deliverable")
            else (section_data["title"] or item.get("title", ""))
        )
        section_data.update(
            {
                "id": section_id,
                "mapping_criteria": list(item.get("criteria_ids", [])),
                "token_usage": usage,
            }
        )
        return {"index": index, "section": section_data, "usage": usage}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _sections_worker(tutorial_id: str, job_id: str) -> None:
    """后台线程：最多 3 路并发生成章节，结果按大纲顺序合并。

    每节使用独立 Session / AIService（互不共享 ORM 与 usage_last），完成一节即按大纲
    顺序提交草稿；任一节最终失败仍使整个 job 失败，但已完成内容已落库不丢。
    """
    from ..db import SessionLocal
    from ..models import LearningGoal

    db = SessionLocal()
    try:
        tutorial = db.get(Tutorial, tutorial_id)
        if tutorial is None:
            _fail_job(db, job_id, "tutorial_not_found")
            return
        goal = db.get(LearningGoal, tutorial.goal_id)
        if goal is None:
            _fail_job(db, job_id, "goal_not_found")
            return
        # materials_text 惰性计算：阅读规范按章注入，全程用不到全量材料（章节走 chapter、
        # 前置全书层走 global_only、后置全书层走各章概要、配套文件被 suppress），
        # 对整本书（40 万字）白读一遍全量是纯浪费。只有非阅读规范才在下方计算全量。
        materials_text = ""
        criteria_dicts = goals_service.confirmed_criteria(db, goal.id)
        version = db.get(TutorialVersion, tutorial.current_version_id) if tutorial.current_version_id else None
        content = jload(version.content_json, {"outline": [], "sections": []}) if version else {}
        outline = content.get("outline", [])
        teaching_plan = content.get("teaching_plan") or normalize_teaching_plan(
            {}, parse_teaching_profile(context_text=goal_context_text(goal))
        )
        # 交付契约决定章节形态；选定规范后不再把旧画像契约叠加进来。
        contract = format_specs_service.contract_for_goal(goal, content.get("delivery_contract"))
        if contract and content.get("delivery_contract") != contract:
            outline = _contract_outline(contract, criteria_dicts)
            content = {
                **content,
                "format_spec": format_specs_service.active_snapshot(goal),
                "delivery_contract": contract,
                "outline": outline,
                "sections": [],
            }
        contract_items = (contract or {}).get("items") or []
        # 选定规范时，配套文件只能由当前规范明确要求，不再沿用旧画像的自动配套设置。
        suppress_companions = (
            bool(contract) or format_specs_service.suppress_legacy_companions(goal)
        )
        if not outline:
            _fail_job(db, job_id, "no_outline")
            return

        model_snapshot = runtime_settings()
        # 草稿版本：每完成一节即写入，避免中断丢失已完成章节
        base_version = version.version if version else 0
        draft = TutorialVersion(
            tutorial_id=tutorial.id,
            version=base_version + 1,
            content_json=jdump(
                {
                    "format_spec": content.get("format_spec") or jload(goal.format_spec_snapshot or "", {}),
                    "teaching_plan": teaching_plan,
                    "outline": outline,
                    "sections": [],
                    **({"delivery_contract": contract} if contract else {}),
                }
            ),
            prompt_version="v1",
            model_provider="demo" if not model_snapshot.llm_configured else "openai-compatible",
            model_name=model_snapshot.llm_model or "demo",
            quality_report=jdump({}),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            usage_source="",
        )
        db.add(draft)
        db.commit()

        outline_titles = [str(o.get("title", "")) for o in outline]
        total = len(outline)
        results: dict[int, dict] = {}
        failures: list[tuple[int, Exception]] = []

        # ---- 阅读教程规范：两阶段 + 按章注入（其它规范 phase["fallback"]=True，逐字走原路径）----
        reading_spec = content.get("format_spec") or jload(goal.format_spec_snapshot or "", {})
        reading_mode = format_specs_service.is_reading_guide(reading_spec)
        piece_titles = _reading_piece_titles(db, goal.id) if reading_mode else []
        phase = (
            _reading_phase_plan(outline, piece_titles) if reading_mode
            else {"fallback": True, "chapters": [], "book_level": [], "marks": {}}
        )
        if phase["fallback"]:
            reading_mode = False
        reading_marks = phase["marks"]
        # 非阅读规范（含阅读规范 fallback：无章号论文导读）走原有全量注入路径，行为逐字不变。
        # reading 模式不预取全量：章节层在子线程内按 chapter 取本章，全书层在第二批取各章概要。
        if not reading_mode:
            materials_text = materials_service.materials_context(db, goal.id)

        generation_outline = outline
        # 大纲后、并行章节前执行两个全局阶段；reading 两阶段保持原契约，
        # 其全书层本来就后置整合各章概要，此处不重复注入（见 test_reading_guide_two_phase）。
        if not reading_mode:
            _update_job(
                db, job_id, progress=4,
                stage="生成全局知识梳理与教学蓝图",
                status="running",
            )
            db.commit()
            # 两个全局阶段共用一次独立模型会话；后续章节 worker 仍保持独立 AIService。
            stage_ai = AIService(
                db, goal_id=goal.id, tutorial_id=tutorial.id, job_id=job_id
            )
            synthesis_data, blueprint_data = synthesis_service.prepare(
                goal, outline, teaching_plan, contract, stage_ai,
            )
            generation_outline = synthesis_service.attach_to_outline(
                outline, synthesis_data, blueprint_data
            )
            _update_job(db, job_id, progress=5, stage="全局梳理与蓝图完成")
            db.commit()

        def _chapter_for(idx: int) -> str | None:
            return reading_marks.get(idx) if reading_mode else None

        def _materials_for(idx: int) -> str:
            """第一批该拿什么材料。

            reading 模式：第一批只有章节层，子线程内用 chapter 参数按章重取，这里传空串占位。
            非 reading 模式：全量注入，行为与从前逐字一致。
            """
            if reading_mode:
                return ""
            return materials_text

        _update_job(
            db,
            job_id,
            progress=5,
            stage=(
                f"并发生成 {total} 节（章节层按章注入材料，全书层后置；最多 {MAX_SECTION_WORKERS} 路）"
                if reading_mode else f"并发生成 {total} 节（最多 {MAX_SECTION_WORKERS} 路）"
            ),
            status="running",
        )
        db.commit()

        done = 0
        # 配套文件只依赖大纲，不依赖章节 → 与章节同池并行：
        # 章节先入队占满工作线程，配套任务随后排队接档，消除「全部章节完成后
        # 再串行等 1-2 次模型往返」的尾巴；复用同一个池子，模型峰值并发仍 ≤ 3 路。
        # 第一批：reading 模式只有章节层（全书层留到第二批吃各章概要）；
        # 非 reading 模式是全部节（原有单批行为，first_batch == 全部 outline）。
        first_batch = (
            [(idx, outline[idx]) for idx in phase["chapters"]]
            if reading_mode
            else list(enumerate(generation_outline))
        )
        with ThreadPoolExecutor(
            max_workers=min(MAX_SECTION_WORKERS, max(1, len(first_batch))),
            thread_name_prefix="section",
        ) as pool:
            futures = {
                pool.submit(
                    _generate_section_task,
                    tutorial_id=tutorial.id,
                    goal_id=goal.id,
                    job_id=job_id,
                    index=idx,
                    item={
                        **item,
                        "_teaching_plan": teaching_plan,
                        "_deliverable": contract_items[idx] if idx < len(contract_items) else None,
                    },
                    criteria_dicts=criteria_dicts,
                    # 并发下「前置章节标题」取大纲静态切片，避免依赖完成顺序
                    prior_titles=outline_titles[:idx],
                    materials_text=_materials_for(idx),
                    outline_titles=outline_titles,
                    chapter=_chapter_for(idx),
                    all_chapters=list(reading_marks.values()),
                ): idx
                for idx, item in first_batch
            }
            companion_futures = (
                {}
                if suppress_companions
                else _submit_companion_tasks(
                    pool,
                    tutorial_id=tutorial.id,
                    goal_id=goal.id,
                    job_id=job_id,
                    outline=outline,
                    materials_text=materials_text,
                    want_cheatsheet=True,
                    want_extra=bool(goal.generate_extra_exercises),
                )
            )
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:  # noqa: BLE001  先收齐其余节再统一判定失败
                    failures.append((idx, exc))
                done += 1
                # 每完成一节：按大纲顺序合并 + 短事务提交（中断也不丢已完成内容）
                sections = [results[i]["section"] for i in sorted(results)]
                usage = _merge_section_usage(results)
                draft.prompt_tokens = usage["prompt_tokens"]
                draft.completion_tokens = usage["completion_tokens"]
                draft.total_tokens = usage["total_tokens"]
                draft.usage_source = usage["usage_source"]
                draft.content_json = jdump(
                    {
                        "format_spec": content.get("format_spec") or jload(goal.format_spec_snapshot or "", {}),
                        "teaching_plan": teaching_plan,
                        "outline": outline,
                        "sections": sections,
                        **({"delivery_contract": contract} if contract else {}),
                    }
                )
                job = db.get(GenerationJob, job_id)
                if job is not None:
                    job.progress = min(85, 5 + int(80 * done / total))
                    job.prompt_tokens = usage["prompt_tokens"]
                    job.completion_tokens = usage["completion_tokens"]
                    job.total_tokens = usage["total_tokens"]
                    job.usage_source = usage["usage_source"]
                    if results:
                        last_title = results[max(results)]["section"].get("title", "")
                        job.stage = f"已完成 {len(results)}/{total} 节：{last_title}"[:200]
                db.commit()

        # ---- 阅读教程规范 第二阶段：全书层（认知地图 / 阅读路线 / 思想背景 / 争鸣…）----
        # 全部放最后生成、统一吃各章概要：它们都要知道每章**实际**讲了什么，
        # 与章节层并行只能凭目录名猜，还会互相看不见（pipeline.md §4 的老故障）。
        # 生成顺序与文档顺序解耦：results 按 index 排序合并，全书认知地图仍排在导出最前。
        book_indices = phase["book_level"] if reading_mode else []
        if book_indices and not failures:
            digest_block = _reading_digest_block(outline, results, phase["chapters"])
            _update_job(
                db, job_id, progress=86,
                stage=f"整合各章概要，生成全书层 {len(book_indices)} 节",
            )
            db.commit()
            book_failures: list[tuple[int, Exception]] = []
            with ThreadPoolExecutor(
                max_workers=min(MAX_SECTION_WORKERS, len(book_indices)),
                thread_name_prefix="reading-book",
            ) as book_pool:
                book_futures = {
                    book_pool.submit(
                        _generate_section_task,
                        tutorial_id=tutorial.id,
                        goal_id=goal.id,
                        job_id=job_id,
                        index=idx,
                        item={
                            **outline[idx],
                            "_teaching_plan": teaching_plan,
                            "_deliverable": (
                                contract_items[idx] if idx < len(contract_items) else None
                            ),
                        },
                        criteria_dicts=criteria_dicts,
                        # 全书层能看到所有章节标题（它本来就要整合全书）
                        prior_titles=outline_titles[:idx],
                        # 关键：注入的是各章概要，不是全书原文（40 万字 ≈ 28 万 token 会超窗口）
                        materials_text=digest_block,
                        outline_titles=outline_titles,
                        # 全书层不按章注入：显式写死这两个参数，避免后来者误以为它
                        # 与第一批共用同一套材料契约（chapter 非空会让子线程重新按章取材料）
                        chapter=None,
                        all_chapters=[],
                    ): idx
                    for idx in book_indices
                }
                for future in as_completed(book_futures):
                    idx = book_futures[future]
                    try:
                        results[idx] = future.result()
                    except Exception as exc:  # noqa: BLE001  先收齐其余节再统一判定失败
                        book_failures.append((idx, exc))
                        continue
                    # 逐节落盘：全书层中途失败也不丢已完成的章节层
                    draft.content_json = jdump(
                        {
                            "format_spec": content.get("format_spec")
                            or jload(goal.format_spec_snapshot or "", {}),
                            "teaching_plan": teaching_plan,
                            "outline": outline,
                            "sections": [results[i]["section"] for i in sorted(results)],
                            **({"delivery_contract": contract} if contract else {}),
                        }
                    )
                    db.commit()
            if book_failures:
                failures.extend(book_failures)

        if failures:
            # 章节已失败：取消仍在排队的配套任务（正在跑的等它自然结束），省 token 也省限流额度
            for companion_future in companion_futures:
                companion_future.cancel()
            db.commit()  # 保住已完成草稿，再判定整体失败
            idx, exc = failures[0]
            message = (
                f"第 {idx + 1}/{total} 节生成失败（已完成 {len(results)}/{total} 节，"
                f"已完成内容已保留）：{str(exc)[:160]}"
            )
            if isinstance(exc, AIServiceError):
                raise AIServiceError(message)
            raise RuntimeError(message)

        _update_job(db, job_id, progress=90, stage="质量检查")
        db.commit()
        sections = [results[i]["section"] for i in sorted(results)]
        # 后置全书层的 token 也要计入草稿统计，否则账面少算第二阶段消耗
        usage = _merge_section_usage(results)
        draft.prompt_tokens = usage["prompt_tokens"]
        draft.completion_tokens = usage["completion_tokens"]
        draft.total_tokens = usage["total_tokens"]
        draft.usage_source = usage["usage_source"]
        new_content = {
            "format_spec": content.get("format_spec") or jload(goal.format_spec_snapshot or "", {}),
            "teaching_plan": teaching_plan,
            "outline": outline,
            "sections": sections,
        }
        if contract:
            new_content["delivery_contract"] = contract
        # 结构与交付契约检查先算一版（章节级质量），试卷账目/盲解核验放到配套文件
        # 合并后统一跑一次——额外练习文件与章节并行生成，此处还没进 new_content。
        quality = check_structure(new_content, criteria_dicts)
        quality["issues"] = quality.get("issues", []) + format_specs_service.check_snapshot_delivery(
            content.get("format_spec") or jload(goal.format_spec_snapshot or "", {}),
            new_content,
        )
        draft.quality_report = jdump(quality)
        tutorial.status = "drafted" if quality.get("passed") else "drafted_with_issues"

        # 配套文件已在上面与章节并行生成：这里只收尾等待（通常已完成或接近完成）；
        # 单个失败只留痕，不阻断正文交付
        _update_job(db, job_id, progress=92, stage="等待配套文件完成（知识速查 / 额外练习）")
        db.commit()
        companions = _collect_companion_results(companion_futures, goal_title=goal.title)
        new_content["cheatsheet"] = companions["cheatsheet"]
        if bool(goal.generate_extra_exercises):
            new_content["extra_exercises"] = companions["extra_exercises"]
        # ---- 试卷质量：L0 账目 + L1 盲解核验 + 跨卷重算（统一入口，就地改写 new_content）----
        # 必须在 content_json 落库之前跑：两层都会改写章节 / 额外练习正文（题号、分值、
        # 答案小节名、账目、被仲裁改正的客观题答案），改写结果要进版本与导出。
        # 额外练习此刻已并入 new_content，所以一次调用即可覆盖章节 + 额外练习 + 跨卷。
        _apply_exam_quality(
            db, new_content, quality, goal, tutorial.id, job_id,
            verify_enabled=settings.exam_verify_enabled, version=draft.version,
        )
        draft.quality_report = jdump(quality)
        tutorial.status = "drafted" if quality.get("passed") else "drafted_with_issues"
        if companions["errors"]:
            _update_job(db, job_id, stage="；".join(companions["errors"])[:200])
            db.commit()
        draft.content_json = jdump(new_content)
        tutorial.current_version_id = draft.id

        # 实践任务与「实践」环节已移除：教程内的必要练习即练习载体
        # （配套文件已在上面写入 new_content）
        # 全部章节完成：知识网络提取挪到后台线程，job 不再多等 1 次模型往返才标完成
        # （失败不阻断教程交付；提取内部有指纹去重，重复触发不会重复烧钱）
        _update_job(db, job_id, status="done", progress=100, stage="完成（知识网络后台更新中）")
        db.commit()  # 先提交并结束本事务，后台提取线程才能读到刚写入的最终版本
        _extract_knowledge_async(goal.id, tutorial.id, draft.id)
    except AIServiceError as exc:
        _fail_job(db, job_id, "llm_error", str(exc))
    except Exception as exc:  # noqa: BLE001
        _fail_job(db, job_id, "internal_error", f"{exc.__class__.__name__}: {exc}")
    finally:
        db.close()


def _companions_worker(tutorial_id: str, job_id: str) -> None:
    """后台线程：为已有章节的教程补齐配套文件（独立会话，失败只影响本 job）。"""
    from ..db import SessionLocal
    from ..models import LearningGoal

    db = SessionLocal()
    try:
        tutorial = db.get(Tutorial, tutorial_id)
        if tutorial is None:
            _fail_job(db, job_id, "tutorial_not_found")
            return
        goal = db.get(LearningGoal, tutorial.goal_id)
        if goal is None:
            _fail_job(db, job_id, "goal_not_found")
            return
        _update_job(db, job_id, status="running", progress=15, stage="生成配套文件（知识速查 / 额外练习）")
        db.commit()
        ai = AIService(db, goal_id=goal.id, tutorial_id=tutorial.id, job_id=job_id)
        result = ensure_companions(db, tutorial.id, ai, strict=False)
        errors = result.get("errors") or []
        if not result.get("changed") and errors:
            _fail_job(db, job_id, "llm_error", "；".join(errors))
            return
        _update_job(
            db,
            job_id,
            status="done",
            progress=100,
            stage="配套文件已生成" if not errors else f"配套文件已生成（部分失败：{errors[0][:80]}）",
        )
        db.commit()
    except AIServiceError as exc:
        _fail_job(db, job_id, "llm_error", str(exc))
    except Exception as exc:  # noqa: BLE001
        _fail_job(db, job_id, "internal_error", f"{exc.__class__.__name__}: {exc}")
    finally:
        db.close()
def _reading_section_materials(db: Session, goal_id: str, content: dict, item: dict) -> str:
    """单节重写时该注入什么材料：阅读规范按篇注入，其它规范全量注入。

    与 `_sections_worker` 的按篇注入必须一致，否则「重写某一节」会把整本书塞进 prompt
    （实测 19 个文件 ≈15.4 万 token，直接超窗口），而正常生成时却只注入一篇。
    非阅读规范或节标题认不出篇号时，退回全量注入，行为与从前一致。
    """
    spec = content.get("format_spec") or {}
    if not format_specs_service.is_reading_guide(spec):
        return materials_service.materials_context(db, goal_id)
    outline = content.get("outline") or []
    marks = [
        m for m in (
            materials_service.chapter_marker(str(o.get("title", "") or "")) for o in outline
        ) if m
    ]
    chapter = materials_service.chapter_marker(str(item.get("title", "") or ""))
    if not chapter:
        norm = materials_service._norm_title(str(item.get("title", "") or ""))
        if norm and norm in {materials_service._norm_title(t) for t in _reading_piece_titles(db, goal_id)}:
            chapter = f"piece::{norm}"
    if not chapter:
        # 全书层节：重写时吃各章已生成的概要，而不是重读原文
        results = {
            idx: {"section": sec}
            for idx, sec in enumerate(content.get("sections") or [])
            if isinstance(sec, dict)
        }
        digest = _reading_digest_block(outline, results, [
            i for i in range(len(outline))
            if materials_service.chapter_marker(str(outline[i].get("title", "") or ""))
        ])
        return digest or materials_service.materials_context(
            db, goal_id, global_only=True, global_max_chars=materials_service.READING_GLOBAL_MAX_CHARS
        )
    if chapter.startswith("piece::"):
        return materials_service.materials_context(
            db, goal_id, piece=chapter[len("piece::"):], all_chapters=marks, global_max_chars=materials_service.READING_GLOBAL_MAX_CHARS
        )
    return materials_service.materials_context(
        db, goal_id, chapter=chapter, all_chapters=marks, global_max_chars=materials_service.READING_GLOBAL_MAX_CHARS
    )


def regenerate_section(db: Session, tutorial_id: str, section_id: str, ai: AIService) -> dict:
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    profile = get_profile(goal.domain_key)
    criteria_dicts = goals_service.confirmed_criteria(db, goal.id)
    criteria_by_id = {c["id"]: c for c in criteria_dicts}
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {"outline": [], "sections": []})
    outline = content.get("outline", [])
    sections = content.get("sections", [])
    target_idx = next((i for i, s in enumerate(sections) if s.get("id") == section_id), None)
    if target_idx is None:
        raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "章节不存在"})
    item = outline[target_idx] if target_idx < len(outline) else {"title": sections[target_idx].get("title", ""), "criteria_ids": sections[target_idx].get("mapping_criteria", [])}
    item = {**item, "_teaching_plan": content.get("teaching_plan") or normalize_teaching_plan({})}
    contract_items = (content.get("delivery_contract") or {}).get("items") or []
    if target_idx < len(contract_items):
        # 契约模式下重写章节也要继续按「成品」而不是「讲解章节」生成
        item["_deliverable"] = contract_items[target_idx]
    mapped = [criteria_by_id[cid] for cid in item.get("criteria_ids", []) if cid in criteria_by_id]
    ai.tutorial_id = tutorial.id
    ai.section_id = section_id
    materials_text = _reading_section_materials(db, goal.id, content, item)
    try:
        raw = ai.section(
            goal, profile, item, mapped or criteria_dicts, [o.get("title", "") for o in outline[:target_idx]], materials_text
        )
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc
    usage = dict(ai.usage_last)
    section_data = _with_rule_check(_normalize_section_raw(raw), raw)
    section_data = prune_section_foreign_blocks(
        section_data, [str(o.get("title", "")) for o in outline]
    )
    if format_specs_service.authoritative_snapshot(goal):
        section_data["title"] = item.get("title", "") or section_data.get("title", "")
    section_data.update(
        {
            "id": section_id,
            "title": (
                item.get("title", "")
                if item.get("_deliverable")
                else (section_data["title"] or item.get("title", sections[target_idx].get("title", "")))
            ),
            "mapping_criteria": list(item.get("criteria_ids", [])),
            "token_usage": usage,
        }
    )
    sections[target_idx] = section_data
    new_content = {**content, "outline": outline, "sections": sections}
    # 试卷质量三层统一入口：单节重生成后同样要在落库前跑（重生成可能重新引入账目
    # 错误），且跨卷一致性必须基于**整份文档**重算——只校验被重写的那一节会漏掉它与
    # 其它卷的答案冲突。L1 盲解会对整份文档的所有试卷重新核验（不只重写的那节），
    # 因为改一节答案可能影响跨卷一致性判定。
    quality = check_structure(new_content, criteria_dicts)
    _apply_exam_quality(
        db, new_content, quality, goal, tutorial.id, getattr(ai, "job_id", "") or "",
        verify_enabled=settings.exam_verify_enabled, version=version.version + 1,
    )
    new_version = TutorialVersion(
        tutorial_id=tutorial.id,
        version=version.version + 1,
        content_json=jdump(new_content),
        prompt_version="v1",
        model_provider="demo" if ai.is_demo else "openai-compatible",
        model_name="demo" if ai.is_demo else "configured",
        quality_report=jdump(quality),
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        usage_source=usage.get("usage_source", ""),
    )
    db.add(new_version)
    db.flush()
    tutorial.current_version_id = new_version.id
    db.commit()
    return {"tutorial": tutorial_dict(db, tutorial), "demo": ai.is_demo}


def get_section(db: Session, tutorial_id: str, section_id: str) -> dict:
    """章节详情：单节内容 + 所属教程 / 目标 + 前后导航。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {"outline": [], "sections": []})
    sections = content.get("sections", [])
    index = next((i for i, s in enumerate(sections) if s.get("id") == section_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "章节不存在"})
    section = sections[index]
    return {
        **section,
        "id": section.get("id", section_id),
        "token_usage": section.get("token_usage") or token_usage_dict(),
        "goal_id": goal.id,
        "goal_title": goal.title,
        "tutorial_id": tutorial.id,
        "tutorial_title": tutorial.title,
        "index": index,
        "total": len(sections),
        "version": version.version,
        "prev_section_id": sections[index - 1].get("id") if index > 0 else None,
        "next_section_id": sections[index + 1].get("id") if index + 1 < len(sections) else None,
    }


def restore_version(db: Session, tutorial_id: str, version_number: int) -> dict:
    tutorial = _get_tutorial(db, tutorial_id)
    version = (
        db.query(TutorialVersion)
        .filter(TutorialVersion.tutorial_id == tutorial.id, TutorialVersion.version == version_number)
        .first()
    )
    if version is None:
        raise HTTPException(status_code=404, detail={"code": "version_not_found", "message": "版本不存在"})
    tutorial.current_version_id = version.id
    db.commit()
    return tutorial_dict(db, tutorial)


# 双链与标签的导出归一化：模型可能写出 [[...]]、[[笔记名]] 这类占位链接，
# 也可能在正文里写 #标签。交付到 Vault 前统一处理：
# - 指向本次配套文件的 [[文件名]] 原样保留（这些文件由插件同时写入）；
# - 其余 [[...]] 与行内 #标签 包进行内代码，既保留原文又不会生成断链/真标签；
# - 围栏代码块与已有行内代码不处理，避免破坏命令、代码和语法示例。
WIKILINK_RE = re.compile(r"!?\[\[[^\[\]\n]{0,200}\]\]")
INLINE_TAG_RE = re.compile(r"(?<![\w#])#([A-Za-z0-9_\u4e00-\u9fff][\w\u4e00-\u9fff/-]*)")


def _wikilink_target(token: str) -> str:
    inner = token[3:-2] if token.startswith("![[") else token[2:-2]
    return inner.split("|", 1)[0].split("#", 1)[0].strip()


def normalize_obsidian_syntax(markdown: str, allowed_links: set[str]) -> str:
    """把不该生效的双链 / 标签降级为行内代码，保证导出文件只有指向真实文件的链接。"""
    allowed = {name.strip().removesuffix(".md") for name in allowed_links if name}
    lines: list[str] = []
    fence: str | None = None
    in_math = False
    for line in markdown.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            lines.append(line)
            continue
        if fence is not None:
            lines.append(line)
            continue
        # 数学环境里的 [[...]] 是合法记号（如形式幂级数环 R[[x]]、矩阵 [[a,b],[c,d]]），
        # 不是双链：$$ 与 \[ 围栏、行内 $...$ / \(...\) / \[...\] 一律跳过，
        # 否则反引号会插进公式，把 \(R[[x]]\) 破坏成不可渲染的形态
        if stripped.count("$$") % 2 == 1:
            in_math = not in_math
            lines.append(line)
            continue
        # \[ ... \] 围栏同样是数学环境：里面的 [[x]] 是记号，不是双链。
        # 按「开/闭」净差翻转状态：同一行自闭合时不翻转（否则单行公式之后的内容
        # 会被误判为数学环境）；单独一行只有闭合符 \] 时也必须翻回来，
        # 否则其后所有正文都会跳过双链与标签处理，真断链就漏检了。
        opens = stripped.count("\\[")
        closes = stripped.count("\\]")
        if opens > closes:
            in_math = True
            lines.append(line)
            continue
        if closes > opens:
            in_math = False  # 闭合行上可能还带正文，继续走后面的处理
        if in_math:
            lines.append(line)
            continue

        def fix_links(part: str) -> str:
            def repl(match: re.Match) -> str:
                target = _wikilink_target(match.group(0))
                if not target or target in allowed:
                    return match.group(0)
                return f"`{match.group(0)}`"

            return WIKILINK_RE.sub(repl, part)

        def fix_tags(part: str) -> str:
            if stripped.startswith("#"):
                return part  # 标题行
            return INLINE_TAG_RE.sub(lambda m: f"`{m.group(0)}`", part)

        # 行内代码与四种数学记法（$$…$$ / \[…\] / \(…\) / $…$）都不做双链、标签处理
        pieces = re.split(
            r"(`[^`\n]*`"
            r"|\$\$[^$\n]*\$\$"
            r"|\\\[[^\n]*?\\\]"
            r"|\\\([^\n]*?\\\)"
            r"|\$[^$\n]+\$)",
            line,
        )
        for idx, piece in enumerate(pieces):
            if idx % 2 == 1:
                continue
            pieces[idx] = fix_links(fix_tags(piece))
        lines.append("".join(pieces))
    return "\n".join(lines)


_LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*+]|\d{1,9}[.)])(?:\s|$)")


def _expand_loose_list_spacing(markdown: str) -> str:
    """Obsidian 阅读视图会把列表项之间的空行压掉（松散列表按紧凑渲染），
    网页端的间隔在导出后因此消失。这里在“空行隔开的两个列表项”之间插入一行
    缩进的 ``<br>`` 续行：阅读视图渲染为空行、恢复题目/条目间隔；源码与编辑视图
    中它只是普通续行，不改变列表结构、编号与折叠行为。"""
    lines = markdown.splitlines()
    out: list[str] = []
    fence: str | None = None
    for idx, line in enumerate(lines):
        out.append(line)
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            continue
        if fence is not None:
            continue
        if not _LIST_ITEM_RE.match(line):
            continue
        nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
        after = lines[idx + 2] if idx + 2 < len(lines) else ""
        if nxt.strip() or not _LIST_ITEM_RE.match(after):
            continue
        indent = line[: len(line) - len(stripped)]
        out.append(indent + "   <br>")
    return "\n".join(out)


# 内容块类型的默认标题（模型未给 title 时使用）
_BLOCK_HEADINGS = {
    "text": "讲解",
    "key_point": "关键结论",
    "formula": "公式与推导",
    "steps": "操作步骤",
    "table": "表格",
    "example": "示例",
    "comparison": "对比分析",
    "method_summary": "方法归纳",
    "diagram": "概念关系图",
    "memory": "记忆材料",
    "note": "注意事项",
}

_LEVEL_LABELS = {"L1": "基础理解", "L2": "独立应用", "L3": "深入掌握与迁移"}


def _render_block(block: dict, lines: list[str]) -> None:
    btype = str(block.get("type", "text") or "text")
    title = str(block.get("title", "") or "").strip()
    heading = title or _BLOCK_HEADINGS.get(btype, "讲解")
    body = _strip_meta_segments(str(block.get("body", "") or "")).strip()
    if btype == "key_point":
        lines.append(f"### {heading}")
        lines.append("")
        lines.append(f"> {body}")
        lines.append("")
        return
    if btype == "note":
        lines.append(f"### {heading}")
        lines.append("")
        lines.append(f"> ⚠️ {body}")
        lines.append("")
        return
    lines.append(f"### {heading}")
    lines.append("")
    lines.append(body)
    lines.append("")


def _render_section_v2(s: dict, lines: list[str]) -> None:
    if s.get("purpose"):
        lines.append(f"> {s['purpose']}")
        lines.append("")
    for block in s.get("content", []):
        if isinstance(block, dict) and not _is_meta_section_title(block.get("title", "")):
            _render_block(block, lines)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_GENERIC_BLOCK_TITLES = {"讲解", "正文", "内容", "说明"}


def _dequote_document_body(body: str) -> str:
    """模型偶尔把整份成品包进引用块；成品的标题和正文不应成为 callout。"""
    lines = body.splitlines()
    content_lines = [line for line in lines if line.strip()]
    if not content_lines or not all(line.lstrip().startswith(">") for line in content_lines):
        return body
    dequoted = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("> "):
            dequoted.append(stripped[2:])
        elif stripped == ">":
            dequoted.append("")
        else:
            dequoted.append(line)
    return "\n".join(dequoted)


def _normalize_deliverable_body(body: str, min_level: int = 3) -> str:
    """去掉文档级 H1，并把内部标题层级归一到 min_level 起步、保留相对层次。

    固定「降一级」不够：模型在不同章节会分别用 ##/###/#### 起笔，降级后得到深浅
    不一的题型标题（同一份文档里第 1 章是 ####、第 6 章是 ###）。按本节自己的最小
    标题层级平移到 ###，既避免与交付物标题（##）同层，也让各章题型标题深度一致。
    """
    text = _dequote_document_body(str(body or "")).strip()
    if not text:
        return ""
    # 第一遍：识别代码块与文档级 H1，记录各标题的层级与「是否在代码块内」
    entries: list[tuple[str, int | None]] = []  # (原始行, 标题层级 or None)
    fence: str | None = None
    removed_document_title = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            entries.append((line, None))
            continue
        if fence is not None:
            entries.append((line, None))
            continue
        match = _HEADING_RE.match(line)
        if not match:
            entries.append((line, None))
            continue
        level = len(match.group(1))
        if level == 1 and not removed_document_title:
            removed_document_title = True
            continue
        entries.append((line, level))
    # 平移到 ### 起步：offset 可正可负，最深层级仍受 H6 限制
    heading_levels = [level for _line, level in entries if level]
    offset = (min_level - min(heading_levels)) if heading_levels else 0
    normalized: list[str] = []
    for line, level in entries:
        if level is None or not offset:
            normalized.append(line)
            continue
        new_level = min(6, max(min_level, level + offset))
        match = _HEADING_RE.match(line)
        normalized.append("#" * new_level + " " + (match.group(2) if match else line))
    while normalized and not normalized[0].strip():
        normalized.pop(0)
    while normalized and not normalized[-1].strip():
        normalized.pop()
    return "\n".join(normalized)


def _merge_reading_section_blocks(section: dict) -> dict:
    """阅读教程规范：把被模型拆成多块的节合并回单块（确定性强制「一节一块」）。

    规范要求「一节只输出一个 content 块，块 title 逐字等于节标题」。但模型偶尔会把
    一章拆成多块并自拟块标题（实测第八篇被拆成「深度导读 · 核心概念详解」等 5 块）。
    后果不是排版美观问题，是**标题层级错位**：`_render_deliverable_blocks` 在块标题
    未被正文首行表达时，会给每块多插一层 `### {块标题}` 并把正文压到 `####` 起步，
    于是第八篇的「本章概要/深度导读」比其它 17 篇深了一级。

    修法：拼接所有块的 body、丢弃块 title，合成一个 title=节标题 的块。
    块内的小标题（### 本章概要 / ### 深度导读 / #### …）本来就在 body 里，
    合并后层级自动恢复一致。**只对 reading_guide 调用**：练习规范刻意用多块
    （易错辨析 + 训练），无条件合并会破坏它。
    """
    blocks = [b for b in (section.get("content") or []) if isinstance(b, dict)]
    if len(blocks) <= 1:
        return section
    title = str(section.get("title", "") or "").strip()
    bodies = [str(b.get("body", "") or "").strip() for b in blocks]
    bodies = [b for b in bodies if b]
    if not bodies:
        return section
    merged = {
        **section,
        "content": [{
            "type": "text",
            "title": title,
            "body": "\n\n".join(bodies),
        }],
    }
    return merged


def _render_deliverable_blocks(section: dict, lines: list[str]) -> None:
    """规范交付物专用渲染：不再追加教程通用栏目或重复块标题。"""
    section_title = _norm_ws(section.get("title", ""))
    for block in section.get("content", []):
        if not isinstance(block, dict):
            continue
        body = _normalize_deliverable_body(str(block.get("body", "") or ""))
        # 正文首行若重复块标题 / 章节标题，去掉，避免标题三连
        body_lines = body.splitlines()
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        if body_lines:
            first = _norm_ws(re.sub(r"^#{1,6}\s*", "", body_lines[0]))
            first = _norm_ws(_ORDINAL_PREFIX_RE.sub("", first))
            if first and first in (
                _norm_ws(_ORDINAL_PREFIX_RE.sub("", str(block.get("title", "")))),
                _norm_ws(_ORDINAL_PREFIX_RE.sub("", section_title)),
            ):
                body_lines.pop(0)
                while body_lines and not body_lines[0].strip():
                    body_lines.pop(0)
        body = "\n".join(body_lines)
        block_title = str(block.get("title", "") or "").strip()
        # 块标题与交付物标题同名（含序号差异）时不再重复输出小标题
        same_as_section = _norm_ws(_ORDINAL_PREFIX_RE.sub("", block_title)) == _norm_ws(
            _ORDINAL_PREFIX_RE.sub("", section_title)
        )
        title_wanted = bool(
            block_title and block_title not in _GENERIC_BLOCK_TITLES and not same_as_section
        )
        # 正文已用首行标题表达过块标题（上面刚去重）时不再补一层；
        # 正文的小标题是块标题的下级分组时，块标题必须保留，并把正文降一级嵌套，
        # 否则「参考答案」块里的「### 一、选择题」会与题面的同名标题混为一谈。
        first_body_heading = _norm_ws(
            _ORDINAL_PREFIX_RE.sub(
                "",
                re.sub(r"^#{1,6}\s*", "", next(
                    (ln.strip() for ln in body.splitlines() if _HEADING_RE.match(ln)), ""
                )),
            )
        )
        title_already_expressed = bool(first_body_heading) and first_body_heading == _norm_ws(
            _ORDINAL_PREFIX_RE.sub("", block_title)
        )
        if title_wanted and not title_already_expressed:
            lines.append(f"### {block_title}")
            lines.append("")
            # 块标题占 ###：正文标题从 #### 起步，形成正确层级
            body = _normalize_deliverable_body(body, min_level=4)
        elif title_wanted:
            body = _normalize_deliverable_body(body, min_level=3)
        if body:
            lines.append(body)
            lines.append("")


_ORDINAL_PREFIX_RE = re.compile(r"^[一二三四五六七八九十百零\d]+[、.．]\s*")


def _template_headings(format_spec: dict | None) -> dict[str, str]:
    """规范模板里的**章级**标题（含中文序号）：节标题 → 模板标题行。

    规范的 content_structure 是排版的唯一模板来源（如「## 一、易错辨析」）。
    渲染时若只按交付物名输出「## 易错辨析」，序号就丢了，导出与模板不一致。

    只收 `##` 级：这张表的键要与**节标题**比对，而节标题一律渲染成 `## 中文序号、`。
    收更深层级会让模板里的**内层小标题名**混进键集合 —— 一旦大纲模型把某节命名为
    「本章概要」「难点辨析」这类内层名，就会命中并原样输出成 `### 本章概要`，
    章级 `##` 序号凭空消失、整篇层级错位。阅读教程规范的 content_structure 里有
    27 个内层标题，撞上任何一个都会静默错版。
    """
    result: dict[str, str] = {}
    structure = str((format_spec or {}).get("content_structure", "") or "")
    for line in structure.splitlines():
        match = _HEADING_RE.match(line.strip())
        if not match or len(match.group(1)) != 2:
            continue
        name = _norm_ws(_ORDINAL_PREFIX_RE.sub("", match.group(2)))
        if name and name not in result:
            result[name] = f"## {match.group(2)}"
    return result


def _render_format_spec_document(content: dict, goal, sections: list[dict], lines: list[str]) -> None:
    """按选定规范输出单一文档，不添加教程目录、第 N 节和通用教学栏目。"""
    headings = _template_headings(content.get("format_spec"))
    lines.append(f"# {goal.title}")
    lines.append("")
    # 配套文件双链（教程族规范会生成速查/额外练习；练习/试卷规范抑制配套，此块自然为空）
    cheatsheet = content.get("cheatsheet") or {}
    exercises_file = content.get("extra_exercises") or {}
    companion = []
    if cheatsheet.get("sections"):
        companion.append(f"[[{cheatsheet.get('filename') or _safe_filename(goal.title) + '-知识速查'}]]（知识速查）")
    if exercises_file.get("exercises"):
        companion.append(
            f"[[{exercises_file.get('filename') or _safe_filename(goal.title) + '-额外练习'}]]（额外练习）"
        )
    if companion:
        lines.append("## 配套文件")
        lines.append("")
        for item in companion:
            lines.append(f"- {item}")
        lines.append("")
    for idx, section in enumerate(sections, 1):
        title = str(section.get("title", "") or "").strip()
        if title:
            heading = headings.get(_norm_ws(title))
            if heading is None:
                # 模板没有该章标题（如按材料分章交付）：统一补中文序号，
                # 保证「## 一、…」「## 二、…」全篇同式，不再出现有的章带序号有的不带
                heading = f"## {format_specs_service.cn_numeral(idx)}、{title}"
            lines.append(heading)
            lines.append("")
        _render_deliverable_blocks(section, lines)


def _render_section_v1(s: dict, lines: list[str]) -> None:
    """旧结构（explanation/steps/examples/...）渲染，保持历史版本可导出。"""
    if s.get("goal_statement"):
        lines.append(f"> {s['goal_statement']}")
        lines.append("")
    if s.get("prerequisites"):
        lines.append("**前置要求**")
        lines.append("")
        for p in s["prerequisites"]:
            lines.append(f"- {p}")
        lines.append("")
    for block in s.get("explanation", []):
        lines.append(f"### {block.get('heading', '')}")
        lines.append("")
        lines.append(str(block.get("body", "")))
        lines.append("")
    steps = s.get("steps", [])
    if steps:
        lines.append("### 操作步骤")
        lines.append("")
        for si, st in enumerate(steps, 1):
            lines.append(f"{si}. {st.get('text', '')}")
            if st.get("expected_result"):
                lines.append(f"   - 预期结果：{st['expected_result']}")
            if st.get("verification"):
                lines.append(f"   - 验证方式：{st['verification']}")
        lines.append("")
    if s.get("examples"):
        lines.append("### 示例")
        lines.append("")
        for e in s["examples"]:
            lines.append(f"- {e}")
        lines.append("")
        for e in s["exercises"]:
            lines.append(f"- [ ] {e}")
        lines.append("")
    if s.get("variation_task"):
        lines.append("### 变式任务（检查迁移）")
        lines.append("")
        lines.append(f"- {s['variation_task']}")
        lines.append("")
        for e in s["common_errors"]:
            lines.append(f"- **{e.get('error', '')}** — 原因：{e.get('cause', '')}；排查：{e.get('diagnose', '')}")
        lines.append("")


def _tutorial_base_name(goal) -> str:
    return f"{_safe_filename(goal.title)}-教程"


def _finalize_markdown(markdown: str, allowed_links: set[str]) -> str:
    """导出统一收尾：公式分隔符归一 → Obsidian 双链/标签降级 → 松散列表间距。

    顺序有讲究：先把 \\(…\\)/\\[…\\] 换成 $…$/$$…$$，
    normalize_obsidian_syntax 的数学围栏判定就只需面对一种风格，历史版本里
    混用的分隔符也不会漏网。
    """
    return _expand_loose_list_spacing(
        normalize_obsidian_syntax(normalize_math_delimiters(markdown), allowed_links)
    )


def export_markdown(db: Session, tutorial_id: str) -> tuple[str, str]:
    """导出聚焦学习的 Markdown；内部验收与质量报告不进正文。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {"outline": [], "sections": []})
    cheatsheet = content.get("cheatsheet") or {}
    exercises_file = content.get("extra_exercises") or {}
    format_spec = content.get("format_spec") or format_specs_service.active_snapshot(goal)
    contract = content.get("delivery_contract") or {}
    content = align_section_titles(prune_foreign_section_blocks(content))
    # 阅读规范：导出前合并被拆成多块的节，历史坏数据（如第八篇）重导出也干净
    if format_specs_service.is_reading_guide(format_spec):
        content["sections"] = [
            _merge_reading_section_blocks(sec) if isinstance(sec, dict) else sec
            for sec in (content.get("sections") or [])
        ]

    lines: list[str] = []
    if str((format_spec or {}).get("name", "") or "").strip():
        _render_format_spec_document(content, goal, content.get("sections", []), lines)
        allowed = {_tutorial_base_name(goal)}
        if cheatsheet.get("sections"):
            allowed.add(cheatsheet.get("filename") or f"{_safe_filename(goal.title)}-知识速查")
        if exercises_file.get("exercises"):
            allowed.add(exercises_file.get("filename") or f"{_safe_filename(goal.title)}-额外练习")
        filename = f"{_tutorial_base_name(goal)}.md"
        return filename, _finalize_markdown("\n".join(lines), allowed)

    lines.append(f"# {tutorial.title}")
    lines.append("")

    # 配套文件是学习内容的直接延伸，保留 Obsidian 双链；验收与质量报告另行在 AI Edu 查看。
    companion = []
    if cheatsheet.get("sections"):
        companion.append(f"[[{cheatsheet.get('filename') or _safe_filename(goal.title) + '-知识速查'}]]（知识速查）")
    if exercises_file.get("exercises"):
        companion.append(
            f"[[{exercises_file.get('filename') or _safe_filename(goal.title) + '-额外练习'}]]（额外练习，含参考答案）"
        )
    if companion:
        lines.append("## 配套文件")
        lines.append("")
        for item in companion:
            lines.append(f"- {item}")
        lines.append("")

    outline = content.get("outline", [])
    sections = content.get("sections", [])
    if outline:
        lines.append("## 目录")
        lines.append("")
        for idx, item in enumerate(outline, 1):
            lines.append(f"{idx}. {item.get('title', '')}")
        lines.append("")

    for idx, section in enumerate(sections, 1):
        lines.append(f"## 第 {idx} 节：{section.get('title', '')}")
        lines.append("")
        if section.get("content"):
            _render_section_v2(section, lines)
        else:
            _render_section_v1(section, lines)

    allowed_links = {_tutorial_base_name(goal)}
    if cheatsheet.get("sections"):
        allowed_links.add(cheatsheet.get("filename") or f"{_safe_filename(goal.title)}-知识速查")
    if exercises_file.get("exercises"):
        allowed_links.add(exercises_file.get("filename") or f"{_safe_filename(goal.title)}-额外练习")
    filename = f"{_tutorial_base_name(goal)}.md"
    return filename, _finalize_markdown("\n".join(lines), allowed_links)
def export_cheatsheet(db: Session, tutorial_id: str) -> tuple[str, str]:
    """导出配套知识速查文件。未生成时 404。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {})
    cheatsheet = content.get("cheatsheet") or {}
    sections = cheatsheet.get("sections") or []
    if not sections:
        raise HTTPException(
            status_code=404,
            detail={"code": "cheatsheet_not_found", "message": "该教程没有可导出的知识速查文件"},
        )

    lines: list[str] = []
    lines.append(f"# {cheatsheet.get('title') or f'{goal.title} · 知识速查'}")
    lines.append("")
    lines.append(f"> 配套教程：[[{_tutorial_base_name(goal)}]]")
    lines.append(">")
    lines.append("> 本文件只用于快速查阅，不能替代教程正文讲解；核心概念以教程正文的解释为准。")
    lines.append("")
    for sec in sections:
        lines.append(f"## {sec.get('heading', '')}")
        lines.append("")
        lines.append(str(sec.get("body", "")))
        lines.append("")

    filename = f"{cheatsheet.get('filename') or _safe_filename(goal.title) + '-知识速查'}.md"
    return filename, _finalize_markdown("\n".join(lines), {_tutorial_base_name(goal)})


def export_extra_exercises(db: Session, tutorial_id: str) -> tuple[str, str]:
    """导出独立额外练习文件（练习生成规范排版的 Markdown 成品）。未生成时 404。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {})
    extra = content.get("extra_exercises") or {}
    markdown = str(extra.get("markdown", "") or "").strip()
    if not markdown:
        raise HTTPException(
            status_code=404,
            detail={"code": "exercises_not_found", "message": "该教程没有额外练习文件（可在学习目标中开启后重新生成）"},
        )
    tutorial_name = _tutorial_base_name(goal)
    header = [
        f"> 配套教程：[[{tutorial_name}]]",
        ">",
        "> 本文件按「练习生成规范」排版：一节一章，题号节内连续，答案在本节末尾。",
        "",
    ]
    body_lines = markdown.splitlines()
    if body_lines and body_lines[0].startswith("# "):
        body_lines = body_lines[1:]
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
    lines_out = [f"# {extra.get('title') or f'{goal.title} · 额外练习'}", ""] + header + body_lines
    filename = f"{extra.get('filename') or _safe_filename(goal.title) + '-额外练习'}.md"
    return filename, _finalize_markdown("\n".join(lines_out), {tutorial_name})


def mark_delivery(db: Session, tutorial_id: str, payload) -> dict:
    """插件写入 Vault 成功后回写交付状态；生成状态与交付状态独立。"""
    tutorial = _get_tutorial(db, tutorial_id)
    version = _current_version(db, tutorial)
    tutorial.delivery_status = "delivered" if payload.status == "delivered" else "failed"
    tutorial.delivery_path = str(payload.path or "")
    version_id = payload.version or (version.version if version else 0)
    tutorial.delivery_version = int(version_id or 0)
    db.commit()
    return tutorial_dict(db, tutorial)
