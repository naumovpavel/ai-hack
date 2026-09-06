# Integrity playback checks

The deterministic timeline checks need Node 22.18+ (or Node 22 with `--experimental-strip-types`):

```sh
node --test tests/evidence-timeline.test.mjs
```

The browser fixture renders the real player, legacy answer evidence and integrity cards. It records a synthetic canvas video locally and uses intercepted API responses; no candidate media, backend or API keys are needed.

Start the isolated fixture from `ui/`:

```sh
pnpm exec vite --config tests/fixtures/evidence-player/vite.config.mjs
```

Then run the suite with an available Playwright installation and Chromium:

```sh
PLAYWRIGHT_MODULE=/absolute/path/to/playwright/index.mjs \
PLAYWRIGHT_EXECUTABLE_PATH=/absolute/path/to/chromium \
node tests/evidence-player.browser.mjs
```

If Playwright and its matching browser are installed in the environment, both variables can be omitted. Optional `EVIDENCE_SCREENSHOT_PATH` writes a screenshot; `EVIDENCE_TEST_URL` overrides the fixture URL (default `http://127.0.0.1:4319`).

Checks cover initial context and autoplay, explicit Play after browser autoplay denial, master clock and recorder offsets, common pause/seek/speed, screen gaps, buffering of either stream, drift recovery, manifest refresh without losing position, repeat, stop at range end, close cleanup, the legacy answer player, missing-video cards and mandatory comments for confirmed findings. Timeline tests additionally cover episodes crossing the 120-second analysis boundary and context bounds.

MinIO Range/CORS and signed-link authorization are backend integration checks; blob-backed synthetic media cannot verify those transport properties.
