# -*- coding: utf-8 -*-
"""Select a small, role-safe representative set from issue-tree expansion."""

import os
from pathlib import Path

from legal_issue_groups import AUTHORITY_RANK, legal_issue_group_index, select_group_representatives
from rule_identity import rule_identity
from rule_vector_index import DEFAULT_VECTOR_INDEX_PATH, load_rule_vector_index, semantic_vector_records
from semantic_recall import cosine_similarity


ACTIONABLE_ROLE_KEYS = {
    'direct': 'direct_rule_uids',
    'fact_check': 'fact_check_rule_uids',
}
NON_ACTIONABLE_KEYS = (
    'supporting_rule_uids', 'proactive_check_rule_uids', 'exception_rule_uids',
)
DEFAULT_LIMITS = {'per_path': 3, 'direct': 6, 'fact_check': 2}


class SelectorSemanticError(RuntimeError):
    def __init__(self, status):
        super().__init__(status)
        self.status = status


def _query_text(request, context_package):
    material = request.get('material') or {}
    context = request.get('context') or {}
    parts = [
        context_package.get('material_text') or material.get('content') or '',
        context_package.get('supplemental_background') or material.get('supplemental_background') or '',
        context_package.get('context_summary') or '',
        context.get('industry') or '', context.get('product_category') or '',
        context.get('scenario') or '',
        ' '.join(context.get('platforms') or []),
        ' '.join(context.get('core_claims') or []),
    ]
    return ' '.join(str(part) for part in parts if part)


def _cached_entry(index, rule, record):
    uid = rule_identity(rule)
    scenario = record.get('scenario_id') or 'rule_summary'
    text_hash = record.get('vector_text_hash')
    entry = index.get((uid, scenario, text_hash))
    if entry is None and rule.get('rule_id') and rule.get('rule_id') != uid:
        entry = index.get((rule.get('rule_id'), scenario, text_hash))
    return entry


def _cached_semantic_scores(rules, request, context_package, *, embedding_client=None,
                            vector_index_path=None, semantic_backend=None):
    backend = (semantic_backend or os.getenv('ADSURE_SEMANTIC_BACKEND') or 'zhipu').lower()
    if backend not in {'embedding', 'zhipu', 'zhipu_embedding'}:
        raise SelectorSemanticError('unsupported_semantic_backend')
    path = Path(vector_index_path or os.getenv('ADSURE_RULE_VECTOR_INDEX') or DEFAULT_VECTOR_INDEX_PATH)
    if not path.exists():
        raise SelectorSemanticError('missing_vector_index')
    try:
        index = load_rule_vector_index(path)
    except Exception as exc:
        raise SelectorSemanticError('invalid_vector_index') from exc
    if not index:
        raise SelectorSemanticError('invalid_vector_index')

    cached = []
    for rule in rules:
        for record in semantic_vector_records(rule):
            entry = _cached_entry(index, rule, record)
            if entry and entry.get('embedding'):
                cached.append((rule, record, entry['embedding']))
    if not cached:
        return {}
    if embedding_client is None:
        from zhipu_embedding_client import ZhipuEmbeddingClient
        embedding_client = ZhipuEmbeddingClient()
    query_vector = embedding_client.embed_texts([_query_text(request, context_package)])[0]
    best = {}
    for rule, record, vector in cached:
        uid = rule_identity(rule)
        score = cosine_similarity(query_vector, vector)
        current = best.get(uid)
        if current is None or score > current['semantic_score']:
            best[uid] = {
                'semantic_score': float(score),
                'scenario_id': record.get('scenario_id') or 'rule_summary',
                'score_source': 'cached_zhipu',
            }
    return best


def _platform(request):
    value = (request.get('context') or {}).get('platforms') or []
    if isinstance(value, list):
        return str(value[0] if value else '')
    return str(value or '')


def _fallback_key(rule, score_item):
    has_score = score_item is not None and score_item.get('semantic_score') is not None
    score = float(score_item.get('semantic_score')) if has_score else 0.0
    return (
        not has_score,
        -score,
        -AUTHORITY_RANK.get(str(rule.get('source_type') or ''), 0),
        rule.get('risk_level') != '高',
        int(rule.get('serial_no') or 999999),
        str(rule_identity(rule) or ''),
    )


def _ordered_issue_ids(selected_issue_paths):
    ordered = []
    for item in selected_issue_paths or []:
        issue_id = item.get('level_3_issue_id') if isinstance(item, dict) else None
        if issue_id and issue_id not in ordered:
            ordered.append(issue_id)
    return ordered


def select_issue_tree_rules(
    expansion,
    selected_issue_paths,
    rules_by_uid,
    request,
    context_package,
    legal_issue_groups,
    *,
    semantic_scorer=None,
    semantic_backend=None,
    embedding_client=None,
    vector_index_path=None,
    per_path_limit=3,
    direct_limit=6,
    fact_check_limit=2,
):
    issue_ids = _ordered_issue_ids(selected_issue_paths)
    role_uids = {
        role: set(expansion.get(key) or []) for role, key in ACTIONABLE_ROLE_KEYS.items()
    }
    non_actionable = sorted({
        uid for key in NON_ACTIONABLE_KEYS for uid in (expansion.get(key) or [])
    })
    traces = expansion.get('trace') or []
    by_path = {issue_id: [] for issue_id in issue_ids}
    seen_path_role_uid = set()
    for trace in traces:
        issue_id = trace.get('issue_id')
        role = trace.get('mapping_type')
        uid = trace.get('canonical_rule_uid')
        key = (issue_id, role, uid)
        if issue_id not in by_path or role not in role_uids or uid not in role_uids[role]:
            continue
        if key in seen_path_role_uid or uid not in rules_by_uid:
            continue
        seen_path_role_uid.add(key)
        by_path[issue_id].append({'issue_id': issue_id, 'mapping_role': role,
                                  'rule_uid': uid, 'rule': rules_by_uid[uid]})

    group_index = legal_issue_group_index(legal_issue_groups or {'groups': []})
    group_collapses = []
    path_data = []
    representatives = []
    for issue_id in issue_ids:
        candidates = by_path.get(issue_id, [])
        buckets = {}
        for candidate in candidates:
            group = group_index.get(candidate['rule_uid'])
            group_id = group.get('issue_group_id') if group else None
            bucket_key = (candidate['mapping_role'], group_id or 'uid:' + candidate['rule_uid'])
            buckets.setdefault(bucket_key, []).append(candidate)
        path_reps = []
        collapsed = []
        for (role, group_key), items in buckets.items():
            if group_key.startswith('uid:'):
                selected_rules = [items[0]['rule']]
                supporting = []
                group_id = None
            else:
                selected_rules, supporting = select_group_representatives(
                    [item['rule'] for item in items], platform=_platform(request)
                )
                group_id = group_key
            item_by_uid = {item['rule_uid']: item for item in items}
            for rule in selected_rules:
                uid = rule_identity(rule)
                candidate = dict(item_by_uid[uid])
                candidate['issue_group_id'] = group_id
                path_reps.append(candidate)
                representatives.append(rule)
            collapsed.extend(supporting)
            if supporting:
                group_collapses.append({
                    'issue_id': issue_id, 'mapping_role': role, 'issue_group_id': group_id,
                    'representative_rule_uids': [rule_identity(rule) for rule in selected_rules],
                    'collapsed_supporting_rule_uids': sorted(supporting),
                })
        path_data.append({'issue_id': issue_id, 'representatives': path_reps,
                          'collapsed_supporting_rule_uids': sorted(set(collapsed))})

    unique_rules = {rule_identity(rule): rule for rule in representatives if rule_identity(rule)}
    semantic_status = 'ok'
    try:
        scorer = semantic_scorer or _cached_semantic_scores
        scores = scorer(
            list(unique_rules.values()), request, context_package,
            embedding_client=embedding_client, vector_index_path=vector_index_path,
            semantic_backend=semantic_backend,
        ) or {}
        if not scores:
            semantic_status = 'no_scores'
    except SelectorSemanticError as exc:
        semantic_status = exc.status
        scores = {}
    except Exception:
        semantic_status = 'provider_error'
        scores = {}

    dropped = []
    rankings = []
    queues = {'direct': {}, 'fact_check': {}}
    for path in path_data:
        ranked = sorted(
            path['representatives'],
            key=lambda item: _fallback_key(item['rule'], scores.get(item['rule_uid'])),
        )
        kept = ranked[:max(0, int(per_path_limit))]
        for item in ranked[max(0, int(per_path_limit)):]:
            dropped.append({'issue_id': path['issue_id'], 'rule_uid': item['rule_uid'],
                            'mapping_role': item['mapping_role'],
                            'drop_reason': 'per_path_limit_exceeded'})
        ranked_records = []
        for item in ranked:
            score_item = scores.get(item['rule_uid']) or {}
            ranked_records.append({
                'rule_uid': item['rule_uid'], 'mapping_role': item['mapping_role'],
                'issue_group_id': item.get('issue_group_id'),
                'semantic_score': score_item.get('semantic_score'),
                'scenario_id': score_item.get('scenario_id'),
                'score_source': score_item.get('score_source'),
                'source_type': item['rule'].get('source_type'),
            })
        for role in queues:
            queues[role][path['issue_id']] = [item for item in kept if item['mapping_role'] == role]
        rankings.append({
            'issue_id': path['issue_id'],
            'representative_rule_uids': [item['rule_uid'] for item in path['representatives']],
            'collapsed_supporting_rule_uids': path['collapsed_supporting_rule_uids'],
            'ranked_rule_uids': [item['rule_uid'] for item in ranked],
            'ranked_rules': ranked_records,
            'per_path_selected_rule_uids': [],
        })

    selected = {'direct': [], 'fact_check': []}
    selected_set = set()
    ranking_by_issue = {item['issue_id']: item for item in rankings}
    role_limits = {'direct': max(0, int(direct_limit)), 'fact_check': max(0, int(fact_check_limit))}
    for role in ('direct', 'fact_check'):
        for round_index in range(max(0, int(per_path_limit))):
            for issue_id in issue_ids:
                queue = queues[role].get(issue_id) or []
                if round_index >= len(queue):
                    continue
                item = queue[round_index]
                uid = item['rule_uid']
                if uid in selected_set:
                    dropped.append({'issue_id': issue_id, 'rule_uid': uid, 'mapping_role': role,
                                    'drop_reason': 'duplicate_uid_already_selected'})
                    continue
                if len(selected[role]) >= role_limits[role]:
                    dropped.append({'issue_id': issue_id, 'rule_uid': uid, 'mapping_role': role,
                                    'drop_reason': role + '_global_limit_exceeded'})
                    continue
                selected[role].append(uid)
                selected_set.add(uid)
                ranking_by_issue[issue_id]['per_path_selected_rule_uids'].append(uid)

    for role in ('direct', 'fact_check'):
        for issue_id in issue_ids:
            for item in queues[role].get(issue_id) or []:
                uid = item['rule_uid']
                if uid in selected_set or any(
                    drop['issue_id'] == issue_id and drop['rule_uid'] == uid for drop in dropped
                ):
                    continue
                dropped.append({'issue_id': issue_id, 'rule_uid': uid, 'mapping_role': role,
                                'drop_reason': role + '_global_limit_exceeded'})

    selected_actionable = selected['direct'] + selected['fact_check']
    return {
        'status': 'ok',
        'semantic_status': semantic_status,
        'limits': {'per_path': int(per_path_limit), 'direct': int(direct_limit),
                   'fact_check': int(fact_check_limit)},
        'expanded_actionable_count': len(set().union(*role_uids.values())),
        'group_representative_count': len(unique_rules),
        'ungrouped_rule_count': sum(uid not in group_index for uid in unique_rules),
        'selected_direct_rule_uids': selected['direct'],
        'selected_fact_check_rule_uids': selected['fact_check'],
        'selected_actionable_rule_uids': selected_actionable,
        'non_actionable_rule_uids': non_actionable,
        'path_rankings': rankings,
        'group_collapses': group_collapses,
        'dropped_rules': dropped,
    }
