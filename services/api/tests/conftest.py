"""pytest 配置：使用独立测试数据库，并在导入应用前设置环境变量。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

TEST_DB = Path(__file__).resolve().parent / "test_aiedu.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ.pop("LLM_API_KEY", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client():
    from app.db import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.main import app

    with TestClient(app) as c:
        yield c
