"""Turn PDFs, web pages and pasted text into page-addressable Source records."""
from __future__ import annotations

import io
import ipaddress
import socket
import uuid
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from .schema import Source, SourceKind

MAX_BYTES = 15 * 1024 * 1024
PAGE_BREAK = "\f"


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def from_text(name: str, text: str, kind: SourceKind = SourceKind.text, url: str | None = None) -> Source:
    pages = [p.strip() for p in text.split(PAGE_BREAK)] if PAGE_BREAK in text else [text.strip()]
    return Source(id=new_id(), kind=kind, name=name, url=url, pages=[p for p in pages if p] or [""])


def from_pdf(name: str, data: bytes, url: str | None = None) -> Source:
    reader = PdfReader(io.BytesIO(data))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    if not any(pages):
        raise ValueError("No extractable text found. Scanned PDFs need OCR, which Orbis does not run yet.")
    return Source(id=new_id(), kind=SourceKind.pdf, name=name, url=url, pages=pages)


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    lines: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr", "dt", "dd"]):
        t = " ".join(el.get_text(" ", strip=True).split())
        if not t:
            continue
        lines.append(f"- {t}" if el.name == "li" else t)
    return "\n".join(lines)


def _assert_public_http_url(url: str) -> None:
    """Block non-http(s) schemes and private/loopback targets (SSRF guard for a deployed app)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only http(s) URLs are supported.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host: {parsed.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("That address is not allowed.")


def from_url(url: str, name: str | None = None) -> Source:
    _assert_public_http_url(url)
    with httpx.Client(follow_redirects=True, timeout=20.0, headers={"User-Agent": "OrbisBot/0.1 (student project)"}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        if len(resp.content) > MAX_BYTES:
            raise ValueError("Document is too large.")
        ctype = resp.headers.get("content-type", "").lower()
        label = name or urlparse(url).netloc
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            return from_pdf(label, resp.content, url=url)
        text = _html_to_text(resp.text)
        if not text:
            raise ValueError("The page had no readable text.")
        return from_text(label, text, kind=SourceKind.webpage, url=url)
