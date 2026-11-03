"""格式规范：管理、匹配、任务快照与交付契约。"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.learning.disciplines import get_profile
from app.llm import prompts
from app.services.format_specs import check_snapshot_delivery, delivery_contract_for_snapshot
from app.services.utils import align_section_titles, prune_foreign_section_blocks
from app.services.tutorials import _render_format_spec_document


def _payload(name: str = "速查表规范", **overrides) -> dict:
    data = {
        "name": name,
        "description": "整理考前速查材料。",
        "scene": "cheatsheet",
        "applicable_tasks": "整理速查材料",
        "applicable_intents": ["整理速查材料"],
        "excluded_intents": ["讲解知识点"],
        "trigger_keywords": ["速查材料"],
        "excluded_keywords": ["解释"],
        "target_reader": "学生",
        "output_goal": "输出高密度速查材料。",
        "deliverables": [
            {"name": "知识速查", "status": "required", "order": 1, "allow_override": True},
        ],
        "content_structure": "# 速查\n\n## 分类",
        "format_rules": "使用短列表和表格。",
        "forbidden_rules": "不输出长篇教程。",
        "acceptance_criteria": "- 分类完整\n- 无无关内容",
        "custom_markdown": "# 只属于本规范的自定义规则",
    }
    data.update(overrides)
    return data


def test_builtin_specs_initialize_once_and_stay_editable(client: TestClient):
    first = client.get("/api/format-specs")
    assert first.status_code == 200
    specs = first.json()
    assert {item["scene"] for item in specs} >= {"default_tutorial", "exam_paper"}
    assert sum(bool(item["is_default"]) for item in specs) == 1

    exam = next(item for item in specs if item["scene"] == "exam_paper")
    changed = client.put(
        f"/api/format-specs/{exam['id']}",
        json={**exam, "forbidden_rules": exam["forbidden_rules"] + "\n- 测试新增规则"},
    )
    assert changed.status_code == 200
    assert "测试新增规则" in changed.json()["forbidden_rules"]
    assert changed.json()["version"] == exam["version"] + 1

    restarted = client.get("/api/format-specs")
    assert restarted.status_code == 200
    assert restarted.json() == changed_context_specs(changed.json(), restarted.json())


def changed_context_specs(updated: dict, specs: list[dict]) -> list[dict]:
    return [
        updated if item["id"] == updated["id"] else item
        for item in specs
    ]


def test_format_spec_crud_default_uniqueness_and_custom_markdown(client: TestClient):
    created = client.post("/api/format-specs", json=_payload())
    assert created.status_code == 200
    spec = created.json()
    assert spec["custom_markdown"] == "# 只属于本规范的自定义规则"

    copied = client.post(f"/api/format-specs/{spec['id']}/duplicate")
    assert copied.status_code == 200
    assert copied.json()["custom_markdown"] == spec["custom_markdown"]

    updated = client.put(
        f"/api/format-specs/{spec['id']}",
        json={**spec, "format_rules": "更新后的格式规则。"},
    )
    assert updated.status_code == 200
    assert updated.json()["format_rules"] == "更新后的格式规则。"
    assert updated.json()["custom_markdown"] == spec["custom_markdown"]

    default = client.post(f"/api/format-specs/{spec['id']}/default")
    assert default.status_code == 200
    assert all(
        (item["id"] == spec["id"]) == item["is_default"]
        for item in client.get("/api/format-specs").json()
    )

    deleted = client.delete(f"/api/format-specs/{spec['id']}")
    assert deleted.status_code == 200
    specs = client.get("/api/format-specs").json()
    assert specs
    assert sum(bool(item["is_default"]) for item in specs) == 1


def test_matching_explicit_keyword_and_exclusion(client: TestClient):
    specs = client.get("/api/format-specs").json()
    exam = next(item for item in specs if item["scene"] == "exam_paper")
    default = next(item for item in specs if item["is_default"])

    matched = client.post("/api/format-specs/match", json={"requirement": "生成一份模拟试卷"})
    assert matched.status_code == 200
    assert matched.json()["source"] == "keyword"
    assert matched.json()["spec"]["id"] == exam["id"]

    explicit = client.post("/api/format-specs/match", json={"requirement": "使用试卷生成规范出题"})
    assert explicit.status_code == 200
    assert explicit.json()["spec"]["id"] == exam["id"]

    excluded = client.post(
        "/api/format-specs/match", json={"requirement": "解释一道模拟试题的解法"}
    )
    assert excluded.status_code == 200
    assert excluded.json()["spec"]["id"] == default["id"]
    assert excluded.json()["source"] == "default"

    manual = client.post(
        "/api/format-specs/match",
        json={"requirement": "生成一份模拟试卷", "manual_spec_id": default["id"]},
    )
    assert manual.status_code == 200
    assert manual.json()["source"] == "manual"
    assert manual.json()["spec"]["id"] == default["id"]


def test_snapshot_delivery_contract_and_check():
    snapshot = {
        "id": "spec",
        "snapshot_version": "v1",
        "deliverables": [
            {"name": "考向分析", "status": "on_request", "order": 1},
            {"name": "模拟试卷", "status": "required", "order": 2},
            {"name": "参考答案", "status": "forbidden", "order": 3},
        ],
    }
    contract = delivery_contract_for_snapshot(snapshot)
    assert contract is not None
    assert contract["items"] == ["考向分析", "模拟试卷"]
    assert contract["forbidden_deliverables"] == ["参考答案"]

    issues = check_snapshot_delivery(snapshot, {"outline": [{"title": "考向分析"}]})
    assert "必需交付物未出现在结构中：模拟试卷" in issues


def test_selected_spec_is_the_only_format_authority():
    snapshot = {
        "id": "spec",
        "name": "练习生成规范",
        "scene": "exercise",
        "snapshot_version": "v3",
        "deliverables": [
            {"name": "训练", "status": "required", "order": 1},
        ],
        "content_structure": "# 练习\n\n## 训练",
        "format_rules": "只使用当前模板。",
        "custom_markdown": "**当前模板专属规则**",
    }
    goal = SimpleNamespace(
        title="Python 冲刺",
        motivation="期中考试",
        application_context="完成训练",
        current_level="有基础",
        time_budget="共 10 小时",
        user_notes=(
            "覆盖基础语法与容器。\n"
            "用户已采纳 AI 建议，请按此约束生成：旧模板曾经要求先输出总览。"
        ),
        hard_constraints="1.练习题型只包括代码补全\n2.不要易错辨析，要知识概要\n3.第一章只输出两套试卷",
        capability_level="L2",
        generation_tier="standard",
        format_spec_snapshot=json.dumps(snapshot, ensure_ascii=False),
        generate_extra_exercises=False,
        domain_key="cs_it",
    )

    system, outline_user = prompts.outline(goal, get_profile("cs_it"), [])
    assert "唯一模板来源" in system
    assert "长期教学宪章" not in outline_user
    assert "不要易错辨析" not in outline_user
    assert "第一章只输出" not in outline_user
    assert "练习题型只包括代码补全" in outline_user
    assert "覆盖基础语法与容器" in outline_user
    assert "旧模板曾经要求先输出总览" not in outline_user
    assert "**当前模板专属规则**" in outline_user

    _, section_user = prompts.section(
        goal,
        get_profile("cs_it"),
        {"title": "训练", "_deliverable": "训练"},
        [],
        [],
    )
    assert "当前唯一交付物：训练" in section_user
    assert "不得套用旧教程模板" in section_user
    assert "分层讲解原则" not in section_user
    structural_only = prompts._teaching_charter(
        "section",
        {"rules": [{"text": "旧模板要求固定栏目", "hard": True, "rule_type": "required", "scopes": ["general"]}]},
        goal,
    )
    assert structural_only == ""

    profile_block = prompts._teaching_charter(
        "section",
        {
            "rules": [
                {
                    "text": "遇到实践性强的项目时，希望有更多操作实例",
                    "hard": False,
                    "rule_type": "conditional",
                    "scopes": ["example"],
                },
                {
                    "text": "生成试卷时四个选项分行输出，并保留旧版目录栏目",
                    "hard": True,
                    "rule_type": "conditional",
                    "scopes": ["format"],
                },
            ]
        },
        goal,
    )
    assert "长期用户画像" in profile_block
    assert "希望有更多操作实例" in profile_block
    assert "四个选项分行" not in profile_block
    assert "旧版目录栏目" not in profile_block
    assert "当前格式规范 > 本次任务明确内容 > 长期画像教学偏好" in profile_block


def test_format_spec_renderer_removes_tutorial_wrappers_and_duplicate_titles():
    goal = SimpleNamespace(title="Python 冲刺")
    sections = [
        {
            "title": "训练",
            "content": [
                {
                    "type": "text",
                    "title": "讲解",
                    "body": "# Python 冲刺\n\n## 第一部分\n\n完成题目。",
                }
            ],
            "key_takeaways": ["旧模板结论"],
            "exercises": ["旧模板练习"],
        }
    ]
    lines: list[str] = []
    _render_format_spec_document({}, goal, sections, lines)
    text = "\n".join(lines)

    assert text.count("# Python 冲刺") == 1
    # 无模板标题时渲染层统一补中文序号（全篇同式）
    assert "## 一、训练" in text
    assert "### 第一部分" in text
    assert "## 第 1 节" not in text
    assert "### 讲解" not in text
    assert "旧模板结论" not in text
    assert "旧模板练习" not in text


def test_manual_spec_replaces_legacy_hard_constraint_structure(client: TestClient):
    created = client.post(
        "/api/format-specs",
        json=_payload(
            name="当前练习模板",
            scene="exercise",
            trigger_keywords=[],
            deliverables=[
                {"name": "训练", "status": "required", "order": 1, "allow_override": True},
            ],
            content_structure="# 练习名称\n\n## 训练",
        ),
    )
    assert created.status_code == 200
    spec_id = created.json()["id"]

    response = client.post(
        "/api/goals/quickstart",
        json={
            "title": "模板冲突验证",
            "requirement": "完成练习",
            "hard_constraints": "第一章只输出两套试卷\n不要易错辨析，要知识概要",
            "format_spec_id": spec_id,
        },
    )
    assert response.status_code == 200
    body = response.json()
    content = body["tutorial"]["current_version"]["content"]
    assert [item["title"] for item in content["outline"]] == ["训练"]
    assert content["delivery_contract"]["items"] == ["训练"]
    assert body["tutorial"]["title"] == "模板冲突验证 · 当前练习模板"


def test_foreign_chapter_blocks_are_pruned_and_titles_aligned():
    content = {
        "format_spec": {"name": "试卷生成规范", "scene": "exam_paper", "deliverables": []},
        "outline": [
            {"title": "第一章　基础对标卷（一套）"},
            {"title": "第二章　高难进阶卷（两套）"},
            {"title": "第三章　试卷答案与难题简析"},
        ],
        "sections": [
            {
                "title": "线性代数期中冲刺（内容参考）",
                "content": [
                    {"type": "text", "title": "第一章　基础对标卷（一套）", "body": "第一章正文"},
                    {"type": "text", "title": "第二章　高难进阶卷（两套）", "body": "第二章正文"},
                    {"type": "text", "title": "## 第三章　试卷答案与难题简析", "body": "第三章正文"},
                    {"type": "text", "title": "第三章 答案与难题简析", "body": "编号启发式应剔除"},
                    {
                        "type": "text",
                        "title": "第一章　基础对标卷（一套）· 填空题答案",
                        "body": "派生块应保留",
                    },
                ],
            },
            {"title": "第二章　高难进阶卷（两套）", "content": [{"type": "text", "title": "第一套", "body": "x"}]},
            {"title": "第三章　试卷答案与难题简析", "content": [{"type": "text", "title": "对照方式", "body": "y"}]},
        ],
    }
    fixed = align_section_titles(prune_foreign_section_blocks(content))
    first = fixed["sections"][0]
    titles = [b.get("title") for b in first["content"]]
    assert first["title"] == "第一章　基础对标卷（一套）"
    assert titles == ["第一章　基础对标卷（一套）", "第一章　基础对标卷（一套）· 填空题答案"]
    # 答案章节保留跨章答案块
    answer_titles = [b.get("title") for b in fixed["sections"][2]["content"]]
    assert answer_titles == ["对照方式"]


def test_export_uses_spec_renderer_for_authoritative_spec(client: TestClient):
    import json as _json

    from app.db import SessionLocal
    from app.models import Tutorial, TutorialVersion
    from app.services.tutorials import export_markdown

    created = client.post(
        "/api/goals",
        json={"title": "导出渲染验证", "hard_constraints": "第一章只输出一套试卷"},
    )
    goal_id = created.json()["id"]
    db = SessionLocal()
    try:
        tutorial = Tutorial(goal_id=goal_id, title="导出渲染验证 · 试卷生成规范", status="drafted")
        db.add(tutorial)
        db.flush()
        content = {
            "format_spec": {"name": "试卷生成规范", "scene": "exam_paper", "deliverables": []},
            "delivery_contract": {"source": "format_spec", "items": ["第一章　基础对标卷（一套）"]},
            "outline": [
                {"title": "第一章　基础对标卷（一套）", "criteria_ids": []},
                {"title": "第二章　高难进阶卷（两套）", "criteria_ids": []},
            ],
            "sections": [
                {
                    "title": "导出渲染验证",
                    "content": [
                        {"type": "text", "title": "第一章　基础对标卷（一套）", "body": "卷面正文"},
                        {"type": "text", "title": "第二章　高难进阶卷（两套）", "body": "不该出现"},
                    ],
                    "key_takeaways": ["旧栏目"],
                }
            ],
        }
        version = TutorialVersion(
            tutorial_id=tutorial.id,
            version=1,
            content_json=_json.dumps(content, ensure_ascii=False),
            prompt_version="v1",
            model_provider="demo",
            model_name="demo",
            quality_report="{}",
            source_refs="[]",
        )
        db.add(version)
        db.flush()
        tutorial.current_version_id = version.id
        db.commit()
        name, md = export_markdown(db, tutorial.id)
    finally:
        db.close()

    assert "## 第 1 节" not in md
    assert "### 核心结论" not in md
    # 模板未给该章标题时渲染层统一补中文序号：全篇「## 一、…」同式
    assert "## 一、第一章　基础对标卷（一套）" in md
    assert "不该出现" not in md
    assert "卷面正文" in md


def test_quickstart_exam_spec_binds_snapshot_and_contract_before_outline(client: TestClient):
    """快照与交付契约必须在大纲前冻结；「只输出 X / 不要答案」要落成结构级约束。

    夹具用自建试卷规范（带交付物清单）而不是内置 exam_paper：内置规范现在
    刻意不带交付物清单（见 test_builtin_exam_spec_has_no_deliverables），
    「只输出 X」这类机制改由带清单的自定义规范承载，所以在这里单独造一个。
    """
    spec = client.post(
        "/api/format-specs",
        json=_payload(
            name="分栏试卷规范",
            scene="exam_columns",
            trigger_keywords=["模拟试卷"],
            deliverables=[
                {"name": "考向分析", "status": "on_request", "order": 1, "allow_override": True},
                {"name": "模拟试卷", "status": "required", "order": 2, "allow_override": True},
                {"name": "参考答案", "status": "required", "order": 3, "allow_override": True},
                {"name": "难题解析", "status": "required", "order": 4, "allow_override": True},
            ],
        ),
    )
    assert spec.status_code == 200, spec.text

    requirement = (
        "使用分栏试卷规范，只输出考向分析和模拟试卷。不要答案，不要解析，"
        "不要学习教程或泛泛的复习建议。"
    )
    response = client.post("/api/goals/quickstart", json={
        "title": "线性代数模拟试卷",
        "requirement": requirement,
        "format_spec_id": spec.json()["id"],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["goal"]["format_spec_source"] == "manual"
    assert body["goal"]["format_spec_snapshot"]["scene"] == "exam_columns"

    content = body["tutorial"]["current_version"]["content"]
    assert content["delivery_contract"]["source"] == "format_spec"
    assert content["delivery_contract"]["forbid_answers"] is True
    titles = [item["title"] for item in content["outline"]]
    assert "考向分析" in titles
    assert "模拟试卷" in titles
    assert "参考答案" not in titles
    assert "难题解析" not in titles
    assert "参考答案" in content["delivery_contract"]["forbidden_deliverables"]
    assert "本次只生成：考向分析" in content["delivery_contract"]["task_overrides"]

    fetched = client.get(f"/api/goals/{body['goal']['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["format_spec_snapshot"]["snapshot_version"]


def test_builtin_exam_spec_has_no_deliverables():
    """内置试卷规范刻意不带交付物清单：分卷结构由 content_structure 承载。

    两条代码级理由（都是实测故障，不是排版偏好）：
    1) apply_task_overrides 按「交付物名是否出现在任务文本里」判定本次只生成什么，
       而卷名/标题很容易撞上栏目名。实测 goal「普通化学训练」+「只生成前两章的练习题」
       命中交付物「训练」→「易错辨析」被强制 forbidden → 导出只剩一章。
       试卷的节名是「线性代数期中模拟试卷」「第 N 章 … 单元检测卷」这类自由文本，
       撞上「参考答案」「模拟试卷」的概率更高。
    2) check_snapshot_delivery 要求 required 交付物名逐字出现在章节标题里；
       按材料分章时标题被 apply_chapter_split 重写成「第 N 章 … 单元检测卷」，
       任何写死的 required 名都对不上 → quality.passed=False → 教程降级。
    """
    from app.services import format_specs as fs

    exam = next(item for item in fs._BUILTINS if item["scene"] == "exam_paper")
    assert exam["deliverables"] == []

    # 无交付物 → 不生成契约（章节结构交回大纲模型按「分卷规则」决定），
    # 但规范仍然接管导出模板（authoritative 判据看的是 name/scene，不是交付物）
    snapshot = {"name": exam["name"], "scene": "exam_paper", "deliverables": []}
    assert fs.delivery_contract_for_snapshot(snapshot) is None
    assert fs.authoritative_spec_dict(snapshot) == snapshot
    assert fs.check_snapshot_delivery(snapshot, {"outline": [{"title": "任意卷名"}]}) == []

    # 分卷规则必须由 content_structure 表达，且卷内结构与练习规范同款（答案不单独成节）
    structure = exam["content_structure"]
    assert "分卷规则" in structure and "一节 = 一整份卷" in structure
    assert "### 参考答案" in structure
    assert "| 题型 | 题号 | 题量 | 每题分值 | 小计 |" in structure
    # 标题层级：正文最浅 ###，不得出现 ## 级模板（章标题由系统输出）
    assert not re.search(r"(?m)^##\s", structure)


def test_exam_noun_regex_stays_in_sync_with_unit_noun_regex():
    """回归：卷面自检的触发词表必须覆盖按章拆分会生成的全部卷名。

    prompts.py 曾在本地另写一份「试卷|练习卷|训练卷|测验|检测卷」，漏了
    「模拟卷」「自测卷」，而这两个词正是 format_specs._UNIT_NOUN_RE 认可、
    并会被写进交付物名（节标题）的合法卷名。词表不一致 → 卷面自检静默丢失 →
    题号按题型重置、声明题量与实际不符无人拦（真实故障：32 个题号仅 18 唯一）。
    """
    from app.llm.prompts import _EXAM_NOUN_RE
    from app.services.format_specs import _UNIT_NOUN_RE

    for noun in ("单元检测卷", "单元测验卷", "单元试卷", "检测卷", "测验卷",
                 "测试卷", "自测卷", "模拟卷", "练习卷", "试卷"):
        assert _UNIT_NOUN_RE.search(noun), f"_UNIT_NOUN_RE 应命中 {noun}"
        assert _EXAM_NOUN_RE.search(noun), f"卷面自检词表漏了 {noun}"

    # 真实节标题形态：章名 + 卷名
    assert _EXAM_NOUN_RE.search("第 1 章 线性方程组 单元检测卷")
    assert _EXAM_NOUN_RE.search("线性代数期中模拟试卷")
    assert _EXAM_NOUN_RE.search("线性代数模拟卷")
    # 非试卷交付物不该被塞进卷面自检
    for name in ("考向分析", "参考答案", "易错辨析", "训练", "掌握 codex 用法", "线性代数笔记"):
        assert not _EXAM_NOUN_RE.search(name), f"{name} 不该触发卷面自检"


def test_exam_type_names_come_from_material_not_a_fixed_enum():
    """回归：试卷题型不固定，来源由「有无例题来源材料」决定，行为按客观/主观二分。

    用户要求：题型根据上传资料（例题来源）确定；没有资料时默认覆盖全部题型。
    旧的封闭枚举（「名称只能取：选择题 / 判断题 / …」）会让材料里的「计算题」
    「名词解释」「简答题」判为违规，或逼模型改写成同义词 —— 与材料脱节。
    但枚举当初要防的是「同一份文档各节各写各的」（v5 真实故障：计算题 /
    计算分析题 / 计算与证明题 / 诊断题 / 变式题 七章一式），所以一致性判据
    不能丢，只是从「取自固定清单」换成「取自材料、全文档同一套」。

    同时：题型名一旦动态化，依赖题型名字面的答案详略与题后留白规则会全部落空，
    必须改为按「客观题/主观题」的作答形态归类，材料写什么名都能落进确定分支。
    """
    from app.services import format_specs as fs

    exam = next(item for item in fs._BUILTINS if item["scene"] == "exam_paper")
    rules = exam["format_rules"] + exam["required_rules"] + exam["acceptance_criteria"]

    # ① 封闭枚举已废除：不得再要求「只能取」固定清单
    assert "名称只能取" not in rules, "封闭枚举仍在，材料里的题型名会被判违规"

    # ② 三档题型来源规则齐全，且顺序明确（有材料 → 材料无划分 → 无材料）
    for fragment in ("题型来源规则", "例题来源", "没有注入任何材料"):
        assert fragment in rules, f"缺题型来源规则片段：{fragment}"
    # 逐字沿用，不许改写成同义词（这是「与例题来源一致」的可执行表述）
    assert "不改写成同义词" in rules
    # 默认档必须覆盖全部题型
    assert "默认覆盖全部题型" in rules

    # ③ 一致性判据仍在：全文档同一套题型名，且与分值分布表一致
    assert "全文档同一套" in rules
    assert "同一套题型名" in exam["required_rules"]

    # ④ 答案详略与留白改为按客观/主观，不再依赖题型名字面
    for fragment in ("客观题", "主观题"):
        assert fragment in rules, f"缺客观/主观归类：{fragment}"
    assert "选择题、判断题、填空题 → 只给答案" not in exam["required_rules"], \
        "答案详略仍按固定题型名映射，材料题型会落空"
    assert "解答题、证明题、综合题 → 给答案" not in exam["required_rules"]
    # 无法归类时有确定兜底，不留自由裁量
    assert "无法确定时按主观题处理" in rules

    # ⑤ custom_markdown 里留白规则同步改口径，且不得再有重复块
    cm = exam["custom_markdown"]
    assert "题后留白规则" in cm
    assert cm.count("**判断题排版规则**") == 1, "判断题排版规则重复注入"
    assert cm.count("题后留白规则") == 1, "留白规则重复注入"

    # ⑥ 模板与正反例都给了「按材料题型」的形态，模型不只见过默认六题型
    assert "名词解释" in exam["content_structure"]
    assert "名词解释" in exam["reference_examples"]


def test_exam_section_prompt_carries_paper_surface_rules():
    """试卷节提示词必须同时带上：规范的卷内四段结构 + 代码侧卷面自检。

    两者来源不同（规范字段 vs prompts._exam_self_check），缺一都会导致真实故障：
    缺规范 → 自拟「第 I 部分」「参考答案与评分说明」「概念标注」；
    缺自检 → 题号按题型重置、声明 20 题实际 25 题。
    """
    from app.services import format_specs as fs

    exam = next(item for item in fs._BUILTINS if item["scene"] == "exam_paper")
    snapshot = {**exam, "snapshot_version": "v9", "chapter_split": False}
    goal = SimpleNamespace(
        title="线性代数期中模拟试卷",
        motivation="", application_context="", current_level="",
        time_budget="", user_notes="", hard_constraints="出两套卷，要求知识点全覆盖",
        capability_level="L3", generation_tier="standard",
        format_spec_snapshot=json.dumps(snapshot, ensure_ascii=False),
    )
    _, user = prompts.section(
        goal, get_profile("math_logic"),
        {"title": "线性代数期中模拟试卷", "_deliverable": "线性代数期中模拟试卷"}, [], [],
    )
    # 规范侧：卷内四段结构、题型来源规则、禁止项、正反例
    for fragment in (
        "一节 = 一整份卷",
        "| 题型 | 题号 | 题量 | 每题分值 | 小计 |",
        "题型来源规则",
        "禁止「第 I 部分」「Part 1」一类前缀",
        "禁止自拟答案小节名",
        "概念标注",
        "参考答案单独成节",
        "客观题/主观题",
        "每题不超过 6 行",
        "禁止使用 \\(…\\)",
    ):
        assert fragment in user, f"section 提示词缺规范片段：{fragment}"
    # 代码侧：卷面自检
    assert "卷面自检" in user
    assert "题号在全卷内连续递增" in user
    # 硬性约束里的内容要求按小句保留（结构字样被剔除，内容要求不丢）
    assert "知识点全覆盖" in user


def test_exam_export_keeps_type_headings_at_level3():
    """导出层级取决于 content 块的 title：块名 == 卷名时题型小节才是 ###。

    _render_deliverable_blocks 只有在块标题与节标题同名（忽略序号）时才不单独输出
    块标题；一旦模型自拟块名（「试卷」「卷面说明」「试卷正文与参考答案」），
    渲染器就多输出一层「### 块名」并把整段正文平移到 #### 起步 ——
    v5 导出里满篇「### 试卷 + #### 选择题」就是这么来的。
    规范因此要求「本节只输出一个正文块，块 title 逐字等于卷名」。
    """
    from types import SimpleNamespace

    from app.services import format_specs as fs

    exam = next(item for item in fs._BUILTINS if item["scene"] == "exam_paper")
    body = (
        "> 本卷满分 100 分，共 10 题。\n\n"
        "| 题型 | 题号 | 题量 | 每题分值 | 小计 |\n|---|---|---|---|---|\n"
        "| 选择题 | 1–6 | 6 | 5 | 30 |\n| 解答题 | 7–10 | 4 | 15 | 60 |\n"
        "| 合计 | 1–10 | 10 | — | 100 |\n\n"
        "### 选择题\n\n**1.**（5 分）题干（　　）\n\n### 解答题\n\n"
        "**7.**（15 分）题干\n\n### 参考答案\n\n**1.** A\n"
    )
    paper_title = "第 1 章 线性方程组 单元检测卷"

    def render(block_title: str) -> list[str]:
        content = {"format_spec": exam, "delivery_contract": None}
        sections = [{"title": paper_title,
                     "content": [{"type": "text", "title": block_title, "body": body}]}]
        lines: list[str] = []
        _render_format_spec_document(
            content, SimpleNamespace(title="线性代数单元检测卷"), sections, lines
        )
        # body 是作为单个元素 append 的（内部含换行），必须 join 后再按行切
        return [ln for ln in "\n".join(lines).splitlines() if ln.startswith("#")]

    good = render(paper_title)
    assert "## 一、第 1 章 线性方程组 单元检测卷" in good
    assert "### 选择题" in good and "### 解答题" in good and "### 参考答案" in good
    assert not any(h.startswith("####") for h in good), good
    # 章标题由系统补序号，正文不带 # / ##
    assert sum(1 for h in good if h.startswith("## ")) == 1

    for bad_title in ("试卷", "卷面说明", "试卷正文与参考答案"):
        bad = render(bad_title)
        assert f"### {bad_title}" in bad, bad
        assert "#### 选择题" in bad, bad  # 自拟块名 → 题型被压到 ####


def test_exam_builtin_seed_matches_saved_spec_fields(client: TestClient):
    """内置种子与已存规范字段同源：种子里的 LaTeX 反斜杠不能被 Python 转义吃掉。

    content_structure / reference_examples / custom_markdown 里写着 \\begin{cases}、
    \\(…\\) 这类字面文本。用普通三引号会让 \\b 变退格符、\\( 变无效转义，
    模板一旦损坏，模型照着抄就会产出无法渲染的公式。
    """
    from app.services import format_specs as fs

    exam_seed = next(item for item in fs._BUILTINS if item["scene"] == "exam_paper")
    fields = ("content_structure", "format_rules", "required_rules", "forbidden_rules",
              "reference_examples", "custom_markdown", "acceptance_criteria")
    for key in fields:
        text = exam_seed[key]
        assert "\x08" not in text and "" not in text, f"{key} 出现退格符：反斜杠被转义吃掉"

    assert "\\begin{cases}" in exam_seed["reference_examples"]
    assert "m\\times n" in exam_seed["reference_examples"]
    assert "\\(…\\)" in exam_seed["format_rules"]
    assert "$$…$$" in exam_seed["format_rules"]

    # 新库首启写入的规范与种子逐字一致（ensure_builtin_specs 不做二次加工）
    specs = client.get("/api/format-specs").json()
    saved = next(item for item in specs if item["scene"] == "exam_paper")
    for key in fields:
        assert saved[key] == exam_seed[key], f"{key} 落库后与种子不一致"
    assert saved["deliverables"] == []


def test_spec_renderer_uses_template_numbered_headings(client: TestClient):
    """导出必须逐字沿用规范模板标题（含中文序号），且模型自带的带序号重复标题被去重。"""
    import json as _json

    from app.db import SessionLocal
    from app.models import Tutorial, TutorialVersion
    from app.services.tutorials import export_markdown

    created = client.post("/api/goals", json={"title": "序号渲染验证"})
    goal_id = created.json()["id"]
    db = SessionLocal()
    try:
        tutorial = Tutorial(goal_id=goal_id, title="序号渲染验证 · 练习生成规范", status="drafted")
        db.add(tutorial)
        db.flush()
        content = {
            "format_spec": {
                "name": "练习生成规范",
                "scene": "exercise",
                "deliverables": [
                    {"name": "易错辨析", "status": "required", "order": 1},
                    {"name": "训练", "status": "required", "order": 2},
                ],
                "content_structure": (
                    "# 练习名称\n\n> 考察知识点简述。\n\n"
                    "## 一、易错辨析\n[ ]**1.** 题干\n\n## 二、训练\n**1.** 题干\n"
                ),
            },
            "delivery_contract": {"source": "format_spec", "items": ["易错辨析", "训练"]},
            "outline": [
                {"title": "易错辨析", "criteria_ids": []},
                {"title": "训练", "criteria_ids": []},
            ],
            "sections": [
                {"title": "易错辨析", "content": [{"type": "text", "title": "", "body": "辨析正文"}]},
                {
                    "title": "训练",
                    "content": [{"type": "text", "title": "训练", "body": "### 二、训练\n\n**1.** 题干"}],
                },
            ],
        }
        version = TutorialVersion(
            tutorial_id=tutorial.id,
            version=1,
            content_json=_json.dumps(content, ensure_ascii=False),
            prompt_version="v1",
            model_provider="demo",
            model_name="demo",
            quality_report="{}",
            source_refs="[]",
        )
        db.add(version)
        db.flush()
        tutorial.current_version_id = version.id
        db.commit()
        _name, md = export_markdown(db, tutorial.id)
    finally:
        db.close()

    assert "## 一、易错辨析" in md
    assert "## 二、训练" in md
    assert "### 二、训练" not in md  # 模型自带的重复序号标题被去重
    assert md.count("## 二、训练") == 1

def test_chapter_split_needs_a_deliverable_noun_not_just_per_chapter():
    """回归：按章拆分必须同时命中「按章」表述与「每章一份什么成品」的名词。

    只看「每/各/逐 + 章」会误伤练习类任务。用户真实写过的硬性约束是
    「训练部分参照参考资料，根据每个习题输出两个变式题，在每一章最后输出十个综合题」——
    这里的「每一章」只是描述题目分布，不是要求把交付物按章拆开。
    旧实现靠 variant_mode 充当挡板；变式汇编模式退役后，挡板必须换成名词判据，
    否则练习规范的「易错辨析/训练」两章会被静默替换成材料里的 7 个章节名。
    """
    from app.services import format_specs as fs

    materials = (
        "# 习题集\n## 第 1 章 线性方程组\n### 习题 1.5 小结\n1. 题\n"
        "## 第 2 章 集合与映射\n### 习题 2.1 集合\n1. 题\n"
    )
    practice = {
        "name": "练习生成规范",
        "scene": "exercise",
        "deliverables": [
            {"name": "易错辨析", "status": "required", "order": 1},
            {"name": "训练", "status": "required", "order": 2},
        ],
    }
    # 练习任务：含「每一章」但无成品名词 -> 不拆分，交付物原样保留
    exercise_requirement = (
        "训练部分参照参考资料，根据每个习题输出两个变式题，在每一章最后输出十个综合题"
    )
    assert fs.chapter_split_mode(dict(practice), exercise_requirement) is False
    snap = fs.apply_chapter_split(dict(practice), exercise_requirement, materials)
    assert snap["chapter_split"] is False
    assert [d["name"] for d in snap["deliverables"]] == ["易错辨析", "训练"]

    # 试卷任务：既有「每一个章节」又有「单元检测卷」-> 按材料章节拆分
    paper_requirement = "为每一个章节生成一份单元检测卷"
    paper = {"name": "试卷生成规范", "scene": "exam_paper", "deliverables": []}
    assert fs.chapter_split_mode(dict(paper), paper_requirement) is True
    snap = fs.apply_chapter_split(dict(paper), paper_requirement, materials)
    assert [d["name"] for d in snap["deliverables"]] == [
        "第 1 章 线性方程组 单元检测卷",
        "第 2 章 集合与映射 单元检测卷",
    ]

    # 快照已冻结 chapter_split：后续调用不再依赖任务文本
    assert fs.chapter_split_mode(snap, "") is True
    assert fs.chapter_split_mode({"name": "练习生成规范", "chapter_split": False}, "每一章") is False


def test_chapter_split_uses_material_chapters_and_hard_constraints():
    """「为每一个章节生成一份 X」必须由代码按材料分章定死交付物，不靠模型自觉。

    硬性约束是这句话最常见的落点，所以任务文本必须把 hard_constraints 拼进来；
    章节名逐字取自材料标题，序号前缀（「## 一、第 1 章 …」）要能识别。
    """
    from app.learning.teaching_profile import task_requirement_text
    from app.services import format_specs as fs

    goal = SimpleNamespace(
        title="线性代数单元检测卷",
        motivation="基础不够扎实",
        application_context="明确易错点",
        current_level="掌握知识点",
        time_budget="无上限",
        user_notes="",
        hard_constraints="根据参考材料的分章，为每一个章节生成单元检测卷，题量不限，要求知识点全覆盖",
    )
    requirement = task_requirement_text(goal)
    assert "为每一个章节生成单元检测卷" in requirement  # 硬性约束进入任务文本

    materials = (
        "# 习题汇编\n"
        "## 目录\n\n"
        "## 第 1 章 线性方程组\n### 习题 1.5 小结\n"
        "## 第 2 章 集合与映射\n"
    )
    base = {"name": "试卷生成规范", "scene": "exam_paper", "deliverables": []}
    assert fs.chapter_split_mode(dict(base), requirement) is True
    assert fs.material_chapters(materials) == ["第 1 章 线性方程组", "第 2 章 集合与映射"]

    snap = fs.apply_chapter_split(dict(base), requirement, materials)
    assert snap["chapter_split"] is True
    assert [item["name"] for item in snap["deliverables"]] == [
        "第 1 章 线性方程组 单元检测卷",
        "第 2 章 集合与映射 单元检测卷",
    ]
    contract = fs.delivery_contract_for_snapshot(snap)
    assert contract["items"] == [
        "第 1 章 线性方程组 单元检测卷",
        "第 2 章 集合与映射 单元检测卷",
    ]


def test_chapter_split_skips_default_tutorial():
    """默认教程规范的结构由大纲模型按知识复杂度决定：不叠加按章拆分。"""
    from app.services import format_specs as fs

    requirement = "为每一个章节生成一份单元检测卷"
    materials = "## 第 1 章 线性方程组\n## 第 2 章 集合与映射\n"

    default = fs.apply_chapter_split(
        {"name": "默认教程规范", "scene": "default_tutorial", "deliverables": []},
        requirement,
        materials,
    )
    assert default["chapter_split"] is False
    assert default["deliverables"] == []


def test_deliverable_body_heading_levels_are_normalized_per_block():
    """题型标题深度归一：模型各章起笔层级不同时，导出后都从 ### 起步并保留相对层次。"""
    from app.services.tutorials import _normalize_deliverable_body

    # 本章用 #### 起笔（模型写成深了一级）
    deep = _normalize_deliverable_body("#### 选择题\n\n**1.** 题干\n\n##### 小题\n\n内容")
    assert deep.startswith("### 选择题"), deep
    assert "#### 小题" in deep, deep  # 相对层次保留：小题比题型深一级

    # 本章用 ## 起笔（模型写成浅了一级，且与交付物标题同层）
    shallow = _normalize_deliverable_body("## 判断题\n\n1. 题干\n\n## 综合题\n\n内容")
    assert shallow.startswith("### 判断题"), shallow
    assert "### 综合题" in shallow, shallow

    # 代码块内的 # 不是标题，不参与层级计算
    fenced = _normalize_deliverable_body("# 标题\n\n```\n# 注释行\n```\n\n### 选择题\n\n题干")
    assert "# 标题" not in fenced.splitlines()[0], fenced  # 文档级 H1 被去掉
    assert "### 选择题" in fenced
    assert "# 注释行" in fenced


def test_chapter_split_paper_requires_self_contained_answers():
    """按章交付时每章自成一卷：卷末必须自带参考答案；单列答案的规范则不叠加该要求。

    实测 7 章里 6 章自带答案、1 章不带，同一份文档形态不一致。要求只在
    chapter_split 快照下注入，避免与「参考答案」作为独立交付物的规范冲突。
    """
    from app.learning.disciplines import get_profile

    def _goal(chapter_split: bool):
        snapshot = {
            "name": "试卷生成规范",
            "scene": "exam_paper",
            "chapter_split": chapter_split,
            "deliverables": [{"name": "第 4 章 行列式 单元检测卷", "status": "required", "order": 1}],
            "content_structure": "# 试卷名称",
        }
        return SimpleNamespace(
            title="线性代数单元检测卷",
            motivation="基础不够扎实",
            application_context="明确易错点",
            current_level="掌握知识点",
            time_budget="无上限",
            user_notes="",
            hard_constraints="为每一个章节生成单元检测卷",
            capability_level="L3",
            generation_tier="standard",
            format_spec_snapshot=json.dumps(snapshot, ensure_ascii=False),
        )

    _, split_user = prompts.section(
        _goal(True), get_profile("math_logic"),
        {"title": "第 4 章 行列式 单元检测卷", "_deliverable": "第 4 章 行列式 单元检测卷"}, [], [],
    )
    assert "自成一卷" in split_user
    assert "卷末必须附「参考答案」" in split_user
    assert "数学表达式一律使用 LaTeX" in split_user

    _, plain_user = prompts.section(
        _goal(False), get_profile("math_logic"),
        {"title": "第 4 章 行列式 单元检测卷", "_deliverable": "第 4 章 行列式 单元检测卷"}, [], [],
    )
    assert "自成一卷" not in plain_user  # 单列答案交付物的规范不叠加


def test_exam_deliverable_prompt_carries_numbering_self_check():
    """试卷类交付物必须带上卷面自检：题号全卷连续、声明题量与实际一致。

    规范模式的章节提示词不经过 _deliverable_task，所以自检要求要在两条路径都注入；
    否则模型会声明「共 20 题」却写出 25 题、并让每个题型都从 1 重新编号。
    """
    from app.learning.disciplines import get_profile

    snapshot = {
        "name": "试卷生成规范",
        "scene": "exam_paper",
        "chapter_split": True,
        "deliverables": [{"name": "第 3 章 矩阵 单元检测卷", "status": "required", "order": 1}],
        "content_structure": "# 试卷名称",
    }
    goal = SimpleNamespace(
        title="线性代数单元检测卷",
        motivation="基础不够扎实",
        application_context="明确易错点",
        current_level="掌握知识点",
        time_budget="无上限",
        user_notes="",
        hard_constraints="为每一个章节生成单元检测卷",
        capability_level="L3",
        generation_tier="standard",
        format_spec_snapshot=json.dumps(snapshot, ensure_ascii=False),
    )
    _, user = prompts.section(
        goal,
        get_profile("math_logic"),
        {"title": "第 3 章 矩阵 单元检测卷", "_deliverable": "第 3 章 矩阵 单元检测卷"},
        [],
        [],
    )
    assert "卷面自检" in user
    assert "题号在全卷内连续递增" in user
    assert "声明 20 题、实际 25 题" in user
    # 非试卷交付物不该被塞进试卷自检
    snapshot["deliverables"] = [{"name": "考向分析", "status": "required", "order": 1}]
    goal.format_spec_snapshot = json.dumps(snapshot, ensure_ascii=False)
    _, user2 = prompts.section(
        goal, get_profile("math_logic"),
        {"title": "考向分析", "_deliverable": "考向分析"}, [], [],
    )
    assert "卷面自检" not in user2


def test_chapter_split_scope_and_content_clauses_reach_section_prompt():
    """按章交付时，章节范围与硬性约束里的内容要求都要进入章节提示词。"""
    from app.learning.disciplines import get_profile

    hard = "根据参考材料的分章，为每一个章节生成单元检测卷，题量不限，要求知识点全覆盖，难度对照例题来源明显拔高"
    snapshot = {
        "name": "试卷生成规范",
        "scene": "exam_paper",
        "chapter_split": True,
        "deliverables": [
            {"name": "第 3 章 矩阵 单元检测卷", "status": "required", "order": 1},
        ],
    }
    goal = SimpleNamespace(
        title="线性代数单元检测卷",
        motivation="基础不够扎实",
        application_context="明确易错点",
        current_level="掌握知识点",
        time_budget="无上限",
        user_notes="",
        hard_constraints=hard,
        capability_level="L3",
        generation_tier="standard",
        format_spec_snapshot=json.dumps(snapshot, ensure_ascii=False),
    )
    _, user = prompts.section(
        goal,
        get_profile("math_logic"),
        {"title": "第 3 章 矩阵 单元检测卷", "_deliverable": "第 3 章 矩阵 单元检测卷"},
        [],
        [],
    )
    # 范围只到章名，不把「单元检测卷」当成知识点
    assert "本次范围：只覆盖「第 3 章 矩阵」这一章" in user
    assert "只覆盖「第 3 章 矩阵 单元检测卷」" not in user
    # 结构字样所在行的内容要求按小句保留，不再整行丢弃
    for clause in ("题量不限", "要求知识点全覆盖", "难度对照例题来源明显拔高"):
        assert clause in user


def test_prompt_injects_spec_fields_without_mode_filtering():
    """规范字段原样注入：不再按「模式」裁剪，也不让 reference_examples 顶替结构模板。

    旧实现有两套隐患，都由变式汇编模式退役后暴露出来：
    1) _filter_mode_blocks 按【模式】标记裁剪规则块，一旦判定走偏就整块规则消失
       （实测 variant=True 时 required_rules 从 165 字被砍到 74 字）；
    2) variant 模式下 reference_examples 会顶替 content_structure，
       等于结构模板有两个来源，而 reference_examples 恰恰是教模型「综合题重置为 1」的元凶。
    现在 content_structure 是结构的唯一来源，reference_examples 只作排版对照示例。
    """
    from types import SimpleNamespace

    from app.llm import prompts

    spec = {
        "name": "练习生成规范",
        "scene": "exercise",
        "content_structure": "# 练习名称\n\n## 一、训练",
        "reference_examples": "✅ 正确：题号全章连续\n❌ 错误：综合题重置为 1",
        "format_rules": "- 题号在整章内连续编号\n- 行内公式一律用 $…$",
        "required_rules": "- 每章末尾必须有且仅有一个「### 参考答案」小节",
        "forbidden_rules": "- 禁止题目后立即附该题答案",
        "acceptance_criteria": "- 章内题号连续且无重复",
        "custom_markdown": "**判断题排版规则**\n1. 题号加粗。",
    }
    goal = SimpleNamespace(format_spec_snapshot=json.dumps(spec, ensure_ascii=False))
    block = prompts._format_spec_block("section", goal, "训练")

    # 结构模板与正反例各自独立出现，互不顶替
    assert "# 练习名称" in block and "## 一、训练" in block
    assert "题号全章连续" in block and "综合题重置为 1" in block
    # 全部规则字段完整注入，无一被裁剪
    for fragment in (
        "题号在整章内连续编号",
        "行内公式一律用",
        "必须有且仅有一个",
        "禁止题目后立即附该题答案",
        "章内题号连续且无重复",
        "题号加粗",
    ):
        assert fragment in block, f"规则片段被裁剪：{fragment}"


def test_chapter_split_sees_hard_constraints_in_task_text():
    """回归：按章拆分的判定必须能看到硬性约束里的要求。

    任务文本只拼 application_context + user_notes 时，写在硬性约束里的
    「为每一个章节生成单元检测卷」永远触发不了按章拆分，交付物永远是一整份。
    （变式汇编模式已退役；hard_constraints 必须进入任务文本这一点由按章拆分继承。）
    """
    from app.learning.teaching_profile import task_requirement_text
    from app.services import format_specs as fs

    context = {
        "title": "期末复习",
        "motivation": "",
        "application_context": "期末复习",
        "current_level": "",
        "time_budget": "",
        "user_notes": "",
    }
    hard = SimpleNamespace(
        **context, hard_constraints="为每一个章节生成单元检测卷"
    )
    assert fs.chapter_split_mode(
        {"name": "试卷生成规范"}, task_requirement_text(hard)
    ) is True

    bare = SimpleNamespace(**context, hard_constraints="")
    assert fs.chapter_split_mode(
        {"name": "试卷生成规范"}, task_requirement_text(bare)
    ) is False

    # 练习类任务即使含「每一章」，缺成品名词也不拆分
    exercise = SimpleNamespace(
        **context, hard_constraints="在每一章最后输出十个综合题"
    )
    assert fs.chapter_split_mode(
        {"name": "练习生成规范"}, task_requirement_text(exercise)
    ) is False


def test_quickstart_chapter_split_reads_hard_constraints(client: TestClient):
    """回归（AI 检查项）：生成流程的模式判定必须读 hard_constraints。

    复现路径：按章交付要求只写在硬性约束里，需求正文与应用场景不含任何按章字样。
    若 pipeline 只拼 application_context + user_notes，chapter_split
    恒为 False，交付物永远不会按材料章节拆分。
    """
    spec = client.post(
        "/api/format-specs",
        json=_payload(
            name="分章检测卷规范",
            scene="unit_paper",
            trigger_keywords=["单元检测卷"],
            deliverables=[
                {"name": "单元检测卷", "status": "required", "order": 1, "allow_override": True}
            ],
            content_structure="# 检测卷\n\n## 题目",
        ),
    )
    assert spec.status_code == 200, spec.text

    goal = client.post(
        "/api/goals",
        json={
            "title": "线性代数期末复习",
            "domain_key": "math_data",
            "application_context": "期末复习",
            # 按章交付要求的唯一落点：硬性约束（正文/应用场景均无按章字样）
            "hard_constraints": "根据参考材料的分章，为每一个章节生成单元检测卷",
        },
    )
    assert goal.status_code == 200, goal.text
    goal_id = goal.json()["id"]

    material = client.post(
        f"/api/goals/{goal_id}/materials",
        files={
            "file": (
                "目录.md",
                "# 线性代数\n\n## 第 1 章 线性方程组\n\n## 第 2 章 集合与映射\n".encode("utf-8"),
                "text/markdown",
            )
        },
        data={"kind": "reference"},
    )
    assert material.status_code == 200, material.text

    response = client.post(f"/api/goals/{goal_id}/tutorials/quickstart")
    assert response.status_code == 200, response.text
    body = response.json()

    fetched = client.get(f"/api/goals/{goal_id}")
    assert fetched.status_code == 200
    snapshot = fetched.json()["format_spec_snapshot"]
    assert snapshot["chapter_split"] is True
    assert [item["name"] for item in snapshot["deliverables"]] == [
        "第 1 章 线性方程组 单元检测卷",
        "第 2 章 集合与映射 单元检测卷",
    ]

    content = body["tutorial"]["current_version"]["content"]
    assert [item["title"] for item in content["outline"]] == [
        "第 1 章 线性方程组 单元检测卷",
        "第 2 章 集合与映射 单元检测卷",
    ]
    assert content["delivery_contract"]["source"] == "format_spec"
    assert content["delivery_contract"]["items"] == [
        "第 1 章 线性方程组 单元检测卷",
        "第 2 章 集合与映射 单元检测卷",
    ]
READING_OUTLINE = [
    {"id": "a1", "title": "全书认知地图", "purpose": "p", "content_type": "application", "criteria_ids": []},
    {"id": "a2", "title": "第一章 导论", "purpose": "p", "content_type": "application", "criteria_ids": []},
    {"id": "a3", "title": "第二章 存在论", "purpose": "p", "content_type": "application", "criteria_ids": []},
    {"id": "a4", "title": "思想背景与理论延拓", "purpose": "p", "content_type": "application", "criteria_ids": []},
    {"id": "a5", "title": "总结与延伸阅读", "purpose": "p", "content_type": "application", "criteria_ids": []},
]


def _reading_spec(deliverables=None, scene="reading_guide") -> dict:
    return {
        "name": "阅读教程规范",
        "scene": scene,
        "snapshot_version": "v1",
        "deliverables": deliverables or [],
        "output_goal": "输出深度导读",
        "content_structure": "# 阅读教程",
        "format_rules": "- 正文最浅标题为 ###",
        "required_rules": "- 每章概要与深度导读同节完成",
        "acceptance_criteria": "- 原文忠实",
    }


_RECORDER_SEQ = {"n": 0}


def _run_sections_worker_with_recorder(monkeypatch, spec: dict, outline: list[dict]):
    """同步跑 _sections_worker，记录每一节实际收到的材料参数。

    用打桩替换 _generate_section_task：真实调用会打模型，测试里既慢又不可控。
    只断言「哪一节收到哪一份材料」——这正是本次改动要保证的契约。
    """
    import json as _json

    from app.db import SessionLocal
    from app.models import GenerationJob, LearningGoal, Tutorial, TutorialVersion
    from app.services import tutorials as T

    calls: list[dict] = []

    def fake_task(**kwargs):
        calls.append(kwargs)
        idx = kwargs["index"]
        return {
            "index": idx,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                      "usage_source": "estimated"},
            "section": {
                "id": f"s{idx}",
                "title": outline[idx]["title"],
                "content": [{"type": "text", "title": "本章概要",
                             "body": f"{outline[idx]['title']} 的概要。"}],
            },
        }

    monkeypatch.setattr(T, "_generate_section_task", fake_task)
    monkeypatch.setattr(T, "_submit_companion_tasks", lambda *a, **k: {})

    # 把 materials_context 换成哨兵：本测试要断言的是「哪一节走哪条材料路由」，
    # 不是材料抽取本身（那由 test_materials.py 覆盖）。哨兵让路由可观测、可断言非空。
    from app.services import materials as _mat

    def _sentinel_context(db, goal_id, *, chapter=None, all_chapters=None,
                          global_only=False, **kwargs):
        if chapter:
            return f"[章节材料:{chapter}]"
        if global_only:
            return "[全书级材料]"
        return "[全量材料]"

    monkeypatch.setattr(_mat, "materials_context", _sentinel_context)

    _RECORDER_SEQ["n"] += 1
    tag = f"{_RECORDER_SEQ['n']}-{spec.get('scene','')}"

    db = SessionLocal()
    try:
        goal = LearningGoal(
            id=f"g-reading-{tag}", title="哲学通论导读", domain_key="humanities",
            status="active", format_spec_snapshot=_json.dumps(spec, ensure_ascii=False),
            format_spec_source="manual", format_spec_id="spec-reading",
        )
        db.add(goal)
        db.flush()
        tutorial = Tutorial(goal_id=goal.id, title="哲学通论导读 · 阅读教程规范", status="outline")
        db.add(tutorial)
        db.flush()
        version = TutorialVersion(
            tutorial_id=tutorial.id, version=1,
            content_json=_json.dumps({
                "format_spec": spec, "outline": outline, "sections": [],
            }, ensure_ascii=False),
            model_provider="demo", model_name="demo",
        )
        db.add(version)
        db.flush()
        tutorial.current_version_id = version.id
        job = GenerationJob(goal_id=goal.id, job_type="tutorial_sections",
                            status="running", progress=0)
        db.add(job)
        db.commit()
        tutorial_id, job_id = tutorial.id, job.id
    finally:
        db.close()

    T._sections_worker(tutorial_id, job_id)

    db = SessionLocal()
    try:
        # _sections_worker 自己会新建一个草稿版本，所以按 version 取最新的那份
        v = (
            db.query(TutorialVersion)
            .filter(TutorialVersion.tutorial_id == tutorial_id)
            .order_by(TutorialVersion.version.desc())
            .first()
        )
        saved = _json.loads(v.content_json)
        t = db.get(Tutorial, tutorial_id)
        return calls, saved, t.status
    finally:
        db.close()


def test_reading_guide_runs_two_phases_with_per_chapter_materials(client, monkeypatch):
    """阅读规范：章节层按章注入、后置全书层吃各章概要，且分两批执行。

    这是「先大纲 -> 章节层并行 -> 最后全书层」这条流程的代码级保证：
    - 章节节的 chapter 参数必须是对应章号（子线程内据此只取本章材料）；
    - 前置全书层（全书认知地图）拿 global_only 材料，chapter 为空；
    - 后置全书层（思想背景 / 总结）第二批执行，materials_text 是各章概要而非全书原文；
    - 最终 sections 按大纲顺序齐全。
    """
    calls, saved, status = _run_sections_worker_with_recorder(
        monkeypatch, _reading_spec(), READING_OUTLINE
    )

    by_index = {c["index"]: c for c in calls}
    assert len(calls) == len(READING_OUTLINE), f"节数 {len(calls)} != {len(READING_OUTLINE)}"

    # READING_OUTLINE: idx0 全书认知地图 / idx1 第一章 / idx2 第二章 / idx3 思想背景 / idx4 总结
    # 新架构：章节层(1,2)进第一批，所有全书层(0,3,4)进第二批吃各章概要
    order = [c["index"] for c in calls]
    assert set(order[:2]) == {1, 2}, f"第一批应是章节层: {order}"
    assert set(order[2:]) == {0, 3, 4}, f"第二批应是全部全书层: {order}"

    # 章节层：章号正确、all_chapters 完整、materials_text 留空由子线程按章取
    assert by_index[1]["chapter"] == "1"
    assert by_index[2]["chapter"] == "2"
    assert sorted(by_index[1]["all_chapters"]) == ["1", "2"]
    assert by_index[1]["materials_text"] == ""     # 章节层在子线程内按 chapter 取，主线程传空

    # 全书层（含前置的认知地图/总结，后置的思想背景）：第二批，统一吃各章概要
    for idx in (0, 3, 4):
        book = by_index[idx]
        assert book["chapter"] is None
        assert book["all_chapters"] == []
        assert "各章导读概要" in book["materials_text"], f"idx{idx} 全书层应吃各章概要"
        assert "第一章 导论" in book["materials_text"]
        assert "不得据此编造原文未出现的内容" in book["materials_text"]

    # 全书认知地图（idx0）也在第二批：它要写核心思想/思维导图，必须等章节层完成才有依据
    assert by_index[0]["materials_text"] != ""

    # 成品：五节齐全、顺序正确（生成顺序 != 文档顺序；results 按 index 排序合并）
    titles = [sec["title"] for sec in saved["sections"]]
    assert titles == [item["title"] for item in READING_OUTLINE], titles
    # 不断言 status == "drafted"：本夹具没建验收标准，check_structure 会因
    # 「章节均映射验收标准」不通过而降级为 drafted_with_issues，与两阶段逻辑无关。
    # 本测试要锁的是「哪一节收到哪一份材料」与「五节齐全且顺序正确」。
    assert status in ("drafted", "drafted_with_issues")


def test_non_reading_specs_keep_single_batch_full_material_injection(client, monkeypatch):
    """硬边界：非阅读规范（练习 / 试卷 / 默认）行为逐字不变。

    授权范围明确是「影响只限于阅读教程规范」。所以任何其它 scene 都必须：
    - 不传 chapter（子线程不会按章过滤材料）；
    - materials_text 是全量材料；
    - 一批全部并行，不分前后阶段。
    这条测试是防止后续重构把按章逻辑泄漏到练习 / 试卷链路的护栏。
    """
    for scene in ("exercise", "exam_paper", "default_tutorial"):
        calls, saved, _status = _run_sections_worker_with_recorder(
            monkeypatch, _reading_spec(scene=scene), READING_OUTLINE
        )
        assert len(calls) == len(READING_OUTLINE)
        for call in calls:
            assert call["chapter"] is None, f"{scene} 不该按章注入"
            assert call["all_chapters"] == []
            assert call["materials_text"] == "[全量材料]", f"{scene} 应走全量注入"
        # 全量材料路径：没有任何一节收到「各章导读概要」，且一批生成（无第二批）
        assert not any("各章导读概要" in c["materials_text"] for c in calls)


def test_reading_guide_without_chapter_headings_falls_back(client, monkeypatch):
    """无章号的大纲（导读一篇论文）必须退回全量注入。

    若强行启用 global_only，论文正文会因为没有章号而被整份过滤掉，
    模型将无内容可写 —— 这比 token 超标更糟，是静默产出空壳。
    """
    paper_outline = [
        {"id": "b1", "title": "全文认知地图", "purpose": "p", "content_type": "application", "criteria_ids": []},
        {"id": "b2", "title": "研究问题与方法", "purpose": "p", "content_type": "application", "criteria_ids": []},
        {"id": "b3", "title": "结论与贡献", "purpose": "p", "content_type": "application", "criteria_ids": []},
    ]
    calls, saved, _status = _run_sections_worker_with_recorder(
        monkeypatch, _reading_spec(), paper_outline
    )
    for call in calls:
        assert call["chapter"] is None
        assert call["materials_text"] == "[全量材料]"   # fallback -> 退回全量注入
    titles = [sec["title"] for sec in saved["sections"]]
    assert titles == [item["title"] for item in paper_outline]
def test_chapter_scope_block_differs_by_scene():
    """按章范围声明必须按 scene 分流：试卷禁跨章，阅读导读允许跨章思想关联。

    这两者语义相反，不是文风差异：
    - 试卷 / 练习：每章自成一卷，跨章就泄题，必须「不得跨章综合」；
    - 阅读导读：规范要求「思想关联：与其他章节的关联」「识别跨章节的概念和论证」，
      照搬「不得跨章综合」会把规范自己定义的核心能力禁掉。
    """
    from app.llm.prompts import _chapter_scope_block

    exam = _chapter_scope_block("第 1 章 线性方程组 单元检测卷", reading_guide=False)
    assert "不得跨章综合" in exam
    assert "只覆盖" in exam

    reading = _chapter_scope_block("第一章 导论", reading_guide=True)
    assert "不得跨章综合" not in reading, "阅读导读不得禁跨章"
    assert "思想联系" in reading
    assert "只导读" in reading
    # 导读版仍要限制：只定位、不展开讲其它章
    assert "不展开讲解其它章的内容" in reading
    assert "全书层章节" in reading

    # 非章标题不触发任何范围块
    assert _chapter_scope_block("全书认知地图", reading_guide=True) == ""
    assert _chapter_scope_block("参考答案") == ""


def test_reading_guide_section_prompt_uses_guide_scope_not_exam(client):
    """阅读规范的章节提示词：走导读版范围声明，且不得混入试卷自检。"""
    from app.learning.disciplines import get_profile

    spec = _reading_spec(scene="reading_guide")
    goal = SimpleNamespace(
        title="哲学通论导读", motivation="", application_context="", current_level="",
        time_budget="", user_notes="", hard_constraints="", capability_level="L3",
        generation_tier="standard", format_spec_snapshot=json.dumps(spec, ensure_ascii=False),
    )
    _, user = prompts.section(
        goal, get_profile("humanities"),
        {"title": "第一章 导论", "_deliverable": None}, [], [], "（本章材料）",
    )
    assert "只导读「第一章 导论」" in user
    assert "不得跨章综合" not in user
    assert "卷面自检" not in user          # 阅读规范不是试卷，不该有试卷自检
    assert "（本章材料）" in user
STRAY_OUTLINE = [
    {"id": "c1", "title": "全书认知地图", "purpose": "p", "content_type": "application", "criteria_ids": []},
    {"id": "c2", "title": "第一章 导论", "purpose": "p", "content_type": "application", "criteria_ids": []},
    {"id": "c3", "title": "补充材料", "purpose": "p", "content_type": "application", "criteria_ids": []},
    {"id": "c4", "title": "第二章 存在论", "purpose": "p", "content_type": "application", "criteria_ids": []},
    {"id": "c5", "title": "总结与延伸阅读", "purpose": "p", "content_type": "application", "criteria_ids": []},
]


def test_reading_guide_stray_section_between_chapters_gets_materials(client, monkeypatch):
    """回归：夹在章号区间中间的无章号节，reading 模式不得拿到空材料。

    「补充材料」这类节没有章号 -> 归为全书层 -> 第二批吃各章概要（digest）。
    digest 由章节层产出拼成，绝不会是空串，模型不会因无上下文而编造。
    （旧实现按 front/back 位置派发，夹在中间的游离节会三不管、拿到空串。）
    """
    calls, saved, _status = _run_sections_worker_with_recorder(
        monkeypatch, _reading_spec(), STRAY_OUTLINE
    )
    by_index = {c["index"]: c for c in calls}
    assert len(calls) == 5

    # STRAY_OUTLINE: idx0 认知地图 / idx1 第一章 / idx2 补充材料(游离) / idx3 第二章 / idx4 总结
    stray = by_index[2]                       # 「补充材料」
    assert stray["chapter"] is None           # 它不是章节层
    # 关键断言：游离节归为全书层，拿到非空的各章概要，不再是被漏掉的空串
    assert "各章导读概要" in stray["materials_text"]

    # 章节层仍按章派发（第一批）
    assert by_index[1]["chapter"] == "1"
    assert by_index[3]["chapter"] == "2"
    # 全部全书层（认知地图 / 补充材料 / 总结）都吃各章概要
    for idx in (0, 2, 4):
        assert "各章导读概要" in by_index[idx]["materials_text"]

    # 生成顺序：章节层(1,3)在前，全书层(0,2,4)在后
    order = [c["index"] for c in calls]
    assert set(order[:2]) == {1, 3}, order
    assert set(order[2:]) == {0, 2, 4}, order

    # 成品：五节齐全、按大纲顺序（生成顺序 != 文档顺序）
    titles = [sec["title"] for sec in saved["sections"]]
    assert titles == [item["title"] for item in STRAY_OUTLINE]
def test_reading_digest_prefers_summary_and_excludes_deep_dive():
    """后置全书层的 digest 必须只取「概要」，不得吞入「深度导读」细节。

    阅读规范要求「一节只输出一个 content 块」，此时概要不是独立的块、而是 body 里的
    `### 本章概要` 小标题段。digest 若退化成「从头截 N 字」，会把深度导读的大段细节
    一起喂给后置全书层——既挤占 token 预算，又让本该有全局视角的那一节陷进细节。

    另有一个陷阱：「深度导读」含「导读」二字，会被 READING_PREFER_BLOCK_RE 误命中，
    而它恰恰是细节层，必须用 READING_DIGEST_STOP_RE 排除。
    """
    from app.services import tutorials as T

    # 一节一块（阅读规范形态）：概要段 + 深度导读段
    body = (
        "### 本章概要\n\n本章提出哲学是对思想的思想，核心问题是前提批判。\n"
        "本章结论：哲学是理论思维的前提批判。\n\n"
        "### 深度导读\n\n#### 核心概念详解\n\n" + "很长的深度细节内容。" * 300
    )
    sec = {"title": "第一章 导论",
           "content": [{"type": "text", "title": "第一章 导论", "body": body}]}
    d = T._reading_digest(sec, limit=3000)
    assert "前提批判" in d                        # 概要被取到
    assert "很长的深度细节内容" not in d          # 深度细节被排除
    assert len(d) < 200                           # 只留下概要段，不是 3000 字

    # 块标题含「概要」-> 第 1 级命中
    sec_block = {"title": "第一章", "content": [
        {"type": "text", "title": "本章概要", "body": "概要内容。"},
        {"type": "text", "title": "深度导读", "body": "细节" * 300},
    ]}
    d2 = T._reading_digest(sec_block, limit=3000)
    assert d2 == "概要内容。"                      # 只取概要块，不含「深度导读」块

    # 兜底：无任何概要标记 -> 从头截，超限标注
    sec_plain = {"title": "x", "content": [
        {"type": "text", "title": "正文", "body": "没有概要小标题的正文。"}]}
    assert "没有概要小标题的正文" in T._reading_digest(sec_plain, limit=3000)

    big = {"title": "x", "content": [{"type": "text", "title": "第一章",
          "body": "### 本章概要\n\n" + "概要" * 2000 + "\n### 深度导读\n细节"}]}
    d3 = T._reading_digest(big, limit=200)
    assert "已截断" in d3 and len(d3) <= 260


def test_reading_digest_block_caps_total_and_flags_missing_chapters():
    """各章概要合计有上限；超限或某章缺失时明确声明，避免全书层以为看全了。"""
    from app.services import tutorials as T

    outline = [{"title": f"第{i+1}章"} for i in range(3)]
    results = {
        i: {"section": {"title": f"第{i+1}章", "content": [
            {"type": "text", "title": "第{i+1}章",
             "body": f"### 本章概要\n\n第{i+1}章的概要内容。"}]}}
        for i in range(3)
    }
    blk = T._reading_digest_block(outline, results, [0, 1, 2])
    assert "各章导读概要" in blk
    assert "第1章的概要内容" in blk and "第3章的概要内容" in blk
    assert "不得据此编造原文未出现的内容" in blk

    # 缺某章结果 -> 不崩，只包含存在的章
    partial = T._reading_digest_block(outline, {0: results[0]}, [0, 1, 2])
    assert "第1章的概要内容" in partial
    assert "第2章的概要内容" not in partial

    # 全缺 -> 空串（调用方据此判断无概要可用）
    assert T._reading_digest_block(outline, {}, [0, 1, 2]) == ""

    # 合计上限：把单章上限调大、总上限调小，验证触发「其余章节概要未注入」声明
    orig_total = T.READING_DIGEST_TOTAL_CHARS
    try:
        T.READING_DIGEST_TOTAL_CHARS = 60
        capped = T._reading_digest_block(outline, results, [0, 1, 2])
        assert "其余章节概要因长度上限未注入" in capped
        assert "不得声称已通读全书" in capped
    finally:
        T.READING_DIGEST_TOTAL_CHARS = orig_total
def test_reading_guide_scene_is_independent_from_guidance_family():
    """阅读规范独立于「教程族」：拿到章名即节标题的指令，但仍接管节标题对齐。

    这是「独立」这条设计决策的护栏，两个方向都要锁死：
    - reading_guide 不进 GUIDANCE_SCENES：否则 authoritative_spec_dict 对无交付物的它
      返回 {}，align_section_titles 跳过，节标题由模型自拟、不再对齐大纲章名；
      而按章注入依赖节标题里可靠的「第 N 章」章名，标题一乱 chapter_marker 就提不到，
      两阶段静默 fallback 到全量注入 -> 大部头超窗口。
    - 但 outline 指令要放行：阅读规范无交付物清单时必须拿到「一章一节，章名即
      section 标题」，而不是试卷那套「每章试卷、答案、判断题各一节」。
    """
    from types import SimpleNamespace

    from app.llm import prompts
    from app.services import format_specs as fs
    from app.services.utils import (
        GUIDANCE_SCENES,
        _spec_dict_is_authoritative,
        is_guidance_snapshot,
    )
    from app.learning.disciplines import get_profile

    spec = _reading_spec(scene="reading_guide")
    assert fs.READING_GUIDE_SCENE == "reading_guide"
    # 方向一：不属于教程族
    assert "reading_guide" not in GUIDANCE_SCENES
    assert is_guidance_snapshot(spec) is False
    # 方向一的效果：仍接管结构（节标题对齐、导出走规范模板）
    assert bool(fs.authoritative_spec_dict(spec)) is True
    assert _spec_dict_is_authoritative(spec) is True
    assert fs.delivery_contract_for_snapshot(spec) is None   # 无交付物 -> 不生成契约

    # 方向二：outline 指令放行到「章名即 section 标题」
    goal = SimpleNamespace(
        title="哲学通论导读", motivation="", application_context="", current_level="",
        time_budget="", user_notes="", hard_constraints="", capability_level="L3",
        generation_tier="standard", format_spec_snapshot=json.dumps(spec, ensure_ascii=False),
    )
    _, outline_user = prompts.outline(goal, get_profile("humanities"), [], "（材料）")
    assert "章名即 section 标题" in outline_user
    assert "每章试卷" not in outline_user

    # _format_spec_block 仍用「结构、排版和交付物唯一依据」措辞（接管结构），
    # 而不是教程族那句「不决定章节数与章节标题」
    block = prompts._format_spec_block("outline", goal)
    assert "结构、排版和交付物唯一依据" in block
    assert "不决定章节数与章节标题" not in block
def test_reading_digest_fallback_never_swallows_deep_dive_nor_drops_chapter():
    """兜底路径的两个失败模式都必须堵住。

    模型漏写 `### 本章概要` 小标题时，digest 走第 3 级兜底。兜底原本「从头截 N 字」，
    会出两种事故，都是静默的：
    1. 吞细节：把「深度导读 / 核心概念详解」的大段内容全喂进后置全书层，
       既挤占 token 预算，又让本该有全局视角的那一节陷进细节（实测 5285 字 body
       被截出 3011 字 digest，其中绝大部分是细节）。
    2. 整章丢失：body 第一个标题就是「深度导读」时，若在深度层标题前截断会得到空串，
       _reading_digest_block 会因此跳过整章 -> 全书层完全不知道这一章存在，
       直接违背规范自己的「思想完整性」。
    """
    from app.services import tutorials as T

    detail = "- 很长的细节展开，不该进 digest。" * 200

    # 事故 1：漏写概要标题，正文里混着概要字段与深度导读
    body_no_summary = (
        "> 本章位置：承接导论。\n\n**核心思想**：哲学是前提批判。\n\n"
        "### 深度导读\n\n#### 核心概念详解\n\n" + detail
    )
    d1 = T._reading_digest(
        {"title": "x", "content": [{"type": "text", "title": "第一章", "body": body_no_summary}]},
        limit=3000,
    )
    assert "哲学是前提批判" in d1                # 概要内容保住了
    assert "很长的细节展开" not in d1             # 深度细节被挡住
    assert len(d1) < 400

    # 事故 2：body 第一个标题就是深度层 -> 不得返回空串（否则整章被跳过）
    body_deep_first = "### 深度导读\n\n##### 概念\n\n" + detail
    d2 = T._reading_digest(
        {"title": "x", "content": [{"type": "text", "title": "第二章", "body": body_deep_first}]},
        limit=3000,
    )
    assert d2.strip(), "digest 为空会导致整章在全书层视野里消失"
    assert "缺「本章概要」小节" in d2              # 显式标注，全书层知道有缺口

    # digest_block 因此不会跳过该章
    results = {0: {"section": {"title": "第二章", "content": [
        {"type": "text", "title": "第二章", "body": body_deep_first}]}}}
    blk = T._reading_digest_block([{"title": "第二章"}], results, [0])
    assert "第二章" in blk

    # 完全空 body 仍返回空串（没有内容可给，不该造出占位文本）
    assert T._reading_digest({"title": "x", "content": [
        {"type": "text", "title": "t", "body": "   "}]}, limit=3000) == ""
def test_template_headings_only_collects_h2_so_inner_headings_cannot_hijack_chapter():
    """回归：_template_headings 只收 ## 级，内层小标题名不得劫持章标题渲染。

    该表的键要与节标题比对（节标题一律渲染成「## 中文序号、」）。若连 ### / #### / #####
    一起收，模板里的内层小标题名会混进键集合：阅读教程规范的 content_structure 有 27 个
    内层标题（本章概要 / 深度导读 / 核心概念详解 / 难点辨析…），大纲模型一旦把某节命名成
    其中之一，就会命中并原样输出成「### 本章概要」，章级 ## 序号凭空消失、整篇层级错位。
    """
    from types import SimpleNamespace

    from app.services.tutorials import _render_format_spec_document, _template_headings

    spec = {
        "name": "阅读教程规范", "scene": "reading_guide", "deliverables": [],
        "content_structure": (
            "# 阅读教程\n\n"
            "### 本章概要\n\n**核心问题**：…\n\n"
            "### 深度导读\n\n#### 核心概念详解\n\n##### 前提批判\n\n- 严谨定义：…\n"
        ),
    }
    heads = _template_headings(spec)
    # 只有 H1 文档标题不算章级；内层标题一律不进表
    assert heads == {}, heads
    for name in ("本章概要", "深度导读", "核心概念详解", "前提批判"):
        assert name not in heads

    # 即便节标题恰好等于内层小标题名，也必须走 fallback 补「## 中文序号、」，
    # 而不是原样输出成 ###
    content = {
        "format_spec": spec,
        "delivery_contract": None,
        "sections": [{"title": "本章概要", "content": [
            {"type": "text", "title": "本章概要", "body": "### 本章概要\n\n正文。\n"}]}],
    }
    lines: list[str] = []
    _render_format_spec_document(content, SimpleNamespace(title="哲学通论导读"),
                                 content["sections"], lines)
    md = "\n".join(lines)
    heads = [ln for ln in md.splitlines() if ln.startswith("#")]
    # 章标题必须是带序号的 ## 级，绝不能退化成模板里那个 ### 本章概要
    assert "## 一、本章概要" in heads, heads
    assert not any(h.startswith("### 本章概要") for h in heads), heads
    # 文档 H1 唯一
    assert sum(1 for h in heads if h.startswith("# ")) == 1, heads

    # 对照：模板确实写了 ## 级章标题时（练习规范形态），必须逐字沿用含序号的模板行
    spec2 = {
        "name": "练习生成规范", "scene": "exercise",
        "content_structure": "# 练习名称\n\n## 一、易错辨析\n\n## 二、训练\n",
    }
    assert _template_headings(spec2) == {"易错辨析": "## 一、易错辨析", "训练": "## 二、训练"}


def test_reading_digest_total_covers_all_chapters_without_dropping():
    """18 章（第一卷规模）必须全部进入 digest，不得静默丢弃后面的章。

    曾固定 3000 字/章 + 30000 字合计上限：18 章需 54000 字，后 8 章被截掉，
    于是「核心概念索引」漏条目、「阅读路线」漏章节，且无任何提示。
    现在单章额度随章数自适应收缩。
    """
    from app.services import tutorials as T

    n = 18
    outline = [{"title": f"第{i+1}篇"} for i in range(n)]
    results = {
        i: {"section": {"title": f"第{i+1}篇", "content": [
            {"type": "text", "title": f"第{i+1}篇",
             "body": "### 本章概要\n\n" + "核心内容。" * 500 + "\n### 深度导读\n细节"}]}}
        for i in range(n)
    }
    blk = T._reading_digest_block(outline, results, list(range(n)))
    missing = [i + 1 for i in range(n) if f"第{i+1}篇" not in blk]
    assert not missing, f"这些章被静默丢弃：{missing}"
    assert len(blk) <= T.READING_DIGEST_TOTAL_CHARS + 2000
    # 超大规模才允许截断，且必须显式声明
    big = T._reading_digest_block(
        [{"title": f"第{i+1}篇"} for i in range(80)],
        {i: results[i % n] | {"section": {**results[i % n]["section"], "title": f"第{i+1}篇"}}
         for i in range(80)},
        list(range(80)),
    )
    assert "其余章节概要因长度上限未注入" in big
def test_reading_section_blocks_are_merged_back_to_one(client):
    """回归：阅读规范里被模型拆成多块的节，必须确定性合并回单块。

    真实故障（毛选第一卷第八篇）：模型把一章拆成「深度导读 · 核心概念详解」等 5 个
    自拟标题的块。_render_deliverable_blocks 发现块标题未被正文首行表达，就给每块多插
    一层 `### {块标题}` 并把正文压到 `####`，于是第八篇的标题层级比其它 17 篇深一级。
    合并在生成落库与导出两处都做，历史坏数据重导出也能修复。
    """
    from types import SimpleNamespace

    from app.services.tutorials import _merge_reading_section_blocks, _render_format_spec_document

    broken = {
        "title": "第八篇 必须注意经济工作",
        "content": [
            {"type": "text", "title": "本章概要", "body": "### 本章概要\n\n概要正文。"},
            {"type": "text", "title": "深度导读 · 核心概念详解",
             "body": "### 深度导读\n\n#### 核心概念详解\n\n内容。"},
            {"type": "text", "title": "深度导读 · 思想关联", "body": "#### 思想关联\n\n内容。"},
        ],
    }
    merged = _merge_reading_section_blocks(broken)
    assert len(merged["content"]) == 1
    assert merged["content"][0]["title"] == "第八篇 必须注意经济工作"  # 块标题=节标题
    body = merged["content"][0]["body"]
    assert "### 本章概要" in body and "### 深度导读" in body and "#### 思想关联" in body

    # 单块节原样返回（幂等）
    single = {"title": "x", "content": [{"type": "text", "title": "x", "body": "### 本章概要\n\ny"}]}
    assert _merge_reading_section_blocks(single) is single

    # 渲染层级：合并后与正常单块节一致（### 本章概要 / ### 深度导读，不被压成 ####）
    spec = {"name": "阅读教程规范", "scene": "reading_guide", "deliverables": []}
    normal = {"title": "第九篇 怎样分析农村阶级",
              "content": [{"type": "text", "title": "第九篇 怎样分析农村阶级",
                           "body": "### 本章概要\n\n概要。\n\n### 深度导读\n\n#### 核心概念详解\n\n内容。"}]}
    lines: list[str] = []
    _render_format_spec_document(
        {"format_spec": spec, "delivery_contract": None, "sections": [merged, normal]},
        SimpleNamespace(title="导读"), [merged, normal], lines,
    )
    md = "\n".join(lines)
    heads = [ln for ln in md.splitlines() if ln.startswith("#")]
    # 合并后第八篇的「本章概要」应是 ###，不是被块标题挤成的 ####
    assert "### 本章概要" in heads, heads
    assert not any(h == "### 深度导读 · 核心概念详解" for h in heads), heads


def test_merge_only_applies_to_reading_guide(client):
    """合并必须只对 reading_guide 生效：练习规范刻意用多块（易错辨析 + 训练）。"""
    from app.services.utils import align_section_titles
    from app.services.tutorials import _merge_reading_section_blocks

    exercise_section = {
        "title": "第二章 训练",
        "content": [
            {"type": "text", "title": "易错辨析", "body": "### 一、易错辨析\n\n判断题。"},
            {"type": "text", "title": "训练", "body": "### 二、训练\n\n基础题。"},
        ],
    }
    # 直接调合并函数会合并（它是纯函数）；关键是**调用点**用 is_reading_guide 门控。
    # 这里验证门控判据本身对练习规范为 False。
    from app.services import format_specs as fs
    assert fs.is_reading_guide({"scene": "exercise"}) is False
    assert fs.is_reading_guide({"scene": "reading_guide"}) is True
