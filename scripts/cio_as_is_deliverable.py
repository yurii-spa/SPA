#!/usr/bin/env python3
"""§6 приказа владельца «Portfolio CIO» ИСПОЛНЕН? — спрашивает дерево, не память.

§6 ТЗ (`nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md`)
называет документ ПО ИМЕНИ — ``PORTFOLIO_CIO_AS_IS.md`` — перечисляет шесть
обязательных разделов и кончается строкой владельца «Только после этого переходить к
реализации.». Прибор ADR-1067 (`scripts/cio_tz_section_census.py`) нашёл, что файла
не было 488 циклов, и честно напечатал свою слепоту: **«адрес назван» НЕ ЕСТЬ
«§ исполнен»** — он мерит реестр решений, а не работу.

Этот прибор задаёт следующий вопрос, и ровно его:

1. **существует ли** документ с НАЗВАННЫМ владельцем именем — в ЛЮБОМ каталоге
   дерева. Владелец назвал ИМЯ, а не путь; искать только в `docs/` значило бы
   получить «нет» от своей двери, а не от дерева (та же дверь, что у ADR-1067);
2. **несёт ли он ВСЕ ШЕСТЬ** названных владельцем разделов — заголовком, а не
   упоминанием в прозе. Подстрока разделом не считается: раздел, названный внутри
   абзаца, читателю §6 не отвечает (урок ADR-333);
3. **есть ли у КАЖДОГО раздела якорь замера** — строка ``Замер:``, называющая путь,
   и этот путь СУЩЕСТВУЕТ в дереве. Раздел без якоря есть проза; раздел с якорем на
   несуществующий путь хуже прозы — он выдаёт ненаблюдённое за наблюдённое.

**Три исхода различимы** (инв. #17): исполнен (0) · НЕ исполнен с названным
отсутствующим куском (1) · **НЕ ИЗМЕРЕНО** с названной причиной (2). Обхода дерева
не вышло, документ не декодируется, ни одного заголовка в объявленной форме — это
`unmeasured`, а не «не исполнен»: неизвестно, что является разделом.

**Чего прибор НЕ судит.** ОСМЫСЛЕННОСТЬ раздела: шесть заголовков с якорями, не
являющиеся отчётом о системе, он пропустит — это следующий вопрос, и мерить его
нечем, кроме независимого читателя. Он не судит и ВЕРНОСТЬ чисел документа; за это
отвечает `--differential` ниже, и только за один из них.

``--differential`` — отдельный вопрос и отдельная цена: воспроизводит замер §2.3
документа (убивает ли трим ADR-850 ход, или ход не стои́т цены и без трима), зовя ТУ
ЖЕ чистую функцию `rebalance_economics.evaluate`, которую зовёт цикл. Сначала
**положительный контроль**: прогон на урезанной цели обязан воспроизвести вердикт,
ЗАПИСАННЫЙ циклом. Не воспроизвёл ⇒ `unmeasured`, и второй прогон не печатается
вовсе — иначе он утверждал бы о мире, которого замер не видел.

Прибор только ЧИТАЕТ. Ничего не чинит, ничего не двигает, в `data/` не пишет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: Имя, названное владельцем в §6. Не путь — ИМЯ.
DOC_NAME = "PORTFOLIO_CIO_AS_IS.md"

#: Шесть разделов §6, дословно. Порядок — владельца.
REQUIRED_SECTIONS: Tuple[str, ...] = (
    "Current architecture",
    "Root cause",
    "Existing reusable components",
    "Missing capability",
    "Policy conflicts",
    "Recommended architecture",
)

#: Якорь замера. Раздел обязан НАЗВАТЬ, чем его числа сняты.
#:
#: Якорь кончается на ПУСТОЙ СТРОКЕ, а не на конце строки. Первая редакция брала
#: `(.+)` — то есть один физический ряд, — и перечень из пяти путей, перенесённый
#: по ширине абзаца, читался как якорь БЕЗ ПУТЕЙ: раздел §3 этого же документа
#: получил «проза, не отчёт о замере» при семи названных путях. Граница «до пустой
#: строки» объявлена, а не выбрана: шире (до конца раздела) якорь зачёл бы любой
#: путь из соседней прозы и перестал бы отвечать на свой вопрос.
ANCHOR_RE = re.compile(r"Замер:[ \t]*((?:.+\n?)+?)(?:\n[ \t]*\n|\Z)", re.U)

#: Расширения, по которым якорь ОБЪЯВЛЯЕТ себя путём. Перечень ЗАМКНУТ намеренно:
#: первая редакция принимала любое `.\w+`, и `adapter_orchestrator.POLLED_ADAPTERS`
#: (модуль + ИМЯ в нём) был прочитан как файл `adapter_orchestrator.POLLED_ADAPTERS`,
#: которого, естественно, в дереве нет — то есть прибор выдумал находку о документе
#: из своей же слепоты к точечной ссылке на символ. Символ пишется отдельно от пути.
PATH_EXTS = ("py", "json", "jsonl", "md", "yaml", "yml", "sh", "toml",
             "txt", "js", "astro", "plist", "cfg", "ini")

#: Путь внутри якоря: `a/b/c.py`, `data/x.json`, `docs/decisions/ADR-1.md`.
#: Граница слева не даёт поймать хвост соседнего слова, справа — обрезать суффикс.
PATH_RE = re.compile(
    r"(?<![\w./-])((?:[\w.-]+/)+[\w.-]+\.(?:" + "|".join(PATH_EXTS) + r"))(?![\w/])")

#: Каталог РАНТАЙМНЫХ артефактов. Его содержимое в git не живёт (`.gitignore`), поэтому
#: «файла нет» в одноразовом дереве есть свойство ДЕРЕВА, а не документа. Считать это
#: дефектом значило бы отвечать на свой вопрос вместо нужного; молчать — сделать «не
#: проверяли» неотличимым от «проверили». Поэтому третий исход: якорь НАЗЫВАЕТСЯ
#: рантаймным и считается ОТДЕЛЬНО (инв. #17).
RUNTIME_PREFIXES = ("data/",)

SATISFIED = "satisfied"
NOT_SATISFIED = "not_satisfied"
UNMEASURED = "unmeasured"

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}


class NotMeasured(Exception):
    """Единственный путь к коду 2: причина названа и печатается."""


def find_document(root: str, name: str = DOC_NAME) -> List[str]:
    """Пути всех файлов дерева с этим именем (относительные). Обход — целиком.

    Возвращается СПИСОК, а не первый найденный: два документа с одним именем —
    это находка («какой из них читать?»), и прятать её выбором первого нельзя.
    """
    base = Path(root)
    if not base.is_dir():
        raise NotMeasured(f"корень не является каталогом: {root}")
    found: List[str] = []
    try:
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in files:
                if fname == name:
                    found.append(os.path.relpath(os.path.join(dirpath, fname), base))
    except OSError as exc:
        raise NotMeasured(f"обход дерева не отработал: {exc}") from exc
    return sorted(found)


def section_blocks(text: str) -> Dict[str, str]:
    """``{название раздела: его тело}`` для разделов, названных ЗАГОЛОВКОМ.

    Заголовком считается строка markdown (`#`…`######`), чей текст СОДЕРЖИТ
    название раздела; нумерация владельцем не задана, поэтому «## 1. Root cause»
    и «### Root cause» равно годятся. Тело кончается на СЛЕДУЮЩЕМ заголовке того
    же или более высокого уровня — иначе хвост последнего раздела утёк бы до конца
    файла и зачёл бы чужие якоря (дословный урок ADR-1067, мутация M16).
    """
    lines = text.splitlines()
    heads: List[Tuple[int, int, str]] = []   # (индекс строки, уровень, текст)
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    out: Dict[str, str] = {}
    for idx, (line_no, level, title) in enumerate(heads):
        for want in REQUIRED_SECTIONS:
            if want.lower() not in title.lower() or want in out:
                continue
            end = len(lines)
            for next_no, next_level, _ in heads[idx + 1:]:
                if next_level <= level:
                    end = next_no
                    break
            out[want] = "\n".join(lines[line_no + 1:end])
    return out


def anchors(block: str) -> List[str]:
    """Пути, названные якорями ``Замер:`` этого раздела."""
    paths: List[str] = []
    for line in ANCHOR_RE.findall(block or ""):
        paths.extend(PATH_RE.findall(line))
    seen, uniq = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def audit(root: str, name: str = DOC_NAME) -> dict:
    """Полный вопрос о §6. :class:`NotMeasured` — единственный путь к коду 2."""
    copies = find_document(root, name)
    if not copies:
        return {
            "status": NOT_SATISFIED, "doc_name": name, "copies": [],
            "why": [f"документа `{name}`, названного владельцем в §6, в дереве НЕТ"],
            "sections": {},
        }
    if len(copies) > 1:
        raise NotMeasured(
            f"документов с именем `{name}` в дереве {len(copies)}: {copies} — "
            "какой из них читатель §6 обязан читать, по дереву не видно")

    rel = copies[0]
    try:
        text = (Path(root) / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise NotMeasured(f"документ `{rel}` не прочитан: {exc}") from exc

    # ДВА РАЗНЫХ состояния, и до замера цикла #1211 они были слиты в одно.
    #
    # «Заголовков нет ВОВСЕ» ⇒ неизвестно, что здесь является разделом: мерить нечем,
    # и это `unmeasured` (fail-CLOSED). «Заголовки есть, но ни один не назван разделом
    # §6» ⇒ разделов НЕТ, и это ИЗМЕРЕНО — ответ `not_satisfied`. Слить их значило бы
    # выдавать измеренное отсутствие за неспособность измерить: документ, перечисливший
    # шесть названий ПРОЗОЙ в одном абзаце, получал `unmeasured` вместо «не исполнен»
    # (нашла проба `test_the_probe_does_not_pass_by_substring`).
    if not re.search(r"^#{1,6}\s+\S", text, re.M):
        raise NotMeasured(
            f"в `{rel}` нет ни одного markdown-заголовка — неизвестно, что здесь "
            "является разделом")
    blocks = section_blocks(text)

    rows, why = {}, []
    for want in REQUIRED_SECTIONS:
        block = blocks.get(want)
        if block is None:
            rows[want] = {"present": False, "anchors": [], "anchors_missing": []}
            why.append(f"раздел «{want}» не назван заголовком")
            continue
        named = anchors(block)
        runtime = [p for p in named if p.startswith(RUNTIME_PREFIXES)]
        checkable = [p for p in named if p not in runtime]
        missing = [p for p in checkable if not (Path(root) / p).exists()]
        rows[want] = {"present": True, "anchors": named, "anchors_runtime": runtime,
                      "anchors_checked": checkable, "anchors_missing": missing}
        if not named:
            why.append(f"у раздела «{want}» нет якоря `Замер:` — это проза, не отчёт о замере")
        if missing:
            why.append(f"раздел «{want}» ссылается на несуществующий путь: {missing}")

    return {
        "status": NOT_SATISFIED if why else SATISFIED,
        "doc_name": name, "copies": copies, "doc": rel,
        "why": why, "sections": rows,
        "blindness": (
            "прибор судит НАЛИЧИЕ раздела и его якорь, а НЕ осмысленность: шесть "
            "заголовков с якорями, не являющиеся отчётом о системе, он пропустит"),
    }


# ─────────────────────────── дифференциал §2.3 ────────────────────────────

def differential(data_dir: str) -> dict:
    """Убивает ли трим ADR-850 ход — или ход не стои́т цены и без трима.

    Зовёт ТУ ЖЕ чистую функцию, что цикл (`rebalance_economics.evaluate`), с
    ОДИНАКОВЫМИ входами, различая ровно одно: цель. Положительный контроль
    (воспроизведение ЗАПИСАННОГО вердикта) обязателен и стои́т ПЕРВЫМ.
    """
    base = Path(data_dir)
    if not base.is_dir():
        raise NotMeasured(f"каталог данных не найден: {data_dir} — из worktree живого "
                          "data/ нет по построению, назови прод-дерево флагом --data-dir")
    # ДЕРЕВО КОДА НАЗЫВАЕТСЯ И ПЕЧАТАЕТСЯ. launchd и прямой зов дают `sys.path[0]` =
    # каталог СКРИПТА (`scripts/`), а не корень репозитория, поэтому `import spa_core`
    # честно падал — и падал в правильную сторону (код 2 «НЕ ИЗМЕРЕНО»), но измерять
    # при этом было нечем. Берётся дерево ЗАПУЩЕННОГО прибора: именно его код сессия
    # собрала и проверила. Молча подставить чужое дерево хуже ошибки — читатель не
    # узнает, о чьём `rebalance_economics` ему ответили (`.claude/rules/deployment.md`,
    # поправка #1031).
    code_root = str(Path(__file__).resolve().parent.parent)
    if code_root not in sys.path:
        sys.path.insert(0, code_root)
    try:
        from spa_core.allocator.rebalance_economics import evaluate, TriggerParams
        from spa_core.paper_trading.allocation_rationale import (
            _history_from_trades, _position_ages)
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(
            f"прибор экономики хода не ввезён из дерева {code_root}: {exc}") from exc

    def _load(rel):
        try:
            return json.loads((base / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise NotMeasured(f"{rel} не прочитан: {exc}") from exc

    rat, pos_doc = _load("allocation_rationale.json"), _load("current_positions.json")
    trim = rat.get("admissible_trim") or {}
    recorded = rat.get("decision_shadow") or {}
    if not trim.get("target_after") or not trim.get("target_before"):
        raise NotMeasured("в allocation_rationale.json нет обеих целей трима ADR-850 "
                          "(target_before/target_after) — различать нечего")
    if not recorded.get("decision"):
        raise NotMeasured("в allocation_rationale.json нет записанного вердикта — "
                          "положительный контроль не на чем поставить")

    fc = pos_doc.get("feed_coverage") or {}
    apy_pct = fc.get("apy_used_pct") or {}
    evidenced = {p for p, s in (fc.get("apy_sources") or {}).items() if s == "live"}
    capital = float(pos_doc.get("capital_usd") or 0.0)
    current = pos_doc.get("positions") or {}

    reg = _load("adapter_registry.json")
    chains = {n: str(e["chain"]).strip().lower()
              for n, e in (reg.get("adapters") or {}).items()
              if isinstance(e, dict) and e.get("chain")}
    orch = _load("adapter_orchestrator_status.json")
    tvl_ev = {str(a["protocol"]) for a in (orch.get("adapters") or [])
              if isinstance(a, dict) and a.get("protocol")
              and a.get("tvl_usd") is not None and a.get("tvl_source") == "live"}

    trades = _load("trades.json")
    if isinstance(trades, dict):
        trades = trades.get("trades") or []
    from datetime import datetime as _dt
    try:
        now = _dt.fromisoformat(rat["generated_at"])
    except (KeyError, ValueError) as exc:
        raise NotMeasured(f"отметка цикла не разобрана: {exc}") from exc
    hist = _history_from_trades(trades, now)
    ages = _position_ages(trades, current, now)

    def run(target):
        d = evaluate(
            current_positions=current, target_positions=target, apy_pct=apy_pct,
            evidenced=evidenced, chains=chains, capital_usd=capital,
            params=TriggerParams.for_mode(),
            days_since_last_act=hist["days_since_last_act"], position_age_days=ages,
            turnover_last_week_usd=hist["turnover_last_week_usd"],
            turnover_today_usd=hist["turnover_today_usd"],
            last_move_legs=hist["last_move_legs"],
            days_since_last_move=hist["days_since_last_move"],
            tvl_evidenced=tvl_ev or None,
        )
        return {"decision": d.decision, "reasons": list(d.reasons),
                "apy_now_pp": d.apy_now_pp, "apy_opt_pp": d.apy_opt_pp,
                "gain_pp": d.gain_pp, "required_gain_pp": d.required_gain_pp,
                "cost_usd": d.cost_usd, "payback_days": d.payback_days,
                "turnover_usd": d.turnover_usd}

    trimmed = run(trim["target_after"])
    control_ok = (trimmed["decision"] == recorded["decision"]
                  and abs((trimmed["gain_pp"] or 0.0)
                          - (recorded.get("gain_pp") or 0.0)) < 1e-6)
    if not control_ok:
        raise NotMeasured(
            "положительный контроль НЕ воспроизвёл записанный вердикт "
            f"(записано {recorded['decision']}/{recorded.get('gain_pp')}, "
            f"получено {trimmed['decision']}/{trimmed['gain_pp']}) — входы прибора "
            "расходятся с входами цикла, и о полном ходе он утверждать не вправе")
    full = run(trim["target_before"])
    return {
        "measured_at": rat.get("generated_at"), "control_reproduced": True,
        "code_root": code_root, "data_dir": str(base),
        "recorded": {"decision": recorded["decision"], "gain_pp": recorded.get("gain_pp")},
        "trimmed": trimmed, "full": full,
        "trim_is_the_cause": trimmed["decision"] != full["decision"],
    }


def render(report: dict) -> str:
    out: List[str] = []
    mark = {SATISFIED: "✅", NOT_SATISFIED: "❌"}[report["status"]]
    out.append(f"§6 приказа «Portfolio CIO» — deliverable `{report['doc_name']}`")
    if report.get("doc"):
        out.append(f"  документ: {report['doc']}")
    for want in REQUIRED_SECTIONS:
        row = report["sections"].get(want)
        if not row:
            out.append(f"  ❌ {want}: раздела НЕТ")
            continue
        if not row["present"]:
            out.append(f"  ❌ {want}: раздела НЕТ")
        elif row["anchors_missing"]:
            out.append(f"  ❌ {want}: якорь на несуществующий путь {row['anchors_missing']}")
        elif not row["anchors"]:
            out.append(f"  ❌ {want}: есть, но БЕЗ якоря `Замер:` — проза")
        else:
            tail = (f", из них рантаймных (в этом дереве не проверяются) "
                    f"{len(row['anchors_runtime'])}" if row.get("anchors_runtime") else "")
            out.append(f"  ✅ {want}: якорей {len(row['anchors'])}{tail}")
    for line in report["why"]:
        out.append(f"  · {line}")
    out.append(f"{mark} §6 {'ИСПОЛНЕН' if report['status'] == SATISFIED else 'НЕ ИСПОЛНЕН'}")
    if report.get("blindness"):
        out.append(f"  НЕ ДОКЛАДЫВАЕТ: {report['blindness']}")
    return "\n".join(out)


def render_differential(d: dict) -> str:
    out = [f"дифференциал трима ADR-850 (замер цикла {d['measured_at']})",
           f"  дерево кода: {d['code_root']} · каталог данных: {d['data_dir']}",
           f"  положительный контроль: ✅ воспроизведён "
           f"({d['recorded']['decision']}, выигрыш {d['recorded']['gain_pp']} пп)"]
    for label, key in (("урезанная цель (её цикл и судил)", "trimmed"),
                       ("полная цель аллокатора (до трима)", "full")):
        r = d[key]
        out.append(f"  {label}: {r['decision']} · выигрыш {r['gain_pp']} пп "
                   f"при полосе {r['required_gain_pp']} пп · цена ${r['cost_usd']} "
                   f"на ${r['turnover_usd']:,.0f} · окупаемость {r['payback_days']} дн")
    out.append("  вердикт: "
               + ("трим И ЕСТЬ причина — без него ход прошёл бы"
                  if d["trim_is_the_cause"] else
                  "трим НЕ причина — ход не стои́т своей цены и БЕЗ трима"))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".", help="корень дерева, которому задаётся вопрос")
    ap.add_argument("--name", default=DOC_NAME, help="имя документа из §6")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--differential", metavar="DATA_DIR", default=None,
                    help="ПРОД-каталог data/: воспроизвести замер §2.3 документа")
    args = ap.parse_args(argv)

    try:
        if args.differential:
            diff = differential(args.differential)
            print(json.dumps(diff, indent=1, ensure_ascii=False) if args.json
                  else render_differential(diff))
            return 0
        report = audit(args.root, args.name)
    except NotMeasured as exc:
        print(f"⚠️  НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=1, ensure_ascii=False) if args.json else render(report))
    return 0 if report["status"] == SATISFIED else 1


if __name__ == "__main__":
    raise SystemExit(main())
