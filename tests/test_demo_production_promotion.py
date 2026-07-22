import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from src import build_chunks
from src.api import create_app, is_production_case


ROOT = Path(__file__).resolve().parents[1]
DEMO_CASE_IDS = {
    "mihoyo_2016_2520150399",
    "shanghai_jingan_2026_062026000257",
    "sector_docx__health__d8460228",
}
REQUESTS = [
    (
        {
            "content": "网络游戏 抽卡 爆率 随机抽取 游戏虚拟货币 概率规则",
            "industry": "游戏",
            "platform": [],
            "top_k": 3,
        },
        "mihoyo_2016_2520150399",
    ),
    (
        {
            "content": "降价 和狗一样跑过来 侮辱消费者 违背社会良好风尚",
            "industry": "通用",
            "platform": ["抖音", "小红书"],
            "top_k": 3,
        },
        "shanghai_jingan_2026_062026000257",
    ),
    (
        {
            "content": "治疗肝癌、肺癌、结肠癌等80%-90%癌症病类",
            "industry": "保健食品",
            "platform": ["微信"],
            "top_k": 3,
        },
        "sector_docx__health__d8460228",
    ),
]


class DemoProductionPromotionTests(unittest.TestCase):
    def test_manifest_is_explicit_and_narrow(self):
        manifest = json.loads(
            (ROOT / "data/config/demo_production_cases.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(manifest["enabled"])
        self.assertEqual(set(manifest["case_ids"]), DEMO_CASE_IDS)
        self.assertTrue(manifest["safety_boundary"]["demo_only"])
        self.assertTrue(
            manifest["safety_boundary"]["not_for_production_factual_use"]
        )

    def test_demo_cases_enter_production_without_rewriting_source_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_chunks.run(
                structured_dir=ROOT / "data/structured",
                structured_candidates_dir=ROOT / "data/structured_candidates",
                structured_samples_dir=ROOT / "data/structured_samples",
                chunks_dir=root / "chunks",
                reports_dir=root / "reports",
                demo_production_manifest=(
                    ROOT / "data/config/demo_production_cases.json"
                ),
            )
            chunks = json.loads(paths["production"].read_text(encoding="utf-8"))

        demo_chunks = [
            chunk for chunk in chunks if chunk["case_id"] in DEMO_CASE_IDS
        ]
        self.assertEqual(len(demo_chunks), 6)
        self.assertEqual({chunk["case_id"] for chunk in demo_chunks}, DEMO_CASE_IDS)
        for chunk in demo_chunks:
            metadata = chunk["metadata"]
            self.assertTrue(metadata["demo_production"])
            self.assertTrue(metadata["demo_only"])
            self.assertTrue(metadata["not_for_production_factual_use"])
            self.assertNotEqual(
                metadata["source_verification_status"],
                "source_verified",
            )
            case = build_chunks.load_case_record(
                ROOT / "data/structured" / f"{chunk['case_id']}.json"
            )
            self.assertTrue(is_production_case(case, chunk))
            self.assertTrue(build_chunks.production_exclusion_reasons(case))

    def test_three_judge_queries_hit_expected_case_first_in_production(self):
        client = TestClient(
            create_app(
                data_dir=ROOT / "data",
                index_scope="production",
                api_key="local-demo-test",
            )
        )
        health = client.get("/health").json()
        self.assertEqual(health["case_count"], 13)
        self.assertEqual(health["chunk_count"], 26)

        for request, expected_case_id in REQUESTS:
            response = client.post(
                "/cases/retrieve",
                headers={"X-API-Key": "local-demo-test"},
                json=request,
            )
            self.assertEqual(response.status_code, 200)
            cases = response.json()["data"]["cases"]
            self.assertTrue(cases, expected_case_id)
            self.assertEqual(cases[0]["case_id"], expected_case_id)
            self.assertFalse(cases[0]["candidate_data"])
            self.assertTrue(cases[0]["approved_for_rag"])
            self.assertNotEqual(
                cases[0]["source_verification_status"],
                "source_verified",
            )


if __name__ == "__main__":
    unittest.main()
