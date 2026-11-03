"""学习目标材料服务：上传 / 列表 / 删除 / 文本抽取 / prompt 注入上下文。

设计要点：
- 文件本体落在 ``settings.materials_dir/{goal_id}/`` 下（默认 ``data/materials``），
  元数据与抽取正文全文落库（表 ``goal_materials``），因此列表与注入不依赖文件系统扫描；
- 只接受白名单扩展名，大小上限 ``settings.material_max_bytes``（默认 20MB），
  校验在「读入前」和「边写边计数」两处做，超限立即中止并删除半成品文件；
- 文本抽取完全零第三方依赖：txt/md/csv 直接解码，docx 解 zip 读 word/document.xml，
  pdf 用 zlib 解压内容流后粗提取字面量字符串（抽不到时状态标记为 empty，不编造内容）；
  图片只登记来源，不做 OCR（状态 unsupported）；
- 注入 prompt 时：纯文本材料（txt/md/csv）直接逐字读文件原文并默认完整注入，
  不经过旧摘要 / 摘录窗口；原文比库内摘录长时回写自愈旧数据。
  PDF/DOCX 使用文本抽取结果，图片仅登记来源。
- prompt 侧仍保留可选字符预算（默认 0 = 不截断）；显式配置上限时，注入块会明确标注
  实际注入字数与总字数，避免模型把不完整材料误认为全文。
"""
from __future__ import annotations

import html
import re
import uuid
import zlib
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..models import GoalMaterial, LearningGoal

# 允许的上传类型（小写扩展名）
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

KIND_LABELS: dict[str, str] = {
    "reference": "参考资料",
    "example_source": "例题来源",
}

EXTRACT_LABELS: dict[str, str] = {
    "ok": "已抽取正文",
    "truncated": "原文超长已截断",
    "empty": "未抽取到正文",
    "unsupported": "仅登记来源",
    "failed": "抽取失败",
    "pending": "待抽取",
}


MAX_EXCERPT_CHARS = settings.material_max_text_chars  # 入库正文上限（默认 0 = 不截断；设正数才启用），仅防极端文件
PROMPT_PER_FILE_CHARS = settings.material_prompt_per_file_chars  # 0 = 单份材料不截断
PROMPT_TOTAL_CHARS = settings.material_prompt_total_chars  # 0 = 全部材料不截断
PDF_MAX_PAGES = 500  # PDF 抽取的页数保险丝，防极端大文件拖死请求
CONTRACT_LISTING_MAX = 64  # 规划阶段篇名清单上限：够列一整卷的篇目，拦住异常材料
# 阅读模式下全书级材料（目录/前言）注入上限：目录全文 3 万字在**每个**阶段都注入，
# 既浪费 token，也更容易触发网关的内容审查（实测《毛选》目录全文被自建网关 502）。
# 前 2000 字足够给出全书骨架 + 篇清单（篇清单另行全量列出），章节正文不受此限。
READING_GLOBAL_MAX_CHARS = 2000
CHUNK_SIZE = 1024 * 256


def _cap_text(text: str) -> tuple[str, bool]:
    """按入库上限截断正文，并显式告知是否截断。

    入库（extract_text）与注入（_material_body）两条路径都必须走它。
    历史上两处各写各的：入库截到 20 万字却仍返回 status='ok'，注入侧反而直接
    path.read_bytes() 读原文全量进 prompt —— 同一份 45 万字材料，库里 20 万字、
    提示词里 45 万字，且前端两处都显示「已抽取正文」，用户完全无法察觉后半本丢了。
    """
    if MAX_EXCERPT_CHARS > 0 and len(text) > MAX_EXCERPT_CHARS:
        return text[:MAX_EXCERPT_CHARS], True
    return text, False


def _materials_root() -> Path:
    return Path(settings.materials_dir)


def _goal_dir(goal_id: str) -> Path:
    return _materials_root() / goal_id


def _goal_or_404(db: Session, goal_id: str) -> LearningGoal:
    goal = db.get(LearningGoal, goal_id)
    if goal is None or goal.archived:
        raise HTTPException(
            status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"}
        )
    return goal


def _material_or_404(db: Session, material_id: str) -> GoalMaterial:
    material = db.get(GoalMaterial, material_id)
    if material is None:
        raise HTTPException(
            status_code=404, detail={"code": "material_not_found", "message": "材料不存在"}
        )
    return material


def _human_size(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"


def safe_display_name(raw: str) -> str:
    name = Path(str(raw or "").replace("\\", "/")).name.strip()
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    return name[:200] or "未命名材料"


def validate_upload(filename: str, size: int, kind: str) -> str:
    """校验类型 / 大小 / 分类，返回规范化扩展名；不合法时抛 400。"""
    if kind and kind not in KIND_LABELS:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_material_kind", "message": f"未知的材料分类：{kind}"},
        )
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = " / ".join(sorted(e.lstrip(".") for e in ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_file_type",
                "message": f"不支持的文件类型「{ext or '无扩展名'}」，仅支持 {allowed}",
            },
        )
    # size 可能未知（流式上传时 Starlette 不给长度），真正的上限在写入时逐块校验
    if size > settings.material_max_bytes:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "file_too_large",
                "message": f"文件过大（{_human_size(size)}），单文件上限 {_human_size(settings.material_max_bytes)}",
            },
        )
    return ext


# ------------------------------------------------------------------ extraction


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _docx_text(path: Path) -> str:
    """docx = zip；读 word/document.xml，把段落 / 制表 / 换行标签转成文本。"""
    import zipfile

    try:
        with zipfile.ZipFile(path) as archive:
            names = [
                n
                for n in archive.namelist()
                if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", n)
            ]
            if not names:
                return ""
            names.sort(key=lambda n: (n != "word/document.xml", n))
            parts: list[str] = []
            for name in names:
                xml = archive.read(name).decode("utf-8", errors="ignore")
                xml = re.sub(r"</w:p\s*>", "\n", xml)
                xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
                xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
                text = re.sub(r"<[^>]+>", "", xml)
                parts.append(html.unescape(text))
            return "\n".join(parts)
    except (zipfile.BadZipFile, OSError, KeyError):
        return ""


def _pdf_literal_text(raw: bytes) -> str:
    """从 PDF 内容流里粗提取 Tj / TJ 字面量（只处理无加密、未压缩为 CJK 字形映射的情形）。"""
    collected: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        payload = match.group(1)
        try:
            payload = zlib.decompress(payload)
        except zlib.error:
            continue
        for chunk in re.finditer(rb"\((?:\\.|[^\\()])*\)", payload):
            literal = chunk.group(0)[1:-1]
            literal = literal.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
            text = literal.decode("latin-1", errors="ignore")
            if text.strip():
                collected.append(text)
    return " ".join(collected)


def _pdf_text(path: Path) -> str:
    try:
        import pypdf  # type: ignore[import-not-found]  # 可选依赖，装了就用
    except ImportError:
        pypdf = None
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages[:PDF_MAX_PAGES]]
            text = _normalize("\n".join(pages))
            if text:
                return text
        except Exception:  # noqa: BLE001  解析失败退回粗提取
            pass
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return _normalize(_pdf_literal_text(raw))


def extract_text(path: Path, ext: str) -> tuple[str, str, int]:
    """返回 (正文, 状态, 原文字数)。状态：ok / empty / unsupported / failed / truncated。

    第三个返回值是**截断前**的原文字数：截断后 len(text) 就等于上限了，
    丢掉原长就无法告诉用户「45 万字只载入了 20 万字」，也无法在提示词里标注缺口。
    """
    if ext in IMAGE_EXTENSIONS:
        return "", "unsupported", 0
    try:
        if ext in TEXT_EXTENSIONS:
            text = _normalize(_decode_text(path.read_bytes()))
        elif ext == ".docx":
            text = _normalize(_docx_text(path))
        elif ext == ".pdf":
            text = _normalize(_pdf_text(path))
        else:
            return "", "unsupported", 0
    except OSError:
        return "", "failed", 0
    if not text:
        return "", "empty", 0
    source_chars = len(text)
    capped, truncated = _cap_text(text)
    return capped, ("truncated" if truncated else "ok"), source_chars


# ------------------------------------------------------------------ CRUD


def material_dict(material: GoalMaterial) -> dict:
    text = material.text_excerpt or ""
    return {
        "id": material.id,
        "goal_id": material.goal_id,
        "kind": material.kind or "reference",
        "filename": material.filename or "",
        "ext": material.ext or "",
        "content_type": material.content_type or "",
        "size": int(material.size or 0),
        "status": material.status or "ready",
        "error_message": material.error_message or "",
        "extract_status": material.extract_status or "pending",
        "char_count": int(material.char_count or 0),
        "source_char_count": int(material.source_char_count or 0),
        "note": material.note or "",
        "created_at": material.created_at,
        "excerpt_preview": text[:160],
    }


def list_materials(db: Session, goal_id: str) -> list[dict]:
    _goal_or_404(db, goal_id)
    rows = (
        db.query(GoalMaterial)
        .filter(GoalMaterial.goal_id == goal_id)
        .order_by(GoalMaterial.created_at.asc())
        .all()
    )
    return [material_dict(m) for m in rows]


def save_upload(
    db: Session, goal_id: str, upload: UploadFile, kind: str = "reference", note: str = ""
) -> dict:
    """保存上传文件 + 元数据；边写边计数，超限立即中止。"""
    goal = _goal_or_404(db, goal_id)
    kind = kind or "reference"
    display_name = safe_display_name(upload.filename or "")
    ext = validate_upload(display_name, int(getattr(upload, "size", 0) or 0), kind)

    material_id = uuid.uuid4().hex
    directory = _goal_dir(goal.id)
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{material_id}{ext}"
    target = directory / stored_name

    size = 0
    try:
        with target.open("wb") as handle:
            while True:
                chunk = upload.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.material_max_bytes:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "code": "file_too_large",
                            "message": (
                                f"文件过大，单文件上限 {_human_size(settings.material_max_bytes)}"
                            ),
                        },
                    )
                handle.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "material_write_failed", "message": f"文件写入失败：{exc}"},
        ) from exc

    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail={"code": "empty_file", "message": "文件为空，无法上传"})

    text, extract_status, source_chars = extract_text(target, ext)
    material = GoalMaterial(
        id=material_id,
        goal_id=goal.id,
        kind=kind,
        filename=display_name,
        stored_name=stored_name,
        ext=ext,
        content_type=upload.content_type or ALLOWED_EXTENSIONS.get(ext, ""),
        size=size,
        status="ready",
        extract_status=extract_status,
        text_excerpt=text,
        char_count=len(text),
        source_char_count=source_chars,
        note=(note or "")[:500],
    )
    db.add(material)
    db.commit()
    return material_dict(material)


def delete_material(db: Session, material_id: str) -> dict:
    material = _material_or_404(db, material_id)
    path = _goal_dir(material.goal_id) / (material.stored_name or "")
    try:
        if material.stored_name:
            path.unlink(missing_ok=True)
    except OSError:
        pass  # 文件删不掉也不阻塞元数据删除
    db.delete(material)
    db.commit()
    return {"ok": True, "id": material_id}


# ------------------------------------------------------------------ prompt 注入


def _material_body(db: Session, row: GoalMaterial) -> str:
    """取材料的注入正文：纯文本文件读原文，其余退回库内抽取文本。

    txt/md/csv 是「文本文件的内容即文件本身」，因此注入时逐字读取文件原文，
    不经过归一化；旧数据入库时正文被截断，原文比库内正文长时回写自愈。
    文件丢失或读取失败时退回库内文本，保证注入不因单份材料中断。
    PDF/DOCX 仍使用上传阶段得到的文本抽取结果。

    **但读取的原文同样要过 _cap_text**：这是历史上「两条路径给出矛盾字数」的根源——
    入库侧截到 MAX_EXCERPT_CHARS，这里却把整本书全量塞进 prompt，既撑爆上下文，
    又让 extract_status 显示 ok。现在两侧共用同一上限，并把原文字数记进
    source_char_count，超限时状态改判为 truncated（前端据此告警）。
    """
    stored_text = (row.text_excerpt or "").strip()
    if not row.stored_name:
        return stored_text
    path = _goal_dir(row.goal_id) / row.stored_name
    if not path.exists():
        return stored_text
    if (row.ext or "") not in TEXT_EXTENSIONS:
        return stored_text  # 非纯文本（图片等）仅作来源标注，不注正文
    try:
        text = _decode_text(path.read_bytes())
    except OSError:
        return stored_text
    text = text.strip()
    if not text:
        return stored_text

    source_len = len(text)
    capped, truncated = _cap_text(text)
    # 回写自愈：库内正文比原文短，或截断状态 / 原文字数与实测不符时更新
    dirty = (
        len(capped) != len(stored_text)
        or capped != stored_text
        or int(row.char_count or 0) != len(capped)
        or int(row.source_char_count or 0) != source_len
        or (row.extract_status or "") != ("truncated" if truncated else "ok")
    )
    if dirty:
        row.text_excerpt = capped
        row.char_count = len(capped)
        row.source_char_count = source_len
        row.extract_status = "truncated" if truncated else "ok"
        try:
            db.commit()
        except Exception:  # noqa: BLE001  回写失败不影响本次注入
            db.rollback()
    return capped


# ------------------------------------------------------------------ 按章切片
#
# 只有「阅读教程规范」（scene == READING_GUIDE_SCENE）会用到这一节：整本书分章上传后，
# 每节只注入自己那一章，而不是把全书塞进每一次调用。其它规范仍走全量注入，行为不变。
#
# 为什么必须切片：materials_context 的结果在 _sections_worker 里被同一个变量传给
# **每一个**并行节任务（tutorials.py 的 materials_text=materials_text）。40 万字的书
# 按 0.70 token/字 换算是 28 万 token/节，单节直接超上下文窗口，不是慢而是调用失败。

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_CHAPTER_MARK_RE = re.compile(r"第\s*([0-9一二三四五六七八九十百]+)\s*[章篇]")

# 全书级材料：任何一节都可能要用（交叉引用、章节定位），不参与按章过滤
GLOBAL_MATERIAL_KEYWORDS = (
    "目录", "前言", "序言", "导言", "绪论", "总览", "全书", "索引",
    "toc", "contents", "introduction", "preface",
)

# 大文件内的章标题：允许 `## 第 1 章 x` 与裸行 `第一章 x`（后者要求整行很短，防误判正文）
_MATERIAL_HEADING_RE = re.compile(
    r"^(?:#{1,4}\s*)?(?:[一二三四五六七八九十百零\d]+\s*[、.．]\s*)?"
    r"(第\s*[0-9一二三四五六七八九十百]+\s*[章篇][^#\n]{0,50}?)\s*$"
)


def _cn_to_int(text: str) -> int | None:
    """中文/阿拉伯数字归一：'1'->1, '一'->1, '十二'->12, '二十三'->23。"""
    text = str(text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    total, num = 0, 0
    for ch in text:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch == "十":
            total += (num or 1) * 10
            num = 0
        elif ch == "百":
            total += (num or 1) * 100
            num = 0
        else:
            return None
    result = total + num
    return result or None


def chapter_marker(text: str) -> str | None:
    """从标题 / 文件名里提取归一化章号：'第一章 导论' -> '1'，无章号 -> None。

    章号必须归一化后再比，否则「第 1 章」（大纲）与「第一章」（文件名）永远匹配不上，
    按章切片会静默退化成「一节材料都拿不到」。
    """
    match = _CHAPTER_MARK_RE.search(str(text or ""))
    if not match:
        return None
    num = _cn_to_int(match.group(1))
    return str(num) if num else None


def heading_lines(text: str) -> list[tuple[int, int, str]]:
    """返回 (行号, 标题级别, 标题文本)；跳过代码块内的 # 行。

    阅读教程规范的「按篇切片」靠它定位篇标题：材料没有「第N章/篇」编号时
    （如《毛选》卷文件 `# 第二卷 → ## 时期 → ### 篇`），章号路径整体失效，
    按章注入会静默退化成每节注入全书（实测 27 万字 ≈ 19 万 token → 502）。
    """
    out: list[tuple[int, int, str]] = []
    fence: str | None = None
    for idx, line in enumerate(str(text or "").splitlines()):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            continue
        if fence is not None:
            continue
        match = re.match(r"^(#{1,6})\s+(.*?)\s*$", stripped)
        if match:
            out.append((idx, len(match.group(1)), match.group(2).strip()))
    return out


def _norm_title(title: str) -> str:
    """篇名归一：去尾注星号与空白，保证大纲标题与正文标题能互相对上。"""
    return re.sub(r"\s+", " ", str(title or "").strip().rstrip("*").strip())


def piece_titles(text: str, min_pieces: int = 2, max_pieces: int = 64) -> list[str]:
    """从单份大材料里提取「篇」级标题（阅读规范按篇分节的结构事实来源）。

    判据（确定性，不靠模型）：取 2..6 级里最浅的、满足
    「本级标题数 >= min_pieces 且 > 上一级标题数 * 2」的层级。
    《毛选》卷文件（1 个卷标题 / 2 个时期 / 30 篇 / 百余小节）会命中「篇」级：
    时期级只有 2 个标题不满足 >= min_pieces，篇级 30 > 2*2 满足。
    普通「# 书 → ## 章x12 → ### 节x60」的书命中章级（12 >= 2 且 12 > 1*2），
    但这类书通常带「第N章」编号，会先走章号路径，轮不到这里。
    找不到时返回 []，调用方退回原有行为（全量注入），绝不静默产出错结构。
    """
    heads = heading_lines(text)
    if not heads:
        return []
    counts: dict[int, int] = {}
    for _idx, level, _title in heads:
        counts[level] = counts.get(level, 0) + 1
    chosen = 0
    for level in range(2, 7):
        if counts.get(level, 0) >= min_pieces and counts.get(level, 0) > counts.get(level - 1, 0) * 2:
            chosen = level
            break
    if not chosen:
        return []
    titles: list[str] = []
    seen: set[str] = set()
    for _idx, level, title in heads:
        if level != chosen:
            continue
        norm = _norm_title(title)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        titles.append(norm)
        if len(titles) >= max_pieces:
            break
    return titles if len(titles) >= min_pieces else []


def slice_by_title(text: str, title: str) -> str | None:
    """切出指定标题对应的整段正文（到下一个同级或更高级标题为止）。

    与 slice_chapter 同思路，但按篇名而不是章号定位：用于阅读规范在
    「材料无章号」时按篇注入。切出的片段自带篇标题行，模型知道自己在读哪一篇。
    """
    target = _norm_title(title)
    if not target or not text:
        return None
    lines = str(text).splitlines()
    heads = heading_lines(text)
    starts = [
        (idx, level, _norm_title(t)) for idx, level, t in heads if _norm_title(t) == target
    ]
    if not starts:
        return None
    begin, level, _ = starts[0]
    end = len(lines)
    for idx, lvl, _t in heads:
        if idx > begin and lvl <= level:
            end = idx
            break
    chunk = "\n".join(lines[begin:end]).strip()
    return chunk or None


def is_global_material(filename: str, body: str = "") -> bool:
    """全书级材料（目录 / 前言 / 索引）：不按章过滤，每节都注入。"""
    name = str(filename or "").lower()
    return any(word.lower() in name for word in GLOBAL_MATERIAL_KEYWORDS)


def chapter_marker_of_any(text: str) -> str | None:
    """文件内部是否存在章结构；有则返回第一个章号，无则 None。

    用于区分两种「文件名没章号」的情况：
    - 整本书存成一个 md（有章结构）-> 应切片或跳过，不该全量注入每节；
    - 单份无章节的讲义 / 论文（无章结构）-> 视为全书级材料，每节都注入。
    只扫前若干行找标题，避免对超大文件做全文遍历。
    """
    fence: str | None = None
    for idx, line in enumerate(str(text or "").splitlines()):
        if idx > 4000:            # 章结构必然出现在文件前部，扫到这就够
            break
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            continue
        if fence is not None:
            continue
        if not stripped.startswith("#") and len(stripped) > 40:
            continue
        match = _MATERIAL_HEADING_RE.match(stripped)
        if not match:
            continue
        mark = chapter_marker(match.group(1))
        if mark:
            return mark
    return None


def slice_chapter(text: str, chapter: str) -> str | None:
    """从含章标题的大文件里切出指定章正文；识别不到章结构时返回 None。

    覆盖「整本书存成一个 md」的用法：用户不必手工拆成 12 个文件。
    切出的片段自带章标题行，模型能知道自己读到的是哪一章。
    """
    target = str(chapter or "").strip()
    if not target or not text:
        return None
    lines = str(text).splitlines()
    starts: list[tuple[int, str]] = []
    fence: str | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        # 代码块里的 # 不是标题
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            continue
        if fence is not None:
            continue
        # 裸行章标题必须够短，避免把正文里的「第三章提到…」误判成标题
        if not stripped.startswith("#") and len(stripped) > 40:
            continue
        match = _MATERIAL_HEADING_RE.match(stripped)
        if not match:
            continue
        mark = chapter_marker(match.group(1))
        if mark:
            starts.append((idx, mark))
    if not starts:
        return None
    for pos, (_, mark) in enumerate(starts):
        if mark != target:
            continue
        begin = starts[pos][0]
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        chunk = "\n".join(lines[begin:end]).strip()
        return chunk or None
    return None



def materials_context(
    db: Session,
    goal_id: str,
    *,
    per_file_chars: int = PROMPT_PER_FILE_CHARS,
    total_chars: int = PROMPT_TOTAL_CHARS,
    chapter: str | None = None,
    all_chapters: list[str] | None = None,
    global_only: bool = False,
    piece: str | None = None,
    global_max_chars: int | None = None,
) -> str:
    """把该目标的材料正文注入 prompt。

    默认 ``per_file_chars=0``、``total_chars=0``：不截断，文本材料以原始全文进入
    prompt。调用方显式传入正数时才执行预算，并在材料块内写明截断状态。

    ``chapter`` 非空时启用**按章注入**（目前只有阅读教程规范使用）：
    - 全书级材料（目录 / 前言 / 索引）始终全文注入；
    - 文件名带章号且与 ``chapter`` 相同的材料全文注入；
    - 文件名无章号但内部有章标题的大文件，切出对应章注入；
    - 属于其它章的材料**不注入正文**，只留一行清单，避免模型以为材料不存在而编造。

    ``piece`` 非空时启用**按篇注入**（阅读规范在材料无「第N章/篇」编号时的路径）：
    全书级材料全文注入；正文里含该篇标题的材料切出该篇注入；不含的材料只留清单行。
    与 ``chapter`` 互斥使用（chapter 优先），语义与按章注入完全同构。

    ``all_chapters`` 用于生成那行清单；不传则不输出清单。
    ``global_only=True`` 时只注入全书级材料（目录 / 前言 / 索引），一份章节正文都不给：
    用于阅读规范的「全书认知地图」与后置全书层——它们需要全书骨架，不需要任何一章的细节。

    不传 ``chapter`` 且不传 ``global_only`` 时行为与从前完全一致（全量注入），
    练习 / 试卷规范不受影响。
    """
    rows = (
        db.query(GoalMaterial)
        .filter(GoalMaterial.goal_id == goal_id, GoalMaterial.status == "ready")
        .order_by(GoalMaterial.created_at.asc())
        .all()
    )
    if not rows:
        return ""

    blocks: list[str] = []
    used = 0
    target_chapter = str(chapter or "").strip()
    # 在循环外归一一次：循环内可能整轮 continue（global_only 跳过），
    # 若把 target_piece 的赋值留在循环里，后面的清单行会 NameError。
    target_piece = _norm_title(piece or "")
    skipped: list[str] = []

    # global_only 兜底：没有任何全书级材料（用户只上传了各章正文）时，
    # 过滤会把材料全部清空，全书层将拿到空上下文 —— 比 token 超标更糟，
    # 是静默产出空壳或纯编造。此时退回全量注入（材料总量本来就不大）。
    if global_only and not any(is_global_material(str(r.filename or "")) for r in rows):
        global_only = False

    for index, row in enumerate(rows, 1):
        label = KIND_LABELS.get(row.kind or "reference", "参考资料")
        body = _material_body(db, row)

        # ---- 只要全书级材料：章节正文一律跳过 ----
        if global_only and body and not is_global_material(row.filename or ""):
            skipped.append(str(row.filename or f"材料{index}"))
            continue

        # ---- 按篇注入：只保留含本篇的材料 + 全书级材料 ----
        if not target_chapter and target_piece and body:
            if not is_global_material(row.filename or ""):
                sliced = slice_by_title(body, target_piece)
                if sliced is not None:
                    body = sliced
                else:
                    skipped.append(str(row.filename or f"材料{index}"))
                    continue

        # ---- 按章注入：只保留本章材料 + 全书级材料 ----
        if target_chapter and body:
            row_marker = chapter_marker(row.filename or "")
            if row_marker is None and not is_global_material(row.filename or ""):
                # 文件名没有章号：可能是「整本书一个文件」，尝试按内部章标题切
                sliced = slice_chapter(body, target_chapter)
                if sliced is not None:
                    body = sliced
                elif chapter_marker_of_any(body) is not None:
                    # 文件里确有章结构、但不含本章 -> 属于别的章，跳过
                    skipped.append(str(row.filename or f"材料{index}"))
                    continue
            elif row_marker is not None and row_marker != target_chapter:
                skipped.append(str(row.filename or f"材料{index}"))
                continue

        if body:
            # 阅读模式的全书级材料限长：骨架 + 篇清单足够定位，正文逐字性由章节层保证。
            # 只在按篇/按章/全书层（即阅读模式的三种取法）下生效，全量路径不受影响。
            if (
                global_max_chars
                and global_max_chars > 0
                and (target_chapter or target_piece or global_only)
                and is_global_material(row.filename or "")
                and len(body) > global_max_chars
            ):
                body = (
                    body[:global_max_chars]
                    + f"\n\n【全书级材料较长，此处仅注入前 {global_max_chars} 字骨架；"
                    "完整篇目见文末清单，正文逐字内容由各篇注入提供】"
                )
            if (row.ext or "") in TEXT_EXTENSIONS:
                source = "原始全文"
            elif (row.ext or "") in {".pdf", ".docx"}:
                source = "文本抽取"
            else:
                source = "已读取正文"
            # 入库即被截断的材料：把「不完整」写进提示词，避免模型把前半本当成全书。
            # source_char_count 为 0 表示旧数据未知，此时只看状态位。
            source_chars = int(row.source_char_count or 0)
            stored_truncated = (
                (row.extract_status or "") == "truncated"
                or (source_chars > 0 and source_chars > len(body))
            )
            if stored_truncated:
                source = f"{source}，已被截断"
            head = (
                f"[材料 {index}] {row.filename}（{label}，{_human_size(int(row.size or 0))}，"
                f"{source}，{len(body)} 字）"
            )
            truncated = bool(per_file_chars and per_file_chars > 0 and len(body) > per_file_chars)
            snippet = body[:per_file_chars] if truncated else body
            if truncated:
                snippet += (
                    f"\n\n【材料内容未完整注入：仅注入前 {per_file_chars} / {len(body)} 字】"
                )
            elif stored_truncated:
                total = source_chars or MAX_EXCERPT_CHARS
                snippet += (
                    f"\n\n【材料原文约 {total:,} 字，超过单份入库上限 "
                    f"{MAX_EXCERPT_CHARS:,} 字，此处仅为前段；后段内容不可见，"
                    f"不得声称已通读全文，也不得为缺失部分编造内容】"
                )
        else:
            head = (
                f"[材料 {index}] {row.filename}（{label}，{_human_size(int(row.size or 0))}，"
                f"正文未抽取）"
            )
            snippet = "（未抽取到正文，仅以文件名作为来源标注）"
        block = f"{head}\n{snippet}"
        if total_chars and total_chars > 0 and used + len(block) > total_chars:
            remaining = total_chars - used
            marker = f"\n\n（其余 {len(rows) - index + 1} 份材料因长度上限未注入）"
            if remaining > len(head) + len(marker) + 100:
                body_limit = remaining - len(head) - len(marker) - 1
                partial = body[:body_limit]
                blocks.append(
                    f"{head}\n{partial}\n\n"
                    f"【材料内容未完整注入：仅注入前 {body_limit} / {len(body)} 字】"
                )
            else:
                blocks.append(marker.strip())
            break
        blocks.append(block)
        used += len(block)

    if (target_chapter or target_piece or global_only) and skipped:
        # 清单是给用户/模型看的：piece:: 前缀是内部切片键，展示时去掉
        _strip = lambda c: str(c)[len("piece::"):] if str(c).startswith("piece::") else str(c)
        others = [_strip(c) for c in (all_chapters or []) if _strip(c).strip() != _strip(target_chapter).strip()]
        scope_desc = (
            f"本节只注入了第 {target_chapter} 章的材料与全书级材料（目录 / 前言等）"
            if target_chapter
            else (
                f"本节只注入了「{target_piece}」一篇的正文与全书级材料（目录 / 前言等）"
                if target_piece
                else "本节只注入了全书级材料（目录 / 前言 / 索引），未注入任何章节正文"
            )
        )
        note = (
            f"\n\n【本次按{'章' if target_chapter else ('篇' if target_piece else '全书级')}注入】{scope_desc}。"
            f"以下材料未注入正文，不要引用或猜测其内容：\n"
            + "\n".join(f"- {name}" for name in skipped)
            + (f"\n全书章节：{', '.join(str(c) for c in others)}（仅供交叉引用时定位，正文不得展开）"
               if others else "")
        )
        blocks.append(note)
    return "\n\n".join(blocks)


def materials_for_planning(db: Session, goal_id: str, snapshot=None) -> str:
    """规划类阶段（价值诊断 / 学习计划 / 大纲）该注入多少材料。

    这些阶段只需要知道「材料是什么、覆盖哪些范围」，不需要逐字读全书；
    而它们都在**章节生成之前**执行，一旦全量注入，整本书会在第一步就把上下文撑爆。
    实测：《毛选》第一卷 19 个文件合计约 22 万字符 ≈ 15.4 万 token，
    diagnose / plan / outline 三步都会在章节层跑起来之前失败。

    阅读教程规范（按篇/章分文件上传）只注入全书级材料（目录 / 前言），
    篇名清单由 `chapter_marker` 从文件名读出，几百字符就够定出全部节标题。
    其它规范行为与从前逐字一致（全量注入）。
    """
    from . import format_specs as format_specs_service

    if format_specs_service.is_reading_guide(snapshot):
        scoped = materials_context(
            db, goal_id, global_only=True, global_max_chars=READING_GLOBAL_MAX_CHARS
        )
        names = [
            re.sub(r"\.[A-Za-z0-9]+$", "", str(row.filename or "")).strip()
            for row in (
                db.query(GoalMaterial)
                .filter(GoalMaterial.goal_id == goal_id, GoalMaterial.status == "ready")
                .order_by(GoalMaterial.created_at.asc())
                .all()
            )
        ]
        chapters = sorted(
            {n for n in names if chapter_marker(n)},
            key=lambda x: (int(chapter_marker(x) or 0), x),
        )
        if not chapters:
            # 文件名无章号（整卷一个大文件）：用正文篇标题做清单，
            # 否则诊断 / 计划阶段完全不知道这卷有哪些篇，只能凭空猜结构。
            from ..models import GoalMaterial as _GM

            for row in (
                db.query(_GM)
                .filter(_GM.goal_id == goal_id, _GM.status == "ready")
                .order_by(_GM.created_at.asc())
                .all()
            ):
                if is_global_material(str(row.filename or "")):
                    continue
                titles = piece_titles(_material_body(db, row))
                if titles:
                    chapters = titles[:CONTRACT_LISTING_MAX]
                    break
        if chapters:
            listing = "\n".join(f"- {name}" for name in chapters)
            scoped = (
                (scoped + "\n\n" if scoped else "")
                + f"【本次上传的分篇材料清单（共 {len(chapters)} 篇，逐篇文件名）】\n"
                + listing
                + "\n\n（以上仅为篇名清单：规划阶段不需要正文，正文会在生成每一篇时按篇注入。）"
            )
        return scoped
    return materials_context(db, goal_id)



def materials_source_refs(db: Session, goal_id: str) -> list[str]:
    """材料文件名列表，供教程版本 source_refs 做来源标注。"""
    rows = (
        db.query(GoalMaterial)
        .filter(GoalMaterial.goal_id == goal_id, GoalMaterial.status == "ready")
        .order_by(GoalMaterial.created_at.asc())
        .all()
    )
    return [f"用户上传：{m.filename}" for m in rows if m.filename]
