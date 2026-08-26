"""Сторож: мягкая ступень стоп-крана (SOFT_DERISK) не подаётся как защита/снижение риска.

**Решение владельца** (`own-rnd-killswitch-soft-tier-meaning`, ответ 2026-08-19T21:51:56Z,
вариант **Б1**; запись — [ADR-089](../../docs/decisions/ADR-089-owner-decisions-batch-2026-08-19.md)
раздел 3). Замер на 852 днях истории: SOFT_DERISK на портфеле с ровными весами не меняет ни
одного числа — она запрещает НАРАЩИВАТЬ, а не снижает уже открытую экспозицию. До этой правки
публичные страницы (`faq.astro`, `strategies/{balanced,aggressive,conservative}.astro`)
использовали глагол «де-риск»/«снижает риск» и называли kill switch «последней линией защиты»
без уточнения, что это верно только для HARD-уровня (all-cash), а не для SOFT.

**Что этот тест проверяет — и чего НЕ проверяет.** Он ловит ВОЗВРАТ конкретных фраз, снятых
этой правкой — не общий запрет слов «de-risk»/«защита» (тег SOFT_DERISK как имя тира и
нейтральные табличные подписи вида «De-risk: halt new entries & increases, no liquidation»
остаются — они называют состояние, а не декларируют эффект). RiskPolicy, kill_switch.py,
пороги 5%/10% — НЕ трогаются и НЕ проверяются здесь (инв. #16: это правка текста, не гейта).

Fail-CLOSED: список сканируемых файлов — те, где фразы РЕАЛЬНО были найдены при разборе
карточки `agent-myagkaya-stupen-perestat-nazyvat-zaschitoi`; список статичен и мал специально
(в отличие от свободного grep по всему landing/, который дал бы много случайных совпадений
на нейтральных фразах) — новое место с тем же дефектом ловится тем же поиском вручную при
следующем аудите текста, а этот сторож держит РЕГРЕССИЮ на уже найденных местах.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

SCANNED_FILES = [
    REPO_ROOT / "landing" / "src" / "pages" / "faq.astro",
    REPO_ROOT / "landing" / "src" / "pages" / "strategies" / "balanced.astro",
    REPO_ROOT / "landing" / "src" / "pages" / "strategies" / "aggressive.astro",
    REPO_ROOT / "landing" / "src" / "pages" / "strategies" / "conservative.astro",
]

# Фразы, которые ЗАЯВЛЯЮТ, что SOFT-ступень снижает риск/экспозицию, а не просто запрещает
# наращивание — ровно то, что решение Б1 велело перестать говорить.
BANNED_PHRASES = [
    "the desk de-risks",
    "деск снижает риск",
    "the kill switch is the last line of defense",
    "аварийный стоп — последняя линия защиты",
    "the kill switch limits further exposure",
    "аварийный стоп ограничивает дальнейшую экспозицию",
]


def find_overclaims(text: str) -> list[str]:
    lowered = text.lower()
    return [p for p in BANNED_PHRASES if p.lower() in lowered]


def test_positive_control_catches_the_banned_phrase(tmp_path: Path) -> None:
    """Авария, которую правка убрала: воспроизвести и убедиться, что сканер её ловит."""
    bad = tmp_path / "regressed.astro"
    bad.write_text(
        "<p>At ≥5% (SOFT) the desk de-risks: it halts new entries.</p>",
        encoding="utf-8",
    )
    found = find_overclaims(bad.read_text(encoding="utf-8"))
    assert found == ["the desk de-risks"], found


def test_negative_control_clean_text_is_silent() -> None:
    """Отрицательный контроль: верная формулировка не краснеет."""
    clean = (
        "At ≥5% (SOFT) the desk halts new entries and any position increase "
        "— this blocks further growth, it does not reduce exposure already open."
    )
    assert find_overclaims(clean) == []


@pytest.mark.parametrize("path", SCANNED_FILES, ids=lambda p: p.name)
def test_live_page_has_no_soft_tier_overclaim(path: Path) -> None:
    """Храповик на живых страницах — тот самый красный, ради которого всё писалось."""
    if not path.exists():
        pytest.skip(f"страницы нет в этом дереве: {path}")
    found = find_overclaims(path.read_text(encoding="utf-8"))
    assert found == [], (
        f"{path.relative_to(REPO_ROOT)} снова описывает SOFT_DERISK как снижение риска/защиту: "
        f"{found} — решение владельца Б1 (ADR-089 §3): формулировка должна называть только "
        "запрет наращивать, не снижение экспозиции."
    )
