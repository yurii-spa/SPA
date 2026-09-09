"""spa_core/monitoring/ranking_tie_persistence.py — ничья РАЗ В ТРИДЦАТЬ ДНЕЙ и
ничья КАЖДЫЙ ДЕНЬ требуют разных решений владельца (заказ цикла #536 по
карточке CIO, гэп G5→G6).

ADR-284 сосчитал ничьи ранжирования на снимке ОДНОГО дня: из 13 соседних пар
порядок решает деньги в трёх, и на двух изолированных переезжает $16 711.
Заказ #536 указал на предел этого числа: вопрос ТЗ CIO — про **режим работы**
системы, а перепись отвечает про **сегодня**. Пара, которая ничья один день из
тридцати, и пара, которая ничья каждый день, в отчёте #536 неразличимы, а
решения требуют разных: первая — случай, вторая — устройство.

Заказ: прогнать перепись по наблюдённым дням и измерить, сколько дней подряд
одна и та же пара остаётся ничьёй.

Ловушка заказа, названная заранее, и ловушка ЭТАЖОМ НИЖЕ
========================================================

Заказ предупредил: цель по журналу решений НЕ считать — ``apy_evidenced_pct``
есть НЕПОЛНАЯ перепись входов (ADR-279: точный реплей сошёлся на 5 из 34 дней,
``morpho_steakhouse`` держал в цели $40 000, не появившись в карте ни разу).
Ставки из журнала брать МОЖНО — это наблюдение того дня; цель — только у живого
производителя в песочнице.

Ровно так здесь и сделано. Но у той же неполноты есть **второе следствие**, и
оно этажом ниже: набор ставок задаёт не только их значения, но и **НАСЕЛЕНИЕ**
ранжирования. Замер: журнал несёт **4–6** ставок в день, живой снимок
ранжирует **14**. Отдать производителю ставки одного дня — значит получить
ранжирование ИЗ ЧЕТЫРЁХ-ШЕСТИ КЛЮЧЕЙ, и «пара соседей» в нём — артефакт
покрытия журнала, а не порядок того дня. Между двумя «соседями» покрытого
набора в настоящем порядке может стоя́ть кто угодно.

Отсюда прибор делит измеряемое на две части, и деление это ИЗМЕРЕНО, а не
объявлено:

* **что от покрытия НЕ зависит** — счёт ключа и стоимость перестановки ПАРЫ.
  Проверяется каждый прогон на КАЖДОМ дне журнала: те же ставки подаются
  производителю дважды — только журнальные (режим A) и живой снимок с
  наложенными журнальными (режим B). Замер 09.09: ``max |score_A − score_B|``
  = **0.000e+00** на 35 днях и 168 ключах, стоимостей перестановки совпало
  **330**, разошлось **0**. ``None`` в обоих режимах засчитывается как
  СОГЛАСИЕ («перестановки нет в диапазоне»), а не расхождение — иначе опора
  падала бы на самом частом честном исходе. Разошлись бы ⇒ прибор
  ОТКАЗЫВАЕТСЯ считаться;
* **что от покрытия зависит** — СОСЕДСТВО и ХОД КАПИТАЛА. Их прибор по дням
  НЕ считает и не печатает. Молчаливо посчитать «сколько денег стояло на
  ничьей 13 августа» значило бы выдать покрытие журнала за книгу того дня.

Что измеряется
==============

Ярлык ничьи — тот же, что у ADR-279 и ADR-284, чтобы числа трёх приборов были
сравнимы: перестановка пары стои́т МЕНЬШЕ, чем эта ставка сама проходит за
сутки на трети наблюдённых дней и чаще. Меняется по дням только СТОИМОСТЬ
ПЕРЕСТАНОВКИ (её задают ставки того дня), ярлык остаётся один.

Стоимость перестановки берётся ИЗМЕРЕНИЕМ у канонического измерителя
(``ranking_tie_census.smallest_flip``), а не аналитической формулой
``разрыв/множитель``. Формула соблазнительна и дешева, и она НЕВЕРНА в сторону
«ничьих больше, чем есть»: замер 09.09 на живом снимке дал у неё 1.5402 pp
против измеренных 1.9195 pp у ``aave_arbitrum``/``sdai`` — **занижение 22.9 %**
на 12 парах, а заниженная стоимость перестановки чаще пролезает под дневной
ход. Точные ничьи в эту долю не входят: у них она 100 % при любом кванте и
говорит о делении на единицу измерения, а не о формуле. Расхождение
``analytic_vs_measured`` печатается рядом с числом: выбор ярлыка обязан быть
виден, а не спрятан.

«Подряд» имеет ДВА смысла, и они разные
=======================================

Дни журнала не сплошные, и пара наблюдается только когда покрыты ОБА её ключа.
``aave_v3``/``compound_v3`` наблюдалась 08-09, 08-10, 09-02, 09-03, 09-04,
09-07, 09-09 — «семь дней подряд» здесь правда про наблюдения и НЕПРАВДА про
календарь: между вторым и третьим 23 дня. Поэтому серия считается ДВАЖДЫ —
``longest_run_observed`` (подряд по наблюдениям) и ``longest_run_calendar``
(подряд по календарю), — и в находки идёт календарная. Одно число вместо двух
читалось бы как утверждение о режиме, которого замер не делает.

Тождество пула — ОТДЕЛЬНЫЙ признак (ловушка #535 остаётся в силе)
================================================================

``morpho_blue``/``morpho_steakhouse`` (ничья 7 дней из 7) и
``fluid_fusdc``/``fluid_usdc`` — ОДИН контракт под двумя именами по
каноническому измерителю ADR-227. Прибор читает тождество по АДРЕСУ у него и
НЕ пересчитывает, ключи НЕ сливает и вердикт печатает рядом: «ничья, потому что
это один пул» и «ничья двух РАЗНЫХ инструментов» — разные предметы и разные
решения владельца. Слив их в одну строку закрыл бы вопрос ссылкой на чужую
находку — ровно то, от чего предостерегал заказ #535.

Отдельно из-за этого же тождества: журнал зовёт пул ``fluid_usdc``, живой
снимок — ``fluid_fusdc``. Соединение переписи с журналом идёт СТРОГО ПО ИМЕНИ,
а совпадение по адресу называется ОТДЕЛЬНОЙ строкой; молча срастив имена, мы
подменили бы «эта пара наблюдалась» на «наблюдалась похожая».

**ADVISORY.** Модуль ничего не гейтит и капитал не двигает: читает снимок и
журнал, считает цель в песочнице (копия), пишет число. Пороги RiskPolicy v1.0,
потолки концентрации, ``TriggerParams``, kill-switch и живой трек не тронуты.
Починка ступеньки отдана владельцу карточкой
``owner-decision-devyat-tysyach-dollarov-dostayutsya-prot`` циклом #535 и здесь
НЕ делается — это money-path. Ветка ``except Exception`` демпфера
``churn_damper``, названная ловушкой в заказе #534, снова НЕ трогается.
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("spa.monitoring.ranking_tie_persistence")

VERSION = "ranking-tie-persistence-v1"
OUTPUT_FILENAME = "ranking_tie_persistence.json"

#: Доля наблюдённых дней, с которой «ставка сама проходит разрыв» перестаёт быть
#: единичным случаем. Тот же ярлык, что у ADR-279 и ADR-284 — намеренно: три
#: прибора отвечают на соседние вопросы об одной ступеньке, и разные пороги
#: сделали бы их числа несравнимыми. Порог прибора, к RiskPolicy отношения не
#: имеет и ничего не гейтит.
NOISE_DECIDED_FRAC = 1.0 / 3.0

#: С какой длины КАЛЕНДАРНАЯ серия ничьих перестаёт быть случаем и называется
#: режимом. Порог прибора; он ничего не гейтит, он решает лишь, писать ли строку
#: находки. Два дня подряд — ещё совпадение, три — уже устройство.
REGIME_RUN_DAYS = 3

STATUS_OK = "OK"
STATUS_CRITICAL = "CRITICAL"
STATUS_WARNING = "WARNING"
STATUS_UNMEASURED = "UNMEASURED"

VERDICT_TIE = "tie"
VERDICT_HOLDS = "gap_holds"
VERDICT_NO_FLIP = "no_flip_in_range"
VERDICT_MOVE_UNMEASURED = "move_unmeasured"


# ──────────────────────────────────────────────────────────────────────────
# входы
# ──────────────────────────────────────────────────────────────────────────
def _read_json(path: Path) -> Tuple[Optional[dict], str]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), ""
    except Exception as exc:  # noqa: BLE001 — причина уезжает в отчёт словами
        return None, f"{type(exc).__name__}: {exc}"


def journal_days(data_dir: Path) -> Tuple[List[dict], str]:
    """[{date, rates в ДОЛЯХ}] по дням журнала решений, по возрастанию даты.

    Журнал даёт НАБЛЮДЕНИЕ ставки того дня (``apy_evidenced_pct``, записан самим
    писателем решения) — и только его. Цель отсюда НЕ берётся: заказ #536 назвал
    это ловушкой, а ADR-279 измерил, что реплей по журналу сходится на 5 днях
    из 34.

    Ставка в файле в ПРОЦЕНТАХ, контракт провайдера аллокатора — ДОЛИ; пересчёт
    здесь единственный и явный, тот же, что в ``target_stability.live_apy_map``.
    """
    from spa_core.monitoring import target_stability as ts

    path = Path(data_dir) / ts.HISTORY_FILENAME
    rows: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:  # noqa: BLE001 — битая строка не рушит перепись
                    continue
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    rows.sort(key=lambda r: (str(r.get("cycle_date") or ""),
                             str(r.get("generated_at") or "")))
    out: List[dict] = []
    for r in rows:
        rates: Dict[str, float] = {}
        for proto, val in (r.get("apy_evidenced_pct") or {}).items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                fv = float(val)
                if fv == fv and abs(fv) != float("inf"):
                    rates[str(proto)] = fv / 100.0
        if rates:
            out.append({"date": str(r.get("cycle_date") or ""), "rates": rates})
    return out, ""


# ──────────────────────────────────────────────────────────────────────────
# серии
# ──────────────────────────────────────────────────────────────────────────
def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:  # noqa: BLE001 — неразобранная дата не рушит счёт
        return None


def longest_run_observed(verdicts: Sequence[str]) -> int:
    """Самая длинная серия ``tie`` ПОДРЯД ПО НАБЛЮДЕНИЯМ.

    Календарные дыры здесь не видны намеренно — это ответ на вопрос «сколько раз
    подряд, когда мы смотрели, она была ничьёй». Второй вопрос («сколько дней
    подряд») меряет :func:`longest_run_calendar`, и путать их нельзя.
    """
    best = cur = 0
    for v in verdicts:
        cur = cur + 1 if v == VERDICT_TIE else 0
        best = max(best, cur)
    return best


def longest_run_calendar(days: Sequence[Tuple[str, str]]) -> Tuple[int, Optional[str], Optional[str]]:
    """Самая длинная серия ``tie`` подряд ПО КАЛЕНДАРЮ: (длина, начало, конец).

    Разрыв в наблюдениях РВЁТ серию: день, который мы не смотрели, ничьёй не
    наблюдался, и считать его ничьёй значило бы дописать наблюдение. Разрыв
    — это третий исход, а не продолжение.
    """
    best, best_lo, best_hi = 0, None, None
    cur, cur_lo, prev = 0, None, None
    for raw, verdict in days:
        d = _parse_date(raw)
        if verdict != VERDICT_TIE or d is None:
            cur, cur_lo, prev = 0, None, d
            continue
        if prev is not None and cur and (d - prev).days == 1:
            cur += 1
        else:
            cur, cur_lo = 1, raw
        prev = d
        if cur > best:
            best, best_lo, best_hi = cur, cur_lo, raw
    return best, best_lo, best_hi


def tie_verdict(flip_pp: Optional[float],
                moves: Dict[str, List[float]],
                above: str,
                below: str,
                noise_frac: float = NOISE_DECIDED_FRAC) -> Tuple[str, int, int]:
    """Вердикт для пары на ОДИН день: (вердикт, дней-пересечений, наблюдений).

    Ярлык ADR-279 без изменений: ставка пары сама проходит стоимость
    перестановки на ≥ ``noise_frac`` наблюдённых дней. Нет истории ни у одной из
    двух ставок ⇒ ``move_unmeasured``: ноль наблюдений за «разрыв держит» не
    выдаётся (третий исход, а не тихое «нет»).
    """
    if flip_pp is None:
        return VERDICT_NO_FLIP, 0, 0
    best_n, best_m = 0, 0
    for side in (above, below):
        series = moves.get(side) or []
        if not series:
            continue
        n = sum(1 for x in series if x >= flip_pp)
        if not best_m or (n / len(series)) > (best_n / best_m):
            best_n, best_m = n, len(series)
    if not best_m:
        return VERDICT_MOVE_UNMEASURED, 0, 0
    if (best_n / best_m) >= noise_frac:
        return VERDICT_TIE, best_n, best_m
    return VERDICT_HOLDS, best_n, best_m


# ──────────────────────────────────────────────────────────────────────────
# ОПОРА: покрытие журнала не должно менять измеряемое
# ──────────────────────────────────────────────────────────────────────────
def verify_coverage_independence(produce,
                                 live: Dict[str, float],
                                 days: Sequence[dict],
                                 quantum: float,
                                 *,
                                 max_days: Optional[int] = None) -> dict:
    """Зависят ли счёт и стоимость перестановки от ПОКРЫТИЯ журнала?

    Единственная опора, на которой стои́т право реконструировать день по 4–6
    ставкам вместо 14. Меряется, а не предполагается: те же ставки подаются
    производителю дважды — только журнальные (режим A) и живой снимок с
    наложенными журнальными (режим B). Совпало ⇒ величина от покрытия не
    зависит и по дням её считать можно; разошлось ⇒ прибор отказывается.

    ``None`` в ОБОИХ режимах — это СОГЛАСИЕ («перестановки нет в диапазоне»), а
    не расхождение. Считать его расхождением значило бы уронить опору на самом
    частом честном исходе.
    """
    from spa_core.monitoring import ranking_tie_census as rtc

    checked = sorted(days, key=lambda d: str(d.get("date") or ""))
    if max_days:
        checked = checked[-int(max_days):]
    worst_score = 0.0
    score_keys = 0
    flip_same = 0
    flip_diverged: List[str] = []
    for day in checked:
        rates = dict(day.get("rates") or {})
        if not rates:
            continue
        try:
            _t, bd_a, _c = produce(dict(rates))
            prov_b = dict(live)
            prov_b.update(rates)
            _t2, bd_b, _c2 = produce(prov_b)
        except Exception as exc:  # noqa: BLE001 — отказ прогона ≠ «совпало»
            return {"verdict": "unmeasured",
                    "note": (f"прогон опоры не удался на {day.get('date')} "
                             f"({type(exc).__name__}: {exc})"),
                    "days_checked": 0, "max_score_delta": None,
                    "flips_identical": 0, "flips_diverged": []}
        for k in sorted(set(bd_a) & set(bd_b) & set(rates)):
            sa = float((bd_a[k] or {}).get("score") or 0.0)
            sb = float((bd_b[k] or {}).get("score") or 0.0)
            worst_score = max(worst_score, abs(sa - sb))
            score_keys += 1
        order_a = rtc.ranked_order(bd_a, [p for p in bd_a if p in rates])
        order_b = rtc.ranked_order(bd_b, [p for p in bd_b if p in prov_b])
        for x, y in itertools.combinations(sorted(rates), 2):
            if x not in order_a or y not in order_a:
                continue
            above, below = ((x, y) if order_a.index(x) < order_a.index(y)
                            else (y, x))
            fa = rtc.smallest_flip(produce, rates, order_a, above, below, quantum)
            fb = rtc.smallest_flip(produce, prov_b, order_b, above, below, quantum)
            va = fa["flip_pp"] if fa else None
            vb = fb["flip_pp"] if fb else None
            if va is None and vb is None:
                flip_same += 1
            elif va is None or vb is None or abs(va - vb) > quantum / 2.0:
                flip_diverged.append(f"{day.get('date')} {above}/{below}: "
                                     f"A={va} B={vb}")
            else:
                flip_same += 1
    if not score_keys:
        return {"verdict": "unmeasured",
                "note": "ни одного ключа не удалось сравнить в двух режимах",
                "days_checked": len(checked), "max_score_delta": None,
                "flips_identical": 0, "flips_diverged": []}
    ok = (worst_score == 0.0) and not flip_diverged
    return {
        "verdict": ("independent" if ok else "DEPENDS_ON_COVERAGE"),
        "note": (f"дней сверено {len(checked)}, ключей {score_keys}; "
                 f"max |score_A−score_B| = {worst_score:.3e}; стоимостей "
                 f"перестановки совпало {flip_same}, разошлось "
                 f"{len(flip_diverged)}"),
        "days_checked": len(checked),
        "max_score_delta": worst_score,
        "flips_identical": flip_same,
        "flips_diverged": flip_diverged[:10],
    }


# ──────────────────────────────────────────────────────────────────────────
# замер
# ──────────────────────────────────────────────────────────────────────────
def measure(data_dir: Path,
            *,
            now: Optional[datetime] = None,
            producer_factory=None,
            noise_frac: float = NOISE_DECIDED_FRAC,
            regime_run_days: int = REGIME_RUN_DAYS,
            coverage_probe_days: Optional[int] = None) -> dict:
    """Полный замер. Никогда не поднимает исключение; отказ = третий исход."""
    from spa_core.monitoring import ranking_tie_census as rtc
    from spa_core.monitoring import target_stability as ts

    now = now or datetime.now(timezone.utc)
    data_dir = Path(data_dir)
    doc: dict = {
        "schema": VERSION,
        "generated_at": now.isoformat(),
        "mode": "advisory",
        "note": ("устойчивость населения ничьих: сколько дней подряд одна и та "
                 "же пара остаётся ничьёй (заказ #536). Ничего не гейтит."),
        "noise_frac": float(noise_frac),
        "regime_run_days": int(regime_run_days),
        "status": STATUS_UNMEASURED,
        "quantum_pp": None,
        "coverage_independence": {"verdict": "unmeasured",
                                  "note": "замер не дошёл до опоры"},
        "day_axis_control": {"verdict": "unmeasured",
                             "note": "замер не дошёл до контроля"},
        "journal_days": 0,
        "journal_coverage": {},
        "live_universe_size": 0,
        "census_pairs": [],
        "pairs": [],
        "analytic_vs_measured": {},
        "counts_by_class": {},
        "findings": [],
        "unmeasured": [],
        "not_measured_by_design": [
            "СОСЕДСТВО пары в порядке того дня — покрытие журнала 4–6 ключей "
            "против 14 ранжируемых живым снимком; кто стоит между двумя "
            "«соседями» покрытого набора, журнал не знает",
            "ХОД КАПИТАЛА на ничьей того дня — по той же причине: книга того "
            "дня из журнала не восстанавливается (ADR-279, реплей сошёлся на "
            "5 днях из 34)",
        ],
    }

    status_doc, err = _read_json(data_dir / "adapter_status.json")
    if status_doc is None:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] снимок наблюдений adapter_status.json нечитаем ({err})")
        return doc
    live = ts.live_apy_map(status_doc)
    if not live:
        doc["findings"].append(
            "[НЕ ИЗМЕРЕНО] ни одной наблюдённой ставки в снимке — "
            "ранжировать нечего (находка о производителе, не о ничьих)")
        return doc

    days, jerr = journal_days(data_dir)
    if jerr or not days:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] журнал решений нечитаем или пуст "
            f"({jerr or 'ни одного дня со ставками'}) — устойчивость мерить не на чем")
        return doc
    doc["journal_days"] = len(days)

    identity_doc, ident_err = _read_json(data_dir / rtc.IDENTITY_ARTIFACT)
    if identity_doc is None:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] канонический измеритель тождества пула нечитаем "
            f"({ident_err}) — признак «один контракт» не спрошен ни у одной пары; "
            f"второй измеритель того же факта здесь НЕ строится (ADR-227)")
    moves, hist_err, _rows = ts.observed_daily_moves(data_dir)
    if hist_err:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] собственный ход ставок нечитаем ({hist_err}) — "
            "ярлык ничьи сравнить не с чем")

    sandbox = Path(tempfile.mkdtemp(prefix="spa_tie_persist_"))
    try:
        for name in ts._SANDBOX_FILES:
            src = data_dir / name
            if src.exists():
                shutil.copyfile(src, sandbox / name)
        produce = (producer_factory or rtc._default_producer)(sandbox)

        try:
            base_target, base_breakdown, _cap = produce(dict(live))
        except Exception as exc:  # noqa: BLE001
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] производитель цели не отработал "
                f"({type(exc).__name__}: {exc})")
            return doc
        live_universe = [p for p in base_breakdown if p in live]
        live_order = rtc.ranked_order(base_breakdown, live_universe)
        doc["live_universe_size"] = len(live_order)

        covered = sorted({k for d in days for k in (d.get("rates") or {})})
        per_day = [len(d.get("rates") or {}) for d in days]
        doc["journal_coverage"] = {
            "keys": covered,
            "keys_total": len(covered),
            "per_day_min": min(per_day) if per_day else 0,
            "per_day_max": max(per_day) if per_day else 0,
            "live_ranked": len(live_order),
            "keys_not_ranked_live": sorted(set(covered) - set(live_order)),
            "ranked_live_not_in_journal": sorted(set(live_order) - set(covered)),
            "note": ("покрытие журнала — НЕ книга того дня. Отсюда следует, что "
                     "соседство и ход капитала по дням не считаются (см. "
                     "not_measured_by_design)"),
        }

        if len(live_order) < 2:
            doc["status"] = STATUS_OK
            doc["findings"].append(
                f"[OK] ранжируемых ключей {len(live_order)} — пары не из чего составить")
            return doc

        quantum, q_err = rtc.measure_quantum(
            lambda pr: produce(pr)[1], live, live_order[-1])
        doc["quantum_pp"] = quantum
        if quantum is None:
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] квант ранжируемой ставки не измерен ({q_err}) — "
                f"перепись НЕ считается: возмущение ниже кванта отвечает «ничего "
                f"не двигается» на любой вопрос, и это молчание неотличимо от "
                f"чистого прогона")
            return doc

        # ОПОРА. Без неё реконструкция дня по 4–6 ставкам — измерение покрытия
        # журнала, выданное за измерение книги.
        ci = verify_coverage_independence(produce, live, days, quantum,
                                          max_days=coverage_probe_days)
        doc["coverage_independence"] = ci
        if ci["verdict"] != "independent":
            doc["status"] = STATUS_UNMEASURED
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] опора не подтверждена ({ci['verdict']}): "
                f"{ci['note']}. Счёт и/или стоимость перестановки ЗАВИСЯТ от "
                f"того, сколько ключей покрыл журнал, поэтому реконструкция дня "
                f"по его ставкам измеряла бы покрытие, а не книгу. Перепись "
                f"отказывается считаться")
            return doc

        # Аналитический ярлык НЕ используется — но расхождение с ним меряется и
        # печатается, чтобы выбор был виден, а не спрятан.
        #
        # ТОЧНАЯ НИЧЬЯ СЧИТАЕТСЯ ОТДЕЛЬНО. У неё аналитический разрыв РОВНО ноль,
        # а измеренная стоимость перестановки — один квант, и доля занижения
        # выходит 100 % при любом кванте. Смешав её с остальными, головное число
        # («формула занижает до 100 %») говорило бы о вырожденном делении на
        # собственную единицу измерения, а не о качестве формулы.
        an_deltas: List[float] = []
        exact_ties = 0
        for i in range(len(live_order) - 1):
            a, b = live_order[i], live_order[i + 1]
            mult = float((base_breakdown[b] or {}).get("risk_multiplier") or 0.0)
            if mult <= 0:
                continue
            gap = (float((base_breakdown[a] or {}).get("score") or 0.0)
                   - float((base_breakdown[b] or {}).get("score") or 0.0))
            fl = rtc.smallest_flip(produce, live, live_order, a, b, quantum)
            if fl is None:
                continue
            analytic, meas = gap / mult, fl["flip_pp"]
            if analytic <= 0.0:
                exact_ties += 1
            elif meas > 0:
                an_deltas.append((meas - analytic) / meas)
        doc["analytic_vs_measured"] = {
            "pairs": len(an_deltas),
            "exact_ties_excluded": exact_ties,
            "max_understatement_frac": (round(max(an_deltas), 4) if an_deltas else None),
            "note": ("аналитическая формула «разрыв/множитель» ЗАНИЖАЕТ стоимость "
                     "перестановки, то есть ошибается в сторону «ничьих больше, "
                     "чем есть». Здесь она НЕ используется — стоимость меряется "
                     "у канонического измерителя; число печатается, чтобы выбор "
                     "ярлыка был виден. Точные ничьи (аналитический разрыв ровно "
                     "0) в долю НЕ входят: у них она 100 % при любом кванте и "
                     "говорит о делении на единицу измерения, а не о формуле"),
        }

        # ── население заказа: ПАРЫ, которые назвала перепись #535/#536 ──
        census_pairs = [(live_order[i], live_order[i + 1])
                        for i in range(len(live_order) - 1)]
        # ── плюс пары, соседние в СВОЁМ покрытом дне (контекст; покрытие-
        #    зависимое население, и это сказано вслух) ──
        day_adjacent: set = set()
        day_orders: List[Tuple[str, Dict[str, float], List[str]]] = []
        for day in days:
            rates = dict(day.get("rates") or {})
            try:
                _t, bd, _c = produce(dict(rates))
            except Exception as exc:  # noqa: BLE001 — день без прогона пропускаем громко
                doc["unmeasured"].append(
                    f"{day.get('date')}: прогон производителя не удался "
                    f"({type(exc).__name__}: {exc})")
                continue
            order = rtc.ranked_order(bd, [p for p in bd if p in rates])
            day_orders.append((str(day.get("date") or ""), rates, order))
            for i in range(len(order) - 1):
                day_adjacent.add(tuple(sorted((order[i], order[i + 1]))))

        population = sorted({tuple(sorted(p)) for p in census_pairs} | day_adjacent)
        doc["census_pairs"] = ["/".join(p) for p in
                               sorted(tuple(sorted(c)) for c in census_pairs)]

        rows: List[dict] = []
        for pair in population:
            x, y = pair
            seq: List[Tuple[str, str]] = []
            flips: List[Optional[float]] = []
            for dstr, rates, order in day_orders:
                if x not in order or y not in order:
                    continue
                above, below = ((x, y) if order.index(x) < order.index(y)
                                else (y, x))
                fl = rtc.smallest_flip(produce, rates, order, above, below, quantum)
                fp = fl["flip_pp"] if fl else None
                verdict, _n, _m = tie_verdict(fp, moves, above, below, noise_frac)
                seq.append((dstr, verdict))
                flips.append(fp)
            in_census = tuple(sorted(pair)) in {tuple(sorted(c)) for c in census_pairs}
            run_obs = longest_run_observed([v for _d, v in seq])
            run_cal, run_lo, run_hi = longest_run_calendar(seq)
            ties = sum(1 for _d, v in seq if v == VERDICT_TIE)
            measured_flips = [f for f in flips if f is not None]
            row = {
                "pair": f"{x}/{y}",
                "keys": [x, y],
                "in_live_census": in_census,
                "days_observed": len(seq),
                "days_tie": ties,
                "longest_run_observed": run_obs,
                "longest_run_calendar": run_cal,
                "longest_run_calendar_from": run_lo,
                "longest_run_calendar_to": run_hi,
                "first_day": seq[0][0] if seq else None,
                "last_day": seq[-1][0] if seq else None,
                "flip_pp_min": (round(min(measured_flips), 6) if measured_flips else None),
                "flip_pp_max": (round(max(measured_flips), 6) if measured_flips else None),
                "pool_identity": rtc.identity_verdict(x, y, identity_doc),
                "days": [{"date": d, "verdict": v} for d, v in seq],
            }
            # «Не измерено» и «измерено, ничьей нет» — РАЗНЫЕ классы, и путать их
            # здесь особенно дёшево: пара, у которой ни один день не дошёл до
            # ярлыка (обе ставки встречались в журнале по разу ⇒ собственного
            # хода нет; либо перестановка не нашлась в диапазоне), при подсчёте
            # «ties == 0» попадала бы в `never_a_tie` — то есть неизмеренное
            # выдавалось бы за измеренный отрицательный ответ. На живом снимке
            # 09.09 таких пар ноль, но это свойство ДАННЫХ, а не кода.
            measured_days = sum(1 for _d, v in seq
                                if v in (VERDICT_TIE, VERDICT_HOLDS))
            row["days_measured"] = measured_days
            if not seq:
                row["class"] = "never_co_observed"
            elif not measured_days:
                row["class"] = "co_observed_but_unmeasured"
            elif ties == 0:
                row["class"] = "never_a_tie"
            elif ties == len(seq):
                row["class"] = "always_a_tie"
            else:
                row["class"] = "sometimes_a_tie"
            rows.append(row)
        doc["pairs"] = rows

        classes: Dict[str, int] = {}
        for r in rows:
            classes[r["class"]] = classes.get(r["class"], 0) + 1
        doc["counts_by_class"] = classes

        # КОНТРОЛЬ ОСИ ДНЕЙ. Если ни у одной пары вердикт не меняется от дня к
        # дню, ось дней инертна — прибор печатал бы «сегодня» N раз подряд, и
        # это неотличимо от измеренного режима.
        varying = [r["pair"] for r in rows if r["class"] == "sometimes_a_tie"]
        doc["day_axis_control"] = {
            "verdict": ("live" if varying else "INERT"),
            "pairs_varying": len(varying),
            "examples": varying[:5],
            "note": ("вердикт обязан меняться хотя бы у одной пары: инертная ось "
                     "дней означала бы, что прибор повторяет снимок одного дня "
                     "столько раз, сколько в журнале строк"),
        }
        if not varying:
            doc["findings"].append(
                "[НЕ ИЗМЕРЕНО] ось дней ИНЕРТНА: ни у одной пары вердикт не "
                "изменился ни разу — прибор повторяет один и тот же ответ, и "
                "отличить режим от снимка по нему нельзя")

        # ── находки ──
        census_rows = [r for r in rows if r["in_live_census"]]
        silent = [r for r in census_rows if r["class"] == "never_co_observed"]
        regime = sorted((r for r in rows
                         if r["longest_run_calendar"] >= regime_run_days),
                        key=lambda r: -r["longest_run_calendar"])
        # МАКСИМУМ берётся ДО пересортировки населения. Ниже `regime`
        # переупорядочивается «пары переписи первыми», и `regime[0]` перестаёт
        # быть рекордом: головная строка сказала бы «максимум 5 дн.» там, где
        # замер видит 6. Замечено поведенческой проверкой отчёта, не тестом.
        longest = (max(regime, key=lambda r: r["longest_run_calendar"])
                   if regime else None)
        occasional = [r for r in rows if r["class"] == "sometimes_a_tie"]

        # Пары ПЕРЕПИСИ идут первыми — это население, о котором спросил заказ.
        # Контекстное население (соседство в СВОЁМ покрытом дне) зависит от
        # покрытия журнала и потому стои́т ниже, а не наравне.
        regime = sorted(regime, key=lambda r: (not r["in_live_census"],
                                               -r["longest_run_calendar"]))
        for r in regime:
            ident = ("; ОДИН пул по ADR-227 — ничья объясняется тождеством, "
                     "а не рынком" if r["pool_identity"] == rtc.IDENTITY_SAME
                     else "; РАЗНЫЕ пулы по ADR-227"
                     if r["pool_identity"] == rtc.IDENTITY_DIFFERENT
                     else "; тождество пула НЕ измерено")
            scope = ("пара ПЕРЕПИСИ #536" if r["in_live_census"]
                     else "контекст (соседство в своём покрытом дне)")
            doc["findings"].append(
                f"[CRITICAL] {r['pair']}: ничья {r['days_tie']} из "
                f"{r['days_observed']} наблюдённых дней, серия ПОДРЯД ПО "
                f"КАЛЕНДАРЮ {r['longest_run_calendar']} дн. "
                f"({r['longest_run_calendar_from']}…{r['longest_run_calendar_to']}), "
                f"подряд по наблюдениям {r['longest_run_observed']}. Это РЕЖИМ, "
                f"а не случай — {scope}{ident}")
        for r in silent:
            other = [k for k in r["keys"]]
            aliases = []
            for k in other:
                for coll in (identity_doc or {}).get("collisions") or []:
                    keys = (coll or {}).get("keys")
                    if isinstance(keys, list) and k in keys:
                        aliases += [a for a in keys if a != k and a in covered]
            hint = (f"; тот же контракт по ADR-227 стои́т в журнале под именем "
                    f"{sorted(set(aliases))} — имена НЕ срощены намеренно"
                    if aliases else "")
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] {r['pair']}: пара переписи #536 в журнале НЕ "
                f"наблюдалась НИ РАЗУ (обе ставки одного дня не встретились) — "
                f"устойчивость её ничьи не измерена, и «не ничья» из этого НЕ "
                f"следует{hint}")
        for r in (r for r in rows if r["class"] == "co_observed_but_unmeasured"):
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] {r['pair']}: пара наблюдалась "
                f"{r['days_observed']} дн., но НИ ОДИН день не дошёл до ярлыка "
                f"(собственного хода ставок нет либо перестановка не нашлась в "
                f"диапазоне) — «ничьей нет» из этого НЕ следует")
        for r in occasional:
            doc["findings"].append(
                f"[WARNING] {r['pair']}: ничья {r['days_tie']} из "
                f"{r['days_observed']} дней (календарная серия "
                f"{r['longest_run_calendar']}) — случай, а не режим; решения "
                f"владельца это требует ДРУГОГО")
        for u in doc["unmeasured"]:
            doc["findings"].append(f"[НЕ ИЗМЕРЕНО] {u}")

        if regime:
            doc["status"] = STATUS_CRITICAL
            in_census_regime = [r for r in regime if r["in_live_census"]]
            answered = [r for r in census_rows if r["days_observed"] > 0]
            always = [r for r in answered if r["class"] == "always_a_tie"]
            always_same_pool = [r for r in always
                                if r["pool_identity"] == rtc.IDENTITY_SAME]
            # ГОЛОВНАЯ СТРОКА ОТВЕЧАЕТ НА ВОПРОС ЗАКАЗА, а не на самый крупный
            # найденный факт: спрошено было про пары ПЕРЕПИСИ. Вести строку
            # рекордом контекстного населения значило бы отчитаться числом,
            # которого заказ не спрашивал, и спрятать за ним молчание про десять
            # пар, ради которых замер и делался.
            doc["findings"].insert(0, (
                f"[CRITICAL] ОТВЕТ ЗАКАЗУ #536, обе половины. (1) Ничья — РЕЖИМ, "
                f"а не случай: календарная серия ничьих ≥ {regime_run_days} дн. "
                f"у {len(regime)} пар(ы), максимум "
                f"{longest['longest_run_calendar']} дн. ({longest['pair']}). "
                f"(2) НО про население переписи #536 журнал почти молчит: из "
                f"{len(census_rows)} её пар он наблюдал {len(answered)}, а "
                f"{len(silent)} не наблюдал НИ РАЗУ — и это НЕ «не ничья», это "
                f"отсутствие замера. В режиме из переписи "
                f"{len(in_census_regime)} пар(ы)"
                + (f", и единственная ничья ВСЕГДА — {always[0]['pair']} "
                   f"({always[0]['days_tie']} из {always[0]['days_observed']} дн.), "
                   f"у которой ADR-227 видит ОДИН контракт под двумя именами: её "
                   f"постоянство объясняется тождеством, а не рынком"
                   if always and always_same_pool else "")
                + f". Журнал покрывает {doc['journal_coverage']['per_day_min']}–"
                f"{doc['journal_coverage']['per_day_max']} ставок в день против "
                f"{len(live_order)} ранжируемых живым снимком "
                f"({len(doc['journal_coverage']['ranked_live_not_in_journal'])} "
                f"ранжируемых ключей в нём не встречаются вовсе), поэтому "
                f"соседство и ход капитала по дням НЕ считаются"))
        elif (silent or occasional or doc["unmeasured"]
              or any(r["class"] == "co_observed_but_unmeasured" for r in rows)):
            doc["status"] = STATUS_WARNING
        else:
            doc["status"] = STATUS_OK
            doc["findings"].insert(0, (
                f"[OK] ни у одной пары календарная серия ничьих не достигла "
                f"{regime_run_days} дн. — ничья остаётся случаем, режима замер "
                f"не нашёл"))
        return doc
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────
# отчёт / проводка
# ──────────────────────────────────────────────────────────────────────────
def format_report(doc: dict) -> List[str]:
    """Строки для обязательного шага 0-офис.

    Порядок строк — порядок вопроса: сперва ОПОРА (покрытие журнала не меняет
    измеряемого) и КОНТРОЛЬ ОСИ ДНЕЙ, без которых «серия» не число, а
    украшение; затем сама серия; затем то, что замер НЕ мерил. Последнее стои́т
    в отчёте намеренно: владелец, увидев только серии, прочёл бы молчание про
    пару как «она не ничья».
    """
    out: List[str] = []
    status = doc.get("status", STATUS_UNMEASURED)
    cov = doc.get("journal_coverage") or {}
    out.append(f"   устойчивость ничьих (заказ CIO #536): {status} · дней "
               f"журнала {doc.get('journal_days', 0)} · пар "
               f"{len(doc.get('pairs') or [])} (из переписи "
               f"{len(doc.get('census_pairs') or [])})")
    ci = doc.get("coverage_independence") or {}
    q = doc.get("quantum_pp")
    out.append(f"   ОПОРА «покрытие журнала не меняет измеряемого»: "
               f"{ci.get('verdict', 'unmeasured')} — {ci.get('note', '')}")
    out.append(f"   квант ранжируемой ставки: "
               f"{'НЕ ИЗМЕРЕН' if q is None else f'{q} pp'} · покрытие журнала "
               f"{cov.get('per_day_min', 0)}–{cov.get('per_day_max', 0)} ставок/день "
               f"против {cov.get('live_ranked', 0)} ранжируемых живым снимком")
    dac = doc.get("day_axis_control") or {}
    out.append(f"   контроль оси дней: {dac.get('verdict', 'unmeasured')} "
               f"(вердикт меняется у {dac.get('pairs_varying', 0)} пар)")
    cls = doc.get("counts_by_class") or {}
    if cls:
        out.append(f"   классы пар: ничья ВСЕГДА {cls.get('always_a_tie', 0)} · "
                   f"иногда {cls.get('sometimes_a_tie', 0)} · никогда "
                   f"{cls.get('never_a_tie', 0)} · НЕ наблюдалась ни разу "
                   f"{cls.get('never_co_observed', 0)} · наблюдалась, но ярлык "
                   f"не применился {cls.get('co_observed_but_unmeasured', 0)}")
    av = doc.get("analytic_vs_measured") or {}
    if av.get("max_understatement_frac") is not None:
        out.append(f"   ярлык взят ИЗМЕРЕНИЕМ, не формулой: аналитический "
                   f"«разрыв/множитель» занижает стоимость перестановки до "
                   f"{av['max_understatement_frac'] * 100:.1f} % "
                   f"({av.get('pairs', 0)} пар) — то есть в сторону «ничьих больше»")
    for line in (doc.get("findings") or [])[:6]:
        out.append(f"   {line}")
    extra = len(doc.get("findings") or []) - 6
    if extra > 0:
        out.append(f"   … и ещё {extra} строк(и) — полный список в артефакте")
    for line in (doc.get("not_measured_by_design") or []):
        out.append(f"   [НЕ МЕРИТСЯ ПО ПОСТРОЕНИЮ] {line}")
    out.append("   ADVISORY: пороги RiskPolicy v1.0, потолки концентрации и форма "
               "целевой функции НЕ трогаются — починка ступеньки money-path и "
               "решение владельца (карточка заведена циклом #535)")
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
        "warn": sum(1 for f in findings if f.startswith("[WARNING]")),
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
        description="устойчивость населения ничьих: сколько дней ПОДРЯД одна и "
                    "та же пара остаётся ничьёй (заказ CIO #536)")
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
