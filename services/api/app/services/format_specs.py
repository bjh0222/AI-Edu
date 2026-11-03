"""格式规范：持久化、默认规范唯一性、Skill 式匹配与任务快照。"""
from __future__ import annotations

import re
from copy import deepcopy
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import FormatSpec, LearningGoal
from ..services import utils
from ..services.utils import jdump, jload


# 阅读教程规范的场景标识：只有它启用「按章注入材料 + 全书层后置生成」。
# 刻意用独立 scene 而不是复用 default_tutorial —— authoritative_spec_dict 对
# scene == "default_tutorial" 且无交付物的规范直接返回 {}，规范会完全不接管模板。
READING_GUIDE_SCENE = "reading_guide"


# 阅读教程规范的三个全书层节名，必须与规范 content_structure 里的节名逐字一致
# （回归测试 test_reading_outline_is_deterministic_from_material_names 会核对，改一处必须改另一处）。
# 放在代码里而不是从 content_structure 解析：解析模板文本太脆，模板改个措辞就断。
READING_BOOK_LEVEL_HEAD = ("全书认知地图", "阅读路线")
# 思想背景与学术争鸣已并入「全书认知地图」节末尾（2026-11-02 用户要求），不再单独成节，
# 故后置全书层为空。保留常量名（而非删除）是为了 _reading_outline_from_materials 的拼接
# HEAD + 各章 + TAIL 在 TAIL 为空时仍自然成立，语义也清晰（「后置全书层：当前无」）。
READING_BOOK_LEVEL_TAIL = ()


def is_reading_guide(snapshot: dict | None) -> bool:
    """本次是否走阅读教程规范的两阶段生成链路。

    判据只看 scene，不看规范名：用户可以改名字、复制副本，但 scene 是结构契约的一部分。
    返回 False 时 tutorials.py 走原有的「一批全并行 + 全量注入材料」路径，行为逐字不变。
    """
    return str((snapshot or {}).get("scene", "")).strip() == READING_GUIDE_SCENE


SOURCE_LABELS = {
    "manual": "手动选择",
    "explicit": "用户指定",
    "keyword": "关键词匹配",
    "semantic": "语义匹配",
    "default": "默认规范",
    "none": "本次不使用特殊规范",
}

# ---------------------------------------------------------------- 试卷规范字段
# 这些常量是 exam_paper 内置种子的字段原文，与前端表单里的取值逐字一致。
# 用 r"""…""" 原样保留 LaTeX 反斜杠（\begin{cases}、\(…\)），普通三引号会把
# \b 解析成退格符，导致模板里的公式变成乱码。
#
# 「deliverables」刻意留空，原因有两条，都是代码级效应，不是排版偏好：
#   1) apply_task_overrides 用「交付物名是否出现在任务文本里」判断本次只生成什么，
#      而卷名/标题很容易撞上栏目名——实测 goal「普通化学训练」+「只生成前两章的练习题」
#      命中了交付物「训练」，于是「易错辨析」被强制 forbidden，导出只剩一章。
#      试卷的节名是「线性代数期中模拟试卷」「第 1 章 … 单元检测卷」这类自由文本，
#      撞上「参考答案」「模拟试卷」的概率更高。
#   2) check_snapshot_delivery 要求 required 交付物名逐字出现在章节标题里，
#      按材料分章时标题由 apply_chapter_split 重写成「第 N 章 … 单元检测卷」，
#      任何写死的 required 名都对不上 → quality.passed=False → 教程降级。
# 分卷结构改由 content_structure 里的「分卷规则」表达：模型按节生成，
# 导出时 _render_format_spec_document 给每节补「## 中文序号、卷名」。


_EXAM_DESCRIPTION = r"""统一试卷模板：按份分节交付，一节一卷；卷首给卷面说明与题型分值分布表，卷中按题型分节给全部题目，卷末附「### 参考答案」。题型不固定：有例题来源材料时逐字沿用材料里的题型划分，没有材料时默认覆盖全部题型。试卷计分并逐题标注分值，答案详略与题后留白按客观题/主观题固定分级。"""


_EXAM_APPLICABLE_TASKS = r"""按份输出可直接计时作答的试卷：本次要求几份卷就分几节，每节一卷、自带卷面说明与卷末参考答案；不输出教程、讲解或泛化学习建议。"""


_EXAM_TARGET_READER = r"""使用电脑阅读、需要限时作答并自行核对答案与评分的学生。默认在 Obsidian 或 Markdown 阅读器中阅读，需支持 KaTeX 数学渲染与 HTML 复选框；读者已学完对应章节，试卷用于阶段性检测与模拟应考，不是首次学习材料。"""


_EXAM_OUTPUT_GOAL = r"""按份分节输出用户明确要求且可直接计时作答的试卷：一节一卷，每卷自带卷面说明、题型分值分布、全部题目与卷末参考答案；不输出教程、讲解或泛化学习建议。"""


_EXAM_CONTENT_STRUCTURE = r"""# 试卷名称

【分卷规则 · 决定本次生成几节，必须逐条遵守】
- 一节 = 一整份卷：卷面说明引子 → 题型分值分布表 → 各题型题目 → 卷末「### 参考答案」，四段全部在同一节内完成。
- 卷数怎么定（按顺序判，取第一个能确定的）：
  ① 本次任务/硬性约束明确点了份数（如「出两套卷」「前两套」）→ 一套卷一节，节数等于套数；
  ② 任务要求按材料分章（如「为每一个章节生成单元检测卷」）→ 系统已按材料章节把节数与节标题定死，逐节照办，本节只写这一章的卷；
  ③ 未指定份数也没要求分章 → 只生成一节（一整份卷）。
- 节标题就是卷名：逐字用本次任务的卷名，或材料里该章的章名 + 卷种（如「线性代数期中模拟试卷」「第1章 线性方程组 单元检测卷」）；必须含「试卷」「检测卷」「测验卷」「模拟卷」之一，且保留「第N章」章号，去掉页码与「（习题）」等后缀。
- 不得为「参考答案」「难题解析」「考向分析」「卷面说明」「选择题」「判断题」等栏目或题型单独设节：它们是节内部的内容，不是节。
- 不得把多份卷合并进同一节，也不得遗漏本次要求覆盖的任何一份卷或任何一章。
- 正文不要写章标题（正文中不出现 # 或 ## 级标题），章标题由系统输出为「## 中文序号、卷名」；正文直接从下面的卷面说明引子开始。
- 本节只输出一个 content 块，且该块的 title 必须逐字等于本节卷名；不得拆成多个块，也不得另起「试卷」「试卷说明」「试卷正文与参考答案」一类自拟块标题（会多出一层无关标题）。

【卷内结构 · 每一节都完整走一遍，标题层级逐字一致】

下面是「没有注入材料」时的默认形态示例（六题型齐全）。本次若注入了「例题来源」材料，
题型小节的名称、种类与先后顺序一律以材料里的题型划分为准，只保留这里演示的结构骨架：
卷面说明引子 → 分值分布表 → 题型小节 → ### 参考答案。

> 本卷满分 100 分，考试时间 120 分钟，共 20 题。

| 题型 | 题号 | 题量 | 每题分值 | 小计 |
|---|---|---|---|---|
| 选择题 | 1–8 | 8 | 4 | 32 |
| 判断题 | 9–12 | 4 | 3 | 12 |
| 填空题 | 13–16 | 4 | 4 | 16 |
| 解答题 | 17–19 | 3 | 8 | 24 |
| 综合题 | 20 | 1 | 16 | 16 |
| 合计 | 1–20 | 20 | — | 100 |

### 选择题

**1.**（4 分）选择题题干，行内公式统一用 $…$；题干末尾用全角括号留选项位（　　）

A. 选项　　B. 选项　　C. 选项　　D. 选项



**2.**（4 分）题干

$$
矩阵、行列式等展示型公式独立成行
$$

A. 选项　　B. 选项　　C. 选项　　D. 选项



### 判断题

**9.**（3 分）判断题题干。

<p align="right"><input type="checkbox"> </p>

### 填空题

**13.**（4 分）填空题题干，答案位在题干内用下划线 ______ 表示。


### 解答题

**17.**（8 分）解答题题干；小题 (1)(2) 各自独立成行。



### 综合题

**20.**（16 分）综合题题干。
(1) 第一问；
(2) 第二问。




### 参考答案

**1.** A　**2.** C　**3.** B　**4.** D　**5.** A　**6.** B　**7.** C　**8.** A

**9.** 错误　**10.** 正确　**11.** 错误　**12.** 正确

**13.** 最终结果　**14.** 最终结果　**15.** 最终结果　**16.** 最终结果

**17.** 关键步骤与判定依据。
最终结论。

**20.** (1) 关键步骤与判定依据；
(2) 关键步骤与判定依据。

【有「例题来源」材料时的卷内形态（示意：材料的题型划分是「单项选择 / 名词解释 / 计算题 / 简答题」）】

> 本卷满分 100 分，考试时间 120 分钟，共 16 题。

| 题型 | 题号 | 题量 | 每题分值 | 小计 |
|---|---|---|---|---|
| 单项选择 | 1–8 | 8 | 4 | 32 |
| 名词解释 | 9–12 | 4 | 4 | 16 |
| 计算题 | 13–14 | 2 | 12 | 24 |
| 简答题 | 15–16 | 2 | 14 | 28 |
| 合计 | 1–16 | 16 | — | 100 |

### 单项选择

**1.**（4 分）题干（　　）

A. 选项　　B. 选项　　C. 选项　　D. 选项



### 名词解释

**9.**（4 分）待解释的术语______



### 计算题

**13.**（12 分）题干；小题 (1)(2) 各自独立成行。



### 简答题

**15.**（14 分）题干。



### 参考答案

**1.** A　**2.** C　**3.** B　**4.** D　**5.** A　**6.** B　**7.** C　**8.** A

**9.** 术语含义　**10.** 术语含义　**11.** 术语含义　**12.** 术语含义

**13.** 关键步骤与判定依据。
最终结论。

**15.** 关键步骤与判定依据。"""


_EXAM_FORMAT_RULES = r"""- 章标题由系统输出为「## 中文序号、卷名」，模型不写章标题，也不得改写卷名
- 正文最浅标题为「###」，不得出现「#」或「##」级标题
- 一节只输出一个正文块，块 title 逐字等于本节卷名；禁止自拟块标题或把一节拆成多块
- 卷内小标题用「###」级。题型小节名不固定，按「题型来源规则」确定后逐字沿用；答案小节固定叫「参考答案」
- 题型来源规则（按顺序判，取第一个成立的）：
  ① 本次注入了「例题来源」类材料 → 题型名逐字取自材料里的题型划分，不改写成同义词（材料写「计算题」就用「计算题」，不要改成「解答题」）；材料里出现多套划分时，取覆盖面最广的那一套，全篇只用这一套
  ② 材料只给题目、没有题型划分 → 按作答形态自行归类，名称从：选择题 / 判断题 / 填空题 / 解答题 / 证明题 / 综合题 中取
  ③ 没有注入任何材料 → 默认覆盖全部题型：选择题 / 判断题 / 填空题 / 解答题 / 证明题 / 综合题，题量按本次要求的总题数分配
- 客观题与主观题的归类判据（决定答案详略与留白，不依赖题型名字面）：
  · 客观题＝答案唯一且可直接判定：选择题、判断题、填空题，以及材料里的同类题型（如「单项选择」「正误判断」「填空」）
  · 主观题＝需要写出推导或论述：解答题、证明题、综合题，以及材料里的同类题型（如「计算题」「简答题」「论述题」「名词解释」「计算与证明题」）
  · 无法确定时按主观题处理
- 题型小节的先后顺序必须与卷面分值分布表一致；同一题型名在分值分布表与小节标题里逐字相同
- 禁止「第 I 部分」「Part 1」一类前缀或编号；禁止把材料里的一个题型拆成多个自拟名（如把「计算与证明题」拆成「计算题」+「证明与综合题」）
- 每节末尾必须有且仅有一个「### 参考答案」小节，位于该节全部题目之后
- 每题独立成段：题号一律加粗「**n.**」起行，紧接全角括注分值「（4 分）」，再空一格写题干；不使用裸数字题号
- 题号在本节（本卷）内从 1 开始连续编号，跨越所有题型小节不得重置；各节独立编号，不跨节承接
- 参考答案的题号必须与本节题目题号逐一对应
- 小题 (1)(2)(3) 每条独立成行，禁止多个小题挤在同一段
- 行内公式一律用 $…$，禁止使用 \(…\)；展示型数学（矩阵、行列式、多行推导、超过一行的公式）一律 $$…$$ 独立成行
- 题后留白代替作答区域，空行数按客观题/主观题固定：判断题 0 行（复选框即作答位）、选择题 2 行、填空题 1 行、其它客观题 1 行；主观题 3 行，含两个及以上小问的压轴主观题 4 行
- 答案位在题干内留出的题型（填空题及其它以短空作答的客观题），答案位用下划线「______」表示，不另起作答行
- 只有判断题用右对齐复选框；其它客观题不得插入复选框
- 全篇题型小节名、题号与分值括注格式必须逐字一致，不得一节一式
- 禁止自拟模板外的小节或标题层级"""


_EXAM_REQUIRED_RULES = r"""- 分卷交付：本次要求几份卷就生成几节，一节只写一份完整的卷；不得合并多卷、不得遗漏、不得为栏目或题型单独设节
- 卷面说明引子只写一行，格式固定：「> 本卷满分 100 分，考试时间 120 分钟，共 20 题。」（满分、时长、题量按本次任务要求替换）
- 卷面说明之后必须紧跟一个 Markdown 表格，表头逐字为「| 题型 | 题号 | 题量 | 每题分值 | 小计 |」，末行为「合计」
- 表格声明的题号区间、题量、每题分值、小计与满分，必须与实际写出的题目完全一致；先定题量与分值再落笔，写完逐条核对
- 题目必须在用户指定或合理推断的考试范围内；材料和任务信息不足时可合理补全，但不得越出范围
- 按材料分章时，本节只取材于本章：命题范围限于材料中该章及其课后习题涉及的知识点，不得跨章综合
- 每节内部按「卷面说明引子 → 题型分值分布表 → 题型小节 → ### 参考答案」的固定顺序组织，四段齐全
- 题型清单在落笔前先按「题型来源规则」定死一次，本次生成的所有节共用同一套题型名；分值分布表里列出的题型必须与后面写出的题型小节完全一致，不多不少
- 硬性约束中的内容要求（范围、题量、覆盖度、难度）必须逐条落实；其中的结构、标题、排版要求已由本规范接管，不作为格式依据
- 题目条件自足可解：所需定义、符号、单位在题干内给全，不依赖外部材料或前题结论
- 每节先给全部题目，再在本节末尾的「### 参考答案」小节集中给答案；答案不得插在题目之间
- 答案详略按客观题/主观题固定分级，不得自行判断某题难易：
  · 客观题 → 只给答案（选项字母 / 对错 / 最终结果），不给解析
  · 主观题 → 给答案 + 关键步骤与判定依据，每题不超过 6 行
- 参考答案只写题号与答案，不重复题干、不写「题干摘要」
- 难度只体现在选题与题型配比上，不在任何单题旁标注
- 本次任务明确写「不要答案」「只要题面」时：省略卷末「### 参考答案」小节，其余结构与题型分值分布表照旧，不得改用其它栏目代替答案"""


_EXAM_FORBIDDEN_RULES = r"""- 除非用户在「硬性约束」中要求，禁止出现本规范规定结构以外的任何内容
- 禁止把多份卷合并写进同一节；禁止为「参考答案」「难题解析」「考向分析」「卷面说明」等栏目单独设节
- 禁止在正文里写章标题（# 或 ## 级标题）；章标题由系统统一输出
- 禁止在节标题或正文里给卷名添加页码、「（习题）」「练习」「训练」等后缀
- 禁止跨节承接题号（各节题号都从 1 开始）；按材料分章时禁止本节出现其它章的题目或知识点
- 禁止自拟答案小节名（如「参考答案与评分说明」「参考答案与诊断说明」「选择题答案」「判断题答案」），只能叫「### 参考答案」
- 禁止把参考答案单独成节或单独成章
- 禁止在任何单题旁标注难度、考点、星级、「（较难）」「（易）」或命题意图（分值括注是必需的，不属于此列）
- 禁止标注题目来源、原题编号、出处，或「（原题…）」「（对应第 N 题的变式…）」「（融合知识点：…）」等溯源括注
- 禁止题目后立即附该题答案；答案只能出现在本节末尾的「### 参考答案」小节
- 禁止输出「作答区域」「答题位置」「请在此作答」「解：」等占位文字，留白只能用空行
- 禁止在卷内插入「概念标注」「知识概要」「易错点归纳」「考点分布」「体例说明」等教学或元信息栏目
- 禁止编造真实考试的既有事实（某年某校真题的考试时间、命题人、真题出处、官方评分细则）；本卷的满分与考试时长属卷面参数，按默认值或用户要求填写，不算编造
- 禁止输出冗长学习教程、泛化学习建议或无关说明"""


_EXAM_SUGGESTED_RULES = r"""- 题型配比与分值分布尽量贴近材料里的真实试卷；材料没有体现配比时，客观题合计不超过满分的一半
- 同一份卷尽量覆盖本次范围内的全部核心知识点，按重要程度分配题量与分值
- 题目条件优先自足；确需依赖前题结论时，在题干内显式复述该结论
- 涉及图形的题目，无法生成原图时用可读文字或表格描述关键信息，并说明「原图请对照教材」
- 主观题的参考答案优先写判定依据与关键转折，不复述完整推导
- 分值最高的主观题安排在本卷最后，难度明显高于同卷其它题
- 材料同时给了目录与课后习题时，以课后习题所在章为准判断本次要覆盖哪几章
- 用户按「第N章」点名章节时，节标题仍逐字沿用材料里的章名，不要改成用户口语里的说法"""


_EXAM_FLEXIBLE_RULES = r"""- 满分、考试时长、题型种类、各题型题量与每题分值：按本次任务要求决定，未指定时用卷面说明的默认值（满分 100 分、考试时间 120 分钟）
- 题型小节的取舍与顺序：有例题来源材料时以材料为准；无材料时默认六题型齐全，可按学科特点删减不适用的题型（如纯证明类学科可不出选择题），实际顺序须与卷面分值分布表一致
- 难度定位（对标例题来源、明显拔高、基础达标）按本次任务要求浮动
- 展示型公式的排版细节（对齐、换行位置）按可读性自行决定
- 主观题答案的步骤详略在「不超过 6 行」范围内按分值与题目复杂度浮动
- 卷数本身不灵活：必须等于本次任务要求的份数或章数，不得自行增减"""


_EXAM_ACCEPTANCE = r"""- 节数等于本次要求的卷数（或分章时的章数），每节只含一份完整的卷，节标题为卷名且含「试卷/检测卷/测验卷/模拟卷」之一
- 每节内部四段齐全且顺序正确：卷面说明引子 → 题型分值分布表 → 题型小节 → 参考答案
- 排版清晰，无冗余或重复内容，无无关内容；不违背用户的「硬性约束」
- 全篇标题层级统一：正文最浅为 ###，题型小节与参考答案都是 ###，无 # 或 ## 级标题
- 题型小节名逐字来自「例题来源」材料里的题型划分（无材料时取默认六题型），全文档同一套；无「第 I 部分」前缀，顺序与分值分布表一致
- 节内题号从 1 开始连续且无重复；参考答案的题号集合与本节题目题号集合完全相同
- 卷面说明与分值分布表声明的题量、题号区间、每题分值、小计、满分与实际写出的题目完全一致
- 每题独立成段，题号加粗「**n.**」并带「（X 分）」括注；展示型公式独立成行；小题逐条成行；行内公式只用 $…$
- 每节末尾有且仅有一个「### 参考答案」小节，答案未散落在题目之间，未重复题干
- 答案详略与客观题/主观题匹配：客观题只有答案，主观题含不超过 6 行的关键步骤
- 题后留白行数与题型匹配；无「作答区域」等占位文字；无「概念标注」等教学栏目"""


_EXAM_REFERENCE_EXAMPLES = r"""✅ 正确（任务要求两套卷 → 两节，一节一卷；下面示意两节的节标题与卷内结构）

## 一、线性代数期中模拟试卷（第一套）        ← 章标题由系统输出，模型不写

> 本卷满分 100 分，考试时间 120 分钟，共 19 题。

| 题型 | 题号 | 题量 | 每题分值 | 小计 |
|---|---|---|---|---|
| 选择题 | 1–8 | 8 | 4 | 32 |
| 判断题 | 9–12 | 4 | 3 | 12 |
| 解答题 | 13–19 | 7 | 8 | 56 |
| 合计 | 1–19 | 19 | — | 100 |

### 选择题

**1.**（4 分）设 $A$ 为 $m\times n$ 实矩阵，若 $AX=0$ 只有零解，则（　　）

A. $m\ge n$　　B. $m<n$　　C. $m=n$　　D. $A$ 可逆



### 判断题

**9.**（3 分）行列式交换两行后，其值不变。

<p align="right"><input type="checkbox"> </p>

### 解答题

**13.**（8 分）解线性方程组

$$
\begin{cases}
x+y=3,\\
x-y=1.
\end{cases}
$$



### 参考答案

**1.** A　**2.** C　**3.** B　**4.** D　**5.** A　**6.** B　**7.** C　**8.** A

**9.** 错误　**10.** 正确　**11.** 错误　**12.** 正确

**13.** 两式相加得 $2x=4$，故 $x=2$；代入第一式得 $y=1$。
解为 $(2,1)$。

## 二、第2章 集合与映射 单元检测卷          ← 第二节，题号重新从 1 开始

> 本卷满分 100 分，考试时间 120 分钟，共 15 题。

| 题型 | 题号 | 题量 | 每题分值 | 小计 |
|---|---|---|---|---|
| 选择题 | 1–5 | 5 | 4 | 20 |
| 解答题 | 6–15 | 10 | 8 | 80 |
| 合计 | 1–15 | 15 | — | 100 |

### 选择题

**1.**（4 分）题干……（　　）

A. 选项　　B. 选项　　C. 选项　　D. 选项



### 参考答案

**1.** A　**2.** B　**3.** C　**4.** D　**5.** A

**6.** 关键步骤与判定依据。
最终结论。

✅ 正确（注入了「例题来源」材料，材料里的题型划分是「单项选择 / 名词解释 / 计算题 / 简答题」→ 题型名逐字沿用，不改写成同义词）

## 一、无机化学期中模拟试卷

> 本卷满分 100 分，考试时间 120 分钟，共 16 题。

| 题型 | 题号 | 题量 | 每题分值 | 小计 |
|---|---|---|---|---|
| 单项选择 | 1–8 | 8 | 4 | 32 |
| 名词解释 | 9–12 | 4 | 4 | 16 |
| 计算题 | 13–14 | 2 | 12 | 24 |
| 简答题 | 15–16 | 2 | 14 | 28 |
| 合计 | 1–16 | 16 | — | 100 |

### 单项选择

**1.**（4 分）题干（　　）

A. 选项　　B. 选项　　C. 选项　　D. 选项



### 名词解释

**9.**（4 分）待解释的术语______



### 计算题

**13.**（12 分）题干；小题 (1)(2) 各自独立成行。



### 简答题

**15.**（14 分）题干。



### 参考答案

**1.** A　**2.** C　**3.** B　**4.** D　**5.** A　**6.** B　**7.** C　**8.** A

**9.** 术语含义　**10.** 术语含义　**11.** 术语含义　**12.** 术语含义

**13.** 关键步骤与判定依据。
最终结论。

**15.** 关键步骤与判定依据。

（「单项选择」「名词解释」是客观题→只给答案；「计算题」「简答题」是主观题→答案加步骤。
判断依据是作答形态，不是名字里有没有「选择」「解答」。）

❌ 错误（均为真实生成版出现过的形态）

## 二、参考答案                      ← 按栏目设节；答案必须写在每份卷的卷末
## 三、难题解析                      ← 同上，不得单独成节
# 线性代数单元检测卷                  ← 正文不得写 # / ## 标题，章标题由系统输出
## 第 I 部分：选择题                  ← 禁「第 X 部分」前缀；层级也不该是 ##
#### 选择题                          ← 无栏目层时题型小节必须是 ###，层级不由模型自定
### 计算与证明题                       ← 材料里只有「计算题」，却自行合并出新名（题型名必须逐字取自材料）
7. 若 \(n\) 元方程组…                ← 裸数字题号 + 行内公式误用 \(…\) + 缺分值括注
**1.**（10 分）解答题题干             ← 题号重置：解答题又从 1 开始，与选择题 1–8 撞号
作答区域：                           ← 已废止，应改为空行
**第 1 题（13 分）** 题干摘要：…      ← 答案区不得重复题干
### 参考答案与评分说明                ← 自拟答案小节名，只能叫「### 参考答案」
#### 概念标注（全卷）                 ← 卷内禁插教学栏目
#### 选择题答案                       ← 答案不得按题型拆成多个小节"""


_EXAM_CUSTOM_MARKDOWN = r"""**选择题排版规则**

1. **目标宽度基准**
   - 使用半角字符宽度单位 `u`：ASCII、数字、英文标点计 `1u`；中文、全角标点计 `2u`。
   - 数学公式按化简后的源文本估算；若使用 LaTeX，先估算渲染后的主要字符宽度，每个 `$...$` 额外加 `2u` 分隔余量。
   - 选项间距每个按 `2u` 计算。

2. **目标渲染档位**
   - 默认按 `W = 88u` 估算，约等于常见桌面 Markdown 阅读宽度。
   - 安全边距默认 `M = 6u`。

3. **估算公式**
   - 选项内容宽度：`a = width(A内容)`，`b = width(B内容)`，`c = width(C内容)`，`d = width(D内容)`。
   - 标签宽度：`A.`、`B.`、`C.`、`D.` 各计 `2u`。
   - 四选项同一行总宽：

   ```text
   S = (a + 2) + (b + 2) + (c + 2) + (d + 2) + 3 × 2
     = a + b + c + d + 14
   ```

   - 两栏模式时，每栏宽度：

   ```text
   col = max(a, b) 或 max(c, d)
   栏宽 = col + 2 + 2
   两栏总宽 S2 = max(max(a,b), max(c,d)) × 2 + 6
   ```

   其中第一个 `2` 是选项标签宽度，第二个 `2` 是栏内最小边距；栏间距按 `6u`。

4. **判定顺序**
   - 若 `S ≤ W - M`，使用方案 A：四个选项同一行。
   - 否则若 `S2 ≤ W - M`，使用方案 B：A/B 一行，C/D 一行。
   - 否则使用方案 C：每个选项单独一行。

5. **分行禁止项**
   - 不得把 `A.` 与其选项内容拆开。
   - 不得在公式、英文单词、数字、函数名内部断开。
   - 不得为了塞入一行缩小字号。
   - 不使用“尽量”“合适”“美观”等模糊判断。

6. **输出方式**
   - 生成过程中先输出判断表：

   ```text
   题号 | A | B | C | D | S | S2 | 可用宽度 | 采用方案
   ```

   - 最终试卷中不保留判断表，只输出排版后的题目

7. **Markdown 输出格式**
   - 方案 A：

   ```markdown
   A. xxx　　B. xxx　　C. xxx　　D. xxx
   ```

   - 方案 B：

   ```markdown
   A. xxx　　B. xxx  
   C. xxx　　D. xxx
   ```

   - 方案 C：

   ```markdown
   A. xxx  
   B. xxx  
   C. xxx  
   D. xxx
   ```

   行尾使用两个空格表示 Markdown 换行。

**判断题排版规则**

1. 题型小标题用三级标题 `### 判断题`，每卷只写一次。
2. 每道题题号加粗并带分值：`**9.**（3 分）`，题目正文紧接其后，同一行。
3. 行内数学公式统一用 `$…$`，例如 `$A$`、`$m\times n$`、`$r(A)\le r$`；禁止使用 `\(…\)`。
4. 每道题题干结束后，另起一行插入右对齐复选框，HTML 固定写成：
   `<p align="right"><input type="checkbox"> </p>`
5. 复选框单独占一行且右对齐；不要勾选。
6. 判断题之后不留空行（复选框即作答位）；题与题之间空一行。
7. 只输出题目和复选框；本卷答案统一写在卷末「### 参考答案」小节。

**题后留白规则（按客观题/主观题，不依赖题型名字面）**

1. 判断题：不留空行（右对齐复选框即作答位）。
2. 选择题：题后空 2 行。
3. 填空题，以及其它以短空作答的客观题（如「名词解释」「单项选择」）：答案位在题干内用下划线 `______` 表示，题后空 1 行。
4. 主观题（解答题、证明题、综合题，以及材料里的「计算题」「简答题」「论述题」等同类）：题后空 3 行；含两个及以上小问的压轴主观题空 4 行。
5. 客观题/主观题归类无法确定时按主观题处理。
6. 留白只能用空行，禁止写「作答区域」「答题位置」「解答：」「解：」等占位文字。
7. 只有判断题用右对齐复选框；其它客观题不得插入复选框。

**卷面分值分布表规则**

1. 表头逐字为 `| 题型 | 题号 | 题量 | 每题分值 | 小计 |`，分隔行 `|---|---|---|---|---|`，末行题型写「合计」。
2. 「题号」列写区间（如 `1–8`），用半角连接号 `–`，不用 `~` 或 `—`。
3. 同题型分值不同时，「每题分值」列逐项列出并用顿号分隔（如 `13、13、14`），「小计」仍写总和。
4. 表格必须在卷面说明引子的下一段，不得插到题型小节之间。
5. 写完逐条核对：各行「题量」之和 = 合计题量 = 卷面说明里的题数；各行「小计」之和 = 合计小计 = 满分。"""


_KNOWLEDGE_CONTENT_STRUCTURE = r"""# 教程名称

【章节规则 · 决定本次生成几节与章节顺序，必须逐条遵守】
- 章节由知识自身的逻辑关系决定，不套用固定目录，也不复制教材或网络资料的目录。
- 前置知识先于依赖它的知识出现；相关知识组织在同一章；不同知识模块边界清晰。
- 重要知识获得与其重要性相称的篇幅；复杂知识可拆成多章或多小节。
- 避免：把不相关知识点堆进同一章；为凑章节数强行拆分或合并；反复介绍同一概念。
- 知识范围围绕学习目标确定：用户指定范围时以它为核心并补足必需前置；未指定时按学科核心→基础→进阶自行定界，不机械覆盖整个学科。
- 第一章是「教程概览」：简要说明学习主题、知识全貌与章节安排，不写学习意义、能力收益或背景铺陈。
- 最后一章是「知识体系总结」：整合核心结构、关键关系与全篇逻辑，不是复制各章小结。
- 知识速查与额外练习是**配套文件**（系统另行生成并双链），不占正文章节，正文不得为它们设章。
- 章标题由系统输出为「## 中文序号、章名」；正文不写 # 或 ## 级标题，正文最浅标题为 ###。
- 每节只输出一个 content 块，块 title 逐字等于本节章名；不得自拟块标题或拆成多块。

【节内结构 · 每节都走一遍，层级与名称一致】

### 本章导入

本章研究什么、试图解决什么问题、与前后章的关系（三至五句，不重复概览）。

### 核心概念

#### 定义与内涵

**核心定义**：准确定义，首次出现的术语给出解释。

**通俗解释**：用直觉或类比降低门槛，指出类比的局限。

#### 典型例子与边界

举例说明：正例、反例或边界案例，并写明它与所解释概念的联系。

### 原理与推导

#### 成立条件

明确前提条件，按逻辑顺序展开推导，交代关键步骤；公式写明变量含义与适用范围。

#### 易错辨析

常见误解及其纠正（对照表优先：定义/前提/观点/适用条件/区别/联系）。

### 本节小结

三至五条本模块的主要结论。"""
_KNOWLEDGE_FORMAT_RULES = r"""- 章标题由系统输出为「## 中文序号、章名」；正文标题层级映射：章下模块 ###、知识点 ####、细分解释 #####；不得出现 # 或 ## 级正文标题
- 每章开头必须有「### 本章导入」，回答研究什么、解决什么、与前后章关系；不得重复概览内容
- 概念性知识按「定义 → 通俗解释 → 背景内涵 → 典型例子 → 混淆辨析 → 适用边界」组织；原理性知识按「问题 → 前提 → 推导 → 案例 → 条件与局限」组织
- 信息组件用加粗引导词起行（**核心定义** / **通俗解释** / **举例说明** / **注意事项** / **易错辨析** / **拓展知识** / **本节小结**），或作 #### 小标题；组件服务于信息功能，不为视觉堆砌
- 组件名不得写成已退役栏目（核心结论 / 常见错误 / 前置知识 / 必要练习 / 使用说明 / 自检清单），否则整块会被系统删除
- 容易混淆的概念、理论或方法优先用对照表，维度含定义、前提、观点、适用条件、区别、联系，并解释差异原因
- 行内公式一律 $…$，展示型公式 $$…$$ 独立成行；新符号及时解释；公式写明变量含义、成立条件与适用范围；推导保持逻辑连续
- 图表按知识性质选择：概念关系用概念图、过程机制用流程图、时间发展用时间线、理论比较用对照表；mermaid 写在 diagram 块；不为装饰加图
- 每节只输出一个 content 块，块 title 逐字等于本节章名
- 正文段落适度拆分；核心术语首次出现加粗一次；重要结论适度突出，避免通篇加粗"""
_KNOWLEDGE_REQUIRED_RULES = r"""- 不默认读者有专业基础：必要前置概念必须在正文解释，专业术语首次出现给出准确解释，抽象程度随难度递升，且不为照顾零基础牺牲严谨性
- 讲解深度：不只给结论不给依据；不只给定义不帮理解；复杂推导交代关键步骤；抽象理论配具体案例或直观解释；简单内容不过度解释
- 案例必须服务于理解：优先典型实例、现实应用、反例与边界案例、思想实验、对比案例；案例与所解释知识建立明确联系，不堆案例凑篇幅
- 主动建立知识联系：前置与后续、上位与下位、相似与对立、因果与逻辑；关系复杂时用概念图或结构图
- 知识速查（配套文件）必须生成：第一章必须是整份教程的知识全貌（定位、核心对象、主要模块、模块关系、章节地图、整体逻辑）；其后按核心概念、重要原理、公式符号与条件、关系与辨析分章
- 速查内容准确简洁、可独立理解、保留限定条件，不重复正文长篇解释
- 额外练习（配套文件，可选）由「练习生成规范」接管排版与结构，本规范不规定其形态"""
_KNOWLEDGE_FORBIDDEN_RULES = r"""- 禁止编造理论、公式、定理、事实或资料来源；不确定的信息必须标注，不得把推测包装成事实
- 禁止混淆公认结论、学术争议与 AI 自己的解释；有争议的观点须说明不同立场及依据
- 禁止出现「使用说明 / 做题方式 / 自检清单 / 核心结论 / 常见错误 / 前置知识 / 必要练习」一类元栏目或块标题
- 禁止在正文为知识速查或额外练习设章（它们是配套文件）
- 禁止机械复制教材或网络目录作为章节结构；禁止为形式统一机械使用全部标题层级
- 禁止无意义重复、过度铺垫与和学习目标关系不大的拓展"""
_KNOWLEDGE_SUGGESTED_RULES = r"""- 用户特别强调的内容增加讲解深度与篇幅；关联较弱的内容可压缩但不得遗漏必要知识环节
- 跨学科案例在确有帮助时使用
- 概念图、流程图在关系复杂时使用，简单关系用文字即可
- 学派争论只在理论性知识确有必要时介绍"""
_KNOWLEDGE_FLEXIBLE_RULES = r"""- 章节数量、每章小节数与组件取舍按知识性质决定，不强制每章出现全部组件
- 讲解组织方式（概念/原理/理论/机制）按本节知识性质选择，不机械套同一种
- 图表类型与数量按表达需要决定"""
_KNOWLEDGE_ACCEPTANCE = r"""- 章节顺序符合知识逻辑：前置先于依赖，相关同章，边界清晰
- 首章为教程概览、末章为知识体系总结；速查与额外练习未占正文章节
- 每章有本章导入；概念有定义与通俗解释；原理有前提、推导与适用条件
- 标题层级统一：正文最浅 ###，模块 ###、知识点 ####、细分 #####；无 # 或 ## 级正文标题
- 组件名未使用退役栏目；无元栏目块
- 公式风格统一 $…$ / $$…$$，变量含义与条件齐全
- 无编造事实；推测已标注；争议已分立场
- 速查文件存在且第一章为知识全貌"""
_KNOWLEDGE_REFERENCE_EXAMPLES = r"""✅ 正确

### 本章导入

本章研究向量组的线性相关性：它回答「一组向量里有没有多余的向量」，是秩与解结构的前提；上一章的矩阵乘法是本章的工具，本章结论将在下一章用于判定方程组解的个数。

### 核心概念

#### 定义与内涵

**核心定义**：向量组 $\alpha_1,\dots,\alpha_s$ 线性相关，指存在不全为零的数 $k_1,\dots,k_s$ 使 $k_1\alpha_1+\cdots+k_s\alpha_s=0$。

**通俗解释**：相关 = 其中某个向量能被其余向量「合成」，即它是多余的；无关 = 每个向量都带来新方向。这个类比在无穷维空间仍成立，但「方向」一词只适合有限维直觉。

#### 典型例子与边界

举例说明：$(1,0),(0,1),(1,1)$ 相关（第三个是前两个之和）；$(1,0),(0,1)$ 无关。边界：含零向量的任何向量组必相关——这是定义直接推出的，不是经验。

### 原理与推导

#### 成立条件

$\alpha_1,\dots,\alpha_s$ 相关 $\iff$ 矩阵 $A=(\alpha_1,\dots,\alpha_s)$ 的秩 $r(A)<s$；推导关键是把组合式写成 $Ax=0$ 有非零解。

#### 易错辨析

| 说法 | 正误 | 纠正 |
|---|---|---|
| 两个向量相关就是成比例 | 对（仅两个时） | 三个及以上不能两两看比例 |
| 无关组添加向量仍无关 | 错 | 添加的向量可能落在原组张成空间内 |

### 本节小结

- 相关 = 存在多余向量 = $Ax=0$ 有非零解 = $r(A)<s$。
- 含零向量必相关；部分相关则整体相关。

❌ 错误（真实生成版出现过的形态）

## 第三章 核心结论            ← 章标题是渲染器的活，正文不得写 ##
### 常见错误                  ← 退役栏目名，整块会被删除
### 必要练习                  ← 练习由额外练习文件承载，正文不设练习章
### 知识速查                  ← 速查是配套文件，不占正文章节
第 3 天再复习一遍             ← 日程化表述属画像硬约束禁止项"""
_KNOWLEDGE_CUSTOM_MARKDOWN = r"""**组件写法**

1. 组件用加粗引导词起行，后接同段正文；需要展开成块时用 #### 小标题。
2. 对照表表头按比较对象定，维度行至少含：定义、前提、适用条件、主要区别。
3. 概念图用 ```mermaid 的 graph TD，节点名用概念全称，边标签写关系（推出/依赖/对立）。

**速查文件结构（cheatsheet 阶段遵守）**

1. 第一章标题固定为「知识全貌」，含：定位、核心研究对象、主要知识模块、模块关系、章节地图、整体逻辑。
2. 其后章节：核心概念速查（表）、重要原理与理论（表或分组列表）、公式符号与条件（表：公式/符号/含义/条件/范围）、关系与辨析（表）。
3. 速查只收录教程大纲涉及的知识，不扩展新主题；每条保留限定条件。"""

_PRACTICAL_CONTENT_STRUCTURE = r"""# 教程名称

【章节规则 · 决定本次生成几节与章节顺序，必须逐条遵守】
- 默认组织方式：基础功能教学 + 实际应用场景教学；操作逻辑本身是核心的技能可用任务驱动组织。
- 基础阶段讲主要功能与基本操作；进阶阶段用实际场景教组合使用与问题解决。
- 不设独立的安装、登录、环境配置等基础准备章（默认读者已完成基础准备）；用户明确要求时才设。
- 章节按工具或技能的性质动态调整，不套僵化模板；相关功能组织在同一章，边界清晰。
- 第一章是「教程概览」：说明学习对象、主要用途、学完能完成哪些任务与章节安排，不写背景铺陈。
- 最后一章是「进阶应用」或「知识体系总结」：给出进一步提升使用能力的方法或整体功能结构回顾。
- 知识速查与额外练习是**配套文件**（系统另行生成并双链），不占正文章节。
- 章标题由系统输出为「## 中文序号、章名」；正文不写 # 或 ## 级标题，正文最浅标题为 ###。
- 每节只输出一个 content 块，块 title 逐字等于本节章名；不得自拟块标题或拆成多块。

【节内结构 · 每节都走一遍，层级与名称一致】

### 本章导入

本章要解决什么真实任务、用到哪些功能、与前后章的衔接（三至五句）。

### 功能与操作

#### 用途与入口

**核心定义**：该功能解决什么问题；**入口**：在哪里打开或调用（菜单路径 / 命令 / 快捷键）。

#### 操作步骤

1. 操作一（含关键参数与配置）。
2. 操作二。
   - 预期结果：看到什么。
   - 验证方式：如何确认成功。

#### 注意事项

容易忽略的条件、限制与特殊情况；破坏性操作必须写明风险与后果。

### 实用技巧

值得记忆的高价值技巧与工作流，每条写明适用场景。

### 典型应用场景

#### 场景示范

展示一项完整实际任务的实现过程：目标 → 步骤 → 关键决策 → 结果检查。

### 本节小结

三至五条本模块的主要操作与结论。"""
_PRACTICAL_FORMAT_RULES = r"""- 章标题由系统输出为「## 中文序号、章名」；正文标题层级映射：功能模块 ###、功能点 ####、细分说明 #####；不得出现 # 或 ## 级正文标题
- 每章开头必须有「### 本章导入」，说明真实任务、涉及功能与前后衔接
- 操作步骤用有序列表，每步含操作、预期结果与验证方式；关键参数与必要配置写在步骤内
- 命令与代码用独立代码块并标明语言或命令类型；示例尽量可直接执行；展示重要操作的预期输出
- 破坏性操作（删除、覆盖、付费、不可逆）必须单独一行写明风险与后果
- 信息组件用加粗引导词起行（**核心定义** / **入口** / **注意事项** / **易错辨析** / **场景示范** / **进阶拓展** / **本节小结**），或作 #### 小标题；同一种信息全篇用同一种表达
- 组件名不得写成已退役栏目（核心结论 / 常见错误 / 前置知识 / 必要练习 / 使用说明 / 自检清单），否则整块会被系统删除
- 依赖界面操作的内容优先用界面要素的文字描述（菜单路径、按钮名、面板名）；流程图用 diagram 块的 mermaid；图片不得只做装饰，须与文字对应
- 行内公式一律 $…$，展示型公式 $$…$$ 独立成行（实践教程少用公式，用到时遵守）
- 每节只输出一个 content 块，块 title 逐字等于本节章名"""
_PRACTICAL_REQUIRED_RULES = r"""- 以实际使用为中心组织教学，不以理论介绍为中心；理论只在支撑操作时出现
- 默认读者已安装、登录并配置好基本环境；除非用户明确要求，不写基础准备内容
- 操作说明必须明确、具体、可执行：入口、步骤、参数、预期结果、验证方式齐全
- 每个核心功能至少配一个真实可运行的示例或完整场景示范
- 关键操作展示预期输出或预期界面状态，读者可据此自检
- 常见问题排查必须覆盖该工具的高频失败点：现象、原因、解决办法
- 知识速查（配套文件）必须生成：第一章必须是「功能与能力全貌」（定位、核心功能分类、主要使用方式、典型应用场景、能力关系、学习路线）；其后按核心功能、常用操作、实用技巧、常见问题、注意事项分章
- 速查只收录教程涉及的功能与操作，注明适用版本或资料更新时间
- 额外练习（配套文件，可选）由「练习生成规范」接管排版与结构，本规范不规定其形态"""
_PRACTICAL_FORBIDDEN_RULES = r"""- 禁止编造功能、快捷键、命令、操作入口或界面元素；不得把过时功能、未核实操作或推测性功能写成确定事实
- 禁止混淆正式功能、实验功能与第三方扩展；实验功能与第三方扩展必须标注
- 禁止出现「使用说明 / 做题方式 / 自检清单 / 核心结论 / 常见错误 / 前置知识 / 必要练习」一类元栏目或块标题
- 禁止在正文为知识速查或额外练习设章（它们是配套文件）
- 禁止设置默认的安装、登录、环境配置等基础准备章（用户明确要求除外）
- 禁止无意义的理论堆积与和操作目标无关的拓展"""
_PRACTICAL_SUGGESTED_RULES = r"""- 用户指定应用方向时围绕该方向组织，同时保留必需的基础功能
- 操作逻辑本身是核心的技能（如正则、SQL）可用任务驱动组织
- 版本差异显著的功能给出「适用版本」标注"""
_PRACTICAL_FLEXIBLE_RULES = r"""- 章节数量与「基础/场景/进阶」的取舍按工具性质决定，不强制每章出现全部组件
- 技巧与场景的数量按功能复杂度决定；没有高价值技巧就不写技巧小节
- 截图、流程图按需使用，能用文字路径说清就不加图"""
_PRACTICAL_ACCEPTANCE = r"""- 章节顺序符合学习逻辑：基础功能先于场景应用，场景先于进阶
- 无默认基础准备章；首章为概览、末章为进阶或总结；速查与额外练习未占正文章节
- 每章有本章导入；每个核心功能有入口、步骤、预期结果与验证方式
- 命令与代码在独立代码块且标明类型；破坏性操作有风险说明
- 标题层级统一：正文最浅 ###，模块 ###、功能点 ####、细分 #####；无 # 或 ## 级正文标题
- 组件名未使用退役栏目；无元栏目块
- 无编造的功能、命令或入口；实验功能与第三方扩展已标注"""
_PRACTICAL_REFERENCE_EXAMPLES = r"""✅ 正确

### 本章导入

本章解决「把一段反复使用的提示词变成可复用技能」这一真实任务，用到技能目录、SKILL.md 与触发词三个功能；上一章的会话管理是本章排错的前提。

### 功能与操作

#### 用途与入口

**核心定义**：技能是一份带触发条件的本地指令集，命中描述时自动注入当前会话。
**入口**：`~/.codex/skills/<名称>/SKILL.md`（目录即技能名）。

#### 操作步骤

1. 新建目录并写入 SKILL.md，frontmatter 含 name 与 description。
   - 预期结果：文件出现在技能目录。
   - 验证方式：重启会话后在技能列表看到该名称。
2. 在 description 里写清「何时使用」与「何时不用」。
   - 预期结果：触发更准，误注入减少。
   - 验证方式：用一句无关任务测试不应命中。

#### 注意事项

- description 过宽会把无关任务也拉进技能上下文，token 成本上升。
- 删除技能目录即卸载，无回收站：先备份再删。

### 实用技巧

- 触发词写进 description 而不是正文：正文只在命中后才被读到。

### 典型应用场景

#### 场景示范

目标：为团队周报建一个固定格式技能。步骤：建目录 → 写模板与字段 → 用三条真实周报需求验证命中与产出格式。关键决策：把「不适用」情形写进 description，避免日常聊天误触发。结果检查：三次验证产出字段齐全、格式一致。

### 本节小结

- 技能 = 目录 + SKILL.md；description 决定触发。
- 验证命中与不命中各至少一次。

❌ 错误（真实生成版出现过的形态）

## 第二章 安装与登录          ← 默认不设基础准备章
### 常见错误                  ← 退役栏目名，整块会被删除
### 必要练习                  ← 练习由额外练习文件承载
点击「魔法按钮」即可          ← 编造界面元素
在旧版本中该命令为 xxx        ← 过时功能写成确定事实"""
_PRACTICAL_CUSTOM_MARKDOWN = r"""**操作步骤写法**

1. 一步只做一件事；参数与配置写进步骤行内，不另起「参数说明」长表。
2. 预期结果写「看到什么」（输出文本 / 界面状态），验证方式写「怎么确认」。
3. 破坏性操作前一行加 `> ⚠️ 风险：…` 引用行，写明后果与可逆性。

**速查文件结构（cheatsheet 阶段遵守）**

1. 第一章标题固定为「功能与能力全貌」，含：定位、核心功能分类、主要使用方式、典型应用场景、能力关系、学习路线与能力地图。
2. 其后章节：核心功能速查（功能/用途/入口/适用场景 表）、常用操作速查（命令或路径 + 用途）、实用技巧速查、常见问题速查（现象/原因/解决）、注意事项与使用限制。
3. 对持续更新的功能注明适用版本或资料更新时间；只收录教程涉及内容。"""

_BUILTINS = [
    {
        "name": "知识性教程规范",
        "description": "面向零基础读者的知识性教程：按知识逻辑分章，概念有定义与通俗解释，原理有推导与条件；首章概览、末章总结，速查与额外练习为配套文件。",
        "scene": "default_tutorial",
        "is_builtin": True,
        "is_default": True,
        "applicable_tasks": "概念解释、原理学习、理论掌握与认知体系构建类任务：数学、自然科学、人文社科、计算机理论等以理解知识为主要目标的教程。",
        "applicable_intents": ["解释", "学习", "掌握", "理解", "上手"],
        "excluded_intents": ["生成试卷", "出题", "整理试卷"],
        "trigger_keywords": ["原理", "概念", "理论", "定理", "推导", "证明", "辨析"],
        "target_reader": "从未系统学习过目标知识领域的读者：不默认任何专业基础，必要前置概念与术语必须在正文解释，抽象程度随难度递升，且不因照顾零基础牺牲严谨性。",
        "output_goal": "输出一份系统、准确、深入且可独立阅读的知识性教程：章节按知识逻辑组织，讲解有定义、解释、推导与案例，首章概览、末章总结，配套知识速查。",
        "content_structure": _KNOWLEDGE_CONTENT_STRUCTURE,
        "format_rules": _KNOWLEDGE_FORMAT_RULES,
        "required_rules": _KNOWLEDGE_REQUIRED_RULES,
        "forbidden_rules": _KNOWLEDGE_FORBIDDEN_RULES,
        "suggested_rules": _KNOWLEDGE_SUGGESTED_RULES,
        "flexible_rules": _KNOWLEDGE_FLEXIBLE_RULES,
        "acceptance_criteria": _KNOWLEDGE_ACCEPTANCE,
        "reference_examples": _KNOWLEDGE_REFERENCE_EXAMPLES,
        "custom_markdown": _KNOWLEDGE_CUSTOM_MARKDOWN,
    },
    {
        "name": "实践性教程规范",
        "description": "面向零基础读者的实践性教程：以实际使用为中心，基础功能 → 实用技巧 → 典型场景 → 进阶；操作步骤含入口、参数、预期结果与验证；速查与额外练习为配套文件。",
        "scene": "practical_tutorial",
        "is_builtin": True,
        "is_default": False,
        "applicable_tasks": "工具使用、软件操作、技能形成类任务：编程工具、办公软件、设计软件、命令行、工作流实践等以独立完成实际任务为主要目标的教程。",
        "applicable_intents": ["学会使用", "上手", "操作", "实践", "配置", "部署"],
        "excluded_scenarios": ["试卷", "练习卷", "纯理论讲解"],
        "excluded_intents": ["生成试卷", "出题"],
        "trigger_keywords": ["操作指南", "使用教程", "工具教程", "软件教程", "实操", "快捷键", "命令行教程"],
        "excluded_keywords": ["试卷", "模拟考试", "期中", "期末", "练习卷"],
        "target_reader": "从未系统学习过目标工具或技能的读者，但默认已完成安装、登录与基本环境配置；除非用户明确要求，不提供基础准备内容。",
        "output_goal": "输出一份以实际使用为中心、可独立跟随操作的实践性教程：功能有入口与步骤、操作有预期结果与验证、场景有完整示范，配套知识速查。",
        "deliverables": [],
        "content_structure": _PRACTICAL_CONTENT_STRUCTURE,
        "format_rules": _PRACTICAL_FORMAT_RULES,
        "required_rules": _PRACTICAL_REQUIRED_RULES,
        "forbidden_rules": _PRACTICAL_FORBIDDEN_RULES,
        "suggested_rules": _PRACTICAL_SUGGESTED_RULES,
        "flexible_rules": _PRACTICAL_FLEXIBLE_RULES,
        "acceptance_criteria": _PRACTICAL_ACCEPTANCE,
        "reference_examples": _PRACTICAL_REFERENCE_EXAMPLES,
        "custom_markdown": _PRACTICAL_CUSTOM_MARKDOWN,
    },
    {
        "name": "试卷生成规范",
        "scene": "exam_paper",
        "is_builtin": True,
        "is_default": False,
        "applicable_intents": ["生成试卷", "编写试卷", "出题", "扩写试卷", "重组试卷"],
        "excluded_scenarios": ["解释已有试题", "单独讲解知识点", "整理复习笔记", "总结课程内容"],
        "excluded_intents": ["解释试题", "讲解知识点", "整理笔记", "总结课程"],
        "trigger_keywords": ["模拟试卷", "试卷生成", "练习卷", "考试出题", "期中试卷", "期末试卷", "阶段测验", "模拟考试"],
        "excluded_keywords": [],
        "deliverables": [],
        "description": _EXAM_DESCRIPTION,
        "applicable_tasks": _EXAM_APPLICABLE_TASKS,
        "target_reader": _EXAM_TARGET_READER,
        "output_goal": _EXAM_OUTPUT_GOAL,
        "content_structure": _EXAM_CONTENT_STRUCTURE,
        "format_rules": _EXAM_FORMAT_RULES,
        "required_rules": _EXAM_REQUIRED_RULES,
        "forbidden_rules": _EXAM_FORBIDDEN_RULES,
        "suggested_rules": _EXAM_SUGGESTED_RULES,
        "flexible_rules": _EXAM_FLEXIBLE_RULES,
        "acceptance_criteria": _EXAM_ACCEPTANCE,
        "reference_examples": _EXAM_REFERENCE_EXAMPLES,
        "custom_markdown": _EXAM_CUSTOM_MARKDOWN,
    },
]


def _normalize_status(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"required", "optional", "on_request", "forbidden"} else "optional"


def _normalize_deliverables(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    for idx, raw in enumerate(value):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        result.append({
            "name": name[:120],
            "description": str(raw.get("description", "")).strip(),
            "status": _normalize_status(raw.get("status")),
            "primary": bool(raw.get("primary", True)),
            "order": int(raw.get("order") or idx + 1),
            "allow_override": bool(raw.get("allow_override", True)),
        })
    return result


def spec_dict(spec: FormatSpec) -> dict:
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description or "",
        "scene": spec.scene or "",
        "is_builtin": bool(spec.is_builtin),
        "is_default": bool(spec.is_default),
        "version": int(spec.version or 1),
        "applicable_tasks": spec.applicable_tasks or "",
        "applicable_intents": jload(spec.applicable_intents, []),
        "excluded_scenarios": jload(spec.excluded_scenarios, []),
        "excluded_intents": jload(spec.excluded_intents, []),
        "trigger_keywords": jload(spec.trigger_keywords, []),
        "excluded_keywords": jload(spec.excluded_keywords, []),
        "allow_keyword_trigger": bool(spec.allow_keyword_trigger),
        "allow_semantic_recommendation": bool(spec.allow_semantic_recommendation),
        "allow_explicit_selection": bool(spec.allow_explicit_selection),
        "target_reader": spec.target_reader or "",
        "output_goal": spec.output_goal or "",
        "deliverables": jload(spec.deliverables, []),
        "content_structure": spec.content_structure or "",
        "format_rules": spec.format_rules or "",
        "required_rules": spec.required_rules or "",
        "forbidden_rules": spec.forbidden_rules or "",
        "suggested_rules": spec.suggested_rules or "",
        "flexible_rules": spec.flexible_rules or "",
        "acceptance_criteria": spec.acceptance_criteria or "",
        "reference_examples": spec.reference_examples or "",
        "custom_markdown": spec.custom_markdown or "",
        "created_at": spec.created_at,
        "updated_at": spec.updated_at,
    }


def _snapshot(spec: FormatSpec, task_overrides: list[str] | None = None) -> dict:
    data = spec_dict(spec)
    data["snapshot_version"] = f"v{spec.version}-{spec.updated_at or spec.created_at}"
    data["task_overrides"] = task_overrides or []
    return data


def _validate_payload(payload) -> None:
    if not str(payload.name or "").strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_format_spec", "message": "规范名称不能为空"},
        )
    if not str(payload.output_goal or "").strip() and not str(payload.description or "").strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_format_spec", "message": "请填写用途描述或输出目标"},
        )
    if not isinstance(payload.deliverables, list):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_format_spec", "message": "交付物清单必须是数组"},
        )
    names = [str(item.get("name", "")).strip() for item in payload.deliverables if isinstance(item, dict)]
    if len(names) != len(set(names)):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_format_spec", "message": "交付物名称不能重复"},
        )


def _apply_payload(spec: FormatSpec, payload, *, is_update: bool = False) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    if isinstance(payload, dict):
        payload = SimpleNamespace(**payload)
    _validate_payload(payload)
    spec.name = str(payload.name).strip()
    spec.description = str(payload.description or "").strip()
    spec.scene = str(payload.scene or "").strip()
    spec.applicable_tasks = str(payload.applicable_tasks or "").strip()
    spec.applicable_intents = jdump(payload.applicable_intents or [])
    spec.excluded_scenarios = jdump(payload.excluded_scenarios or [])
    spec.excluded_intents = jdump(payload.excluded_intents or [])
    spec.trigger_keywords = jdump(payload.trigger_keywords or [])
    spec.excluded_keywords = jdump(payload.excluded_keywords or [])
    spec.allow_keyword_trigger = bool(payload.allow_keyword_trigger)
    spec.allow_semantic_recommendation = bool(payload.allow_semantic_recommendation)
    spec.allow_explicit_selection = bool(payload.allow_explicit_selection)
    spec.target_reader = str(payload.target_reader or "").strip()
    spec.output_goal = str(payload.output_goal or "").strip()
    spec.deliverables = jdump(_normalize_deliverables(payload.deliverables))
    spec.content_structure = str(payload.content_structure or "")
    spec.format_rules = str(payload.format_rules or "")
    spec.required_rules = str(payload.required_rules or "")
    spec.forbidden_rules = str(payload.forbidden_rules or "")
    spec.suggested_rules = str(payload.suggested_rules or "")
    spec.flexible_rules = str(payload.flexible_rules or "")
    spec.acceptance_criteria = str(payload.acceptance_criteria or "")
    spec.reference_examples = str(payload.reference_examples or "")
    spec.custom_markdown = str(payload.custom_markdown or "")
    if is_update:
        spec.version = int(spec.version or 1) + 1


def _clear_default(db: Session, *, keep_id: str | None = None) -> None:
    query = db.query(FormatSpec).filter(FormatSpec.is_default.is_(True))
    if keep_id:
        query = query.filter(FormatSpec.id != keep_id)
    for item in query.all():
        item.is_default = False


def set_default(db: Session, spec_id: str) -> dict:
    spec = db.get(FormatSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail={"code": "format_spec_not_found", "message": "格式规范不存在"})
    _clear_default(db)
    db.commit()
    spec.is_default = True
    db.commit()
    db.refresh(spec)
    return spec_dict(spec)


def list_specs(db: Session) -> list[dict]:
    return [spec_dict(item) for item in db.query(FormatSpec).order_by(FormatSpec.is_default.desc(), FormatSpec.updated_at.desc()).all()]


def get_spec(db: Session, spec_id: str) -> dict:
    spec = db.get(FormatSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail={"code": "format_spec_not_found", "message": "格式规范不存在"})
    return spec_dict(spec)


def create_spec(db: Session, payload) -> dict:
    spec = FormatSpec(is_builtin=False, is_default=False, version=1)
    _apply_payload(spec, payload)
    if bool(getattr(payload, "is_default", False)):
        _clear_default(db)
        db.commit()
        spec.is_default = True
    db.add(spec)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "default_conflict", "message": "默认规范设置冲突，请刷新后重试"})
    db.refresh(spec)
    return spec_dict(spec)


def update_spec(db: Session, spec_id: str, payload) -> dict:
    spec = db.get(FormatSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail={"code": "format_spec_not_found", "message": "格式规范不存在"})
    was_default = spec.is_default
    _apply_payload(spec, payload, is_update=True)
    if bool(getattr(payload, "is_default", False)) and not spec.is_default:
        _clear_default(db, keep_id=spec.id)
        db.commit()
        spec.is_default = True
    elif was_default and not spec.is_default:
        fallback = (
            db.query(FormatSpec)
            .filter(FormatSpec.id != spec.id)
            .order_by(FormatSpec.is_builtin.desc(), FormatSpec.updated_at.desc())
            .first()
        )
        if fallback is not None:
            fallback.is_default = True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "default_conflict", "message": "默认规范设置冲突，请刷新后重试"})
    db.refresh(spec)
    return spec_dict(spec)


def duplicate_spec(db: Session, spec_id: str) -> dict:
    source = db.get(FormatSpec, spec_id)
    if source is None:
        raise HTTPException(status_code=404, detail={"code": "format_spec_not_found", "message": "格式规范不存在"})
    spec = FormatSpec(
        name=f"{source.name}（副本）",
        description=source.description,
        scene=source.scene,
        is_builtin=False,
        is_default=False,
        version=1,
        applicable_tasks=source.applicable_tasks,
        applicable_intents=source.applicable_intents,
        excluded_scenarios=source.excluded_scenarios,
        excluded_intents=source.excluded_intents,
        trigger_keywords=source.trigger_keywords,
        excluded_keywords=source.excluded_keywords,
        allow_keyword_trigger=source.allow_keyword_trigger,
        allow_semantic_recommendation=source.allow_semantic_recommendation,
        allow_explicit_selection=source.allow_explicit_selection,
        target_reader=source.target_reader,
        output_goal=source.output_goal,
        deliverables=source.deliverables,
        content_structure=source.content_structure,
        format_rules=source.format_rules,
        required_rules=source.required_rules,
        forbidden_rules=source.forbidden_rules,
        suggested_rules=source.suggested_rules,
        flexible_rules=source.flexible_rules,
        acceptance_criteria=source.acceptance_criteria,
        reference_examples=source.reference_examples,
        custom_markdown=source.custom_markdown,
    )
    db.add(spec)
    db.commit()
    db.refresh(spec)
    return spec_dict(spec)


def delete_spec(db: Session, spec_id: str) -> dict:
    spec = db.get(FormatSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail={"code": "format_spec_not_found", "message": "格式规范不存在"})
    remaining = db.query(FormatSpec).filter(FormatSpec.id != spec_id).count()
    if remaining == 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "last_format_spec", "message": "至少保留一份格式规范；可先创建或复制另一份再删除"},
        )
    was_default = spec.is_default
    name = spec.name
    db.delete(spec)
    db.flush()
    if was_default:
        fallback = (
            db.query(FormatSpec)
            .filter(FormatSpec.scene == "default_tutorial")
            .order_by(FormatSpec.is_builtin.desc(), FormatSpec.updated_at.desc())
            .first()
        )
        if fallback is None:
            fallback = db.query(FormatSpec).order_by(FormatSpec.is_builtin.desc(), FormatSpec.updated_at.desc()).first()
        if fallback is not None:
            fallback.is_default = True
    db.commit()
    return {"ok": True, "deleted": name}


def get_exercise_spec_dict(db: Session) -> dict:
    """练习生成规范（scene=exercise）的当前字段 dict；额外练习配套文件按它排版。

    与目标绑定哪条规范无关：教程类目标绑的是知识性/实践性规范，
    但它的额外练习文件必须长得像练习生成规范的成品。
    """
    spec = db.query(FormatSpec).filter(FormatSpec.scene == "exercise").first()
    return spec_dict(spec) if spec is not None else {}


def ensure_builtin_specs(db: Session) -> None:
    """首次启动写入两份内置规范；已有记录不会被覆盖。"""
    existing_scenes = {
        item.scene for item in db.query(FormatSpec).filter(FormatSpec.is_builtin.is_(True)).all()
    }
    changed = False
    for item in _BUILTINS:
        if item["scene"] in existing_scenes:
            continue
        spec = FormatSpec(
            name=item["name"],
            description=item["description"],
            scene=item["scene"],
            is_builtin=True,
            is_default=False,
            version=1,
            applicable_tasks=item["applicable_tasks"],
            applicable_intents=jdump(item["applicable_intents"]),
            excluded_scenarios=jdump(item.get("excluded_scenarios", [])),
            excluded_intents=jdump(item["excluded_intents"]),
            trigger_keywords=jdump(item.get("trigger_keywords", [])),
            excluded_keywords=jdump(item.get("excluded_keywords", [])),
            allow_keyword_trigger=True,
            allow_semantic_recommendation=True,
            allow_explicit_selection=True,
            target_reader=item["target_reader"],
            output_goal=item["output_goal"],
            deliverables=jdump(item.get("deliverables", [])),
            content_structure=item["content_structure"],
            format_rules=item["format_rules"],
            required_rules=item["required_rules"],
            forbidden_rules=item["forbidden_rules"],
            suggested_rules=item.get("suggested_rules", ""),
            flexible_rules=item.get("flexible_rules", ""),
            acceptance_criteria=item["acceptance_criteria"],
            # 漏传 reference_examples 会让全新安装永远拿不到排版正反例（种子白写）：
            # 该字段在 outline / section 阶段注入，是纠正「题号按题型重置」的主要手段。
            reference_examples=item.get("reference_examples", ""),
            custom_markdown=item.get("custom_markdown", ""),
        )
        db.add(spec)
        changed = True
    if changed:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    if not db.query(FormatSpec).filter(FormatSpec.is_default.is_(True)).first():
        fallback = (
            db.query(FormatSpec)
            .filter(FormatSpec.scene == "default_tutorial")
            .first()
            or db.query(FormatSpec).first()
        )
        if fallback is not None:
            fallback.is_default = True
            db.commit()


def _match_form(text: str) -> str:
    return re.sub(r"[\s，。、；：,.;:的了我你您请帮给一下]", "", str(text or "")).lower()


def _explicit_spec(db: Session, requirement: str, spec_id: str | None = None) -> tuple[str, dict]:
    if spec_id is not None:
        if spec_id == "":
            return "none", {"reason": "用户本次选择不使用特殊规范"}
        spec = db.get(FormatSpec, spec_id)
        if spec is None:
            names = [item.name for item in db.query(FormatSpec).order_by(FormatSpec.name).all()]
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "format_spec_not_found",
                    "message": f"指定的格式规范不存在。可用规范：{ '、'.join(names) }",
                },
            )
        if not spec.allow_explicit_selection:
            raise HTTPException(
                status_code=400,
                detail={"code": "format_spec_not_allowed", "message": f"「{spec.name}」不允许被明确指定"},
            )
        return "manual", {"reason": "用户在生成前明确选择"}

    lowered = str(requirement or "")
    specs = db.query(FormatSpec).order_by(FormatSpec.is_default.desc()).all()
    if re.search(r"不要使用.{0,20}(规范|模板)", lowered):
        return "none", {"reason": "用户明确排除特殊规范"}
    for spec in specs:
        if spec.allow_explicit_selection and _match_form(spec.name) in _match_form(lowered):
            return "explicit", {"reason": f"需求文本明确指定「{spec.name}」"}
    return "", {}


def _keyword_matches(spec: FormatSpec, requirement: str) -> tuple[bool, bool]:
    haystack = _match_form(requirement)
    if not spec.allow_keyword_trigger:
        return False, False
    included = any(_match_form(word) and _match_form(word) in haystack for word in jload(spec.trigger_keywords, []))
    excluded = any(_match_form(word) and _match_form(word) in haystack for word in jload(spec.excluded_keywords, []))
    return included, excluded


def _semantic_match(db: Session, ai, requirement: str, candidates: list[FormatSpec]) -> tuple[str, FormatSpec | None, dict]:
    if not candidates:
        return "", {}
    payloads = [{"id": item.id, "name": item.name, "description": item.description} for item in candidates]
    try:
        result = ai.format_spec_match(requirement, payloads)
        selected = next((item for item in candidates if item.id == result.get("format_spec_id")), None)
        if selected is None or not selected.allow_semantic_recommendation:
            return "", None, {}
        confidence = float(result.get("confidence") or 0)
        if confidence < 0.6:
            return "", {}
        return "semantic", selected, {
            "reason": str(result.get("reason") or "语义匹配"),
            "confidence": confidence,
        }
    except Exception:
        return "", None, {"reason": "语义识别失败，已回退默认规范"}


def resolve_spec(db: Session, requirement: str, ai=None, manual_spec_id: str | None = None) -> dict:
    """返回 selected_spec / snapshot / source / note；未选中时 selected_spec 为 None。"""
    explicit_source, explicit_note = _explicit_spec(db, requirement, manual_spec_id)
    if explicit_source:
        if explicit_source == "none":
            return {
                "selected_spec": None,
                "snapshot": {},
                "source": "none",
                "note": explicit_note["reason"],
            }
        spec_id = manual_spec_id
        if not spec_id:
            source, note = _explicit_spec(db, requirement, None)
            selected = None
            if source == "explicit":
                name = re.search(r"(?:使用|按|按照|采用)([^，。；\n]{1,30}?规范)", str(requirement))
                if name:
                    token = _match_form(name.group(1))
                    selected = next((item for item in db.query(FormatSpec).all() if _match_form(item.name) == token), None)
            if selected is None:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "format_spec_not_found", "message": "无法确定需求文本指定的格式规范"},
                )
            spec_id = selected.id
        spec = db.get(FormatSpec, spec_id)
        return {
            "selected_spec": spec,
            "snapshot": _snapshot(spec),
            "source": explicit_source,
            "note": explicit_note["reason"],
        }

    candidates: list[FormatSpec] = []
    notes: list[str] = []
    for spec in db.query(FormatSpec).all():
        included, excluded = _keyword_matches(spec, requirement)
        if excluded:
            notes.append(f"「{spec.name}」命中排除关键词")
            continue
        if included:
            candidates.append(spec)

    if len(candidates) == 1:
        spec = candidates[0]
        return {
            "selected_spec": spec,
            "snapshot": _snapshot(spec),
            "source": "keyword",
            "note": f"关键词命中「{spec.name}」",
        }

    if candidates:
        source, selected, note = _semantic_match(db, ai, requirement, candidates)
        if source:
            spec = selected
            return {
                "selected_spec": spec,
                "snapshot": _snapshot(spec),
                "source": source,
                "note": note.get("reason", ""),
            }
        notes.append(note.get("reason", "候选不唯一且语义识别不可用"))

    default = db.query(FormatSpec).filter(FormatSpec.is_default.is_(True)).first()
    if default is None:
        default = db.query(FormatSpec).order_by(FormatSpec.is_builtin.desc()).first()
    if default is None:
        return {"selected_spec": None, "snapshot": {}, "source": "default", "note": "暂无可用规范"}
    note = "；".join(notes) if notes else "未命中特殊规范"
    return {
        "selected_spec": default,
        "snapshot": _snapshot(default),
        "source": "default",
        "note": f"{note}，使用默认规范「{default.name}」",
    }


def bind_goal_spec(db: Session, goal: LearningGoal, requirement: str, ai=None, manual_spec_id: str | None = None) -> dict:
    """在大纲前绑定任务规范；已绑定则不重新匹配。"""
    if goal.format_spec_source and goal.format_spec_snapshot:
        return {
            "selected_spec": db.get(FormatSpec, goal.format_spec_id),
            "snapshot": jload(goal.format_spec_snapshot, {}),
            "source": goal.format_spec_source,
            "note": goal.format_spec_match_note or "",
        }
    resolved = resolve_spec(db, requirement, ai=ai, manual_spec_id=manual_spec_id)
    spec = resolved["selected_spec"]
    goal.format_spec_id = spec.id if spec is not None else ""
    goal.format_spec_source = resolved["source"]
    goal.format_spec_match_note = resolved["note"]
    goal.format_spec_snapshot = jdump(resolved["snapshot"])
    db.commit()
    return resolved


# 材料章节标题：允许 H1–H4、允许「## 一、第 1 章 …」这类带中文序号前缀的写法
_MATERIAL_CHAPTER_RE = re.compile(
    r"^#{1,4}\s*(?:[一二三四五六七八九十百零\d]+\s*[、.．]\s*)?"
    r"(第\s*[0-9一二三四五六七八九十]+\s*[章篇][^#\n]*?)\s*$"
)
# 「为每一章各生成一份 X」这类按章交付要求：结构由代码定死，不靠模型自觉
_CHAPTER_SPLIT_RE = re.compile(
    r"(?:每|各|逐|按|分)\s*(?:一|1)?\s*(?:个)?\s*(?:章节|章|单元)|(?:章节|每章)\s*(?:各|都|分别)|分章"
)
# 交付物名词：用于把「第 1 章 线性方程组」写成「第 1 章 线性方程组 单元检测卷」
_UNIT_NOUN_RE = re.compile(r"(单元检测卷|单元测验卷|单元试卷|检测卷|测验卷|测试卷|自测卷|模拟卷|练习卷|试卷)")
_CN_NUMERALS = "一二三四五六七八九十"


def cn_numeral(n: int) -> str:
    """1-99 的中文序号（模板标题用）：1→一、11→十一、21→二十一。"""
    if n <= 10:
        return _CN_NUMERALS[n - 1]
    if n < 20:
        return "十" + _CN_NUMERALS[n - 11]
    tens, rem = divmod(n, 10)
    return _CN_NUMERALS[tens - 1] + "十" + (_CN_NUMERALS[rem - 1] if rem else "")


def material_chapters(materials_text: str) -> list[str]:
    """按出现顺序提取材料里的章节名（去重、去「一、」这类序号前缀）。

    这是「按章交付」的结构事实来源：章节名逐字取自用户上传的参考材料，
    既不用模型猜，也不会因为材料换了目录写法就漏章。
    """
    chapters: list[str] = []
    seen: set[str] = set()
    for line in str(materials_text or "").splitlines():
        match = _MATERIAL_CHAPTER_RE.match(line.strip())
        if not match:
            continue
        name = re.sub(r"\s+", " ", match.group(1)).strip(" 、.．:：")
        if not name or name in seen:
            continue
        seen.add(name)
        chapters.append(name)
    return chapters


def chapter_split_mode(snapshot: dict | None, requirement: str = "") -> bool:
    """本次是否按材料章节拆分交付物（每章一份成品）。

    由任务文本确定性决定：用户写「为每一个章节生成单元检测卷」时，章节数就是交付物数。
    硬性约束是这句话最常见的落点，所以调用方必须把 hard_constraints 一并拼进
    requirement（见 teaching_profile.task_requirement_text）。

    必须同时命中「按章」表述与「每章一份什么成品」的名词（_UNIT_NOUN_RE）才算按章交付。
    只看「每/各/逐 + 章」会误伤练习类任务：「在每一章最后输出十个综合题」里的
    「每一章」只是描述题目分布，不是要求按章拆成交付物；缺了名词就按原交付物走。
    """
    snap = snapshot or {}
    if not str(snap.get("name", "")).strip():
        return False
    if snap.get("chapter_split") is not None:
        return bool(snap.get("chapter_split"))
    text = str(requirement or "")
    return bool(_CHAPTER_SPLIT_RE.search(text)) and bool(_UNIT_NOUN_RE.search(text))


def apply_chapter_split(snapshot: dict | None, requirement: str = "", materials_text: str = "") -> dict:
    """按材料章节把交付物切换为「每章一份」，并把判定冻结进快照。

    只改本任务快照，不动已保存模板。默认教程规范（无交付物清单）不参与：
    它的章节结构本来就由大纲模型按知识复杂度决定，强行按材料分章会改变普通教程行为。
    """
    result = deepcopy(snapshot or {})
    if not chapter_split_mode(result, requirement):
        result["chapter_split"] = False
        return result
    if str(result.get("scene", "")) == "default_tutorial" and not (result.get("deliverables") or []):
        result["chapter_split"] = False
        return result
    result["chapter_split"] = True
    chapters = material_chapters(materials_text)
    if not chapters:
        # 材料里没有可识别的章节标题：保留原交付物，章节结构交回大纲（不编造章节）
        return result
    noun_match = _UNIT_NOUN_RE.search(str(requirement or ""))
    noun = noun_match.group(1) if noun_match else ""
    names = [f"{chapter} {noun}".strip() if noun else chapter for chapter in chapters]
    result["deliverables"] = [
        {
            "name": name,
            "description": "",
            "status": "required",
            "primary": idx == 1,
            "order": idx,
            "allow_override": True,
        }
        for idx, name in enumerate(names, 1)
    ]
    result["task_overrides"] = list(result.get("task_overrides") or []) + [
        f"按材料分章交付：共 {len(names)} 份，每份只覆盖对应章节，第 i 份不得写入其它章节内容"
    ]
    return result


def apply_task_overrides(snapshot: dict, requirement: str) -> dict:
    """把本次明确要求转成快照内覆盖项；不修改已保存模板。"""
    result = deepcopy(snapshot or {})
    task_text = str(requirement or "")
    overrides: list[str] = []
    if re.search(r"不要[^。；\n]{0,10}答案", task_text):
        for item in result.get("deliverables", []):
            if "答案" in str(item.get("name", "")):
                item["status"] = "forbidden"
                overrides.append(f"本次不生成{item['name']}")
    if re.search(r"不要[^。；\n]{0,10}解析", task_text):
        for item in result.get("deliverables", []):
            if "解析" in str(item.get("name", "")):
                item["status"] = "forbidden"
                overrides.append(f"本次不生成{item['name']}")
    if re.search(r"只(?:输出|包括|保留|生成|交付)", task_text):
        mentioned = [
            item
            for item in result.get("deliverables", [])
            if str(item.get("name", "")) and str(item.get("name", "")) in task_text
        ]
        if mentioned:
            keep = {item["name"] for item in mentioned}
            for item in result.get("deliverables", []):
                if item["name"] not in keep and item.get("status") != "forbidden":
                    item["status"] = "forbidden"
            overrides.extend([f"本次只生成：{name}" for name in sorted(keep)])
    result["task_overrides"] = overrides
    return result


def delivery_contract_for_snapshot(snapshot: dict) -> dict | None:
    """把规范交付清单并入现有契约结构；普通教程规范不生成契约。"""
    deliverables = (snapshot or {}).get("deliverables") or []
    if not deliverables:
        return None
    ordered = sorted(
        [item for item in deliverables if str(item.get("status")) in {"required", "on_request"}],
        key=lambda item: int(item.get("order") or 0),
    )
    items = [str(item.get("name", "")).strip() for item in ordered]
    items = [item for item in items if item]
    if not items:
        return None
    forbidden_names = [
        str(item.get("name", "")) for item in deliverables if str(item.get("status")) == "forbidden"
    ]
    return {
        "items": items,
        "forbid_answers": any("答案" in name for name in forbidden_names),
        "exclusive": True,
        "suppress_companions": True,
        "source": "format_spec",
        "format_spec_id": snapshot.get("id", ""),
        "format_spec_version": snapshot.get("snapshot_version", ""),
        "forbidden_deliverables": forbidden_names,
        "task_overrides": snapshot.get("task_overrides") or [],
    }


def check_snapshot_delivery(snapshot: dict, content: dict) -> list[str]:
    """结构化交付物清单的确定性检查；语义验收仍由提示词和现有检查承担。"""
    titles = [str(item.get("title", "")) for item in content.get("outline", [])]
    titles += [str(item.get("title", "")) for item in content.get("sections", [])]
    issues: list[str] = []
    for item in (snapshot or {}).get("deliverables", []):
        name = str(item.get("name", "")).strip()
        status = str(item.get("status", ""))
        if not name:
            continue
        if status == "required" and not any(name in title for title in titles):
            issues.append(f"必需交付物未出现在结构中：{name}")
        if status == "forbidden" and any(name in title for title in titles):
            issues.append(f"禁止交付物出现在结构中：{name}")
    return issues


def active_snapshot(goal) -> dict:
    """返回已绑定且可执行的格式规范快照。"""
    snapshot = jload(getattr(goal, "format_spec_snapshot", "") or "", {})
    return snapshot if isinstance(snapshot, dict) and snapshot.get("name") else {}


def authoritative_snapshot(goal) -> dict:
    """真正接管模板的规范；默认教程规范继续走普通教程链路。"""
    snapshot = active_snapshot(goal)
    return authoritative_spec_dict(snapshot)


def authoritative_spec_dict(snapshot: dict) -> dict:
    """dict 版本：判断一份快照是否真正接管模板。

    指导型规范（教程族，见 utils.GUIDANCE_SCENES）在没有交付物清单时**不接管**：
    章节数与标题交回大纲模型，规范只作为写法与质量的注入源。
    """
    if not isinstance(snapshot, dict) or not str(snapshot.get("name", "")).strip():
        return {}
    deliverables = snapshot.get("deliverables") or []
    if utils.is_guidance_snapshot(snapshot) and not deliverables:
        return {}
    return snapshot


def contract_for_goal(goal, existing: dict | None = None) -> dict | None:
    """统一交付契约来源。

    选定格式规范后，它独占结构、标题、顺序和排版权限：即使规范没有交付物清单，
    也不再回退到旧画像契约，避免两套模板同时生效。
    """
    if isinstance(existing, dict) and existing.get("source") == "format_spec":
        return existing
    snapshot = authoritative_snapshot(goal)
    if snapshot:
        return delivery_contract_for_snapshot(snapshot)
    if isinstance(existing, dict) and existing:
        return existing
    from ..learning.teaching_profile import delivery_contract_for

    return delivery_contract_for(goal)


def suppress_legacy_companions(goal) -> bool:
    """选定规范后，配套文件必须由规范明确要求，不能沿用旧教程画像自动生成。"""
    return bool(authoritative_snapshot(goal))
