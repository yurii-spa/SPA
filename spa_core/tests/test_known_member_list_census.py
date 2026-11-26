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
    root = _probe_scene(tmp_path, patch=(
        "    if positive:\n        return POSITIVE_CONTROL",
        "    if True:\n        return POSITIVE_CONTROL"))
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
