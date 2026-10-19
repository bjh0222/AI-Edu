"""应用配置：从环境变量 / .env 加载（零第三方依赖）。"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # ai-edu/


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
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./data/aiedu.db").strip()
        self.cors_origins = os.getenv(
            "CORS_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000"
        ).strip()
        self.demo_mode = os.getenv("DEMO_MODE", "1").strip() not in ("0", "false", "False")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
