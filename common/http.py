"""Cliente HTTP secuencial, pausado y con reintentos conservadores."""

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class PoliteHttpClient:
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        user_agent: str,
        delay_seconds: float = 1.5,
        timeout_seconds: float = 30,
        max_retries: int = 4,
        backoff_seconds: float = 2.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if delay_seconds < 1:
            raise ValueError("delay_seconds debe ser al menos 1 segundo")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds debe ser positivo")
        if max_retries < 0:
            raise ValueError("max_retries no puede ser negativo")
        if backoff_seconds <= 0:
            raise ValueError("backoff_seconds debe ser positivo")
        if not user_agent.strip():
            raise ValueError("user_agent no puede estar vacío")

        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_finished: float | None = None
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent.strip(),
                "Accept": "application/json",
            }
        )

    def _wait_between_requests(self) -> None:
        if self._last_request_finished is None:
            return
        elapsed = self._monotonic() - self._last_request_finished
        remaining = self.delay_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        delay = self.backoff_seconds * (2**attempt)
        retry_after = response.headers.get("Retry-After")
        if not retry_after:
            return delay

        try:
            return max(delay, float(retry_after.strip()))
        except ValueError:
            pass

        try:
            retry_at = parsedate_to_datetime(retry_after)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
            return max(delay, seconds, 0)
        except (TypeError, ValueError):
            return delay

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Realiza una petición con delay, backoff exponencial y Retry-After."""
        sender = getattr(self._session, method.casefold(), None)
        if sender is None:
            raise ValueError(f"Método HTTP no soportado: {method}")

        for attempt in range(self.max_retries + 1):
            self._wait_between_requests()
            response: requests.Response | None = None
            try:
                response = sender(
                    url,
                    timeout=self.timeout_seconds,
                    **kwargs,
                )
                if response.status_code not in self.RETRYABLE_STATUS_CODES:
                    response.raise_for_status()
                    return response

                if attempt >= self.max_retries:
                    response.raise_for_status()

                delay = self._retry_delay(response, attempt)
                LOGGER.warning(
                    "HTTP %s en %s; reintento %d/%d en %.1f s",
                    response.status_code,
                    url,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                self._sleep(delay)
            except requests.RequestException:
                if response is not None or attempt >= self.max_retries:
                    raise
                delay = self.backoff_seconds * (2**attempt)
                LOGGER.warning(
                    "Error de red en %s; reintento %d/%d en %.1f s",
                    url,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                self._sleep(delay)
            finally:
                self._last_request_finished = self._monotonic()

        raise RuntimeError("Se agotaron los reintentos HTTP")

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self._response_json(self.get(url, **kwargs), url)

    def post_json(self, url: str, **kwargs: Any) -> Any:
        return self._response_json(self.post(url, **kwargs), url)

    @staticmethod
    def _response_json(response: requests.Response, url: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"La respuesta de {url} no es JSON válido") from exc
