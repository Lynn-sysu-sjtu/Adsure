# -*- coding: utf-8 -*-
"""法条引用抽取测试。

用例取自实际抓回的通报原文写法，不是编的 —— 这个正则要面对的就是这些形态。
"""

from __future__ import annotations

import pytest

from app.crawler.legalref import (
    BasisKind,
    find_citations,
    legal_basis_from_text,
    merge_legal_basis,
)


# ══════════════════════════════════════════════════════════════
#  真实句式
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("text,expected", [
    # 实测样本：湖北省宜昌市西陵区远浦帆归百货店虚假宣传案
    ("当事人的上述行为违反了《中华人民共和国反不正当竞争法》第九条第一款的规定。",
     ["《中华人民共和国反不正当竞争法》第九条第一款"]),
    # 实测样本：广东中正珠宝鉴定有限公司广州分公司案
    ("当事人的行为违反了《检验检测机构监督管理办法》第十五条的规定。",
     ["《检验检测机构监督管理办法》第十五条"]),
    ("依据《中华人民共和国广告法》第五十八条第一款第（三）项，责令停止发布。",
     ["《中华人民共和国广告法》第五十八条第一款第（三）项"]),
    ("违反《中华人民共和国广告法》第十七条规定。",
     ["《中华人民共和国广告法》第十七条"]),
    ("违反了《中华人民共和国食品安全法》第七十三条之一的规定",
     ["《中华人民共和国食品安全法》第七十三条之一"]),
])
def test_real_citation_forms_are_extracted(text, expected):
    assert legal_basis_from_text(text) == expected


def test_one_sentence_citing_several_articles_expands():
    """一处引用多条要展开 —— 规则 RAG 按法条检索，不按引用句检索。"""
    text = ("当事人的行为违反了《中华人民共和国广告法》第四条第一款、"
            "第二十八条第二款第（二）项的规定。")
    assert legal_basis_from_text(text) == [
        "《中华人民共和国广告法》第四条第一款",
        "《中华人民共和国广告法》第二十八条第二款第（二）项",
    ]


def test_阿拉伯数字条号也认():
    assert legal_basis_from_text("依据《广告法》第58条") == ["《广告法》第58条"]


# ══════════════════════════════════════════════════════════════
#  不该被当成法律依据的东西
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("text", [
    # 书名号里是文书名/证书名/标准名，后面不跟条号
    "当事人出具虚假的《宝玉石及贵金属饰品鉴定证书》。",
    "当事人未按《食品经营许可证》载明的范围经营。",
    # 只提法规不带条号 —— 无法定位到具体规范，不能当依据
    "上述行为违反广告法相关规定。",
    "当事人的行为违反了《中华人民共和国广告法》的规定。",
])
def test_non_citations_are_not_picked_up(text):
    assert legal_basis_from_text(text) == []


def test_duplicate_citations_collapse():
    text = ("违反了《中华人民共和国广告法》第十七条的规定。……"
            "依据《中华人民共和国广告法》第十七条，责令改正。")
    assert legal_basis_from_text(text) == ["《中华人民共和国广告法》第十七条"]


def test_empty_and_none_are_safe():
    assert legal_basis_from_text("") == []
    assert legal_basis_from_text(None) == []


# ══════════════════════════════════════════════════════════════
#  违反 vs 处罚依据
# ══════════════════════════════════════════════════════════════

def test_violated_and_penalty_bases_are_distinguished():
    text = ("当事人的行为违反了《中华人民共和国广告法》第十七条的规定。"
            "依据《中华人民共和国广告法》第五十八条，处以罚款。")
    kinds = {c.article: c.kind for c in find_citations(text)}
    assert kinds["第十七条"] is BasisKind.VIOLATED
    assert kinds["第五十八条"] is BasisKind.PENALTY


def test_context_does_not_leak_across_sentences():
    """语境判断只看本句。

    跨句去猜会把上一案的「违反」算到下一案的引用头上 —— 通报里一段接一段，
    这种串味会让「违反了哪一条」这个字段整体不可信。
    """
    text = "当事人的行为违反了广告法。《中华人民共和国行政处罚法》第二十八条另有规定。"
    c = find_citations(text)[0]
    assert c.kind is BasisKind.UNMARKED


def test_quote_is_verbatim_locatable():
    """每条引用都要能回原文定位 —— 这是它比模型抽取更可信的全部理由。"""
    text = "当事人的行为违反了《中华人民共和国反不正当竞争法》第九条第一款的规定。"
    for c in find_citations(text):
        assert c.quote in text.replace(" ", "")


# ══════════════════════════════════════════════════════════════
#  与模型抽取合并
# ══════════════════════════════════════════════════════════════

def test_regex_result_leads_and_model_extras_follow():
    text = "违反了《中华人民共和国广告法》第十七条的规定。"
    lb = merge_legal_basis(["《中华人民共和国广告法》第五十八条"], text)
    assert lb.citations[0] == "《中华人民共和国广告法》第十七条"
    assert "《中华人民共和国广告法》第五十八条" in lb.citations
    assert lb.inferred == []


def test_model_normalised_duplicate_defers_to_verbatim_form():
    """模型把《广告法》补全成《中华人民共和国广告法》，是同一条，不要两条都留。"""
    lb = merge_legal_basis(["《中华人民共和国广告法》第十七条"],
                           "违反了《广告法》第十七条的规定。")
    assert lb.basis == ["《广告法》第十七条"]


def test_nothing_in_nothing_out():
    lb = merge_legal_basis(None, "当事人销售不合格商品。")
    assert lb.basis == [] and lb.inferred == []


# ══════════════════════════════════════════════════════════════
#  法规级援引 与 模型推断
# ══════════════════════════════════════════════════════════════

# 实测原文：总局「十起违法广告典型案例」的通行写法，只到法规名，没有条号
_NO_ARTICLE = ("邳州市市场监管局依据《中华人民共和国广告法》有关规定，"
               "对当事人作出罚没款62.91万元的行政处罚。")


def test_law_level_mention_is_recorded_as_law_not_article():
    lb = merge_legal_basis(None, _NO_ARTICLE)
    assert lb.laws == ["《中华人民共和国广告法》"]
    assert lb.citations == []
    assert lb.basis == ["《中华人民共和国广告法》"]


def test_model_supplied_article_without_textual_support_is_marked_inferred():
    """原文只写「有关规定」，模型补出「第十七条」—— 法律上多半对，但原文没这句话。

    这是引用核对拦不住的一类：模型可以照抄「依据《中华人民共和国广告法》有关规定」
    作为 quote，那句话确实在原文里，**却支撑不了它给的条号**。
    混进 legal_basis 就是编造法律依据，法务照着去核会核不到。
    """
    lb = merge_legal_basis(["《中华人民共和国广告法》第十七条"], _NO_ARTICLE)
    assert lb.inferred == ["《中华人民共和国广告法》第十七条"]
    assert "《中华人民共和国广告法》第十七条" not in lb.basis


def test_model_article_is_trusted_when_the_text_cites_that_law_by_article():
    """原文已经在用条号引这部法，模型补出同法的另一条，属于可采信的补充。"""
    text = "违反了《中华人民共和国广告法》第四条的规定，依据该法有关条款处罚。"
    lb = merge_legal_basis(["《中华人民共和国广告法》第五十八条"], text)
    assert "《中华人民共和国广告法》第五十八条" in lb.citations
    assert lb.inferred == []


def test_law_level_and_article_level_of_same_law_do_not_double_up():
    """同一部法既被条号引用又被泛引，只留精度更高的那个。"""
    text = "违反了《中华人民共和国广告法》第十七条的规定，依据《中华人民共和国广告法》有关规定处罚。"
    lb = merge_legal_basis(None, text)
    assert lb.citations == ["《中华人民共和国广告法》第十七条"]
    assert lb.laws == []


@pytest.mark.parametrize("text", [
    "当事人出具虚假的《宝玉石及贵金属饰品鉴定证书》。",
    "当事人未按《食品经营许可证》载明的范围经营。",
])
def test_document_names_are_not_mistaken_for_laws(text):
    """书名号里是证书名/许可证名，不是法规 —— 不能当法律依据。"""
    from app.crawler.legalref import find_law_mentions
    assert find_law_mentions(text) == []
