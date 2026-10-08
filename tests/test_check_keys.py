"""check_keys.py: понятные сообщения, никаких ключей в выводе, без интернета не падает."""
import base64

import httpx

import check_keys
from check_keys import BAD, OK, SKIP, Checker, report
from app.logging_setup import redact

from .conftest import make_settings
from .test_providers import CF_ACCOUNT, CF_TOKEN, GEMINI_KEY, OPENAI_KEY, PNG, jr

TG_TOKEN = "123456789:TESTtokenTESTtokenTESTtokenTEST12345"


def run(tmp_path, handler, **settings):
    base = dict(telegram_bot_token=TG_TOKEN, webapp_url="", admin_chat_id=None)
    s = make_settings(tmp_path, **{**base, **settings})
    redact.add(s.secrets)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Checker(s, client).run()


def flat(sections):
    return [(line.mark, line.name, line.text) for _, lines in sections for line in lines]


def find(sections, name):
    return next(x for x in flat(sections) if x[1] == name)


def test_valid_telegram_token_reports_bot_name(tmp_path):
    def handler(request):
        assert request.url.path == f"/bot{TG_TOKEN}/getMe"
        return jr(200, {"ok": True, "result": {"id": 1, "username": "my_tale_bot"}})
    mark, _, text = find(run(tmp_path, handler), "TELEGRAM_BOT_TOKEN")
    assert mark == OK and "@my_tale_bot" in text and TG_TOKEN not in text


def test_wrong_telegram_token_says_what_to_do(tmp_path):
    mark, _, text = find(run(tmp_path, lambda r: jr(401, {"ok": False})), "TELEGRAM_BOT_TOKEN")
    assert mark == BAD and "@BotFather" in text


def test_everything_offline_gives_messages_not_traceback(tmp_path):
    def handler(request):
        raise httpx.ConnectError("no route to host")
    sections = run(tmp_path, handler, openai_api_key=OPENAI_KEY, gemini_api_key=GEMINI_KEY,
                   cloudflare_account_id=CF_ACCOUNT, cloudflare_api_token=CF_TOKEN, cloudflare_image_model="@cf/x/y",
                   text_provider="gemini", gemini_model="g")
    marks = {name: mark for mark, name, _ in flat(sections)}
    assert marks["TELEGRAM_BOT_TOKEN"] == SKIP and marks["OPENAI_API_KEY"] == SKIP and marks["GEMINI_API_KEY"] == SKIP
    assert "нет подключения к интернету" in find(sections, "TELEGRAM_BOT_TOKEN")[2]
    assert report(sections) == 0       # без сети — это не «ошибка ключа»


def test_openai_key_and_models_are_checked_with_hints(tmp_path):
    def handler(request):
        if request.url.host == "api.telegram.org":
            return jr(200, {"ok": True, "result": {"username": "b"}})
        assert request.headers["authorization"] == f"Bearer {OPENAI_KEY}"
        return jr(200, {"data": [{"id": "model-luna"}, {"id": "image-sunburst"}]})
    s = run(tmp_path, handler, openai_api_key=OPENAI_KEY, openai_base_url="https://api.openai.test/v1",
            text_provider="openai", image_provider="openai", openai_text_model="model-luna", openai_image_model="image-sunburnt")
    assert find(s, "OPENAI_API_KEY")[0] == OK and find(s, "OPENAI_TEXT_MODEL")[0] == OK
    mark, _, text = find(s, "OPENAI_IMAGE_MODEL")
    assert mark == BAD and "image-sunburst" in text           # подсказка про похожее название


def test_openai_wrong_key(tmp_path):
    def handler(request):
        return jr(200, {"ok": True, "result": {"username": "b"}}) if request.url.host == "api.telegram.org" else jr(401, {"error": {}})
    mark, _, text = find(run(tmp_path, handler, openai_api_key=OPENAI_KEY, openai_base_url="https://api.openai.test/v1"), "OPENAI_API_KEY")
    assert mark == BAD and "platform.openai.com" in text and OPENAI_KEY not in text


def test_selected_provider_without_key_is_an_error_but_unused_one_is_fine(tmp_path):
    s = run(tmp_path, lambda r: jr(200, {"ok": True, "result": {"username": "b"}}), text_provider="openai", image_provider="cloudflare")
    assert find(s, "OPENAI_API_KEY")[0] == BAD and find(s, "CLOUDFLARE_*")[0] == BAD
    assert find(s, "GEMINI_API_KEY")[0] == SKIP


def test_gemini_model_missing_suggests_names(tmp_path):
    def handler(request):
        if request.url.host == "api.telegram.org":
            return jr(200, {"ok": True, "result": {"username": "b"}})
        assert request.headers["x-goog-api-key"] == GEMINI_KEY and GEMINI_KEY not in str(request.url)
        if request.url.path.endswith("/models/gemini-x"):
            return jr(404, {"error": {"message": "not found"}})
        return jr(200, {"models": [{"name": "models/gemini-y", "supportedGenerationMethods": ["generateContent"]}]})
    s = run(tmp_path, handler, gemini_api_key=GEMINI_KEY, gemini_model="gemini-x", text_provider="gemini")
    assert find(s, "GEMINI_API_KEY")[0] == OK
    mark, _, text = find(s, "GEMINI_MODEL")
    assert mark == BAD and "gemini-y" in text


def test_gemini_wrong_key(tmp_path):
    def handler(request):
        if request.url.host == "api.telegram.org":
            return jr(200, {"ok": True, "result": {"username": "b"}})
        return jr(400, {"error": {"message": "API key not valid. Please pass a valid API key."}})
    mark, _, text = find(run(tmp_path, handler, gemini_api_key=GEMINI_KEY, gemini_model="m"), "GEMINI_API_KEY")
    assert mark == BAD and "aistudio.google.com" in text


def test_cloudflare_makes_one_small_picture(tmp_path):
    calls = []

    def handler(request):
        if request.url.host == "api.telegram.org":
            return jr(200, {"ok": True, "result": {"username": "b"}})
        calls.append(request)
        return jr(200, {"result": {"image": base64.b64encode(PNG * 20).decode()}, "success": True})
    s = run(tmp_path, handler, cloudflare_account_id=CF_ACCOUNT, cloudflare_api_token=CF_TOKEN,
            cloudflare_image_model="@cf/x/y", image_provider="cloudflare")
    assert len(calls) == 1 and find(s, "CLOUDFLARE_API_TOKEN")[0] == OK and find(s, "CLOUDFLARE_IMAGE_MODEL")[0] == OK


def test_cloudflare_daily_limit_and_bad_token(tmp_path):
    def limit(request):
        if request.url.host == "api.telegram.org":
            return jr(200, {"ok": True, "result": {"username": "b"}})
        return jr(429, {"errors": [{"code": 3036, "message": "daily"}]})
    s = run(tmp_path, limit, cloudflare_account_id=CF_ACCOUNT, cloudflare_api_token=CF_TOKEN, cloudflare_image_model="m")
    assert find(s, "Лимит")[0] == BAD and "00:00" in find(s, "Лимит")[2]

    def denied(request):
        return jr(200, {"ok": True, "result": {"username": "b"}}) if request.url.host == "api.telegram.org" else jr(403, {"errors": [{"code": 10000}]})
    s = run(tmp_path, denied, cloudflare_account_id=CF_ACCOUNT, cloudflare_api_token=CF_TOKEN, cloudflare_image_model="m")
    mark, _, text = find(s, "CLOUDFLARE_API_TOKEN")
    assert mark == BAD and "Create a Workers AI API Token" in text and CF_TOKEN not in text


def test_webapp_url_checks(tmp_path):
    def handler(request):
        if request.url.host == "api.telegram.org":
            return jr(200, {"ok": True, "result": {"username": "b"}})
        return jr(200, {"status": "ok"}) if request.url.host == "good.example.test" else jr(530, {})
    assert find(run(tmp_path, handler, webapp_url="https://good.example.test"), "WEBAPP_URL")[0] == OK
    assert find(run(tmp_path, handler, webapp_url="https://dead.example.test"), "WEBAPP_URL")[0] == BAD
    mark, _, text = find(run(tmp_path, handler, webapp_url="http://localhost:8080"), "WEBAPP_URL")
    assert mark == BAD and "https://" in text


def test_report_never_prints_any_secret(tmp_path, capsys):
    s = run(tmp_path, lambda r: jr(401, {"error": {"message": f"bad {OPENAI_KEY} {GEMINI_KEY}"}}),
            openai_api_key=OPENAI_KEY, gemini_api_key=GEMINI_KEY, gemini_model="m")
    report(s)
    out = capsys.readouterr().out
    for secret in (OPENAI_KEY, GEMINI_KEY, TG_TOKEN, CF_TOKEN):
        assert secret not in out
