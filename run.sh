#!/usr/bin/env bash
# Запуск одной командой для macOS и Linux.
#   ./run.sh          — запустить сервер на http://localhost:8080 (при первом запуске поставит всё нужное)
#   ./run.sh dev      — то же, но с DEV_MODE=1: Mini App открывается в обычном браузере (только для теста!)
#   ./run.sh demo     — собрать пробную книгу из samples/profile_example.json без сервера
#   ./run.sh check    — проверить ключи из .env
#   ./run.sh botprofile — оформить бота: описание, команды, кнопка меню (./run.sh botprofile --name — ещё и имя)
#   ./run.sh story    — показать сказку, которую пишет выбранный в .env текстовый провайдер (без картинок)
#   ./run.sh test     — запустить автоматические проверки
set -e
cd "$(dirname "$0")"

say() { printf '%s\n' "$*"; }

# 1. Ищем Python 3.11 или новее
PY=""
for candidate in python3.12 python3.13 python3.14 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  say "Не нашёл Python версии 3.11 или новее."
  say "Установите его: https://www.python.org/downloads/  (на macOS можно: brew install python@3.12)"
  say "Потом закройте и снова откройте терминал и повторите ./run.sh"
  exit 1
fi

# 2. Файл с настройками
if [ ! -f .env ]; then
  cp .env.example .env
  say "Создал файл .env из шаблона. Пока ключей нет — всё работает на заглушках."
fi

# 3. Виртуальное окружение и зависимости
VENV=".venv"
if [ ! -x "$VENV/bin/python" ]; then
  say "Создаю виртуальное окружение (один раз)…"
  "$PY" -m venv "$VENV"
fi
hash_of() { "$VENV/bin/python" -c 'import hashlib,sys; print(hashlib.sha256(b"".join(open(f,"rb").read() for f in sys.argv[1:])).hexdigest())' "$@"; }
install_deps() { # $1 — файл для pip, $2 — имя метки, остальное — файлы, по которым видно, что зависимости изменились
  local file="$1" label="$2"; shift 2
  local stamp="$VENV/.deps-$label" now
  now="$(hash_of "$@")"
  if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$now" ]; then
    say "Ставлю зависимости (один раз, около минуты)…"
    "$VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    "$VENV/bin/python" -m pip install --quiet -r "$file"
    printf '%s\n' "$now" > "$stamp"
  fi
}

MODE="${1:-start}"
if [ "$MODE" = "test" ]; then
  install_deps requirements-dev.txt dev requirements.txt requirements-dev.txt
else
  install_deps requirements.txt main requirements.txt
fi

export PYTHONUTF8=1
case "$MODE" in
  start)  exec "$VENV/bin/python" -m app.main ;;
  dev)    export DEV_MODE=1; say "DEV_MODE=1 на этот запуск: откройте http://localhost:8080 в браузере."; exec "$VENV/bin/python" -m app.main ;;
  demo)   shift || true; exec "$VENV/bin/python" demo.py "$@" ;;
  check)  exec "$VENV/bin/python" check_keys.py ;;
  botprofile) shift || true; exec "$VENV/bin/python" setup_bot.py "$@" ;;
  story)  shift || true; exec "$VENV/bin/python" story_preview.py "$@" ;;
  test)   exec "$VENV/bin/python" -m pytest -q ;;
  *)      say "Не знаю такой команды: $MODE"; say "Можно: ./run.sh | dev | demo | check | story | botprofile | test"; exit 1 ;;
esac
