"""IP 库 schema/加载器测试（实施方案 v2 §5）。"""

from pathlib import Path

import pytest
import yaml

from app.ip.library import load_library
from app.ip.schema import IPLibraryEntry

SEED = Path(__file__).resolve().parents[1] / "app" / "ip" / "library" / "ip_library.seed.yaml"


def test_seed_loads_and_declares_unreviewed():
    lib = load_library(SEED)
    assert len(lib.entries) >= 15
    assert lib.meta.reviewed_by_legal is False
    for e in lib.entries:
        assert e.ip_id and e.rights_holder and e.law_ref and e.required_materials


def test_seed_covers_plan_starter_list():
    lib = load_library(SEED)
    ids = {e.ip_id for e in lib.entries}
    assert {"disney_mickey", "pokemon_pikachu", "sanrio_hello_kitty",
            "sanrio_kuromi", "ultraman", "peppa_pig", "spongebob",
            "pleasant_goat", "boonie_bears", "nezha"} <= ids


def test_duplicate_ip_id_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    good = {
        "meta": {"name": "t", "version": "0", "reviewed_by_legal": False},
        "entries": [
            {"ip_id": "a", "name_cn": "甲", "rights_holder": "R",
             "law_ref": ["法"], "required_materials": ["授权书"]},
            {"ip_id": "a", "name_cn": "甲", "rights_holder": "R",
             "law_ref": ["法"], "required_materials": ["授权书"]},
        ],
    }
    bad.write_text(yaml.safe_dump(allow_unicode=True, data=good), encoding="utf-8")
    with pytest.raises(ValueError, match="重复 ip_id"):
        load_library(bad)


def test_entry_requires_materials_and_law():
    with pytest.raises(Exception):
        IPLibraryEntry(ip_id="x", name_cn="x", rights_holder="R")


def test_customer_owned_library_type_accepted():
    e = IPLibraryEntry(
        ip_id="brand_mascot", name_cn="品牌自有形象", rights_holder="客户",
        library_type="customer_owned", law_ref=["《商标法》第五十七条"],
        required_materials=["权属证明"],
    )
    assert e.library_type == "customer_owned"


def test_match_by_name_alias_hit_and_phrase_miss():
    lib = load_library(SEED)
    assert lib.match_by_name("米老鼠") is not None
    assert lib.match_by_name("Hello Kitty").ip_id == "sanrio_hello_kitty"
    # 刻意只做精确归一匹配：描述性短语不得命中
    assert lib.match_by_name("一个像米老鼠的玩偶挂饰") is None
    assert lib.match_by_name("") is None
