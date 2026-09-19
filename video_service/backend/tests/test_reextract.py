# -*- coding: utf-8 -*-
"""重抽脚本的溯源保全测试。

这一条是补的回归测试：一次重抽把候选库里 107 条的 `content_sha256` 全清空了，
**没有任何报错**，字段填充率也不看这个键 —— 直到有人去查存证才会发现。
存证哈希是「站点日后改版或删文时，能证明我们当时看到的就是这个」的唯一凭据。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from reextract import EXTRACTION_OUTPUTS, carry_over_provenance  # noqa: E402


def _old():
    """一条抓取产出的完整记录 —— 溯源字段与抽取字段都有。"""
    return {
        "case_id": "samr_abc_01",
        "source_url": "https://www.samr.gov.cn/xw/zj/art/2026/art_abc.html",
        "raw_text_path": "data/raw_text/samr_abc.json",
        "raw_html_path": "data/raw_html/samr_abc.html",
        "content_sha256": "0f1e2d3c4b5a69788796a5b4c3d2e1f0" * 2,
        "fetched_at": "2026-09-08T06:00:00+00:00",
        "title": "某某公司违法广告案",
        "segment_index": 1,
        "segment_title": "某某公司违法广告案",
        "also_seen_at": ["https://other.gov.cn/x"],
        "party_name": "某某公司",
        "penalty_amount": 600000,
    }


# ══════════════════════════════════════════════════════════════
#  溯源字段必须保全
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("key", [
    "content_sha256", "title", "raw_html_path", "fetched_at",
    "segment_index", "segment_title", "also_seen_at",
])
def test_provenance_survives_reextraction(key):
    """重抽产生不了这些，丢了就再也回不来。"""
    old = _old()
    new = {"case_id": old["case_id"], "party_name": "某某公司"}
    carry_over_provenance(old, new)
    assert new[key] == old[key]


def test_evidence_hash_is_not_silently_dropped():
    """这一条单独立着，因为它是真出过事的那个。

    存证哈希被清空时不会报错，字段填充率统计里也没有它 ——
    只有等到需要自证「我们当时看到的就是这个」时才会发现，那时已经晚了。
    """
    new = {"case_id": "samr_abc_01"}
    carry_over_provenance(_old(), new)
    assert len(new["content_sha256"]) == 64


def test_unknown_future_provenance_field_is_kept():
    """将来加的溯源字段要自动被保住 —— 这正是白名单做不到、而这个方向能做到的。

    出事的那版是一份「要保留的键」白名单：它随溯源字段增加而悄悄过期，
    过期时没有任何信号。
    """
    old = _old() | {"archived_at": "2026-09-08", "wayback_url": "https://web.archive.org/x"}
    new = {"case_id": old["case_id"]}
    carry_over_provenance(old, new)
    assert new["archived_at"] == "2026-09-08"
    assert new["wayback_url"] == "https://web.archive.org/x"


# ══════════════════════════════════════════════════════════════
#  抽取字段不得被老值复活
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("key,old_value", [
    ("penalty_amount", 600000),
    ("legal_basis", ["《中华人民共和国广告法》第十七条"]),
    ("industry", "保健食品"),
    ("illegal_claims", ["三天彻底根治"]),
])
def test_extraction_fields_are_not_resurrected(key, old_value):
    """本次没抽出来，就是没抽出来。

    把老值补回去等于用旧代码的结论冒充新一轮的抽取结果 ——
    而重抽的全部意义就是让全库出自同一个代码版本。
    """
    old = _old() | {key: old_value}
    new = {"case_id": old["case_id"]}
    carry_over_provenance(old, new)
    assert key not in new


def test_isolated_inferred_basis_is_not_resurrected():
    """上一版误留在 legal_basis 里的推断条号，不能借保全之名回到库里。"""
    old = _old() | {"legal_basis": ["《中华人民共和国广告法》第十七条"],
                    "legal_basis_inferred": ["《中华人民共和国广告法》第十七条"]}
    new = {"case_id": old["case_id"], "legal_basis": ["《中华人民共和国广告法》"]}
    carry_over_provenance(old, new)
    assert new["legal_basis"] == ["《中华人民共和国广告法》"]
    assert "legal_basis_inferred" not in new


def test_review_status_is_not_carried_over():
    """复核状态由质量门禁写，不由老记录带 —— 抓取产出一律 pending_review。"""
    old = _old() | {"review_status": "approved"}
    new = {"case_id": old["case_id"]}
    carry_over_provenance(old, new)
    assert "review_status" not in new


def test_new_value_wins_over_old():
    """新抽出来的值优先，保全只补新记录里没有的键。"""
    old = _old()
    new = {"case_id": old["case_id"], "title": "重抽后的新标题"}
    carry_over_provenance(old, new)
    assert new["title"] == "重抽后的新标题"


def test_extraction_outputs_covers_every_model_field():
    """FIELD_SPECS 里的每个字段都必须算作抽取产物。

    漏一个就会被当成溯源字段保全下来 —— 旧值悄悄混进新一轮结果。
    """
    from app.crawler.extract import FIELD_SPECS

    assert set(FIELD_SPECS) <= EXTRACTION_OUTPUTS
