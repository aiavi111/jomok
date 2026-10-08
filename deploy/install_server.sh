#!/usr/bin/env bash
# Ставит «Персональную сказку» на чистый сервер (Ubuntu 22.04 / 24.04 или Debian 12).
# Запускается НА СЕРВЕРЕ от root; обычно его запускает deploy.sh с вашего компьютера.
#
# Что делает: ставит Python и Caddy, раскладывает проект в /opt/skazka, создаёт службу systemd
# (автозапуск и перезапуск при сбоях) и получает бесплатный HTTPS-адрес вида 1-2-3-4.sslip.io.
set -euo pipefail

APP_USER=skazka
APP_DIR=/opt/skazka
ARCHIVE="${ARCHIVE:-/root/skazka.tar.gz}"
ENV_UPLOAD="${ENV_UPLOAD:-/root/skazka.env}"
DOMAIN="${DOMAIN:-}"                 # необязательно: свой домен вместо sslip.io
SKIP_SYSTEMD="${SKIP_SYSTEMD:-0}"    # только для проверки в контейнере

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*" >&2; }
fail() { printf '\n\033[31mОШИБКА: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ]            || fail "Запускать нужно от root (или через sudo)."
[ -f "$ARCHIVE" ]               || fail "Не нашёл архив проекта: $ARCHIVE"
[ -f "$ENV_UPLOAD" ]            || fail "Не нашёл файл настроек: $ENV_UPLOAD"
command -v apt-get >/dev/null   || fail "Скрипт рассчитан на Ubuntu или Debian (нужен apt-get)."
export DEBIAN_FRONTEND=noninteractive

say "1/6  Ставлю программы (1–3 минуты)"
apt-get update -y
apt-get install -y ca-certificates curl gnupg python3 python3-venv python3-pip \
  debian-keyring debian-archive-keyring apt-transport-https

PY=python3
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  warn "В системе Python старше 3.11 — ставлю Python 3.12 из deadsnakes."
  apt-get install -y software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa || fail "Не получилось подключить репозиторий Python. Возьмите сервер с Ubuntu 24.04."
  apt-get update -y
  apt-get install -y python3.12 python3.12-venv
  PY=python3.12
fi

if ! command -v caddy >/dev/null; then
  say "2/6  Ставлю Caddy (он выдаёт HTTPS-сертификат)"
  if curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
     && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' -o /etc/apt/sources.list.d/caddy-stable.list; then
    apt-get update -y
    apt-get install -y caddy
  else
    warn "Официальный репозиторий Caddy недоступен — ставлю версию из системы."
    apt-get install -y caddy
  fi
else
  say "2/6  Caddy уже установлен"
fi

say "3/6  Раскладываю проект в $APP_DIR"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR"
tar -xzf "$ARCHIVE" -C "$APP_DIR"
install -m 600 "$ENV_UPLOAD" "$APP_DIR/.env"
"$PY" -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

set_env() {   # set_env КЛЮЧ ЗНАЧЕНИЕ — меняет строку в .env или добавляет её
  local key="$1" val="$2"
  if grep -q "^${key}=" "$APP_DIR/.env"; then sed -i "s|^${key}=.*|${key}=${val}|" "$APP_DIR/.env"; else printf '%s=%s\n' "$key" "$val" >> "$APP_DIR/.env"; fi
}

say "4/6  Определяю адрес сервера"
if [ -n "$DOMAIN" ]; then
  PUBLIC_HOST="$DOMAIN"
else
  PUBLIC_IP="$(curl -4 -fsS --max-time 10 https://api.ipify.org 2>/dev/null || curl -4 -fsS --max-time 10 https://ifconfig.me 2>/dev/null || true)"
  [ -n "$PUBLIC_IP" ] || fail "Не удалось узнать внешний IP-адрес сервера. Проверьте, что у сервера есть интернет."
  PUBLIC_HOST="$(printf '%s' "$PUBLIC_IP" | tr . -).sslip.io"
fi
echo "Адрес Mini App: https://$PUBLIC_HOST"
set_env WEBAPP_URL "https://$PUBLIC_HOST"
set_env DEV_MODE 0                  # на сервере проверка подписи Telegram всегда включена
set_env HOST 127.0.0.1              # наружу сервер смотрит только через Caddy
set_env PORT 8080
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

say "5/6  Настраиваю автозапуск и HTTPS"
if [ -d /run/systemd/system ] && [ "$SKIP_SYSTEMD" != "1" ]; then
  cat > /etc/systemd/system/skazka.service <<UNIT
[Unit]
Description=Persональная сказка: Mini App и бот
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUTF8=1
ExecStart=$APP_DIR/.venv/bin/python -m app.main
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
UNIT
  sed -i 's/^Description=Persональная/Description=Персональная/' /etc/systemd/system/skazka.service
else
  warn "systemd не найден — службу не создаю (нормально для проверки в контейнере)."
fi

[ -f /etc/caddy/Caddyfile ] && [ ! -f /etc/caddy/Caddyfile.original ] && cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.original || true
mkdir -p /etc/caddy
cat > /etc/caddy/Caddyfile <<CADDY
$PUBLIC_HOST {
	encode gzip
	reverse_proxy 127.0.0.1:8080
}
CADDY
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 || fail "Caddy не принял настройки (/etc/caddy/Caddyfile)."

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
fi

rm -f "$ENV_UPLOAD" "$ARCHIVE"        # на сервере не должно лежать лишних копий ключей

if [ -d /run/systemd/system ] && [ "$SKIP_SYSTEMD" != "1" ]; then
  systemctl daemon-reload
  systemctl enable skazka >/dev/null 2>&1
  systemctl restart skazka
  systemctl enable caddy >/dev/null 2>&1
  systemctl restart caddy
else
  echo "Проверка в контейнере завершена без запуска служб."
  exit 0
fi

say "6/6  Жду, пока сервер запустится и получит сертификат (до 2 минут)"
OK=0
for _ in $(seq 1 40); do
  if curl -fsS --max-time 8 "https://$PUBLIC_HOST/api/health" 2>/dev/null | grep -q '"ok"'; then OK=1; break; fi
  sleep 3
done

echo
if [ "$OK" = 1 ]; then
  printf '\033[32m✔ ГОТОВО. Mini App работает: https://%s\033[0m\n' "$PUBLIC_HOST"
  journalctl -u skazka --no-pager -n 40 2>/dev/null | grep -E "Бот @|Кнопка меню|Ошибка|ERROR" | sed 's/^/   /' || true
  echo
  echo "Откройте бота в Telegram, отправьте /start и нажмите «✨ Создать сказку»."
  echo "Логи:      journalctl -u skazka -f"
  echo "Перезапуск: systemctl restart skazka"
else
  warn "Сайт пока не отвечает по https://$PUBLIC_HOST. Что проверить:"
  warn "  1) В панели хостинга (фаервол/группа безопасности) должны быть открыты порты 80 и 443."
  warn "  2) systemctl status skazka    — работает ли приложение"
  warn "  3) journalctl -u caddy -n 40  — получил ли Caddy сертификат"
  systemctl --no-pager --lines=5 status skazka 2>&1 | sed 's/^/   /' || true
  exit 1
fi
