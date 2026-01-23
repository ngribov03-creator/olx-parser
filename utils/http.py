"""HTTP utilities with retry/backoff support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class HttpResponse:
    text: str
    status_code: int


class HttpClient:
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: int = 20) -> None:
        self._timeout = timeout
        self._session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._session.headers.update({"User-Agent": user_agent})

    def get(self, url: str, params: Optional[dict[str, Any]] = None) -> HttpResponse:
        response = self._session.get(url, params=params, timeout=self._timeout)
        response.raise_for_status()
        return HttpResponse(text=response.text, status_code=response.status_code)

    def post(
        self, url: str, json: Optional[dict[str, Any]] = None, data: Any = None
    ) -> requests.Response:
        response = self._session.post(url, json=json, data=data, timeout=self._timeout)
        response.raise_for_status()
        return response
