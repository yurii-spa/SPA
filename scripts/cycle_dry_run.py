#!/usr/bin/env python3
"""
MP-428: Dry-run smoke test for SPA daily cycle.
Reads but does NOT write production data.
Проверяет адаптеры, стратегии, PaperEvidenceTracker и наличие data-файлов.

Usage:
    python3 scripts/cycle_dry_run.py

Exit code:
    0  — все проверки прошли и ВСЁ измерено
    1  — есть FAIL (адаптер, стратегия или файл)
    2  — FAIL нет, но что-то НЕ ИЗМЕРЕНО (ADR-878, инв. #17): «судить было нечем»
         обязано отличаться и от «прошло», и от «упало» — иначе третий исход
         неотличим от чистого прогона и глохнет так же, как молчание
"""

import sys
import os
import importlib
import json
import traceback
from datetime import date, datetime, timezone

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

#: Окно, в котором отметка ПИСАТЕЛЯ ещё считается свежей (ч). Такт цикла суточный
#: (daily_cycle 08:00 local), поэтому 48 ч = «один пропущенный прогон ещё терпим, два
#: уже нет». Окно короче такта краснело бы на исправной системе между прогонами.
WRITER_FRESHNESS_WINDOW_H = 48.0

#: Обязательные артефакты и ОТМЕТКА ПИСАТЕЛЯ у каждого (ADR-878, решение владельца
#: 31.10, вариант 1; находка ADR-876).
#:
#: Здесь был простой список путей, а проверка ниже начисляла `n_pass` за
#: `os.path.isfile()` и печатала рядом РАЗМЕР. Ни то, ни другое наблюдением не
#: является: размер — свойство байтов, а не свидетельство о том, что артефакт кто-то
#: СЕГОДНЯ написал; пустой словарь `{}` весит 2 байта и проходил. Теперь у каждого
#: артефакта ОБЪЯВЛЕНО, где лежит отметка его писателя:
#:
#:   ``keys``   — отметка в корне документа (первый найденный ключ из кортежа)
#:   ``series`` — (имя списка, имя поля с датой): отметка = САМАЯ ПОЗДНЯЯ запись
#:                (у `paper_evidence.json` отметки в корне нет вовсе, а `days[].date`
#:                пишет `cycle_runner` — это и есть след писателя)
WRITER_STAMP: dict[str, dict] = {
    "data/golive_status.json":      {"keys": ("timestamp", "generated_at")},
    "data/paper_evidence.json":     {"series": ("days", "date")},
    "data/tournament_ranking.json": {"keys": ("timestamp", "generated_at")},
    "data/adapter_status.json":     {"keys": ("generated_at",)},
}

#: Прежнее имя сохранено: на него ссылается внешний читатель, а порядок обхода —
#: порядок объявления выше.
REQUIRED_FILES = list(WRITER_STAMP)


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

def _writer_stamp_age_h(doc, spec: dict, now: datetime) -> tuple[float | None, str]:
    """Возраст отметки ПИСАТЕЛЯ в часах — или ``None`` с названной причиной.

    ``None`` значит «отметки нет», а не «ноль часов назад»: подстановка нуля
    объявила бы артефакт без отметки самым свежим из возможных (инв. #17).
    """
    stamp = None
    if "keys" in spec:
        if not isinstance(doc, dict):
            return None, f"документ не словарь, а {type(doc).__name__}"
        for key in spec["keys"]:
            value = doc.get(key)
            if isinstance(value, str) and value.strip():
                stamp = value
                break
        if stamp is None:
            return None, f"ни одного объявленного ключа отметки {spec['keys']}"
    else:
        list_key, date_key = spec["series"]
        rows = doc.get(list_key) if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            return None, f"`{list_key}` не список записей"
        dates = [r.get(date_key) for r in rows if isinstance(r, dict)]
        dates = [d for d in dates if isinstance(d, str) and d.strip()]
        if not dates:
            return None, f"в `{list_key}` нет ни одной записи с `{date_key}`"
        stamp = max(dates)

    raw = stamp.strip().replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        try:
            when = datetime.fromisoformat(raw + "T00:00:00+00:00")
        except ValueError:
            return None, f"отметка {stamp!r} не разбирается как ISO-8601"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (now - when).total_seconds() / 3600.0, ""


def check_files(now: datetime | None = None) -> tuple[int, int, int]:
    """Спрашивает у обязательных data/-артефактов их ПИСАТЕЛЯ. → (pass, fail, не измерено).

    **Присутствие файла и его размер наблюдением не являются (ADR-878, решение
    владельца 31.10, вариант 1; находка ADR-876).** Прежняя проверка начисляла
    `n_pass` за `os.path.isfile()` и печатала рядом число байтов — то есть отвечала
    на вопрос «лежит ли файл», а читалась как «цикл свои артефакты пишет». Между
    этими двумя вопросами и живёт класс: `git checkout`, старый бэкап и пустой `{}`
    проходят первый и ничего не говорят про второй.

    Три исхода различимы (инв. #17):

      PASS           — документ разобран И отметка его писателя в окне
                       ``WRITER_FRESHNESS_WINDOW_H``
      FAIL           — файла НЕТ · документ не разбирается · отметка СТАРШЕ окна
                       (писатель молчит — это ответ, а не «нечем судить»)
      НЕ ИЗМЕРЕНО    — файл есть и читается, а объявленной отметки в нём нет:
                       возраст неизвестен, и выдавать это за PASS нельзя

    Часы — ВХОД (``now``): иначе проверка краснела бы от сдвига календаря
    (``.claude/rules/deployment.md``).
    """
    at = now or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)

    print(f"\n{'─'*60}")
    print("DATA FILES — спрашиваем ПИСАТЕЛЯ (отметка в окне "
          f"{WRITER_FRESHNESS_WINDOW_H:.0f}ч), а не присутствие файла")
    print(f"{'─'*60}")

    n_pass = n_fail = n_unmeasured = 0

    for rel_path, spec in WRITER_STAMP.items():
        abs_path = os.path.join(ROOT, rel_path)
        if not os.path.isfile(abs_path):
            fail(f"{rel_path}  — файл НЕ СУЩЕСТВУЕТ: писатель не писал")
            n_fail += 1
            continue
        try:
            with open(abs_path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            fail(f"{rel_path}  — не разбирается ({type(exc).__name__}: {exc})")
            n_fail += 1
            continue

        age_h, why = _writer_stamp_age_h(doc, spec, at)
        if age_h is None:
            warn(f"{rel_path}  — НЕ ИЗМЕРЕНО: {why}; возраст записи неизвестен, "
                 f"и это НЕ PASS")
            n_unmeasured += 1
        elif age_h > WRITER_FRESHNESS_WINDOW_H:
            fail(f"{rel_path}  — писатель МОЛЧИТ: отметка {age_h:.1f}ч назад, "
                 f"окно {WRITER_FRESHNESS_WINDOW_H:.0f}ч")
            n_fail += 1
        elif age_h < -1.0:
            fail(f"{rel_path}  — отметка в БУДУЩЕМ на {-age_h:.1f}ч: часам писателя "
                 f"верить нельзя")
            n_fail += 1
        else:
            ok(f"{rel_path}  (писатель отметился {age_h:.1f}ч назад)")
            n_pass += 1

    return n_pass, n_fail, n_unmeasured


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
    f_pass, f_fail, f_unmeasured = check_files()

    total_pass = a_pass + s_pass + e_pass + f_pass
    total_fail = a_fail + s_fail + e_fail + f_fail
    overall_ok = (total_fail == 0)

    print(f"\n{'═'*60}")
    print("  SUMMARY")
    print(f"{'═'*60}")
    print(f"  Адаптеры:      {a_pass:2d} PASS  {a_fail:2d} FAIL  (из {a_pass+a_fail})")
    print(f"  Стратегии:     {s_pass:2d} PASS  {s_fail:2d} FAIL  (из {s_pass+s_fail})")
    print(f"  EvidenceTrack: {e_pass:2d} PASS  {e_fail:2d} FAIL")
    print(f"  Data files:    {f_pass:2d} PASS  {f_fail:2d} FAIL  "
          f"{f_unmeasured:2d} НЕ ИЗМЕРЕНО  (из {f_pass+f_fail+f_unmeasured})")
    print(f"{'─'*60}")
    print(f"  ИТОГО:         {total_pass:2d} PASS  {total_fail:2d} FAIL")

    if not overall_ok:
        print(f"\n{RED}  ❌ ЕСТЬ ОШИБКИ — см. FAIL выше{RESET}")
    elif f_unmeasured:
        print(f"\n{YELLOW}  ⚠️  FAIL нет, но НЕ ИЗМЕРЕНО {f_unmeasured} — "
              f"см. WARN выше. Это НЕ «все проверки прошли»{RESET}")
    else:
        print(f"\n{GREEN}  ✅ ALL CHECKS PASSED — всё измерено{RESET}")

    print("=" * 60)
    if not overall_ok:
        return 1
    return 2 if f_unmeasured else 0


if __name__ == "__main__":
    sys.exit(main())
