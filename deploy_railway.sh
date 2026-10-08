#!/usr/bin/env bash
# Выкладывает «Персональную сказку» на Railway:   ./deploy_railway.sh
# Ключи берутся из вашего .env и уходят только в раздел Variables на Railway.
# Повторный запуск обновляет уже созданный сервис.
set -euo pipefail
cd "$(dirname "$0")"

fail() { printf '\n\033[31mОШИБКА: %s\033[0m\n' "$*" >&2; exit 1; }
say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

command -v railway >/dev/null || fail "Не найден railway. Установка: brew install railway"
[ -f .env ] || fail "Нет файла .env."
if ! railway whoami >/dev/null 2>&1; then
  fail "Вы не вошли в Railway. Выполните в терминале:  railway login   (откроется браузер), потом запустите этот скрипт снова."
fi

say "1/5  Проект Railway"
if ! railway status >/dev/null 2>&1; then
  WS="$(railway whoami --json 2>/dev/null | python3 -c 'import sys,json; w=json.load(sys.stdin).get("workspaces") or []; print(w[0]["id"] if w else "")' 2>/dev/null || true)"
  if [ -n "$WS" ]; then railway init --name skazka --workspace "$WS"; else railway init --name skazka; fi
fi
if ! railway variable list >/dev/null 2>&1; then
  railway add --service skazka
  railway service link skazka || true
fi

say "2/5  Постоянный диск для базы и книг (/data)"
if railway volume list 2>/dev/null | grep -q "/data"; then
  echo "Диск уже есть."
else
  railway volume add --mount-path /data || echo "Не удалось добавить диск автоматически: добавьте Volume с путём /data в панели Railway (сервис → Settings → Volumes)."
fi

say "3/5  Переношу настройки из .env (значения на экран не выводятся)"
SKIP='^(WEBAPP_URL|HOST|PORT|DATA_DIR|DEV_MODE)$'
COUNT=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|'#'*) continue;; esac
  key="${line%%=*}"; val="${line#*=}"
  key="$(printf '%s' "$key" | tr -d '[:space:]')"
  [[ "$key" =~ ^[A-Z0-9_]+$ ]] || continue
  [[ "$key" =~ $SKIP ]] && continue
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  [ -n "$val" ] || continue
  printf '%s' "$val" | railway variable set "$key" --stdin --skip-deploys >/dev/null
  COUNT=$((COUNT+1))
done < .env
printf '%s' "0" | railway variable set DEV_MODE --stdin --skip-deploys >/dev/null
echo "Перенесено настроек: $COUNT (DEV_MODE на сервере всегда 0)."

say "4/5  Публичный адрес (HTTPS)"
railway domain || echo "Если адрес не создался: в панели Railway → сервис → Settings → Networking → Generate Domain."

say "5/5  Загружаю и запускаю (2–4 минуты)"
if pgrep -f "python.* -m app.main" >/dev/null 2>&1; then
  echo "На этом компьютере запущен бот. Два бота с одним токеном мешают друг другу."
  read -r -p "Остановить локальный бот сейчас? [Д/н] " ANSWER || ANSWER="Д"
  case "${ANSWER:-Д}" in [Нн]*) echo "Остановите его сами, иначе будет ошибка «Conflict».";; *) pkill -INT -f "python.* -m app.main" || true; sleep 2;; esac
fi
railway up --ci

echo
echo "Готово. Откройте бота в Telegram и отправьте /start."
echo "Логи:  railway logs"
