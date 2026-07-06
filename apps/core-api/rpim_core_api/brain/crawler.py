import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

MAX_BYTES = 1_000_000
TIMEOUT = 10.0


def validate_public_http_url(url: str) -> None:
    """SSRF guard: http(s) schemes only; hosts that resolve to private,
    loopback, link-local, reserved, multicast or unspecified addresses are
    rejected. Unresolvable hostnames pass — the fetch itself will fail, and
    blocking them would break nothing but offline tests. (DNS-rebinding
    TOCTOU is accepted for the MVP crawl of the brand's OWN site; the M3
    trend crawlers get the hardened fetcher.)"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("only public http(s) URLs are allowed")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        return
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("host resolves to a non-public address")


def fetch_page(url: str) -> tuple[str, list[str]]:
    """Fetch one HTML page → (extracted text, same-domain links).
    Tests monkeypatch this function."""
    response = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
    response.raise_for_status()
    if "text/html" not in response.headers.get("content-type", ""):
        return "", []

    soup = BeautifulSoup(response.text[:MAX_BYTES], "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = "\n\n".join(t.strip() for t in soup.stripped_strings if len(t.strip()) > 1)

    base_host = urlparse(url).netloc
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, anchor["href"]).split("#")[0]
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https") and parsed.netloc == base_host:
            links.append(href)
    return text, links


def crawl_site(start_url: str, max_pages: int = 5) -> tuple[str, int]:
    """Same-domain breadth-first crawl. Returns (joined text, pages fetched)."""
    seen: set[str] = set()
    queue = [start_url]
    texts: list[str] = []
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        text, links = fetch_page(url)
        if text.strip():
            texts.append(text.strip())
        for link in links:
            if link not in seen and link not in queue:
                queue.append(link)
    return "\n\n".join(texts), len(seen)
