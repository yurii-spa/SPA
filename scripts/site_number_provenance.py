#!/usr/bin/env python3
"""site_number_provenance.py — откуда на сайте взялось КАЖДОЕ число (идея владельца 10.09).

Вопрос, на который отвечает этот сторож
---------------------------------------
Рядом уже работают три проверки сайта, и ни одна не отвечает на этот вопрос:

| Вопрос | Кто отвечает | Чего НЕ проверяет |
|---|---|---|
| свежи ли числа в снимке? | ``site_freshness_monitor`` | берёт ли их страница вообще |
| разошлись ли числа МЕЖДУ страницами? | ``site_content_audit`` (METRIC_DIVERGENCE) | откуда взято совпадающее число |
| не убрали ли токен честности? | ``check_owner_gate`` | ничего про источник |
| **откуда это число взялось?** | **этот файл** | всё остальное |

Согласованные между собой литералы проходят проверку на расхождение и остаются
литералами: два одинаковых напечатанных «~3,3 %» не расходятся ни с чем, кроме
реальности. Замер 09.09: строка «~3,3 % фактических» была вписана руками в
шестнадцати местах, трек к тому дню давал 5,3 %, и НИ ОДИН сторож этого не сказал.

Три класса чисел — и четвёртый исход
------------------------------------
1. ``sourced``   — страница берёт числа из объявленного источника (снимок трека,
   ``realized_rate``, ``golive_label``, ``tier_bands``, конфиг, живой API).
2. ``declared``  — числа объявлены в шапке страницы строкой::

       // site-numbers: illustrative — учебный пример, не претензия о системе
       // site-numbers: constitutional — пороги стоп-крана, источник RiskConfig

   Классы: ``illustrative`` (учебный пример, не претензия) и ``constitutional``
   (порог, заданный политикой; причина ОБЯЗАНА назвать, где он живёт).
3. ``UNDECLARED`` — напечатано число-претензия, источника нет, объявления нет.
   Это находка.
4. ``unmeasured`` — каталог страниц не найден или файл не прочитан. Отдельный
   ГРОМКИЙ исход: «не измерено» никогда не выдаётся за «чисто» (инв. #2).

Почему объявление ФАЙЛОМ, а не строкой. Замер 10.09: 33 страницы печатают 322
литерала без единого источника, и почти все — учебные примеры академии. Пометка
на каждой строке означала бы 322 правки ради разметки того, что и так не является
претензией. Классификация живёт на файле, а храповик держит остаток.

Храповик
--------
``scripts/site_numbers_baseline.json`` перечисляет файлы, у которых провенанса нет
СЕГОДНЯ. База может только УМЕНЬШАТЬСЯ. Новая страница с числом-претензией без
провенанса краснеет сразу — ровно это и просил владелец: «одно место, откуда всё
берётся», и правило, которое не даёт появиться второму.

Дописывать файл в базу, чтобы погасить падение, ЗАПРЕЩЕНО — тот же порядок, что у
``frozen_date_baseline.json``.

stdlib-only, детерминирован, fail-CLOSED.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_REPO = Path(__file__).resolve().parents[1]
_SITE = _REPO / "landing" / "src"
_BASELINE = _REPO / "scripts" / "site_numbers_baseline.json"

#: Импорт/обращение, после которого числа на странице СЧИТАЮТСЯ, а не печатаются.
#: Это и есть «одно место», о котором речь: снимок трека собирает
#: ``scripts/generate_track_snapshot.py`` из ``data/`` раз в сутки.
SOURCES: Tuple[str, ...] = (
    "data/track_snapshot.json",
    "track_snapshot",
    "lib/constitution",
    "lib/realized_rate",
    "lib/golive_label",
    "lib/tier_bands",
    "lib/protocol_verdicts",
    "data/strategy_config",
    "api.earn-defi.com",
    "/api/",
)

#: Объявление класса в шапке страницы.
_DECL = re.compile(
    r"//\s*site-numbers:\s*(illustrative|constitutional)\s*[—-]\s*(\S.*)")

#: Число-претензия: процент или сумма в долларах. Всё остальное (версии, годы,
#: размеры в css, номера уроков) претензией о доходности не является.
_CLAIM = re.compile(r"(?<![\w.])(?:\$\s?\d[\d   ,.]*|\d{1,3}(?:[.,]\d+)?\s?%)")

_STRIP = re.compile(r"<style[\s\S]*?</style>|<script[\s\S]*?</script>"
                    r"|<!--[\s\S]*?-->|\{/\*[\s\S]*?\*/\}")
#: Выражение Astro — там число ВЫЧИСЛЯЕТСЯ, литералом оно не является.
_EXPR = re.compile(r"\{[^{}]*\}")


def _frontmatter(text: str) -> str:
    """Шапка `---…---` файла .astro; её не видит посетитель, объявление живёт там."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end > 0 else ""


def literal_claims(text: str) -> List[str]:
    """Числа-претензии, НАПЕЧАТАННЫЕ в разметке (не вычисленные, не в комментарии)."""
    body = _STRIP.sub(" ", text)
    fm = _frontmatter(text)
    if fm:
        body = body.replace(fm, " ", 1)
    return _CLAIM.findall(_EXPR.sub(" ", body))


def classify(path: Path, text: str) -> Dict:
    """Класс одной страницы. Ключи: ``file``, ``verdict``, ``claims``, ``why``."""
    claims = literal_claims(text)
    rel = str(path)
    if not claims:
        return {"file": rel, "verdict": "no_claims", "claims": 0, "why": ""}
    decl = _DECL.search(_frontmatter(text))
    if decl:
        return {"file": rel, "verdict": "declared", "claims": len(claims),
                "why": f"{decl.group(1)}: {decl.group(2).strip()}"}
    src = next((s for s in SOURCES if s in text), None)
    if src:
        return {"file": rel, "verdict": "sourced", "claims": len(claims),
                "why": f"источник {src}"}
    return {"file": rel, "verdict": "UNDECLARED", "claims": len(claims),
            "why": "напечатано число-претензия, источника нет, класс не объявлен"}


def scan(site_dir: Path = _SITE) -> Dict:
    """Перепись всех страниц. Каталога нет ⇒ ``unmeasured``, а не «чисто»."""
    if not site_dir.exists():
        return {"unmeasured": [f"каталог страниц не найден: {site_dir}"], "rows": []}
    rows: List[Dict] = []
    unmeasured: List[str] = []
    for p in sorted(site_dir.rglob("*.astro")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            unmeasured.append(f"{p}: {type(exc).__name__}: {exc}")
            continue
        row = classify(p.relative_to(site_dir), text)
        rows.append(row)
    if not rows and not unmeasured:
        unmeasured.append(f"в {site_dir} не найдено ни одной страницы .astro")
    return {"unmeasured": unmeasured, "rows": rows}


def undeclared(report: Dict) -> List[str]:
    return sorted(r["file"] for r in report["rows"] if r["verdict"] == "UNDECLARED")


def load_baseline(path: Path = _BASELINE) -> Tuple[List[str], str]:
    """База храповика. Нечитаемая база — ``unmeasured``, НЕ пустой список."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], f"база храповика не прочитана: {type(exc).__name__}: {exc}"
    files = doc.get("files")
    if not isinstance(files, list):
        return [], "база храповика без списка `files`"
    return sorted(str(f) for f in files), ""


def verdict(report: Dict, baseline: List[str]) -> Dict:
    """Итог: что появилось нового и что уже можно вычеркнуть из базы."""
    now = set(undeclared(report))
    base = set(baseline)
    counts: Dict[str, int] = {}
    for r in report["rows"]:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {
        "counts": counts,
        "new_undeclared": sorted(now - base),
        "fixed_since_baseline": sorted(base - now),
        "undeclared_total": len(now),
        "baseline_total": len(base),
        "unmeasured": report.get("unmeasured", []),
    }


def format_report(v: Dict) -> List[str]:
    out = [f"страницы по классам: {v['counts']}",
           f"без провенанса сейчас: {v['undeclared_total']} · в базе: {v['baseline_total']}"]
    if v["unmeasured"]:
        out.append("НЕ ИЗМЕРЕНО:")
        out += [f"  • {u}" for u in v["unmeasured"]]
    if v["new_undeclared"]:
        out.append("НОВОЕ без провенанса (это находка):")
        out += [f"  ✗ {f}" for f in v["new_undeclared"]]
    if v["fixed_since_baseline"]:
        out.append("уже с провенансом — вычеркнуть из базы:")
        out += [f"  ✓ {f}" for f in v["fixed_since_baseline"]]
    return out


def main(argv: List[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    rep = scan()
    base, why = load_baseline()
    if why:
        rep.setdefault("unmeasured", []).append(why)
    v = verdict(rep, base)
    print("\n".join(format_report(v)))
    if "--emit-baseline" in argv:
        _BASELINE.write_text(json.dumps(
            {"note": "Файлы без провенанса чисел. База может ТОЛЬКО уменьшаться "
                     "(scripts/site_number_provenance.py, .claude/rules/site-numbers.md). "
                     "Дописывать сюда файл, чтобы погасить падение, ЗАПРЕЩЕНО.",
             "files": undeclared(rep)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"база записана: {len(undeclared(rep))} файлов")
        return 0
    if v["unmeasured"]:
        return 2
    return 1 if v["new_undeclared"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
