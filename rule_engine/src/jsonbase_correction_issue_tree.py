import json
import hashlib
from collections import defaultdict
from pathlib import Path
from copy import deepcopy
from jsonbase_correction_migration import inventory_rules, load_manifest, _atomic_write_json


def correct_issue_assets(result, project_root):
    assets = project_root / 'assets'
    contract = json.loads((assets / 'issue_redirects_20260917.json').read_text(encoding='utf-8'))
    manifest = load_manifest(assets / 'jsonbase_correction_manifest_20260917.json')
    entries = {e['rule_uid']: e for e in manifest['rules']}
    rules = inventory_rules(project_root / 'jsonbase')
    redirects = contract['redirects']
    targets = contract['rule_issue_targets']
    uid_redirects = {
        e['rule_uid']: e['canonical_rule_uid']
        for e in manifest['rules'] if e['action'] == 'duplicate_source'
    }
    nodes = [n for n in result['taxonomy']['nodes'] if n['issue_id'] not in redirects]
    node_ids = {n['issue_id'] for n in nodes}
    if not set(redirects.values()) <= node_ids:
        raise ValueError('Dangling issue redirect')
    for node in nodes:
        if node.get('parent_issue_id') in redirects:
            node['parent_issue_id'] = redirects[node['parent_issue_id']]
        if node['issue_id'] in contract.get('node_names', {}):
            node['name'] = contract['node_names'][node['issue_id']]
    active, excluded, seen = [], [], set()
    all_rows = result['mappings']['mappings'] + result['mappings']['excluded_mappings']
    for raw in all_rows:
        item = deepcopy(raw)
        original_uid = item['rule_uid']
        entry = entries.get(original_uid) or {}
        if entry.get('action') == 'side_path':
            item['exclusion_role'] = 'workflow_reference'
            item['exclusion_reason'] = '经批准归入流程、准入或资料核验旁路，不参与普通文案违规召回'
            excluded.append(item)
            continue
        uid = uid_redirects.get(original_uid, original_uid)
        item['rule_uid'] = uid
        entry = entries.get(uid) or {}
        if 'exclusion_role' in item and uid not in targets:
            excluded.append(item)
            continue
        item.pop('exclusion_role', None)
        item.pop('exclusion_reason', None)
        changes = entry.get('field_changes') or {}
        role = changes.get('review_role', item.get('mapping_type', 'direct'))
        if role == 'legal_issue':
            role = 'direct'
        destinations = targets.get(uid, [redirects.get(item['issue_id'], item['issue_id'])])
        if uid in rules:
            current = rules[uid][0]['rule']
            item['rule_title'] = current.get('title', item['rule_title'])
            item['original_text'] = (entry.get('source_evidence') or {}).get(
                'restored_original_text',
                (current.get('legal_basis') or [{}])[0].get('text', item['original_text']),
            )
        for target in destinations:
            target = redirects.get(target, target)
            if target not in node_ids:
                raise ValueError(f'Dangling corrected mapping: {uid} -> {target}')
            mapped = deepcopy(item)
            mapped['issue_id'] = target
            mapped['mapping_type'] = role
            special_issue = 'EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.COSMETIC_SPECIAL_EFFICACY_CLAIM_BY_ORDINARY_PRODUCT'
            if item['issue_id'] == special_issue or special_issue in destinations:
                mapped['scope_condition'] = 'ordinary_product_special_efficacy'
            if uid == 'RUID-fba2b7c4e349d1ee':
                mapped['mapping_type'] = 'fact_check' if target.startswith('EFFICACY_PERFORMANCE.') else 'proactive_check'
            key = (uid, target, mapped['mapping_type'])
            if key not in seen:
                seen.add(key)
                active.append(mapped)
    result['taxonomy']['nodes'] = nodes
    result['taxonomy']['migration_version'] = manifest['manifest_version']
    result['mappings']['mappings'] = active
    result['mappings']['excluded_mappings'] = excluded
    result['mappings']['uid_redirects'] = uid_redirects
    resolutions = {
        old: {'action': 'merge', 'targets': [target]}
        for old, target in redirects.items()
    }
    resolutions['DISCLOSURE_WARNING.CONDITIONS_LIMITS.COSMETIC_EFFICACY_EXEMPTION_SCOPE'] = {
        'action': 'applicability_condition',
        'targets': ['EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.COSMETIC_EFFICACY_CLAIM_NONCOMPLIANT'],
    }
    resolutions['DISCLOSURE_WARNING.STATUTORY_WARNING.STATUTORY_DISCLOSURE_NOT_PROMINENT_OR_CLEAR'] = {
        'action': 'distribute_to_specific_obligations',
        'targets': sorted(n['issue_id'] for n in nodes if n.get('parent_issue_id') == 'DISCLOSURE_WARNING.STATUTORY_WARNING'),
    }
    resolutions['WORKFLOW_DUTY.PRE_REVIEW'] = {
        'action': 'distribute_to_existing_directories',
        'targets': ['WORKFLOW_DUTY.PLATFORM_ALGORITHM', 'SCOPE_ACCESS.AD_REVIEW_ACCESS.PRE_REVIEW_APPROVAL_AND_CONTENT_CONSISTENCY'],
    }
    for resolution in resolutions.values():
        if not set(resolution['targets']) <= node_ids:
            raise ValueError('Dangling historical issue resolution')
    result['taxonomy']['issue_resolutions'] = resolutions
    inputs = list((assets / 'all_primary_issue_review_draft_v0.1').rglob('review_assets.json'))
    inputs += list((project_root / 'jsonbase').rglob('*.json'))
    inputs += [assets / name for name in (
        'endorsement_issue_taxonomy_draft_v0.3.json',
        'endorsement_candidate_clusters_draft_v0.3.json',
        'endorsement_rule_mapping_draft_v0.3.json',
        'endorsement_proactive_checklist_draft_v0.3.json',
        'jsonbase_correction_manifest_20260917.json',
        'rule_correction_overrides_20260917.json',
        'source_repair_evidence_20260917.json',
        'issue_redirects_20260917.json',
    )]
    hashes = {
        path.relative_to(project_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(inputs)
    }
    result['taxonomy']['source_hashes'] = hashes
    result['mappings']['source_hashes'] = hashes
    return result


def write_final_assets(result, base_dir):
    '''Export canonical JSONs preserving the existing v0.3 consumer shape.'''
    base_dir = Path(base_dir)
    assets = base_dir / 'assets'
    report_dir = base_dir / 'reports' / 'approved_issue_tree_v03'
    assets.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    tax_path = assets / 'legal_issue_taxonomy_draft_v0.3.json'
    map_path = assets / 'rule_issue_mapping_draft_v0.3.json'
    old_tax = json.loads(tax_path.read_text(encoding='utf-8')) if tax_path.exists() else {}
    old_map = json.loads(map_path.read_text(encoding='utf-8')) if map_path.exists() else {}
    old_nodes = {n['issue_id']: n for n in old_tax.get('issues', [])}
    issues = []
    for node in result['taxonomy']['nodes']:
        normalized = deepcopy(old_nodes.get(node['issue_id'], {}))
        normalized.update(deepcopy(node))
        normalized.setdefault('aliases', [])
        normalized.setdefault('applicability', {'industries': [], 'platforms': []})
        normalized['candidate_rule_uids'] = sorted({
            row['rule_uid'] for row in result['mappings']['mappings'] if row['issue_id'] == node['issue_id']
        })
        issues.append(normalized)
    by_uid = defaultdict(list)
    for row in result['mappings']['mappings']:
        by_uid[row['rule_uid']].append(row)
    old_rows = {r['rule_uid']: r for r in old_map.get('mappings', [])}
    mappings = []
    for uid, rows in sorted(by_uid.items()):
        normalized = deepcopy(old_rows.get(uid, {}))
        destinations = list(dict.fromkeys(row['issue_id'] for row in rows))
        normalized.update(
            rule_uid=uid,
            primary_issue_id=destinations[0],
            secondary_issue_ids=destinations[1:],
            issue_roles=[{
                'issue_id': row['issue_id'],
                'mapping_type': row['mapping_type'],
                'scope_condition': row.get('scope_condition'),
            } for row in rows],
        )
        mappings.append(normalized)
    metadata = {
        'schema_version': '0.3',
        'asset_status': 'approved',
        'migration_version': result['taxonomy']['migration_version'],
        'source_hashes': result['taxonomy']['source_hashes'],
    }
    taxonomy = {
        **old_tax, **metadata, 'issues': issues,
        'issue_resolutions': result['taxonomy']['issue_resolutions'],
    }
    mapping_asset = {
        **old_map, **metadata, 'mappings': mappings,
        'excluded_mappings': result['mappings']['excluded_mappings'],
        'uid_redirects': result['mappings']['uid_redirects'],
    }
    paths = {
        'taxonomy': tax_path, 'mapping': map_path,
        'review_taxonomy': report_dir / 'approved_issue_taxonomy_v0.2.json',
        'review_mapping': report_dir / 'approved_rule_issue_mapping_v0.2.json',
    }
    for key, payload in (
        ('taxonomy', taxonomy), ('mapping', mapping_asset),
        ('review_taxonomy', result['taxonomy']), ('review_mapping', result['mappings']),
    ):
        _atomic_write_json(paths[key], payload)
    return paths
