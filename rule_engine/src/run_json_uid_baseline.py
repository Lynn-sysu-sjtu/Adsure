# -*- coding: utf-8 -*-
"""Score explicit UID expectations independently of the legacy rule_id score."""

import argparse
import json
from collections import Counter
from pathlib import Path

from run_three_dataset_baseline import _load_json_dataset, _sha256, run_baseline, save_report


BASE = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BASE / 'reports' / 'json_test_uid_migration_20260917'
DEFAULT_OUTPUT = BASE / 'test_reports' / 'three_dataset_baseline'
SOURCES = ('20260906保健食品测试样例集.json', '20260908美妆测试样例集.json')


def score_uid_results(results):
    counts = Counter()
    rows = []
    for item in results:
        expected = item['expected']
        required = set(expected.get('must_recall_rule_uids') or [])
        forbidden = set(expected.get('must_not_recall_rule_uids') or [])
        diagnostics = item.get('diagnostics') or {}
        response = item.get('actual_response') or {}
        matched = (response.get('data') or {}).get('matched_rules') or []
        candidate = set(diagnostics.get('candidate_rule_uids') or [])
        final = {rule['rule_uid'] for rule in matched if rule.get('rule_uid')}
        bindings = expected.get('expected_rule_bindings') or []
        counts.update(item['resolution_status'] + '_expectation_count' for item in bindings)
        if response.get('code') == 0:
            counts['successful_responses'] += 1
        if required:
            counts['positive_case_denominator'] += 1
            counts['required_uid_denominator'] += len(required)
            counts['candidate_uid_hits'] += len(required & candidate)
            counts['final_uid_hits'] += len(required & final)
            counts['candidate_all_required_hit'] += required.issubset(candidate)
            counts['final_all_required_hit'] += required.issubset(final)
        elif expected.get('must_recall_rule_ids'):
            counts['unscorable_positive_cases'] += 1
        counts['forbidden_uid_denominator'] += len(forbidden)
        counts['forbidden_candidate_false_hits'] += len(forbidden & candidate)
        counts['forbidden_final_false_hits'] += len(forbidden & final)
        rows.append({
            'case_id': item['case_id'],
            'scoring_status': ('scorable_positive' if required else
                               'unscorable_no_uid_target' if expected.get('must_recall_rule_ids') else
                               'negative_control'),
            'required_rule_uids': sorted(required),
            'missing_candidate_rule_uids': sorted(required - candidate),
            'missing_final_rule_uids': sorted(required - final),
            'forbidden_candidate_rule_uids': sorted(forbidden & candidate),
            'forbidden_final_rule_uids': sorted(forbidden & final),
            'candidate_rule_uids': sorted(candidate),
            'final_rule_uids': sorted(final),
            'legacy_missing_candidate_rule_ids': item.get('comparison', {}).get('missing_required_candidate_rule_ids', []),
        })
    return {'summary': {'case_count': len(results), **dict(counts)}, 'cases': rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset-dir', default=str(DEFAULT_DATASET))
    parser.add_argument('--output-dir', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--llm-backend', choices=['mock', 'deepseek'], default='mock')
    parser.add_argument('--semantic-backend', choices=['local', 'zhipu'], default='local')
    args = parser.parse_args()
    dataset_dir = Path(args.dataset_dir)
    cases = []
    sources = []
    for name, label in zip(SOURCES, ('保健食品', '美妆')):
        path = dataset_dir / name
        cases.extend(_load_json_dataset(path, label))
        sources.append({'path': str(path), 'file': name, 'sha256': _sha256(path)})
    if len(cases) != 20:
        raise ValueError(f'expected 20 cases, got {len(cases)}')
    report = run_baseline(cases, sources, f'uid20_{args.llm_backend}_{args.semantic_backend}',
                          args.llm_backend, args.semantic_backend)
    json_path, csv_path = save_report(report, args.output_dir)
    uid_score = score_uid_results(report['cases'])
    uid_score['baseline_json'] = str(json_path)
    uid_score['baseline_csv'] = str(csv_path)
    uid_score['sources'] = sources
    score_path = json_path.with_name(json_path.stem + '_uid_score.json')
    score_path.write_text(json.dumps(uid_score, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'summary': uid_score['summary'], 'score_path': str(score_path)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
