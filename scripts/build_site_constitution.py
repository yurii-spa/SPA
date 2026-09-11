#!/usr/bin/env python3
"""build_site_constitution.py — числа-КОНСТИТУЦИЯ сайта из одного источника.

Идея владельца 10.09: все числа на сайте обязаны браться из одного места, а не
перепечатываться по страницам. Замер того дня: 140 страниц, 32 печатают
число-претензию, не подключившись ни к одному источнику.

Мест оказалось ДВА, и делит их не удобство, а природа числа:

| Что за число | Где живёт | Как часто меняется | Кто пишет |
|---|---|---|---|
| **замер** (ставка, дни, NAV, просадка, гейты) | ``landing/src/data/track_snapshot.json`` | раз в сутки | ``generate_track_snapshot.py`` |
| **решение** (пороги стоп-крана, потолки, floor TVL, стартовый капитал) | ``landing/src/lib/constitution.json`` | только новым ADR | ЭТОТ файл |

Смешивать их нельзя: замер устаревает за сутки, а порог не устаревает вовсе —
он меняется решением. Число, которое НЕ является ни тем, ни другим, а просто
напечатано, — третий случай, и его-то и запрещает
``.claude/rules/site-numbers.md``.

Источник конституции ОДИН — ``data/capital_config.json`` (git-tracked, живёт в
репозитории, меняется ADR). Сторож ``scripts/tests/test_site_constitution_parity.py``
краснеет, если сгенерированный файл разошёлся с источником: разойтись они не могут
дольше одного прогона CI.

stdlib-only, атомарная запись, fail-CLOSED: источник не прочитан ⇒ НИЧЕГО не
переписываем и выходим с ненулевым кодом (устаревшая копия хуже отсутствия).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Tuple

_REPO = Path(__file__).resolve().parents[1]
SOURCE = _REPO / "data" / "capital_config.json"
OUT = _REPO / "landing" / "src" / "lib" / "constitution.json"

#: Что именно сайт вправе печатать как «порог». Ключ — имя для страницы,
#: значение — путь в источнике. Ничего сверх этого списка наружу не уезжает:
#: конфиг несёт и то, что публике знать незачем.
FIELDS: Dict[str, Tuple[str, ...]] = {
    "start_capital_usd":      ("capital", "starting_capital_usd"),
    "currency":               ("capital", "currency"),
    "min_cash_buffer_pct":    ("allocation_limits", "min_cash_buffer_pct"),
    "max_per_protocol_t1_pct": ("allocation_limits", "max_per_protocol_t1_pct"),
    "max_per_protocol_t2_pct": ("allocation_limits", "max_per_protocol_t2_pct"),
    "max_t2_total_pct":       ("allocation_limits", "max_t2_total_pct"),
    "tvl_floor_usd":          ("allocation_limits", "tvl_floor_usd"),
    "apy_floor_pct":          ("risk_parameters", "apy_floor_pct"),
    "apy_ceiling_pct":        ("risk_parameters", "apy_ceiling_pct"),
    "min_paper_days_before_live": ("risk_parameters", "min_paper_days_before_live"),
}

def kill_switch_ladder() -> Tuple[dict, str]:
    """Лестница стоп-крана — ИЗ ЖИВОГО КОДА governance, а не переписанная сюда.

    В ``capital_config.json`` лежит устаревшее ОДНОступенчатое
    ``max_drawdown_kill_pct: 5.0``; напечатать его на сайте значило бы объявить одну
    ступень вместо двух (ADR-034/048: SOFT −5 %, HARD −10 %). Числа берутся из
    констант модуля: копия, переписанная в этот файл, была бы ровно тем литералом,
    который правило и запрещает.
    """
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    try:
        from spa_core.governance import kill_switch as ks
    except Exception as exc:  # noqa: BLE001 — отказ уезжает словами, не молчанием
        return {}, f"governance-слой не импортирован: {type(exc).__name__}: {exc}"
    return {"soft_derisk_pct": float(ks.SOFT_DERISK_THRESHOLD_PCT),
            "hard_kill_pct": float(ks.DRAWDOWN_THRESHOLD_PCT),
            "_source": "spa_core/governance/kill_switch.py (ADR-034/ADR-048)"}, ""


def _dig(doc: dict, path: Tuple[str, ...]):
    cur = doc
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def chain_caps() -> Tuple[dict, str]:
    """Потолки СЕТИ — из живого кода аллокатора, а не переписанные сюда.

    Той же природы, что лестница стоп-крана выше: в `capital_config.json` этих
    порогов нет вовсе, они живут константами класса (ADR-025/ADR-136), и страница
    академии печатала «Base ≤ 20 %» литералом. Копия здесь была бы ровно тем
    литералом, который правило `.claude/rules/site-numbers.md` и запрещает.
    """
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    try:
        from spa_core.allocator.allocator import StrategyAllocator as _A
    except Exception as exc:  # noqa: BLE001 — источник не прочитан ⇒ отказ целиком
        return {}, f"потолки сети не прочитаны из аллокатора: {type(exc).__name__}: {exc}"
    caps = {}
    for site_key, attr in (("single_chain_pct", "SINGLE_CHAIN_CAP"),
                           ("l2_total_pct", "L2_TOTAL_CAP"),
                           ("base_chain_pct", "BASE_CHAIN_CAP")):
        val = getattr(_A, attr, None)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            return {}, f"в аллокаторе нет числового {attr} — конституция была бы неполной"
        caps[site_key] = round(float(val) * 100.0, 4)
    caps["_source"] = "spa_core/allocator/allocator.py (ADR-025/ADR-136)"
    return caps, ""


def build(source: Path = SOURCE) -> Tuple[dict, str]:
    """``(документ, причина-отказа)``. Отказ ⇒ документ пустой, писать нечего."""
    try:
        doc = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, f"источник не прочитан: {source} — {type(exc).__name__}: {exc}"
    ladder, why = kill_switch_ladder()
    if why:
        return {}, why
    caps, why_caps = chain_caps()
    if why_caps:
        return {}, why_caps
    out: Dict[str, object] = {
        "note": ("Числа-РЕШЕНИЯ сайта. Источник — data/capital_config.json + "
                 "governance/kill_switch.py + потолки сети из allocator.py; файл СГЕНЕРИРОВАН "
                 "scripts/build_site_constitution.py, руками не править. "
                 "Замеры (ставка, дни, NAV) живут в data/track_snapshot.json."),
        "source": "data/capital_config.json",
        "kill_switch": ladder,
        "chain_caps": caps,
    }
    missing = []
    for name, path in FIELDS.items():
        val = _dig(doc, path)
        if val is None:
            missing.append(name + " (" + "/".join(path) + ")")
        out[name] = val
    if missing:
        # fail-CLOSED: неполная конституция хуже отсутствующей — страница
        # напечатала бы «data unavailable» там, где порог ЕСТЬ, но не найден.
        return {}, "в источнике нет полей: " + ", ".join(missing)
    return out, ""


def write(doc: dict, out: Path = OUT) -> None:
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, out)


def main(argv=None) -> int:
    doc, why = build()
    if why:
        print("ОТКАЗ:", why, file=sys.stderr)
        return 2
    write(doc)
    print(f"записан {OUT.relative_to(_REPO)}: {len(FIELDS)} порогов + лестница стоп-крана")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
