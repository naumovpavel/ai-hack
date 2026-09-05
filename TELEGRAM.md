# Telegram: вход и уведомления

Кнопка «Войти через Telegram» открывает бота. После «Старт» исходная вкладка
автоматически получает сессию. Один Telegram ID соответствует одному аккаунту;
в меню аккаунта доступны кабинеты HR и кандидата, а также выход.

Приглашения `/?invite=...`, `/invite/...` и `/interview/...` требуют входа.
После входа сайт проверяет приглашение и привязывает кандидата к аккаунту.
Если в резюме указан Telegram, для первой привязки требуется совпадение ника.
Если ника нет, действующее персональное приглашение может принять вошедший
пользователь. После привязки доступ определяется аккаунтом, а не изменяемым ником.

Из текста PDF/DOCX/TXT извлекаются `t.me/username`, `telegram.me/username`,
`Telegram: username`, `@username`. Email и явно подписанные контакты других
сервисов пропускаются. HR видит найденный ник и может исправить его перед сохранением.

Кандидат получает приглашение, подтверждение записи интервью и решение рекрутера
с публичной обратной связью. HR получает уведомления о приглашении, начале,
завершении записи, готовности/ошибке анализа и решении по кандидату.
Отправка возможна только в известный личный чат пользователя, запускавшего бота.
Внутренняя причина отказа не включается в сообщение кандидату.

## Настройки

В игнорируемом корневом `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=<токен из BotFather>
TELEGRAM_BOT_USERNAME=sslopy_bot
TELEGRAM_UPDATE_MODE=polling
APP_BASE_URL=http://localhost:3100
WORKFLOW_INVITE_BASE_URL=http://localhost:3100/?invite=
CORS_ORIGINS=http://localhost:3100,http://127.0.0.1:3100
SESSION_COOKIE_NAME=signal_telegram_session
```

В `ui/.env.local`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100
```

Имя бота можно не указывать: backend получает его через `getMe`. Для текущего
worktree локальные файлы настроек уже заполнены. Compose также передаёт настройки
Telegram из корневого `.env`; для стандартных портов Compose используйте адреса
из `.env.example`.

## Локальный запуск

Из корня worktree, с установленными зависимостями Python и Node.js 22.13+,
в двух терминалах:

```bash
SIGNAL_LOCAL_DATABASE_URL=sqlite+aiosqlite:////private/tmp/signal-telegram-auth.sqlite3 \
SIGNAL_LOCAL_MEDIA_ROOT=/private/tmp/signal-telegram-auth-media \
backend/.venv/bin/uvicorn interview_api.local_demo:app \
  --app-dir backend/src --host 127.0.0.1 --port 8100
```

```bash
cd ui
./node_modules/.bin/vinext dev --port 3100
```

Откройте http://localhost:3100. В режиме polling нужен **один процесс backend
на один токен бота**, без нескольких uvicorn workers. Публичный адрес для бота
не нужен. Telegram polling cursor хранится в БД и восстанавливается после рестарта.

Для сервера с публичным HTTPS можно включить `TELEGRAM_UPDATE_MODE=webhook`,
задать `TELEGRAM_WEBHOOK_SECRET` и зарегистрировать в Telegram `setWebhook` с
URL `https://<api-host>/api/v1/telegram/webhook` и тем же `secret_token`.
Настройки webhook автоматически не меняются. Для возврата к polling сначала
удалите webhook через Bot API. `TELEGRAM_UPDATE_MODE=disabled` отключает фоновые
обращения к Telegram; это удобно для изолированных тестов.

Cookie используют HttpOnly, SameSite=Lax и опциональный Secure через
`WORKFLOW_COOKIE_SECURE=true`. UI и API должны быть на одном сайте
(например, `app.example.com` и `api.example.com`); межсайтовые cookie эта
конфигурация не поддерживает.

## API и хранение

- `POST /api/v1/auth/telegram/start` — `{role, inviteToken?}`, возвращает ссылку
  и время истечения; отдельный HttpOnly cookie привязывает ожидание к браузеру.
- `GET /api/v1/auth/telegram/status` — `pending`, `expired` или `authenticated`.
- `POST /api/v1/auth/role` — `{role: "hr" | "candidate"}`, сохраняет аккаунт
  и выбранное интервью, заменяя текущую сессию.
- `DELETE /api/v1/auth/session` — отзывает сессию в БД и очищает cookie.
- `POST /api/v1/invites/resolve` — требует Telegram-сессию и проверяет владельца.
- `POST /api/v1/telegram/webhook` — проверяет секрет Telegram-заголовка;
  без настройки webhook недоступен.

Запрос входа действует пять минут; в БД хранятся хэши двух разных секретов.
Подтверждение можно погасить только один раз. Блокировка уведомлений бота
не удаляет связь аккаунта с Telegram. Тестовый вход выключен по умолчанию и
всегда выключен при настроенном токене или `APP_ENV=production`.

Схема автоматически расширяется без удаления имеющихся записей. Уведомления
хранятся в outbox, повторяются при временных ошибках и учитывают Telegram 429.
При блокировке бота доставка прекращается до следующего `/start`.
После аварии между отправкой и фиксацией результата возможно повторное сообщение.

## Проверка

```bash
cd backend
.venv/bin/python -m pytest
.venv/bin/python -m ruff check src tests
```

В `ui`: `./node_modules/.bin/tsc --noEmit --incremental false`,
`./node_modules/.bin/oxlint`, `./node_modules/.bin/vinext build`.
Тесты бота используют подставные обновления/транспорт и не отправляют сообщения.

Протокол основан на официальной документации Telegram:
[deep links](https://core.telegram.org/bots/features#deep-linking),
[getUpdates](https://core.telegram.org/bots/api#getupdates),
[setWebhook](https://core.telegram.org/bots/api#setwebhook).
