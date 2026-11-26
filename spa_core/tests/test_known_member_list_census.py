"""Сторож прибора полноты закрытого перечня известных членов (ADR-1114).

Предмет — `scripts/known_member_list_census.py`. Он отвечает на ДВА вопроса:
«какие закрытые перечни стоя́т положительным контролем и НЕ спрашивают, полны ли
они» (население) и «полон ли перечень, объявивший источник» (вердикт).

У КАЖДОГО теста здесь есть положительный контроль: каждый воспроизводит либо
настоящую находку ADR-1113 (перечень отстал на одного члена, а строка «все 3 из
3 внутри» оставалась правдой), либо дефект ПЕРВОЙ редакции прибора (признак
«объявил источник» читался у МОДУЛЯ, и сосед по файлу зачитывался как
спрашивающий о своей полноте).

Ни одной двери к окружению тесты не открывают: ни часов, ни pid, ни git, ни
сети, ни подпроцессов — поэтому ни календарь, ни глубина клона, ни имя ветки
хоста их вердикта не меняют (`.claude/rules/deployment.md`, §§ про календарь,
личность процесса и git-окружение).
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
_TOOL = REPO / "scripts" / "known_member_list_census.py"


def _load():
    spec = importlib.util.spec_from_file_location("kmlc_under_test", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kmlc_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


kmlc = _load()


def _scene(tmp_path: pathlib.Path, body: str, name: str = "m.py") -> pathlib.Path:
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / name).write_text(body, encoding="utf-8")
    return tmp_path


def _role(tmp_path: pathlib.Path, body: str, const: str = "KNOWN") -> str:
    entries, unparsed = kmlc.measure_surface(_scene(tmp_path, body), ("scripts",))
    assert not unparsed, unparsed
    got = [e for e in entries if e.name == const]
    assert len(got) == 1, [f"{e.path}::{e.name}" for e in entries]
    return got[0].role


# ─────────────────────── РОЛЬ: направление сверки, не имя ───────────────────
def test_members_required_inside_the_subject_is_a_positive_control(tmp_path):
    """`NAME - computed` — перечень обязан быть ВНУТРИ предмета. Это наш класс."""
    assert _role(tmp_path,
                 "KNOWN = {'a': 'ADR-001', 'b': 'ADR-002'}\n"
                 "def lost(found):\n"
                 "    return {k: v for k, v in KNOWN.items() if k not in found}\n"
                 ) == kmlc.POSITIVE_CONTROL


def test_set_difference_in_the_same_direction_is_a_positive_control(tmp_path):
    assert _role(tmp_path,
                 "KNOWN = {'a', 'b'}\n"
                 "def lost(found):\n"
                 "    return KNOWN - set(found)\n"
                 ) == kmlc.POSITIVE_CONTROL


def test_the_opposite_direction_is_an_allowlist_not_our_class(tmp_path):
    """`computed - NAME` — предмет обязан быть внутри перечня: белый список.

    Мерка, не различающая направления, объявила бы членами класса все храповики
    и белые списки дерева — ровно та подмена, против которой написан п. 1 метода
    карточки (дословный урок ADR-1074 и ADR-1096 про мерку по ИМЕНИ).
    """
    assert _role(tmp_path,
                 "KNOWN = {'a', 'b'}\n"
                 "def extra(found):\n"
                 "    return set(found) - KNOWN\n"
                 ) == kmlc.ALLOWLIST


def test_membership_test_over_computed_items_is_an_allowlist(tmp_path):
    assert _role(tmp_path,
                 "KNOWN = {'a': 1, 'b': 2}\n"
                 "def extra(found):\n"
                 "    return [x for x in found if x not in KNOWN]\n"
                 ) == kmlc.ALLOWLIST


def test_a_constant_nobody_compares_is_not_in_the_class(tmp_path):
    assert _role(tmp_path,
                 "KNOWN = {'a': 1, 'b': 2}\n"
                 "def show():\n"
                 "    return sorted(KNOWN)\n"
                 ) == kmlc.NO_COMPARISON


def test_comparison_against_another_literal_is_the_third_outcome(tmp_path):
    """Сверка с ДРУГИМ закрытым литералом роли не называет — это вилка.

    Ноль на неразобранной роли и был бы тем дефектом, против которого написан
    инвариант #17: «не измерено» стало бы неотличимо от «не член».
    """
    assert _role(tmp_path,
                 "KNOWN = {'a', 'b'}\n"
                 "OTHER = {'a', 'c'}\n"
                 "def lost():\n"
                 "    return KNOWN - OTHER\n"
                 ) == kmlc.UNRESOLVED_ROLE


def test_an_inline_literal_operand_is_also_the_third_outcome(tmp_path):
    """РАЗЛИЧАЮЩАЯ сцена: второй операнд — литерал ПРЯМО В ВЫРАЖЕНИИ, не имя.

    Мутация «литерал объявлен ВЫЧИСЛЕННЫМ» ВЫЖИЛА на первом прогоне не из-за
    кода: все сцены подавали второй операнд ИМЕНЕМ, а у `_computed` имя ловит
    ВТОРАЯ ветка (имя из того же модуля — не вычисленное), и снятие первой
    вердикта не меняло. Выжившую мутацию записывают, а не замазывают: сцена
    различителя добавлена, и без неё мера перестаёт отличать «сверка с другим
    литералом» от «сверка с вычисленным предметом».
    """
    assert _role(tmp_path,
                 "KNOWN = {'a', 'b'}\n"
                 "def lost():\n"
                 "    return KNOWN - {'a', 'c'}\n"
                 ) == kmlc.UNRESOLVED_ROLE


def test_one_entry_is_not_a_closed_list(tmp_path):
    entries, _ = kmlc.measure_surface(
        _scene(tmp_path, "KNOWN = {'a': 'ADR-001'}\n"
                         "def lost(found):\n"
                         "    return {k for k in KNOWN if k not in found}\n"),
        ("scripts",))
    assert [e.name for e in entries] == []


# ───────────── объявление источника — свойство ПЕРЕЧНЯ, не МОДУЛЯ ───────────
_TWO_LISTS = (
    "KNOWN = {'a': 'ADR-001', 'b': 'ADR-002'}\n"
    "OTHER = {'c': 'ADR-003', 'd': 'ADR-004'}\n"
    "KNOWN_MEMBERS_SOURCE = {'describes': 'KNOWN', "
    "'generator': {'all': ('x',)}, 'members': {'ADR-001': 'why'}}\n"
    "def lost(found):\n"
    "    a = {k: v for k, v in KNOWN.items() if k not in found}\n"
    "    b = {k: v for k, v in OTHER.items() if k not in found}\n"
    "    return a, b\n"
)


def test_the_declaration_credits_only_the_list_it_describes(tmp_path):
    """Дефект ПЕРВОЙ редакции прибора, найденный его же первым прогоном.

    Признак читался у ФАЙЛА, и сосед по модулю (`SANDBOX_MARKERS` переписи
    производных артефактов) оказался «спрашивающим о своей полноте», которым он
    не является. Ошибка шла в сторону «чисто» — то есть уменьшала население
    класса молча.
    """
    entries, unparsed = kmlc.measure_surface(_scene(tmp_path, _TWO_LISTS), ("scripts",))
    assert not unparsed, unparsed
    assert {e.name for e in entries if e.declares} == {"KNOWN"}
    assert {e.name for e in entries if not e.declares} == {"OTHER"}


def test_a_declaration_without_describes_credits_nobody(tmp_path):
    body = _TWO_LISTS.replace("'describes': 'KNOWN', ", "")
    entries, _ = kmlc.measure_surface(_scene(tmp_path, body), ("scripts",))
    assert {e.name for e in entries if e.declares} == set()


def test_the_adr_axis_separates_the_narrow_class_from_the_broad_form(tmp_path):
    """Класс карточки УЖЕ формы: член рождается ADR-ом (п. 2 метода).

    Перечень обязательных полей без единого ADR внешнего источника полноты не
    имеет ВОВСЕ — реестр решений о нём ответить не может, и числить его членом
    значило бы выдать форму за класс.
    """
    entries, _ = kmlc.measure_surface(
        _scene(tmp_path,
               "WITH_ADR = {'a': 'ADR-001', 'b': 'ADR-002'}\n"
               "NO_ADR = {'c': 'first', 'd': 'second'}\n"
               "def lost(found):\n"
               "    a = {k for k in WITH_ADR if k not in found}\n"
               "    b = {k for k in NO_ADR if k not in found}\n"
               "    return a, b\n"), ("scripts",))
    backed = {e.name: e.adr_backed for e in entries}
    assert backed == {"WITH_ADR": True, "NO_ADR": False}


# ───────────────────────── ВЕРДИКТ: полон / отстал / не измерено ────────────
def _live_declaration() -> tuple[dict, dict[str, str]]:
    rows, unreadable = kmlc.read_registry(REPO)
    assert not unreadable, unreadable
    decl, named, why = kmlc._declaration_of(REPO, "scripts/derived_artifact_census.py")
    assert decl is not None, why
    assert named, "перечень не называет ни одного ADR"
    return decl, rows


def test_the_live_declaration_is_complete_today():
    decl, rows = _live_declaration()
    verdict, detail = kmlc.verdict_for_declaration(
        decl, rows, set(decl["members"]))
    assert verdict == kmlc.COMPLETE, detail


def test_dropping_a_known_member_is_reported_as_lagging_by_name():
    """Положительный контроль, воспроизводящий НАСТОЯЩУЮ находку ADR-1113.

    На вершине `fbb0fa45a` реестр уже нёс строку ADR-1112, а `KNOWN_MEMBERS`
    нёс ТРИ члена — и перепись печатала «все 3 известных члена ВНУТРИ предмета».
    Прибор, не говорящий про такое состояние «ОТСТАЛ, ADR-1112», ОПРОВЕРГНУТ:
    он не находит отставания, которое там БЫЛО.
    """
    decl, rows = _live_declaration()
    short = dict(decl)
    short["members"] = {k: v for k, v in decl["members"].items() if k != "ADR-1112"}
    verdict, detail = kmlc.verdict_for_declaration(
        short, rows, set(short["members"]))
    assert verdict == kmlc.LAGGING, detail
    assert "ADR-1112" in detail


def test_an_unreadable_registry_is_the_third_outcome():
    """И ПРИЧИНА обязана быть о РЕЕСТРЕ, а не о генераторе.

    Мутация «пустой реестр читается как основание для вердикта» ВЫЖИЛА на первом
    прогоне: вердикт `НЕ ИЗМЕРЕНО` оставался тем же, его выдавала СЛЕДУЮЩАЯ
    проверка, и подменялась только ПРИЧИНА — «генератор слеп» вместо «реестр не
    прочитан». Вердикт без верной причины инвариант #17 не выполняет: лечить
    стали бы генератор, а сломан реестр.
    """
    decl, _ = _live_declaration()
    verdict, detail = kmlc.verdict_for_declaration(decl, {}, set(decl["members"]))
    assert verdict == kmlc.UNMEASURED
    assert "реестр" in detail, detail
    assert "генератор" not in detail, detail


def test_a_named_unreadable_registry_file_is_the_third_outcome():
    decl, rows = _live_declaration()
    verdict, detail = kmlc.verdict_for_declaration(
        decl, rows, set(decl["members"]), unreadable=("INDEX.md: нет файла",))
    assert verdict == kmlc.UNMEASURED
    assert "INDEX.md" in detail


def test_a_generator_producing_nothing_is_the_third_outcome():
    decl, rows = _live_declaration()
    blind = dict(decl)
    blind["generator"] = {"all": ("zavedomo-nesushchestvuyushchee-slovo",)}
    verdict, detail = kmlc.verdict_for_declaration(blind, rows, set(decl["members"]))
    assert verdict == kmlc.UNMEASURED
    # Обратная половина различения причин: реестр ПРОЧИТАН, слеп генератор.
    assert "генератор" in detail, detail


def test_a_generator_that_misses_a_declared_member_refutes_the_measure():
    """Генератор обязан производить КАЖДОГО объявленного члена.

    Иначе «приговорены все кандидаты» было бы правдой о пустом пересечении, то
    есть мерка отвечала бы о классе, которого не видела.
    """
    decl, rows = _live_declaration()
    narrow = dict(decl)
    # Генератор НЕ пустой: он производит часть кандидатов (у заголовков со
    # словами «не спрашива») и теряет объявленного члена ADR-1073 — то есть
    # ответил бы «полон» о классе, которого не видел.
    narrow["generator"] = {"all": ("доставк",), "any": ("не спрашива",)}
    verdict, detail = kmlc.verdict_for_declaration(narrow, rows, set(decl["members"]))
    assert verdict == kmlc.UNMEASURED
    assert "опровергнута" in detail


def test_a_declaration_that_drifted_from_its_own_list_is_the_third_outcome():
    """Объявление, отставшее от своего перечня, ответом о перечне не является."""
    decl, rows = _live_declaration()
    verdict, detail = kmlc.verdict_for_declaration(
        decl, rows, set(decl["members"]) | {"ADR-001"})
    assert verdict == kmlc.UNMEASURED
    assert "расходится" in detail


def test_a_verdict_without_a_reason_is_the_third_outcome():
    decl, rows = _live_declaration()
    silent = dict(decl)
    silent["non_members"] = dict(decl["non_members"])
    silent["non_members"][next(iter(silent["non_members"]))] = "  "
    verdict, detail = kmlc.verdict_for_declaration(silent, rows, set(decl["members"]))
    assert verdict == kmlc.UNMEASURED
    assert "без причины" in detail


# ───────────────── реестр живёт в ДВУХ файлах, и это несущее ────────────────
def test_the_registry_is_read_from_both_declared_files():
    """ADR-889 лежит в АРХИВНОЙ части реестра (ADR-1046, номера ≤ 900).

    Прочитать только `INDEX.md` значило бы потерять известного члена молча — то
    есть недосчитать класс, ничего об этом не сказав.
    """
    both, unreadable = kmlc.read_registry(REPO)
    assert not unreadable, unreadable
    only_index, _ = kmlc.read_registry(REPO, ("docs/decisions/INDEX.md",))
    assert "ADR-889" in both
    assert "ADR-889" not in only_index
    assert len(both) > len(only_index)


def test_a_missing_registry_file_is_named_not_silently_zero(tmp_path):
    rows, unreadable = kmlc.read_registry(tmp_path)
    assert rows == {}
    assert len(unreadable) == len(kmlc.REGISTRY_PATHS)
    assert all(u.strip() for u in unreadable)


# ─────────────────────────── коды возврата CLI ──────────────────────────────
def test_a_tree_without_a_subject_exits_zero(tmp_path, capsys):
    _scene(tmp_path, "KNOWN = {'a', 'b'}\n"
                     "def extra(found):\n"
                     "    return set(found) - KNOWN\n")
    entries, unparsed = kmlc.measure_surface(tmp_path, ("scripts",))
    _, code = kmlc.render_surface(tmp_path, entries, unparsed)
    assert code == 0


def test_a_tree_with_a_subject_exits_one(tmp_path):
    _scene(tmp_path, "KNOWN = {'a': 'ADR-001', 'b': 'ADR-002'}\n"
                     "def lost(found):\n"
                     "    return {k for k in KNOWN if k not in found}\n")
    entries, unparsed = kmlc.measure_surface(tmp_path, ("scripts",))
    text, code = kmlc.render_surface(tmp_path, entries, unparsed)
    assert code == 1
    assert "KNOWN" in text


def test_a_missing_named_tree_exits_two(capsys):
    assert kmlc.main(["--repo-root", "/nonexistent/spa/tree", "--surface"]) == 2


def test_the_default_tree_is_printed_not_guessed(capsys):
    kmlc.main(["--surface"])
    assert "дерево НЕ НАЗВАНО" in capsys.readouterr().out


def test_a_tree_with_no_declaration_cannot_produce_a_verdict(tmp_path):
    _scene(tmp_path, "KNOWN = {'a': 'ADR-001', 'b': 'ADR-002'}\n"
                     "def lost(found):\n"
                     "    return {k for k in KNOWN if k not in found}\n")
    entries, _ = kmlc.measure_surface(tmp_path, ("scripts",))
    text, code = kmlc.render_verdicts(tmp_path, entries)
    assert code == 2
    assert kmlc.UNMEASURED in text or "НЕ ИЗМЕРЕНО" in text


def test_an_unparsable_file_is_named_not_counted_as_clean(tmp_path):
    _scene(tmp_path, "KNOWN = {'a': 'ADR-001',\n")
    entries, unparsed = kmlc.measure_surface(tmp_path, ("scripts",))
    assert entries == []
    assert len(unparsed) == 1 and unparsed[0].strip()


# ───────────────── живое дерево: перечень СПРАШИВАЕТ о полноте ──────────────
def test_the_live_known_member_list_declares_its_completeness_source():
    entries, unparsed = kmlc.measure_surface(REPO)
    assert not unparsed, unparsed[:3]
    asking = {(e.path, e.name) for e in entries if e.declares}
    assert ("scripts/derived_artifact_census.py", "KNOWN_MEMBERS") in asking


def test_the_live_subject_is_a_fork_and_every_member_is_named():
    """Население — ЧИСЛО с вилкой, а не проза, и вилка названа поимённо."""
    entries, unparsed = kmlc.measure_surface(REPO)
    text, _ = kmlc.render_surface(REPO, entries, unparsed)
    assert "ВИЛКА населения предмета" in text
    unres = [e for e in entries if e.role == kmlc.UNRESOLVED_ROLE]
    for e in unres:
        assert f"{e.path}::{e.name}" in text


# ──────────────────────────── проба приёмки карточки ────────────────────────
def test_the_card_probe_is_registered_and_satisfied():
    from spa_core.monitoring import card_acceptance as ca
    name = "known_member_list_completeness_is_asked"
    assert name in ca.PROBES
    status, detail = ca.PROBES[name](None)
    assert status == ca.SATISFIED, detail


def test_the_card_probe_refuses_an_argument():
    from spa_core.monitoring import card_acceptance as ca
    status, detail = ca.PROBES["known_member_list_completeness_is_asked"]("x.md")
    assert status == ca.UNMEASURED
    assert detail.strip()


def test_the_card_probe_fails_when_the_instrument_is_absent(tmp_path):
    """Контроль пробы: порвано звено «прибор есть» ⇒ критерий НЕ ВЫПОЛНЕН."""
    from spa_core.monitoring import card_acceptance as ca
    status, detail = ca._probe_known_member_list_completeness_is_asked(
        None, repo_root=str(tmp_path))
    assert status == ca.NOT_SATISFIED
    assert "known_member_list_census.py" in detail


def _probe_scene(tmp_path: pathlib.Path, patch: tuple[str, str] | None = None,
                 census: str | None = None) -> str:
    """Одноразовое дерево для пробы: реестр и перепись НАСТОЯЩИЕ, прибор — под правкой."""
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "docs" / "decisions").mkdir(parents=True, exist_ok=True)
    for rel in kmlc.REGISTRY_PATHS:
        (tmp_path / rel).write_text((REPO / rel).read_text(encoding="utf-8"),
                                    encoding="utf-8")
    tool = _TOOL.read_text(encoding="utf-8")
    if patch is not None:
        old_s, new_s = patch
        assert tool.count(old_s) == 1, "якорь правки не уникален"
        tool = tool.replace(old_s, new_s)
    (tmp_path / "scripts" / "known_member_list_census.py").write_text(
        tool, encoding="utf-8")
    body = census if census is not None else (
        REPO / "scripts" / "derived_artifact_census.py").read_text(encoding="utf-8")
    (tmp_path / "scripts" / "derived_artifact_census.py").write_text(
        body, encoding="utf-8")
    return str(tmp_path)


def test_the_card_probe_refuses_an_instrument_blind_to_direction(tmp_path):
    """Контроль пробы: прибор, не различающий НАПРАВЛЕНИЕ сверки ⇒ НЕ ВЫПОЛНЕН.

    Мутация «проба: контроль обратного направления снят» ВЫЖИЛА на первом
    прогоне: на ИСПРАВНОМ приборе условие не срабатывает никогда, а сломанным
    прибором пробу не кормил ни один тест. Дыра МОЕГО покрытия, не кода.
    """
    from spa_core.monitoring import card_acceptance as ca
    # Якорь переставлен циклом #1261 вместе с рефакторингом `classify_role`:
    # обход сверок вынесен в ЕДИНСТВЕННУЮ дверь `comparison_sites`, и прежней
    # строки `if positive:` в приборе больше нет. Мутация та же ПО ДЕЙСТВИЮ —
    # вердикт перестаёт зависеть от НАПРАВЛЕНИЯ сверки и становится
    # `positive_control` при любой сверке, то есть белый список зачитывается
    # нашим классом. Проверка НЕ ослаблена: контроль по-прежнему кормит пробу
    # прибором, слепым к направлению, и требует НЕ ВЫПОЛНЕН.
    root = _probe_scene(tmp_path, patch=(
        "        if role in votes:",
        "        if votes:"))
    status, detail = ca._probe_known_member_list_completeness_is_asked(
        None, repo_root=root)
    assert status == ca.NOT_SATISFIED, detail
    assert "белый список" in detail or "направлени" in detail, detail


def test_the_card_probe_refuses_an_instrument_that_never_says_lagging(tmp_path):
    """Контроль пробы: прибор, не умеющий сказать ОТСТАЛ ⇒ НЕ ВЫПОЛНЕН.

    Та же дыра покрытия с другой стороны (мутация «проба: контроль ОТСТАВАНИЯ
    снят» выжила): на исправном приборе условие не срабатывает, и пробу надо
    кормить прибором, который отставание потерял.
    """
    from spa_core.monitoring import card_acceptance as ca
    root = _probe_scene(tmp_path, patch=(
        "    unjudged = [c for c in candidates if c not in members "
        "and c not in non_members]",
        "    unjudged = []"))
    status, detail = ca._probe_known_member_list_completeness_is_asked(
        None, repo_root=root)
    assert status == ca.NOT_SATISFIED, detail
    assert "ADR-1112" in detail, detail


def test_the_card_probe_fails_when_the_declaration_is_gone(tmp_path):
    """Контроль пробы: перепись БЕЗ объявления источника ⇒ НЕ ВЫПОЛНЕН.

    Это ровно состояние дерева ДО этого цикла, и проба обязана его отвергать —
    иначе критерий зелен ПО ПОСТРОЕНИЮ, как и сам перечень до ADR-1113.
    """
    from spa_core.monitoring import card_acceptance as ca
    (tmp_path / "scripts").mkdir()
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    for rel in kmlc.REGISTRY_PATHS:
        (tmp_path / rel).write_text((REPO / rel).read_text(encoding="utf-8"),
                                    encoding="utf-8")
    (tmp_path / "scripts" / "known_member_list_census.py").write_text(
        _TOOL.read_text(encoding="utf-8"), encoding="utf-8")
    census = (REPO / "scripts" / "derived_artifact_census.py").read_text(
        encoding="utf-8")
    head, _, _ = census.partition("KNOWN_MEMBERS_SOURCE = {")
    (tmp_path / "scripts" / "derived_artifact_census.py").write_text(
        head, encoding="utf-8")
    status, detail = ca._probe_known_member_list_completeness_is_asked(
        None, repo_root=str(tmp_path))
    assert status == ca.NOT_SATISFIED
    assert "НЕ СПРАШИВАЕТСЯ" in detail or "не объявила" in detail


# ═════════════════════════════════════════════════════════════════════════════
# ТРЕТЬЯ ПОЛОВИНА (`--sources`, ADR-1115): есть ли у перечня ФОРМЫ внешний
# источник полноты ВООБЩЕ. Заказ G1089 п. 2 запретил выдумывать мерку до того,
# как задан этот вопрос, и замер его подтвердил: признак «операнд приходит
# извне» НЕОБХОДИМ, но НЕ ДОСТАТОЧЕН — из 10 кандидатов ручной приговор
# подтвердил ДВА.
#
# Положительный контроль у каждого теста ниже — либо НАСТОЯЩИЙ сайт дерева
# (четыре замеренных руками, п. 4 метода карточки: прибор, не воспроизводящий
# ручной замер, ОПРОВЕРГНУТ), либо дефект ПЕРВОЙ редакции этой половины:
#   · порог MIN_ENTRIES не был общим с `measure_surface`, и 3 перечня из 157
#     выпали в «НЕ ИЗМЕРЕНО» — нашёл это собственный счётчик 154 ≠ 157;
#   · ведро звалось «источник ЕСТЬ» и зачло `sys.modules` источником полноты —
#     ошибка в сторону НАХОДКИ.
# ═════════════════════════════════════════════════════════════════════════════
def _sources(tmp_path: pathlib.Path, body: str):
    """Сцена → (вердикты провенанса, причины НЕ ИЗМЕРЕНО)."""
    root = _scene(tmp_path, body)
    entries, _ = kmlc.measure_surface(root)
    return kmlc.measure_sources(root, entries)


def test_an_operand_read_from_a_file_is_a_candidate_not_a_verdict(tmp_path):
    """Дверь наружу в привязке операнда ⇒ кандидат `external_read`."""
    v, unm = _sources(tmp_path, '''
import json, pathlib
REQUIRED = ("a", "b")
def check(p):
    stored = json.loads(pathlib.Path(p).read_text())
    return [k for k in REQUIRED if k not in stored]
''')
    assert unm == []
    assert [(x.name, x.provenance) for x in v] == [("REQUIRED", kmlc.EXTERNAL_READ)]
    assert kmlc.EXTERNAL_READ in kmlc.OPERAND_FROM_OUTSIDE


def test_a_door_inside_the_operand_itself_outranks_any_binding(tmp_path):
    """`NAME - set(json.load(f))`: дверь в САМОМ операнде сильнее имён."""
    v, _ = _sources(tmp_path, '''
import json
REQUIRED = ("a", "b")
def check(f):
    return REQUIRED - set(json.load(f))
''')
    assert [x.provenance for x in v] == [kmlc.EXTERNAL_READ]


def test_an_imported_operand_is_a_candidate(tmp_path):
    v, _ = _sources(tmp_path, '''
import other
REQUIRED = ("a", "b")
def check():
    return REQUIRED - other.LIVE
''')
    assert [x.provenance for x in v] == [kmlc.IMPORTED]


def test_a_parameter_operand_names_the_callers_contract_not_this_module(tmp_path):
    """Настоящая форма `architect_contract.validate_output(doc)`."""
    v, _ = _sources(tmp_path, '''
REQUIRED = ("a", "b")
def validate(doc):
    for s in REQUIRED:
        if s not in doc:
            raise ValueError(s)
''')
    assert [x.provenance for x in v] == [kmlc.PARAMETER]
    assert "КОНТРАКТ зовущего" in v[0].detail


def test_a_module_local_operand_is_not_an_external_source(tmp_path):
    """Настоящая форма `registry.validate_registry` — сверка со своим модулем."""
    v, _ = _sources(tmp_path, '''
META = {"x": {"module": 1}}
REQUIRED = {"module", "class"}
def check():
    out = []
    for k, meta in META.items():
        out.append(REQUIRED - set(meta.keys()))
    return out
''')
    assert [x.provenance for x in v] == [kmlc.MODULE_LOCAL]
    assert kmlc.MODULE_LOCAL not in kmlc.OPERAND_FROM_OUTSIDE


def test_a_string_operand_means_completeness_is_not_a_defined_question(tmp_path):
    """Настоящая форма `agent_quarantine.check_protected` — поиск ПОДСТРОКИ.

    У строки нет элементов: объявить такой перечень «неполным» значило бы родить
    находку, которой в мире нет. Поэтому ведро существует отдельно и НЕ является
    находкой (код возврата это проверяет ниже).
    """
    v, _ = _sources(tmp_path, '''
WORDS = ("kill", "risk")
def check(label, entry):
    hay = f"{label} {entry.get('role','')}".lower()
    for w in WORDS:
        if w in hay:
            raise ValueError(w)
''')
    assert [x.provenance for x in v] == [kmlc.HAYSTACK]
    assert kmlc.HAYSTACK in kmlc.NO_QUESTION
    assert kmlc.HAYSTACK not in kmlc.OPERAND_FROM_OUTSIDE


def test_two_different_bindings_are_the_third_outcome_not_a_chosen_side(tmp_path):
    """Разные привязки ⇒ `several`: выбрать сторону значило бы угадать.

    Выбрать «внешний» пригласило бы мерку туда, где её, возможно, не определить;
    выбрать «нет источника» — списать настоящий пробел. Ни одна ошибка не честнее.
    """
    v, _ = _sources(tmp_path, '''
import json, other
REQUIRED = ("a", "b")
def one(p):
    stored = json.loads(p.read_text())
    return [k for k in REQUIRED if k not in stored]
def two():
    return REQUIRED - other.LIVE
''')
    assert [x.provenance for x in v] == [kmlc.SEVERAL]
    assert v[0].sites == 2
    assert kmlc.EXTERNAL_READ in v[0].detail and kmlc.IMPORTED in v[0].detail


def test_an_unbound_operand_is_unresolved_not_silently_local(tmp_path):
    v, _ = _sources(tmp_path, '''
REQUIRED = ("a", "b")
def check():
    return REQUIRED - mystery
''')
    assert [x.provenance for x in v] == [kmlc.PROV_UNRESOLVED]


def test_every_form_member_gets_exactly_one_bucket(tmp_path):
    """Вёдра ИСЧЕРПЫВАЮТ форму: сумма по вёдрам равна числу перечней формы.

    Дефект первой редакции был ровно здесь: порог MIN_ENTRIES не совпадал с
    `measure_surface`, и трое выпадали в «НЕ ИЗМЕРЕНО» — счётчик показал 154
    против 157, и это нашла не вычитка, а сама строка итога.
    """
    root = _scene(tmp_path, '''
import json
AB = ("a", "b")
def check(p):
    stored = json.loads(p.read_text())
    return [k for k in AB if k not in stored]
''')
    entries, _ = kmlc.measure_surface(root)
    form = [e for e in entries
            if e.role == kmlc.POSITIVE_CONTROL and not e.declares]
    verdicts, unmeasured = kmlc.measure_sources(root, entries)
    assert len(verdicts) + len(unmeasured) == len(form) == 1
    assert sum(1 for v in verdicts if v.provenance in kmlc.PROVENANCES) == len(verdicts)


def test_a_short_literal_operand_is_judged_by_both_halves_alike(tmp_path):
    """Порог MIN_ENTRIES ОБЩИЙ у половин — положительный контроль на тот дефект.

    РАЗЛИЧАЮЩАЯ сцена, и первая редакция теста ею НЕ БЫЛА: мутация «порог у
    половин снова РАЗНЫЙ» на ней ВЫЖИЛА (замер #1261, M06). Сцена с операндом
    `json.loads(...)` вердикта не меняет — корень операнда не является закрытым
    литералом, поэтому шире `closed` или уже, роль воспроизводится одинаково.
    Различает только операнд, который САМ есть короткий закрытый литерал: при
    общем пороге `SHORT` (1 элемент) в `closed` НЕ входит ⇒ операнд считается
    ВЫЧИСЛЕННЫМ ⇒ роль `positive_control` воспроизводится; при разошедшемся
    пороге `SHORT` попадает в `closed`, операнд перестаёт быть вычисленным, и
    вторая половина докладывает НЕ ИЗМЕРЕНО о перечне, который первая числит
    предметом.
    """
    root = _scene(tmp_path, 'SHORT = ("q",)\nPAIR = ("a", "b")\n'
                            'def check():\n    return PAIR - SHORT\n')
    entries, _ = kmlc.measure_surface(root)
    form = [e for e in entries
            if e.role == kmlc.POSITIVE_CONTROL and not e.declares]
    assert [e.name for e in form] == ["PAIR"], [e.name for e in form]
    verdicts, unmeasured = kmlc.measure_sources(root, entries)
    assert unmeasured == [], unmeasured
    assert [(v.name, v.provenance) for v in verdicts] == [("PAIR", kmlc.MODULE_LOCAL)]


def test_the_role_and_the_provenance_read_the_same_comparisons(tmp_path):
    """ОДНА дверь к сверкам: роль `positive_control` ⟺ есть второй операнд.

    Своя копия обхода у второй половины означала бы, что половины судят о РАЗНЫХ
    наборах сверок, а счётчики при этом складываются — расхождение было бы молчаливым.
    """
    import ast as _ast
    body = '''
import json, other
A = ("a", "b")
B = ("c", "d")
C = ("e", "f")
def f(p, doc):
    stored = json.loads(p.read_text())
    x = [k for k in A if k not in stored]
    y = B - other.LIVE
    z = "e" in C
    return x, y, z
'''
    tree = _ast.parse(body)
    closed = {"A", "B", "C"}
    for name in sorted(closed):
        sites = kmlc.comparison_sites(tree, name, closed)
        role = kmlc.classify_role(tree, name, closed)
        positive = [op for vote, op in sites
                    if vote == kmlc.POSITIVE_CONTROL and op is not None]
        assert (role == kmlc.POSITIVE_CONTROL) == bool(positive), (name, role)


def test_the_four_hand_measured_sites_are_reproduced(tmp_path):
    """НАСТОЯЩАЯ история, а не выдуманная сцена (п. 4 метода карточки).

    Четыре сайта дерева прочитаны руками ДО написания классификатора, и прибор
    обязан воспроизвести все четыре. Не воспроизводит — ОПРОВЕРГНУТ: он отвечает
    не о том мире, в котором живёт.
    """
    hand = {
        "scripts/cartographer/brief.py::REQUIRED_DIFF_KEYS": kmlc.EXTERNAL_READ,
        "scripts/agent_quarantine.py::PROTECTED_WORDS": kmlc.HAYSTACK,
        "scripts/cartographer/architect_contract.py::REQUIRED_SECTIONS": kmlc.PARAMETER,
        "spa_core/adapters/registry.py::_REQUIRED_KEYS": kmlc.MODULE_LOCAL,
    }
    missing = [rel.split("::")[0] for rel in hand
               if not (REPO / rel.split("::")[0]).is_file()]
    if missing:
        pytest.fail("НЕ ИЗМЕРЕНО: сайтов ручного замера нет в дереве: "
                    f"{missing} — это предпосылка теста, а не вердикт о приборе")
    entries, _ = kmlc.measure_surface(REPO)
    got = {f"{v.path}::{v.name}": v.provenance
           for v in kmlc.measure_sources(REPO, entries)[0]}
    for key, want in hand.items():
        assert got.get(key) == want, (key, want, got.get(key))


def test_a_candidate_without_a_sentence_is_a_finding(monkeypatch, tmp_path):
    """Выросший кандидат БЕЗ приговора — находка, а не молчание.

    Это тот же механизм, который ADR-1113 нашёл сломанным у соседа: закрытый
    перечень, не спрашивающий о своей полноте, зелен ПО ПОСТРОЕНИЮ.
    """
    v = [kmlc.SourceVerdict("scripts/m.py", "NEW", 3, kmlc.EXTERNAL_READ, "д", 1)]
    monkeypatch.setattr(kmlc, "ADJUDICATED", {})
    text, code = kmlc.render_sources(tmp_path, v, [])
    assert code == 1
    assert "КАНДИДАТ БЕЗ ПРИГОВОРА" in text and "scripts/m.py::NEW" in text


def test_a_sentence_without_a_candidate_is_named_as_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(kmlc, "ADJUDICATED",
                        {"scripts/gone.py::OLD": (kmlc.REJECTED, "причина")})
    text, code = kmlc.render_sources(tmp_path, [], [])
    assert code == 1
    assert "ПРИГОВОР УСТАРЕЛ" in text and "scripts/gone.py::OLD" in text


def test_a_rejected_candidate_is_not_a_finding(monkeypatch, tmp_path):
    """ОТКЛОНЁННЫЙ кандидат мерки НЕ требует — иначе прибор рождал бы находки.

    Обратная половина обязательна: подтверждённый источник, которого никто не
    спрашивает, находкой БЫТЬ ОБЯЗАН, иначе половина молчит всегда.
    """
    v = [kmlc.SourceVerdict("scripts/m.py", "X", 3, kmlc.EXTERNAL_READ, "д", 1)]
    monkeypatch.setattr(kmlc, "ADJUDICATED",
                        {"scripts/m.py::X": (kmlc.REJECTED, "стог, не контракт")})
    _, code = kmlc.render_sources(tmp_path, v, [])
    assert code == 0

    monkeypatch.setattr(kmlc, "ADJUDICATED",
                        {"scripts/m.py::X": (kmlc.CONFIRMED, "писатель объявил контракт")})
    text, code = kmlc.render_sources(tmp_path, v, [])
    assert code == 1
    assert kmlc.CONFIRMED in text


def test_a_string_bucket_alone_exits_zero(monkeypatch, tmp_path):
    """Ведро «ВОПРОСА НЕТ» одно по себе кодом 1 не становится."""
    v = [kmlc.SourceVerdict("scripts/m.py", "W", 3, kmlc.HAYSTACK, "строка", 1)]
    monkeypatch.setattr(kmlc, "ADJUDICATED", {})
    text, code = kmlc.render_sources(tmp_path, v, [])
    assert code == 0
    assert "ВОПРОСА О ПОЛНОТЕ НЕТ" in text


def test_an_unreadable_scene_is_the_third_outcome_not_zero(tmp_path):
    """Нечитаемый файл при пустом замере — НЕ ИЗМЕРЕНО (код 2), не «чисто»."""
    text, code = kmlc.render_sources(tmp_path, [], ["scripts/x.py: SyntaxError"])
    assert code == 2
    assert "НЕ ИЗМЕРЕНО" in text


def test_the_two_halves_agree_on_the_live_tree():
    """Вёдра ИСЧЕРПЫВАЮТ форму на ЖИВОМ дереве, и НЕ ИЗМЕРЕНО там пусто.

    Это тот самый счётчик, который нашёл дефект первой редакции: половины
    разошлись порогом `MIN_ENTRIES`, и строка итога показала **154 против 157**.
    Нужен он и как контроль ПОВЕРХНОСТИ: расширь `measure_sources` на белые
    списки — и они, не давая ни одного операнда роли `positive_control`, уедут
    в НЕ ИЗМЕРЕНО, то есть прибор начнёт докладывать «судить было нечем» о
    перечнях, которых его вопрос не касается вовсе (мутация M15 замера #1261
    ВЫЖИЛА ровно на отсутствии этой проверки — дыра МОЕГО покрытия, не кода).
    """
    entries, surface_unparsed = kmlc.measure_surface(REPO)
    form = [e for e in entries
            if e.role == kmlc.POSITIVE_CONTROL and not e.declares]
    verdicts, unmeasured = kmlc.measure_sources(REPO, entries)
    assert unmeasured == [], unmeasured
    assert len(verdicts) == len(form), (len(verdicts), len(form))
    assert all(v.provenance in kmlc.PROVENANCES for v in verdicts)
    # поверхность третьей половины — РОВНО форма, ни шире, ни уже
    assert {f"{v.path}::{v.name}" for v in verdicts} == \
        {f"{e.path}::{e.name}" for e in form}


def test_the_live_tree_has_every_candidate_sentenced():
    """На живом дереве приговорён КАЖДЫЙ кандидат, и приговоры не устарели."""
    entries, _ = kmlc.measure_surface(REPO)
    verdicts, _ = kmlc.measure_sources(REPO, entries)
    keys = {f"{v.path}::{v.name}" for v in verdicts
            if v.provenance in kmlc.OPERAND_FROM_OUTSIDE}
    assert keys - set(kmlc.ADJUDICATED) == set(), "кандидат без приговора"
    assert set(kmlc.ADJUDICATED) - keys == set(), "приговор без кандидата"
    assert all(kmlc.ADJUDICATED[k][1].strip() for k in kmlc.ADJUDICATED), \
        "приговор без причины приговором не является"


def test_the_sources_half_does_not_drag_the_other_two(tmp_path, capsys):
    """`--sources` отвечает на СВОЙ вопрос и печатает выбор дерева."""
    _scene(tmp_path, 'A = ("a", "b")\n')
    code = kmlc.main(["--sources", "--repo-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert "ВНЕШНИЙ ИСТОЧНИК ПОЛНОТЫ" in out
    assert "ВЕРДИКТ по объявившим источник" not in out
    assert str(tmp_path) in out
    assert code in (0, 1, 2)
