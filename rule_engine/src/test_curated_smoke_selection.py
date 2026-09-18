# -*- coding: utf-8 -*-
import unittest

from legal_issue_smoke_selection import select_representative_smoke_rules


def _record(uid, dimension, title):
    return {"rule": {"rule_uid": uid, "dimension": dimension, "title": title}, "source_file": f"游戏/{uid}.json", "track": "游戏"}


class CuratedSmokeSelectionTests(unittest.TestCase):
    def test_prefers_track_specific_topics_over_generic_rules(self):
        records = [
            _record("RUID-GAME-GENERIC", "IP侵权", "商标授权证明"),
            _record("RUID-GAME-PROB", "概率公示", "抽卡概率应当公示"),
            _record("RUID-GAME-LICENSE", "平台准入", "游戏版号核验"),
            _record("RUID-GAME-MINOR", "未成年人保护", "限制未成年人充值付费"),
            _record("RUID-GAME-ENDORSE", "代言规范", "代言人真实体验要求"),
            _record("RUID-GAME-MORALS", "公序良俗", "不得侮辱贬损消费者"),
        ]
        selected = select_representative_smoke_rules(records, per_track=5)
        self.assertNotIn("RUID-GAME-GENERIC", {item["rule"]["rule_uid"] for item in selected})


if __name__ == "__main__":
    unittest.main()
