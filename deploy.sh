#!/usr/bin/env bash
# Выкладывает «Персональную сказку» на сервер одной командой:
#     ./deploy.sh root@IP-АДРЕС
# Повторный запуск обновляет сервер (база заказов на сервере сохраняется).
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "Использование:  ./deploy.sh root@IP-АДРЕС"
  echo "IP-адрес и пароль выдаёт хостинг после заказа сервера (Ubuntu 24.04, от 1 ГБ памяти)."
  exit 1
fi
[ -f .env ] || { echo "Нет файла .env — сначала заполните его (см. README.md)."; exit 1; }
grep -q '^TELEGRAM_BOT_TOKEN=.\+' .env || { echo "В .env пустая строка TELEGRAM_BOT_TOKEN."; exit 1; }
command -v ssh >/dev/null && command -v scp >/dev/null || { echo "Не нашёл ssh/scp. На Windows запускайте из Git Bash или WSL."; exit 1; }

WORK="$(mktemp -d)"
trap 'ssh -O exit -o ControlPath="$WORK/ssh.sock" "$TARGET" >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
ARCHIVE="$WORK/skazka.tar.gz"

echo "==> Упаковываю проект (без ключей и без локальной базы)"
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" \
  --exclude='./.env' --exclude='./.env.*' --exclude='./.venv' --exclude='./data' --exclude='./demo_output' \
  --exclude='./branding' --exclude='./tests' --exclude='./.git' --exclude='__pycache__' --exclude='.pytest_cache' \
  --exclude='.DS_Store' --exclude='._*' .
# .env.example нужен приложению как образец — кладём его отдельно
SSH_OPTS=(-o ControlMaster=auto -o ControlPath="$WORK/ssh.sock" -o ControlPersist=300 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=20)

echo "==> Подключаюсь к $TARGET (если спросит пароль — введите пароль от сервера; символы при вводе не видны)"
ssh "${SSH_OPTS[@]}" "$TARGET" true
REMOTE_HOME="$(ssh "${SSH_OPTS[@]}" "$TARGET" 'printf %s "$HOME"')"
REMOTE_UID="$(ssh "${SSH_OPTS[@]}" "$TARGET" 'id -u')"
SUDO=""; [ "$REMOTE_UID" = "0" ] || SUDO="sudo"

echo "==> Копирую файлы на сервер"
scp -q "${SSH_OPTS[@]}" "$ARCHIVE" "$TARGET:$REMOTE_HOME/skazka.tar.gz"
scp -q "${SSH_OPTS[@]}" .env "$TARGET:$REMOTE_HOME/skazka.env"
ssh "${SSH_OPTS[@]}" "$TARGET" "chmod 600 $REMOTE_HOME/skazka.env"

if pgrep -f "python.* -m app.main" >/dev/null 2>&1; then
  echo
  echo "На этом компьютере сейчас запущен бот. Его нужно остановить: два бота с одним токеном мешают друг другу."
  read -r -p "Остановить локальный бот сейчас? [Д/н] " ANSWER || ANSWER="Д"
  case "${ANSWER:-Д}" in
    [Нн]*) echo "Хорошо, но остановите его сами, иначе бот на сервере будет получать ошибку «Conflict».";;
    *) pkill -INT -f "python.* -m app.main" || true; sleep 2; echo "Локальный бот остановлен.";;
  esac
fi

echo "==> Устанавливаю на сервере (это займёт 2–5 минут, не закрывайте окно)"
ssh -t "${SSH_OPTS[@]}" "$TARGET" "$SUDO env ARCHIVE=$REMOTE_HOME/skazka.tar.gz ENV_UPLOAD=$REMOTE_HOME/skazka.env DOMAIN='${DOMAIN:-}' bash -s" < deploy/install_server.sh
