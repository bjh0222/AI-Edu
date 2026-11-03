# -*- coding: utf-8 -*-
"""命题知识库与变式引擎（P2）：母题 → 同构变式 → 质量回流 → 命题规律。

============================================================================
理论依据
============================================================================

1. **AIG item model**（Automatic Item Generation，起源于 Bormuth 1960s）
   一道题拆成三层：
   - ``radicals``：决定难度与认知要求的**结构元素**（定义式、所问的量、答题约束）。
     同构题共享 radicals。
   - ``incidentals``：**表面特征**（具体参数值、情境包装、对象名）。可随机变化而不
     改变考查目标。
   - ``isomorphs``：同一 item model 代入不同 incidentals 得到的**同构题**。

2. **变式教学理论**（顾泠沅）
   - ``conceptual`` 概念性变式：故意改动 radicals（含反例 / 非例），用于厘清概念边界；
   - ``procedural`` 过程性变式：放松条件、难度递减，用于搭建解题台阶。
   这两类**改变了题目结构**，因此原母题的解法模板不再适用，答案必须独立验证。

3. **与项目既有规范表述的对应关系**
   项目里曾有一份「变式与综合题汇编规范」（导出件 ``data/spec_variant_v2.json``，
   2026-10-31 创建后**当日即停用**，数据库中已无此规范、也无任何目标绑定它）。它的
   required_rules 写着「变式保持原题考点与难度档，只改情境、参数、对象或结论方向」
   ——那就是 radicals 不变、只换 incidentals，即 isomorph。
   **本模块不依赖该规范**（``extract_item_models`` 只吃 markdown 文本，不认 scene），
   引用它仅因为它用教学语言准确描述了同一个区分。活跃规范中「练习生成规范」的
   ``变式题`` 题型同样落在这个语义上。

============================================================================
为什么必须分 ItemModel / ItemInstance 两张表（本模块的核心价值）
============================================================================

实测那份 5 套微积分卷里：

- 母题 ``x=ln(t+sqrt(1+t^2)), y=arctan t`` 出现 5 次，给出 4 个不同答案
  （``sqrt2`` / ``sqrt2/2`` / ``-2`` / ``sqrt2``）；
- 母题 ``f_n(x)=x^n+2nx-2`` 出现 4 次，给出 ``e`` / ``e^2`` / ``e^{-1}`` 三个答案。

根因不是模型「不够聪明」，而是**每次出现都独立重新生成**。只要生成路径是独立的，
漂移就是必然的——提高温度控制、加强提示词都只能降低频率，不能消除。

分表之后，决定答案结构的 radicals 只在 ``ItemModel`` 存一份；同构变式的答案由
``solution_template`` 代入新的 incidentals **用 sympy 机械求解**得到
（``verified_by="tool_symbolic"``），从架构上消除「同母题答案漂移」。

============================================================================
两条不可让步的边界
============================================================================

- **求解失败绝不编造答案**。``solve_isomorph`` 返回 ``computed=False``，
  ``make_variation`` 对 isomorph 直接抛 409，宁可不产出也不产出一个未经验证的答案。
  理由：一个看起来很确定的错答案，比「这题我算不出来」危害大得多——前者会被直接
  交付给学生。
- **变式 ↔ 原题的对应关系只存 ``ItemInstance.item_model_id``，绝不写进输出 Markdown**。
  这条约束来自项目规范的一贯要求：内置试卷生成规范的 forbidden_rules 明令禁止
  「（原题…）」「（对应第 N 题的变式…）」等溯源括注，已停用的变式汇编规范亦然。
  所以溯源是**数据库事实**，不是**交付物内容**。
"""
from __future__ import annotations

import ast
import hashlib
import io
import keyword
import logging
import re
import tokenize
from datetime import datetime, timezone

import sympy
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sympy.parsing.sympy_parser import parse_expr, standard_transformations

from ..learning.disciplines import get_profile
from ..learning.teaching_profile import DEFAULT_SOFT_BUDGET
from ..models import DesignPrinciple, ItemInstance, ItemModel, QualityRecord
from . import exam_check
from .utils import jdump, jload

logger = logging.getLogger("aiedu")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# sympy 受控执行环境
# ===========================================================================
#
# solution_template 是**数据**（存在数据库里、可由人编辑），不是代码。直接 eval 它
# 等于把任意代码执行权交给任何能写库的人。三道防线，每道都对应一类实测风险：
#
# 1. **token 白名单**：只允许 名字 / 数字 / 少数运算符。这一条挡掉属性访问
#    （``x.__class__.__bases__`` 沙箱逃逸的经典路径，实测在 __builtins__={} 下**仍然
#    可用**，只靠清空 builtins 挡不住）、字符串字面量、以及一切点号调用。
# 2. **Python 关键字黑名单**：``lambda`` / ``if-else`` / ``import`` 全是 NAME 或 OP
#    token，光看 token 类型看不出来，必须按关键字挡。
# 3. **幂运算规模守卫**：实测 ``parse_expr("9**9**9")`` 会让 sympy 试图构造一个
#    3.8 亿位的整数而**永久挂死**（不是变慢，是不返回）。命名空间限制对此毫无作用，
#    因为 9 是个完全合法的小字面量。必须在**求值之前**用 AST 静态判定。
#
# 为什么不用子进程 + 超时：那要给每次求解付一次进程启动成本，而 Windows 上无法
# 可靠地取消一个卡在 C 扩展里的线程。静态守卫足以覆盖已知的挂死路径，成本低得多。

# 允许的运算符。注意**没有** ``.``（属性访问）与 ``'``/``"``（字符串）。
_ALLOWED_OPS = frozenset({"+", "-", "*", "**", "/", "//", "%", "(", ")", "[", "]", ",", "=", ":", "<", ">", "<=", ">="})

_MAX_TEMPLATE_CHARS = 512
_MAX_TOKENS = 200
_MAX_AST_NODES = 400
# 整底数的指数上限：超过就拒解。64 已经远超任何真实题目（2**64 本身就不是题目答案），
# 而 9**9 这类「看起来无害」的写法一旦超过就会让 sympy 挂死。
_MAX_INT_EXPONENT = 64
_MAX_COUNT_OPS = 4000

# sympy 命名空间：只放数学构造函数，不放任何能触碰解释器的东西。
_SYMPY_NAMES = (
    "sqrt", "exp", "log", "ln", "sin", "cos", "tan", "cot", "sec", "csc",
    "asin", "acos", "atan", "acot", "asec", "acsc",
    "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
    "Abs", "sign", "floor", "ceiling", "Min", "Max", "Mod",
    "Rational", "Integer", "Float", "Symbol", "Pow",
    "pi", "E", "I", "oo", "zoo", "nan",
    "Eq", "Ne", "Lt", "Le", "Gt", "Ge", "And", "Or", "Not",
    "diff", "limit", "Integral", "Sum", "Product",
    "factorial", "binomial", "gcd", "lcm",
    "Piecewise", "FiniteSet", "Tuple", "Interval", "Union", "Intersection",
    "Matrix", "atan2", "root", "real_root", "conjugate", "re", "im",
)


def _sympy_namespace() -> dict:
    ns: dict = {"__builtins__": {}}
    for name in _SYMPY_NAMES:
        obj = getattr(sympy, name, None)
        if obj is not None:
            ns[name] = obj
    return ns


_SYMPY_NS = _sympy_namespace()


class TemplateError(ValueError):
    """solution_template / answer_expr 不合法或不可求解。

    继承 ValueError 而不是抛裸异常：调用方（solve_isomorph）要把它转成
    ``computed=False`` + 可读 error，绝不能让它冒泡成 500。
    """


def _guard_tokens(src: str) -> None:
    """token 白名单 + 关键字黑名单；不合法就抛 TemplateError。"""
    if len(src) > _MAX_TEMPLATE_CHARS:
        raise TemplateError(f"表达式超过 {_MAX_TEMPLATE_CHARS} 字符上限")
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise TemplateError(f"表达式无法解析：{exc}") from exc
    count = 0
    for tok in tokens:
        if tok.type in (
            tokenize.ENDMARKER, tokenize.NEWLINE, tokenize.NL,
            tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT,
        ):
            continue
        count += 1
        if count > _MAX_TOKENS:
            raise TemplateError(f"表达式超过 {_MAX_TOKENS} 个 token 上限")
        if tok.type == tokenize.OP:
            if tok.string not in _ALLOWED_OPS:
                raise TemplateError(f"不允许的运算符：{tok.string!r}")
        elif tok.type == tokenize.NAME:
            # 关键字必须是 NAME 才挡得住：lambda / if / import 在 token 类型上与普通
            # 名字无异，只有按字面比对关键字表才能识别。
            if keyword.iskeyword(tok.string) or tok.string in ("True", "False", "None"):
                raise TemplateError(f"不允许的关键字：{tok.string!r}")
        elif tok.type != tokenize.NUMBER:
            # 字符串字面量（tokenize.STRING）与 f-string 等一律拒绝
            raise TemplateError(f"不允许的语法元素：{tokenize.tok_name[tok.type]}")


def _const_magnitude(node) -> float:
    """AST 数值常量的量级；算不出精确值时返回 inf 表示「巨大」。

    **绝不能在这里直接算 ``b ** e``**：那正是要防的挂死路径。所以指数一旦超过上限就
    立刻返回 inf，把判定交给调用方，而不是先把大整数造出来。
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return abs(float(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _const_magnitude(node.operand)
    if isinstance(node, ast.BinOp):
        left, right = _const_magnitude(node.left), _const_magnitude(node.right)
        if isinstance(node.op, ast.Pow):
            if left <= 1.0 or right != right or right == float("inf"):
                return left if right == 0 else float("inf")
            if right > _MAX_INT_EXPONENT:
                return float("inf")
            try:
                return abs(left ** right)
            except OverflowError:
                return float("inf")
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Add):
            return left + right
    return float("nan")   # 含符号：不是常量，规模由 sympy 自己管


def _guard_pow(node, depth: int = 0) -> None:
    """静态拒绝会导致 sympy 挂死的大整数幂运算。

    **必须先判定 node 自身、再递归子节点**：``9**9**9`` 的根节点就是那个致命的 Pow，
    只遍历 ``iter_child_nodes`` 会把它整个跳过（实测确实会跳，然后 sympy 永久不返回）。
    """
    if depth > 40:
        raise TemplateError("表达式嵌套过深")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        base = _const_magnitude(node.left)
        exponent = _const_magnitude(node.right)
        # 判定必须精确到「两端都是字面量」这一种形态，其余一律放行：
        #
        # - 指数为 nan = 含符号（``9**n``、``(1+p)**n``）：sympy 惰性保留、不会构造大整数，
        #   **必须放行**，否则合法的参数化模板会被误拒。
        # - 底数为 nan = 含符号（``p**9``）：同样不会构造大整数，放行。
        # - 只有「底数是大于 1 的字面量 + 指数是字面量且过大」才会触发大整数构造。
        #   实测 ``9**9**9`` 正是这一形态，会让 sympy 永久不返回（不是变慢）。
        base_is_literal = (base == base) and base != float("inf")
        exp_is_literal = (exponent == exponent) and exponent != float("inf")
        if base_is_literal and exp_is_literal and base > 1.0 and exponent > _MAX_INT_EXPONENT:
            raise TemplateError("整数幂规模超过上限（底数大于 1 且指数过大），拒绝求解")
    for child in ast.iter_child_nodes(node):
        _guard_pow(child, depth + 1)


def parse_sympy(src: str, *, what: str = "表达式") -> sympy.Expr:
    """把一段模板文本解析成 sympy 表达式；任何不合法都抛 TemplateError。

    这是本模块**唯一**接触 sympy 解析器的入口，三道守卫都在这里，别处不得绕过。
    """
    text = str(src or "").strip()
    if not text:
        raise TemplateError(f"{what}为空")
    _guard_tokens(text)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise TemplateError(f"{what}语法错误：{exc.msg}") from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
        raise TemplateError(f"{what}超过 {_MAX_AST_NODES} 个语法节点上限")
    _guard_pow(tree.body)
    try:
        expr = parse_expr(
            text,
            global_dict=_SYMPY_NS,
            local_dict={},
            transformations=standard_transformations,
            evaluate=True,
        )
    except TemplateError:
        raise
    except Exception as exc:  # noqa: BLE001  解析失败一律转成可读错误，不冒泡
        raise TemplateError(f"{what}无法解析：{exc.__class__.__name__}: {str(exc)[:120]}") from exc
    if not isinstance(expr, (sympy.Basic,)):
        raise TemplateError(f"{what}不是合法的数学表达式")
    try:
        if sympy.count_ops(expr) > _MAX_COUNT_OPS:
            raise TemplateError(f"{what}规模超过 {_MAX_COUNT_OPS} 个运算上限")
    except TemplateError:
        raise
    except Exception:  # noqa: BLE001  count_ops 自己出错不该拖垮求解
        pass
    return expr

# 未知量的保留符号名。solution_template 里出现它，表示「要求解的就是这个量」；
# 代入 incidentals 时**绝不**替换它。
UNKNOWN_SYMBOL = "ANS"

# 多解时的选取规则白名单。必须显式声明才选，绝不猜：
# 「同一道题给出多个互斥答案」正是本模块要根治的病（E018），求解器自己再犯一次
# 就毫无意义了。未声明规则又确实多解时，返回 computed=False 并说明原因。
ANSWER_SELECTORS = ("positive", "negative", "max", "min", "nonnegative")


def _to_sympy_value(value):
    """把一个 incidental 值转成 sympy 对象；转不了返回 None（调用方判失败，不猜）。

    接受 int / float / Decimal 字面量、``"3/4"`` 这类分数字符串，以及 ``"sqrt(2)"``
    这类需要走同一套守卫的表达式字符串。布尔值**不接受**：``True`` 在 Python 里等于
    ``1``，静默当成数字会让「参数填错了」变成「答案算错了」，两者都难排查。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return sympy.Integer(value)
    if isinstance(value, float):
        return sympy.Float(value)
    if isinstance(value, sympy.Basic):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # 纯小数 / 分数优先按精确有理数解析，避免 0.1 变成二进制浮点误差
        m = re.fullmatch(r"([+-]?\d+)\s*/\s*(\d+)", text)
        if m:
            denom = int(m.group(2))
            return sympy.Rational(int(m.group(1)), denom) if denom else None
        if re.fullmatch(r"[+-]?\d+", text):
            return sympy.Integer(int(text))
        if re.fullmatch(r"[+-]?\d*\.\d+([eE][+-]?\d+)?", text):
            return sympy.Rational(text)
        try:
            return parse_sympy(text, what="参数值")
        except TemplateError:
            return None
    return None


def _subs_values(expr, values: dict):
    """代入参数；返回 (结果表达式, 未能解析的键列表)。"""
    mapping: dict = {}
    unresolved: list[str] = []
    for key, raw in (values or {}).items():
        name = str(key)
        val = _to_sympy_value(raw)
        if val is None:
            unresolved.append(name)
            continue
        mapping[sympy.Symbol(name)] = val
    if not mapping:
        return expr, unresolved
    try:
        # mapping 的键恒为 sympy.Symbol（见上），所以用 xreplace：它做纯结构替换，
        # 不会像 subs 那样触发额外化简与求值——更快，也不会引入意外的重写。
        out = expr.xreplace(mapping)
    except Exception as exc:  # noqa: BLE001
        raise TemplateError(f"代入参数失败：{exc.__class__.__name__}: {str(exc)[:120]}") from exc
    # xreplace 不做算术化简，这里补一次；失败就保留原样（不因为化简失败而判无解）
    try:
        out = sympy.simplify(out) if sympy.count_ops(out) <= 60 else out
    except Exception:  # noqa: BLE001
        pass
    return out, unresolved


def _pick_solution(solutions: list, selector: str):
    """从多个候选解里按**显式声明**的规则挑一个；挑不出就返回 (None, 原因)。"""
    if not solutions:
        return None, "方程无解"
    if len(solutions) == 1:
        return solutions[0], ""
    if selector == "positive":
        pool = [s for s in solutions if (s.is_positive is True)]
    elif selector == "nonnegative":
        pool = [s for s in solutions if (s.is_positive is True or s.is_zero is True)]
    elif selector == "negative":
        pool = [s for s in solutions if (s.is_negative is True)]
    elif selector == "max":
        pool = []
        try:
            pool = [max(solutions, key=lambda s: complex(sympy.N(s)).real)]
        except Exception:  # noqa: BLE001
            pool = []
    elif selector == "min":
        pool = []
        try:
            pool = [min(solutions, key=lambda s: complex(sympy.N(s)).real)]
        except Exception:  # noqa: BLE001
            pool = []
    else:
        pool = []
    if len(pool) == 1:
        return pool[0], ""
    shown = ", ".join(str(s) for s in solutions[:4])
    if not selector:
        return None, (
            f"方程有 {len(solutions)} 个解（{shown}），但母题未声明 answer_select 选取规则；"
            "拒绝任选其一（那正是「同题多解」的病根）"
        )
    return None, f"answer_select={selector!r} 未能唯一确定解（候选：{shown}）"


def _is_unusable(expr) -> str:
    r"""结果是不是「数学上无意义」的；是则返回原因，否则返回空串。

    必须挡掉 ``zoo`` 与 ``nan``：实测 ``1/(p-2)`` 在 ``p=2`` 时 sympy 给出 ``zoo``
    （复无穷），若原样当成答案交付，学生看到的就是一个除零错误的产物。``nan``
    同理（``0/0``、``oo-oo``）。

    **``oo`` / ``-oo`` 要放行**：它们是极限题的合法答案（实测那份卷的选项里就有
    ``D. $+\infty$``），不是错误。
    """
    try:
        if expr.has(sympy.zoo, sympy.nan):
            return "求解结果为未定义值（除零或不定式），拒绝当作答案"
        if expr is sympy.zoo or expr is sympy.nan:
            return "求解结果为未定义值（除零或不定式），拒绝当作答案"
    except Exception:  # noqa: BLE001  has() 自身异常时不拦，交由后续判定
        return ""
    return ""


def _format_answer(expr) -> dict:
    """把 sympy 结果格式化成可交付文本。

    ``answer`` 用 ``str(expr)``：确定、可复现、可直接比对（``sqrt(2)``、``1/2``、
    ``exp(-1)``）。``answer_latex`` 供 Markdown 数学环境使用。``numeric`` 供快速核对，
    算不出（含符号 / 无界）就是空串，不硬凑。
    """
    try:
        latex = sympy.latex(expr)
    except Exception:  # noqa: BLE001
        latex = ""
    numeric = ""
    try:
        if not expr.free_symbols:
            val = sympy.N(expr, 10)
            if val.is_finite is not False and not val.has(sympy.zoo, sympy.nan, sympy.oo):
                numeric = str(val)
    except Exception:  # noqa: BLE001
        numeric = ""
    return {"answer": str(expr), "answer_latex": latex, "numeric": numeric}


def solve_isomorph(item_model_dict: dict, incidental_values: dict) -> dict:
    """把 incidentals 代入母题的参数化解法，用 sympy **机械求解**出答案。

    返回 ``{"answer": str, "computed": bool, "error": str}``（另附 answer_latex /
    numeric 供渲染与核对）。``computed=False`` 时 ``answer`` 恒为空串——**求解失败绝不
    编造答案**，这是本模块最重要的一条约束：一个看起来很确定的错答案会被直接交付给
    学生，危害远大于「这题算不出来」。

    两种求解形态（按优先级）：

    1. ``answer_expr`` 非空：它就是答案的参数化表达式（如 ``sqrt(p)/2``），代入后直接
       化简。适合「答案 = 参数的闭式函数」的绝大多数客观题。
    2. ``solution_template`` 非空：
       - 是关系式（``Eq(ANS**2 - p, 0)``）→ 对未知量求解，按 ``answer_select`` 选解；
       - 是普通表达式 → 视作答案表达式本身（与形态 1 等价）。

    两者都为空 → ``computed=False``。抽出的母题默认没有模板（不能凭空造），必须由人
    补录或从已确认的典型题导入；在那之前该母题**不产出** isomorph 变式。
    """
    result = {"answer": "", "answer_latex": "", "numeric": "", "computed": False, "error": ""}
    model = item_model_dict if isinstance(item_model_dict, dict) else {}
    unknown_name = str(model.get("unknown") or UNKNOWN_SYMBOL).strip() or UNKNOWN_SYMBOL
    unknown = sympy.Symbol(unknown_name)
    selector = str(model.get("answer_select") or "").strip().lower()
    if selector and selector not in ANSWER_SELECTORS:
        result["error"] = f"未知的 answer_select 规则：{selector!r}（可选：{'/'.join(ANSWER_SELECTORS)}）"
        return result

    values = dict(incidental_values or {})
    # 未知量不能被当作参数代入，否则方程会被消掉
    values.pop(unknown_name, None)

    declared = model.get("incidentals") or {}
    if isinstance(declared, dict) and declared:
        missing = sorted(k for k in declared if k not in values and k != unknown_name)
        if missing:
            result["error"] = f"缺少母题声明的参数：{', '.join(missing)}"
            return result

    expr_src = str(model.get("answer_expr") or "").strip()
    tmpl_src = str(model.get("solution_template") or "").strip()
    if not expr_src and not tmpl_src:
        result["error"] = "母题未定义 answer_expr / solution_template，无法机械求解（拒绝编造答案）"
        return result

    try:
        if expr_src:
            expr = parse_sympy(expr_src, what="answer_expr")
            solved, unresolved = _subs_values(expr, values)
            if unresolved:
                result["error"] = f"参数值无法解析为数学量：{', '.join(unresolved)}"
                return result
            if solved.free_symbols:
                result["error"] = (
                    "代入后仍含未定符号："
                    + ", ".join(sorted(str(s) for s in solved.free_symbols))
                )
                return result
            bad = _is_unusable(solved)
            if bad:
                result["error"] = bad
                return result
            result.update(_format_answer(solved))
            result["computed"] = True
            return result

        tmpl = parse_sympy(tmpl_src, what="solution_template")
        substituted, unresolved = _subs_values(tmpl, values)
        if unresolved:
            result["error"] = f"参数值无法解析为数学量：{', '.join(unresolved)}"
            return result
        if substituted.free_symbols and not (substituted.free_symbols == {unknown}):
            result["error"] = (
                "代入后仍含未定符号："
                + ", ".join(sorted(str(s) for s in (substituted.free_symbols - {unknown})))
            )
            return result
        if isinstance(substituted, sympy.logic.boolalg.Boolean) or substituted.has(sympy.Eq):
            if not substituted.has(unknown):
                result["error"] = f"解法模板不含未知量 {unknown_name}，无法求解"
                return result
            try:
                solutions = sympy.solve(substituted, unknown)
            except Exception as exc:  # noqa: BLE001  解不出如实报告
                result["error"] = f"符号求解失败：{exc.__class__.__name__}: {str(exc)[:120]}"
                return result
            picked, reason = _pick_solution(list(solutions or []), selector)
            if picked is None:
                result["error"] = reason
                return result
            bad = _is_unusable(picked)
            if bad:
                result["error"] = bad
                return result
            result.update(_format_answer(picked))
            result["computed"] = True
            return result
        # 普通表达式：化简后即为答案
        if substituted.free_symbols:
            result["error"] = (
                "解法模板化简后仍含未定符号："
                + ", ".join(sorted(str(s) for s in substituted.free_symbols))
            )
            return result
        bad = _is_unusable(substituted)
        if bad:
            result["error"] = bad
            return result
        result.update(_format_answer(substituted))
        result["computed"] = True
        return result
    except TemplateError as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001  兜底：任何异常都转成「算不出」，不冒泡成 500
        logger.warning("机械求解异常：%s", exc)
        result["error"] = f"求解异常：{exc.__class__.__name__}: {str(exc)[:120]}"
        return result

# ===========================================================================
# 母题抽取
# ===========================================================================

# 题干里可替换的数字槽位上限：超过说明这道题的数字太多，位置替换已不可靠，
# 交给人工重新定义槽位，而不是硬凑。
_MAX_SLOTS = 12

# 留存题干样本的长度上限：够覆盖一道完整题（含选项），又不至于让 radicals 膨胀。
_MAX_STEM_CHARS = 1200

# 只认 ``$...$`` / ``$$...$$`` 里的数字字面量当槽位。
# **必须限定在数学环境内**：题干开头的 ``**1.**（20 分）`` 里的 1 与 20 是题号与分值，
# 把它们当参数替换掉，生成的变式会直接变成另一道题的编号。
_MATH_SPAN = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)
_NUM_IN_MATH = re.compile(r"(?<![\w\\])\d+(?:\.\d+)?")


def _stem_slots(stem: str) -> list[tuple[int, int, str]]:
    """题干数学环境里的数字字面量，按出现顺序返回 [(起, 止, 原值)]。"""
    out: list[tuple[int, int, str]] = []
    text = str(stem or "")
    for span in _MATH_SPAN.finditer(text):
        start = span.start(1) if span.group(1) is not None else span.start(2)
        body = span.group(1) if span.group(1) is not None else span.group(2)
        for m in _NUM_IN_MATH.finditer(body or ""):
            out.append((start + m.start(), start + m.end(), m.group(0)))
    return out[:_MAX_SLOTS]


def _slot_names(count: int) -> list[str]:
    return [f"p{i + 1}" for i in range(count)]


def _render_stem(stem: str, slots: list[tuple[int, int, str]], values: dict) -> str:
    """按位置把新参数值替换进题干；未给值的槽位保留原值。

    位置替换而不是文本查找替换：同一个数字在题干里可能出现多次且含义不同
    （``x^n+2nx-2`` 里两个 2 就是不同参数），按 ``str.replace`` 会把它们混为一谈。
    """
    text = str(stem or "")
    if not slots:
        return text
    pieces: list[str] = []
    cursor = 0
    for idx, (start, end, original) in enumerate(slots):
        name = f"p{idx + 1}"
        pieces.append(text[cursor:start])
        new = values.get(name, None)
        pieces.append(original if new is None else str(new))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _papers_from_markdown(markdown: str, chapter: str = "") -> list[tuple[str, "exam_check.ExamPaper"]]:
    """把一份 Markdown 解析成 [(卷名, ExamPaper)]。

    含 ``## `` 分节时按 exam_check.split_papers 切卷（试卷规范是「一节一卷」，各卷题号
    都从 1 开始，整份一起解析会把题号混起来）；否则整份当一卷。
    """
    text = str(markdown or "")
    if not text.strip():
        return []
    parts = exam_check.split_papers(text)
    if len(parts) >= 2:
        out: list[tuple[str, "exam_check.ExamPaper"]] = []
        used: dict[str, int] = {}
        for name, body in parts:
            title = str(name or chapter or "")
            # **卷名必须唯一**：exam_check._definition_index 用 ``(卷名, 题号)`` 当键，
            # 两节同名时后一节会覆盖前一节的同一题号，母题的出现次数就被少算了。
            # 教程大纲理论上可能出现同名章节，所以这里确定性地补序号消歧。
            seen = used.get(title, 0)
            used[title] = seen + 1
            unique = title if seen == 0 else f"{title}#{seen + 1}"
            out.append((unique, exam_check.parse_paper(body, unique)))
        return out
    title = chapter or (parts[0][0] if parts else "")
    return [(title, exam_check.parse_paper(text, title))]


def _model_fingerprint(domain_key: str, definitions: list[str]) -> str:
    """母题身份指纹：学科 + 定义式集合。

    重复抽取同一份卷子时必须落到同一条 ItemModel 上（更新出现位置），而不是每次新建
    一条——否则母题库会被自己的重复抽取淹没。
    """
    payload = domain_key + "\x00" + "\x00".join(sorted(set(definitions)))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _item_model_dict(m: ItemModel) -> dict:
    radicals = jload(m.radicals, {}) or {}
    return {
        "id": m.id,
        "domain_key": m.domain_key or "",
        "title": m.title or "",
        "chapter": m.chapter or "",
        "knowledge_points": jload(m.knowledge_points, []) or [],
        "radicals": radicals,
        "incidentals": jload(m.incidentals, {}) or {},
        "solution_template": m.solution_template or "",
        "answer_expr": m.answer_expr or "",
        # 求解所需的附加约定随 radicals 一起存（models.py 无独立列，且不得改表）
        "unknown": str(radicals.get("unknown") or UNKNOWN_SYMBOL),
        "answer_select": str(radicals.get("answer_select") or ""),
        "difficulty": m.difficulty or "",
        "provenance": m.provenance or "",
        "status": m.status or "draft",
        "source_ref": m.source_ref or "",
        "created_at": m.created_at,
        "updated_at": m.updated_at,
    }


def extract_item_models(
    db: Session, domain_key: str, markdown: str, chapter: str = "",
) -> list[dict]:
    """从一份卷子抽出母题（ItemModel），落库为 ``status="draft"``。

    **radicals 自动可得，solution_template 不可自动得到**——这是本函数最重要的取舍：

    - radicals 复用 ``exam_check._definition_index``：定义式指纹是母题的身份标识，与
      问法无关。它已经在跨卷一致性检查（E017/E018）里被实测校准过（长度下限、排除
      查询式 / 裸区间 / 选项行、max_df 去高频套路），直接复用即可，不必另写一套。
    - 参数化解法**不能凭空造**。让模型「看着题目写一个 sympy 模板」等于把答案正确性
      重新交回给模型——那正是本模块要消除的漂移源。所以抽出的母题一律
      ``solution_template=""``，在人工补录或从已核实典型题导入之前，
      ``solve_isomorph`` 对它返回 ``computed=False``，``make_variation`` 拒绝产出。
      宁可母题库里躺着一批暂时不能用的草稿，也不产出一个未经验证的答案。

    顺带做两件事：
    - **槽位（incidentals）自动候选**：题干数学环境里的数字字面量按出现顺序编号为
      ``p1..pn``，原值记录在案。人工写模板时直接引用这些名字即可。
    - **答案冲突就地留痕**：同一母题在本卷内出现互斥答案时记 ``radicals.answer_conflict``，
      这正是 E018 的现场证据，补录模板时可据此判断哪个答案是对的。

    重复调用同一份卷子不会重复建档（按学科 + 定义式集合指纹去重）。
    """
    papers = _papers_from_markdown(markdown, chapter)
    if not papers:
        return []
    by_name = {name: paper for name, paper in papers}
    index, _total = exam_check._definition_index(papers)
    domain = str(domain_key or "general")

    existing: dict[str, ItemModel] = {}
    for row in db.query(ItemModel).filter(ItemModel.domain_key == domain).all():
        fp = str((jload(row.radicals, {}) or {}).get("fingerprint") or "")
        if fp:
            existing[fp] = row

    out: list[dict] = []
    for motif, locations in sorted(index.items()):
        definitions = [motif]
        fingerprint = _model_fingerprint(domain, definitions)
        occurrences: list[dict] = []
        queries: list[str] = []
        answers: list[str] = []
        kinds: list[str] = []
        stem = ""
        slots: list[tuple[int, int, str]] = []
        for pname, num in locations:
            paper = by_name.get(pname)
            if paper is None:
                continue
            block = paper.blocks.get(num) or []
            q = next((q for q in paper.questions if q.number == num), None)
            text = "\n".join(str(x) for x in block) or (q.stem if q else "")
            occurrences.append({"paper": pname, "number": num, "kind": (q.kind if q else "")})
            if q is not None and q.kind not in kinds:
                kinds.append(q.kind)
            qkey = exam_check.query_key(paper, num)
            if qkey and qkey not in queries:
                queries.append(qkey)
            _cat, content = exam_check.answer_content(paper, num)
            if content and content not in answers:
                answers.append(content)
            # 以第一个出现位置的题干作为槽位与渲染基准（同母题各处的定义式相同，
            # 题面包装可能不同；取第一个是确定性的选择，不引入随机）
            if not stem and text.strip():
                # 先截断、再算槽位：槽位是按**字符偏移**定位的，若在完整题干上算偏移、
                # 却把截断后的文本存进 stem_sample，渲染时槽位就会对不上号。
                stem = text[:_MAX_STEM_CHARS]
                slots = _stem_slots(stem)

        slot_values = {name: original for name, (_s, _e, original) in zip(_slot_names(len(slots)), slots)}
        radicals = {
            "definitions": definitions,
            "queries": queries,
            "kinds": kinds,
            "occurrences": occurrences,
            "occurrence_count": len(occurrences),
            "observed_answers": answers,
            # 同一母题给出多个互斥答案 = E018 现场。留痕以便补录模板时人工裁定。
            "answer_conflict": len(answers) > 1,
            "slot_spans": [{"name": n, "original": o} for n, (_s, _e, o) in zip(_slot_names(len(slots)), slots)],
            "unknown": UNKNOWN_SYMBOL,
            "answer_select": "",
            "fingerprint": fingerprint,
            "stem_sample": stem,
        }

        row = existing.get(fingerprint)
        if row is not None:
            # 已存在：更新出现位置与冲突证据，**不清空**人工补录过的成果。
            #
            # unknown / answer_select 必须从**旧 radicals** 继承：它们与
            # solution_template 是一套的（模板里写的就是那个未知量符号）。只保留模板、
            # 把约定重置成默认值，会让模板去解一个不存在的符号——实测确实会这样，
            # 而且比模板一起丢掉更隐蔽（看起来还能求解，解出来的却是错的）。
            prior = jload(row.radicals, {}) or {}
            if isinstance(prior, dict):
                for key in ("unknown", "answer_select"):
                    value = str(prior.get(key) or "")
                    if value:
                        radicals[key] = value
            # 人工补录过的槽位定义（可能已改成命名式）同样保留，只在为空时回填抽取值
            if not (row.incidentals and jload(row.incidentals, {}) not in ({}, None)):
                row.incidentals = jdump(slot_values)
            row.radicals = jdump(radicals)
            if chapter and not row.chapter:
                row.chapter = chapter
            db.commit()
            out.append(_item_model_dict(row))
            continue

        title = exam_check._short(motif, 60)
        row = ItemModel(
            domain_key=domain,
            title=title,
            chapter=chapter or "",
            knowledge_points=jdump([q for q in queries][:8]),
            radicals=jdump(radicals),
            incidentals=jdump(slot_values),
            solution_template="",
            answer_expr="",
            difficulty="",
            # 从生成物里抽出来的，不是人工核实的典型题：出处如实标注
            provenance="ai_constructed",
            status="draft",
            source_ref=chapter or "",
        )
        db.add(row)
        db.commit()
        existing[fingerprint] = row
        out.append(_item_model_dict(row))
    return out

# ===========================================================================
# 变式生成
# ===========================================================================

VARIATION_TYPES = ("isomorph", "procedural", "conceptual")

# 只有 isomorph 的答案能由母题模板机械求出。procedural / conceptual 改变了题目结构
# （放松条件 / 改动 radicals），原模板**不再适用**，答案必须独立验证——本函数不做，
# 只如实标 verified_by="none"，绝不把母题答案抄给它们（那会是比没有答案更糟的错误）。
_MECHANICALLY_SOLVABLE = frozenset({"isomorph"})


def _instance_dict(i: ItemInstance) -> dict:
    return {
        "id": i.id,
        "item_model_id": i.item_model_id or "",
        "incidental_values": jload(i.incidental_values, {}) or {},
        "stem": i.stem or "",
        "answer": i.answer or "",
        "variation_type": i.variation_type or "isomorph",
        "verified_by": i.verified_by or "none",
        "verified_at": i.verified_at or "",
        "source_tutorial_id": i.source_tutorial_id or "",
        "created_at": i.created_at,
        "updated_at": i.updated_at,
    }


def _effective_values(model: ItemModel, requested: dict) -> dict:
    """本次变式实际生效的参数值：调用方给的优先，缺的用母题记录的原值补。

    为什么补、以及为什么只补数字：

    - **补**：抽出的母题会把题干数学环境里的每个数字都登记成一个槽位（实测那道
      f_n(x)=x^n+2nx-2 有 5 个）。做变式时人只想改其中一两个，其余保持原值——
      而「保持原值」正是 _render_stem 对未给值槽位的行为。两边用同一组生效值，
      题面与答案才不会对不上。
    - **只补数字**：手工建的母题里 incidentals 可能是**槽位定义**而非具体值
      （models.py 注释举的例子是 {"参数": "n"}）。把 "n" 当参数值代进去会被 sympy
      解析成符号，最终得到「仍含未定符号」而不是清晰报错。所以只补
      _to_sympy_value 能解析成数的项；补不了的保持缺失，由 solve_isomorph 明确报
      「缺少母题声明的参数」——**绝不拿非数字糊弄求解器**。

    这不是猜测：补进去的都是母题自己记录在案的原值（数据库事实）。
    """
    declared = jload(model.incidentals, {}) or {}
    values: dict = {}
    if isinstance(declared, dict):
        for key, raw in declared.items():
            if _to_sympy_value(raw) is not None:
                values[str(key)] = raw
    for key, raw in dict(requested or {}).items():
        values[str(key)] = raw
    return values


def make_variation(
    db: Session, item_model_id: str, incidental_values: dict, variation_type: str = "isomorph",
) -> dict:
    """按一组具体 incidentals 生成一个 ``ItemInstance``。

    三类变式的答案处理**必须区别对待**（这是本函数唯一的关键决策）：

    - ``isomorph``（同构，radicals 不变）：调 ``solve_isomorph`` 机械求答案，
      ``verified_by="tool_symbolic"``。**求不出来就抛 409、不落库**——留一条没有答案的
      isomorph 在库里，等于宣称「这道题的答案是空的」，下游会把它当成品用。
    - ``procedural`` / ``conceptual``：结构已变，母题模板不适用。答案留空、
      ``verified_by="none"``，如实标注「待独立验证」。

    变式 ↔ 母题的关系**只存在 ``item_model_id`` 列**。项目规范一贯禁止溯源括注
    （内置试卷生成规范 forbidden_rules：「禁止标注题目来源、原题编号，或（原题…）
    （对应第 N 题的变式…）等溯源括注」），所以 stem 里绝不写入任何母题指纹、
    题号或来源文字。
    """
    model = db.get(ItemModel, item_model_id)
    if model is None:
        raise HTTPException(status_code=404, detail={"code": "item_model_not_found", "message": "母题不存在"})
    vtype = str(variation_type or "isomorph").strip().lower()
    if vtype not in VARIATION_TYPES:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_variation_type", "message": f"variation_type 必须是 {'/'.join(VARIATION_TYPES)}"},
        )
    model_dict = _item_model_dict(model)
    values = _effective_values(model, incidental_values or {})
    # 题面按母题留存的题干样本渲染，槽位以**题干解析结果**为准（位置替换，见
    # _render_stem）。未给值的槽位保留原值，因此少传参数不会破坏题面。
    base_stem = str(model_dict.get("radicals", {}).get("stem_sample") or "")
    stem = _render_stem(base_stem, _stem_slots(base_stem), values) if base_stem else ""

    if vtype in _MECHANICALLY_SOLVABLE:
        solved = solve_isomorph(model_dict, values)
        if not solved.get("computed"):
            # 不编造、也不静默降级成「无答案的同构题」
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "answer_not_computable",
                    "message": "同构变式的答案无法由母题模板机械求出，拒绝生成",
                    "reason": solved.get("error", ""),
                },
            )
        answer = str(solved.get("answer") or "")
        verified_by = "tool_symbolic"
    else:
        answer = ""
        verified_by = "none"

    instance = ItemInstance(
        item_model_id=model.id,
        incidental_values=jdump(values),
        stem=stem,
        answer=answer,
        variation_type=vtype,
        verified_by=verified_by,
        verified_at=_now_iso() if verified_by != "none" else "",
        source_tutorial_id=None,
    )
    db.add(instance)
    db.commit()
    payload = _instance_dict(instance)
    # 把本次求解的可读结论一并返回（不入库，避免 stem/answer 之外的字段污染交付）
    payload["answer_latex"] = ""
    if vtype in _MECHANICALLY_SOLVABLE:
        payload["answer_latex"] = str(solved.get("answer_latex") or "")
        payload["numeric"] = str(solved.get("numeric") or "")
    else:
        payload["numeric"] = ""
        payload["needs_independent_verification"] = True
    return payload


# ===========================================================================
# 质量记录回流
# ===========================================================================

# L0 违规里与**命题**（而非排版账目）直接相关的码。
# E017 母题重复、E018 同题多解 → 正是 ItemModel / ItemInstance 分表要根治的两类病；
# DEFECT → L1 盲解发现的题目自身缺陷（选项不完备、条件不足等），学生无解。
# 其余 E00x 是排版账目（题号加粗、分值表、留白行数），由 exam_check 的自动修复负责，
# 回流它们只会让命题规律被排版噪音淹没。
_PROPOSITION_CODES = frozenset({"E017", "E018", "DEFECT"})


def _motif_of(detail: str) -> str:
    """从违规 detail 里取回母题指纹片段，用于命题规律的示例。

    exam_check 的 detail 形如 ``母题「f_n(x)=x^n+2nx-2」出现 4 次：…``，取书名号内
    的内容即是 ``question_motifs`` 产出的定义式指纹（已截断）。取不到就返回空串——
    命题规律的示例允许缺失，但**不允许编造**。
    """
    m = re.search(r"母题「(.+?)」", str(detail or ""))
    return m.group(1) if m else ""


def _question_number_of(detail: str, violation: dict) -> int:
    """从 detail 里解析题号；解析不到用违规自带的 number（可能没有）再退回 0。"""
    for pattern in (r"第\s*(\d+)\s*题", r"#(\d+)\b"):
        m = re.search(pattern, str(detail or ""))
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                continue
    raw = violation.get("number") if isinstance(violation, dict) else None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def reflow_quality_records(
    db: Session, goal, tutorial_id: str, version: int, exam_summary: dict, l1_summary: dict,
) -> int:
    """把 L0 / L1 的发现沉淀成 ``QualityRecord``，返回本次**新写入**的条数。

    这是命题规律的冷启动素材：不需要用户先上传典型题，系统在生成过程中自己发现的
    「同题多解」「选项不完备」就自动入库，跨版本累积。

    **去重键 ``(tutorial_id, version, code, question_number)``**。重生成（同一版本再跑
    一次质量检查）绝不能把同一个缺陷重复计数——否则 ``distill_principles`` 的
    「出现 ≥ N 次」阈值会被同一次错误刷满，产出毫无根据的规律。

    只收 ``_PROPOSITION_CODES``：排版账目类违规由 exam_check 自动修复负责，把它们混进
    命题质量记录会让聚类结果全是「题号要加粗」这类与命题无关的噪音。
    """
    domain = str(getattr(goal, "domain_key", "") or "general")
    goal_id = str(getattr(goal, "id", "") or "")
    tid = str(tutorial_id or "")
    ver = int(version or 0)

    existing = {
        (r.code or "", int(r.question_number or 0))
        for r in db.query(QualityRecord)
        .filter(QualityRecord.tutorial_id == tid, QualityRecord.version == ver)
        .all()
    }

    candidates: list[dict] = []

    # ---- L0：跨卷一致性（E017 / E018）----
    for v in (exam_summary or {}).get("cross") or []:
        if not isinstance(v, dict):
            continue
        code = str(v.get("code") or "")
        if code not in _PROPOSITION_CODES:
            continue
        detail = str(v.get("detail") or "")
        candidates.append({
            "source": "l0_cross",
            "code": code,
            "paper_title": "",
            "question_number": _question_number_of(detail, v),
            "motif": _motif_of(detail),
            "detail": detail,
            "severity": str(v.get("severity") or ("blocking" if exam_check.is_blocking(code) else "advisory")),
            "question_text": "",
        })

    # ---- L0：逐卷未修复的 blocking 违规 ----
    for section in (exam_summary or {}).get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "")
        for v in section.get("violations") or []:
            if not isinstance(v, dict):
                continue
            code = str(v.get("code") or "")
            if code not in _PROPOSITION_CODES:
                continue
            if v.get("fixed"):
                continue   # 已自动修好的不再是待改进项
            if str(v.get("severity") or exam_check.SEVERITY.get(code, "blocking")) != "blocking":
                continue
            detail = str(v.get("detail") or "")
            candidates.append({
                "source": "l0_account",
                "code": code,
                "paper_title": title,
                "question_number": _question_number_of(detail, v),
                "motif": _motif_of(detail),
                "detail": detail,
                "severity": "blocking",
                "question_text": "",
            })

    # ---- L1：盲解发现的题目缺陷 ----
    for paper in (l1_summary or {}).get("papers") or []:
        if not isinstance(paper, dict):
            continue
        title = str(paper.get("title") or "")
        for d in paper.get("defects") or []:
            if not isinstance(d, dict):
                continue
            try:
                num = int(d.get("number") or 0)
            except (TypeError, ValueError):
                num = 0
            text = str(d.get("defect") or "")
            candidates.append({
                "source": "l1_defect",
                "code": "DEFECT",
                "paper_title": title,
                "question_number": num,
                "motif": "",
                "detail": text[:600],
                "severity": "blocking",
                "question_text": str(d.get("question") or d.get("blind_answer") or "")[:400],
            })

    written = 0
    for c in candidates:
        key = (c["code"], c["question_number"])
        if key in existing:
            continue
        existing.add(key)
        db.add(QualityRecord(
            domain_key=domain,
            goal_id=goal_id or None,
            tutorial_id=tid or None,
            version=ver,
            source=c["source"],
            code=c["code"],
            paper_title=c["paper_title"][:200],
            question_number=c["question_number"],
            motif=c["motif"][:200],
            detail=c["detail"],
            severity=c["severity"],
            question_text=c["question_text"],
        ))
        written += 1
    if written:
        db.commit()
    return written

# ===========================================================================
# 命题规律：聚类 → 提议 → 三态评审 → 注入
# ===========================================================================

# 每个命题缺陷码对应的**具体**整改动作。
#
# 措辞必须是「做什么 / 不做什么」的可执行动作，且与该缺陷的产生机理一一对应。
# EMG 一类工作批评的「脆弱规律」正是「要注意答案正确性」这种空话——它无法被违反，
# 也无法被验证，注入提示词只是白白吃掉预算。所以这里逐码写死机理级动作，
# 并由 statement 绑定 code + 出现次数 + 示例 motif，让规律可回溯到具体证据。
_CODE_GUIDANCE: dict[str, str] = {
    "E018": (
        "同一母题、同一所问量在一套文档里只能有一个答案：答案必须由该母题的参数化解法"
        "机械求出（ItemModel.solution_template 代入 incidentals），禁止每次出现各自独立生成。"
    ),
    "E017": (
        "命题前先按定义式指纹查重：同一母题不得在多份卷里重复考查，需要再考时必须换掉 "
        "radicals（定义式 / 所问量），或明确改用同构变式（只换 incidentals、由同一模板求答案）。"
    ),
    "DEFECT": (
        "题目条件必须自足可解：所需定义、符号、单位在题干内给全，不依赖外部材料或前题结论；"
        "客观题必须至少有一个选项与正确答案相符。缺陷题应整题替换，不要在错题上修修补补。"
    ),
}

# 没有专门话术的码也要能出规律，但同样必须绑定 code + 次数 + 示例（不许泛化成空话）
_GENERIC_GUIDANCE = "该缺陷在同一学科内反复出现，命题时必须按上列机理逐条自查后再交付。"

# DesignPrinciple 没有独立的「聚类键」列，用 rationale 前缀承载。
# 前缀是机器可解析的（``[cluster:domain|code]``），同时也是人读得懂的一句话，
# 不额外占列、也不改 models.py。distill 的幂等与 review 的「不复活」都靠它，
# 所以解析必须是**唯一一份**实现，不得在各处各写一遍字符串切割。
_CLUSTER_PREFIX = "[cluster:"


def _cluster_tag(domain_key: str, code: str) -> str:
    return f"{_CLUSTER_PREFIX}{domain_key}|{code}]"


def _parse_cluster(rationale: str) -> tuple[str, str]:
    """从 rationale 解析出 ``(domain_key, code)``；不是聚类产出的返回 ``("", "")``。"""
    text = str(rationale or "")
    if not text.startswith(_CLUSTER_PREFIX):
        return "", ""
    head = text.split("]", 1)[0] + "]"
    body = head[len(_CLUSTER_PREFIX):-1]
    domain, sep, code = body.rpartition("|")
    return (domain, code) if sep else ("", "")


def _principle_dict(p: DesignPrinciple) -> dict:
    return {
        "id": p.id,
        "domain_key": p.domain_key or "",
        "domain_name": get_profile(p.domain_key or "").display_name,
        "statement": p.statement or "",
        "principle_type": p.principle_type or "discipline",
        "scope_knowledge_points": jload(p.scope_knowledge_points, []) or [],
        "positive_refs": jload(p.positive_refs, []) or [],
        "negative_refs": jload(p.negative_refs, []) or [],
        "evidence_count": int(p.evidence_count or 0),
        "status": p.status or "proposed",
        "rationale": p.rationale or "",
        "reviewed_at": p.reviewed_at or "",
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def _quality_record_dict(r: QualityRecord) -> dict:
    return {
        "id": r.id,
        "domain_key": r.domain_key or "",
        "goal_id": r.goal_id or "",
        "tutorial_id": r.tutorial_id or "",
        "version": int(r.version or 0),
        "source": r.source or "",
        "code": r.code or "",
        "paper_title": r.paper_title or "",
        "question_number": int(r.question_number or 0),
        "motif": r.motif or "",
        "detail": r.detail or "",
        "severity": r.severity or "",
        "question_text": r.question_text or "",
        "created_at": r.created_at,
    }


def _scope_knowledge_points(db: Session, domain: str, rows: list) -> list[str]:
    """这批质量记录覆盖的**知识点名**（供 principles_for_injection 按知识点过滤）。

    必须返回知识点名，不能返回定义式指纹。实测踩过的坑：直接把 ``QualityRecord.motif``
    塞进 ``scope_knowledge_points``，而 motif 是 ``f_n(x)=x^n+2nx-2`` 这样的指纹，
    与调用方传进来的真实知识点名（「数列极限」「参数方程求导」）**永远不相交**——
    于是调用方一旦传 knowledge_points，已确认的规律就被整条静默过滤掉，
    注入形同虚设，且从日志里完全看不出来。

    知识点从母题取：``ItemModel.knowledge_points`` 存的是 ``query_key`` 抽出的「所问的量」，
    那才是知识点的表达。用 motif 回连母题，把它的知识点收集起来。

    连不上任何母题时返回**空列表**——按 models.py 的注释语义，空 = 全学科通用，
    即总是注入。这比塞进一个永远匹配不上的指纹安全得多：宁可多注入一条已确认的规律，
    也不能因为作用域写错而把人的核实成果悄悄丢掉。
    """
    motifs = {str(r.motif).strip() for r in rows if str(r.motif or "").strip()}
    if not motifs:
        return []
    points: list[str] = []
    for row in db.query(ItemModel).filter(ItemModel.domain_key == domain).all():
        radicals = jload(row.radicals, {}) or {}
        definitions = radicals.get("definitions") if isinstance(radicals, dict) else None
        if not isinstance(definitions, list):
            continue
        if not motifs.intersection({str(d).strip() for d in definitions}):
            continue
        for kp in jload(row.knowledge_points, []) or []:
            text = str(kp).strip()
            if text and text not in points:
                points.append(text)
    return points[:8]


def distill_principles(db: Session, domain_key: str, threshold: int = 3) -> list[dict]:
    """规则聚类（**确定性、零 token**）：把反复出现的同类缺陷提炼成候选命题规律。

    聚类键是 ``(domain_key, code)``。同一缺陷码在某学科累计出现 ≥ ``threshold`` 次，
    才生成一条 ``status="proposed"`` 的 DesignPrinciple——阈值挡掉「偶然一次」，
    学科维度挡掉「把数学的教训套到化学上」。

    为什么是规则聚类而不是让模型总结：模型总结出来的规律无法保证绑定证据，实测容易
    滑向「要注意答案正确性」这类不可验证的空话。这里的 statement 由代码拼装，
    **必然**带上具体 code、出现次数与示例母题指纹，可逐条回溯到 QualityRecord。

    幂等与状态语义：
    - 已存在的聚类（按 rationale 里的 ``[cluster:domain|code]`` 标记识别）不重复建档，
      只更新 ``evidence_count`` / 正例引用；proposed 态同时刷新 statement（次数变了要如实反映）；
    - **rejected 的聚类不复活**。用户已经驳回过的规律，不能因为又攒够证据就重新提议
      （与 knowledge.py「已驳回的关系不被重新生成复活」同一语义）；
    - confirmed 的聚类只累加证据数，不改写用户已确认的措辞。

    返回本次**新生成**的规律列表（不含已存在的）。
    """
    domain = str(domain_key or "general")
    try:
        limit = int(threshold)
    except (TypeError, ValueError):
        limit = 3
    limit = max(1, limit)

    records = (
        db.query(QualityRecord)
        .filter(QualityRecord.domain_key == domain)
        .order_by(QualityRecord.created_at.asc())
        .all()
    )
    if not records:
        return []

    clusters: dict[str, list[QualityRecord]] = {}
    for r in records:
        code = str(r.code or "").strip()
        if not code:
            continue
        clusters.setdefault(code, []).append(r)

    existing: dict[str, DesignPrinciple] = {}
    for p in db.query(DesignPrinciple).filter(DesignPrinciple.domain_key == domain).all():
        c_domain, c_code = _parse_cluster(p.rationale)
        if c_domain == domain and c_code:
            existing[c_code] = p

    created: list[dict] = []
    for code, rows in sorted(clusters.items()):
        if len(rows) < limit:
            continue
        prior = existing.get(code)
        if prior is not None and prior.status == "rejected":
            continue   # 已驳回：不复活
        motifs = [r.motif for r in rows if str(r.motif or "").strip()]
        seen_motifs: list[str] = []
        for m in motifs:
            if m not in seen_motifs:
                seen_motifs.append(m)
        spots = [f"{r.paper_title or '卷'}·第{r.question_number}题" for r in rows if r.question_number]
        guidance = _CODE_GUIDANCE.get(code, _GENERIC_GUIDANCE)
        rule_name = exam_check.CODES.get(code, ("", ""))[0] if code in exam_check.CODES else code
        statement = (
            f"[{code}{('·' + rule_name) if rule_name and rule_name != code else ''}] {guidance} "
            f"依据：本学科累计出现 {len(rows)} 次"
            + (f"；示例母题指纹「{exam_check._short(seen_motifs[0], 40)}」" if seen_motifs else "")
            + (f"；示例位置 {('、'.join(dict.fromkeys(spots)))[:120]}" if spots else "")
            + "。"
        )
        refs = [r.id for r in rows][:50]
        scope = _scope_knowledge_points(db, domain, rows)
        rationale = (
            _cluster_tag(domain, code)
            + f" 由 {len(rows)} 条 QualityRecord（source="
            + "/".join(sorted({r.source for r in rows if r.source}))
            + "）确定性聚类得出，非模型生成。"
        )

        if prior is not None:
            prior.evidence_count = len(rows)
            prior.positive_refs = jdump(refs)
            if not jload(prior.scope_knowledge_points, []):
                prior.scope_knowledge_points = jdump(scope)
            if prior.status == "proposed":
                # 证据变了，措辞也要如实反映（confirmed 的用户措辞不动）
                prior.statement = statement
                prior.rationale = rationale
            db.commit()
            continue

        principle = DesignPrinciple(
            domain_key=domain,
            statement=statement,
            principle_type="discipline" if domain not in ("", "general") else "general",
            scope_knowledge_points=jdump(scope),
            positive_refs=jdump(refs),
            negative_refs=jdump([]),
            evidence_count=len(rows),
            status="proposed",
            rationale=rationale,
        )
        db.add(principle)
        db.commit()
        existing[code] = principle
        created.append(_principle_dict(principle))
    return created


def review_principle(db: Session, principle_id: str, action: str, rationale: str = "") -> dict:
    """三态流转 ``proposed → confirmed / rejected``（参照 knowledge.review_proposal）。

    只有 ``confirmed`` 的规律会被 ``principles_for_injection`` 取到——未验证的经验不得
    影响交付。``rejected`` 是终态：``distill_principles`` 不会把它复活。
    """
    principle = db.get(DesignPrinciple, principle_id)
    if principle is None:
        raise HTTPException(status_code=404, detail={"code": "principle_not_found", "message": "命题规律不存在"})
    act = str(action or "").strip().lower()
    if act not in ("confirm", "reject"):
        raise HTTPException(
            status_code=422, detail={"code": "invalid_action", "message": "action 必须是 confirm / reject"},
        )
    if principle.status != "proposed":
        raise HTTPException(status_code=409, detail={"code": "already_reviewed", "message": "该规律已处理"})
    principle.status = "confirmed" if act == "confirm" else "rejected"
    # 保留聚类标记（distill 的幂等与「不复活」都靠它），把用户理由追加在后面。
    # 标记从原 rationale 解析后重建，不做裸字符串切割。
    c_domain, c_code = _parse_cluster(principle.rationale)
    head = _cluster_tag(c_domain, c_code) if (c_domain or c_code) else _cluster_tag(
        principle.domain_key or "general", ""
    )
    note = str(rationale or "").strip()
    principle.rationale = (head + (f" 评审意见：{note}" if note else "")).strip()
    principle.reviewed_at = _now_iso()
    db.commit()
    return _principle_dict(principle)


def principles_for_injection(
    db: Session, domain_key: str, knowledge_points: list[str] | None = None,
    budget_chars: int = DEFAULT_SOFT_BUDGET,
) -> str:
    """把**已确认**的命题规律拼成一段可注入提示词的文本；超预算按证据强度裁剪。

    三条不可让步的规则：

    1. **只注入 ``status="confirmed"``**。``proposed`` 是未经人核实的候选，注入它等于让
       一条没人验证过的经验去影响交付——与 KnowledgeProposal / ConceptRelation 的
       三态语义一致（未确认不入图、不注入）。
    2. **预算裁剪复用 teaching_profile.select_rules 的思路**（同一套「按成本累加、
       超预算就跳过并记录、不静默截断」的做法）。排序是 ``evidence_count`` 降序、
       创建时间升序：证据越强的越先进，预算不够时被丢的一定是证据最弱的那条，
       裁剪结果因此可解释。
    3. **返回空串就是空串**，不编造任何「一般性建议」来填空。没有已确认的规律时，
       提示词里就不该出现这一段。

    知识点过滤：``scope_knowledge_points`` 为空表示该学科通用（总是注入）；非空则要求与
    调用方给的知识点有交集。调用方没给知识点时，只按学科过滤（例如做整体预览）。
    """
    domain = str(domain_key or "general")
    rows = (
        db.query(DesignPrinciple)
        .filter(DesignPrinciple.domain_key == domain, DesignPrinciple.status == "confirmed")
        .all()
    )
    if not rows:
        return ""

    wanted = {str(k).strip() for k in (knowledge_points or []) if str(k).strip()}
    picked: list[DesignPrinciple] = []
    for p in rows:
        scope = {str(s).strip() for s in (jload(p.scope_knowledge_points, []) or []) if str(s).strip()}
        if scope and wanted and not (scope & wanted):
            continue
        picked.append(p)
    if not picked:
        return ""

    picked.sort(key=lambda p: (-int(p.evidence_count or 0), str(p.created_at or "")))
    try:
        budget = int(budget_chars)
    except (TypeError, ValueError):
        budget = DEFAULT_SOFT_BUDGET

    kept: list[str] = []
    used = 0
    for p in picked:
        line = f"- {str(p.statement or '').strip()}"
        cost = len(line) + 1
        if budget > 0 and used + cost > budget:
            continue
        used += cost
        kept.append(line)
    if not kept:
        return ""
    return (
        "【命题规律（已由人核实，出题时必须遵守）】\n" + "\n".join(kept)
    )

# ===========================================================================
# CRUD
# ===========================================================================

def _get_model(db: Session, item_model_id: str) -> ItemModel:
    row = db.get(ItemModel, item_model_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "item_model_not_found", "message": "母题不存在"})
    return row


def list_item_models(
    db: Session, domain_key: str = "", status: str = "", *, limit: int = 200, offset: int = 0,
) -> dict:
    """母题列表：按学科 / 状态过滤，冲突母题优先（那是最需要补录模板的一批）。"""
    q = db.query(ItemModel)
    if domain_key:
        q = q.filter(ItemModel.domain_key == str(domain_key))
    if status:
        q = q.filter(ItemModel.status == str(status))
    total = q.count()
    rows = q.order_by(ItemModel.created_at.desc()).limit(max(1, int(limit))).offset(max(0, int(offset))).all()
    items = [_item_model_dict(r) for r in rows]
    # 答案冲突的排前面：它们就是「同题多解」的现场，最该先被人补录模板
    items.sort(key=lambda d: (not bool(d["radicals"].get("answer_conflict")), d.get("created_at") or ""))
    return {
        "total": total,
        "items": items,
        "conflicts": sum(1 for d in items if d["radicals"].get("answer_conflict")),
        "solvable": sum(1 for d in items if d["solution_template"] or d["answer_expr"]),
    }


def get_item_model(db: Session, item_model_id: str) -> dict:
    """母题详情：附带它已产出的全部变式（变式↔母题关系只在这里体现）。"""
    row = _get_model(db, item_model_id)
    payload = _item_model_dict(row)
    payload["instances"] = list_instances(db, item_model_id=row.id, limit=200)
    return payload


def patch_item_model(db: Session, item_model_id: str, payload) -> dict:
    """补录母题的参数化解法与求解约定。

    **入库前必须先用 sympy 试解析**（``parse_sympy``）。理由：模板是数据，人会写错；
    把 ``9**9**9``、``x.__class__`` 这类东西存进库，等到生成变式时才失败，
    错误现场离原因很远，排查成本高。试解析只检查语法与规模（不做代入求解），
    成本是一次 AST 解析，可以接受。

    ``unknown`` 与 ``answer_select`` 存在 radicals 里——models.py 没有独立列，
    而本模块不得改表。radicals 本来就是「决定认知要求的结构元素」，把求解约定放这里
    在语义上也成立（约定属于母题结构的一部分，不是表面特征）。
    """
    row = _get_model(db, item_model_id)
    radicals = jload(row.radicals, {}) or {}
    if not isinstance(radicals, dict):
        radicals = {}

    for field_name in ("title", "chapter", "solution_template", "answer_expr", "difficulty", "provenance", "status", "source_ref"):
        value = getattr(payload, field_name, None)
        if value is not None:
            setattr(row, field_name, str(value))

    kp = getattr(payload, "knowledge_points", None)
    if kp is not None:
        row.knowledge_points = jdump([str(k) for k in kp])

    inc = getattr(payload, "incidentals", None)
    if inc is not None:
        row.incidentals = jdump({str(k): v for k, v in dict(inc).items()})

    unknown = getattr(payload, "unknown", None)
    if unknown is not None:
        name = str(unknown).strip()
        # 未知量必须是合法 sympy 符号名，否则求解时会变成一个未定义的表达式
        if name and not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_unknown", "message": f"unknown 必须是合法符号名，收到 {unknown!r}"},
            )
        radicals["unknown"] = name or UNKNOWN_SYMBOL

    select = getattr(payload, "answer_select", None)
    if select is not None:
        s = str(select).strip().lower()
        if s and s not in ANSWER_SELECTORS:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_answer_select",
                    "message": f"answer_select 必须是 {'/'.join(ANSWER_SELECTORS)} 之一（或空串）",
                },
            )
        radicals["answer_select"] = s

    # 模板试解析：不合法就整体回滚（前面 setattr 的改动不落库）
    for field_name in ("answer_expr", "solution_template"):
        text = str(getattr(row, field_name, "") or "").strip()
        if not text:
            continue
        try:
            parse_sympy(text, what=field_name)
        except TemplateError as exc:
            db.rollback()
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_solution_template", "message": str(exc), "field": field_name},
            ) from exc

    row.radicals = jdump(radicals)
    db.commit()
    return _item_model_dict(row)


def list_instances(
    db: Session, item_model_id: str = "", *, variation_type: str = "", limit: int = 200, offset: int = 0,
) -> list[dict]:
    q = db.query(ItemInstance)
    if item_model_id:
        q = q.filter(ItemInstance.item_model_id == str(item_model_id))
    if variation_type:
        q = q.filter(ItemInstance.variation_type == str(variation_type))
    rows = q.order_by(ItemInstance.created_at.desc()).limit(max(1, int(limit))).offset(max(0, int(offset))).all()
    return [_instance_dict(r) for r in rows]


def list_principles(
    db: Session, domain_key: str = "", status: str = "", *, limit: int = 200, offset: int = 0,
) -> dict:
    """命题规律列表：按学科 / 状态过滤，证据多的排前面。"""
    q = db.query(DesignPrinciple)
    if domain_key:
        q = q.filter(DesignPrinciple.domain_key == str(domain_key))
    if status:
        q = q.filter(DesignPrinciple.status == str(status))
    total = q.count()
    rows = (
        q.order_by(DesignPrinciple.evidence_count.desc(), DesignPrinciple.created_at.asc())
        .limit(max(1, int(limit))).offset(max(0, int(offset))).all()
    )
    items = [_principle_dict(r) for r in rows]
    return {
        "total": total,
        "items": items,
        "confirmed": sum(1 for d in items if d["status"] == "confirmed"),
        "proposed": sum(1 for d in items if d["status"] == "proposed"),
        "rejected": sum(1 for d in items if d["status"] == "rejected"),
    }


def list_quality_records(
    db: Session, domain_key: str = "", code: str = "", tutorial_id: str = "",
    *, limit: int = 200, offset: int = 0,
) -> dict:
    """质量记录列表：按学科 / 缺陷码 / 教程过滤，最新在前。"""
    q = db.query(QualityRecord)
    if domain_key:
        q = q.filter(QualityRecord.domain_key == str(domain_key))
    if code:
        q = q.filter(QualityRecord.code == str(code))
    if tutorial_id:
        q = q.filter(QualityRecord.tutorial_id == str(tutorial_id))
    total = q.count()
    rows = q.order_by(QualityRecord.created_at.desc()).limit(max(1, int(limit))).offset(max(0, int(offset))).all()
    items = [_quality_record_dict(r) for r in rows]
    codes: dict[str, int] = {}
    for d in items:
        codes[d["code"]] = codes.get(d["code"], 0) + 1
    return {"total": total, "items": items, "by_code": codes}


def preview_injection(
    db: Session, domain_key: str, knowledge_points: list[str] | None = None,
    budget_chars: int = DEFAULT_SOFT_BUDGET,
) -> dict:
    """注入预览：返回文本与统计，供前端核对「哪些规律会被注入、哪些被预算裁掉」。"""
    text = principles_for_injection(db, domain_key, knowledge_points, budget_chars)
    confirmed = (
        db.query(DesignPrinciple)
        .filter(DesignPrinciple.domain_key == str(domain_key or "general"), DesignPrinciple.status == "confirmed")
        .count()
    )
    lines = [l for l in text.split("\n") if l.startswith("- ")] if text else []
    return {
        "text": text,
        "chars": len(text),
        "budget_chars": int(budget_chars or 0),
        "injected": len(lines),
        "confirmed_total": int(confirmed or 0),
        "dropped": max(0, int(confirmed or 0) - len(lines)),
    }