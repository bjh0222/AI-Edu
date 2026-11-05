"""架构与跨语言不变量：让「文档过期 / 双端副本分叉」变成测试失败。

背景：2026-10-30 的审计发现 docs/architecture.md 描述的还是已废弃的 10 阶段流程
（代码早已是 5 阶段）；4 天后补写的解析文档也错了 4 项（路由 / 表 / 模块数）。
散文文档一定会过期，过期文档比没有更糟 —— AI 会信任它然后返工。
所以这里把三类「过期后代价高」的知识变成可执行检查：

1. 后端 PHASES ↔ 前端 GOAL_PHASES（跨语言，无测试绑定就会静默分叉）
2. docs/ARCHITECTURE.generated.md 是否与当前代码一致（过期即红，跑一次脚本修复）
3. specs.ts ↔ main.js 规范预览实现（等价副本，靠人肉比对不可持续）

这些测试不测业务逻辑 —— 业务逻辑归各功能测试文件。它们只回答一个问题：
「AI / 人读到的心智模型，是否还和代码一致」。
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# 用应用自己的 REPO_ROOT（services/api/app/config.py），而不是手数 parents——
# 数错一层就会把 services/ 当成仓库根（首轮就犯过）。
from app.config import REPO_ROOT  # noqa: E402  conftest 已把 services/api 加进 sys.path
assert (REPO_ROOT / "AGENTS.md").exists(), f"REPO_ROOT 解析错误：{REPO_ROOT}"


def _read(path: str | Path) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _load_arch_map():
    script = REPO_ROOT / "scripts" / "arch_map.py"
    spec = importlib.util.spec_from_file_location("aiedu_arch_map", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------- 阶段机双端一致

def _frontend_goal_phases(ts: str) -> list[dict[str, str]]:
    """从 goal-phases.ts 的 GOAL_PHASES 数组提取 key/slug（顺序即阶段顺序）。"""
    start = ts.index("export const GOAL_PHASES")
    block = ts[start : ts.index("];", start)]
    keys = re.findall(r'key:\s*"([^"]+)"', block)
    slugs = re.findall(r'slug:\s*"([^"]+)"', block)
    assert len(keys) == len(slugs), f"GOAL_PHASES 的 key 与 slug 数量不一致：{len(keys)} vs {len(slugs)}"
    return [{"key": k, "slug": s} for k, s in zip(keys, slugs)]


def test_frontend_goal_phases_keys_match_backend_phases():
    """前端 GOAL_PHASES 的 key 顺序必须与后端 PHASES 完全一致。

    前端阶段条、子路由 slug、上一步/下一步导航都由 GOAL_PHASES 派生；
    后端阶段推进由 PHASES 决定。两者分叉时，用户会在前端看到后端不认识的阶段。
    """
    from app.learning.engine import PHASES

    phases = _frontend_goal_phases(_read("apps/web/lib/goal-phases.ts"))
    frontend_keys = [p["key"] for p in phases]
    assert frontend_keys == list(PHASES), (
        "前端 GOAL_PHASES 与后端 PHASES 不一致。\n"
        f"  前端: {frontend_keys}\n  后端: {list(PHASES)}\n"
        "两处都要改：services/api/app/learning/engine.py 与 apps/web/lib/goal-phases.ts"
    )


def test_frontend_goal_phase_labels_cover_backend():
    """后端 PHASE_LABELS 的每个 key，前端都要能显示中文。

    前端额外保留的旧阶段名（practice/feedback/...）是刻意的：
    停留在旧阶段的历史数据仍要能正常显示徽章。
    """
    from app.learning.engine import PHASE_LABELS

    ts = _read("apps/web/lib/goal-phases.ts")
    missing = [key for key in PHASE_LABELS if f'"{key}"' not in ts and f"{key}:" not in ts]
    assert not missing, f"前端 goal-phases.ts 缺少后端阶段标签：{missing}"


def test_frontend_goal_phase_slugs_have_route_dirs():
    """GOAL_PHASES 的每个 slug 必须有对应的路由目录（apps/web/app/goals/[id]/<slug>/）。

    phaseHref() 用 slug 拼子路由；slug 与目录名漂移时用户点阶段条会 404。
    """
    phases = _frontend_goal_phases(_read("apps/web/lib/goal-phases.ts"))
    base = REPO_ROOT / "apps" / "web" / "app" / "goals" / "[id]"
    for phase in phases:
        page = base / phase["slug"] / "page.tsx"
        assert page.exists(), (
            f"阶段 {phase['key']} 的 slug「{phase['slug']}」没有对应路由：{page} 不存在。\n"
            "slug 改名时必须同步移动 apps/web/app/goals/[id]/ 下的目录。"
        )
    # 反向：目录里不该有 GOAL_PHASES 之外的阶段子目录（改名残留）
    expected = {p["slug"] for p in phases}
    actual = {d.name for d in base.iterdir() if d.is_dir()}
    stray = actual - expected
    assert not stray, f"apps/web/app/goals/[id]/ 下有 GOAL_PHASES 之外的阶段目录：{sorted(stray)}（改名残留？）"


# ------------------------------------------------------ 架构地图不过期

def test_architecture_map_is_current():
    """docs/ARCHITECTURE.generated.md 必须与当前代码一致。

    该文件由 scripts/arch_map.py 从 openapi + SQLAlchemy metadata + 文件系统生成，
    记录路由 / 数据表 / 模块 / 前端页面。代码变了不重新生成，这里就会失败 ——
    这是让「文档过期」从静默变成显式报警的机制。
    """
    doc = REPO_ROOT / "docs" / "ARCHITECTURE.generated.md"
    assert doc.exists(), (
        "docs/ARCHITECTURE.generated.md 不存在。\n"
        "运行：cd services/api 后 .venv/Scripts/python.exe ../scripts/arch_map.py"
    )
    expected = _load_arch_map().build_report()
    actual = doc.read_text(encoding="utf-8")
    assert actual == expected, (
        "docs/ARCHITECTURE.generated.md 已过期（代码变了，地图没重新生成）。\n"
        "运行：cd services/api 后 .venv/Scripts/python.exe ../scripts/arch_map.py\n"
        + _first_diff_line(actual, expected)
    )


def _first_diff_line(actual: str, expected: str) -> str:
    a, e = actual.splitlines(), expected.splitlines()
    for i, (x, y) in enumerate(zip(a, e), 1):
        if x != y:
            return f"首个差异（行 {i}）：\n  文件: {x[:160]}\n  期望: {y[:160]}"
    longer, which = (a, "文件") if len(a) > len(e) else (e, "期望")
    return f"行数不一致（文件 {len(a)} / 期望 {len(e)}），{which} 多出：{longer[min(len(a), len(e))][:160]}"


# --------------------------------------------- 规范预览双端副本一致

def test_spec_preview_implementations_are_in_sync():
    """specs.ts 与 main.js 的规范预览实现必须逐字等价。

    插件不能 import 前端代码，两份是手工同步的等价副本（skill 有记录）。
    靠人肉比对不可持续，这里交给 scripts/verify_spec_preview_sync.mjs：
    用同一批 fixtures（全字段 / 空字段 / 交付物边界 / scene 分支）跑两份实现，
    逐字比较输出，并核对 SPEC_GROUPS / SPEC_DELIVERABLE_STATUS 数据与分组标签。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用，无法运行跨语言一致性校验")
    script = REPO_ROOT / "scripts" / "verify_spec_preview_sync.mjs"
    assert script.exists(), f"{script} 不存在"
    result = subprocess.run(
        [node, str(script)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, (
        "specs.ts 与 main.js 的规范预览实现已分叉（两份必须逐字等价）：\n"
        f"{result.stdout}\n{result.stderr}"
    )
