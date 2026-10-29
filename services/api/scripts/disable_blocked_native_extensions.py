r"""禁用被「智能应用控制」拦截的原生扩展（Windows）。

现象
----
Windows 11 的「智能应用控制」（Smart App Control）会拦截没有信誉 / 未签名的本地
编译二进制。本仓库的 venv 里 SQLAlchemy 的 C 扩展就是这类文件，被拦时导入会失败：

    ImportError: DLL load failed while importing _row_cy: 应用程序控制策略已阻止此文件

对应 Win32 错误码 4551（ERROR_APPLICATION_CONTROL_POLICY_VIOLATION）。后端因此起不来
或每个请求 500。

做法
----
SQLAlchemy 的每个 `<mod>_cy.pyd` 旁边都有一份等价的纯 Python 实现 `<mod>_cy.py`。
Python 优先加载 .pyd，所以只要把这些 .pyd 改名停用，导入就会自动回退到纯 Python 实现：
功能不变，只是略慢。

安全性
------
- 只处理「加载失败」且「存在同名 .py 回退实现」的文件，其余一律不碰；
- 只改名、不删除，文件名加 `.disabled-by-smart-app-control` 后缀，随时可以改回来：

    Get-ChildItem -Recurse -Filter *.pyd.disabled-by-smart-app-control | Rename-Item -NewName { $_.Name -replace '\.disabled-by-smart-app-control$','' }

重新安装 / 升级依赖会带回 .pyd，届时重跑本脚本即可。

用法
----
    .\.venv\Scripts\python.exe scripts\disable_blocked_native_extensions.py
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import sysconfig
from pathlib import Path

SUFFIX = ".disabled-by-smart-app-control"
# 应用程序控制策略阻止此文件（智能应用控制 / WDAC 拦截）
BLOCKED_WINERRORS = {4551}


def _loads(path: Path) -> tuple[bool, int | None, str]:
    """在子进程里试加载，返回 (是否成功, winerror, 错误描述)。子进程隔离掉崩溃风险。"""
    code = (
        "import ctypes, sys\n"
        "try:\n"
        "    ctypes.WinDLL(sys.argv[1])\n"
        "except OSError as exc:\n"
        "    print(f'{getattr(exc, \"winerror\", -1)}|{exc.strerror}'); sys.exit(3)\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.SubprocessError as exc:  # noqa: BLE001  探测失败按「无法确认」处理
        return False, None, str(exc)
    if proc.returncode == 0:
        return True, None, ""
    detail = (proc.stdout or proc.stderr or "").strip().splitlines()
    last = detail[-1] if detail else ""
    winerror = None
    if "|" in last:
        head, _, message = last.partition("|")
        try:
            winerror = int(head)
        except ValueError:
            winerror = None
        return False, winerror, message
    return False, None, last


def main() -> int:
    if sys.platform != "win32":
        print("本脚本只处理 Windows 上被应用程序控制拦截的情况，其它平台无需运行。")
        return 0
    purelib = Path(sysconfig.get_paths()["purelib"])
    if not purelib.exists():
        print(f"找不到 site-packages：{purelib}")
        return 1
    print(f"扫描：{purelib}")

    disabled: list[tuple[Path, int | None]] = []
    skipped: list[tuple[Path, str]] = []
    for pyd in sorted(purelib.rglob("*.pyd")):
        twin = pyd.with_suffix(".py")
        if not twin.exists():
            # 没有纯 Python 回退实现，停用会让导入直接报 ModuleNotFoundError
            skipped.append((pyd, "无同名 .py 回退实现"))
            continue
        ok, winerror, message = _loads(pyd)
        if ok:
            continue
        if winerror is not None and winerror not in BLOCKED_WINERRORS:
            skipped.append((pyd, f"加载失败但不是应用程序控制拦截（winerror={winerror}: {message}）"))
            continue
        target = pyd.with_name(pyd.name + SUFFIX)
        pyd.rename(target)
        disabled.append((target, winerror))

    if disabled:
        print(f"\n已停用 {len(disabled)} 个被拦截的原生扩展（导入会自动回退到 .py 实现）：")
        for path, winerror in disabled:
            print(f"  - {path.relative_to(purelib)}")
    else:
        print("\n没有被应用程序控制拦截、且可安全回退的原生扩展。")
    if skipped:
        print(f"\n跳过 {len(skipped)} 个（未改动）：")
        for path, reason in skipped[:10]:
            print(f"  - {path.relative_to(purelib)}：{reason}")
        if len(skipped) > 10:
            print(f"  …… 另外 {len(skipped) - 10} 个")
    print("\n验证：python -c \"import sqlalchemy; print(sqlalchemy.__version__)\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
