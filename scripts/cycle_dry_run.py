#!/usr/bin/env python3
"""
MP-428: Dry-run smoke test for SPA daily cycle.
Reads but does NOT write production data.
Проверяет адаптеры, стратегии, PaperEvidenceTracker и наличие data-файлов.

Usage:
    python3 scripts/cycle_dry_run.py

Exit code:
    0  — все проверки прошли
    1  — есть FAIL (адаптер, стратегия или файл)
"""

import sys
import os
import importlib
import traceback
from datetime import date

# Путь к корню проекта (scripts/ → ..)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ─── Цвета для вывода ─────────────────────────────────────────────────────────

GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
RESET  = "\033[0m"

def ok(msg):  print(f"  {GREEN}✅ PASS{RESET}  {msg}")
def fail(msg): print(f"  {RED}❌ FAIL{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠️  WARN{RESET}  {msg}")

# ─── Mock APY map для стратегий ───────────────────────────────────────────────

MOCK_APY_MAP = {
    "aave_v3":           3.5,
    "aave_arbitrum":     4.6,
    "compound_v3":       4.8,
    "morpho_blue":       6.2,
    "morpho_steakhouse": 6.5,
    "yearn_v3":          5.1,
    "euler_v2":          5.8,
    "maple":             7.0,
    "pendle":            9.5,
    "pendle_pt":         8.5,
    "fluid_fusdc":       6.5,
    "sfrax":             5.3,
    "spark_susds":       5.5,
    "susde":             5.0,
}

# ─── Маппинг S0-S11 → (module_path, class_name_or_None) ─────────────────────

STRATEGY_MAP = [
    ("S0",  "spa_core.strategies.baseline",                   "BaselineStrategy",            "simulate_day"),
    ("S1",  "spa_core.strategies.s1_conservative_lending",    "ConservativeLendingStrategy", None),
    ("S2",  "spa_core.strategies.s2_lp_stable",               "LPStableStrategy",            None),
    ("S3",  "spa_core.strategies.s3_yield_loop",              "YieldLoopStrategy",           None),
    ("S4",  "spa_core.strategies.s4_spark_fluid_conservative","S4ConservativeSparkFluid",    "simulate_day"),
    ("S5",  "spa_core.strategies.s5_pendle_enhanced",         "S5PendleEnhanced",            "simulate_day"),
    ("S6",  "spa_core.strategies.s6_max_diversified",         None,                          "simulate_day"),
    ("S7",  "spa_core.strategies.s7_pendle_yt_aggressive",    "S7PendleYTAggressive",        "simulate_day"),
    ("S8",  "spa_core.strategies.delta_neutral_susde",        "DeltaNeutralSUSDeStrategy",   "simulate_day"),
    ("S9",  "spa_core.strategies.emode_looping",              "EModeLoopingStrategy",        "simulate_day"),
    ("S10", "spa_core.strategies.pendle_yt",                  "PendleYTStrategy",            "simulate_day"),
    ("S11", "spa_core.strategies.s11_hybrid_yield_max",       "S11HybridYieldMax",           "run_day"),
]

# ─── Требуемые файлы данных ───────────────────────────────────────────────────

REQUIRED_FILES = [
    "data/golive_status.json",
    "data/paper_evidence.json",
    "data/tournament_ranking.json",
    "data/adapter_status.json",
]


# ══════════════════════════════════════════════════════════════════════════════
# 1. Проверка адаптеров
# ══════════════════════════════════════════════════════════════════════════════

def check_adapters() -> tuple[int, int]:
    """Проверяет каждый адаптер из ADAPTER_REGISTRY: get_apy() → float > 0."""
    print(f"\n{'─'*60}")
    print("АДАПТЕРЫ — import + get_apy()")
    print(f"{'─'*60}")

    n_pass = n_fail = 0

    try:
        from spa_core.adapters import ADAPTER_REGISTRY
    except Exception as e:
        fail(f"Не удалось импортировать ADAPTER_REGISTRY: {e}")
        return 0, 1

    for protocol_key, tier, adapter_cls in ADAPTER_REGISTRY:
        label = f"{protocol_key} [{tier}] ({adapter_cls.__name__})"
        try:
            adapter = adapter_cls()
            apy = adapter.get_apy()
            if apy is None:
                warn(f"{label} → get_apy() вернул None (сеть недоступна или адаптер без данных)")
                # None — не фатал в dry-run (сеть может быть offline)
                n_pass += 1
            elif isinstance(apy, float) and apy >= 0:
                ok(f"{label} → {apy:.2f}%")
                n_pass += 1
            else:
                fail(f"{label} → get_apy() вернул неожиданный тип: {type(apy).__name__} = {apy!r}")
                n_fail += 1
        except Exception as e:
            fail(f"{label} → {type(e).__name__}: {e}")
            traceback.print_exc()
            n_fail += 1

    return n_pass, n_fail


# ══════════════════════════════════════════════════════════════════════════════
# 2. Проверка стратегий S0-S11
# ══════════════════════════════════════════════════════════════════════════════

def _call_strategy(sid: str, mod_path: str, cls_name: str | None, method: str | None) -> None:
    """Импортирует и вызывает run-метод стратегии. Бросает исключение при ошибке."""
    mod = importlib.import_module(mod_path)

    if cls_name is not None:
        cls = getattr(mod, cls_name, None)
        if cls is None:
            raise AttributeError(f"Класс '{cls_name}' не найден в {mod_path}")
        instance = cls()

        # Ищем run-метод: run_day → simulate_day → run
        for mname in ([method] if method else []) + ["run_day", "simulate_day", "run"]:
            if mname and hasattr(instance, mname):
                bound = getattr(instance, mname)
                # Пробуем вызвать с apy_map
                try:
                    bound(MOCK_APY_MAP)
                except TypeError:
                    # Может принимать capital или другие аргументы — пробуем без аргументов
                    try:
                        bound()
                    except TypeError:
                        bound(MOCK_APY_MAP, 100_000.0)
                return
        raise AttributeError(
            f"У {cls_name} не найден метод run_day/simulate_day/run"
        )
    else:
        # Нет класса — ищем модульную функцию simulate_day / run_day
        for fname in ["simulate_day", "run_day", "run"]:
            fn = getattr(mod, fname, None)
            if fn is not None and callable(fn):
                try:
                    fn(MOCK_APY_MAP)
                except TypeError:
                    fn(MOCK_APY_MAP, 100_000.0)
                return
        raise AttributeError(f"Модуль {mod_path} не содержит simulate_day/run_day/run")


def check_strategies() -> tuple[int, int]:
    """Проверяет каждую стратегию S0-S11: импорт + run_day()/simulate_day() без исключений."""
    print(f"\n{'─'*60}")
    print("СТРАТЕГИИ S0–S11 — import + run-метод")
    print(f"{'─'*60}")

    n_pass = n_fail = 0

    for (sid, mod_path, cls_name, method) in STRATEGY_MAP:
        label = f"{sid}  {mod_path.split('.')[-1]}"
        try:
            _call_strategy(sid, mod_path, cls_name, method)
            ok(label)
            n_pass += 1
        except ImportError as e:
            fail(f"{label} → ImportError: {e}")
            n_fail += 1
        except AttributeError as e:
            fail(f"{label} → AttributeError: {e}")
            n_fail += 1
        except Exception as e:
            fail(f"{label} → {type(e).__name__}: {e}")
            traceback.print_exc()
            n_fail += 1

    return n_pass, n_fail


# ══════════════════════════════════════════════════════════════════════════════
# 3. Проверка PaperEvidenceTracker
# ══════════════════════════════════════════════════════════════════════════════

def check_evidence_tracker() -> tuple[int, int]:
    """Проверяет PaperEvidenceTracker.record_day() в /tmp/ (не трогает production data/)."""
    print(f"\n{'─'*60}")
    print("PAPER EVIDENCE TRACKER — record_day() в /tmp/")
    print(f"{'─'*60}")

    import tempfile

    n_pass = n_fail = 0
    tmp_file = os.path.join(tempfile.gettempdir(), "spa_dry_run_evidence_test.json")

    try:
        from spa_core.paper_trading.paper_evidence_tracker import PaperEvidenceTracker
        tracker = PaperEvidenceTracker(evidence_file=tmp_file)
        result = tracker.record_day(
            trade_date=date.today(),
            apy_pct=8.5,
            equity_value=100_100.0,
            strategy_id="S7",
            notes="dry-run smoke test",
        )
        if isinstance(result, dict) and "date" in result:
            ok(f"record_day() вернул запись: date={result['date']}, apy_pct={result.get('apy_pct')}")
            n_pass += 1
        else:
            fail(f"record_day() вернул неожиданный результат: {result!r}")
            n_fail += 1
    except Exception as e:
        fail(f"PaperEvidenceTracker → {type(e).__name__}: {e}")
        traceback.print_exc()
        n_fail += 1
    finally:
        # Удаляем временный файл
        try:
            os.remove(tmp_file)
        except OSError:
            pass

    return n_pass, n_fail


# ══════════════════════════════════════════════════════════════════════════════
# 4. Проверка наличия data/*.json файлов
# ══════════════════════════════════════════════════════════════════════════════

def check_files() -> tuple[int, int]:
    """Проверяет наличие обязательных data/ файлов."""
    print(f"\n{'─'*60}")
    print("DATA FILES — проверка существования")
    print(f"{'─'*60}")

    n_pass = n_fail = 0

    for rel_path in REQUIRED_FILES:
        abs_path = os.path.join(ROOT, rel_path)
        if os.path.isfile(abs_path):
            size = os.path.getsize(abs_path)
            ok(f"{rel_path}  ({size:,} bytes)")
            n_pass += 1
        else:
            fail(f"{rel_path}  — файл НЕ СУЩЕСТВУЕТ")
            n_fail += 1

    return n_pass, n_fail


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 60)
    print("  MP-428  SPA CYCLE DRY-RUN SMOKE TEST")
    print(f"  {date.today().isoformat()}")
    print("=" * 60)

    a_pass, a_fail = check_adapters()
    s_pass, s_fail = check_strategies()
    e_pass, e_fail = check_evidence_tracker()
    f_pass, f_fail = check_files()

    total_pass = a_pass + s_pass + e_pass + f_pass
    total_fail = a_fail + s_fail + e_fail + f_fail
    overall_ok = (total_fail == 0)

    print(f"\n{'═'*60}")
    print("  SUMMARY")
    print(f"{'═'*60}")
    print(f"  Адаптеры:      {a_pass:2d} PASS  {a_fail:2d} FAIL  (из {a_pass+a_fail})")
    print(f"  Стратегии:     {s_pass:2d} PASS  {s_fail:2d} FAIL  (из {s_pass+s_fail})")
    print(f"  EvidenceTrack: {e_pass:2d} PASS  {e_fail:2d} FAIL")
    print(f"  Data files:    {f_pass:2d} PASS  {f_fail:2d} FAIL  (из {f_pass+f_fail})")
    print(f"{'─'*60}")
    print(f"  ИТОГО:         {total_pass:2d} PASS  {total_fail:2d} FAIL")

    if overall_ok:
        print(f"\n{GREEN}  ✅ ALL CHECKS PASSED — система готова к первому launchd-запуску 2026-06-13{RESET}")
    else:
        print(f"\n{RED}  ❌ ЕСТЬ ОШИБКИ — см. FAIL выше{RESET}")

    print("=" * 60)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
