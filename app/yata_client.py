from __future__ import annotations

import logging
import time
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class YataClientError(RuntimeError):
    pass


class YataClient:
    def __init__(self, url: str, timeout_seconds: int = 15, max_attempts: int = 3) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.session = requests.Session()

    def fetch_json(self) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.get(self.url, timeout=self.timeout_seconds)
                if response.status_code == 429:
                    retry_after = _retry_after_seconds(response)
                    LOGGER.warning("YATA rate limited request; retry_after=%s", retry_after)
                    time.sleep(retry_after)
                    continue
                if response.status_code >= 500:
                    LOGGER.warning("YATA transient HTTP error status=%s body=%s", response.status_code, response.text[:500])
                    time.sleep(_backoff(attempt))
                    continue
                if response.status_code >= 400:
                    raise YataClientError(f"YATA HTTP {response.status_code}: {response.text[:500]}")

                payload = response.json()
                if not isinstance(payload, dict):
                    raise YataClientError(f"Expected YATA JSON object, got {type(payload).__name__}")
                LOGGER.info("Fetched YATA travel export successfully status=%s", response.status_code)
                return payload
            except (requests.RequestException, ValueError, YataClientError) as exc:
                last_error = exc
                LOGGER.warning("YATA fetch attempt failed attempt=%s/%s error=%s", attempt, self.max_attempts, exc)
                if attempt < self.max_attempts:
                    time.sleep(_backoff(attempt))

        raise YataClientError(f"YATA fetch failed after {self.max_attempts} attempts: {last_error}")


def _backoff(attempt: int) -> float:
    return min(30.0, 2.0 ** (attempt - 1))


def _retry_after_seconds(response: requests.Response) -> float:
    header = response.headers.get("Retry-After") or response.headers.get("X-RateLimit-Reset-After")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    try:
        data = response.json()
    except ValueError:
        return 5.0
    try:
        return max(0.0, float(data.get("retry_after", 5.0)))
    except (TypeError, ValueError, AttributeError):
        return 5.0

