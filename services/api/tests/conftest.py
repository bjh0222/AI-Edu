"""pytest 配置：使用独立测试数据库，并在导入应用前设置环境变量。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 并行测试隔离：AIEDU_TEST_SUFFIX 给每个测试进程一套独立的库 / 材料 / 备份 / 模型配置路径。
# 必须可隔离，因为 client fixture 在 setup 时对同一个库做 drop_all + create_all：
# 两个 pytest 进程同时跑时，一方的 drop_all 会把另一方正在用的表删掉，产生
# 「no such table」「database is locked」这类与被测代码无关的假失败。
# 不设置该变量时后缀为空串，路径与从前逐字一致（默认行为不变）。
_SUFFIX = os.environ.get("AIEDU_TEST_SUFFIX", "")

TEST_DB = Path(__file__).resolve().parent / f"test_aiedu{_SUFFIX}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
# 上传材料的落盘目录也放到测试目录，避免污染 data/materials
TEST_MATERIALS = Path(__file__).resolve().parent / f"test_materials{_SUFFIX}"
os.environ["MATERIALS_DIR"] = TEST_MATERIALS.as_posix()
# 删除目标前的 JSON 备份放到测试目录
os.environ["BACKUP_DIR"] = (Path(__file__).resolve().parent / f"test_backups{_SUFFIX}").as_posix()
# 测试必须运行在演示模式：显式置空（环境下已有的同名变量优先于 .env，防止测试意外调用真实模型）
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_MODEL"] = ""
os.environ["MODEL_SETTINGS_FILE"] = str(Path(__file__).parent / f"test_model_settings{_SUFFIX}.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client():
    Path(os.environ["MODEL_SETTINGS_FILE"]).unlink(missing_ok=True)
    from app.db import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.main import app

    with TestClient(app) as c:
        yield c
    Path(os.environ["MODEL_SETTINGS_FILE"]).unlink(missing_ok=True)
