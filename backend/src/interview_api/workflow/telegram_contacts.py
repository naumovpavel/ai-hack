"""Conservative, deterministic Telegram contact extraction from resume text."""

from __future__ import annotations

import re

_USERNAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{4,31}\Z")
_LINK = re.compile(
    r"(?<![\w./@-])(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/"
    r"([a-zA-Z][a-zA-Z0-9_]{4,31})(?![\w/+-])",
    re.IGNORECASE,
)
_LABEL = re.compile(
    r"(?<!\w)(?:telegram|телеграм(?:м)?|тг|tg)\b"
    r"(?:[ \t]+(?:username|ник|аккаунт))?"
    r"(?:[ \t]*[:=—–-][ \t]*@?|[ \t]+@)"
    r"([a-zA-Z][a-zA-Z0-9_]{4,31})(?![\w@/+:—-])",
    re.IGNORECASE,
)
_HANDLE = re.compile(r"(?<![\w.+/@-])@([a-zA-Z][a-zA-Z0-9_]{4,31})(?![\w@/+-])")
_OTHER_SERVICE = re.compile(
    r"(?:github|gitlab|instagram|twitter|linkedin|discord|skype|почта|email|e-mail|"
    r"mastodon|facebook|вконтакте|\bvk\b|\bx\b)\s*[:=—–-]?\s*[\[(]?\s*$",
    re.IGNORECASE,
)
_RESERVED_PATHS = {"joinchat", "addstickers", "addemoji", "share", "proxy", "socks"}


def normalize_telegram_username(value: str | None) -> str | None:
    if not value:
        return None
    username = value.strip().removeprefix("@")
    return username.lower() if _USERNAME.fullmatch(username) else None


def extract_telegram_username(text: str) -> str | None:
    """Prefer explicit Telegram links/labels; avoid emails and other named services.

    A bare @handle cannot prove which platform it belongs to. It is accepted only
    when its surrounding text does not identify a different platform. This is a
    contact hint, never proof of ownership or a basis for authentication.
    """
    for pattern in (_LINK, _LABEL):
        for match in pattern.finditer(text):
            username = normalize_telegram_username(match.group(1))
            if re.match(r"\.[a-zA-Z]", text[match.end() : match.end() + 20]):
                continue
            if username and username not in _RESERVED_PATHS:
                return username
    for match in _HANDLE.finditer(text):
        prefix = text[max(0, match.start() - 100) : match.start()].split("\n")[-1]
        # A dot followed by letters after @name is usually a domain/email, even
        # when malformed extraction introduced whitespace before the @ sign.
        suffix = text[match.end() : match.end() + 20]
        if _OTHER_SERVICE.search(prefix) or re.match(r"\.[a-zA-Z]", suffix):
            continue
        return normalize_telegram_username(match.group(1))
    return None
