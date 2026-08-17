"""Сторож «профинансирован протокол, которого нет в реестре» (карточка
`agent-funded-protocol-not-in-registry`, остаточная дыра ADR-062).

Проверка идёт в ОБЕ стороны, как требует карточка: книга с незарегистрированным
протоколом ⇒ сторож краснеет; книга из зарегистрированных ⇒ молчит.

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ (`.claude/rules/deployment.md`) —
`test_the_cheap_route_is_blind_to_this` воспроизводит ровно ту слепоту, ради
которой сторож написан отдельным модулем, а не строкой в кэп-правиле: протокол,
которого НЕТ в реестре, но который знает статическая карта `chain_limits`,
разрешает цепочку, `chain_unresolved` остаётся ПУСТЫМ — и дешёвый сторож,
читающий только это поле, молчит о деньгах без записи в реестре. Имена в тесте не
выдуманы: `compound_v3_base` и `aave_v3_arbitrum` — это ровно те два имени, что
на замере 16.08 были в статической карте и отсутствовали в реестре, причём первое
из них на Base, то есть буквально случай, записанный ADR-062 как дыра.

Часов здесь нет: вопрос «есть ли запись в реестре» не про свежесть, поэтому в
фикстурах нет ни одной даты — ни литеральной, ни вычисленной.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.monitoring.registry_coverage_watch import (
    BOOK_FILE,
    REGISTRY_FILE,
    STATE_COVERED,
    STATE_GAP,
    STATE_NO_BOOK,
    STATE_UNCHECKED,
    check_registry_coverage,
)

# Слепок формы живых файлов (`data/adapter_registry.json` → adapters[имя].chain).
_REGISTERED = {
    "aave_v3": {"tier": 1, "chain": "ethereum"},
    "compound_v3": {"tier": 1, "chain": "ethereum"},
    "morpho_steakhouse": {"tier": 2, "chain": "base"},
}


def _book(tmp_path: Path, positions: dict) -> Path:
    (tmp_path / BOOK_FILE).write_text(
        json.dumps({"current_positions": positions}), encoding="utf-8")
    return tmp_path


def _registry(tmp_path: Path, adapters=None) -> Path:
    (tmp_path / REGISTRY_FILE).write_text(
        json.dumps({"version": "1.0",
                    "adapters": _REGISTERED if adapters is None else adapters}),
        encoding="utf-8")
    return tmp_path


# ── 1. Книга из зарегистрированных — сторож молчит ──────────────────────────
def test_a_fully_registered_book_is_silent(tmp_path):
    _registry(_book(tmp_path, {"aave_v3": 23250.0, "compound_v3": 15852.27}))
    v = check_registry_coverage(tmp_path)

    assert v.state == STATE_COVERED
    assert v.severity == "OK"
    assert v.issue is None
    assert v.uncovered_pct == 0.0


def test_a_closed_position_is_not_funded(tmp_path):
    """Нулевая строка — след закрытой позиции: денег нет, кричать не о чем."""
    _registry(_book(tmp_path, {"aave_v3": 23250.0, "ghost_protocol": 0.0}))
    v = check_registry_coverage(tmp_path)

    assert v.state == STATE_COVERED
    assert "ghost_protocol" not in v.funded


# ── 2. Авария, ради которой сторож написан ──────────────────────────────────
def test_a_funded_unregistered_protocol_is_critical_and_named(tmp_path):
    """Книга с незарегистрированным протоколом ⇒ сторож краснеет (карточка, п.3)."""
    _registry(_book(tmp_path, {"aave_v3": 75_000.0, "mystery_pool": 25_000.0}))
    v = check_registry_coverage(tmp_path)

    assert v.state == STATE_GAP
    assert v.severity == "CRITICAL"
    assert v.missing_from_registry == ["mystery_pool"]
    assert "mystery_pool" in v.issue
    assert v.uncovered_usd == 25_000.0
    assert v.uncovered_pct == pytest.approx(25.0)


def test_a_registry_entry_without_a_chain_is_the_same_hole(tmp_path):
    """Карточка дословно: «отсутствующий в реестре ИЛИ без поля chain»."""
    adapters = dict(_REGISTERED, half_known={"tier": 2})
    _registry(_book(tmp_path, {"aave_v3": 90_000.0, "half_known": 10_000.0}), adapters)
    v = check_registry_coverage(tmp_path)

    assert v.state == STATE_GAP
    assert v.without_chain == ["half_known"]
    assert v.missing_from_registry == []
    assert "цепочка не названа" in v.issue


@pytest.mark.parametrize("chain", ["", "   ", None, 5, {}])
def test_a_chain_that_is_not_a_name_is_not_a_chain(tmp_path, chain):
    adapters = dict(_REGISTERED, half_known={"tier": 2, "chain": chain})
    _registry(_book(tmp_path, {"half_known": 10_000.0}), adapters)

    assert check_registry_coverage(tmp_path).state == STATE_GAP


def test_the_cheap_route_is_blind_to_this(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: почему сторож не читает только `chain_unresolved`.

    `compound_v3_base` отсутствует в реестре, но известен статической карте
    `chain_limits`. Кэп-правило разрешает его цепочку, `chain_unresolved` пуст —
    и сторож, построенный по дешёвому маршруту, промолчал бы о деньгах под
    протоколом без записи в реестре. Сторож обязан краснеть здесь.
    """
    from spa_core.risk.chain_limits import get_default_chain_map
    from spa_core.risk.policy_enforcer import _resolve_chain_map

    unregistered_but_mapped = "compound_v3_base"
    assert unregistered_but_mapped in get_default_chain_map(), (
        "имя выбрано как известное статической карте — иначе контроль пустой")
    assert unregistered_but_mapped not in _REGISTERED

    # Дешёвый маршрут молчит: цепочка разрешена резервной картой.
    _map, unresolved = _resolve_chain_map([unregistered_but_mapped])
    assert unresolved == [], "контроль устарел: имя больше не разрешается картой"

    _registry(_book(tmp_path, {"aave_v3": 80_000.0, unregistered_but_mapped: 20_000.0}))
    v = check_registry_coverage(tmp_path)

    assert v.state == STATE_GAP
    assert v.missing_from_registry == [unregistered_but_mapped]


# ── 3. Fail-CLOSED: «не измерено» не хранится как «в порядке» ────────────────
def test_an_unreadable_registry_beside_a_funded_book_is_unchecked(tmp_path):
    _book(tmp_path, {"aave_v3": 50_000.0})
    (tmp_path / REGISTRY_FILE).write_text("{ это не json", encoding="utf-8")
    v = check_registry_coverage(tmp_path)

    assert v.state == STATE_UNCHECKED
    assert v.severity == "WARNING"
    assert "НЕ ИЗМЕРЕНО" in v.detail
    # И НИ В КОЕМ СЛУЧАЕ не «вся книга не покрыта»: это был бы ложный приговор.
    assert v.missing_from_registry == []


def test_a_missing_registry_beside_a_funded_book_is_unchecked(tmp_path):
    _book(tmp_path, {"aave_v3": 50_000.0})

    assert check_registry_coverage(tmp_path).state == STATE_UNCHECKED


def test_an_unreadable_book_is_unchecked_not_covered(tmp_path):
    _registry(tmp_path)
    (tmp_path / BOOK_FILE).write_text("{ обрыв", encoding="utf-8")
    v = check_registry_coverage(tmp_path)

    assert v.state == STATE_UNCHECKED
    assert v.severity == "WARNING"


def test_an_unparsable_amount_still_counts_as_funded(tmp_path):
    """«Сумму не разобрал» ≠ «денег там нет» — протокол остаётся под надзором."""
    _registry(_book(tmp_path, {"mystery_pool": "много"}))
    v = check_registry_coverage(tmp_path)

    assert v.state == STATE_GAP
    assert v.missing_from_registry == ["mystery_pool"]
    # Долю измерить нечем — и она честно не выдумывается.
    assert v.uncovered_pct is None


def test_an_absent_book_is_nothing_to_watch(tmp_path):
    """Пустое дерево — не авария: сторож, всегда красный, читается как немой."""
    v = check_registry_coverage(tmp_path)

    assert v.state == STATE_NO_BOOK
    assert v.severity == "OK"
    assert v.issue is None


def test_an_empty_book_is_nothing_to_watch(tmp_path):
    _registry(_book(tmp_path, {}))

    assert check_registry_coverage(tmp_path).state == STATE_NO_BOOK


# ── 4. Сторож НИЧЕГО не пишет ───────────────────────────────────────────────
def test_the_watch_writes_nothing(tmp_path):
    """Домен read-only: карточка разрешает детекцию, но не запись в data/."""
    _registry(_book(tmp_path, {"aave_v3": 75_000.0, "mystery_pool": 25_000.0}))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    check_registry_coverage(tmp_path)

    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert after == before, "сторож изменил дерево данных"


# ── 5. Проводка: сторож должен быть СЛЫШЕН, а не лежать в модуле ────────────
# Урок цикла #144: снятие ОДНОГО места вызова оставляет собственные тесты зелёными,
# пока фича мертва в проде. Здесь проверяется ЭФФЕКТ — скрипт исполняется настоящим
# процессом, а шаг в обёртке дневного цикла берётся дословно из файла.
import subprocess  # noqa: E402
import sys  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "registry_coverage_check.py"
_WRAPPER = _REPO / "scripts" / "run_daily_paper_cycle.sh"


def _run(tmp_path, *extra):
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--data-dir", str(tmp_path), *extra],
        capture_output=True, text=True, cwd=str(_REPO))


def test_the_entrypoint_reports_the_gap(tmp_path):
    """Находка обязана быть СЛЫШНА снаружи процесса, а не только в объекте."""
    _registry(_book(tmp_path, {"aave_v3": 75_000.0, "mystery_pool": 25_000.0}))
    r = _run(tmp_path)

    assert r.returncode == 1, r.stderr
    assert "mystery_pool" in r.stdout
    assert "CRITICAL" in r.stdout


def test_the_entrypoint_is_silent_on_a_covered_book(tmp_path):
    """Контроль в обратную сторону: покрытая книга не поднимает тревогу."""
    _registry(_book(tmp_path, {"aave_v3": 75_000.0}))
    r = _run(tmp_path)

    assert r.returncode == 0, r.stderr
    assert "CRITICAL" not in r.stdout


def test_the_entrypoint_separates_unchecked_from_ok(tmp_path):
    """Fail-CLOSED доезжает до кода возврата, а не теряется по дороге."""
    _book(tmp_path, {"aave_v3": 50_000.0})   # реестра нет
    r = _run(tmp_path)

    assert r.returncode == 2, r.stderr
    assert "НЕ ИЗМЕРЕНО" in r.stdout


def test_the_entrypoint_writes_nothing(tmp_path):
    _registry(_book(tmp_path, {"aave_v3": 75_000.0, "mystery_pool": 25_000.0}))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    _run(tmp_path)

    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_the_json_mode_is_machine_readable(tmp_path):
    _registry(_book(tmp_path, {"aave_v3": 75_000.0, "mystery_pool": 25_000.0}))
    r = _run(tmp_path, "--json")
    payload = json.loads(r.stdout)

    assert payload["state"] == STATE_GAP
    assert payload["missing_from_registry"] == ["mystery_pool"]
    assert payload["uncovered_pct"] == pytest.approx(25.0)


def test_the_daily_cycle_actually_calls_it():
    """Без вызывающего сторож — мёртвый код: ровно тот класс, что ловит храповик."""
    text = _WRAPPER.read_text(encoding="utf-8")

    assert "scripts/registry_coverage_check.py" in text
    step = [ln for ln in text.splitlines() if "registry_coverage_check.py" in ln][0]
    # Шаг обязан быть НЕ фатальным: находка — не поломка цикла.
    assert "||" in step or "|| echo" in text


def test_the_step_cannot_break_the_cycle(tmp_path):
    """Лечение не должно быть опаснее болезни: находка не смеет уронить цикл.

    Строка шага исполняется настоящим bash с заведомо падающим «питоном».
    """
    text = _WRAPPER.read_text(encoding="utf-8")
    idx = [i for i, ln in enumerate(text.splitlines())
           if "registry_coverage_check.py" in ln][0]
    lines = text.splitlines()
    step = lines[idx] + ("\n" + lines[idx + 1] if lines[idx].rstrip().endswith("\\") else "")

    log = tmp_path / "cycle.log"
    r = subprocess.run(
        ["bash", "-c", f'PYTHON=/bin/false; LOG_FILE="{log}"; {step}; echo CYCLE_CONTINUED'],
        capture_output=True, text=True, cwd=str(_REPO))

    assert "CYCLE_CONTINUED" in r.stdout, "шаг оборвал цикл — так нельзя"
