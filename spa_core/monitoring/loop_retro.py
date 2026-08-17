"""loop_retro.py — еженедельное ретро петли решений (ADR-066, Фаза 4).

Отвечает на вопрос «говорят ли аналитики дело и работает ли сама петля» —
тем, что ИЗМЕРИМО сегодня, и честным UNCHECKED по тому, что не измеримо:

  ИЗМЕРИМО (из data/investment_os/*_proof.jsonl — hash-chain выработки):
    каденция   доля дней окна, покрытых выработкой аналитика;
    свежесть   возраст последней выработки.
  ИЗМЕРИМО с 2026-08-06 (из data/investment_os/*_verdicts.jsonl, ADR-066):
    flip-rate  как часто аналитик меняет постуру от дня ко дню, и менялось ли
               содержание вердикта вообще (content_sha256 без меток времени).
    Архив завёл `spa_core/investment_os/verdict_archive.py` — до него
    <agent>.json перезаписывался и вчерашнее мнение исчезало навсегда.
  НЕ ИЗМЕРИМО и после архива (называется, а не замалчивается): подтверждение
    RED-сигнала реальностью и реализация возможностей — для них нужен архив
    ИСХОДОВ (реализованный APY/просадка), сопоставленный с постурой по дням;
    архив вердиктов даёт левую половину пары, правой пока нет.

Фейл-CLOSED по самому архиву: нет файлов или ноль строк — находка
`retro:verdict_archive_missing`; архив есть, но отстал от proof-цепочки
(аналитик выработал, вердикт не записан) — находка `retro:verdict_archive_lagging`.
Второе важнее первого: молча сломавшийся архив выглядит как работающий.

Кандидаты (ретайр/калибровка — ТОЛЬКО карточками, решение владельца, R4):
  аналитик с каденцией < MIN_CADENCE за окно или молчащий > STALE_H часов.

Findings ретро уходят В МОСТ (findings_bridge берёт data/loop_retro.json
третьим источником) — рекомендация не имеет права остаться в отчёте,
который никто не обязан открыть. Ратчет unresolved-агентов — отдельный
тест test_architecture_ratchet.py; здесь только сводка.
LLM_FORBIDDEN. Только stdlib. Время — вход (now=).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import os

from spa_core.monitoring.architecture_conformance import REPO_ROOT, _parse_iso

RETRO_REL = os.path.join("data", "loop_retro.json")
WINDOW_DAYS = 14
MIN_CADENCE = 0.5
STALE_H = 78.0  # 3 × SLO 26ч

_UNMEASURABLE = [
    {"metric": "flip-rate вердиктов", "reason": "proof.jsonl хранит только хэши — содержимого вердиктов нет"},
    {"metric": "подтверждение RED реальностью", "reason": "нет архива вердиктов с постурами по дням"},
    {"metric": "реализация возможностей (forward evidenced APY)", "reason": "нет ежедневного архива позиций и вердиктов"},
]

# Что остаётся неизмеримым, КОГДА архив вердиктов уже есть: левая половина пары
# (что офис говорил) записана, правой (что вышло на самом деле) — нет. Причина
# меняется вместе с реальностью, иначе отчёт врал бы о том, чего ему не хватает.
_UNMEASURABLE_WITH_ARCHIVE = [
    {"metric": "подтверждение RED реальностью",
     "reason": "архив постур по дням есть, но исход (реализованный APY / просадка) с постурой не сопоставлен"},
    {"metric": "реализация возможностей (forward evidenced APY)",
     "reason": "архив вердиктов есть, ежедневного архива позиций и реализованной доходности — нет"},
]


def analyze_verdicts(verdict_lines: dict[str, list[dict]] | None,
                     analysts: list[dict]) -> dict | None:
    """Покрытие архива вердиктов и flip-rate. None = архив НЕ измерялся (fail-CLOSED).

    Отставание считается ТОЛЬКО по аналитикам, которые в окне реально выработали:
    у молчащего аналитика пустой архив — не поломка архива, а его собственное
    молчание, и приписывать его архиву значило бы сочинить находку.
    """
    if verdict_lines is None:
        return None
    from spa_core.investment_os.verdict_archive import flip_stats

    # Считаем ВСЕ строки архива, а не только у аналитиков с proof-файлом: иначе
    # архив, переживший свой proof, читался бы как «архива нет».
    total = sum(len(v) for v in verdict_lines.values())
    per, lagging = [], []
    for a in analysts:
        name = a["analyst"]
        if name.startswith("_"):
            # Служебные сводки (_health) пишутся МИМО harness (append_daily_proof)
            # и вердиктов не архивируют ПО ПОСТРОЕНИЮ — ожидать от них архив
            # значит сочинять находку (ложный lagging 2026-08-06, класс
            # «читатель слеп к схеме», как ложный кандидат по каденции).
            continue
        lines = verdict_lines.get(name, [])
        days = sorted({str(r.get("date")) for r in lines if r.get("date")})
        last_archived = days[-1] if days else None
        proof_last = (a["last_generated_at"] or "")[:10] or None
        behind = bool(proof_last) and (last_archived is None or last_archived < proof_last)
        if behind:
            lagging.append(name)
        entry = {"analyst": name, "archived_days": len(days),
                 "last_archived_date": last_archived, "proof_last_date": proof_last,
                 "archive_behind_proof": behind}
        entry.update(flip_stats(lines))
        per.append(entry)
    return {"total_lines": total, "analysts": per, "lagging": sorted(lagging)}


OUTCOME_HORIZON_DAYS = 7
OUTCOME_MIN_PAIRS = 5


def analyze_outcomes(chief_verdicts: list[dict],
                     outcomes: list[dict],
                     horizon_days: int = OUTCOME_HORIZON_DAYS,
                     min_pairs: int = OUTCOME_MIN_PAIRS) -> dict:
    """Левая половина пары (постура офиса по дням) × правая (исходы по дням).

    Подтверждение RED: форвардная доходность за ≤horizon дней ПОСЛЕ RED-дня
    отрицательна. Пар меньше min_pairs ⇒ вердикт UNCHECKED с динамической
    причиной (сколько собрано) — не молчание и не догадка. Дни без исхода
    просто не образуют пару (никакой интерполяции).
    """
    eq_by_date = {str(r.get("date")): r.get("equity_close")
                  for r in outcomes
                  if r.get("date") and isinstance(r.get("equity_close"), (int, float))}
    dates = sorted(eq_by_date)
    pairs, red_pairs, red_confirmed = [], [], []
    for v in chief_verdicts:
        d = str(v.get("date") or "")
        posture = str(v.get("posture") or "").upper()
        if not d or not posture or d not in eq_by_date:
            continue
        fwd = [x for x in dates if d < x][:horizon_days]
        if not fwd:
            continue
        ret_pct = (eq_by_date[fwd[-1]] - eq_by_date[d]) / eq_by_date[d] * 100.0
        pair = {"date": d, "posture": posture,
                "forward_days": len(fwd), "forward_return_pct": round(ret_pct, 4)}
        pairs.append(pair)
        if posture == "RED":
            red_pairs.append(pair)
            if ret_pct < 0.0:
                red_confirmed.append(d)
    scored = len(pairs)
    red_rate = (round(len(red_confirmed) / len(red_pairs), 3) if red_pairs else None)
    return {"outcome_days": len(dates), "pairs_scored": scored,
            "red_pairs": len(red_pairs), "red_confirmed": len(red_confirmed),
            "red_confirmation_rate": red_rate,
            "pairs": pairs[-30:],
            "measured": scored >= min_pairs,
            "note": (f"пар {scored} < {min_pairs} — копится, вердикта нет"
                     if scored < min_pairs else "")}


def analyze_proofs(proof_lines: dict[str, list[dict]], now: dt.datetime) -> list[dict]:
    """proof_lines: analyst → строки proof.jsonl. Каденция и свежесть за окно."""
    out = []
    window_start = now - dt.timedelta(days=WINDOW_DAYS)
    for name, lines in sorted(proof_lines.items()):
        days = set()
        last_ts = None
        for rec in lines:
            # Две живые схемы proof-строк: generated_at (harness аналитиков) и
            # date (append_daily_proof, _health) — ретро обязан читать обе.
            # Слепота к date дала ложного кандидата «_health: каденция 0%»
            # (2026-08-06) — аналитик работал, читатель не умел его видеть.
            ts = _parse_iso(rec.get("generated_at"))
            if ts is None and rec.get("date"):
                ts = _parse_iso(str(rec["date"]) + "T00:00:00+00:00")
            if ts is None:
                continue
            if last_ts is None or ts > last_ts:
                last_ts = ts
            if ts >= window_start:
                days.add(ts.date().isoformat())
        cadence = round(len(days) / WINDOW_DAYS, 3)
        stale_h = (round((now - last_ts).total_seconds() / 3600.0, 1)
                   if last_ts else None)
        out.append({"analyst": name, "days_covered": len(days),
                    "window_days": WINDOW_DAYS, "cadence": cadence,
                    "last_generated_at": last_ts.isoformat() if last_ts else None,
                    "stale_h": stale_h})
    return out


def build_report(analysts: list[dict], loop_health: dict | None,
                 unresolved_now: int | None, now: dt.datetime,
                 verdicts: dict | None = None,
                 outcomes_stats: dict | None = None,
                 outcomes_completeness: dict | None = None) -> dict:
    """`verdicts` — результат analyze_verdicts; None означает «архив не измеряли»
    и трактуется как его отсутствие (fail-CLOSED): молчание не считается за «есть»."""
    candidates, findings = [], []
    for a in analysts:
        problems = []
        if a["cadence"] < MIN_CADENCE:
            problems.append(f"каденция {a['cadence']:.0%} < {MIN_CADENCE:.0%} окна {WINDOW_DAYS}д")
        if a["stale_h"] is None or a["stale_h"] > STALE_H:
            problems.append(f"молчит {a['stale_h']}ч > {STALE_H}ч" if a["stale_h"] is not None
                            else "ни одной датированной выработки")
        if problems:
            candidates.append({"analyst": a["analyst"], "evidence": problems,
                               "recommendation": "разобраться/калибровать или честно ретайр — решение владельца (R4)"})
            findings.append({"key": f"retro:analyst_low_output:{a['analyst']}",
                             "severity": "WARN",
                             "message": f"аналитик {a['analyst']}: {'; '.join(problems)} — "
                                        f"кандидат на калибровку/ретайр (owner-gated)"})

    archive_alive = bool(verdicts and verdicts.get("total_lines"))
    if not archive_alive:
        findings.append({
            "key": "retro:verdict_archive_missing", "severity": "WARN",
            "message": "hit-rate аналитиков не вычислим: proof.jsonl хранит только хэши, "
                       "содержимое вердиктов не архивируется — завести append-only архив "
                       "вердиктов (постура/сигналы по дням), иначе «говорит ли офис дело» "
                       "останется вечным UNCHECKED"})
    elif verdicts.get("lagging"):
        # Архив есть — и именно поэтому его молчание опаснее его отсутствия.
        findings.append({
            "key": "retro:verdict_archive_lagging", "severity": "WARN",
            "message": "архив вердиктов отстаёт от выработки: аналитики "
                       f"{', '.join(verdicts['lagging'])} выработали, а их вердикт за этот день "
                       "не записан — архив выглядит рабочим, но hit-rate считать не по чему"})

    # ПОЛНОТА архива исходов — вопрос, отдельный от его ВОЗРАСТА (B2 сторожа
    # архитектуры). Находка идёт отсюда, потому что здесь у неё уже есть
    # читатель: findings_bridge берёт loop_retro.json третьим источником, то
    # есть рекомендация не остаётся в файле, который никто не обязан открыть.
    if outcomes_completeness is not None:
        if outcomes_completeness.get("measured") and outcomes_completeness.get("missing_days"):
            miss = outcomes_completeness["missing_days"]
            findings.append({
                "key": "retro:outcomes_incomplete", "severity": "WARN",
                "message": f"архив исходов неполон: строки нет за {len(miss)} закрыт(ых) "
                           f"evidenced-дн(я/ей) ({', '.join(miss[:5])}"
                           f"{' …' if len(miss) > 5 else ''}) — это ОСТАНОВКА записи, "
                           "а не ожидание бара; производитель (append_daily_outcome) "
                           "пишет ТОЛЬКО сегодняшний день, поэтому сам он эти дни уже "
                           "не догонит: нужен разбор причины, затем дозапись — "
                           "`python3 -m spa_core.monitoring.outcomes_archive --backfill "
                           "--since <дата> --until <дата>` (руками: автолечение стёрло "
                           "бы эту находку раньше, чем её прочитают)"})

    # Динамическая честность (цикл 3 ADR-067): архив исходов снимает вечный
    # UNCHECKED «подтверждение RED» ровно в тот момент, когда пар достаточно;
    # до того причина называет, СКОЛЬКО уже собрано — прогресс виден, не туман.
    unchecked = list(_UNMEASURABLE_WITH_ARCHIVE if archive_alive else _UNMEASURABLE)
    if outcomes_stats is not None:
        unchecked = [u for u in unchecked
                     if u["metric"] not in ("подтверждение RED реальностью",
                                            "реализация возможностей (forward evidenced APY)")]
        if not outcomes_stats.get("measured"):
            unchecked.append({"metric": "подтверждение RED реальностью",
                              "reason": f"исходов {outcomes_stats['outcome_days']} дн., "
                                        f"пар {outcomes_stats['pairs_scored']}/"
                                        f"{OUTCOME_MIN_PAIRS} — копится (outcomes.jsonl)"})
        unchecked.append({"metric": "реализация возможностей (forward evidenced APY)",
                          "reason": f"позиции и evidenced-APY копятся в outcomes.jsonl "
                                    f"({outcomes_stats['outcome_days']} дн.) — "
                                    f"пропротокольный join будет включён при покрытии "
                                    f"≥{OUTCOME_HORIZON_DAYS} дн."})

    # Неизмеренная полнота — это НЕ «полно»: причина называется вслух, находкой
    # не объявляется (пустой архив в свежем дереве — не поломка производителя).
    if outcomes_completeness is not None and not outcomes_completeness.get("measured"):
        unchecked.append({"metric": "полнота архива исходов по закрытым дням",
                          "reason": str(outcomes_completeness.get("reason")
                                        or "причина не названа производителем")})

    return {"generated_at": now.isoformat(), "adr": "ADR-066",
            "window_days": WINDOW_DAYS,
            "analysts": analysts,
            "candidates": candidates,
            "findings": findings,
            "verdict_archive": verdicts,
            "outcomes": outcomes_stats,
            "outcomes_completeness": outcomes_completeness,
            "unchecked": unchecked,
            "loop_health_snapshot": {k: loop_health.get(k) for k in
                                     ("open_cards", "recurrences_total", "cards_fate")}
                                    if loop_health else None,
            "ratchet": {"unresolved_agents_now": unresolved_now,
                        "rule": "может только уменьшаться (test_architecture_ratchet)"}}


def run(root: str = REPO_ROOT, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    proofs: dict[str, list[dict]] = {}
    verdicts: dict[str, list[dict]] | None = None
    io_dir = os.path.join(root, "data", "investment_os")
    if os.path.isdir(io_dir):
        verdicts = {}
        for fn in sorted(os.listdir(io_dir)):
            if fn.endswith("_proof.jsonl"):
                name = fn[:-len("_proof.jsonl")]
                lines = []
                try:
                    with open(os.path.join(io_dir, fn), encoding="utf-8") as f:
                        for ln in f:
                            try:
                                lines.append(json.loads(ln))
                            except json.JSONDecodeError:
                                continue
                except Exception:
                    continue
                proofs[name] = lines
        from spa_core.investment_os.verdict_archive import ARCHIVE_SUFFIX, read_verdicts
        for fn in sorted(os.listdir(io_dir)):
            if fn.endswith(ARCHIVE_SUFFIX):
                verdicts[fn[:-len(ARCHIVE_SUFFIX)]] = read_verdicts(fn[:-len(ARCHIVE_SUFFIX)], io_dir)
    try:
        lh = json.load(open(os.path.join(root, "data", "loop_health.json")))
    except Exception:
        lh = None
    unresolved = None
    try:
        man = json.load(open(os.path.join(root, "architecture", "manifest.json")))
        unresolved = sum(1 for a in man.get("agents", []) if a.get("intent") == "unresolved")
    except Exception:
        pass
    analysts = analyze_proofs(proofs, now)
    try:
        from spa_core.monitoring.outcomes_archive import load_outcomes
        chief_v = (verdicts or {}).get("chief_investment", [])
        outc = load_outcomes(root)
        outcomes_stats = analyze_outcomes(chief_v, outc) if (outc or chief_v) else None
    except Exception:  # noqa: BLE001 — исходы не смеют валить ретро
        outcomes_stats = None
    try:
        from spa_core.monitoring.outcomes_archive import analyze_completeness
        completeness = analyze_completeness(root, now)
    except Exception as exc:  # noqa: BLE001 — падение проверки не смеет валить ретро
        # …но и исчезнуть в тишине не смеет: упавшая проверка — это «не измерено»
        # С ПРИЧИНОЙ, а не отсутствие вопроса (иначе fail-OPEN внутри fail-CLOSED).
        completeness = {"measured": False,
                        "reason": f"проверка полноты не выполнена: {exc}"}
    report = build_report(analysts, lh, unresolved, now,
                          verdicts=analyze_verdicts(verdicts, analysts),
                          outcomes_stats=outcomes_stats,
                          outcomes_completeness=completeness)
    from spa_core.utils.atomic import atomic_save
    atomic_save(report, os.path.join(root, RETRO_REL))
    return report
