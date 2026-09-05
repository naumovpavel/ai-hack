"""Small async Telegram Bot API transport with redacted, bounded failures."""

from __future__ import annotations

import asyncio
import json
import re
import ssl
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi


class TelegramAPIError(Exception):
    """Never contains the request URL, bot token, or untrusted API descriptions."""

    def __init__(self, error_code: int = 0, *, retry_after: int | None = None) -> None:
        self.error_code = error_code
        self.retry_after = retry_after
        self.blocked = error_code == 403
        self.retryable = error_code in {0, 408, 409, 429} or error_code >= 500
        super().__init__(f"Telegram API request failed (code {error_code}).")


class TelegramBotClient:
    def __init__(self, token: str, *, timeout: float = 15.0) -> None:
        token = token.strip()
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
            raise ValueError("A valid Telegram bot token is required.")
        self._token = token
        self.timeout = max(1.0, min(timeout, 60.0))

    async def call(
        self, method: str, payload: Mapping[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*", method):
            raise ValueError("Invalid Telegram API method.")
        request_timeout = self.timeout if timeout is None else max(1.0, min(timeout, 60.0))
        return await asyncio.to_thread(self._call, method, dict(payload or {}), request_timeout)

    def _call(self, method: str, payload: dict[str, Any], timeout: float) -> Any:
        request = Request(
            f"https://api.telegram.org/bot{self._token}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(
                request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where())
            ) as response:
                raw = response.read(2_000_001)
        except HTTPError as error:
            try:
                response_data = json.loads(error.read(16_384))
            except (ValueError, OSError):
                response_data = {}
            raise self._api_error(response_data, fallback=error.code) from None
        except (URLError, TimeoutError, OSError):
            raise TelegramAPIError() from None
        if len(raw) > 2_000_000:
            raise TelegramAPIError()
        try:
            response_data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise TelegramAPIError() from None
        if not isinstance(response_data, dict) or response_data.get("ok") is not True:
            raise self._api_error(response_data)
        return response_data.get("result")

    @staticmethod
    def _api_error(value: Any, *, fallback: int = 0) -> TelegramAPIError:
        value = value if isinstance(value, dict) else {}
        code = value.get("error_code", fallback)
        code = code if isinstance(code, int) and not isinstance(code, bool) else fallback
        parameters = value.get("parameters")
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        if not isinstance(retry_after, int) or isinstance(retry_after, bool) or retry_after < 0:
            retry_after = None
        return TelegramAPIError(code, retry_after=retry_after)

    async def get_me(self) -> dict[str, Any]:
        result = await self.call("getMe")
        if not isinstance(result, dict):
            raise TelegramAPIError()
        return result

    async def get_updates(
        self, *, offset: int | None = None, timeout: int = 25
    ) -> list[dict[str, Any]]:
        timeout = max(0, min(timeout, 45))
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = await self.call("getUpdates", payload, timeout=max(self.timeout, timeout + 10))
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise TelegramAPIError()
        return result

    async def send_message(self, chat_id: int, text: str) -> dict[str, Any]:
        if isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id <= 0:
            raise ValueError("Telegram notifications require a known private chat ID.")
        result = await self.call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:4000],
                "link_preview_options": {"is_disabled": True},
            },
        )
        if not isinstance(result, dict):
            raise TelegramAPIError()
        return result
