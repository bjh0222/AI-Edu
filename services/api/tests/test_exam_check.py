# -*- coding: utf-8 -*-
"""exam_check（L0 卷面账目校验与一轮自动修复）单元测试。

重点覆盖三类**实测发生过**的故障，而不是理想输入：
1. 规范模板自身账目错误被模型照抄（满分 100、各行之和 96）；
2. 答案小节名自拟 5 种写法，以及答案区里夹元栏目导致答案被当成题目重新编号；
3. 答案区泄漏「需核验」这类不确定性表述。
"""
from __future__ import annotations

from app.services import exam_check as ec


def _paper(body: str) -> ec.ExamPaper:
    return ec.parse_paper(body)


GOOD = """
> 本卷满分 100 分，考试时间 120 分钟，共 4 题。

| 题型 | 题号 | 题量 | 每题分值 | 小计 |
|---|---|---|---|---|
| 选择题 | 1–2 | 2 | 20 | 40 |
| 判断题 | 3–4 | 2 | 30 | 60 |
| 合计 | 1–4 | 4 | — | 100 |

### 选择题

**1.**（20 分）题干一（　　）

A. 甲　　B. 乙　　C. 丙　　D. 丁


**2.**（20 分）题干二（　　）

A. 甲　　B. 乙　　C. 丙　　D. 丁


### 判断题

**3.**（30 分）判断题一。

<p align="right"><input type="checkbox"> </p>

**4.**（30 分）判断题二。

<p align="right"><input type="checkbox"> </p>

### 参考答案

**1.** A　**2.** C

**3.** 正确　**4.** 错误
"""


def test_good_paper_has_no_violations():
    paper = _paper(GOOD)
    assert [q.number for q in paper.questions] == [1, 2, 3, 4]
    assert sorted(set(paper.answer_numbers)) == [1, 2, 3, 4]
    assert paper.answer_heading_count == 1
    assert ec.check_paper(paper) == []
    assert ec.check_answer_detail(GOOD, paper) == []


def test_good_paper_fix_is_noop():
    """合格卷子必须逐字不动：修复器不能对正确内容做任何改写。"""
    fixed, violations = ec.fix_markdown(GOOD)
    assert violations == []
    assert fixed == GOOD


# ------------------------------------------------------------------ 账目


def test_score_table_not_summing_to_declared_total():
    """实测故障：规范模板各行之和 96，合计行与卷面声明都写 100。"""
    bad = GOOD.replace("| 判断题 | 3–4 | 2 | 30 | 60 |", "| 判断题 | 3–4 | 2 | 28 | 56 |")
    bad = bad.replace("（30 分）", "（28 分）")
    paper = _paper(bad)
    codes = [v.code for v in ec.check_paper(paper)]
    assert "E008" in codes
    e008 = next(v for v in ec.check_paper(paper) if v.code == "E008")
    assert e008.auto_fixable is True
    assert "96" in e008.detail and "100" in e008.detail


def test_accounting_fix_normalizes_to_actual_face_scores():
    """修复以「题面实际分值之和」为准，不凭空补分。"""
    bad = GOOD.replace("| 判断题 | 3–4 | 2 | 30 | 60 |", "| 判断题 | 3–4 | 2 | 28 | 56 |")
    bad = bad.replace("（30 分）", "（28 分）")
    fixed, violations = ec.fix_markdown(bad)
    assert any(v.code == "E008" and v.fixed for v in violations)
    assert "> 本卷满分 96 分" in fixed
    assert "| 合计 | 1–4 | 4 | — | 96 |" in fixed
    # 二轮校验必须干净（一轮修复的收敛性）
    assert ec.check_paper(_paper(fixed)) == []


def test_declared_count_mismatch_is_reported():
    bad = GOOD.replace("共 4 题", "共 5 题")
    codes = [v.code for v in ec.check_paper(_paper(bad))]
    assert "E007" in codes


def test_count_times_each_not_equal_subtotal():
    """6×5=30 却写小计 28：乘积与小计不一致也要报。"""
    bad = GOOD.replace("| 选择题 | 1–2 | 2 | 20 | 40 |", "| 选择题 | 1–2 | 2 | 20 | 38 |")
    bad = bad.replace("| 判断题 | 3–4 | 2 | 30 | 60 |", "| 判断题 | 3–4 | 2 | 31 | 62 |")
    bad = bad.replace("（20 分）", "（20 分）").replace("（30 分）", "（31 分）")
    detail = next(v for v in ec.check_paper(_paper(bad)) if v.code == "E008").detail
    assert "2×20=40 ≠ 小计 38" in detail


# ------------------------------------------------------------------ 题号与分值括注


def test_bare_question_numbers_are_renumbered_and_bolded():
    bad = GOOD.replace("**3.**（30 分）判断题一。", "3.（30 分）判断题一。")
    bad = bad.replace("**4.**（30 分）判断题二。", "4.（30 分）判断题二。")
    paper = _paper(bad)
    assert "E003" in [v.code for v in ec.check_paper(paper)]
    fixed, violations = ec.fix_markdown(bad)
    assert any(v.code == "E003" and v.fixed for v in violations)
    assert "**3.**（30 分）判断题一。" in fixed
    assert "\n3.（30 分）" not in fixed


def test_missing_score_is_backfilled_from_table():
    """分值括注缺失时按分值表同题型回填（表里有统一分值才回填）。"""
    bad = GOOD.replace("**1.**（20 分）题干一", "**1.**题干一")
    paper = _paper(bad)
    assert "E004" in [v.code for v in ec.check_paper(paper)]
    fixed, violations = ec.fix_markdown(bad)
    assert any(v.code == "E004" and v.fixed for v in violations)
    assert "**1.**（20 分）题干一" in fixed


def test_score_backfill_keeps_space_when_table_has_no_value():
    """表里没有分值依据时不能编造分值，但题号后的空格必须保留。

    回归：早期实现把 `**1.** 题干` 压成 `**1.**题干`，题号与题干粘连。
    """
    no_table = """
### 选择题

**1.** 题干一（　　）

A. 甲　　B. 乙

### 参考答案

**1.** A
"""
    fixed, _ = ec.fix_markdown(no_table)
    assert "**1.** 题干一" in fixed
    assert "**1.**题干" not in fixed


def test_duplicate_question_numbers_reported():
    bad = GOOD.replace("**2.**（20 分）题干二", "**1.**（20 分）题干二")
    vs = [v for v in ec.check_paper(_paper(bad)) if v.code == "E005"]
    # 题号重复会同时触发「不连续」与「重复」两条 E005，断言两条都在
    joined = "；".join(v.detail for v in vs)
    assert "重复" in joined and "[1]" in joined
    # 有重复号 => 全部 E005 都不可自动修（重编号会使答案错配）
    assert vs and all(not v.auto_fixable for v in vs)


def test_duplicate_numbers_are_not_renumbered():
    """题号重复时**不得**重编号：映射会多对一坍缩，导致答案与题目错配。

    实测早期实现把答案区的 `**1.**` 错映射成 `**2.**`，一条答案凭空消失。
    正确行为是保留原题号、只把 E005 报为不可自动修（交人工决定哪个号是对的）。
    """
    bad = GOOD.replace("**2.**（20 分）题干二", "**1.**（20 分）题干二")
    fixed, violations = ec.fix_markdown(bad)
    e005 = [v for v in violations if v.code == "E005"]
    assert e005 and all(not v.auto_fixable for v in e005)
    assert all(not v.fixed for v in e005)
    # 题号保持原样（没有被重编），答案区题号也没被错映射：
    # 只改了题面的第 2 题题号，答案区 `**1.** A　**2.** C` 未动，仍是完整 1..4。
    # 关键断言是「答案区没有被重编号破坏」——早期实现会把它错映射成 2..4。
    paper = ec.parse_paper(fixed)
    assert sorted(set(paper.answer_numbers)) == [1, 2, 3, 4]
    # 但加粗形式与分值括注这类**不改动题号**的修复仍应照常执行
    assert "**1.**（20 分）题干二" in fixed


def test_renumber_applies_when_no_duplicates():
    """无重复时正常连续重编号，且答案题号同步映射，一轮收敛。"""
    # 题号从 5 开始（非 1..4），但无重复 => 可安全重编号
    bad = (GOOD
           .replace("**1.**（20 分）", "**5.**（20 分）")
           .replace("**2.**（20 分）", "**6.**（20 分）")
           .replace("**3.**（30 分）", "**7.**（30 分）")
           .replace("**4.**（30 分）", "**8.**（30 分）")
           .replace("**1.** A　**2.** C", "**5.** A　**6.** C")
           .replace("**3.** 正确　**4.** 错误", "**7.** 正确　**8.** 错误"))
    fixed, violations = ec.fix_markdown(bad)
    assert any(v.code == "E005" and v.fixed for v in violations)
    paper = ec.parse_paper(fixed)
    assert [q.number for q in paper.questions] == [1, 2, 3, 4]
    assert sorted(set(paper.answer_numbers)) == [1, 2, 3, 4]
    assert ec.fix_markdown(fixed)[0] == fixed


# ------------------------------------------------------------------ 答案小节


def test_answer_numbers_on_one_line_are_all_collected():
    """回归：答案区一行多题号（`**1.** A　**2.** C`）必须全部收齐。

    早期实现按行首匹配，只拿到第 1 题，每卷都误报「答案区缺题号 2..16」。
    """
    paper = _paper(GOOD)
    assert sorted(set(paper.answer_numbers)) == [1, 2, 3, 4]
    assert not [v for v in ec.check_paper(paper) if v.code == "E006"]


def test_bare_answer_numbers_are_collected():
    """回归：答案区用裸题号（`1. A。`）时不能被当成题目解析。"""
    bad = GOOD.replace("**1.** A　**2.** C", "1. A\n2. C")
    paper = _paper(bad)
    assert 1 in paper.answer_numbers and 2 in paper.answer_numbers
    # 题面仍只有 4 题，答案行不得混进 questions
    assert len(paper.questions) == 4
    assert not [v for v in ec.check_paper(paper) if v.code == "E006"]


def test_variant_answer_headings_reported_and_renamed():
    """实测 5 种自拟答案小节名：「选择题答案」「判断题答案」等。"""
    bad = GOOD.replace(
        "### 参考答案\n\n**1.** A　**2.** C\n\n**3.** 正确　**4.** 错误",
        "### 参考答案\n\n#### 选择题答案\n\n**1.** A　**2.** C\n\n#### 判断题答案\n\n**3.** 正确　**4.** 错误",
    )
    paper = _paper(bad)
    v002 = [v for v in ec.check_paper(paper) if v.code == "E002"]
    assert v002 and "选择题答案" in v002[0].detail
    fixed, violations = ec.fix_markdown(bad)
    assert any(v.code == "E002" and v.fixed for v in violations)
    assert "#### 选择题答案" not in fixed
    assert "#### 判断题答案" not in fixed
    # 答案正文一个字都不能丢
    assert "**1.** A　**2.** C" in fixed
    assert "**3.** 正确　**4.** 错误" in fixed


def test_meta_section_inside_answer_block_does_not_reopen_questions():
    """**回归测试**：答案区里夹元栏目时，答案不得被重新编号。

    实测第三套的答案区里有「#### 概念标注（全卷）」，早期实现据此关闭 in_answer，
    于是 18 条答案被当成题目重新编号成 19..36，第二轮修复不幂等。
    """
    bad = GOOD.replace(
        "### 参考答案\n\n**1.** A",
        "### 参考答案\n\n#### 概念标注（全卷）\n- 矩阵的秩：行向量组的极大线性无关组所含向量个数。\n\n**1.** A",
    )
    fixed, _ = ec.fix_markdown(bad)
    # 答案题号必须仍是 1..4，绝不能变成 5..8
    for wrong in ("**5.**", "**6.**", "**7.**", "**8.**"):
        assert wrong not in fixed, f"答案被重新编号：出现 {wrong}"
    assert "**1.** A" in fixed
    # 幂等性：再修一次不得有任何变化
    fixed2, _ = ec.fix_markdown(fixed)
    assert fixed2 == fixed
    # 元栏目仍要如实报告（内容删除不可逆，交人工决定）
    assert "E009" in [v.code for v in ec.check_paper(_paper(bad))]


def test_meta_section_with_suffix_is_detected():
    """「概念标注（全卷）」带括号后缀也要命中 forbidden。"""
    bad = GOOD.replace("### 选择题", "### 概念标注（全卷）\n\n### 选择题")
    assert "E009" in [v.code for v in ec.check_paper(_paper(bad))]


def test_illegal_type_name_reported():
    bad = GOOD.replace("### 判断题", "### 计算与证明题")
    v = [x for x in ec.check_paper(_paper(bad)) if x.code == "E001"]
    assert v and "计算与证明题" in v[0].detail


def test_material_types_are_allowed():
    """材料给了题型划分时（_EXAM_SUGGESTED_RULES）沿用不算非法。"""
    bad = GOOD.replace("### 判断题", "### 计算题")
    assert "E001" not in [v.code for v in ec.check_paper(_paper(bad), material_types={"计算题"})]
    assert "E001" in [v.code for v in ec.check_paper(_paper(bad))]


def test_type_order_mismatch_reported():
    bad = GOOD.replace("| 选择题 | 1–2 | 2 | 20 | 40 |\n| 判断题 | 3–4 | 2 | 30 | 60 |",
                       "| 判断题 | 3–4 | 2 | 30 | 60 |\n| 选择题 | 1–2 | 2 | 20 | 40 |")
    assert "E010" in [v.code for v in ec.check_paper(_paper(bad))]


# ------------------------------------------------------------------ 内容层信号


def test_uncertain_answer_reported():
    """实测第五套压轴题答案原文含「此处结论标注『需核验』」。"""
    bad = GOOD.replace("**3.** 正确　**4.** 错误", "**3.** 正确　**4.** 错误（此处结论标注「需核验」）")
    v = ec.check_answer_detail(bad, _paper(bad))
    assert "E015" in [x.code for x in v]
    # 不可自动修：删掉「需核验」会掩盖真实的不确定性
    assert all(not x.auto_fixable for x in v if x.code == "E015")


def test_objective_answer_with_explanation_reported():
    bad = GOOD.replace(
        "**1.** A　**2.** C",
        "**1.** A。因为由定义可知第一项为负，所以选 A　**2.** C",
    )
    v = ec.check_answer_detail(bad, _paper(bad))
    assert "E012" in [x.code for x in v]


# ------------------------------------------------------------------ 文档级


def test_whole_document_checks():
    doc = "# 卷名\n\n## 一、第一套\n\n### 选择题\n\n**1.**（4 分）题干\n\n请在此作答\n"
    codes = [v.code for v in ec.check_whole_document(doc)]
    assert "E014" in codes


def test_placeholder_text_is_removed():
    bad = GOOD.replace("**1.**（20 分）题干一（　　）", "**1.**（20 分）题干一（　　）\n\n请在答题位置作答")
    fixed, violations = ec.fix_markdown(bad)
    assert "答题位置" not in fixed
    assert any(v.code == "E014" and v.fixed for v in violations)


# ------------------------------------------------------------------ 切卷与识别


def test_split_papers():
    doc = "# 标题\n\n## 一、第一套卷\n\n正文A\n\n## 二、第二套卷\n\n正文B\n"
    parts = ec.split_papers(doc)
    assert [n for n, _ in parts] == ["一、第一套卷", "二、第二套卷"]
    assert parts[0][1].strip() == "正文A"


def test_is_exam_markdown_true():
    assert ec.is_exam_markdown(GOOD)


def test_is_exam_markdown_false_for_tutorial_body():
    """讲解型教程的有序列表不能被误判成试卷（否则一片假阳性）。"""
    tutorial = """
### 一、安装步骤

1. 下载安装包
2. 双击运行
3. 按提示完成配置

### 二、常见问题

- 配置丢失：检查环境变量
- 启动失败：查看日志
"""
    assert ec.is_exam_markdown(tutorial) is False


def test_code_fence_content_is_ignored():
    """代码块里的 `**1.**` 与 `| 表格 |` 不参与解析。"""
    fenced = GOOD + "\n```\n**99.** 这是代码示例\n| 选择题 | 1–8 | 8 | 4 | 32 |\n```\n"
    paper = _paper(fenced)
    assert 99 not in [q.number for q in paper.questions]
    assert [v.code for v in ec.check_paper(paper)] == []
