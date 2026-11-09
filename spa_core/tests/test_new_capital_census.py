"""Батарея §20 «New capital» — прибор :mod:`spa_core.analytics.new_capital_census`.

Каждая проба — контроль в ОБЕ стороны: сцена, где прибор обязан сказать «да», и
сцена, где он обязан сказать «нет». Проба, видевшая только один ответ, не
отличает работающий прибор от заклинившего на одном вердикте (урок §16…§19).

Время, номера процессов и git-окружение в предмет не входят: сцены прибора
ОБЪЯВЛЕНЫ константами модуля, живой трек не читается ни одним числом, и ответ
воспроизводим на любой машине в любой день. Литеральных дат здесь нет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from spa_core.analytics import new_capital_census as ncc


REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Словари ВВЕЗЕНЫ, а не перепечатаны — иначе две шкалы разойдутся молча
# ---------------------------------------------------------------------------

def test_dictionaries_are_imported_not_reprinted():
    """Ввоз обязан быть УСПЕШНЫМ: заглушка молча развела бы две шкалы."""
    assert ncc._VOCAB_ERRORS == [], ncc._VOCAB_ERRORS

    from spa_core.analytics.transaction_economics import CHARGE_KINDS, UNMEASURED
    from spa_core.analytics.correlated_dependency_census import (
        EXPRESS_KINDS, MONEY_PATH_FILES,
    )
    from spa_core.monitoring.cio_auto_execution_limits import SURFACES

    assert ncc.CHARGE_KINDS is CHARGE_KINDS
    assert ncc.UNMEASURED == UNMEASURED
    assert ncc.EXPRESS_KINDS is EXPRESS_KINDS
    # Расширения НАЗВАНЫ и содержат ввезённое целиком, а не вместо него.
    assert tuple(SURFACES) == ncc.SURFACES_20[:len(SURFACES)]
    assert ncc.SURFACES_20[len(SURFACES):] == ("book", "journal")
    assert tuple(MONEY_PATH_FILES) == ncc.MONEY_PATH_20[:len(MONEY_PATH_FILES)]


def test_own_dictionaries_carry_the_third_outcome():
    """Свои шкалы обязаны нести `unmeasured` — инв. #17, а не «ноль»."""
    assert ncc.UNMEASURED in ncc.SOURCE_KINDS
    assert ncc.UNMEASURED in ncc.SLOT_KINDS
    # Своя шкала не является КОПИЕЙ ввезённой и не поглощает её. Отдельные
    # совпадающие имена исходов (`absent`, `unmeasured`) общие НАМЕРЕННО: это
    # терминальные исходы одного языка, а не вторая шкала. Вторая шкала — это
    # когда ввезённый перечень воспроизведён целиком.
    shared_terminals = {"absent", ncc.UNMEASURED}
    for own in (ncc.SOURCE_KINDS, ncc.SLOT_KINDS):
        assert set(own) != set(ncc.EXPRESS_KINDS)
        assert not set(ncc.EXPRESS_KINDS) <= set(own), (
            "ввезённая шкала воспроизведена целиком — это вторая шкала")
        assert (set(own) & set(ncc.EXPRESS_KINDS)) <= shared_terminals, (
            set(own) & set(ncc.EXPRESS_KINDS))


def test_every_declared_source_kind_is_reachable_by_a_scene(monkeypatch):
    """КАЖДЫЙ род своей шкалы обязан достигаться сценой.

    Эта проба нашла в приборе ДВА недостижимых рода (`no_input_door` в
    :data:`ncc.SOURCE_KINDS` и `absent` в :data:`ncc.SLOT_KINDS`) — ровно род
    дефекта, который §19 нашёл у потолка T3 (ADR-962). Без неё шкала выглядела
    бы полной, а её часть не значила бы ничего.
    """
    price, err = ncc.load_price_door()
    assert err is None, err
    real = ncc._call_price_door
    reached = set()

    # живая дверь
    reached.add(ncc.distinction(price)["kind"])

    # оборот различается ⇒ source_charged
    def halve(p, cur, tgt, **kw):
        d = real(p, cur, tgt, **kw)
        if len(d.legs or []) == 1:
            d.turnover_usd = round(d.turnover_usd / 2.0, 2)
        return d
    monkeypatch.setattr(ncc, "_call_price_door", halve)
    reached.add(ncc.distinction(price)["kind"])

    # перекладка отказана ⇒ source_refused
    def mute(p, cur, tgt, **kw):
        d = real(p, cur, tgt, **kw)
        if len(d.legs or []) == 2:
            d.decision = "HOLD"
        return d
    monkeypatch.setattr(ncc, "_call_price_door", mute)
    reached.add(ncc.distinction(price)["kind"])

    # дверь не ввезена ⇒ unmeasured
    monkeypatch.setattr(ncc, "_call_price_door", real)
    reached.add(ncc.distinction(None)["kind"])

    assert reached == set(ncc.SOURCE_KINDS), (
        "недостижимые роды шкалы: {}".format(sorted(set(ncc.SOURCE_KINDS) - reached)))


def test_every_declared_slot_kind_is_reachable_by_a_scene(tmp_path):
    """То же требование к шкале ячейки журнала."""
    reached = set()

    def tree_with(slug: str, body: str) -> Path:
        root = tmp_path / slug
        (root / Path(ncc.JOURNAL_WRITER_REL).parent).mkdir(parents=True)
        (root / ncc.JOURNAL_WRITER_REL).write_text(body, encoding="utf-8")
        return root

    for slug, body, expect in (
        ("literal", "def w():\n    return {'type': 'rebalance'}\n",
         "named_but_unreachable"),
        ("computed", "def w(k):\n    return {'type': k}\n", "many_kinds_written"),
        ("no_cell", "def w():\n    return {'diff_usd': 1.0}\n", "absent"),
    ):
        row = next(r for r in ncc.expressibility(tree_with(slug, body))
                   if r["surface"] == "journal")
        assert row["slot_kind"] == expect, (expect, row)
        reached.add(row["slot_kind"])

    row = next(r for r in ncc.expressibility(tmp_path / "no-such-tree")
               if r["surface"] == "journal")
    reached.add(row["slot_kind"])

    assert reached == set(ncc.SLOT_KINDS), (
        "недостижимые роды шкалы ячейки: {}".format(
            sorted(set(ncc.SLOT_KINDS) - reached)))


def test_no_second_copy_of_an_imported_dictionary_in_the_source():
    """Шкалы ввозятся; второе ОБЪЯВЛЕНИЕ ввезённого имени — красный тест."""
    tree = ast.parse((REPO / "spa_core/analytics/new_capital_census.py")
                     .read_text(encoding="utf-8"))
    assigned: set = set()
    for node in tree.body:   # только модульный уровень: ввоз живёт в `except`
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                assigned.add(tgt.id)
    for imported in ("CHARGE_KINDS", "EXPRESS_KINDS", "SURFACES", "MONEY_PATH_FILES"):
        assert imported not in assigned, (
            "{} объявлен заново на модульном уровне — это вторая шкала".format(imported))


# ---------------------------------------------------------------------------
# (а) ВЫРАЗИМОСТЬ — контроль в обе стороны на ПОДСТАВЛЕННЫХ контрактах
# ---------------------------------------------------------------------------

def test_expressibility_answers_every_declared_surface():
    """Поверхность без ответа — НЕ ИЗМЕРЕНО, а не пустота (инв. #17)."""
    rows = ncc.expressibility(REPO)
    answered = {r["surface"] for r in rows}
    assert answered == set(ncc.SURFACES_20), answered
    for row in rows:
        assert row["kind"] in tuple(ncc.EXPRESS_KINDS) + (ncc.UNMEASURED,), row
        assert row.get("why"), row


def test_expressibility_says_absent_on_the_live_price_door():
    """Отрицательная сторона: у живой двери цены входа про источник НЕТ."""
    row = next(r for r in ncc.expressibility(REPO) if r["surface"] == "economics")
    assert row["kind"] == "absent", row
    assert row["params_naming_source"] == []
    # Подпись ПРОЧИТАНА, а не угадана: входы перечислены поимённо.
    assert "current_positions" in row["params"] and "target_positions" in row["params"]


def test_expressibility_would_say_door_input_if_the_door_gained_the_input(monkeypatch):
    """Положительная сторона: дверь с входом про источник ⇒ род меняется.

    Без этой пробы «absent» неотличим от «прибор всегда отвечает absent».
    """
    def evaluate_with_source(*, current_positions, target_positions, apy_pct,
                             evidenced, chains, capital_usd, new_money_usd=0.0,
                             **kw):  # pragma: no cover — зовётся только подписью
        raise NotImplementedError

    fake = type("FakeDoor", (), {"evaluate": staticmethod(evaluate_with_source)})
    monkeypatch.setattr(ncc, "load_price_door", lambda: (fake, None))
    row = next(r for r in ncc.expressibility(REPO) if r["surface"] == "economics")
    assert row["kind"] == "door_input", row
    assert row["params_naming_source"] == ["new_money_usd"]


def test_expressibility_is_unmeasured_when_a_contract_is_missing(monkeypatch):
    """Третий исход: дверь не ввезена ⇒ НЕ ИЗМЕРЕНО с причиной, не `absent`."""
    monkeypatch.setattr(ncc, "load_price_door", lambda: (None, "дверь не ввезена: сцена"))
    row = next(r for r in ncc.expressibility(REPO) if r["surface"] == "economics")
    assert row["kind"] == ncc.UNMEASURED
    assert "не ввезена" in row["why"]


# ---------------------------------------------------------------------------
# Ячейка рода хода у журнала — своя шкала, и у неё обе стороны
# ---------------------------------------------------------------------------

def test_journal_slot_is_named_but_unreachable_in_the_live_writer():
    row = next(r for r in ncc.expressibility(REPO) if r["surface"] == "journal")
    # Источник денег не выразим НИГДЕ, включая запись хода.
    assert row["kind"] == "absent", row
    # А ячейка РОДА хода есть, и в неё кладут литерал.
    assert row["slot_kind"] == "named_but_unreachable", row
    assert row["literals"] == ["rebalance"], row
    assert row["all_literal"] is True


def test_journal_slot_reads_many_kinds_when_the_writer_computes_it(tmp_path):
    """Положительная сторона своей шкалы: выражение вместо литерала ⇒ другой род."""
    tree_root = tmp_path / "tree"
    (tree_root / Path(ncc.JOURNAL_WRITER_REL).parent).mkdir(parents=True)
    (tree_root / ncc.JOURNAL_WRITER_REL).write_text(
        "def w(kind):\n    return {'type': kind, 'diff_usd': 1.0}\n", encoding="utf-8")
    slot, err = ncc._journal_kind_slot(tree_root)
    assert err is None, err
    assert slot["all_literal"] is False
    assert slot["sites"][0]["shape"] == "name:kind"


def test_journal_slot_absent_is_measured_not_unmeasured(tmp_path):
    """«Файл прочитан, ячейки нет» — ИЗМЕРЕННЫЙ ноль, а не «не измерено».

    Слей их — и род `absent` стал бы НЕДОСТИЖИМ, то есть шкала понесла бы
    собственную находку §19 (`named_but_unreachable`).
    """
    tree_root = tmp_path / "tree"
    (tree_root / Path(ncc.JOURNAL_WRITER_REL).parent).mkdir(parents=True)
    (tree_root / ncc.JOURNAL_WRITER_REL).write_text(
        "def w():\n    return {'diff_usd': 1.0}\n", encoding="utf-8")
    slot, err = ncc._journal_kind_slot(tree_root)
    assert err is None and slot["no_slot"] is True and slot["sites"] == []


def test_journal_slot_is_unmeasured_when_the_file_is_unreadable(tmp_path):
    """А вот НЕЧИТАЕМЫЙ файл — настоящий третий исход, с названной причиной."""
    slot, err = ncc._journal_kind_slot(tmp_path / "no-such-tree")
    assert slot == {} and "файла нет" in err


# ---------------------------------------------------------------------------
# (б) РАЗЛИЧЕНИЕ — сцены, контроль, и ЧТО именно сравнивается
# ---------------------------------------------------------------------------

def test_the_two_scenes_differ_in_exactly_the_source_of_the_dollar():
    """Предпосылка сцены: цель, капитал и фондируемая нога СОВПАДАЮТ бит в бит.

    Разойдись они — дифференциал мерил бы два разных хода, и ответ был бы о
    сценах, а не об источнике денег.
    """
    books = ncc._scene_books()
    (new_cur, new_tgt), (swap_cur, swap_tgt) = books["new"], books["swap"]
    assert new_tgt == swap_tgt, "целевая книга обязана совпадать"
    # Фондируемая нога одна и та же.
    assert (new_tgt[ncc.SCENE_DEST] - new_cur[ncc.SCENE_DEST]
            == swap_tgt[ncc.SCENE_DEST] - swap_cur[ncc.SCENE_DEST]
            == ncc.SCENE_FUND_USD)
    # И различается РОВНО источник: в сцене `new` доллар приходит из кэша.
    assert sum(new_cur.values()) + ncc.SCENE_FUND_USD == sum(swap_cur.values())
    assert sum(swap_cur.values()) == ncc.SCENE_CAPITAL_USD - ncc.SCENE_FUND_USD * 0 - (
        ncc.SCENE_CAPITAL_USD - sum(swap_cur.values()))  # кэш сцены swap назван ниже
    assert sum(new_cur.values()) < ncc.SCENE_CAPITAL_USD, "в сцене ввода обязан быть кэш"


def test_distinction_is_source_invisible_on_the_live_price_door():
    price, err = ncc.load_price_door()
    assert err is None, err
    d = ncc.distinction(price)
    assert d["kind"] == "source_invisible", d
    assert d["turnover_identical"] is True
    # Сдвиг цены есть РОВНО один литерал газа за тронутую позицию — не род хода.
    from spa_core.backtesting.tier1.cost_model import GAS_USD_PER_POSITION_CHANGE
    assert d["cost_delta_usd"] == pytest.approx(
        GAS_USD_PER_POSITION_CHANGE[ncc.SCENE_CHAIN])
    assert d["scenes"]["new"]["leg_count"] == 1
    assert d["scenes"]["swap"]["leg_count"] == 2


def test_distinction_refuses_to_answer_when_the_control_does_not_move(monkeypatch):
    """Контроль — не украшение: он не сменил вердикт ⇒ ответ НЕ ВЫДАЁТСЯ."""
    price, _ = ncc.load_price_door()
    monkeypatch.setattr(ncc, "_controls",
                        lambda _p: {"all_changed": False, "gain": {"changed": False},
                                    "week_budget": {"changed": True}})
    d = ncc.distinction(price)
    assert d["kind"] == ncc.UNMEASURED
    assert "контроль" in d["why"]


def test_the_real_control_refuses_when_the_doors_gates_do_not_move(monkeypatch):
    """Сведение контролей проверяется НА ПРОИЗВОДСТВЕННОМ коде, не на подмене.

    Мутант M5 цикла #1081 объявил контроль живым всегда (`all_changed = True`) и
    ВЫЖИЛ: единственная проба об отказе подменяла :func:`ncc._controls` целиком,
    поэтому сама строка сведения не исполнялась ни разу. Здесь подменяется ДВЕРЬ
    (её ворота замораживаются), а `_controls` работает настоящий.
    """
    price, _ = ncc.load_price_door()
    real = ncc._call_price_door

    def frozen(p, cur, tgt, **kw):
        d = real(p, cur, tgt, **kw)
        # ворота не двигаются ни от чего — дверь «заклинила» на одном ответе
        d.gates = {k: True for k in (d.gates or {})}
        d.gain_pp = 1.0
        return d

    monkeypatch.setattr(ncc, "_call_price_door", frozen)
    d = ncc.distinction(price)
    assert d["kind"] == ncc.UNMEASURED, d
    assert d["controls"]["all_changed"] is False
    assert "контроль" in d["why"]


def test_distinction_says_source_charged_when_turnover_differs(monkeypatch):
    """Положительная сторона главной оси: оборот различается ⇒ род меняется.

    Возмущается ЕДИНСТВЕННАЯ величина, на которой стоит вердикт оси, — оборот;
    всё остальное у сцен остаётся прежним.
    """
    price, _ = ncc.load_price_door()
    real = ncc._call_price_door

    def call(p, current, target, **kw):
        d = real(p, current, target, **kw)
        # Ход ВВОДА (одна нога) получает половинный оборот — как если бы цена
        # учла, что продавать нечего.
        if len(d.legs or []) == 1:
            d.turnover_usd = round(d.turnover_usd / 2.0, 2)
        return d

    monkeypatch.setattr(ncc, "_call_price_door", call)
    d = ncc.distinction(price)
    assert d["kind"] == "source_charged", d
    assert d["turnover_identical"] is False


def test_distinction_says_source_refused_when_the_door_blocks_the_swap(monkeypatch):
    """Вторая положительная сторона: отказ перекладке — то, что §20 просит.

    Проба держит И достижимость рода: она глушит перекладку во ВСЕХ зовах,
    включая контрольные, то есть ставит прибор ровно в то состояние, в котором
    первая редакция контроля объявляла род недостижимым. Контроль обязан
    остаться живым, потому что меряет ВОРОТА, а не итоговый вердикт.
    """
    price, _ = ncc.load_price_door()
    real = ncc._call_price_door

    def call(p, current, target, **kw):
        d = real(p, current, target, **kw)
        if len(d.legs or []) == 2:      # перекладка — глушится везде
            d.decision = "HOLD"
        return d

    monkeypatch.setattr(ncc, "_call_price_door", call)
    d = ncc.distinction(price)
    assert d["kind"] == "source_refused", d
    assert d["controls"]["all_changed"] is True, (
        "контроль обязан остаться живым при заглушённом вердикте — иначе род "
        "`source_refused` НЕДОСТИЖИМ по построению")


# ---------------------------------------------------------------------------
# (в) ЗАРЯД ОБОРОТА — и доказательство РАВЕНСТВА, а не только связывания
# ---------------------------------------------------------------------------

def test_turnover_charge_is_merged_on_the_live_door():
    price, _ = ncc.load_price_door()
    c = ncc.turnover_charge(price)
    assert c["kind"] == "charged_merged", c
    assert c["refused_by_week_budget"] is True
    assert c["refused_by_day_budget"] is True
    # «ТЕМ ЖЕ числом» — утверждение о равенстве, и оно ИЗМЕРЕНО.
    assert c["refusal_identical"] is True
    assert c["turnover_reasons_new"] == c["turnover_reasons_swap"]
    # Ворота на обороте перечислены, а не посчитаны на глаз.
    assert c["gates_on_turnover_count"] == 4
    assert c["gates_on_turnover_count"] < c["gates_total"]


def test_turnover_charge_says_named_when_the_inflow_keeps_its_budget(monkeypatch):
    """Положительная сторона: ввод обороту не заряжен ⇒ род меняется.

    Возмущается РОВНО оборот хода ввода — до нуля, как если бы дверь знала, что
    продавать нечего.
    """
    price, _ = ncc.load_price_door()
    real = ncc._call_price_door

    def call(p, current, target, **kw):
        d = real(p, current, target, **kw)
        if len(d.legs or []) == 1:
            d.turnover_usd = 0.0
        return d

    monkeypatch.setattr(ncc, "_call_price_door", call)
    c = ncc.turnover_charge(price)
    assert c["kind"] == "not_charged", c


def test_turnover_charge_measures_sameness_and_not_just_binding(monkeypatch):
    """Равенство причин ИЗМЕРЯЕТСЯ: разошлись причины ⇒ род обязан смениться.

    Мутант M7 цикла #1081 подставил `same_refusal = True` и ВЫЖИЛ: живая дверь
    даёт одинаковые причины, поэтому проба на живом дереве мутанта не отличала.
    Отличить может только сцена, где причины РАЗНЫЕ.
    """
    price, _ = ncc.load_price_door()
    real = ncc._call_price_door

    def call(p, cur, tgt, **kw):
        d = real(p, cur, tgt, **kw)
        if len(d.legs or []) == 2 and kw.get("turnover_last_week_usd"):
            # перекладку отказывает ДРУГАЯ причина
            d.reasons = ["move_turnover_over_budget:99.0%>15%"]
        return d

    monkeypatch.setattr(ncc, "_call_price_door", call)
    c = ncc.turnover_charge(price)
    assert c["refusal_identical"] is False, c
    assert c["kind"] == "charged_named", c
    assert c["turnover_reasons_new"] != c["turnover_reasons_swap"]


def test_turnover_charge_says_named_when_the_budget_does_not_bind(monkeypatch):
    """Вторая положительная сторона: оборот заряжен, а ворота ввод НЕ отказывают.

    Нужна отдельно от сцены `not_charged`: без неё род `charged_named` не
    достигался бы НИ ОДНОЙ сценой, то есть шкала понесла бы собственную находку
    §19 (`named_but_unreachable`).
    """
    price, _ = ncc.load_price_door()
    real = ncc._call_price_door

    def call(p, cur, tgt, **kw):
        d = real(p, cur, tgt, **kw)
        if kw.get("turnover_last_week_usd") or kw.get("turnover_today_usd"):
            d.decision = "ACT"          # бюджет как будто не связал
        return d

    monkeypatch.setattr(ncc, "_call_price_door", call)
    c = ncc.turnover_charge(price)
    assert c["kind"] == "charged_named", c
    assert c["refused_by_week_budget"] is False


def test_which_imported_charge_kinds_this_axis_can_reach():
    """Ввезённая шкала §13 шире предмета §20, и это объявлено, а не умолчано.

    `no_input_door` на этой оси недостижим ПО ПОСТРОЕНИЮ: оборот у двери цены
    всегда вычисляется, входа «нет оборота» не бывает. Шкала ввезена целиком
    намеренно (своя копия развела бы две шкалы), но какая её часть предметна для
    §20 — сказано вслух, а не оставлено читателю.
    """
    reachable_here = {"not_charged", "charged_merged", "charged_named", ncc.UNMEASURED}
    assert reachable_here <= set(ncc.CHARGE_KINDS) | {ncc.UNMEASURED}
    assert set(ncc.CHARGE_KINDS) - reachable_here == {"no_input_door"}, (
        "состав ввезённой шкалы изменился — перечень предметных родов §20 "
        "надо перемерить, а не поправить литерал")


def test_turnover_charge_is_unmeasured_without_the_door():
    c = ncc.turnover_charge(None)
    assert c["kind"] == ncc.UNMEASURED and "не ввезена" in c["why"]


# ---------------------------------------------------------------------------
# Читатели словаря родов операции: зов обязан ДОХОДИТЬ до словаря
# ---------------------------------------------------------------------------

def test_operation_readers_do_not_count_a_merely_matching_string(tmp_path):
    """Предмет ловушки четвёртой: `add_argument("rebalance")` читателем НЕ является.

    Сцена — одноразовое дерево: корень засева объявляет параметр `operation`,
    а чужой зов лишь совпадает строкой.
    """
    root = tmp_path / "tree"
    (root / "spa_core/analytics").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / ncc.GAS_UNITS_HOME).write_text(
        "def estimate_gas_fee_usd(self, operation, chain):\n    return 1.0\n",
        encoding="utf-8")
    (root / "spa_core/analytics/impostor.py").write_text(
        "def main(ap):\n    ap.add_argument('rebalance')\n", encoding="utf-8")
    (root / "spa_core/analytics/honest.py").write_text(
        "def f(calc):\n    return calc.estimate_gas_fee_usd('deposit', 'ethereum')\n",
        encoding="utf-8")
    callees, err = ncc._operation_taking_callees(root)
    assert err is None, err
    assert "estimate_gas_fee_usd" in callees
    assert "add_argument" not in callees

    report = ncc.operation_kind_readers(root)
    files = {r["file"] for r in report["readers"]}
    assert "spa_core/analytics/honest.py" in files
    assert "spa_core/analytics/impostor.py" not in files, (
        "совпадение строкой зачтено как чтение — ровно ловушка четвёртая")


def test_a_matching_string_is_not_a_reader_even_in_a_readers_own_file(tmp_path):
    """Самозванец и настоящий читатель в ОДНОМ файле — и это не придирка.

    Мутант M2 цикла #1081 снял проверку «зов доходит до словаря» и ВЫЖИЛ:
    предыдущая проба держала самозванца в ОТДЕЛЬНОМ файле, который отсекался
    дешёвым файловым фильтром ДО разбора, поэтому поимённая проверка зова не
    исполнялась ни разу. Настоящая форма — ровно эта: `allocator_advisors.py`
    несёт и честные зовы, и посторонние с теми же строками.
    """
    root = tmp_path / "tree"
    (root / "spa_core/analytics").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / ncc.GAS_UNITS_HOME).write_text(
        "def estimate_gas_fee_usd(self, operation, chain):\n    return 1.0\n",
        encoding="utf-8")
    (root / "spa_core/analytics/mixed.py").write_text(
        "def honest(calc):\n"
        "    return calc.estimate_gas_fee_usd('deposit', 'ethereum')\n"
        "def impostor(ap, q):\n"
        "    ap.add_argument('rebalance')\n"
        "    q.enqueue_digest('rebalance')\n", encoding="utf-8")
    report = ncc.operation_kind_readers(root)
    callees = {r["callee"] for r in report["readers"]}
    assert callees == {"estimate_gas_fee_usd"}, (
        "посторонний зов в ОДНОМ файле с честным зачтён читателем: {}".format(callees))


def test_operation_readers_follow_one_forwarding_hop(tmp_path):
    """Засев до неподвижной точки: обёртка, пробрасывающая параметр, — читатель."""
    root = tmp_path / "tree"
    (root / "spa_core/analytics").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / ncc.GAS_UNITS_HOME).write_text(
        "def estimate_gas_fee_usd(self, operation, chain):\n    return 1.0\n",
        encoding="utf-8")
    (root / "spa_core/analytics/wrap.py").write_text(
        "def _gas_usd(calc, operation, chain):\n"
        "    return calc.estimate_gas_fee_usd(operation, chain)\n"
        "def caller(calc):\n"
        "    return _gas_usd(calc, 'deposit', 'ethereum')\n", encoding="utf-8")
    callees, err = ncc._operation_taking_callees(root)
    assert err is None, err
    assert {"estimate_gas_fee_usd", "_gas_usd"} <= callees, sorted(callees)
    report = ncc.operation_kind_readers(root)
    assert any(r["callee"] == "_gas_usd" and "deposit" in r["operations"]
               for r in report["readers"]), report["readers"]


def test_forwarding_a_foreign_parameter_does_not_seed_a_name(tmp_path):
    """Проброс в СОСЕДНЮЮ позицию обёрткой НЕ делает — иначе засев раздувается.

    Мутант M3 цикла #1081 снял условие проброса и ВЫЖИЛ: прежняя проба
    требовала лишь, чтобы честная обёртка ПОПАЛА в засев, и не проверяла, что
    посторонняя в него НЕ попадает. На живом дереве цена этой неточности
    измерена: засев 6 имён против 3 канонических.
    """
    root = tmp_path / "tree"
    (root / "spa_core/analytics").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / ncc.GAS_UNITS_HOME).write_text(
        "def estimate_gas_fee_usd(self, operation, chain):\n    return 1.0\n",
        encoding="utf-8")
    (root / "spa_core/analytics/two_kinds.py").write_text(
        # обёртка: СВОЙ параметр уходит В ПОЗИЦИЮ ОПЕРАЦИИ
        "def real_wrapper(calc, operation, chain):\n"
        "    return calc.estimate_gas_fee_usd(operation, chain)\n"
        # не обёртка: свой параметр уходит в позицию КАЛЬКУЛЯТОРА, операция — литерал
        "def foreign(calc, chain):\n"
        "    return calc.estimate_gas_fee_usd('deposit', chain)\n",
        encoding="utf-8")
    callees, err = ncc._operation_taking_callees(root)
    assert err is None, err
    assert "real_wrapper" in callees
    assert "foreign" not in callees, (
        "имя, пробросившее ПОСТОРОННИЙ параметр, засеяно как обёртка: {}"
        .format(sorted(callees)))


def test_operation_readers_are_unmeasured_when_the_seed_root_is_empty(tmp_path):
    """Третий исход: корень засева пуст ⇒ НЕ ИЗМЕРЕНО, и нулём это не считается."""
    root = tmp_path / "tree"
    (root / "spa_core/analytics").mkdir(parents=True)
    (root / ncc.GAS_UNITS_HOME).write_text(
        "def unrelated(x):\n    return x\n", encoding="utf-8")
    callees, err = ncc._operation_taking_callees(root)
    assert callees is None and "корень засева пуст" in err


def test_the_distinction_exists_in_the_system_and_no_money_path_door_reads_it():
    """Главный факт §20, замером: словарь родов есть, на денежном пути читателей 0."""
    report = ncc.operation_kind_readers(REPO)
    assert report.get("kind") != ncc.UNMEASURED, report.get("why")
    assert set(report["operations_declared"]) >= {"deposit", "rebalance", "withdraw"}
    assert report["pairs"]["deposit:ethereum"] < report["pairs"]["rebalance:ethereum"], (
        "система обязана знать, что ввод дешевле перекладки — иначе §20 не о том")
    assert report["readers_count"] > 0, "читателей ноль — прибор не нашёл бы и advisory"
    assert report["readers_on_money_path"] == [], report["readers_on_money_path"]
    assert report["operations_read_on_money_path"] == []


def test_money_path_is_declared_and_contains_the_price_door():
    """Перечень денежного пути ОБЪЯВЛЕН: вне перечня — советательный путь."""
    assert ncc.PRICE_DOOR_REL in ncc.MONEY_PATH_20
    assert ncc.JOURNAL_WRITER_REL in ncc.MONEY_PATH_20
    for rel in ncc.MONEY_PATH_20:
        assert (REPO / rel).exists(), "{} объявлен денежным путём и не существует".format(rel)


def test_the_price_door_cost_model_has_no_operation_kind():
    """Претензия «рода операции у двери цены нет» СВЕРЯЕТСЯ с файлом."""
    text = (REPO / ncc.PRICE_COST_MODEL_REL).read_text(encoding="utf-8")
    tree = ast.parse(text)
    names = {t.id for node in tree.body
             if isinstance(node, ast.Assign)
             for t in node.targets if isinstance(t, ast.Name)}
    assert "GAS_USD_PER_POSITION_CHANGE" in names
    # Ни одной функции с параметром про род операции.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = {a.arg for a in node.args.args + node.args.kwonlyargs}
            assert not (params & {"operation", "op", "tx_type", "transaction_type"}), (
                "{} получил род операции — претензия прибора устарела".format(node.name))


# ---------------------------------------------------------------------------
# (г) ДОСТИЖИМОСТЬ — каталог данных ВХОД, умолчание ПЕЧАТАЕТСЯ
# ---------------------------------------------------------------------------

def test_reachability_names_the_data_dir_and_prints_the_default():
    named = ncc.reachability(Path("/nonexistent-dir"), REPO)
    assert named["journal_dir_named"] is True
    assert "journal_default_printed" not in named

    defaulted = ncc.reachability(None, REPO)
    assert defaulted["journal_dir_named"] is False
    assert "НЕ НАЗВАН" in defaulted["journal_default_printed"], (
        "умолчание обязано ПЕЧАТАТЬСЯ: иначе замер git-замороженного канона "
        "читался бы как замер живого трека")


def test_reachability_separates_absent_journal_from_a_single_capital(tmp_path):
    """Три исхода журнала различимы (инв. #17)."""
    missing = ncc.reachability(tmp_path, REPO)
    assert missing["journal"]["kind"] == ncc.UNMEASURED
    assert "файла нет" in missing["journal"]["why"]

    (tmp_path / "trades.json").write_text(json.dumps(
        [{"type": "rebalance", "capital": 100000.0}] * 3), encoding="utf-8")
    one = ncc.reachability(tmp_path, REPO)
    assert one["journal"]["kind"] == "single_capital"
    assert one["journal"]["kinds_written"] == ["rebalance"]

    (tmp_path / "trades.json").write_text(json.dumps(
        [{"type": "deposit", "capital": 100000.0},
         {"type": "rebalance", "capital": 110000.0}]), encoding="utf-8")
    many = ncc.reachability(tmp_path, REPO)
    assert many["journal"]["kind"] == "many_capitals"
    assert many["journal"]["kinds_written"] == ["deposit", "rebalance"]


def test_reachability_names_the_binding_ceiling_from_the_live_policy():
    """Контрапункт §19 МЕРИТСЯ, а не перепечатывается из текста заказа."""
    r = ncc.reachability(None, REPO)["ceiling"]
    assert r["kind"] == "measured"
    # Поля потолка T3 на протокол нет вовсе — это замер, он и объясняет сцену T1.
    assert r["max_concentration_t3_field_exists"] is False
    assert r["max_total_t3_allocation"] < r["max_concentration_t1"], (
        "если суммарный потолок T3 перестал быть жёстче, сцену §20 надо перемерить"
    )
    assert r["scene_tier"] == "T1"


# ---------------------------------------------------------------------------
# Сборка, вердикт и форма отчёта
# ---------------------------------------------------------------------------

def test_census_on_the_live_tree_names_the_finding():
    report = ncc.census(REPO)
    assert report["vocab_errors"] == []
    assert report["unmeasured"] == [], report["unmeasured"]
    assert ncc.verdict_code(report) == 1, "находка обязана быть НАЗВАНА, а не скрыта"
    v = report["verdict"]
    assert v["source_kind"] == "source_invisible"
    assert v["charge_kind"] == "charged_merged"
    assert set(v["express_absent"]) == set(ncc.SURFACES_20)
    assert set(v["operations_without_a_money_path_reader"]) == {
        "deposit", "rebalance", "withdraw"}


def test_verdict_code_prefers_unmeasured_over_a_verdict_about_the_world():
    """«Не измерено» решается ПЕРВЫМ: ненадёжный замер вердиктом не становится."""
    clean = {"vocab_errors": [], "unmeasured": [],
             "verdict": {"source_kind": "source_refused", "charge_kind": "charged_named",
                         "express_absent": [],
                         "operations_without_a_money_path_reader": []}}
    assert ncc.verdict_code(clean) == 0
    dirty = dict(clean, unmeasured=["журнал не прочитан"])
    assert ncc.verdict_code(dirty) == 2
    vocab = dict(clean, vocab_errors=["§13 не ввезён"])
    assert ncc.verdict_code(vocab) == 2
    finding = dict(clean, verdict=dict(clean["verdict"],
                                       source_kind="source_invisible"))
    assert ncc.verdict_code(finding) == 1


def test_render_prints_every_axis_and_the_advisory_line():
    text = ncc.render(ncc.census(REPO))
    for marker in ("(а) ВЫРАЗИМОСТЬ", "(б) РАЗЛИЧАЕТ", "(в) ЗАРЯД",
                   "(г) ДОСТИЖИМОСТЬ", "СЛОВАРЬ РОДОВ ОПЕРАЦИИ", "ADVISORY"):
        assert marker in text, marker
    assert "НАХОДКА НАЗВАНА" in text


def test_main_returns_the_verdict_code(capsys):
    code = ncc.main(["--root", str(REPO), "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["paragraph"] == 20
    assert payload["advisory"].startswith("прибор только ЧИТАЕТ")


def test_the_instrument_writes_nothing(tmp_path, monkeypatch):
    """ADVISORY — утверждение о ПОВЕДЕНИИ, и оно проверяется, а не обещается."""
    monkeypatch.chdir(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    ncc.census(REPO, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
