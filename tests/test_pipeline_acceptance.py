import json
import tempfile
import unittest
from pathlib import Path

from src import build_chunks, clean_cases, extract_text, fetch_cases, test_retrieval


class PipelineAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in [
            "data/sources",
            "data/raw_html",
            "data/raw_text",
            "data/structured",
            "data/structured_samples",
            "data/chunks",
            "data/reports",
            "prompts",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        self.prompt_path = self.root / "prompts/clean_case_prompt.md"
        self.prompt_path.write_text("案例正文：\n{{case_text}}\n", encoding="utf-8")
        sample_html = self.root / "data/sources/sample_cases.html"
        sample_html.write_text(
            """
<article data-source-url="https://example.com/offline/absolute-terms">
  <h1>某公司绝对化用语广告案</h1>
  <p>某公司在互联网广告中宣称产品为“国家级最佳”，违反广告法第二十八条。</p>
</article>
<article data-source-url="https://example.com/offline/food-blood-sugar">
  <h1>普通食品宣传降血糖案</h1>
  <p>某公司将普通食品宣传为可以“降血糖”，违反广告法第二十八条，监管机关认为容易误导消费者。</p>
</article>
<article data-source-url="https://example.com/offline/cosmetic-medical">
  <h1>化妆品医疗化宣传案</h1>
  <p>某公司宣传化妆品具有“治疗皮炎”效果，违反广告法第二十八条。</p>
</article>
""",
            encoding="utf-8",
        )
        (self.root / "data/sources/sources.yaml").write_text(
            """
sources:
  - source_id: offline_samples
    source_name: 离线样例
    source_type: offline_sample
    priority: DEMO
    base_url: "https://example.com"
    list_urls: []
    detail_urls:
      - "https://example.com/offline/absolute-terms"
      - "https://example.com/offline/food-blood-sugar"
      - "https://example.com/offline/cosmetic-medical"
    allowed_domains:
      - "example.com"
    crawl_mode: manual_seed
    sample_file: "data/sources/sample_cases.html"

  - source_id: official_seed
    source_name: 官方手动种子
    source_type: official_typical_case
    priority: P0
    base_url: "https://www.samr.gov.cn"
    list_urls:
      - "https://www.samr.gov.cn/list-page-that-should-not-be-crawled"
    detail_urls:
      - "https://www.samr.gov.cn/example-official.html"
    allowed_domains:
      - "samr.gov.cn"
    crawl_mode: manual_seed
""",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_manual_seed_sample_pipeline_outputs_three_cases_and_two_chunk_types(self):
        raw_html = fetch_cases.run(
            sources_path=self.root / "data/sources/sources.yaml",
            raw_html_dir=self.root / "data/raw_html",
            base_dir=self.root,
        )
        raw_text = extract_text.run(self.root / "data/raw_html", self.root / "data/raw_text")
        structured = clean_cases.run(
            raw_text_dir=self.root / "data/raw_text",
            structured_dir=self.root / "data/structured",
            structured_samples_dir=self.root / "data/structured_samples",
            prompt_path=self.prompt_path,
            reports_dir=self.root / "data/reports",
            mode="mock",
        )
        chunk_paths = build_chunks.run(
            structured_dir=self.root / "data/structured",
            structured_samples_dir=self.root / "data/structured_samples",
            chunks_dir=self.root / "data/chunks",
        )
        chunks_path = chunk_paths["test"]
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        results = test_retrieval.search(
            query="普通食品宣传降血糖",
            chunks_path=chunks_path,
            top_k=1,
        )

        self.assertEqual(len(raw_html), 3)
        self.assertEqual(len(raw_text), 3)
        self.assertEqual(len(structured), 3)
        self.assertEqual(list((self.root / "data/structured").glob("*.json")), [])
        self.assertGreaterEqual(len(chunks), 6)
        self.assertEqual(
            {"case_summary", "regulatory_logic"},
            {chunk["chunk_type"] for chunk in chunks},
        )
        self.assertIn("food-blood-sugar", results[0]["source_url"])

    def test_allow_network_fetches_only_manual_detail_urls(self):
        fetched_urls = []

        def fake_fetch(url):
            fetched_urls.append(url)
            return "<html><h1>官方案例</h1><p>某公司发布违法广告。</p></html>"

        outputs = fetch_cases.run(
            sources_path=self.root / "data/sources/sources.yaml",
            raw_html_dir=self.root / "data/raw_html",
            fetcher=fake_fetch,
            allow_network=True,
            base_dir=self.root,
        )

        self.assertIn("https://www.samr.gov.cn/example-official.html", fetched_urls)
        self.assertNotIn("https://www.samr.gov.cn/list-page-that-should-not-be-crawled", fetched_urls)
        self.assertEqual(len(outputs), 4)

    def test_build_chunks_rebuilds_without_stale_chunks(self):
        chunks_dir = self.root / "data/chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        (chunks_dir / "chunks.json").write_text(
            json.dumps(
                [
                    {
                        "chunk_id": "stale_sample__case_summary",
                        "case_id": "stale_sample",
                        "chunk_type": "case_summary",
                        "title": "旧样例",
                        "source_name": "旧样例",
                        "source_url": "sample://old",
                        "risk_dimensions": [],
                        "keywords": [],
                        "text": "旧样例",
                        "metadata": {},
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        chunk_paths = build_chunks.run(
            structured_dir=self.root / "data/structured",
            chunks_dir=chunks_dir,
        )

        self.assertEqual(json.loads(chunk_paths["production"].read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
