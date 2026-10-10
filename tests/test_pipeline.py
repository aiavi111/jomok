"""Сборка книги: сбой одной картинки не ломает книгу, промты, параллелизм."""
import asyncio

import pytest
from pypdf import PdfReader

from app import prompts
from app.bookgen import build_book
from app.errors import ProviderError
from app.profile import Profile
from app.providers.text_mock import MockTextProvider
from app.story import PAGES

from .conftest import SAMPLE, ScriptedImage, provider_error


async def run(tmp_path, image, profile, *, photo=None, text=None, **kw):
    return await build_book(profile, text or MockTextProvider(), image, tmp_path / "order", photo=photo,
                            image_sem=asyncio.Semaphore(3), mock=True, **kw)


def pdf_pages(path) -> int:
    return len(PdfReader(str(path)).pages)


async def test_failed_page_is_replaced_by_placeholder_and_book_is_still_built(tmp_path, profile):
    image = ScriptedImage(fail=lambda n, prompt, label: provider_error("сервис не ответил") if label == "Страница 3" else None)
    result = await run(tmp_path, image, profile)
    assert result.failed_pages == ["p3"]
    assert "Страница 3" in result.failure_notes[0]
    for name in ["cover"] + [f"p{i}" for i in range(1, PAGES + 1)]:
        assert (tmp_path / "order" / f"{name}.jpg").stat().st_size > 5_000
    assert pdf_pages(result.pdf_path) == PAGES + 2     # развороты: обложка, страницы сказки, финал


async def test_page_is_retried_three_times_then_succeeds(tmp_path, profile):
    attempts = {"n": 0}

    def flaky(n, prompt, label):
        if label == "Страница 5":
            attempts["n"] += 1
            if attempts["n"] < 3:
                return provider_error("временный сбой")

    result = await run(tmp_path, ScriptedImage(fail=flaky), profile)
    assert attempts["n"] == 3 and result.failed_pages == []


async def test_page_gives_up_after_exactly_three_attempts(tmp_path, profile):
    image = ScriptedImage(fail=lambda n, p, label: provider_error("всегда сбой") if label == "Страница 2" else None)
    result = await run(tmp_path, image, profile)
    assert sum(1 for c in image.calls if c["label"] == "Страница 2") == 3
    assert result.failed_pages == ["p2"]


async def test_filter_rejection_is_not_retried(tmp_path, profile):
    image = ScriptedImage(fail=lambda n, p, label: provider_error("фильтр", no_retry=True) if label == "Страница 4" else None)
    result = await run(tmp_path, image, profile)
    assert sum(1 for c in image.calls if c["label"] == "Страница 4") == 1
    assert result.failed_pages == ["p4"]


async def test_fatal_error_stops_the_order(tmp_path, profile):
    image = ScriptedImage(fail=lambda n, p, label: provider_error("неверный ключ", fatal=True))
    with pytest.raises(ProviderError) as err:
        await run(tmp_path, image, profile)
    assert err.value.fatal
    assert not (tmp_path / "order" / "book.pdf").exists()


async def test_cover_failure_does_not_break_pages_and_cover_is_not_used_as_reference(tmp_path, profile):
    image = ScriptedImage(fail=lambda n, p, label: provider_error("сбой") if label == "Обложка" else None)
    result = await run(tmp_path, image, profile)
    assert "cover" in result.failed_pages and pdf_pages(result.pdf_path) == PAGES + 2
    page_calls = [c for c in image.calls if c["label"].startswith("Страница")]
    assert all(c["refs"] is None for c in page_calls)                       # заглушка не может быть референсом
    assert all(result.story.hero_visual in c["prompt"] for c in page_calls)  # героя описываем текстом


async def test_prompt_order_is_layout_then_scene_then_hero_then_style_without_references(tmp_path, profile):
    image = ScriptedImage(supports_reference=False)
    result = await run(tmp_path, image, profile, photo=b"\xff\xd8secret-photo")
    pages = sorted((c for c in image.calls if c["label"].startswith("Страница")), key=lambda c: int(c["label"].split()[-1]))
    assert len(pages) == PAGES
    for number, call in enumerate(pages, start=1):
        prompt = call["prompt"]
        scene = prompts.pin_hero(result.story.pages[number - 1].scene, result.story, profile)    # «the hero» в кадре называется мальчиком или девочкой
        assert call["refs"] is None                                     # фото и обложка не уходят провайдеру без референсов
        assert prompt.lower().startswith("wide panoramic double-page spread, 2:1")      # сначала разметка кадра
        assert prompt.index(prompts.page_layout_clause(number, has_refs=False)) == 0
        assert prompt.index(scene) < prompt.index(result.story.hero_visual) < prompt.index(prompts.LEGAL_CLAUSE) \
            < prompt.index(prompts.STYLE)
        assert len(prompt) <= 2000
    assert all(c["refs"] is None for c in image.calls)                   # фото вообще не передавалось


async def test_references_are_cover_and_photo_when_provider_supports_them(tmp_path, profile):
    photo = b"\xff\xd8photo-bytes"
    image = ScriptedImage(supports_reference=True)
    result = await run(tmp_path, image, profile, photo=photo)
    cover_call = next(c for c in image.calls if c["label"] == "Обложка")
    assert cover_call["refs"] == [photo]
    assert "reference photo" in cover_call["prompt"] and "no photorealism" in cover_call["prompt"]
    cover_bytes = (tmp_path / "order" / "cover.jpg").read_bytes()
    page_calls = [c for c in image.calls if c["label"].startswith("Страница")]
    assert len(page_calls) == PAGES
    for call in page_calls:
        assert call["refs"] == [cover_bytes, photo]
        assert "same character and the same outfit" in call["prompt"].lower()
        assert result.story.hero_visual not in call["prompt"]


async def test_child_name_never_reaches_image_prompts(tmp_path):
    profile = Profile.from_payload({**SAMPLE, "name": "Бекзат"})

    class NameLeaking(MockTextProvider):
        async def generate_story(self, p):
            story = (await super().generate_story(p)).to_dict()
            story["hero_visual"] += " Бекзат has a red cap."
            for page in story["pages"]:
                page["scene"] += " Then бекзат smiles."
            from app.story import validate_story
            return validate_story(story, p.language)

    image = ScriptedImage()
    await run(tmp_path, image, profile, text=NameLeaking())
    assert image.calls and all("бекзат" not in c["prompt"].lower() for c in image.calls)


async def test_islamic_prompt_adds_modest_clothing_and_headscarf_only_when_chosen(tmp_path):
    girl = Profile.from_payload({**SAMPLE, "gender": "girl", "islamic": True, "headscarf": True})
    image = ScriptedImage()
    await run(tmp_path, image, girl)
    assert all("modest clothing" in c["prompt"] and "wears a simple headscarf" in c["prompt"] for c in image.calls)

    no_scarf = Profile.from_payload({**SAMPLE, "gender": "girl", "islamic": True, "headscarf": False})
    image2 = ScriptedImage()
    await run(tmp_path / "b", image2, no_scarf)
    assert all("does not wear a headscarf" in c["prompt"] for c in image2.calls)

    plain = ScriptedImage()
    await run(tmp_path / "c", plain, Profile.from_payload(SAMPLE))
    assert all("modest clothing" not in c["prompt"] for c in plain.calls)


async def test_no_more_than_three_images_are_drawn_at_once(tmp_path, profile):
    image = ScriptedImage(delay=0.05)
    await run(tmp_path, image, profile)
    assert 1 < image.max_active <= 3
    assert len(image.calls) == PAGES + 1            # обложка и страницы сказки


async def test_cover_is_requested_square_and_pages_wide_and_saved_at_exactly_those_sizes(tmp_path, profile):
    """Обложка 1024x1024 (1:1), страницы 2048x1024 (2:1). Что бы ни прислал провайдер, файл обрезается по центру
    до нужного соотношения и приводится к размеру точно."""
    import io

    from PIL import Image

    class Squares(ScriptedImage):
        async def generate(self, prompt, refs=None, size="1024x1024", *, label=None):
            await super().generate(prompt, refs, size, label=label)
            out = io.BytesIO()
            Image.new("RGB", (1024, 1024), (240, 180, 60)).save(out, "PNG")      # как Cloudflare: всегда квадрат
            return out.getvalue()

    image = Squares()
    result = await run(tmp_path, image, profile)
    sizes = {c["label"]: c["size"] for c in image.calls}
    assert len(image.calls) == PAGES + 1
    assert sizes["Обложка"] == "1024x1024"
    assert all(sizes[f"Страница {i}"] == "2048x1024" for i in range(1, PAGES + 1))
    with Image.open(tmp_path / "order" / "cover.jpg") as saved:
        assert saved.size == (1024, 1024) and saved.format == "JPEG"
    for i in range(1, PAGES + 1):
        with Image.open(tmp_path / "order" / f"p{i}.jpg") as saved:
            assert saved.size == (2048, 1024) and saved.format == "JPEG", f"p{i}"
    assert pdf_pages(result.pdf_path) == PAGES + 2


async def test_wide_picture_from_the_provider_is_cropped_to_a_square_cover_and_kept_wide_for_pages(tmp_path, profile):
    import io

    from PIL import Image

    class AnyShape(ScriptedImage):
        async def generate(self, prompt, refs=None, size="1024x1024", *, label=None):
            await super().generate(prompt, refs, size, label=label)
            out = io.BytesIO()
            Image.new("RGB", (1536, 1024), (240, 180, 60)).save(out, "PNG")
            return out.getvalue()

    await run(tmp_path, AnyShape(), profile)
    with Image.open(tmp_path / "order" / "cover.jpg") as cover, Image.open(tmp_path / "order" / "p1.jpg") as page:
        assert cover.size == (1024, 1024) and page.size == (2048, 1024)


async def test_pages_are_saved_at_quality_88_and_the_cover_at_90(tmp_path, profile):
    await run(tmp_path, ScriptedImage(), profile)
    from PIL import Image
    with Image.open(tmp_path / "order" / "p1.jpg") as page, Image.open(tmp_path / "order" / "cover.jpg") as cover:
        # у JPEG качество видно по таблице квантования: чем выше качество, тем меньше числа в таблице
        assert sum(page.quantization[0]) > sum(cover.quantization[0])


async def test_failed_wide_page_gets_a_wide_placeholder_in_the_right_proportions(tmp_path, profile):
    from PIL import Image
    image = ScriptedImage(fail=lambda n, p, label: provider_error("сбой", no_retry=True) if label == "Страница 2" else None)
    await run(tmp_path, image, profile)
    with Image.open(tmp_path / "order" / "p2.jpg") as page, Image.open(tmp_path / "order" / "cover.jpg") as cover:
        assert page.size == (2048, 1024) and cover.size == (1024, 1024)


async def test_overlay_mode_is_passed_to_the_pdf_and_chosen_styles_are_saved_for_the_app(tmp_path, profile):
    import json
    result = await run(tmp_path, ScriptedImage(), profile, overlay_mode="plate")
    assert result.text_styles and set(result.text_styles) <= {"plate-cream", "plate-dark"}
    meta = json.loads((tmp_path / "order" / "layout.meta.json").read_text(encoding="utf-8"))
    assert meta["overlay_mode"] == "plate" and meta["text_styles"] == result.text_styles
    assert meta["text_sides"] == ["right" if i % 2 else "left" for i in range(1, PAGES + 1)]
    from app.bookgen import read_layout_meta
    assert read_layout_meta(tmp_path / "order") == meta and read_layout_meta(tmp_path / "nowhere") == {}


async def test_wrong_overlay_mode_is_refused_before_any_picture_is_paid_for(tmp_path, profile):
    image = ScriptedImage()
    with pytest.raises(ValueError):
        await run(tmp_path, image, profile, overlay_mode="sticker")
    assert image.calls == []


async def test_status_callbacks_in_order_and_images_saved_before_pdf(tmp_path, profile):
    seen = []

    async def on_status(status):
        seen.append(status)

    await build_book(profile, MockTextProvider(), ScriptedImage(), tmp_path / "o", on_status=on_status, mock=True)
    assert seen == ["writing", "drawing", "assembling"]


# ----------------------------------------------------------------------- имя ребёнка латиницей
import pytest as _pytest

from app.prompts import latin_variants, scrub_name


@_pytest.mark.parametrize("name, gender, text, forbidden", [
    ("Айдар", "boy", "Aidar sits on a hill. Then Aydar's horse runs; AIDAR smiles.", ["aidar", "aydar"]),
    ("Айгүл", "girl", "Aigul stands by the lake and Aygul waves.", ["aigul", "aygul"]),
    ("Егор", "boy", "Yegor and Egor play. Yegor's cap is red.", ["yegor", "egor"]),
    ("Нурбек", "boy", "Nurbek, Nurbek's friend, and nurbek again.", ["nurbek"]),
    ("Айдар", "boy", "A 6-year-old Central Asian boy named Aidar with black hair.", ["aidar", "named"]),
    ("Айдар", "boy", "Айдар и Айдару на картинке", ["айдар"]),
])
def test_scrub_name_removes_cyrillic_and_latin_forms(name, gender, text, forbidden):
    cleaned = scrub_name(text, name, gender).lower()
    for word in forbidden:
        assert word not in cleaned, cleaned


def test_scrub_name_uses_neutral_words_and_keeps_grammar():
    assert scrub_name("Aidar sits on a hill.", "Айдар", "boy") == "The boy sits on a hill."
    assert scrub_name("Next to her, Aigul smiles.", "Айгүл", "girl") == "Next to her, the girl smiles."
    assert scrub_name("Aidar's horse", "Айдар", "boy") == "The boy's horse"
    assert scrub_name("A pair of airplanes and an aim", "Ай", "boy") == "A pair of airplanes and an aim"   # короткие имена не ломают обычные слова


def test_latin_variants_cover_common_spellings():
    assert {"aidar", "aydar"} <= latin_variants("Айдар")
    assert {"aigul", "aygul"} <= latin_variants("Айгүл")
    assert latin_variants("Emma") == {"emma"}


async def test_real_gemini_style_story_with_latin_name_does_not_leak_into_image_prompts(tmp_path):
    """Так ответил настоящий Gemini: имя в scene и hero_visual записано латиницей."""
    profile = Profile.from_payload(SAMPLE)

    class LatinName(MockTextProvider):
        async def generate_story(self, p):
            data = (await super().generate_story(p)).to_dict()
            data["hero_visual"] = "A 6-year-old Central Asian boy named Aidar. He has short black hair and a blue vest."
            for page in data["pages"]:
                page["scene"] = "Aidar stands on a hill next to his white horse, looking at the mountains. Aidar's drawing is in his hand."
            from app.story import validate_story
            return validate_story(data, p.language)

    image = ScriptedImage(supports_reference=False)
    await run(tmp_path, image, profile, text=LatinName())
    assert image.calls and all("aidar" not in c["prompt"].lower() and "named" not in c["prompt"].lower() for c in image.calls)
