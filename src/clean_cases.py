import argparse
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen


DEFAULT_RAW_TEXT_DIR = Path("data/raw_text")
DEFAULT_STRUCTURED_DIR = Path("data/structured")
DEFAULT_STRUCTURED_SAMPLES_DIR = Path("data/structured_samples")
DEFAULT_PROMPT_PATH = Path("prompts/clean_case_prompt.md")
DEFAULT_REPORTS_DIR = Path("data/reports")
DEFAULT_MODEL = "gpt-5.5"
MAX_RETRIES = 2

RISK_DIMENSIONS = [
    "虚假宣传",
    "绝对化用语",
    "涉医疗宣传",
    "保健食品违规宣传",
    "化妆品医疗化宣传",
    "广告引证内容不规范",
    "广告可识别性不足",
    "房地产广告误导",
    "价格促销误导",
    "未成年人保护",
    "平台准入/资质不符",
    "广告代言不合规",
    "用户评价/种草误导",
    "其他",
]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    request_id: str
    model: str


LLMRequester = Callable[[str, str, str, str], LLMResponse]


def load_prompt(path: Path = DEFAULT_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def render_prompt(prompt_template: str, case_text: str) -> str:
    return prompt_template.replace("{{case_text}}", case_text)


def extract_quoted_claims(text: str) -> list[str]:
    claims = re.findall(r"[“\"]([^”\"]{2,80})[”\"]", text)
    seen = set()
    unique = []
    for claim in claims:
        claim = claim.strip()
        if claim and claim not in seen:
            unique.append(claim)
            seen.add(claim)
    return unique


def infer_risk_dimensions(text: str) -> list[str]:
    risks = []
    if any(keyword in text for keyword in ["绝对化", "国家级", "最高级", "最佳", "第一"]):
        risks.append("绝对化用语")
    if any(keyword in text for keyword in ["虚假", "引人误解", "与实际不符"]):
        risks.append("虚假宣传")
    if any(keyword in text for keyword in ["医疗", "治疗", "疗效", "疾病", "诊疗"]):
        risks.append("涉医疗宣传")
    if any(keyword in text for keyword in ["普通食品"]) and any(
        keyword in text for keyword in ["降血糖", "降血压", "降血脂", "治疗", "疗效"]
    ):
        risks.append("涉医疗宣传")
    if "保健食品" in text:
        risks.append("保健食品违规宣传")
    if any(keyword in text for keyword in ["化妆品", "护肤品"]) and any(
        keyword in text for keyword in ["治疗", "医疗", "修复疾病"]
    ):
        risks.append("化妆品医疗化宣传")
    if any(keyword in text for keyword in ["用户评价", "种草", "达人推荐"]):
        risks.append("用户评价/种草误导")
    if any(keyword in text for keyword in ["价格", "促销", "原价"]):
        risks.append("价格促销误导")
    return list(dict.fromkeys(risks)) or ["其他"]


def parse_penalty_amount(text: str) -> int | float | None:
    match = re.search(r"罚款\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万元|元)?", text)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    if match.group(2) == "万元":
        value *= 10000
    return int(value) if value.is_integer() else value


def infer_legal_basis(text: str) -> tuple[list[str], str]:
    basis = []
    notes = []
    if "广告法" in text:
        basis.append("《中华人民共和国广告法》")
        if not re.search(r"广告法[^\n。；,，]*第[一二三四五六七八九十百0-9]+条", text):
            notes.append("待人工补充条款编号")
    return basis, "；".join(notes)


def compact_summary(text: str, limit: int = 160) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:limit]


def mock_llm_clean(raw: dict[str, Any], prompt: str) -> dict[str, Any]:
    text = raw.get("case_text", "")
    claims = extract_quoted_claims(text)
    risks = infer_risk_dimensions(text)
    penalty_amount = parse_penalty_amount(text)
    legal_basis, notes = infer_legal_basis(text)
    party_name = "某公司" if "某公司" in text else ""
    ad_channel = "互联网广告" if "互联网" in text else ""
    title = raw.get("title") or "待人工补充标题"
    facts_summary = compact_summary(text)
    regulatory_logic = "监管机关认为广告宣传内容可能误导消费者或违反广告监管要求。"
    if "绝对化用语" in risks:
        regulatory_logic = "监管机关认为广告使用国家级、最佳等绝对化表述，违反广告用语限制。"
    if "涉医疗宣传" in risks:
        regulatory_logic = "监管机关认为广告涉及医疗、治疗或疾病功效宣传，容易误导消费者。"
    vector_text = (
        f"{party_name or '当事人'}通过{ad_channel or '广告'}发布宣传内容，"
        f"涉及{ '、'.join(risks) }风险；主要宣称为"
        f"{ '；'.join(claims) if claims else facts_summary }。"
    )
    review_status = "pending_review"

    return {
        "case_id": raw["case_id"],
        "title": title,
        "source_type": raw.get("source_type", ""),
        "source_name": raw.get("source_name", ""),
        "source_url": raw.get("source_url", ""),
        "publish_date": "",
        "decision_date": "",
        "penalty_authority": "",
        "party_name": party_name,
        "region": "",
        "industry": "",
        "product_or_service": "",
        "ad_channel": ad_channel,
        "risk_dimensions": risks,
        "illegal_claims": claims or [facts_summary],
        "facts_summary": facts_summary,
        "legal_basis": legal_basis,
        "penalty_result": f"罚款{penalty_amount:g}元" if penalty_amount is not None else "",
        "penalty_amount": penalty_amount,
        "regulatory_logic": regulatory_logic,
        "mapped_rule_ids": [],
        "keywords": sorted(set(risks + claims)),
        "vector_text": vector_text,
        "rag_chunk_type": "case_summary",
        "review_status": review_status,
        "notes": notes,
        "raw_text_path": raw.get("raw_text_path", ""),
        "raw_html_path": raw.get("raw_html_path", ""),
    }


def api_key_for(provider: str, env: dict[str, str]) -> str | None:
    if provider == "openai":
        return env.get("OPENAI_API_KEY") or None
    if provider == "anthropic":
        return env.get("ANTHROPIC_API_KEY") or None
    return None


def model_for(provider: str, env: dict[str, str]) -> str:
    if env.get("LLM_MODEL"):
        return env["LLM_MODEL"]
    if provider == "anthropic":
        return "claude-sonnet-4-5"
    return DEFAULT_MODEL


def post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=90) as response:
        body = json.loads(response.read().decode("utf-8"))
        request_id = response.headers.get("x-request-id") or body.get("id") or str(uuid.uuid4())
        return body, request_id


def extract_openai_text(body: dict[str, Any]) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    texts: list[str] = []
    for item in body.get("output", []):
        for content in item.get("content", []):
            if isinstance(content.get("text"), str):
                texts.append(content["text"])
    return "\n".join(texts)


def extract_anthropic_text(body: dict[str, Any]) -> str:
    texts = []
    for item in body.get("content", []):
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            texts.append(item["text"])
    return "\n".join(texts)


def request_openai(model: str, prompt: str, api_key: str) -> LLMResponse:
    body, request_id = post_json(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}"},
        payload={"model": model, "input": prompt},
    )
    return LLMResponse(text=extract_openai_text(body), request_id=body.get("id") or request_id, model=model)


def request_anthropic(model: str, prompt: str, api_key: str) -> LLMResponse:
    body, request_id = post_json(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        payload={
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    return LLMResponse(text=extract_anthropic_text(body), request_id=body.get("id") or request_id, model=model)


def default_llm_requester(provider: str, model: str, prompt: str, api_key: str) -> LLMResponse:
    if provider == "openai":
        return request_openai(model, prompt, api_key)
    if provider == "anthropic":
        return request_anthropic(model, prompt, api_key)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append_llm_run(
    reports_dir: Path,
    *,
    case_id: str,
    provider: str,
    model: str,
    request_id: str,
    attempt: int,
) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": timestamp(),
        "case_id": case_id,
        "provider": provider,
        "model": model,
        "request_id": request_id,
        "attempt": attempt,
    }
    with (reports_dir / "llm_runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_failed_output(
    reports_dir: Path,
    *,
    case_id: str,
    provider: str,
    attempt: int,
    raw_output: str,
) -> Path:
    failed_dir = reports_dir / "failed_outputs"
    failed_dir.mkdir(parents=True, exist_ok=True)
    safe_case_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", case_id)
    path = failed_dir / f"{safe_case_id}__{provider}__attempt{attempt}__{int(time.time() * 1000)}.txt"
    path.write_text(raw_output, encoding="utf-8")
    return path


def parse_structured_json(raw_output: str) -> dict[str, Any]:
    parsed = json.loads(raw_output)
    if not isinstance(parsed, dict):
        raise ValueError("LLM output JSON must be an object.")
    return parsed


def normalize_structured_case(structured: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(structured)
    normalized.setdefault("case_id", raw["case_id"])
    normalized.setdefault("title", raw.get("title", ""))
    normalized.setdefault("source_type", raw.get("source_type", ""))
    normalized.setdefault("source_name", raw.get("source_name", ""))
    normalized.setdefault("source_url", raw.get("source_url", ""))
    normalized.setdefault("publish_date", "")
    normalized.setdefault("decision_date", "")
    normalized.setdefault("penalty_authority", "")
    normalized.setdefault("party_name", "")
    normalized.setdefault("region", "")
    normalized.setdefault("industry", "")
    normalized.setdefault("product_or_service", "")
    normalized.setdefault("ad_channel", "")
    normalized.setdefault("risk_dimensions", [])
    normalized.setdefault("illegal_claims", [])
    normalized.setdefault("facts_summary", "")
    normalized.setdefault("legal_basis", [])
    normalized.setdefault("penalty_result", "")
    normalized.setdefault("penalty_amount", None)
    normalized.setdefault("regulatory_logic", "")
    normalized.setdefault("mapped_rule_ids", [])
    normalized.setdefault("keywords", [])
    normalized.setdefault("vector_text", "")
    normalized.setdefault("rag_chunk_type", "case_summary")
    normalized.setdefault("review_status", "pending_review")
    normalized.setdefault("notes", "")
    normalized.setdefault("raw_text_path", raw.get("raw_text_path", ""))
    normalized.setdefault("raw_html_path", raw.get("raw_html_path", ""))
    return normalized


def output_dir_for_raw(raw: dict[str, Any], structured_dir: Path, structured_samples_dir: Path) -> Path:
    if raw.get("source_type") == "offline_sample":
        return structured_samples_dir
    return structured_dir


def clean_one(
    raw_text_path: Path,
    structured_dir: Path,
    structured_samples_dir: Path,
    prompt_template: str,
    mode: str,
    reports_dir: Path,
    env: dict[str, str],
    llm_requester: LLMRequester,
    max_retries: int = MAX_RETRIES,
) -> Path | None:
    raw = json.loads(raw_text_path.read_text(encoding="utf-8"))
    output_dir = output_dir_for_raw(raw, structured_dir, structured_samples_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{raw['case_id']}.json"
    if output_path.exists():
        return None
    prompt = render_prompt(prompt_template, raw.get("case_text", ""))
    provider = mode
    api_key = api_key_for(provider, env)
    if provider not in {"openai", "anthropic"} or not api_key:
        structured = mock_llm_clean(raw, prompt)
        output_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    model = model_for(provider, env)
    for attempt in range(1, max_retries + 2):
        response = llm_requester(provider, model, prompt, api_key)
        append_llm_run(
            reports_dir,
            case_id=raw["case_id"],
            provider=provider,
            model=response.model,
            request_id=response.request_id,
            attempt=attempt,
        )
        try:
            structured = normalize_structured_case(parse_structured_json(response.text), raw)
        except (json.JSONDecodeError, ValueError):
            save_failed_output(
                reports_dir,
                case_id=raw["case_id"],
                provider=provider,
                attempt=attempt,
                raw_output=response.text,
            )
            continue
        output_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path
    return None


def run(
    raw_text_dir: Path = DEFAULT_RAW_TEXT_DIR,
    structured_dir: Path = DEFAULT_STRUCTURED_DIR,
    structured_samples_dir: Path = DEFAULT_STRUCTURED_SAMPLES_DIR,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    mode: str | None = None,
    llm_mode: str | None = None,
    env: dict[str, str] | None = None,
    llm_requester: LLMRequester = default_llm_requester,
    max_retries: int = MAX_RETRIES,
) -> list[Path]:
    prompt = load_prompt(prompt_path)
    env = dict(os.environ if env is None else env)
    selected_mode = mode or llm_mode or env.get("LLM_PROVIDER") or "mock"
    outputs = []
    for raw_text_path in sorted(raw_text_dir.glob("*.json")):
        path = clean_one(
            raw_text_path,
            structured_dir,
            structured_samples_dir,
            prompt,
            selected_mode,
            reports_dir,
            env,
            llm_requester,
            max_retries=max_retries,
        )
        if path:
            outputs.append(path)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean raw case text into structured JSON.")
    parser.add_argument("--raw-text-dir", type=Path, default=DEFAULT_RAW_TEXT_DIR)
    parser.add_argument("--structured-dir", type=Path, default=DEFAULT_STRUCTURED_DIR)
    parser.add_argument("--structured-samples-dir", type=Path, default=DEFAULT_STRUCTURED_SAMPLES_DIR)
    parser.add_argument("--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--mode", default=None, choices=["mock", "openai", "anthropic"])
    parser.add_argument("--llm-mode", default=None, choices=["mock", "openai", "anthropic"])
    args = parser.parse_args()

    outputs = run(
        args.raw_text_dir,
        args.structured_dir,
        args.structured_samples_dir,
        args.prompt_path,
        args.reports_dir,
        mode=args.mode,
        llm_mode=args.llm_mode,
    )
    for path in outputs:
        print(path)
    if not outputs:
        print("No new structured files written.")


if __name__ == "__main__":
    main()
