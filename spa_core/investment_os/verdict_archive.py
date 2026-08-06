"""verdict_archive.py — append-only архив вердиктов аналитиков (ADR-066, находка ретро).

**Что было сломано.** `<agent>_proof.jsonl` хранит ТОЛЬКО хэш факта выработки
(`{agent, date, generated_at, hash, prev_hash}`), а `<agent>.json` каждый прогон
ПЕРЕЗАПИСЫВАЕТСЯ. То есть по проду видно, что аналитик вчера что-то сказал, но
навсегда потеряно, ЧТО именно он сказал. Поэтому вопрос «говорит ли офис дело»
(flip-rate постур, подтверждение RED, реализация возможностей) был не «плохим»,
а НЕИЗМЕРИМЫМ — `loop_retro` честно писал его в `unchecked` и эмитил находку
`retro:verdict_archive_missing` (2026-08-05, подтверждена двумя прогонами).

**Что делает этот модуль.** Кладёт рядом с proof-цепочкой второй файл —
`data/investment_os/<agent>_verdicts.jsonl` — одна hash-chained строка на
(аналитик, UTC-день): сжатый СНИМОК вердикта, а не весь payload.

  posture           постура/вердикт (`combined_posture`, `overall`, `posture`,
                    `house_view.posture`, `status` — первое найденное);
  fields            плоские скаляры глубины ≤2 (`house_view.posture`, `coverage.n`…);
  sizes             длины коллекций (`top_stablecoin_yields`: 5 — «сколько сигналов»);
  names             до 5 идентификаторов элементов списка (какие именно возможности);
  content_sha256    хэш КАНОНИЧЕСКОГО payload БЕЗ временных меток.

Последнее — то, ради чего всё: одинаковый по существу вердикт в разные дни даёт
ОДИНАКОВЫЙ хэш, значит «флип» отличим от «просто пересчитали в новую секунду».
Если бы в хэш попал `generated_at`, флипало бы каждый день и метрика была бы
ложью, выглядящей как измерение.

**Границы.** Только stdlib · LLM_FORBIDDEN · advisory: капитал не двигает, гейтом
не является, RiskPolicy не касается · пишет ТОЛЬКО в `data/investment_os/`.
Время — вход (`now=`). Запись идемпотентна по дню (тот же контракт, что у
proof-цепочки: строки архива и proof-строки соответствуют 1:1 по дням).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.strategy_lab.swarm.common import append_daily_proof

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data" / "investment_os"

ARCHIVE_SUFFIX = "_verdicts.jsonl"

#: Метки времени НЕ входят в отпечаток содержания — иначе «флип» показывал бы
#: ход часов, а не смену мнения.
VOLATILE_KEYS: frozenset[str] = frozenset({
    "generated_at", "last_verified", "as_of", "last_updated", "timestamp",
    "ts", "updated_at", "run_at",
})

#: Служебная обвязка артефакта: одинакова у всех аналитиков, вердиктом не является.
BOILERPLATE_KEYS: frozenset[str] = frozenset({
    "agent", "is_advisory", "consumer_contract", "note", "model", "generated_at",
})

#: Где искать постуру — в порядке предпочтения, точка = вложенность.
#: `status` СЮДА НЕ ВХОДИТ СОЗНАТЕЛЬНО. Замер по проду 2026-08-06: постуру
#: публикуют только 4 аналитика из 12 (chief, market_regime, red_team, _health),
#: у остальных есть лишь `status: "ok"` — они измеряют, а не занимают позицию.
#: Подставить `status` вместо постуры значило бы получить метрику, которая
#: ВСЕГДА показывает «мнение не менялось»: измерением она бы выглядела,
#: измерением бы не была. Нет постуры ⇒ None, и сменяемость меряется по
#: содержанию (content_sha256), а не выдумывается.
POSTURE_PATHS: tuple[str, ...] = (
    "combined_posture", "posture", "overall_posture", "house_view.overall_posture",
    "house_view.combined_posture", "house_view.posture", "house_view.stance",
    "overall", "verdict", "stance",
)

#: Ключи, по которым узнаётся ИМЯ элемента списка (какая именно возможность/конфликт).
_NAME_KEYS: tuple[str, ...] = ("name", "protocol", "pool", "id", "key", "metric", "label", "analyst")

MAX_FIELDS = 40
MAX_STR = 120
MAX_NAMES = 5


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _is_scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool)) or v is None


def _trunc(v: Any) -> Any:
    return v[:MAX_STR] if isinstance(v, str) and len(v) > MAX_STR else v


def strip_volatile(obj: Any) -> Any:
    """Рекурсивно убрать метки времени — основа стабильного отпечатка вердикта."""
    if isinstance(obj, dict):
        return {k: strip_volatile(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [strip_volatile(v) for v in obj]
    return obj


def content_sha256(payload: dict) -> str:
    """Отпечаток СОДЕРЖАНИЯ вердикта: канонический JSON без временных меток."""
    canon = json.dumps(strip_volatile(payload), sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _names_of(seq: list) -> list[str]:
    """До MAX_NAMES идентификаторов элементов списка (иначе виден только размер)."""
    out: list[str] = []
    for item in seq[:MAX_NAMES]:
        if isinstance(item, dict):
            for nk in _NAME_KEYS:
                if isinstance(item.get(nk), (str, int, float)):
                    out.append(str(item[nk])[:60])
                    break
        elif isinstance(item, (str, int, float)):
            out.append(str(item)[:60])
    return out


def digest(payload: dict) -> dict:
    """Сжатый снимок вердикта: постура + скаляры (глубина ≤2) + размеры + имена.

    Ограничен по размеру НАМЕРЕННО: архив живёт вечно и растёт каждый день, а для
    вопроса «менял ли аналитик мнение и на чём» нужен снимок, а не копия payload.
    """
    fields: dict[str, Any] = {}
    sizes: dict[str, int] = {}
    names: dict[str, list[str]] = {}

    for k, v in sorted((payload or {}).items()):
        if k in BOILERPLATE_KEYS or k in VOLATILE_KEYS:
            continue
        if _is_scalar(v):
            fields[k] = _trunc(v)
        elif isinstance(v, list):
            sizes[k] = len(v)
            n = _names_of(v)
            if n:
                names[k] = n
        elif isinstance(v, dict):
            sizes[k] = len(v)
            for k2, v2 in sorted(v.items()):
                if k2 in BOILERPLATE_KEYS or k2 in VOLATILE_KEYS:
                    continue
                path = f"{k}.{k2}"
                if _is_scalar(v2):
                    fields[path] = _trunc(v2)
                elif isinstance(v2, (list, dict)):
                    sizes[path] = len(v2)
                    if isinstance(v2, list):
                        n = _names_of(v2)
                        if n:
                            names[path] = n

    if len(fields) > MAX_FIELDS:  # детерминированная отсечка, а не случайная порча
        fields = dict(sorted(fields.items())[:MAX_FIELDS])

    posture = None
    for path in POSTURE_PATHS:
        val = fields.get(path)
        if isinstance(val, str) and val:
            posture = val
            break

    return {"posture": posture, "fields": fields, "sizes": sizes, "names": names,
            "content_sha256": content_sha256(payload or {})}


def archive_path(agent: str, data_dir: Optional[str | Path] = None) -> Path:
    return Path(data_dir or _DEFAULT_DATA_DIR) / f"{agent}{ARCHIVE_SUFFIX}"


def append_verdict(agent: str, payload: dict, *,
                   data_dir: Optional[str | Path] = None,
                   now: Optional[datetime] = None) -> bool:
    """Одна строка на (аналитик, UTC-день). True — записали, False — день уже покрыт.

    Идемпотентность по дню унаследована от proof-цепочки СОЗНАТЕЛЬНО: строки архива
    и proof-строки должны сходиться 1:1, иначе «архив отстаёт» стало бы неотличимо
    от «аналитик прогонялся дважды».
    """
    ts = _now(now)
    rec = {"agent": agent, "generated_at": (payload or {}).get("generated_at") or ts.isoformat()}
    rec.update(digest(payload or {}))
    return append_daily_proof(rec, archive_path(agent, data_dir), day=ts.strftime("%Y-%m-%d"))


def read_verdicts(agent: str, data_dir: Optional[str | Path] = None) -> list[dict]:
    """Строки архива аналитика; битая строка пропускается, отсутствие файла = []."""
    out: list[dict] = []
    try:
        with archive_path(agent, data_dir).open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out


def flip_stats(lines: list[dict]) -> dict:
    """Сменяемость вердикта по соседним АРХИВНЫМ дням.

    Две разные метрики, и смешивать их нельзя:
      content_flip_rate  менялся ли вердикт ВООБЩЕ — измерим у любого аналитика;
      flip_rate          менял ли аналитик ПОСТУРУ — измерим только у тех, кто
                         постуру публикует (4 из 12 на 2026-08-06).

    Меньше двух дней — не «0 флипов», а ЧЕСТНОЕ «не измерено» с причиной:
    один день не даёт ни одной пары для сравнения, и подать это как «стабильно»
    было бы ровно тем fail-OPEN, из-за которого архив и заводится.
    """
    days = sorted({str(r.get("date")) for r in lines if r.get("date")})
    dated = {str(r.get("date")): r for r in lines if r.get("date")}
    if len(days) < 2:
        return {"days": len(days), "flip_rate": None, "posture_flips": None,
                "content_flips": None, "content_flip_rate": None,
                "unchecked_reason": f"архив покрывает {len(days)} дн. — для сравнения нужно ≥2"}

    has_posture = all(dated[d].get("posture") for d in days)
    posture_flips = 0 if has_posture else None
    content_flips = pairs = 0
    for prev_day, day in zip(days, days[1:]):
        a, b = dated[prev_day], dated[day]
        pairs += 1
        if has_posture and a.get("posture") != b.get("posture"):
            posture_flips += 1
        if a.get("content_sha256") != b.get("content_sha256"):
            content_flips += 1
    return {"days": len(days), "posture_flips": posture_flips,
            "content_flips": content_flips,
            "content_flip_rate": round(content_flips / pairs, 3),
            "flip_rate": round(posture_flips / pairs, 3) if has_posture else None,
            "unchecked_reason": None if has_posture else
            "аналитик не публикует постуру — сменяемость меряется по содержанию (content_flip_rate)"}
