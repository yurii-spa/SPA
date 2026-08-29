"""Заявка об уровне доказательности не может обгонять то, что мы реально сделали.

# LLM_FORBIDDEN

Канон уровней — ``docs/37_apy_realism_and_evidence_standard.md`` (ADR-YL-009),
и он сам запрещает себя переопределять: «This is the CANONICAL definition of
evidence levels L0–L6. Other docs use the tags; none re-defines them.»

По этому канону:

* **L4** — «исполнено реальным, хоть и небольшим, капиталом; наблюдались
  проскальзывание, газ, наполнение заявки»;
* **L5** — исполнено значимым капиталом через полный вход/выход;
* **L6** — пережито несколько рыночных режимов на живом капитале, включая стресс.

**Реального капитала не было ни разу.** Система на paper-стадии, внешний капитал
закрыт до legal-clearance (инвариант 8), а сам документ 37 называет наш paper-трек
эталоном **L3**. Значит любое L4+ в коде — заявка о том, чего не было.

Слой аналитиков ``investment_os`` при этом ПРЯМО ссылается на канон
(``harness.py``: «Evidence ladder (docs/37)»), то есть это не своя шкала, а
неверное применение общей: уровни там используются как «насколько живой ИСТОЧНИК»,
а канон измеряет «насколько далеко это ИСПОЛНЕНО». Разные оси, одни метки.

Сторож не чинит слой — он не даёт классу расти и держит премиссу проверяемой.
Разбор и предлагаемое соответствие — ``docs/apy_evidence_enforcement.md``.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DOC_37 = _ROOT / "docs" / "37_apy_realism_and_evidence_standard.md"

HIGH_LEVELS = {"L4", "L5", "L6"}

# Перепись на 2026-08-29. Ключ — (файл, уровень), БЕЗ номера строки: якорь на
# `файл:строка` ломается от любой вставки выше и уже стоил проекту цикла.
# Список может ТОЛЬКО СОКРАЩАТЬСЯ. Пополнять его, чтобы погасить падение,
# запрещено — это ровно то, ради чего сторож написан.
# ПУСТО с 2026-08-29. Перепись была 12 заявок в 9 файлах; все понижены до честных
# уровней (полный мандат владельца): живые измерения цикла → L2, бэктест → L2
# (канон дословно: «a backtest is not live-tested… never L4+»), наш paper-трек → L3
# (канон называет его ЭТАЛОНОМ L3, а не L6).
#
# Список задуман сокращающимся, и он сократился до нуля. Пока система не исполняла
# реальный капитал, ЛЮБОЕ имя здесь — регресс, а не «известное состояние».
KNOWN_HIGH_CLAIMS: dict[str, int] = {}

def _level_of(raw: str) -> str | None:
    """«L4» и «L4 — пояснение» это заявка; «L40», «L4x» — нет."""
    s = raw.strip()
    if s in HIGH_LEVELS:
        return s
    if len(s) > 2 and s[:2] in HIGH_LEVELS and s[2:3] in (" ", "-", "—", ":"):
        return s[:2]
    return None


def _claims_in(tree: ast.AST) -> list[tuple[int, str]]:
    """Только ТОЧКИ НАЗНАЧЕНИЯ уровня, а не всякое вхождение строки «L4».

    Иначе сторож ловит чужие пространства имён: в рое (``api/routers/swarm.py``)
    «L4» — это НОМЕР СЛОЯ, в ``harness.py`` — элемент кортежа допустимых значений,
    в ``draft_prep.py`` — член множества для валидации. Ни одно из них не является
    утверждением о доказанности, и сторож, который их считает, кричит не о том.
    """
    out: list[tuple[int, str]] = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "evidence" and len(n.args) >= 2
                and isinstance(n.args[1], ast.Constant)
                and isinstance(n.args[1].value, str)):
            lvl = _level_of(n.args[1].value)
            if lvl:
                out.append((n.lineno, lvl))
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if (isinstance(k, ast.Constant) and k.value == "evidence_level"
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                    lvl = _level_of(v.value)
                    if lvl:
                        out.append((k.lineno, lvl))
    return out


def _census() -> dict[str, int]:
    found: dict[str, int] = {}
    for f in (_ROOT / "spa_core").rglob("*.py"):
        if "/tests/" in str(f):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — нечитаемый файл не наша тема
            continue
        hits = _claims_in(tree)
        if hits:
            found[str(f.relative_to(_ROOT))] = len(hits)
    return found


def test_the_premise_still_holds_in_the_canon():
    """Если канон переопределят, вывод сторожа станет ложным — заметить обязан он сам."""
    text = _DOC_37.read_text(encoding="utf-8")
    assert "CANONICAL" in text, "документ 37 перестал объявлять себя каноном"
    l4 = [ln for ln in text.splitlines() if ln.strip().startswith("| **L4**")]
    assert len(l4) == 1, "строка L4 в каноне не найдена или задвоена"
    assert "real but small capital" in l4[0], (
        "L4 в каноне больше не означает исполнение реальным капиталом — "
        "перепроверь docs/apy_evidence_enforcement.md, вывод сторожа мог устареть")


def test_no_new_file_claims_l4_or_above():
    census = _census()
    new = sorted(set(census) - set(KNOWN_HIGH_CLAIMS))  # KNOWN пуст ⇒ любое имя новое
    assert not new, (
        f"новые заявки L4+ в {new}. L4 по канону — исполнение РЕАЛЬНЫМ капиталом, "
        "которого не было ни разу. Для наблюдённого источника уровень — L2. "
        "В KNOWN_HIGH_CLAIMS НЕ добавлять.")


def test_nothing_in_the_codebase_claims_l4_or_above():
    """Полный запрет, а не храповик: с 29.08 таких заявок НОЛЬ.

    Тест перевёрнут намеренно — раньше он сторожил, чтобы известный список
    не рос. Список опустел, и охранять стало нечего, кроме самого правила:
    пока система не исполняла реальный капитал, L4+ не вправе заявить никто.
    """
    census = _census()
    assert census == {}, (
        f"заявки L4+ вернулись: {census}. L4 по канону — исполнение РЕАЛЬНЫМ "
        "капиталом, которого не было ни разу. Живое измерение цикла — L2, "
        "наш paper-трек — L3, бэктест — L2 (docs/apy_evidence_enforcement.md).")


def test_the_yield_surface_is_already_clean():
    """Единственная поверхность, где уровень стоял рядом с ДОХОДНОСТЬЮ, — починена."""
    from spa_core.investment_os.agents.stablecoin_yield import (
        _evidence_level_for_observed_feed,
    )
    assert _evidence_level_for_observed_feed("T1") == "L2"
    assert _evidence_level_for_observed_feed("T2") == "L2"
    src = _ROOT / "spa_core/investment_os/agents/stablecoin_yield.py"
    assert str(src.relative_to(_ROOT)) not in _census()


def test_detector_catches_a_planted_claim_and_ignores_other_namespaces():
    """Положительный контроль в обе стороны — иначе сторож мог бы не считать ничего."""
    planted = ast.parse('self.evidence(x, "L4", "data/whatever.json")\n')
    assert _claims_in(planted) == [(1, "L4")]

    prose = ast.parse('LAYERS = ("L1", "L4")\nVALID = {"L4", "L5"}\nswarm_layer = "L4"\n')
    assert _claims_in(prose) == [], "чужое пространство имён не должно считаться заявкой"

    with_note = ast.parse('d = {"evidence_level": "L4 — real historical series"}\n')
    assert _claims_in(with_note) == [(1, "L4")]


@pytest.mark.parametrize("raw,expect", [
    ("L4", "L4"), ("L5", "L5"), ("L6", "L6"),
    ("L4 — пояснение", "L4"), ("L4: x", "L4"), ("L4-x", "L4"),
    ("L2", None), ("L3", None), ("L40", None), ("L4x", None), ("", None),
])
def test_level_parsing_is_exact(raw, expect):
    assert _level_of(raw) == expect
