# -*- coding: utf-8 -*-
"""Tests for authority- and platform-aware group representative selection."""

import unittest

from legal_issue_groups import select_group_representatives


class LegalIssueRuleSelectionTests(unittest.TestCase):
    def setUp(self):
        self.department = {
            "rule_uid": "RUID-DEPT",
            "rule_id": "COSM-002",
            "source_type": "部门规章",
            "serial_no": 20,
        }
        self.xhs = {
            "rule_uid": "RUID-XHS",
            "rule_id": "XHS-COSM-002",
            "source_type": "平台规则",
            "platform": "小红书",
            "serial_no": 30,
        }
        self.douyin = {
            "rule_uid": "RUID-DY",
            "rule_id": "DY-COSM-002",
            "source_type": "平台规则",
            "platform": "抖音",
            "serial_no": 10,
        }

    def test_keeps_highest_authority_and_current_platform_rule(self):
        selected, supporting = select_group_representatives(
            [self.xhs, self.douyin, self.department],
            platform="小红书",
        )
        self.assertEqual(["RUID-DEPT", "RUID-XHS"], [rule["rule_uid"] for rule in selected])
        self.assertEqual(["RUID-DY"], supporting)

    def test_missing_platform_keeps_only_highest_authority_rule(self):
        selected, supporting = select_group_representatives(
            [self.xhs, self.department],
            platform="",
        )
        self.assertEqual(["RUID-DEPT"], [rule["rule_uid"] for rule in selected])
        self.assertEqual(["RUID-XHS"], supporting)

    def test_platform_only_group_is_empty_without_platform_and_kept_when_matching(self):
        selected, supporting = select_group_representatives([self.xhs, self.douyin], platform="")
        self.assertEqual([], selected)
        self.assertEqual(["RUID-DY", "RUID-XHS"], supporting)

        selected, supporting = select_group_representatives(
            [self.xhs, self.douyin],
            platform="抖音",
        )
        self.assertEqual(["RUID-DY"], [rule["rule_uid"] for rule in selected])
        self.assertEqual(["RUID-XHS"], supporting)

    def test_same_authority_uses_specificity_then_stable_uid(self):
        broad = {
            "rule_uid": "RUID-B",
            "source_type": "部门规章",
            "applies_to": {"industries": ["通用", "美妆"]},
        }
        specific = {
            "rule_uid": "RUID-A",
            "source_type": "部门规章",
            "applies_to": {"industries": ["美妆"]},
        }
        selected, supporting = select_group_representatives([broad, specific], platform="")
        self.assertEqual(["RUID-A"], [rule["rule_uid"] for rule in selected])
        self.assertEqual(["RUID-B"], supporting)


if __name__ == "__main__":
    unittest.main()
