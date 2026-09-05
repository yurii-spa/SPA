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

import json
from pathlib import Path

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
# ПУСТО с 2026-08-29: расхождение исполнено — класс адаптера приведён к канону
# (решение владельца ADR-070 п.6, полный мандат 29.08). Список задуман
# сокращающимся, и он сократился до нуля. Любое новое имя здесь — регресс.
KNOWN_TIER_DISAGREEMENT: set[str] = set()

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


def test_the_owner_decision_is_now_delivered_everywhere():
    """Бывший единственный денежный разрыв: класс догнал канон.

    Тест перевёрнут НАМЕРЕННО 2026-08-29 (инвариант 16, обоснование здесь +
    журнал): раньше он закреплял РАСХОЖДЕНИЕ как известное состояние. Теперь
    сторожит исполненность решения — если класс когда-нибудь снова объявит T1,
    покраснеет и он, и `test_no_new_class_disagrees_with_the_canon_on_tier`.
    """
    rows = {p: (ct, a) for p, ct, _, _, a in _rows()}
    ct, auth = rows["morpho_steakhouse"]
    assert auth["tier"] == "T2", "канон изменился — перепроверь ADR-070 п.6"
    assert str(ct).upper() == "T2", (
        f"класс адаптера снова объявляет {ct} — решение владельца откатилось")
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


# ── пятый источник тира: `data/adapter_registry.json` ────────────────────
# Найден 2026-08-29, когда я гнался за «откуда `ethena_susde` взял T3».
# Цепочка: файл данных → `adapter_status_generator` копирует `tier` в
# `data/adapter_status.json` → `tier_curator` читает. Мой прежний сторож
# сверял РЕЕСТР В КОДЕ (`ADAPTER_REGISTRY`) и одноимённый файл в данных
# не видел: два разных объекта с одним именем.
#
# `ethena_susde`: файл говорит T3, канон — T2. Файл СТРОЖЕ (T3 совокупно ≤ 15 %
# против T2 ≤ 50 %), поэтому приводить его к канону значило бы ПОСЛАБИТЬ —
# это решение владельца, а не механическая правка. Оставлено намеренно.
DATA_REGISTRY_KNOWN = {"ethena_susde"}


def _data_registry_tiers(path) -> dict:
    """{протокол: 'T1'|'T2'|'T3'} из файла данных; целые числа переводятся."""
    import json
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = doc.get("adapters") or doc
    out = {}
    if isinstance(rows, dict):
        for k, v in rows.items():
            if not isinstance(v, dict):
                continue
            raw = v.get("tier")
            if isinstance(raw, bool) or raw is None:
                continue
            if isinstance(raw, (int, float)) and int(raw) in (1, 2, 3):
                out[k] = f"T{int(raw)}"
            elif isinstance(raw, str) and raw.strip().upper() in ("T1", "T2", "T3"):
                out[k] = raw.strip().upper()
    return out


def _data_registry_disagreements(tiers: dict) -> dict:
    return {p: (t, PROTOCOL_RISK_SCORES[p]["tier"])
            for p, t in tiers.items()
            if p in PROTOCOL_RISK_SCORES and t != PROTOCOL_RISK_SCORES[p]["tier"]}


def test_data_registry_logic_catches_a_planted_mismatch(tmp_path):
    """Логика работает БЕЗ живого data/ — иначе в CI тест молча пропускался бы."""
    import json
    proto = next(p for p, v in PROTOCOL_RISK_SCORES.items() if v["tier"] == "T2")
    f = tmp_path / "reg.json"
    f.write_text(json.dumps({"adapters": {proto: {"tier": 1}}}), encoding="utf-8")
    assert _data_registry_disagreements(_data_registry_tiers(f)) == {proto: ("T1", "T2")}

    f.write_text(json.dumps({"adapters": {proto: {"tier": 2}}}), encoding="utf-8")
    assert _data_registry_disagreements(_data_registry_tiers(f)) == {}

    f.write_text(json.dumps({"adapters": {proto: {"tier": None}, "чужой": {"tier": 1}}}),
                 encoding="utf-8")
    assert _data_registry_disagreements(_data_registry_tiers(f)) == {}, \
        "пустой тир и протокол вне канона — не расхождения"


def test_live_data_registry_agrees_with_the_canon():
    """Второй слой — по живому файлу там, где он есть."""
    import pytest
    root = Path(__file__).resolve().parents[2]
    f = root / "data" / "adapter_registry.json"
    if not f.exists():
        pytest.skip("data/ отсутствует (worktree/CI) — логика проверена на фикстуре выше")
    bad = _data_registry_disagreements(_data_registry_tiers(f))
    new = sorted(set(bad) - DATA_REGISTRY_KNOWN)
    assert not new, (
        f"data/adapter_registry.json разошёлся с каноном: "
        f"{ {p: bad[p] for p in new} }. Этот файл — вход "
        "adapter_status_generator, и его тир доезжает до куратора.")
    fixed = sorted(DATA_REGISTRY_KNOWN - set(bad))
    assert not fixed, f"расхождение закрыто для {fixed} — убери из DATA_REGISTRY_KNOWN"


# ── шестой источник тира: КЛАСС БЕЗ АТРИБУТА `TIER` ──────────────────────
#
# Замер 2026-09-05 (цикл #488, остаток G1 приказа Portfolio CIO). Всё, что
# выше, спрашивает у класса ОДНО: `getattr(cls, "TIER", None)`. Каждое
# сравнение стои́т под `if ct is not None`, поэтому класс, который тир не
# ОБЪЯВЛЯЕТ атрибутом, а ПРИСВАИВАЕТ (`self.tier = ...`) или передаёт
# аргументом (`YieldInfo(tier=...)`), из сверки выпадает целиком — молча,
# как «нечего сравнивать».
#
# Таких классов пять из тридцати шести: `morpho_blue`, `yearn_v3`,
# `euler_v2`, `maple`, `pendle`. И все пятеро — в `POLLED_ADAPTERS`, то есть
# ровно на том пути, который докстрока этого файла объявляет защищённым
# («ТИР класса доходит до денег через снимок оркестратора — здесь допуск
# нулевой»). Сторож с нулевым допуском не видел почти половины предмета.
#
# Четверо из пяти присваивают КОНСТАНТУ, совпадающую с каноном, — их
# невидимость ничего не стоила. Пятый, `pendle`, тир ВЫЧИСЛЯЕТ:
# `_classify_tier(tvl)` (TVL ≥ $100M → T2, ≥ $20M → T3) и кладёт результат
# в `YieldInfo.tier`; оркестратор пишет `record["tier"] = getattr(info,
# "tier", tier) or tier` — то есть адаптер выигрывает у реестра, — а
# `allocator._load_adapters` читает `a.get("tier")` в `tier_map`. Замер
# 04.09: снимок несёт `pendle: T3` при каноне T2, и в этом протоколе стои́т
# $20 000 книги.
#
# Почему это НЕ авария сегодня — сказано числом, а не надеждой:
# `_cap_for` возвращает `T1_CAP` только для «T1», всё остальное — `T2_CAP`,
# то есть 0.20 и для T2, и для T3; а совокупный потолок T3 (ADR-020, 15 %)
# считает `_enforce_t3_total_cap` по КАНОНУ (`tier_map.tier_of`), а не по
# снимку. Потолок сегодня совпадает по обоим путям. Но держится это на
# схлопывании T3→T2_CAP, которое комментарий самого аллокатора (строка ~700)
# называет прежней ошибкой, а не защитой. Утверждение карточки CIO «два
# разных потолка на один капитал» замером НЕ подтвердилось — расхождение
# есть, денежного эффекта у него сегодня нет.
#
# Правка самого `PendleAdapter` сюда НЕ входит: `_classify_tier` — не только
# ярлык, но и ФИЛЬТР пригодности (TVL < $20M ⇒ рынок не берётся вовсе), и
# снятие вывода тира меняет состав рынков на денежном пути. Это решение
# владельца — тем же порядком, каким `ethena_susde` оставлен строже канона.
# Карточка: `owner-decision-pendle-sam-naznachaet-sebe-uroven-riska`.

#: Протоколы, чей класс ВЫВОДИТ тир из живых данных вместо чтения канона.
#: База установлена замером 05.09 и может ТОЛЬКО СОКРАЩАТЬСЯ. Дописывать
#: сюда имя, чтобы погасить падение, запрещено — это ровно тот дефект, ради
#: которого проверка написана (тот же порядок, что у `frozen_date_baseline`).
TIER_DERIVED_AT_RUNTIME: set[str] = {"pendle"}

#: Выражения, которые тир не ОБЪЯВЛЯЮТ, а лишь перечитывают уже объявленный:
#: `tier=self.tier`, `tier=self.TIER`, `tier=TIER`. Считать их выводом значило
#: бы назвать нарушителями тридцать классов и утопить единственного настоящего.
_TIER_ECHO_ATTRS = {"tier", "TIER"}

#: ГОЛОЕ имя — перечитывание только в ВЕРХНЕМ регистре (`tier=TIER`, модульная
#: константа `extra_finance_base`). Строчное `tier` — ЛОКАЛЬНАЯ переменная, и
#: у `pendle` в ней лежит ровно результат `_classify_tier(tvl)`. Первая
#: редакция держала здесь оба регистра и потому объявила единственного
#: настоящего нарушителя перечитыванием самого себя: слово стало своей же
#: меткой. Поймано положительным контролем ниже, а не чтением.
_TIER_ECHO_BARE_NAMES = {"TIER"}


def _is_tier_echo(node) -> bool:
    """`self.tier` / `self.TIER` / голое `TIER` — перечитывание, не объявление."""
    import ast as _ast
    if isinstance(node, _ast.Attribute) and node.attr in _TIER_ECHO_ATTRS:
        return isinstance(node.value, _ast.Name) and node.value.id == "self"
    return isinstance(node, _ast.Name) and node.id in _TIER_ECHO_BARE_NAMES


def _tier_declarations(source: str, class_name: str, class_attr: str | None):
    """Все тиры, которые класс способен отдать в ``YieldInfo``.

    Возвращает ``(literals, derived, measured)``:

    * ``literals`` — множество констант (атрибут класса + константные
      присваивания ``self.tier`` + константные аргументы ``tier=``);
    * ``derived``  — места, где тир приходит из вычисления (список
      ``(строка, краткое описание)``);
    * ``measured`` — нашлось ли ХОТЬ ОДНО объявление. ``False`` — это третий
      исход «не измерено», а не «расхождений нет»: молчать о классе, о
      котором нечего сказать, — ровно та ошибка, что здесь и чинится.

    Граница метода названа вслух: разбирается ТЕЛО САМОГО класса плюс
    атрибут ``TIER`` со всей цепочки наследования (``getattr``). Класс,
    который сам не объявляет ничего, а получает ``get_yield_info`` с
    ``tier=`` от базового, здесь виден не будет — но и не пройдёт молча: у
    него нет ни одного объявления, значит ``measured=False``, то есть
    громкое «НЕ ИЗМЕРЕНО». Дыры это не оставляет; сегодня таких классов
    в реестре нет (замер 05.09: `tbtc_lending`/`cbbtc_lending` берут
    ``TIER`` с базы, и он читается).
    """
    import ast as _ast

    tree = _ast.parse(source)
    cd = next((n for n in _ast.walk(tree)
               if isinstance(n, _ast.ClassDef) and n.name == class_name), None)
    if cd is None:
        return set(), [], False

    literals: set[str] = set()
    derived: list[tuple[int, str]] = []
    if isinstance(class_attr, str) and class_attr.strip():
        literals.add(class_attr.strip().upper())

    def _take(value, lineno: int, where: str) -> None:
        if isinstance(value, _ast.Constant) and isinstance(value.value, str):
            literals.add(value.value.strip().upper())
        elif _is_tier_echo(value):
            return  # перечитывание уже объявленного
        else:
            derived.append((lineno, where))

    for n in _ast.walk(cd):
        if isinstance(n, _ast.Assign):
            for t in n.targets:
                if (isinstance(t, _ast.Attribute) and t.attr in _TIER_ECHO_ATTRS
                        and isinstance(t.value, _ast.Name) and t.value.id == "self"):
                    _take(n.value, n.lineno, f"self.{t.attr} = …")
        elif isinstance(n, _ast.Call):
            for kw in (n.keywords or []):
                if kw.arg == "tier":
                    _take(kw.value, n.lineno, "tier=… в вызове")

    return literals, derived, bool(literals or derived)


def _declared_rows():
    """(протокол, literals, derived, measured, запись канона) по ВСЕМ классам."""
    import inspect
    out = []
    for entry in ADAPTER_REGISTRY:
        try:
            proto, cls = entry[0], entry[2]
        except Exception:  # noqa: BLE001 — кривая строка реестра
            continue
        auth = PROTOCOL_RISK_SCORES.get(proto)
        if auth is None:
            continue
        try:
            src = Path(inspect.getsourcefile(cls)).read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            out.append((proto, set(), [(0, f"исходник нечитаем: {exc}")], False, auth))
            continue
        lit, der, measured = _tier_declarations(
            src, cls.__name__, getattr(cls, "TIER", None))
        out.append((proto, lit, der, measured, auth))
    return out


def test_every_adapter_class_tier_declaration_is_measured():
    """Третий исход. «Не нашли объявления» — не «объявлений нет»."""
    rows = _declared_rows()
    assert len(rows) >= 30, f"популяция сжалась до {len(rows)} — сверка ослабла"
    unmeasured = sorted(p for p, _, _, measured, _ in rows if not measured)
    assert not unmeasured, (
        f"тир {len(unmeasured)} классов НЕ ИЗМЕРЕН: {unmeasured}. Это третий исход, "
        "а не зелёный: до 2026-09-05 такие классы молча выпадали из всей сверки.")


def test_class_tier_agrees_with_the_canon_however_it_is_declared():
    """Сверка по ФАКТУ объявления, а не по его форме (закрытие слепоты #488)."""
    bad = {}
    for proto, lit, _, _, auth in _declared_rows():
        off = sorted(t for t in lit if t != auth["tier"])
        if off:
            bad[proto] = (off, auth["tier"])
    new = sorted(set(bad) - KNOWN_TIER_DISAGREEMENT)
    assert not new, (
        f"класс объявляет тир мимо канона: { {p: bad[p] for p in new} }. Форма "
        "объявления (атрибут / self.tier / аргумент) значения не имеет — тир "
        "задаётся в PROTOCOL_RISK_SCORES и только там (docs/tier_criteria.md §2).")


def test_no_class_derives_its_tier_from_live_data():
    """Тир — решение политики, а не наблюдение. Ратчет, только вниз."""
    rows = _declared_rows()
    derived = {p for p, _, der, _, _ in rows if der}
    new = sorted(derived - TIER_DERIVED_AT_RUNTIME)
    assert not new, (
        f"класс ВЫЧИСЛЯЕТ свой тир из живых данных: {new}. Тир задаёт потолок "
        "концентрации; выводить его из фида значит назначать себе потолок "
        "наблюдением. В TIER_DERIVED_AT_RUNTIME не дописывать.")
    fixed = sorted(TIER_DERIVED_AT_RUNTIME - derived)
    assert not fixed, (
        f"вывод тира снят у {fixed} — убери из TIER_DERIVED_AT_RUNTIME. База "
        "сокращается вместе с починкой, иначе перестаёт что-либо значить.")


def test_the_derived_tier_baseline_names_a_real_disagreement():
    """База не абстрактна: у `pendle` вывод тира и правда расходится с каноном.

    Без этого ратчет мог бы стеречь пустое место — «положительный контроль
    может быть украшением» (журнал W33).
    """
    from spa_core.adapters.pendle_adapter import _classify_tier, _TIER_T3_TVL
    assert PROTOCOL_RISK_SCORES["pendle"]["tier"] == "T2", "канон по pendle изменился"
    assert _classify_tier(_TIER_T3_TVL) == "T3", (
        "класс перестал выводить T3 из TVL — перепроверь TIER_DERIVED_AT_RUNTIME")


def test_a_class_declaring_its_tier_without_the_attribute_is_caught():
    """Положительный контроль слепоты: ИМЕННО эта форма и была невидима.

    Контроль прежнего теста (`test_a_planted_wrong_tier_is_caught`) подкладывал
    атрибут `TIER` — единственную форму, которая слепой НЕ была.
    """
    src = (
        "class Blind:\n"
        "    def __init__(self):\n"
        "        self.tier = 'T1'\n"
    )
    lit, der, measured = _tier_declarations(src, "Blind", None)
    assert measured and lit == {"T1"} and not der, (lit, der, measured)


def test_a_computed_tier_is_told_apart_from_a_re_read_one():
    """Вывод отличается от перечитывания — иначе тридцать ложных и один утоплен."""
    echo = (
        "class Echo:\n"
        "    TIER = 'T2'\n"
        "    def get_yield_info(self):\n"
        "        return YieldInfo(tier=self.tier)\n"
    )
    _, der, _ = _tier_declarations(echo, "Echo", "T2")
    assert not der, f"перечитывание принято за вывод: {der}"

    computed = (
        "class Computed:\n"
        "    def get_yield_info(self):\n"
        "        return YieldInfo(tier=_classify(self.tvl))\n"
    )
    lit, der, measured = _tier_declarations(computed, "Computed", None)
    assert measured and der and not lit, (lit, der, measured)

    # Форма самого `pendle`: вычисленное значение проходит через ЛОКАЛЬНУЮ
    # переменную с именем `tier`. Пока строчное имя числилось перечитыванием,
    # ратчет молчал именно о нём — контроль стоит здесь, чтобы это не вернулось.
    via_local = (
        "class ViaLocal:\n"
        "    def get_yield_info(self):\n"
        "        tier = _classify(self.tvl)\n"
        "        self.tier = tier\n"
        "        return YieldInfo(tier=tier)\n"
    )
    lit, der, measured = _tier_declarations(via_local, "ViaLocal", None)
    assert measured and der and not lit, (
        f"вычисленный тир, прошедший через локальную `tier`, принят за "
        f"перечитывание: {(lit, der, measured)}")


def test_a_class_with_no_tier_declaration_at_all_is_unmeasured():
    """Молчащий класс обязан стать «не измерено», а не «сошлось»."""
    lit, der, measured = _tier_declarations("class Mute:\n    pass\n", "Mute", None)
    assert not measured and not lit and not der
