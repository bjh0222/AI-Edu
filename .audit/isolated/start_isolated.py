"""Isolated test backend: own SQLite + own materials/backups + demo mode. Never touches user data."""
import os
BASE = os.path.dirname(os.path.abspath(__file__))
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(BASE, "data", "isolated.db").replace(os.sep, "/")
os.environ["MATERIALS_DIR"] = os.path.join(BASE, "data", "materials")
os.environ["BACKUP_DIR"] = os.path.join(BASE, "data", "backups")
os.environ["MODEL_SETTINGS_FILE"] = os.path.join(BASE, "data", "model-settings.json")
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_MODEL"] = ""
os.environ["DEMO_MODE"] = "1"
import sys
sys.path.insert(0, r"D:\桌面\dsh\ai-edu\services\api")
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port=8199, log_level="warning")
