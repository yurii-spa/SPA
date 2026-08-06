"""loop_retro.py — еженедельное ретро петли решений (ADR-066, Фаза 4).

Отвечает на вопрос «говорят ли аналитики дело и работает ли сама петля» —
тем, что ИЗМЕРИМО сегодня, и честным UNCHECKED по тому, что не измеримо:

  ИЗМЕРИМО (из data/investment_os/*_proof.jsonl — hash-chain выработки):
    каденция   доля дней окна, покрытых выработкой аналитика;
    свежесть   возраст последней выработки.
  НЕ ИЗМЕРИМО (и это главная находка): proof-файлы хранят ТОЛЬКО хэши —
    содержимое вердиктов не архивируется, поэтому flip-rate, подтверждение
    RED-сигналов реальностью и реализация возможностей НЕ вычислимы ни за
    какое окно. Пишется в unchecked с именованной причиной, а ретро эмитит
    находку «нужен архив вердиктов» — без него hit-rate вечно UNCHECKED.

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


def analyze_proofs(proof_lines: dict[str, list[dict]], now: dt.datetime) -> list[dict]:
    """proof_lines: analyst → строки proof.jsonl. Каденция и свежесть за окно."""
    out = []
    window_start = now - dt.timedelta(days=WINDOW_DAYS)
    for name, lines in sorted(proof_lines.items()):
        days = set()
        last_ts = None
        for rec in lines:
            ts = _parse_iso(rec.get("generated_at"))
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
                 unresolved_now: int | None, now: dt.datetime) -> dict:
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

    findings.append({
        "key": "retro:verdict_archive_missing", "severity": "WARN",
        "message": "hit-rate аналитиков не вычислим: proof.jsonl хранит только хэши, "
                   "содержимое вердиктов не архивируется — завести append-only архив "
                   "вердиктов (постура/сигналы по дням), иначе «говорит ли офис дело» "
                   "останется вечным UNCHECKED"})

    return {"generated_at": now.isoformat(), "adr": "ADR-066",
            "window_days": WINDOW_DAYS,
            "analysts": analysts,
            "candidates": candidates,
            "findings": findings,
            "unchecked": list(_UNMEASURABLE),
            "loop_health_snapshot": {k: loop_health.get(k) for k in
                                     ("open_cards", "recurrences_total", "cards_fate")}
                                    if loop_health else None,
            "ratchet": {"unresolved_agents_now": unresolved_now,
                        "rule": "может только уменьшаться (test_architecture_ratchet)"}}


def run(root: str = REPO_ROOT, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    proofs: dict[str, list[dict]] = {}
    io_dir = os.path.join(root, "data", "investment_os")
    if os.path.isdir(io_dir):
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
    report = build_report(analyze_proofs(proofs, now), lh, unresolved, now)
    from spa_core.utils.atomic import atomic_save
    atomic_save(report, os.path.join(root, RETRO_REL))
    return report
