import pytest

from interview_api.workflow.telegram_contacts import (
    extract_telegram_username,
    normalize_telegram_username,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Контакты https://t.me/John_Doe", "john_doe"),
        ("Контакты: t.me/John_Doe.", "john_doe"),
        ("https://telegram.me/SomeOne_99", "someone_99"),
        ("telegram: JohnDoe", "johndoe"),
        ("Telegram — @JohnDoe", "johndoe"),
        ("Telegram username: JohnDoe", "johndoe"),
        ("телеграмм: @SomeOne", "someone"),
        ("ТГ @SomeOne", "someone"),
        ("tg: SomeOne", "someone"),
        ("Контакты (@John_Doe)", "john_doe"),
        ("alice@example.com\nTelegram: @Real_Name", "real_name"),
        ("Twitter: @Other_name\nTelegram: @Real_Name", "real_name"),
        ("@Other_name\nhttps://t.me/Real_Name", "real_name"),
        ("https://t.me/Person_1?start=hello", "person_1"),
        ("alice@example.com", None),
        ("alice @example.com", None),
        ("https://github.com/@JohnDoe", None),
        ("Twitter: @JohnDoe", None),
        ("GitHub: @JohnDoe", None),
        ("GitHub (@JohnDoe)", None),
        ("X: @JohnDoe", None),
        ("Instagram — @JohnDoe", None),
        ("@name@mastodon.social", None),
        ("https://t.me/+secretInvite", None),
        ("https://t.me/joinchat/Secret", None),
        ("https://t.me/channel/123", None),
        ("https://evil.t.me/JohnDoe", None),
        ("Telegram: https://example.com/JohnDoe", None),
        ("Telegram integrations and APIs", None),
        ("Telegram: johndoe@gmail.com", None),
        ("Telegram: johndoe.name", None),
        ("t.me/short", "short"),
        ("t.me/tiny", None),
        ("@12345", None),
        ("@_abcde", None),
        ("@" + "x" * 33, None),
        ("", None),
    ],
)
def test_contact_extraction(source, expected):
    assert extract_telegram_username(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (" @John_Doe ", "john_doe"),
        ("abcde", "abcde"),
        ("t.me/abcde", None),
        ("abcde@mail.test", None),
        ("abcde-name", None),
        ("@@@@abcde", None),
        (None, None),
    ],
)
def test_normalization(source, expected):
    assert normalize_telegram_username(source) == expected
