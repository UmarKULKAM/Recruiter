"""HTTP fetch for public career pages.

Uses a browser TLS fingerprint so the request is the same kind of GET a
browser sends. A Cloudflare challenge page is not treated as a listing page.
"""

import gzip
import json
from dataclasses import dataclass

from curl_cffi import requests as curl_requests


@dataclass
class Page:
    url: str
    status: int
    text: str
    ok: bool

    @property
    def challenge(self) -> bool:
        sample = self.text[:5000].lower()
        return (
            "just a moment" in sample
            or "performing security verification" in sample
            or "cf-mitigated" in sample
        )

    def json(self):
        return json.loads(self.text)


def live_fetch(url: str, *, method: str = "GET", json_body=None, timeout: int = 25) -> Page:
    try:
        if method.upper() == "POST":
            response = curl_requests.post(
                url,
                json=json_body,
                impersonate="chrome",
                timeout=timeout,
                allow_redirects=True,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        else:
            response = curl_requests.get(
                url,
                impersonate="chrome",
                timeout=timeout,
                allow_redirects=True,
            )
    except Exception:
        return Page(url=url, status=0, text="", ok=False)
    text = _decode(response.content)
    page = Page(url=str(response.url), status=response.status_code, text=text, ok=False)
    page.ok = 200 <= response.status_code < 300 and not page.challenge
    return page


def _decode(raw: bytes) -> str:
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    return raw.decode("utf-8", "replace")
