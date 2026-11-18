#!/usr/bin/env bash
# Установка/обновление на Ubuntu VPS без Docker (nginx + systemd). Запускать от root:
#   bash /opt/reels/deploy/install-vps.sh reels.ai-studio.kz admin@example.com
# Перед первым запуском положить /opt/reels/.env (см. .env.example).
set -euo pipefail
DOMAIN="${1:-reels.ai-studio.kz}"
EMAIL="${2:-}"
APP=/opt/reels

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git ffmpeg fonts-dejavu-core python3-venv nginx certbot python3-certbot-nginx >/dev/null

id reels >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin reels
[ -d "$APP/.git" ] || git clone -q https://github.com/bazarbajzanadilov-glitch/reels.git "$APP"
cd "$APP"
git pull -q --ff-only || true

[ -f .env ] || { echo "Нет $APP/.env — создайте его по .env.example"; exit 1; }
chmod 600 .env

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.lock

mkdir -p jobs cache .models backups
chown -R reels:reels "$APP"
chmod 700 jobs backups

install -m 644 deploy/systemd/reels-web.service /etc/systemd/system/reels-web.service
install -m 644 deploy/systemd/reels-worker.service /etc/systemd/system/reels-worker.service
systemctl daemon-reload
systemctl enable --now reels-web reels-worker
systemctl restart reels-web reels-worker

sed "s/reels.ai-studio.kz/$DOMAIN/g" deploy/nginx/reels.ai-studio.kz.conf > "/etc/nginx/sites-available/$DOMAIN.conf"
ln -sf "/etc/nginx/sites-available/$DOMAIN.conf" "/etc/nginx/sites-enabled/$DOMAIN.conf"
nginx -t
systemctl reload nginx

# HTTPS: сразу, если DNS уже указывает сюда; иначе cron пробует каждые 10 минут
install -m 755 deploy/reels-cert.sh /usr/local/bin/reels-cert.sh
echo "*/10 * * * * root /usr/local/bin/reels-cert.sh $DOMAIN $EMAIL" > /etc/cron.d/reels-cert
/usr/local/bin/reels-cert.sh "$DOMAIN" "$EMAIL" || true
[ -d "/etc/letsencrypt/live/$DOMAIN" ] && echo "HTTPS: есть" || echo "HTTPS: ждёт DNS-запись $DOMAIN -> IP сервера"
systemctl status reels-web reels-worker --no-pager -n 3
echo "Готово: https://$DOMAIN"
