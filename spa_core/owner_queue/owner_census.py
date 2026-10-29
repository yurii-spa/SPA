"""Адресный разбор вопросов, назначенных владельцу (STUDIO-AUTONOMY-01 E1.4, ADR-857). ТОЛЬКО ЧТЕНИЕ.

Население — карточки, реально назначенные Юрию: ``status: needs-owner`` либо карточки решений
(``own-*`` / ``owner-decision-*``), чей статус не терминальный. Каждая попадает РОВНО в один класс;
сумма классов равна населению (проверяется самой функцией — иначе отказ, а не отчёт).

Классы (не «закрыто» = «сделано»: закрытие вопроса и выполнение работы — разные статусы):

* ``answer_recorded`` — ответ владельца записан в карточке (``owner_choice``) или статус ingested;
* ``answer_in_session_register`` — ответ есть в реестре сессии 27.10 и сверен по версии вопроса
  (``owner_answer.verify_session_answers``; доверие ``operator-import`` — не удостоверение личности);
* ``register_conflict`` — запись реестра есть, но карточка с ней не сходится (выбор/канал/версия);
* ``agent_work`` — вопрос снят с владельца по предмету (``closed_by_class: ADR-285``): это работа агента;
* ``needs_decision`` — открытый вопрос без ответа: настоящее решение владельца;
* ``other_open`` — назначен владельцу, но ни один признак выше не подходит (назван, а не спрятан).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

OWNER_PREFIXES = ("own-", "owner-decision-")
TERMINAL = ("owner-done", "done", "closed", "owner-accepted")
CLASSES = ("answer_recorded", "answer_in_session_register", "register_conflict", "agent_work",
           "needs_decision", "other_open")


def _fm(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        if ":" in ln and not ln[:1].isspace():
            k, v = ln.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def census(tracker_dir: Path, register_path: Optional[Path] = None) -> Dict[str, Any]:
    tracker_dir = Path(tracker_dir)
    if not tracker_dir.is_dir():
        return {"measured": False, "why": f"каталог трекера не найден: {tracker_dir}"}
    reg_ok: Dict[str, Optional[str]] = {}
    if register_path is not None:
        from spa_core.owner_queue.owner_answer import verify_session_answers
        reg_ok = dict(verify_session_answers(Path(register_path), tracker_dir))
    rows: List[Dict[str, Any]] = []
    unreadable: List[str] = []
    for p in sorted(tracker_dir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        try:
            fm = _fm(p.read_text(encoding="utf-8"))
        except OSError:
            unreadable.append(p.name)
            continue
        status = fm.get("status", "")
        owner_card = p.stem.startswith(OWNER_PREFIXES)
        if not (status == "needs-owner" or (owner_card and status not in TERMINAL)):
            continue
        if p.stem in reg_ok:
            cls = "answer_in_session_register" if reg_ok[p.stem] is None else "register_conflict"
        elif fm.get("closed_by_class") == "ADR-285":
            cls = "agent_work"
        elif fm.get("owner_choice") or status == "ingested":
            cls = "answer_recorded"
        elif status == "needs-owner":
            cls = "needs_decision"
        else:
            cls = "other_open"
        rows.append({"card": p.stem, "status": status, "class": cls, "title": fm.get("title", ""),
                     "why": reg_ok.get(p.stem) if cls == "register_conflict" else None})
    counts = {c: sum(1 for r in rows if r["class"] == c) for c in CLASSES}
    if sum(counts.values()) != len(rows):
        raise AssertionError("сумма классов не равна населению")
    missing_reg = sorted(k for k in reg_ok if k not in {r["card"] for r in rows})
    return {"measured": True, "tracker": str(tracker_dir), "population": len(rows), "counts": counts,
            "rows": rows, "unreadable": unreadable,
            "register_cards_outside_population": missing_reg}


def compare(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Расхождение двух копий трекера (например, origin и прод): карточки и классы."""
    ra = {r["card"]: r["class"] for r in a.get("rows", [])}
    rb = {r["card"]: r["class"] for r in b.get("rows", [])}
    return {"only_a": sorted(set(ra) - set(rb)), "only_b": sorted(set(rb) - set(ra)),
            "class_differs": sorted(k for k in set(ra) & set(rb) if ra[k] != rb[k])}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Разбор вопросов владельца (только чтение)")
    ap.add_argument("--tracker", required=True, nargs="+")
    ap.add_argument("--register", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    res = [census(Path(t), Path(a.register) if a.register else None) for t in a.tracker]
    doc: Dict[str, Any] = {"census": res}
    if len(res) == 2 and all(r.get("measured") for r in res):
        doc["compare"] = compare(res[0], res[1])
    text = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    for r in res:
        print(r.get("tracker"), "НЕ ИЗМЕРЕНО: " + r["why"] if not r.get("measured") else
              f"население {r['population']}: " + ", ".join(f"{k}={v}" for k, v in r["counts"].items()))
    return 0 if all(r.get("measured") for r in res) else 2


if __name__ == "__main__":
    raise SystemExit(main())
