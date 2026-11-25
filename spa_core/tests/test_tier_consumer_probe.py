"""Контроль пробы `tier_consumer_measure_judges_role_not_name` — в ОБЕ стороны.

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется только с тестом, где
она ЗЕЛЕНА на целом контуре и КРАСНА на каждом порванном звене — с названным
звеном; и где она НЕ проходит подстрокой (ADR-333).

Предмет пробы — мера потребления отчёта тир-куратора (ADR-1096, карточка
`inbox-storozh-tira-sudit-podstrokoi-imya-kurat`). Звеньев шесть, и каждое рвётся
здесь СВОЕЙ сценой: дверь не ввезена · мера слепа к роли данных · мера кусается на
всём · третий исход проглочен · сторож не зовёт дверь (в том числе когда ввоз стои́т
ПРОЗОЙ) · у сторожа своя копия ролей · перечень `allowed` вырос · сторож красен ·
узла сторожа нет вовсе.

Живое дерево ничем не трогается: сцены — одноразовые каталоги, а подмена двери
живёт ровно на время сцены (`monkeypatch`, § «СОСЕД ПО ПРОЦЕССУ»
`.claude/rules/deployment.md`: подмена, пережившая сцену, есть дефект даже когда
зелена).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from spa_core import monitoring as monitoring_pkg
from spa_core.monitoring import tier_report_consumption as real_door
from spa_core.monitoring.card_acceptance import (
    NOT_SATISFIED,
    PROBES,
    SATISFIED,
    TIER_ALLOWED_CEILING,
    TIER_CONSUMPTION_SCENES,
    UNMEASURED,
)

PROBE_NAME = "tier_consumer_measure_judges_role_not_name"
DOOR_MODULE = "spa_core.monitoring.tier_report_consumption"
REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_REL = "spa_core/tests/test_tier_curator.py"
NODE = "test_no_module_consumes_report_to_mutate_tiers"


def _probe(**kw):
    return PROBES[PROBE_NAME](None, **kw)


def _swap_door(monkeypatch, stub) -> None:
    """Подменить дверь ТАМ, ГДЕ её берёт проба — у атрибута пакета.

    Первая редакция этих сцен правила только `sys.modules`, и подмена до пробы НЕ
    ДОХОДИЛА: `from spa_core.monitoring import tier_report_consumption` читает
    АТРИБУТ пакета, а в `sys.modules` заглядывает лишь когда атрибута нет. Шесть
    сцен при этом не краснели и не падали — они МОЛЧА мерили настоящую дверь и
    отвечали «satisfied», то есть контроль существовал и предмета не видел
    (`.claude/rules/deployment.md`: «проверять надо не „есть ли параметр", а все
    ли двери закрыты для того пути, который идёт тест»).

    Подмена живёт ровно на время сцены: `monkeypatch` возвращает оба места сам.
    """
    monkeypatch.setattr(monitoring_pkg, "tier_report_consumption", stub)
    monkeypatch.setitem(sys.modules, DOOR_MODULE, stub)


def _guard_tree(tmp_path: Path, body: str) -> Path:
    """Одноразовое дерево с ОДНИМ файлом сторожа — ровно то, что проба читает."""
    path = tmp_path / GUARD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return tmp_path


#: Сторож-минимум: ввозит дверь разбором, перечень в пределе, нужный узел ЗЕЛЕН.
#: Сцены ниже портят в нём РОВНО по одному звену — иначе красный не называл бы, что
#: именно порвано.
HEALTHY_GUARD = f'''
from spa_core.monitoring.tier_report_consumption import consumes_report
allowed = {{"a", "b", "c", "d"}}


def {NODE}():
    assert consumes_report("P = 'data/tier_curator_report.json'\\n")
'''


@pytest.fixture()
def child_can_import(monkeypatch):
    """Ребёнок-`pytest` обязан видеть пакет: дерево сцены его не содержит.

    Без этого «сторож КРАСЕН» было бы неотличимо от «пакет не ввезён», и проба
    отвечала бы верным словом о неверной причине.
    """
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))


# ─────────────────────────── целый контур ────────────────────────────────────

def test_probe_is_green_on_the_live_contour():
    """На ЖИВОМ дереве проба зелена, и вердикт даёт прогон сторожа, а не проза."""
    status, why = _probe(repo_root=str(REPO_ROOT))
    assert status == SATISFIED, why
    assert "по РОЛИ вхождения" in why
    assert "ЗЕЛЕН прогоном" in why


def test_probe_refuses_an_argument_it_has_no_meaning_for():
    status, why = _probe(repo_root=str(REPO_ROOT))
    assert status == SATISFIED, why
    status, why = PROBES[PROBE_NAME]("spa_core/x.py", repo_root=str(REPO_ROOT))
    assert status == UNMEASURED
    assert "не принимает аргумента" in why


# ─────────────────── звено 1: двери меры нет вовсе ───────────────────────────

def test_broken_link_door_not_importable_is_unmeasured(monkeypatch):
    monkeypatch.delattr(monitoring_pkg, "tier_report_consumption")
    monkeypatch.setitem(sys.modules, DOOR_MODULE, None)
    status, why = _probe(repo_root=str(REPO_ROOT))
    assert status == UNMEASURED, why
    assert "дверь меры tier_report_consumption не ввезена" in why


def test_broken_link_door_without_its_api_is_unmeasured(monkeypatch):
    """Дверь есть, а мерить нечем — это НЕ «потребления нет» (инв. #17)."""
    stub = types.ModuleType(DOOR_MODULE)
    stub.consumes_report = lambda text: False
    _swap_door(monkeypatch, stub)
    status, why = _probe(repo_root=str(REPO_ROOT))
    assert status == UNMEASURED, why
    assert "у двери меры нет `mentions`" in why


# ─────────────────── звенья 2–3: мера и её третий исход ──────────────────────

def _stub_door(consumes):
    stub = types.ModuleType(DOOR_MODULE)
    stub.TierReportConsumptionUnmeasured = real_door.TierReportConsumptionUnmeasured
    stub.mentions = real_door.mentions
    stub.consumes_report = consumes
    return stub


def test_broken_link_measure_blind_to_the_data_role_names_the_scene(monkeypatch):
    """Мера, кусающаяся на ВСЁМ, — прежняя подстрока; проба обязана назвать сцену."""
    _swap_door(monkeypatch, _stub_door(lambda text: True))
    status, why = _probe(repo_root=str(REPO_ROOT))
    assert status == NOT_SATISFIED, why
    assert "голое имя элементом словаря" in why
    assert "сочтена потреблением" in why


def test_broken_link_measure_blind_to_consumption_names_the_scene(monkeypatch):
    """Мера, молчащая на ВСЁМ, зелена у проверки «молчит» и красна здесь."""
    _swap_door(monkeypatch, _stub_door(lambda text: False))
    status, why = _probe(repo_root=str(REPO_ROOT))
    assert status == NOT_SATISFIED, why
    assert "сочтена данными" in why


def test_broken_link_third_outcome_swallowed_is_not_satisfied(monkeypatch):
    """Неразбираемое, проглоченное молча, — ложный зелёный, и проба его видит."""
    def swallow(text: str) -> bool:
        try:
            return real_door.consumes_report(text)
        except real_door.TierReportConsumptionUnmeasured:
            return True                       # «строго», но БЕЗ третьего исхода
    _swap_door(monkeypatch, _stub_door(swallow))
    status, why = _probe(repo_root=str(REPO_ROOT))
    assert status == NOT_SATISFIED, why
    assert "проглочен молча" in why


def test_broken_link_third_outcome_without_words_is_not_satisfied(monkeypatch):
    """Третий исход без слов «НЕ ИЗМЕРЕНО» вызывающий не отличит от вердикта."""
    def mute(text: str) -> bool:
        try:
            return real_door.consumes_report(text)
        except real_door.TierReportConsumptionUnmeasured as exc:
            raise real_door.TierReportConsumptionUnmeasured("syntax") from exc
    _swap_door(monkeypatch, _stub_door(mute))
    status, why = _probe(repo_root=str(REPO_ROOT))
    assert status == NOT_SATISFIED, why
    assert "без слов «НЕ ИЗМЕРЕНО»" in why


# ─────────────── звенья 4–5: проводка сторожа и его копия правила ────────────

def test_broken_link_guard_does_not_call_the_door(tmp_path):
    root = _guard_tree(tmp_path, f"allowed = {{'a'}}\n\n\ndef {NODE}():\n    pass\n")
    status, why = _probe(repo_root=str(root))
    assert status == NOT_SATISFIED, why
    assert "НЕ ввозит дверь меры" in why


def test_the_probe_does_not_pass_by_substring(tmp_path):
    """ADR-333: ввоз ПРОЗОЙ проводкой не является.

    Дословное имя двери стои́т в файле дважды — в докстроке и в строке-сообщении, —
    и подстрочная проверка объявила бы проводку исправной. Проба спрашивает разбор.
    """
    body = (
        '"""Сторож зовёт spa_core.monitoring.tier_report_consumption."""\n'
        'MSG = "from spa_core.monitoring.tier_report_consumption import consumes_report"\n'
        f"allowed = {{'a'}}\n\n\ndef {NODE}():\n    pass\n")
    root = _guard_tree(tmp_path, body)
    status, why = _probe(repo_root=str(root))
    assert status == NOT_SATISFIED, why
    assert "НЕ ввозит дверь меры" in why
    assert "не подстрокой" in why


def test_broken_link_guard_keeps_its_own_copy_of_the_roles(tmp_path):
    body = HEALTHY_GUARD + '\nROLES = ("report_path", "assembled_path")\n'
    root = _guard_tree(tmp_path, body)
    status, why = _probe(repo_root=str(root))
    assert status == NOT_SATISFIED, why
    assert "своя копия перечня РОЛЕЙ" in why


def test_the_closed_scene_list_keeps_both_polarities_and_the_measured_defect():
    """Содержание закрытого перечня сцен ЗАКРЕПЛЕНО, а не только его обход.

    Дыру нашёл мутационный замер #1241: снять из перечня сцену роли ДАННЫХ можно
    было молча — обход честно проходил по тому, что осталось, и проба отвечала
    `satisfied`. Перечень, у которого проверяется только обход, сокращается в
    тишине до набора, который мера проходит и так.

    Закрепляются три вещи: обе полярности присутствуют (мера, зелёная всегда,
    обязана падать хотя бы на одной сцене) и ДОСЛОВНАЯ сцена измеренного дефекта
    25.11 — имя элементом кортежа ключевых слов `cadence_census.py:302`. Её
    исчезновение вернуло бы класс, из-за которого ADR-1096 и написан.
    """
    expectations = {expected for _, expected, _ in TIER_CONSUMPTION_SCENES}
    assert expectations == {True, False}, (
        f"перечень сцен потерял полярность ({expectations}) — мера, отвечающая "
        f"одинаково на всё, прошла бы его насквозь")

    data_scenes = [src for _, expected, src in TIER_CONSUMPTION_SCENES if not expected]
    assert any('("tier_curator", "tier_"' in s for s in data_scenes), (
        "из перечня ушла ДОСЛОВНАЯ сцена дефекта 25.11 (имя элементом кортежа "
        "ключевых слов) — без неё класс ADR-1096 возвращается молча")

    consuming_scenes = [src for _, expected, src in TIER_CONSUMPTION_SCENES if expected]
    assert any(s.startswith("import ") for s in consuming_scenes), (
        "из перечня ушла сцена ПЛОСКОГО ввоза (`ast.Import` — узел, отличный от "
        "`ast.ImportFrom`); её отсутствие и было дырой, найденной мутацией M05")


def test_the_allowed_ceiling_is_a_ratchet_and_may_only_shrink():
    """Потолок `allowed` — ЧИСЛО с замером, и сцены ниже его не охраняют.

    Дыру нашёл мутационный замер #1241: сцена «перечень вырос» строит набор из
    `TIER_ALLOWED_CEILING + 1`, поэтому ПОДНЯТЫЙ потолок она пропускает молча —
    мерка выведена из того, что меряет. Замер 25.11 ПОСЛЕ ADR-1096: имён **4**
    (было пять, ушёл `monitoring/tier_touch.py`). Число может только УМЕНЬШАТЬСЯ;
    поднять его значит погасить падение именем, а не мерой (инв. #16).
    """
    assert TIER_ALLOWED_CEILING == 4, (
        f"потолок `allowed` стал {TIER_ALLOWED_CEILING}: вверх он не ходит — "
        f"починить меру и ОПУСТИТЬ потолок, а не поднять его")


def test_broken_link_allowed_list_grew_instead_of_the_measure(tmp_path):
    """Инв. #16 по исходу: падение гасят именем — проба обязана это назвать."""
    grown = ", ".join(f'"n{i}"' for i in range(TIER_ALLOWED_CEILING + 1))
    body = HEALTHY_GUARD.replace('allowed = {"a", "b", "c", "d"}',
                                 f"allowed = {{{grown}}}")
    root = _guard_tree(tmp_path, body)
    status, why = _probe(repo_root=str(root))
    assert status == NOT_SATISFIED, why
    assert f"вырос до {TIER_ALLOWED_CEILING + 1} имён" in why


def test_broken_link_allowed_list_absent_is_unmeasured(tmp_path):
    body = HEALTHY_GUARD.replace('allowed = {"a", "b", "c", "d"}', "")
    root = _guard_tree(tmp_path, body)
    status, why = _probe(repo_root=str(root))
    assert status == UNMEASURED, why
    assert "нет перечня `allowed`" in why


# ─────────────── звено 6: вердикт даёт ПРОГОН, а не пересказ ─────────────────

def test_broken_link_guard_is_red_on_the_tree(tmp_path, child_can_import):
    body = HEALTHY_GUARD.replace(
        'assert consumes_report("P = \'data/tier_curator_report.json\'\\n")',
        "assert False, 'красный сторож'")
    root = _guard_tree(tmp_path, body)
    status, why = _probe(repo_root=str(root))
    assert status == NOT_SATISFIED, why
    assert "КРАСЕН на дереве" in why


def test_broken_link_guard_node_missing_is_unmeasured(tmp_path, child_can_import):
    """Переименование узла есть смена предмета, а не чистота."""
    body = HEALTHY_GUARD.replace(f"def {NODE}()", "def test_renamed_away()")
    root = _guard_tree(tmp_path, body)
    status, why = _probe(repo_root=str(root))
    assert status == UNMEASURED, why
    assert "не найден по узлу" in why


def test_the_minimal_healthy_guard_is_green_so_each_red_names_one_link(
        tmp_path, child_can_import):
    """Контроль сцен: минимум ЗЕЛЕН, значит каждый красный выше рвал РОВНО одно звено.

    Без этого утверждения любая сцена могла краснеть по чужой причине, и набор
    мерил бы не то, что обещает.
    """
    root = _guard_tree(tmp_path, HEALTHY_GUARD)
    status, why = _probe(repo_root=str(root))
    assert status == SATISFIED, why
