import io
import json
from urllib.error import HTTPError, URLError

import pytest

from interview_api.workflow.telegram_client import TelegramAPIError, TelegramBotClient


@pytest.mark.asyncio
async def test_api_failure_never_exposes_token_or_response_description(monkeypatch):
    token = "123456:very_secret_token"
    secret_url = f"https://api.telegram.org/bot{token}/sendMessage"

    def fail(*args, **kwargs):
        raise HTTPError(
            secret_url,
            429,
            secret_url,
            {},
            io.BytesIO(
                json.dumps(
                    {
                        "ok": False,
                        "error_code": 429,
                        "description": secret_url,
                        "parameters": {"retry_after": 7},
                    }
                ).encode()
            ),
        )

    monkeypatch.setattr("interview_api.workflow.telegram_client.urlopen", fail)
    with pytest.raises(TelegramAPIError) as caught:
        await TelegramBotClient(token).send_message(123, "hello")
    assert token not in str(caught.value)
    assert token not in repr(caught.value)
    assert caught.value.retry_after == 7
    assert caught.value.retryable


@pytest.mark.asyncio
async def test_network_failure_redacted(monkeypatch):
    def fail(*args, **kwargs):
        raise URLError("https://api.telegram.org/bot123:secret/getMe")

    monkeypatch.setattr("interview_api.workflow.telegram_client.urlopen", fail)
    with pytest.raises(TelegramAPIError, match=r"code 0"):
        await TelegramBotClient("123:secret").get_me()


@pytest.mark.asyncio
async def test_polling_request_timeout_exceeds_telegram_wait(monkeypatch):
    captured = []

    def success(request, *, timeout, **kwargs):
        captured.append((json.loads(request.data), timeout))
        return io.BytesIO(b'{"ok":true,"result":[]}')

    monkeypatch.setattr("interview_api.workflow.telegram_client.urlopen", success)
    assert await TelegramBotClient("123:secret").get_updates(offset=88, timeout=25) == []
    assert captured == [({"timeout": 25, "offset": 88, "allowed_updates": ["message"]}, 35)]


@pytest.mark.asyncio
async def test_send_uses_plain_text_and_private_numeric_chat_only(monkeypatch):
    captured = []

    def success(request, *, timeout, **kwargs):
        captured.append(json.loads(request.data))
        return io.BytesIO(b'{"ok":true,"result":{"message_id":1}}')

    monkeypatch.setattr("interview_api.workflow.telegram_client.urlopen", success)
    client = TelegramBotClient("123:secret")
    await client.send_message(42, "<script>plain text</script>")
    assert "parse_mode" not in captured[0]
    assert captured[0]["link_preview_options"] == {"is_disabled": True}
    for invalid in [-1, 0, "@username", True]:
        with pytest.raises(ValueError):
            await client.send_message(invalid, "hello")
