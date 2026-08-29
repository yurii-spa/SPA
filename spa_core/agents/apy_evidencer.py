"""APY Evidencer: у каждого записанного числа доходности — уровень доказательности.

# LLM_FORBIDDEN

Задача AI1-2.2. **ADR-YL-006** (принят 02.07): «No APY may be stated, displayed, or
recorded without an explicit evidence level (L0–L6) and a yield-source explanation».

Правило есть, исполнителя не было. Замер 2026-08-29: четыре живых артефакта
записывают APY (`apy_ranking.json`, `current_positions.json`, `analytics_report.json`,
`tier_curator_report.json`) — и **ни один не несёт уровня**.

Уровни НЕ определяются здесь: канон — `docs/37_apy_realism_and_evidence_standard.md`,
правило перевода провенанса в уровень — `docs/apy_evidence_enforcement.md` §2.
Этот модуль их только ПРИМЕНЯЕТ:

* **L2** — наблюдено нашим кодом, свежо (≤ 36 ч) и в полосе санитарности.
  Это потолок: провенанс выше L2 не поднимает НИКОГДА. L3 требует нашего
  paper-трека, L4+ — реального исполнения капиталом, которого не было ни разу.
* **L1** — наблюдение есть, но старше окна: исторически наблюдённое число.
* **L0** — не наблюдено (литерал `fallback`, провенанс `unchecked`, пустой источник).
  По канону на этом уровне APY «may not be quoted, even a range».
* **UNCHECKED** — судить нечем (строка без обязательных полей). Это НЕ уровень
  и никогда не схлопывается в L0: «не измерено» ≠ «не наблюдено».

Read-only: читает ранжирование, пишет только свой артефакт. Капитал не двигает,
ничего не гейтит. stdlib · детерминирован · часы и пути инъектируются.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from spa_core.utils.atomic import atomic_save

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
PRODUCES = (
    "data/apy_evidence.json",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RANKING_PATH = _REPO_ROOT / "data" / "apy_ranking.json"
_DEFAULT_OUT = _REPO_ROOT / "data" / "apy_evidence.json"

L0, L1, L2 = "L0", "L1", "L2"
UNCHECKED = "UNCHECKED"

#: Окно свежести наблюдения — ADR-060 §3 (paper), зеркалит allocator._EVIDENCE_MAX_AGE_H.
EVIDENCE_MAX_AGE_H = 36.0
#: Полоса санитарности живого APY в процентах — зеркалит allocator._LIVE_APY_*_DECIMAL.
APY_SANE_MIN_PCT = 0.0    # строго больше
APY_SANE_MAX_PCT = 200.0

#: Значения `apy_source`, означающие НАБЛЮДЕНИЕ. Всё остальное — не наблюдение,
#: включая незнакомое: новый источник не получает доверия по умолчанию.
_OBSERVED_SOURCES = frozenset({"live"})


@dataclass(frozen=True)
class Evidence:
    protocol: str
    level: str
    apy_pct: Optional[float]
    apy_source: Optional[str]
    as_of: Optional[str]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceReport:
    generated_at: str
    ranking_as_of: Optional[str] = None
    items: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    quotable_pct: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["items"] = [i.to_dict() if isinstance(i, Evidence) else i for i in self.items]
        return d


def _finite(v: object) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _parse_ts(v: object) -> Optional[datetime]:
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        ts = datetime.fromisoformat(v.strip())
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def level_for(row: dict, now: datetime, max_age_h: float = EVIDENCE_MAX_AGE_H) -> tuple[str, str]:
    """Уровень и ПРИЧИНА для одной строки ранжирования. Никогда не бросает."""
    if not isinstance(row, dict):
        return UNCHECKED, "строка не объект"
    proto = row.get("protocol")
    if not isinstance(proto, str) or not proto.strip():
        return UNCHECKED, "нет имени протокола — судить не о чем"

    src = row.get("apy_source")
    apy = _finite(row.get("apy_pct"))
    if apy is None:
        return UNCHECKED, f"apy_pct не число: {row.get('apy_pct')!r}"

    if not isinstance(src, str) or not src.strip():
        return UNCHECKED, "провенанс APY не объявлен — молчание не значит наблюдение"

    if src.strip().lower() not in _OBSERVED_SOURCES:
        return L0, (f"не наблюдено (apy_source={src!r}) — число не может быть "
                    f"процитировано даже как диапазон (docs/37, L0)")

    ts = _parse_ts(row.get("last_updated"))
    if ts is None:
        return UNCHECKED, "наблюдение без разбираемой отметки времени — возраст неизвестен"

    age_h = (now - ts).total_seconds() / 3600.0
    if age_h < 0:
        return UNCHECKED, f"отметка из будущего ({row.get('last_updated')!r})"
    if age_h > max_age_h:
        return L1, (f"наблюдение старше окна ({age_h:.1f} ч > {max_age_h:.0f} ч) — "
                    f"исторически наблюдённое, не текущее")

    if not (APY_SANE_MIN_PCT < apy <= APY_SANE_MAX_PCT):
        return UNCHECKED, (f"наблюдение вне полосы санитарности "
                           f"({APY_SANE_MIN_PCT}%, {APY_SANE_MAX_PCT}%]: {apy}")

    return L2, (f"наблюдено нашим кодом, возраст {age_h:.1f} ч ≤ {max_age_h:.0f} ч, "
                f"в полосе санитарности")


class ApyEvidencer:
    def __init__(self, ranking_path: os.PathLike | str | None = None) -> None:
        self.ranking_path = Path(ranking_path) if ranking_path else _RANKING_PATH

    def _rows(self) -> tuple[list, Optional[str], Optional[str]]:
        try:
            doc = json.loads(self.ranking_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return [], None, f"файла нет: {self.ranking_path}"
        except Exception as exc:  # noqa: BLE001
            return [], None, f"нечитаемый {self.ranking_path}: {exc}"
        if not isinstance(doc, dict):
            return [], None, f"{self.ranking_path}: JSON не объект"
        rows = doc.get("by_apy")
        if not isinstance(rows, list):
            return [], None, f"{self.ranking_path}: нет списка by_apy"
        as_of = doc.get("generated_at") if isinstance(doc.get("generated_at"), str) else None
        return rows, as_of, None

    def run(self, now: Optional[datetime] = None) -> EvidenceReport:
        now = now or datetime.now(timezone.utc)
        rep = EvidenceReport(generated_at=now.isoformat())
        rows, as_of, err = self._rows()
        rep.ranking_as_of = as_of
        if err:
            rep.items.append(Evidence("<ранжирование>", UNCHECKED, None, None, None, err))
            rep.counts = {UNCHECKED: 1, L0: 0, L1: 0, L2: 0}
            return rep

        for row in rows:
            lvl, why = level_for(row if isinstance(row, dict) else {}, now)
            r = row if isinstance(row, dict) else {}
            rep.items.append(Evidence(
                protocol=str(r.get("protocol") or "<без имени>"),
                level=lvl,
                apy_pct=_finite(r.get("apy_pct")),
                apy_source=r.get("apy_source") if isinstance(r.get("apy_source"), str) else None,
                as_of=r.get("last_updated") if isinstance(r.get("last_updated"), str) else None,
                reason=why,
            ))

        counts = {L0: 0, L1: 0, L2: 0, UNCHECKED: 0}
        for it in rep.items:
            counts[it.level] = counts.get(it.level, 0) + 1
        rep.counts = counts
        total = len(rep.items)
        # Доля чисел, которые ВООБЩЕ можно показывать: по ADR-YL-006 ниже L2
        # число не идёт ни на публичную, ни на инвесторскую поверхность.
        rep.quotable_pct = round(100.0 * counts[L2] / total, 2) if total else None
        return rep

    @staticmethod
    def save(rep: EvidenceReport, out_path: os.PathLike | str | None = None) -> Path:
        p = Path(out_path) if out_path else _DEFAULT_OUT
        atomic_save(rep.to_dict(), str(p))
        return p


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="APY Evidencer — уровень доказательности каждому APY")
    ap.add_argument("--ranking", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    ev = ApyEvidencer(ranking_path=a.ranking)
    rep = ev.run()
    if not a.no_write:
        ev.save(rep, a.out)

    if a.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    else:
        c = rep.counts
        print(f"APY Evidencer: L2={c.get(L2,0)} · L1={c.get(L1,0)} · L0={c.get(L0,0)} · "
              f"не измерено={c.get(UNCHECKED,0)} (ранжирование от {rep.ranking_as_of})")
        if rep.quotable_pct is not None:
            print(f"  показывать можно {rep.quotable_pct}% чисел — остальные ниже L2 (ADR-YL-006)")
        for it in rep.items:
            if it.level != L2:
                print(f"  [{it.level}] {it.protocol}: apy={it.apy_pct} — {it.reason}")
    # 0 — всё наблюдаемо; 1 — есть непроцитируемые; 2 — есть неизмеримые
    if rep.counts.get(UNCHECKED, 0):
        return 2
    return 1 if rep.counts.get(L0, 0) or rep.counts.get(L1, 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
