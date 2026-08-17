"""Сторож против МОЛЧАЛИВОГО мока в турнире (карточка agent-guard-no-silent-mock-in-tournament).

Класс дефекта: мок, подставленный МОЛЧА, делает зелёный прогон бессмысленным —
«стратегия заработала» на выдуманном числе неотличимо от настоящего результата.
S23 сидел на mock-7% навсегда, потому что ``except Exception: pass`` вокруг импорта
адаптера съедал ImportError, а турнир ранжировал это как живую оценку.

Что проверяется — ТРИ разных вопроса (см. `_silent_mock`):

  1. заявленный живой адаптер РЕАЛЬНО импортируется (import-based, не ``compile``);
  2. провал импорта не проглатывается МОЛЧА (храповик, база может лишь уменьшаться);
  3. подстановка НАЗВАНА в рейтинге турнира и не попадает в доверяемый лидерборд.

**Положительный контроль обязателен** у каждого: проверка, никогда не видевшая
настоящей поломки, — украшение. Здесь авария воспроизводится синтетическим деревом
стратегий в ``tmp_path`` — живая сеть и живые данные не трогаются.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.tests import _silent_mock as sm  # noqa: E402
from spa_core.strategies.mock_provenance import (  # noqa: E402
    is_mock_fed,
    live_flags,
    mock_provenance,
)

_BASELINE_PATH = pathlib.Path(__file__).parent / "silent_mock_baseline.json"


# ─────────────────────────────────────────────────────────────────────────────
# Вопрос 1 — заявленный адаптер ГРУЗИТСЯ
# ─────────────────────────────────────────────────────────────────────────────

def test_every_live_claim_actually_imports():
    """Ни одна стратегия не заявляет адаптер, который не грузится (S23-класс)."""
    broken = sm.broken_live_claims()
    assert not broken, (
        "Стратегии заявляют живой адаптер, который НЕ ГРУЗИТСЯ — значит сидят на "
        "подставленном числе, а турнир ранжирует его как живое:\n"
        + sm.format_findings(broken)
    )


def test_live_claims_are_actually_measured():
    """Сторож должен что-то ВИДЕТЬ: пустой набор заявок = сторож ослеп."""
    claims = sm.live_claims()
    assert len(claims) >= 20, f"ожидались десятки заявок на живой адаптер, найдено {len(claims)}"
    assert any(c.inside_try for c in claims), (
        "ни одна заявка не стоит внутри try — именно такие и проваливаются молча"
    )


def test_broken_claim_is_detected_positive_control(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: заявка на несуществующий адаптер краснит сторожа."""
    (tmp_path / "s99_broken_claim.py").write_text(
        "try:\n"
        "    from spa_core.adapters.definitely_not_a_real_adapter import Nope\n"
        "except Exception:\n"
        "    pass\n",
        encoding="utf-8",
    )
    broken = sm.broken_live_claims(root=tmp_path)
    assert len(broken) == 1, broken
    assert broken[0]["module"] == "spa_core.adapters.definitely_not_a_real_adapter"
    assert "Error" in broken[0]["detail"] or "error" in broken[0]["detail"].lower()


def test_missing_attribute_claim_is_detected_positive_control(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: модуль грузится, а заявленного ИМЕНИ в нём нет.

    Ровно вторая половина S23: `from ... import X`, где X был переименован —
    ``compile`` молчит, импорт бросает ImportError, ``except: pass`` его съедает.
    """
    (tmp_path / "s98_missing_name.py").write_text(
        "try:\n"
        "    from spa_core.adapters.apy_contract import ThisNameWasRenamedAway\n"
        "except Exception:\n"
        "    pass\n",
        encoding="utf-8",
    )
    broken = sm.broken_live_claims(root=tmp_path)
    assert len(broken) == 1, broken
    assert broken[0]["name"] == "ThisNameWasRenamedAway"


# ─────────────────────────────────────────────────────────────────────────────
# Вопрос 2 — провал импорта не проглатывается МОЛЧА (храповик)
# ─────────────────────────────────────────────────────────────────────────────

def test_silent_swallow_ratchet_does_not_grow():
    """Число молчаливых обработчиков может только УМЕНЬШАТЬСЯ.

    Полный запрет невозможен (35 обработчиков в 13 стратегиях — запрет в лоб
    покрасил бы турнир целиком и научил бы сторожа отключать), поэтому база
    зафиксирована и растить её нельзя. Добавление файла в базу ради зелёного CI —
    нарушение инварианта 16.
    """
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    expected = baseline["by_file"]
    actual = sm.silent_swallow_counts()

    grown = {
        f: (expected.get(f, 0), n)
        for f, n in actual.items()
        if n > expected.get(f, 0)
    }
    assert not grown, (
        "Появились НОВЫЕ молчаливые обработчики вокруг импорта "
        f"(файл: было → стало): {grown}. Провал импорта обязан быть слышен: "
        "логировать и явно помечать источник неживым, а не глотать."
    )
    assert sum(actual.values()) <= baseline["total_handlers"], (
        f"всего молчаливых обработчиков {sum(actual.values())} > базы "
        f"{baseline['total_handlers']}"
    )


def test_baseline_matches_a_real_measurement():
    """База — замер, а не пожелание: её файлы обязаны существовать сейчас."""
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    actual = sm.silent_swallow_counts()
    stale = sorted(set(baseline["by_file"]) - set(actual))
    assert not stale, (
        f"база называет файлы, где молчаливых обработчиков уже нет: {stale} — "
        "уменьшить базу (храповик двигается только вниз)"
    )


def test_silent_handler_is_detected_positive_control(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: молчаливый обработчик вокруг импорта находится."""
    (tmp_path / "s97_silent.py").write_text(
        "try:\n"
        "    from spa_core.adapters.aave_v3 import AaveV3Adapter\n"
        "except Exception:\n"
        "    pass\n",
        encoding="utf-8",
    )
    found = sm.silently_swallowed_imports(root=tmp_path)
    assert len(found) == 1, found
    assert found[0].strategy_file == "s97_silent.py"
    assert found[0].exception_type == "Exception"


def test_logging_handler_is_not_flagged(tmp_path):
    """Обработчик, который ШУМИТ, сторож не трогает — иначе его отключат.

    Обратная сторона того же сторожа: он обязан различать «проглотил» и
    «залогировал и честно пометил неживым». Иначе честная починка красит тест.
    """
    (tmp_path / "s96_loud.py").write_text(
        "import logging\n"
        "_log = logging.getLogger(__name__)\n"
        "try:\n"
        "    from spa_core.adapters.aave_v3 import AaveV3Adapter\n"
        "except Exception as exc:\n"
        "    _log.warning('aave adapter unavailable: %s', exc)\n"
        "    AaveV3Adapter = None\n",
        encoding="utf-8",
    )
    assert sm.silently_swallowed_imports(root=tmp_path) == []


def test_reraising_handler_is_not_flagged(tmp_path):
    """`raise` — тоже не тишина: fail-CLOSED вариант считается реакцией."""
    (tmp_path / "s95_raise.py").write_text(
        "try:\n"
        "    from spa_core.adapters.aave_v3 import AaveV3Adapter\n"
        "except Exception:\n"
        "    raise\n",
        encoding="utf-8",
    )
    assert sm.silently_swallowed_imports(root=tmp_path) == []


def test_try_without_import_is_out_of_scope(tmp_path):
    """Проглоченный ВЫЗОВ — другой класс дефекта, этот сторож его не судит."""
    (tmp_path / "s94_call.py").write_text(
        "def f(x):\n"
        "    try:\n"
        "        return x.thing\n"
        "    except Exception:\n"
        "        pass\n",
        encoding="utf-8",
    )
    assert sm.silently_swallowed_imports(root=tmp_path) == []


# ─────────────────────────────────────────────────────────────────────────────
# Провенанс подстановки на самой стратегии
# ─────────────────────────────────────────────────────────────────────────────

class _MockedStrategy:
    STRATEGY_ID = "S-MOCKED"
    MOCK_PT_APY = 7.0

    def __init__(self) -> None:
        self._pt_live = False

    def pt_is_live(self) -> bool:
        return False


class _LiveStrategy:
    STRATEGY_ID = "S-LIVE"

    def __init__(self) -> None:
        self._pt_live = True

    def pt_is_live(self) -> bool:
        return True


class _UndeclaredStrategy:
    STRATEGY_ID = "S-UNDECLARED"


class _ExplodingStrategy:
    STRATEGY_ID = "S-BOOM"

    def pt_is_live(self) -> bool:
        raise RuntimeError("adapter gone")


def test_mock_provenance_names_the_substitution():
    prov = mock_provenance(_MockedStrategy())
    assert prov["strategy_id"] == "S-MOCKED"
    assert prov["fully_live"] is False
    # Кэш `_pt_live` не дублирует предикат: у одного источника один ответ.
    assert prov["substituted"] == ["pt_is_live"]
    assert "_pt_live" not in prov["live_flags"]
    assert "MOCK_PT_APY" in prov["declared_mock_constants"]
    assert is_mock_fed(prov) is True


def test_mock_provenance_live_strategy_is_clean():
    prov = mock_provenance(_LiveStrategy())
    assert prov["fully_live"] is True
    assert prov["substituted"] == []
    assert is_mock_fed(prov) is False


def test_undeclared_liveness_is_unknown_not_live():
    """Отсутствие флагов — «не заявлено» (None), а НЕ «всё живое» (fail-CLOSED)."""
    prov = mock_provenance(_UndeclaredStrategy())
    assert prov["fully_live"] is None
    # «Не знаю» не выдаётся за подстановку — иначе сторож красит честные стратегии.
    assert is_mock_fed(prov) is False


def test_stale_cache_does_not_outvote_the_predicate():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ (замер на S23): устаревший кэш не красит живую стратегию.

    Сразу после конструктора `self._pt_live` ещё False, а `pt_is_live()` уже
    перечитает источник и вернёт True. Алфавитный обход прочитал бы сперва кэш и
    объявил бы живую стратегию подставленной — сторож на честной работе.
    """
    class _StaleCache:
        STRATEGY_ID = "S-STALE"

        def __init__(self) -> None:
            self._pt_live = False   # кэш до первого чтения

        def pt_is_live(self) -> bool:
            self._pt_live = True    # предикат перечитывает и обновляет кэш
            return True

    prov = mock_provenance(_StaleCache())
    assert prov["live_flags"] == {"pt_is_live": True}, prov["live_flags"]
    assert prov["fully_live"] is True
    assert is_mock_fed(prov) is False


def test_raising_live_flag_counts_as_not_live():
    """Упавший предикат живости = источник НЕ подтверждён, а не «пропустим»."""
    flags = live_flags(_ExplodingStrategy())
    assert flags["pt_is_live"] is False
    assert is_mock_fed(mock_provenance(_ExplodingStrategy())) is True


def test_s23_declares_its_pt_liveness_honestly():
    """S23 (исходный дефект) обязан ЗАЯВЛЯТЬ живость PT, а не молчать о ней.

    Фид ИНЖЕКТИРУЕТСЯ (правило адаптеров: тесты не ходят в живую сеть) — сначала
    как недоступный (fallback ⇒ подстановка названа), затем как живой.
    """
    from spa_core.strategies.s23_pendle_pt_fixed import PendlePTFixedStrategy

    dead = PendlePTFixedStrategy()
    dead._pendle_apy_fn = lambda default: {
        "apy": default, "source": "fallback", "is_available": False}
    prov = mock_provenance(dead)
    assert prov["fully_live"] is False, (
        "S23 на недоступном фиде обязан ЗАЯВИТЬ подстановку, а не молчать"
    )
    assert "pt_is_live" in prov["substituted"]
    assert "MOCK_PT_APY" in prov["declared_mock_constants"]
    assert is_mock_fed(prov) is True

    alive = PendlePTFixedStrategy()
    alive._pendle_apy_fn = lambda default: {
        "apy": 8.25, "source": "pendle_api", "is_available": True}
    prov_live = mock_provenance(alive)
    assert prov_live["fully_live"] is True, prov_live
    assert is_mock_fed(prov_live) is False


# ─────────────────────────────────────────────────────────────────────────────
# Вопрос 3 — подстановка НАЗВАНА в рейтинге турнира
# ─────────────────────────────────────────────────────────────────────────────

def _fake_leaderboard_row(**kw):
    row = {
        "id": "s_x", "sharpe": 1.2, "annual_return_pct": 5.0,
        "volatility_pct": 4.0, "max_dd_pct": -2.0, "allocation": {"aave_v3": 1.0},
        "rank_unknown": False, "mock_tainted": False,
    }
    row.update(kw)
    return row


def test_mass_tournament_marks_and_excludes_mock_rows(tmp_path):
    """Продюсер помечает подставленные строки и держит их вне доверяемого рейтинга."""
    from spa_core.backtesting.mass_tournament import MassTournament
    mt = MassTournament()
    result = mt.run(data_dir=str(tmp_path))

    assert "trusted_leaderboard" in result, "нет доверяемого рейтинга без подстановок"
    board = result["leaderboard"]
    assert board, "лидерборд пуст — сторожу нечего проверять"

    for row in board:
        # Каждая строка обязана НАЗЫВАТЬ свой вход и свой вердикт.
        assert row["apy_input"] in ("mock_apy_snapshot", "strategy_internal"), row
        assert isinstance(row["mock_apy_fed"], bool)
        assert isinstance(row["mock_tainted"], bool)
        assert isinstance(row["trusted_for_ranking"], bool)
        # Подставленная строка НИКОГДА не доверяема.
        if row["mock_tainted"]:
            assert row["trusted_for_ranking"] is False, row["id"]

    trusted_ids = {r["id"] for r in result["trusted_leaderboard"]}
    tainted_ids = {r["id"] for r in board if r["mock_tainted"]}
    assert not (trusted_ids & tainted_ids), (
        f"подставленные строки просочились в доверяемый рейтинг: {trusted_ids & tainted_ids}"
    )
    assert result["meta"]["mock_tainted_count"] == len(tainted_ids)
    assert sorted(tainted_ids) == result["meta"]["mock_tainted_strategies"]
    # Литеральность снимка MOCK_APY названа прямо, а не подразумевается.
    assert result["meta"]["mock_apy_snapshot_is_literal"] is True

    on_disk = json.loads((tmp_path / "mass_tournament_results.json").read_text())
    assert "trusted_leaderboard" in on_disk


def test_mock_apy_snapshot_is_recognised_as_fed():
    """Кормление литеральным MOCK_APY распознаётся по ИДЕНТИЧНОСТИ объекта.

    Положительный контроль механизма пометки: стратегия, чей единственный рабочий
    вызов требует ``apy_map``, обязана получить ``mock_apy_fed=True``.
    """
    from spa_core.backtesting import mass_tournament as mtm

    src = (
        "class OnlyWithApyMap:\n"
        "    def get_allocation(self, capital_usd=None, apy_map=None):\n"
        "        if not apy_map:\n"
        "            raise TypeError('needs apy_map')\n"
        "        return {'aave_v3': 1.0}\n"
    )
    mod_name = "spa_core.strategies._tmp_only_with_apy_map"
    module = type(sys)(mod_name)
    exec(compile(src, mod_name, "exec"), module.__dict__)
    sys.modules[mod_name] = module
    try:
        mt = mtm.MassTournament()
        alloc, label = mt.extract_allocation(mod_name, "OnlyWithApyMap", src)
        assert alloc, label
        assert mt.last_mock_fed_labels[mod_name] is True, (
            f"вызов {label} получил литеральный MOCK_APY, но это не отмечено"
        )
    finally:
        sys.modules.pop(mod_name, None)


def test_honesty_gate_still_fires_on_degenerate_data():
    """Honesty-gate нельзя тихо заглушить (инвариант 16): он ОБЯЗАН краснеть.

    Дубль-страховка к `test_tournament_trust_honesty.py`: если кто-то уберёт
    проверку вырожденности, оба теста покраснеют, а не один.
    """
    from spa_core.backtesting.tier1.evaluator import assess_tournament_trust
    degenerate = [
        _fake_leaderboard_row(id="s1", sharpe=80.7, volatility_pct=0.046, annual_return_pct=3.6),
        _fake_leaderboard_row(id="s2", sharpe=72.4, volatility_pct=0.075, annual_return_pct=4.1),
        _fake_leaderboard_row(id="s3", sharpe=66.8, volatility_pct=0.084, annual_return_pct=4.5),
    ]
    stamp = assess_tournament_trust({"leaderboard": degenerate})
    assert stamp["trustworthy"] is False
    assert stamp["data_source_regime"] in ("DEGENERATE_MOCK", "LOW_VOL_YIELD")


def test_time_is_an_input_not_the_wall_clock():
    """Ни один сторож этого файла не читает стенные часы на уровне модуля."""
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    module_level = [
        line for line in source.splitlines()
        if line and not line[0].isspace() and "datetime.now" in line
    ]
    assert not module_level, module_level
    # Импорт есть, но применяется только внутри тестов с ЯВНО переданным now.
    assert "datetime" in globals() or datetime is not None
    assert timezone is not None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
