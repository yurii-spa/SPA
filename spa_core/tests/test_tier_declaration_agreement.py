"""Тир объявляется в ОДНОМ месте — сторож правила §2 из docs/tier_criteria.md.

# LLM_FORBIDDEN

Тир задаёт потолок концентрации (40 % против 20 %) и участвует в совокупных
потолках, поэтому второе объявление тира — это второй потолок, живущий рядом
с настоящим и расходящийся с ним молча.

Ровно эта болезнь уже лечилась: докстрока ``spa_core/adapters/tier_map.py``
описывает, как тир вёлся руками продублированными словарями в десятке модулей.
Классы адаптеров — последний невылеченный экземпляр того же класса, и на
2026-08-29 ровно один из них выигрывает у канона на денежном пути.

Тест НЕ читает живой ``data/``: только код и его таблицы.
"""
from __future__ import annotations

import pytest

from spa_core.adapters import ADAPTER_REGISTRY
from spa_core.risk.protocol_risk_map import PROTOCOL_RISK_SCORES, TIER_BANDS

# Известное расхождение класса с каноном по ТИРУ, названное поимённо.
# `morpho_steakhouse`: класс объявляет TIER="T1"/T1_CAP=0.40, канон — T2 (0.30),
# и канон исполняет решение владельца ADR-070 п.6 («один vault — один риск»).
# Класс это решение не получил. Карточка: owner-decision-tier-steakhouse-2026-08-29.
#
# Список может ТОЛЬКО СОКРАЩАТЬСЯ. Пополнить его, чтобы погасить падение, —
# запрещено: это ровно то, ради чего сторож написан.
KNOWN_TIER_DISAGREEMENT = {"morpho_steakhouse"}

# Классы, чья СОБСТВЕННАЯ оценка попадает в другую полосу, чем их же TIER
# (§3.3 docs/tier_criteria.md). Денег не касается — RISK_SCORE класса на
# денежном пути никем не читается, — но это довод за единственный источник.
KNOWN_SELF_CONTRADICTION = {
    "aave_v3_optimism", "aave_v3_polygon", "compound_v3",
    "extra_finance_base", "moonwell_base", "spark_susds",
}


def _band_of(score: float) -> str | None:
    for tier, (lo, hi) in TIER_BANDS.items():
        if (lo is None or score >= lo) and (hi is None or score <= hi):
            return tier
    return None


def _rows():
    """(протокол, tier класса, score класса, tier реестра, запись канона)."""
    out = []
    for entry in ADAPTER_REGISTRY:
        try:
            proto, reg_tier, cls = entry[0], entry[1], entry[2]
        except Exception:  # noqa: BLE001 — кривая строка реестра
            continue
        auth = PROTOCOL_RISK_SCORES.get(proto)
        if auth is None:
            continue
        out.append((proto, getattr(cls, "TIER", None), getattr(cls, "RISK_SCORE", None),
                    reg_tier, auth))
    return out


def test_authoritative_table_covers_every_adapter():
    """Без этого вся сверка ниже была бы вакуумной: сравнивать не с чем."""
    registry = {e[0] for e in ADAPTER_REGISTRY}
    missing = sorted(registry - set(PROTOCOL_RISK_SCORES))
    assert not missing, (
        f"у {len(missing)} адаптеров нет записи в PROTOCOL_RISK_SCORES: {missing}. "
        "Тир без обоснования — это тир, назначенный дефолтом.")
    assert len(registry) >= 30, f"реестр внезапно сжался до {len(registry)} — сверка ослабла"


def test_registry_tier_never_disagrees_with_the_canon():
    """Реестр — производное объявление и обязано совпадать с каноном."""
    bad = [(p, rt, a["tier"]) for p, _, _, rt, a in _rows()
           if str(rt).upper() != a["tier"]]
    assert not bad, f"реестр разошёлся с PROTOCOL_RISK_SCORES: {bad}"


def test_no_new_class_disagrees_with_the_canon_on_tier():
    """ТИР класса доходит до денег через снимок оркестратора — здесь допуск нулевой."""
    bad = {p for p, ct, _, _, a in _rows()
           if ct is not None and str(ct).upper() != a["tier"]}
    new = sorted(bad - KNOWN_TIER_DISAGREEMENT)
    assert not new, (
        f"новое расхождение класса с каноном по ТИРУ: {new}. Тир объявляется в "
        "PROTOCOL_RISK_SCORES и только там (docs/tier_criteria.md §2); класс обязан "
        "его читать, а не повторять. В список известных НЕ добавлять.")
    fixed = sorted(KNOWN_TIER_DISAGREEMENT - bad)
    assert not fixed, (
        f"расхождение починено для {fixed} — убери его из KNOWN_TIER_DISAGREEMENT. "
        "Список сокращается вместе с починкой, иначе он перестаёт что-либо значить.")


def test_the_known_disagreement_is_still_the_money_path_one():
    """Именно этот протокол, а не «какой-нибудь»: у него держится 15 % книги."""
    rows = {p: (ct, a) for p, ct, _, _, a in _rows()}
    ct, auth = rows["morpho_steakhouse"]
    assert str(ct).upper() == "T1" and auth["tier"] == "T2"
    assert "ADR-070" in str(auth.get("note", "")), \
        "обоснование канона потеряло ссылку на решение владельца"


def test_no_new_class_contradicts_its_own_tier_band():
    """Оценка класса и тир класса обязаны лежать в одной полосе."""
    bad = {p for p, ct, cs, _, _ in _rows()
           if ct is not None and isinstance(cs, (int, float))
           and _band_of(float(cs)) is not None
           and _band_of(float(cs)) != str(ct).upper()}
    new = sorted(bad - KNOWN_SELF_CONTRADICTION)
    assert not new, (
        f"класс противоречит сам себе (оценка в одной полосе, TIER в другой): {new}")


def test_class_score_is_not_read_on_the_money_path():
    """Замер, на котором держится «31 расхождение — не авария».

    Если аллокатор когда-нибудь начнёт читать ``RISK_SCORE`` класса, вывод §3.2
    станет ложным, а тридцать одно расхождение — денежным. Тест обязан это заметить.
    """
    import ast
    from pathlib import Path

    src = Path(__import__("spa_core.allocator.allocator", fromlist=["x"]).__file__)
    tree = ast.parse(src.read_text(encoding="utf-8"))
    # Ищем ОБРАЩЕНИЕ к атрибуту, а не подстроку: в модуле есть константа
    # _RISK_SCORES_PATH, и текстовый поиск краснел на имени файла — та же
    # ошибка «сторож не отличает код от прозы», что и в аудиторе.
    reads = [n for n in ast.walk(tree)
             if isinstance(n, ast.Attribute) and n.attr == "RISK_SCORE"]
    # Имя атрибута — ВТОРОЙ аргумент getattr, не последний: у трёхаргументной
    # формы getattr(x, "RISK_SCORE", None) последний это значение по умолчанию.
    # Проверка на args[-1] пропускала ровно её — поймано мутацией M3.
    getattrs = [n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "getattr"
                and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)
                and n.args[1].value == "RISK_SCORE"]
    assert not reads and not getattrs, (
        "аллокатор начал читать RISK_SCORE класса — перепроверь docs/tier_criteria.md "
        "§3.2: расхождения классов с каноном перестали быть advisory")


def test_a_planted_wrong_tier_is_caught():
    """Положительный контроль: без него сторож мог бы не сравнивать ничего."""
    class _Fake:
        TIER = "T1"
        RISK_SCORE = 0.9

    auth = {"tier": "T3", "risk_score": 0.9}
    assert str(_Fake.TIER).upper() != auth["tier"], "подлог не отличается от нормы"
    assert _band_of(_Fake.RISK_SCORE) == "T3" != str(_Fake.TIER).upper()


@pytest.mark.parametrize("score,tier", [
    (0.0, "T1"), (0.249, "T1"), (0.25, "T2"), (0.60, "T2"), (0.601, "T3"), (1.0, "T3"),
])
def test_tier_bands_are_the_documented_ones(score, tier):
    """Полосы из docs/tier_criteria.md §1.1 — границы проверяются поимённо."""
    assert _band_of(score) == tier
