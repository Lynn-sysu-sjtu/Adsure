# -*- coding: utf-8 -*-
"""Select a small, role-safe representative set from issue-tree expansion."""

import os
import re
from pathlib import Path

from applicability_aliases import expand_material_types, expand_product_categories
from issue_tree_targeted_policy import (
    match_targeted_policy,
    targeted_policy_enabled as policy_enabled,
)
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


def _declared_values(rule, applies_to, plural_key, top_level_key):
    values = applies_to.get(plural_key) or []
    if not values and rule.get(top_level_key):
        values = [rule.get(top_level_key)]
    if not isinstance(values, list):
        values = [values]
    return {str(value).strip() for value in values if str(value).strip()}


def _product_category_variants(values):
    return expand_product_categories(values)


def _material_type_variants(values):
    return expand_material_types(values)


def _applicability_features(rule, request):
    applies_to = rule.get("applies_to") or {}
    context = request.get("context") or {}
    dimensions = (
        ("industry", "industries", "industry", {str(context.get("industry") or "").strip()}),
        ("platform", "platforms", "platform", {
            str(value).strip() for value in (context.get("platforms") or []) if str(value).strip()
        }),
        ("product_category", "product_categories", "product_category", {
            str(context.get("product_category") or "").strip()
        }),
        ("material_type", "material_types", "material_type", {
            str(context.get("material_type") or "").strip()
        }),
        ("scenario", "scenarios", "scenario", {str(context.get("scenario") or "").strip()}),
    )
    matches = {}
    for label, plural_key, top_level_key, actual in dimensions:
        declared = _declared_values(rule, applies_to, plural_key, top_level_key)
        actual.discard("")
        if label == 'product_category':
            declared = _product_category_variants(declared)
            actual = _product_category_variants(actual)
        elif label == 'material_type':
            declared = _material_type_variants(declared)
            actual = _material_type_variants(actual)
        if label == 'product_category' and '通用' in declared and actual:
            matches[label] = True
        else:
            matches[label] = bool(declared & actual) if declared else None
    return matches, sum(value is True for value in matches.values())


def _evidence_features(rule, request, context_package):
    text = str(
        context_package.get("material_text")
        or (request.get("material") or {}).get("content")
        or ""
    )
    signals = ((rule.get("detection") or {}).get("keyword_signals") or {})
    literal_terms = list(signals.get("hit_terms") or [])
    literal_terms.extend((rule.get("examples") or {}).get("violation") or [])
    matched_literals = []
    matched_regexes = []
    for term in literal_terms:
        value = str(term or "").strip()
        if value and value in text and value not in matched_literals:
            matched_literals.append(value)
    for pattern in signals.get("regex") or []:
        value = str(pattern or "").strip()
        if not value:
            continue
        try:
            hit = re.search(value, text, flags=re.IGNORECASE)
        except re.error:
            hit = None
        if hit and value not in matched_regexes:
            matched_regexes.append(value)
    recall = rule.get('recall') or {}
    dimension_tags = ' '.join([
        str(rule.get('dimension') or ''),
        *[str(value) for value in (recall.get('tags') or [])],
    ])
    if '绝对化用语' in dimension_tags:
        absolute_patterns = (
            r'全消失',
            r'立竿见影',
            r'(?:彻底|永久|永不)(?:治愈|根治|复发|反弹)?',
            r'(?:百分之百|100\s*%)',
            r'(?:绝对|保证|确保|承诺)(?:有效|见效|安全)?',
            r'(?:零风险|无副作用|无毒副作用|无依赖)',
            r'(?:无效退款|无效包退)',
        )
        for pattern in absolute_patterns:
            hit = re.search(pattern, text, flags=re.IGNORECASE)
            if hit:
                value = 'derived:absolute_expression:' + hit.group(0)
                if value not in matched_literals:
                    matched_literals.append(value)
    matched = matched_literals + [
        value for value in matched_regexes if value not in matched_literals
    ]
    strength = 2 if matched_regexes else (1 if matched_literals else 0)
    return bool(matched), matched, strength, matched_literals, matched_regexes


def _ranking_features(rule, score_item, request, context_package):
    has_score = score_item is not None and score_item.get('semantic_score') is not None
    score = float(score_item.get('semantic_score')) if has_score else 0.0
    applicability_matches, applicability_count = _applicability_features(rule, request)
    (
        evidence_match,
        matched_triggers,
        evidence_strength,
        matched_literals,
        matched_regexes,
    ) = _evidence_features(
        rule, request, context_package
    )
    authority_rank = AUTHORITY_RANK.get(str(rule.get('source_type') or ''), 0)
    high_risk = rule.get('risk_level') == '高'
    serial_sort_value = int(rule.get('serial_no') or 999999)
    key = (
        not bool(applicability_count),
        -evidence_strength,
        -applicability_count,
        not has_score,
        -score,
        -authority_rank,
        not high_risk,
        serial_sort_value,
        str(rule_identity(rule) or ''),
    )
    return {
        'key': key,
        'applicability_matches': applicability_matches,
        'applicability_match': bool(applicability_count),
        'applicability_match_count': applicability_count,
        'evidence_trigger_match': evidence_match,
        'evidence_strength': evidence_strength,
        'matched_evidence_triggers': matched_triggers,
        'matched_evidence_literals': matched_literals,
        'matched_evidence_regexes': matched_regexes,
        'score_available': has_score,
        'semantic_score': score if has_score else None,
        'authority_rank': authority_rank,
        'high_risk': high_risk,
        'serial_sort_value': serial_sort_value,
    }


def _ordered_issue_ids(selected_issue_paths):
    ordered = []
    for item in selected_issue_paths or []:
        issue_id = item.get('level_3_issue_id') if isinstance(item, dict) else None
        if issue_id and issue_id not in ordered:
            ordered.append(issue_id)
    return ordered


def _issue_family(issue_id):
    return str(issue_id or '').split('.', 1)[0]


def _allocation_key(item, issue_order):
    return (
        not item['targeted_policy']['targeted_priority_applied'],
        *item['ranking_features']['key'],
        issue_order.get(item['issue_id'], 999999),
    )


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
    targeted_policy_enabled=None,
):
    targeted_enabled = policy_enabled(targeted_policy_enabled)
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
                group = group_index.get(items[0]['rule_uid']) or {}
                industry = str((request.get('context') or {}).get('industry') or '')
                preferred_by_industry = (
                    group.get('preferred_rule_uids_by_industry') or {}
                )
                preferred_rule_uid = (
                    preferred_by_industry.get(industry)
                    or group.get('preferred_rule_uid')
                )
                selected_rules, supporting = select_group_representatives(
                    [item['rule'] for item in items],
                    platform=_platform(request),
                    preferred_rule_uid=preferred_rule_uid,
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
    targeted_displacements = []
    queues = {'direct': {}, 'fact_check': {}}
    for path in path_data:
        for item in path['representatives']:
            item['ranking_features'] = _ranking_features(
                item['rule'],
                scores.get(item['rule_uid']),
                request,
                context_package,
            )
            item['targeted_policy'] = match_targeted_policy(
                item['rule_uid'],
                path['issue_id'],
                request,
                context_package,
                enabled=targeted_enabled,
            )
        original_ranked = sorted(
            path['representatives'],
            key=lambda item: item['ranking_features']['key'],
        )
        original_ranks = {
            item['rule_uid']: index for index, item in enumerate(original_ranked, start=1)
        }
        ranked = sorted(
            path['representatives'],
            key=lambda item: (
                not item['targeted_policy']['targeted_priority_applied'],
                *item['ranking_features']['key'],
            ),
        )
        adjusted_ranks = {
            item['rule_uid']: index for index, item in enumerate(ranked, start=1)
        }
        kept = ranked[:max(0, int(per_path_limit))]
        original_kept = original_ranked[:max(0, int(per_path_limit))]
        promoted = [
            item for item in kept
            if item not in original_kept
            and item['targeted_policy']['targeted_priority_applied']
        ]
        displaced = [item for item in original_kept if item not in kept]
        for displaced_item, promoted_item in zip(displaced, promoted):
            targeted_displacements.append({
                'issue_id': path['issue_id'],
                'rule_uid': displaced_item['rule_uid'],
                'mapping_role': displaced_item['mapping_role'],
                'displaced_by_rule_uid': promoted_item['rule_uid'],
                'targeted_policy_id': promoted_item['targeted_policy']['targeted_policy_id'],
            })
        for item in ranked[max(0, int(per_path_limit)):]:
            dropped.append({'issue_id': path['issue_id'], 'rule_uid': item['rule_uid'],
                            'mapping_role': item['mapping_role'],
                            'drop_reason': 'per_path_limit_exceeded'})
        ranked_records = []
        for item in ranked:
            score_item = scores.get(item['rule_uid']) or {}
            policy_item = item['targeted_policy']
            ranking_item = item['ranking_features']
            ranked_records.append({
                'rule_uid': item['rule_uid'], 'mapping_role': item['mapping_role'],
                'issue_group_id': item.get('issue_group_id'),
                'semantic_score': score_item.get('semantic_score'),
                'scenario_id': score_item.get('scenario_id'),
                'score_source': score_item.get('score_source'),
                'source_type': item['rule'].get('source_type'),
                'targeted_policy_id': policy_item['targeted_policy_id'],
                'targeted_priority_applied': policy_item['targeted_priority_applied'],
                'targeted_priority_reason': policy_item['targeted_priority_reason'],
                'original_rank': original_ranks[item['rule_uid']],
                'adjusted_rank': adjusted_ranks[item['rule_uid']],
                'applicability_matches': ranking_item['applicability_matches'],
                'applicability_match': ranking_item['applicability_match'],
                'applicability_match_count': ranking_item['applicability_match_count'],
                'evidence_trigger_match': ranking_item['evidence_trigger_match'],
                'evidence_strength': ranking_item['evidence_strength'],
                'matched_evidence_triggers': ranking_item['matched_evidence_triggers'],
                'matched_evidence_literals': ranking_item['matched_evidence_literals'],
                'matched_evidence_regexes': ranking_item['matched_evidence_regexes'],
                'score_available': ranking_item['score_available'],
                'authority_rank': ranking_item['authority_rank'],
                'high_risk': ranking_item['high_risk'],
                'serial_sort_value': ranking_item['serial_sort_value'],
                'ranking_key': list(ranking_item['key']),
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
    quota_allocations = []
    ranking_by_issue = {item['issue_id']: item for item in rankings}
    role_limits = {'direct': max(0, int(direct_limit)), 'fact_check': max(0, int(fact_check_limit))}
    issue_order = {issue_id: index for index, issue_id in enumerate(issue_ids)}
    for role in ('direct', 'fact_check'):
        candidates = [
            item
            for issue_id in issue_ids
            for item in (queues[role].get(issue_id) or [])
        ]
        candidates.sort(key=lambda item: _allocation_key(item, issue_order))
        families = []
        by_family = {}
        for item in candidates:
            family = _issue_family(item['issue_id'])
            if family not in by_family:
                families.append(family)
                by_family[family] = []
            by_family[family].append(item)
        family_candidates = [by_family[family][0] for family in families]
        family_candidates.sort(key=lambda item: _allocation_key(item, issue_order))
        phases = (
            ('family_coverage', family_candidates),
            ('global_competition', candidates),
        )
        allocated_keys = set()
        for phase, phase_candidates in phases:
            for item in phase_candidates:
                if len(selected[role]) >= role_limits[role]:
                    break
                candidate_key = (item['issue_id'], item['rule_uid'])
                if candidate_key in allocated_keys:
                    continue
                uid = item['rule_uid']
                if uid in selected_set:
                    dropped.append({
                        'issue_id': item['issue_id'],
                        'rule_uid': uid,
                        'mapping_role': role,
                        'drop_reason': 'duplicate_uid_already_selected',
                    })
                    allocated_keys.add(candidate_key)
                    continue
                selected[role].append(uid)
                selected_set.add(uid)
                allocated_keys.add(candidate_key)
                ranking_by_issue[item['issue_id']]['per_path_selected_rule_uids'].append(uid)
                quota_allocations.append({
                    'mapping_role': role,
                    'slot_number': len(selected[role]),
                    'allocation_phase': phase,
                    'issue_family': _issue_family(item['issue_id']),
                    'issue_id': item['issue_id'],
                    'winning_rule_uid': uid,
                    'ranking_key': list(item['ranking_features']['key']),
                    'displaced_candidate_uids': [
                        candidate['rule_uid']
                        for candidate in phase_candidates
                        if candidate is not item
                        and candidate['rule_uid'] not in selected_set
                    ],
                })
        for item in candidates:
            uid = item['rule_uid']
            if uid in selected_set or any(
                drop['issue_id'] == item['issue_id'] and drop['rule_uid'] == uid
                for drop in dropped
            ):
                continue
            dropped.append({
                'issue_id': item['issue_id'],
                'rule_uid': uid,
                'mapping_role': role,
                'drop_reason': role + '_global_limit_exceeded',
            })

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
        'displaced_by_targeted_policy': targeted_displacements,
        'quota_allocations': quota_allocations,
    }
