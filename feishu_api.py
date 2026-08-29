"""
飞书开放平台 API 封装 — 多维表格读写
"""
import time
import logging
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, BITABLE_TABLE_ID
from error_handling import OperationError
from logging_utils import context_fields

BASE_URL = "https://open.feishu.cn/open-apis"
DEFAULT_TIMEOUT = 8
logger = logging.getLogger(__name__)


class FeishuAPIError(OperationError):
    def __init__(self, category: str, *, retryable: bool, code=None, message="feishu request failed"):
        super().__init__(category, retryable=retryable, message=message)
        self.code = code

# 缓存 token，避免频繁请求
_token_cache = {"token": None, "expire": 0}


def get_tenant_access_token():
    """获取 tenant_access_token（应用身份令牌）"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expire"]:
        return _token_cache["token"]

    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    response = requests.post(url, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }, timeout=DEFAULT_TIMEOUT)
    data = _response_data(response)

    token = data["tenant_access_token"]
    expire = data.get("expire", 7200)
    _token_cache["token"] = token
    _token_cache["expire"] = now + expire - 300  # 提前5分钟刷新
    return token


def _headers():
    """构建请求头"""
    return {
        "Authorization": f"Bearer {get_tenant_access_token()}",
        "Content-Type": "application/json",
    }


def _response_data(response) -> dict:
    """Parse a Feishu response and preserve retry/permanent error semantics."""
    status_code = int(getattr(response, "status_code", 200) or 200)
    try:
        data = response.json()
    except Exception as exc:
        if status_code == 429:
            raise FeishuAPIError("rate_limited", retryable=True, code=status_code) from exc
        if status_code >= 500:
            raise FeishuAPIError("transient_network", retryable=True, code=status_code) from exc
        raise FeishuAPIError("engine_unavailable", retryable=True, code=status_code) from exc
    if status_code >= 400 or data.get("code") != 0:
        _raise_api_error(data, status_code)
    return data


def list_records(filter_formula=None, page_size=100, page_token=None):
    """
    读取多维表格记录
    filter_formula: 筛选公式，如 CurrentValue.[审核状态]="待人工复核"
    """
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records"

    params = {"page_size": page_size}
    if page_token:
        params["page_token"] = page_token

    body = {}
    if filter_formula:
        body["filter"] = filter_formula

    # 用 GET + query params（飞书bitable list接口）
    response = requests.get(
        url, headers=_headers(), params=params, timeout=DEFAULT_TIMEOUT,
    )
    data = _response_data(response)

    items = data.get("data", {}).get("items", [])
    has_more = data.get("data", {}).get("has_more", False)
    next_token = data.get("data", {}).get("page_token", None)

    return items, has_more, next_token


def list_all_records(filter_formula=None):
    """读取所有记录（自动翻页）"""
    all_items = []
    page_token = None

    while True:
        items, has_more, page_token = list_records(
            filter_formula=filter_formula,
            page_token=page_token
        )
        all_items.extend(items)
        if not has_more:
            break

    return all_items


def get_record(record_id):
    """读取单条记录"""
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records/{record_id}"
    response = requests.get(url, headers=_headers(), timeout=DEFAULT_TIMEOUT)
    data = _response_data(response)

    return data.get("data", {}).get("record", {})


def update_record(record_id, fields):
    """
    更新多维表格记录
    record_id: 记录ID
    fields: 要更新的字段字典，如 {"审核状态": "已通过", "物料裁决": "通过"}
    """
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records/{record_id}"
    body = {"fields": fields}

    response = requests.put(
        url, headers=_headers(), json=body, timeout=DEFAULT_TIMEOUT,
    )
    data = _response_data(response)

    return data.get("data", {}).get("record", {})


def search_records(filter_formula, page_size=100):
    """
    使用 search 接口筛选记录（支持复杂筛选条件）
    filter_formula 示例: 'AND(CurrentValue.[审核状态]="待人工复核")'
    """
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records/search"

    body = {
        "page_size": page_size,
        "filter": {
            "conjunction": "and",
            "conditions": []
        }
    }

    # 简单场景：直接用 list_records
    # search 接口用于更复杂的筛选需求，暂不使用
    pass


# === 组织架构：按部门名称查成员 ===

_dept_cache: dict = {}   # {dept_name: [open_id, ...]}，缓存 10 分钟


def get_dept_open_ids(dept_name: str) -> list:
    """
    按部门名称返回该部门所有成员的 open_id 列表。
    需要应用已开通权限：contact:contact.base:readonly
    实现：从根部门("0")做 BFS 遍历整棵子部门树，按名称匹配。
    若组织架构查询失败或部门为空，自动兜底到 config.LEGAL_OPEN_IDS。
    """
    import time
    cache_key = dept_name
    cached = _dept_cache.get(cache_key)
    if cached and time.time() < cached["expire"]:
        return cached["ids"]

    token = get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    def _list_children(parent_id: str) -> list:
        """列出 parent_id 下所有直接子部门"""
        items = []
        page_token = None
        while True:
            params = {
                "user_id_type": "open_id",
                "department_id_type": "open_department_id",
                "parent_department_id": parent_id,
                "page_size": 50,
            }
            if page_token:
                params["page_token"] = page_token
            try:
                resp = _response_data(requests.get(
                    f"{BASE_URL}/contact/v3/departments",
                    headers=headers,
                    params=params,
                    timeout=DEFAULT_TIMEOUT,
                ))
            except FeishuAPIError as exc:
                if exc.retryable:
                    raise
                logger.warning(
                    "event=department_list_degraded parent=%s error_category=%s feishu_code=%s",
                    parent_id, exc.category, exc.code,
                )
                break
            items.extend(resp.get("data", {}).get("items", []))
            if not resp.get("data", {}).get("has_more"):
                break
            page_token = resp.get("data", {}).get("page_token")
        return items

    # 第一步：BFS 遍历部门树，按名称匹配
    dept_id = None
    queue = ["0"]  # 从根部门开始
    while queue and not dept_id:
        parent_id = queue.pop(0)
        children = _list_children(parent_id)
        for dept in children:
            if dept.get("name") == dept_name:
                dept_id = dept.get("open_department_id")
                break
            # 子部门入队，继续向下搜索
            child_id = dept.get("open_department_id")
            if child_id:
                queue.append(child_id)

    if not dept_id:
        logger.warning("event=legal_department_not_found department=%s", dept_name)
        import config
        return list(getattr(config, "LEGAL_OPEN_IDS", []))

    # 第二步：拉取该部门成员
    open_ids = []
    page_token = None
    while True:
        params = {
            "user_id_type": "open_id",
            "department_id_type": "open_department_id",
            "department_id": dept_id,
            "page_size": 50,
        }
        if page_token:
            params["page_token"] = page_token
        try:
            members_resp = _response_data(requests.get(
                f"{BASE_URL}/contact/v3/users",
                headers=headers,
                params=params,
                timeout=DEFAULT_TIMEOUT,
            ))
        except FeishuAPIError as exc:
            if exc.retryable:
                raise
            logger.warning(
                "event=department_members_degraded department=%s error_category=%s feishu_code=%s",
                dept_name, exc.category, exc.code,
            )
            import config
            return list(getattr(config, "LEGAL_OPEN_IDS", []))
        for u in members_resp.get("data", {}).get("items", []):
            oid = u.get("open_id")
            if oid:
                open_ids.append(oid)
        if not members_resp.get("data", {}).get("has_more"):
            break
        page_token = members_resp.get("data", {}).get("page_token")

    if not open_ids:
        logger.warning("event=legal_department_empty department=%s", dept_name)
        import config
        return list(getattr(config, "LEGAL_OPEN_IDS", []))

    _dept_cache[cache_key] = {"ids": open_ids, "expire": time.time() + 600}
    logger.info("event=legal_department_loaded department=%s member_count=%s", dept_name, len(open_ids))
    return open_ids


def upload_image(image_bytes: bytes) -> str:
    """
    把图片字节上传到飞书 IM，返回 img_key（供卡片 img 元素使用）。
    """
    import io
    token = get_tenant_access_token()
    resp = requests.post(
        f"{BASE_URL}/im/v1/images",
        headers={"Authorization": f"Bearer {token}"},
        data={"image_type": "message"},
        files={"image": ("image.png", io.BytesIO(image_bytes), "image/png")},
        timeout=30,
    )
    data = _response_data(resp)
    return data["data"]["image_key"]


def download_attachment(file_token: str) -> bytes:
    """
    下载飞书附件，返回原始字节。
    file_token 来自附件字段 [{file_token, name, type, size}, ...]。
    """
    token = get_tenant_access_token()
    resp = requests.get(
        f"{BASE_URL}/drive/v1/medias/{file_token}/download",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    status_code = int(getattr(resp, "status_code", 200) or 200)
    if status_code >= 400:
        _raise_api_error({}, status_code)
    return resp.content


def send_card(open_id: str, card: dict, *, idempotency_uuid: str) -> dict:
    """Send a card with Feishu's official request-body uuid idempotency field."""
    import json as _json
    token = get_tenant_access_token()
    try:
        response = requests.post(
            f"{BASE_URL}/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "receive_id": open_id,
                "msg_type": "interactive",
                "content": _json.dumps(card, ensure_ascii=False),
                "uuid": idempotency_uuid,
            },
            timeout=8,
        )
    except Exception as exc:
        name = exc.__class__.__name__.lower()
        retryable = "timeout" in name or "connection" in name
        raise FeishuAPIError(
            "transient_network" if retryable else "engine_unavailable",
            retryable=True,
        ) from exc

    status_code = getattr(response, "status_code", 200)
    try:
        data = response.json()
    except Exception as exc:
        raise FeishuAPIError(
            "transient_network" if status_code >= 500 else "invalid_card",
            retryable=status_code >= 500,
            code=status_code,
        ) from exc

    code = data.get("code")
    if status_code == 429 or code in {99991400, 99991401, 99991663, 99991664}:
        raise FeishuAPIError("rate_limited", retryable=True, code=code or status_code)
    if status_code >= 500:
        raise FeishuAPIError("transient_network", retryable=True, code=code or status_code)
    if code != 0:
        category = _feishu_error_category(code)
        raise FeishuAPIError(category, retryable=False, code=code)

    message_id = data.get("data", {}).get("message_id")
    headers = getattr(response, "headers", {}) or {}
    request_id = headers.get("X-Tt-Logid") or headers.get("x-tt-logid") or headers.get("X-Request-Id")
    return {"success": True, "message_id": message_id, "code": code, "request_id": request_id}


def _feishu_error_category(code) -> str:
    text = str(code or "")
    if text.startswith("230"):
        return "invalid_recipient"
    if text.startswith("200") or text.startswith("99991"):
        return "permission_denied"
    return "invalid_card"


def _raise_api_error(data: dict, status_code: int = 200):
    code = data.get("code")
    if status_code == 429 or code in {99991400, 99991401, 99991663, 99991664}:
        raise FeishuAPIError("rate_limited", retryable=True, code=code or status_code)
    if status_code in {408, 425}:
        raise FeishuAPIError("transient_network", retryable=True, code=code or status_code)
    if status_code >= 500:
        raise FeishuAPIError("transient_network", retryable=True, code=code or status_code)
    if status_code in {401, 403}:
        raise FeishuAPIError("permission_denied", retryable=False, code=code or status_code)
    raise FeishuAPIError(_feishu_error_category(code), retryable=False, code=code)


def send_card_to(open_id: str, card: dict, idempotency_key: str = "") -> bool:
    """Compatibility wrapper for old callers; new reliable delivery uses send_card()."""
    import hashlib
    import uuid
    seed = idempotency_key or hashlib.sha256(
        (open_id + repr(card)).encode("utf-8")
    ).hexdigest()
    request_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
    try:
        send_card(open_id, card, idempotency_uuid=request_uuid)
        return True
    except FeishuAPIError as exc:
        logger.error(
            "event=legacy_card_send_failed %s",
            context_fields(open_id=open_id, error_category=exc.category, feishu_code=exc.code),
        )
        return False
if __name__ == "__main__":
    from logging_utils import configure_logging
    configure_logging()
    try:
        get_tenant_access_token()
        records, _has_more, _page_token = list_records()
        logger.info("event=feishu_connectivity_check_succeeded record_count=%s", len(records))
    except Exception:
        logger.exception("event=feishu_connectivity_check_failed")
