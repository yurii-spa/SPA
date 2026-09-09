"""Меняет ли расширение записи решения САМО РЕШЕНИЕ, а не приборы (заказ #540).

Заказ цикла #540 (ADR-290) поставил вопрос ровно так: запись решения
(``data/allocation_rationale_history.jsonl``) — вход ``shadow_trigger_eval`` и,
после взвода, money-path. **Меняется ли хоть один ВЕРДИКТ тени (``ACT``/``HOLD``)
или хоть один гейт ``TriggerParams``, если запись несёт весь ранжированный набор
вместо книги?**

И назвал ловушку заранее: соблазн взять готовую строку #540
(``shadow_trigger_eval`` → ``insensitive``, покрытие ``2→2`` бит в бит) как
ответ. Это ответ на вопрос «замечает ли потребитель рост НАСЕЛЕНИЯ», а не
«меняет ли он РЕШЕНИЕ». ``2→2`` — **пол, а не потолок**.

Прибор отвечает ЗАМЕРОМ, и вопрос распадается на две поверхности с
ПРОТИВОПОЛОЖНЫМИ ответами. Смешать их — значит верно ответить не на тот вопрос:

1. **Живой путь вердикта** (``allocation_rationale.write_shadow_rationale`` →
   ``decision_shadow.decision`` + ``gates``). Здесь запись — **выход**, а не
   вход: анти-чёрн-история гейтов приходит из ``trades.json``
   (``_history_from_trades``), а не из журнала. Утверждение проверяется
   **МАКСИМАЛЬНЫМ возмущением**: журнал УДАЛЯЕТСЯ целиком, настоящий писатель
   зовётся снова, вердикт и все восемь гейтов сверяются бит в бит. Совпало ⇒
   расширение не может изменить сегодняшний вердикт — это ПОТОЛОК, а не пол.
2. **Путь реплея** (``shadow_trigger_eval.evaluate_window``). Здесь запись —
   настоящий вход: контрфакт дня *d* оценивается по ставкам ПОСЛЕДУЮЩИХ дней, и
   нога, которую день *d* двигал, у дня *f* может отсутствовать. Тогда день *f*
   не оценивается (fail-CLOSED), а при нуле оценённых дней весь вердикт дня *d*
   становится ``UNCHECKED`` и выпадает из знаменателя приёмки взвода.

**Отрицательный результат здесь ничего не стоит без положительного контроля.**
Заказ сказал это прямо: «мерить возмущением, которое СПОСОБНО изменить вердикт;
отрицательный результат закрывает ветку только если положительный был возможен».
Поэтому у КАЖДОЙ из двух поверхностей есть свой обязательный контроль, и оба
обязаны сработать, иначе прибор ОТКАЗЫВАЕТ (``UNMEASURED``), а не докладывает
«ничего не изменилось»:

* поверхность 1 — контроль на ПРОВОДКУ: опустошить ``trades``, из которых гейты
  и берутся. Не поехали гейты ⇒ мерился не тот путь, и молчание журнала ничего
  не доказывает;
* поверхность 2 — контроль на СПОСОБНОСТЬ: одному дню выдаётся ставка, при
  которой его же ход окупается, и он ОБЯЗАН перевернуться ``hit``→``miss``.
  Заодно печатается, какое **преимущество в пп** для этого нужно, — чтобы
  «положительный был возможен» было числом, а не словом.

**ADVISORY.** Прибор ничего не чинит и не предлагает чинить молча: ни писатель,
ни ``TriggerParams``, ни пороги RiskPolicy v1.0, ни потолки концентрации, ни
kill-switch, ни живой трек не трогаются, капитал не двигается. Живое ``data/``
открывается на запись ровно один раз — для собственного артефакта; всё остальное
считается в песочнице.
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
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("spa.monitoring.decision_record_verdict_sensitivity")

VERSION = "decision-record-verdict-sensitivity-v1"
OUTPUT_FILENAME = "decision_record_verdict_sensitivity.json"

HISTORY_FILENAME = "allocation_rationale_history.jsonl"

#: Снимок, который копируется в песочницу. Живое ``data/`` ни писателю, ни
#: реплею не показывается: они читают пути, которые мы передаём.
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

#: Ставка (пп), которой хватает, чтобы ход дня окупился в контроле способности.
#: Число ПРИБОРА: оно ничего не гейтит и в решение не попадает — им только
#: доказывается, что переворот вердикта достижим через настоящий путь замера.
_CONTROL_RATE_PP = 60.0

#: Поля ответа реплея, которые и ЕСТЬ решение. Перечислены ПОИМЁННО, а не
#: срезаны регуляркой: ровно на подмене этого списка первая проба (#540)
#: получила «нечувствителен» — она спрашивала у отчёта ключ ``observed_days``,
#: которого в нём нет (там ``observation_days``), брала имя критерия ключом
#: ``name`` (там ``criterion``) и не смотрела в ``counts`` вовсе.
_DECISION_FIELDS = ("hit_rate", "net_bps_if_followed", "net_usd_if_followed",
                    "hold_missed_usd_total", "ready_to_arm", "observation_days")


# ──────────────────────────────────────────────────────────────────────────
# проекция «что здесь есть решение»
# ──────────────────────────────────────────────────────────────────────────
def decision_slice(doc: dict) -> dict:
    """Решающая часть ответа реплея: без отметок времени, с ИМЕНАМИ критериев.

    Отметки времени исключены ПОИМЁННО (``generated_at``), а не «по датному
    виду»: регулярка по виду глушит и настоящие входы. Всё остальное здесь —
    то, чем принимается решение о взводе, плюс перепись дней, на которой оно
    посчитано.
    """
    crit = [{"criterion": c.get("criterion"), "status": c.get("status"),
             "actual": c.get("actual"), "threshold": c.get("threshold")}
            for c in (doc.get("criteria") or [])]
    per_day = {str(r.get("cycle_date")): {"verdict": r.get("verdict"),
                                          "outcome": r.get("outcome"),
                                          "material": bool(r.get("material"))}
               for r in (doc.get("per_verdict") or []) if r.get("cycle_date")}
    return {
        "counts": dict(doc.get("counts") or {}),
        "criteria": crit,
        "per_day": per_day,
        **{k: doc.get(k) for k in _DECISION_FIELDS},
    }


def _outcome_transitions(base: dict, wide: dict) -> Dict[str, List[str]]:
    """Поимённо: какие дни сменили исход и в какую сторону.

    Три разряда, и путать их нельзя. ``scored`` — день, у которого ВЕРДИКТА НЕ
    БЫЛО и он появился (потолок покрытия платился прямо здесь). ``flipped`` —
    день, у которого вердикт БЫЛ и стал ДРУГИМ; только этот разряд означает,
    что расширение меняет решение. ``lost`` — обратное: день перестал
    оцениваться, чего расширение делать не должно вовсе.
    """
    bd, wd = base.get("per_day") or {}, wide.get("per_day") or {}
    out: Dict[str, List[str]] = {"scored": [], "flipped": [], "lost": []}
    for day in sorted(set(bd) | set(wd)):
        b = (bd.get(day) or {}).get("outcome")
        w = (wd.get(day) or {}).get("outcome")
        if b == w:
            continue
        if b == "UNCHECKED" and w in ("hit", "miss"):
            out["scored"].append(f"{day}: UNCHECKED→{w}")
        elif w == "UNCHECKED" and b in ("hit", "miss"):
            out["lost"].append(f"{day}: {b}→UNCHECKED")
        else:
            out["flipped"].append(f"{day}: {b}→{w}")
    return out


def _criteria_status_changes(base: dict, wide: dict) -> List[str]:
    """Смена СТАТУСА критерия приёмки — единственное, что двигает взвод."""
    bw = {c["criterion"]: c for c in (base.get("criteria") or [])}
    ww = {c["criterion"]: c for c in (wide.get("criteria") or [])}
    out = []
    for name in sorted(set(bw) | set(ww)):
        b, w = bw.get(name) or {}, ww.get(name) or {}
        if b.get("status") != w.get("status"):
            out.append(f"{name}: {b.get('status')}→{w.get('status')} "
                       f"({b.get('actual')}→{w.get('actual')})")
    return out


# ──────────────────────────────────────────────────────────────────────────
# поверхность 1 — живой путь вердикта
# ──────────────────────────────────────────────────────────────────────────
def _writer_verdict(sandbox: Path, journal_rows: Optional[List[dict]],
                    inputs: dict, *, trades: Optional[List[dict]],
                    now: datetime) -> dict:
    """Вердикт НАСТОЯЩЕГО писателя при заданном содержимом журнала.

    ``journal_rows is None`` ⇒ журнал УДАЛЯЕТСЯ. Это и есть максимальное
    возмущение: если вердикт не дрогнул от полного исчезновения записи, то от
    её расширения он тем более не дрогнет — вывод получается потолком, а не
    полом. ``write=False``: на диск писатель не ходит.
    """
    from spa_core.paper_trading.allocation_rationale import write_shadow_rationale

    root = sandbox / "writer"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    for name in _SANDBOX_FILES:
        src = sandbox / name
        if src.exists():
            shutil.copyfile(src, root / name)
    path = root / HISTORY_FILENAME
    if journal_rows is None:
        if path.exists():
            path.unlink()
    else:
        _write_journal(journal_rows, path)

    doc = write_shadow_rationale(
        data_dir=root,
        current_positions=inputs["current_positions"],
        target_positions=inputs["target_positions"],
        apy_pct=inputs["apy_pct"],
        apy_sources=inputs["apy_sources"],
        capital_usd=inputs["capital_usd"],
        cycle_date=inputs["cycle_date"],
        run_ts=now.isoformat(),
        trades=trades,
        now=now,
        write=False,
    )
    dec = doc.get("decision_shadow") or {}
    return {"decision": dec.get("decision"), "gates": dict(dec.get("gates") or {}),
            "reasons": list(dec.get("reasons") or []),
            "cost_usd": dec.get("cost_usd"), "gain_pp": dec.get("gain_pp")}


def live_path_sensitivity(sandbox: Path, rows: List[dict], widened: List[dict],
                          inputs: dict, trades: Optional[List[dict]],
                          now: datetime) -> dict:
    """Вход ли журнал сегодняшнему вердикту и гейтам — замером, не чтением кода.

    Возвращает третий исход с НАЗВАННОЙ причиной, если писатель не отработал:
    «не измерено» здесь обязано быть отличимо от «не изменилось».
    """
    out: dict = {"surface": "allocation_rationale.write_shadow_rationale",
                 "perturbation": "журнал УДАЛЁН целиком (максимальное возмущение)"}
    j = lambda v: json.dumps(v, sort_keys=True, default=str)  # noqa: E731
    try:
        real = _writer_verdict(sandbox, rows, inputs, trades=trades, now=now)
        gone = _writer_verdict(sandbox, None, inputs, trades=trades, now=now)
        wide = _writer_verdict(sandbox, widened, inputs, trades=trades, now=now)
    except Exception as exc:  # noqa: BLE001 — отказ писателя есть ИСХОД
        out.update(verdict="unmeasured",
                   note=f"настоящий писатель не отработал ({type(exc).__name__}: {exc})")
        return out

    # Контроль на ПРОВОДКУ, обязателен. Гейты берут анти-чёрн-историю из
    # `trades`; опустошив их, мы обязаны увидеть, как гейты поехали. Не поехали
    # ⇒ мерился не тот путь, и молчание журнала не доказывает ничего.
    try:
        control = _writer_verdict(sandbox, rows, inputs, trades=[], now=now)
    except Exception as exc:  # noqa: BLE001
        out.update(verdict="unmeasured",
                   note=f"контроль на проводку не отработал ({type(exc).__name__}: {exc})")
        return out
    moved_gates = sorted(k for k in set(real["gates"]) | set(control["gates"])
                         if real["gates"].get(k) != control["gates"].get(k))
    out["control"] = {
        "perturbation": "trades=[] — источник анти-чёрн-истории гейтов опустошён",
        "gates_moved": moved_gates,
        "fired": bool(moved_gates) or real["decision"] != control["decision"],
    }
    if not out["control"]["fired"]:
        out.update(verdict="unmeasured",
                   note=("контроль на проводку НЕ сработал: опустошение `trades` не "
                         "сдвинуло ни одного гейта — путь замера не доказан живым, "
                         "и совпадение вердиктов ниже ничего не значит"))
        return out

    out["verdict_real"] = real["decision"]
    out["gates_real"] = real["gates"]
    out["same_when_journal_deleted"] = j(real) == j(gone)
    out["same_when_journal_widened"] = j(real) == j(wide)
    if out["same_when_journal_deleted"] and out["same_when_journal_widened"]:
        out["verdict"] = "journal_is_an_output_here"
    else:
        out["verdict"] = "journal_binds_here"
        out["changed_fields"] = sorted(
            k for k in set(real) | set(gone) if j(real.get(k)) != j(gone.get(k)))
    return out


# ──────────────────────────────────────────────────────────────────────────
# поверхность 2 — путь реплея
# ──────────────────────────────────────────────────────────────────────────
def _write_journal(rows: List[dict], path: Path) -> None:
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True, default=str) for r in rows) + "\n",
        encoding="utf-8")


def _replay(sandbox: Path, rows: List[dict], tag: str) -> dict:
    """Настоящий ``evaluate_window`` над заданным журналом. Второй копии правил нет."""
    from spa_core.paper_trading.shadow_trigger_eval import evaluate_window

    root = sandbox / tag
    root.mkdir(parents=True, exist_ok=True)
    for name in _SANDBOX_FILES:
        src = sandbox / name
        if src.exists():
            shutil.copyfile(src, root / name)
    _write_journal(rows, root / HISTORY_FILENAME)
    return evaluate_window(root, write=False)


def _record_deltas(rec: dict) -> Dict[str, float]:
    """Ноги записи — тем же правилом, что у реплея (порог 0.005 его же)."""
    cur = rec.get("current_positions") or {}
    tgt = rec.get("target_positions") or {}
    out: Dict[str, float] = {}
    for p in set(cur) | set(tgt):
        d = float(tgt.get(p, 0.0) or 0.0) - float(cur.get(p, 0.0) or 0.0)
        if abs(d) > 0.005:
            out[p] = d
    return out


def capability_control(sandbox: Path, rows: List[dict], base: dict,
                       horizon_days: int = 7) -> dict:
    """Положительный контроль поверхности 2: переворот вердикта ДОСТИЖИМ.

    Берётся оценённый существенный день с наименьшим запасом и его же ногам на
    ПОСЛЕДУЮЩИХ днях выдаётся ставка, при которой ход окупается. День обязан
    стать ``miss``. Не стал ⇒ путь «журнал → вердикт» не доказан живым, и
    отрицательный ответ выше не имеет силы.

    Рядом печатается ПРЕИМУЩЕСТВО В ПП, которого для переворота хватило бы:
    ``cost · 365 · 100 / (Σ_{Δ>0} Δ · дней_вперёд)``. Оно превращает «положительный
    был возможен» из слова в число, сравнимое с разбросом ставок набора.
    """
    out: dict = {"purpose": ("доказать, что переворот вердикта достижим через "
                             "НАСТОЯЩИЙ путь замера — иначе отрицательный "
                             "результат вакуумен")}
    scored = [r for r in (base.get("per_verdict") or [])
              if r.get("material") and r.get("outcome") in ("hit", "miss")
              and r.get("net_usd") is not None]
    if not scored:
        out.update(fired=False, note=("оценённых существенных дней нет — контроль "
                                      "ставить не на чем"))
        return out
    day = min(scored, key=lambda r: abs(float(r.get("net_usd") or 0.0)))
    date = str(day.get("cycle_date"))
    idx = {str(r.get("cycle_date")): i for i, r in enumerate(rows)}
    if date not in idx:
        out.update(fired=False, note=f"день {date} не найден в журнале — контроль не поставлен")
        return out

    i = idx[date]
    deltas = _record_deltas(rows[i])
    forward = list(range(i + 1, min(i + 1 + horizon_days, len(rows))))
    if not deltas or not forward:
        out.update(fired=False, note=(f"у дня {date} нет ног или нет последующих дней "
                                      "— контроль не поставлен"))
        return out

    perturbed = json.loads(json.dumps(rows, default=str))
    for j in forward:
        m = dict(perturbed[j].get("apy_evidenced_pct") or {})
        for p, d in deltas.items():
            m[p] = _CONTROL_RATE_PP if d > 0 else 0.0
        perturbed[j]["apy_evidenced_pct"] = m
    doc = _replay(sandbox, perturbed, "control")
    row = next((r for r in (doc.get("per_verdict") or [])
                if str(r.get("cycle_date")) == date), None)

    bought = sum(d for d in deltas.values() if d > 0)
    cost = float(day.get("cost_usd_used") or 0.0)
    advantage_pp = (cost * 365.0 * 100.0 / (bought * len(forward))
                    if bought > 0 and forward else None)
    out.update({
        "day": date,
        "outcome_before": day.get("outcome"),
        "outcome_after": (row or {}).get("outcome"),
        "net_before": day.get("net_usd"),
        "net_after": (row or {}).get("net_usd"),
        "hit_rate_before": base.get("hit_rate"),
        "hit_rate_after": doc.get("hit_rate"),
        "control_rate_pp": _CONTROL_RATE_PP,
        "advantage_pp_to_flip": (round(advantage_pp, 4)
                                 if advantage_pp is not None else None),
        "bought_usd": round(bought, 2),
        "forward_days": len(forward),
        "fired": bool(row and row.get("outcome") == "miss"
                      and day.get("outcome") == "hit"),
    })
    if not out["fired"]:
        out["note"] = ("контроль НЕ перевернул вердикт — путь «журнал → вердикт» "
                       "не доказан живым; всё отрицательное выше вакуумно")
    return out


def rate_spread(rows: List[dict]) -> dict:
    """Разброс ставок, который журнал ВООБЩЕ наблюдал.

    Нужен ровно затем, чтобы «преимущество, которого хватило бы» можно было
    сравнить с наблюдаемым, а не с воображаемым: контроль обязан быть не только
    сработавшим, но и соизмеримым с миром.
    """
    lo = hi = None
    for r in rows:
        for v in (r.get("apy_evidenced_pct") or {}).values():
            try:
                x = float(v)
            except (TypeError, ValueError):
                continue
            lo = x if lo is None else min(lo, x)
            hi = x if hi is None else max(hi, x)
    return {"min_pp": lo, "max_pp": hi,
            "spread_pp": (round(hi - lo, 4) if lo is not None and hi is not None
                          else None)}


# ──────────────────────────────────────────────────────────────────────────
# поверхность 3 — перепроверка чужого утверждения (#540)
# ──────────────────────────────────────────────────────────────────────────
def prior_claim_recheck(sandbox: Path, rows: List[dict], widened: List[dict],
                        base_slice: dict, wide_slice: dict) -> dict:
    """Что именно спрашивала проба #540 у ЭТОГО потребителя — её же кодом.

    Проба зовётся ДОСЛОВНО (``decision_journal_coverage._reader_probe``), а не
    пересказывается: утверждение «прибор ответил не на тот вопрос» обязано
    держаться на её собственном выводе, а не на нашем чтении её исходника.
    Расхождение с замером выше и есть предмет.
    """
    out: dict = {"claim": ("#540 (ADR-290): shadow_trigger_eval → `insensitive`, "
                           "покрытие 2→2 — «населению карты не подчинён»")}
    try:
        from spa_core.monitoring.decision_journal_coverage import _reader_probe

        spec = {"module": "spa_core.paper_trading.shadow_trigger_eval",
                "probe": "evaluate_window"}
        for tag, data in (("base", rows), ("wide", widened)):
            root = sandbox / f"prior_{tag}"
            (root / "data").mkdir(parents=True, exist_ok=True)
            for name in _SANDBOX_FILES:
                src = sandbox / name
                if src.exists():
                    shutil.copyfile(src, root / "data" / name)
            _write_journal(data, root / "data" / HISTORY_FILENAME)
        b_cov, b_raw = _reader_probe(spec, sandbox / "prior_base")
        w_cov, w_raw = _reader_probe(spec, sandbox / "prior_wide")
        b_snap: dict = b_raw if isinstance(b_raw, dict) else {"snapshot": b_raw}
        w_snap: dict = w_raw if isinstance(w_raw, dict) else {"snapshot": w_raw}
    except Exception as exc:  # noqa: BLE001
        out.update(verdict="unmeasured",
                   note=f"проба #540 не воспроизведена ({type(exc).__name__}: {exc})")
        return out

    same = json.dumps(b_snap, sort_keys=True, default=str) == \
        json.dumps(w_snap, sort_keys=True, default=str)
    out["prior_probe"] = {"coverage_base": b_cov, "coverage_wide": w_cov,
                          "snapshot_identical": same,
                          "verdict_it_would_give": "insensitive" if same else "moved"}
    b_counts = base_slice.get("counts") or {}
    w_counts = wide_slice.get("counts") or {}
    out["measured_here"] = {
        "scored": [b_counts.get("scored"), w_counts.get("scored")],
        "unchecked": [b_counts.get("unchecked"), w_counts.get("unchecked")],
    }
    # ПОЧЕМУ проба промолчала — тремя проверяемыми фактами о ней самой, а не
    # общими словами. Каждый меряется прямо здесь, на её же выводе.
    reasons = []
    snap_criteria = (b_snap or {}).get("criteria") or []
    if snap_criteria and all((c or [None])[0] is None for c in snap_criteria):
        reasons.append("имена критериев в её слепке пусты: ключ отчёта — "
                       "`criterion`, а проба берёт `name`")
    if "observed_days" in (b_snap or {}) and b_snap.get("observed_days") is None:
        reasons.append("`observed_days` в её слепке всегда None: в отчёте поле "
                       "называется `observation_days`")
    if "counts" not in (b_snap or {}):
        reasons.append("`counts` в слепок не входит вовсе — а поехало именно оно")
    if b_cov == w_cov and b_counts.get("scored") != w_counts.get("scored"):
        reasons.append(f"её счётчик покрытия — это ЧИСЛО ПРОВЕРЕННЫХ КРИТЕРИЕВ "
                       f"(их всего три), а не дней: {b_cov}→{w_cov} при "
                       f"{b_counts.get('scored')}→{w_counts.get('scored')} "
                       f"оценённых днях")
    out["reasons_it_stayed_silent"] = reasons
    out["verdict"] = ("prior_claim_refuted"
                      if same and b_counts.get("scored") != w_counts.get("scored")
                      else "prior_claim_stands" if same else "prior_claim_not_reproduced")
    return out


# ──────────────────────────────────────────────────────────────────────────
# сборка
# ──────────────────────────────────────────────────────────────────────────
def _writer_inputs(rows: List[dict]) -> Tuple[Optional[dict], str]:
    """Входы последнего решения — из САМОЙ записи, а не собранные заново.

    Пересобирать их значило бы измерить свою реконструкцию вместо того решения,
    которое система приняла.
    """
    if not rows:
        return None, "журнал пуст"
    last = rows[-1]
    cur = {str(k): float(v) for k, v in (last.get("current_positions") or {}).items()}
    tgt = {str(k): float(v) for k, v in (last.get("target_positions") or {}).items()}
    rates = {str(k): float(v) for k, v in (last.get("apy_evidenced_pct") or {}).items()}
    if not (cur or tgt) or not rates:
        return None, "в последней записи нет книги или нет ни одной ставки"
    return {
        "current_positions": cur,
        "target_positions": tgt,
        "apy_pct": rates,
        "apy_sources": {k: "live" for k in rates},
        "capital_usd": float(last.get("capital_usd") or 0.0),
        "cycle_date": str(last.get("cycle_date") or ""),
    }, ""


def _load_trades(data_dir: Path) -> Optional[List[dict]]:
    try:
        doc = json.loads((Path(data_dir) / "trades.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — отсутствие сделок не фатально
        log.warning("trades.json unreadable (%s)", exc)
        return None
    rows = doc.get("trades") if isinstance(doc, dict) else doc
    return rows if isinstance(rows, list) else None


def measure(data_dir: Path, *, now: Optional[datetime] = None,
            horizon_days: int = 7) -> dict:
    """Полный замер. Детерминирован при заданном ``now`` и файлах на диске."""
    from spa_core.monitoring.decision_journal_coverage import (
        _default_ranked_producer, read_journal, widen_journal,
    )

    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    doc: dict = {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "order": ("заказ #540 (ADR-290): меняет ли расширение записи решения САМО "
                  "решение — вердикт тени ACT/HOLD или гейт TriggerParams"),
        "trap_respected": ("строка #540 «shadow_trigger_eval нечувствителен, 2→2» "
                           "НЕ взята за ответ: она перепроверена её же кодом и "
                           "сопоставлена с замером ниже"),
        "findings": [],
        "advisory": ("писатель, TriggerParams, пороги RiskPolicy v1.0, потолки "
                     "концентрации, kill-switch и живой трек не тронуты, "
                     "капитал не сдвинут"),
    }

    rows, jerr = read_journal(data_dir)
    doc["journal_rows"] = len(rows)
    if jerr or not rows:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] журнал решений нечитаем или пуст "
            f"({jerr or 'ни одной записи'}) — мерить нечего")
        doc["status"] = STATUS_UNMEASURED
        return doc

    sandbox = Path(tempfile.mkdtemp(prefix="spa_drvs_"))
    try:
        for name in _SANDBOX_FILES:
            src = data_dir / name
            if src.exists():
                shutil.copyfile(src, sandbox / name)

        try:
            ranked, sources = _default_ranked_producer(sandbox)()
        except Exception as exc:  # noqa: BLE001
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] производитель ранжируемого набора не отработал "
                f"({type(exc).__name__}: {exc}) — расширять запись не по чему")
            doc["status"] = STATUS_UNMEASURED
            return doc
        ranked_live = {p for p, s in (sources or {}).items() if s == "live"}
        doc["ranked_live"] = len(ranked_live)
        if not ranked_live:
            doc["findings"].append(
                "[НЕ ИЗМЕРЕНО] живых ранжируемых ставок ноль — расширение записи "
                "не отличалось бы от неё самой; это находка о ПРОИЗВОДИТЕЛЕ")
            doc["status"] = STATUS_UNMEASURED
            return doc

        # Расширение берётся ТО ЖЕ, что определил #540: своё определение
        # ответило бы на свой вопрос, а спрошено про заказанное.
        widened = widen_journal(rows, ranked, ranked_live)

        # ── поверхность 2: реплей ──────────────────────────────────────────
        try:
            base_doc = _replay(sandbox, rows, "base")
            wide_doc = _replay(sandbox, widened, "wide")
        except Exception as exc:  # noqa: BLE001
            doc["findings"].append(
                f"[НЕ ИЗМЕРЕНО] реплей не отработал ({type(exc).__name__}: {exc})")
            doc["status"] = STATUS_UNMEASURED
            return doc
        base_slice, wide_slice = decision_slice(base_doc), decision_slice(wide_doc)
        doc["replay"] = {
            "surface": "shadow_trigger_eval.evaluate_window",
            "base": base_slice, "wide": wide_slice,
            "transitions": _outcome_transitions(base_slice, wide_slice),
            "criteria_status_changes": _criteria_status_changes(base_slice, wide_slice),
            "ready_to_arm": [base_slice.get("ready_to_arm"),
                             wide_slice.get("ready_to_arm")],
        }

        # ── контроль способности (обязателен) ──────────────────────────────
        doc["capability"] = capability_control(sandbox, rows, base_doc,
                                               horizon_days=horizon_days)
        doc["rate_spread_observed"] = rate_spread(rows)

        # ── поверхность 1: живой путь вердикта ─────────────────────────────
        inputs, ierr = _writer_inputs(rows)
        if inputs is None:
            doc["live_path"] = {"verdict": "unmeasured", "note": ierr}
        else:
            doc["live_path"] = live_path_sensitivity(
                sandbox, rows, widened, inputs, _load_trades(sandbox), now)

        # ── перепроверка утверждения #540 ──────────────────────────────────
        doc["prior_claim"] = prior_claim_recheck(sandbox, rows, widened,
                                                 base_slice, wide_slice)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    _judge(doc)
    return doc


def _judge(doc: dict) -> None:
    """Вердикт по замерам выше. Второго набора правил здесь нет."""
    cap = doc.get("capability") or {}
    live = doc.get("live_path") or {}
    rep = doc.get("replay") or {}
    prior = doc.get("prior_claim") or {}
    tr = rep.get("transitions") or {}

    # Отрицательный результат без сработавшего контроля — не результат.
    if not cap.get("fired"):
        doc["findings"].append(
            "[НЕ ИЗМЕРЕНО] положительный контроль НЕ сработал: переворот вердикта "
            "через настоящий путь замера не показан, поэтому «ничего не "
            f"изменилось» ниже вакуумно ({cap.get('note') or 'причина не названа'})")
        doc["status"] = STATUS_UNMEASURED
        return
    spread = (doc.get("rate_spread_observed") or {}).get("spread_pp")
    adv = cap.get("advantage_pp_to_flip")
    doc["findings"].append(
        f"[КОНТРОЛЬ] переворот вердикта ДОСТИЖИМ: день {cap.get('day')} "
        f"{cap.get('outcome_before')}→{cap.get('outcome_after')}, hit_rate "
        f"{cap.get('hit_rate_before')}→{cap.get('hit_rate_after')}. Хватило бы "
        f"преимущества {adv} пп на ноге покупки, удержанного {cap.get('forward_days')} "
        f"дн."
        + (f" — при разбросе ставок, который журнал НАБЛЮДАЛ, {spread} пп"
           if spread is not None else "")
        + ". Положительный результат был возможен, поэтому отрицательный ниже "
          "что-то значит")

    if live.get("verdict") == "journal_is_an_output_here":
        doc["findings"].append(
            "[ОТВЕТ ЗАКАЗУ, половина 1] на ЖИВОМ пути вердикта запись решения — "
            "ВЫХОД, а не вход: журнал удалён ЦЕЛИКОМ, и вердикт "
            f"({live.get('verdict_real')}), все "
            f"{len(live.get('gates_real') or {})} гейт(а/ов) TriggerParams, "
            "стоимость и выигрыш совпали бит в бит. Расширение записи не может "
            "изменить сегодняшний ACT/HOLD ни при каком содержимом — это ПОТОЛОК, "
            "а не пол. Контроль на проводку сработал: опустошение `trades` "
            f"сдвинуло гейты {', '.join((live.get('control') or {}).get('gates_moved') or [])}")
    elif live.get("verdict") == "journal_binds_here":
        doc["findings"].append(
            "[CRITICAL] на ЖИВОМ пути вердикта журнал СВЯЗЫВАЕТ: удаление записи "
            f"изменило {', '.join(live.get('changed_fields') or [])} — расширение "
            "записи двигает путь капитала, и делать это молча нельзя")
    else:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] живой путь вердикта не измерен: {live.get('note')}")

    flipped = tr.get("flipped") or []
    scored = tr.get("scored") or []
    lost = tr.get("lost") or []
    crit_changes = rep.get("criteria_status_changes") or []
    if flipped or crit_changes or lost:
        doc["findings"].append(
            "[CRITICAL] на пути РЕПЛЕЯ расширение меняет решение: "
            + "; ".join(flipped + crit_changes + lost)
            + ". Это money-path после взвода — решение владельца")
    else:
        doc["findings"].append(
            "[ОТВЕТ ЗАКАЗУ, половина 2] на пути РЕПЛЕЯ ни один вердикт не "
            "перевернулся (`hit`↔`miss`), ни один критерий приёмки не сменил "
            "СТАТУС, `ready_to_arm` не изменился — при том что контроль выше "
            "показал: переворот достижим")
    if scored:
        b = (rep.get("base") or {}).get("counts") or {}
        w = (rep.get("wide") or {}).get("counts") or {}
        doc["findings"].append(
            f"[ЦЕНА ПОТОЛКА] но НАСЕЛЕНИЕ, на котором решение посчитано, растёт: "
            f"оценённых дней {b.get('scored')}→{w.get('scored')}, без вердикта "
            f"{b.get('unchecked')}→{w.get('unchecked')}. Дни, получившие вердикт: "
            + "; ".join(scored)
            + ". Сегодняшний hit_rate посчитан на том подмножестве дней, которое "
              "потолок дал оценить, — «не измерено» это, а не «HOLD был прав»")

    if prior.get("verdict") == "prior_claim_refuted":
        m = prior.get("measured_here") or {}
        doc["findings"].append(
            "[CRITICAL] утверждение #540 об ЭТОМ потребителе не подтвердилось: "
            f"его проба и сейчас даёт `insensitive` (покрытие "
            f"{(prior.get('prior_probe') or {}).get('coverage_base')}→"
            f"{(prior.get('prior_probe') or {}).get('coverage_wide')}), тогда как "
            f"оценённых дней {(m.get('scored') or [None, None])[0]}→"
            f"{(m.get('scored') or [None, None])[1]}. Причины измерены: "
            + "; ".join(prior.get("reasons_it_stayed_silent") or ["не названы"])
            + ". Правило #540 «направление мерить СОБСТВЕННЫМ счётчиком "
              "покрытия потребителя» верно — но у единственного потребителя, "
              "который и есть поверхность решения, счётчик взят не тот")
    elif prior.get("verdict") == "unmeasured":
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] проба #540 не воспроизведена: {prior.get('note')}")

    has_critical = any(f.startswith("[CRITICAL]") for f in doc["findings"])
    doc["status"] = STATUS_CRITICAL if has_critical else (
        STATUS_WARNING if scored else STATUS_OK)


def format_report(doc: dict) -> List[str]:
    out = [f"чувствительность РЕШЕНИЯ к населению записи (заказ #540): "
           f"{doc.get('status')} · дней журнала {doc.get('journal_rows')}"]
    live = doc.get("live_path") or {}
    if live:
        out.append(f"   живой путь вердикта: {live.get('verdict')}"
                   + (f" (вердикт {live.get('verdict_real')}, журнал удалён — "
                      f"совпало: {live.get('same_when_journal_deleted')})"
                      if live.get("verdict_real") else ""))
    rep = doc.get("replay") or {}
    if rep:
        b = (rep.get("base") or {}).get("counts") or {}
        w = (rep.get("wide") or {}).get("counts") or {}
        tr = rep.get("transitions") or {}
        out.append(f"   реплей: оценено {b.get('scored')}→{w.get('scored')} · "
                   f"без вердикта {b.get('unchecked')}→{w.get('unchecked')} · "
                   f"перевернулось {len(tr.get('flipped') or [])} · "
                   f"ready_to_arm {rep.get('ready_to_arm')}")
    cap = doc.get("capability") or {}
    if cap:
        out.append(f"   контроль способности: сработал={cap.get('fired')} "
                   f"(день {cap.get('day')} {cap.get('outcome_before')}→"
                   f"{cap.get('outcome_after')}, нужно {cap.get('advantage_pp_to_flip')} пп)")
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
        "warn": sum(1 for f in findings if f.startswith("[ЦЕНА")),
        "info": sum(1 for f in findings if f.startswith("[ОТВЕТ")
                    or f.startswith("[КОНТРОЛЬ]")),
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
        description="меняет ли расширение записи решения САМО решение (заказ #540)")
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
