# -*- coding: utf-8 -*-
"""v2 章节可验证性与双量规分组输出。"""
from __future__ import annotations

from app.learning.engine import check_structure


def _criteria():
    return [{"id": "C1", "statement": "能够运行程序"}]


def test_v2_operational_step_requires_expected_or_verify():
    content = {
        "outline": [{"title": "第 1 章"}],
        "sections": [{
            "title": "第 1 章",
            "mapping_criteria": ["C1"],
            "content": [
                {"type": "text", "body": "概念说明。"},
                {"type": "steps", "body": "1. 保存文件\n2. 运行命令"},
            ],
        }],
    }
    report = check_structure(content, _criteria())
    check = next(c for c in report["checks"] if c["name"] == "内容块与步骤规范")
    assert check["passed"] is False
    assert check["group"] == "teaching_quality"


def test_v2_step_with_expected_and_verify_passes():
    content = {
        "outline": [{"title": "第 1 章"}],
        "sections": [{
            "title": "第 1 章",
            "mapping_criteria": ["C1"],
            "content": [
                {"type": "steps", "body": "1. 保存并运行。预期：命令成功。验证：终端返回 0。"},
            ],
        }],
    }
    report = check_structure(content, _criteria())
    check = next(c for c in report["checks"] if c["name"] == "内容块与步骤规范")
    assert check["passed"] is True


def test_double_rubric_summary_keeps_old_fields():
    content = {
        "outline": [{"title": "第 1 章"}],
        "sections": [{"title": "第 1 章", "mapping_criteria": ["C1"], "content": [{"type": "text", "body": "内容"}]}],
    }
    report = check_structure(content, _criteria())
    assert report["passed"] is True
    assert set(report["summary"]) == {"knowledge_quality", "teaching_quality"}
    assert report["summary"]["knowledge_quality"] == {"passed": True, "passed_checks": 2, "total_checks": 2}
    assert report["summary"]["teaching_quality"] == {"passed": True, "passed_checks": 3, "total_checks": 3}
    assert {c["group"] for c in report["checks"]} == {"knowledge_quality", "teaching_quality"}
