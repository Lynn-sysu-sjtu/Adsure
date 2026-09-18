# -*- coding: utf-8 -*-
"""Public V3 candidate pipeline entry point."""

import legal_issue_candidate_pipeline_v3_impl as _impl
from legal_issue_candidate_pipeline_v3_impl import *  # noqa: F401,F403


def build_candidate_messages(rule, source_file):
    messages = _impl.build_candidate_messages(rule, source_file)
    messages[0]["content"] += " 不得新增法条。"
    return messages


parse_candidate_response = _impl.parse_candidate_response
compile_draft_assets = _impl.compile_draft_assets
select_smoke_rules = _impl.select_smoke_rules
