"""Optional offline browser smoke. Start UI on localhost:3017 with API port 8017.

Run with Python that has backend dev dependencies and Playwright installed:
    python tests/browser/practice_smoke.py
Uses installed Edge on Windows, Playwright Chromium elsewhere. No live LLM or bot calls.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from test_hiring import (  # noqa: E402
    assert_ok,
    candidate_draft,
    hiring_client,
    make_plan,
    sign_in_telegram,
)


def main():
    with contextmanager(hiring_client.__wrapped__)() as (client, service):
        _, plan = make_plan(client)
        approval = assert_ok(
            client.post(
                f"/api/v1/interview-plans/{plan['id']}/candidates",
                json=candidate_draft(client, plan),
            )
        )
        sign_in_telegram(client, service)
        assert_ok(client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]}))
        cookie = client.cookies.get(service.cookie_name, domain="testserver.local")
        # Explicitly permit only this isolated preview's origin.
        for middleware in client.app.user_middleware:
            if middleware.cls.__name__ == "CORSMiddleware":
                middleware.kwargs["allow_origins"].append("http://localhost:3017")
        server = uvicorn.Server(
            uvicorn.Config(client.app, host="127.0.0.1", port=8017, log_level="error")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            run_browser(cookie, service.cookie_name, approval)
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def run_browser(cookie, cookie_name, approval):
    api = "http://localhost:8017/api/v1"
    path = f"{api}/interviews/{approval['interviewId']}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="msedge" if sys.platform == "win32" else None,
            headless=True,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
        )
        context = browser.new_context(
            permissions=["camera", "microphone"], viewport={"width": 1440, "height": 1000}
        )
        context.add_cookies(
            [
                {
                    "name": cookie_name,
                    "value": cookie,
                    "domain": "localhost",
                    "path": "/",
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page = context.new_page()
        page.set_default_timeout(30000)
        errors, writes = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: writes.append(request.url) if request.method == "POST" else None,
        )
        page.add_init_script("""window.practiceTracks = [];
            const getMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = async (...args) => {
                const stream = await getMedia(...args);
                window.practiceTracks.push(...stream.getTracks());
                return stream;
            };""")
        page.goto("http://localhost:3017", wait_until="networkidle")
        page.get_by_role("button", name=re.compile("Пройти интервью")).click()
        expect(page.get_by_role("button", name="Проверить устройства", exact=True)).to_be_disabled()
        before = context.request.get(f"{path}/state").json()

        # Error/retry while loading examples.
        page.route(
            "**/practice",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": {"message": "Проверка ошибки генерации"}}),
            ),
            times=1,
        )
        page.get_by_role("button", name="Посмотреть примеры").click()
        expect(page.get_by_role("alert")).to_contain_text("Проверка ошибки генерации")
        page.get_by_role("button", name="Посмотреть примеры").click()
        expect(page.get_by_role("button", name="Примеры загружены")).to_be_visible()
        writes.clear()

        def enter_practice():
            page.get_by_role("button", name="Пройти тренировку", exact=True).click()
            page.get_by_role("button", name=re.compile("Разрешить")).click()
            page.get_by_role("button", name="Начать тренировку", exact=True).click()

        enter_practice()
        # A failed recorder remains retryable and visible.
        page.evaluate(
            "window.RealRecorder = window.MediaRecorder; window.MediaRecorder = class {"
            "static isTypeSupported() { return true; }"
            "constructor() { throw Error('Recorder test failure'); } };"
        )
        page.get_by_role("button", name="Начать ответ", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("Recorder test failure")
        page.evaluate("window.MediaRecorder = window.RealRecorder")
        page.get_by_role("button", name="Начать ответ", exact=True).click()
        page.get_by_role("button", name="Выйти из тренировки").click()
        expect(page.get_by_role("button", name="Пройти тренировку", exact=True)).to_be_visible()
        assert page.evaluate("window.practiceTracks.every(track => track.readyState === 'ended')")
        assert context.request.get(f"{path}/state").json() == before

        # Repeat after exit; complete the last answer using the countdown.
        enter_practice()
        for _ in range(2):
            page.get_by_role("button", name="Начать ответ", exact=True).click()
            page.get_by_role("button", name="Закончить тренировочный ответ").click()
        page.clock.install()
        page.get_by_role("button", name="Начать ответ", exact=True).click()
        page.clock.fast_forward(91000)
        expect(page.get_by_text("Тренировка завершена", exact=True)).to_be_visible()
        assert page.evaluate("window.practiceTracks.every(track => track.readyState === 'ended')")
        assert context.request.get(f"{path}/state").json() == before
        assert not [url for url in writes if re.search(r"/(start|answers|complete)$", url)], writes
        page.get_by_role("button", name="Перейти к согласию и старту").click()
        expect(page.get_by_role("button", name="Проверить устройства", exact=True)).to_be_disabled()
        page.get_by_role("checkbox").check()
        page.get_by_role("button", name="Проверить устройства", exact=True).click()
        page.get_by_role("button", name=re.compile("Разрешить")).click()
        page.get_by_role("button", name="Начать интервью", exact=True).click()
        expect(page.get_by_role("button", name="Завершить ответ", exact=True)).to_be_visible()
        assert context.request.get(f"{path}/state").json()["status"] == "in_progress"
        # A resumed real interview must not offer rehearsal.
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name=re.compile("Продолжить интервью")).click()
        expect(page.get_by_role("button", name="Пройти тренировку", exact=True)).to_have_count(0)
        assert not errors, errors
        print(
            "PASS: examples error/retry, recording error/retry, exit/repeat, countdown, "
            "media cleanup, no practice uploads, real consent/start/resume"
        )
        browser.close()


if __name__ == "__main__":
    main()
