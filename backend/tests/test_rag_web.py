"""网页抓取与 SSRF 防护测试。"""

from __future__ import annotations

import httpx
import pytest

from app.rag.web import (
    WebFetchError,
    assert_safe_url,
    fetch_document,
    is_public_ip,
)


@pytest.mark.parametrize(
    "ip",
    [
        "8.8.8.8",
        "1.1.1.1",
        "223.5.5.5",
        "2606:4700:4700::1111",
    ],
)
def test_public_ips_allowed(ip):
    assert is_public_ip(ip) is True


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "127.0.0.2",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "0.0.0.0",
        "100.64.0.1",
        "::1",
        "fe80::1",
    ],
)
def test_private_ips_rejected(ip):
    assert is_public_ip(ip) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost/admin",
        "http://10.0.0.8/",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        "ftp://example.com/a",
        "javascript:alert(1)",
        "http://user:pass@example.com/",
        "http://example.com:8080/",
    ],
)
async def test_unsafe_urls_rejected(url):
    with pytest.raises(WebFetchError):
        await assert_safe_url(url)


@pytest.mark.asyncio
async def test_fetch_html_document():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=(
                "<html><head><title>HTTP 缓存</title></head><body>"
                "<nav>导航</nav><article><h1>强缓存</h1>"
                "<p>强缓存直接读取本地副本。</p><p>协商缓存返回 304。</p></article>"
                "</body></html>"
            ).encode("utf-8"),
        )
    )
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        doc = await fetch_document("https://example.com/cache", client=client)
    assert doc.title == "HTTP 缓存"
    assert "强缓存" in doc.text
    assert "304" in doc.text
    assert "导航" not in doc.text


@pytest.mark.asyncio
async def test_fetch_revalidates_redirect_to_private_ip():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, content=b"secret")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        with pytest.raises(WebFetchError):
            await fetch_document("https://example.com/start", client=client)


@pytest.mark.asyncio
async def test_fetch_rejects_oversize_body():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"x" * 2048,
        )
    )
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        with pytest.raises(WebFetchError) as exc:
            await fetch_document("https://example.com/big", client=client, max_bytes=1024)
    assert "过大" in str(exc.value)


@pytest.mark.asyncio
async def test_fetch_rejects_unsupported_content_type():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "application/zip"}, content=b"PK\x03\x04"
        )
    )
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        with pytest.raises(WebFetchError):
            await fetch_document("https://example.com/a.zip", client=client)


@pytest.mark.asyncio
async def test_fetch_http_error_is_friendly():
    transport = httpx.MockTransport(lambda request: httpx.Response(403, content=b"forbidden"))
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        with pytest.raises(WebFetchError) as exc:
            await fetch_document("https://example.com/private", client=client)
    assert "403" in str(exc.value) or "访问" in str(exc.value)