"""学习目标材料服务：上传 / 列表 / 删除 / 文本抽取 / prompt 注入上下文。

设计要点：
- 文件本体落在 ``settings.materials_dir/{goal_id}/`` 下（默认 ``data/materials``），
  元数据与抽取正文全文落库（表 ``goal_materials``），因此列表与注入不依赖文件系统扫描；
- 只接受白名单扩展名，大小上限 ``settings.material_max_bytes``（默认 20MB），
  校验在「读入前」和「边写边计数」两处做，超限立即中止并删除半成品文件；
- 文本抽取完全零第三方依赖：txt/md/csv 直接解码，docx 解 zip 读 word/document.xml，
  pdf 用 zlib 解压内容流后粗提取字面量字符串（抽不到时状态标记为 empty，不编造内容）；
  图片只登记来源，不做 OCR（状态 unsupported）；
- 注入 prompt 时：纯文本材料（txt/md/csv）直接逐字读文件原文交给模型
  （上限可配，默认单份 1.2 万字 / 全部 4.8 万字），原文比库内摘录长时回写自愈旧数据；
  其他类型或文件丢失时退回库内摘录。
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
    "empty": "未抽取到正文",
    "unsupported": "仅登记来源",
    "failed": "抽取失败",
    "pending": "待抽取",
}

MAX_EXCERPT_CHARS = settings.material_max_text_chars  # 入库正文上限（默认 20 万字，可配），仅防极端文件
PROMPT_PER_FILE_CHARS = settings.material_prompt_per_file_chars  # 单份材料注入 prompt 的上限（可配）
PROMPT_TOTAL_CHARS = settings.material_prompt_total_chars  # 全部材料注入 prompt 的总上限（可配）
PDF_MAX_PAGES = 500  # PDF 抽取的页数保险丝，防极端大文件拖死请求
CHUNK_SIZE = 1024 * 256


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


def extract_text(path: Path, ext: str) -> tuple[str, str]:
    """返回 (正文, 状态)。状态：ok / empty / unsupported / failed。"""
    if ext in IMAGE_EXTENSIONS:
        return "", "unsupported"
    try:
        if ext in TEXT_EXTENSIONS:
            text = _normalize(_decode_text(path.read_bytes()))
        elif ext == ".docx":
            text = _normalize(_docx_text(path))
        elif ext == ".pdf":
            text = _normalize(_pdf_text(path))
        else:
            return "", "unsupported"
    except OSError:
        return "", "failed"
    if not text:
        return "", "empty"
    return text[:MAX_EXCERPT_CHARS], "ok"


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

    text, extract_status = extract_text(target, ext)
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
    """取材料的注入正文：纯文本文件直接读文件原文交给模型，其余退回库内摘录。

    txt/md/csv 是「文本文件的内容即文件本身」，因此注入时逐字读取文件原文，
    不经过抽取 / 归一化；旧数据入库时正文被截断为 8000 字摘录，原文比摘录长时
    回写自愈。文件丢失或读取失败时退回库内摘录，保证注入不因单份材料中断。
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
    text = text.strip()[:MAX_EXCERPT_CHARS]
    if not text:
        return stored_text
    if len(text) > len(stored_text):
        row.text_excerpt = text
        row.char_count = len(text)
        row.extract_status = "ok"
        try:
            db.commit()
        except Exception:  # noqa: BLE001  回写失败不影响本次注入
            db.rollback()
    return text


def materials_context(
    db: Session,
    goal_id: str,
    *,
    per_file_chars: int = PROMPT_PER_FILE_CHARS,
    total_chars: int = PROMPT_TOTAL_CHARS,
) -> str:
    """把该目标的材料正文注入 prompt（纯文本材料为文件原文，超长截断并标注，上限可配）。"""
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
    for index, row in enumerate(rows, 1):
        label = KIND_LABELS.get(row.kind or "reference", "参考资料")
        head = (
            f"[材料 {index}] {row.filename}（{label}，{_human_size(int(row.size or 0))}，"
            f"正文{'已抽取' if row.extract_status == 'ok' else '未抽取'}）"
        )
        body = _material_body(db, row)
        if body:
            truncated = len(body) > per_file_chars
            snippet = body[:per_file_chars]
            if truncated:
                snippet += "…（摘录已截断）"
        else:
            snippet = "（未抽取到正文，仅以文件名作为来源标注）"
        block = f"{head}\n{snippet}"
        if used + len(block) > total_chars:
            blocks.append(f"（其余 {len(rows) - index + 1} 份材料因长度上限未注入）")
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def materials_source_refs(db: Session, goal_id: str) -> list[str]:
    """材料文件名列表，供教程版本 source_refs 做来源标注。"""
    rows = (
        db.query(GoalMaterial)
        .filter(GoalMaterial.goal_id == goal_id, GoalMaterial.status == "ready")
        .order_by(GoalMaterial.created_at.asc())
        .all()
    )
    return [f"用户上传：{m.filename}" for m in rows if m.filename]
