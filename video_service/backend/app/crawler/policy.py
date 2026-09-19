"""抓取策略：robots 门禁、两级限速、姓名脱敏。

这三件事编码的是**决策**，不是实现细节，所以放在一起、单独成文件、单独测试。
改这里等于改立场，不该顺手改。
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.robotparser
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


def build_ssl_context() -> ssl.SSLContext:
    """握手用的 SSL 上下文。

    不少政府站点的证书密钥强度低于新版 OpenSSL 的默认安全级别（SECLEVEL=2），
    握手会被直接拒掉：`EE certificate key too weak`。同一个站点浏览器打得开、
    脚本打不开，差别只在这个默认值 —— 实测 samr.gov.cn 有部分节点如此，
    同一轮抓取里前十页正常、后二十页全挂。

    这里把安全级别降到 1 以接受这类证书，**但证书链、主机名、有效期的校验
    全部保留**。这和 `verify=False` 是两回事：后者是谁来都收（中间人也收），
    这里只是接受了一个弱一点的密钥。

    ⚠️ robots 探测也必须用它。否则弱证书站点的 robots.txt 会取不到，
    而「取不到 robots」按设计是**拒绝抓取** —— 一个 TLS 默认值就能让
    整个源静默失效，且失效原因看上去像是对方不许我们抓。
    """
    ctx = ssl.create_default_context()
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:  # 某些 OpenSSL 构建不支持这个写法
        logger.warning("当前 OpenSSL 不支持调整安全级别，弱证书站点可能握手失败")
    return ctx

def _build_ua() -> str:
    """构造 User-Agent。

    两条约束是踩出来的，不是推出来的：

    ① **必须是纯 ASCII。** HTTP 头按 latin-1 编码，UA 里放中文会让
       每一次请求在发出前就抛 UnicodeEncodeError。第一次真实抓取时才暴露 ——
       单元测试注入的是假客户端，从不真正发送 header，测不出这个。

    ② **默认不含邮箱。** 联系方式是好的爬虫礼仪，但 UA 会广播给每一个
       被抓的站点。把谁的邮箱公开出去是本人的选择，不该由代码替他决定。
       需要时通过 CRAWLER_CONTACT 环境变量显式提供。
    """
    import os

    contact = (os.getenv("CRAWLER_CONTACT") or "").strip()
    base = "AdsureCaseBot/0.1 (+ad-compliance research; non-commercial)"
    if not contact:
        return base
    if not contact.isascii():
        logger.warning("CRAWLER_CONTACT 含非 ASCII 字符，已忽略（HTTP 头不支持）")
        return base
    return f"AdsureCaseBot/0.1 (+ad-compliance research; contact: {contact})"


UA = _build_ua()


# ══════════════════════════════════════════════════════════════
#  robots.txt 门禁
# ══════════════════════════════════════════════════════════════


class RobotsDenied(RuntimeError):
    """robots.txt 不允许抓这个地址。

    **刻意做成异常而不是返回 False** —— 调用方必须显式处理，
    不能顺手 `if allowed:` 一带而过。
    """


class RobotsStatus(StrEnum):
    RULES = "rules"
    """拿到了 robots.txt，按其中的规则判。"""

    ABSENT = "absent"
    """站点明确没有 robots.txt（4xx）。按 RFC 9309，此时视为无限制。"""

    UNKNOWN = "unknown"
    """拿不到、或拿到的东西不是 robots.txt。状态未知，按禁止处理。"""


def looks_like_html(text: str) -> bool:
    """内容是不是 HTML 而非 robots.txt。

    很多站点用 HTML 错误页代替标准 404。把这种页面丢给 robots 解析器，
    它找不到任何 Disallow，于是**判成「允许一切」** —— 门禁就此形同虚设，
    而且不会报错。这是实测 creditchina.gov.cn 时踩到的。
    """
    head = (text or "").lstrip()[:400].lower()
    return head.startswith(("<!doctype", "<html", "<?xml")) or "<head>" in head


@dataclass
class RobotsGate:
    """robots.txt 检查与缓存。

    ⚠️ 这是**硬门禁，不提供绕过开关**。

    留了 `force=True` 这种参数，就一定会有人在赶进度的时候打开它，
    然后这个开关会永远开着。所以这里根本不提供。
    真需要抓某个 robots 禁止的页面，那是要人去跟对方沟通的事，
    不是改一个布尔值的事。
    """

    fetcher: object | None = None  # 注入 HTTP 客户端，便于测试
    _cache: dict[str, tuple[RobotsStatus, object]] = field(default_factory=dict)

    def _robots_for(self, url: str) -> tuple[RobotsStatus, object]:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._cache:
            return self._cache[origin]

        robots_url = urljoin(origin, "/robots.txt")
        try:
            text = self._fetch_text(robots_url)
        except FileNotFoundError as exc:
            # 站点明确回了 4xx —— 这是「没有规则」的肯定答复，不是失败
            logger.info("%s 没有 robots.txt（%s），按无限制处理", origin, exc)
            entry = (RobotsStatus.ABSENT, None)
            self._cache[origin] = entry
            return entry
        except Exception as exc:
            logger.warning("拉取 %s 失败：%s", robots_url, exc)
            entry = (RobotsStatus.UNKNOWN, None)
            self._cache[origin] = entry
            return entry

        if looks_like_html(text):
            logger.warning("%s 返回的是 HTML 而非 robots.txt，状态按未知处理", robots_url)
            entry = (RobotsStatus.UNKNOWN, None)
            self._cache[origin] = entry
            return entry

        rp = urllib.robotparser.RobotFileParser()
        rp.parse(text.splitlines())
        entry = (RobotsStatus.RULES, rp)
        self._cache[origin] = entry
        return entry

    def _fetch_text(self, url: str) -> str:
        if self.fetcher is not None:
            return self.fetcher(url)  # type: ignore[operator]
        import httpx

        r = httpx.get(url, headers={"User-Agent": UA}, timeout=15,
                      follow_redirects=True, verify=build_ssl_context())
        if 400 <= r.status_code < 500:
            # 用 FileNotFoundError 表达「明确不存在」，与网络故障区分开
            raise FileNotFoundError(f"HTTP {r.status_code}")
        r.raise_for_status()
        # 软 404：站点把 /robots.txt 重定向到自己的 404 页（HTTP 200），
        # 实际就是「没有 robots.txt」。按 RFC 9309 视为无限制，不应被判成 HTML 未知。
        if re.search(r"/404(?:\.html)?$|/error/?$|notfound", str(r.url), re.I):
            raise FileNotFoundError(f"robots.txt 软 404：{r.url}")
        return r.text

    def check(self, url: str) -> None:
        """允许则静默返回，否则抛 RobotsDenied。

        三种状态三种处理，**「明确没有」和「不知道」必须分开**：

          RULES   按 robots 规则判
          ABSENT  站点回了 4xx —— RFC 9309 规定此时可访问全部资源。
                  这是肯定答复「本站没有限制」，不是失败。
          UNKNOWN 网络故障、5xx、或返回的根本不是 robots.txt。
                  状态未知就按禁止处理 —— 此时继续抓既失礼，
                  也让我们说不清自己合不合规。

        早先把这两种合并成「拿不到就拒绝」，结果 samr.gov.cn 这种
        没有 robots.txt 的站点被自己的门禁挡在外面。
        """
        status, rp = self._robots_for(url)
        if status is RobotsStatus.ABSENT:
            return
        if status is RobotsStatus.UNKNOWN:
            raise RobotsDenied(
                f"无法确认 {urlparse(url).netloc} 的 robots.txt 状态，按禁止处理。\n"
                "（网络故障、5xx，或对方返回的不是 robots.txt 而是 HTML 错误页。"
                "把 HTML 当 robots 解析会解出「允许一切」，那是静默失效。）"
            )
        if not rp.can_fetch(UA, url):  # type: ignore[union-attr]
            raise RobotsDenied(f"robots.txt 不允许抓取 {url}")

    def crawl_delay(self, url: str, default: float) -> float:
        """尊重对方声明的 Crawl-delay；对方要求更慢就听对方的。"""
        status, rp = self._robots_for(url)
        if status is not RobotsStatus.RULES:
            return default
        try:
            declared = rp.crawl_delay(UA)  # type: ignore[union-attr]
        except Exception:
            declared = None
        return max(float(declared), default) if declared else default


# ══════════════════════════════════════════════════════════════
#  两级限速
# ══════════════════════════════════════════════════════════════


@dataclass
class RateLimiter:
    """两级限速，两级管的是完全不同的事，不能合并。

    **请求级（politeness）**：对同一站点两次请求的最小间隔。
        目的是不给对方服务器造成压力。这是礼貌问题。

    **案例级（capacity）**：每小时最多入库多少条案例。
        目的是匹配**人工复核产能** —— 抓得再快，没人复核的候选就是积压。
        这是产能问题，不是技术限制。

    合并成一个的话，改「抓快点」会同时把礼貌那一级也放宽，
    而那一级本来就不该动。
    """

    cases_per_hour: int = 100
    min_request_interval: float = 3.0
    quota_state_path: Path | None = None

    _last_request_at: dict[str, float] = field(default_factory=dict)
    _case_times: list[float] = field(default_factory=list)
    _sleep: object = time.sleep
    _now: object = time.monotonic
    _wall_now: object = time.time

    # ── 请求级 ────────────────────────────────────────────────

    def before_request(self, host: str, interval: float | None = None) -> float:
        """按需等待，返回实际等待秒数。"""
        gap = self.min_request_interval if interval is None else max(interval, 0.0)
        now = self._now()  # type: ignore[operator]
        last = self._last_request_at.get(host)
        waited = 0.0
        if last is not None:
            remaining = gap - (now - last)
            if remaining > 0:
                self._sleep(remaining)  # type: ignore[operator]
                waited = remaining
        self._last_request_at[host] = self._now()  # type: ignore[operator]
        return waited

    # ── 案例级 ────────────────────────────────────────────────

    def _prune(self, now: float) -> None:
        cutoff = now - 3600.0
        self._case_times = [t for t in self._case_times if t > cutoff]

    def _quota_now(self) -> float:
        # monotonic clocks cannot survive a process restart.  Persisted quota
        # state therefore uses wall-clock epoch seconds, while the in-process
        # request-delay limiter retains monotonic time.
        clock = self._wall_now if self.quota_state_path else self._now
        return float(clock())  # type: ignore[operator]

    def _load_quota_state(self) -> None:
        path = self.quota_state_path
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw = payload.get("consumed_at") if isinstance(payload, dict) else None
            if not isinstance(raw, list):
                raise ValueError("consumed_at must be a list")
            self._case_times = [float(value) for value in raw]
        except Exception as exc:
            # A corrupt state file must not silently reset the quota and allow
            # another burst.  Fail closed until a human inspects the file.
            raise RuntimeError(f"抓取配额状态文件不可读：{path}: {exc}") from exc

    def _save_quota_state(self) -> None:
        path = self.quota_state_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps({"version": 1, "consumed_at": self._case_times}, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    @contextmanager
    def _quota_lock(self):
        path = self.quota_state_path
        if path is None:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(path.name + ".lock")
        with lock_path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl
            except ImportError as exc:  # pragma: no cover - macOS/Linux target
                raise RuntimeError("持久化抓取配额需要 fcntl 文件锁") from exc
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def remaining_quota(self) -> int:
        with self._quota_lock():
            self._load_quota_state()
            self._prune(self._quota_now())
            self._save_quota_state()
            return max(0, self.cases_per_hour - len(self._case_times))

    def try_consume_case(self) -> bool:
        """入库一条案例前调用。配额用尽返回 False —— **不阻塞等待**。

        用尽时应当停下来收工，而不是挂在那里等一小时。
        长时间挂起的抓取任务没人看得住，也没法回答「现在跑到哪了」。
        """
        with self._quota_lock():
            self._load_quota_state()
            now = self._quota_now()
            self._prune(now)
            if len(self._case_times) >= self.cases_per_hour:
                self._save_quota_state()
                return False
            self._case_times.append(now)
            self._save_quota_state()
            return True


# ══════════════════════════════════════════════════════════════
#  自然人姓名脱敏
# ══════════════════════════════════════════════════════════════

# 出现这些字样基本可判定为组织而非自然人
_ORG_MARKERS = (
    "公司", "有限", "股份", "集团", "企业", "厂", "店", "中心", "医院", "诊所",
    "药房", "药店", "超市", "商行", "商贸", "经营部", "合作社", "事务所",
    "工作室", "俱乐部", "协会", "学校", "学院", "银行", "酒店", "餐厅",
    "个体工商户", "分公司", "门市", "网络科技", "电子商务", "旗舰店",
)

# 常见姓氏（含复姓）。用于判断一个短串是不是人名。
_SURNAMES = (
    "欧阳", "司马", "上官", "诸葛", "东方", "皇甫", "尉迟", "公孙", "慕容",
    "赵", "钱", "孙", "李", "周", "吴", "郑", "王", "冯", "陈", "褚", "卫",
    "蒋", "沈", "韩", "杨", "朱", "秦", "尤", "许", "何", "吕", "施", "张",
    "孔", "曹", "严", "华", "金", "魏", "陶", "姜", "戚", "谢", "邹", "喻",
    "柏", "水", "窦", "章", "云", "苏", "潘", "葛", "奚", "范", "彭", "郎",
    "鲁", "韦", "昌", "马", "苗", "凤", "花", "方", "俞", "任", "袁", "柳",
    "唐", "罗", "薛", "伍", "余", "米", "贝", "姚", "孟", "顾", "尹", "江",
    "钟", "徐", "邱", "高", "夏", "蔡", "田", "樊", "胡", "凌", "霍", "虞",
    "万", "支", "柯", "管", "卢", "莫", "房", "缪", "干", "解", "应", "宗",
    "丁", "宣", "贲", "邓", "郁", "杜", "阮", "蓝", "闵", "季", "贾", "路",
    "娄", "危", "刘", "梁", "林", "曾", "廖", "谭", "邵", "岑", "薄", "宁",
)

_CJK_NAME = re.compile(r"^[一-鿿]{2,4}$")


def is_organization(name: str) -> bool:
    return any(m in name for m in _ORG_MARKERS)


def mask_person_name(name: str) -> str:
    """自然人姓名脱敏：保留姓氏，其余掩码。张三 → 张*，欧阳修文 → 欧阳**"""
    for surname in _SURNAMES:  # 复姓排在前面，先匹配到的就是最长的
        if name.startswith(surname) and len(name) > len(surname):
            return surname + "*" * (len(name) - len(surname))
    return name[0] + "*" * (len(name) - 1) if len(name) > 1 else name


def desensitize_party(name: str) -> str:
    """处罚当事人脱敏。企业名照留，自然人姓名掩码。

    ⚠️ 判定是启发式的，必然有误差，所以**误差方向必须选对**：
        把企业名误判成人名 → 报告里少了个名字，无伤大雅
        把人名误判成企业名 → 真实姓名进了 RAG、进了给客户的报告
    后者是实打实的个人信息问题。所以拿不准时一律按自然人处理（掩码）。
    """
    name = (name or "").strip()
    if not name:
        return name
    if is_organization(name):
        return name
    if _CJK_NAME.match(name):
        return mask_person_name(name)
    # 既不像组织也不像标准中文姓名（外文名、含数字的字号等）：
    # 拿不准就掩码，宁可信息少一点。
    if len(name) <= 6 and not any(ch.isdigit() for ch in name):
        return mask_person_name(name)
    return name
