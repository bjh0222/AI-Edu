"""应用配置：从环境变量 / .env 加载（零第三方依赖）。"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # ai-edu/
BACKEND_ROOT = Path(__file__).resolve().parents[1]  # services/api/


def _resolve_path(value: str) -> str:
    """相对路径一律相对后端目录解析。

    这些路径（数据目录、材料目录、备份目录）以前是相对进程工作目录的：从仓库根启动
    后端就会打开 / 新建另一份空库，表现为每个请求 500「unable to open database file」。
    锚定到后端目录后，从哪里启动都落在同一份数据上。
    """
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((BACKEND_ROOT / path).resolve())


def _resolve_database_url(url: str) -> str:
    """把相对的 SQLite 连接串锚定到后端目录；绝对路径 / 内存库 / URI 形式原样返回。"""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw = url[len(prefix):]
    if raw == ":memory:" or raw.startswith("file:"):
        return url
    return prefix + Path(_resolve_path(raw)).as_posix()


def _load_env_files() -> None:
    for candidate in (REPO_ROOT / ".env", Path(".env")):
        if not candidate.exists():
            continue
        try:
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            continue


class Settings:
    """运行配置。"""

    def __init__(self) -> None:
        _load_env_files()
        self.llm_base_url = os.getenv("LLM_BASE_URL", "").strip()
        self.llm_api_key = os.getenv("LLM_API_KEY", "").strip()
        self.llm_model = os.getenv("LLM_MODEL", "").strip()
        self.llm_timeout = int(os.getenv("LLM_TIMEOUT", "120") or 120)
        # 单次输出上限（max_tokens）：0 表示不发送，沿用提供方默认。章节正文很长时
        # 可能被截断（finish_reason=length），调大此值可减少截断，代价是单次调用更慢。
        self.llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "0") or 0)
        self.database_url = _resolve_database_url(os.getenv("DATABASE_URL", "sqlite:///./data/aiedu.db").strip())
        # 用户上传的参考资料 / 例题来源：文件落在 MATERIALS_DIR，元数据落库
        self.materials_dir = _resolve_path(os.getenv("MATERIALS_DIR", "data/materials").strip() or "data/materials")
        # 删除学习目标前的 JSON 备份目录（不可逆操作的兜底）
        self.backup_dir = _resolve_path(os.getenv("BACKUP_DIR", "data/backups").strip() or "data/backups")
        self.material_max_bytes = int(os.getenv("MATERIAL_MAX_BYTES", str(20 * 1024 * 1024)) or 20 * 1024 * 1024)
        # 材料正文入库上限（字符）：默认 0 = 不截断，原文逐字入库（磁盘与 SQLite 都承受得住
        # 整本书量级；用户明确要求「不要限制注入字数」）。设正数才启用截断保险丝，
        # 截断会显式标记 extract_status='truncated' 并在注入时告知后段不可见。
        self.material_max_text_chars = int(os.getenv("MATERIAL_MAX_TEXT_CHARS", "0") or 0)
        # 注入 prompt 的材料正文上限（字符）：0 表示不额外截断，文本材料按原始全文注入。
        # 这不同于上传时的入库保险丝 material_max_text_chars；只有显式设置正数时才启用
        # prompt 侧预算，并且 materials_context 会在正文中明确标注截断状态。
        self.material_prompt_per_file_chars = int(
            os.getenv("MATERIAL_PROMPT_PER_FILE_CHARS", "0") or 0
        )
        self.material_prompt_total_chars = int(
            os.getenv("MATERIAL_PROMPT_TOTAL_CHARS", "0") or 0
        )
        self.cors_origins = os.getenv(
            "CORS_ORIGINS",
            "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:3001,http://localhost:3001,app://obsidian.md,capacitor://localhost",
        ).strip()
        self.demo_mode = os.getenv("DEMO_MODE", "1").strip() not in ("0", "false", "False")
        # L1 试卷盲解核验开关：对每份卷额外发起 1~2 次模型往返（盲解 + 冲突仲裁），
        # 用于揪出「账目全对但答案算错」的题目（实测最新一份卷 67 题里 21 处实质错误）。
        # 默认开启；关掉可省 token，代价是答案正确性只靠 L0 账目校验、不再复核内容。
        # 演示模式（未配置模型）下自动跳过，与此开关无关。
        self.exam_verify_enabled = os.getenv("AIEDU_EXAM_VERIFY", "1").strip() not in ("0", "false", "False")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_model and (self.llm_api_key or getattr(self, "allow_no_key", False)))

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
