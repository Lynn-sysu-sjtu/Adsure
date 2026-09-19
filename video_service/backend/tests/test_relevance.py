# -*- coding: utf-8 -*-
"""相关性标注测试。

标题全部取自实际抓回的案例 —— 这个判定要面对的就是这些。
"""

from __future__ import annotations

import pytest

from app.crawler.relevance import Relevance, ad_relevance, tag_case


# ══════════════════════════════════════════════════════════════
#  本项目的正题
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("title", [
    "江苏省徐州市邳州市市场监管局查处徐州多赢记文化传媒有限公司违法广告案",
    "湖北省宜昌市西陵区远浦帆归百货店虚假宣传案",
    "河南省商丘市虞城县市场监管局查处王某帮助其他经营者进行虚假宣传案",
    "市场监管总局公布五起民生领域私域直播虚假宣传典型案例",
])
def test_ad_cases_are_recognised(title):
    assert ad_relevance(title) is Relevance.AD


def test_ad_wins_even_when_the_product_is_also_substandard():
    """「在广告中宣称不含防腐剂（实为不合格产品）」是广告案，不是质量案。

    违法性在「广告里怎么说」，不在产品本身 —— 判定顺序反过来就会漏掉这类，
    而它恰恰是本项目最典型的场景。
    """
    text = "当事人在广告中宣称该产品不含防腐剂，经检验为不合格产品，属虚假宣传。"
    assert ad_relevance(text) is Relevance.AD


# ══════════════════════════════════════════════════════════════
#  别的监管条线（混编通报带进来的）
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("title", [
    "山东省聊城市市场监管局查处高唐县运发加油站为加油机增加作弊装置案",
    "山东省青岛市市场监管局查处市北区张先杰水产品商店使用以欺骗消费者为目的的电子秤案",
    "新疆…市场监管局查处新疆蓝润能源有限公司破坏计量器具准确度案",
    "河南省许昌市长葛市市场监管局查处长葛市胤同金属制品厂生产不合格家用燃气防爆管案",
    "四川省自贡市荣县市场监管局查处张某昭、李某兵侵犯注册商标专用权案",
    "江苏省无锡市江阴市市场监管局查处江阴猛想星辉游泳健身有限公司违反合同条款案",
    "新疆维吾尔自治区哈密市市场监管局查处新疆信达睿安检测技术有限公司出具虚假检验检测报告案",
])
def test_other_regulatory_tracks_are_marked(title):
    """这些是真实可溯源的处罚案例，只是对广告合规没用。

    标注不是删除 —— 删掉等于替人做了取舍，而它们对别的用途仍有价值。
    """
    assert ad_relevance(title) is Relevance.OTHER_TRACK


def test_unrelated_text_defaults_to_other_not_ad():
    """判不准的时候倒向「不相关」。

    错标成相关会让复核的人白读一条；错标成不相关只是排序靠后，还在库里。
    """
    assert ad_relevance("当事人未按规定办理营业执照变更登记。") is Relevance.OTHER_TRACK


def test_empty_input_is_maybe_not_a_verdict():
    """没有信息就不要给结论。"""
    assert ad_relevance("") is Relevance.MAYBE
    assert ad_relevance(None, None) is Relevance.MAYBE


# ══════════════════════════════════════════════════════════════
#  打标
# ══════════════════════════════════════════════════════════════

def test_tag_case_reads_several_fields():
    """标题看不出来时，事实摘要和违法表述要能救回来。"""
    case = {"segment_title": "某公司案",
            "facts_summary": "当事人在抖音直播间带货时宣称产品可治疗糖尿病。"}
    assert tag_case(case)["topic_relevance"] == "ad"


def test_tag_case_uses_illegal_claims():
    case = {"segment_title": "某公司案", "illegal_claims": ["国家级配方", "三天彻底根治"]}
    tag_case(case, segment_text="当事人发布的广告中宣称国家级配方。")
    assert case["topic_relevance"] == "ad"


def test_tag_case_never_drops_the_case():
    """标注层不得有「丢弃」这个动作。"""
    case = {"segment_title": "查处某加油站为加油机增加作弊装置案", "case_id": "x"}
    out = tag_case(case)
    assert out is case
    assert out["case_id"] == "x"
    assert out["topic_relevance"] == "other"
