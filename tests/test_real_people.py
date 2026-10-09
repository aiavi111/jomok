"""Реальные знаменитости (футболисты и т. п.) в книгу не попадают: ни именем, ни обликом."""
import pytest

from app import prompts
from app.simple_writer import system_prompt
from app.writer import brand_hits

from .conftest import SAMPLE
from app.profile import Profile


@pytest.mark.parametrize("text", ["Артём играл как Роналду.", "Он болеет за Месси и Мбаппе.", "Неймар забил гол.", "Cristiano Ronaldo scores",
                                  "как Зидан", "Бекхэм бьёт штрафной"])
def test_famous_people_are_caught(text):
    assert brand_hits(text)


@pytest.mark.parametrize("text", ["Он стал чемпионом двора.", "Мессия пришёл в мир.", "Рональд Макдональд", "Мяч попал в штангу."])
def test_ordinary_words_are_not_caught(text):
    assert not [h for h in brand_hits(text) if h in ("месси", "роналд", "мбапп")]


def test_writer_and_artist_are_told_not_to_use_real_people():
    assert "реальных знаменитостей" in system_prompt(Profile.from_payload(SAMPLE))
    assert "real celebrities" in prompts.LEGAL_CLAUSE
