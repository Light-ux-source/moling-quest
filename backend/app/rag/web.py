"""网页抓取：SSRF 防护、重定向复检、内容类型与大小限制、正文提取。"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from .parsers import ParseError, parse_document
from .types import ParsedDocument

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 20.0
MAX_REDIRECTS = 3
_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {None, 80, 443}
_EXTRA_BLOCKED = [
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("240.0.0.0/4"),
]
_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")


class WebFetchError(Exception):
    """网页抓取失败；消息可直接展示给用户。"""


def is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(str(value).strip("[]"))
    except ValueError:
        return False
    if any(address in network for network in _EXTRA_BLOCKED):
        return False
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _resolve_host(host: str) -> list:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise WebFetchError(f"无法解析域名 {host}，请检查链接是否正确") from exc
    addresses = []
    for info in infos:
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    return addresses


def _check_host_sync(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise WebFetchError("只支持 http / https 链接")
    if parsed.username or parsed.password:
        raise WebFetchError("链接不能包含用户名或密码")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise WebFetchError("链接缺少域名")
    if parsed.port not in _ALLOWED_PORTS:
        raise WebFetchError("只支持 80 / 443 端口")
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise WebFetchError("不允许访问内网或本机地址")
    if host.replace(".", "").isdigit() or ":" in host:
        if not is_public_ip(host):
            raise WebFetchError("不允许访问内网或本机地址")
        return url
    for address in _resolve_host(host):
        if not is_public_ip(address):
            raise WebFetchError("该链接解析到内网地址，已拒绝访问")
    return url


async def assert_safe_url(url: str) -> str:
    """校验协议/端口/主机解析结果；DNS 解析放到线程池，避免阻塞事件循环。"""
    return await asyncio.to_thread(_check_host_sync, url)


def _content_type(headers: httpx.Headers) -> str:
    return (headers.get("content-type") or "").split(";")[0].strip().lower()


async def fetch_document(
    url: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    max_pages: int = 300,
) -> ParsedDocument:
    """抓取网页/PDF 并解析成 ParsedDocument；任何失败都抛 WebFetchError。"""
    current = await assert_safe_url(url)
    owns_client = client is None
    active = client or httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=8.0),
        headers={
            "User-Agent": "MoLingKB/1.0 (+https://example.com; learning assistant)",
            "Accept": "text/html,application/xhtml+xml,text/plain,application/pdf;q=0.9,*/*;q=0.5",
        },
        follow_redirects=False,
    )
    try:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                response = await active.get(current)
            except httpx.HTTPError as exc:
                raise WebFetchError(f"网页访问失败：{str(exc)[:120]}") from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise WebFetchError("网页重定向缺少目标地址")
                current = await assert_safe_url(urljoin(current, location))
                continue
            if response.status_code >= 400:
                raise WebFetchError(f"网页返回 {response.status_code}，可能被反爬或需要登录")
            body = response.content or b""
            if len(body) > max_bytes:
                raise WebFetchError(f"网页内容过大（超过 {max_bytes // 1024 // 1024 or 1}MB）")
            if not body:
                raise WebFetchError("网页内容为空")
            content_type = _content_type(response.headers)
            try:
                if content_type == "application/pdf" or body.lstrip().startswith(b"%PDF"):
                    return parse_document(
                        "pdf", body, filename=current.rsplit("/", 1)[-1], url=current, max_pages=max_pages
                    )
                if content_type in {"text/html", "application/xhtml+xml", ""}:
                    return parse_document("html", body, filename=current, url=current)
                if content_type.startswith("text/"):
                    return parse_document("text", body, filename=current, url=current)
            except ParseError as exc:
                raise WebFetchError(str(exc)) from exc
            raise WebFetchError(f"暂不支持抓取 {content_type or '未知类型'} 的内容")
        raise WebFetchError("网页重定向次数过多")
    finally:
        if owns_client:
            await active.aclose()


def format_web_error(exc: Exception) -> str:
    if isinstance(exc, WebFetchError):
        return str(exc)
    return "网页抓取失败，请稍后重试或改用粘贴文本"