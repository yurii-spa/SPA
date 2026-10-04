"""Батарея переписи мутационных подмен (заказ G96 п. 2, ADR-508).

Каждый тест здесь — либо ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ реальной формы (той, что
ADR-508 измерил рукой в цикле #727, либо той, что нашлась в дереве), либо
контроль В ОБРАТНУЮ СТОРОНУ с НАЗВАННЫМ порванным звеном.

**Сцена доказывает свою породу раньше, чем о ней судят.** Фикстура — это
ИСХОДНЫЙ ТЕКСТ, и утверждать «вот тут подмена без проверки якоря», не доказав
сперва, что прибор вообще увидел тут подмену над текстом ФАЙЛА, значило бы
мерить собственную опечатку. Поэтому первые два теста — про предпосылку.

Литеральных дат здесь нет: отметку прибор берёт параметром `now`, и батарея
передаёт ЕГО (`FROZEN-DATE-OK` не нужен — литерала нет вовсе). Литеральных pid
нет: ни одного процесса прибор не спрашивает. Сеть не задействуется.
"""

# FROZEN-DATE-OK: injected-clock — отметку прибор принимает ВХОДОМ (`now=`), и
# батарея передаёт якорь ему аргументом; напечатанная отметка сверяется с ТЕМ ЖЕ
# якорем, то есть закреплены обе стороны и календарь на вердикт не влияет.
from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

import pytest

from spa_core.monitoring import mutation_application_census as mac


# ─────────────────────────────────────────────────────────────────────────────
# Сцена: одноразовое дерево из объявленного текста
# ─────────────────────────────────────────────────────────────────────────────

#: Словарь, делающий модуль БАТАРЕЕЙ в глазах прибора. Вынесен в константу
#: ровно для того, чтобы тест обратной стороны мог его УБРАТЬ и назвать звено.
BATTERY_HEAD = '"""mutant/survivor scorecard."""\nimport subprocess\n'


def _tree(tmp_path: Path, **modules: str) -> Path:
    """Дерево с объявленными каталогами и названными модулями."""
    root = tmp_path / "stand"
    for rel, text in modules.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    # Каталоги прибора обязаны СУЩЕСТВОВАТЬ: их отсутствие — отдельный исход,
    # и он проверяется своим тестом ниже, а не случайно здесь.
    for name in ("scripts", "spa_core"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _rows(tmp_path: Path, body: str, *, rel: str = "scripts/battery.py",
          head: str = BATTERY_HEAD) -> list:
    root = _tree(tmp_path, **{rel: head + body})
    doc = mac.measure(root, now=dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc))
    return doc["rows"]


def _only(rows: list) -> dict:
    assert len(rows) == 1, f"сцена дала {len(rows)} мест(а) вместо одного: {rows}"
    return rows[0]


# ── сцена доказывает породу ──────────────────────────────────────────────────

_UNCHECKED = """
def apply(path, old, new):
    src = path.read_text(encoding="utf-8")
    path.write_text(src.replace(old, new), encoding="utf-8")
"""


def test_the_scene_really_puts_a_substitution_over_file_read_text(tmp_path):
    """Предпосылка: прибор ВИДИТ в фикстуре подмену над текстом файла."""
    row = _only(_rows(tmp_path, _UNCHECKED))
    assert row["form"] == "str.replace"
    assert row["file"] == "scripts/battery.py"
    assert row["reaches_disk"] is True, (
        "сцена обязана писать файл — иначе она не та порода, о которой заказ")


def test_a_substitution_over_a_literal_is_not_in_the_population(tmp_path):
    """Обратная сторона: порванное звено — ПРОИСХОЖДЕНИЕ текста от чтения."""
    rows = _rows(tmp_path, """
def apply(path, old, new):
    src = "status: new\\n"
    path.write_text(src.replace(old, new), encoding="utf-8")
""")
    assert rows == [], (
        "подмена над ЛИТЕРАЛОМ в предмет не входит: терять тут нечего, "
        "потому что источника на диске не читали")


# ── ось якоря: пять исходов, каждый со своим звеном ──────────────────────────

_UNIQUE = """
def apply(path, old, new):
    src = path.read_text(encoding="utf-8")
    if src.count(old) != 1:
        return {"applied": False, "why": "anchor is not unique"}
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    return {"applied": True}
"""


def test_uniqueness_compared_with_one_is_the_only_proven_form(tmp_path):
    row = _only(_rows(tmp_path, _UNIQUE))
    assert row["anchor"] == mac.ANCHOR_UNIQUE
    assert row["speech"] == mac.SPOKEN, (
        "`return <вердикт>` и есть третий исход заказа — считать его тишиной "
        "значило бы не увидеть единственный верный образец")


def test_dropping_the_comparison_with_one_drops_the_verdict_to_presence(tmp_path):
    """Порванное звено НАЗВАНО: сравнение счёта с ЕДИНИЦЕЙ."""
    row = _only(_rows(tmp_path, _UNIQUE.replace("!= 1", "== 0")))
    assert row["anchor"] == mac.ANCHOR_PRESENCE, (
        "`count(old) == 0` ловит ноль и пропускает ДВА — это и есть авария #727")
    assert "ДВА от одного" in row["anchor_why"]


def test_dropping_the_count_entirely_is_the_orders_finding(tmp_path):
    row = _only(_rows(tmp_path, _UNCHECKED))
    assert row["anchor"] == mac.ANCHOR_UNCHECKED
    assert row["speech"] == mac.NO_BRANCH
    assert "неотличима" in row["anchor_why"]


_BOUND = """
import re

def apply(path, pattern, repl, floor):
    src = path.read_text(encoding="utf-8")
    cut, n = re.subn(pattern, repl, src)
    assert n > floor, "подмена мерила бы пустоту"
    path.write_text(cut, encoding="utf-8")
"""


def test_a_count_read_and_loudly_bounded_is_not_a_finding(tmp_path):
    """`re.sub` многоместен ПО ПОСТРОЕНИЮ: единица у него не критерий."""
    root = _tree(tmp_path, **{"scripts/battery.py": BATTERY_HEAD + _BOUND})
    doc = mac.measure(root, now=dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc))
    row = _only(doc["rows"])
    assert row["anchor"] == mac.ANCHOR_BOUND
    assert row["speech"] == mac.SPOKEN
    assert doc["findings"] == [], (
        "верная форма не вправе быть находкой — иначе перепись становится "
        "источником ложных карточек")


def test_throwing_the_subn_count_away_is_a_finding_that_names_the_waste(tmp_path):
    row = _only(_rows(tmp_path, """
import re

def apply(path, pattern, repl):
    src = path.read_text(encoding="utf-8")
    path.write_text(re.subn(pattern, repl, src)[0], encoding="utf-8")
"""))
    assert row["anchor"] == mac.ANCHOR_UNCHECKED
    assert "отказ от готового ответа" in row["anchor_why"], (
        "форма, ОТДАЮЩАЯ счёт, и форма, его не имеющая, стоя́т одного — но "
        "причины у них разные, и причина обязана быть названа")


def test_a_presence_only_check_is_a_finding_because_two_places_pass(tmp_path):
    row = _only(_rows(tmp_path, """
def apply(path, old, new):
    src = path.read_text(encoding="utf-8")
    if old in src:
        path.write_text(src.replace(old, new), encoding="utf-8")
"""))
    assert row["anchor"] == mac.ANCHOR_PRESENCE
    assert "наличие" in row["anchor_why"]


def test_a_starred_anchor_is_the_third_outcome_not_a_silent_drop(tmp_path):
    row = _only(_rows(tmp_path, """
def apply(path, pair):
    src = path.read_text(encoding="utf-8")
    path.write_text(src.replace(*pair), encoding="utf-8")
"""))
    assert row["anchor"] == mac.ANCHOR_UNMEASURED
    assert row["speech"] == mac.SPEECH_UNMEASURED
    assert "разборе отсутствует" in row["anchor_why"], (
        "выброшенное из населения место молча стало бы «дефектов меньше»")


# ── якорь — ЭТОТ, а не похожий ───────────────────────────────────────────────

def test_the_count_of_a_different_anchor_does_not_count(tmp_path):
    """Порванное звено: ТОЖДЕСТВО якоря у подмены и у проверки."""
    row = _only(_rows(tmp_path, """
def apply(path, old, new, other):
    src = path.read_text(encoding="utf-8")
    if src.count(other) != 1:
        return {"applied": False}
    path.write_text(src.replace(old, new), encoding="utf-8")
    return {"applied": True}
"""))
    assert row["anchor"] == mac.ANCHOR_UNCHECKED, (
        "проверка ЧУЖОГО якоря об этой подмене не говорит ничего")


#: Единственный читатель счёта стои́т ЗА перекладыванием имени — ровно форма,
#: на которой ADR-550 поймал обрыв дороги у привязок конституции.
_RENAMED = """
import re

def apply(path, pattern, repl, floor):
    src = path.read_text(encoding="utf-8")
    cut, n = re.subn(pattern, repl, src)
    seen = n
    assert seen > floor, "подмен меньше объявленной границы"
    path.write_text(cut, encoding="utf-8")
"""


def test_the_count_travels_through_a_renaming_binding(tmp_path):
    """Счёт, переложенный в другое имя, несёт себя дальше (урок ADR-550)."""
    row = _only(_rows(tmp_path / "with", _RENAMED))
    assert row["anchor"] == mac.ANCHOR_BOUND, (
        "`seen = n` — перекладывание счёта, а не его потеря")
    # Звено названо и порвано: без строки-перекладывания читателей у счёта
    # НЕТ, и вердикт обязан упасть до «не спрошено ничего».
    broken = _only(_rows(tmp_path / "without",
                         _RENAMED.replace("    seen = n\n", "")
                                 .replace("assert seen > floor", "assert floor >= 0")))
    assert broken["anchor"] == mac.ANCHOR_UNCHECKED, (
        "обрыв дороги объявил бы ЕДИНСТВЕННОГО настоящего читателя "
        f"отсутствующим, и это обязано быть видно: {broken['anchor_why']}")


def test_a_silent_branch_is_told_apart_from_a_loud_one(tmp_path):
    """Вторая половина вопроса заказа: «не применена» произносится или молчит."""
    loud = _only(_rows(tmp_path, """
def apply(path, old, new):
    src = path.read_text(encoding="utf-8")
    if src.count(old) == 0:
        print("не применена")
    path.write_text(src.replace(old, new), encoding="utf-8")
"""))
    quiet = _only(_rows(tmp_path, """
def apply(path, old, new):
    src = path.read_text(encoding="utf-8")
    if src.count(old) == 0:
        return
    path.write_text(src.replace(old, new), encoding="utf-8")
"""))
    assert (loud["speech"], quiet["speech"]) == (mac.SPOKEN, mac.SILENT), (
        f"громкую и тихую ветку прибор не различил: {loud['speech']} / {quiet['speech']}")
    assert "усох молча" in quiet["speech_why"]


# ── происхождение значения: ПОТОКОМ, а не по имени ───────────────────────────

def test_the_origin_survives_a_strip_in_between(tmp_path):
    row = _only(_rows(tmp_path, """
def apply(path, old, new):
    src = path.read_text(encoding="utf-8").strip()
    path.write_text(src.replace(old, new), encoding="utf-8")
"""))
    assert row["anchor"] == mac.ANCHOR_UNCHECKED, (
        "`.strip()` между чтением и подменой — то же значение; оборвать поток "
        "на нём значило бы объявить самую обычную форму отсутствующей")


def test_a_chained_substitution_is_two_sites_with_two_addresses(tmp_path):
    rows = _rows(tmp_path, """
def apply(path, a, b, c, d):
    src = path.read_text(encoding="utf-8")
    path.write_text(src.replace(a, b).replace(c, d), encoding="utf-8")
""")
    assert len(rows) == 2, f"цепочка дала {len(rows)} мест(а) вместо двух"
    addresses = {(r["line"], r["col"], r["end_col"]) for r in rows}
    assert len(addresses) == 2, (
        "у внешнего и внутреннего вызова НАЧАЛО одно и то же — без конца "
        "выражения две разные подмены печатались бы одной записью дважды")


# ── одно имя — два объекта ───────────────────────────────────────────────────

def test_datetime_replace_is_not_a_textual_substitution(tmp_path):
    """Контроль на десять ложных членов первой редакции прибора."""
    rows = _rows(tmp_path, """
import datetime

def age(path):
    stamp = path.read_text(encoding="utf-8")
    moment = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment
""")
    assert len(rows) == 1, (
        "`moment.replace(tzinfo=…)` — подмена ПОЛЯ `datetime`, а не текста; "
        f"признак строковой подмены есть АРИТЕТ, не имя метода. Мест: {rows}")
    # Номер строки берётся ИЗ САМОЙ сцены: литерал тут сломался бы от любой
    # правки фикстуры по причине, не имеющей отношения к предмету.
    stand = (tmp_path / "stand" / "scripts" / "battery.py").read_text(encoding="utf-8")
    expected = next(i for i, line in enumerate(stand.splitlines(), start=1)
                    if "fromisoformat" in line)
    assert rows[0]["line"] == expected, (
        "единственное место обязано быть строковой подменой внутри "
        "`fromisoformat`, а не подменой поля времени")


# ── род места ────────────────────────────────────────────────────────────────

def test_the_kind_needs_both_the_vocabulary_and_a_run(tmp_path):
    battery = _only(_rows(tmp_path, _UNCHECKED, head=BATTERY_HEAD))
    assert battery["kind"] == mac.KIND_BATTERY
    no_words = _only(_rows(tmp_path, _UNCHECKED, head="import subprocess\n"))
    assert no_words["kind"] == mac.KIND_REWRITER
    assert "словаря мутанта" in no_words["kind_why"]
    no_run = _only(_rows(tmp_path, _UNCHECKED,
                         head='"""mutant/survivor scorecard."""\n'))
    assert no_run["kind"] == mac.KIND_REWRITER
    assert "прогона-судьи" in no_run["kind_why"]


def test_the_kind_does_not_match_by_substring(tmp_path):
    """`permutation` содержит `mutation` — и батареей от этого не становится."""
    row = _only(_rows(tmp_path, _UNCHECKED,
                      head='"""permutation helper."""\nimport subprocess\n'))
    assert row["kind"] == mac.KIND_REWRITER, (
        "ADR-333: проба не проходит подстрокой, и прибор не вправе носить тот "
        "дефект, который ищет у других")


def test_the_headline_answer_counts_batteries_only(tmp_path):
    root = _tree(tmp_path, **{
        "scripts/battery.py": BATTERY_HEAD + _UNCHECKED,
        "spa_core/plain.py": "import subprocess\n" + _UNCHECKED,
    })
    doc = mac.measure(root, now=dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc))
    assert doc["counts"]["kind"] == {mac.KIND_BATTERY: 1, mac.KIND_REWRITER: 1}
    assert doc["counts_batteries"]["anchor"][mac.ANCHOR_UNCHECKED] == 1
    assert "род «батарея мутаций» — 1 мест(о)" in doc["answer"]


# ── третий исход у самого замера ─────────────────────────────────────────────

def test_a_tree_without_the_declared_roots_is_unmeasured_not_zero(tmp_path):
    empty = tmp_path / "nowhere"
    empty.mkdir()
    with pytest.raises(mac.Unmeasured) as exc:
        mac.measure(empty)
    assert "не в то дерево" in str(exc.value)


def test_main_refuses_with_code_two_when_nothing_could_be_measured(tmp_path, capsys):
    empty = tmp_path / "nowhere"
    empty.mkdir()
    code = mac.main(["--root", str(empty)])
    assert code == 2, "«не измерено» обязано иметь НЕНУЛЕВОЙ код возврата (инв. #17)"
    out = capsys.readouterr().out
    assert "НЕ ИЗМЕРЕНО" in out and "НЕ СКАЗАНО НИЧЕГО" in out


def test_an_unparsable_file_is_named_with_a_reason(tmp_path):
    root = _tree(tmp_path, **{"scripts/broken.py": "def (:\n"})
    doc = mac.measure(root, now=dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc))
    assert [u["file"] for u in doc["unreadable"]] == ["scripts/broken.py"]
    assert "не разобран" in doc["unreadable"][0]["why"], (
        "нечитаемый файл — третий исход с причиной, а не вычет из населения")


def test_report_refuses_instead_of_printing_zeros(tmp_path):
    lines = mac.report({"status": "OK"})
    assert any("НЕ ИЗМЕРЕНО" in line for line in lines)
    assert not any("anchor_unchecked 0" in line for line in lines), (
        "нули про замер, которого не читали, и есть подстановка вместо отказа")


def test_report_respects_an_unmeasured_status():
    lines = mac.report({"status": "UNMEASURED", "reason": "каталогов нет"})
    assert "каталогов нет" in lines[0]
    assert "НЕ СКАЗАНО НИЧЕГО" in lines[1]


# ── коды возврата и артефакт ─────────────────────────────────────────────────

def test_main_returns_one_on_findings_and_zero_on_a_clean_tree(tmp_path, capsys):
    dirty = _tree(tmp_path / "a", **{"scripts/battery.py": BATTERY_HEAD + _UNCHECKED})
    clean = _tree(tmp_path / "b", **{"scripts/battery.py": BATTERY_HEAD + _UNIQUE})
    assert mac.main(["--root", str(dirty)]) == 1
    assert mac.main(["--root", str(clean)]) == 0
    capsys.readouterr()


def test_run_writes_the_artifact_with_the_injected_stamp(tmp_path):
    root = _tree(tmp_path, **{"scripts/battery.py": BATTERY_HEAD + _UNIQUE})
    moment = dt.datetime(2001, 2, 3, 4, 5, 6, tzinfo=dt.timezone.utc)
    out = mac.run(root, dest=tmp_path / "art.json", now=moment)
    doc = json.loads((tmp_path / "art.json").read_text(encoding="utf-8"))
    assert out["doc"]["status"] == "OK"
    assert doc["generated_at"] == "2001-02-03T04:05:06Z", (
        "отметку прибор обязан брать ВХОДОМ: иначе батарея краснела бы от "
        "календаря, а не от кода")
    assert doc["applied"] is False, "перепись только читает"


def test_run_carries_the_refusal_into_the_artifact(tmp_path):
    empty = tmp_path / "nowhere"
    empty.mkdir()
    out = mac.run(empty, dest=tmp_path / "art.json",
                  now=dt.datetime(2001, 2, 3, tzinfo=dt.timezone.utc))
    assert out["doc"]["status"] == "UNMEASURED"
    assert "не в то дерево" in out["doc"]["reason"]


# ── форма самого прибора ─────────────────────────────────────────────────────

def test_every_declared_outcome_has_a_producer():
    """Исход, который нечему произвести, есть проза, выданная за измерение."""
    source = Path(mac.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    returned: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        for part in ast.walk(node.value):
            if isinstance(part, ast.Name):
                returned.add(part.id)
    declared = {"ANCHOR_UNIQUE", "ANCHOR_BOUND", "ANCHOR_PRESENCE",
                "ANCHOR_UNCHECKED", "ANCHOR_UNMEASURED",
                "SPOKEN", "SILENT", "NO_BRANCH", "SPEECH_UNMEASURED"}
    assert declared <= returned, f"исходов без производителя: {sorted(declared - returned)}"


# ─────────────────────────────────────────────────────────────────────────────
# Дыры СЦЕНЫ, названные мутациями цикла #767 (все четыре выживших — здесь)
# ─────────────────────────────────────────────────────────────────────────────

def test_a_single_positional_argument_is_not_a_textual_substitution(tmp_path):
    """`str.replace` требует ДВА позиционных: и старое, и новое.

    Выживший мутант `len(node.args) < 2` → `< 1` назвал дыру сцены: контроль
    на `datetime.replace(tzinfo=…)` проверял НОЛЬ позиционных, и порог между
    одним и двумя не мерил никто.
    """
    rows = _rows(tmp_path, """
def normalise(path, old):
    cfg = path.read_text(encoding="utf-8")
    return cfg.replace(old)
""")
    assert rows == [], (
        "один позиционный аргумент — не `str.replace` (у неё старое И новое "
        f"позиционны), а чей-то одноимённый метод. Мест: {rows}")


def test_the_finding_rule_depends_on_the_form_in_both_directions(tmp_path):
    """Выживший мутант `return row["form"] == "str.replace"` → `False`.

    Правило находки формо-зависимо, и обе стороны обязаны быть измерены: у
    адресной `str.replace` слепота к кратности ЕСТЬ находка (авария #727), у
    многоместного `re.subn` — НЕТ.
    """
    addressed = """
def apply(path, old, new):
    src = path.read_text(encoding="utf-8")
    if src.count(old) == 0:
        print("не применена")
    path.write_text(src.replace(old, new), encoding="utf-8")
"""
    many = """
import re

def apply(path, pattern, repl):
    src = path.read_text(encoding="utf-8")
    cut, n = re.subn(pattern, repl, src)
    assert n > 0, "ни одной подмены"
    path.write_text(cut, encoding="utf-8")
"""
    one = mac.measure(_tree(tmp_path / "a", **{"scripts/b.py": BATTERY_HEAD + addressed}),
                      now=dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc))
    few = mac.measure(_tree(tmp_path / "b", **{"scripts/b.py": BATTERY_HEAD + many}),
                      now=dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc))
    assert _only(one["rows"])["anchor"] == mac.ANCHOR_PRESENCE
    assert _only(few["rows"])["anchor"] == mac.ANCHOR_PRESENCE, (
        "обе сцены обязаны лежать в ОДНОМ вердикте оси якоря — иначе тест "
        "мерил бы не правило находки, а вердикт")
    assert len(one["findings"]) == 1, "у адресной подмены слепота к кратности — находка"
    assert few["findings"] == [], (
        "у многоместной по построению требовать единицу значило бы объявить "
        "дефектом верный код")


def test_the_origin_is_found_through_a_chain_assigned_out_of_order(tmp_path):
    """Выживший мутант `rounds: int = 4` → `1` назвал дыру сцены.

    В цикле значение предыдущего витка законно используется раньше, чем его
    присваивание встречается обходу дерева. Один проход такую цепочку теряет,
    и место ВЫПАДАЕТ из населения молча — ровно та подстановка, против которой
    прибор написан.
    """
    rows = _rows(tmp_path, """
def apply(path, pairs):
    for old, new in pairs:
        trimmed = raw.strip()
        raw = path.read_text(encoding="utf-8")
        path.write_text(trimmed.replace(old, new), encoding="utf-8")
""")
    assert len(rows) == 1, (
        "цепочка «чтение → обрезка → подмена», присвоенная не в порядке "
        f"обхода, обязана находиться до НЕПОДВИЖНОЙ ТОЧКИ. Мест: {rows}")


def test_a_substitution_over_a_previous_substitution_is_also_a_site(tmp_path):
    """Выживший мутант, потерявший `from_sub`, назвал дыру сцены.

    Контроль цепочки был только ОДНОЙ формы — `src.replace(a, b).replace(c, d)`,
    где внутренний вызов виден прямо в дереве. Форма с ПРОМЕЖУТОЧНЫМ ИМЕНЕМ
    (`once = src.replace(...)`, затем `once.replace(...)`) не проверялась, а
    в батареях живёт именно она.
    """
    rows = _rows(tmp_path, """
def apply(path, a, b, c, d):
    src = path.read_text(encoding="utf-8")
    once = src.replace(a, b)
    path.write_text(once.replace(c, d), encoding="utf-8")
""")
    assert len(rows) == 2, (
        "подмена НАД ПОДМЕНОЙ — то же значение, доехавшее до диска; потеряв "
        f"её, прибор объявил бы вторую подмену несуществующей. Мест: {rows}")
