"""Перепись входов журнала решений: что писатель ДЕРЖИТ и что ПИШЕТ (заказ #539).

Заказ цикла #539 (ADR-287) назвал потолок числом: журнал решений
(``data/allocation_rationale_history.jsonl``) покрывает 4–6 ставок в день против
15 ранжируемых живым снимком, и часть ранжируемых ключей не встречается в нём
НИКОГДА. Пока это так, каждый вопрос о РЕЖИМЕ (ничья, устойчивость цели,
воспроизводимость решения) платит одну и ту же цену: делить измеряемое на
«зависит от покрытия» и «не зависит».

Прибор отвечает на три вопроса заказа — ЗАМЕРОМ У ПИСАТЕЛЯ, а не рассуждением
о нём:

1. **Кто пишет.** ``spa_core/paper_trading/allocation_rationale.py``
   (``build_history_record`` ← ``write_shadow_rationale``, шаг 2f дневного цикла
   и оба рукава ``hy_cycle``/``lp_cycle``). Здесь этот путь не переписывается —
   зовётся НАСТОЯЩАЯ функция писателя.
2. **Почему в него попадают 4–6 ставок из ранжируемых.** Отбор измеряется
   МУТАЦИЕЙ ПО КООРДИНАТЕ, а не чтением исходника: три пробы разводят три
   кандидатные причины (профинансированность · живость фида · наличие ставки в
   карте) и оставляют ровно ту, что действительно связывает.
3. **Что мешает писать весь набор — и дёшево ли это.** Половина ответа лежит у
   писателя (держит ли он полный набор в руках в момент отсечения), вторая —
   У ПОТРЕБИТЕЛЕЙ: журнал читают семь модулей, и для одних рост населения есть
   выигрыш, а для других — регрессия. Считать «дёшево» по первой половине
   значило бы ответить на не тот вопрос.

**Ловушка заказа соблюдена.** Соблазн был объявить причиной ADR-279 («реплей
сошёлся на 5 днях из 34»). Там мерилась воспроизводимость ЦЕЛИ по журналу,
здесь — полнота ПЕРЕПИСИ ВХОДОВ; неполный вход объясняет невоспроизводимую
цель, но не наоборот, и обратное рассуждение есть круг. Поэтому ни одна цифра
ниже не берётся из ADR-279.

**ADVISORY.** Прибор ничего не чинит и не предлагает чинить молча: писатель не
трогается ни на строку, пороги RiskPolicy v1.0, потолки концентрации,
``TriggerParams``, kill-switch и живой трек — тем более. Живое ``data/`` на
запись открывается ровно один раз, для собственного артефакта; производитель
цели и писатель работают в песочнице.

Третий исход обязателен везде: нечитаемый вход, неотработавший производитель и
упавший потребитель дают ``unmeasured`` с НАЗВАННОЙ причиной, а не число и не
молчание.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from spa_core.utils.errors import SPAError

log = logging.getLogger("spa.monitoring.decision_journal_coverage")

VERSION = "decision-journal-coverage-v1"
OUTPUT_FILENAME = "decision_journal_coverage.json"

#: Журнал решений — тот же файл, что читают все потребители ниже.
HISTORY_FILENAME = "allocation_rationale_history.jsonl"

#: Снимок, который копируется в песочницу производителю цели и потребителям.
#: Живое ``data/`` им не показывается: они читают пути, которые мы передаём.
_SANDBOX_FILES = (
    "adapter_orchestrator_status.json",
    "adapter_status.json",
    "risk_scores.json",
    "adapter_registry.json",
    "strategy_shadow_comparison.json",
    "current_positions.json",
    "trades.json",
    "equity_curve_daily.json",
    HISTORY_FILENAME,
)

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Доля живых ранжируемых ставок, с которой отсечение перестаёт быть краем и
#: становится потолком. Порог ПРИБОРА, к RiskPolicy отношения не имеет и ничего
#: не гейтит.
_CEILING_FRAC = 0.5

# ── Население потребителей журнала ────────────────────────────────────────────
# Список закрыт ЗАМЕРОМ, а не памятью: это все модули не-тестового дерева, где
# встречается ключ ``apy_evidenced_pct`` (сторож полноты — тест этого модуля).
#
# ``role`` — не украшение, а половина вердикта. Для одних рост населения журнала
# есть ВЫИГРЫШ (они и просили полноту), для других — РЕГРЕССИЯ: они оценивают
# ноги КНИГИ и обязаны дать тот же ответ на более широкой карте. Потребитель
# роли ``must_not_move``, у которого вердикт поехал, означает, что починка
# журнала НЕ дешёвая, и это самая важная находка прибора.
#: Счётчик ПОКРЫТИЯ, который потребитель публикует САМ: сколько он сумел
#: оценить. Он и разводит два исхода, которые первая редакция прибора путала
#: (и на этом изготовила ложную находку — см. журнал цикла #540):
#:
#:   * покрытие ВЫРОСЛО ⇒ потребитель ПЛАТИТ за потолок. Его числа сегодня
#:     посчитаны на тех днях, которые потолок дал оценить; починка журнала их
#:     переизложит — вширь, а не наизнанку.
#:   * ответ поехал, а покрытие НЕ выросло ⇒ вот это регрессия: то же
#:     население, другое число. Только такой исход делает починку дорогой.
#:
#: Счётчик берётся у САМОГО потребителя, а не выводится прибором: своя
#: производная от чужого отчёта была бы вторым определением покрытия.
VERDICT_PAYS = "coverage_grew"
VERDICT_MOVED = "moved_without_coverage"
VERDICT_INSENSITIVE = "insensitive"
VERDICT_UNMEASURED = "unmeasured"

READERS: Tuple[dict, ...] = (
    {"module": "spa_core.monitoring.target_stability", "probe": "observed_daily_moves"},
    {"module": "spa_core.monitoring.ranking_tie_persistence", "probe": "journal_days"},
    {"module": "spa_core.paper_trading.shadow_trigger_eval", "probe": "evaluate_window"},
    {"module": "spa_core.monitoring.cio_shadow_replay", "probe": "run"},
    {"module": "spa_core.monitoring.apy_forecast_accuracy", "probe": "run"},
    {"module": "spa_core.monitoring.outcomes_archive", "probe": "build_outcome_line"},
    {"module": "spa_core.monitoring.cio_explainability", "probe": "run"},
    # Четыре потребителя, читавшие ключ, но НЕ измерявшиеся прибором (замер
    # храповика `ReaderPopulationRatchet`, 10.09). У каждого свой `run(root,
    # write=False)`; отказ или отсутствие счётчика покрытия у любого из них
    # остаётся третьим исходом `unmeasured` с названной причиной, а не молчанием.
    {"module": "spa_core.monitoring.arming_wall_order", "probe": "run"},
    {"module": "spa_core.monitoring.g1_verdict_recoverability", "probe": "run"},
    {"module": "spa_core.monitoring.journal_backfill_material", "probe": "run"},
    {"module": "spa_core.monitoring.unevidenced_leg_causes", "probe": "run"},
    # Пятый — доставлен циклом #549 (ADR-311) и в население не вписан, отчего
    # храповик `ReaderPopulationRatchet` краснел на чистом origin/main 6e7eb58d5
    # (замер цикла #550 контрольным прогоном по тому же sha). Это и есть работа
    # храповика: новый потребитель ключа обязан попасть под замер стоимости
    # починки журнала, иначе прибор ответит за население, которого уже нет.
    {"module": "spa_core.monitoring.leg_provenance_split", "probe": "run"},
    # Шестой — доставлен циклом #552 (ADR-314). Счётчика покрытия он НЕ
    # публикует НАМЕРЕННО, и это решение, а не недосмотр: его вердикты стоят не
    # на одном журнале, а на ВТОРОМ носителе (`audit_trail.jsonl`, опознание
    # прогона по `correlation_id`/`cycle_start`), которого в песочнице прибора
    # нет. Счётчик, посчитанный здесь, дал бы 0 и в базе, и в расширении — то
    # есть ровно тот `insensitive` из несуществующего населения, за который
    # прибор уже краснел однажды (#540). Третий исход `unmeasured` с названной
    # причиной честнее числа, которого никто не мерил.
    {"module": "spa_core.monitoring.decision_record_run_identity", "probe": "run"},
)


# ──────────────────────────────────────────────────────────────────────────
# входы
# ──────────────────────────────────────────────────────────────────────────
def _read_json(path: Path) -> Tuple[Optional[object], str]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), ""
    except Exception as exc:  # noqa: BLE001 — причина уезжает в отчёт словами
        return None, f"{type(exc).__name__}: {exc}"


def read_journal(data_dir: Path) -> Tuple[List[dict], str]:
    """Строки журнала решений по возрастанию даты. Битая строка не рушит перепись."""
    rows: List[dict] = []
    try:
        with open(Path(data_dir) / HISTORY_FILENAME, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    rows.sort(key=lambda r: (str(r.get("cycle_date") or ""),
                             str(r.get("generated_at") or "")))
    return rows, ""


def record_universe(rec: dict) -> set:
    """Население ОДНОЙ записи журнала — то, что НАЗЫВАЕТ сама запись.

    Прежняя редакция считала его как ``current_positions ∪ target_positions``,
    то есть держала ВТОРУЮ КОПИЮ правила писателя — ровно то, чего шапка этого
    модуля обещает не делать. Пока писатель брал книгу, копия совпадала с
    оригиналом и молчала; ADR-309 расширил писателя до всего живого набора дня,
    и копия начала бы занижать население каждой новой строки, а разницу
    записывать в `dropped_by_funding` — то есть докладывать отсечение, которого
    больше нет.

    Правило теперь одно и читается прямо со строки: население записи есть
    объединение двух её собственных словарей — ставки с живым провенансом плюс
    ноги, о которых писатель сказал «провенанса нет». Оно верно для обеих эпох
    журнала: строка ДО ADR-309 называет ровно свою книгу, строка после —
    весь живой набор. Позиции остаются запасным ответом для строк совсем старой
    схемы, где обоих словарей нет вовсе; пустая строка так и остаётся пустой.
    """
    named = set((rec.get("apy_evidenced_pct") or {}).keys()) \
        | set(rec.get("apy_unevidenced") or [])
    if named:
        return named
    if "apy_evidenced_pct" in rec or "apy_unevidenced" in rec:
        return named  # запись НАЗВАЛА пустое население — это ответ, а не пробел
    return set(rec.get("current_positions") or {}) | set(rec.get("target_positions") or {})


def _default_ranked_producer(sandbox: Path) -> Callable[[], Tuple[Dict[str, float], Dict[str, str]]]:
    """Возвращает функцию → (ранжируемые ставки в ПРОЦЕНТАХ, их провенанс).

    Зовёт НАСТОЯЩИЙ производитель — ``StrategyAllocator``, собранный ровно так
    же, как его собирает дневной цикл (``cycle_runner._default_allocator``:
    только путь к снимку оркестратора). Второй реализации ранжирования здесь
    нет намеренно: измерять надо тот набор, который писатель получает на вход,
    а не свою копию правил отбора.

    ``allocate()`` в файлы не пишет; все пути ведут в песочницу.
    """
    def produce() -> Tuple[Dict[str, float], Dict[str, str]]:
        from spa_core.allocator.allocator import StrategyAllocator

        res = StrategyAllocator(
            status_path=str(sandbox / "adapter_orchestrator_status.json"),
            strategy_loop_enabled=False,
        ).allocate()
        used = {str(k): float(v) for k, v in (getattr(res, "apy_used", {}) or {}).items()}
        src = {str(k): str(v) for k, v in (getattr(res, "apy_sources", {}) or {}).items()}
        return used, src

    return produce


# ──────────────────────────────────────────────────────────────────────────
# A. держит против пишет
# ──────────────────────────────────────────────────────────────────────────
def split_gap(ranked_live: set, universe: set, written: set) -> dict:
    """Разложение щели «ранжировано живым числом → записано» по ПРИЧИНАМ.

    Две причины применяются писателем подряд (``p in universe and p in evidenced``),
    и путать их нельзя: одна отсекает НЕПРОФИНАНСИРОВАННОЕ, другая — вошедшее в
    книгу без живого числа. Вторая при этом не молчит: такой ключ писатель
    честно кладёт в ``apy_unevidenced``.
    """
    by_funding = sorted(ranked_live - universe)
    by_evidence = sorted(universe - written)
    return {
        "ranked_live": len(ranked_live),
        "written": len(written),
        "universe": len(universe),
        "dropped_by_funding": by_funding,
        "dropped_by_funding_n": len(by_funding),
        "dropped_by_evidence": by_evidence,
        "dropped_by_evidence_n": len(by_evidence),
        "written_frac_of_ranked_live": (len(written) / len(ranked_live)
                                        if ranked_live else None),
    }


def never_seen(rows: List[dict], ranked_live: set) -> List[str]:
    """Живые ранжируемые ключи, не встречавшиеся в журнале НИ РАЗУ за всю историю.

    Это не «ставка нулевая» и не «пара не ничья» — это ОТСУТСТВИЕ ЗАМЕРА, и
    именно оно делает каждый вопрос о режиме дороже.
    """
    ever: set = set()
    for r in rows:
        ever |= set((r.get("apy_evidenced_pct") or {}).keys())
    return sorted(ranked_live - ever)


# ──────────────────────────────────────────────────────────────────────────
# B. отбор назван МУТАЦИЕЙ, а не чтением исходника
# ──────────────────────────────────────────────────────────────────────────
def probe_criterion(*, apy_pct: Dict[str, float], apy_sources: Dict[str, str],
                    current_positions: Dict[str, float],
                    target_positions: Dict[str, float],
                    capital_usd: float,
                    unfunded_live: Optional[str],
                    funded_live: Optional[str],
                    build: Optional[Callable[..., dict]] = None) -> dict:
    """Является ли население записи ПОЛНЫМ живым набором дня — четыре пробы у писателя.

    Зовётся НАСТОЯЩИЙ ``build_history_record``; своей копии правила отбора
    здесь нет. Мутируется КООРДИНАТА входа (позиция, провенанс, карта ставок),
    а не текст исходника.

    **Вопрос переставлен ADR-309 (ответ владельца 2026-09-10, Вариант Б), и
    ожидания проб переставлены вместе с ним — намеренно, инвариант #16.** До
    ADR-309 писатель брал ``current ∪ target``, и прибор спрашивал «ЧТО
    отсекает запись»: тогда «ключ попал в запись одной картой ставок» был
    ПАДЕНИЕМ контроля (дверей оказалось две, вывод о причине недействителен).
    После ADR-309 карта ставок — дверь ПО ЗАМЫСЛУ: население записи есть весь
    живой набор дня. Прежний контроль на неизменном коде писателя краснел бы
    каждый цикл на ВЕРНОЙ доставке (класс «сторож звенит на нашей же поставке»),
    поэтому утверждение не ослаблено, а ПЕРЕВЁРНУТО и расширено четвёртой
    пробой:

    * **map_widens** — ключ вне обеих книг, с живым провенансом и числом,
      кладётся ТОЛЬКО в карту ставок. Обязан появиться в записи. Молчание ⇒
      расширение ADR-309 до писателя не доехало (находка, а не норма).
    * **funding** — тот же ключ БЕЗ единой мутации обязан уже лежать в записи:
      профинансированность больше не связывает. Если он появляется лишь
      после попадания в цель — писатель по-прежнему узкий.
    * **evidence** — у профинансированного ключа провенанс меняется с ``live``
      на ``fallback_stale``. Уехал в ``apy_unevidenced`` ⇒ живость фида
      остаётся правилом и НЕ молчит. Эта проба ADR-309 не тронул.
    * **unpriced_live_stays_out** (контроль, обязан НЕ сработать) — ключ с
      живым провенансом, но БЕЗ числа. Он не должен попасть НИ в
      ``apy_evidenced_pct``, ни в ``apy_unevidenced``: расширение идёт ровно на
      ``priced_live``, и ключ без значения не вправе войти в население ни одной
      из двух дверей.

    Отсутствие пригодной пробы — третий исход (``unmeasured`` с причиной), а не
    тихо пропущенная строка.
    """
    if build is None:
        from spa_core.paper_trading.allocation_rationale import build_history_record as build

    doc = {"cycle_date": "2026-01-01", "generated_at": "2026-01-01T00:00:00+00:00",
           "decision_shadow": {}, "params": {}}

    def written_of(*, sources: Dict[str, str], target: Dict[str, float],
                   rates: Dict[str, float]) -> Tuple[set, set]:
        rec = build(doc, apy_pct=rates, apy_sources=sources,
                    current_positions=current_positions, target_positions=target,
                    capital_usd=capital_usd)
        return (set((rec.get("apy_evidenced_pct") or {}).keys()),
                set(rec.get("apy_unevidenced") or []))

    base_written, base_unev = written_of(sources=apy_sources, target=target_positions,
                                         rates=apy_pct)
    out: dict = {"base_written_n": len(base_written), "probes": {}}

    # ── проба funding ──────────────────────────────────────────────────────
    # После ADR-309 вопрос не «появится ли ключ, когда его профинансируют», а
    # «лежит ли он там УЖЕ». Прежняя редакция сравнивала лишь членство ПОСЛЕ
    # мутации и на расширенном писателе отвечала «binds» на ключ, который был в
    # записи и до мутации, — верный ответ на вопрос, который больше не задают.
    if not unfunded_live:
        out["probes"]["funding"] = {
            "verdict": "unmeasured",
            "note": ("нет непрофинансированного ключа с живым числом — "
                     "пробе не на чем различить причину"),
        }
    elif unfunded_live in base_written:
        out["probes"]["funding"] = {
            "verdict": "does_not_bind",
            "key": unfunded_live,
            "note": ("непрофинансированный ключ лежит в записи БЕЗ единой "
                     "мутации — профинансированность население не связывает"),
        }
    else:
        tgt = dict(target_positions)
        tgt[unfunded_live] = 1.0
        got, _ = written_of(sources=apy_sources, target=tgt, rates=apy_pct)
        out["probes"]["funding"] = {
            "verdict": "binds" if unfunded_live in got else "does_not_bind",
            "key": unfunded_live,
            "note": ("ключа не было в записи и он появился, как только попал в "
                     "цель — писатель по-прежнему пишет книгу, а не живой набор"
                     if unfunded_live in got else
                     "ключ в цели, а в записи его нет — причина НЕ профинансированность"),
        }

    # ── проба evidence ─────────────────────────────────────────────────────
    if not funded_live:
        out["probes"]["evidence"] = {
            "verdict": "unmeasured",
            "note": "нет профинансированного ключа с живым числом — пробу ставить не на чем",
        }
    else:
        src = dict(apy_sources)
        src[funded_live] = "fallback_stale"
        got, unev = written_of(sources=src, target=target_positions, rates=apy_pct)
        moved = funded_live not in got and funded_live in unev
        out["probes"]["evidence"] = {
            "verdict": "binds_inside_book" if moved else (
                "silent" if funded_live not in got else "does_not_bind"),
            "key": funded_live,
            "note": ("снятие живого провенанса уводит ключ в apy_unevidenced — "
                     "правило есть и оно НЕ молчит" if moved else
                     "ключ пропал из записи, не появившись в apy_unevidenced — "
                     "потеря была бы молчаливой" if funded_live not in got else
                     "провенанс на состав записи не влияет"),
        }

    # ── проба map_widens (ADR-309: карта ставок — дверь ПО ЗАМЫСЛУ) ─────────
    _probe_key = "__probe_map_only__"
    if _probe_key in (current_positions or {}) or _probe_key in (target_positions or {}):
        out["probes"]["map_widens"] = {
            "verdict": "unmeasured",
            "note": "служебное имя пробы занято реальным ключом — мутация неотличима от факта",
        }
    else:
        rates = dict(apy_pct)
        rates[_probe_key] = 1.0
        src = dict(apy_sources)
        src[_probe_key] = "live"
        got, unev = written_of(sources=src, target=target_positions, rates=rates)
        out["probes"]["map_widens"] = {
            "verdict": "widens" if _probe_key in got else "silent",
            "key": _probe_key,
            "note": ("ключ вне обеих книг попал в запись одной картой ставок — "
                     "расширение ADR-309 у писателя ЕСТЬ" if _probe_key in got else
                     "ключ вне книг с живым числом в запись НЕ попал — расширение "
                     "ADR-309 до писателя не доехало"),
        }

        # ── контроль unpriced_live (обязан НЕ сработать) ────────────────────
        # Тот же ключ, но БЕЗ числа: расширение идёт ровно на priced_live.
        # Появление означало бы, что в население входит ставка, которой нет.
        src_np = dict(apy_sources)
        src_np[_probe_key] = "live"
        got_np, unev_np = written_of(sources=src_np, target=target_positions,
                                     rates=dict(apy_pct))
        landed = _probe_key in got_np or _probe_key in unev_np
        out["probes"]["unpriced_live_stays_out"] = {
            "verdict": "stays_out" if not landed else "UNPRICED_ADMITTED",
            "key": _probe_key,
            "note": ("ключ с живым провенансом, но без числа, в население не вошёл — "
                     "контроль сработал как должен" if not landed else
                     "ключ БЕЗ ставки попал в население записи: расширение идёт не "
                     "по priced_live, и запись несёт ставку, которой нет"),
        }
    out["probes"].setdefault("unpriced_live_stays_out", {
        "verdict": "unmeasured",
        "note": "проба map_widens не ставилась — контролю не на чем стоять",
    })

    verdicts = {k: v.get("verdict") for k, v in out["probes"].items()}
    if verdicts.get("unpriced_live_stays_out") == "UNPRICED_ADMITTED":
        out["verdict"] = "unpriced_admitted"
    elif verdicts.get("map_widens") == "silent":
        out["verdict"] = "still_funded_set"
    elif "unmeasured" in verdicts.values():
        out["verdict"] = "unmeasured"
    elif verdicts.get("map_widens") == "widens" and \
            verdicts.get("funding") == "does_not_bind" and \
            verdicts.get("evidence") == "binds_inside_book":
        out["verdict"] = "full_live_set"
    else:
        out["verdict"] = "partial"
    return out


# ──────────────────────────────────────────────────────────────────────────
# C. цена у ПОТРЕБИТЕЛЕЙ
# ──────────────────────────────────────────────────────────────────────────
def widen_journal(rows: List[dict], rates_pct: Dict[str, float],
                  ranked_live: set) -> List[dict]:
    """Копия журнала, где ``apy_evidenced_pct`` расширен до живого ранжируемого набора.

    Это **проба чувствительности, а не реконструкция истории**: ставок для
    непрофинансированных ключей в прошлом никто не записывал, и выдумывать их
    прибор не вправе. Значения берутся из СЕГОДНЯШНЕГО снимка и одинаковы во все
    дни — этого достаточно, чтобы различить потребителя, которому важно
    НАСЕЛЕНИЕ карты, от потребителя, которому важны только ЗНАЧЕНИЯ по своим
    ключам. Ни одна цифра отсюда не переносится в утверждения о прошлом.
    """
    extra = {k: float(rates_pct[k]) for k in sorted(ranked_live)
             if k in rates_pct}
    out: List[dict] = []
    for r in rows:
        rec = json.loads(json.dumps(r))
        merged = dict(extra)
        merged.update(rec.get("apy_evidenced_pct") or {})
        rec["apy_evidenced_pct"] = merged
        out.append(rec)
    return out


def _write_journal(rows: List[dict], path: Path) -> None:
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True, default=str) for r in rows) + "\n",
        encoding="utf-8")


def _reader_probe(spec: dict, root: Path) -> Tuple[Optional[int], object]:
    """Один прогон потребителя над журналом в ``root/data`` → (покрытие, слепок).

    **Покрытие** — счётчик, который потребитель публикует САМ («сколько дней я
    сумел оценить», «сколько фактов подтвердил»). Прибор его не выводит: своя
    производная от чужого отчёта была бы вторым определением покрытия, а спорить
    двум определениям тут не о чем. ``None`` ⇒ счётчика у потребителя нет, и
    направление сдвига остаётся НЕ ИЗМЕРЕННЫМ (отдельный исход, не молчание).

    **Слепок** — сравнимая часть ответа, без отметок времени: хеш ВСЕГО отчёта
    отвечал бы не на тот вопрос ([[reproducibility-probe-must-name-clock-fields]]).
    """
    import importlib

    mod = importlib.import_module(spec["module"])
    ddir = root / "data"
    name = spec["probe"]

    if name == "observed_daily_moves":
        moves, err, rows = mod.observed_daily_moves(ddir)
        if err:
            raise SPAError(err, code="PROBE_MOVES_UNREADABLE",
                           details={"probe": name, "module": spec["module"]})
        # покрытие = сколько протоколов вообще получили ряд наблюдений
        return len(moves), {"protocols": sorted(moves), "rows": rows,
                            "n_moves": {k: len(v) for k, v in sorted(moves.items())}}
    if name == "journal_days":
        days, err = mod.journal_days(ddir)
        if err:
            raise SPAError(err, code="PROBE_JOURNAL_DAYS_UNREADABLE",
                           details={"probe": name, "module": spec["module"]})
        # покрытие = сколько пар (день, ключ) прибор вообще увидел
        pairs = sum(len(d["rates"]) for d in days)
        return pairs, {"days": len(days), "keys": [sorted(d["rates"]) for d in days]}
    if name == "evaluate_window":
        doc = mod.evaluate_window(ddir, write=False)
        crit = doc.get("criteria") or []
        checked = sum(1 for c in crit if str(c.get("status")) != "UNCHECKED")
        return checked, {"criteria": [(c.get("name"), c.get("status"), c.get("actual"))
                                      for c in crit],
                         "ready": doc.get("ready_to_arm"),
                         "observed_days": doc.get("observed_days")}
    if name == "build_outcome_line":
        rows, err = read_journal(ddir)
        if err or not rows:
            raise SPAError(err or "журнал пуст",
                           code="PROBE_JOURNAL_EMPTY",
                           details={"probe": name, "module": spec["module"]})
        day = str(rows[-1].get("cycle_date"))
        line = mod.build_outcome_line(str(root), day)
        cov = len(line.get("apy_evidenced_pct") or {})
        return cov, {k: line.get(k) for k in sorted(line) if k != "generated_at"}
    if name == "run":
        is_expl = spec["module"].endswith("cio_explainability")
        doc = (mod.run(root=str(root), write=False) if is_expl
               else mod.run(str(root), write=False))
        if not isinstance(doc, dict):
            raise SPAError(f"потребитель вернул {type(doc).__name__}, не отчёт",
                           code="PROBE_CONSUMER_NOT_A_REPORT",
                           details={"probe": name, "module": spec["module"],
                                    "returned": type(doc).__name__})
        cov = _own_coverage(doc)
        return cov, {k: v for k, v in sorted(doc.items())
                     if k not in ("generated_at", "as_of", "now", "root")}
    raise SPAError(f"проба `{name}` не описана", code="PROBE_UNKNOWN",
                   details={"probe": name})


def _own_coverage(doc: dict) -> Optional[int]:
    """Счётчик покрытия из отчёта потребителя — по ЕГО собственному имени поля.

    Имена перечислены поимённо, а не угаданы регуляркой: «поле, похожее на
    счётчик» — это ровно тот приём, из-за которого прибор однажды принял
    отметку времени за вход. Не нашли ни одного ⇒ ``None`` (третий исход).
    """
    pop = doc.get("population")
    if isinstance(pop, dict):
        for key in ("common_scored_days", "scoreable"):
            v = pop.get(key)
            if isinstance(v, int):
                return v
    facts_total = doc.get("facts_total")
    if isinstance(facts_total, int):
        # покрытие объяснимости = факты, у которых значение НАШЛОСЬ в записи
        absent = 0
        for b in doc.get("books") or []:
            absent += sum(1 for f in (b.get("facts") or [])
                          if str(f.get("outcome")) == "ABSENT")
        return facts_total - absent
    return None


def _changed_keys(base: object, wide: object) -> List[str]:
    """Поимённо: какие поля ответа поехали. Без этого «регрессия» — обвинение без адреса."""
    if not (isinstance(base, dict) and isinstance(wide, dict)):
        return []
    return sorted(k for k in set(base) | set(wide)
                  if json.dumps(base.get(k), sort_keys=True, default=str)
                  != json.dumps(wide.get(k), sort_keys=True, default=str))


def probe_readers(rows: List[dict], widened: List[dict], sandbox: Path,
                  readers: Tuple[dict, ...] = READERS) -> List[dict]:
    """Для каждого потребителя: изменился ли ответ — и ВЫРОСЛО ЛИ ПРИ ЭТОМ ПОКРЫТИЕ.

    Одного «вердикт изменился» мало, и первая редакция этого прибора на том и
    ошиблась: она объявила четверых потребителей сломанными, тогда как у всех
    четверых просто выросло число дней, которые они СУМЕЛИ оценить. Разница
    решает ответ на вопрос заказа: рост покрытия — это цена потолка, которую
    они платят сегодня, а сдвиг БЕЗ роста покрытия — регрессия, и только он
    делает починку дорогой.

    Три исхода на потребителя, третий обязателен: не запустился или не публикует
    счётчика покрытия ⇒ ``unmeasured`` с названной причиной.
    """
    out: List[dict] = []
    base_root = sandbox / "base"
    wide_root = sandbox / "wide"
    for root, data in ((base_root, rows), (wide_root, widened)):
        (root / "data").mkdir(parents=True, exist_ok=True)
        for name in _SANDBOX_FILES:
            src = sandbox / name
            if src.exists():
                shutil.copyfile(src, root / "data" / name)
        _write_journal(data, root / "data" / HISTORY_FILENAME)

    for spec in readers:
        row = {"module": spec["module"], "probe": spec["probe"]}
        try:
            base_cov, base = _reader_probe(spec, base_root)
        except Exception as exc:  # noqa: BLE001 — отказ потребителя есть ИСХОД
            row.update(verdict=VERDICT_UNMEASURED,
                       note=f"на базовом журнале не отработал ({type(exc).__name__}: {exc})")
            out.append(row)
            continue
        try:
            wide_cov, wide = _reader_probe(spec, wide_root)
        except Exception as exc:  # noqa: BLE001
            row.update(verdict=VERDICT_UNMEASURED,
                       note=f"на расширенном журнале не отработал ({type(exc).__name__}: {exc})")
            out.append(row)
            continue

        row["coverage_base"] = base_cov
        row["coverage_wide"] = wide_cov
        same = json.dumps(base, sort_keys=True, default=str) == \
            json.dumps(wide, sort_keys=True, default=str)
        if same:
            row.update(verdict=VERDICT_INSENSITIVE,
                       note="ответ не изменился: населению карты этот потребитель не подчинён")
        elif base_cov is None or wide_cov is None:
            row.update(verdict=VERDICT_UNMEASURED,
                       note=("ответ изменился, но собственного счётчика покрытия у "
                             "потребителя нет — НАПРАВЛЕНИЕ сдвига не измерено, и "
                             "выдавать его за регрессию нельзя"))
        elif wide_cov > base_cov:
            row.update(verdict=VERDICT_PAYS,
                       note=(f"покрытие выросло {base_cov} → {wide_cov}: сегодня этот "
                             "потребитель считает свои числа на том, что потолок дал "
                             "оценить — он ПЛАТИТ за потолок, а не ломается от полноты"))
        else:
            row.update(verdict=VERDICT_MOVED,
                       moved_keys=_changed_keys(base, wide),
                       note=(f"ответ изменился, а покрытие НЕ выросло ({base_cov} → "
                             f"{wide_cov}): то же население, другое число — регрессия"))
        out.append(row)
    return out


# ──────────────────────────────────────────────────────────────────────────
# сборка
# ──────────────────────────────────────────────────────────────────────────
def measure(data_dir: Path, *,
            now: Optional[datetime] = None,
            ranked_producer_factory: Optional[Callable[[Path], Callable]] = None,
            readers: Tuple[dict, ...] = READERS) -> dict:
    """Полный замер. Детерминирован при тех же файлах на диске."""
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    doc: dict = {
        "schema": VERSION,
        "generated_at": now.isoformat(),
        "status": STATUS_UNMEASURED,
        "writer": ("spa_core/paper_trading/allocation_rationale.py::"
                   "build_history_record ← write_shadow_rationale"),
        "callers": ["spa_core/paper_trading/cycle_runner.py (шаг 2f)",
                    "spa_core/paper_trading/hy_cycle.py",
                    "spa_core/paper_trading/lp_cycle.py"],
        "findings": [],
        "not_measured_by_design": [
            "ставки прошлого для НЕПРОФИНАНСИРОВАННЫХ ключей — их не записывал "
            "никто, и расширенный журнал пробы чувствительности историей не является",
            "воспроизводимость ЦЕЛИ по журналу (ADR-279) — это другой вопрос, и "
            "ссылаться на него как на причину неполноты входов значило бы замкнуть круг",
        ],
        "advisory": ("писатель не изменён ни на строку; пороги RiskPolicy v1.0, "
                     "потолки концентрации, TriggerParams, kill-switch и живой "
                     "трек не тронуты, капитал не сдвинут"),
    }

    rows, jerr = read_journal(data_dir)
    doc["journal_rows"] = len(rows)
    if jerr or not rows:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] журнал решений нечитаем или пуст "
            f"({jerr or 'ни одной записи'}) — перепись входов мерить не на чем")
        return doc

    sandbox = Path(tempfile.mkdtemp(prefix="spa_djc_"))
    try:
        for name in _SANDBOX_FILES:
            src = data_dir / name
            if src.exists():
                shutil.copyfile(src, sandbox / name)

        produce = (ranked_producer_factory or _default_ranked_producer)(sandbox)
        try:
            ranked, sources = produce()
        except Exception as exc:  # noqa: BLE001
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] производитель ранжируемого набора не отработал "
                f"({type(exc).__name__}: {exc}) — «держит» сравнить не с чем")
            return doc
        if not ranked:
            doc["findings"].append(
                "[НЕ ИЗМЕРЕНО] производитель вернул пустой ранжируемый набор — "
                "это находка о ПРОИЗВОДИТЕЛЕ, а не о переписи входов")
            return doc

        # Контроль детерминизма — положительный контроль на сам стенд:
        # недетерминированный производитель обесценил бы каждое число ниже, и
        # молчать об этом нельзя (тот же приём, что в ``target_stability``).
        try:
            again_ranked, again_sources = produce()
            doc["determinism"] = ("reproduced"
                                  if (again_ranked, again_sources) == (ranked, sources)
                                  else "DIVERGED")
        except Exception as exc:  # noqa: BLE001
            doc["determinism"] = "unmeasured"
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] повтор прогона производителя не удался "
                f"({type(exc).__name__}: {exc})")
        if doc["determinism"] == "DIVERGED":
            doc["findings"].append(
                "[CRITICAL] производитель ранжируемого набора НЕдетерминирован "
                "на одних и тех же входах — щель ниже измерена быть не может")
            # Статус ставится ЗДЕСЬ и намеренно: ранний возврат минует `_judge`,
            # и без этой строки отчёт вышел бы с находкой [CRITICAL] при статусе
            # UNMEASURED — два артефакта одного прогона, спорящие между собой.
            # Недетерминизм производителя — громкий дефект, а не «нечего мерить».
            doc["status"] = STATUS_CRITICAL
            return doc

        ranked_live = {p for p, s in sources.items() if s == "live"}
        doc["ranked"] = len(ranked)
        doc["ranked_live"] = len(ranked_live)
        doc["ranked_by_source"] = {s: sum(1 for v in sources.values() if v == s)
                                   for s in sorted(set(sources.values()))}

        last = rows[-1]
        universe = record_universe(last)
        written = set((last.get("apy_evidenced_pct") or {}).keys())
        gap = split_gap(ranked_live, universe, written)
        gap["journal_day"] = last.get("cycle_date")
        doc["gap"] = gap
        doc["never_written"] = never_seen(rows, ranked_live)

        # ── B: чем именно отсекает писатель ────────────────────────────────
        unfunded_live = next((k for k in sorted(ranked_live - universe)), None)
        funded_live = next((k for k in sorted(written)), None)
        cur = {str(k): float(v) for k, v in (last.get("current_positions") or {}).items()}
        tgt = {str(k): float(v) for k, v in (last.get("target_positions") or {}).items()}
        src_for_probe = {k: "live" for k in written}
        src_for_probe.update({k: "live" for k in ranked_live})
        rates_for_probe = dict(ranked)
        rates_for_probe.update({k: float(v) for k, v
                                in (last.get("apy_evidenced_pct") or {}).items()})
        doc["criterion"] = probe_criterion(
            apy_pct=rates_for_probe, apy_sources=src_for_probe,
            current_positions=cur, target_positions=tgt,
            capital_usd=float(last.get("capital_usd") or 0.0),
            unfunded_live=unfunded_live, funded_live=funded_live)

        # ── C: цена у потребителей ─────────────────────────────────────────
        doc["readers"] = probe_readers(
            rows, widen_journal(rows, ranked, ranked_live), sandbox, readers)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    _judge(doc)
    return doc


def _judge(doc: dict) -> None:
    """Вердикт и находки — по замерам выше, без второго набора правил."""
    gap = doc.get("gap") or {}
    crit = doc.get("criterion") or {}
    readers = doc.get("readers") or []

    moved = [r for r in readers if r.get("verdict") == VERDICT_MOVED]
    pays = [r for r in readers if r.get("verdict") == VERDICT_PAYS]
    unmeasured = [r for r in readers if r.get("verdict") == VERDICT_UNMEASURED]

    frac = gap.get("written_frac_of_ranked_live")
    if crit.get("verdict") == "full_live_set":
        doc["findings"].append(
            "[ПИСАТЕЛЬ РАСШИРЕН] население записи — весь живой набор дня "
            f"(ADR-309): проба положила ключ ОДНОЙ картой ставок, и он в записи "
            f"появился; непрофинансированный ключ лежит там без единой мутации. "
            f"Живой снимок писателя сейчас {crit.get('base_written_n')} ставок. "
            "Живость фида отсекать не перестала и НЕ молчит (ключ без провенанса "
            "уезжает в `apy_unevidenced`), а ключ с провенансом, но без числа, "
            "в население не входит вовсе — контроль это подтвердил")
        doc["findings"].append(
            "[СМЕШАННОЕ НАСЕЛЕНИЕ] строки журнала ДО ADR-309 писались узким "
            f"писателем: сейчас в файле записано {gap.get('written')} ставок "
            f"против {gap.get('ranked_live')} ранжируемых живым снимком. Пока "
            "обратное заполнение не применено, любое сравнение дня с днём через "
            "границу правки сравнивает не поведение, а ПЕРЕПИСЬ "
            "(`journal_population_backfill.json` — что и чем закрываемо)")
    elif crit.get("verdict") == "still_funded_set":
        doc["findings"].append(
            "[НАХОДКА] расширение ADR-309 до писателя НЕ ДОЕХАЛО: ключ вне обеих "
            "книг с живым провенансом и числом в запись не попал. Население "
            "записи снова КНИГА, и всё, что считается на журнале, платит "
            "прежнюю цену узкой переписи")
    elif crit.get("verdict") == "unpriced_admitted":
        doc["findings"].append(
            "[НАХОДКА] в население записи вошёл ключ с живым провенансом, но БЕЗ "
            "числа — расширение идёт не по `priced_live`, и запись несёт ставку, "
            "которой нет")
    elif crit.get("verdict") == "unmeasured":
        doc["findings"].append(
            "[НЕ ИЗМЕРЕНО] пробы населения не на чем поставить — состав записи "
            "названа НЕ БЫЛ (см. `criterion.probes`)")
    else:
        doc["findings"].append(
            "[НАХОДКА] население записи не совпало ни с книгой, ни с живым "
            "набором дня — разбирать по `criterion.probes` поимённо")

    if doc.get("never_written"):
        doc["findings"].append(
            f"[ПОТОЛОК] {len(doc['never_written'])} живых ранжируемых ключей не "
            f"встречаются в журнале НИ РАЗУ за {doc.get('journal_rows')} дней: "
            f"{', '.join(doc['never_written'])} — это отсутствие ЗАМЕРА, а не "
            "наблюдение «ставка не двигалась»")

    if pays:
        doc["findings"].append(
            f"[ЦЕНА ПОТОЛКА] {len(pays)} потребител(я/ей) журнала платят за него "
            "прямо сейчас — их собственный счётчик покрытия растёт вместе с "
            "населением карты: "
            + "; ".join(f"{r['module'].rsplit('.', 1)[-1]} {r.get('coverage_base')}→"
                        f"{r.get('coverage_wide')}" for r in sorted(pays, key=lambda x: x["module"]))
            + ". Это НЕ поломка от полноты: сегодня их числа посчитаны на том "
              "подмножестве дней, которое потолок дал оценить, и починка журнала их "
              "переизложит — вширь")
    if moved:
        doc["findings"].append(
            f"[CRITICAL] {len(moved)} потребител(я/ей) сдвинули ответ БЕЗ роста "
            "покрытия — то же население, другое число: "
            f"{', '.join(sorted(r['module'] for r in moved))}. Это и есть настоящая "
            "цена расширения записи, и её нельзя платить молча")
    if unmeasured:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] у {len(unmeasured)} потребител(я/ей) направление сдвига "
            "не измерено (не отработал либо не публикует счётчика покрытия): "
            f"{', '.join(sorted(r['module'] for r in unmeasured))}")

    if crit.get("verdict") == "unmeasured" or not readers:
        doc["status"] = STATUS_UNMEASURED
    elif moved or crit.get("verdict") == "second_door_found":
        doc["status"] = STATUS_CRITICAL
    elif frac is not None and frac < _CEILING_FRAC:
        doc["status"] = STATUS_CRITICAL
    else:
        doc["status"] = STATUS_WARNING


def format_report(doc: dict) -> List[str]:
    gap = doc.get("gap") or {}
    out = [f"перепись входов журнала решений (заказ #539): {doc.get('status')}"]
    if gap:
        frac = gap.get("written_frac_of_ranked_live")
        out.append(
            f"   держит {gap.get('ranked_live')} живых ранжируемых → пишет "
            f"{gap.get('written')}"
            + (f" ({frac * 100:.0f} %)" if isinstance(frac, float) else "")
            + f" · день {gap.get('journal_day')} · дней в журнале {doc.get('journal_rows')}")
    if doc.get("criterion"):
        out.append(f"   отбор: {doc['criterion'].get('verdict')}")
    for r in doc.get("readers") or []:
        cov = ("" if r.get("coverage_base") is None
               else f" (покрытие {r.get('coverage_base')}→{r.get('coverage_wide')})")
        out.append(f"   · {r['module'].rsplit('.', 1)[-1]} → {r['verdict']}{cov}")
    for f in doc.get("findings") or []:
        out.append(f"   {f}")
    if doc.get("advisory"):
        out.append(f"   ADVISORY: {doc['advisory']}")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, **kwargs) -> dict:
    """Форма, которую ждут ступень переписей ``findings_bridge`` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = measure(data_dir, now=now, **kwargs)
    findings = list(doc.get("findings") or [])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for f in findings if f.startswith("[CRITICAL]")),
        "warn": sum(1 for f in findings if f.startswith("[ПОТОЛОК]")
                    or f.startswith("[ЦЕНА")),
        "info": 0,
        # «не измерено» считается ОТДЕЛЬНО: растворив его в нулях, мы сделали бы
        # молчание прибора неотличимым от чистого прогона.
        "unchecked": (1 if doc["status"] == STATUS_UNMEASURED else 0)
                     + sum(1 for f in findings if f.startswith("[НЕ ИЗМЕРЕНО]")),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="перепись входов журнала решений: что писатель держит и что пишет")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    data_dir = (Path(args.data_dir) if args.data_dir
                else Path(os.environ.get("SPA_DATA_DIR")
                          or (Path(__file__).resolve().parents[2] / "data")))
    doc = measure(data_dir)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(data_dir) / OUTPUT_FILENAME))
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
