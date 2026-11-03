# -*- coding: utf-8 -*-
"""exam_check 管线接入层测试：classify_spec / apply_to_section / apply_to_content。

这一层决定「哪些 section 会被校验」与「按哪种规范校验」，判错就会
要么静默漏检（试卷没被认出来），要么误伤讲解型教程（把有序列表当题号）。
"""
from __future__ import annotations

from app.services import exam_check as ec


EXAM_BODY = """
> 本卷满分 100 分，考试时间 120 分钟，共 2 题。

| 题型 | 题号 | 题量 | 每题分值 | 小计 |
|---|---|---|---|---|
| 选择题 | 1–2 | 2 | 25 | 50 |
| 判断题 | 3–4 | 2 | 25 | 50 |
| 合计 | 1–4 | 4 | — | 100 |

### 选择题

**1.**（25 分）题干（　　）

A. 甲　　B. 乙


**2.**（25 分）题干（　　）

A. 甲　　B. 乙


### 判断题

**3.**（25 分）判断题。

<p align="right"><input type="checkbox"> </p>

**4.**（25 分）判断题二。

<p align="right"><input type="checkbox"> </p>

### 参考答案

**1.** A　**2.** B

**3.** 正确　**4.** 错误
"""

TUTORIAL_BODY = """
### 一、安装步骤

1. 下载安装包
2. 双击运行
3. 按提示完成配置

### 二、常见问题

- 配置丢失：检查环境变量
- 启动失败：查看日志
"""


def _section(title: str, body: str) -> dict:
    return {"title": title, "content": [{"type": "example", "title": title, "body": body}]}


# ------------------------------------------------------------------ 分类


def test_classify_by_scene_exam():
    assert ec.classify_spec("任意标题", {"scene": "exam_paper"}, EXAM_BODY) == "exam"


def test_classify_by_scene_exercise():
    assert ec.classify_spec("任意标题", {"scene": "exercise"}, EXAM_BODY) == "exercise"


def test_classify_by_title_when_scene_missing():
    """旧数据没有 scene：靠标题里的卷种名词 + 正文形态判定。"""
    assert ec.classify_spec("第 1 章 线性方程组 单元检测卷", {}, EXAM_BODY) == "exam"
    assert ec.classify_spec("线性代数期中模拟试卷", {}, EXAM_BODY) == "exam"


def test_classify_skips_tutorial_sections():
    """讲解型教程的有序列表不得被当成试卷（否则一片假阳性）。"""
    assert ec.classify_spec("第一章 环境准备", {}, TUTORIAL_BODY) is None
    assert ec.classify_spec("第一章 环境准备", {"scene": "default_tutorial"}, TUTORIAL_BODY) is None


def test_classify_by_exercise_marker():
    body = EXAM_BODY.replace("### 选择题", "### 一、易错辨析").replace("### 判断题", "### 二、训练")
    assert ec.classify_spec("第一章 练习", {}, body) == "exercise"


# ------------------------------------------------------------------ 单节


def test_apply_to_section_fixes_and_reports():
    """账目错的卷（同题型分值均匀）：就地修复，并返回违规清单。"""
    # 满分声明与合计行都写 100，但题面实际只有 25+25+25+25=100…改表让它对不上：
    bad = EXAM_BODY.replace("| 判断题 | 3–4 | 2 | 25 | 50 |", "| 判断题 | 3–4 | 2 | 20 | 40 |")
    section = _section("期中模拟试卷", bad)
    result = ec.apply_to_section(section, {"scene": "exam_paper"})
    assert result["spec"] == "exam" and result["changed"] is True
    assert any(v["code"] == "E008" and v["fixed"] for v in result["violations"])
    # 以题面实际分值之和为准（25+25+25+25=100），表格与合计行被校正回自洽
    reparsed = ec.parse_paper(ec.section_body(section))
    assert not [v for v in ec.check_paper(reparsed) if v.code == "E008"]
    assert reparsed.lead_total == 100


def test_non_uniform_scores_are_not_auto_fixed():
    """同题型各题分值不同时**不得**自动改账目。

    实测踩坑：判断题一题 20 分、一题 25 分时，早期实现把小计改成实际之和 45，
    却留下「2×20=40 ≠ 小计 45」，产出一张比原来更自相矛盾的表。改题面分值会动
    配分结构（内容决策），改表格等于编数，两者都只能交人工。
    """
    bad = EXAM_BODY.replace("**4.**（25 分）判断题二。", "**4.**（20 分）判断题二。")
    bad = bad.replace("| 判断题 | 3–4 | 2 | 25 | 50 |", "| 判断题 | 3–4 | 2 | 25 | 45 |")
    section = _section("期中模拟试卷", bad)
    result = ec.apply_to_section(section, {"scene": "exam_paper"})
    e008 = [v for v in result["violations"] if v["code"] == "E008"]
    assert e008 and not e008[0]["auto_fixable"] and not e008[0]["fixed"]
    assert "无法表达事实" in e008[0]["detail"]
    assert not ec.score_is_uniform(ec.parse_paper(bad))
    # 属 blocking：必须进 issues，不能静默交付
    content = {"format_spec": {"scene": "exam_paper"}, "sections": [section]}
    assert any("E008" in i for i in ec.quality_issues(ec.apply_to_content(content)))


def test_apply_to_section_noop_for_tutorial():
    """讲解型教程 section 必须原样不动。"""
    section = _section("第一章 环境准备", TUTORIAL_BODY)
    before = ec.section_body(section)
    result = ec.apply_to_section(section, {})
    assert result["spec"] is None and result["changed"] is False
    assert result["violations"] == []
    assert ec.section_body(section) == before


def test_apply_to_section_preserves_answer_text():
    """自拟答案小节名被改回「参考答案」，且答案内容一字不动。"""
    section = _section("期中模拟试卷", EXAM_BODY.replace("### 参考答案", "### 参考答案与评分说明"))
    result = ec.apply_to_section(section, {"scene": "exam_paper"})
    body = ec.section_body(section)
    assert "**1.** A　**2.** B" in body
    assert "**3.** 正确　**4.** 错误" in body
    # 「参考答案与评分说明」是 forbidden 明令禁止的自拟名，必须被检出并改名
    assert any(v["code"] == "E002" and v["fixed"] for v in result["violations"])
    assert "### 参考答案\n" in body
    assert "参考答案与评分说明" not in body


def test_section_body_joins_multiple_blocks():
    """模型有时把参考答案单独放一块：必须拼接全部块，只看第一块会漏掉答案区。"""
    section = {
        "title": "期中模拟试卷",
        "content": [
            {"type": "example", "title": "", "body": "### 选择题\n\n**1.**（4 分）题干\n"},
            {"type": "text", "title": "", "body": "### 参考答案\n\n**1.** A\n"},
        ],
    }
    body = ec.section_body(section)
    assert "### 参考答案" in body and "**1.** A" in body


# ------------------------------------------------------------------ 整份内容


# 含真实数学定义式的母题：跨卷一致性靠「共享定义式」聚类，
# 纯中文「题干」抽不出数学指纹，聚不成簇（这不是缺陷，是判据设计）。
_MOTIF_Q = "**1.**（25 分）设 $f_n(x)=x^n+2nx-2$ 的正根为 $a_n$，则 $\\lim_{n\\to\\infty}(1+a_n)^n=$（　　）\n\nA. $1$　　B. $e$　　C. $e^2$　　D. $+\\infty$"


def test_apply_to_content_cross_paper_conflict_is_blocking():
    """两份卷同一母题给不同答案：E018 必须让 checks 判为未通过。"""
    body_a = EXAM_BODY.replace("**1.**（25 分）题干（　　）\n\nA. 甲　　B. 乙", _MOTIF_Q) \
        .replace("**1.** A　**2.** B", "**1.** C　**2.** B")
    body_b = EXAM_BODY.replace("**1.**（25 分）题干（　　）\n\nA. 甲　　B. 乙", _MOTIF_Q) \
        .replace("**1.** A　**2.** B", "**1.** B　**2.** A")
    content = {
        "format_spec": {"scene": "exam_paper"},
        "sections": [
            _section("第一套试卷", body_a),
            _section("第二套试卷", body_b),
        ],
    }
    summary = ec.apply_to_content(content)
    assert any(v["code"] == "E018" for v in summary["cross"])
    cross_check = next(c for c in ec.quality_checks(summary) if c["name"] == "跨卷命题一致性")
    assert cross_check["passed"] is False
    assert any("E018" in i for i in ec.quality_issues(summary))


def test_apply_to_content_extra_exercises_checked():
    """额外练习文件此前完全裸奔：这里必须被校验且逐节重编号。"""
    md = "\n".join([
        "# 教程 · 额外练习", "",
        "## 第一章", "", "### 一、易错辨析", "",
        "**3.** 判断题。", "", '<p align="right"><input type="checkbox"> </p>', "",
        "### 参考答案", "", "**3.** 错误。", "",
        "## 第二章", "", "### 一、易错辨析", "",
        "**5.** 判断题。", "", '<p align="right"><input type="checkbox"> </p>', "",
        "### 参考答案", "", "**5.** 错误。", "",
    ])
    content = {
        "format_spec": {"scene": "default_tutorial"},
        "sections": [_section("第一章 环境准备", TUTORIAL_BODY)],
        "extra_exercises": {"title": "教程 · 额外练习", "markdown": md},
    }
    summary = ec.apply_to_content(content)
    assert summary["extra_exercises"] is not None
    assert summary["extra_exercises"]["changed"] is True
    # 各节独立从 1 编号（练习规范要求），且答案跟着改
    fixed = content["extra_exercises"]["markdown"]
    assert "**1.** 判断题。" in fixed
    assert "**3.** 判断题。" not in fixed and "**5.** 判断题。" not in fixed
    # 讲解型章节不受影响
    assert ec.section_body(content["sections"][0]) == TUTORIAL_BODY


def test_advisory_only_does_not_block_delivery():
    """只有留白不符（advisory）时不得让教程判为不合格。

    实测一份 5 套卷有 42 处 E013、10 处 E017，而真正严重的 E018 只有 2 处；
    把 advisory 算进 passed 会让几乎每份卷子都变「待改进」，淹没真信号。
    """
    section = _section("期中模拟试卷", EXAM_BODY.replace("A. 甲　　B. 乙\n\n\n", "A. 甲　　B. 乙\n"))
    content = {"format_spec": {"scene": "exam_paper"}, "sections": [section]}
    summary = ec.apply_to_content(content)
    codes = {v["code"] for item in summary["sections"] for v in item["violations"] if not v["fixed"]}
    assert codes <= {"E013", "E017", "E003", "E004", "E010", "E012"}
    assert all(not ec.is_blocking(c) for c in codes)
    assert ec.quality_issues(summary) == []
    assert all(c["passed"] for c in ec.quality_checks(summary))


def test_quality_issues_advisory_flag():
    section = _section("期中模拟试卷", EXAM_BODY.replace("A. 甲　　B. 乙\n\n\n", "A. 甲　　B. 乙\n"))
    content = {"format_spec": {"scene": "exam_paper"}, "sections": [section]}
    summary = ec.apply_to_content(content)
    assert ec.quality_issues(summary) == []
    assert any("E013" in i for i in ec.quality_issues(summary, advisory=True))


def test_fix_is_idempotent_through_pipeline():
    """「只改一次」的可测试形式：整份内容跑两遍，第二遍不得再有任何改动。"""
    bad = EXAM_BODY.replace("| 判断题 | 3–4 | 2 | 25 | 50 |", "| 判断题 | 3–4 | 2 | 20 | 40 |")
    content = {"format_spec": {"scene": "exam_paper"}, "sections": [_section("期中模拟试卷", bad)]}
    first = ec.apply_to_content(content)
    assert any(i["changed"] for i in first["sections"])
    snapshot = ec.section_body(content["sections"][0])
    second = ec.apply_to_content(content)
    assert not any(i["changed"] for i in second["sections"])
    assert ec.section_body(content["sections"][0]) == snapshot
