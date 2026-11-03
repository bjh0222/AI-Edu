# -*- coding: utf-8 -*-
"""Tier-1 工具验证层：用**确定性工具**（sympy / 守恒核算 / 静态检查）判定答案对错。

为什么必须有这一层（调研结论，不是理想设计）：

- **T1：记忆密集型验证必须外包给工具。** 数值与符号计算属于「记忆密集型」推理，
  模型即使被蒸馏过也会稳定算错。本项目实测：5 套微积分卷的账目（L0）几乎全绿，
  67 题客观验算却有 21 处实质错误（y''(0) 算错、比值算错、一道选择题四个选项全错）。
  这类错误只有 sympy 这类外部工具能判，再问模型几次都没用。
- **Nine Judges：同模型多次独立调用的信息增益≈0。** 再开一路盲解、再投票三次，
  拿到的仍是同一个模型的同一个偏差。真正能提高答案置信度的增量信息，
  只能来自模型之外的确定性计算。

所以本模块是 ``exam_check``（L0 账目）与 ``exam_verify``（L1 盲解）之外的
**L1.5 工具验证**：能形式化的交给工具给出 confirmed / refuted，
不能形式化的**明确说 undecidable 并给出回落原因**，绝不假装能判。

三态判定（而不是「对 / 错」二值）是刻意的：

    confirmed    工具算出的结果与卷面答案一致
    refuted      工具算出的结果与卷面答案矛盾——**唯一允许驱动自动改写的信号**
    undecidable  工具无能为力（无法形式化 / 解析失败 / 学科无手段 / 环境缺依赖）

``undecidable`` 必须携带 ``fallback_reason``：调用方据此回落 Tier-2 模型核验与
Tier-3 人工抽检，并能在质量报告里说明「这题为什么没能工具验证」。没有这句原因，
用户看到的只是沉默，而沉默与「验证通过」无法区分。

零假阳性优先于召回：宁可 undecidable，也不能因为**工具自己的局限**去 refuted 一个
本来正确的答案。因此解析不了 → undecidable；本机没装某命令 → undecidable（环境差异
不是答案错误）；表达式无法比较 → undecidable。refuted 只在工具算出了确定反例时出现。

安全边界（本模块会执行模型产出的代码，必须写死，不能靠约定）：

- sympy 断言在**子进程 + 隔离模式(-I) + 超时**里执行：死循环 / 崩溃 / MemoryError
  都只损失那一个子进程，父进程（FastAPI worker）不受影响；
- 进子进程**之前**先做静态黑名单扫描（``open(`` / ``exec(`` / ``eval(`` /
  ``__import__`` / ``os.`` / ``sys.`` / ``subprocess`` 等），命中直接拒绝，根本不启动；
- 计算机学科**只做静态语法检查与命令存在性探测**，绝不执行模型生成的任意代码。

本模块零模型调用、零 DB、零 token，全部函数可单测（见 tests/test_tool_verify.py）。
"""
from __future__ import annotations

import ast
import functools
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

# ------------------------------------------------------------------ 判定常量

VERDICT_CONFIRMED = "confirmed"
VERDICT_REFUTED = "refuted"
VERDICT_UNDECIDABLE = "undecidable"

# capability -> 工具名。写进返回值的 ``tool`` 字段，让质量报告能说明
# 「这条结论是哪个工具给的」——不同工具的可信度与适用面并不相同。
TOOL_BY_CAPABILITY: dict[str, str] = {
    "symbolic": "sympy",
    "symbolic_partial": "stoichiometry_balance",
    "executable": "static_check",
    "none": "none",
}

# 各 capability 需要调用方补充的载荷。提示词侧（prompts.py）据此要求模型输出对应形态，
# 集成侧据此判断「载荷缺失」是模型没给还是本层没接。
PAYLOAD_HINT: dict[str, str] = {
    "symbolic": "需要一段可执行的 sympy 断言代码（见 SYMPY_ASSERTION_CONTRACT）",
    "symbolic_partial": "需要一个化学方程式（本层只验配平与电荷守恒，不做计量计算）",
    "executable": "需要一段代码或一条命令（本层只做静态检查与命令存在性探测）",
    "none": "无形式化验证手段",
}

# 提示词契约：模型侧必须按这两种形态之一输出，否则本层无法判定。
# 放在这里而不是 prompts.py，是为了让「契约」与「执行契约的代码」同处一地：
# 改了执行方式却忘了改提示词，是本类系统最常见的静默失效。
SYMPY_ASSERTION_CONTRACT = """\
把题目与给定答案转写成**一段**可在 sympy 里直接执行的 Python 代码，只输出代码，不要解释。
必须遵守：
1. 自行声明符号：x = symbols('x')（常用单字母符号已预置，可省略）。
2. 二选一给出结论形态：
   A. 赋值式——把题目所求的量算出来赋给 RESULT：
        x = symbols('x')
        RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)
   B. 断言式——把「给定答案是否正确」写成断言：
        assert simplify(limit((cos(x))**(1/sin(x)**2), x, 0) - exp(-Rational(1, 2))) == 0
3. 分数一律用 Rational(1, 2) 或 1/2（会按精确有理数解析），不要用 0.5 之类小数近似。
4. 禁止：import 语句、文件读写、open( / exec( / eval( / __import__ / os. / sys. / subprocess。
5. 若题目无法形式化（证明题、概念题、条件不足），只输出一行：# UNFORMALIZABLE
"""

# 未形式化的约定标记：模型明确说「这题转写不了」时输出它，本层直接 undecidable。
# 有这个显式出口，模型才不会硬编一段跑不通的代码来「交差」。
UNFORMALIZABLE_MARKERS = ("# UNFORMALIZABLE", "#UNFORMALIZABLE", "UNFORMALIZABLE")


@dataclass
class ToolVerdict:
    """一次工具验证的结论。``to_dict()`` 的键集合即本模块对外的返回契约。"""

    verdict: str
    tool: str
    computed: str = ""
    given: str = ""
    evidence: str = ""
    fallback_reason: str = ""
    # 额外字段（非契约必需）：工具算出的**LaTeX 形态**。
    # 为什么需要：自动改写会把 correct_answer 原样写回卷面答案区，若写回
    # sympy 的源码形态（``exp(-1/2)``）就等于把一份 LaTeX 排版的试卷改成了
    # 代码风，交付质量反而下降。有 LaTeX 时优先回填 LaTeX，没有时退回 computed。
    computed_latex: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "verdict": self.verdict,
            "tool": self.tool,
            "computed": self.computed,
            "given": self.given,
            "evidence": self.evidence,
            "fallback_reason": self.fallback_reason,
            "computed_latex": self.computed_latex,
        }


def _verdict(
    verdict: str,
    tool: str,
    *,
    computed: str = "",
    given: str = "",
    evidence: str = "",
    fallback_reason: str = "",
    computed_latex: str = "",
) -> dict[str, str]:
    """构造返回 dict（统一走 ToolVerdict，避免各函数漏键导致上层 KeyError）。"""
    return ToolVerdict(
        verdict=verdict, tool=tool, computed=computed, given=given,
        evidence=evidence, fallback_reason=fallback_reason,
        computed_latex=computed_latex,
    ).to_dict()


def _undecidable(tool: str, reason: str, *, given: str = "") -> dict[str, str]:
    """``undecidable`` 必须带原因，这里做成专用构造器以防漏写。"""
    return _verdict(
        VERDICT_UNDECIDABLE, tool, given=given, fallback_reason=reason[:400],
    )


# ------------------------------------------------------------------ sympy 执行

# 黑名单：命中即拒绝执行。分两类——
# 1) 内建逃逸口：exec/eval/compile/open/input/__import__/globals/locals/vars/breakpoint。
#    其中 open(/eval( 等**前面带点号**时不算命中（``Interval.open(0, 1)`` 是合法的
#    sympy 区间写法，一刀切会把定义域类题目的断言全部误拒）。
# 2) 模块与反射通道：os. / sys. / subprocess / socket / shutil / pathlib / builtins /
#    __class__ / __subclasses__ / __globals__ 等。用 \b 词边界匹配，避免误伤
#    ``acos.``、``cos(x)`` 这类含 "os" 的正常数学写法。
_FORBIDDEN_BARE = (
    "__import__", "__builtins__", "__class__", "__bases__", "__mro__",
    "__subclasses__", "__globals__", "__code__", "__dict__", "__getattr__",
    "breakpoint", "memoryview",
)
_FORBIDDEN_CALL_RE = re.compile(r"(?<!\.)(?<![\w.])(exec|eval|compile|open|input|globals|locals|vars)\s*\(")
_FORBIDDEN_MODULE_RE = re.compile(
    r"\b(os|sys|subprocess|socket|shutil|pathlib|builtins|ctypes|pickle|marshal|"
    r"importlib|threading|multiprocessing|signal|tempfile|io|platform)\b\s*(\.|;|$)"
)
_FORBIDDEN_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(os|sys|subprocess|socket|shutil|pathlib|builtins|ctypes|"
    r"pickle|importlib|threading|multiprocessing|signal|tempfile|io|platform)\b",
    re.M,
)

# 断言代码长度上限：正常一道题的转写不会超过几百字符，超长通常意味着模型把整篇
# 解析贴了进来。设上限既是资源保护，也是「输入形态不对」的早失败信号。
_MAX_ASSERTION_CHARS = 8000


def _sandbox_rejection(code: str) -> str:
    """返回拒绝原因；空串表示通过。

    只做**静态字符串 / 正则**判定，不做 AST 白名单——AST 白名单更严但会把
    ``Function('f')``、``Piecewise`` 等合法 sympy 写法一并拒掉，产生大量
    undecidable（本层的首要 KPI 是「能判多少」，其次才是「多严」）。
    真正的隔离由子进程 + ``-I`` + 超时兜底，黑名单只挡最低级的越权。
    """
    text = str(code or "")
    if len(text) > _MAX_ASSERTION_CHARS:
        return f"断言代码超过 {_MAX_ASSERTION_CHARS} 字符上限"
    for token in _FORBIDDEN_BARE:
        if token in text:
            return f"代码含被禁标识 {token}"
    m = _FORBIDDEN_CALL_RE.search(text)
    if m:
        return f"代码含被禁调用 {m.group(1)}("
    m = _FORBIDDEN_MODULE_RE.search(text)
    if m:
        return f"代码含被禁模块引用 {m.group(1)}"
    m = _FORBIDDEN_IMPORT_RE.search(text)
    if m:
        return f"代码试图 import 被禁模块 {m.group(1)}"
    return ""


@functools.lru_cache(maxsize=1)
def sympy_available() -> bool:
    """sympy 是否可导入（用 find_spec 探测，**不真的 import**）。

    惰性且缓存：本模块被 tutorials / exam_verify 等多处导入，若在模块顶部
    ``import sympy`` 会让所有不需要工具验证的请求也付出 ~0.7s 的导入代价。
    """
    try:
        return importlib.util.find_spec("sympy") is not None
    except (ImportError, ValueError):
        return False


# 子进程执行体。以 ``python -I -X utf8 -c <本源> <target> <given_source>`` 启动，
# 待执行代码走 **stdin**（不走 argv）：Windows 命令行有 ~32k 长度上限，且 argv 传码
# 会把引号 / 换行的转义责任推给调用方；stdin 传码没有这两个问题。
# -I 会忽略 PYTHON* 环境变量（含 PYTHONIOENCODING），所以编码靠 -X utf8 + 显式
# reconfigure 双保险，保证中文错误信息不会在管道里变成 GBK 乱码。
_RUNNER_SRC = r'''
import json
import sys

SENTINEL = "__AIEDU_TOOL_RESULT__"
_PRESET_SYMBOLS = ("x", "y", "z", "t", "n", "m", "k", "a", "b", "c",
                   "p", "q", "r", "s", "u", "v", "w")


def _emit(out):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.stdout.write("\n" + SENTINEL + json.dumps(out, ensure_ascii=False, default=str))
    sys.stdout.flush()


def _blank():
    return {"ok": False, "value": "", "error": "", "latex": "", "float": "",
            "equal": None, "equal_method": "", "given_parsed": "",
            "assertion_failed": False}


def _equal(a, b, ns):
    """三级相等判定：结构相等 -> 差式化简为零 -> 数值一致。

    返回 (True/False/None, 方法说明)。**None 表示无法比较**，调用方必须把它当
    undecidable，绝不能当成「不相等」——那是本层唯一会制造假 refuted 的路径。
    """
    simplify = ns.get("simplify")
    N = ns.get("N")
    try:
        if bool(a == b):
            return True, "结构相等 a == b"
    except Exception:
        pass
    try:
        d = simplify(a - b)
        if d == 0 or getattr(d, "is_zero", None) is True:
            return True, "simplify(a - b) == 0"
        if getattr(d, "is_zero", None) is False and not d.free_symbols:
            return False, "simplify(a - b) = %s != 0" % (d,)
    except Exception:
        pass
    try:
        af = complex(N(a, 25))
        bf = complex(N(b, 25))
        tol = 1e-9 * max(1.0, abs(bf))
        if abs(af - bf) <= tol:
            return True, "数值一致 |a-b| <= %g" % (tol,)
        return False, "数值不一致 a ~= %s, b ~= %s" % (af, bf)
    except Exception:
        pass
    return None, "两式无法比较（含自由符号或类型不可化简）"


def main():
    out = _blank()
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    given_src = sys.argv[2] if len(sys.argv) > 2 else ""
    code = sys.stdin.read()
    ns = {}
    try:
        exec("from sympy import *", ns)
        from sympy.parsing.sympy_parser import (
            convert_xor, parse_expr, standard_transformations)
        ns["parse_expr"] = parse_expr
        ns["_transforms"] = standard_transformations + (convert_xor,)
    except Exception as exc:
        out["error"] = "sympy 导入失败：%s: %s" % (type(exc).__name__, exc)
        _emit(out)
        return
    # 预置常用单字母符号与 e=E：模型经常省略 symbols('x')，若不预置就会得到一堆
    # NameError -> undecidable，白白损失可判定率。e 映射到欧拉数是因为卷面答案里的
    # e 几乎总是自然常数（E 已由 sympy 导出，这里只是补一个小写别名）。
    for _name in _PRESET_SYMBOLS:
        ns.setdefault(_name, ns["symbols"](_name))
    ns.setdefault("e", ns["E"])
    # \lg（常用对数）在本层统一转成 log10(...)，而 sympy 没有 log10 这个名字，
    # 不注入就会变成未定义函数 -> 假 refuted / undecidable。
    ns.setdefault("log10", lambda z: ns["log"](z, 10))
    ns.setdefault("lg", ns["log10"])
    try:
        exec(compile(code, "<aiedu_assertion>", "exec"), ns)
    except AssertionError as exc:
        # 断言不成立：代码本身是跑通的，这是**有效反证**，不是执行失败。
        out["assertion_failed"] = True
        out["error"] = "AssertionError: %s" % (exc,)
        _emit(out)
        return
    except BaseException as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
        _emit(out)
        return
    out["ok"] = True
    if target:
        try:
            val = ns.get(target, None)
            if val is None:
                raise NameError("代码里没有定义 %s" % target)
            out["value"] = str(val)
            try:
                out["latex"] = " ".join(str(ns["latex"](val)).split())
            except Exception:
                pass
            try:
                out["float"] = repr(float(ns["N"](val, 15)))
            except Exception:
                pass
        except Exception as exc:
            out["ok"] = False
            out["error"] = "%s 求值失败：%s: %s" % (target, type(exc).__name__, exc)
            _emit(out)
            return
        if given_src:
            try:
                # local_dict 必须传：parse_expr 默认另起一个只含 sympy 的命名空间，
                # 于是卷面答案里的 ``e`` 会被 auto_symbol 变成**自由符号** e 而非欧拉数 E，
                # 比较必然退化成 undecidable（实测 ``e^{-1/2}`` 就栽在这里）。
                gval = parse_expr(
                    given_src,
                    local_dict={k: v for k, v in ns.items() if not k.startswith("_")},
                    transformations=ns["_transforms"],
                )
            except Exception as exc:
                out["equal_method"] = "卷面答案无法解析为 sympy 表达式：%s: %s" % (
                    type(exc).__name__, exc)
                _emit(out)
                return
            out["given_parsed"] = str(gval)
            eq, method = _equal(val, gval, ns)
            out["equal"] = eq
            out["equal_method"] = method
    _emit(out)


try:
    main()
except BaseException as _exc:  # 兜底：无论如何都要吐出一个可解析的 JSON
    _emit({"ok": False, "value": "", "error": "runner 崩溃：%s: %s" % (
        type(_exc).__name__, _exc), "latex": "", "float": "", "equal": None,
        "equal_method": "", "given_parsed": "", "assertion_failed": False})
'''

# 哨兵行：子进程里用户代码可能自己 print 东西，必须靠哨兵定位真正的结果行。
# 取**最后一条**哨兵行，防止用户代码伪造哨兵来注入结论。
_SENTINEL = "__AIEDU_TOOL_RESULT__"


def _parse_runner_output(stdout: str) -> dict[str, Any] | None:
    """从子进程 stdout 里取出结果 JSON；取不到返回 None（调用方看 stderr）。"""
    lines = [ln for ln in str(stdout or "").splitlines() if _SENTINEL in ln]
    if not lines:
        return None
    payload = lines[-1].split(_SENTINEL, 1)[1].strip()
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def run_sympy_assertion(
    sympy_code: str,
    timeout: float = 5.0,
    *,
    target: str = "",
    given_source: str = "",
) -> dict[str, Any]:
    """在子进程里执行一段 sympy 代码，返回 ``{"ok", "value", "error", ...}``。

    为什么必须子进程而不是 ``exec`` 在本进程：

    - **超时可控**：``integrate`` / ``simplify`` 在病态输入上可能几十秒不返回，
      线程里的 ``exec`` 无法安全中断（Python 没有可靠的线程杀手段），
      而子进程可以直接 kill；
    - **崩溃隔离**：sympy 的递归化简可能 RecursionError / MemoryError，
      在 FastAPI worker 里发生会连带影响同一进程的其它请求；
    - **安全**：配合 ``-I``（隔离模式，不读 PYTHONPATH、不加载用户 site-packages）
      与执行前的黑名单扫描，模型产出的代码拿不到本项目的任何模块与凭据。

    ``target`` / ``given_source`` 是给 :func:`verify_math` 用的可选参数：
    指定 ``target="RESULT"`` 时，子进程会额外取出该变量的值，并与 ``given_source``
    （已归一化成 sympy 源码的卷面答案）做三级相等判定，结果放在 ``equal`` /
    ``equal_method`` 里。放在**同一次**子进程里做，是为了避免「算一遍 RESULT、
    再启一个进程比对」的双倍进程开销（每次 ~0.6s，一卷几十题会很痛）。
    """
    result: dict[str, Any] = {
        "ok": False, "value": "", "error": "", "latex": "", "float": "",
        "equal": None, "equal_method": "", "given_parsed": "",
        "assertion_failed": False, "rejected": "", "timed_out": False,
    }
    code = str(sympy_code or "")
    if not code.strip():
        result["error"] = "sympy 代码为空"
        return result
    rejection = _sandbox_rejection(code)
    if rejection:
        # 安全拒绝不算「执行失败」，单独标记：调用方据此说明是**我们不肯跑**，
        # 而不是模型写错了代码。
        result["rejected"] = rejection
        result["error"] = f"安全拒绝：{rejection}"
        return result
    if not sympy_available():
        result["error"] = "运行环境未安装 sympy，无法做符号验算"
        return result

    cmd = [sys.executable, "-I", "-X", "utf8", "-c", _RUNNER_SRC,
           str(target or ""), str(given_source or "")]
    env = dict(os.environ)
    # 字节码缓存对一次性子进程没有收益，只会往 __pycache__ 里写垃圾。
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(  # noqa: S603  argv 为列表、不经 shell，无注入面
            cmd,
            input=code.encode("utf-8"),
            capture_output=True,
            timeout=max(0.5, float(timeout)),
            env=env,
        )
    except subprocess.TimeoutExpired:
        result["timed_out"] = True
        result["error"] = f"sympy 计算超时（>{max(0.5, float(timeout)):.1f}s），子进程已终止"
        return result
    except (OSError, ValueError) as exc:
        result["error"] = f"无法启动 sympy 子进程：{exc.__class__.__name__}: {exc}"
        return result

    data = _parse_runner_output(proc.stdout.decode("utf-8", "replace"))
    if data is None:
        tail = (proc.stderr.decode("utf-8", "replace") or "").strip().splitlines()[-3:]
        result["error"] = (
            f"子进程未返回结果（退出码 {proc.returncode}）：" + " | ".join(tail)
        )[:400]
        return result
    result.update({k: v for k, v in data.items() if k in result})
    result["ok"] = bool(data.get("ok"))
    return result

# ------------------------------------------------------------------ 数学（symbolic）

# 卷面答案是 LaTeX / 排版混排，sympy 只吃 Python 源码。下面这张替换表是**唯一**的
# 归一化入口：把「模型写出来的答案形态」映射到「parse_expr 能吃」的形态。
# 转换失败不猜——统一 undecidable，绝不因为解析歧义去 refuted 一个可能正确的答案。
_ANSWER_NOISE_RE = re.compile(r"^\$+|\$+$|\\\(|\\\)|\\\[|\\\]|\\displaystyle|\\!|\\,|\\;|\\ ")
_ANSWER_FUNC_MAP = (
    (r"\\operatorname\s*\{?\s*(\w+)\s*\}?", r"\1"),
    (r"\\mathrm\s*\{([^{}]*)\}", r"\1"),
    (r"\\text\s*\{([^{}]*)\}", r"\1"),
    (r"\\d?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"((\1)/(\2))"),
    (r"\\tfrac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"((\1)/(\2))"),
    (r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)"),
    (r"\\sqrt\[([^\]]+)\]\s*\{([^{}]+)\}", r"(\2)**(1/(\1))"),
    (r"\\ln\b", "log"),
    (r"\\lg\b", "log10"),
    # \log_b x（带底数）必须在无底数的 \log 之前处理，否则底数会先被吃掉
    (r"\\log_\{?([A-Za-z0-9]+)\}?\s*\(([^()]+)\)", r"log((\2), (\1))"),
    (r"\\log_\{?([A-Za-z0-9]+)\}?\s+([A-Za-z0-9]+)", r"log((\2), (\1))"),
    (r"\\log\b", "log"),
    # sympy 没有 arctan/arcsin/arccos 这些名字（它叫 atan/asin/acos），
    # 不映射就会变成未定义符号，白白丢一次判定机会。
    (r"\\arcsin\b|\\asin\b", "asin"),
    (r"\\arccos\b|\\acos\b", "acos"),
    (r"\\arctan\b|\\atan\b", "atan"),
    (r"\\operatorname\s*\{\s*(asin|acos|atan|sin|cos|tan|log|exp|arctan)\s*\}", r"\1"),
    # 去反斜杠即可：这些名字 sympy 全都有（sin/cos/tan/sec/csc/cot + arc/双曲）
    (r"\\(?:arc)?(?:sin|cos|tan|sec|csc|cot)h?\b", None),
    (r"\\exp\b", "exp"),
    (r"\\pi\b", "pi"),
    (r"\\infty\b", "oo"),
    (r"\\cdot\b|\\times\b", "*"),
    (r"\\div\b", "/"),
    (r"\\left|\\right", ""),
    (r"\\e\b|\\mathrm\{e\}", "E"),
)


# LaTeX 里函数与参数之间靠**空格**分隔（``\ln 2``、``\sin x``），而 sympy 要 ``log(2)``。
# 必须在去空白之前补括号：一旦把空格删掉，``\ln 2`` 会变成 ``log2``，
# parse_expr 只能把它当成一个名为 ``log2`` 的**自由符号**，与 RESULT 的 ``log(2)``
# 永远比不上（结果是 undecidable，安全但白丢一次判定机会）。
# 只匹配「函数名 + 空白 + 单个 atom / 一个括号组」，绝不做贪婪吞并，
# 因为吞错参数就是假 refuted——宁可漏（→undecidable）不可错。
_LATEX_FUNC_ARG_RE = re.compile(
    r"\\?(arcsin|arccos|arctan|asin|acos|atan|sinh|cosh|tanh|sec|csc|cot|"
    r"sin|cos|tan|ln|lg|log10|log|exp)\s+(\([^()]*\)|[A-Za-z0-9]+)"
)


def _latex_func_args(text: str) -> str:
    r"""``\ln 2`` → ``\ln(2)``；``\sin(2x)`` 原样保留。"""
    # 保留原有的反斜杠前缀（映射表按「有无反斜杠」区分阶段），只补括号
    return _LATEX_FUNC_ARG_RE.sub(
        lambda m: ("\\" if m.group(0).startswith("\\") else "") + m.group(1) + "(" + m.group(2) + ")",
        text,
    )


# 可形式化的函数名闭集（sympy 侧真实存在的名字）。用于「隐式乘号该插在哪」的判定。
_FUNC_NAMES = ("log10", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
               "asin", "acos", "atan", "log", "sin", "cos", "tan", "sec",
               "csc", "cot", "exp", "sqrt")
_FUNC_NAME_RE = re.compile(r"(?:" + "|".join(_FUNC_NAMES) + r")\(")


def _insert_implicit_product(text: str) -> str:
    r"""在「变量 / 数字紧跟已知函数名」处补乘号：``xlog(x)`` -> ``x*log(x)``。

    两道防呆，缺一个就会产生**语法合法但含义全错**的表达式（= 假 refuted）：

    1. 只在这张闭集函数名前插入，绝不做通用的「字母后接字母就补乘号」
       （那会把 ``sin`` 拆成 ``s*in``）；
    2. 插入点的**整个标识符串**必须不是一个完整函数名。否则 ``arctan(1)`` 会在
       ``arc`` 与 ``tan(`` 之间被切成 ``arc*tan(1)``——实测踩到的坑：
       ``tan`` 是 ``arctan`` 的后缀，纯 lookahead 判定无法区分二者。
    """
    out = text
    for m in reversed(list(_FUNC_NAME_RE.finditer(out))):
        pos = m.start()
        if pos == 0 or out[pos - 1] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789)":
            continue
        ident = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", out[:pos])
        if ident and ident.group(0) in _FUNC_NAMES:
            continue          # 前面的字母属于这个函数名本身，不是乘数
        out = out[:pos] + "*" + out[pos:]
    return out


def answer_to_sympy_source(text: str) -> tuple[str, str]:
    r"""把卷面答案文本归一成 sympy 可解析的源码；返回 ``(源码, 失败原因)``。

    源码为空串表示转不了（原因在第二项）。设计要点：

    - ``e^{...}`` / ``x^{...}`` 的 ``^{...}`` 统一转成 ``**(...)``，因为 parse_expr
      里 ``^`` 是异或（虽然 convert_xor 会纠正，但显式转换可读性更好、也避开
      ``e^{1/2}`` 这种嵌套场景）；
    - ``\frac{a}{b}`` 必须加括号转成 ``((a)/(b))``：不加括号会让
      ``\frac{1}{2}x`` 变成 ``1/2x`` → 被隐式乘法解析成 ``1/(2x)``，
      这类「差一个括号」的假 refuted 是最难排查的一种；
    - ``\sqrt``、``\ln`` 等函数名换成 sympy 名（``sqrt``、``log``）；
    - 剩余反斜杠命令一律视为**无法形式化**并返回原因，不做「猜一个最像的」映射。
    """
    raw = str(text or "").strip()
    if not raw:
        return "", "卷面答案为空"
    # 去掉「答：」「= 」这类前缀，只留数学部分
    raw = re.sub(r"^(?:答案|答|解|故|即)\s*[：:]?\s*", "", raw)
    raw = raw.rstrip("。．.;；，,")
    src = _ANSWER_NOISE_RE.sub("", raw.strip())
    src = re.sub(r"^=+\s*", "", src)
    # 先补函数括号（依赖空格），再做后面的去空白
    src = _latex_func_args(src)
    for pattern, repl in _ANSWER_FUNC_MAP:
        if repl is None:
            src = re.sub(pattern, lambda m: m.group(0).lstrip("\\"), src)
        else:
            src = re.sub(pattern, repl, src)
    # 反斜杠命令映射之后**再补一遍**函数括号：``\operatorname{arctan} 1`` 会先被
    # 映射成 ``\arctan 1``，而第一遍补括号跑在映射之前，漏了它就会得到 ``arctan1``
    # （一个未定义符号，等于白丢一次判定）。
    src = _latex_func_args(src)
    # sympy 侧不存在 arctan / arcsin / arccos（叫 atan / asin / acos），
    # 不归一就会得到一个未定义函数，与 RESULT 永远比不上。
    src = re.sub(r"\b(arcsin|arccos|arctan|arccot|arcsec|arccsc)\b",
                 lambda m: "a" + m.group(1)[3:], src)
    # 中文括号 / 全角字符
    src = (src.replace("（", "(").replace("）", ")")
              .replace("［", "[").replace("］", "]")
              .replace("×", "*").replace("÷", "/").replace("−", "-")
              .replace("π", "pi").replace("∞", "oo").replace("≈", "="))
    src = _insert_implicit_product(src)
    src = re.sub(r"\^\{([^{}]+)\}", r"**(\1)", src)
    src = re.sub(r"\^(\w)", r"**(\1)", src)
    # 隐式乘法：LaTeX 里 ``2\sqrt{3}``、``3x``、``2(x+1)`` 都省略乘号，
    # 转成源码后必须补上，否则 parse_expr 直接 SyntaxError（实测踩过）。
    # 只在这四种边界补，绝不碰「字母后跟字母」（那会把 sin 拆成 si*n）。
    # 数字串整体前移乘号：``2sqrt(3)`` -> ``2*sqrt(3)``、``2x`` -> ``2*x``。
    # 必须整串匹配且**前面不是字母/数字**，否则 ``log10(100)`` 会被拆成
    # ``log10*(100)`` = 1000 —— 一个语法合法但含义全错的表达式，会直接导致
    # 假 refuted。这是「隐式乘法补全」唯一安全的形态。
    src = re.sub(r"(?<![A-Za-z0-9])(\d+)(?=[A-Za-z(])", r"\1*", src)
    src = re.sub(r"(\))(?=[A-Za-z0-9(])", r"\1*", src)
    src = re.sub(r"_\{[^{}]*\}", "", src)     # 下标是记号不是运算：x_1 -> x
    src = re.sub(r"_(\w)", "", src)
    src = re.sub(r"\s+", "", src)
    if not src:
        return "", f"卷面答案「{raw[:40]}」去排版后为空"
    # 还留着反斜杠命令说明有没覆盖到的 LaTeX 结构，宁可 undecidable 也不猜
    leftover = re.search(r"\\[A-Za-z]+", src)
    if leftover:
        return "", f"卷面答案含未支持的 LaTeX 命令 {leftover.group(0)}"
    if not re.search(r"[\w\d(]", src):
        return "", f"卷面答案「{raw[:40]}」不是可计算的数学表达式"
    # 含中日韩文字 => 这是**文字答案**（判断题「正确」、简答题「因为…」），不是
    # 可计算的数学表达式。必须显式拒绝：parse_expr 会把「正确」当成一个自由符号，
    # 与 RESULT 比不上，于是得到一个**假 refuted**——而 refuted 会驱动自动改写。
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", src):
        return "", f"卷面答案是文字表述（{raw[:24]}），不是可计算的数学表达式"
    # 单个大写字母 A-D 是**选择题的选项字母**，不是数学量。它应由 exam_check 的
    # 选择题路径（answer_content 把字母解析成选项内容）处理，本层比对字母没有意义。
    if re.fullmatch(r"[A-D]", src):
        return "", f"卷面答案是选项字母 {src}，应先解析成选项内容再做符号验算"
    return src, ""


def _detect_assertion_mode(code: str) -> tuple[str, str]:
    """判断模型给的断言代码属于哪种形态；返回 ``(mode, target)``。

    ``result`` = 代码把所求量赋给 RESULT，由本层与卷面答案比对（**推荐**，
    因为它把「算」与「比」分开，比对逻辑在我们手里，模型没有机会把答案抄进断言里
    从而自证成功）；
    ``assert`` = 代码自带 assert，断言通过即 confirmed；
    ``none``   = 两者都没有，无法判定。
    """
    text = str(code or "")
    m = re.search(r"^\s*(RESULT|result)\s*(?::[^=]+)?=(?!=)", text, re.M)
    if m:
        return "result", m.group(1)
    if re.search(r"^\s*assert\b", text, re.M):
        return "assert", ""
    return "none", ""


def verify_math(
    question_text: str,
    given_answer: str,
    sympy_assertion_code: str,
    *,
    timeout: float = 5.0,
) -> dict[str, str]:
    """用 sympy 核验一道数学题的给定答案。

    ``sympy_assertion_code`` 是**模型把题目转写成的可执行代码**（契约见
    ``SYMPY_ASSERTION_CONTRACT``）。本函数只负责执行与判定，不调模型：
    转写这一步必须发生在模型层（exam_verify），因为只有模型能把自然语言题面
    翻成符号表达式；但**判定必须由代码做**，因为只有代码的结论是确定的。

    三态映射（零假阳性优先）：

    - ``result`` 形态：RESULT 与卷面答案相等 → confirmed；确定不等 → refuted；
      无法比较（含自由符号 / 化简失败）→ undecidable。
    - ``assert`` 形态：断言通过 → confirmed；抛 AssertionError → refuted；
      其它异常（语法错、NameError）→ undecidable（那是转写失败，不是答案错）。
    - 代码执行报错、超时、被安全策略拒绝、sympy 未安装 → undecidable + 原因。
    """
    tool = TOOL_BY_CAPABILITY["symbolic"]
    given = str(given_answer or "").strip()
    code = str(sympy_assertion_code or "").strip()
    if not code:
        return _undecidable(tool, f"未提供 sympy 断言代码；{PAYLOAD_HINT['symbolic']}", given=given)
    if any(mark in code for mark in UNFORMALIZABLE_MARKERS):
        return _undecidable(
            tool, "模型判定本题无法形式化（证明题 / 概念题 / 条件不足），回落模型核验+人工",
            given=given,
        )
    if not sympy_available():
        return _undecidable(tool, "运行环境未安装 sympy，回落模型核验+人工", given=given)

    mode, target = _detect_assertion_mode(code)
    if mode == "none":
        return _undecidable(
            tool,
            "断言代码既未定义 RESULT 也不含 assert，无法确定要比对什么；"
            + PAYLOAD_HINT["symbolic"],
            given=given,
        )

    given_source, why = ("", "")
    if mode == "result":
        if not given:
            return _undecidable(tool, "缺少卷面答案，无法与 sympy 计算结果比对", given=given)
        given_source, why = answer_to_sympy_source(given)
        if not given_source:
            # 卷面答案转不成表达式：这是**答案形态**问题，不是答案对错问题
            return _undecidable(tool, f"卷面答案无法转成 sympy 表达式：{why}", given=given)

    run = run_sympy_assertion(code, timeout, target=target, given_source=given_source)
    if run.get("rejected"):
        return _undecidable(tool, f"断言代码被安全策略拒绝（{run['rejected']}），不执行", given=given)
    if run.get("timed_out"):
        return _undecidable(tool, run.get("error", "计算超时"), given=given)

    error = str(run.get("error") or "").strip()
    if mode == "assert":
        if run.get("assertion_failed"):
            return _verdict(
                VERDICT_REFUTED, tool, computed=error.replace("AssertionError:", "").strip(),
                given=given,
                evidence=f"模型转写的 sympy 断言未通过：{error[:200]}",
            )
        if not run.get("ok"):
            return _undecidable(tool, f"断言代码执行失败（{error[:200]}），属转写问题而非答案错误", given=given)
        return _verdict(
            VERDICT_CONFIRMED, tool, computed=str(run.get("value") or ""), given=given,
            evidence="sympy 断言通过（assert 未抛异常）",
        )

    # result 形态
    if not run.get("ok"):
        return _undecidable(tool, f"sympy 求值失败（{error[:200]}），属转写问题而非答案错误", given=given)
    computed = str(run.get("value") or "")
    detail = [f"RESULT = {computed}"]
    if run.get("latex"):
        detail.append(f"LaTeX {run['latex']}")
    if run.get("float"):
        detail.append(f"数值 {run['float']}")
    equal = run.get("equal")
    method = str(run.get("equal_method") or "")
    if equal is None and error and not method:
        method = error[:160]
    detail.append(f"卷面答案 {given_source} 解析为 {run.get('given_parsed') or given}")
    # sympy 的 latex() 会在负号与 \frac 之间插空格（``e^{- \frac{1}{2}}``），
    # 而本项目卷面一律写紧凑形式（``e^{-\frac{1}{2}}``）。两者渲染等价，但
    # 自动改写后若风格不一致，会让同一份卷里出现两种排版，观感上是「改脏了」。
    latex = re.sub(r"\s+", "", str(run.get("latex") or "")).replace(" ", "")
    if equal is True:
        return _verdict(
            VERDICT_CONFIRMED, tool, computed=computed, given=given,
            evidence="；".join(detail) + f"；{method}",
            computed_latex=latex,
        )
    if equal is False:
        return _verdict(
            VERDICT_REFUTED, tool, computed=computed, given=given,
            evidence="；".join(detail) + f"；{method}",
            computed_latex=latex,
        )
    return _undecidable(
        tool, f"sympy 无法判定两式是否相等（{method or '比较失败'}）；{error[:120]}",
        given=given,
    )


# ------------------------------------------------------------------ 化学（symbolic_partial）

# 元素符号表：解析化学式时**只认这张表里的符号**。
# 为什么必须白名单：没有它，「Co」（钴）与「CO」（一氧化碳）无法区分，
# 「No」（锘）会被当成「N + o」，把配平判定变成猜谜。白名单让解析确定，
# 也让「出现表外记号」成为 undecidable 的明确信号（通常是 LaTeX 噪音或有机结构式）。
_ELEMENTS = frozenset("""
H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn
Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La
Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po
At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg
Cn Nh Fl Mc Lv Ts Og D T
""".split())

# 箭头：覆盖 LaTeX（\\to / \\longrightarrow / \\xrightarrow）、Unicode、ASCII 与可逆号
_ARROW_RE = re.compile(
    r"\\xrightleftharpoons(?:\[[^\]]*\])?\{[^{}]*\}"
    r"|\\xrightarrow(?:\[[^\]]*\])?\{[^{}]*\}"
    r"|\\rightleftharpoons|\\longrightarrow|\\rightarrow|\\longleftarrow|\\to\b"
    r"|<=>+|<-+>|<--+>|=+>|-+>|⟶|→|⇌|↔|⇄|="
)
# 物态标注：(aq)/(s)/(g)/(l) 及其中文/带空格变体
_STATE_RE = re.compile(
    r"[（(]\s*(?:aq|aqueous|s|solid|l|liq|liquid|g|gas|水溶液|固|液|气|浓|稀)\s*[)）]",
    re.I,
)
# 反应条件（写在箭头上方）：\Delta、加热、催化剂等，出现在箭头条目里直接丢弃
# 反应条件：**只收不可能是化学式的 token**（中文词 / 希腊字母）。
# 曾经把 ``MnO2``、``浓硫酸`` 也列进来，结果 ``2KMnO4 -> K2MnO4 + MnO2 + O2`` 里
# 作为**产物**的 MnO2 被当条件删掉，一个正确方程式被判成不守恒。字符串层面无法区分
# 「催化剂 MnO2」与「产物 MnO2」，所以一律不剥：宁可 undecidable（写条件在箭头上方
# 的 LaTeX 形式 \\xrightarrow{MnO2} 已由 _ARROW_RE 吃掉），也不制造假 refuted。
_CONDITION_RE = re.compile(r"\\Delta|Δ|△|加热|点燃|高温|高压|催化剂|通电|光照|一定条件")


# Unicode 上下标 → ASCII。必须在**解析入口**就做，不能等到 _clean_species_text：
# ``+`` 分隔判据依赖「前一项以字母/数字结尾」这条字符类规则，而 ``₂`` 不在
# [A-Za-z0-9] 里，于是 ``2H₂ + O₂`` 的 ``+`` 会被误认成电荷符号，整侧解析失败
# （实测踩过：Unicode 下标的方程式全部落到 undecidable）。
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def _normalize_equation_text(text: str) -> str:
    r"""方程式的**入口级**归一：Unicode 上下标 → ASCII、剥 $ 与 LaTeX 间距命令。

    刻意**保留普通空格**：空格是 ``+`` 分隔判据的重要信号（``Fe + Cu2+`` 的加号
    两侧都有空格，而 ``Cu2+`` 内部的加号没有），删掉空格会让判据退化成纯靠
    字符形态猜，风险更高。
    """
    t = str(text or "").translate(_SUPERSCRIPT).translate(_SUBSCRIPT)
    t = re.sub(r"\[,;!>| ]", "", t)
    return t.replace("$", "")


@dataclass
class Species:
    """一个化学计量项（如 ``2H2O`` 中的 ``2H2O``）。"""

    raw: str
    coefficient: Fraction
    atoms: dict[str, Fraction]
    charge: Fraction


def _parse_formula(formula: str) -> tuple[dict[str, Fraction], str]:
    """解析化学式主体 → ``({元素: 个数}, 失败原因)``。

    手写扫描而不用正则：括号可以嵌套（``Ca(OH)2``、``K4[Fe(CN)6]``），
    正则要么不支持嵌套要么写成一坨不可读的怪物。扫描器同时负责
    「元素符号必须首字母大写 + 在元素表内」这条硬约束，
    这是零假阳性的关键：碰到不认识的记号立刻放弃，而不是硬拆成单字母元素。

    水合物 / 复盐的 ``·``（``CuSO4·5H2O``）走递归：点号后是「倍数 + 化学式」，
    递归把剩余整串解析完再按倍数并入，因此本层不支持在 ``·`` 之后再接括号组。
    """
    stack: list[dict[str, Fraction]] = [{}]
    i, n = 0, len(formula)
    while i < n:
        ch = formula[i]
        if ch in "([{":
            stack.append({})
            i += 1
            continue
        if ch in ")]}":
            if len(stack) == 1:
                return {}, f"括号不匹配：{formula}"
            group = stack.pop()
            i += 1
            mult = _leading_count(formula, i)
            i += mult[1]
            _merge_into(stack[-1], group, mult[0])
            continue
        if ch == "·":
            # 水合物：点号之后是「倍数 + 完整化学式」，递归解析剩余整串
            if len(stack) != 1:
                return {}, f"括号不匹配：{formula}"
            i += 1
            mult = _leading_count(formula, i)
            sub, why = _parse_formula(formula[i + mult[1]:])
            if why:
                return {}, why
            _merge_into(stack[0], sub, mult[0])
            return stack[0], ""
        if ch in " \t\u3000":
            i += 1
            continue
        m = re.match(r"([A-Z][a-z]?)(\d*)", formula[i:])
        if not m or m.group(1) not in _ELEMENTS:
            # 两字母组合不在元素表时退回单字母（``Co`` 是钴，但 ``Cn`` 之后接 ``O``
            # 的情形必须能拆成 C + nO？不——拆错就是假结论，所以只在单字母本身是
            # 合法元素且两字母组合非法时才回退，其余一律判为无法解析。）
            m1 = re.match(r"([A-Z])(\d*)", formula[i:])
            if not m1 or m1.group(1) not in _ELEMENTS:
                return {}, f"无法识别的化学记号「{formula[i:i + 4]}」（式子：{formula}）"
            m = m1
        el = m.group(1)
        cnt = Fraction(int(m.group(2))) if m.group(2) else Fraction(1)
        top = stack[-1]
        top[el] = top.get(el, Fraction(0)) + cnt
        i += m.end()
    if len(stack) != 1:
        return {}, f"括号不匹配：{formula}"
    return stack[0], ""


def _leading_count(text: str, pos: int) -> tuple[Fraction, int]:
    """读取 ``pos`` 处紧跟的数字（括号后 / 点号后的倍数）；返回 ``(倍数, 消耗字符数)``。"""
    m = re.match(r"\d+", text[pos:])
    return (Fraction(int(m.group(0))), m.end()) if m else (Fraction(1), 0)


def _merge_into(target: dict[str, Fraction], source: dict[str, Fraction], mult: Fraction) -> None:
    """把 ``source`` 按倍数 ``mult`` 并入 ``target``。"""
    for el, cnt in source.items():
        target[el] = target.get(el, Fraction(0)) + cnt * mult




def _clean_species_text(raw: str) -> str:
    """把一个计量项的**排版**剥掉，只留「系数 + 化学式 + 电荷」的纯文本。

    顺序有讲究：先剥 LaTeX 包装（``\\mathrm``、``$``、``\\,``）再处理下标，
    否则 ``SO_4^{2-}`` 里的 ``_{4}`` 会被当成普通字符留在串里，电荷就抽不出来。
    """
    t = str(raw or "").strip()
    t = _STATE_RE.sub("", t)
    t = re.sub(r"\$(?:displaystyle)?", "", t)
    t = re.sub(r"\\mathrm|\\text|\\mathit", "", t)
    t = t.replace("\\cdot", "·").replace("\\times", "*")
    t = re.sub(r"\\[,;!>| ]", "", t)
    t = t.replace("{", "").replace("}", "")
    t = t.translate(_SUPERSCRIPT)
    # 下标 ``_4`` / ``_{4}`` 去掉下划线即可（H_2O -> H2O）
    t = t.replace("_", "")
    t = t.translate(_SUBSCRIPT)
    t = t.replace("（", "(").replace("）", ")").replace("［", "[").replace("］", "]")
    return re.sub(r"[\s\u3000]+", "", t)


def _parse_species(token: str) -> tuple[Species | None, str]:
    """解析一个计量项 → ``(Species, 失败原因)``。

    **电荷必须在化学式之前抽出**，否则 ``Cu2+`` 会被当成「两个铜原子」，
    于是 ``Fe + Cu2+ -> Fe2+ + Cu`` 这个正确的离子方程式会被判成不守恒——
    这正是「工具自己制造假 refuted」的典型，必须在解析顺序上堵死。

    电荷写法有**真歧义**时（``SO42-`` 既可能是 SO₄²⁻ 也可能是 SO₄₂⁻）不猜，
    返回原因让上层判 undecidable：猜错的代价是把正确答案改成错的。
    明确写法（``SO4^2-``、``SO4^{2-}``、``Ca+2``、``²⁻``）一律精确解析。
    """
    raw = str(token or "").strip()
    if not raw:
        return None, "空的计量项"
    body = _clean_species_text(raw)
    if not body:
        return None, f"计量项「{raw}」去掉排版后为空"

    # 电子项特判：``5e-`` / ``2e^-`` 的系数后面紧跟小写 e，会被下面系数正则的
    # ``(?![a-z])`` 前瞻挡掉（那条前瞻是为了别把 ``Cu`` 的 C 当系数）。半反应里
    # 电子必须能带系数，否则 ``MnO4- + 8H+ + 5e- -> ...`` 整侧解析失败。
    m_e = re.fullmatch(r"(\d+(?:\.\d+)?|\d+/\d+)\s*(?:e\^?-{1,3}|-{1,3}\^?e)", body)
    if m_e:
        try:
            e_coeff = Fraction(m_e.group(1))
        except (ValueError, ZeroDivisionError):
            return None, f"电子项系数无法解析：{m_e.group(1)}"
        # 正则只有一个捕获组（系数），符号要从整串取
        sign = -1 if "-" in m_e.group(0) else 1
        mag = m_e.group(0).count("-")
        return Species(raw=raw, coefficient=e_coeff, atoms={},
                       charge=Fraction(sign * max(1, mag))), ""

    # 系数：\frac{1}{2} / 1/2 / 0.5 / 2
    coeff = Fraction(1)
    m = re.match(r"^\\d?frac(\d+)/(\d+)", body)
    if m:
        coeff = Fraction(int(m.group(1)), int(m.group(2)))
        body = body[m.end():]
    else:
        m = re.match(r"^(\d+/\d+|\d+\.\d+|\d+)(?![a-z])", body)
        if m:
            try:
                coeff = Fraction(m.group(1))
            except (ValueError, ZeroDivisionError):
                return None, f"计量项「{raw}」的系数无法解析：{m.group(1)}"
            body = body[m.end():]

    charge, why = _extract_charge(body, raw)
    if why:
        return None, why
    charge, body = charge[0], charge[1]

    if not body:
        return None, f"计量项「{raw}」只有系数或电荷，没有化学式"
    # 电子（半反应用）：没有元素，只带电荷
    if re.fullmatch(r"e\^?-?|\^?-?e", body):
        return Species(raw=raw, coefficient=coeff, atoms={}, charge=charge), ""
    if not re.fullmatch(r"[A-Za-z0-9()\[\]·*]+", body):
        return None, f"计量项「{raw}」含无法解析的记号：{body[:24]}"
    atoms, why_f = _parse_formula(body)
    if why_f:
        return None, why_f
    if not atoms:
        return None, f"计量项「{raw}」未解析出任何元素"
    return Species(raw=raw, coefficient=coeff, atoms=atoms, charge=charge), ""


def _extract_charge(body: str, raw: str) -> tuple[tuple[Fraction, str], str]:
    """从化学式尾部抽出净电荷；返回 ``((电荷, 剩余化学式), 歧义原因)``。

    尾部是「数字 + 符号」时，数字既可能是**下标**也可能是**电荷量**——这是化学
    记号本身的重叠，必须靠上下文消歧。判定按确定性从高到低排列：

      1. ``^`` 显式上标（``SO4^2-``、``Fe^3+``）：``^`` 之后必属电荷，无歧义；
      2. 符号在前（``Ca+2``、``Fe+3``）：符号后的数字必属电荷，无歧义；
      3. 数字在前 + **单原子**（``Fe2+``、``Cu2+``、``O2-``）：数字是电荷量
         （「Fe₂⁺」这种二聚离子在普化语境里不存在，所以不必犹豫）；
      4. 数字在前 + **多原子** + 1 位数字（``MnO4-``、``NO3-``、``NH4+``）：
         数字是下标，电量由符号个数给出。这是通行读法；反读成 MnO⁴⁻ 在真实题目里
         几乎不存在（真那样写作者会用 ``^``）；
      5. 数字在前 + 多原子 + ≥2 位数字（``SO42-``）：两种读法都能解析成合法化学式，
         **猜错就会把正确方程式判成不守恒**，因此明确要求用 ``^`` 标注并返回歧义原因。

    第 3、4 条的分界（单原子 vs 多原子）是本函数唯一需要「化学常识」的地方，
    它换来的是 ``Fe + Cu2+ -> Fe2+ + Cu`` 与 ``MnO4- + 8H+ + 5e- -> Mn2+ + 4H2O``
    这两类高频离子方程式都能被正确判定，而不是双双落到歧义。
    """
    if not body:
        return (Fraction(0), body), ""
    m = re.search(r"\^([0-9]*[+-][0-9]*|[0-9]+)$", body)
    if m:
        return (Fraction(_charge_value(m.group(1))), body[:m.start()]), ""
    # 顺序很关键：先试「数字 + 符号」（``Cu2+``），再试「符号 + 数字」（``Ca+2``）。
    # 反过来会让 ``Cu2+`` 命中后一条（符号在前、数字为空）而被解析成「Cu2 带 +1」，
    # 于是 ``Fe + Cu2+ -> Fe2+ + Cu`` 这个正确离子方程式被判成不守恒——实测踩过。
    m = re.search(r"(\d+)([+-]{1,3})$", body)
    if m:
        digits, signs = m.group(1), m.group(2)
        head = body[:m.start()]
        sign = 1 if signs[0] == "+" else -1
        # 单原子离子：``Fe2+``、``Cu2+``、``O2-``、``Al3+``——数字只能是电荷量，
        # 因为「Fe₂⁺」这种二聚离子在中学/大学普化语境里不存在。
        monatomic = bool(re.fullmatch(r"[A-Z][a-z]?", head))
        if monatomic:
            # ``Ca++`` = +2（符号个数即电量），``Fe2+`` = +2（数字即电量）
            mag = int(digits) if len(signs) == 1 else int(digits) * len(signs)
            return (Fraction(sign * mag), head), ""
        if len(digits) == 1:
            # 多原子离子 + 1 位数字：``MnO4-`` = MnO₄⁻、``NO3-`` = NO₃⁻、``NH4+`` = NH₄⁺。
            # 数字是**下标**，电量由符号个数给出。这是化学记号的通行读法；
            # 反过来读（把 4 当电荷 → MnO⁴⁻）在真实题目里几乎不存在。
            return (Fraction(sign * len(signs)), body[:m.end() - len(signs)]), ""
        # 多原子离子 + ≥2 位数字：``SO42-`` 到底是 SO₄²⁻ 还是 S O₄₂⁻？
        # 两种读法都能解析成合法化学式，**猜错就会把正确方程式判成不守恒**，
        # 所以明确要求作者用 ^ 显式标注，本层判 undecidable。
        return (Fraction(0), body), (
            f"计量项「{raw}」的电荷写法有歧义：结尾「{digits}{signs}」既可能是下标也可能是电荷"
            f"（SO₄²⁻ 应写成 SO4^2- 或 SO4^(2-)，不要写成 SO42-）"
        )
    m = re.search(r"([+-]{1,3})(\d*)$", body)
    if m:
        # 「符号在前」的写法（``Ca+2``、``Fe+3``）：符号后的数字必属电荷，无歧义
        sign = 1 if m.group(1)[0] == "+" else -1
        digits = m.group(2)
        if digits:
            return (Fraction(sign * int(digits)), body[:m.start()]), ""
        return (Fraction(sign * len(m.group(1))), body[:m.start()]), ""
    return (Fraction(0), body), ""


def _charge_value(text: str) -> int:
    """把 ``^`` 之后的电荷串（``2-`` / ``-2`` / ``++``）转成带符号整数。"""
    signs = re.findall(r"[+-]", text)
    digits = re.findall(r"\d+", text)
    sign = 1 if (not signs or signs[0] == "+") else -1
    if digits:
        return sign * int(digits[0])
    return sign * max(1, len(signs))


def _split_side(side: str) -> tuple[list[Species], str]:
    """把箭头一侧按「加号」拆成计量项列表。

    ``+`` 不能盲目 split：``Cu2+`` 内部就带 ``+``。判据（两条都要满足才算分隔符）：

    1. ``+`` 之后能开始一个新计量项：大写元素字母 / ``(`` / ``\\d?frac(`` / 电子 ``e``，
       或者「数字后面紧跟大写字母或括号」（``+ 2NaOH`` 的 ``2`` 是系数，
       而 ``Ca+2`` 的 ``2`` 是电荷量）；
    2. ``+`` 之前已有一个完整计量项（以元素字母、数字、右括号或电荷符号结尾）。

    这样 ``Fe + Cu2+``、``Cu2+ + Fe``、``H+ + OH-``、``Fe3+ + 3OH-``、
    无空格的 ``2H2+O2`` 都能正确切分，而 ``Ca+2``、``SO42-`` 里的符号不会被当加号。
    """
    text = str(side or "").strip().strip("$").strip()
    text = _CONDITION_RE.sub(" ", text)
    text = text.replace("{", "").replace("}", "")
    if not text:
        return [], "该侧为空"
    # 新项的起头形态。``\d+(?=[A-Z(\[]|e\^?-)`` 这一支是必需的：半反应里
    # ``8H+ + 5e-`` 的 ``5e-`` 以数字起头，漏了它会把 ``+ 5e-`` 当成 ``8H+`` 的电荷，
    # 整侧解析失败（实测过）。而 ``Ca+2`` 的 ``2`` 后面没有元素字母，不会被误判成系数。
    new_item = re.compile(r"(?:\\d?frac\(|[A-Z(\[]|e\^?-|\d+(?:\.\d+)?(?=[A-Z(\[]|e\^?-))")
    parts: list[str] = []
    buf = ""
    for i, ch in enumerate(text):
        if ch != "+":
            buf += ch
            continue
        prev, nxt = buf.rstrip(), text[i + 1:].lstrip()
        if not prev:
            continue                      # 前导孤立加号：丢弃，不产生空项
        prev_ok = bool(re.search(r"[A-Za-z0-9)）\]+-]$", prev))
        nxt_ok = bool(new_item.match(nxt))
        if prev_ok and nxt_ok:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)

    species: list[Species] = []
    for part in parts:
        token = part.strip().strip("·").strip()
        if not token:
            continue
        sp, why = _parse_species(token)
        if sp is None:
            return [], why
        species.append(sp)
    if not species:
        return [], f"该侧未解析出任何计量项：{side[:40]}"
    return species, ""


def balance_check(equation: str) -> dict[str, str]:
    """核验化学方程式是否**原子守恒 + 净电荷守恒**；不做任何计量计算。

    范围是刻意的：用户明确「化生简化处理」。配平与电荷守恒是纯机械可判定的
    （纯代码、零依赖、零假阳性），而「生成多少克沉淀」这类计量计算依赖题目条件，
    条件解析一旦出错就会把正确答案判成错的——那比不判更糟。
    因此本函数只回答一个问题：**这个方程式自己是否自洽**。

    - 两侧每种元素原子总数相等且净电荷相等 → confirmed
    - 任一元素或电荷不等 → refuted（附逐项差额，让人一眼看出缺什么）
    - 解析失败 / 含表外记号 / 不是方程式 → undecidable + 原因
    """
    tool = TOOL_BY_CAPABILITY["symbolic_partial"]
    text = _normalize_equation_text(equation).strip()
    if not text:
        return _undecidable(tool, "未提供化学方程式")
    m = _ARROW_RE.search(text)
    if not m:
        return _undecidable(
            tool, f"未识别出反应箭头（需要 -> / → / \\to / = 之一）：{text[:60]}",
        )
    left_raw, right_raw = text[:m.start()], text[m.end():]
    left, why_l = _split_side(left_raw)
    if why_l:
        return _undecidable(tool, f"反应物一侧解析失败：{why_l}", given=text[:120])
    right, why_r = _split_side(right_raw)
    if why_r:
        return _undecidable(tool, f"生成物一侧解析失败：{why_r}", given=text[:120])

    def tally(items: list[Species]) -> tuple[dict[str, Fraction], Fraction]:
        atoms: dict[str, Fraction] = {}
        charge = Fraction(0)
        for sp in items:
            for el, cnt in sp.atoms.items():
                atoms[el] = atoms.get(el, Fraction(0)) + cnt * sp.coefficient
            charge += sp.charge * sp.coefficient
        return atoms, charge

    l_atoms, l_charge = tally(left)
    r_atoms, r_charge = tally(right)

    def fmt(val: Fraction) -> str:
        return str(val.numerator) if val.denominator == 1 else f"{val.numerator}/{val.denominator}"

    diffs: list[str] = []
    for el in sorted(set(l_atoms) | set(r_atoms)):
        lv, rv = l_atoms.get(el, Fraction(0)), r_atoms.get(el, Fraction(0))
        if lv != rv:
            diffs.append(f"{el}：左 {fmt(lv)} ≠ 右 {fmt(rv)}")
    if l_charge != r_charge:
        diffs.append(f"净电荷：左 {fmt(l_charge)} ≠ 右 {fmt(r_charge)}")

    summary = (
        "元素数 " + ", ".join(f"{el}={fmt(v)}" for el, v in sorted(l_atoms.items()))
        + f"；净电荷 {fmt(l_charge)}"
    )
    if diffs:
        return _verdict(
            VERDICT_REFUTED, tool,
            computed="；".join(diffs), given=text[:200],
            evidence=f"左侧（{summary}）与右侧不守恒：{'；'.join(diffs)}",
        )
    return _verdict(
        VERDICT_CONFIRMED, tool,
        computed=summary, given=text[:200],
        evidence=f"两侧原子数与净电荷均守恒（{summary}）",
    )


# ------------------------------------------------------------------ 计算机（executable）

# 各语言的静态检查能力。**只有 python 做真语法检查**：其它语言要么本机没有解析器，
# 要么解析器版本与目标环境不一致，硬判会产生假 refuted。
_LANG_ALIASES: dict[str, str] = {
    "py": "python", "python3": "python", "python": "python",
    "sh": "shell", "bash": "shell", "zsh": "shell", "shell": "shell",
    "cmd": "windows_cmd", "bat": "windows_cmd", "powershell": "windows_cmd",
    "ps1": "windows_cmd", "console": "shell", "terminal": "shell",
}


# POSIX shell 内建 / 保留命令：由 shell 本身实现，PATH 里查不到但一定存在。
# 不列这张表的话，``echo done``、``pwd`` 这类合法示例会因为 which 找不到而判
# undecidable，白白损失可判定率（它们不可能「命令不存在」，所以也没有假 confirmed 风险）。
_SHELL_BUILTINS = frozenset("""
echo pwd cd test export set unset alias read exit true false printf source
shift return eval exec local declare typeset readonly command builtin getopts
wait jobs kill trap times umask break continue case if then else elif fi while
until for do done function in esac
""".split())


def _extract_command_names(code: str) -> list[str]:
    """从命令行文本里抽出**被调用的命令名**，用于存在性探测。

    只看每行第一个词与管道 ``|``、``&&``、``;`` 之后的第一个词：这才是「会被执行的
    程序」。文件路径、参数、重定向目标一律不算，否则 ``git status`` 里能抽出
    ``status``，探测必然失败，进而把正确示例误报成「命令不存在」。
    """
    names: list[str] = []
    for line in str(code or "").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        text = re.sub(r"^\$\s*", "", text)          # 提示符
        text = re.sub(r"^\s*(?:sudo|time|nohup)\s+", "", text)
        for seg in re.split(r"\|\||&&|;|\|", text):
            seg = seg.strip()
            if not seg:
                continue
            # 绝对路径形态：``/usr/bin/python3``、``C:\tools\foo.exe``、``./venv/bin/py``。
            # 必须先于「取第一个词」处理，否则 Windows 盘符会被切成 ``D``，
            # which("D") 必然失败，把一条**本机确实存在**的命令报成「找不到」。
            m_path = re.match(r'''^(?:[A-Za-z]:[\\/]|[\\/]|\.{1,2}[\\/])([^\s'"]+)''', seg)
            if m_path:
                names.append(m_path.group(0).strip('"').strip("'"))
                continue
            m = re.match(r"^([A-Za-z_][\w.\-+]*)", seg)
            if not m:
                continue
            name = m.group(1)
            # 赋值不是可执行文件；cd/export 这类 shell 内建也不算「命令存在性」的对象
            if re.match(r"^[A-Za-z_]\w*=", seg) or name in ("cd", "export", "set", "alias"):
                continue
            names.append(name)
    return names


def _command_exists(name: str) -> bool:
    """命令是否存在：绝对路径查文件，其余查 PATH。

    绝对路径不能用 ``shutil.which``——which 对 ``C:\tools\foo.exe`` 这种带路径的
    参数行为不可靠（它会当成 PATH 里的名字去找）。分两条路径判才是确定的。
    """
    text = str(name or "").strip().strip('"').strip("'")
    if not text:
        return False
    if re.match(r"^(?:[A-Za-z]:[\\/]|[\\/]|\.{1,2}[\\/])", text):
        return os.path.isfile(text) or bool(shutil.which(text))
    return text in _SHELL_BUILTINS or shutil.which(text) is not None


def static_code_check(code: str, lang: str = "python") -> dict[str, str]:
    """对计算机学科的代码 / 命令做**静态**检查；绝不执行任何被检代码。

    安全边界写死在这里：本层会拿到模型生成的任意代码，一旦执行就等于把生成端的
    输出直接接到本机的 shell 上。因此只做两件不可能产生副作用的事：

    1. **Python 语法检查**：``ast.parse`` + ``compile``。两者都要用——``ast.parse``
       只查语法树能否构建，``compile`` 额外查「结构合法性」
       （实测 ``return 1`` 在模块级、``def f(a, a)`` 重复形参都能过 ast.parse
       却被 compile 拒），少一个就会漏报。
       语法错 → refuted（这是确定的事实，不是主观判断）。
    2. **命令存在性探测**：``shutil.which`` 查命令是否在本机 PATH 里。
       **找不到 → undecidable，而不是 refuted**：命令不存在可能只是本机没装
       （Windows 上没有 ``grep``），环境差异不是答案错误，报 refuted 会逼着
       上层去「修正」一个本来正确的示例。
    """
    tool = TOOL_BY_CAPABILITY["executable"]
    text = str(code or "").strip()
    if not text:
        return _undecidable(tool, f"未提供代码或命令；{PAYLOAD_HINT['executable']}")
    language = _LANG_ALIASES.get(str(lang or "").strip().lower(), str(lang or "").strip().lower())

    if language == "python":
        problems: list[str] = []
        try:
            ast.parse(text)
        except SyntaxError as exc:
            problems.append(
                f"第 {exc.lineno} 行第 {exc.offset or 0} 列：{exc.msg}"
                + (f"（{exc.text.strip()[:60]}）" if exc.text else "")
            )
        except (ValueError, RecursionError) as exc:
            return _undecidable(tool, f"Python 源码无法解析：{exc}", given=text[:200])
        if not problems:
            try:
                compile(text, "<aiedu_static_check>", "exec")
            except SyntaxError as exc:
                problems.append(f"编译期结构错误 第 {exc.lineno} 行：{exc.msg}")
            except (ValueError, TypeError) as exc:
                return _undecidable(tool, f"编译检查异常：{exc}", given=text[:200])
        if problems:
            return _verdict(
                VERDICT_REFUTED, tool, computed="；".join(problems), given=text[:200],
                evidence="Python 语法/结构检查未通过（学生复制后无法运行）：" + "；".join(problems),
            )
        return _verdict(
            VERDICT_CONFIRMED, tool, computed="语法与结构检查通过", given=text[:200],
            evidence="ast.parse 与 compile 均通过；未执行代码（安全边界）",
        )

    if language in ("shell", "windows_cmd"):
        names = _extract_command_names(text)
        if not names:
            return _undecidable(tool, "未从命令文本中识别出可执行命令名", given=text[:200])
        missing = sorted({n for n in names if not _command_exists(n)})
        found = sorted({n for n in names if n not in missing})
        if missing:
            return _undecidable(
                tool,
                f"本机 PATH 中未找到命令 {', '.join(missing)}（可能是环境差异而非答案错误，"
                "需人工确认目标平台）",
                given=text[:200],
            )
        return _verdict(
            VERDICT_CONFIRMED, tool, computed=f"命令均存在：{', '.join(found)}",
            given=text[:200],
            evidence="shutil.which 探测通过；未执行命令（安全边界）",
        )

    return _undecidable(
        tool,
        f"语言「{lang or '未指定'}」暂不支持静态检查（仅 python 语法检查与 shell 命令探测），"
        "回落模型核验+人工",
        given=text[:200],
    )


# ------------------------------------------------------------------ 分派

def resolve_capability(domain_key: str | None) -> str:
    """学科 key → verify_capability。

    **刻意不直接用 ``get_profile(key).verify_capability``**：``get_profile`` 对未知 key
    与 ``None`` 都回退到 ``cs_it``（那是为教学画像服务的合理默认），而 cs_it 的
    capability 是 ``executable``。照抄这个默认会让「没填学科」的题目走 Python 静态检查，
    于是一段普通文字答案（``"叶绿体"`` 不是合法 Python，但 ``"a"`` 是）可能被判
    confirmed —— 这是**假确认**，比 undecidable 危险得多。
    验证层的默认必须是「不知道就不判」，所以这里只认 PROFILES 里真实存在的 key。
    """
    from ..learning.disciplines import PROFILES

    profile = PROFILES.get(str(domain_key or "").strip())
    if profile is None:
        return "none"
    return str(getattr(profile, "verify_capability", "none") or "none")


# 化学记号字符集：抽取方程式时的「可扩窗」字符。含 LaTeX 排版符（$ \ _ ^ { }）
# 是因为题干里的方程式往往就是 `$2H_2 + O_2 \to 2H_2O$` 这种形态。
_CHEM_CHAR_RE = re.compile(r"[A-Za-z0-9+\-·^_{}\[\]()$\\ ]")


def _extract_equation(text: str) -> str:
    r"""从题干 / 答案里抠出化学方程式（调用方没显式给载荷时的兜底）。

    做法：找到反应箭头，再以箭头为中心向两侧**只在化学字符集内扩张**，遇到中文
    （「配平：」）、标点、行边界就停。这样既能从 ``**5.**（10 分）配平：2H2 + O2 -> 2H2O``
    里正确抠出方程式，又不会把中文说明当成反应物。

    抽不出来就返回空串让上层判 undecidable，**绝不做模糊匹配或跨行拼接**：
    一旦把「H₂O 的性质描述」错认成方程式，本层就会对一段普通文字做守恒核算并
    报 refuted——那比不判糟得多。
    """
    blob = _normalize_equation_text(text)
    for line in blob.splitlines():
        m = _ARROW_RE.search(line)
        if not m:
            continue
        start = m.start()
        while start > 0 and _CHEM_CHAR_RE.match(line[start - 1]):
            start -= 1
        end = m.end()
        while end < len(line) and _CHEM_CHAR_RE.match(line[end]):
            end += 1
        cand = line[start:end].strip().strip("$").strip()
        left, right = line[start:m.start()], line[m.end():end]
        # 两侧都得有大写元素记号，否则「->」只是行文里的箭头
        if re.search(r"[A-Z][a-z]?\d*", left) and re.search(r"[A-Z][a-z]?\d*", right):
            return cand
    return ""


def verify_by_discipline(
    domain_key: str | None,
    question_text: str,
    given_answer: str,
    *,
    capability: str | None = None,
    payload: Any = None,
    timeout: float = 5.0,
) -> dict[str, str]:
    """按学科的 ``verify_capability`` 分派到对应工具；统一返回三态结论。

    ``payload`` 是各学科所需的额外载荷（**必须由模型层提供**，本层不调模型）：

    - ``symbolic``：``str``（sympy 断言代码）或 ``{"sympy_code": ..., "target": ...}``；
    - ``symbolic_partial``：``str``（化学方程式）或 ``{"equation": ...}``；
      缺省时尝试从 ``question_text`` / ``given_answer`` 里抽取，抽不到 → undecidable；
    - ``executable``：``str``（代码或命令）或 ``{"code": ..., "lang": ...}``；
    - ``none``：不需要载荷。

    显式传 ``capability`` 时以它为准（测试与「跨学科组合卷」需要绕过学科推断）。
    """
    cap = str(capability or "").strip().lower() or resolve_capability(domain_key)
    tool = TOOL_BY_CAPABILITY.get(cap, "none")
    data = payload if isinstance(payload, dict) else {}
    blob = payload if isinstance(payload, str) else ""

    if cap == "symbolic":
        code = str(data.get("sympy_code") or data.get("code") or blob or "").strip()
        answer = given_answer if not data.get("given_answer") else str(data["given_answer"])
        return verify_math(question_text, answer, code, timeout=timeout)

    if cap == "symbolic_partial":
        equation = str(data.get("equation") or blob or "").strip()
        if not equation:
            equation = _extract_equation(f"{question_text}\n{given_answer}")
        if not equation:
            return _undecidable(
                tool,
                "未提供可判定的化学方程式（本层只验配平与电荷守恒，不做计量计算）；"
                + PAYLOAD_HINT["symbolic_partial"],
                given=str(given_answer or "")[:200],
            )
        return balance_check(equation)

    if cap == "executable":
        code = str(data.get("code") or data.get("command") or blob or "").strip()
        if not code:
            code = str(given_answer or "").strip()
        lang = str(data.get("lang") or data.get("language") or "python").strip()
        return static_code_check(code, lang)

    return _undecidable(
        TOOL_BY_CAPABILITY.get(cap, "none"),
        f"该学科（{domain_key or '未知'}，capability={cap or 'none'}）无形式化验证手段，"
        "回落模型核验+人工",
        given=str(given_answer or "")[:200],
    )


# ------------------------------------------------------------------ 集成层
#
# 下面三个函数是本层与既有流水线（exam_check / exam_verify / llm.service）之间的
# 全部接口。刻意做成纯函数：不碰 DB、不碰 Session、不调模型，因此可单测、可在
# ThreadPoolExecutor 里并发调用（exam_verify 就是 3 路并发核验的）。

def build_transcription_request(items: list[dict]) -> str:
    """把「待核验题目 + 卷面答案」拼成一次**转写请求**（模型只负责转写，不负责判定）。

    为什么转写必须单独一次调用、且**要把答案给模型看**：

    盲解（``exam_verify``）阶段刻意不给答案，那是为了防止确认偏误。但转写阶段的
    任务不是「判断答案对不对」，而是「把题面与答案翻译成 sympy 表达式」——翻译
    任务给不给答案都不会产生偏误，反而**必须**给答案：``verify_math`` 的 result
    形态要拿卷面答案与 RESULT 比对，assert 形态要把答案写进断言。
    真正的防偏误发生在下一步：判定由 sympy 执行，模型没有裁量权。

    ``items`` 形如 ``{"number": int, "question": str, "answer": str, "type": str}``，
    可直接由 ``exam_check.build_verification_payload`` + ``paper.answers`` 拼出。
    """
    lines = [
        "你是符号计算转写器。把下面每道题的题面与参考答案转写成**一段**可在 sympy 中"
        "直接执行的 Python 代码，由外部程序执行并判定，你不负责判断答案对错。",
        "",
        SYMPY_ASSERTION_CONTRACT,
        "",
        f"共 {len(items or [])} 道题。严格输出 JSON："
        '{"items": [{"number": int, "sympy_code": str, "target": "RESULT", '
        '"unformalizable": bool, "note": str}]}',
        "items 必须覆盖下面每一个 number。无法形式化的题置 unformalizable=true，"
        "sympy_code 填 \\"# UNFORMALIZABLE\\"，note 说明原因（证明题 / 概念题 / 条件不足）。",
        "",
    ]
    for it in items or []:
        num = it.get("number")
        q = str(it.get("question") or "").strip()
        a = str(it.get("answer") or "").strip()
        lines.append(f"--- 第 {num} 题（{it.get('type') or '未知题型'}）---")
        lines.append(q)
        lines.append(f"参考答案：{a or '（缺失）'}")
        lines.append("")
    return "\n".join(lines).strip()


def run_batch(
    items: list[dict],
    *,
    domain_key: str | None = None,
    capability: str | None = None,
    timeout: float = 5.0,
    max_workers: int = 0,
) -> list[dict[str, Any]]:
    """批量核验，返回**按 number 排序**的结果列表。

    每项输入：``{"number", "question", "answer", "type", "sympy_code"|"payload"}``。
    每项输出：``{"number", "type", "capability", "tool", **三态结论}``。

    ``max_workers`` > 1 时用线程池并发（每次 sympy 调用要起一个子进程，~0.6s，
    一卷几十题串行会很慢）。默认 0 = 串行，便于调试与在受限环境下避免
    一次拉起过多 Python 子进程；生产接入建议 3~4，与 ``exam_verify.VERIFY_WORKERS``
    同量级（两者都会吃 CPU，不宜叠加）。

    任何一题抛异常都不会中断整批：本层是质量增强环节，**绝不能因为它失败而让
    整份卷子交付失败**（与 ``exam_verify.verify_paper_with_ai`` 的既有约定一致）。
    """
    src = [it for it in (items or []) if isinstance(it, dict)]
    cap = str(capability or "").strip().lower() or resolve_capability(domain_key)

    def one(item: dict) -> dict[str, Any]:
        num = item.get("number")
        try:
            payload = item.get("payload")
            if payload is None:
                payload = item.get("sympy_code") or item.get("code") or item.get("equation") or ""
            res = verify_by_discipline(
                domain_key,
                str(item.get("question") or ""),
                str(item.get("answer") or ""),
                capability=cap,
                payload=payload,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001  单题兜底：验证失败不得中断整批
            res = _undecidable(
                TOOL_BY_CAPABILITY.get(cap, "none"),
                f"工具验证异常：{exc.__class__.__name__}: {str(exc)[:120]}",
                given=str(item.get("answer") or "")[:200],
            )
        return {
            "number": num, "type": str(item.get("type") or ""),
            "capability": cap, **res,
        }

    if max_workers and max_workers > 1 and len(src) > 1:
        from concurrent.futures import ThreadPoolExecutor

        workers = min(int(max_workers), len(src))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="toolverify") as pool:
            results = list(pool.map(one, src))
    else:
        results = [one(it) for it in src]

    def _key(r: dict[str, Any]) -> int:
        try:
            return int(r.get("number"))
        except (TypeError, ValueError):
            return 10 ** 6

    results.sort(key=_key)
    return results


def to_fix_verdicts(
    results: list[dict], *, only_confidence: str = "high",
) -> list[dict[str, Any]]:
    """把本层结论翻译成 ``exam_check.apply_answer_fixes`` 吃的 verdict 形态。

    这是「工具验证 → 自动改写」的唯一通道，映射规则必须写死，因为
    ``apply_answer_fixes`` 会**真的改卷面答案**：

    - ``refuted`` → ``verdict="paper_wrong"`` + ``confidence="high"``。
      置信度敢给 high 是因为它来自确定性计算而非模型判断（``apply_answer_fixes``
      只采信 high，这正是工具验证相对盲解仲裁的关键优势：仲裁模型的 high 是
      自评，工具的 high 是可复算的）。
      ``correct_answer`` 取 ``computed``（sympy 算出的真值），让改写用**算出来的**
      答案覆盖错的，而不是用另一次未经验证的模型输出覆盖。
    - ``confirmed`` → ``verdict="blind_wrong"``：卷面是对的，若盲解曾与之冲突，
      以工具为准；``apply_answer_fixes`` 不会改写这个 verdict（安全）。
    - ``undecidable`` → 原样透传 ``verdict="undecidable"``，
      ``apply_answer_fixes`` 会记入 skipped 并注明原因，**绝不改写**。

    ``only_confidence`` 之外的结论一律降级为 undecidable，防止将来有人给工具结论
    标了别的置信度却仍被改写。
    """
    out: list[dict[str, Any]] = []
    for r in results or []:
        if not isinstance(r, dict):
            continue
        try:
            num = int(r.get("number"))
        except (TypeError, ValueError):
            continue
        verdict = str(r.get("verdict") or "").strip().lower()
        tool = str(r.get("tool") or "")
        computed = str(r.get("computed") or "").strip()
        base: dict[str, Any] = {
            "number": num,
            "reasoning": (r.get("evidence") or r.get("fallback_reason") or "")[:400],
            "question_defect": "",
            "tool": tool,
            "capability": str(r.get("capability") or ""),
        }
        if verdict == VERDICT_REFUTED and tool == "sympy" and computed:
            # 回填形态优先级：LaTeX（保持试卷排版风格）> sympy 源码。
            # 卷面答案原本被 $...$ 包裹时才加 $：与 exam_check 的答案区风格保持一致。
            latex = str(r.get("computed_latex") or "").strip()
            replacement = computed
            if latex and str(r.get("given") or "").strip().startswith("$"):
                replacement = f"${latex}$"
            elif latex:
                replacement = latex
            base.update({
                "verdict": "paper_wrong",
                "confidence": only_confidence,
                "correct_answer": replacement,
                "correct_answer_text": computed,
                "reasoning": f"[工具验证·{tool}] {base['reasoning']}".strip()[:400],
            })
        elif verdict == VERDICT_REFUTED:
            # 化学/静态检查也能 refuted，但它们没有「正确值」可回填
            # （守恒核算只说哪里不守恒，静态检查只说哪行语法错）。
            # 没有可回填的确定答案就不许触发改写，只上报为题目缺陷。
            base.update({
                "verdict": "undecidable",
                "confidence": "high",
                "correct_answer": "",
                "correct_answer_text": "",
                "question_defect": f"[工具验证·{tool}] {computed[:200]}",
            })
        elif verdict == VERDICT_CONFIRMED:
            base.update({
                "verdict": "blind_wrong",
                "confidence": only_confidence,
                "correct_answer": "",
                "correct_answer_text": "",
                "reasoning": f"[工具验证·{tool}] 卷面答案经确定性计算确认正确；{base['reasoning']}"[:400],
            })
        else:
            base.update({
                "verdict": "undecidable",
                "confidence": "low",
                "correct_answer": "",
                "correct_answer_text": "",
                "reasoning": f"[工具验证·{tool or 'none'}] {r.get('fallback_reason') or '无法判定'}"[:400],
            })
        out.append(base)
    return out
