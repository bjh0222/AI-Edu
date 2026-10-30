import os, sys, pathlib
root = r"D:\桌面\dsh\ai-edu"
sys.path.insert(0, os.path.join(root,"services","api"))
os.chdir(root)   # 模拟从仓库根启动
from app.config import settings
import app.services.export as ex
print("CWD:", os.getcwd())
print("settings.backup_dir (anchored, correct) :", settings.backup_dir)
print("export._backup_path()  (CWD-relative)   :", ex._backup_path())
print()
print("root data/aiedu.db size  :", os.path.getsize(os.path.join(root,"data","aiedu.db")))
print("root data/backups count  :", len(list(pathlib.Path(root,"data","backups").glob("*.json"))))
print("api  data/backups count  :", len(list(pathlib.Path(root,"services","api","data","backups").glob("*.json"))))
