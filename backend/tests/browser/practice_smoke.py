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
from dataclasses import replace
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

from interview_api.workflow.ai import DeterministicWorkflowAI  # noqa: E402


class BrowserPracticeAI(DeterministicWorkflowAI):
    async def analyze(self, **kwargs):
        return replace(await super().analyze(**kwargs), recommendation="fit")


def main():
    with contextmanager(hiring_client.__wrapped__)() as (client, service):
        service.ai = BrowserPracticeAI()
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
        practice = context.request.post(f"{path}/practice").json()
        practice_path = f"{api}/practice/{practice['practiceId']}"
        assert practice["localOnly"] is False
        writes.clear()

        def enter_practice():
            page.get_by_role("button", name=re.compile("^(Пройти|Продолжить) тренировку$")).click()
            access = page.get_by_role("button", name="Продолжить к системному запросу")
            expect(access).to_be_disabled()
            page.get_by_role("checkbox").check()
            access.click()
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
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Выйти из тренировки").click()
        expect(page.get_by_role("button", name="Продолжить тренировку", exact=True)).to_be_visible()
        assert page.evaluate("window.practiceTracks.every(track => track.readyState === 'ended')")
        assert context.request.get(f"{path}/state").json() == before

        # Retrying an upload keeps the recording and does not create another real answer.
        enter_practice()
        page.route(
            "**/practice/*/answers",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": {"message": "Проверка ошибки загрузки ответа"}}),
            ),
            times=1,
        )
        page.get_by_role("button", name="Начать ответ", exact=True).click()
        page.wait_for_timeout(650)
        page.get_by_role("button", name="Закончить тренировочный ответ").click()
        expect(page.get_by_role("alert")).to_contain_text("Проверка ошибки загрузки ответа")
        page.get_by_role("button", name="Повторить загрузку ответа").click()
        expect(page.get_by_role("heading", name=practice["questions"][1]["text"])).to_be_visible()
        assert len(context.request.get(practice_path).json()["answeredQuestionIds"]) == 1

        # Resume the persisted session after a reload, then complete the last answer by timer.
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name=re.compile("Пройти интервью")).click()
        enter_practice()
        expect(page.get_by_role("heading", name=practice["questions"][1]["text"])).to_be_visible()
        for index in range(1, len(practice["questions"]) - 1):
            expect(
                page.get_by_role("heading", name=practice["questions"][index]["text"])
            ).to_be_visible()
            page.get_by_role("button", name="Начать ответ", exact=True).click()
            page.wait_for_timeout(650)
            page.get_by_role("button", name="Закончить тренировочный ответ").click()
        expect(page.get_by_role("heading", name=practice["questions"][-1]["text"])).to_be_visible()
        page.clock.install()
        page.get_by_role("button", name="Начать ответ", exact=True).click()
        page.wait_for_timeout(650)
        page.clock.fast_forward(practice["questions"][-1]["answerSeconds"] * 1000 + 1000)
        expect(page.get_by_role("heading", name="Разбор вашей тренировки")).to_be_visible()
        expect(page.get_by_role("heading", name="Оцените ответы")).to_be_visible()
        assert page.evaluate("window.practiceTracks.every(track => track.readyState === 'ended')")
        assert context.request.get(f"{path}/state").json() == before
        assert not [
            url
            for url in writes
            if url.startswith(path + "/") and re.search(r"/(start|answers|complete)$", url)
        ], writes

        # Human-first candidate flow: all ratings, independent reflection, AI, reason for change.
        locked = context.request.get(f"{practice_path}/analysis").json()
        assert locked["recommendationLocked"] is True and locked["summary"] is None
        for index in range(len(practice["questions"])):
            page.get_by_role("radio", name="Достаточный ответ", exact=True).check()
            next_label = (
                "Следующий вопрос" if index < len(practice["questions"]) - 1 else "К самооценке"
            )
            page.get_by_role("button", name=next_label, exact=True).click()
        page.get_by_role("radio", name="Нужно ещё подготовиться", exact=True).check()
        page.locator("#initial-feedback").fill("Хочу повторить основные темы перед интервью.")
        page.get_by_role("button", name="Сохранить и посмотреть рекомендацию ИИ").click()
        expect(page.get_by_role("heading", name="Сравните свою оценку с ИИ")).to_be_visible()
        page.locator('input[name="final-decision"]').nth(1).check()
        expect(page.get_by_role("button", name="Сохранить выводы")).to_be_disabled()
        page.locator("#change-reason").fill(
            "Сравнил аргументы ИИ со своими ответами и уточнил самооценку."
        )
        page.locator("#final-feedback").fill("Готов к интервью; перед ним повторю отмеченные темы.")
        page.get_by_role("button", name="Сохранить выводы").click()
        expect(page.get_by_role("heading", name="Разбор тренировки завершён")).to_be_visible()
        assert context.request.get(f"{api}/candidate/outcome").json()["status"] == "pending"
        assert context.request.get(f"{path}/state").json() == before
        saved = context.request.get(f"{practice_path}/analysis").json()
        assert saved["finalDecision"]["status"] == "next_stage" and saved["changeReason"]

        page.get_by_role("button", name="К подготовке", exact=True).click()
        page.get_by_role("button", name="Открыть разбор тренировки").click()
        expect(page.get_by_role("heading", name="Разбор тренировки завершён")).to_be_visible()
        page.get_by_role("button", name="К подготовке", exact=True).click()
        expect(page.get_by_role("button", name="Проверить устройства", exact=True)).to_be_disabled()
        page.get_by_role("checkbox").check()
        page.get_by_role("button", name="Проверить устройства", exact=True).click()
        page.get_by_role("button", name="Продолжить к системному запросу").click()
        page.get_by_role("button", name="Начать интервью", exact=True).click()
        expect(page.get_by_role("button", name="Завершить ответ", exact=True)).to_be_visible()
        assert context.request.get(f"{path}/state").json()["status"] == "in_progress"
        # A resumed real interview must not offer rehearsal.
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name=re.compile("Продолжить интервью")).click()
        expect(page.get_by_role("button", name="Пройти тренировку", exact=True)).to_have_count(0)
        assert not errors, errors
        print(
            "PASS: examples and media error/retry, persisted upload/resume, countdown, "
            "private human-first practice review, media cleanup, real consent/start/isolation"
        )
        browser.close()


if __name__ == "__main__":
    main()
