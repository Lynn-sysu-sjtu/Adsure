"""Shared hard eligibility gates; legacy records retain their prior defaults."""


def rule_roles(rule):
    roles = rule.get('review_roles') or []
    if not roles and rule.get('review_role'):
        roles = [rule['review_role']]
    return set(roles)


def active_rule(rule):
    return rule.get('asset_disposition') not in {
        'duplicate_source', 'source_repair_required', 'workflow_reference',
    }


def content_recall_eligible(rule):
    recall = rule.get('recall') or {}
    roles = rule_roles(rule)
    return (
        active_rule(rule)
        and (recall.get('trigger_layer') or 'content') == 'content'
        and (not roles or bool(roles & {'direct', 'fact_check'}))
    )


def judgment_candidate_eligible(rule):
    recall = rule.get('recall') or {}
    roles = rule_roles(rule)
    return (
        active_rule(rule)
        and (recall.get('trigger_layer') or 'content') in {'content', 'fact'}
        and (not roles or bool(roles & {'direct', 'fact_check'}))
    )
