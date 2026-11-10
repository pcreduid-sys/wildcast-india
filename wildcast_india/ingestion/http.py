"""Shared HTTP helper with retries and clear error messages."""
from __future__ import annotations

import time

import requests

from config import settings

HEADERS = {"User-Agent": "WILDCAST-INDIA/1.0 (research prototype)"}


class FetchError(RuntimeError):
    pass


def get(url: str, params: dict | None = None, retries: int = 2, accept: str | None = None,
        headers: dict | None = None) -> requests.Response:
    headers = {**HEADERS, **(headers or {})}
    if accept:
        headers["Accept"] = accept
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=settings.REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (401, 403):
                raise FetchError(f"Authentication failed (HTTP {r.status_code}) - check the API key/token.")
            if r.status_code < 500 and r.status_code != 429:
                break
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(1.5 * (attempt + 1))
    raise FetchError(last or "Unknown network error")
