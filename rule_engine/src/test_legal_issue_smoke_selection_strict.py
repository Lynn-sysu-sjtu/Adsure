# -*- coding: utf-8 -*-
import unittest

from legal_issue_smoke_selection_strict import select_strict_smoke_rules


class StrictSmokeSelectionTests(unittest.TestCase):
    def test_nested_weak_signal_is_a_gap_not_direct_topic_support(self):
        record = {"track": "游戏", "source_file": "游戏/a.json", "rule": {"rule_uid": "R1", "title": "禁止虚构使用效果", "dimension": "虚假宣传", "detection": {"semantic_criteria": ["概率"]}}}
        _, gaps = select_strict_smoke_rules([record], per_track=1)
        self.assertTrue(any(item["track"] == "游戏" and item["topic"] == "probability" for item in gaps))


if __name__ == "__main__": unittest.main()
