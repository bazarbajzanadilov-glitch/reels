#!/usr/bin/env bash
# Получает HTTPS-сертификат, как только DNS домена указывает на этот сервер. Запускается cron каждые 10 минут;
# после успеха больше ничего не делает (продление — штатный таймер certbot).
DOMAIN="${1:-reels.ai-studio.kz}"
EMAIL="${2:-}"
[ -d "/etc/letsencrypt/live/$DOMAIN" ] && exit 0
MYIP=$(curl -s -4 --max-time 10 https://api.ipify.org || true)
DNSIP=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1{print $1}')
[ -n "$MYIP" ] && [ "$MYIP" = "$DNSIP" ] || exit 0
if [ -n "$EMAIL" ]; then CONTACT=(-m "$EMAIL"); else CONTACT=(--register-unsafely-without-email); fi
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --redirect "${CONTACT[@]}" >>/var/log/reels-cert.log 2>&1
