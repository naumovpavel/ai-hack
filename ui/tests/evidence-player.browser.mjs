const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE || 'playwright'
);
import assert from 'node:assert/strict';
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || undefined,
});
try {
  const page = await browser.newPage({
    viewport: { width: 1400, height: 1100 },
  });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(process.env.EVIDENCE_TEST_URL || 'http://127.0.0.1:4319');
  await page.waitForFunction(() => window.fixtureReady);
  const manifest = await page.evaluate(async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 360;
    const context = canvas.getContext('2d');
    const stream = canvas.captureStream(20);
    const recorder = new MediaRecorder(stream, {
      mimeType: 'video/webm;codecs=vp8',
    });
    const chunks = [];
    recorder.ondataavailable = (event) => chunks.push(event.data);
    const stopped = new Promise((resolve) => {
      recorder.onstop = resolve;
    });
    let frame = 0;
    const timer = setInterval(() => {
      context.fillStyle = '#26343e';
      context.fillRect(0, 0, 640, 360);
      context.fillStyle = '#bbedcb';
      context.font = '32px sans-serif';
      context.fillText(`TEST VIDEO ${++frame}`, 80, 180);
    }, 50);
    recorder.start();
    await new Promise((resolve) => setTimeout(resolve, 6200));
    recorder.stop();
    await stopped;
    clearInterval(timer);
    stream.getTracks().forEach((track) => track.stop());
    const url = URL.createObjectURL(new Blob(chunks, { type: 'video/webm' }));
    const manifest = {
      findingId: 'synthetic',
      title: 'Возможное использование внешней подсказки',
      episode: { startMs: 12000, endMs: 13000 },
      context: { startMs: 10000, endMs: 26000 },
      answerRange: { startMs: 10000, endMs: 26000 },
      camera: [
        {
          mediaId: 'cam-1',
          streamId: 'one',
          url,
          startMs: 10000,
          endMs: 16000,
          mediaOffsetMs: 0,
        },
        {
          mediaId: 'cam-2',
          streamId: 'two',
          url,
          startMs: 20000,
          endMs: 26000,
          mediaOffsetMs: 0,
        },
      ],
      screen: [
        {
          mediaId: 'screen-1',
          streamId: 'three',
          url,
          startMs: 10500,
          endMs: 16000,
          mediaOffsetMs: 500,
        },
        {
          mediaId: 'screen-2',
          streamId: 'four',
          url,
          startMs: 21000,
          endMs: 26000,
          mediaOffsetMs: 1000,
        },
      ],
      transcript: [
        { text: 'слово без выравнивания', words: [] },
        {
          text: 'слово другое',
          startMs: 10000,
          endMs: 16000,
          words: [
            { text: 'слово', startMs: 10000, endMs: 12000 },
            { text: 'другое', startMs: 12000, endMs: 15000 },
          ],
        },
      ],
      observations: [
        { text: 'Экран открыт', source: 'vlm', startMs: 12000, endMs: 15000 },
      ],
      expiresAt: new Date(Date.now() + 300000).toISOString(),
    };
    window.mountPlayer(manifest, { refresh: true });
    return manifest;
  });
  const seek = async (value) => {
    await page
      .getByRole('slider', { name: 'Позиция в записи' })
      .fill(String(value));
  };
  const values = () =>
    page
      .locator('video')
      .evaluateAll((videos) =>
        videos.map((video) => ({
          time: video.currentTime,
          paused: video.paused,
          muted: video.muted,
          rate: video.playbackRate,
          ready: video.readyState,
        })),
      );
  await page.waitForTimeout(900);

  await page.getByRole('button', { name: 'Пауза', exact: true }).click();
  await seek(12500);
  await page.waitForTimeout(300);
  const both = await values();

  assert.equal(both.length, 2);
  assert(both.every((video) => video.paused));
  assert(Math.abs(both[0].time - 2.5) < 0.1);
  assert(Math.abs(both[1].time - 2.5) < 0.1);
  assert.equal(both[0].muted, false);
  assert.equal(both[1].muted, true);
  await page.getByLabel('Скорость воспроизведения').selectOption('2');
  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await page.waitForTimeout(500);
  assert((await values()).every((video) => video.rate === 2));
  await page
    .locator('video')
    .last()
    .evaluate((video) =>
      Object.defineProperty(video, 'readyState', {
        get: () => 2,
        configurable: true,
      }),
    );
  await page.waitForTimeout(150);
  assert(
    (await values()).every((video) => video.paused),
    'one stream buffering pauses both',
  );
  await page
    .locator('video')
    .last()
    .evaluate((video) => {
      delete video.readyState;
    });
  await page.waitForTimeout(300);
  assert(
    (await values()).every((video) => !video.paused),
    'both resume when buffer is ready',
  );
  await page
    .locator('video')
    .last()
    .evaluate((video) => {
      video.currentTime -= 0.7;
    });
  await page.waitForTimeout(300);
  const synced = await values();
  assert(
    Math.abs(synced[0].time - synced[1].time) < 0.25,
    'screen drift corrected',
  );
  await page.getByRole('button', { name: 'Пауза', exact: true }).click();
  await seek(17000);
  await page.waitForTimeout(200);
  assert.equal(await page.locator('video').count(), 0);
  assert(await page.getByText('Нет записи экрана на этом участке').isVisible());
  await page
    .getByRole('button', { name: 'Показать весь ответ', exact: true })
    .click();
  await seek(22000);
  await page.waitForTimeout(300);
  const restarted = await values();
  assert.equal(restarted.length, 2);
  assert(Math.abs(restarted[0].time - 2) < 0.1);
  assert(Math.abs(restarted[1].time - 2) < 0.1);
  await page
    .locator('video')
    .first()
    .evaluate((video) => video.dispatchEvent(new Event('error')));
  await page.waitForTimeout(300);
  assert.equal(await page.evaluate(() => window.refreshCalls), 1);
  assert(Math.abs((await values())[0].time - 2) < 0.1);
  await page.getByRole('button', { name: 'Повторить', exact: true }).click();
  await page.waitForTimeout(350);
  assert(Number(await page.getByRole('slider').inputValue()) < 11000);
  await page.getByRole('button', { name: 'Пауза', exact: true }).click();
  await seek(25500);
  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await page.waitForTimeout(550);
  assert.equal(
    Number(await page.getByRole('slider').inputValue()),
    26000,
    'playback stops at range end',
  );
  assert(
    await page.getByRole('button', { name: 'Play', exact: true }).isVisible(),
  );
  await page.getByRole('button', { name: 'Повторить', exact: true }).click();
  await page.waitForTimeout(350);
  await page.waitForTimeout(700);
  if (process.env.EVIDENCE_SCREENSHOT_PATH)
    await page.screenshot({
      path: process.env.EVIDENCE_SCREENSHOT_PATH,
      fullPage: true,
    });
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click();
  assert.equal(await page.locator('video').count(), 0);
  await page.evaluate((manifest) => {
    // Keep the native function; the test explicitly restores its media receiver via call().
    // oxlint-disable-next-line typescript/unbound-method
    const nativePlay = HTMLMediaElement.prototype.play;
    let deny = true;
    HTMLMediaElement.prototype.play = function () {
      if (deny) {
        deny = false;
        return Promise.reject(
          new DOMException('User gesture required', 'NotAllowedError'),
        );
      }
      return nativePlay.call(this);
    };
    window.mountPlayer(manifest);
  }, manifest);
  await page.waitForTimeout(300);
  assert(
    await page
      .getByText('Нажмите Play, чтобы запустить запись со звуком.')
      .isVisible(),
  );
  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await page.waitForTimeout(350);
  assert(
    !(await values())[0].paused,
    'explicit play recovers from autoplay denial',
  );
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await page.evaluate((url) => window.mountLegacy(url), manifest.camera[0].url);
  await page.getByRole('button', { name: 'слово', exact: true }).click();
  await page.waitForTimeout(350);
  assert.equal(
    await page.locator('video').count(),
    1,
    'old answer uses single-stream player',
  );
  await page
    .getByRole('button', { name: 'Показать весь ответ', exact: true })
    .click();
  assert(
    Number(await page.getByRole('slider').getAttribute('max')) > 6000,
    'legacy duration inferred from metadata',
  );
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click();
  const finding = {
    id: 'synthetic',
    interviewId: 'i1',
    questionId: 'q1',
    category: 'external_assistance',
    source: 'vlm',
    observation: 'На экране открыт AI-чат.',
    reason: 'Нужно сопоставить содержимое с ответом.',
    alternativeExplanations: ['Обычная справочная вкладка.'],
    limitations: ['Сообщение читается частично.'],
    startMs: 12000,
    endMs: 13000,
    evidenceRefs: [{ mediaId: 'cam-1', startMs: 12000, endMs: 13000 }],
    observability: 'partial',
    videoAvailable: true,
    review: null,
  };
  const summary = {
    enabled: true,
    session: null,
    findings: [finding, { ...finding, id: 'missing', videoAvailable: false }],
    recordingCoverage: {
      cameraMs: 12000,
      screenMs: 11000,
      jointMs: 11000,
      totalMs: 16000,
    },
    analysisCoverage: { analyzedMs: 10000, totalMs: 16000 },
    costUsd: 0.0132,
    costKnown: false,
    pendingJobs: 0,
    failedJobs: 0,
  };
  let saved = null;
  await page.route(
    '**/api/v1/candidates/candidate-one/integrity**',
    async (route) => {
      const url = route.request().url();
      if (url.endsWith('/playback')) return route.fulfill({ json: manifest });
      if (url.endsWith('/review')) {
        saved = route.request().postDataJSON();
        finding.review = { ...saved, reviewedAt: new Date().toISOString() };
        return route.fulfill({ json: finding.review });
      }
      return route.fulfill({ json: summary });
    },
  );
  await page.evaluate(() => window.mountReview());
  await page.getByRole('button', { name: /Посмотреть фрагмент/ }).waitFor();
  assert.equal(
    await page.getByRole('button', { name: /Посмотреть фрагмент/ }).count(),
    1,
    'missing media has no broken play button',
  );
  assert(await page.getByText('Видео этого интервала отсутствует').isVisible());
  assert(await page.getByText('Стоимость частично неизвестна').isVisible());
  await page.getByRole('button', { name: /Посмотреть фрагмент/ }).click();
  const dialog = page.getByRole('dialog');
  await dialog
    .getByRole('button', { name: 'Нарушение подтверждено', exact: true })
    .click();
  assert(
    await dialog
      .getByRole('button', { name: 'Сохранить решение', exact: true })
      .isDisabled(),
  );
  await dialog
    .getByRole('textbox')
    .fill('Проверено в записи: ответ был скопирован из чата.');
  await dialog
    .getByRole('button', { name: 'Сохранить решение', exact: true })
    .click();
  await page.waitForTimeout(200);
  assert.equal(saved.decision, 'confirmed');
  assert(saved.comment.length > 0);
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click();
  assert.deepEqual(errors, []);
  console.log('Browser interaction checks passed');
} finally {
  await browser.close();
}
