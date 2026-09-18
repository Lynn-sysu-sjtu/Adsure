# -*- coding: utf-8 -*-
"""Strict representative selection: weak nested metadata cannot define a smoke topic."""

from legal_issue_smoke_selection import SMOKE_TOPICS, _topic_score


def _has_direct_support(record, keywords):
    rule = record["rule"]
    direct = " ".join((str(rule.get("title") or ""), str(rule.get("dimension") or "")))
    return any(keyword in direct for keyword in keywords)


def select_strict_smoke_rules(records, per_track=5):
    selected = []
    gaps = []
    for track, topics in SMOKE_TOPICS.items():
        pool = [record for record in records if record.get("track") == track]
        used = set()
        for topic, keywords in topics:
            ranked = sorted(pool, key=lambda record: (-_topic_score(record, keywords), str(record["rule"].get("rule_uid") or "")))
            winner = next((record for record in ranked if record["rule"].get("rule_uid") not in used and _has_direct_support(record, keywords)), None)
            if winner:
                selected.append(winner); used.add(winner["rule"]["rule_uid"])
            else:
                gaps.append({"track": track, "topic": topic, "keywords": list(keywords)})
            if len(used) >= per_track:
                break
        if len(used) < per_track:
            for record in sorted(pool, key=lambda item: (str(item["rule"].get("dimension") or ""), str(item["rule"].get("rule_uid") or ""))):
                uid = record["rule"].get("rule_uid")
                if uid in used:
                    continue
                selected.append(record); used.add(uid)
                if len(used) >= per_track:
                    break
    return selected, gaps
