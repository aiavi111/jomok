"""Проверка ключей и настроек из файла .env.

Для каждого заполненного ключа делается одна дешёвая проверка:
  Telegram — getMe; OpenAI и Gemini — запрос модели (без расхода денег);
  Cloudflare — одна совсем маленькая картинка (около 30 из 10 000 бесплатных «нейронов» в сутки).
Значения ключей никогда не печатаются. Без интернета скрипт не падает, а объясняет, что случилось.

Запуск:  python check_keys.py     (или ./run.sh check)
"""
from __future__ import annotations

import base64
import difflib
import sys
from dataclasses import dataclass

import httpx

from app.config import ConfigError, Settings
from app.logging_setup import redact

OK, BAD, SKIP = "[ОК]    ", "[ОШИБКА]", "[ — ]   "
TELEGRAM = "https://api.telegram.org"
GEMINI = "https://generativelanguage.googleapis.com/v1beta"
CLOUDFLARE = "https://api.cloudflare.com/client/v4"


@dataclass
class Line:
    mark: str
    name: str
    text: str


class Offline(Exception):
    pass


class Checker:
    def __init__(self, settings: Settings, client: httpx.Client):
        self.s = settings
        self.client = client
        self.offline = False
        self.sections: list[tuple[str, list[Line]]] = []

    # ------------------------------------------------------------------ сеть
    def call(self, method: str, url: str, **kw) -> httpx.Response:
        if self.offline:
            raise Offline()
        try:
            return self.client.request(method, url, **kw)
        except httpx.TimeoutException:
            raise Offline("сервис не ответил за 15 секунд")
        except httpx.HTTPError:
            self.offline = True
            raise Offline()

    def add(self, section: str, mark: str, name: str, text: str) -> None:
        for title, lines in self.sections:
            if title == section:
                lines.append(Line(mark, name, text))
                return
        self.sections.append((section, [Line(mark, name, text)]))

    def offline_line(self, section: str, name: str, why: str = "") -> None:
        self.add(section, SKIP, name, why or "пропущено: нет подключения к интернету. Проверьте сеть и запустите проверку ещё раз.")

    # ------------------------------------------------------------------ Telegram
    def telegram(self) -> None:
        sec, name = "Telegram", "TELEGRAM_BOT_TOKEN"
        token = self.s.telegram_bot_token
        self.me: dict | None = None
        if not token:
            self.add(sec, BAD, name, "не заполнен. Токен выдаёт @BotFather в Telegram (команда /newbot, либо /token для готового бота).")
            return
        try:
            resp = self.call("GET", f"{TELEGRAM}/bot{token}/getMe")
        except Offline as e:
            self.offline_line(sec, name, str(e) or "")
            return
        if resp.status_code == 200 and resp.json().get("ok"):
            self.me = resp.json()["result"]
            self.add(sec, OK, name, f"токен принят, бот @{self.me.get('username')}.")
        elif resp.status_code in (401, 404):
            self.add(sec, BAD, name, "Telegram не принял токен. Откройте @BotFather → /mybots → ваш бот → API Token, "
                                     "скопируйте токен целиком (вида 123456:ABC…) в строку TELEGRAM_BOT_TOKEN файла .env.")
        else:
            self.add(sec, BAD, name, f"Telegram ответил неожиданно (код {resp.status_code}). Попробуйте позже.")

    def webapp(self) -> None:
        sec, name = "Telegram", "WEBAPP_URL"
        url = self.s.webapp_url
        if not url:
            self.add(sec, SKIP, name, "не заполнен. Он нужен, чтобы открыть Mini App в Telegram. Для теста запустите "
                                      "«cloudflared tunnel --url http://localhost:8080», он напечатает адрес https://…trycloudflare.com — "
                                      "впишите его сюда (при каждом запуске адрес новый).")
            return
        if not url.startswith("https://"):
            self.add(sec, BAD, name, "адрес должен начинаться с https:// — Telegram не принимает другие.")
            return
        try:
            resp = self.call("GET", f"{url}/api/health", follow_redirects=True)
        except Offline as e:
            self.offline_line(sec, name, str(e) or "")
            return
        try:
            healthy = resp.status_code == 200 and resp.json().get("status") == "ok"
        except ValueError:
            healthy = False
        if healthy:
            self.add(sec, OK, name, "адрес отвечает, сервер доступен снаружи.")
        else:
            self.add(sec, BAD, name, f"по этому адресу сервера нет (код {resp.status_code}). Запущен ли сервер (run.sh) и туннель "
                                     "cloudflared? Туннель при перезапуске получает новый адрес — впишите его и перезапустите сервер.")

    def admin(self) -> None:
        sec, name = "Telegram", "ADMIN_CHAT_ID"
        if self.s.admin_chat_id is None:
            self.add(sec, SKIP, name, "не заполнен (необязательно). Отправьте боту /id — он ответит числом для этой строки; "
                                      "туда будут приходить копии книг и отзывы.")
            return
        if not self.s.telegram_bot_token or self.me is None:
            self.add(sec, SKIP, name, "число задано; проверить его можно, только когда токен бота принят.")
            return
        try:
            resp = self.call("GET", f"{TELEGRAM}/bot{self.s.telegram_bot_token}/getChat", params={"chat_id": self.s.admin_chat_id})
        except Offline as e:
            self.offline_line(sec, name, str(e) or "")
            return
        if resp.status_code == 200:
            self.add(sec, OK, name, "чат найден, бот сможет туда писать.")
        else:
            self.add(sec, BAD, name, "бот не видит такой чат. Откройте своего бота в Telegram, нажмите «Запустить» (/start), "
                                     "затем отправьте /id и впишите именно это число.")

    # ------------------------------------------------------------------ провайдеры
    def providers_summary(self) -> None:
        s = self.s
        self.add("Что выбрано", OK, "TEXT_PROVIDER", f"{s.text_provider}" + (" (заглушки, ключ не нужен)" if s.text_provider == "mock" else ""))
        self.add("Что выбрано", OK, "IMAGE_PROVIDER", f"{s.image_provider}" + (" (заглушки, ключ не нужен)" if s.image_provider == "mock" else ""))

    def openai(self) -> None:
        sec, s = "OpenAI", self.s
        used = "openai" in (s.text_provider, s.image_provider)
        if not s.openai_api_key:
            if used:
                self.add(sec, BAD, "OPENAI_API_KEY", "не заполнен, а OpenAI выбран в .env. Ключ: platform.openai.com → API keys → "
                                                     "Create new secret key (показывается один раз). Нужен баланс от $5.")
            else:
                self.add(sec, SKIP, "OPENAI_API_KEY", "не заполнен (сейчас не нужен).")
            return
        try:
            resp = self.call("GET", f"{s.openai_base_url}/models", headers={"Authorization": f"Bearer {s.openai_api_key}"})
        except Offline as e:
            self.offline_line(sec, "OPENAI_API_KEY", str(e) or "")
            return
        if resp.status_code == 401:
            self.add(sec, BAD, "OPENAI_API_KEY", "OpenAI не принял ключ. Создайте новый на platform.openai.com → API keys и вставьте целиком (sk-…).")
            return
        if resp.status_code != 200:
            self.add(sec, BAD, "OPENAI_API_KEY", f"OpenAI ответил кодом {resp.status_code}. Попробуйте позже или проверьте OPENAI_BASE_URL.")
            return
        ids = [m.get("id", "") for m in (resp.json().get("data") or []) if isinstance(m, dict)]
        note = "" if used else " (сейчас не используется)"
        self.add(sec, OK, "OPENAI_API_KEY", f"ключ принят{note}.")
        for var, model, needed in (("OPENAI_TEXT_MODEL", s.openai_text_model, s.text_provider == "openai"),
                                   ("OPENAI_IMAGE_MODEL", s.openai_image_model, s.image_provider == "openai")):
            self._model_line(sec, var, model, ids, needed)
        if s.image_provider == "openai":
            self.add(sec, SKIP, "Картинки", "для моделей картинок OpenAI может понадобиться подтверждение организации: "
                                            "platform.openai.com → Settings → Organization → General → Verify Organization. "
                                            "Баланс от $5 тоже нужен — проверить его без списания нельзя.")

    def _model_line(self, sec: str, var: str, model: str, ids: list[str], needed: bool) -> None:
        if not model:
            self.add(sec, BAD if needed else SKIP, var, "не заполнено: впишите название модели (см. .env.example).")
        elif model in ids:
            self.add(sec, OK, var, f"модель «{model}» существует.")
        else:
            close = difflib.get_close_matches(model, ids, n=3, cutoff=0.5)
            hint = f" Похожие у вас: {', '.join(close)}." if close else ""
            self.add(sec, BAD if needed else SKIP, var, f"модели «{model}» у вас нет. Проверьте название в .env.{hint}")

    def gemini(self) -> None:
        sec, s = "Gemini", self.s
        used = s.text_provider == "gemini"
        if not s.gemini_api_key:
            if used:
                self.add(sec, BAD, "GEMINI_API_KEY", "не заполнен, а Gemini выбран в .env. Бесплатный ключ: aistudio.google.com → Get API key.")
            else:
                self.add(sec, SKIP, "GEMINI_API_KEY", "не заполнен (сейчас не нужен).")
            return
        headers = {"x-goog-api-key": s.gemini_api_key}
        model = s.gemini_model.removeprefix("models/")
        try:
            resp = self.call("GET", f"{GEMINI}/models/{model}" if model else f"{GEMINI}/models",
                             headers=headers, params=None if model else {"pageSize": 1})
        except Offline as e:
            self.offline_line(sec, "GEMINI_API_KEY", str(e) or "")
            return
        text = resp.text.lower()
        if resp.status_code in (400, 401, 403) and ("api key" in text or "api_key" in text or resp.status_code != 400):
            self.add(sec, BAD, "GEMINI_API_KEY", "Google не принял ключ. Создайте новый на aistudio.google.com → Get API key и вставьте целиком.")
            return
        note = "" if used else " (сейчас не используется)"
        if resp.status_code == 404:
            self.add(sec, OK, "GEMINI_API_KEY", f"ключ принят{note}.")
            self._gemini_model_missing(sec, model, used, headers)
        elif resp.status_code == 200:
            self.add(sec, OK, "GEMINI_API_KEY", f"ключ принят{note}.")
            if model:
                self.add(sec, OK, "GEMINI_MODEL", f"модель «{model}» существует. Бесплатный тариф: Google использует присланное для "
                                                  "улучшения своих продуктов — вводите только вымышленные данные.")
            else:
                self.add(sec, BAD if used else SKIP, "GEMINI_MODEL", "не заполнено: впишите название модели (см. .env.example).")
        else:
            self.add(sec, BAD, "GEMINI_API_KEY", f"Gemini ответил кодом {resp.status_code}. Попробуйте позже.")

    def _gemini_model_missing(self, sec: str, model: str, needed: bool, headers: dict) -> None:
        names: list[str] = []
        try:
            resp = self.call("GET", f"{GEMINI}/models", headers=headers, params={"pageSize": 200})
            for m in resp.json().get("models", []):
                if "generateContent" in (m.get("supportedGenerationMethods") or []):
                    names.append(str(m.get("name", "")).removeprefix("models/"))
        except (Offline, ValueError):
            pass
        close = difflib.get_close_matches(model, names, n=3, cutoff=0.5)
        hint = f" Похожие: {', '.join(close)}." if close else ""
        self.add(sec, BAD if needed else SKIP, "GEMINI_MODEL", f"модели «{model}» нет. Проверьте название в .env.{hint}")

    def cloudflare(self) -> None:
        sec, s = "Cloudflare", self.s
        used = s.image_provider == "cloudflare"
        if not s.cloudflare_account_id and not s.cloudflare_api_token:
            if used:
                self.add(sec, BAD, "CLOUDFLARE_*", "не заполнены, а Cloudflare выбран в .env. dash.cloudflare.com → Workers AI → "
                                                   "Use REST API → Create a Workers AI API Token; Account ID — на той же странице.")
            else:
                self.add(sec, SKIP, "CLOUDFLARE_*", "не заполнены (сейчас не нужны).")
            return
        if not s.cloudflare_account_id or not s.cloudflare_api_token:
            missing = "CLOUDFLARE_ACCOUNT_ID" if not s.cloudflare_account_id else "CLOUDFLARE_API_TOKEN"
            self.add(sec, BAD, missing, "не заполнено: нужны оба значения — Account ID и API Token (Workers AI → Use REST API).")
            return
        if not s.cloudflare_image_model:
            self.add(sec, BAD, "CLOUDFLARE_IMAGE_MODEL", "не заполнено: впишите название модели (см. .env.example).")
            return
        url = f"{CLOUDFLARE}/accounts/{s.cloudflare_account_id}/ai/run/{s.cloudflare_image_model}"
        try:
            resp = self.call("POST", url, headers={"Authorization": f"Bearer {s.cloudflare_api_token}"},
                             json={"prompt": "a tiny red apple, simple watercolor", "steps": 1}, timeout=60)
        except Offline as e:
            self.offline_line(sec, "CLOUDFLARE_API_TOKEN", str(e) or "")
            return
        code = None
        try:
            errors = resp.json().get("errors") or []
            code = errors[0].get("code") if errors else None
        except (ValueError, AttributeError):
            pass
        if resp.status_code == 200 and (resp.headers.get("content-type", "").startswith("image/") or _has_image(resp)):
            self.add(sec, OK, "CLOUDFLARE_API_TOKEN", "токен и Account ID приняты, тестовая картинка нарисована "
                                                      f"(потрачено около 30 из 10 000 бесплатных «нейронов» в сутки).")
            self.add(sec, OK, "CLOUDFLARE_IMAGE_MODEL", f"модель «{s.cloudflare_image_model}» отвечает.")
        elif code == 3036:
            self.add(sec, OK, "CLOUDFLARE_API_TOKEN", "токен и Account ID приняты.")
            self.add(sec, BAD, "Лимит", "бесплатные 10 000 «нейронов» на сегодня закончились — сбросятся в 00:00 по UTC.")
        elif resp.status_code in (401, 403):
            self.add(sec, BAD, "CLOUDFLARE_API_TOKEN", "Cloudflare не принял токен или Account ID. Создайте токен заново: Workers AI → "
                                                       "Use REST API → Create a Workers AI API Token; Account ID — там же.")
        elif resp.status_code == 404 or code in (3042, 5007):
            self.add(sec, BAD, "CLOUDFLARE_IMAGE_MODEL", f"модели «{s.cloudflare_image_model}» нет. Проверьте название в .env.")
        else:
            self.add(sec, BAD, "CLOUDFLARE_API_TOKEN", f"Cloudflare ответил кодом {resp.status_code}. Попробуйте позже.")

    # ------------------------------------------------------------------ итог
    def run(self) -> list[tuple[str, list[Line]]]:
        self.providers_summary()
        self.telegram()
        self.webapp()
        self.admin()
        self.openai()
        self.gemini()
        self.cloudflare()
        return self.sections


def _has_image(resp: httpx.Response) -> bool:
    try:
        result = resp.json().get("result", {})
        return bool(result.get("image")) and len(base64.b64decode(result["image"])) > 100
    except (ValueError, AttributeError, TypeError):
        return False


def report(sections: list[tuple[str, list[Line]]]) -> int:
    problems = 0
    for title, lines in sections:
        print(f"\n{title}")
        for line in lines:
            print(f"  {line.mark} {line.name} — {redact(line.text)}")
            problems += line.mark == BAD
    print()
    if problems:
        print(f"Нашлось проблем: {problems}. Исправьте строки с [ОШИБКА] в файле .env и запустите проверку ещё раз.")
    else:
        print("Всё в порядке: ошибок нет. Строки с [ — ] не заполнены, но сейчас не обязательны.")
    return 1 if problems else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        print(f"Ошибка настройки: {e}")
        return 2
    redact.add(settings.secrets)
    print("Проверка ключей и настроек (сами ключи не показываются)")
    with httpx.Client(timeout=15, headers={"User-Agent": "skazka-check-keys"}) as client:
        sections = Checker(settings, client).run()
    return report(sections)


if __name__ == "__main__":
    sys.exit(main())
