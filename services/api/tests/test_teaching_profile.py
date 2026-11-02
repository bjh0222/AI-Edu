"""用户画像规则解析、按阶段注入与硬约束核验的针对性测试。"""

from app.learning.teaching_profile import (
    check_rule_compliance,
    condition_triggers,
    delivery_contract_for,
    goal_context_text,
    normalize_teaching_plan,
    parse_teaching_profile,
    rule_is_active,
    select_rules,
)
from app.llm import prompts

# 用户真实画像里的最后一条：条件满足时必须只交付试卷清单
_PAPER_RULE = (
    "当“学完想能做什么”中出现“输出试卷“的时候，务必模仿参考资料输出标准试卷，"
    "且内容只包括对真题风格的简要分析，三套模拟试卷和对压轴题的3个合理拓展，不要输出答案及其它内容"
)


def _goal(**overrides):
    attrs = {
        "title": "查一个简单命令",
        "motivation": "",
        "application_context": "",
        "current_level": "",
        "time_budget": "",
        "capability_level": "L2",
        "user_notes": "",
    }
    attrs.update(overrides)
    return type("G", (), attrs)()


DISCIPLINE = type("D", (), {"display_name": "计算机/命令行"})()


def _set_profile(client, content: str) -> None:
    resp = client.put("/api/settings/models/user-profile", json={"content": content})
    assert resp.status_code == 200, resp.text


def test_parse_teaching_profile_classifies_rule_strength():
    profile = parse_teaching_profile(
        "- 不要跳过理解当前知识所必需的推理步骤\n"
        "必须解释关键推理步骤\n"
        "如果遇到抽象概念，先给一个具体例子\n"
        "先看整体框架\n"
    )
    rules = profile["rules"]
    assert [rule["rule_type"] for rule in rules] == ["forbidden", "required", "conditional", "default"]
    assert [rule["hard"] for rule in rules] == [True, True, False, False]


def test_rule_scopes_tag_what_a_rule_is_about():
    rules = parse_teaching_profile(
        "不要跳过前置概念\n先给一个具体例子\n练习按难度递增\n不要安排日程\n"
    )["rules"]
    assert rules[0]["scopes"] == ["depth"]
    assert rules[1]["scopes"] == ["example"]
    assert rules[2]["scopes"] == ["exercise"]
    assert rules[3]["scopes"] == ["schedule"]


def test_select_rules_drops_irrelevant_soft_rules_but_keeps_hard_rules():
    rules = parse_teaching_profile(
        "不要跳过前置概念\n先给一个具体例子\n练习按难度递增\n"
    )["rules"]

    cheatsheet_texts = [rule["text"] for rule in select_rules(rules, "cheatsheet")["rules"]]
    # 速查文件不需要「例题顺序」「练习梯度」，但硬性约束不能因为阶段不相关被丢弃
    assert "先给一个具体例子" not in cheatsheet_texts
    assert "练习按难度递增" not in cheatsheet_texts
    assert "不要跳过前置概念" in cheatsheet_texts

    section_texts = [rule["text"] for rule in select_rules(rules, "section")["rules"]]
    assert "先给一个具体例子" in section_texts
    assert "练习按难度递增" in section_texts


def test_select_rules_caps_soft_rules_with_budget():
    rules = [
        {
            "id": f"rule-{index:02d}",
            "text": "很长的导向规则" * 10,
            "rule_type": "default",
            "hard": False,
            "scopes": ["general"],
        }
        for index in range(5)
    ]
    selection = select_rules(rules, "section", budget_chars=100)
    assert selection["soft_count"] == 1
    assert len(selection["dropped"]) == 4

    hard = {
        "id": "rule-99",
        "text": "不要安排日程" * 20,
        "rule_type": "forbidden",
        "hard": True,
        "scopes": ["schedule"],
    }
    selection = select_rules([*rules, hard], "section", budget_chars=100)
    assert any(rule["id"] == "rule-99" for rule in selection["rules"])


def test_check_rule_compliance_flags_forbidden_expressions_only():
    rules = parse_teaching_profile("不要安排日程\n不要加标签\n")["rules"]

    schedule_hits = check_rule_compliance("本章学习计划：第 3 天复习一遍。", rules)
    assert [hit["rule"] for hit in schedule_hits] == ["不要安排日程"]

    tag_hits = check_rule_compliance("正文末尾堆叠 #基础 #命令行", rules)
    assert [hit["rule"] for hit in tag_hits] == ["不要加标签"]

    assert check_rule_compliance("本章讲解管道原理，用时 1–2 小时。", rules) == []


def test_prompt_separates_charter_from_task_requirements(client):
    _set_profile(client, "不要跳过前置概念\n必须解释关键推理步骤\n先看整体框架\n")

    goal = _goal(user_notes="本次只要速查式结果，不要展开整体框架")
    _, user = prompts.outline(goal, DISCIPLINE, [])
    assert "长期教学宪章" in user
    assert "硬性约束" in user
    assert "教学导向" in user
    assert "- [禁止] 不要跳过前置概念" in user
    assert "- [必须] 必须解释关键推理步骤" in user
    assert "- [默认偏好] 先看整体框架" in user
    assert "交付前自检" in user
    assert "current_task_special_requirements" in user
    assert "本次只要速查式结果" in user
    assert "普通偏好，写入 task_overrides" in user


def test_empty_profile_injects_no_charter(client):
    _set_profile(client, "")
    _, user = prompts.outline(_goal(), DISCIPLINE, [])
    assert "长期教学宪章" not in user


def test_section_prompt_injects_each_rule_exactly_once(client):
    _set_profile(client, "不要跳过前置概念\n必须解释关键推理步骤\n先看整体框架\n")

    plan = normalize_teaching_plan({"decisions": ["按单命令速查组织"]})
    item = {"title": "管道的用法", "_teaching_plan": plan}
    _, user = prompts.section(_goal(), DISCIPLINE, item, [], [])
    assert user.count("不要跳过前置概念") == 1
    assert user.count("必须解释关键推理步骤") == 1
    assert "按单命令速查组织" in user


def test_stage_specific_charter_keeps_only_relevant_soft_rules(client):
    _set_profile(client, "不要跳过前置概念\n练习按难度递增\n")

    _, section_user = prompts.section(_goal(), DISCIPLINE, {"title": "管道"}, [], [])
    _, cheatsheet_user = prompts.cheatsheet(_goal(), DISCIPLINE, [])

    assert "练习按难度递增" in section_user
    assert "练习按难度递增" not in cheatsheet_user
    assert "不要跳过前置概念" in cheatsheet_user


def _real_mode_service(monkeypatch, payloads):
    """构造一个「非演示模式」的 AIService：_real_json 依次返回 payloads，并记录提示词。"""
    from app.llm.service import AIService

    seen: list[str] = []
    ai = AIService(None)
    monkeypatch.setattr(type(ai), "is_demo", property(lambda self: False))

    def fake_real_json(feature, system, user, required, goal=None):
        seen.append(user)
        return payloads[min(len(seen) - 1, len(payloads) - 1)]

    monkeypatch.setattr(ai, "_real_json", fake_real_json)
    return ai, seen


def test_section_repairs_forbidden_schedule_expression_once(client, monkeypatch):
    _set_profile(client, "不要安排日程\n")

    dirty = {
        "title": "管道的用法",
        "content": [{"type": "text", "title": "学习计划", "body": "第 2 天复习一遍"}],
        "mapping_criteria": [],
    }
    clean = {
        "title": "管道的用法",
        "content": [{"type": "text", "title": "管道", "body": "把前一个命令的输出接到下一个"}],
        "mapping_criteria": [],
    }
    ai, seen = _real_mode_service(monkeypatch, [dirty, clean])

    data = ai.section(_goal(), DISCIPLINE, {"title": "管道"}, [], [])

    assert len(seen) == 2, "命中硬约束后应当只补一次定向修复"
    assert "不要安排日程" in seen[1]
    assert data["rule_check"] == {"repaired": True, "violations": ["出现按日历 / 天次分配时间的表述"]}
    assert "第 2 天" not in str(data["content"])


def test_section_keeps_first_output_when_repair_still_violates(client, monkeypatch):
    _set_profile(client, "不要安排日程\n")

    dirty = {
        "title": "管道的用法",
        "content": [{"type": "text", "title": "学习计划", "body": "每天复习 20 分钟"}],
        "mapping_criteria": [],
    }
    ai, seen = _real_mode_service(monkeypatch, [dirty, dict(dirty)])

    data = ai.section(_goal(), DISCIPLINE, {"title": "管道"}, [], [])

    assert len(seen) == 2, "只修复一次，不无限重试"
    assert data["rule_check"]["repaired"] is False
    assert "不要安排日程" in data["rule_check"]["violations"][0]


def test_cheatsheet_repairs_forbidden_schedule_expression_once(client, monkeypatch):
    """配套文件也注入画像，核验必须同样覆盖，否则硬约束只停留在提示词里。"""
    _set_profile(client, "不要安排日程\n")

    dirty = {"title": "速查", "sections": [{"heading": "复习节奏", "body": "第 3 天再看一遍"}]}
    clean = {"title": "速查", "sections": [{"heading": "管道", "body": "| 命令 | 用途 |"}]}
    ai, seen = _real_mode_service(monkeypatch, [dirty, clean])

    data = ai.cheatsheet(_goal(), DISCIPLINE, [])

    assert len(seen) == 2, "命中硬约束后应当只补一次定向修复"
    assert "不要安排日程" in seen[1]
    assert data["rule_check"] == {"repaired": True, "violations": ["出现按日历 / 天次分配时间的表述"]}
    assert "第 3 天" not in str(data["sections"])


def test_extra_exercises_keeps_first_output_when_repair_still_violates(client, monkeypatch):
    _set_profile(client, "不要安排日程\n")

    dirty = "# 练习\n\n**1.** 每天做一遍管道练习\n"
    still_dirty = "# 练习\n\n**1.** 每周完成一次复盘，每天看一眼\n"

    ai, seen = _real_mode_service(monkeypatch, [dirty, still_dirty])

    class _P:
        def complete_text(self, system, user):
            return ai._real_json("x", system, user, (), None), 1, None

    monkeypatch.setattr(ai, "provider", _P())

    data = ai.extra_exercises(_goal(), DISCIPLINE, [])

    assert len(seen) == 2, "只修复一次，不无限重试"
    assert data["rule_check"]["repaired"] is False
    assert "不要安排日程" in data["rule_check"]["violations"][0]
    assert data["markdown"] == dirty.strip()

def test_rule_check_is_not_dropped_by_response_schema():
    """核验结果必须穿得出去：响应模型此前没有这个字段，违规信息在 API 层被静默丢弃。"""
    from app.schemas import CheatsheetOut, SectionOut, TutorialContent

    check = {"repaired": False, "violations": ["不要安排日程（出现按日历 / 天次分配时间的表述）"]}
    section = SectionOut.model_validate(
        {"title": "管道", "content": [], "mapping_criteria": [], "rule_check": check}
    )
    assert section.rule_check is not None
    assert section.rule_check.repaired is False
    assert section.rule_check.violations == check["violations"]

    sheet = CheatsheetOut.model_validate({"title": "速查", "sections": [], "rule_check": check})
    assert sheet.rule_check is not None
    assert sheet.rule_check.violations == check["violations"]

    # 嵌套在教程内容里也不能被吞掉（这才是 API 实际返回的形状）
    content = TutorialContent.model_validate(
        {
            "outline": [],
            "sections": [
                {"title": "管道", "content": [], "mapping_criteria": [], "rule_check": check}
            ],
        }
    )
    assert content.sections[0].rule_check is not None
    assert content.sections[0].rule_check.violations == check["violations"]


def test_conditional_rule_is_inert_until_goal_matches_trigger(client):
    _set_profile(client, _PAPER_RULE)
    paper = _goal(title="线性代数期中冲刺", application_context="完成你输出的试卷")
    logs = _goal(title="掌握命令行管道", application_context="分析服务器日志")

    rule = parse_teaching_profile(_PAPER_RULE)["rules"][0]
    # 「当…的时候」是条件从句，强度由条件里的「务必 / 不要」决定，不能变成无条件硬约束
    assert rule["rule_type"] == "conditional"
    assert rule["hard"] is True
    assert condition_triggers(rule) == ["输出试卷"]
    assert rule_is_active(rule, goal_context_text(paper)) is True
    assert rule_is_active(rule, goal_context_text(logs)) is False

    # 条件不成立：整条规则不注入，并如实记到 inactive 里（可解释，不是静默丢失）
    data = parse_teaching_profile(_PAPER_RULE, context_text=goal_context_text(logs))
    assert data["rules"] == []
    assert data["inactive"] == [_PAPER_RULE]


def test_exhaustive_rule_becomes_delivery_contract(client):
    _set_profile(client, _PAPER_RULE)
    paper = _goal(title="线性代数期中冲刺", application_context="完成你输出的试卷")
    logs = _goal(title="掌握命令行管道", application_context="分析服务器日志")

    contract = delivery_contract_for(paper)
    assert contract["items"] == ["对真题风格的简要分析", "三套模拟试卷", "对压轴题的3个合理拓展"]
    assert contract["forbid_answers"] is True
    assert contract["suppress_companions"] is True
    assert delivery_contract_for(logs) is None


def test_section_prompt_switches_to_deliverable_mode(client):
    _set_profile(client, _PAPER_RULE)
    paper = _goal(title="线性代数期中冲刺", application_context="完成你输出的试卷")

    _, deliverable_user = prompts.section(
        paper, DISCIPLINE, {"title": "三套模拟试卷", "_deliverable": "三套模拟试卷"}, [], []
    )
    _, teaching_user = prompts.section(paper, DISCIPLINE, {"title": "矩阵运算"}, [], [])

    # 交付物章节直接产出成品，不能套讲解模板
    assert "不是教学讲解章节" in deliverable_user
    assert "分层讲解原则" not in deliverable_user
    assert "不写答案" in deliverable_user
    assert "分层讲解原则" in teaching_user


def test_outline_prompt_carries_delivery_contract(client):
    _set_profile(client, _PAPER_RULE)
    paper = _goal(title="线性代数期中冲刺", application_context="完成你输出的试卷")

    _, user = prompts.outline(paper, DISCIPLINE, [])

    assert "本次交付契约" in user
    assert "三套模拟试卷" in user
    assert "章节数必须严格等于 3" in user


def test_goal_asking_for_paper_gets_only_contract_deliverables(client):
    """端到端：提示词里的「只包括…」必须变成教程结构，而不是一份讲解教程。"""
    _set_profile(client, _PAPER_RULE)
    goal = client.post(
        "/api/goals",
        json={
            "title": "线性代数期中冲刺",
            "domain_key": "math_logic",
            "motivation": "期中考试冲刺满分",
            "application_context": "完成你输出的试卷",
            "current_level": "掌握必备知识",
            "time_budget": "共 3 小时",
        },
    ).json()
    body = client.post(f"/api/goals/{goal['id']}/tutorials/quickstart").json()
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{body['job_id']}").json()
        if job["status"] in ("done", "failed"):
            break
    assert job["status"] == "done", job

    content = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()["current_version"]["content"]
    assert [item["title"] for item in content["outline"]] == [
        "对真题风格的简要分析",
        "三套模拟试卷",
        "对压轴题的3个合理拓展",
    ]
    assert content["delivery_contract"]["forbid_answers"] is True
    # 「不要输出答案及其它内容」把配套文件也排除在外
    assert content.get("cheatsheet") is None


def test_unrelated_goal_keeps_normal_tutorial_shape(client):
    _set_profile(client, _PAPER_RULE)
    goal = client.post(
        "/api/goals",
        json={
            "title": "掌握命令行管道",
            "domain_key": "cs_it",
            "motivation": "处理日志",
            "application_context": "分析服务器日志",
        },
    ).json()
    body = client.post(f"/api/goals/{goal['id']}/tutorials/quickstart").json()
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{body['job_id']}").json()
        if job["status"] in ("done", "failed"):
            break
    assert job["status"] == "done", job

    content = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()["current_version"]["content"]
    assert content.get("delivery_contract") is None
    assert "三套模拟试卷" not in [item["title"] for item in content["outline"]]
    assert content.get("cheatsheet") is not None


def test_regenerating_old_tutorial_rebuilds_outline_from_contract(client):
    """已生成跑偏的教程：补上画像规则后重跑章节生成，结构必须被纠正。"""
    goal = client.post(
        "/api/goals",
        json={
            "title": "线性代数期中冲刺",
            "domain_key": "math_logic",
            "application_context": "完成你输出的试卷",
        },
    ).json()
    body = client.post(f"/api/goals/{goal['id']}/tutorials/quickstart").json()
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{body['job_id']}").json()
        if job["status"] in ("done", "failed"):
            break
    assert job["status"] == "done", job

    tutorial_id = body["tutorial"]["id"]
    before = client.get(f"/api/tutorials/{tutorial_id}").json()["current_version"]["content"]
    assert before.get("delivery_contract") is None
    assert "三套模拟试卷" not in [item["title"] for item in before["outline"]]

    # 规则是后来才补上的：重跑章节生成应按契约重建结构
    _set_profile(client, _PAPER_RULE)
    regen = client.post(f"/api/tutorials/{tutorial_id}/sections/generate").json()
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{regen['job_id']}").json()
        if job["status"] in ("done", "failed"):
            break
    assert job["status"] == "done", job

    after = client.get(f"/api/tutorials/{tutorial_id}").json()["current_version"]["content"]
    assert [item["title"] for item in after["outline"]] == [
        "对真题风格的简要分析",
        "三套模拟试卷",
        "对压轴题的3个合理拓展",
    ]
    assert after["delivery_contract"]["exclusive"] is True
    assert after.get("cheatsheet") is None


def test_quickstart_persists_teaching_plan(client):
    _set_profile(client, "不要跳过前置概念\n必须解释关键推理步骤\n先看整体框架\n")

    goal = client.post(
        "/api/goals",
        json={
            "title": "掌握命令行管道与重定向",
            "domain_key": "cs_it",
            "motivation": "处理日志",
            "application_context": "分析服务器日志",
            "current_level": "基础",
            "time_budget": "共 5 小时",
        },
    ).json()
    body = client.post(f"/api/goals/{goal['id']}/tutorials/quickstart").json()
    job_id = body["job_id"]
    assert job_id
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
    assert job["status"] == "done", job

    tutorial = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()
    plan = tutorial["current_version"]["content"]["teaching_plan"]
    assert plan["source"] == "long_term_user_profile"
    assert any("不要跳过前置概念" in text for text in plan["rules_applied"])
    assert any("必须解释关键推理步骤" in text for text in plan["rules_applied"])
    assert any(rule["hard"] for rule in plan["rules"])


def test_normalize_teaching_plan_keeps_hard_rules_when_model_omits_them():
    profile = parse_teaching_profile("不要跳过前置概念\n先看整体框架\n")
    plan = normalize_teaching_plan(
        {"rules_applied": ["先看整体框架"], "decisions": ["按单命令速查组织"]},
        profile,
    )
    assert "不要跳过前置概念" in plan["rules_applied"]
    assert "先看整体框架" in plan["rules_applied"]
    assert plan["decisions"] == ["按单命令速查组织"]


def test_rules_applied_lists_only_rules_actually_used():
    profile = parse_teaching_profile("不要跳过前置概念\n先看整体框架\n多给对比表格\n")
    plan = normalize_teaching_plan({"rules_applied": ["先看整体框架"]}, profile)
    # 模型没有采用的导向类规则不再被回填，教学决策保持收敛
    assert plan["rules_applied"] == ["不要跳过前置概念", "先看整体框架"]


def test_profile_suggestion_only_after_every_ten_completed_goals(client):
    goal_ids = []
    for index in range(10):
        goal = client.post(
            "/api/goals",
            json={"title": f"目标 {index + 1}", "domain_key": "cs_it"},
        ).json()
        resp = client.patch(f"/api/goals/{goal['id']}", json={"completed": True})
        assert resp.status_code == 200, resp.text
        goal_ids.append(goal["id"])

        state = client.get("/api/settings/models/user-profile-suggestion").json()
        if index < 9:
            assert state["eligible"] is False

    state = client.get("/api/settings/models/user-profile-suggestion").json()
    assert state["eligible"] is True
    assert state["suggestion"] is not None
    assert "演示建议" in state["suggestion"]["notes"]

    dismissed = client.post("/api/settings/models/user-profile-suggestion/dismiss").json()
    assert dismissed["eligible"] is False
    assert client.get("/api/settings/models/user-profile-suggestion").json()["eligible"] is False
