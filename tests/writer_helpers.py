"""Помощники тестов писателя: правильные ответы режиссёра, автора, редактора и корректора для профиля и запись вызовов.

Модель текста в тестах всегда поддельная: ответы приходят из списка или из функции, сеть не нужна.
"""
from __future__ import annotations

import json
import random
import re

from app.providers.base import TextProvider
from app.providers.text_mock import HELPERS, build_mock_story
from app.writer import Seeds, pick_seeds, team_size_needed


def stage_of(system: str) -> str:
    """Какой шаг конвейера задаёт эта системная инструкция."""
    head = system[:120].lower()
    if "понятности" in head:
        return "comprehension"
    if "режиссёр" in head:
        return "planner"
    if "автор текстов" in head:
        return "author"
    if "редактор" in head:
        return "editor"
    if "корректор" in head:
        return "proof"
    return "other"


def seeds_for(profile, seed: int = 1) -> Seeds:
    return pick_seeds(profile, random.Random(seed))


TEAM_LOOKS = ("a small panda cub in a bright green scarf", "a tiny frog with a sunny yellow vest",
              "a fluffy hedgehog with a pink bow", "a little blue owlet in orange boots")
TEAM_KINDS = ("панда", "лягушонок", "ёжик", "совёнок")


def team_size_for(profile, team: int | None) -> int:
    """Сколько друзей в команде: сколько попросили, иначе сколько требует мир (0 — помощник один)."""
    return team if team is not None else team_size_needed(profile)


def teammates_for(profile, seeds: Seeds, team: int | None = None) -> list[tuple[str, str, str]]:
    """Друзья команды без лидера: (имя из зёрен, кто, внешность)."""
    size = team_size_for(profile, team)
    return [(name, TEAM_KINDS[i], TEAM_LOOKS[i]) for i, name in enumerate(seeds.team_names[:max(0, size - 1)])]


def plan_dict(profile, seeds: Seeds | None = None, team: int | None = None) -> dict:
    """Верный план для профиля: помощник и рефрен как в заглушке, сцены — её сцены. team: сколько друзей в команде
    (по умолчанию как требуют мир-команда или просьба родителей; иначе помощник один)."""
    seeds = seeds or seeds_for(profile)
    story = build_mock_story(profile)
    helper = story["cast"][1]
    obstacle = story["cast"][2]
    mates = teammates_for(profile, seeds, team)
    briefs = [p["scene"] for p in story["pages"]]
    if mates:                                                       # на каждом кадре вся команда рядом с героем
        briefs = [(b if len(b) <= 262 else b[:262].rsplit(" ", 1)[0]) + " The helper team is close to the hero." for b in briefs]
    plan = {
        "framework": "fear" if profile.topic == "life_lesson" else seeds.framework,
        "logline": "Ребёнок несёт бабушке лепёшки и с другом переходит ручей.",
        "meaning": "Вместе с другом можно пройти любой трудный путь.",
        "retell": "Ребёнок несёт бабушке лепёшки, но ручей не пускает; вместе с помощником он находит путь, и бабушка рада.",
        "premise": "Ребёнок несёт бабушке лепёшки, но ручей без мостика мешает; он сам придумывает переправу.",
        "want": "донести лепёшки бабушке",
        "trait": "находчивый",
        "tool": "красный шнурок на корзинке",
        "stakes": "если не перейдёт ручей, то бабушка не дождётся лепёшек",
        "helper": {"name": seeds.helper_name.name, "trait": "подбадривает и шутит", "kind": seeds.helper_type.ru},
        "obstacle": "широкий ручей без мостика",
        "attempts": [
            {"action": "у ручья: прыгнуть по камням", "fail_reason": "камень скользкий"},
            {"action": "на берегу: перейти вброд на спине помощника", "fail_reason": "вода слишком глубокая"},
            {"action": "у корня: помочь палкой и красным шнурком дотянуться до другого берега", "fail_reason": ""},
        ],
        "solution": "герой сам протягивает шнурок через ручей, и они переходят по нему вместе",
        "plant_payoff": {"plant": "стр. 1: красный шнурок на ручке корзинки", "payoff": "стр. 7: шнурок слегка помог перейти"},
        "refrain": {"text": story["refrain"], "break": "на третий раз обрывается словом «стоп»"},
        "character_bible": {"hero": story["hero_visual"], "helper": helper["look"], "obstacle": obstacle["look"]},
        "style_note": story["style_note"],
        "image_brief": briefs,
    }
    if mates:
        plan["helper"]["team"] = [{"name": seeds.helper_name.name, "kind": seeds.helper_type.ru, "trait": "ведёт друзей"}] + [
            {"name": name, "kind": kind, "trait": "коротко шутит", "look": look} for name, kind, look in mates]
    return plan


def author_dict(profile, seeds: Seeds | None = None, team: int | None = None) -> dict:
    """Верный ответ автора: тексты заглушки, в которых имя помощника заменено на имя из зёрен; у команды каждый друг
    назван хотя бы раз (короткая фраза «Рядом Имя.» на страницах 2, 5 и 7)."""
    seeds = seeds or seeds_for(profile)
    story = build_mock_story(profile)
    mock_name = HELPERS[profile.place][4]

    def fix(text: str) -> str:
        return re.sub(rf"\b{mock_name}\b", seeds.helper_name.name, text)

    pages = [fix(p["text"]) for p in story["pages"]]
    for index, (name, _, _) in zip((1, 4, 6), teammates_for(profile, seeds, team)):
        pages[index] += f" Рядом {name}."
    return {"title": fix(story["title"]), "pages": [{"text": t} for t in pages], "moral": story["moral"], "wish": story["wish"]}


def dump(data) -> str:
    return json.dumps(data, ensure_ascii=False)


NO_FIXES = dump({"fixes": []})
CLEAR = {"retell": [f"Страница {i}: герой идёт дальше." for i in range(1, 9)], "problems": [],
         "summary": "несли лепёшки, перешли ручей, бабушка рада"}


def seeded(provider, seed: int = 1):
    """Зёрна случайны; тестовая модель получает тот же random.Random(seed), по которому составлен план."""
    provider.rng = random.Random(seed)
    return provider


def plan_and_text(profile, seed: int = 1) -> tuple[str, str]:
    """Верные ответы режиссёра и автора для профиля (строки JSON)."""
    seeds = seeds_for(profile, seed)
    return dump(plan_dict(profile, seeds)), dump(author_dict(profile, seeds))


class ScriptedPipeline(TextProvider):
    """Поддельная модель текста: отвечает по шагам конвейера и записывает все вызовы.

    replies — готовые ответы по шагам: {"planner": [...], "author": [...], "editor": [...], "proof": [...]}
    (по порядку вызовов; последний повторяется; None значит «ответь верно»); чего нет в replies, то отвечает верно
    (план, автор, пустые правки, корректор без изменений)."""

    name = "scripted"

    def __init__(self, profile, replies: dict | None = None, *, polish: bool = False, seed: int = 1):
        self.profile = profile
        self.rng = random.Random(seed)
        self.seeds = seeds_for(profile, seed)
        self.polish = polish
        self.replies = {k: list(v) for k, v in (replies or {}).items()}
        self.calls: list[dict] = []

    def default_reply(self, stage: str) -> str:
        if stage == "planner":
            return dump(plan_dict(self.profile, self.seeds))
        if stage == "author":
            return dump(author_dict(self.profile, self.seeds))
        if stage == "editor":
            return dump({"fixes": []})
        if stage == "comprehension":
            return dump(CLEAR)
        story = author_dict(self.profile, self.seeds)
        return dump(story)                     # корректор: тексты без изменений

    async def _complete(self, system, messages, model=None):
        stage = stage_of(system)
        self.calls.append({"stage": stage, "system": system, "messages": list(messages), "model": model})
        queue = self.replies.get(stage)
        if queue:
            item = queue.pop(0) if len(queue) > 1 else queue[0]
            if item is not None:
                return item
        return self.default_reply(stage)

    @property
    def stages(self) -> list[str]:
        return [c["stage"] for c in self.calls]

    def calls_of(self, stage: str) -> list[dict]:
        return [c for c in self.calls if c["stage"] == stage]
