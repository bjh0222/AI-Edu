r"""从运行中的代码导出架构事实，生成 docs/ARCHITECTURE.generated.md。

手写的架构清单会在几天内过期（2026-10-30 写的解析文档到 11-03 已错 4 项：
路由 86→98、表 21→25、service 模块 12→19）。本脚本让这些事实从代码里取，
而不是靠人记。生成文件带「勿手改」标记，`test_arch_invariants.py` 会在它
过期时失败并提示重新生成。

用法：仓库根 services\api\.venv\Scripts\python.exe scripts\arch_map.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

OUT_PATH = REPO_ROOT / "docs" / "ARCHITECTURE.generated.md"

HEADER = r"""<!-- 由 scripts/arch_map.py 从代码生成，禁止手改。
     更新：仓库根 services\api\.venv\Scripts\python.exe scripts\arch_map.py -->

# 架构事实（自动生成）

"""

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def _route_prefix(path: str) -> str:
    """/api/goals/{id}/materials -> goals；/api/health -> health。"""
    segs = [s for s in path.split("/") if s]
    if segs and segs[0] == "api":
        segs = segs[1:]
    return segs[0] if segs else path


def build_report() -> str:
    """返回完整 Markdown 内容。纯函数：只读代码，不落盘，排序后跨运行稳定。"""
    from app.main import app
    from app.db import Base
    from app import models  # noqa: F401  确保模型注册

    lines = [HEADER]

    # ---- 路由（按资源分组）----
    spec = app.openapi()
    grouped: dict[str, list[tuple[str, str]]] = {}
    for path, ops in sorted(spec["paths"].items()):
        methods = sorted(m.upper() for m in ops if m in HTTP_METHODS)
        grouped.setdefault(_route_prefix(path), []).append((path, methods))
    route_total = sum(len(methods) for entries in grouped.values() for _, methods in entries)

    lines.append(f"## 路由（{route_total} 条 = 路径 × 方法，{len(grouped)} 组资源）\n")
    for prefix in sorted(grouped):
        entries = grouped[prefix]
        lines.append(f"### {prefix}（{len(entries)} 条）\n")
        lines.append("| 方法 | 路径 |")
        lines.append("|---|---|")
        for path, methods in entries:
            lines.append(f"| {'/'.join(methods)} | `{path}` |")
        lines.append("")

    # ---- 数据表 ----
    tables = Base.metadata.sorted_tables
    lines.append(f"## 数据表（{len(tables)} 张）\n")
    lines.append("| 表 | 列 |")
    lines.append("|---|---|")
    for table in tables:
        cols = ", ".join(c.name for c in table.columns)
        lines.append(f"| `{table.name}` | {cols} |")
    lines.append("")

    # ---- 后端模块 ----
    for sub, label in (("api", "路由层"), ("services", "业务层"), ("learning", "学习引擎"), ("llm", "模型调用")):
        mods = sorted(
            p.stem for p in (REPO_ROOT / "services" / "api" / "app" / sub).glob("*.py")
            if p.stem != "__init__"
        )
        lines.append(f"### app/{sub}/ — {label}（{len(mods)} 个）\n")
        lines.append("、".join(f"`{m}`" for m in mods))
        lines.append("")

    # ---- 前端页面 ----
    web_app = REPO_ROOT / "apps" / "web" / "app"
    pages = []
    for p in sorted(web_app.rglob("page.tsx")):
        rel = p.parent.relative_to(web_app).as_posix()
        pages.append("/" if rel == "." else f"/{rel}")
    lines.append(f"## 前端页面（{len(pages)} 个）\n")
    for route in pages:
        lines.append(f"- `{route}`")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(build_report(), encoding="utf-8", newline="\n")
    print(f"written: {OUT_PATH}")


if __name__ == "__main__":
    main()
