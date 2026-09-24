"""Заказ G84 п. 2 — форма вреда у ПИСАТЕЛЯ открытого счётчика.

Весь ряд G76…G84 мерил ЧИТАТЕЛЯ: доходит ли незнакомый класс до вердикта.
Форма вреда у ПИСАТЕЛЯ не измерена ни одним шагом ряда, и заказ повторяет
вопрос третий раз подряд (G82 п. 2 → G83 п. 2 → G84 п. 2):

    Сколько открытых счётчиков принимают незнакомый класс МОЛЧА, а сколько
    падают на нём ``KeyError``.

Вопрос назвал сам сосед — в собственном перечне слепоты: «род накопителя
здесь НЕ доказывается». Отсюда следствие, которого ряд не проверял ни разу:
часть населения, которую ПЯТЬ шагов подряд звали ОТКРЫТОЙ, может быть не
открыта вовсе.

Каждый тест здесь — положительный контроль (воспроизводит уже случившуюся
форму: известный случай ADR-459, случай, названный заказом дословно, либо
дефект, найденный при постройке самого прибора) либо контроль В ОБРАТНУЮ
СТОРОНУ: правило обязано не только НАЙТИ, но и ПРОМАХНУТЬСЯ там, где
промахнуться должно.

**Дефект прибора, найденный ЗАМЕРОМ и закреплённый здесь** (``test_silence_*``):
поле ``silence_proved_by`` считало доказательства по ВСЕМУ населению, а
``WRITER_BY_KIND`` доказывает и громкий исход тоже — поле носило имя «чем
доказано МОЛЧАНИЕ» и считало заодно 36 падающих. Число, чьё имя не описывает
того, что оно считает, есть ровно тот дефект, против которого написан ряд.

Литеральных дат в файле нет: у шага нет понятия свежести, и вводить его
фикстурой значило бы завести бомбу на пустом месте.
"""

from __future__ import annotations

import ast

import pytest

from spa_core.monitoring import rule_second_copy_census as census
from spa_core.monitoring.rule_second_copy_census import (
    WRITER_BY_FORM,
    WRITER_BY_KIND,
    WRITER_GAP_MANY_KINDS,
    WRITER_GAP_NO_BINDING,
    WRITER_GAP_OPAQUE,
    WRITER_LOUD,
    WRITER_SILENT,
    WRITER_UNRESOLVED,
    UNMEASURED_WRITER_CONTROL,
    UNMEASURED_WRITER_NEIGHBOUR,
    UNMEASURED_WRITER_POPULATION,
    _WRITER_GAPS,
    _WRITER_OUTCOMES,
    writer_harm_form,
)

# Хвост, которым КАЖДАЯ сцена делает свой счётчик ОТКРЫТЫМ по правилу соседа:
# ключ приходит из артефакта и принадлежностью не сверен. Без него сцена не
# попала бы в население вовсе, и тест мерил бы отсутствие, а не исход.
_OPEN_KEY = 'str(row.get("verdict"))'


def _sites(body: str) -> list:
    """Разбор одной сцены правилом шага. Сцена — исходник, а не описание."""
    return census._writer_kind_sites("<scene>", ast.parse(body))


def _one(body: str) -> dict:
    found = _sites(body)
    assert len(found) == 1, f"сцена обязана дать ровно один счётчик: {found}"
    return found[0]


# ---------------------------------------------------------------------------
# ИЗВЕСТНЫЕ СЛУЧАИ РЯДА — положительные контроли
# ---------------------------------------------------------------------------

def test_the_case_the_order_named_is_loud():
    """`{v: 0 for v in _VERDICTS}` + `+=` — случай, названный заказом дословно.

    `copy_independence_probe.measure`. Предзаполненный ОБЪЯВЛЕННЫМ перечнем
    словарь падает `KeyError` на классе вне перечня: он не «молча другой
    исход», он вовсе не доезжает до счёта.
    """
    site = _one(f'''
_VERDICTS = ("clean", "dirty")


def measure(rows):
    counts = {{v: 0 for v in _VERDICTS}}
    for row in rows:
        counts[{_OPEN_KEY}] += 1
''')
    assert site["writer"] == WRITER_LOUD
    assert site["proved_by"] == WRITER_BY_KIND
    assert site["accumulator"] == "strict"


def test_the_adr_459_case_is_silent_and_proved_by_the_form():
    """`X[k] = X.get(k, 0) + 1` — известный случай ADR-459.

    Молчание здесь доказано ФОРМОЙ: `.get` с умолчанием заводит класс любым
    родом накопителя, и род спрашивать не о чем.
    """
    site = _one(f'''
def audit(rows):
    counts = {{}}
    for row in rows:
        counts[{_OPEN_KEY}] = counts.get({_OPEN_KEY}, 0) + 1
''')
    assert site["writer"] == WRITER_SILENT
    assert site["proved_by"] == WRITER_BY_FORM
    assert site["accumulator"] is None


def test_the_get_form_is_silent_even_on_a_strict_accumulator():
    """Контроль В ОБРАТНУЮ СТОРОНУ к предыдущему.

    Род накопителя СТРОГ, а исход всё равно молчание — потому что доказан он
    формой. Не будь этого теста, «форма молчит» было бы неотличимо от «род
    не посмотрели».
    """
    site = _one(f'''
_VERDICTS = ("clean", "dirty")


def audit(rows):
    counts = {{v: 0 for v in _VERDICTS}}
    for row in rows:
        counts[{_OPEN_KEY}] = counts.get({_OPEN_KEY}, 0) + 1
''')
    assert site["writer"] == WRITER_SILENT
    assert site["proved_by"] == WRITER_BY_FORM


# ---------------------------------------------------------------------------
# РОД НАКОПИТЕЛЯ — обе стороны
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ctor", ["Counter()", "defaultdict(int)",
                                  "collections.Counter()",
                                  "collections.defaultdict(list)"])
def test_forgiving_accumulators_are_silent(ctor):
    site = _one(f'''
def scene(rows):
    acc = {ctor}
    for row in rows:
        acc[{_OPEN_KEY}] += 1
''')
    assert site["writer"] == WRITER_SILENT
    assert site["proved_by"] == WRITER_BY_KIND
    assert site["accumulator"] == "forgiving"


@pytest.mark.parametrize("ctor", ["{}", "{'clean': 0}", "dict()",
                                  "collections.OrderedDict()",
                                  "dict.fromkeys(_VERDICTS, 0)"])
def test_strict_accumulators_are_loud(ctor):
    site = _one(f'''
_VERDICTS = ("clean", "dirty")


def scene(rows):
    acc = {ctor}
    for row in rows:
        acc[{_OPEN_KEY}] += 1
''')
    assert site["writer"] == WRITER_LOUD
    assert site["accumulator"] == "strict"


def test_defaultdict_without_a_factory_is_strict():
    """Самое острое место правила, и оно ПОЛОЖИТЕЛЬНЫЙ контроль.

    По короткому ИМЕНИ `defaultdict` снисходителен; по ЗНАЧЕНИЮ аргумента —
    строг: без фабрики `default_factory is None`, и отсутствующий ключ даёт
    `KeyError`. Правило, судящее род по имени конструктора, объявило бы этот
    счётчик молчащим — и ошиблось бы ровно на том случае, который выглядит
    очевидным.
    """
    site = _one(f'''
def scene(rows):
    acc = defaultdict()
    for row in rows:
        acc[{_OPEN_KEY}] += 1
''')
    assert site["writer"] == WRITER_LOUD
    assert site["accumulator"] == "strict"


def test_a_counter_from_a_foreign_module_is_not_measured():
    """Контроль В ОБРАТНУЮ СТОРОНУ: род — предмет доказательства, не догадки.

    `shelf.Counter(...)` по короткому имени неотличим от
    `collections.Counter(...)`, но чей он — неизвестно. Признать его
    снисходительным значило бы вывести род из СОВПАДЕНИЯ ИМЕНИ.
    """
    site = _one(f'''
def scene(rows):
    acc = shelf.Counter()
    for row in rows:
        acc[{_OPEN_KEY}] += 1
''')
    assert site["writer"] == WRITER_UNRESOLVED
    assert site["writer_gap"] == WRITER_GAP_OPAQUE


# ---------------------------------------------------------------------------
# ТРЕТИЙ ИСХОД — и у каждой причины СВОЁ имя
# ---------------------------------------------------------------------------

def test_an_opaque_call_is_the_third_outcome():
    site = _one(f'''
def scene(rows):
    acc = build_tally()
    for row in rows:
        acc[{_OPEN_KEY}] += 1
''')
    assert site["writer"] == WRITER_UNRESOLVED
    assert site["writer_gap"] == WRITER_GAP_OPAQUE


def test_an_accumulator_bound_outside_this_scope_is_the_third_outcome():
    """ОБЪЯВЛЕННАЯ односторонность шага, а не находка.

    Имя пришло параметром — связывания в этой области нет. Посмотреть выше
    по дереву областей значило бы поставить ответ в зависимость от того, как
    далеко прибор решил заглянуть.
    """
    site = _one(f'''
def scene(rows, acc):
    for row in rows:
        acc[{_OPEN_KEY}] += 1
''')
    assert site["writer"] == WRITER_UNRESOLVED
    assert site["writer_gap"] == WRITER_GAP_NO_BINDING


def test_an_accumulator_that_is_not_a_name_is_the_third_outcome():
    """`by_leg[p['protocol']][cls] += 1` — живая форма дерева (замер).

    Накопитель — не имя, а выражение: связывать в этой области нечего.
    """
    site = _one(f'''
def scene(rows, by_leg):
    for row in rows:
        by_leg[row["leg"]][{_OPEN_KEY}] += 1
''')
    assert site["writer"] == WRITER_UNRESOLVED
    assert site["writer_gap"] == WRITER_GAP_NO_BINDING


def test_two_kinds_of_binding_are_the_third_outcome():
    """Род, связанный по-разному, НЕ решается в пользу одного из двух."""
    site = _one(f'''
def scene(rows, flag):
    acc = Counter()
    if flag:
        acc = {{}}
    for row in rows:
        acc[{_OPEN_KEY}] += 1
''')
    assert site["writer"] == WRITER_UNRESOLVED
    assert site["writer_gap"] == WRITER_GAP_MANY_KINDS


def test_every_gap_has_its_own_name():
    """Один отказ на все причины посылал бы чинить не то.

    Ровно этот урок ADR-467: у восьми остатков имя отказа было НЕ ТО, и
    число ответа не изменилось — изменилось УКАЗАНИЕ, что чинить.
    """
    assert len(set(_WRITER_GAPS)) == 3
    assert len(set(_WRITER_OUTCOMES)) == 3
    assert not set(_WRITER_GAPS) & set(_WRITER_OUTCOMES)


# ---------------------------------------------------------------------------
# ОГОВОРКА К «ГРОМКО» — измерена числом, а не прозой
# ---------------------------------------------------------------------------

def test_a_swallowed_keyerror_does_not_reach_the_caller():
    """«Громко» внутри `try/except Exception` снова становится тишиной."""
    site = _one(f'''
def scene(rows):
    acc = {{}}
    for row in rows:
        try:
            acc[{_OPEN_KEY}] += 1
        except Exception:
            pass
''')
    assert site["writer"] == WRITER_LOUD
    assert site["keyerror_reaches_the_caller"] is False


@pytest.mark.parametrize("catch", ["ValueError", "OSError"])
def test_a_narrow_handler_does_not_swallow_the_keyerror(catch):
    """Контроль В ОБРАТНУЮ СТОРОНУ: не всякий `try` глушит.

    Без него «внутри try» было бы неотличимо от «проглочен», и оговорка
    съела бы исход.
    """
    site = _one(f'''
def scene(rows):
    acc = {{}}
    for row in rows:
        try:
            acc[{_OPEN_KEY}] += 1
        except {catch}:
            pass
''')
    assert site["writer"] == WRITER_LOUD
    assert site["keyerror_reaches_the_caller"] is True


def test_a_counter_inside_the_handler_is_not_protected_by_that_try():
    """Счётчик, стоящий В `except`, этим `try` не защищён.

    Считать иначе значило бы объявить проглоченным то, что этот обработчик
    поймать не может по построению.
    """
    site = _one(f'''
def scene(rows):
    acc = {{}}
    for row in rows:
        try:
            risky()
        except Exception:
            acc[{_OPEN_KEY}] += 1
''')
    assert site["writer"] == WRITER_LOUD
    assert site["keyerror_reaches_the_caller"] is True


# ---------------------------------------------------------------------------
# КОНТРОЛЬ ОБЪЯВЛЕННОГО ПРАВИЛА — и у контроля есть ЗУБЫ
# ---------------------------------------------------------------------------

def test_the_declared_control_passes_on_the_known_cases():
    control = census._writer_kind_control()
    assert control["passed"] is True, control
    assert control["loud"] == 1 and control["silent"] == 3
    assert control["proved_by_form"] == 1 and control["proved_by_kind"] == 2
    assert control["clean_false_positives"] == 0
    assert len(control["gaps"]) == 3


def test_the_control_refuses_when_the_kind_rule_is_blunted(monkeypatch):
    """У контроля обязаны быть ЗУБЫ: правило, судящее род по имени, обязано
    его НЕ пройти. Контроль, не видевший настоящей поломки, — украшение."""
    real = census._accumulator_kind

    def by_name_only(expr):
        # Дословно та ошибка, против которой написан острый случай сцены:
        # `defaultdict` снисходителен по имени, без взгляда на аргумент.
        if isinstance(expr, ast.Call):
            fn = expr.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name in ("Counter", "defaultdict"):
                return "forgiving"
        return real(expr)

    monkeypatch.setattr(census, "_accumulator_kind", by_name_only)
    control = census._writer_kind_control()
    assert control["passed"] is False
    # Отказ приходит РАНЬШЕ именной ветки — на ложном срабатывании: затупленное
    # правило объявляет `defaultdict()` молчащим, и отрицательная половина ловит
    # это первой. Ветка названа здесь явно, чтобы тест проверял ТУ проверку,
    # которая сработала, а не ту, которую я ожидал увидеть.
    assert control["clean_false_positives"] == 1
    assert "по ЗНАЧЕНИЮ аргумента" in control["reason"]


def test_the_step_refuses_when_its_own_control_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(census, "_writer_kind_control",
                        lambda: {"passed": False, "reason": "сцена порвана"})
    out = writer_harm_form(tmp_path, {"status": "MEASURED",
                                      "open_to_an_unnamed_class": 1})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_WRITER_CONTROL


# ---------------------------------------------------------------------------
# НАСЕЛЕНИЕ — у соседа, и СВЕРЯЕТСЯ
# ---------------------------------------------------------------------------

def _tree(tmp_path, body: str):
    for sub in ("spa_core/monitoring", "scripts"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / "spa_core/monitoring/scene.py").write_text(body,
                                                           encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("neighbour,why", [
    (None, "соседа нет вовсе"),
    ({"status": "UNMEASURED"}, "сосед сам не измерен"),
    ({"status": "MEASURED"}, "сосед не назвал числа"),
    ({"status": "MEASURED", "open_to_an_unnamed_class": "158"}, "число не число"),
])
def test_the_step_refuses_without_a_neighbour_population(tmp_path, neighbour,
                                                         why):
    """Населения нет ⇒ ТРЕТИЙ ИСХОД, а не «таких счётчиков нет»."""
    out = writer_harm_form(_tree(tmp_path, "x = 1\n"), neighbour)
    assert out["status"] == "UNMEASURED", why
    assert out["unmeasured_class"] == UNMEASURED_WRITER_NEIGHBOUR, why


def test_the_step_refuses_when_the_two_walks_disagree(tmp_path):
    """Две дороги к одному населению, разойдясь, отвечают на РАЗНЫЕ вопросы."""
    body = f'''
def scene(rows):
    acc = {{}}
    for row in rows:
        acc[{_OPEN_KEY}] += 1
'''
    out = writer_harm_form(_tree(tmp_path, body),
                           {"status": "MEASURED",
                            "open_to_an_unnamed_class": 99})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_WRITER_POPULATION
    assert out["population"] == 1 and out["declared_population"] == 99


def test_an_unreadable_file_is_not_an_empty_population(tmp_path):
    """Неполное население не есть измеренное — тот же порядок, что у соседей."""
    root = _tree(tmp_path, "x = 1\n")
    (root / "spa_core/monitoring/broken.py").write_text("def (:\n",
                                                        encoding="utf-8")
    out = writer_harm_form(root, {"status": "MEASURED",
                                  "open_to_an_unnamed_class": 0})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_WRITER_POPULATION
    assert out["files_unreadable"]


def test_a_missing_directory_is_not_an_empty_population(tmp_path):
    (tmp_path / "spa_core/monitoring").mkdir(parents=True)
    out = writer_harm_form(tmp_path, {"status": "MEASURED",
                                      "open_to_an_unnamed_class": 0})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_WRITER_POPULATION


def test_a_measured_run_agrees_with_the_neighbour(tmp_path):
    """Контроль В ОБРАТНУЮ СТОРОНУ к двум предыдущим: сойдясь — MEASURED."""
    body = f'''
def scene(rows):
    acc = {{}}
    other = Counter()
    for row in rows:
        acc[{_OPEN_KEY}] += 1
        other[{_OPEN_KEY}] += 1
'''
    out = writer_harm_form(_tree(tmp_path, body),
                           {"status": "MEASURED",
                            "open_to_an_unnamed_class": 2})
    assert out["status"] == "MEASURED"
    assert out["population"] == 2
    assert out["writer_outcomes"][WRITER_LOUD] == 1
    assert out["writer_outcomes"][WRITER_SILENT] == 1


# ---------------------------------------------------------------------------
# ДЕФЕКТ, НАЙДЕННЫЙ ЗАМЕРОМ В СОБСТВЕННОМ ПРИБОРЕ
# ---------------------------------------------------------------------------

def test_silence_proved_by_counts_only_the_silent(tmp_path):
    """Положительный контроль на МОЮ СОБСТВЕННУЮ ошибку.

    Первый прогон дал `silence_proved_by` = 105 + 37 = 142 при 106 молчащих:
    `WRITER_BY_KIND` доказывает и ГРОМКИЙ исход тоже, а поле носило имя «чем
    доказано МОЛЧАНИЕ». Имя, не описывающее того, что поле считает, — ровно
    тот дефект, против которого написан весь ряд.
    """
    body = f'''
def scene(rows):
    loud = {{}}
    soft = Counter()
    gets = {{}}
    for row in rows:
        loud[{_OPEN_KEY}] += 1
        soft[{_OPEN_KEY}] += 1
        gets[{_OPEN_KEY}] = gets.get({_OPEN_KEY}, 0) + 1
'''
    out = writer_harm_form(_tree(tmp_path, body),
                           {"status": "MEASURED",
                            "open_to_an_unnamed_class": 3})
    assert out["status"] == "MEASURED"
    silent = out["writer_outcomes"][WRITER_SILENT]
    assert sum(out["silence_proved_by"].values()) == silent
    assert out["silence_proved_by"][WRITER_BY_FORM] == 1
    assert out["silence_proved_by"][WRITER_BY_KIND] == 1
    assert out["writer_outcomes"][WRITER_LOUD] == 1


def test_the_outcome_list_is_closed(tmp_path):
    """Класс вне объявленного перечня — отказ, а не тишина (урок ADR-468)."""
    body = f'''
def scene(rows, given):
    a = {{}}
    b = Counter()
    c = build()
    for row in rows:
        a[{_OPEN_KEY}] += 1
        b[{_OPEN_KEY}] += 1
        c[{_OPEN_KEY}] += 1
        given[{_OPEN_KEY}] += 1
'''
    out = writer_harm_form(_tree(tmp_path, body),
                           {"status": "MEASURED",
                            "open_to_an_unnamed_class": 4})
    assert out["status"] == "MEASURED"
    assert sum(out["writer_outcomes"].values()) == out["population"]
    assert sum(out["unresolved_reasons"].values()) == out["still_unmeasured"]
    assert set(out["writer_outcomes"]) == set(_WRITER_OUTCOMES)


def test_the_step_is_advisory(tmp_path):
    out = writer_harm_form(_tree(tmp_path, "x = 1\n"),
                           {"status": "MEASURED",
                            "open_to_an_unnamed_class": 0})
    assert out["applied"] is False
    assert out["order"] == "G84.2"


def test_the_instrument_does_not_measure_itself():
    """Урок цикла #689: ОТКРЫТЫЙ счётчик внутри прибора, ищущего открытые
    счётчики, дописывает приборам население и заставляет мерить самого себя.
    Все счётчики нового шага — ЗАКРЫТОЙ формы."""
    source = census.__file__
    with open(source, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names = {"writer_harm_form", "_writer_kind_sites", "_writer_kind_site",
             "_writer_kind_control", "_accumulator_kind",
             "_swallowed_by_a_broad_handler"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in names:
            continue
        for inner in ast.walk(node):
            assert census._counter_target_key(inner) is None, (
                f"{node.name}:{getattr(inner, 'lineno', '?')} — счётчик "
                f"ОТКРЫТОЙ формы внутри прибора, ищущего открытые счётчики")


def test_the_report_names_the_third_outcome(tmp_path):
    out = writer_harm_form(_tree(tmp_path, "x = 1\n"),
                           {"status": "MEASURED",
                            "open_to_an_unnamed_class": 0})
    lines = census.report({"writer_harm_form": out})
    body = "\n".join(lines)
    assert "[ФОРМА ВРЕДА У ПИСАТЕЛЯ]" in body
    assert "род накопителя не измерен" in body


def test_the_report_says_not_measured_when_the_step_is_absent():
    """«Шага нет» не выдаётся за «все счётчики молчат»."""
    body = "\n".join(census.report({}))
    assert "[ФОРМА ВРЕДА У ПИСАТЕЛЯ] НЕ ИЗМЕРЕНО" in body
    assert "НЕ «все счётчики молчат»" in body


def test_measure_wires_the_step():
    """Проводка: параметр, до которого не доходит вызов, — половина инъекции."""
    source = census.__file__
    with open(source, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "measure":
            called = {ast.unparse(n.func) for n in ast.walk(node)
                      if isinstance(n, ast.Call)}
            assert "writer_harm_form" in called
            keys = {n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            assert "writer_harm_form" in keys
            return
    raise AssertionError("в модуле нет `measure` — проводка не измерена")


# ---------------------------------------------------------------------------
# КОНТРОЛИ НА КОНТРОЛЬ — заведены по ВЫЖИВШИМ мутациям первого прогона
# ---------------------------------------------------------------------------
# Первый прогон мутаций: убито 22, ВЫЖИЛО 4, не применилось 2. Каждая выжившая
# есть слабость ЭТОЙ батареи, а не прибора, и закрывается она сценой, которой
# батарее не хватало. Засчитать их убитыми «по смыслу» значило бы выдать НЕ
# ИЗМЕРЕНО за измеренный исход.


def test_a_bare_except_swallows_the_keyerror_too():
    """Выжившая мутация №1: `handler.type is None` → `return False`.

    Голого `except:` в батарее не было ни одной сценой, и правило, переставшее
    считать его широким, проходило молча.
    """
    site = _one(f'''
def scene(rows):
    acc = {{}}
    for row in rows:
        try:
            acc[{_OPEN_KEY}] += 1
        except:
            pass
''')
    assert site["writer"] == WRITER_LOUD
    assert site["keyerror_reaches_the_caller"] is False


def test_an_unmeasured_neighbour_is_refused_even_when_it_carries_a_number(
        tmp_path):
    """Выжившая мутация №2: снятая сверка `status != "MEASURED"`.

    Прежние сцены отказа давали соседа БЕЗ числа, и отказ приходил по ветке
    «числа нет» — сверку статуса не проверял никто. Сосед, который сам не
    измерен, но число несёт, разводит эти две ветки.
    """
    out = writer_harm_form(_tree(tmp_path, "x = 1\n"),
                           {"status": "UNMEASURED",
                            "open_to_an_unnamed_class": 0})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_WRITER_NEIGHBOUR


def test_the_control_refuses_when_silence_is_proved_by_the_wrong_evidence(
        monkeypatch):
    """Выжившая мутация №3: снятая сверка `by_form`/`by_kind` в контроле.

    Числа исходов остаются 1 и 3, а доказательства съезжают: молчание формы
    объявляется молчанием рода. Контроль, не сверяющий ЧЕМ доказано, этого не
    видит — и тогда «доказано формой» в отчёте держится ни на чём.
    """
    real = census._writer_kind_site

    def all_by_kind(scope, node, target, form):
        out = real(scope, node, target, form)
        if out["proved_by"] == WRITER_BY_FORM:
            out = {**out, "proved_by": WRITER_BY_KIND}
        return out

    monkeypatch.setattr(census, "_writer_kind_site", all_by_kind)
    control = census._writer_kind_control()
    assert control["passed"] is False
    assert control["by_form"] == 0 and control["by_kind"] == 3


def test_the_control_refuses_when_the_refusal_names_collapse(monkeypatch):
    """Выжившая мутация №4: снятая сверка числа РАЗНЫХ имён отказа.

    Два отказа сливаются в одно имя. Счёт третьего исхода не меняется ни на
    единицу — меняется УКАЗАНИЕ, что чинить, и ровно это ADR-467 назвал
    главным содержанием замера.
    """
    real = census._writer_kind_site

    def collapse(scope, node, target, form):
        out = real(scope, node, target, form)
        if out["writer_gap"] == WRITER_GAP_MANY_KINDS:
            out = {**out, "writer_gap": WRITER_GAP_OPAQUE}
        return out

    monkeypatch.setattr(census, "_writer_kind_site", collapse)
    control = census._writer_kind_control()
    assert control["passed"] is False
    assert len(control["gaps"]) == 2
