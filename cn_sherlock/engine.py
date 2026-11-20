# -*- coding: utf-8 -*-
"""探测引擎：HTTP 请求、判定策略、结果模型。

设计目标
--------
1. 与 Sherlock 一样由配置驱动，新增站点只改 JSON；
2. 国内平台大量存在 WAF、登录墙、纯前端渲染，因此把「请求失败/被风控」与
   「账号不存在」严格区分，绝不把 403/412/521 当成未注册；
3. 零第三方依赖，仅用标准库，方便在内网、离线环境与 Windows 上直接运行。
"""
from __future__ import annotations

import html
import json
import os
import re
import socket
import ssl
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

VERSION = "1.0.0"

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)

STATUS_FOUND = "found"
STATUS_NOT_FOUND = "not_found"
STATUS_BLOCKED = "blocked"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"
STATUS_MANUAL = "manual"

STATUS_CN = {
    STATUS_FOUND: "已发现",
    STATUS_NOT_FOUND: "未发现",
    STATUS_BLOCKED: "受限",
    STATUS_ERROR: "错误",
    STATUS_SKIPPED: "跳过",
    STATUS_MANUAL: "待核验",
}

BLOCKED_HINT = "平台风控或要求登录，结果未知"


@dataclass
class Response:
    status: int
    final_url: str
    text: str
    elapsed_ms: int
    error: str = ""
    headers: Dict[str, str] = None


class HttpClient:
    """极简 HTTP 客户端：超时重试、代理、编码探测。"""

    def __init__(self, timeout: int = 12, retries: int = 2,
                 proxy: Optional[str] = None, insecure: bool = False):
        self.timeout = timeout
        self.retries = retries
        handlers: List[Any] = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        ctx = ssl.create_default_context()
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
        self._opener = urllib.request.build_opener(*handlers)

    def fetch(self, url: str, headers: Dict[str, str],
              method: str = "GET", body: Optional[bytes] = None,
              timeout: Optional[int] = None) -> Response:
        last_error = ""
        for attempt in range(self.retries + 1):
            start = time.monotonic()
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method=method)
                with self._opener.open(req, timeout=timeout or self.timeout) as resp:
                    raw = resp.read(2_000_000)
                    text = decode_body(raw, resp.headers)
                    elapsed = int((time.monotonic() - start) * 1000)
                    return Response(resp.status, resp.geturl(), text, elapsed,
                                    headers=dict(resp.headers))
            except urllib.error.HTTPError as exc:
                raw = b""
                try:
                    raw = exc.read(2_000_000)
                except Exception:
                    pass
                text = decode_body(raw, exc.headers)
                elapsed = int((time.monotonic() - start) * 1000)
                return Response(exc.code, url, text, elapsed,
                                headers=dict(exc.headers or {}))
            except (urllib.error.URLError, socket.timeout, TimeoutError,
                    ConnectionError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.retries:
                    time.sleep(0.6 * (2 ** attempt))
                    continue
            except Exception as exc:  # noqa: BLE001 兜底，避免单站点拖垮整体
                last_error = f"{type(exc).__name__}: {exc}"
                break
        return Response(0, url, "", int((time.monotonic() - start) * 1000),
                        error=last_error)


def decode_body(raw: bytes, headers: Any) -> str:
    charset = ""
    try:
        charset = (headers.get_content_charset() or "") if headers else ""
    except Exception:
        charset = ""
    if not charset:
        match = re.search(br"charset=[\"']?([a-zA-Z0-9_\-]+)", raw[:4096], re.I)
        if match:
            charset = match.group(1).decode("ascii", "ignore")
    for candidate in (charset, "utf-8", "gb18030"):
        if not candidate:
            continue
        try:
            return raw.decode(candidate, "replace")
        except LookupError:
            continue
    return raw.decode("utf-8", "replace")


class DomainLimiter:
    """同一域名串行排队，避免对国内平台造成突发压力、触发风控。"""

    def __init__(self) -> None:
        self._next: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str, delay: float) -> None:
        host = urllib.parse.urlparse(url).netloc
        with self._lock:
            now = time.monotonic()
            start_at = max(now, self._next.get(host, 0.0))
            self._next[host] = start_at + delay
        pause = start_at - now
        if pause > 0:
            time.sleep(pause)


def normalize(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", "", text)
    text = unicodedata.normalize("NFKC", text)
    return text.strip().casefold()


def dig(data: Any, path: str) -> Any:
    """按 a.b.c 取值，支持 None 安全。"""
    cur = data
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else None
        else:
            return None
    return cur


class Engine:
    def __init__(self, sites: List[Dict[str, Any]], defaults: Dict[str, Any],
                 timeout: Optional[int] = None, retries: Optional[int] = None,
                 proxy: Optional[str] = None, insecure: bool = False):
        self.sites = sites
        self.defaults = defaults
        self.timeout = timeout if timeout is not None else defaults.get("timeout", 12)
        self.retries = retries if retries is not None else defaults.get("retries", 2)
        self.client = HttpClient(self.timeout, self.retries, proxy, insecure)
        self.limiter = DomainLimiter()
        self._bili_lock = threading.Lock()
        self._bili_cookie = ""
        self._bili_cookie_at = 0.0

    # ---------- 对外入口 ----------
    def check(self, site: Dict[str, Any], username: str) -> Dict[str, Any]:
        if site.get("status") == STATUS_MANUAL:
            return self._manual_result(site, username)

        probe = site.get("probe") or {}
        if probe.get("username_charset") == "ascii" and not str(username).isascii():
            return self._result(site, username, STATUS_SKIPPED, 0, 0,
                                "该站用户名仅支持 ASCII，中文昵称无法用于子域名/工号路径")
        headers = {
            "User-Agent": MOBILE_UA if probe.get("ua") == "mobile" else DESKTOP_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        headers.update(probe.get("headers") or {})

        cookie_env = probe.get("cookie_env")
        if cookie_env:
            cookie_value = os.environ.get(cookie_env, "").strip()
            if not cookie_value:
                return self._result(site, username, STATUS_SKIPPED, 0, 0,
                                    f"未配置 Cookie：请设置环境变量 {cookie_env}")
            headers["Cookie"] = cookie_value
        elif probe.get("optional_cookie_env"):
            optional_cookie = os.environ.get(probe["optional_cookie_env"], "").strip()
            if optional_cookie:
                headers["Cookie"] = optional_cookie

        if probe.get("bilibili_buvid"):
            headers["Cookie"] = self._get_buvid_cookie()

        url = render_url(probe.get("url", ""), username)
        self.limiter.wait(url, float(probe.get("delay", self.defaults.get("delay", 0.6))))
        resp = self.client.fetch(url, headers, method=probe.get("method", "GET"))

        # 部分站点首次请求触发风控，稍后重试一次往往可恢复
        retry_on = probe.get("retry_on") or []
        if resp.status in retry_on:
            self.limiter.wait(url, float(probe.get("retry_delay", 1.5)))
            resp = self.client.fetch(url, headers, method=probe.get("method", "GET"))

        # B 站 412 常见于 buvid 失效，刷新指纹后重试一次
        if resp.status == 412 and probe.get("bilibili_buvid"):
            self._refresh_buvid()
            headers["Cookie"] = self._bili_cookie
            self.limiter.wait(url, 1.0)
            resp = self.client.fetch(url, headers, method=probe.get("method", "GET"))

        return self._evaluate(site, username, resp)

    # ---------- 判定 ----------
    def _evaluate(self, site, username, resp) -> Dict[str, Any]:
        if resp.error:
            return self._result(site, username, STATUS_ERROR, resp.status,
                                resp.elapsed_ms, f"请求失败：{resp.error}")

        detect = site.get("detect") or {}
        blocked_codes = detect.get("blocked") or []
        blocked_markers = detect.get("blocked_markers") or []
        text = resp.text or ""

        if resp.status in blocked_codes:
            return self._result(site, username, STATUS_BLOCKED, resp.status,
                                resp.elapsed_ms, f"HTTP {resp.status}，{BLOCKED_HINT}")
        if any(marker in text for marker in blocked_markers):
            return self._result(site, username, STATUS_BLOCKED, resp.status,
                                resp.elapsed_ms, "命中安全验证页，结果未知")

        dtype = detect.get("type", "status")
        if dtype == "status":
            return self._detect_status(site, username, resp, detect)
        if dtype == "message":
            return self._detect_message(site, username, resp, detect)
        if dtype == "search":
            return self._detect_search(site, username, resp, detect)
        return self._result(site, username, STATUS_ERROR, resp.status,
                            resp.elapsed_ms, f"未知判定类型：{dtype}")

    def _detect_status(self, site, username, resp, detect):
        for marker in detect.get("not_found_markers") or []:
            if marker in resp.text:
                return self._not_found(site, username, resp, f"命中未注册标识：{marker}")
        if resp.status in (detect.get("not_found") or []):
            return self._not_found(site, username, resp, f"HTTP {resp.status}")
        if resp.status in (detect.get("found") or []):
            profile = self._resolve_status_url(site, username, resp)
            return self._result(site, username, STATUS_FOUND, resp.status,
                                resp.elapsed_ms, f"HTTP {resp.status}，页面正常",
                                url=profile)
        return self._result(site, username, STATUS_ERROR, resp.status,
                            resp.elapsed_ms, f"未预期的状态码 HTTP {resp.status}")

    def _detect_message(self, site, username, resp, detect):
        for marker in detect.get("not_found_markers") or []:
            if marker in resp.text:
                return self._not_found(site, username, resp, f"命中未注册文案：{marker}")
        if resp.status in (detect.get("found") or [200]):
            found_markers = detect.get("found_markers") or []
            if not found_markers or all(m in resp.text for m in found_markers):
                title = extract_title(resp.text)
                detail = f"页面正常，标题：{title}" if title else "页面正常"
                return self._result(site, username, STATUS_FOUND, resp.status,
                                    resp.elapsed_ms, detail)
        return self._result(site, username, STATUS_ERROR, resp.status,
                            resp.elapsed_ms, f"未预期响应 HTTP {resp.status}")

    def _detect_search(self, site, username, resp, detect):
        try:
            data = json.loads(resp.text)
        except (ValueError, TypeError):
            return self._result(site, username, STATUS_ERROR, resp.status,
                                resp.elapsed_ms, "搜索接口返回非 JSON")

        check = detect.get("json_check") or {}
        field = check.get("field")
        if field:
            value = dig(data, field)
            if "ok_min" in check and isinstance(value, (int, float)):
                if value < check["ok_min"]:
                    return self._not_found(site, username, resp, "搜索结果为空")
            elif "ok" in check and value not in check["ok"]:
                if value in (check.get("blocked_values") or []):
                    return self._result(site, username, STATUS_BLOCKED, resp.status,
                                        resp.elapsed_ms, f"接口返回风控码 {value}")
                return self._result(site, username, STATUS_ERROR, resp.status,
                                    resp.elapsed_ms, f"接口返回异常字段 {field}={value}")

        items = dig(data, detect.get("list_path", ""))
        if items is None:
            return self._not_found(site, username, resp, "搜索结果为 null")
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return self._result(site, username, STATUS_ERROR, resp.status,
                                resp.elapsed_ms, "搜索列表结构异常")

        target = normalize(username)
        for item in items:
            if not isinstance(item, dict):
                continue
            for name in detect.get("match_fields") or []:
                if normalize(item.get(name)) == target:
                    profile = self._resolve_item_url(site, username, item)
                    matched = html.unescape(str(item.get(name)))
                    return self._result(site, username, STATUS_FOUND, resp.status,
                                        resp.elapsed_ms,
                                        f"搜索精确匹配：{matched}", url=profile)

        return self._not_found(site, username, resp, f"搜索结果 {len(items)} 条，无同名")

    # ---------- 辅助 ----------
    def _resolve_status_url(self, site, username, resp):
        resolve = site.get("resolve") or {}
        if resolve.get("use_final_url") and resp.final_url:
            return resp.final_url
        field = resolve.get("json_field")
        if field:
            try:
                data = json.loads(resp.text)
                value = dig(data, field)
                if value:
                    return resolve["url"].replace("{value}", urllib.parse.quote(str(value)))
            except (ValueError, TypeError):
                pass
        return render_url(site.get("url", ""), username)

    def _resolve_item_url(self, site, username, item):
        resolve = site.get("resolve") or {}
        field = resolve.get("field")
        if field:
            value = item.get(field)
            if value:
                if str(value).startswith("http"):
                    return str(value)
                if resolve.get("url"):
                    return resolve["url"].replace("{value}", str(value))
        return render_url(site.get("url", ""), username)

    def _not_found(self, site, username, resp, detail):
        note = site.get("negative_note")
        if note:
            detail = f"{detail}；{note}"
        return self._result(site, username, STATUS_NOT_FOUND, resp.status,
                            resp.elapsed_ms, detail,
                            url=render_url(site.get("fallback_url") or site.get("url", ""), username))

    def _manual_result(self, site, username):
        return {
            "site": site.get("name"),
            "category": site.get("category"),
            "status": STATUS_MANUAL,
            "status_cn": STATUS_CN[STATUS_MANUAL],
            "confidence": site.get("confidence", "none"),
            "url": render_url(site.get("manual_url", ""), username),
            "profile_url": render_url(site.get("manual_url", ""), username),
            "http_status": None,
            "elapsed_ms": 0,
            "method": "manual",
            "detail": site.get("reason", "需要登录态或签名校验，请人工核验"),
            "reason": site.get("reason", ""),
        }

    def _result(self, site, username, status, http_status, elapsed_ms,
                detail, url=None):
        profile = url or render_url(site.get("fallback_url") or site.get("url", ""), username)
        return {
            "site": site.get("name"),
            "category": site.get("category"),
            "status": status,
            "status_cn": STATUS_CN[status],
            "confidence": site.get("confidence", "medium"),
            "url": profile,
            "profile_url": profile,
            "http_status": http_status,
            "elapsed_ms": elapsed_ms,
            "method": (site.get("detect") or {}).get("type", "status"),
            "detail": detail,
        }

    # ---------- B 站指纹 ----------
    def _get_buvid_cookie(self) -> str:
        with self._bili_lock:
            if self._bili_cookie and time.time() - self._bili_cookie_at < 1800:
                return self._bili_cookie
            self._fetch_buvid_locked()
            return self._bili_cookie

    def _refresh_buvid(self) -> None:
        with self._bili_lock:
            self._fetch_buvid_locked()

    def _fetch_buvid_locked(self) -> None:
        url = "https://api.bilibili.com/x/frontend/finger/spi"
        try:
            resp = self.client.fetch(url, {"User-Agent": DESKTOP_UA,
                                           "Referer": "https://www.bilibili.com/"})
            data = json.loads(resp.text).get("data") or {}
            b3, b4 = data.get("b_3", ""), data.get("b_4", "")
            if b3:
                self._bili_cookie = f"buvid3={b3}; buvid4={b4};"
                self._bili_cookie_at = time.time()
        except Exception:
            self._bili_cookie = ""


def render_url(template: str, username: str) -> str:
    if not template:
        return ""
    return template.replace("{username}", urllib.parse.quote(str(username), safe=""))


def extract_title(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text or "", re.S | re.I)
    if not match:
        return ""
    title = html.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
    return re.sub(r"\s+", " ", title).strip()[:80]
