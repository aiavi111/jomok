"""Провайдеры OpenAI, Gemini, Cloudflare на поддельном сетевом слое: форма запросов, повторы, ошибки."""
import base64
import json
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
from app.profile import Profile

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
    assert http_mod.IMAGE_TIMEOUT.read == 300 and http_mod.TEXT_TIMEOUT.read <= 180


# ----------------------------------------------------------------------- OpenAI, текст
def chat_reply(content: str) -> httpx.Response:
    return jr(200, {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]})


async def test_openai_text_request_follows_docs_and_omits_temperature_and_max_tokens(profile):
    server = Recorder(chat_reply(json.dumps(good_story(), ensure_ascii=False)))
    provider = OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1/", "model-from-env", transport=server.transport)
    story = await provider.generate_story(profile)
    assert story.title
    request = server.requests[0]
    assert str(request.url) == "https://api.openai.test/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {OPENAI_KEY}"
    body = server.json()
    assert set(body) == {"model", "messages", "response_format"}               # ни temperature, ни max_tokens
    assert body["model"] == "model-from-env" and body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system" and "JSON" in body["messages"][0]["content"]
    assert body["messages"][1]["role"] == "user" and "<child>" in body["messages"][1]["content"]
    assert OPENAI_KEY not in str(request.url)


async def test_openai_text_retry_sends_error_text_back_to_model(profile):
    server = Recorder(chat_reply("не JSON"), chat_reply(json.dumps(good_story(), ensure_ascii=False)))
    provider = OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", transport=server.transport)
    await provider.generate_story(profile)
    second = server.json(1)["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[2]["content"] == "не JSON" and "не прошёл проверку" in second[3]["content"]


async def test_openai_text_falls_back_when_model_rejects_response_format(profile):
    server = Recorder(jr(400, {"error": {"message": "Unsupported parameter: 'response_format'"}}),
                      chat_reply(json.dumps(good_story(), ensure_ascii=False)))
    provider = OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", transport=server.transport)
    await provider.generate_story(profile)
    assert "response_format" in server.json(0) and "response_format" not in server.json(1)


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
    server = Recorder(jr(429, {"error": {"message": "Rate limit reached", "code": "rate_limit_exceeded"}},
                         headers={"Retry-After": "1"}), chat_reply(json.dumps(good_story(), ensure_ascii=False)))
    provider = OpenAITextProvider(OPENAI_KEY, "https://api.openai.test/v1", "m", transport=server.transport)
    provider.polish = False
    assert (await provider.generate_story(profile)).title and len(server.requests) == 2


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
    server = Recorder(gemini_reply("не JSON"), gemini_reply(json.dumps(good_story(), ensure_ascii=False)))
    provider = GeminiTextProvider(GEMINI_KEY, "models/gemini-model-from-env", transport=server.transport)
    await provider.generate_story(profile)
    request = server.requests[0]
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-model-from-env:generateContent"
    assert request.headers["x-goog-api-key"] == GEMINI_KEY and GEMINI_KEY not in str(request.url)
    body = server.json(0)
    assert body["systemInstruction"]["parts"][0]["text"].startswith("Ты детский писатель")
    assert body["contents"] == [{"role": "user", "parts": [{"text": body["contents"][0]["parts"][0]["text"]}]}]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["maxOutputTokens"] >= 8192
    second = server.json(1)["contents"]
    assert [c["role"] for c in second] == ["user", "model", "user"] and "не прошёл проверку" in second[2]["parts"][0]["text"]


async def test_gemini_skips_thought_parts_and_joins_text(profile):
    reply = jr(200, {"candidates": [{"content": {"parts": [
        {"text": "размышления", "thought": True}, {"text": json.dumps(good_story(), ensure_ascii=False)[:50]},
        {"text": json.dumps(good_story(), ensure_ascii=False)[50:]}]}}]})
    story = await GeminiTextProvider(GEMINI_KEY, "m", transport=Recorder(reply).transport).generate_story(
        Profile.from_payload(SAMPLE))
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
    limited = jr(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "slow down",
                                 "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "4s"}]}})
    server = Recorder(limited, jr(503, {"error": {"message": "overloaded"}}),
                      gemini_reply(json.dumps(good_story(), ensure_ascii=False)))
    provider = GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport)
    provider.polish = False
    await provider.generate_story(profile)
    assert len(server.requests) == 3 and no_real_sleep[0] == 4.0


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
    assert make_text_provider(g).model == "g-model"
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
def _edited(story: dict, suffix: str = " Бряк!") -> str:
    return json.dumps({"title": "Новое название", "pages": [{"text": p["text"] + suffix} for p in story["pages"]],
                       "moral": "Живая мысль этой истории.", "wish": "Айдар, пусть тебе всегда везёт!"},
                      ensure_ascii=False)


async def test_editor_pass_rewrites_text_but_keeps_pictures_data(profile):
    story = good_story()
    server = Recorder(gemini_reply(json.dumps(story, ensure_ascii=False)), gemini_reply(_edited(story)))
    result = await GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport).generate_story(profile)
    assert len(server.requests) == 2
    assert result.title == "Новое название" and result.moral == "Живая мысль этой истории."
    assert all(p.text.endswith("Бряк!") for p in result.pages)
    assert [p.scene for p in result.pages] == [p["scene"] for p in story["pages"]]
    assert result.hero_visual == story["hero_visual"]
    sent = server.requests[1].content.decode()
    assert "<draft>" in sent and "scene" not in sent and "hero_visual" not in sent    # редактор не видит описаний для художника


@pytest.mark.parametrize("bad", ['{"pages": []}', "это не JSON", '{"title": "x", "pages": [{"text": "коротко"}]}'])
async def test_editor_failure_keeps_draft(profile, bad):
    story = good_story()
    server = Recorder(gemini_reply(json.dumps(story, ensure_ascii=False)), gemini_reply(bad))
    result = await GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport).generate_story(profile)
    assert result.title == story["title"] and result.pages[0].text == story["pages"][0]["text"]


async def test_editor_provider_error_keeps_draft(profile, no_real_sleep):
    story = good_story()
    server = Recorder(gemini_reply(json.dumps(story, ensure_ascii=False)), jr(400, {"error": {"message": "bad"}}))
    result = await GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport).generate_story(profile)
    assert result.title == story["title"]


async def test_editor_shortened_pages_are_rejected(profile):
    story = good_story()
    short = json.dumps({"title": "T", "pages": [{"text": "Ок."} for _ in story["pages"]], "moral": "м", "wish": "п"}, ensure_ascii=False)
    server = Recorder(gemini_reply(json.dumps(story, ensure_ascii=False)), gemini_reply(short))
    result = await GeminiTextProvider(GEMINI_KEY, "m", transport=server.transport).generate_story(profile)
    assert result.title == story["title"]
