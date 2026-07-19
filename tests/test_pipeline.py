import json
import tempfile
import unittest
from pathlib import Path

from src import build_chunks, clean_cases, extract_text, fetch_cases, test_retrieval, validate_cases


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in [
            "data/sources",
            "data/raw_html",
            "data/raw_text",
            "data/structured",
            "data/chunks",
            "data/reports",
            "prompts",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)

        (self.root / "data/sources/sources.yaml").write_text(
            """
sources:
  - source_id: samr_typical_ads
    source_name: 国家市场监督管理总局违法广告典型案例
    source_type: official_typical_case
    priority: P0
    base_url: "https://www.samr.gov.cn"
    list_urls:
      - "https://www.samr.gov.cn/example-list"
    detail_urls:
      - "https://www.samr.gov.cn/example-case.html"
    allowed_domains:
      - "samr.gov.cn"
    crawl_mode: manual_seed
    notes: "优先抓典型违法广告案例，用于 MVP"
""",
            encoding="utf-8",
        )
        (self.root / "prompts/clean_case_prompt.md").write_text(
            "案例正文：\n{{case_text}}\n", encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_manual_seed_fetch_saves_raw_html_once(self):
        def fake_fetch(url):
            return "<html><h1>违法广告典型案例</h1><p>当事人发布绝对化广告。</p></html>"

        saved = fetch_cases.run(
            sources_path=self.root / "data/sources/sources.yaml",
            raw_html_dir=self.root / "data/raw_html",
            fetcher=fake_fetch,
            allow_network=True,
        )
        saved_again = fetch_cases.run(
            sources_path=self.root / "data/sources/sources.yaml",
            raw_html_dir=self.root / "data/raw_html",
            fetcher=fake_fetch,
            allow_network=True,
        )

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved_again, [])
        payload = json.loads(saved[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["source_id"], "samr_typical_ads")
        self.assertEqual(payload["source_url"], "https://www.samr.gov.cn/example-case.html")
        self.assertIn("违法广告典型案例", payload["html"])

    def test_extract_text_writes_plain_text_and_metadata(self):
        raw_html = self.root / "data/raw_html/samr_typical_ads__abc123.json"
        raw_html.write_text(
            json.dumps(
                {
                    "case_id": "samr_typical_ads__abc123",
                    "source_id": "samr_typical_ads",
                    "source_name": "国家市场监督管理总局违法广告典型案例",
                    "source_type": "official_typical_case",
                    "priority": "P0",
                    "source_url": "https://www.samr.gov.cn/example-case.html",
                    "html": "<html><script>ignore()</script><h1>标题</h1><p>发布“国家级”广告。</p></html>",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        outputs = extract_text.run(
            raw_html_dir=self.root / "data/raw_html",
            raw_text_dir=self.root / "data/raw_text",
        )

        self.assertEqual(len(outputs), 1)
        payload = json.loads(outputs[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["case_id"], "samr_typical_ads__abc123")
        self.assertIn("发布“国家级”广告。", payload["case_text"])
        self.assertNotIn("ignore", payload["case_text"])

    def test_mock_clean_validate_chunk_and_retrieve(self):
        raw_text = self.root / "data/raw_text/samr_typical_ads__abc123.json"
        raw_text.write_text(
            json.dumps(
                {
                    "case_id": "samr_typical_ads__abc123",
                    "title": "某公司违法广告案",
                    "source_type": "official_typical_case",
                    "source_name": "国家市场监督管理总局违法广告典型案例",
                    "source_url": "https://www.samr.gov.cn/example-case.html",
                    "raw_text_path": str(raw_text),
                    "case_text": "某公司在互联网广告中宣称产品为“国家级最佳”，监管机关认定构成绝对化用语违法，违反广告法第九条，罚款10000元。",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        structured = clean_cases.run(
            raw_text_dir=self.root / "data/raw_text",
            structured_dir=self.root / "data/structured",
            prompt_path=self.root / "prompts/clean_case_prompt.md",
            llm_mode="mock",
        )
        report = validate_cases.run(
            structured_dir=self.root / "data/structured",
            reports_dir=self.root / "data/reports",
        )

        case = json.loads(structured[0].read_text(encoding="utf-8"))
        case["review_status"] = "approved"
        case["approved_for_rag"] = True
        case["source_verification_status"] = "source_verified"
        case["publish_date"] = "2026-01-01"
        case["penalty_authority"] = "某地市场监督管理局"
        case["party_name"] = "某公司"
        case["industry"] = "通用"
        case["product_or_service"] = "测试产品"
        case["violation_type"] = "绝对化用语"
        case["audit"] = {"review_status": "approved", "approved_for_rag": True}
        structured[0].write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")

        case = json.loads(structured[0].read_text(encoding="utf-8"))
        self.assertEqual(case["review_status"], "approved")
        self.assertIn("绝对化用语", case["risk_dimensions"])
        self.assertEqual(case["penalty_amount"], 10000)
        self.assertEqual(case["raw_text_path"], str(raw_text))
        self.assertEqual(case["raw_html_path"], "")

        chunks = build_chunks.run(
            structured_dir=self.root / "data/structured",
            chunks_dir=self.root / "data/chunks",
        )
        production_chunks = chunks["production"]
        results = test_retrieval.search(
            query="互联网广告 国家级 绝对化用语",
            chunks_path=production_chunks,
            top_k=1,
        )

        self.assertEqual(report["invalid_count"], 0)
        chunk_payload = json.loads(production_chunks.read_text(encoding="utf-8"))
        self.assertEqual(len(chunk_payload), 2)
        self.assertEqual(
            {"case_summary", "regulatory_logic"},
            {chunk["chunk_type"] for chunk in chunk_payload},
        )
        self.assertTrue(all(chunk["scope"] == "public" for chunk in chunk_payload))
        self.assertTrue(all(chunk["tenant_id"] is None for chunk in chunk_payload))
        self.assertTrue(
            all(chunk["metadata"]["scope"] == "public" for chunk in chunk_payload)
        )
        self.assertEqual(results[0]["case_id"], "samr_typical_ads__abc123")

    def test_tenant_case_without_tenant_id_is_excluded_from_production(self):
        case_path = self.root / "data/structured/tenant_case.json"
        case_path.write_text(
            json.dumps(
                {
                    "case_id": "tenant_case",
                    "title": "企业私有案例",
                    "source_type": "official_typical_case",
                    "source_name": "企业核验来源",
                    "source_url": "https://example.com/tenant-case",
                    "source_verification_status": "source_verified",
                    "raw_text_path": "data/raw_text/tenant-case.json",
                    "risk_dimensions": ["虚假宣传"],
                    "illegal_claims": ["私有宣称"],
                    "facts_summary": "企业已核验该私有广告案例的事实摘要。",
                    "legal_basis": ["《中华人民共和国广告法》"],
                    "regulatory_logic": "企业已核验该案例的监管逻辑。",
                    "vector_text": "企业私有广告案例涉及虚假宣传，已完成来源和法律复核。",
                    "review_status": "approved",
                    "approved_for_rag": True,
                    "scope": "tenant",
                    "tenant_id": None,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        paths = build_chunks.run(
            structured_dir=self.root / "data/structured",
            chunks_dir=self.root / "data/chunks",
            reports_dir=self.root / "data/reports",
        )

        production = json.loads(paths["production"].read_text(encoding="utf-8"))
        report = (self.root / "data/reports/chunk_build_report.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(production, [])
        self.assertIn("tenant_scope_missing_tenant_id", report)

    def test_incomplete_official_case_is_excluded_from_production(self):
        case_path = self.root / "data/structured/incomplete_official_case.json"
        case_path.write_text(
            json.dumps(
                {
                    "case_id": "incomplete_official_case",
                    "title": "字段不完整的官方案例",
                    "source_type": "official_typical_case",
                    "source_name": "市场监管部门",
                    "source_url": "https://example.com/official-case",
                    "source_verification_status": "source_verified",
                    "raw_text_path": "data/raw_text/official-case.json",
                    "risk_dimensions": ["虚假宣传"],
                    "illegal_claims": ["虚假宣称"],
                    "facts_summary": "经营者发布虚假广告，监管部门依法处理。",
                    "legal_basis": ["《中华人民共和国广告法》"],
                    "regulatory_logic": "广告内容与实际情况不符。",
                    "vector_text": "经营者发布与实际情况不符的商品广告，监管部门认定相关内容可能误导消费者。",
                    "review_status": "approved",
                    "approved_for_rag": True,
                    "audit": {
                        "review_status": "approved",
                        "approved_for_rag": True,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        paths = build_chunks.run(
            structured_dir=self.root / "data/structured",
            chunks_dir=self.root / "data/chunks",
            reports_dir=self.root / "data/reports",
        )

        production = json.loads(paths["production"].read_text(encoding="utf-8"))
        report = (self.root / "data/reports/chunk_build_report.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(production, [])
        for reason in [
            "missing_publish_date",
            "missing_penalty_authority",
            "missing_party_name",
            "missing_industry",
            "missing_product_or_service",
            "missing_penalty_result",
            "missing_violation_type",
        ]:
            self.assertIn(reason, report)

    def test_verified_tenant_case_can_use_private_source_without_public_url(self):
        case_path = self.root / "data/structured/tenant_case.json"
        case_path.write_text(
            json.dumps(
                {
                    "case_id": "tenant_case",
                    "title": "企业私有案例",
                    "source_type": "tenant_case",
                    "source_name": "企业私有案例库",
                    "source_url": None,
                    "source_verification_status": "tenant_verified",
                    "raw_text_path": "data/raw_text/tenant-case.json",
                    "risk_dimensions": ["虚假宣传"],
                    "illegal_claims": ["私有宣称"],
                    "facts_summary": "企业已核验该私有广告案例的事实摘要。",
                    "legal_basis": ["《中华人民共和国广告法》"],
                    "regulatory_logic": "企业已核验该案例的监管逻辑。",
                    "vector_text": "企业私有广告案例涉及虚假宣传，已完成来源和法律复核。",
                    "review_status": "approved",
                    "approved_for_rag": True,
                    "scope": "tenant",
                    "tenant_id": "tenant_company_a",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        paths = build_chunks.run(
            structured_dir=self.root / "data/structured",
            chunks_dir=self.root / "data/chunks",
            reports_dir=self.root / "data/reports",
        )

        production = json.loads(paths["production"].read_text(encoding="utf-8"))
        self.assertEqual(len(production), 2)
        self.assertTrue(all(chunk["scope"] == "tenant" for chunk in production))
        self.assertTrue(
            all(chunk["tenant_id"] == "tenant_company_a" for chunk in production)
        )


if __name__ == "__main__":
    unittest.main()
