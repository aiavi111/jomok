"""Сквозная проверка: приложение с провайдерами OpenAI работает по настоящему HTTP с поддельным сервером OpenAI."""
import base64
import io
import json

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image

from app.layout import parse_size
from app.placeholder import draw_placeholder
from app.profile import Profile
from app.providers.image_openai import OpenAIImageProvider
from app.providers.text_openai import OpenAITextProvider
from app.story import PAGES

from .conftest import SAMPLE, build_env, tma
from .writer_helpers import CLEAR, author_dict, dump, plan_dict, seeded, seeds_for, stage_of

KEY = "sk-proj-INTEGRATIONkeyINTEGRATIONkey1234"


class FakeOpenAI:
    def __init__(self):
        self.calls: list[tuple[str, dict, str]] = []
        self.app = web.Application()
        self.app.router.add_post("/v1/chat/completions", self.chat)
        self.app.router.add_post("/v1/images/generations", self.images)
        self.app.router.add_post("/v1/images/edits", self.images)

    def _check_auth(self, request):
        if request.headers.get("Authorization") != f"Bearer {KEY}":
            raise web.HTTPUnauthorized(text=json.dumps({"error": {"message": "Incorrect API key provided", "code": "invalid_api_key"}}),
                                       content_type="application/json")

    async def chat(self, request):
        self._check_auth(request)
        body = await request.json()
        self.calls.append(("chat", body, request.path))
        profile = Profile.from_payload(SAMPLE)
        seeds = seeds_for(profile)
        system = body["messages"][0]["content"] if body["messages"][0]["role"] == "system" else ""
        stage = stage_of(system)
        if stage == "planner":
            reply = plan_dict(profile, seeds)
        elif stage == "author":
            reply = author_dict(profile, seeds)
        elif stage == "comprehension":
            reply = CLEAR
        elif stage == "editor":
            reply = {"fixes": []}
        else:                                                    # чтение названия, нарисованного на обложке
            reply = {"title": author_dict(profile, seeds)["title"]}
        return web.json_response({"choices": [{"message": {"role": "assistant", "content": dump(reply)}}]})

    async def images(self, request):
        self._check_auth(request)
        body = await request.json()
        self.calls.append(("images", body, request.path))
        picture = draw_placeholder("fake", body["prompt"][:80], body["prompt"], size=parse_size(body["size"]))
        return web.json_response({"data": [{"b64_json": base64.b64encode(picture).decode()}]})


async def start_fake():
    fake = FakeOpenAI()
    server = TestServer(fake.app)
    await server.start_server()
    return fake, server, f"http://127.0.0.1:{server.port}/v1"


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), (210, 160, 120)).save(out, "JPEG")
    return out.getvalue()


async def test_whole_order_over_real_http_without_photo(tmp_path):
    fake, server, base = await start_fake()
    e = await build_env(tmp_path, text=seeded(OpenAITextProvider(KEY, base, "text-model-from-env")),
                        image=OpenAIImageProvider(KEY, base, "image-model-from-env", "low"),
                        text_provider="openai", image_provider="openai")
    try:
        order = await e.wait_done(await e.create())
        assert order["status"] == "done" and order["pdf_url"] and len(order["pages"]) == PAGES
        kinds = [(path, body.get("model")) for kind, body, path in fake.calls]
        assert kinds.count(("/v1/chat/completions", "text-model-from-env")) == 5   # план, текст, «понятно ли пятилетнему», редактор и чтение названия на обложке
        assert kinds.count(("/v1/images/generations", "image-model-from-env")) == 1       # лист героев на белом фоне, без референсов
        assert kinds.count(("/v1/images/edits", "image-model-from-env")) == PAGES + 1     # обложка и страницы: референс — лист героев
        edits = [body for _, body, path in fake.calls if path.endswith("/edits")]
        assert all(len(b["images"]) == 1 and b["images"][0]["image_url"].startswith("data:image/jpeg;base64,") for b in edits)
        assert all("input_fidelity" not in b and b["quality"] == "low" for b in edits)
        assert sorted(b["size"] for b in edits) == ["1024x1024"] + ["2048x1024"] * PAGES   # обложка квадратная, страницы широкие
        generations = [body for _, body, path in fake.calls if path.endswith("/generations")]
        assert [b["size"] for b in generations] == ["1024x1024"]                         # лист героев квадратный
        pages = [b for b in edits if b["size"] == "2048x1024"]                            # у обложки имя есть в названии: это его единственное место
        assert all("hero_visual" not in b and "Айдар" not in b["prompt"] for b in pages)
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close(); await server.close()


async def test_photo_goes_to_openai_only_as_reference_and_book_still_builds(tmp_path):
    fake, server, base = await start_fake()
    e = await build_env(tmp_path, text=seeded(OpenAITextProvider(KEY, base, "t")), image=OpenAIImageProvider(KEY, base, "i"),
                        text_provider="openai", image_provider="openai")
    try:
        form = aiohttp.FormData()
        form.add_field("profile", json.dumps({**SAMPLE, "photo_consent": True}, ensure_ascii=False), content_type="application/json")
        form.add_field("photo", jpeg(), filename="kid.jpg", content_type="image/jpeg")
        resp = await e.client.post("/api/orders", data=form, headers=tma())
        assert resp.status == 201
        order = await e.wait_done((await resp.json())["order_id"])
        assert order["status"] == "done"
        edits = [body for _, body, path in fake.calls if path.endswith("/edits")]
        assert len(edits) == PAGES + 1                                      # обложка по фото + страницы сказки
        assert all(len(b["images"]) == 2 for b in edits)                    # у каждой: фото ребёнка + лист героев (не обложка)
        generations = [body for _, body, path in fake.calls if path.endswith("/generations")]
        assert len(generations) == 1 and "images" not in generations[0]     # лист героев рисуется без фото
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close(); await server.close()


async def test_wrong_key_gives_explained_error_over_real_http(tmp_path):
    fake, server, base = await start_fake()
    e = await build_env(tmp_path, text=OpenAITextProvider("sk-wrong-WRONGWRONGWRONGWRONG1234", base, "t"),
                        text_provider="openai")
    try:
        order = await e.wait_done(await e.create())
        assert order["status"] == "error" and "не засчитана" in order["error"]
        assert any("Неверный ключ OpenAI" in t for t in e.notifier.admin_texts)
        assert not any("sk-wrong" in t for t in e.notifier.admin_texts)
    finally:
        await e.service.shutdown(); await e.client.close(); e.db.close(); await server.close()
