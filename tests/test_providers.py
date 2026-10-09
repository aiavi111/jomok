"""Провайдеры OpenAI, Gemini, Cloudflare на поддельном сетевом слое: форма запросов, повторы, ошибки."""
import base64
import json
import re
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import ConfigError
from app.errors import ProviderError, StoryError
from app.logging_setup import redact
from app.providers import http as http_mod
from app.providers import make_image_provider, make_text_provider
from app.providers.image_cloudflare import CloudflareImageProvider
from app.providers.image_openai import OpenAIImageProvider
from app.providers.text_gemini import GeminiTextProvider
from app.providers.text_openai import OpenAITextProvider

from .conftest import SAMPLE, make_settings
from .test_story import good_story
from .writer_helpers import CLEAR, NO_FIXES, dump, plan_and_text, seeded
from app.profile import Profile

CLEAR_JSON = json.dumps(CLEAR, ensure_ascii=False)       # проверка понятности («пятилетний слушатель»): всё понятно
OPENAI_KEY = "sk-proj-TESTKEYtestkeyTESTKEYtestkey12345"
GEMINI_KEY = "AIzaSyTESTKEYtestkeyTESTKEYtestkey12345"
CF_TOKEN = "cfTESTtokenTESTtokenTESTtoken1234567890ab"
CF_ACCOUNT = "0123456789abcdef0123456789abcdef"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(http_mod, "_sleep", fake_sleep)
    redact.add([OPENAI_KEY, GEMINI_KEY, CF_TOKEN, CF_ACCOUNT])
    return slept


class Recorder:
    """Поддельный сервер: отвечает по очереди и запоминает запросы."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def transport(self):
        return httpx.MockTransport(self)

    def json(self, i=0):
        return json.loads(self.requests[i].content)


def jr(status=200, body=None, headers=None):
    return httpx.Response(status, json=body if body is not None else {}, headers=headers or {})




# ----------------------------------------------------------------------- общие правила повторов
async def test_retries_429_and_5xx_with_growing_pauses_and_gives_result(no_real_sleep):
    server = Recorder(jr(429), jr(503), jr(500), jr(200, {"ok": 1}))
    async with httpx.AsyncClient(transport=server.transport) as client:
        resp = await http_mod.request_with_retries(client, "GET", "https://x.test", provider="Тест")
    assert resp.status_code == 200 and len(server.requests) == 4
    assert len(no_real_sleep) == 3 and no_real_sleep[0] < no_real_sleep[1] < no_real_sleep[2]


async def test_retry_after_seconds_and_date_are_respected(no_real_sleep):
    soon = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    server = Recorder(jr(429, headers={"Retry-After": "7"}), jr(429, headers={"Retry-After": soon}), jr(200))
    async with httpx.AsyncClient(transport=server.transport) as client:
        await http_mod.request_with_retries(client, "GET", "https://x.test", provider="Тест")
    assert no_real_sleep[0] == 7 and 25 <= no_real_sleep[1] <= 31


async def test_huge_retry_after_is_not_waited_for(no_real_sleep):
    server = Recorder(jr(429, headers={"Retry-After": "7200"}), jr(200))
    async with httpx.AsyncClient(transport=server.transport) as client:
        resp = await http_mod.request_with_retries(client, "GET", "https://x.test", provider="Тест")
    assert resp.status_code == 429 and len(server.requests) == 1 and no_real_sleep == []


async def test_timeout_is_retried_and_final_failure_has_no_url_or_key(no_real_sleep):
    server = Recorder(httpx.ReadTimeout("t"), httpx.ConnectError("boom https://api.test/?key=" + OPENAI_KEY), jr(200))
    async with httpx.AsyncClient(transport=server.transport) as client:
        assert (await http_mod.request_with_retries(client, "GET", "https://x.test", provider="Тест")).status_code == 200
    always = Recorder(httpx.ConnectError("https://api.telegram.org/bot123:SECRET " + OPENAI_KEY))
    async with httpx.AsyncClient(transport=always.transport) as client:
        with pytest.raises(ProviderError) as err:
            await http_mod.request_with_retries(client, "GET", "https://x.test", provider="Тест", attempts=3)
    assert "нет связи" in err.value.message and OPENAI_KEY not in err.value.message and "SECRET" not in err.value.message
    assert len(always.requests) == 3


async def test_client_errors_are_not_retried():
    server = Recorder(jr(400, {"error": {"message": "bad"}}))
    async with httpx.AsyncClient(transport=server.transport) as client:
        resp = await http_mod.request_with_retries(client, "GET", "https://x.test", provider="Тест")
    assert resp.status_code == 400 and len(server.requests) == 1


def test_image_timeout_is_five_minutes():
    assert http_mod.IMAGE_TIMEOUT.read == 300 and http_mod.TEXT_TIMEOUT.read <= 300


# ----------------------------------------------------------------------- OpenAI, текст
def chat_reply(content: str) -> httpx.Response:
    return jr(200, {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]})


async def test_openai_text_request_follows_docs_and_omits_temperature_and_max_tokens(profile):
    plan, text = plan_and_text(profile)
    server = Recorder(chat_reply(plan), chat_reply(text), chat_reply(CLEAR_JSON), chat_reply(NO_FIXES))
    provider = seeded(OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1/", "model-from-env", transport=server.transport))
    story = await provider.generate_story(profile)
    assert story.title and len(server.requests) == 4                 # режиссёр, автор, понятность, редактор
    request = server.requests[0]
    assert str(request.url) == "https://api.openai.test/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {OPENAI_KEY}"
    body = server.json()
    assert set(body) == {"model", "messages", "response_format"}               # ни temperature, ни max_tokens
    assert body["model"] == "model-from-env" and body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system" and "JSON" in body["messages"][0]["content"]
    assert body["messages"][0]["content"].startswith("Ты режиссёр")             # первый шаг — план
    assert body["messages"][1]["role"] == "user" and "<child>" in body["messages"][1]["content"]
    assert server.json(1)["messages"][0]["content"].startswith("Ты автор текстов")
    assert server.json(3)["messages"][0]["content"].startswith("Ты строгий редактор")
    assert OPENAI_KEY not in str(request.url)


async def test_openai_text_retry_sends_error_text_back_to_model(profile):
    plan, text = plan_and_text(profile)
    server = Recorder(chat_reply("не JSON"), chat_reply(plan), chat_reply(text), chat_reply(CLEAR_JSON), chat_reply(NO_FIXES))
    provider = seeded(OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", transport=server.transport))
    await provider.generate_story(profile)
    second = server.json(1)["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[2]["content"] == "не JSON" and "не прошёл проверку" in second[3]["content"]


async def test_openai_text_falls_back_when_model_rejects_response_format(profile):
    plan, text = plan_and_text(profile)
    server = Recorder(jr(400, {"error": {"message": "Unsupported parameter: 'response_format'"}}),
                      chat_reply(plan), chat_reply(text), chat_reply(CLEAR_JSON), chat_reply(NO_FIXES))
    provider = seeded(OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", transport=server.transport))
    await provider.generate_story(profile)
    assert "response_format" in server.json(0) and "response_format" not in server.json(1)
    assert all("response_format" not in server.json(i) for i in range(1, len(server.requests)))


@pytest.mark.parametrize("response, fragment", [
    (jr(401, {"error": {"message": "Incorrect API key provided: " + OPENAI_KEY, "code": "invalid_api_key"}}), "Неверный ключ OpenAI"),
    (jr(403, {"error": {"message": "Your organization must be verified to use the model `m`."}}), "Verify Organization"),
    (jr(404, {"error": {"message": "The model `m` does not exist", "code": "model_not_found"}}), "OPENAI_TEXT_MODEL"),
    (jr(429, {"error": {"message": "You exceeded your current quota", "type": "insufficient_quota", "code": "insufficient_quota"}}), "закончились деньги"),
    (jr(429, {"error": {"message": "x", "code": "credit_balance_exhausted"}}), "закончились деньги"),
    (jr(429, {"error": {"message": "x", "code": "project_spend_limit_exceeded"}}), "лимит расходов"),
])
async def test_openai_text_errors_are_explained_in_russian_without_leaking_key(profile, response, fragment):
    server = Recorder(response)
    provider = OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", transport=server.transport)
    with pytest.raises(ProviderError) as err:
        await provider.generate_story(profile)
    assert fragment in err.value.message and err.value.fatal
    assert OPENAI_KEY not in err.value.message
    assert len(server.requests) == 1                                          # деньги/ключ/модель не повторяем


async def test_openai_rate_limit_is_retried(profile):
    plan, text = plan_and_text(profile)
    server = Recorder(jr(429, {"error": {"message": "Rate limit reached", "code": "rate_limit_exceeded"}},
                         headers={"Retry-After": "1"}), chat_reply(plan), chat_reply(text))
    provider = seeded(OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", transport=server.transport))
    provider.polish = False
    assert (await provider.generate_story(profile)).title and len(server.requests) == 3


# ----------------------------------------------------------------------- OpenAI, картинки
def image_reply(data: bytes = PNG) -> httpx.Response:
    return jr(200, {"data": [{"b64_json": base64.b64encode(data).decode()}]})


async def test_openai_image_generation_without_references():
    server = Recorder(image_reply())
    provider = OpenAIImageProvider(OPENAI_KEY, "https://api.openai.test/v1", "img-model", "high", transport=server.transport)
    assert provider.supports_reference is True
    assert await provider.generate("a red apple", None, "1024x1024") == PNG
    request = server.requests[0]
    assert str(request.url) == "https://api.openai.test/v1/images/generations"
    assert request.headers["authorization"] == f"Bearer {OPENAI_KEY}"
    assert server.json() == {"model": "img-model", "prompt": "a red apple", "size": "1024x1024", "quality": "high", "n": 1}


async def test_openai_image_sends_the_requested_custom_size_for_wide_pages_and_square_covers():
    """Страница — широкий разворот 2048x1024 (кратно 16, не больше 3:1), обложка — квадрат; провайдер передаёт размер как есть."""
    server = Recorder(image_reply(), image_reply(), image_reply())
    provider = OpenAIImageProvider(OPENAI_KEY, "https://api.openai.test/v1", "img-model", "medium", transport=server.transport)
    await provider.generate("page", None, "2048x1024")
    await provider.generate("page with refs", [b"\xff\xd8cover"], "2048x1024")
    await provider.generate("cover", None, "1024x1024")
    assert [r.url.path for r in server.requests] == ["/v1/images/generations", "/v1/images/edits", "/v1/images/generations"]
    assert [server.json(i)["size"] for i in range(3)] == ["2048x1024", "2048x1024", "1024x1024"]


async def test_openai_image_edit_sends_json_with_data_urls_and_no_input_fidelity():
    server = Recorder(image_reply())
    provider = OpenAIImageProvider(OPENAI_KEY, "https://api.openai.test/v1", "img-model", "medium", transport=server.transport)
    refs = [b"\xff\xd8cover", b"\xff\xd8photo"]
    await provider.generate("scene", refs, "1024x1024")
    request = server.requests[0]
    assert str(request.url).endswith("/images/edits") and request.headers["content-type"] == "application/json"
    body = server.json()
    assert "input_fidelity" not in body and "response_format" not in body
    assert [i["image_url"] for i in body["images"]] == [
        "data:image/jpeg;base64," + base64.b64encode(r).decode() for r in refs]
    assert body["size"] == "1024x1024" and body["quality"] == "medium" and body["n"] == 1


async def test_openai_image_edit_accepts_at_most_sixteen_references():
    server = Recorder(image_reply())
    provider = OpenAIImageProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", transport=server.transport)
    await provider.generate("p", [b"\xff\xd8%d" % i for i in range(20)])
    assert len(server.json()["images"]) == 16


async def test_openai_image_edit_falls_back_to_multipart_if_json_is_not_accepted():
    server = Recorder(jr(400, {"error": {"message": "Invalid Content-Type: expected multipart/form-data"}}), image_reply())
    provider = OpenAIImageProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", "low", transport=server.transport)
    assert await provider.generate("p", [b"\xff\xd8one", b"\x89PNG\r\n\x1a\ntwo"]) == PNG
    second = server.requests[1]
    assert second.headers["content-type"].startswith("multipart/form-data")
    assert second.content.count(b'name="image[]"') == 2
    assert b'name="model"' in second.content and b'name="quality"' in second.content
    assert b"input_fidelity" not in second.content


async def test_openai_image_quality_is_validated():
    assert OpenAIImageProvider("k", "https://x/v1", "m", "ultra").quality == "medium"


@pytest.mark.parametrize("response, fatal, no_retry, fragment", [
    (jr(400, {"error": {"message": "Your request was rejected by the safety system.", "code": "moderation_blocked"}}), False, True, "фильтр безопасности"),
    (jr(403, {"error": {"message": "Your organization must be verified to use the model `gpt-image`. Please go to ..."}}), True, False, "Verify Organization"),
    (jr(429, {"error": {"message": "x", "type": "insufficient_quota"}}), True, False, "закончились деньги"),
    (jr(404, {"error": {"message": "model not found"}}), True, False, "OPENAI_IMAGE_MODEL"),
    (jr(401, {"error": {"message": "bad key " + OPENAI_KEY}}), True, False, "Неверный ключ"),
])
async def test_openai_image_errors(response, fatal, no_retry, fragment):
    server = Recorder(response)
    provider = OpenAIImageProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", transport=server.transport)
    with pytest.raises(ProviderError) as err:
        await provider.generate("p")
    assert fragment in err.value.message and err.value.fatal is fatal and err.value.no_retry is no_retry
    assert OPENAI_KEY not in err.value.message and len(server.requests) == 1


async def test_openai_image_without_picture_in_answer_is_an_error():
    server = Recorder(jr(200, {"data": [{"url": "https://x"}]}))
    with pytest.raises(ProviderError):
        await OpenAIImageProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", transport=server.transport).generate("p")


# ----------------------------------------------------------------------- Gemini
def gemini_reply(text: str, **extra) -> httpx.Response:
    return jr(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}], **extra})


async def test_gemini_request_follows_docs(profile):
    plan, text = plan_and_text(profile)
    server = Recorder(gemini_reply("не JSON"), gemini_reply(plan), gemini_reply(text), gemini_reply(CLEAR_JSON), gemini_reply(NO_FIXES))
    provider = seeded(GeminiTextProvider(GEMINI_KEY, "models/gemini-model-from-env", transport=server.transport))
    await provider.generate_story(profile)
    request = server.requests[0]
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-model-from-env:generateContent"
    assert request.headers["x-goog-api-key"] == GEMINI_KEY and GEMINI_KEY not in str(request.url)
    body = server.json(0)
    assert body["systemInstruction"]["parts"][0]["text"].startswith("Ты режиссёр")
    assert body["contents"] == [{"role": "user", "parts": [{"text": body["contents"][0]["parts"][0]["text"]}]}]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["maxOutputTokens"] >= 8192
    second = server.json(1)["contents"]
    assert [c["role"] for c in second] == ["user", "model", "user"] and "не прошёл проверку" in second[2]["parts"][0]["text"]
    assert server.json(2)["systemInstruction"]["parts"][0]["text"].startswith("Ты автор текстов")


async def test_gemini_skips_thought_parts_and_joins_text():
    profile = Profile.from_payload(SAMPLE)
    plan, text = plan_and_text(profile)
    reply = jr(200, {"candidates": [{"content": {"parts": [
        {"text": "размышления", "thought": True}, {"text": plan[:50]}, {"text": plan[50:]}]}}]})
    provider = seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=Recorder(reply, gemini_reply(text), gemini_reply(CLEAR_JSON), gemini_reply(NO_FIXES)).transport))
    story = await provider.generate_story(profile)
    assert story.title


@pytest.mark.parametrize("response, fatal, fragment", [
    (jr(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}), True, "Неверный ключ Gemini"),
    (jr(403, {"error": {"message": "Permission denied"}}), True, "403"),
    (jr(404, {"error": {"message": "models/zzz is not found"}}), True, "GEMINI_MODEL"),
    (jr(429, {"error": {"message": "Quota exceeded for metric ... PerDay", "status": "RESOURCE_EXHAUSTED"}}), True, "дневной лимит"),
])
async def test_gemini_errors_in_russian(profile, response, fatal, fragment):
    server = Recorder(response)
    with pytest.raises(ProviderError) as err:
        await GeminiTextProvider(GEMINI_KEY, "zzz", transport=server.transport).generate_story(profile)
    assert fragment in err.value.message and err.value.fatal is fatal and GEMINI_KEY not in err.value.message
    assert len(server.requests) == 1


async def test_gemini_429_with_short_retry_delay_is_retried_and_503_too(profile, no_real_sleep):
    plan, text = plan_and_text(profile)
    limited = jr(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "slow down",
                                 "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "4s"}]}})
    server = Recorder(limited, jr(503, {"error": {"message": "overloaded"}}), gemini_reply(plan), gemini_reply(text), gemini_reply(CLEAR_JSON))
    provider = seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport))
    provider.polish = False
    await provider.generate_story(profile)
    assert len(server.requests) == 4 and no_real_sleep[0] == 4.0


async def test_gemini_blocked_prompt_is_reported(profile):
    server = Recorder(jr(200, {"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(ProviderError) as err:
        await GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport).generate_story(profile)
    assert "SAFETY" in err.value.message


# ----------------------------------------------------------------------- Cloudflare
async def test_cloudflare_request_follows_docs_and_never_sends_references_or_photo():
    server = Recorder(jr(200, {"result": {"image": base64.b64encode(PNG).decode()}, "success": True, "errors": [], "messages": []}))
    provider = CloudflareImageProvider(CF_ACCOUNT, CF_TOKEN, "@cf/test/model-from-env", transport=server.transport)
    assert provider.supports_reference is False
    data = await provider.generate("x" * 3000, refs=[b"photo-of-a-child"], size="1024x1024")
    assert data == PNG
    request = server.requests[0]
    assert str(request.url) == f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/@cf/test/model-from-env"
    assert request.headers["authorization"] == f"Bearer {CF_TOKEN}"
    body = server.json()
    assert set(body) == {"prompt", "steps"} and len(body["prompt"]) == 2048 and 1 <= body["steps"] <= 8
    assert b"photo-of-a-child" not in request.content and base64.b64encode(b"photo-of-a-child") not in request.content


async def test_cloudflare_returns_squares_and_ignores_the_wide_size_the_pipeline_crops_them():
    """FLUX schnell не принимает размер: для страницы 2048x1024 в запрос width/height не уходят, ответ — квадрат,
    обрезку до 2:1 делает normalize_image."""
    import io
    from PIL import Image
    from app.imaging import normalize_image
    square = io.BytesIO()
    Image.new("RGB", (1024, 1024), (10, 120, 200)).save(square, "PNG")
    server = Recorder(jr(200, {"result": {"image": base64.b64encode(square.getvalue()).decode()}, "success": True}))
    provider = CloudflareImageProvider(CF_ACCOUNT, CF_TOKEN, "m", transport=server.transport)
    raw = await provider.generate("scene", size="2048x1024")
    assert set(server.json()) == {"prompt", "steps"}                       # ни width, ни height, ни size
    page = Image.open(io.BytesIO(normalize_image(raw, (2048, 1024), 88)))
    assert page.size == (2048, 1024)


async def test_cloudflare_accepts_raw_image_bytes_too():
    server = Recorder(httpx.Response(200, content=PNG, headers={"content-type": "image/jpeg"}))
    provider = CloudflareImageProvider(CF_ACCOUNT, CF_TOKEN, "m", transport=server.transport)
    assert await provider.generate("p") == PNG


@pytest.mark.parametrize("response, fatal, fragment", [
    (jr(401, {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}), True, "CLOUDFLARE_API_TOKEN"),
    (jr(429, {"success": False, "errors": [{"code": 3036, "message": "You have used up your daily free allocation of 10,000 neurons."}]}), True, "дневной лимит"),
    (jr(404, {"success": False, "errors": [{"code": 3042, "message": "Invalid model ID"}]}), True, "CLOUDFLARE_IMAGE_MODEL"),
])
async def test_cloudflare_errors_in_russian_without_pointless_retries(response, fatal, fragment):
    server = Recorder(response)
    with pytest.raises(ProviderError) as err:
        await CloudflareImageProvider(CF_ACCOUNT, CF_TOKEN, "m", transport=server.transport).generate("p")
    assert fragment in err.value.message and err.value.fatal is fatal and CF_TOKEN not in err.value.message
    assert len(server.requests) == 1


async def test_cloudflare_capacity_error_is_retried(no_real_sleep):
    busy = jr(429, {"success": False, "errors": [{"code": 3040, "message": "Capacity temporarily exceeded"}]})
    server = Recorder(busy, jr(200, {"result": {"image": base64.b64encode(PNG).decode()}, "success": True}))
    assert await CloudflareImageProvider(CF_ACCOUNT, CF_TOKEN, "m", transport=server.transport).generate("p") == PNG
    assert len(server.requests) == 2 and len(no_real_sleep) == 1


async def test_cloudflare_answer_without_image_is_an_error():
    server = Recorder(jr(200, {"result": {}, "success": True}))
    with pytest.raises(ProviderError):
        await CloudflareImageProvider(CF_ACCOUNT, CF_TOKEN, "m", transport=server.transport).generate("p")


# ----------------------------------------------------------------------- выбор провайдеров из настроек
def test_factory_builds_each_provider_from_env_settings(tmp_path):
    s = make_settings(tmp_path, text_provider="openai", image_provider="openai", openai_api_key=OPENAI_KEY,
                      openai_text_model="t-model", openai_image_model="i-model", openai_image_quality="low")
    assert isinstance(make_text_provider(s), OpenAITextProvider) and make_text_provider(s).model == "t-model"
    assert make_image_provider(s).model == "i-model" and make_image_provider(s).quality == "low"
    g = make_settings(tmp_path, text_provider="gemini", gemini_api_key=GEMINI_KEY, gemini_model="g-model")
    assert make_text_provider(g).model == "g-model" and make_text_provider(g).proof_model == ""
    c = make_settings(tmp_path, image_provider="cloudflare", cloudflare_account_id=CF_ACCOUNT,
                      cloudflare_api_token=CF_TOKEN, cloudflare_image_model="@cf/x/y")
    assert make_image_provider(c).model == "@cf/x/y"
    assert make_text_provider(make_settings(tmp_path)).name == "mock" and make_image_provider(make_settings(tmp_path)).name == "mock"


@pytest.mark.parametrize("over, var", [
    ({"text_provider": "openai"}, "OPENAI_API_KEY"),
    ({"text_provider": "openai", "openai_api_key": "k"}, "OPENAI_TEXT_MODEL"),
    ({"text_provider": "gemini"}, "GEMINI_API_KEY"),
    ({"text_provider": "gemini", "gemini_api_key": "k"}, "GEMINI_MODEL"),
    ({"image_provider": "openai", "openai_api_key": "k"}, "OPENAI_IMAGE_MODEL"),
    ({"image_provider": "cloudflare"}, "CLOUDFLARE_ACCOUNT_ID"),
    ({"image_provider": "cloudflare", "cloudflare_account_id": "a"}, "CLOUDFLARE_API_TOKEN"),
    ({"image_provider": "cloudflare", "cloudflare_account_id": "a", "cloudflare_api_token": "t"}, "CLOUDFLARE_IMAGE_MODEL"),
])
def test_missing_setting_gives_clear_russian_message(tmp_path, over, var):
    s = make_settings(tmp_path, **over)
    with pytest.raises(ConfigError) as err:
        make_text_provider(s) if "text_provider" in over else make_image_provider(s)
    assert var in str(err.value)


# ----------------------------------------------------------------------- проход «редактор»
ALT_PAGE_4 = "Раз, два, три — прыг! — и мальчик поскользнулся на мокром камне. Ноги сразу оказались в ледяной воде."


def _fixes(*items) -> str:
    return dump({"fixes": [{"page": n, "problem": "не так", "fixed_text": t} for n, t in items]})


async def test_editor_pass_rewrites_only_failing_pages_and_keeps_pictures_data(profile):
    plan, text = plan_and_text(profile)
    server = Recorder(gemini_reply(plan), gemini_reply(text), gemini_reply(CLEAR_JSON), gemini_reply(_fixes((4, ALT_PAGE_4))))
    result = await seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport)).generate_story(profile)
    draft, planned = json.loads(text), json.loads(plan)
    assert len(server.requests) == 4                                           # один цикл: план, текст, понятность, правки
    assert result.pages[3].text == ALT_PAGE_4
    assert [p.text for i, p in enumerate(result.pages) if i != 3] == [p["text"] for i, p in enumerate(draft["pages"]) if i != 3]
    assert result.title == draft["title"] and result.moral == draft["moral"] and result.wish == draft["wish"]
    assert [p.scene for p in result.pages] == planned["image_brief"]
    assert result.hero_visual == planned["character_bible"]["hero"] and result.refrain == planned["refrain"]["text"]
    sent = server.requests[3].content.decode()
    assert "<draft>" in sent and "<plan>" in sent and "hero_visual" not in sent and "image_brief" not in sent


@pytest.mark.parametrize("bad", [
    '{"fixes": "нет"}', "это не JSON", '{"fixes": [{"page": 99, "fixed_text": "Страница с несуществующим номером."}]}',
    '{"fixes": [{"page": 2}]}', '{"fixes": [{"page": 2, "fixed_text": "Ок."}]}', '[]', '{"fixes": []}',
])
async def test_editor_failure_keeps_draft(profile, bad):
    plan, text = plan_and_text(profile)
    server = Recorder(gemini_reply(plan), gemini_reply(text), gemini_reply(CLEAR_JSON), gemini_reply(bad))
    result = await seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport)).generate_story(profile)
    assert [p.text for p in result.pages] == [p["text"] for p in json.loads(text)["pages"]]


async def test_editor_provider_error_keeps_draft(profile, no_real_sleep):
    plan, text = plan_and_text(profile)
    server = Recorder(gemini_reply(plan), gemini_reply(text), gemini_reply(CLEAR_JSON), jr(400, {"error": {"message": "bad"}}))
    result = await seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport)).generate_story(profile)
    assert result.title == json.loads(text)["title"]


async def test_editor_merge_takes_good_fixes_and_drops_the_one_that_breaks_the_rules(profile):
    plan, text = plan_and_text(profile)
    bad = "Раз, два, три — Топ подставил спину, и у мальчика сердце наполнилось радостью до самых краёв."
    server = Recorder(gemini_reply(plan), gemini_reply(text), gemini_reply(CLEAR_JSON), gemini_reply(_fixes((4, ALT_PAGE_4), (5, bad))))
    result = await seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport)).generate_story(profile)
    draft = json.loads(text)
    assert result.pages[3].text == ALT_PAGE_4                                  # хорошая правка принята
    assert result.pages[4].text == draft["pages"][4]["text"]                   # правка с запрещённым оборотом отброшена


def test_factory_passes_proof_model_to_real_text_providers_and_ignores_it_for_mock(tmp_path):
    o = make_settings(tmp_path, text_provider="openai", openai_api_key=OPENAI_KEY, openai_text_model="t",
                      text_proof_model="proof-from-env")
    assert make_text_provider(o).proof_model == "proof-from-env"
    g = make_settings(tmp_path, text_provider="gemini", gemini_api_key=GEMINI_KEY, gemini_model="g",
                      text_proof_model="models/proof-from-env")
    assert make_text_provider(g).proof_model == "proof-from-env"
    assert make_text_provider(make_settings(tmp_path, text_proof_model="ignored")).proof_model == ""


# ----------------------------------------------------------------------- вычитка кыргызского (последний проход)
KY_PROFILE = {**SAMPLE, "language": "ky"}


def _ky():
    profile = Profile.from_payload(KY_PROFILE)
    plan, text = plan_and_text(profile)
    edited_first = json.loads(text)["pages"][0]["text"].replace("ысык", "жылуу")
    edited = json.loads(text)
    edited["pages"][0]["text"] = edited_first
    return profile, plan, text, edited_first, edited


def _bless(text: str) -> str:
    """Маленькая правка корректора, не меняющая длину страницы заметно."""
    return re.sub(r"([.!?…]+)\s*$", r", ооба\1", text)


def _proof_reply(edited: dict, fn=_bless) -> str:
    data = json.loads(json.dumps(edited))
    data["title"] = "Вычитанное название"
    data["pages"] = [{"text": fn(p["text"])} for p in data["pages"]]
    data["moral"] = "Вычитанная мысль."
    return dump(data)


def _ky_requests(proof_reply):
    """Запросы режиссёра, автора, редактора (правит страницу 1) и корректора к поддельному Gemini."""
    profile, plan, text, edited_first, edited = _ky()
    return profile, text, edited_first, edited, Recorder(
        gemini_reply(plan), gemini_reply(text), gemini_reply(CLEAR_JSON), gemini_reply(_fixes((1, edited_first))), proof_reply)


async def test_kyrgyz_proofreading_runs_after_editor_and_merges_only_texts():
    profile, text, edited_first, edited, server = _ky_requests(None)
    server.responses[-1] = gemini_reply(_proof_reply(edited))
    result = await seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport)).generate_story(profile)
    assert len(server.requests) == 5
    editor_system = server.json(3)["systemInstruction"]["parts"][0]["text"]
    proof_system = server.json(4)["systemInstruction"]["parts"][0]["text"]
    assert "редактор" in editor_system and "корректор" in proof_system and "носитель кыргызского" in proof_system
    proof_user = server.requests[4].content.decode()
    assert "жылуу" in proof_user and "<draft>" in proof_user                    # корректор получил текст ПОСЛЕ редактора
    assert "scene" not in proof_user and "hero_visual" not in proof_user         # описания для художника не видит
    assert result.title == "Вычитанное название" and result.moral == "Вычитанная мысль."
    assert result.pages[0].text == _bless(edited_first) and all(", ооба" in p.text for p in result.pages)
    planned = json.loads(plan_and_text(profile)[0])
    assert [p.scene for p in result.pages] == planned["image_brief"] and result.hero_visual == planned["character_bible"]["hero"]
    assert result.refrain == planned["refrain"]["text"] and [c.role for c in result.cast] == ["hero", "helper", "obstacle"]


async def test_russian_book_gets_no_kyrgyz_proofreading(profile):
    plan, text = plan_and_text(profile)
    server = Recorder(gemini_reply(plan), gemini_reply(text), gemini_reply(CLEAR_JSON), gemini_reply(NO_FIXES), gemini_reply(dump(json.loads(text))))
    result = await seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport)).generate_story(profile)
    assert len(server.requests) == 4 and result.title == json.loads(text)["title"]


async def test_kyrgyz_proofreading_is_off_when_polishing_is_off():
    profile, _, _, edited, server = _ky_requests(None)
    provider = seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport))
    provider.polish = False
    await provider.generate_story(profile)
    assert len(server.requests) == 2                                          # только режиссёр и автор


def _russian_pages_of_same_length(edited: dict) -> list[dict]:
    """Русский текст той же длины, что у кыргызского: перевод на русский, а не сокращение или раздувание."""
    russian = good_story("ru")["pages"]
    return [{"text": (ru["text"] * 4)[:len(ky["text"])]} for ru, ky in zip(russian, edited["pages"])]


@pytest.mark.parametrize("kind", ["not_json", "wrong_page_count", "shortened", "bloated", "translated_to_russian",
                                  "provider_error", "empty_page", "breaks_refrain"])
async def test_kyrgyz_proofreading_failure_keeps_editor_text(kind):
    profile, text, edited_first, edited, _ = _ky_requests(None)
    bad = {
        "not_json": "это не JSON",
        "wrong_page_count": dump({**edited, "pages": edited["pages"][:5]}),
        "shortened": dump({**edited, "pages": [{"text": "Ок."} for _ in edited["pages"]]}),
        "bloated": dump({**edited, "pages": [{"text": p["text"] * 2} for p in edited["pages"]]}),
        "translated_to_russian": dump({**edited, "pages": _russian_pages_of_same_length(edited)}),
        "empty_page": dump({**edited, "pages": [{"text": ""}] + edited["pages"][1:]}),
        "breaks_refrain": dump({**edited, "pages": [{"text": p["text"].replace("Бир, эки, үч", "Алты, жети, сегиз")}
                                                    for p in edited["pages"]]}),
    }.get(kind)
    reply = jr(400, {"error": {"message": "bad"}}) if kind == "provider_error" else gemini_reply(bad)
    profile, text, edited_first, edited, server = _ky_requests(reply)
    result = await seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport)).generate_story(profile)
    assert len(server.requests) == 5
    assert [p.text for p in result.pages] == [p["text"] for p in edited["pages"]]       # остался текст редактора
    assert result.title == json.loads(text)["title"]


async def test_kyrgyz_proofreading_after_failed_editor_still_proofreads_the_draft():
    profile, plan, text, _, _ = _ky()
    draft = json.loads(text)
    server = Recorder(gemini_reply(plan), gemini_reply(text), gemini_reply(CLEAR_JSON), gemini_reply("это не JSON"), gemini_reply(_proof_reply(draft)))
    result = await seeded(GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport)).generate_story(profile)
    assert result.title == "Вычитанное название" and result.pages[0].text == _bless(draft["pages"][0]["text"])


async def test_gemini_uses_proof_model_only_for_the_kyrgyz_proofreading_call():
    profile, _, _, edited, server = _ky_requests(None)
    server.responses[-1] = gemini_reply(_proof_reply(edited))
    provider = seeded(GeminiTextProvider(GEMINI_KEY, "main-model", proof_model="models/proof-model", transport=server.transport))
    await provider.generate_story(profile)
    urls = [str(r.url) for r in server.requests]
    assert [("main-model" in u, "proof-model" in u) for u in urls] == [(True, False)] * 4 + [(False, True)]


async def test_openai_uses_proof_model_only_for_the_kyrgyz_proofreading_call():
    profile, plan, text, edited_first, edited = _ky()
    server = Recorder(chat_reply(plan), chat_reply(text), chat_reply(CLEAR_JSON), chat_reply(_fixes((1, edited_first))), chat_reply(_proof_reply(edited)))
    provider = seeded(OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1", "main-model", proof_model="proof-model",
                                         transport=server.transport))
    result = await provider.generate_story(profile)
    assert [server.json(i)["model"] for i in range(5)] == ["main-model"] * 4 + ["proof-model"]
    assert result.title == "Вычитанное название"


async def test_without_proof_model_the_main_model_proofreads():
    profile, plan, text, edited_first, edited = _ky()
    server = Recorder(chat_reply(plan), chat_reply(text), chat_reply(CLEAR_JSON), chat_reply(_fixes((1, edited_first))), chat_reply(_proof_reply(edited)))
    provider = seeded(OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1", "main-model", transport=server.transport))
    await provider.generate_story(profile)
    assert {server.json(i)["model"] for i in range(5)} == {"main-model"}


async def test_proof_model_errors_name_the_right_setting_and_do_not_break_the_order():
    missing = jr(404, {"error": {"message": "models/zzz is not found"}})
    with pytest.raises(ProviderError) as gemini_err:
        await GeminiTextProvider(GEMINI_KEY, "main", transport=Recorder(missing).transport)._complete(
            "s", [("user", "u")], "zzz")
    assert "TEXT_PROOF_MODEL" in gemini_err.value.message and "zzz" in gemini_err.value.message
    with pytest.raises(ProviderError) as openai_err:
        await OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1", "main",
                                 transport=Recorder(jr(404, {"error": {"message": "x", "code": "model_not_found"}})).transport
                                 )._complete("s", [("user", "u")], "zzz")
    assert "TEXT_PROOF_MODEL" in openai_err.value.message
    # а сама книга при неверной модели корректора всё равно готова: остаётся текст редактора
    profile, text, edited_first, edited, _ = _ky_requests(None)
    server = Recorder(*[gemini_reply(x) for x in (plan_and_text(profile)[0], text, CLEAR_JSON, _fixes((1, edited_first)))], missing)
    provider = seeded(GeminiTextProvider(GEMINI_KEY, "main", proof_model="zzz", transport=server.transport))
    result = await provider.generate_story(profile)
    assert result.pages[0].text == edited_first and result.title == json.loads(text)["title"]
