# -*- coding: utf-8 -*-
"""Run a local mock LLM judgment demo through the existing rule engine."""

import json
from pathlib import Path

from audit_api import audit_endpoint


def main():
    project_base = Path(__file__).resolve().parents[1]
    payload = {
        "record_id": "rec_llm_mock_demo",
        "mode": "标准",
        "fields": {
            "①运营·物料编号": "AD-MOCK-001",
            "①运营·行业领域": "美妆",
            "①运营·物料内容": "15天见效，全网第一，焕发新生",
            "①美妆·物料类型": "Banner",
            "①美妆·投放平台": ["抖音"],
            "①美妆·产品品类": "护肤",
            "①美妆·产品备案名称": "某某精华液",
            "①美妆·核心宣称功效": "改善肤色",
            "①美妆·物料涉及场景": "新品推广",
        },
    }
    response = audit_endpoint(payload, base_dir=project_base)
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
