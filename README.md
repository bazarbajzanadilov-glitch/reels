# Reels Studio

Веб-сервис: описываете идею — получаете готовый ролик (9:16 или 16:9, до 15 минут) со сценарием, озвучкой,
анимацией, субтитрами, обложкой и текстами для YouTube, Instagram, TikTok и Facebook.
Вся генерация — через один ключ [Pollinations](https://pollinations.ai).

## Структура

```
server.py          веб-сервер и API
worker.py          очередь: генерация и монтаж роликов
manage.py          резервные копии и обслуживание
factory/           сценарий, голос, картинки, анимация, монтаж, бюджет
web/               интерфейс
  index.html       разметка
  css/app.css      единая дизайн-система
  js/*.js          клиентские скрипты
  voices/          пробы голосов
deploy/            установка на Ubuntu: install-vps.sh, systemd, nginx, HTTPS
tests/             проверки без платных запросов: python tests/run.py
```

## Настройки — `.env`

```
POLLINATIONS_KEY=sk_...
ACCESS_LOGIN=...         # логин входа (необязательно)
ACCESS_PASSWORD=...      # пароль входа
DOMAIN=reels.example.com
```

Остальные параметры — в `.env.example`.

## Установка на сервер (Ubuntu 24.04)

```sh
git clone https://github.com/bazarbajzanadilov-glitch/reels.git /opt/reels
cp /opt/reels/.env.example /opt/reels/.env   # заполнить
bash /opt/reels/deploy/install-vps.sh reels.example.com admin@example.com
```

Скрипт ставит ffmpeg и Python-окружение, службы `reels-web` и `reels-worker`, сайт nginx и HTTPS
(сертификат выдаётся автоматически, когда DNS домена указывает на сервер). Обновление — тот же скрипт.
Логи: `journalctl -u reels-web -u reels-worker -f`.

## Локально

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock
.venv/bin/python server.py      # http://127.0.0.1:8000
```

Синхронизация субтитров по словам (необязательно): `.venv/bin/pip install -r requirements-align.txt`.

## Проверки интерфейса

```sh
python tests/run.py                  # offline-тесты, без внешних запросов
START_WORKER=0 PORT=8765 .venv/bin/python server.py
uv pip install playwright --python .venv/bin/python
TEST_URL=http://127.0.0.1:8765 .venv/bin/python tests/mobile_ui.py
```

UI-тест проверяет 260–360 px с шагом 5 px и контрольные 375, 390, 414, 430, 480, 600, 768, 834,
1024, 1280, 1440 px. Используется локальный Chrome (`channel="chrome"`), интернет не нужен.
Скриншоты: `UI_SCREENSHOTS=1 TEST_URL=... .venv/bin/python tests/mobile_ui.py`.
