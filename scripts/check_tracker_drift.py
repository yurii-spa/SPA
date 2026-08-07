#!/usr/bin/env python3
"""Шаг 1-пред: сверка трекера рабочего дерева с `origin/main` — read-only, stdlib, без сети.

**Зачем.** `orchestrator_queue.py list` (шаг 1 протокола) читает трекер ТОГО дерева, чья копия
скрипта запущена (`spa_core/owner_queue/queue.py::TRACKER_DIR` выводится из `__file__`, cwd не
влияет). Циклы работают в изолированных worktree и пушат результат **прямо на origin** через
Contents API — хост-дерево при этом не обновляется НИКОГДА. Никто эти два набора карточек не
сверял, и очередь молча отвечала не на тот вопрос.

Измерено циклом #147 на живом входе: хост-дерево выдало **5 карточек `inbox` в статусе `new`**,
и все пять на `origin/main` уже `done`/`in-progress`, — а **7 настоящих открытых карточек не
показало вовсе**, потому что их файлов в хост-дереве нет. Очередь была неверна в обе стороны
одновременно и на 100%: показывала сделанное и прятала новое. Это ровно класс fail-OPEN, за
который проект платит с #29 (сторож честно отвечает на СВОЙ вопрос — «что лежит в этом
каталоге?» — а читается как ответ на нужный: «что ждёт работы?»).

**Что этот сторож НЕ делает.** Он ничего не переписывает и не «синхронизирует». Массовый
`git checkout origin/main -- <трекер>` запрещён по построению: он стёр бы карточки, которые
существуют ТОЛЬКО в рабочем дереве (их заводит мост ADR-066 и сами сессии). Поэтому сторож
только **измеряет и называет** расхождение, а разрешение — по классу расхождения:

* ``stale``            — файл дерева найден в ИСТОРИИ origin для этого же пути ⇒ дерево строго
                         ОТСТАЁТ (доказано, а не предположено), origin авторитетен;
* ``diverged``         — содержимого дерева в истории origin НЕТ ⇒ у дерева своя правка,
                         судить нельзя, только ручная сверка;
* ``hidden``           — карточка есть на origin, в дереве её НЕТ ⇒ задание невидимо;
* ``undelivered``      — карточка есть в дереве, на origin НЕТ ⇒ не доставлена;
* ``deleted_on_origin``— в дереве есть, на origin удалена (её содержимое в истории пути есть).

**Fail-CLOSED.** Нет git / нет ref / нечитаем каталог ⇒ вердикт «НЕ ИЗМЕРЕНО» и код 2.
Молчаливого «всё в порядке» здесь не будет.

**`git fetch` НЕ вызывается** (как и в шаге 0a): сторож не ходит в сеть, он сверяется с той
копией `origin/main`, что уже есть локально, и ВСЕГДА печатает её sha — чтобы «сверено с origin»
нельзя было прочитать как «сверено с самой свежей версией origin». Закреплено тестом.

Коды возврата: **0** — расхождений нет · **1** — есть находки · **2** — не измерено.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    # Явно, а не через try/except: своя копия правила разбора карточки и есть чинимый дефект
    # (урок #145 — доска потеряла свою копию `resolve_tracker_type` и разошлась с CLI молча).
    # При вызове `python3 scripts/check_tracker_drift.py` корня репо на sys.path нет — капкан,
    # в котором #111 потерял перевод алертов в CI.
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.owner_queue.queue import TRACKER_DIR, load_card_text  # noqa: E402
# Имена полей захвата берём ОТТУДА, ГДЕ ИХ ПИШУТ, а не переписываем сюда: список из двух строк
# кажется безобидным для копии ровно до того дня, когда в захват добавят третье поле, и этот
# сторож молча начнёт считать захваченную карточку «разошедшейся». Проект уже дважды заплатил
# за вторую копию одного правила (#143–#145).
from check_card_claim import _CLAIM_KEYS  # noqa: E402

DEFAULT_REF = "origin/main"
TRACKER_REL = "nimbalyst-local/tracker"

# `_BOARD.md` лежит в том же каталоге, но карточкой не является: это ПРОИЗВОДНЫЙ индекс,
# который регенерируется на каждой мутации из того дерева, где выполнена команда, и потому
# расходится всегда. Считать его карточкой — значит подмешивать вечную находку к настоящим
# и приучать читателя пролистывать вывод сторожа. Его собственный дрейф — отдельная тема
# (карточка `agent-tracker-host-tree-drifts-from-origin`, раздел про доску).
_NOT_CARDS = frozenset({"_BOARD"})

# Классы находок, по возрастанию «насколько это мешает работать».
KIND_STALE = "stale"
KIND_DIVERGED = "diverged"
KIND_HIDDEN = "hidden"
KIND_UNDELIVERED = "undelivered"
KIND_DELETED = "deleted_on_origin"


class Unmeasured(RuntimeError):
    """Сверка не выполнилась. Вердикт — «не измерено» (код 2), а не «расхождений нет»."""


@dataclass
class Finding:
    kind: str
    card_id: str
    detail: str = ""
    tree_status: str = ""
    origin_status: str = ""
    tracker_type: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "card_id": self.card_id,
            "detail": self.detail,
            "tree_status": self.tree_status,
            "origin_status": self.origin_status,
            "tracker_type": self.tracker_type,
        }


@dataclass
class Report:
    ref: str
    ref_sha: str
    tracker_dir: str
    tree_count: int
    origin_count: int
    findings: list[Finding] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[Finding]:
        return [f for f in self.findings if f.kind == kind]

    @property
    def stale_ids(self) -> set[str]:
        return {f.card_id for f in self.of_kind(KIND_STALE)}

    def as_dict(self) -> dict:
        return {
            "ref": self.ref,
            "ref_sha": self.ref_sha,
            "tracker_dir": self.tracker_dir,
            "tree_count": self.tree_count,
            "origin_count": self.origin_count,
            "findings": [f.as_dict() for f in self.findings],
        }


def _git(root: Path, args: list[str], stdin_text: str | None = None) -> tuple[int, str]:
    try:
        res = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=120,
            input=stdin_text,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # git отсутствует / упал
        raise Unmeasured(f"git не выполнился ({' '.join(args[:2])}): {exc}") from exc
    return res.returncode, res.stdout


def repo_root_of(path: Path) -> Path:
    """Корень рабочего дерева, которому принадлежит путь. Не измерилось ⇒ Unmeasured."""
    rc, out = _git(path if path.is_dir() else path.parent, ["rev-parse", "--show-toplevel"])
    if rc != 0 or not out.strip():
        raise Unmeasured(f"путь не принадлежит git-репозиторию: {path}")
    return Path(out.strip())


def blob_sha(data: bytes) -> str:
    """git-совместимый sha1 blob'а — считаем сами, без процесса на каждый файл."""
    header = b"blob %d\0" % len(data)
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 — формат git, не криптография


def origin_snapshot(root: Path, ref: str, tracker_rel: str = TRACKER_REL) -> dict[str, str]:
    """{card_id: blob_sha} для `*.md` каталога трекера на ref. Нет ref ⇒ Unmeasured."""
    rc, _ = _git(root, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    if rc != 0:
        raise Unmeasured(f"ref `{ref}` в этом репозитории не разрешается — сверять не с чем")
    rc, out = _git(root, ["ls-tree", "-r", ref, "--", tracker_rel])
    if rc != 0:
        raise Unmeasured(f"`git ls-tree {ref} -- {tracker_rel}` вернул код {rc}")
    snapshot: dict[str, str] = {}
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 3 or parts[1] != "blob" or not path.endswith(".md"):
            continue
        stem = Path(path).stem
        if stem in _NOT_CARDS:
            continue
        snapshot[stem] = parts[2]
    return snapshot


def tree_snapshot(tracker_dir: Path) -> dict[str, tuple[Path, str]]:
    """{card_id: (path, blob_sha)} для карточек рабочего дерева. Нет каталога ⇒ Unmeasured."""
    if not tracker_dir.is_dir():
        raise Unmeasured(f"каталог трекера не существует или не каталог: {tracker_dir}")
    out: dict[str, tuple[Path, str]] = {}
    for p in sorted(tracker_dir.glob("*.md")):
        if p.stem in _NOT_CARDS:
            continue
        try:
            data = p.read_bytes()
        except OSError as exc:
            raise Unmeasured(f"карточка нечитаема: {p} ({exc})") from exc
        out[p.stem] = (p, blob_sha(data))
    return out


def historical_blobs(root: Path, rel_path: str, ref: str) -> set[str]:
    """Все версии blob'а этого ПУТИ в истории ref. Пусто = путь на ref не жил никогда."""
    rc, out = _git(root, ["rev-list", ref, "--", rel_path])
    if rc != 0:
        raise Unmeasured(f"`git rev-list {ref} -- {rel_path}` вернул код {rc}")
    commits = out.split()
    if not commits:
        return set()
    probe = "".join(f"{c}:{rel_path}\n" for c in commits)
    rc, out = _git(root, ["cat-file", "--batch-check=%(objectname) %(objecttype)"], stdin_text=probe)
    if rc != 0:
        raise Unmeasured(f"`git cat-file --batch-check` вернул код {rc}")
    shas: set[str] = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == "blob":
            shas.add(parts[0])
    return shas


# Сколько версий пути смотреть при сверке «с точностью до захвата». Не безлимит: у карточки
# с длинной историей это N процессов git на карточку. Упёрлись в потолок — вердикт остаётся
# `diverged` (не «совпало»), и причина названа: недоказанное не выдаётся за доказанное.
_HISTORY_PROBE_CAP = 40


def strip_claim_keys(text: str) -> str:
    """Убрать из frontmatter строки захвата (`claimed_by`/`claimed_at`).

    Захват — СЕССИОННАЯ пометка рабочего дерева (её пишет `check_card_claim.py claim`), а не
    содержание карточки. Без этой нормализации любая взятая карточка становится «разошедшейся»
    навсегда: её файл в дереве по построению отличается от origin, и доказать устаревание по
    сырому blob'у уже нельзя. Измерено #147: три из пяти карточек, закрытых на origin, очередь
    продолжала выдавать как `new` именно поэтому.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    out, in_fm = [lines[0]], True
    for raw in lines[1:]:
        if in_fm and raw.strip() == "---":
            in_fm = False
            out.append(raw)
            continue
        if in_fm and not raw[:1].isspace():
            key = raw.partition(":")[0].strip()
            if key in _CLAIM_KEYS:
                continue  # только ВЕРХНЕУРОВНЕВЫЕ ключи: вложенный блок не трогаем
        out.append(raw)
    return "".join(out)


def historical_texts(root: Path, rel_path: str, ref: str) -> tuple[list[str], bool]:
    """Тексты версий пути на ref (новые первыми) + флаг «упёрлись в потолок»."""
    rc, out = _git(root, ["rev-list", ref, "--", rel_path])
    if rc != 0:
        raise Unmeasured(f"`git rev-list {ref} -- {rel_path}` вернул код {rc}")
    commits = out.split()
    capped = len(commits) > _HISTORY_PROBE_CAP
    texts = []
    for commit in commits[:_HISTORY_PROBE_CAP]:
        rc, text = _git(root, ["show", f"{commit}:{rel_path}"])
        if rc == 0:
            texts.append(text)
    return texts, capped


def read_origin_card(root: Path, ref: str, rel_path: str):
    """Карточка в версии ref — тем же единственным парсером, что и файл на диске."""
    rc, out = _git(root, ["show", f"{ref}:{rel_path}"])
    if rc != 0:
        raise Unmeasured(f"`git show {ref}:{rel_path}` вернул код {rc}")
    return load_card_text(out, Path(rel_path).name)


def analyze(tracker_dir: Path | None = None, ref: str = DEFAULT_REF) -> Report:
    """Сверить трекер рабочего дерева с ref. Любая неизмеримость — Unmeasured, не «ок»."""
    tracker_dir = Path(tracker_dir) if tracker_dir is not None else Path(TRACKER_DIR)
    root = repo_root_of(tracker_dir)
    try:
        tracker_rel = tracker_dir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise Unmeasured(f"каталог трекера вне своего репозитория: {tracker_dir}") from exc

    rc, sha_out = _git(root, ["rev-parse", ref])
    ref_sha = sha_out.strip() if rc == 0 else ""

    origin = origin_snapshot(root, ref, tracker_rel)
    tree = tree_snapshot(tracker_dir)
    report = Report(ref=ref, ref_sha=ref_sha, tracker_dir=str(tracker_dir),
                    tree_count=len(tree), origin_count=len(origin))

    for card_id in sorted(set(tree) | set(origin)):
        rel_path = f"{tracker_rel}/{card_id}.md"
        in_tree, in_origin = card_id in tree, card_id in origin

        if in_origin and not in_tree:
            card = read_origin_card(root, ref, rel_path)
            report.findings.append(Finding(
                kind=KIND_HIDDEN, card_id=card_id,
                detail=f"есть на {ref}, в дереве файла нет — задание невидимо этому дереву",
                origin_status=card.status, tracker_type=card.tracker_type))
            continue

        path, tree_sha = tree[card_id]
        tree_card = load_card_text(path.read_text(encoding="utf-8"), path.name)

        if not in_origin:
            history = historical_blobs(root, rel_path, ref)
            if history:
                report.findings.append(Finding(
                    kind=KIND_DELETED, card_id=card_id,
                    detail=f"в дереве есть, на {ref} УДАЛЕНА (путь в истории ref жил)",
                    tree_status=tree_card.status, tracker_type=tree_card.tracker_type))
            else:
                report.findings.append(Finding(
                    kind=KIND_UNDELIVERED, card_id=card_id,
                    detail=f"есть в дереве, на {ref} нет — карточка не доставлена",
                    tree_status=tree_card.status, tracker_type=tree_card.tracker_type))
            continue

        if tree_sha == origin[card_id]:
            continue  # совпадает байт-в-байт — не находка

        origin_card = read_origin_card(root, ref, rel_path)
        proven, why = _proven_behind(root, rel_path, ref, path, tree_sha)
        if proven:
            report.findings.append(Finding(
                kind=KIND_STALE, card_id=card_id, detail=why,
                tree_status=tree_card.status, origin_status=origin_card.status,
                tracker_type=origin_card.tracker_type))
        else:
            report.findings.append(Finding(
                kind=KIND_DIVERGED, card_id=card_id, detail=why,
                tree_status=tree_card.status, origin_status=origin_card.status,
                tracker_type=origin_card.tracker_type))
    return report


def _proven_behind(root: Path, rel_path: str, ref: str, path: Path,
                   tree_sha: str) -> tuple[bool, str]:
    """Доказано ли, что копия дерева — ПРЕЖНЯЯ версия этого же пути на ref.

    Две ступени, обе доказательные, ни одна не «похоже старее»:
    1) сырой blob дерева найден среди версий пути на ref;
    2) он же найден ПОСЛЕ снятия сессионных полей захвата с обеих сторон.

    Не доказано — так и говорим (`diverged`), а не выбираем сторону молча.
    """
    if tree_sha in historical_blobs(root, rel_path, ref):
        return True, (f"содержимое дерева найдено в истории {ref} для этого пути ⇒ дерево "
                      f"строго ОТСТАЁТ, авторитетен {ref}")
    texts, capped = historical_texts(root, rel_path, ref)
    tree_norm = strip_claim_keys(path.read_text(encoding="utf-8"))
    for text in texts:
        if strip_claim_keys(text) == tree_norm:
            return True, (f"содержимое дерева совпало с версией из истории {ref} С ТОЧНОСТЬЮ ДО "
                          f"полей захвата ({', '.join(_CLAIM_KEYS)}) ⇒ дерево строго ОТСТАЁТ, "
                          f"а отличие — сессионная пометка, не содержание карточки")
    tail = (f"; просмотрены только {_HISTORY_PROBE_CAP} последних версий пути — потолок зонда, "
            f"глубже НЕ измерено") if capped else ""
    return False, (f"содержимого дерева НЕТ в истории {ref} даже без полей захвата ⇒ у дерева "
                   f"своя правка; кто новее — не измерено, нужна ручная сверка{tail}")


_KIND_TITLE = {
    KIND_STALE: "УСТАРЕЛИ в дереве (origin строго новее — очередь показывает вчерашний день)",
    KIND_HIDDEN: "НЕВИДИМЫ этому дереву (есть на origin, файла нет)",
    KIND_UNDELIVERED: "НЕ ДОСТАВЛЕНЫ (есть в дереве, на origin нет)",
    KIND_DIVERGED: "РАЗОШЛИСЬ (у дерева своя правка — судить нельзя, сверять руками)",
    KIND_DELETED: "УДАЛЕНЫ на origin (в дереве ещё лежат)",
}


def format_report(report: Report) -> str:
    head = (f"Сверка трекера с {report.ref} ({report.ref_sha[:9] or '?'}); "
            f"карточек в дереве: {report.tree_count}, на {report.ref}: {report.origin_count}; "
            f"каталог: {report.tracker_dir}")
    if not report.findings:
        return head + "\n✅ расхождений нет."
    lines = [head]
    for kind in (KIND_STALE, KIND_HIDDEN, KIND_UNDELIVERED, KIND_DIVERGED, KIND_DELETED):
        group = report.of_kind(kind)
        if not group:
            continue
        lines.append(f"\n⚠️  {_KIND_TITLE[kind]} ({len(group)}):")
        for f in group:
            status = ""
            if f.tree_status or f.origin_status:
                status = f" [дерево: {f.tree_status or '—'} · {report.ref}: {f.origin_status or '—'}]"
            lines.append(f"  - {f.card_id}{status}")
            lines.append(f"      {f.detail}")
    lines.append("\nЭто находки, а не декорация: очередь этого дерева отвечает не на тот вопрос.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tracker-dir", default=None,
                    help="каталог трекера (по умолчанию — трекер дерева этой копии скрипта)")
    ap.add_argument("--ref", default=DEFAULT_REF, help=f"с чем сверять (по умолчанию {DEFAULT_REF})")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    try:
        report = analyze(args.tracker_dir, args.ref)
    except Unmeasured as exc:
        if args.json:
            print(json.dumps({"verdict": "unmeasured", "reason": str(exc)}, ensure_ascii=False))
        else:
            print(f"❓ НЕ ИЗМЕРЕНО — {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    return 1 if report.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
