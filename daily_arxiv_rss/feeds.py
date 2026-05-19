import time
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

BASE = "https://rss.arxiv.org/rss"
_RETRY_STATUS = {429, 503}


def feed_url(category: str) -> str:
    return f"{BASE}/{category}"


def sot_path(sot_dir: str, category: str, yyyymmdd: str) -> str:
    return f"{sot_dir}/{category}_{yyyymmdd}.xml"


def save_sot(xml_bytes: bytes, path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(xml_bytes)


def _default_opener(url: str, timeout: int = 30):
    return urllib.request.urlopen(url, timeout=timeout)


def fetch(url: str, *, sleep=time.sleep, retries: int = 5,
          base_delay: float = 3.0, _opener=_default_opener) -> bytes:
    attempt = 0
    while True:
        try:
            with _opener(url, timeout=30) as resp:
                return resp.read()
        except HTTPError as e:
            attempt += 1
            if e.code in _RETRY_STATUS and attempt < retries:
                sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise
