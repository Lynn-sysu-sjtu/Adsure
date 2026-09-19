# -*- coding: utf-8 -*-
"""Regression contracts for preserving strong paths outside the pruned branch."""

import json
import unittest

from issue_tree_shadow_recall import recall_issue_tree_shadow


ACTUAL_USE_PATH = (
    "ENDORSEMENT.ACTUAL_USE_DUTY."
    "ENDORSER_RECOMMENDS_WITHOUT_ACTUAL_USE"
)


def _tree(*issue_ids):
    branches = []
    for issue_id in issue_ids:
        if issue_id == ACTUAL_USE_PATH:
            level_1 = "ENDORSEMENT_REVIEW"
            level_2 = "ENDORSEMENT.ACTUAL_USE_DUTY"
        else:
            level_1 = issue_id.split(".", 1)[0]
            level_2 = issue_id.rsplit(".", 1)[0]
        branches.append({
            "issue_id": level_1,
            "children": [{
                "issue_id": level_2,
                "children": [{"issue_id": issue_id, "children": []}],
            }],
        })
    return {"branches": branches}


class _Client:
    def create_chat_completion(self, messages, **kwargs):
        payload = {"selected_paths": []}
        return {
            "choices": [{"message": {"content": json.dumps(payload)}}],
        }


class RemainingCrossBranchPathPreservationTests(unittest.TestCase):
    def test_actual_use_path_can_be_preserved_from_full_tree_after_pruning(self):
        pruned_tree = _tree(
            "CLAIM_EXPRESSION.ABSOLUTE.ABSOLUTE_SUPERLATIVE_TERMS"
        )
        full_tree = _tree(
            "CLAIM_EXPRESSION.ABSOLUTE.ABSOLUTE_SUPERLATIVE_TERMS",
            ACTUAL_USE_PATH,
        )
        result = recall_issue_tree_shadow(
            {
                "material_text": "某知名明星代言并称每天登录游戏，强烈推荐。",
                "supplemental_background": "没有代言人实际游玩记录或战绩截图可供核验。",
                "industry": "游戏",
                "product_category": "MOBA手游",
            },
            pruned_tree,
            client=_Client(),
            preservation_tree=full_tree,
        )
        self.assertIn(
            ACTUAL_USE_PATH,
            {
                item["level_3_issue_id"]
                for item in result["selected_issue_paths"]
            },
        )


if __name__ == "__main__":
    unittest.main()
