# CI/CD: тесты, образ в GHCR и деплой collector

Цепочка при push в `main`:

```text
CI (pytest, ruff, mypy, docker smoke) → сборка образа → ghcr.io → ручное подтверждение → SSH на сервер → pull + up collector
```

Workflow:

- [.github/workflows/ci.yml](../.github/workflows/ci.yml) — CI на каждый PR и push в `develop`; для `main` вызывается из деплоя.
- [.github/workflows/deploy.yml](../.github/workflows/deploy.yml) — сборка образа и деплой.

Образ: `ghcr.io/sorokad/tumar-collector`, теги `<полный sha коммита>` и `latest`.
Деплой обновляет только сервис `collector`. Prometheus, Alertmanager и alert-webhook из `docker/docker-compose.yml` не трогаются.

---

## 1. Когда срабатывает

| Событие | Что запускается |
|---------|-----------------|
| Pull request в любую ветку | CI |
| `push` в `develop` | CI |
| `push` в `main` с изменением `src/**`, `requirements.txt`, `docker/Dockerfile`, `docker/docker-compose.yml` | CI → образ → деплой (после подтверждения) |
| `workflow_dispatch` | ручной запуск Deploy из GitHub → Actions |

`ruff` и `mypy` пока не блокируют деплой (`continue-on-error` в `ci.yml`).

---

## 2. Однократная настройка GitHub

### Секреты

**Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret | Пример значения |
|--------|-----------------|
| `VPS_SSH_HOST` | IP сервера collector |
| `VPS_SSH_USER` | пользователь деплоя |
| `VPS_SSH_PRIVATE_KEY` | приватный deploy-ключ целиком |
| `VPS_DEPLOY_PATH` | корень клона репозитория, например `/opt/okx-hft-collector` |

### Окружение и ветка

- **Settings** → **Environments** → `production` → **Required reviewers** (себя), **Deployment branches** → `main`.
- **Settings** → **Branches** → правило для `main`: merge только через PR, обязательные проверки `test` и `docker`.

---

## 3. Однократная настройка сервера

```bash
cd /opt/okx-hft-collector          # VPS_DEPLOY_PATH
git status                          # локальных правок быть не должно: деплой делает git reset --hard
test -f docker/.env && chmod 600 docker/.env
docker compose version              # нужна v2.17+ для `up --wait --wait-timeout`
```

Collector должен быть запущен из `docker/` этого клона (`docker compose ps` в `docker/` показывает `collector`).
Иначе после деплоя появится второй collector, и порт 9108 будет занят.

---

## 4. Что делает деплой на сервере

1. `git fetch` + `git reset --hard <sha>` — только ради `docker/docker-compose.yml`.
2. Проверка `docker/.env`.
3. `docker login ghcr.io` временным `GITHUB_TOKEN`.
4. `docker compose pull collector` (до 3 попыток).
5. `docker compose up -d --no-deps --no-build --wait collector` — ждёт healthcheck (`/metrics` отвечает).
6. Проверка, что в логах нет `Working without storage` (collector подключился к PostgreSQL).
7. До 90 секунд ждёт появления `events_total` в `/metrics` — данные от OKX пошли.
8. `docker logout ghcr.io`.

При перезапуске collector получает SIGTERM, сбрасывает накопленные батчи в базу и выходит (`stop_grace_period: 30s`).
Пока новый контейнер подключается к OKX, данные за несколько секунд не собираются — это неизбежный разрыв при любом перезапуске.

---

## 5. Откат

Из GitHub: Actions → Deploy → старый успешный запуск → **Re-run all jobs**.

Вручную на сервере:

```bash
cd /opt/okx-hft-collector
git fetch origin && git reset --hard <старый_sha>
cd docker
COLLECTOR_IMAGE_TAG=<старый_sha> docker compose pull collector
COLLECTOR_IMAGE_TAG=<старый_sha> docker compose up -d --no-deps --no-build collector
```
