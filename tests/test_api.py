import json
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from src.api import case_matches_industry, create_app


class CaseApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        (self.data_dir / "chunks").mkdir(parents=True)
        (self.data_dir / "structured").mkdir()
        (self.data_dir / "structured_candidates").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(
        self,
        directory: str,
        case_id: str,
        *,
        approved: bool,
        source_type: str,
        scope: str = "public",
        tenant_id: str | None = None,
        industry: str = "美妆",
    ) -> dict:
        case = {
            "case_id": case_id,
            "title": f"{case_id} 标题",
            "source_type": source_type,
            "source_name": "市场监管部门",
            "source_url": "https://example.gov.cn/case",
            "publish_date": "2026-01-01",
            "source_verification_status": "source_verified" if approved else "pending_source_lookup",
            "raw_text_path": f"data/raw_text/{case_id}.json" if approved else "",
            "penalty_authority": "某地市场监督管理局",
            "party_name": "某公司",
            "industry": industry,
            "violation_type": "虚假宣传",
            "product_or_service": "测试产品",
            "ad_channel": "互联网广告",
            "risk_dimensions": ["虚假宣传"],
            "illegal_claims": ["15天见效"],
            "facts_summary": "某公司发布广告宣称产品十五天见效，监管部门依法处理。",
            "legal_basis": ["《中华人民共和国广告法》"],
            "penalty_result": "罚款1万元",
            "regulatory_logic": "监管机关认定相关宣传内容没有事实依据，容易误导消费者。",
            "vector_text": "经营者发布产品十五天见效的广告宣传，监管机关认定相关内容没有事实依据并依法处罚。",
            "review_status": "approved" if approved else "pending_review",
            "approved_for_rag": approved,
            "scope": scope,
            "tenant_id": tenant_id,
        }
        path = self.data_dir / directory / f"{case_id}.json"
        path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        return case

    def write_chunks(self, name: str, chunks: list[dict]) -> None:
        (self.data_dir / "chunks" / name).write_text(
            json.dumps(chunks, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def chunk(case: dict, chunk_type: str, text: str) -> dict:
        return {
            "chunk_id": f"{case['case_id']}__{chunk_type}",
            "case_id": case["case_id"],
            "chunk_type": chunk_type,
            "scope": case.get("scope", "public"),
            "tenant_id": case.get("tenant_id"),
            "title": case["title"],
            "source_name": case["source_name"],
            "source_url": case["source_url"],
            "risk_dimensions": case["risk_dimensions"],
            "keywords": [],
            "text": text,
            "metadata": {
                "source_type": case["source_type"],
                "industry": case["industry"],
                "ad_channel": case["ad_channel"],
                "scope": case.get("scope", "public"),
                "tenant_id": case.get("tenant_id"),
            },
        }

    def client(self, scope: str = "production", api_key: str = "test-secret") -> TestClient:
        return TestClient(
            create_app(data_dir=self.data_dir, index_scope=scope, api_key=api_key)
        )

    def test_requires_api_key(self):
        self.write_chunks("production_chunks.json", [])
        client = self.client()
        response = client.post(
            "/cases/retrieve",
            json={"content": "测试广告", "industry": "通用"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], -1)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"]))

    def test_health_reports_missing_key_and_stable_index_version(self):
        self.write_chunks("production_chunks.json", [])
        client_without_key = self.client(api_key="")
        missing_key_health = client_without_key.get("/health").json()

        self.assertEqual(missing_key_health["status"], "degraded")
        self.assertEqual(missing_key_health["checks"]["api_key"], "missing")
        self.assertEqual(missing_key_health["checks"]["index"], "ok")
        self.assertRegex(missing_key_health["index_version"], r"^[0-9a-f]{16}$")
        self.assertTrue(missing_key_health["loaded_at"].endswith("Z"))

        client_with_key = self.client(api_key="test-secret")
        configured_health = client_with_key.get("/health").json()
        self.assertEqual(configured_health["status"], "ok")
        self.assertEqual(configured_health["checks"]["api_key"], "configured")
        self.assertEqual(
            configured_health["index_version"],
            missing_key_health["index_version"],
        )

    def test_echoes_safe_request_id_and_exposes_index_version_in_meta(self):
        self.write_chunks("production_chunks.json", [])
        response = self.client().post(
            "/cases/retrieve",
            headers={
                "X-API-Key": "test-secret",
                "X-Request-ID": "feishu-record-rec_123",
            },
            json={"content": "测试广告", "industry": "通用"},
        )

        self.assertEqual(response.headers["X-Request-ID"], "feishu-record-rec_123")
        self.assertRegex(
            response.json()["data"]["retrieval_meta"]["index_version"],
            r"^[0-9a-f]{16}$",
        )

    def test_validates_request_fields(self):
        self.write_chunks("production_chunks.json", [])
        client = self.client()
        headers = {"X-API-Key": "test-secret"}

        self.assertEqual(
            client.post("/cases/retrieve", headers=headers, json={"industry": "通用"}).status_code,
            400,
        )
        self.assertEqual(
            client.post(
                "/cases/retrieve",
                headers=headers,
                json={"content": "测试", "industry": "其他"},
            ).status_code,
            400,
        )
        self.assertEqual(
            client.post(
                "/cases/retrieve",
                headers=headers,
                json={"content": "测试", "industry": "通用", "top_k": 6},
            ).status_code,
            400,
        )
        malformed = client.post(
            "/cases/retrieve",
            headers={**headers, "Content-Type": "application/json"},
            content="{invalid json",
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(
            malformed.json(),
            {
                "code": -1,
                "msg": "请求体必须是有效 JSON 对象",
                "data": None,
            },
        )

    def test_deduplicates_chunks_and_adapts_full_case(self):
        case = self.write_case(
            "structured",
            "official_case_001",
            approved=True,
            source_type="official_typical_case",
        )
        self.write_chunks(
            "production_chunks.json",
            [
                self.chunk(case, "case_summary", "美妆广告宣称15天见效"),
                self.chunk(case, "regulatory_logic", "监管机关认定15天见效没有依据"),
            ],
        )

        response = self.client().post(
            "/cases/retrieve",
            headers={"X-API-Key": "test-secret"},
            json={
                "content": "15天见效",
                "industry": "美妆",
                "platform": ["小红书"],
                "top_k": 3,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data"]["retrieval_meta"]["returned"], 1)
        result = payload["data"]["cases"][0]
        self.assertEqual(result["case_id"], "official_case_001")
        self.assertEqual(result["ruling"], "罚款1万元")
        self.assertEqual(result["legal_basis"], ["《中华人民共和国广告法》"])
        self.assertEqual(result["score_type"], "bm25")
        self.assertIsNone(result["similarity"])
        self.assertFalse(result["candidate_data"])
        self.assertTrue(
            {
                "case_id",
                "title",
                "risk_level",
                "violation_type",
                "risk_dimensions",
                "score",
                "source_name",
                "source_url",
                "candidate_data",
                "content_snippet",
                "ruling",
                "regulatory_logic",
                "legal_basis",
            }.issubset(result)
        )

    def test_empty_production_index_never_falls_back_to_candidates(self):
        candidate = self.write_case(
            "structured_candidates",
            "candidate_case_001",
            approved=False,
            source_type="manual_compilation_pending_source_verification",
            industry="普通食品",
        )
        self.write_chunks("production_chunks.json", [])
        self.write_chunks(
            "candidate_chunks.json",
            [self.chunk(candidate, "case_summary", "普通食品降血糖")],
        )
        self.write_chunks("sector_candidate_chunks.json", [])

        response = self.client("production").post(
            "/cases/retrieve",
            headers={"X-API-Key": "test-secret"},
            json={"content": "普通食品降血糖", "industry": "保健食品"},
        )

        self.assertEqual(response.json()["data"]["cases"], [])
        self.assertEqual(
            response.json()["data"]["retrieval_meta"]["index_scope"],
            "production",
        )

    def test_candidate_scope_is_explicitly_marked(self):
        candidate = self.write_case(
            "structured_candidates",
            "candidate_case_001",
            approved=False,
            source_type="manual_compilation_pending_source_verification",
            industry="普通食品",
        )
        self.write_chunks(
            "candidate_chunks.json",
            [self.chunk(candidate, "case_summary", "普通食品降血糖")],
        )
        self.write_chunks("sector_candidate_chunks.json", [])

        response = self.client("candidate").post(
            "/cases/retrieve",
            headers={"X-API-Key": "test-secret"},
            json={"content": "普通食品降血糖", "industry": "保健食品"},
        )

        result = response.json()["data"]["cases"][0]
        self.assertTrue(result["candidate_data"])
        self.assertFalse(result["approved_for_rag"])
        self.assertEqual(
            response.json()["data"]["retrieval_meta"]["index_scope"],
            "candidate",
        )

    def test_specific_industry_does_not_return_cross_industry_case(self):
        food_case = self.write_case(
            "structured",
            "official_food_case",
            approved=True,
            source_type="official_typical_case",
            industry="普通食品",
        )
        self.write_chunks(
            "production_chunks.json",
            [
                self.chunk(
                    food_case,
                    "case_summary",
                    "普通食品广告存在虚假宣传和疾病治疗功效宣传",
                )
            ],
        )

        response = self.client().post(
            "/cases/retrieve",
            headers={"X-API-Key": "test-secret"},
            json={
                "content": "游戏抽奖概率未公示，涉嫌虚假宣传",
                "industry": "游戏",
                "platform": ["抖音"],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["cases"], [])

    def test_specific_industry_always_allows_general_cases(self):
        for industry in ("美妆", "游戏", "保健食品"):
            with self.subTest(industry=industry):
                self.assertTrue(
                    case_matches_industry(
                        industry,
                        {"industry": "通用"},
                        {},
                    )
                )

    def test_health_food_request_can_retrieve_verified_ordinary_food_case(self):
        food_case = self.write_case(
            "structured",
            "official_food_case",
            approved=True,
            source_type="official_typical_case",
            industry="普通食品",
        )
        self.write_chunks(
            "production_chunks.json",
            [
                self.chunk(
                    food_case,
                    "case_summary",
                    "普通食品广告宣称可以降血糖和治疗高血压",
                )
            ],
        )

        response = self.client().post(
            "/cases/retrieve",
            headers={"X-API-Key": "test-secret"},
            json={
                "content": "产品宣称降血糖并治疗高血压",
                "industry": " 保健食品 ",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [case["case_id"] for case in response.json()["data"]["cases"]],
            ["official_food_case"],
        )

    def test_production_eligibility_is_filtered_before_top_k(self):
        invalid_case = self.write_case(
            "structured",
            "unapproved_case",
            approved=False,
            source_type="official_typical_case",
        )
        valid_case = self.write_case(
            "structured",
            "approved_case",
            approved=True,
            source_type="official_typical_case",
        )
        self.write_chunks(
            "production_chunks.json",
            [
                self.chunk(
                    invalid_case,
                    "case_summary",
                    "美妆广告宣称十五天见效十五天见效十五天见效",
                ),
                self.chunk(
                    valid_case,
                    "case_summary",
                    "美妆产品宣称十五天见效",
                ),
            ],
        )

        response = self.client().post(
            "/cases/retrieve",
            headers={"X-API-Key": "test-secret"},
            json={
                "content": "十五天见效",
                "industry": "美妆",
                "top_k": 1,
            },
        )

        cases = response.json()["data"]["cases"]
        self.assertEqual([case["case_id"] for case in cases], ["approved_case"])

    def test_relative_score_threshold_removes_weak_tail_matches(self):
        real_estate_case = self.write_case(
            "structured",
            "real_estate_case",
            approved=True,
            source_type="official_typical_case",
            industry="房地产",
        )
        medical_case = self.write_case(
            "structured",
            "medical_case",
            approved=True,
            source_type="official_typical_case",
            industry="医疗服务",
        )
        self.write_chunks(
            "production_chunks.json",
            [
                self.chunk(
                    real_estate_case,
                    "case_summary",
                    "房地产广告承诺升值并宣传尚未纳入规划的交通商业医疗配套",
                ),
                self.chunk(
                    medical_case,
                    "case_summary",
                    "医疗机构发布互联网宣传内容",
                ),
            ],
        )

        response = self.client().post(
            "/cases/retrieve",
            headers={"X-API-Key": "test-secret"},
            json={
                "content": "房地产广告承诺升值并宣传尚未纳入规划的医疗商业配套",
                "industry": "通用",
                "top_k": 3,
            },
        )

        self.assertEqual(
            [case["case_id"] for case in response.json()["data"]["cases"]],
            ["real_estate_case"],
        )

    def test_retrieve_reports_broken_index_as_degraded_service(self):
        self.write_chunks("production_chunks.json", [])
        (self.data_dir / "chunks/production_chunks.json").write_text(
            "{invalid json",
            encoding="utf-8",
        )
        client = self.client()

        response = client.post(
            "/cases/retrieve",
            headers={"X-API-Key": "test-secret"},
            json={"content": "游戏充值", "industry": "游戏"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "code": -1,
                "msg": "案例检索服务暂不可用",
                "data": {"cases": []},
            },
        )
        self.assertEqual(client.get("/health").json()["status"], "degraded")

    def test_search_returns_standard_contract_and_real_similarity(self):
        case = self.write_case(
            "structured",
            "public_game_case",
            approved=True,
            source_type="official_typical_case",
        )
        case["industry"] = "游戏"
        case["facts_summary"] = "游戏广告承诺充值赠送宠物，但活动条件没有清楚说明。"
        (self.data_dir / "structured/public_game_case.json").write_text(
            json.dumps(case, ensure_ascii=False),
            encoding="utf-8",
        )
        self.write_chunks(
            "production_chunks.json",
            [self.chunk(case, "case_summary", "游戏广告承诺充值赠送宠物")],
        )
        client = self.client()
        request = {
            "query": "充3元送一只宠物",
            "industry": "游戏",
            "risk_level": "中",
            "opinion_type": "需补资料",
            "matched_rules": [
                {"rule_id": "GAME-AD-002", "dimension": "虚假宣传"}
            ],
            "top_k": 3,
        }

        tenant_a = client.post(
            "/search",
            headers={"X-API-Key": "test-secret"},
            json={"tenant_id": "tenant_company_a", **request},
        ).json()
        tenant_b = client.post(
            "/search",
            headers={"X-API-Key": "test-secret"},
            json={"tenant_id": "tenant_company_b", **request},
        ).json()

        result = tenant_a["data"]["cases"][0]
        self.assertEqual(result["case_id"], "public_game_case")
        self.assertGreater(result["similarity"], 0)
        self.assertLessEqual(result["similarity"], 1)
        self.assertEqual(result["penalty_result"], "罚款1万元")
        self.assertEqual(tenant_b["data"]["cases"][0]["case_id"], "public_game_case")

    def test_search_filters_private_cases_before_scoring(self):
        tenant_a_case = self.write_case(
            "structured",
            "tenant_a_case",
            approved=True,
            source_type="tenant_case",
            scope="tenant",
            tenant_id="tenant_company_a",
        )
        tenant_a_case["facts_summary"] = "星芒礼包仅供甲企业会员使用。"
        tenant_a_case["source_url"] = None
        tenant_a_case["source_verification_status"] = "tenant_verified"
        (self.data_dir / "structured/tenant_a_case.json").write_text(
            json.dumps(tenant_a_case, ensure_ascii=False),
            encoding="utf-8",
        )
        self.write_chunks(
            "production_chunks.json",
            [self.chunk(tenant_a_case, "case_summary", "星芒礼包甲企业会员")],
        )
        client = self.client()
        request = {
            "query": "星芒礼包会员",
            "industry": "通用",
            "matched_rules": [],
            "top_k": 3,
        }

        owner = client.post(
            "/search",
            headers={"X-API-Key": "test-secret"},
            json={"tenant_id": "tenant_company_a", **request},
        ).json()
        other = client.post(
            "/search",
            headers={"X-API-Key": "test-secret"},
            json={"tenant_id": "tenant_company_b", **request},
        ).json()

        self.assertEqual(owner["data"]["cases"][0]["case_id"], "tenant_a_case")
        self.assertEqual(other["data"]["cases"], [])

    def test_search_unrelated_query_and_index_failure_return_empty_array(self):
        case = self.write_case(
            "structured",
            "public_game_case",
            approved=True,
            source_type="official_typical_case",
        )
        self.write_chunks(
            "production_chunks.json",
            [self.chunk(case, "case_summary", "游戏充值赠送宠物")],
        )
        client = self.client()
        response = client.post(
            "/search",
            headers={"X-API-Key": "test-secret"},
            json={
                "tenant_id": "tenant_company_a",
                "query": "量子火箭发动机推力校准",
                "industry": "航空航天",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["cases"], [])

        (self.data_dir / "chunks/production_chunks.json").write_text(
            "{invalid json",
            encoding="utf-8",
        )
        degraded_client = self.client()
        degraded = degraded_client.post(
            "/search",
            headers={"X-API-Key": "test-secret"},
            json={
                "tenant_id": "tenant_company_a",
                "query": "游戏充值",
                "industry": "游戏",
            },
        )
        self.assertEqual(degraded.status_code, 200)
        self.assertEqual(degraded.json()["data"]["cases"], [])
        self.assertEqual(degraded_client.get("/health").json()["status"], "degraded")


if __name__ == "__main__":
    unittest.main()
