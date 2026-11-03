# -*- coding: utf-8 -*-
"""实践性教程「可执行性」的确定性校验（L0，零模型调用、零 token）。

设计依据（与 ``exam_check`` / ``quote_check`` 同源：把规范里已经写死的铁律变成代码）：

``format_specs``（数据库 format_specs 表 name="实践性教程规范" scene="practical_tutorial"）
的 ``forbidden_rules`` 第一条：**禁止编造功能、快捷键、命令、操作入口或界面元素**；
``required_rules``：操作说明必须明确、具体、可执行——**入口、步骤、参数、预期结果、
验证方式齐全**；``custom_markdown``「操作步骤写法」第 2 条：预期结果写「看到什么」，
验证方式写「怎么确认」。

现状缺口：``engine.check_structure`` 只对 **v1** 结构的 ``steps`` 校验
``expected_result`` / ``verification``，而 v2 的 ``content`` 块里 ``type=="steps"``
完全不校验（那里只查「type 合法 + body 非空」）。实测库内 99 个版本有 110 个 v2
steps 块，全部裸奔。本模块补齐这个缺口，并新增两项确定性事实检查：代码语法、命令存在性。

误判防护（全部是**实测**踩出来的，改这里前先读完）：

1. **P002 只解析「已闭合」的围栏，且按围栏长度配对**。实测某个 body 用 ````markdown
   四反引号包了一个 ```python 三反引号示例，朴素正则把后文散文（「## 小结\n到这里结束。」）
   一起吞进代码块送去 ast.parse，报出「invalid character '。'」的假阳性。
2. **P002 跳过练习留白与缩进片段**。实测 4 个 python 失败样本里 3 个是刻意留白
   （``# 在此补全一行``）与缩进片段（``    a, b = b, a % b``）——那是教学设计，不是语法错。
3. **P003 绝不对 PowerShell 代码块做 which 探测**。实测库内命令行围栏 86 个是
   powershell、3 个 bash、3 个 bat，而 PowerShell 的首词是 Cmdlet（``Get-ChildItem``、
   ``Where-Object``），``shutil.which`` 对它们 100% 返回 None。不加这道闸，一份教程会
   报出上百条「命令可能不存在」，全是假的。
4. **P003 的 which 失败不等于命令不存在**：``docker`` / ``g++`` / ``ls`` / ``cat`` /
   ``grep`` / ``echo`` / ``mkdir`` 在未安装或 Windows 环境下同样 which 不到（实测这 7 个
   在本机全为 False）。所以维护「Shell 内建 / 关键字」与「通用工具」两份白名单，
   只有既 which 不到、又不在白名单、又长得像命令名的 token 才报——而且**只报 advisory**，
   **绝不执行任何命令**。
5. **P001 按「顶层步骤 + 其子项」聚合判定**，且**一个块只报一条**。实测 785 个步骤行里
   243 行不含预期/验证措辞，但它们绝大多数是子项（``- 失败：…``、``- 常见情况：…``）——
   预期与验证写在子项里，逐行判会把合规教程判成大面积缺项。

本模块**只判定不改写**：步骤缺预期结果、命令可能不存在，都没有唯一正确的修法
（补什么内容要回到工具文档核实）。因此全部 ``auto_fixable=False``。
"""
from __future__ import annotations

import ast
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------------ 规范条文

_BASIS_STEPS = (
    "实践性教程规范 required_rules：操作说明必须明确、具体、可执行——入口、步骤、参数、"
    "预期结果、验证方式齐全；custom_markdown「操作步骤写法」第 2 条：预期结果写「看到什么」，"
    "验证方式写「怎么确认」"
)
_BASIS_CODE = (
    "实践性教程规范 forbidden_rules：禁止编造功能、命令、操作入口；required_rules：每个核心功能"
    "至少配一个真实可运行的示例（语法错的示例不可能运行）"
)
_BASIS_COMMAND = (
    "实践性教程规范 forbidden_rules：禁止编造功能、快捷键、命令、操作入口或界面元素"
)
_BASIS_NOTATION = (
    "实践性教程规范 required_rules：操作说明必须明确、具体、可执行"
    "（同一篇里快捷键与菜单路径格式不统一，读者无法照做）"
)

CODES = {
    "P001": ("操作步骤缺「预期结果」或「验证方式」", _BASIS_STEPS),
    "P002": ("示例代码语法错误（不可运行）", _BASIS_CODE),
    "P003": ("命令可能不存在或需安装", _BASIS_COMMAND),
    "P004": ("快捷键 / 菜单路径格式在同一篇内不统一", _BASIS_NOTATION),
}


@dataclass
class Violation:
    """一条确定性违规（结构与 ``exam_check.Violation`` 逐字同构，便于同一套报告消费）。"""

    code: str
    rule: str
    basis: str
    detail: str
    auto_fixable: bool = False
    fixed: bool = False

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.code, "blocking")

    @property
    def blocking(self) -> bool:
        """未修复且属 blocking 级才算阻塞交付（已修好的不该再拦）。"""
        return self.severity == "blocking" and not self.fixed

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "rule": self.rule,
            "basis": self.basis,
            "detail": self.detail,
            "auto_fixable": self.auto_fixable,
            "fixed": self.fixed,
            "severity": self.severity,
        }


# P002 是唯一的 blocking：语法错的代码块**确定**跑不起来，读者照着做必然失败，
# 而且是纯事实判定（ast.parse），没有假阳性空间——前提是守住上面 1、2 两条防护。
# P001/P003/P004 全是 advisory：
#   P001 靠措辞启发式，规范未穷举的合理写法会被误伤；
#   P003 的 which 失败可能只是「没装」（实测 docker/g++/ls 在本机全 False）；
#   P004 是排版偏好。
# 把它们算进 blocking 会让几乎每份实践教程都变成「待改进」，反而淹没 P002。
SEVERITY: dict[str, str] = {
    "P001": "advisory",   # 步骤三要素（措辞启发式）
    "P002": "blocking",   # 代码语法错：确定跑不起来
    "P003": "advisory",   # 命令存在性（which 失败 ≠ 命令不存在）
    "P004": "advisory",   # 记法一致性
}


def is_blocking(code: str) -> bool:
    return SEVERITY.get(code, "blocking") == "blocking"


# ------------------------------------------------------------------ section 取正文

def iter_blocks(section: dict) -> list[dict]:
    """取出 section 里的全部 content 块（只保留 dict）。"""
    blocks = (section or {}).get("content")
    if not isinstance(blocks, list):
        return []
    return [b for b in blocks if isinstance(b, dict)]


def section_body(section: dict) -> str:
    """拼接 section 全部 content 块的 body（取法与 ``exam_check.section_body`` 一致）。

    必须拼接而不是只看第一块：模型有时把操作步骤拆成多块，只看第一块会漏检。
    """
    parts = [str(b.get("body", "") or "") for b in iter_blocks(section)]
    parts = [p for p in parts if p.strip()]
    if not parts:
        return str((section or {}).get("markdown", "") or "")
    return "\n\n".join(parts)


def _block_where(section: dict, block: dict, index: int) -> str:
    """定位一个 content 块的可读描述，用于 detail。"""
    title = str(block.get("title", "") or "").strip()
    sec_title = str((section or {}).get("title", "") or "").strip()
    if title:
        return f"「{_short(sec_title, 16)}」第 {index + 1} 块「{_short(title, 20)}」"
    return f"「{_short(sec_title, 16)}」第 {index + 1} 块"


def _short(text: str, limit: int = 42) -> str:
    """截断成可读片段，用于 detail 展示。"""
    t = str(text or "")
    return t if len(t) <= limit else t[:limit] + "…"


# ------------------------------------------------------------------ 代码围栏解析

@dataclass
class CodeFence:
    """一个围栏代码块。``closed=False`` 表示文档里没收场标记（不送语法检查）。"""

    lang: str
    code: str
    lineno: int
    closed: bool = True


_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([A-Za-z0-9_+\-.]*)\s*$")


def parse_code_fences(text: str) -> list[CodeFence]:
    """按**围栏长度配对**提取代码块。

    这是 P002 的第一道防假阳性闸门（见模块 docstring 第 1 条）：Markdown 允许用
    ```````` 四个反引号包住带 ```python 的示例，此时内层三反引号不是围栏边界。
    朴素正则会把示例后文（实测是「## 小结 / 到这里结束。」）一起当成代码送去
    ast.parse，报出「invalid character '。'」。配对规则与 CommonMark 一致：
    **收场标记必须与开场标记同字符、且长度不小于开场**。
    """
    out: list[CodeFence] = []
    lines = str(text or "").split("\n")
    open_marker: str | None = None
    open_lang = ""
    open_line = 0
    buf: list[str] = []
    for idx, raw in enumerate(lines, 1):
        m = _FENCE_RE.match(raw)
        if open_marker is None:
            if m:
                open_marker, open_lang, open_line, buf = m.group(1), m.group(2), idx, []
            continue
        # 在围栏内：只有同字符且不短于开场的标记行才收场
        if m and m.group(1)[0] == open_marker[0] and len(m.group(1)) >= len(open_marker):
            out.append(CodeFence(open_lang.lower(), "\n".join(buf), open_line, True))
            open_marker = None
            continue
        buf.append(raw)
    if open_marker is not None:
        # 未闭合：整段可能是被吞掉的正文，不能当代码判语法（见 docstring 第 1 条）
        out.append(CodeFence(open_lang.lower(), "\n".join(buf), open_line, False))
    return out


# 练习留白标记：这些块是**故意**不完整的（让读者自己补一行），报语法错纯属假阳性。
_BLANK_MARK_RE = re.compile(
    r"在此补全|在此填写|请补全|请填写|待补全|自行补全|补全一行|TODO|FIXME|\bpass\b\s*#|"
    r"^\s*\.\.\.\s*$|<[^>\n]{1,24}>",
    re.M,
)


def is_incomplete_code(code: str) -> bool:
    """这个代码块是不是**刻意不完整**（练习留白 / 占位符 / 缩进片段）。"""
    text = str(code or "")
    if _BLANK_MARK_RE.search(text):
        return True
    # 缩进片段：整块以缩进行开头，说明它是从更大程序里截出来的一段（实测踩过）
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        return raw[:1] in (" ", "\t")
    return False


# ------------------------------------------------------------------ P001 步骤三要素

# 「预期结果」措辞：规范 custom_markdown 要求写「看到什么」（输出文本 / 界面状态）。
# 词表按实测校准：库内 785 个步骤行里「预期」345 次、「看到」28 次，
# 另有「应显示 / 应返回 / 屏幕上出现」这类同义表述。
_EXPECTED_RE = re.compile(
    r"预期|应显示|应该显示|应返回|应出现|应看到|应无|不再出现|不再有|"
    r"会看到|会显示|会出现|看到|出现|屏幕上|界面上|结果是|结果应为|输出为|输出是|"
    r"显示为|显示成|返回一|生效|无报错|没有报错"
)
# 「验证方式」措辞：规范要求写「怎么确认」。实测「验证」364 次、「确认」63 次、「检查」89 次。
_VERIFY_RE = re.compile(
    r"验证|确认|检查|核对|判据|自查|复核|对照|再看|看一下|确保|怎么知道|如何知道|能否重跑|重跑"
)
# **操作性闸门**：只有「操作工具」的步骤才要求预期结果与验证方式。
#
# 这道闸门是实测逼出来的：库内 71 个「既无预期也无验证」的步骤里，42 个属于
# **非操作性**内容——数学推导（「验算：任取 $A$ 的第 $i$ 行与 $A^{-1}$ 的第 $j$ 列作内积」）、
# 概念辨析（「问意义来源：是不是『世界本身不再提供意义』在起作用？」）。
# 对它们要求「预期结果 / 验证方式」是把实践规范套到思辨内容上，判出来全是假阳性。
# 加闸门后块级报告从 67 条降到 18 条，留下的才是真缺项。
_OPERATIONAL_RE = re.compile(
    r"```|`[^`]{1,60}`|菜单|点击|右击|双击|单击|按下|运行|执行|输入|打开|勾选|选择|"
    r"命令行|终端|窗口|面板|对话框|选项卡|按钮|图标|界面|截图|快捷键|配置文件|环境变量"
)
# 顶层编号步骤：行首无缩进的 ``1.`` / ``2、`` / ``3)``。
# 必须认**全角右括号**「2）」：模型输出中文步骤时全角是常态，漏掉它会让整块步骤
# 解析不出来（parse_steps 返回空 → P001 静默不判，是漏判而非误判，更隐蔽）。
_TOP_STEP_RE = re.compile(r"^(\d+)[\.、)）]\s*(.*)$")
# 任意列表项（含子项 ``- 预期：…``）
_ANY_ITEM_RE = re.compile(r"^(?:\d+[\.、)）]|[-*+])\s*(.*)$")


@dataclass
class StepItem:
    """一个顶层步骤及其全部子项文本（聚合判定的单位，见 docstring 第 5 条）。"""

    number: int
    lineno: int
    text: str
    sub: list[str] = field(default_factory=list)

    @property
    def whole(self) -> str:
        return "\n".join([self.text, *self.sub])

    @property
    def has_expected(self) -> bool:
        return bool(_EXPECTED_RE.search(self.whole))

    @property
    def has_verify(self) -> bool:
        return bool(_VERIFY_RE.search(self.whole))


def parse_steps(body: str) -> list[StepItem]:
    """把 steps 块的 body 解析成「顶层步骤 + 子项」列表；跳过代码围栏内的行。"""
    out: list[StepItem] = []
    current: StepItem | None = None
    fence: str | None = None
    for idx, raw in enumerate(str(body or "").split("\n"), 1):
        stripped = raw.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            continue
        if fence is not None:
            continue
        if not stripped:
            continue
        top = _TOP_STEP_RE.match(stripped) if raw[:1] not in (" ", "\t") else None
        if top:
            current = StepItem(int(top.group(1)), idx, top.group(2))
            out.append(current)
            continue
        item = _ANY_ITEM_RE.match(stripped)
        if item and current is not None:
            current.sub.append(item.group(1))
            continue
        # 非列表的续行也算进当前步骤（实测「预期：…」有时直接换行写）
        if current is not None:
            current.sub.append(stripped)
    return out


def check_steps_elements(section: dict) -> list[Violation]:
    """P001：``type=="steps"`` 块里的**操作性步骤**是否给出「预期结果」与「验证方式」。

    这是补 ``engine.check_structure`` 的 v2 缺口：那里只校验 v1 的 ``steps`` 列表项，
    v2 的 content 块只查「type 合法 + body 非空」。实测库内 99 个版本有 110 个 v2
    steps 块、584 个步骤，此前全部裸奔。

    三条判定约束（都是实测校准出来的，见 ``_OPERATIONAL_RE`` 与模块 docstring）：

    1. 非操作性块整体跳过：数学推导、概念辨析不适用「预期结果 / 验证方式」。
    2. 只报**两者皆缺**的步骤。「预期与验证合并写在一句里」是实测大量存在的合理写法
       （「**只修这一处，重新编译**。验证：对比报错条数是否明显减少」），
       分别判会把 103 个只有验证措辞的合规步骤全判违规。
    3. **一个块只报一条**（缺失步骤号聚合进 detail），与 exam_check 对 E011 的处理一致：
       逐条报会让一个块产出十几条同质 advisory，把 quality_report 淹掉。
    """
    v: list[Violation] = []
    for index, block in enumerate(iter_blocks(section)):
        if str(block.get("type", "")).strip().lower() != "steps":
            continue
        body = str(block.get("body", "") or "")
        if not body.strip() or not _OPERATIONAL_RE.search(body):
            continue
        steps = parse_steps(body)
        if not steps:
            continue
        lacking = [s.number for s in steps if not s.has_expected and not s.has_verify]
        if not lacking:
            continue
        v.append(Violation(
            "P001", *CODES["P001"],
            f"{_block_where(section, block, index)}共 {len(steps)} 步，其中 {len(lacking)} 步"
            f"（步骤 {_nums(lacking)}）既没写「预期结果」也没写「验证方式」；"
            f"规范要求预期写「看到什么」、验证写「怎么确认」",
        ))
    return v


def _nums(numbers: list[int], limit: int = 8) -> str:
    shown = "、".join(str(n) for n in numbers[:limit])
    return shown + (" 等" if len(numbers) > limit else "")


# ------------------------------------------------------------------ P002 代码语法

_PYTHON_LANGS = ("python", "py", "python3", "py3")
_JS_LANGS = ("javascript", "js", "jsx", "mjs", "cjs", "typescript", "ts")
# 括号平衡检查用：JS/TS 不引入 node 依赖，只做确定性词法层面的配平
_PAIRS = {")": "(", "]": "[", "}": "{"}
_OPENERS = set("([{")


def _strip_js_literals(code: str) -> str:
    """去掉 JS 的注释与字符串字面量，只留下括号结构（避免把 ``"}"`` 当成括号）。"""
    out: list[str] = []
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        two = code[i:i + 2]
        if two == "//":
            j = code.find("\n", i)
            i = n if j < 0 else j
            continue
        if two == "/*":
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch in "'\"`":
            quote = ch
            i += 1
            while i < n:
                if code[i] == "\\":
                    i += 2
                    continue
                if code[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _js_balance_error(code: str) -> str | None:
    """JS 括号配平检查：返回错误描述，或 None 表示配平。

    只做确定性检查（不引入 node）：教程里的 JS 片段常常是不完整的表达式，
    语法层面的深层校验必然假阳性，所以只抓「括号数量不配平」这一铁的事实——
    括号不配平的代码在任何引擎里都跑不起来。
    """
    text = _strip_js_literals(code)
    stack: list[tuple[str, int]] = []
    line = 1
    for ch in text:
        if ch == "\n":
            line += 1
            continue
        if ch in _OPENERS:
            stack.append((ch, line))
        elif ch in _PAIRS:
            if not stack:
                return f"第 {line} 行出现多余的闭合括号「{ch}」"
            opener, oline = stack.pop()
            if opener != _PAIRS[ch]:
                return f"第 {line} 行的「{ch}」与第 {oline} 行的「{opener}」不配对"
    if stack:
        opener, oline = stack[-1]
        return f"第 {oline} 行的「{opener}」没有闭合（共 {len(stack)} 个未闭合）"
    return None


def check_code_syntax(section: dict) -> list[Violation]:
    """P002：``python`` 块用 ``ast.parse``、``javascript`` 块用括号配平做语法检查。

    三重防假阳性闸门（见模块 docstring 第 1、2 条）：未闭合围栏不查、练习留白不查、
    缩进片段不查。守住这三条后，报出来的一定是「读者照抄必然失败」的真错。
    """
    v: list[Violation] = []
    seen: set[tuple[str, int]] = set()
    for index, block in enumerate(iter_blocks(section)):
        body = str(block.get("body", "") or "")
        if not body.strip():
            continue
        for fence in parse_code_fences(body):
            if not fence.closed:
                continue
            code = fence.code
            if not code.strip():
                continue
            if is_incomplete_code(code):
                continue
            if fence.lang in _PYTHON_LANGS:
                try:
                    ast.parse(code)
                    continue
                except (SyntaxError, ValueError) as exc:
                    lineno = getattr(exc, "lineno", None)
                    msg = str(getattr(exc, "msg", "") or exc)
                    where = (
                        f"{_block_where(section, block, index)}第 {fence.lineno} 行起的 ```python 块"
                        + (f"第 {lineno} 行" if lineno else "")
                    )
                    key = (where, fence.lineno)
                    if key in seen:
                        continue
                    seen.add(key)
                    v.append(Violation(
                        "P002", *CODES["P002"],
                        f"{where}语法错误：{msg}（示例必须可直接运行）",
                    ))
            elif fence.lang in _JS_LANGS:
                err = _js_balance_error(code)
                if not err:
                    continue
                where = f"{_block_where(section, block, index)}第 {fence.lineno} 行起的 ```{fence.lang} 块"
                key = (where, fence.lineno)
                if key in seen:
                    continue
                seen.add(key)
                v.append(Violation(
                    "P002", *CODES["P002"],
                    f"{where}括号不配平：{err}（示例必须可直接运行）",
                ))
    return v


# ------------------------------------------------------------------ P003 命令存在性

# 计算机类领域（``disciplines.COMPUTER_CLI`` 的 key 与映射到它的学科 key）。
# 只有这些领域才做命令探测：其它领域的「命令」多半是领域专用记法，which 无意义。
COMPUTER_DOMAINS = frozenset({"computer_cli", "cs_it"})

# which 能探测的命令行语言。**powershell/ps1/pwsh 刻意排除**：实测库内 86 个 powershell
# 围栏的首词全是 Cmdlet（Get-ChildItem / Where-Object / Select-Object），
# shutil.which 对 Cmdlet 100% 返回 None（Cmdlet 是 shell 内建命令，不是可执行文件），
# 探测它们只会产出成片假阳性。
_WHICHABLE_LANGS = frozenset({"bash", "sh", "shell", "zsh", "console", "terminal", "cmd", "bat", "dos"})

# Shell 内建与关键字：它们本来就不是可执行文件，which 不到是正常的。
_SHELL_BUILTINS = frozenset("""
echo cd pwd ls dir cat type more less head tail grep egrep fgrep sed awk cut tr sort uniq wc
mkdir rmdir rm del copy cp mv move ren erase touch ln link chmod chown chgrp stat file test
export unset set local readonly declare typeset alias unalias source history jobs bg fg wait
if then else elif fi for while until do done case esac function in select time coproc return
break continue exit shift getopts trap eval exec command builtin let printf read readarray
mapfile true false umask pushd popd dirs suspend disown enable help logout shopt compgen
complete compopt caller : . [ [[ ]] { } ( ) | & && || > < >> 2> ; ! * @ # $ ? ~ ^ = + -
start call setlocal endlocal goto errorlevel rem cls ver vol path assoc ftype mklink xcopy
robocopy find findstr choice pause title attrib icacls net ping ipconfig tasklist taskkill
""".split())

# 通用工具白名单：**which 失败不等于命令不存在**，可能只是本机没装。
# 实测本机 docker / g++ / ls / cat / grep / echo / mkdir 全部 which=False，
# 但没有任何人会说「docker 是编造的命令」。这份白名单收录跨平台常见工具，
# 只有既 which 不到、又不在这两份名单里的 token 才报——而且只报 advisory。
_KNOWN_TOOLS = frozenset("""
python python3 pip pip3 py conda uv poetry pipx virtualenv
node npm npx yarn pnpm bun deno tsc eslint prettier vite webpack
git gh svn hg
docker docker-compose podman kubectl helm terraform ansible vagrant
gcc g++ cc clang clang++ make cmake ninja gdb lldb valgrind
java javac mvn gradle kotlin kotlinc scala scalac sbt dotnet cargo rustc go gofmt
php composer ruby gem bundle rails perl lua R Rscript julia swift swiftc
curl wget ssh scp sftp rsync nc ncat telnet netstat ss lsof tcpdump dig nslookup host traceroute
tar gzip gunzip bzip2 zip unzip xz 7z zstd
ps top htop kill killall pkill free df du mount umount lsblk fdisk systemctl service journalctl
man info which whereis locate realpath basename dirname mktemp sha256sum md5sum base64 xxd
jq yq rg fd bat fzf tree watch parallel tmux screen nvim vim nano emacs code
mysql psql sqlite3 redis-cli mongo mongosh
apt apt-get yum dnf pacman brew snap choco scoop winget
aws az gcloud terraform ansible-playbook
ffmpeg convert magick pandoc latex pdflatex xelatex
""".split())

# 命令行语言的关键字 / 提示符：这些 token 不是命令名
_PROMPT_RE = re.compile(r"^[$#%>]|^\([^)]*\)\s*\$|^PS\s|^\[.*\][\$#]")
# 长得像命令名的 token（其余一律不判：变量、路径、重定向、管道片段都不是命令）
_CMD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.+\-]{1,40}$")
# 明显不是命令：变量 / 路径 / 选项 / 参数赋值
_NOT_CMD_RE = re.compile(r"^[-$./\\<>=|&!*?~@#%^+]|\.(?:py|js|ts|sh|ps1|exe|json|md|csv|txt|c|cpp|java)$|=")
# PowerShell Cmdlet 形态（Verb-Noun）：在 cmd/bat 里也不会是外部命令，跳过
_CMDLET_RE = re.compile(r"^[A-Z][a-z]+-[A-Z][A-Za-z]+$")


def _command_tokens(code: str) -> list[tuple[int, str]]:
    """提取命令行代码块里每行的首词（命令名）。

    只取**看起来像命令**的 token，其余（变量、路径、选项、管道右半、提示符）一律不判。
    这一步的保守程度直接决定 P003 的假阳性率。
    """
    out: list[tuple[int, str]] = []
    for idx, raw in enumerate(str(code or "").split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith(("#", "//", "::", ";", "<!--")):
            continue
        # 去掉行首提示符（``$ ls``、``(venv) $ ls``、``PS C:\> ls``）
        line = _PROMPT_RE.sub("", line).strip()
        if not line:
            continue
        # 管道 / 逻辑连接的后续命令也算（``a && b``、``a | b``）
        for piece in re.split(r"&&|\|\||\|", line):
            token = piece.strip().split()[0] if piece.strip() else ""
            if not token:
                continue
            token = token.strip("'\"`()")
            if not _CMD_NAME_RE.match(token) or _NOT_CMD_RE.search(token):
                continue
            if _CMDLET_RE.match(token):
                continue
            out.append((idx, token))
            break   # 一行只取第一个真正的命令名，避免把参数当命令
    return out


def probe_commands(code: str) -> list[tuple[int, str]]:
    """对一段命令行代码做存在性探测，返回 (行号, 命令名) 的**可疑**清单。

    **只探测、绝不执行**：``shutil.which`` 是路径查找，不会启动进程。
    这条边界必须写死在代码里——校验器执行教程里的命令等于把「校验」变成「运行未知代码」。
    """
    suspects: list[tuple[int, str]] = []
    for lineno, token in _command_tokens(code):
        low = token.lower()
        if low in _SHELL_BUILTINS or low in _KNOWN_TOOLS or token in _KNOWN_TOOLS:
            continue
        if shutil.which(token):
            continue
        suspects.append((lineno, token))
    return suspects


def check_commands(section: dict, *, domain_key: str = "") -> list[Violation]:
    """P003：计算机类领域下，命令行代码块的首词是否真的存在。

    ``domain_key`` 不是计算机类时直接返回空：其它领域的「命令」多是领域记法，
    which 探测没有意义（见 COMPUTER_DOMAINS 说明）。
    """
    if str(domain_key or "").strip() not in COMPUTER_DOMAINS:
        return []
    v: list[Violation] = []
    for index, block in enumerate(iter_blocks(section)):
        body = str(block.get("body", "") or "")
        if not body.strip():
            continue
        for fence in parse_code_fences(body):
            if not fence.closed or fence.lang not in _WHICHABLE_LANGS:
                continue
            if is_incomplete_code(fence.code):
                continue
            suspects = probe_commands(fence.code)
            if not suspects:
                continue
            # 去重后只展示前 6 个：一个块里同一条命令可能重复出现多次，全列出来没有信息量
            unique = list(dict.fromkeys(t for _, t in suspects))
            names = "、".join(f"`{t}`" for t in unique[:6]) + ("等" if len(unique) > 6 else "")
            v.append(Violation(
                "P003", *CODES["P003"],
                f"{_block_where(section, block, index)}第 {fence.lineno} 行起的 ```{fence.lang} 块里，"
                f"命令 {names} 在本机 PATH 中找不到（可能不存在、拼写有误，或需要安装）；"
                f"请核对工具文档，不确定时标注而非当作事实",
            ))
    return v


# ------------------------------------------------------------------ P004 记法一致性
#
# **实测校准**：库内 99 个版本 / 318 个章节里，宽松规则（把 `/`、`→`、`>` 都当菜单分隔符）
# 报出 137 条 P004，误报率 42%——`/` 命中 1072 处全是「文件/目录」「大于 / 大于等于」
# 这类并列词，`→` 命中 786 处全是「取数 → 筛选」这类流程箭头（规范模板自己就写
# 「目标 → 步骤 → 关键决策 → 结果检查」），`>` 命中 148 处大量是 Markdown 引用块符号。
# 严格化后混用数为 **0**：只在真不一致时才触发。

# 经典菜单顶级项：只有左侧是这些词才算菜单路径。
# 不用「中文词 + 分隔符 + 中文词」这种泛规则，否则流程箭头与并列词全被吞进来。
_MENU_TOP_WORDS = (
    "文件|编辑|视图|插入|格式|工具|帮助|设置|开始|主页|审阅|数据|开发|窗口|"
    "账户|首选项|偏好设置|菜单|右键|右击|资源管理器|控制面板|系统设置|项目|生成|调试|团队"
)
# 菜单路径分隔符：只认这五种（`/` 刻意排除——它在中文技术写作里压倒性地表示并列）
_MENU_SEP_STYLES = {
    "->": "箭头 ->",
    "→": "全角 →",
    "＞": "全角 ＞",
    "»": "»",
    ">": "半角 >",
}
_MENU_RE = re.compile(
    rf"(?:{_MENU_TOP_WORDS})\s*(->|→|＞|»|>)\s*[^\s<>|，。；、）)]{{1,16}}"
)

# 快捷键：修饰键与按键之间**必须有连接符**（+ / ＋ / -> / → / 空格+）。
# 不加这个约束会把「Windows 11」「Command Get」「Option 3」这类普通短语误当快捷键
# （实测宽松规则误匹配 8 处，全是这类）。
_SHORTCUT_RE = re.compile(
    r"(?i)\b(ctrl|control|alt|cmd|command|meta|win|windows|shift|option|super)\b"
    r"\s*(?:[+＋]|--|->|→)\s*"
    r"([A-Za-z0-9]{1,3}|F\d{1,2}|Esc|Space|Tab|Enter|Backspace|Del|Insert|Home|End|"
    r"PgUp|PgDn|Up|Down|Left|Right)\b"
)
# 修饰键组合（Ctrl+Alt+Del、Cmd+Opt+I）：连接符形态与上面同源
_SHORTCUT_COMBO_RE = re.compile(
    r"(?i)\b(?:ctrl|control|alt|cmd|command|meta|win|windows|shift|option|super)\b"
    r"(\s*[+＋]\s*\w+){1,4}"
)


def _shortcut_style(segment: str) -> str:
    """一个快捷键片段属于哪种连接符风格。"""
    if "＋" in segment:
        return "全角 ＋"
    if re.search(r"\s\+\s", segment):
        return "加空格 +"
    if re.search(r"\s*\+\s*", segment):
        return "紧贴 +"
    if "->" in segment or "→" in segment:
        return "箭头"
    return "其它"


def _styles(counter: dict[str, int]) -> list[str]:
    return sorted(counter)


def check_notation_consistency(section: dict) -> list[Violation]:
    """P004：同一节里快捷键 / 菜单路径的记法是否统一。

    规范要求「操作说明必须明确、具体、可执行」：同一篇里既写 ``Ctrl+C`` 又写
    ``Ctrl + C``、菜单既写 ``文件 > 保存`` 又写 ``文件 → 保存``，读者会怀疑这是两个
    不同入口。但这是**排版偏好**，判定必须极度保守（见上面实测校准）：

    1. 同类记法至少出现 3 次才判（1~2 次无法区分「不统一」与「只用了一次」）；
    2. 菜单路径左侧必须是经典菜单顶级项，分隔符不含 ``/``；
    3. 快捷键必须有连接符，且只在**正文**里找（代码块里的 ``->`` 是代码，不是菜单）；
    4. 两种风格各自占比都不低于 1/4 才报（25:1 这种压倒性主风格 + 一处笔误不值得报）。
    """
    body = section_body(section)
    if not body.strip():
        return []

    # 代码块里的 > / -> / + 是代码语法，必须排除后再判
    prose_lines: list[str] = []
    fence: str | None = None
    for raw in str(body).split("\n"):
        stripped = raw.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            continue
        if fence is None:
            prose_lines.append(raw)
    prose = "\n".join(prose_lines)

    v: list[Violation] = []

    # 两条正则会匹配到同一段文本（``Ctrl+C`` 同时命中「组合键」与「修饰键+按键」），
    # 直接累加会把 3 处快捷键算成 6 处，报告里的数字就不可信了。按 span 去重。
    sc: Counter[str] = Counter()
    taken: list[tuple[int, int]] = []
    for regex in (_SHORTCUT_COMBO_RE, _SHORTCUT_RE):
        for m in regex.finditer(prose):
            if any(not (m.end() <= s or m.start() >= e) for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            sc[_shortcut_style(m.group(0))] += 1
    sc_total = sum(sc.values())
    if len(sc) > 1 and sc_total >= 3:
        counts = sorted(sc.values(), reverse=True)
        if counts[-1] >= max(1, sc_total // 4):   # 闸门 4：次要风格不能只是零星笔误
            v.append(Violation(
                "P004", *CODES["P004"],
                f"快捷键记法在本节内不统一：{'、'.join(f'{k}×{sc[k]}' for k in _styles(sc))}"
                f"（共 {sc_total} 处）；应全篇用同一种（如统一写「Ctrl+C」）",
            ))

    menu: Counter[str] = Counter()
    for m in _MENU_RE.finditer(prose):
        menu[_MENU_SEP_STYLES.get(m.group(1), m.group(1))] += 1
    menu_total = sum(menu.values())
    if len(menu) > 1 and menu_total >= 3:
        counts = sorted(menu.values(), reverse=True)
        if counts[-1] >= max(1, menu_total // 4):
            v.append(Violation(
                "P004", *CODES["P004"],
                f"菜单路径分隔符在本节内不统一：{'、'.join(f'{k}×{menu[k]}' for k in _styles(menu))}"
                f"（共 {menu_total} 处）；应全篇用同一种（如统一写「文件 > 保存」）",
            ))
    return v


# ------------------------------------------------------------------ 对外入口

def check_practice_section(section: dict, *, domain_key: str = "") -> list[Violation]:
    """实践性教程规范 Tier-0 校验入口：返回全部违规（**只判定，不改写**）。

    参数：
    - ``section``：章节 dict（``{title, content: [{type, title, body}]}``）。
      兼容 v1 结构（顶层 ``steps`` 列表）：v1 的三要素已由 ``engine.check_structure``
      校验，但代码语法与命令存在性对 v1/v2 一视同仁。
    - ``domain_key``：领域 key。只有计算机类（``computer_cli`` / ``cs_it``）才做 P003
      命令探测。
    """
    v: list[Violation] = []
    v += check_steps_elements(section)
    v += check_code_syntax(section)
    v += check_commands(section, domain_key=domain_key)
    v += check_notation_consistency(section)
    return v


def summarize(violations: list[Violation]) -> dict[str, Any]:
    """汇总成可写进 quality_report 的结构（与 exam_check.quality_checks 同构）。

    ``passed`` 只看 blocking：步骤措辞、命令是否安装、记法风格都是提示级，
    不该把整份教程标成「待改进」，否则 P002 这个真正致命的信号会被噪音淹没。
    """
    codes = Counter(v.code for v in violations)
    blocking = [v for v in violations if v.blocking]
    return {
        "passed": not blocking,
        "codes": dict(codes),
        "blocking": len(blocking),
        "advisory": len(violations) - len(blocking),
        "violations": [v.to_dict() for v in violations],
    }
