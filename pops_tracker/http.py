"""Small polite HTTP layer shared by every downloader."""
import hashlib
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers["User-Agent"] = config.USER_AGENT
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET", "HEAD"))
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.mount("http://", HTTPAdapter(max_retries=retry))
        _session = s
    return _session


class SourceBlocked(RuntimeError):
    """The source refused us (403/429). Carries enough detail to tell an IP-reputation block from a real removal."""


def get(url: str, **kw) -> requests.Response:
    time.sleep(config.REQUEST_DELAY_SECONDS)
    r = session().get(url, timeout=config.HTTP_TIMEOUT, **kw)
    if r.status_code in (403, 429):
        snippet = " ".join(r.text.split())[:160]
        raise SourceBlocked(f"HTTP {r.status_code} from {url} (server={r.headers.get('Server', '?')}, "
                            f"content-type={r.headers.get('Content-Type', '?')}): {snippet}")
    r.raise_for_status()
    return r


def head(url: str) -> requests.Response:
    time.sleep(config.REQUEST_DELAY_SECONDS)
    return session().head(url, timeout=config.HTTP_TIMEOUT, allow_redirects=True)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
