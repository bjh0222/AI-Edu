"""pytest 配置：使用独立测试数据库，并在导入应用前设置环境变量。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

TEST_DB = Path(__file__).resolve().parent / "test_aiedu.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
# 上传材料的落盘目录也放到测试目录，避免污染 data/materials
TEST_MATERIALS = Path(__file__).resolve().parent / "test_materials"
os.environ["MATERIALS_DIR"] = TEST_MATERIALS.as_posix()
# 测试必须运行在演示模式：显式置空（环境下已有的同名变量优先于 .env，防止测试意外调用真实模型）
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_MODEL"] = ""

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
