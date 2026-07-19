import unittest

from field_mapper import map_feishu_payload


class FieldMapperFlatPayloadTests(unittest.TestCase):
    def test_maps_cosmetics_flat_payload(self):
        payload = {
            "record_id": "rec_cosm",
            "mode": "\u6807\u51c6",
            "industry": "\u7f8e\u5986",
            "content": "15\u5929\u89c1\u6548\uff0c\u5168\u7f51\u7b2c\u4e00",
            "urgency": "\u666e\u901a",
            "supplement": "\u6d4b\u8bd5",
            "platform": ["\u6296\u97f3", "\u5c0f\u7ea2\u4e66"],
            "material_type": "Banner",
            "product_category": "\u62a4\u80a4",
            "extras": {
                "\u4ea7\u54c1\u5907\u6848\u540d\u79f0": "XX\u6c34\u5149\u7cbe\u534e\u6db2",
                "\u6838\u5fc3\u5ba3\u79f0\u529f\u6548": "\u6539\u5584\u80a4\u8272",
            },
        }

        mapped = map_feishu_payload(payload)

        self.assertEqual("rec_cosm", mapped["request_id"])
        self.assertEqual("\u7f8e\u5986", mapped["context"]["industry"])
        self.assertEqual("Banner\u6587\u5b57", mapped["context"]["material_type"])
        self.assertEqual(["\u6296\u97f3", "\u5c0f\u7ea2\u4e66"], mapped["context"]["platforms"])
        self.assertEqual(["\u6539\u5584\u80a4\u8272"], mapped["context"]["core_claims"])
        self.assertEqual("XX\u6c34\u5149\u7cbe\u534e\u6db2", mapped["context"]["product_filing_name"])

    def test_maps_health_food_flat_payload(self):
        payload = {
            "record_id": "rec_hf",
            "mode": "\u6807\u51c6",
            "industry": "\u4fdd\u5065\u98df\u54c1",
            "content": "\u6bcf\u5929\u4e00\u7c92",
            "platform": ["\u6296\u97f3", "\u5929\u732b"],
            "material_type": "\u77ed\u89c6\u9891",
            "product_category": "\u7ef4\u751f\u7d20/\u77ff\u7269\u8d28",
            "extras": {
                "\u6838\u5fc3\u5ba3\u79f0\u529f\u6548": "\u6297\u6c27\u5316\u3001\u589e\u5f3a\u514d\u75ab\u529b",
                "\u4ea7\u54c1\u5907\u6848\u540d\u79f0": "XX\u724c\u7ef4C\u7247",
                "\u6279\u51c6\u6587\u53f7": "\u56fd\u98df\u5065\u5b57G20210001",
            },
        }

        mapped = map_feishu_payload(payload)

        self.assertEqual("\u77ed\u89c6\u9891\u811a\u672c", mapped["context"]["material_type"])
        self.assertEqual(["\u6297\u6c27\u5316", "\u589e\u5f3a\u514d\u75ab\u529b"], mapped["context"]["core_claims"])
        self.assertEqual("XX\u724c\u7ef4C\u7247", mapped["context"]["product_filing_name"])
        self.assertEqual("\u56fd\u98df\u5065\u5b57G20210001", mapped["context"]["approval_or_filing_number"])

    def test_maps_game_flat_payload(self):
        payload = {
            "record_id": "rec_game",
            "mode": "\u6807\u51c6",
            "industry": "\u6e38\u620f",
            "content": "\u5168\u7403\u7b2c\u4e00\u6218\u795e\u6e38\u620f",
            "platform": ["\u6296\u97f3", "B\u7ad9"],
            "material_type": "\u77ed\u89c6\u9891",
            "product_category": "MOBA",
            "extras": {
                "\u6e38\u620f\u540d\u79f0": "\u4e71\u4e16\u9738\u4e3b",
                "IP\u540d\u79f0": "\u539f\u521bIP",
            },
        }

        mapped = map_feishu_payload(payload)

        self.assertEqual("\u77ed\u89c6\u9891\u811a\u672c", mapped["context"]["material_type"])
        self.assertEqual("\u4e71\u4e16\u9738\u4e3b", mapped["context"]["game_name"])
        self.assertEqual("\u539f\u521bIP", mapped["context"]["ip_name"])

    def test_maps_canonical_payload_and_defaults_demo_tenant(self):
        payload = {
            "request_id": "req_internal_001",
            "source": "internal",
            "material": {
                "content": "新品上市，欢迎选购",
                "urgency": "普通",
                "supplemental_background": "",
            },
            "context": {
                "industry": "美妆",
                "platforms": ["抖音"],
                "material_type": "Banner",
                "product_category": "护肤",
            },
            "audit": {"requested_mode": "标准"},
            "unknown_field": "ignored",
        }

        mapped = map_feishu_payload(payload)

        self.assertEqual("adsure_demo", mapped["tenant_id"])
        self.assertEqual("req_internal_001", mapped["request_id"])
        self.assertEqual("internal", mapped["source"])
        self.assertEqual("新品上市，欢迎选购", mapped["material"]["content"])
        self.assertEqual("美妆", mapped["context"]["industry"])
        self.assertEqual(["抖音"], mapped["context"]["platforms"])
        self.assertEqual("Banner文字", mapped["context"]["material_type"])
        self.assertNotIn("unknown_field", mapped)

    def test_canonical_payload_preserves_explicit_tenant(self):
        mapped = map_feishu_payload(
            {
                "tenant_id": "tenant_example",
                "request_id": "req_internal_002",
                "material": {"content": "测试文案"},
                "context": {"industry": "游戏"},
            }
        )

        self.assertEqual("tenant_example", mapped["tenant_id"])
        self.assertEqual("req_internal_002", mapped["request_id"])


if __name__ == "__main__":
    unittest.main()
