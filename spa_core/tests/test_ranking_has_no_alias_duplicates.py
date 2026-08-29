"""Протокол не может стоять в ранжировании дважды — под ключом и под слагом.

# LLM_FORBIDDEN

Найдено 2026-08-29 при разборе собственного «не измерено». В `data/apy_ranking.json`
33 строки, но только **30 различных протоколов**: три слага DeFiLlama лежат рядом
со своими каноническими ключами.

| Слаг | Ведёт на (tier_map._ALIASES) | Число слага | Число канона |
|---|---|---|---|
| `pendle-pt` | `pendle_pt_susde` | **8.0 %**, `unchecked` | 4.7026 %, `live` |
| `morpho-blue-steakhouse` | `morpho_steakhouse` | 4.0739 %, `unchecked` | 4.0739 %, `live` |
| `aave-v3-arbitrum` | `aave_arbitrum` | 2.2855 %, `unchecked` | 2.2855 %, `live` |

Опаснее всего первая строка: **один протокол соревнуется сам с собой, и побеждает
ненаблюдённый литерал** — 8.0 % против наблюдённых 4.70 %. Сортировка по доходности
ставит выдуманное число выше настоящего.

Побочно: любой счётчик «сколько протоколов мы отслеживаем» по этому файлу завышает
на три.

Логика проверки работает на фикстуре всегда; живой файл — вторым слоем (в worktree
и CI `data/` нет по построению).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.adapters.tier_map import _ALIASES

_RANKING = Path(__file__).resolve().parents[2] / "data" / "apy_ranking.json"

# Известные дубли на 2026-08-29. Список может ТОЛЬКО СОКРАЩАТЬСЯ: чинится
# производитель ранжирования (он обязан разрешать слаг в канонический ключ
# ДО записи строки), а не этот список.
KNOWN_ALIAS_DUPLICATES = {"pendle-pt", "morpho-blue-steakhouse", "aave-v3-arbitrum"}


def _duplicates(rows: list) -> dict:
    """{слаг: канонический ключ} для слагов, чей канон ТОЖЕ в ранжировании."""
    names = {r["protocol"] for r in rows if isinstance(r, dict) and r.get("protocol")}
    out = {}
    for name in sorted(names):
        target = _ALIASES.get(name)
        if not target:
            continue
        canon = target[0]
        if canon != name and canon in names:
            out[name] = canon
    return out


def test_logic_catches_a_planted_duplicate():
    """Положительный контроль: без него проверка могла бы не сравнивать ничего."""
    slug, canon = "pendle-pt", _ALIASES["pendle-pt"][0]
    assert _duplicates([{"protocol": slug}, {"protocol": canon}]) == {slug: canon}


def test_logic_is_quiet_when_only_one_of_the_pair_is_present():
    """Обратный контроль: слаг САМ ПО СЕБЕ — не дубль, а просто имя из фида."""
    slug = "pendle-pt"
    assert _duplicates([{"protocol": slug}]) == {}
    assert _duplicates([{"protocol": _ALIASES[slug][0]}]) == {}


def test_logic_ignores_names_that_are_not_aliases():
    assert _duplicates([{"protocol": "aave_v3"}, {"protocol": "compound_v3"}]) == {}


def test_no_new_alias_duplicate_in_the_live_ranking():
    if not _RANKING.exists():
        pytest.skip("data/ отсутствует (worktree/CI) — логика проверена на фикстуре")
    # Файл переписывается циклом каждые несколько минут: прочитать его можно
    # в середине записи. Это не находка ЭТОГО сторожа (его предмет — дубли),
    # и красный вердикт был бы ложным. Пропуск с названной причиной; здоровье
    # файла сторожат другие проверки. Наблюдалось 29.08: два прогона подряд
    # красные, третий зелёный на том же коде.
    try:
        doc = json.loads(_RANKING.read_text(encoding="utf-8"))
        rows = doc.get("by_apy")
    except (json.JSONDecodeError, OSError) as exc:
        pytest.skip(f"ранжирование нечитаемо в момент прогона ({exc}) — предмет проверки не в этом")
    if not isinstance(rows, list) or len(rows) < 20:
        pytest.skip(f"ранжирование неполно ({len(rows) if isinstance(rows, list) else '?'} строк) "
                    "— вероятно, читается в момент перезаписи")
    dups = _duplicates(rows)
    new = sorted(set(dups) - KNOWN_ALIAS_DUPLICATES)
    assert not new, (
        f"новый дубль в ранжировании: { {s: dups[s] for s in new} }. Производитель "
        "обязан разрешать слаг в канонический ключ ДО записи строки, иначе протокол "
        "соревнуется сам с собой.")
    # СОКРАЩЕНИЯ здесь НЕ требуем — намеренно, и это исправление собственной
    # ошибки (29.08). Ранжирование перегенерируется, и в разных деревьях лежат
    # РАЗНЫЕ его версии: в worktree — замороженный снимок с origin, в проде —
    # живой. Требование «список обязан сокращаться» давало красный вердикт
    # в одном дереве и зелёный в другом на ОДНОМ коде: вердикт решало окружение,
    # а не предмет. Храповик уместен там, где предмет стабилен (код), а не над
    # артефактом, который переписывается каждые несколько минут.
    #
    # Поэтому живой слой отвечает на ОДИН вопрос: не появилось ли НОВОГО дубля.


def test_the_dangerous_one_is_still_the_pendle_pair():
    """Не «какой-нибудь» дубль: у этого две РАЗНЫЕ доходности, и врёт бо́льшая."""
    if not _RANKING.exists():
        pytest.skip("data/ отсутствует (worktree/CI)")
    rows = {r["protocol"]: r for r in json.loads(_RANKING.read_text(encoding="utf-8"))["by_apy"]}
    slug, canon = "pendle-pt", _ALIASES["pendle-pt"][0]
    if slug not in rows or canon not in rows:
        pytest.skip("пара распалась — перепроверь замер")
    assert rows[slug]["apy_source"] != "live", "слаг вдруг стал наблюдаемым — перепроверь"
    assert rows[canon]["apy_source"] == "live"
    assert rows[slug]["apy_pct"] > rows[canon]["apy_pct"], (
        "литерал перестал быть выше наблюдения — находка изменилась, обнови разбор")
