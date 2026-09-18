# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from issue_tree_rule_selector import select_issue_tree_rules
from rule_vector_index import vector_text_hash


def _rule(uid, source_type='法规', platform=None, serial_no=1, vector_text=None):
    rule = {
        'rule_uid': uid,
        'rule_id': uid,
        'source_type': source_type,
        'risk_level': '高',
        'serial_no': serial_no,
        'recall': {'semantic_enabled': bool(vector_text), 'vector_text': vector_text or ''},
        'applies_to': {'platforms': [platform] if platform else []},
    }
    return rule


def _expansion(rows, non_actionable=None):
    result = {
        'direct_rule_uids': [], 'fact_check_rule_uids': [],
        'supporting_rule_uids': [], 'proactive_check_rule_uids': [],
        'exception_rule_uids': [], 'trace': [],
    }
    for issue_id, role, uid in rows:
        result[role + '_rule_uids' if role != 'supporting_basis' else 'supporting_rule_uids'].append(uid)
        result['trace'].append({
            'canonical_rule_uid': uid, 'original_rule_uids': [uid],
            'issue_id': issue_id, 'mapping_type': role,
        })
    for role, uid in non_actionable or []:
        key = {'supporting_basis': 'supporting_rule_uids', 'proactive_check': 'proactive_check_rule_uids',
               'exception': 'exception_rule_uids'}[role]
        result[key].append(uid)
        result['trace'].append({'canonical_rule_uid': uid, 'original_rule_uids': [uid],
                                'issue_id': 'L1.L2.LEAF', 'mapping_type': role})
    return result


class IssueTreeRuleSelectorTests(unittest.TestCase):
    def _select(self, expansion, rules, paths=None, groups=None, scorer=None, **kwargs):
        return select_issue_tree_rules(
            expansion,
            selected_issue_paths=paths or [{'level_3_issue_id': 'L1.L2.LEAF'}],
            rules_by_uid={rule['rule_uid']: rule for rule in rules},
            request={'context': {'platforms': ['抖音']}},
            context_package={'material_text': '测试广告文案', 'context_summary': '测试'},
            legal_issue_groups={'groups': groups or []},
            semantic_scorer=scorer or (lambda rules, request, context, **options: {}),
            **kwargs,
        )

    def test_non_actionable_roles_are_never_promoted(self):
        expansion = _expansion(
            [('L1.L2.LEAF', 'direct', 'D'), ('L1.L2.LEAF', 'fact_check', 'F')],
            [('supporting_basis', 'S'), ('proactive_check', 'P'), ('exception', 'E')],
        )
        result = self._select(expansion, [_rule(uid) for uid in 'DF SPE'.replace(' ', '')])
        self.assertEqual({'D', 'F'}, set(result['selected_actionable_rule_uids']))
        self.assertEqual({'S', 'P', 'E'}, set(result['non_actionable_rule_uids']))

    def test_approved_group_keeps_authority_and_current_platform_representatives(self):
        rows = [('L1.L2.LEAF', 'direct', uid) for uid in ('LAW', 'DEPT', 'DY', 'XHS')]
        rules = [
            _rule('LAW', '法律', serial_no=4), _rule('DEPT', '部门规章', serial_no=1),
            _rule('DY', '平台规则', platform='抖音'), _rule('XHS', '平台规则', platform='小红书'),
        ]
        groups = [{'issue_group_id': 'g1', 'member_rule_uids': ['LAW', 'DEPT', 'DY', 'XHS'],
                   'selection_policy': {'primary_rule_strategy': 'highest_legal_authority',
                                        'platform_rule_strategy': 'current_platform_only',
                                        'max_primary_rules': 1, 'max_platform_rules': 1}}]
        result = self._select(_expansion(rows), rules, groups=groups)
        self.assertEqual(['LAW', 'DY'], result['path_rankings'][0]['representative_rule_uids'])
        self.assertEqual({'DEPT', 'XHS'}, set(result['path_rankings'][0]['collapsed_supporting_rule_uids']))

    def test_semantic_scores_rank_best_scenario_first(self):
        rows = [('L1.L2.LEAF', 'direct', uid) for uid in ('A', 'B')]
        scores = {
            'A': {'semantic_score': 0.41, 'scenario_id': 'a'},
            'B': {'semantic_score': 0.91, 'scenario_id': 'safety_guarantee'},
        }
        result = self._select(_expansion(rows), [_rule('A'), _rule('B')],
                              scorer=lambda rules, request, context, **options: scores)
        ranking = result['path_rankings'][0]['ranked_rules']
        self.assertEqual('B', ranking[0]['rule_uid'])
        self.assertEqual('safety_guarantee', ranking[0]['scenario_id'])

    def test_round_robin_enforces_path_and_global_role_limits(self):
        paths = [{'level_3_issue_id': f'L1.L2.P{i}'} for i in range(4)]
        rows = []
        rules = []
        scores = {}
        for path_index in range(4):
            for rank in range(4):
                uid = f'D{path_index}{rank}'
                rows.append((f'L1.L2.P{path_index}', 'direct', uid))
                rules.append(_rule(uid, serial_no=rank))
                scores[uid] = {'semantic_score': 1 - rank / 10, 'scenario_id': 's'}
        for path_index in range(2):
            uid = f'F{path_index}'
            rows.append((f'L1.L2.P{path_index}', 'fact_check', uid))
            rules.append(_rule(uid))
            scores[uid] = {'semantic_score': 0.95, 'scenario_id': 's'}
        result = self._select(_expansion(rows), rules, paths=paths,
                              scorer=lambda rules, request, context, **options: scores)
        self.assertEqual(6, len(result['selected_direct_rule_uids']))
        self.assertEqual(2, len(result['selected_fact_check_rule_uids']))
        self.assertEqual(8, len(result['selected_actionable_rule_uids']))
        self.assertTrue(all(len(item['per_path_selected_rule_uids']) <= 3
                            for item in result['path_rankings']))
        first_round = set(result['selected_direct_rule_uids'][:4])
        self.assertEqual({'D00', 'D10', 'D20', 'D30'}, first_round)
        reasons = {item['drop_reason'] for item in result['dropped_rules']}
        self.assertIn('per_path_limit_exceeded', reasons)
        self.assertIn('direct_global_limit_exceeded', reasons)

    def test_semantic_failure_uses_deterministic_fallback_and_keeps_limits(self):
        rows = [('L1.L2.LEAF', 'direct', uid) for uid in ('LOW', 'HIGH', 'MID', 'FOUR')]
        rules = [_rule('LOW', '平台规则'), _rule('HIGH', '法律'),
                 _rule('MID', '部门规章'), _rule('FOUR', '规范性文件')]
        def fail(*args, **kwargs):
            raise RuntimeError('provider failed')
        result = self._select(_expansion(rows), rules, scorer=fail)
        self.assertEqual('provider_error', result['semantic_status'])
        self.assertEqual(['HIGH', 'MID', 'FOUR'], result['selected_direct_rule_uids'])
        self.assertLessEqual(len(result['selected_actionable_rule_uids']), 8)


class IssueTreeRuleSelectorCachedVectorTests(unittest.TestCase):
    def test_shadow_scorer_uses_cached_vector_when_main_semantic_recall_is_disabled(self):
        class FakeClient:
            def __init__(self): self.calls = []
            def embed_texts(self, texts):
                self.calls.append(list(texts))
                return [[1.0, 0.0] for _ in texts]

        rule = _rule('DY-HF-003', source_type='平台规则', platform='抖音',
                     vector_text='绝对化效果和安全承诺')
        rule['recall']['semantic_enabled'] = False
        vector_record = {
            'rule_uid': rule['rule_uid'],
            'scenario_id': 'rule_summary',
            'vector_text_hash': vector_text_hash(rule['recall']['vector_text']),
            'embedding': [1.0, 0.0],
        }
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / 'index.json'
            index.write_text(
                json.dumps({'meta': {'model': 'embedding-3'}, 'vectors': [vector_record]}),
                encoding='utf-8',
            )
            client = FakeClient()
            result = select_issue_tree_rules(
                _expansion([('L1.L2.LEAF', 'direct', rule['rule_uid'])]),
                [{'level_3_issue_id': 'L1.L2.LEAF'}], {rule['rule_uid']: rule},
                {'context': {'platforms': ['抖音']}},
                {'material_text': '三天见效，腰酸腿疼全消失'}, {'groups': []},
                embedding_client=client, vector_index_path=index, semantic_backend='zhipu',
            )

        ranked = result['path_rankings'][0]['ranked_rules'][0]
        self.assertFalse(rule['recall']['semantic_enabled'])
        self.assertEqual([['三天见效，腰酸腿疼全消失 抖音']], client.calls)
        self.assertEqual('DY-HF-003', ranked['rule_uid'])
        self.assertEqual(1.0, ranked['semantic_score'])
        self.assertEqual('cached_zhipu', ranked['score_source'])

    def test_default_scorer_uses_one_query_embedding_and_best_cached_scenario(self):
        class FakeClient:
            def __init__(self): self.calls = []
            def embed_texts(self, texts):
                self.calls.append(list(texts))
                return [[1.0, 0.0] for _ in texts]

        rules = [_rule('A', vector_text='alpha'), _rule('B', vector_text='beta')]
        rules[0]['recall']['semantic_scenarios'] = [
            {'scenario_id': 'weak', 'vector_text': 'weak'},
            {'scenario_id': 'best', 'vector_text': 'best'},
        ]
        vectors = []
        for uid, scenario, text, embedding in (
            ('A', 'weak', 'weak', [0.0, 1.0]), ('A', 'best', 'best', [1.0, 0.0]),
            ('B', 'rule_summary', 'beta', [0.6, 0.8]),
        ):
            vectors.append({'rule_uid': uid, 'scenario_id': scenario,
                            'vector_text_hash': vector_text_hash(text), 'embedding': embedding})
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / 'index.json'
            index.write_text(json.dumps({'meta': {'model': 'embedding-3'}, 'vectors': vectors}), encoding='utf-8')
            client = FakeClient()
            result = select_issue_tree_rules(
                _expansion([('L1.L2.LEAF', 'direct', 'A'), ('L1.L2.LEAF', 'direct', 'B')]),
                [{'level_3_issue_id': 'L1.L2.LEAF'}], {r['rule_uid']: r for r in rules},
                {'context': {}}, {'material_text': 'query'}, {'groups': []},
                embedding_client=client, vector_index_path=index, semantic_backend='zhipu',
            )
        self.assertEqual([['query']], client.calls)
        first = result['path_rankings'][0]['ranked_rules'][0]
        self.assertEqual('A', first['rule_uid'])
        self.assertEqual('best', first['scenario_id'])


if __name__ == '__main__':
    unittest.main()
