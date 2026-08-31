#!/usr/bin/env python3
# LLM_FORBIDDEN
"""scripts/check_owner_choice_authorship.py — ЗАПИСЬ ответа владельца закрыта на двери доставки.

**Зачем (цикл #437 → #439, карточка `inbox-agent-mozhet-napisat-owner-choice-otvet`).**
Поле ``owner_choice`` в карточке решения — это ЗАПИСЬ ОТВЕТА ВЛАДЕЛЬЦА. Написать в него
до сих пор мог кто угодно, и один раз это уже случилось. ``git show 765363a8e``
(2026-08-29 14:41Z): карточка ``owner-decision-tier-steakhouse-2026-08-29`` была
``needs-owner`` с ``owner_choice: ""`` — владелец ещё не отвечал, — и сессия одним
коммитом поставила ``status: ingested`` и ``owner_choice: "2"``. Проза того же коммита
говорит обратное («Выбран вариант 1… Вариант 2 — НЕ сделан»). Владелец ответил на
6 ч 20 мин ПОЗЖЕ, кнопкой, и ответил **1**.

Цена заплачена не один раз: обязательный шаг 0-офис несколько прогонов подряд печатал
«⛔ ДВА РАЗНЫХ ОТВЕТА ВЛАДЕЛЬЦА, нужен человек» на состоянии, где ответ владельца ОДИН.
ADR-186 научил СТОРОЖА отличать безымянную запись от ответа. Здесь закрывается вторая
половина: ПИСАТЕЛЬ.

**ПОЧЕМУ ДВЕРЬ ИМЕННО ЗДЕСЬ — двери посчитаны, а не выбраны на глаз.**
Замер по всему рантайму (цикл #439, ``grep owner_choice`` по ``spa_core/`` и ``scripts/``
минус тесты): единственный код, ПИШУЩИЙ поле, — ``spa_core/owner_queue/owner_answer.py``
(``record_owner_answer`` и перенос следа); все остальные упоминания — ЧТЕНИЕ
(``findings_bridge``, ``card_delivery``, ``owner_answer_delivery``, ``orchestrator_queue``).
``queue.set_status`` переписывает ровно строку ``status:``, ``create_card`` рождает
карточку с ``owner_choice: ""``. То есть заслон на ``set_status`` был бы сторожем у двери,
которой никто не пользовался, — украшением.

Авария прошла ЧЕРЕЗ ПУШ: файл поправлен руками, доставлен ``push_to_github``. Поэтому
проверка стоит на двери доставки — единственной, через которую ручная правка попадает
на origin, — и зовётся ОДНОЙ реализацией из ОБОИХ CLI (``push_to_github.py`` и
``push_to_github_batch.py``): урок ADR-номеров, где вторая дверь пропускала столкновения.

**ЧТО ИМЕННО СЧИТАЕТСЯ НАХОДКОЙ.** Уезжающая карточка несёт НЕПУСТОЙ ``owner_choice``,
который отличается от значения на ``origin/main`` (или там его нет вовсе), И в уезжающем
файле НЕТ НИ ОДНОГО признака авторства — ни поля провенанса, ни отметки штатного писателя
в ``status_trail``. Признаки читаются ``owner_answer_delivery.attribution_keys`` —
ИМПОРТОМ, не второй копией имён (урок #47).

**Замер по всей популяции ДО написания правила (цикл #439).** ``origin/main`` e49641f0e:
карточек 845, с непустым ``owner_choice`` — 88, изменённых против origin — **0**
(правило не краснит ни на чём уже доставленном). Прод-дерево: карточек 572, непустой
``owner_choice`` — 73, изменённых против origin — **2**, и ОБЕ несут полный провенанс
кнопки ⇒ проходят. На блобе аварии 765363a8e правило ОТКАЗЫВАЕТ. То есть: одно истинное
красное, ноль ложных на 1417 карточках.

**Граница названа честно.** Гейт КООПЕРАТИВНЫЙ, как owner-gate сайта: тот, кто вместе с
``owner_choice`` подделает и поля провенанса, пройдёт. Это уже не «поставил статус за
владельца», а подпись его именем — другой по громкости поступок, и ловить его следовало
бы иначе. Планка выбрана ЗАМЕРОМ (ноль ложных на живой популяции), а не на глаз.

**Третий исход обязателен.** Прочитать ``origin/main`` не удалось ⇒ код 2 «НЕ ИЗМЕРЕНО»,
и это ОТКАЗ, а не «чисто»: молчаливое «претензий нет» на слепом сторо́же — ровно тот
класс, ради которого файл написан.

Коды возврата: **0** — находок нет · **1** — находка · **2** — не измерено (fail-CLOSED).
stdlib-only, детерминирован, сети не трогает (читает ``git show origin/main:<путь>``).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring.owner_answer_delivery import (  # noqa: E402
    PROVENANCE_FIELDS, attribution_keys, same_scalar, _read_fields,
)

#: Каталог, в котором живут карточки. Отбор — ТРИГГЕР: пуш без карточек проверку не будит.
TRACKER_DIR = "nimbalyst-local/tracker/"

#: Доска — авто-индекс, а не карточка: у неё нет frontmatter решения и судить в ней нечего.
NOT_A_CARD = {"_BOARD.md"}

CLEAN, FINDING, UNMEASURED = 0, 1, 2


def is_card(path: str) -> bool:
    """Путь доставки — карточка трекера? Отбор объявленный, а не угаданный по имени."""
    norm = str(path).replace("\\", "/")
    if TRACKER_DIR not in norm or not norm.endswith(".md"):
        return False
    return os.path.basename(norm) not in NOT_A_CARD


def repo_path_of(path: str) -> str:
    """Путь внутри репозитория (``nimbalyst-local/tracker/<имя>.md``) из любого пути доставки."""
    norm = str(path).replace("\\", "/")
    return TRACKER_DIR + norm.split(TRACKER_DIR, 1)[1]


def choice_of(blob: bytes | None):
    """``owner_choice`` копии, либо ``None``.

    Пустой скаляр (``owner_choice: ""``) читается как ОТСУТСТВИЕ ответа — тем же кодом,
    что и у сторожа доставки: «ответа нет» и «ответ пустой» — разные вещи (ADR-176).
    """
    if blob is None:
        return None
    return _read_fields(blob, ("owner_choice",)).get("owner_choice")


def origin_blob(repo_path: str, root: Path, ref: str = "origin/main"):
    """``(bytes|None, измерено?)`` — версия пути на origin.

    Три исхода, а не два: файл есть · файла на origin НЕТ (новая карточка — это
    измерение, а не слепота) · git не ответил вовсе (слепота, код 2).
    """
    proc = subprocess.run(["git", "show", f"{ref}:{repo_path}"],
                          capture_output=True, cwd=str(root))
    if proc.returncode == 0:
        return proc.stdout, True
    err = (proc.stderr or b"").decode("utf-8", "replace")
    # «path does not exist» / «exists on disk, but not in» — карточки на origin нет.
    if "does not exist" in err or "exists on disk" in err:
        return None, True
    return None, False


def verdict(local: bytes, remote: bytes | None) -> tuple[str, str]:
    """``(исход, причина)`` для ОДНОЙ карточки. Чистая функция — её и красят мутации."""
    ours = choice_of(local)
    if ours is None:
        return "ok", "уезжающая копия ответа владельца не несёт — судить нечего"
    theirs = choice_of(remote)
    if theirs is not None and same_scalar(str(theirs), str(ours)):
        return "ok", f"owner_choice не меняется ({ours!r}) — записи ответа в этом пуше нет"
    attrib = attribution_keys(local)
    if attrib:
        return "ok", (f"owner_choice {theirs!r} → {ours!r} подписан: "
                      f"{', '.join(sorted(attrib))}")
    return "finding", (
        f"уезжающая карточка ставит owner_choice={ours!r} "
        f"(на origin {theirs!r}) БЕЗ ЕДИНОГО признака авторства — ни "
        f"{', '.join(PROVENANCE_FIELDS)}, ни отметки штатного писателя в status_trail. "
        f"Ответ владельца пишет ТОЛЬКО он сам (кнопка → "
        f"owner_answer.record_owner_answer); агент, пишущий это поле, подделывает ответ "
        f"владельца — так 2026-08-29 родился коммит 765363a8e")


def check(files, root: Path, ref: str = "origin/main") -> dict:
    """Разобрать набор доставки. Возвращает отчёт; решение о коде принимает :func:`main`."""
    cards = [f for f in files if is_card(f)]
    findings, ok, blind = [], [], []
    for f in cards:
        rel = repo_path_of(f)
        p = Path(f)
        if not p.is_file():
            blind.append((rel, "файла нет на диске — уезжающую копию прочитать нечем"))
            continue
        remote, measured = origin_blob(rel, root, ref)
        if not measured:
            blind.append((rel, f"версию {ref} прочитать не удалось — сравнивать не с чем"))
            continue
        kind, why = verdict(p.read_bytes(), remote)
        (findings if kind == "finding" else ok).append((rel, why))
    return {"cards": len(cards), "findings": findings, "ok": ok, "blind": blind}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", nargs="*", default=[], help="весь набор доставки")
    ap.add_argument("--root", default=str(_REPO_ROOT), help="дерево, чей origin/main судим")
    ap.add_argument("--ref", default="origin/main")
    args = ap.parse_args(argv)

    report = check(args.files, Path(args.root), args.ref)
    if not report["cards"]:
        print("owner_choice: карточек в наборе нет — проверке нечего сказать")
        return CLEAN

    for rel, why in report["ok"]:
        print(f"  ✅ {rel}: {why}")
    for rel, why in report["blind"]:
        print(f"  ⚠️  НЕ ИЗМЕРЕНО {rel}: {why}", file=sys.stderr)
    for rel, why in report["findings"]:
        print(f"  ⛔ {rel}: {why}", file=sys.stderr)

    if report["findings"]:
        print(f"ОТКАЗ (запись ответа владельца): находок {len(report['findings'])} "
              f"из {report['cards']} карточк(и) набора", file=sys.stderr)
        return FINDING
    if report["blind"]:
        print(f"ОТКАЗ (не измерено): {len(report['blind'])} карточк(и) набора судить "
              f"нечем — fail-CLOSED, слепое «претензий нет» здесь и есть дефект",
              file=sys.stderr)
        return UNMEASURED
    print(f"owner_choice: {report['cards']} карточк(и) набора — подделанной записи "
          f"ответа владельца нет")
    return CLEAN


if __name__ == "__main__":
    sys.exit(main())
