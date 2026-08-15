#!/usr/bin/env python3
"""Распределитель номеров ADR: номер нельзя занять дважды (карточка «Номера ADR сталкиваются»).

**Что было измерено.** За один день 2026-08-08 номера ADR столкнулись ДВАЖДЫ: две параллельные
сессии выписали `ADR-073`, потом две выписали `ADR-076`. Оба раза приоритет отдавали по факту
приземления на origin, а проигравший переименовывал свой файл и оставлял на старом имени
указатель — ссылка уже уехала в коммит, и мёртвая ссылка хуже указателя. На 2026-08-08 в дереве
остались следы обоих исходов: `ADR-073` разошёлся честно сразу (живая строка + строка-указатель
`Superseded`), `ADR-067` — не разошёлся и держал два действующих решения до 2026-08-15, когда
гейт go-live был перенумерован в `ADR-087` тем же правилом приоритета (цикл #251). Живых дублей
в реестре больше нет; храповик `test_live_duplicate_numbers_only_shrink` стоит с ПУСТОЙ базой,
то есть теперь любой дубль для него — новый.

**Причина — не невнимательность.** Номер выбирается взглядом на каталог `docs/decisions/` в
НАЧАЛЕ работы, а приземляется через час-два. Между этими двумя моментами живёт вся работа цикла,
и параллельная сессия за это время успевает занять тот же номер. Пока номер выдаёт взгляд, а не
распределитель, столкновения гарантированы — вопрос только частоты.

**Почему существующий сторож этого не видит.** `check_memory_in_git --links` отвечает на СВОЙ
вопрос: «каждая ссылка реестра разрешается, каждый файл решения упомянут в реестре». Два разных
решения под одним номером проходят его НАСКВОЗЬ зелёными — оба файла есть, обе строки на месте.
Это ровно тот класс, которым проект уже платил: сторож честно отвечает на свой вопрос, а читают
его как ответ на нужный. Поэтому здесь ДОБАВЛЕНО недостающее измерение, а не переписано старое:
ссылочная целостность по-прежнему меряется вызовом `check_index_links` (переиспользование, не
копия — второй реализации одного измерения в этом репозитории быть не должно).

**Два вопроса — два ответа:**

| Вопрос | Команда | Когда |
|---|---|---|
| Какой номер брать? | `next` | В МОМЕНТ пуша, не в начале работы |
| Этот набор файлов можно доставлять? | `check --files …` | Интерлок пушера, до сети |

`next` меряет занятость по СОЮЗУ origin/main и рабочего дерева. Смотреть только в дерево — это
и есть исходный дефект: параллельная сессия живёт на origin, а не у тебя на диске.

**Почему `max+1`, а не «первый свободный».** В нумерации есть дыры (31–47, 49, 51, 52, 71), и
они не свободны: `ADR-071` уже назван в `docs/STATE.md` как «аудит-как-код» — решение, о котором
договорились раньше, чем написали файл. Выдать такой номер новому решению значит столкнуть его
с уже уехавшей ссылкой, то есть воспроизвести ровно ту аварию, которую этот модуль устраняет.
Карточка оставляла выбор реализации агенту; дыры дороже, чем плотность нумерации.

Коды возврата: **0** — свободно / находок нет · **1** — есть находки · **2** — что-то не
измерено (fail-CLOSED: «не измерено» никогда не сворачивается в «в порядке»).

stdlib-only, детерминирован, без сети (git читает локальные ref'ы).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from check_undelivered_work import _git  # noqa: E402  (переиспользование, не копия)

DEFAULT_BASE = "origin/main"
DECISIONS_DIR = "docs/decisions"
INDEX_REL = f"{DECISIONS_DIR}/INDEX.md"

# Имя файла решения: ADR-<ключ>-<слаг>.md. Ключ бывает числовым (`067`) и именованным
# (`YL`, `OWN`, `TEST`) — это РАЗНЫЕ пространства имён, и распределяется только числовое.
_FILE_RE = re.compile(r"^ADR-(?P<key>\d+|[A-Z]+)-(?P<slug>.+)\.md$")
_NUMERIC_KEY_RE = re.compile(r"^\d+$")

# Строка реестра: `| ADR-067 | заголовок | статус | ссылка |`. Пометка «(дубль)» в первой
# колонке — часть принятого способа расходиться, а не мусор: см. ADR-073.
_ROW_RE = re.compile(r"^\|\s*(?P<num>ADR-[0-9A-Za-z.-]+?)\s*(?P<dup>\(дубль\))?\s*\|")

# Статус, снимающий претензию на номер. Строка-указатель не занимает номер: она объясняет,
# КУДА уехало решение, и без неё ссылка из старого коммита упирается в пустоту.
_RELEASED_STATUS_RE = re.compile(r"^\s*(superseded|withdrawn|rejected|отозван|заменен|заменён)",
                                 re.IGNORECASE)


def file_key(name: str):
    """Ключ нумерации по имени файла решения, либо None если это не файл решения."""
    m = _FILE_RE.match(name)
    return m.group("key") if m else None


def _row_fields(line: str):
    """(ключ, статус, дубль?) для строки реестра, либо None.

    Колонки берутся с КОНЦА: заголовки решений длинные и содержат запятые, скобки и
    вложенные ссылки, поэтому «третья колонка слева» ломается на первом же заголовке
    с разделителем внутри, а «предпоследняя» — нет.
    """
    m = _ROW_RE.match(line)
    if not m:
        return None
    parts = line.split("|")
    if len(parts) < 5:
        return None
    status = parts[-3].strip()
    key = m.group("num")[len("ADR-"):]
    return key, status, bool(m.group("dup"))


def parse_index(text: str):
    """{ключ: [(статус, дубль?), …]} по тексту реестра. Ничего не читает с диска."""
    rows: dict[str, list] = {}
    for line in text.splitlines():
        fields = _row_fields(line)
        if fields is None:
            continue
        key, status, dup = fields
        rows.setdefault(key, []).append((status, dup))
    return rows


def is_live_claim(status: str, dup: bool) -> bool:
    """Строка ПРЕТЕНДУЕТ на номер? Указатель и снятое решение — не претендуют."""
    if dup:
        return False
    return not _RELEASED_STATUS_RE.match(status or "")


def _origin_files(root, base_ref, git=_git):
    """Имена файлов решений на base ref, либо None если ref не измерим (fail-CLOSED)."""
    rc, out, _ = git(root, "ls-tree", "--name-only", f"{base_ref}:{DECISIONS_DIR}")
    if rc != 0:
        return None
    return [line.strip() for line in out.splitlines() if line.strip()]


def _origin_index(root, base_ref, git=_git):
    """Текст реестра на base ref, либо None если не измерим."""
    rc, out, _ = git(root, "show", f"{base_ref}:{INDEX_REL}")
    if rc != 0:
        return None
    return out


def taken_keys(root, base_ref=DEFAULT_BASE, git=_git):
    """(занятые ключи, не_измерено). Союз origin и рабочего дерева.

    Смотреть только в дерево — исходный дефект: параллельная сессия занимает номер НА ORIGIN,
    и её файла у тебя на диске нет по построению. Поэтому недоступность origin — не повод
    ответить «ну, по дереву свободно»: это отказ измерить (код 2).
    """
    root = Path(root)
    taken: dict[str, set] = {}
    unchecked = []

    def claim(key, where):
        taken.setdefault(key, set()).add(where)

    origin_names = _origin_files(root, base_ref, git=git)
    if origin_names is None:
        unchecked.append(
            f"каталог решений на {base_ref} не читается — занятость номеров НЕ измерена; "
            f"выдать номер по одному лишь рабочему дереву значит воспроизвести аварию 08.08")
    else:
        for name in origin_names:
            key = file_key(name)
            if key:
                claim(key, f"{base_ref}:{DECISIONS_DIR}/{name}")

    origin_index = _origin_index(root, base_ref, git=git)
    if origin_index is None:
        unchecked.append(f"{INDEX_REL} на {base_ref} не читается — строки реестра НЕ измерены")
    else:
        for key, rows in parse_index(origin_index).items():
            if any(is_live_claim(s, d) for s, d in rows):
                claim(key, f"{base_ref}:{INDEX_REL}")

    decisions = root / DECISIONS_DIR
    if decisions.is_dir():
        for p in sorted(decisions.glob("*.md")):
            key = file_key(p.name)
            if key:
                claim(key, f"дерево:{DECISIONS_DIR}/{p.name}")
    index = root / INDEX_REL
    if index.is_file():
        try:
            for key, rows in parse_index(index.read_text(encoding="utf-8")).items():
                if any(is_live_claim(s, d) for s, d in rows):
                    claim(key, f"дерево:{INDEX_REL}")
        except OSError as exc:
            unchecked.append(f"{INDEX_REL} не читается ({exc}) — строки дерева НЕ измерены")

    return taken, unchecked


def next_number(root, base_ref=DEFAULT_BASE, git=_git):
    """(следующий свободный номер | None, занятые, не_измерено)."""
    taken, unchecked = taken_keys(root, base_ref, git=git)
    if unchecked:
        return None, taken, unchecked
    numeric = [int(k) for k in taken if _NUMERIC_KEY_RE.match(k)]
    if not numeric:
        # Пустой каталог решений — это не «начинай с 001», а сломанное измерение:
        # у живого репозитория решения есть. Молчаливого «всё в порядке» здесь не будет.
        return None, taken, [
            f"на {base_ref} и в дереве не найдено НИ ОДНОГО числового решения — "
            f"измерение сломано, номер не выдаю"]
    return max(numeric) + 1, taken, []


# ── интерлок пушера: набор файлов ────────────────────────────────────────────

def check_push(root, files, base_ref=DEFAULT_BASE, git=_git):
    """(находки, не_измерено) для НАБОРА доставляемых файлов.

    Судит только то, что уезжает этим пушем, и то, чего этот пуш касается. Иначе
    предсуществующий дубль `ADR-067` запирал бы любую доставку, к нему не относящуюся, —
    сторож, краснеющий не на твоей работе, отключается первым.
    """
    root = Path(root)
    findings, unchecked = [], []

    rel_files = []
    for f in files:
        p = Path(f)
        try:
            rel = p.resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            rel = p.as_posix()
        rel_files.append(rel)

    pushed_decisions = [r for r in rel_files
                        if r.startswith(f"{DECISIONS_DIR}/") and file_key(Path(r).name)]
    if not pushed_decisions:
        return [], []  # решения не уезжают — этому сторожу нечего сказать

    origin_names = _origin_files(root, base_ref, git=git)
    if origin_names is None:
        return [], [f"каталог решений на {base_ref} не читается — столкновение номеров "
                    f"НЕ измерено (fail-CLOSED)"]

    # Реестр, который БУДЕТ на origin после этого пуша: если INDEX.md уезжает — берём
    # версию из дерева, иначе действует та, что уже лежит на origin.
    if INDEX_REL in rel_files:
        index_path = root / INDEX_REL
        if not index_path.is_file():
            return [], [f"{INDEX_REL} объявлен к доставке, но в дереве его нет — не измерено"]
        try:
            index_text = index_path.read_text(encoding="utf-8")
        except OSError as exc:
            return [], [f"{INDEX_REL} не читается ({exc}) — не измерено"]
    else:
        index_text = _origin_index(root, base_ref, git=git)
        if index_text is None:
            return [], [f"{INDEX_REL} на {base_ref} не читается — не измерено"]
    index_rows = parse_index(index_text)

    origin_by_key: dict[str, list] = {}
    for name in origin_names:
        key = file_key(name)
        if key:
            origin_by_key.setdefault(key, []).append(name)

    for rel in sorted(pushed_decisions):
        name = Path(rel).name
        key = file_key(name)

        # 1. Столкновение: НОВЫЙ файл берёт номер, уже занятый ДРУГИМ файлом на origin.
        others = [n for n in origin_by_key.get(key, []) if n != name]
        if others and name not in origin_by_key.get(key, []):
            findings.append(
                f"{rel}: номер ADR-{key} уже занят на {base_ref} файлом "
                f"{', '.join(sorted(others))} — это столкновение, а не обновление. "
                f"Возьми номер через `scripts/adr_number.py next` и переименуй ДО пуша")

        # 2. Решение вне реестра — ловится ДО приземления, а не тестом после (карточка).
        rows = index_rows.get(key, [])
        if not rows:
            findings.append(
                f"{rel}: в {INDEX_REL} нет ни одной строки ADR-{key} — решение уехало бы "
                f"вне реестра и покрасило бы main (test_live_registry_of_decisions_is_intact)")
        elif not any(is_live_claim(s, d) for s, d in rows):
            findings.append(
                f"{rel}: все строки ADR-{key} в реестре сняты (Superseded/указатель), "
                f"а файл доставляется как действующее решение — реестр и файл спорят")

    # 3. Две ЖИВЫЕ строки на один номер среди тронутых этим пушем — но находка только
    #    если ИМЕННО ЭТОТ пуш их создаёт или добавляет. Предсуществующий дубль (ADR-067)
    #    не должен запирать правку файла под тем же номером: сторож, краснеющий на чужой
    #    беспорядок, отключают первым, и тогда он не поймает и настоящее столкновение.
    #    Порог — состояние origin: стало хуже ⇒ отказ, не хуже (в т.ч. ЛУЧШЕ) ⇒ пропуск.
    before_rows = parse_index(_origin_index(root, base_ref, git=git) or "")
    for key in sorted({file_key(Path(r).name) for r in pushed_decisions}):
        live = [s for s, d in index_rows.get(key, []) if is_live_claim(s, d)]
        was = len([s for s, d in before_rows.get(key, []) if is_live_claim(s, d)])
        if len(live) > 1 and len(live) > was:
            findings.append(
                f"ADR-{key}: в {INDEX_REL} становится {len(live)} действующих строки на один "
                f"номер ({', '.join(live)}), было {was} — номер делят двое. Разойтись: "
                f"проигравший перенумеровывается, на старом номере остаётся "
                f"строка-указатель Superseded")

    return findings, unchecked


def live_duplicates(root, index_rel=INDEX_REL):
    """{ключ: [статусы]} — номера с ДВУМЯ действующими претензиями в реестре дерева.

    Отдельно от `check_push`: тот судит доставку, этот — состояние живого репозитория
    (ратчет в тестах). Оба меряют одним `parse_index`/`is_live_claim`.
    """
    index = Path(root) / index_rel
    if not index.is_file():
        return {}
    out = {}
    for key, rows in parse_index(index.read_text(encoding="utf-8")).items():
        live = [s for s, d in rows if is_live_claim(s, d)]
        if len(live) > 1:
            out[key] = live
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_next(args) -> int:
    number, taken, unchecked = next_number(Path(args.root), args.base)
    if args.json:
        print(json.dumps({"next": number, "taken": sorted(taken),
                          "unchecked": unchecked}, ensure_ascii=False, indent=2))
    elif unchecked:
        print("❓ НЕ ИЗМЕРЕНО — номер не выдан (fail-CLOSED):")
        for u in unchecked:
            print(f"  - {u}")
    else:
        print(f"ADR-{number:03d}")
        print(f"  занято номеров: {len(taken)} (союз {args.base} и рабочего дерева)")
    return 2 if unchecked else 0


def _cmd_check(args) -> int:
    findings, unchecked = check_push(Path(args.root), args.files, args.base)
    if args.json:
        print(json.dumps({"findings": findings, "unchecked": unchecked},
                         ensure_ascii=False, indent=2))
        return 2 if unchecked else (1 if findings else 0)
    if unchecked:
        print("❓ НЕ ИЗМЕРЕНО — доставку решений не подтверждаю (fail-CLOSED):")
        for u in unchecked:
            print(f"  - {u}")
        return 2
    if findings:
        print(f"⚠️  НОМЕРА ADR ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("✅ номера решений в наборе свободны, каждое есть в реестре.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help="корень репозитория")
    ap.add_argument("--base", default=DEFAULT_BASE, help="базовый ref (по умолчанию origin/main)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("next", help="следующий свободный номер (мерить В МОМЕНТ пуша)")

    c = sub.add_parser("check", help="можно ли доставлять этот набор файлов")
    c.add_argument("--files", nargs="+", required=True, help="файлы набора доставки")

    args = ap.parse_args(argv)
    return _cmd_next(args) if args.cmd == "next" else _cmd_check(args)


if __name__ == "__main__":
    raise SystemExit(main())
