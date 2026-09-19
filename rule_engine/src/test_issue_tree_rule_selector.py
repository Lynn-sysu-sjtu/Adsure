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
    def _select(self, expansion, rules, paths=None, groups=None, scorer=None,
                request=None, context_package=None, **kwargs):
        return select_issue_tree_rules(
            expansion,
            selected_issue_paths=paths or [{'level_3_issue_id': 'L1.L2.LEAF'}],
            rules_by_uid={rule['rule_uid']: rule for rule in rules},
            request=request or {'context': {'platforms': ['抖音']}},
            context_package=context_package or {
                'material_text': '测试广告文案', 'context_summary': '测试'
            },
            legal_issue_groups={'groups': groups or []},
            semantic_scorer=scorer or (lambda rules, request, context, **options: {}),
            **kwargs,
        )

    def test_targeted_policy_promotes_douyin_health_effect_rule_into_path_top_three(self):
        issue_id = 'CLAIM_EXPRESSION.GUARANTEE_COMMITMENT.EFFECT_GUARANTEE_COMMITMENT'
        target_uid = 'RUID-3c268b6928ff21d7'
        other_uids = ['A', 'B', 'C']
        rows = [(issue_id, 'direct', uid) for uid in other_uids + [target_uid]]
        scores = {
            'A': {'semantic_score': 0.90},
            'B': {'semantic_score': 0.80},
            'C': {'semantic_score': 0.70},
            target_uid: {'semantic_score': 0.10},
        }
        result = self._select(
            _expansion(rows),
            [_rule(uid, platform='抖音') for uid in other_uids + [target_uid]],
            paths=[{'level_3_issue_id': issue_id}],
            scorer=lambda rules, request, context, **options: scores,
            request={'context': {'industry': '保健食品', 'platforms': ['抖音']}},
            context_package={
                'material_text': (
                    '一吃就精神，三天排出体内毒素，腰酸腿疼全消失，'
                    '效果立竿见影，老人必备。'
                )
            },
            targeted_policy_enabled=True,
        )

        ranking = result['path_rankings'][0]
        self.assertIn(target_uid, ranking['per_path_selected_rule_uids'])
        target = next(item for item in ranking['ranked_rules'] if item['rule_uid'] == target_uid)
        self.assertEqual('shadow-target-dy-hf-003-v1', target['targeted_policy_id'])
        self.assertTrue(target['targeted_priority_applied'])
        self.assertEqual(4, target['original_rank'])
        self.assertEqual(1, target['adjusted_rank'])
        self.assertEqual('C', result['displaced_by_targeted_policy'][0]['rule_uid'])

    def test_targeted_policy_does_not_promote_effect_rule_outside_exact_scope(self):
        issue_id = 'CLAIM_EXPRESSION.GUARANTEE_COMMITMENT.EFFECT_GUARANTEE_COMMITMENT'
        target_uid = 'RUID-3c268b6928ff21d7'
        rules = [_rule(uid) for uid in ('A', 'B', 'C', target_uid)]
        scores = {uid: {'semantic_score': score} for uid, score in
                  zip(('A', 'B', 'C', target_uid), (0.9, 0.8, 0.7, 0.1))}
        variants = [
            ({'context': {'industry': '保健食品', 'platforms': ['小红书']}},
             {'material_text': '三天见效，安全无副作用'}, issue_id, True),
            ({'context': {'industry': '保健食品', 'platforms': ['抖音']}},
             {'material_text': '日常营养补充'}, issue_id, True),
            ({'context': {'industry': '保健食品', 'platforms': ['抖音']}},
             {'material_text': '三天见效，安全无副作用'}, 'OTHER.PATH.LEAF', True),
            ({'context': {'industry': '保健食品', 'platforms': ['抖音']}},
             {'material_text': '三天见效，安全无副作用'}, issue_id, False),
        ]
        for request, context_package, selected_issue, enabled in variants:
            with self.subTest(selected_issue=selected_issue, enabled=enabled,
                              platform=request['context']['platforms'][0],
                              material=context_package['material_text']):
                variant_rows = [
                    (selected_issue, 'direct', uid) for uid in ('A', 'B', 'C', target_uid)
                ]
                result = self._select(
                    _expansion(variant_rows), rules,
                    paths=[{'level_3_issue_id': selected_issue}],
                    scorer=lambda rules, request, context, **options: scores,
                    request=request, context_package=context_package,
                    targeted_policy_enabled=enabled,
                )
                ranking = result['path_rankings'][0]
                self.assertNotIn(target_uid, ranking['per_path_selected_rule_uids'])
                target = next(
                    item for item in ranking['ranked_rules'] if item['rule_uid'] == target_uid
                )
                self.assertFalse(target['targeted_priority_applied'])

    def test_targeted_policy_gives_hf_005_a_global_direct_slot_for_endorsement_evidence(self):
        issue_id = 'ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY'
        target_uid = 'RUID-d79610014e487328'
        rows = [(issue_id, 'direct', uid) for uid in ('A', 'B', target_uid)]
        scores = {'A': {'semantic_score': 0.9}, 'B': {'semantic_score': 0.8},
                  target_uid: {'semantic_score': 0.1}}
        result = self._select(
            _expansion(rows), [_rule(uid) for uid in ('A', 'B', target_uid)],
            paths=[{'level_3_issue_id': issue_id}],
            scorer=lambda rules, request, context, **options: scores,
            request={'context': {'industry': '保健食品', 'platforms': ['抖音']}},
            context_package={'material_text': '国家级科研机构专家联名推荐并作功效证明'},
            targeted_policy_enabled=True,
            direct_limit=1,
        )

        self.assertEqual([target_uid], result['selected_direct_rule_uids'])
        ranked = result['path_rankings'][0]['ranked_rules'][0]
        self.assertEqual(target_uid, ranked['rule_uid'])
        self.assertEqual('shadow-target-hf-005-v1', ranked['targeted_policy_id'])

    def test_targeted_policy_keeps_limits_and_non_actionable_roles_isolated(self):
        issue_id = 'ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY'
        target_uid = 'RUID-d79610014e487328'
        expansion = _expansion(
            [(issue_id, 'direct', target_uid), (issue_id, 'direct', 'D2'),
             (issue_id, 'fact_check', 'F1')],
            [('supporting_basis', 'S'), ('proactive_check', 'P'), ('exception', 'E')],
        )
        result = self._select(
            expansion, [_rule(uid) for uid in (target_uid, 'D2', 'F1', 'S', 'P', 'E')],
            paths=[{'level_3_issue_id': issue_id}],
            request={'context': {'industry': '保健食品', 'platforms': ['抖音']}},
            context_package={'material_text': '专家和科研机构联名推荐证明'},
            targeted_policy_enabled=True,
            per_path_limit=1, direct_limit=1, fact_check_limit=1,
        )

        self.assertLessEqual(len(result['selected_actionable_rule_uids']), 2)
        self.assertLessEqual(len(result['path_rankings'][0]['per_path_selected_rule_uids']), 1)
        self.assertEqual({'S', 'P', 'E'}, set(result['non_actionable_rule_uids']))
        self.assertTrue({'S', 'P', 'E'}.isdisjoint(result['selected_actionable_rule_uids']))

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

    def test_exact_applicability_ranks_specific_rule_before_higher_semantic_score(self):
        specific = _rule('SPECIFIC', platform='抖音')
        specific['applies_to'].update({
            'industries': ['保健食品'],
            'product_categories': ['滋补保健'],
            'material_types': ['直播话术'],
            'scenarios': ['达人直播'],
        })
        generic = _rule('GENERIC')
        scores = {
            'SPECIFIC': {'semantic_score': 0.20},
            'GENERIC': {'semantic_score': 0.95},
        }
        result = self._select(
            _expansion([
                ('L1.L2.LEAF', 'direct', 'GENERIC'),
                ('L1.L2.LEAF', 'direct', 'SPECIFIC'),
            ]),
            [generic, specific],
            scorer=lambda rules, request, context, **options: scores,
            request={'context': {
                'industry': '保健食品',
                'platforms': ['抖音'],
                'product_category': '滋补保健',
                'material_type': '直播话术',
                'scenario': '达人直播',
            }},
        )
        first = result['path_rankings'][0]['ranked_rules'][0]
        self.assertEqual('SPECIFIC', first['rule_uid'])
        self.assertEqual(5, first['applicability_match_count'])
        self.assertEqual(
            {
                'industry': True,
                'platform': True,
                'product_category': True,
                'material_type': True,
                'scenario': True,
            },
            first['applicability_matches'],
        )

    def test_absolute_expression_dimension_adds_general_evidence_patterns(self):
        rule = _rule('ABSOLUTE')
        rule['dimension'] = '绝对化用语'
        rule['recall']['tags'] = ['效果保证', '绝对化用语']
        result = self._select(
            _expansion([('L1.L2.LEAF', 'direct', 'ABSOLUTE')]),
            [rule],
            context_package={'material_text': '三天后腰腿疼全消失，效果立竿见影'},
        )
        ranked = result['path_rankings'][0]['ranked_rules'][0]
        self.assertTrue(ranked['evidence_trigger_match'])
        self.assertTrue(any(
            item.startswith('derived:absolute_expression:')
            for item in ranked['matched_evidence_triggers']
        ))

    def test_product_category_suffix_is_normalized_for_applicability(self):
        rule = _rule('CATEGORY')
        rule['applies_to']['product_categories'] = ['滋补保健品']
        result = self._select(
            _expansion([('L1.L2.LEAF', 'direct', 'CATEGORY')]),
            [rule],
            request={'context': {'product_category': '滋补保健'}},
        )
        ranked = result['path_rankings'][0]['ranked_rules'][0]
        self.assertTrue(ranked['applicability_matches']['product_category'])
        self.assertEqual(1, ranked['applicability_match_count'])

    def test_product_category_hierarchy_matches_reviewed_food_and_cosmetic_children(self):
        variants = (
            ('食品', '进口保健食品'),
            ('保健食品', '进口保健食品'),
            ('美妆', '唇部护理'),
            ('普通化妆品', '护肤'),
        )
        for declared, actual in variants:
            with self.subTest(declared=declared, actual=actual):
                rule = _rule('CATEGORY')
                rule['applies_to']['product_categories'] = [declared]
                result = self._select(
                    _expansion([('L1.L2.LEAF', 'direct', 'CATEGORY')]),
                    [rule],
                    request={'context': {'product_category': actual}},
                )
                ranked = result['path_rankings'][0]['ranked_rules'][0]
                self.assertTrue(ranked['applicability_matches']['product_category'])

    def test_material_type_aliases_match_within_the_same_media_family(self):
        variants = (
            ('短视频脚本中的文字内容', '短视频脚本'),
            ('详情页文字', '详情页'),
            ('图文文案', '图文'),
            ('Banner文字', 'Banner'),
        )
        for declared, actual in variants:
            with self.subTest(declared=declared, actual=actual):
                rule = _rule('MATERIAL')
                rule['applies_to']['material_types'] = [declared]
                result = self._select(
                    _expansion([('L1.L2.LEAF', 'direct', 'MATERIAL')]),
                    [rule],
                    request={'context': {'material_type': actual}},
                )
                ranked = result['path_rankings'][0]['ranked_rules'][0]
                self.assertTrue(ranked['applicability_matches']['material_type'])

    def test_rule_owned_combination_regex_is_stronger_than_literal_hit(self):
        literal = _rule('LITERAL')
        literal['detection'] = {
            'keyword_signals': {'hit_terms': ['100%'], 'regex': []}
        }
        combination = _rule('COMBINATION')
        combination['detection'] = {
            'keyword_signals': {
                'hit_terms': [],
                'regex': [r'(?:100\s*%|百分百).{0,12}(?:无风险|没有任何风险|安全|无副作用)'],
            }
        }
        scores = {
            'LITERAL': {'semantic_score': 0.95},
            'COMBINATION': {'semantic_score': 0.10},
        }
        result = self._select(
            _expansion([
                ('L1.L2.LEAF', 'direct', 'LITERAL'),
                ('L1.L2.LEAF', 'direct', 'COMBINATION'),
            ]),
            [literal, combination],
            scorer=lambda rules, request, context, **options: scores,
            context_package={'material_text': '宝宝舔了也能吃，100%没有任何风险'},
        )
        first = result['path_rankings'][0]['ranked_rules'][0]
        self.assertEqual('COMBINATION', first['rule_uid'])
        self.assertEqual(2, first['evidence_strength'])
        self.assertTrue(first['matched_evidence_regexes'])

    def test_evidence_match_beats_more_specific_rule_without_evidence(self):
        specific = _rule('SPECIFIC', platform='抖音')
        specific['applies_to'].update({
            'industries': ['保健食品'],
            'material_types': ['直播话术'],
        })
        evidence = _rule('EVIDENCE')
        evidence['applies_to'].update({
            'industries': ['保健食品'],
            'material_types': ['直播话术'],
        })
        evidence['detection'] = {
            'keyword_signals': {'hit_terms': ['专家推荐'], 'regex': []}
        }
        scores = {
            'SPECIFIC': {'semantic_score': 0.95},
            'EVIDENCE': {'semantic_score': 0.20},
        }
        result = self._select(
            _expansion([
                ('L1.L2.LEAF', 'direct', 'SPECIFIC'),
                ('L1.L2.LEAF', 'direct', 'EVIDENCE'),
            ]),
            [specific, evidence],
            scorer=lambda rules, request, context, **options: scores,
            request={'context': {
                'industry': '保健食品',
                'platforms': ['抖音'],
                'material_type': '直播话术',
            }},
            context_package={'material_text': '国家级专家推荐该产品'},
        )
        self.assertEqual(
            'EVIDENCE',
            result['path_rankings'][0]['ranked_rules'][0]['rule_uid'],
        )

    def test_structured_evidence_trigger_ranks_before_higher_semantic_score(self):
        evidence = _rule('EVIDENCE')
        evidence['detection'] = {
            'keyword_signals': {
                'hit_terms': ['立竿见影'],
                'regex': [r'三天.*全消失'],
            }
        }
        semantic = _rule('SEMANTIC')
        scores = {
            'EVIDENCE': {'semantic_score': 0.20},
            'SEMANTIC': {'semantic_score': 0.95},
        }
        result = self._select(
            _expansion([
                ('L1.L2.LEAF', 'direct', 'SEMANTIC'),
                ('L1.L2.LEAF', 'direct', 'EVIDENCE'),
            ]),
            [semantic, evidence],
            scorer=lambda rules, request, context, **options: scores,
            context_package={'material_text': '三天排出毒素，腰腿疼全消失，效果立竿见影'},
        )
        first = result['path_rankings'][0]['ranked_rules'][0]
        self.assertEqual('EVIDENCE', first['rule_uid'])
        self.assertTrue(first['evidence_trigger_match'])
        self.assertIn('立竿见影', first['matched_evidence_triggers'])
        self.assertIn(r'三天.*全消失', first['matched_evidence_triggers'])

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

    def test_global_quota_covers_distinct_issue_families_before_extra_slots(self):
        paths = [
            {'level_3_issue_id': 'FAMILY_A.P1.LEAF'},
            {'level_3_issue_id': 'FAMILY_A.P2.LEAF'},
            {'level_3_issue_id': 'FAMILY_B.P1.LEAF'},
        ]
        rows = [
            ('FAMILY_A.P1.LEAF', 'direct', 'A1'),
            ('FAMILY_A.P2.LEAF', 'direct', 'A2'),
            ('FAMILY_B.P1.LEAF', 'direct', 'B1'),
        ]
        scores = {
            'A1': {'semantic_score': 0.99},
            'A2': {'semantic_score': 0.98},
            'B1': {'semantic_score': 0.20},
        }
        result = self._select(
            _expansion(rows),
            [_rule(uid) for uid in ('A1', 'A2', 'B1')],
            paths=paths,
            scorer=lambda rules, request, context, **options: scores,
            direct_limit=2,
        )

        self.assertEqual({'A1', 'B1'}, set(result['selected_direct_rule_uids']))
        allocations = result['quota_allocations']
        self.assertEqual(['family_coverage', 'family_coverage'], [
            item['allocation_phase'] for item in allocations
        ])
        self.assertEqual([1, 2], [item['slot_number'] for item in allocations])
        self.assertEqual({'A1', 'B1'}, {
            item['winning_rule_uid'] for item in allocations
        })
        self.assertTrue(any(
            item['rule_uid'] == 'A2' and item['drop_reason'] == 'direct_global_limit_exceeded'
            for item in result['dropped_rules']
        ))

    def test_global_quota_uses_ranked_competition_for_remaining_slots(self):
        paths = [
            {'level_3_issue_id': 'FAMILY_A.P1.LEAF'},
            {'level_3_issue_id': 'FAMILY_B.P1.LEAF'},
        ]
        rows = [
            ('FAMILY_A.P1.LEAF', 'direct', 'A1'),
            ('FAMILY_A.P1.LEAF', 'direct', 'A2'),
            ('FAMILY_B.P1.LEAF', 'direct', 'B1'),
        ]
        scores = {
            'A1': {'semantic_score': 0.99},
            'A2': {'semantic_score': 0.80},
            'B1': {'semantic_score': 0.20},
        }
        result = self._select(
            _expansion(rows),
            [_rule(uid) for uid in ('A1', 'A2', 'B1')],
            paths=paths,
            scorer=lambda rules, request, context, **options: scores,
            direct_limit=3,
        )
        self.assertEqual({'A1', 'A2', 'B1'}, set(result['selected_direct_rule_uids']))
        self.assertEqual(
            ['family_coverage', 'family_coverage', 'global_competition'],
            [item['allocation_phase'] for item in result['quota_allocations']],
        )
        self.assertEqual('A2', result['quota_allocations'][2]['winning_rule_uid'])

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
