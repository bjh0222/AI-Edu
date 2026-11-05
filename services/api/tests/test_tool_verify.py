# -*- coding: utf-8 -*-
r"""Tier-1 工具验证层（tool_verify）测试。

本文件的用例分两类，密度刻意不均：

1. **能力用例**：证明工具能判对（sympy 验算、化学守恒、静态检查、学科分派）。
   这些真值全部是**实际跑出来的**，不是推测：
   ``limit((cos(x))**(1/sin(x)**2), x, 0) == exp(-1/2)``、
   ``diff(asin(x), x, 5).subs(x, 0) == 9``（sympy 1.14.0 实测）。

2. **零假阳性回归用例**（本层最重要的测试）：每条都对应开发中**实际踩到**的坑，
   坑的共同形态是「工具因为自己的解析/环境局限，把一个**正确**的答案判成
   refuted」，而 refuted 是本项目唯一允许驱动自动改写的信号——一旦假阳性，
   流水线会主动把对的卷面答案改错。已收录的坑：

   - ``Fe + Cu2+ -> Fe2+ + Cu``：电荷解析顺序错会把 ``Cu2+`` 当成两个铜原子；
   - ``MnO4- + 8H+ + 5e- -> ...``：多原子离子尾数字是下标不是电荷；
   - ``2KMnO4 -> K2MnO4 + MnO2 + O2``：把产物 MnO2 当反应条件删掉；
   - ``$e^{-1/2}$``：``e`` 被 auto_symbol 变成自由符号，比较必然失败；
   - ``$2\sqrt{3}$``：LaTeX 隐式乘法没补 ``*``，parse_expr 直接 SyntaxError；
   - ``$\lg 100$``：数字粘连规则把它拆成 ``log10*(100)`` = 1000；
   - ``arctan(1)``：隐式乘号切进函数名内部变成 ``arc*tan(1)``；
   - ``ls`` / ``grep``：本机（Windows）没装这些命令，属环境差异不是答案错误。
"""
from __future__ import annotations

import re
import sys

import pytest

from app.services import tool_verify as tv

# sympy 缺失时跳过符号验算用例：CI / 精简环境不应因此红。
# 但化学与静态检查是零依赖的，任何环境都必须跑。
requires_sympy = pytest.mark.skipif(
    not tv.sympy_available(), reason="运行环境未安装 sympy"
)


# ============================================================ 一、sympy 子进程执行


@requires_sympy
def test_run_sympy_assertion_returns_result_value():
    """最基本的通路：子进程能算出值并结构化返回。"""
    run = tv.run_sympy_assertion("RESULT = 1 + 1", target="RESULT")
    assert run["ok"] is True
    assert run["value"] == "2"
    assert run["error"] == ""


@requires_sympy
def test_run_sympy_assertion_has_preset_symbols():
    """预置符号必须可用：模型经常省略 ``symbols('x')``，不预置就会一片 NameError。"""
    run = tv.run_sympy_assertion("RESULT = sin(pi/2) + x - x", target="RESULT")
    assert run["ok"] is True, run["error"]
    assert run["value"] == "1"


@requires_sympy
def test_run_sympy_assertion_reports_traceback_without_raising():
    """用户代码报错必须被捕获成结构化结果，而不是把异常抛到父进程。"""
    run = tv.run_sympy_assertion("RESULT = undefined_function(x)")
    assert run["ok"] is False
    assert "NameError" in run["error"]


@requires_sympy
def test_run_sympy_assertion_isolates_hard_crash():
    """子进程崩溃（SystemExit / 除零 / 语法错）不得影响父进程，且都要有可读错误。"""
    for code in ("RESULT = 1/0", "raise SystemExit(3)", "x = ((" * 400):
        run = tv.run_sympy_assertion(code, target="RESULT")
        assert run["ok"] is False
        assert run["error"], code
    assert 1 + 1 == 2   # 父进程仍然活着


@requires_sympy
def test_run_sympy_assertion_kills_infinite_loop_by_timeout():
    """超时是子进程存在的**首要理由**：线程里的 exec 无法安全中断死循环。"""
    import time

    started = time.monotonic()
    run = tv.run_sympy_assertion("while True:\n    pass", timeout=2.0)
    elapsed = time.monotonic() - started
    assert run["ok"] is False
    assert run["timed_out"] is True
    assert "超时" in run["error"]
    assert elapsed < 15, f"超时未生效，实际耗时 {elapsed:.1f}s"


@requires_sympy
def test_run_sympy_assertion_compares_given_expression():
    """三级相等判定：结构相等 / 差式化简为零 / 数值一致。"""
    code = "RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)"
    ok = tv.run_sympy_assertion(code, target="RESULT", given_source="exp(-Rational(1,2))")
    assert ok["ok"] is True
    assert ok["equal"] is True
    assert ok["equal_method"]

    bad = tv.run_sympy_assertion(code, target="RESULT", given_source="exp(Rational(1,2))")
    assert bad["equal"] is False

    # 等价的不同写法也必须判等（否则正确答案会被判 refuted）
    same = tv.run_sympy_assertion(code, target="RESULT", given_source="1/sqrt(E)")
    assert same["equal"] is True


@requires_sympy
def test_run_sympy_assertion_returns_none_equal_when_incomparable():
    """**无法比较**必须是 None，不能被当成「不相等」——那是唯一会制造假 refuted 的路径。"""
    run = tv.run_sympy_assertion(
        "y = symbols('y')\nRESULT = x + y", target="RESULT", given_source="x",
    )
    assert run["ok"] is True
    assert run["equal"] is None
    assert run["equal_method"]


# ------------------------------------------------------------------ 安全沙箱


@pytest.mark.parametrize("evil", [
    "__import__('os').system('dir')",
    "open('/etc/passwd').read()",
    "RESULT = eval('1+1')",
    "RESULT = exec('x = 1')",
    "os.system('rm -rf /')",
    "sys.exit(1)",
    "subprocess.run(['dir'])",
    "import os\nRESULT = 1",
    "RESULT = 1\nprint(__class__.__mro__)",
    "shutil.rmtree('/tmp/x')",
    "RESULT = 1 if globals() else 2",
])
def test_sandbox_rejects_forbidden_code(evil):
    """危险代码必须**在执行前**被拒绝，一个都不能漏。"""
    run = tv.run_sympy_assertion(evil)
    assert run["ok"] is False, evil
    assert run["rejected"], f"未标记为安全拒绝：{evil}"
    assert "安全拒绝" in run["error"]


@requires_sympy
def test_sandbox_rejection_does_not_spawn_subprocess():
    """被拒绝的代码根本不该启动子进程（拒绝路径要快、且零副作用）。"""
    import time

    started = time.monotonic()
    tv.run_sympy_assertion("__import__('os').system('dir')")
    rejected_elapsed = time.monotonic() - started

    started = time.monotonic()
    tv.run_sympy_assertion("RESULT = 1 + 1", target="RESULT")
    executed_elapsed = time.monotonic() - started

    assert rejected_elapsed < 0.2, f"拒绝路径耗时 {rejected_elapsed:.3f}s，疑似起了子进程"
    assert rejected_elapsed < executed_elapsed


@pytest.mark.parametrize("legit", [
    "RESULT = Interval.open(0, 1).sup",      # .open( 是 sympy 区间写法，不是文件打开
    "RESULT = limit(sin(x)/x, x, 0)",
    "RESULT = acos(0)",                      # acos 里含 "os"，不能被 os 模块规则误伤
    "x = symbols('x')\nRESULT = cos(x).subs(x, 0)",
    "RESULT = Piecewise((1, x > 0), (0, True))",
])
def test_sandbox_allows_legitimate_sympy_code(legit):
    """沙箱不能把正常 sympy 代码误拒：误拒 = 白丢一次判定机会。"""
    assert tv._sandbox_rejection(legit) == "", legit


def test_sandbox_rejects_oversized_code():
    """超长输入要早失败：正常一道题的转写不可能有几千行。"""
    run = tv.run_sympy_assertion("RESULT = " + "1+" * 5000 + "1")
    assert run["ok"] is False
    assert run["rejected"]


def test_sandbox_rejects_empty_code():
    run = tv.run_sympy_assertion("   ")
    assert run["ok"] is False
    assert run["error"]

# ============================================================ 二、数学验算（symbolic）


@requires_sympy
def test_verify_math_confirms_correct_limit_answer():
    """实测真值：lim(x->0) (cos x)^(csc^2 x) = e^(-1/2)。卷面答案对 => confirmed。"""
    code = "RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)"
    r = tv.verify_math("求 $\\lim_{x\\to0}(\\cos x)^{\\csc^2x}$", r"$e^{-1/2}$", code)
    assert r["verdict"] == "confirmed"
    assert r["tool"] == "sympy"
    assert r["computed"] == "exp(-1/2)"
    assert r["evidence"]


@requires_sympy
def test_verify_math_refutes_wrong_limit_answer():
    """同一个式子，卷面答案写成 e^(1/2) => refuted（这正是实测那批卷子里的真错误形态）。"""
    code = "RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)"
    r = tv.verify_math("求极限", r"$e^{1/2}$", code)
    assert r["verdict"] == "refuted"
    assert r["computed"] == "exp(-1/2)"
    assert r["given"] == r"$e^{1/2}$"


@requires_sympy
def test_verify_math_confirms_fifth_derivative_value():
    """实测真值：d^5/dx^5 arcsin(x) 在 x=0 处 = 9。"""
    code = "RESULT = diff(asin(x), x, 5).subs(x, 0)"
    r = tv.verify_math("设 $y=\\arcsin x$，求 $y^{(5)}(0)$", "9", code)
    assert r["verdict"] == "confirmed"
    assert r["computed"] == "9"

    wrong = tv.verify_math("同上", "-9", code)
    assert wrong["verdict"] == "refuted"


@requires_sympy
def test_verify_math_assert_mode_confirmed_and_refuted():
    """assert 形态：断言通过 => confirmed；抛 AssertionError => refuted。"""
    good = ("assert simplify(limit((cos(x))**(1/sin(x)**2), x, 0)"
            " - exp(-Rational(1, 2))) == 0")
    assert tv.verify_math("求极限", r"$e^{-1/2}$", good)["verdict"] == "confirmed"

    bad = good.replace("-Rational(1, 2)", "+ Rational(1, 2)")
    r = tv.verify_math("求极限", r"$e^{1/2}$", bad)
    assert r["verdict"] == "refuted"
    assert "断言未通过" in r["evidence"]


@requires_sympy
def test_verify_math_transcription_failure_is_undecidable_not_refuted():
    """**核心不变量**：转写失败（NameError / 语法错）是模型的问题，不是答案的问题。

    判成 refuted 就会触发自动改写，等于因为「我们没读懂题」去改学生的正确答案。
    """
    for code in ("RESULT = undefined_function(x)", "RESULT = = =", "def f(:\n"):
        r = tv.verify_math("求极限", "9", code)
        assert r["verdict"] == "undecidable", code
        assert r["fallback_reason"]


@requires_sympy
def test_verify_math_unformalizable_marker():
    """模型显式声明无法形式化（证明题/概念题）=> undecidable，不硬跑。"""
    r = tv.verify_math("证明：当 $x>0$ 时 $\\ln(1+x)<x$", "见解析", "# UNFORMALIZABLE")
    assert r["verdict"] == "undecidable"
    assert "无法形式化" in r["fallback_reason"]


@requires_sympy
def test_verify_math_requires_payload():
    """没给断言代码时必须说明缺什么（提示词侧靠这句话定位问题）。"""
    r = tv.verify_math("求极限", "9", "")
    assert r["verdict"] == "undecidable"
    assert "sympy 断言代码" in r["fallback_reason"]

    r2 = tv.verify_math("求极限", "9", "y = sin(x)")
    assert r2["verdict"] == "undecidable"
    assert "RESULT" in r2["fallback_reason"]


@requires_sympy
def test_verify_math_missing_given_answer_is_undecidable():
    """result 形态必须有卷面答案才能比对；缺答案不是「答案错」。"""
    r = tv.verify_math("求极限", "", "RESULT = 1")
    assert r["verdict"] == "undecidable"
    assert "缺少卷面答案" in r["fallback_reason"]


@requires_sympy
def test_verify_math_incomparable_is_undecidable():
    """两式无法比较（含自由符号）=> undecidable，绝不当成「不相等」。"""
    r = tv.verify_math("求 f(x)", "x", "y = symbols('y')\nRESULT = x + y")
    assert r["verdict"] == "undecidable"
    assert "无法判定" in r["fallback_reason"]


# -------------------------------------------------- 答案归一化（假 refuted 重灾区）


@pytest.mark.parametrize("answer,expected", [
    (r"$e^{-1/2}$", "e**(-1/2)"),
    (r"$e^{1/2}$", "e**(1/2)"),
    ("9", "9"),
    ("-9", "-9"),
    (r"$\dfrac{1}{2}$", "((1)/(2))"),
    (r"$2\sqrt{3}$", "2*sqrt(3)"),
    (r"$\frac{\pi}{4}$", "((pi)/(4))"),
    (r"$\ln 2$", "log(2)"),
    (r"$\lg 100$", "log10(100)"),
    (r"$x\ln x - x$", "x*log(x)-x"),
    (r"$\sin x$", "sin(x)"),
    (r"$\sin(2\pi)$", "sin(2*pi)"),
    (r"$2^{10}$", "2**(10)"),
    (r"$\sqrt[3]{8}$", "(8)**(1/(3))"),
    (r"$\mathrm{e}^{-x}$", "e**(-x)"),
    (r"$\operatorname{arctan} 1$", "atan(1)"),
    (r"$+\infty$", "+oo"),
    (r"$\left(1,2\right)$", "(1,2)"),
    (r"$-\dfrac{8}{3}$", "-((8)/(3))"),
    (r"$\log_2 8$", "log((8),(2))"),
])
def test_answer_to_sympy_source_known_forms(answer, expected):
    r"""卷面答案 -> sympy 源码。每条都对应一次实测踩坑，形态必须逐字一致。"""
    src, why = tv.answer_to_sympy_source(answer)
    assert why == "", why
    assert src == expected


@pytest.mark.parametrize("answer", [
    "",                        # 空
    r"$\int_0^1 x\,dx$",       # 未覆盖的 LaTeX 结构
    r"$\oint_C \vec F$",
    "正确",                     # 判断题文字答案
    "A",                       # 选择题字母（不在本层判定范围）
])
def test_answer_to_sympy_source_refuses_to_guess(answer):
    r"""转不了就明说，**绝不猜一个最像的**：猜错 = 假 refuted。"""
    src, why = tv.answer_to_sympy_source(answer)
    assert src == ""
    assert why


@requires_sympy
@pytest.mark.parametrize("answer,code", [
    (r"$\lg 100$", "RESULT = log(100, 10)"),        # 曾经被拆成 log10*(100)=1000
    (r"$\ln 2$", "RESULT = log(2)"),
    (r"$2\sqrt{3}$", "RESULT = 2*sqrt(3)"),
    (r"$\operatorname{arctan} 1$", "RESULT = atan(1)"),
    (r"$\log_2 8$", "RESULT = log(8, 2)"),
    (r"$\frac{\pi}{4}$", "RESULT = pi/4"),
    (r"$2^{10}$", "RESULT = 1024"),
])
def test_verify_math_end_to_end_on_tricky_answers(answer, code):
    r"""端到端回归：这些形态曾经全部落到 undecidable，现在必须能判 confirmed。"""
    r = tv.verify_math("题目", answer, code)
    assert r["verdict"] == "confirmed", (answer, r)


@requires_sympy
def test_verify_math_latex_form_is_compact_for_rewrite():
    r"""自动改写会把这个值写回卷面，因此 LaTeX 形态要与项目排版风格一致（无多余空格）。"""
    r = tv.verify_math("求极限", r"$e^{-1/2}$",
                       "RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)")
    assert r["computed_latex"] == r"e^{-\frac{1}{2}}"
    assert " " not in r["computed_latex"]


# ============================================================ 三、化学守恒（symbolic_partial）


@pytest.mark.parametrize("equation", [
    "2H2 + O2 -> 2H2O",
    "2Na + Cl2 -> 2NaCl",
    "CaCO3 -> CaO + CO2",
    "2H2O -> 2H2 + O2",
    "CH4 + 2O2 -> CO2 + 2H2O",
    "N2 + 3H2 -> 2NH3",
    "C6H12O6 + 6O2 -> 6CO2 + 6H2O",
    "2KMnO4 -> K2MnO4 + MnO2 + O2",
    "Ca(OH)2 + 2HCl -> CaCl2 + 2H2O",
    "CuSO4·5H2O -> CuSO4 + 5H2O",
])
def test_balance_check_confirms_balanced_molecular_equations(equation):
    """分子方程式配平正确 => confirmed。"""
    r = tv.balance_check(equation)
    assert r["verdict"] == "confirmed", (equation, r)
    assert r["tool"] == "stoichiometry_balance"
    assert "净电荷 0" in r["computed"]


@pytest.mark.parametrize("equation,missing", [
    ("H2 + O2 -> H2O", "O"),
    ("2H2 + O2 -> 3H2O", "H"),
    ("Fe + Cu2+ -> Fe3+ + Cu", "净电荷"),
    ("2KMnO4 -> K2MnO4 + O2", "Mn"),
])
def test_balance_check_refutes_unbalanced_equations(equation, missing):
    """不守恒 => refuted，且必须指出**具体缺什么**（用户要能照着改）。"""
    r = tv.balance_check(equation)
    assert r["verdict"] == "refuted", (equation, r)
    assert missing in r["computed"]


@pytest.mark.parametrize("equation", [
    "Fe + Cu2+ -> Fe2+ + Cu",
    "H+ + OH- -> H2O",
    "Fe3+ + 3OH- -> Fe(OH)3",
    "Zn + 2H+ -> Zn2+ + H2",
    "MnO4- + 8H+ + 5e- -> Mn2+ + 4H2O",
    "Cl2 + 2Br- -> 2Cl- + Br2",
])
def test_balance_check_confirms_ionic_equations(equation):
    r"""离子方程式：原子数**与净电荷**都要守恒。

    这几条是回归重点，每条都曾因解析顺序问题被判 refuted：
    ``Cu2+`` 被当成两个铜原子、``MnO4-`` 的 4 被当成电荷、``5e-`` 的系数被吞。
    """
    r = tv.balance_check(equation)
    assert r["verdict"] == "confirmed", (equation, r)


def test_balance_check_charge_conservation_is_actually_checked():
    """净电荷必须真的参与判定，不能只查原子数。"""
    ok = tv.balance_check("Fe + Cu2+ -> Fe2+ + Cu")
    assert ok["verdict"] == "confirmed"
    assert "净电荷 2" in ok["computed"]

    bad = tv.balance_check("Fe + Cu2+ -> Fe3+ + Cu")
    assert bad["verdict"] == "refuted"
    assert "净电荷：左 2 ≠ 右 3" in bad["computed"]


@pytest.mark.parametrize("equation", [
    "2H2 + O2 = 2H2O",
    r"$2H_2 + O_2 \to 2H_2O$",
    "2H2+O2->2H2O",
    r"2H_{2} + O_{2} \longrightarrow 2H_{2}O",
    "2H₂ + O₂ → 2H₂O",
])
def test_balance_check_accepts_layout_variants(equation):
    r"""排版差异（= / -> / \to / LaTeX 下标 / Unicode 下标）都不该影响判定。"""
    r = tv.balance_check(equation)
    assert r["verdict"] == "confirmed", (equation, r)


@pytest.mark.parametrize("equation", [
    "",
    "水的沸点是 100℃",
    "not an equation",
    "Xq + O2 -> H2O",                 # 表外元素记号
    "SO42- + Ba2+ -> BaSO4",           # 电荷写法真歧义（SO4^2- vs SO42^-）
])
def test_balance_check_undecidable_on_unparsable_input(equation):
    """解析不了 => undecidable + 原因，绝不硬判。"""
    r = tv.balance_check(equation)
    assert r["verdict"] == "undecidable", (equation, r)
    assert r["fallback_reason"]


def test_balance_check_ambiguity_message_tells_how_to_fix():
    r"""歧义要给出**可操作**的修正建议（用 ^ 显式标电荷），而不是只说「看不懂」。"""
    r = tv.balance_check("SO42- + Ba2+ -> BaSO4")
    assert r["verdict"] == "undecidable"
    assert "^" in r["fallback_reason"]


def test_balance_check_never_strips_a_product_as_condition():
    r"""回归：``MnO2`` 既是常见催化剂也是真实产物，绝不能被当条件删掉。

    删掉产物会让 ``2KMnO4 -> K2MnO4 + MnO2 + O2`` 这个**正确**方程式被判不守恒。
    """
    r = tv.balance_check("2KMnO4 -> K2MnO4 + MnO2 + O2")
    assert r["verdict"] == "confirmed"
    assert "Mn=2" in r["computed"]


def test_balance_check_distinguishes_co_from_c_plus_o():
    r"""元素白名单的作用：``Co``（钴）不能被拆成 ``C`` + ``O``。"""
    counts, why = tv._parse_formula("Co")
    assert why == ""
    assert list(counts) == ["Co"]

    counts2, why2 = tv._parse_formula("CO")
    assert why2 == ""
    assert set(counts2) == {"C", "O"}


def test_balance_check_scope_is_balance_only():
    """范围守卫：本层只做配平/电荷守恒，不做计量计算（用户明确「化生简化处理」）。"""
    r = tv.balance_check("需要 4g H2 才能生成 36g H2O")
    assert r["verdict"] == "undecidable"
    assert "计量" in r["fallback_reason"] or r["fallback_reason"]


# ============================================================ 四、计算机静态检查（executable）


def test_static_code_check_refutes_python_syntax_error():
    r = tv.static_code_check("def f(:\n", "python")
    assert r["verdict"] == "refuted"
    assert r["tool"] == "static_check"
    assert "invalid syntax" in r["computed"]


def test_static_code_check_confirms_valid_python():
    r = tv.static_code_check("def f():\n    return 1\n", "python")
    assert r["verdict"] == "confirmed"
    assert "未执行代码" in r["evidence"]


@pytest.mark.parametrize("code", [
    "return 1\n",                       # ast.parse 过，compile 拒
    "def f(a, a):\n    pass\n",         # 重复形参
    "x = (1\n",
    "for i in range(3)\n    pass\n",
])
def test_static_code_check_needs_compile_not_just_ast(code):
    r"""**必须同时用 compile**：``ast.parse`` 查不出结构性错误，只用它会漏报。"""
    r = tv.static_code_check(code, "python")
    assert r["verdict"] == "refuted", code


@pytest.mark.parametrize("code", [
    "def f():\n    def g():\n        return 2\n    return g()\n",
    "import math\nprint(math.sqrt(2))\n",
    "class A:\n    x = 1\n",
    "# 只有注释\n",
])
def test_static_code_check_does_not_over_reject_valid_python(code):
    """合法代码不能误判（误判 refuted = 假阳性，会逼上层改正确示例）。"""
    assert tv.static_code_check(code, "python")["verdict"] == "confirmed"


def test_static_code_check_never_executes_code():
    """安全边界：被检代码里的副作用绝不能发生（我们只 parse，不 exec）。"""
    import tempfile
    from pathlib import Path

    marker = Path(tempfile.gettempdir()) / "aiedu_static_check_must_not_exist.txt"
    marker.unlink(missing_ok=True)
    r = tv.static_code_check(
        f"open({str(marker)!r}, 'w').write('pwned')\n", "python",
    )
    assert r["verdict"] == "confirmed"      # 语法合法
    assert not marker.exists()              # 但文件必须不存在


def test_static_code_check_missing_command_is_undecidable():
    r"""命令不存在可能是**环境差异**（Windows 上没有 grep），不是答案错误。

    判 refuted 会驱动上层去「修正」一个本来正确的示例，所以必须 undecidable。
    """
    r = tv.static_code_check("definitely_not_a_real_cmd_xyz --help\n", "shell")
    assert r["verdict"] == "undecidable"
    assert "环境差异" in r["fallback_reason"]

    r2 = tv.static_code_check("cat a.txt | grep TODO && echo done\n", "bash")
    assert r2["verdict"] == "undecidable"


def test_static_code_check_shell_builtins_are_not_probed():
    r"""POSIX 内建命令由 shell 本身提供，PATH 里查不到也一定存在。"""
    r = tv.static_code_check("cd /tmp\npwd\necho hi\n", "sh")
    assert r["verdict"] == "confirmed", r


def test_static_code_check_finds_real_command():
    r"""本机一定存在的命令应 confirmed（用当前解释器自身，跨平台稳）。"""
    r = tv.static_code_check(f"{sys.executable} --version\n", "shell")
    assert r["verdict"] == "confirmed", r


def test_static_code_check_command_extraction_ignores_arguments():
    r"""只抽「会被执行的程序名」，不把参数/子命令当命令（否则会一片假 undecidable）。"""
    names = tv._extract_command_names("git status\nls -la | grep TODO\nexport PATH=/bin\n")
    assert "git" in names
    assert "status" not in names
    assert "TODO" not in names
    assert "PATH" not in names


@pytest.mark.parametrize("lang", ["java", "go", "rust", ""])
def test_static_code_check_unsupported_language_is_undecidable(lang):
    r"""不支持的语言要明说，不能默认按 Python 检查（那会产生假 refuted）。"""
    r = tv.static_code_check("class A { void f() {} }", lang)
    assert r["verdict"] == "undecidable"
    assert "回落" in r["fallback_reason"]


def test_static_code_check_empty_input():
    r = tv.static_code_check("", "python")
    assert r["verdict"] == "undecidable"


def test_static_code_check_language_aliases():
    r"""语言别名要归一：``py`` / ``python3`` / ``bash`` / ``sh`` / ``console`` 都常见。"""
    assert tv.static_code_check("def f(:\n", "py")["verdict"] == "refuted"
    assert tv.static_code_check("def f():\n    pass\n", "python3")["verdict"] == "confirmed"
    assert tv.static_code_check("pwd\n", "console")["verdict"] == "confirmed"


# ============================================================ 五、学科分派


def test_dispatch_by_discipline_capability():
    """分派必须按 disciplines.verify_capability 走，且工具名要写进返回值。"""
    cases = [
        ("math_logic", "symbolic", "sympy"),
        ("cs_it", "executable", "static_check"),
        ("chemistry_materials", "symbolic_partial", "stoichiometry_balance"),
        ("biology_life", "none", "none"),
    ]
    for key, cap, tool in cases:
        assert tv.resolve_capability(key) == cap, key
        assert tv.TOOL_BY_CAPABILITY[cap] == tool


def test_verify_by_discipline_biology_is_undecidable():
    """生物：无形式化手段 => undecidable + 明确的回落说明。"""
    r = tv.verify_by_discipline("biology_life", "光合作用的场所是？", "叶绿体")
    assert r["verdict"] == "undecidable"
    assert r["tool"] == "none"
    assert "回落模型核验+人工" in r["fallback_reason"]


@pytest.mark.parametrize("key", ["history_culture", "law_policy", "arts_creativity",
                                 "psychology_cognition", "economics_business"])
def test_verify_by_discipline_humanities_are_undecidable(key):
    """文科 / 社科：同样只能 undecidable（GENERIC 画像 capability=none）。"""
    r = tv.verify_by_discipline(key, "题目", "答案")
    assert r["verdict"] == "undecidable"


def test_unknown_or_missing_domain_must_not_run_static_check():
    """**关键守卫**：未知学科不得继承 get_profile 的 cs_it 默认（executable）。

    否则「没填学科」的题会走 Python 语法检查，而一段普通文字答案
    （比如 ``a``、``pass``）恰好是合法 Python，就会得到**假 confirmed**——
    假确认比 undecidable 危险得多。
    """
    for key in (None, "", "not_a_real_domain", "physics_astronomy_typo"):
        assert tv.resolve_capability(key) == "none", key
        r = tv.verify_by_discipline(key, "光合作用的场所是？", "a")
        assert r["verdict"] == "undecidable", key
        assert r["tool"] == "none"


def test_explicit_capability_overrides_discipline():
    """显式 capability 优先：跨学科组合卷与单测都需要绕过学科推断。"""
    r = tv.verify_by_discipline(
        "biology_life", "配平：", "2H2 + O2 -> 2H2O", capability="symbolic_partial",
    )
    assert r["verdict"] == "confirmed"
    assert r["tool"] == "stoichiometry_balance"


def test_invalid_capability_is_undecidable():
    r = tv.verify_by_discipline("math_logic", "q", "a", capability="wat")
    assert r["verdict"] == "undecidable"


@requires_sympy
def test_verify_by_discipline_math_with_payload():
    r = tv.verify_by_discipline(
        "math_logic", "求极限", r"$e^{-1/2}$",
        payload="RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)",
    )
    assert r["verdict"] == "confirmed"


def test_verify_by_discipline_chem_payload_forms():
    """化学载荷支持 str 与 dict 两种形态；都缺时尝试从题面抽取。"""
    a = tv.verify_by_discipline("chemistry_materials", "q", "a", payload="H2 + O2 -> H2O")
    assert a["verdict"] == "refuted"

    b = tv.verify_by_discipline("chemistry_materials", "q", "a",
                                payload={"equation": "2H2 + O2 -> 2H2O"})
    assert b["verdict"] == "confirmed"

    c = tv.verify_by_discipline("chemistry_materials",
                                "**5.**（10 分）配平：2H2 + O2 -> 2H2O", "已配平")
    assert c["verdict"] == "confirmed", c

    d = tv.verify_by_discipline("chemistry_materials", "水的沸点是多少？", "100℃")
    assert d["verdict"] == "undecidable"


def test_extract_equation_never_grabs_prose():
    """抽取要保守：纯中文说明一行不得被当成方程式。"""
    assert tv._extract_equation("水的性质：无色无味液体，沸点 100℃") == ""
    assert tv._extract_equation("请配平：2H2 + O2 -> 2H2O") == "2H2 + O2 -> 2H2O"
    assert tv._extract_equation("下面这段文字没有任何箭头") == ""


def test_verify_by_discipline_computer_payload():
    r = tv.verify_by_discipline("cs_it", "写一个函数", "def f():\n    return 1\n",
                                payload={"code": "def f(:\n", "lang": "python"})
    assert r["verdict"] == "refuted"

    ok = tv.verify_by_discipline("cs_it", "写一个函数", "见答案",
                                 payload="def f():\n    return 1\n")
    assert ok["verdict"] == "confirmed"


def test_return_dict_always_has_contract_keys():
    """返回契约：任何路径都必须给全 6 个键，否则上层报告会 KeyError。"""
    contract = {"verdict", "tool", "computed", "given", "evidence", "fallback_reason"}
    results = [
        tv.verify_by_discipline("biology_life", "q", "a"),
        tv.balance_check("2H2 + O2 -> 2H2O"),
        tv.balance_check(""),
        tv.static_code_check("def f(:\n", "python"),
        tv.verify_math("q", "9", ""),
        tv.verify_by_discipline("math_logic", "q", "a"),
        tv.verify_by_discipline(None, "q", "a", capability="wat"),
    ]
    for r in results:
        assert contract <= set(r), (contract - set(r), r)
        assert r["verdict"] in ("confirmed", "refuted", "undecidable")
        assert isinstance(r["tool"], str) and r["tool"]


def test_undecidable_always_carries_a_reason():
    """undecidable 必须带原因：没有原因，用户无法区分「没验」和「验过了」。"""
    for r in (tv.verify_by_discipline("biology_life", "q", "a"),
              tv.balance_check("Xq + O2 -> H2O"),
              tv.static_code_check("foo --bar", "java"),
              tv.verify_math("q", "9", "# UNFORMALIZABLE")):
        assert r["verdict"] == "undecidable"
        assert r["fallback_reason"].strip()


# ============================================================ 六、批量 / 集成


@requires_sympy
def test_run_batch_returns_sorted_results_with_metadata():
    """批量结果必须按 number 排序（调用方按题号对账），并带上 capability / tool。"""
    items = [
        {"number": 2, "type": "填空题", "question": "q2", "answer": "9",
         "sympy_code": "RESULT = diff(asin(x), x, 5).subs(x, 0)"},
        {"number": 1, "type": "填空题", "question": "q1", "answer": r"$e^{-1/2}$",
         "sympy_code": "RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)"},
        {"number": 3, "type": "解答题", "question": "q3", "answer": "见解析",
         "sympy_code": "# UNFORMALIZABLE"},
    ]
    out = tv.run_batch(items, domain_key="math_logic", timeout=15)
    assert [r["number"] for r in out] == [1, 2, 3]
    assert [r["verdict"] for r in out] == ["confirmed", "confirmed", "undecidable"]
    assert all(r["capability"] == "symbolic" for r in out)
    assert all(r["tool"] == "sympy" for r in out)


@requires_sympy
def test_run_batch_concurrent_matches_serial():
    """并发路径必须与串行等价（exam_verify 是 3 路 ThreadPoolExecutor，会并发进来）。"""
    items = [
        {"number": i, "type": "填空题", "question": f"q{i}",
         "answer": "$e^{-1/2}$" if i % 2 == 0 else "$e^{1/2}$",
         "sympy_code": "RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)"}
        for i in range(1, 7)
    ]
    serial = tv.run_batch(items, domain_key="math_logic", timeout=15)
    concurrent = tv.run_batch(items, domain_key="math_logic", max_workers=3, timeout=15)
    assert [r["verdict"] for r in serial] == [r["verdict"] for r in concurrent]
    # range(1, 7) 从奇数起：奇数题给了错答案 e^{1/2} => refuted
    assert [r["verdict"] for r in concurrent] == [
        "refuted", "confirmed", "refuted", "confirmed", "refuted", "confirmed",
    ]
    assert [r["computed"] for r in concurrent] == ["exp(-1/2)"] * 6


@requires_sympy
def test_run_batch_survives_a_bad_item():
    """单题异常不得中断整批（质量增强环节绝不能拖垮交付）。"""
    items = [
        {"number": 1, "answer": "9",
         "sympy_code": "RESULT = diff(asin(x), x, 5).subs(x, 0)"},
        {"number": "not-an-int", "answer": "9", "sympy_code": "RESULT = 1"},
        {"number": 3, "answer": "9", "sympy_code": None},
    ]
    out = tv.run_batch(items, domain_key="math_logic")
    assert len(out) == 3
    assert any(r["verdict"] == "confirmed" for r in out)


def test_run_batch_empty():
    assert tv.run_batch([], domain_key="math_logic") == []


def test_run_batch_rejects_non_dict_items():
    """脏输入（None / 字符串）不得让整批崩掉。"""
    out = tv.run_batch([None, "x", 42], domain_key="biology_life")
    assert out == []


@requires_sympy
def test_to_fix_verdicts_maps_refuted_to_paper_wrong_with_computed_answer():
    """refuted（有真值）-> paper_wrong + high，且 correct_answer 用**算出来的**真值。"""
    results = tv.run_batch(
        [{"number": 1, "type": "填空题", "question": "q", "answer": r"$e^{1/2}$",
          "sympy_code": "RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)"}],
        domain_key="math_logic", timeout=15,
    )
    v = tv.to_fix_verdicts(results)[0]
    assert v["verdict"] == "paper_wrong"
    assert v["confidence"] == "high"
    assert v["correct_answer"] == r"$e^{-\frac{1}{2}}$"   # LaTeX 形态，保持试卷排版风格
    assert v["correct_answer_text"] == "exp(-1/2)"        # 源码形态留给报告/调试
    assert "工具验证" in v["reasoning"]


@requires_sympy
def test_to_fix_verdicts_maps_confirmed_to_blind_wrong():
    """confirmed -> blind_wrong：卷面是对的，apply_answer_fixes 不会改写它。"""
    results = tv.run_batch(
        [{"number": 1, "type": "填空题", "question": "q", "answer": r"$e^{-1/2}$",
          "sympy_code": "RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)"}],
        domain_key="math_logic", timeout=15,
    )
    v = tv.to_fix_verdicts(results)[0]
    assert v["verdict"] == "blind_wrong"
    assert v["correct_answer"] == ""


def test_to_fix_verdicts_refuted_without_value_never_triggers_rewrite():
    r"""化学 / 静态检查能 refuted 但**给不出正确值**，此时不许驱动改写。

    守恒核算只说「哪里不守恒」，静态检查只说「哪行语法错」；
    拿这种结论去覆盖卷面答案，等于用一条不完整的判断改学生的答案。
    因此降级为 undecidable + question_defect（上层会计入 skipped 并上报缺陷）。
    """
    chem = dict(tv.balance_check("H2 + O2 -> H2O"), number=4)
    v = tv.to_fix_verdicts([chem])[0]
    assert v["verdict"] == "undecidable"
    assert v["correct_answer"] == ""
    assert "工具验证" in v["question_defect"]

    code = dict(tv.static_code_check("def f(:\n", "python"), number=5)
    v2 = tv.to_fix_verdicts([code])[0]
    assert v2["verdict"] == "undecidable"
    assert v2["correct_answer"] == ""


def test_to_fix_verdicts_undecidable_never_triggers_rewrite():
    bio = dict(tv.verify_by_discipline("biology_life", "q", "a"), number=7)
    v = tv.to_fix_verdicts([bio])[0]
    assert v["verdict"] == "undecidable"
    assert v["confidence"] == "low"
    assert v["correct_answer"] == ""


def test_to_fix_verdicts_ignores_items_without_number():
    assert tv.to_fix_verdicts([{"verdict": "refuted"}, "not-a-dict", None]) == []


@requires_sympy
def test_full_chain_with_exam_check_is_idempotent():
    r"""**端到端 + 幂等**：与 exam_check.apply_answer_fixes 串起来跑三轮。

    第 1 轮改掉错答案，第 2、3 轮必须 confirmed 且**零改写**。
    若非幂等，说明工具验证与「自动改，但只改一次」的约定冲突
    （会来回震荡，或把已改对的又改回去）。
    """
    from app.services import exam_check as ec

    paper_md = """
### 填空题

**1.**（20 分）$\\lim_{x\\to0}(\\cos x)^{\\csc^2x}=$ ______。

**2.**（20 分）设 $y=\\arcsin x$，则 $y^{(5)}(0)=$ ______。

### 参考答案

**1.** $e^{1/2}$　**2.** $-9$
"""
    code = {1: "RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)",
            2: "RESULT = diff(asin(x), x, 5).subs(x, 0)"}

    md = paper_md
    applied_history = []
    for _ in range(3):
        paper = ec.parse_paper(md)
        items = [{"number": q.number, "type": q.kind, "question": q.stem,
                  "answer": paper.answers[q.number], "sympy_code": code[q.number]}
                 for q in paper.questions]
        results = tv.run_batch(items, domain_key="math_logic", timeout=15)
        verdicts = tv.to_fix_verdicts(results)
        md, applied, _skipped = ec.apply_answer_fixes(md, paper, verdicts)
        applied_history.append([a["correct_answer"] for a in applied])

    assert applied_history[0] == [r"$e^{-\frac{1}{2}}$", "$9$"]
    assert applied_history[1] == [] and applied_history[2] == [], applied_history
    assert r"$e^{-\frac{1}{2}}$" in md and "$9$" in md


@requires_sympy
def test_full_chain_keeps_choice_answer_untouched():
    r"""选择题字母答案不该被符号验算动：``C`` 不是可计算表达式（应 undecidable）。

    选择题的正确路径是 exam_check.answer_content 把字母解析成**选项内容**再比对；
    本层拿到字母时只能明确说判不了，绝不能猜。
    """
    from app.services import exam_check as ec

    paper_md = """
### 选择题

**1.**（20 分）$\\lim_{n\\to\\infty}(1+a_n)^n=$（　　）

A. $1$　　B. $e$　　C. $e^2$　　D. $+\\infty$

### 参考答案

**1.** C
"""
    paper = ec.parse_paper(paper_md)
    results = tv.run_batch(
        [{"number": 1, "type": "选择题", "question": paper.questions[0].stem,
          "answer": paper.answers[1], "sympy_code": "RESULT = exp(2)"}],
        domain_key="math_logic",
    )
    assert results[0]["verdict"] == "undecidable"
    assert "选项字母" in results[0]["fallback_reason"]
    _md, applied, skipped = ec.apply_answer_fixes(
        paper_md, paper, tv.to_fix_verdicts(results))
    assert applied == []
    assert len(skipped) == 1


def test_transcription_request_includes_answers_and_contract():
    """转写请求必须包含答案（转写任务不存在确认偏误，判定权在 sympy 手里）。"""
    req = tv.build_transcription_request([
        {"number": 1, "type": "填空题", "question": "求极限", "answer": r"$e^{-1/2}$"},
    ])
    assert "RESULT" in req                       # 契约：两种形态之一
    assert "UNFORMALIZABLE" in req               # 契约：显式退出通道
    assert r"$e^{-1/2}$" in req
    assert "第 1 题" in req
    assert '"items"' in req                      # 输出 JSON 形态
    assert "不负责判断答案对错" in req             # 职责边界写进提示词
    assert "Rational" in req                     # 精确有理数要求（防 0.5 近似）


def test_transcription_request_forbids_dangerous_code():
    """提示词侧也要写清禁用项，与 _sandbox_rejection 的黑名单同源。"""
    req = tv.build_transcription_request([{"number": 1, "question": "q", "answer": "a"}])
    for token in ("open(", "eval(", "__import__", "subprocess"):
        assert token in req, token


def test_transcription_request_empty():
    req = tv.build_transcription_request([])
    assert "共 0 道题" in req


# ============================================================ 七、模块约束


def test_module_does_not_import_heavy_deps_at_top():
    """模块顶部不得 import sympy（惰性），否则所有请求都要付 ~0.7s 导入代价。"""
    from pathlib import Path

    src = Path(tv.__file__).read_text(encoding="utf-8")
    body = src.split('"""', 2)[2]
    header = body[:body.index("def ")]
    assert not re.search(r"^\s*import sympy|^\s*from sympy", header, re.M), \
        "sympy 必须惰性导入（只在子进程执行体里 from sympy import *）"
    assert "import sympy" not in header


def test_contract_and_prompt_are_exposed_for_the_model_layer():
    """exam_verify / prompts 侧要能拿到契约文本，避免各处各写一份（会漂移）。"""
    assert "RESULT" in tv.SYMPY_ASSERTION_CONTRACT
    assert "UNFORMALIZABLE" in tv.SYMPY_ASSERTION_CONTRACT
    assert isinstance(tv.PAYLOAD_HINT, dict)
    assert set(tv.PAYLOAD_HINT) == set(tv.TOOL_BY_CAPABILITY)


def test_verdict_constants_are_the_only_allowed_values():
    assert (tv.VERDICT_CONFIRMED, tv.VERDICT_REFUTED, tv.VERDICT_UNDECIDABLE) == (
        "confirmed", "refuted", "undecidable")
