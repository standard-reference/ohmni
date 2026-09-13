"""The network boundary, and the only one.

`fetch` is the sole place bytes enter the system; everything downstream is a pure
function of what it cached. That split is not tidiness — it is what makes
`normalize` re-runnable after a bugfix with no refetch, testable without a
network, and provably deterministic. The conformance suite's no-network check
enforces it from the other side.

Raw responses are cached verbatim and gzipped. A raw cache is also what lets a
normalization bug be fixed without re-pulling, and what lets the same historical
pull be replayed identically months later.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "raw"

#: SEC requires a descriptive User-Agent with contact details and caps at 10/s.
#: GDELT asks for one request every five seconds. Both are honoured here rather
#: than discovered through a ban.
USER_AGENT = "ohmni-research/0.1 (contact: bato2912@gmail.com)"

MIN_INTERVAL = {
    "data.sec.gov": 0.15,
    "api.gdeltproject.org": 9.0,
    "wikimedia.org": 0.2,
    "cdn.finra.org": 0.1,
    "query1.finance.yahoo.com": 0.3,
}

_last_call: dict[str, float] = {}


@dataclass
class FetchResult:
    url: str
    body: bytes
    from_cache: bool
    status: int = 200

    def json(self):
        return json.loads(self.body)

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class FetchFailed(Exception):
    pass


def _key(url: str) -> Path:
    return CACHE_DIR / f"{hashlib.sha256(url.encode()).hexdigest()}.gz"


def _throttle(host: str) -> None:
    interval = MIN_INTERVAL.get(host, 0.3)
    last = _last_call.get(host)
    if last is not None:
        wait = interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_call[host] = time.monotonic()


def fetch(url: str, *, absent: tuple[int, ...] = (), attempts: int = 7) -> FetchResult | None:
    path = _key(url)
    if path.exists():
        return FetchResult(url, gzip.decompress(path.read_bytes()), from_cache=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    host = urllib.parse.urlsplit(url).netloc
    delay = 5.0
    for attempt in range(attempts):
        _throttle(host)
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                path.write_bytes(gzip.compress(body))
                return FetchResult(url, body, from_cache=False, status=resp.status)
        except urllib.error.HTTPError as e:
            if e.code in absent:
                # An absent file is a real answer — a market that was closed, or a
                # concept the filer never tagged. It is None, never an empty
                # series, and never a zero.
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise FetchFailed(f"{e.code} {url}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < attempts - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise FetchFailed(f"{e} {url}") from e
    raise FetchFailed(f"exhausted attempts: {url}")


import urllib.parse  # noqa: E402  (used by fetch, imported late to keep the top tidy)
