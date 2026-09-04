# Remote stands on 84.201.155.4

Nginx exposes TCP 3000–3003. Each stand routes UI, /api/, /health,
/docs, /openapi.json and /ai-interviews/ through its single public port.

| Stand | Public | UI loopback | API loopback | PostgreSQL loopback | S3 loopback | MinIO console loopback | Compose project |
|---|---:|---:|---:|---:|---:|---:|---|
| Current | 3000 | 13000 | 18000 | 15432 | 19000 | 19010 | ai-interview |
| Colleague 1 | 3001 | 13001 | 18001 | 15433 | 19001 | 19011 | ai-interview-dev1 |
| Colleague 2 | 3002 | 13002 | 18002 | 15434 | 19002 | 19012 | ai-interview-dev2 |
| Demo | 3003 | 13003 | 18003 | 15435 | 19003 | 19013 | ai-interview-demo |

Only the current stand has been deployed. Ports 3001–3003 have proxy routes;
until their containers start, those routes return HTTP 502.

## Start another stand

Use a separate repository checkout and its own .env. Copy .env.example, set
independent database/MinIO credentials and your model API key, then chmod 600 .env.
Do not reuse the current stand's COMPOSE_PROJECT_NAME: it controls container,
network and volume isolation. Always run commands from that stand's checkout.

For colleague 1 use these non-secret settings (adjust by the table for others):

```dotenv
COMPOSE_PROJECT_NAME=ai-interview-dev1
HOST_BIND_ADDRESS=127.0.0.1
UI_PORT=13001
BACKEND_PORT=18001
POSTGRES_PORT=15433
MINIO_API_PORT=19001
MINIO_CONSOLE_PORT=19011
S3_BUCKET=ai-interviews
NEXT_PUBLIC_API_BASE_URL=http://84.201.155.4:3001
S3_PUBLIC_BASE_URL=http://84.201.155.4:3001
CORS_ORIGINS=http://84.201.155.4:3001
APP_BASE_URL=http://84.201.155.4:3001
WORKFLOW_INVITE_BASE_URL=http://84.201.155.4:3001/?invite=
SESSION_COOKIE_NAME=signal_session_3001
```

Add compose.override.yaml in each checkout:

```yaml
services:
  backend:
    environment:
      SESSION_COOKIE_NAME: ${SESSION_COOKIE_NAME:-signal_session}
```

Cookie names must differ because browsers share cookies across ports on the same
host. Keep S3_BUCKET=ai-interviews to match the proxy route; each stand has its own
MinIO and volume, so this bucket name does not share data between stands.

```sh
sudo docker compose config --quiet
sudo docker compose up --build --detach
sudo make smoke
sudo docker compose ps
```

Changing NEXT_PUBLIC_API_BASE_URL requires rebuilding UI. Credentials and URLs
must remain in the ignored .env, not in committed files. Persistent data lives in
Compose volumes; docker compose down does not erase it.

## Host configuration

- Proxy: /etc/nginx/sites-available/ai-hack
- Check: sudo nginx -t && sudo systemctl reload nginx
- Logs: sudo docker compose logs --tail=100

Public HTTP is suitable for checking UI/API. Browser microphone/camera use on a
public origin requires HTTPS; configure DNS/TLS before a complete remote interview.
