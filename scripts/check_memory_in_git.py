#!/usr/bin/env python3
"""Шаг 0c протокола — «память лежит в git?» (инвариант #13, детерминированно).

**Зачем.** `CLAUDE.md` #13 говорит: источник правды — файлы в git, приложения и рабочие
деревья — только окна в них. До сих пор это было утверждение, а не измерение. 2026-08-02
цикл #86 обнаружил, что решения владельца живой сессии **2026-07-23** (ADR-054 kill-switch
authority, ADR-055 Head-of-Investment, два RFC-054, идея-источник, девять карточек бэклога и
ответы «Вариант X» в десяти карточках `owner-decision`) существовали **только в рабочем дереве
хоста** и не были закоммичены ни в одну ветку — одиннадцать дней. Радиус: автономные циклы
читают очередь и решения ИЗ GIT, поэтому одиннадцать циклов подряд видели вопросы, на которые
владелец уже ответил, а TOP-приоритетную директиву владельца не видели вовсе.

Шаг 0a (`check_undelivered_work.py`) на этот вопрос не отвечает по построению: он сверяет
**объявленную** в `session_changes.jsonl` работу. Работа живой сессии с владельцем ничего не
объявляет — её не видно ни одному существующему сторожу.

**Два независимых измерения (разные точки наблюдения):**

1. `--tree` (по умолчанию) — файлы доменов памяти в рабочем дереве против `origin/main`.
   Работает ТОЛЬКО на хосте: в чистом чекауте CI дерево равно origin по построению, и проверка
   честно скажет «всё совпадает». Это host-side шаг протокола, не CI-гейт.
2. `--links` — ссылочная целостность реестра решений: каждая ссылка из
   `docs/decisions/INDEX.md` разрешается в существующий файл, и каждый ADR-файл упомянут в
   реестре. Это измерение работает **в чистом чекауте**, то есть видно в CI: именно так
   `origin/main` одиннадцать дней держал строку `ADR-054` со ссылкой на файл, которого на
   origin не было.

Только stdlib, read-only, без сети (`git fetch` не вызывается — как и в шаге 0a).
Измерение «содержимое дерева когда-либо было на origin для этого пути» переиспользовано из
шага 0a (`origin_blob_history` / `_blob_sha`), а не скопировано.

Коды возврата: **0** — всё измерено и лежит в git · **1** — есть находки · **2** — что-то не
измерено (fail-CLOSED; «не измерено» никогда не сворачивается в «в порядке»).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from check_undelivered_work import (  # noqa: E402  (переиспользование, не копия)
    _blob_sha,
    _git,
    origin_blob_history,
)

DEFAULT_BASE = "origin/main"

# ── что считается «памятью» ──────────────────────────────────────────────────
# Домены, в которых живут решения, правила и очередь. Расширять осознанно: каждый
# добавленный домен обязан быть местом, где отсутствие файла в git = потеря решения.
MEMORY_DOMAINS = (
    "docs/decisions",
    "docs/rfcs",
    "docs/ideas",
    "docs/rules-draft",
    ".claude/rules",
    "nimbalyst-local/tracker",
)

# Отдельные файлы-записи решений, лежащие вне доменов-каталогов.
MEMORY_FILES = (
    "docs/POST_PAPER_TEST_PLAN.md",
)

# Реестр исключений: путь → ПРОСЛЕЖИВАЕМОЕ обоснование. Молчаливых исключений нет —
# тест требует непустого обоснования и существования пути (протухшие записи краснят).
EXCLUSIONS = {
    "nimbalyst-local/tracker/_BOARD.md":
        "авто-индекс: регенерится scripts/build_tracker_board.py из самих карточек, "
        "источник правды — карточки, расхождение доски ничего не теряет",
}

SUFFIXES = (".md",)

# ── состояния ────────────────────────────────────────────────────────────────
OK = "OK"                    # совпадает с base ref
STALE_LOCAL = "STALE_LOCAL"  # дерево отстало (его содержимое известно истории base) — не находка
ABSENT = "ABSENT"            # пути нет на base и содержимого нет в истории — НАХОДКА
DIVERGED = "DIVERGED"        # путь есть, но содержимого дерева не было на base НИКОГДА — НАХОДКА
UNCHECKED = "UNCHECKED"      # измерить не удалось — fail-CLOSED

FINDING_STATES = (ABSENT, DIVERGED)


def iter_memory_paths(root, domains=MEMORY_DOMAINS, files=MEMORY_FILES,
                      exclusions=EXCLUSIONS):
    """Пути памяти в рабочем дереве, относительные к корню, отсортированы."""
    root = Path(root)
    out = []
    for d in domains:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in SUFFIXES:
                continue
            rel = p.relative_to(root).as_posix()
            if rel in exclusions:
                continue
            out.append(rel)
    for f in files:
        if (root / f).is_file() and f not in exclusions:
            out.append(f)
    return sorted(set(out))


def classify(root, base_ref, rel, git=_git):
    """(состояние, объяснение) для одного пути. Ничего не пишет."""
    path = Path(root) / rel
    sha = _blob_sha(path)
    if sha is None:
        return UNCHECKED, "файл не читается — содержимое не измерено"

    history = origin_blob_history(root, base_ref, rel, git=git)
    if history is None:
        return UNCHECKED, f"git log по {base_ref} не отработал — история не измерена"

    rc, _, _ = git(root, "cat-file", "-e", f"{base_ref}:{rel}")
    if rc != 0:
        if sha in history:
            return (STALE_LOCAL,
                    f"путь удалён на {base_ref}, но это же содержимое там было — не потеря")
        return (ABSENT,
                f"на {base_ref} пути нет, и такого содержимого не было в его истории НИКОГДА")

    rc, head_sha, _ = git(root, "rev-parse", f"{base_ref}:{rel}")
    if rc != 0 or not head_sha.strip():
        return UNCHECKED, f"не удалось прочитать blob {base_ref}:{rel}"
    if sha == head_sha.strip():
        return OK, f"совпадает с {base_ref}"
    if sha in history:
        return (STALE_LOCAL,
                f"дерево отстало: это содержимое было на {base_ref} раньше (не потеря)")
    return (DIVERGED,
            f"есть на {base_ref}, но содержимого рабочего дерева НЕ БЫЛО в его истории — "
            f"правка не доставлена")


_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+\.md)\)")
_BACKTICK_RE = re.compile(r"`(docs/[^`\s]+\.md)`")
_ADR_FILE_RE = re.compile(r"^ADR-[\w.-]+\.md$")


def check_index_links(root, index_rel="docs/decisions/INDEX.md"):
    """Ссылочная целостность реестра решений. (находки, не_измерено).

    Работает в ЧИСТОМ чекауте, поэтому видна в CI: битая строка реестра (ADR указан,
    файла нет) краснит гейт там же, где живёт origin.
    """
    root = Path(root)
    index = root / index_rel
    if not index.is_file():
        return [], [f"{index_rel}: файла нет — ссылочная целостность не измерена"]
    try:
        text = index.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [f"{index_rel}: не читается ({exc}) — не измерено"]

    findings = []
    targets = set(_LINK_RE.findall(text)) | set(_BACKTICK_RE.findall(text))
    for t in sorted(targets):
        if (index.parent / t).is_file() or (root / t).is_file():
            continue
        findings.append(f"{index_rel} ссылается на `{t}`, но такого файла нет в дереве")

    listed = {Path(t).name for t in targets}
    for p in sorted((root / "docs" / "decisions").glob("*.md")):
        if not _ADR_FILE_RE.match(p.name):
            continue  # INDEX.md, _TEMPLATE.md и прочее — не решения
        if p.name not in listed:
            findings.append(
                f"{p.relative_to(root).as_posix()} существует, но не упомянут в {index_rel} "
                f"— решение вне реестра")
    return findings, []


def build_report(root=ROOT, base_ref=DEFAULT_BASE, git=_git, do_tree=True, do_links=True,
                 domains=MEMORY_DOMAINS, files=MEMORY_FILES, exclusions=EXCLUSIONS):
    report = {"base_ref": base_ref, "root": str(root), "checked": 0,
              "findings": [], "unchecked": [], "stale_local": [], "link_findings": []}

    rc, _, _ = git(root, "rev-parse", "--verify", base_ref)
    if rc != 0:
        report["unchecked"].append(f"базовый ref {base_ref} не разрешается — дерево не измерено")
        do_tree = False

    if do_tree:
        for rel in iter_memory_paths(root, domains, files, exclusions):
            report["checked"] += 1
            state, why = classify(root, base_ref, rel, git=git)
            if state in FINDING_STATES:
                report["findings"].append({"path": rel, "state": state, "why": why})
            elif state == UNCHECKED:
                report["unchecked"].append(f"{rel}: {why}")
            elif state == STALE_LOCAL:
                report["stale_local"].append({"path": rel, "why": why})

    if do_links:
        lf, lu = check_index_links(root)
        report["link_findings"] = lf
        report["unchecked"].extend(lu)
    return report


def render(report) -> str:
    lines = [f"Сверка «память в git» против {report['base_ref']}; "
             f"файлов памяти проверено: {report['checked']}"]

    if report["findings"]:
        lines.append("")
        lines.append(f"⚠️  НЕ В GIT ({len(report['findings'])}) — решение/правило/карточка живёт "
                     f"только в рабочем дереве:")
        for f in report["findings"]:
            lines.append(f"  [{f['state'].lower()}] {f['path']}")
            lines.append(f"      {f['why']}")

    if report["link_findings"]:
        lines.append("")
        lines.append(f"⚠️  РЕЕСТР РЕШЕНИЙ РАСПАЛСЯ ({len(report['link_findings'])}):")
        for f in report["link_findings"]:
            lines.append(f"  - {f}")

    if report["unchecked"]:
        lines.append("")
        lines.append(f"❓ НЕ ИЗМЕРЕНО ({len(report['unchecked'])}) — молчаливого «всё в порядке» "
                     f"здесь не будет:")
        for u in report["unchecked"]:
            lines.append(f"  - {u}")

    if report["stale_local"]:
        lines.append("")
        lines.append(f"🕓 дерево отстало ({len(report['stale_local'])}) — не находки:")
        for s in report["stale_local"][:10]:
            lines.append(f"  - {s['path']}")
        if len(report["stale_local"]) > 10:
            lines.append(f"  … и ещё {len(report['stale_local']) - 10}")

    if not report["findings"] and not report["link_findings"] and not report["unchecked"]:
        lines.append("")
        lines.append("✅ вся память доменов лежит в git, реестр решений цел.")
    return "\n".join(lines)


def exit_code(report) -> int:
    if report["unchecked"]:
        return 2  # fail-CLOSED: «не измерено» важнее «нашёл»
    if report["findings"] or report["link_findings"]:
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE, help="базовый ref (по умолчанию origin/main)")
    ap.add_argument("--root", default=str(ROOT), help="корень репозитория")
    ap.add_argument("--tree-only", action="store_true", help="только сверка дерева с base")
    ap.add_argument("--links-only", action="store_true", help="только ссылочная целостность реестра")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    do_tree = not args.links_only
    do_links = not args.tree_only
    report = build_report(root=Path(args.root), base_ref=args.base,
                          do_tree=do_tree, do_links=do_links)
    if args.json:
        import json
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
