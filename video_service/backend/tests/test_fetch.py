# -*- coding: utf-8 -*-
"""传输层测试：TLS 安全级别与重试。

这两处都是「为了让抓取跑通而放宽了什么」，所以测试的重点不是
「放宽后能不能跑通」，而是**到底放宽了哪一条、有没有连带把别的也放宽**。
"""

from __future__ import annotations

import ssl

import pytest

from app.crawler.fetch import Fetcher, _is_transient
from app.crawler.policy import RateLimiter, RobotsGate, build_ssl_context


class _Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _open_gate():
    """robots 允许一切的门禁 —— 本文件测的是传输层，不测门禁。"""
    return RobotsGate(fetcher=lambda url: "User-agent: *\nAllow: /\n")


def _limiter(interval=3.0):
    clk = _Clock()
    return RateLimiter(min_request_interval=interval,
                       _sleep=clk.sleep, _now=clk.now), clk


# ══════════════════════════════════════════════════════════════
#  TLS 安全级别
# ══════════════════════════════════════════════════════════════

def test_weak_key_workaround_does_not_disable_verification():
    """降安全级别是为了接受弱密钥证书，**不是**为了不验证证书。

    这两件事很容易被一起做掉（`verify=False` 一行就能让抓取跑通），
    而那样做之后，中间人返回的任何内容都会被当成官方公示原文入库 ——
    案例库的全部价值就建立在「这确实是官方页面」上。
    """
    ctx = build_ssl_context()
    assert ctx.verify_mode is ssl.CERT_REQUIRED, "证书校验被关掉了"
    assert ctx.check_hostname is True, "主机名校验被关掉了"


def test_weak_key_workaround_still_rejects_expired_and_untrusted():
    """默认信任库与过期检查保持不变。"""
    ctx = build_ssl_context()
    default = ssl.create_default_context()
    assert ctx.get_ca_certs() == default.get_ca_certs()
    # VERIFY_X509_STRICT 之类的标志位不应被顺手清掉
    assert ctx.verify_flags == default.verify_flags


def test_fetcher_session_verifies_certificates():
    """真实会话（不是注入的假 client）确实在验证证书。

    ⚠️ 这里读的是 httpx 的私有属性，升级 httpx 可能读不到 —— 读不到就跳过，
    不要因此判失败。这条测试防的是「有人为了跑通把 verify 关了」，
    不是给 httpx 的内部结构上锁。
    """
    f = Fetcher(gate=_open_gate())
    try:
        ctx = getattr(getattr(getattr(f._session(), "_transport", None),
                              "_pool", None), "_ssl_context", None)
        if ctx is None:
            pytest.skip("httpx 内部结构已变，取不到 SSLContext")
        assert ctx.verify_mode is ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
    finally:
        f.close()


# ══════════════════════════════════════════════════════════════
#  重试
# ══════════════════════════════════════════════════════════════

class _FlakyClient:
    """前 n 次抛指定异常，之后正常返回。"""

    def __init__(self, exc, fail_times: int):
        self.exc = exc
        self.fail_times = fail_times
        self.calls = 0

    def __call__(self, url):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return 200, "<html>ok</html>"


def _transient_exc():
    import httpx

    return httpx.ConnectError("[SSL] EE certificate key too weak")


def test_transient_failure_is_retried():
    client = _FlakyClient(_transient_exc(), fail_times=2)
    rl, _ = _limiter(interval=0.0)
    f = Fetcher(gate=_open_gate(), limiter=rl, client=client, retries=2)
    assert f.fetch("https://x.gov.cn/a").ok
    assert client.calls == 3


def test_retries_are_bounded():
    client = _FlakyClient(_transient_exc(), fail_times=99)
    rl, _ = _limiter(interval=0.0)
    f = Fetcher(gate=_open_gate(), limiter=rl, client=client, retries=2)
    with pytest.raises(Exception):
        f.fetch("https://x.gov.cn/a")
    assert client.calls == 3, "重试次数必须有上限，否则一个坏页面能耗死整轮抓取"


def test_non_transient_failure_is_not_retried():
    """解析错误、编码错误这类问题重试多少次都一样，只是白白打扰对方。"""
    client = _FlakyClient(ValueError("解析失败"), fail_times=99)
    rl, _ = _limiter(interval=0.0)
    f = Fetcher(gate=_open_gate(), limiter=rl, client=client, retries=3)
    with pytest.raises(ValueError):
        f.fetch("https://x.gov.cn/a")
    assert client.calls == 1


def test_every_retry_waits_the_request_interval():
    """重试也要过限速。

    站点正在抖动的时候连发三次请求，是把「它扛不住」当成了「再试一次就好」。
    """
    client = _FlakyClient(_transient_exc(), fail_times=2)
    rl, clk = _limiter(interval=3.0)
    f = Fetcher(gate=_open_gate(), limiter=rl, client=client, retries=2)
    f.fetch("https://x.gov.cn/a")
    assert clk.t == pytest.approx(6.0), "三次请求之间应各等 3 秒"


def test_robots_denial_is_not_retried():
    """robots 说不行就是不行，重试是明知故犯。"""
    from app.crawler.policy import RobotsDenied

    gate = RobotsGate(fetcher=lambda url: "User-agent: *\nDisallow: /\n")
    client = _FlakyClient(_transient_exc(), fail_times=0)
    f = Fetcher(gate=gate, limiter=_limiter(0.0)[0], client=client, retries=3)
    with pytest.raises(RobotsDenied):
        f.fetch("https://x.gov.cn/a")
    assert client.calls == 0, "被 robots 拒绝时不应发出任何请求"


def test_non_https_is_rejected_before_robots_or_network():
    calls = []
    gate = RobotsGate(fetcher=lambda url: calls.append(("robots", url)) or "")
    fetcher = Fetcher(gate=gate, client=lambda url: calls.append(("page", url)) or (200, "ok"))
    with pytest.raises(ValueError, match="必须使用 HTTPS"):
        fetcher.fetch("http://www.samr.gov.cn/example")
    assert calls == []


def test_host_outside_allowlist_is_rejected_before_robots_or_network():
    calls = []
    gate = RobotsGate(fetcher=lambda url: calls.append(("robots", url)) or "")
    fetcher = Fetcher(
        gate=gate,
        client=lambda url: calls.append(("page", url)) or (200, "ok"),
        allowed_hosts={"www.samr.gov.cn"},
    )
    with pytest.raises(ValueError, match="不在允许的官方域名"):
        fetcher.fetch("https://example.com/redirect")
    assert calls == []


def test_is_transient_classifies_httpx_transport_errors():
    import httpx

    assert _is_transient(httpx.ConnectError("x")) is True
    assert _is_transient(httpx.ReadTimeout("x")) is True
    assert _is_transient(ValueError("x")) is False
    # HTTP 状态码不是传输错误 —— 404 重试一百次还是 404
    assert _is_transient(httpx.HTTPStatusError(
        "404", request=httpx.Request("GET", "https://x/"),
        response=httpx.Response(404))) is False
