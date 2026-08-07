#!/usr/bin/env python3
"""Сверка «что уносим из STATE.md — есть ли это в docs/journal/».

**Зачем.** `docs/STATE.md` заявляет предел ~150 строк и держит ~1900: файл ведётся
дописыванием СВЕРХУ, и хроника циклов вытеснила то, ради чего файл заведён (фокус ·
активные задачи · последние решения · открытые вопросы). Его читает КАЖДАЯ сессия
по `CLAUDE.md` §Протокол сессии — это самый часто читаемый файл репозитория.

Карточка `inbox-docs-state-md-razrossya-do-1647-strok-pr` требует сокращения, но с
условием: **ни одна запись не потеряна** — то, что уносится, обязано присутствовать в
`docs/journal/`. Проверка ДО переноса, а не «на глаз»: запись цикла есть в журнале ⇒
из STATE она просто удаляется; НЕТ в журнале ⇒ её надо перенести, а не удалить.

**Единица сверки — ЦИКЛ, а не текст.** Записи в STATE и в журнале пишутся независимо и
разными словами: сверять их построчно/по хэшу нельзя — это дало бы «не совпало» на 100 %
и обесценило проверку. Совпадает у них ИДЕНТИФИКАТОР события: номер цикла (`цикл #131`,
`Цикл #131`, `(2026-08-05, #124)`) и дата. Поэтому вердикт даётся по номеру цикла, а
записи без номера (интерактивные сессии, блоки ADR-066, автопилот) отдельным классом
`NO_CYCLE_ID` — они требуют ручного взгляда и молча удалёнными быть не могут.

Вердикты по записи STATE:
  COVERED    — все номера циклов записи найдены в журнале ⇒ можно удалять из STATE;
  MISSING    — номер цикла в журнале НЕ найден ⇒ переносить, не удалять;
  NO_CYCLE_ID — номера цикла в записи нет ⇒ ручной разбор (fail-CLOSED: не «покрыто»).

Только чтение. Ничего не меняет. Коды возврата: 0 — всё COVERED; 1 — есть MISSING или
NO_CYCLE_ID (то есть нужен ручной шаг). Только stdlib.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

#: Номер цикла — ТОЛЬКО по контексту, а не по любому `#N`.
#:
#: Голое `#(\d{2,3})` разбирать нельзя дважды: снизу оно теряет однозначные циклы
#: (`#2`…`#9` — реальные записи от 2026-07-16, их семь), а сверху ловит чужие решётки
#: (`PR #2`, `инв. #16`, `класс #29/#31`), и тогда запись «покрыта» циклом, о котором
#: в ней не было речи. Обе ошибки молчаливы. Поэтому берутся две формы, в которых
#: номер действительно называет цикл:
#:   * `цикл #131` / `Циклом #124` / `циклы #49–#50` — слово «цикл» перед решёткой;
#:   * `(2026-07-30, #48)` — форма заголовков раздела «Последние решения».
CYCLE_RE = re.compile(r"(?:цикл\w*\s+#(\d{1,3})|,\s*#(\d{1,3})\s*[),])", re.I)

#: Заголовок записи STATE: блок-цитата в прологе либо верхнеуровневый пункт в «Последних решениях».
BQ_ENTRY_RE = re.compile(r"^> \*\*")
BULLET_ENTRY_RE = re.compile(r"^- \*\*")


def cycle_ids(text: str) -> list:
    """Номера циклов, НАЗВАННЫЕ в тексте (см. CYCLE_RE). Порядок — по возрастанию, без повторов."""
    out = set()
    for m in CYCLE_RE.finditer(text):
        out.add(m.group(1) or m.group(2))
    return sorted(out, key=int)


def split_entries(lines: list, start: int, end: int, header_re) -> list:
    """Нарезать [start, end) на записи по строкам-заголовкам. Возвращает [(номер строки, текст)].

    Жирная строка ВНУТРИ записи (`> **Границы измерены:** …`) — это подзаголовок тела, а
    не новая запись: в блок-цитате записи разделяются пустой строкой цитаты (`>`). Считать
    новой записью каждую жирную строку значило бы дробить одну запись на куски, у которых
    номера цикла нет, — и получать `NO_CYCLE_ID` там, где цикл назван абзацем выше.
    """
    starts = []
    for i in range(start, end):
        if not header_re.match(lines[i]):
            continue
        if header_re is BQ_ENTRY_RE and i > start and lines[i - 1].startswith(">") \
                and lines[i - 1].strip() != ">":
            continue                      # продолжение тела записи, а не её начало
        starts.append(i)
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else end
        out.append((s + 1, "\n".join(lines[s:e])))
    return out


def journal_cycles(journal_dir: pathlib.Path) -> tuple:
    """(циклы в ЗАГОЛОВКАХ журнала, циклы в теле) → каждый: номер → файлы.

    Различие существенно и потому не сворачивается в один набор. Покрытие засчитывается
    ТОЛЬКО по заголовку `## …`: это значит «у цикла есть СВОЯ запись в журнале». Упоминание
    в теле чужой записи («поднята осиротевшая работа цикла #137») доказывает, что номер
    где-то встречался, но не что запись цикла сохранена, — засчитывать его за покрытие
    значило бы разрешить удаление из STATE того, чего в журнале нет.
    """
    heads, bodies = {}, {}
    for f in sorted(journal_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        for line in text.split("\n"):
            sink = heads if line.startswith("## ") else bodies
            for c in cycle_ids(line):
                sink.setdefault(c, set()).add(f.name)
    return ({k: sorted(v) for k, v in heads.items()},
            {k: sorted(v) for k, v in bodies.items()})


def audit(state_path: pathlib.Path, journal_dir: pathlib.Path) -> dict:
    lines = state_path.read_text(encoding="utf-8").split("\n")

    def section_bounds(marker: str, stop_prefix: str = "## ") -> tuple:
        s = next((i for i, l in enumerate(lines) if l.startswith(marker)), None)
        if s is None:
            return (None, None)
        e = next((i for i in range(s + 1, len(lines)) if lines[i].startswith(stop_prefix)), len(lines))
        return (s, e)

    # Пролог — всё до первого раздела `## `, кроме шапки файла.
    first_section = next((i for i, l in enumerate(lines) if i > 0 and l.startswith("## ")), len(lines))
    entries = split_entries(lines, 0, first_section, BQ_ENTRY_RE)
    region = {id(e): "пролог" for e in entries}

    ds, de = section_bounds("## 🗂️ Последние решения")
    if ds is not None:
        dec = split_entries(lines, ds + 1, de, BULLET_ENTRY_RE)
        for e in dec:
            region[id(e)] = "Последние решения"
        entries += dec

    heads, bodies = journal_cycles(journal_dir)
    report = {"state_lines": len(lines), "journal_cycles_headed": len(heads),
              "journal_cycles_body_only": len(set(bodies) - set(heads)), "entries": []}
    for ent in entries:
        line_no, text = ent
        cycles = cycle_ids(text)
        if not cycles:
            verdict, missing = "NO_CYCLE_ID", []
        else:
            missing = [c for c in cycles if c not in heads]
            verdict = "MISSING" if missing else "COVERED"
        report["entries"].append({
            "line": line_no,
            "region": region[id(ent)],
            "title": text.split("\n")[0][:120],
            "lines": len(text.split("\n")),
            "cycles": cycles,
            "missing_cycles": missing,
            # упоминание в ТЕЛЕ журнала — подсказка для ручного разбора, НЕ покрытие
            "body_only_hint": sorted(set(missing) & set(bodies)),
            "verdict": verdict,
        })
    counts = {}
    for e in report["entries"]:
        counts[e["verdict"]] = counts.get(e["verdict"], 0) + 1
    report["counts"] = counts
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="docs/STATE.md")
    ap.add_argument("--journal-dir", default="docs/journal")
    ap.add_argument("--json", action="store_true", help="вывести отчёт машиночитаемо")
    args = ap.parse_args(argv)

    rep = audit(pathlib.Path(args.state), pathlib.Path(args.journal_dir))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        c = rep["counts"]
        print(f"STATE: {rep['state_lines']} строк · записей {len(rep['entries'])} · "
              f"циклов со СВОЕЙ записью в журнале {rep['journal_cycles_headed']} "
              f"(ещё {rep['journal_cycles_body_only']} только в теле — не покрытие)")
        print(f"COVERED={c.get('COVERED', 0)} MISSING={c.get('MISSING', 0)} "
              f"NO_CYCLE_ID={c.get('NO_CYCLE_ID', 0)}")
        for e in rep["entries"]:
            if e["verdict"] != "COVERED":
                print(f"  [{e['verdict']}] стр.{e['line']} ({e['region']}, {e['lines']} строк) "
                      f"циклы={e['cycles'] or '—'} нет-в-журнале={e['missing_cycles'] or '—'}")
                print(f"      {e['title']}")
    c = rep["counts"]
    return 0 if not (c.get("MISSING") or c.get("NO_CYCLE_ID")) else 1


if __name__ == "__main__":
    sys.exit(main())
