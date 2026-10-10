"""Тексты инструкций моделям: промты для иллюстраций (здесь) и совместимые имена для писателя.

Писатель (режиссёр, автор, редактор, корректор кыргызского) живёт в writer_prompts.py, а его правила, лимиты и проверки в
writer.py. Ниже они переэкспортированы под прежними именами, чтобы старый код и тесты продолжали работать.
"""
from __future__ import annotations

import re

from .layout import calm_side, hero_side
from .profile import Profile
from .story import PAGES, Story
from .textutil import cut_words
from .translit import latin_variants
from .writer import FAMILY_SHOWN
from .writer_prompts import (AUTHOR_SCHEMA as STORY_SCHEMA_TEXT, AUTHOR_TEMPLATE as SYSTEM_TEMPLATE,  # noqa: F401
                             EDITOR_TEMPLATE, HEADSCARF_OFF, HEADSCARF_ON, ISLAMIC_BLOCK, KY_AUTHOR_NOTE as KYRGYZ_NOTE,
                             KY_PROOF_ISLAMIC, KY_PROOF_TEMPLATE, PHOTO_NOTE, PLANNER_TEMPLATE, build_editor_prompts,
                             build_ky_proof_prompts, build_planner_prompts, build_system_prompt, build_user_prompt, years)

_years = years


# ------------------------------------------------------------------ иллюстрации
STYLE_BASE = ("vivid saturated candy-bright rainbow palette, playful cinematic 3D-animated family-film children's book "
              "illustration, glowing magical light with sparkles and soft bokeh, cheerful happy faces with big sparkling "
              "eyes, rich but clean background with depth")
STYLE = STYLE_BASE + ", no text, no letters, no watermark"
STYLE_COVER = STYLE_BASE + ", no watermark, no logos"          # на обложке название рисуется буквами внутри картинки

# Стиль иллюстраций выбирает родитель (profile.style, options.STYLES): один блок на всю книгу, для страниц и для обложки.
STYLE_FLAT = ("flat vector-like children's book illustration, clean confident outlines, saturated rainbow colours, simple "
              "shapes with soft flat shading, cheerful happy faces with big sparkling eyes, rich but clean background, no "
              "photorealism, no 3D render")
STYLE_REALISTIC = ("cinematic photoreal family-film still, natural skin and hair texture, warm bright natural light with soft "
                   "sparkles, a real child whose face and hair look exactly like the reference photo, the same child identity "
                   "preserved, fantasy creatures and magic rendered as high-end CGI, rich detailed background with depth, no "
                   "cartoon, no illustration")
STYLE_BASES = {"cartoon3d": STYLE_BASE, "flat2d": STYLE_FLAT, "realistic": STYLE_REALISTIC}


def style_block(profile: Profile, *, cover: bool = False) -> str:
    """Блок стиля картинок по выбору родителя; неизвестный стиль (старый профиль) — 3D-мультик по умолчанию."""
    base = STYLE_BASES.get(profile.style, STYLE_BASE)
    return base + (", no watermark, no logos" if cover else ", no text, no letters, no watermark")

# Название на обложке рисует сама модель картинок. Просим сверить написание 20 раз, а дальше текст на картинке
# всё равно проверяется отдельно (bookgen: модель читает надпись и сравнивает с названием).
COVER_TITLE_CLAUSE = (
    "Front cover of a children's picture book. Write the title exactly once in large bold rounded lettering: one or "
    "two straight horizontal centred lines at the top, flat cream-yellow letters with a thick dark indigo outline, no "
    "3D, gradients or sparkles on the letters: «{title}». Check the spelling letter by letter twenty times over: every "
    "letter exactly as given and in this order, no extra, missing, doubled, swapped, mirrored or invented letters "
    "(Cyrillic, including ү ө ң when present). No other text on the cover: no subtitle, name, signature or logo."
)
COVER_CALM = ("The background is beautiful but calm and not overloaded: soft depth of field, one clear focal point, "
              "nothing competing with the hero and the title.")

SAME_CHARACTER = ("The same character and the same outfit as in the reference image. The hero is active: running, climbing, "
                  "exploring or reaching, standing or crouching, and not sitting still unless the scene says so. "
                  "Use the reference images ONLY to keep the characters' faces, looks and outfits identical: do NOT reuse "
                  "their background, place, pose or composition; paint the new place from this scene.")
REALISTIC_PHOTO_INSTRUCTION = ("The child's face must be recognisably the same real person as in the reference photo: the same face "
                               "shape, eyes, hair, skin tone and age, identity preserved exactly. Do not copy the photo's pose, "
                               "background or clothes: the hero is active and in motion, not sitting at a desk.")
REALISTIC_SAME_CHARACTER = ("The same child, recognisably the same person, and the same outfit as in the reference image. The hero "
                            "is active: running, climbing, exploring or reaching, and not sitting still unless the scene says so. "
                            "Use the reference images ONLY to keep the characters' faces, looks and outfits identical: do NOT "
                            "reuse their background, place, pose or composition; paint the new place from this scene.")
PHOTO_INSTRUCTION = ("Draw the child from the reference photo as the hero of this illustration; keep recognizable "
                     "features (hair color and shape, face shape, skin tone, age), no photorealism. Do not copy the "
                     "photo's pose, background or clothes: the hero is active and in motion, not sitting at a desk.")
MODEST = "All characters wear modest clothing that fully covers arms and legs."
# Юридическое правило для всех картинок: чужих персонажей не рисуем, берём собирательный образ.
LEGAL_CLAUSE = ("Never draw existing trademarked or copyrighted characters or real celebrities; if the "
                "story mentions a famous type of character, draw an original look-alike archetype.")
MAX_PROMPT = 2000  # FLUX принимает до 2048 символов; всё, что нельзя резать (разметка кадра, юридическое правило, стиль), входит сюда
NOTE_MAX = 240     # палитра книги (style_note режиссёра): ей оставляется место всегда, её держат все страницы и обложка
COVER_WORLD_MAX = 170   # сколько знаков первой сцены идёт на обложку как «мир за героем»
COVER_FRIENDS_MAX = 170   # друзья мира на обложке: коротко, место нужно названию, фото и помощнику
WORLD_MAX = 230    # описание друзей выбранного мира на странице (на обложке чуть длиннее): режется по слову


def page_layout_clause(index: int, *, has_refs: bool) -> str:
    """Композиция страницы истории: широкий разворот 2:1, герои на одной половине, другая — спокойная, под текст.
    Текст в книге лежит справа у нечётных страниц и слева у чётных (app/layout.py): там и просим покой."""
    who = ("the hero from the reference image and the helper character" if has_refs
           else "the hero and the helper character")
    return (f"Wide panoramic double-page spread, 2:1. The main characters ({who}) are large, clearly visible, in "
            f"action, standing or moving (never sitting at a desk), in the {hero_side(index)} half. The "
            f"{calm_side(index)} half is a calm, softly lit, uncluttered area (a quieter, softer-detail part of the "
            "same place as in the scene, such as blurred foliage, mist, rock, water or ground) with nothing important in it, "
            f"left free for text. Keep busy details on the {hero_side(index)} half.")


def scrub_name(text: str, name: str, gender: str = "boy") -> str:
    """Имя ребёнка в промты для картинок не попадает: заменяем его на «the boy / the girl»
    (кириллица в любом падеже и латиница в разных вариантах записи)."""
    if not name or len(name.strip()) < 2:
        return text
    word = "the girl" if gender == "girl" else "the boy"
    names = [re.escape(n) for n in sorted(latin_variants(name) | {name.lower()}, key=len, reverse=True)]
    cyr = re.escape(name.lower())
    # «named Aidar», «called Aidar» — слово с именем исчезает вместе с пояснением
    text = re.sub(r"(?i),?\s*\b(?:named|called)\s+(?:" + "|".join(names) + r")(?:['’]s)?\b", "", text)
    text = re.sub(r"(?i)(?<![\w])" + cyr + r"\w*", word, text)                         # кириллица, любой падеж
    pattern = re.compile(r"(?i)(?<![\w])(?:" + "|".join(names) + r")(?=['’]s\b|\b)")
    def repl(m: re.Match) -> str:
        start = m.start()
        sentence_start = start == 0 or text[:start].rstrip().endswith((".", "!", "?", ":", "\n"))
        return word[0].upper() + word[1:] if sentence_start else word
    return pattern.sub(repl, text)


def photo_instruction(profile: Profile) -> str:
    return REALISTIC_PHOTO_INSTRUCTION if profile.style == "realistic" else PHOTO_INSTRUCTION


def same_character(profile: Profile) -> str:
    return REALISTIC_SAME_CHARACTER if profile.style == "realistic" else SAME_CHARACTER


def _modest(profile: Profile) -> str:
    if not profile.islamic:
        return ""
    clause = MODEST
    if profile.gender == "girl":
        clause += " The girl wears a simple headscarf." if profile.headscarf else " The girl does not wear a headscarf."
    return clause


def _join(*parts: str) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


_DANGLING = frozenset("a an the and with of in on to by for at from or".split())


def _cut_head(text: str, room: int) -> str:
    """Режет описание по слову и убирает висящие обрывки («…carrying a»): последний кусок не должен кончаться артиклем или предлогом."""
    cut = cut_words(text, max(0, room))
    words = cut.split(" ")
    while len(words) > 1 and words[-1].lower().rstrip(".,;:") in _DANGLING:
        words.pop()
    return " ".join(words).rstrip(" ,;:—-")


def _finish(head: list[str], style_note: str, style: str | None = None, *, lead: str = "", keep: tuple[str, ...] = ()) -> str:
    """Порядок: lead (разметка кадра или название на обложке, целиком) → сцена и герои (head) → keep (короткие правила,
    которые нельзя терять: фото ребёнка, скромная одежда, спокойный фон обложки) → юридическое правило → стиль →
    палитра книги (style_note). Если всё длиннее MAX_PROMPT, режутся сцена и описания героев (head); lead, keep,
    юридическое правило, общий стиль и палитра остаются: стиль отвечает за яркий вид картинок, а палитру держат все
    страницы книги (место под неё резервируется заранее, до NOTE_MAX знаков)."""
    style = style or STYLE
    tail = _join(LEGAL_CLAUSE, style)
    note = cut_words(style_note.strip(), NOTE_MAX) if style_note and style_note.strip() else ""
    fixed = [part for part in (lead, _join(*keep), tail, note) if part]
    room = MAX_PROMPT - sum(len(part) + 1 for part in fixed) - 1
    return _join(lead, _cut_head(_join(*head), room), *fixed[1 if lead else 0:])


def _look(story: Story, profile: Profile, role: str) -> str:
    character = story.character(role)
    return scrub_name(character.look, profile.name, profile.gender) if character else ""


def world_clause(story: Story, profile: Profile, *, limit: int = WORLD_MAX, cover: bool = False) -> str:
    """Друзья выбранного мира книги (внешность архетипа из cast, роль world): одинаковые на всех страницах и на обложке.
    Мира нет — пусто, поэтому у обычных книг и старых книг промты прежние."""
    look = _look(story, profile, "world")
    if not look or story.characters("teammate"):           # команда уже описана, друзья мира её только дублируют
        return ""
    look = _cut_head(look, limit)
    if cover:
        return f"Softly behind them, the friends of the story's world, drawn the same as on every page: {look}."
    return f"Friends of the story's world may appear small and supporting, always drawn the same: {look}."


TEAM_LOOK_MAX = 110       # знаков на одного друга из команды в промте: команда из четырёх должна влезть вместе со сценой


def _team_looks(story: Story, profile: Profile) -> list[str]:
    """Лидер и остальные друзья команды: внешность каждого (без имени ребёнка), коротко. Пусто, если помощник один."""
    mates = [scrub_name(c.look, profile.name, profile.gender) for c in story.characters("teammate")]
    if not mates:
        return []
    return [_cut_head(look, TEAM_LOOK_MAX) for look in [_look(story, profile, "helper"), *mates] if look]


PERSON_PHOTO_CLAUSE = ("The adult/person in the scene looks exactly like the person in the last reference photo "
                       "(same face, hair, skin tone).")
PERSON_SHOWN = re.compile(r"\b(?:person|parent|parents|mother|mom|mum|mommy|mama|father|dad|daddy|papa|grandmother|grandma|granny|grandfather|"
                          r"grandpa|granddad|grandad|brother|sister|sibling|aunt|auntie|uncle|relative|family)\b", re.I)


def person_photo_family(story: Story) -> bool:
    """В cast есть взрослый, который рисуется по фото близкого человека (его внешность — «the person from the reference photo»)."""
    family = story.character("family")
    return bool(family) and "reference photo" in family.look.lower()


def person_in_scene(story: Story, scene: str) -> bool:
    """Близкий человек по фото показан в этом кадре: тогда фото человека уходит в картинку последним референсом."""
    return person_photo_family(story) and bool(PERSON_SHOWN.search(scene))


def cast_clause(story: Story, profile: Profile, scene: str, *, person_ref: bool = False) -> str:
    """Помощник и препятствие этой страницы (герой приходит по референсу или из hero_visual).

    Режиссёр называет героев в сцене словами "the helper" и "the obstacle": по ним видно, кто в кадре. Если в сцене
    нет ни того, ни другого (старые книги, заглушки), помощник считается присутствующим: он спутник героя на каждой странице.
    В старых книгах без cast блока нет совсем."""
    low = scene.lower()
    parts = []
    helper = _look(story, profile, "helper")
    team = _team_looks(story, profile)
    if team:                                  # помощник — команда: все друзья всегда рядом с героем и нарисованы одинаково
        parts.append(f"The helper team always stays together near the hero, all {len(team)} friends clearly visible, each drawn "
                     f"the same on every page: " + "; ".join(f"{i}) {look}" for i, look in enumerate(team, start=1)) + ".")
    elif helper and ("helper" in low or "obstacle" not in low):
        parts.append(f"The helper character, drawn the same on every page: {helper}.")
    obstacle = _look(story, profile, "obstacle")
    if obstacle and "obstacle" in low:
        parts.append(f"The obstacle in this scene: {obstacle}.")
    family = _look(story, profile, "family")
    if family and person_ref and person_in_scene(story, scene):       # человек по фото: внешность берётся с референса
        parts.append("The person from the last reference photo, calm and kind, clearly visible and drawn the same on every page.")
    elif family and FAMILY_SHOWN.search(scene):          # взрослый или родной в этом кадре (в конце книги): добрый, спокойный, виден целиком
        parts.append(f"The family member, a calm and kind adult, clearly visible and drawn the same on every page: {family}.")
    world = world_clause(story, profile)
    if world:
        parts.append(world)
    return " ".join(parts)


def cover_helper_clause(story: Story, profile: Profile) -> str:
    team = _team_looks(story, profile)
    if team:
        return (f"Right next to the hero stand all {len(team)} friends of the helper team, a little smaller than the hero, everyone "
                "clearly visible: " + "; ".join(f"{i}) {look}" for i, look in enumerate(team, start=1)) + ".")
    helper = _look(story, profile, "helper")
    if not helper:
        return ""
    return f"Right next to the hero stands the hero's helper, a little smaller than the hero, both clearly visible: {helper}."


def build_cover_prompt(story: Story, profile: Profile, *, photo_ref: bool, title_in_image: bool = False,
                       person_ref: bool = False) -> str:
    """Обложка (квадрат 1:1): герой крупным планом, рядом с ним помощник, за ними мир книги.

    title_in_image=True: модель рисует название книги крупными буквами внутри картинки (имя ребёнка в названии
    остаётся: это единственное место, где оно попадает в сервис картинок), фон красивый, но не перегруженный.
    Если места мало, режутся описание мира и героя (они в конце head); помощник рядом с героем остаётся."""
    world = cut_words(scrub_name(story.pages[0].scene, profile.name, profile.gender), COVER_WORLD_MAX)
    hero = scrub_name(story.hero_visual, profile.name, profile.gender)
    friends = world_clause(story, profile, limit=COVER_FRIENDS_MAX, cover=True)
    parent = PERSON_PHOTO_CLAUSE if person_ref and person_in_scene(story, story.pages[0].scene) else ""
    helper = cover_helper_clause(story, profile)
    if title_in_image:
        framing = "The main hero, smiling warmly and shown from the knees up, fills the lower centre of the cover."
        head = [framing, helper, friends, f"The story's world is softly behind: {world}", hero]
        keep = (photo_instruction(profile) if photo_ref else "", parent, _modest(profile), COVER_CALM)
        return _finish(head, story.style_note, style_block(profile, cover=True),
                       lead=COVER_TITLE_CLAUSE.format(title=story.title.strip()), keep=keep)
    framing = "Book cover illustration: a close-up portrait of the main hero smiling warmly."
    return _finish([framing, helper, friends, f"The story's world is behind: {world}", hero], story.style_note,
                   style_block(profile), keep=(photo_instruction(profile) if photo_ref else "", parent, _modest(profile)))


SHEET_LEAD = ("Character model sheet on a plain, seamless pure-white studio background, like a catalogue cut-out: nothing "
              "behind or under the characters, no landscape, no sky, no plants, no ground texture, only a faint soft "
              "shadow under their feet. The characters stand full-body and large, side by side, facing the viewer in "
              "friendly neutral poses, at their true relative sizes.")


def has_sheet_characters(story: Story) -> bool:
    """Лист нужен, если в книге есть кто-то кроме героя-ребёнка: помощник, друзья команды или взрослый."""
    return any(c.role in ("helper", "teammate") or (c.role == "family" and "reference photo" not in c.look.lower())
               for c in story.cast)


def build_sheet_prompt(story: Story, profile: Profile) -> str:
    """Лист героев: помощник, друзья и взрослый на ЧИСТО БЕЛОМ фоне, рисуется без референсов (с фото модель тянет в кадр
    пейзаж). Он не попадает в книгу: это образец внешности существ для обложки и страниц, без места действия, поэтому
    страницы не копируют друг друга. Ребёнка здесь нет: его лицо берётся из фото."""
    helper = _look(story, profile, "helper")
    looks = [f"Helper: {helper}"] if helper else []
    looks += [f"Friend: {_cut_head(c.look, TEAM_LOOK_MAX)}" for c in story.characters("teammate")]
    family = "" if person_photo_family(story) else _look(story, profile, "family")       # человека по фото на листе нет: людей на листе не рисуем
    if family:
        looks.append(f"Family member (calm, kind adult): {family}")
    return _finish(looks, "", style_block(profile), lead=SHEET_LEAD, keep=(_modest(profile),))


def build_page_prompt(story: Story, profile: Profile, index: int, *, has_refs: bool, person_ref: bool = False) -> str:
    """Страница index (1..PAGES): широкая иллюстрация на весь разворот (2:1). Композиция: герои на одной половине,
    другая спокойная и пустая под текст (справа у нечётных страниц, слева у чётных). Герой приходит по референсу
    (без них hero_visual вставляется дословно), помощник и препятствие страницы описаны текстом из cast."""
    raw_scene = story.pages[index - 1].scene
    scene = scrub_name(raw_scene, profile.name, profile.gender)
    if has_refs:
        hero = same_character(profile)
    else:
        hero = scrub_name(story.hero_visual, profile.name, profile.gender)
    parent = PERSON_PHOTO_CLAUSE if person_ref and person_in_scene(story, raw_scene) else ""
    return _finish([scene, cast_clause(story, profile, raw_scene, person_ref=person_ref), hero], story.style_note,
                   style_block(profile), lead=page_layout_clause(index, has_refs=has_refs), keep=(parent, _modest(profile)))
