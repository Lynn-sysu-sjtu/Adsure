# -*- coding: utf-8 -*-
'''Temporary, opt-in ranking policies for issue-tree shadow evaluation.'''

from dataclasses import dataclass
import os
import re

TARGETED_POLICY_ENV = 'ADSURE_ISSUE_TREE_TARGETED_POLICY_ENABLED'


@dataclass(frozen=True)
class TargetedPolicy:
    rule_uid: str
    policy_id: str
    allowed_issue_ids: tuple
    evidence_patterns: tuple
    reason: str
    allowed_industries: tuple = ()
    allowed_platforms: tuple = ()


TARGETED_POLICIES = (
    TargetedPolicy(
        'RUID-3c268b6928ff21d7',
        'shadow-target-dy-hf-003-v1',
        ('CLAIM_EXPRESSION.GUARANTEE_COMMITMENT.EFFECT_GUARANTEE_COMMITMENT',),
        (
            r'\d+\s*(?:天|日|小时|分钟)[^。；，,]{0,12}(?:见效|有效|改善|消失)',
            r'(?:百分之百|100\s*%)[^。；，,]{0,8}(?:有效|见效|安全)',
            r'(?:保证|确保|承诺)[^。；，,]{0,10}(?:有效|见效|效果|安全)',
            r'(?:安全无副作用|无副作用|零风险|无毒副作用|无依赖)',
            r'(?:全消失|立竿见影|立即见效|马上见效)',
        ),
        'health-food Douyin material contains explicit effect or safety guarantee evidence',
        ('保健食品',),
        ('抖音',),
    ),
    TargetedPolicy(
        'RUID-d79610014e487328',
        'shadow-target-hf-005-v1',
        ('ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY',),
        (
            r'(?:科研单位|科研机构|学术机构|研究机构|行业协会)',
            r'(?:专家|学者|医师|医生|药师|营养师|专业人士)',
        ),
        'material contains expert or research-institution recommendation evidence',
    ),
)
_POLICY_BY_UID = {policy.rule_uid: policy for policy in TARGETED_POLICIES}


def targeted_policy_enabled(value=None):
    if value is not None:
        return bool(value)
    return str(os.getenv(TARGETED_POLICY_ENV) or '').strip().lower() in {
        '1', 'true', 'yes', 'on', 'enabled',
    }


def _as_values(value):
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value or '').strip()
    return (text,) if text else ()


def _material_text(request, context_package):
    material = request.get('material') or {}
    parts = (
        context_package.get('material_text'),
        material.get('content'),
        context_package.get('supplemental_background'),
        material.get('supplemental_background'),
    )
    return ' '.join(str(part) for part in parts if part)


def match_targeted_policy(rule_uid, issue_id, request, context_package, *, enabled=None):
    '''Return audit metadata; never changes candidate eligibility.'''
    disabled = {
        'targeted_policy_id': None,
        'targeted_priority_applied': False,
        'targeted_priority_reason': None,
    }
    if not targeted_policy_enabled(enabled):
        return disabled
    policy = _POLICY_BY_UID.get(str(rule_uid or ''))
    if policy is None:
        return disabled
    result = dict(disabled, targeted_policy_id=policy.policy_id)
    if issue_id not in policy.allowed_issue_ids:
        return result
    context = request.get('context') or {}
    industries = _as_values(context.get('industry'))
    platforms = _as_values(context.get('platforms'))
    if policy.allowed_industries and not set(industries).intersection(policy.allowed_industries):
        return result
    if policy.allowed_platforms and not set(platforms).intersection(policy.allowed_platforms):
        return result
    text = _material_text(request, context_package)
    if not any(re.search(pattern, text, flags=re.IGNORECASE)
               for pattern in policy.evidence_patterns):
        return result
    return {
        'targeted_policy_id': policy.policy_id,
        'targeted_priority_applied': True,
        'targeted_priority_reason': policy.reason,
    }
