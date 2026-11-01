"""Закрытая просьба владельца, в которой ответа «не записано ничем» (ADR-885, цикл #1000).

Предмет — ОДИН вопрос, оставленный ADR-863 открытым (его раздел «Чего это НЕ закрывает»,
п. 2) и выписанный заказом G882 п. 9(б): перепись канала ответа говорила, что у **55 из
75** закрытых заданий владельца ответа не записано НИЧЕМ, и выдавала это число за
однородное. Карточка `inbox-pyatdesyat-pyat-zakrytyh-prosb-vladeltsa` перечислила три
взаимно исключающих объяснения, требующих РАЗНЫХ действий:

1. задание было мусором или дублем — закрывать нечего, и это нормально;
2. ответ был, но лёг не в карточку, а в журнал цикла или в ADR — карточка потеряла ссылку;
3. задание закрыли, не сделав, — это долг перед владельцем.

Сегодня эти три неотличимы. Этот модуль их РАЗЛИЧАЕТ замером и называет третью группу
поимённо.

## Что замер нашёл, и почему вопрос оказался не тем

Первое же разложение (01.11, живая очередь, 74 закрытых задания владельца) показало, что
**само число не про очередь, а про ЧИТАТЕЛЯ**: из 50, про которые перепись говорила
«ответа не записано ничем», **47** несут в теле раздел работы — «Что сделано», «Разбор»,
«Резолюция», «Исполнено», «Обработано», «Закрыто как дубль якорной задачи». Ответ лежал
В КАРТОЧКЕ. Его не видел словарь заголовков, которым ADR-863 спрашивал «есть ли ответ»
(``ОТВЕТ|ОТВЕЧАЮ|ЗАМЕР|РЕЗУЛЬТАТ|РАЗОБРАНО``): формулировки цикла в него не попадали.

Поэтому объяснение 2 в его исходном виде («ответ лёг НЕ в карточку») на этом населении
**опровергнуто**, а словарь заменён СТРУКТУРНЫМ вопросом
(:func:`spa_core.owner_queue.answer_channel.work_sections`) — «есть ли в теле хоть один
раздел, которого приём не писал». Расширять словарь было нельзя: он и есть лазейка,
следующая формулировка снова оказалась бы вне списка, причём молча.

## Ось этого модуля — ГДЕ лежит след работы, и у неё четыре значения

* :data:`RECORD_IN_BODY` — след в САМОЙ карточке (раздел, которого приём не писал);
* :data:`RECORD_OUTSIDE` — в теле следа нет, но карточку НАЗЫВАЕТ журнал, ADR или другая
  карточка. **Это не «ответ есть».** Упоминание карточки чужим документом ответом
  владельцу не является, и группа существует ровно чтобы сказать это вслух: след есть,
  ответа — не измерено;
* :data:`NO_TRACE` — ни в теле, ни в корпусе. Кандидат в долг, и такие карточки
  **называются поимённо**;
* :data:`UNMEASURED` — карточка не прочитана ЛИБО корпус ссылок не прочитан.

## «Мусор» группой НЕ является — и это решение, а не пропуск

Объяснение 1 («задание было мусором») машиной не решается. Пример владельца — карточки с
заголовком «1», «2»; на живом населении таких **нет ни одной**, а есть «купить зонт в
пятницу» и «Давай так и сделаем»: для машины это обычный текст задания, и отличить
личное поручение от задачи системе она не может. Завести для этого признак по длине
заголовка или по словарю бытовых слов значило бы ВЫДУМАТЬ меру и оправдывать ею закрытые
карточки — ошибка в сторону «всё хорошо».

Поэтому «мусор» остаётся вопросом к человеку, а модуль отдаёт по каждой карточке группы
:data:`NO_TRACE` те ФАКТЫ, которые для этого вопроса нужны (заголовок, длина тела,
есть ли карточка-близнец с тем же заголовком) — и ни одного вердикта о мусоре.
:data:`UNMEASURED` при этом СВОЙ и с «мусором» не смешан (инв. #17): «не прочитали» и
«нечего закрывать» — разные исходы, требующие разных действий.

## Цена односторонняя и названа

* **Корпус ссылок НЕ включает авто-индекс** (`_BOARD.md`): он перечисляет КАЖДУЮ карточку
  по построению, поэтому его упоминание оправдало бы любую. Включить его значило бы
  обнулить группу :data:`NO_TRACE` молча.
* **Корпус не прочитан ⇒ :data:`UNMEASURED`, а не :data:`NO_TRACE`.** Обратный выбор
  обвинял бы цикл в недоделанной работе по причине «у нас не открылся каталог» — ровно
  тот дефект, против которого написан инв. #17.
* **Упоминание не есть ответ** — поэтому :data:`RECORD_OUTSIDE` не складывается с
  :data:`RECORD_IN_BODY` ни в одной сумме этого модуля.
* **Вердикт не сильнее ДЕРЕВА, и дерево обязано быть НАЗВАНО.** Замер 01.11 тем же
  прибором: worktree от `origin/main` даёт ``no_trace`` **0** при корпусе **759**
  файлов, прод-дерево — ``no_trace`` **11** при корпусе **51**, и вердикт расходится у
  **6** карточек из 63 общих, ВСЕГДА в сторону обвинения. Причины измерены и обе
  штатные: прод-копии карточек усечены, а `docs/` в прод-дерево не синхронизируется
  вовсе (ADR-152). Поэтому ответ по этому предмету берётся из git-worktree `origin/main`,
  а отчёт печатает `repo_root` и размер корпуса РЯДОМ с числом — число без дерева здесь
  не является наблюдением.

# LLM_FORBIDDEN — детерминированный учёт, никакого суждения модели (инв. #3).
"""
from __future__ import annotations

import re
from pathlib import Path

from spa_core.owner_queue import answer_channel as ac

#: Где ищется СЛЕД работы вне карточки. Границу рисует НЕ удобство: объяснение 2 самой
#: карточки владельца названо дословно — «ответ был, но лёг не в карточку, а в журнал
#: цикла или в ADR». Поэтому корпус группы — ровно журнал и решения.
CORPUS_GLOBS: tuple[str, ...] = (
    "docs/journal/*.md",
    "docs/decisions/*.md",
)

#: Соседние карточки — ОТДЕЛЬНАЯ ось и НИКОГДА не группа. Замер 01.11 объясняет почему:
#: с карточками в корпусе группа :data:`NO_TRACE` обнуляется (0 из 66), потому что
#: карточку называет то якорный приказ CIO на 31 тысячу строк, то храповик приёмки, то
#: соседняя находка — и ни одно из этих упоминаний ответом владельцу не является.
#: Признак, оправдывающий ВСЁ население, мерит не предмет, а связность трекера; он
#: остаётся ФАКТОМ строки, который читает человек.
NEIGHBOUR_GLOBS: tuple[str, ...] = ("nimbalyst-local/tracker/*.md",)

#: Файлы корпуса, упоминание в которых следом НЕ является. `_BOARD.md` — авто-индекс
#: трекера: он перечисляет каждую карточку по построению (`scripts/build_tracker_board.py`),
#: поэтому его «упоминание» оправдало бы любую карточку и обнулило бы группу долга.
CORPUS_EXCLUDED: frozenset[str] = frozenset({"_BOARD.md"})

#: Имя карточки в тексте. Хвост `.md` необязателен: ссылки в журналах и ADR идут и так и так.
_CARD_TOKEN = re.compile(r"inbox-[a-z0-9][a-z0-9\-]{3,}")

#: Значения оси «где лежит след работы».
RECORD_IN_BODY = "record_in_body"
RECORD_OUTSIDE = "record_outside"
NO_TRACE = "no_trace"
UNMEASURED = "unmeasured"

GROUPS: tuple[str, ...] = (RECORD_IN_BODY, RECORD_OUTSIDE, NO_TRACE, UNMEASURED)


def corpus_references(repo_root, *, globs: tuple[str, ...] = CORPUS_GLOBS) -> tuple[dict[str, list[str]], dict]:
    """Какая карточка НАЗВАНА какими файлами корпуса. Второй элемент — замер чтения.

    Отдаётся не множество, а адреса: «след есть» без адреса проверить нечем, и группа
    :data:`RECORD_OUTSIDE` стала бы утверждением на честном слове.

    Читаемость спрашивается ОТДЕЛЬНЫМ вопросом (урок ``pyflakes`` из
    ``.claude/rules/deployment.md``): пустой результат и непрочитанный корпус — разные
    исходы, и первый нельзя выдавать за второй. Поэтому возвращается ещё и
    ``{"files": N, "failed": M, "dirs_missing": [...]}``, а вердикт о корпусе выносит
    :func:`measure`, а не эта функция.

    Самоссылка не считается: файл, называющий СЕБЯ, следа работы не несёт.
    """
    root = Path(repo_root)
    refs: dict[str, list[str]] = {}
    stat: dict = {"files": 0, "failed": 0, "dirs_missing": [], "excluded": 0}
    for g in globs:
        parent = root / Path(g).parent
        if not parent.is_dir():
            stat["dirs_missing"].append(str(Path(g).parent))
            continue
        for p in sorted(root.glob(g)):
            if p.name in CORPUS_EXCLUDED:
                stat["excluded"] += 1
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="strict")
            except (OSError, ValueError):
                stat["failed"] += 1
                continue
            stat["files"] += 1
            own = p.name[:-3] if p.name.endswith(".md") else p.name
            for token in set(_CARD_TOKEN.findall(text)):
                if token == own:
                    continue
                refs.setdefault(token, []).append(p.name)
    return refs, stat


def classify(card_path, *, refs: dict[str, list[str]] | None,
             body: str | None = None) -> tuple[str, str, list[str]]:
    """Группа ОДНОЙ карточки, причина словами и АДРЕСА следа вне карточки.

    ``refs is None`` означает «корпус ссылок НЕ прочитан»: тогда карточка без следа в
    теле получает :data:`UNMEASURED`, а не :data:`NO_TRACE`. Это и есть граница, за
    которой обвинение стало бы выводом из нашего собственного незнания.
    """
    p = Path(card_path)
    if body is None:
        try:
            body = ac.split_frontmatter(p.read_text(encoding="utf-8"))[1]
        except OSError as exc:
            return UNMEASURED, f"карточка не прочитана ({exc.__class__.__name__}) — НЕ ИЗМЕРЕНО", []
    sections = ac.work_sections(body)
    if sections:
        return RECORD_IN_BODY, f"след работы в самой карточке: раздел «{sections[0]}»", []
    if refs is None:
        return UNMEASURED, ("в теле следа работы нет, а корпус ссылок НЕ ПРОЧИТАН — "
                            "НЕ ИЗМЕРЕНО, а не «следа нет»"), []
    stem = p.name[:-3] if p.name.endswith(".md") else p.name
    where = sorted(set(refs.get(stem, []) + refs.get(p.name, [])))
    if where:
        return RECORD_OUTSIDE, ("в теле следа работы нет; карточку называет журнал/ADR — "
                                "это СЛЕД, но не ответ владельцу"), where
    return NO_TRACE, "следа работы нет ни в теле, ни в журнале, ни в ADR — кандидат в долг", []


def measure(tracker_dir, *, repo_root=None, globs: tuple[str, ...] = CORPUS_GLOBS) -> dict:
    """Разложить закрытые задания владельца БЕЗ записанного ответа по оси следа.

    Население ОБЪЯВЛЕНО: закрытое задание владельца, у которого нет СИЛЬНОГО основания
    ответа — ни пробы (``verified_by_probe``), ни адреса, куда ответ уехал
    (``carried_to``). Это ровно те карточки, про которые вопрос «был ли ответ» ЖИВОЙ;
    у остальных он уже отвечен полем frontmatter, и мерить там нечего.

    Спрашивается оно у того же ``answer_evidence``, но С ПУСТЫМ ТЕЛОМ — то есть у
    единственного читателя оснований задаётся именно вопрос «есть ли основание ПОМИМО
    тела». Своей редакции списка сильных оснований здесь нет намеренно: две копии этого
    знания разошлись бы молча, и число стало бы зависеть от того, какой читатель спросил.

    ``repo_root`` — корень, в котором лежит корпус; по умолчанию берётся дерево, в
    котором лежит сам каталог трекера (его родитель на два уровня вверх).
    """
    d = Path(tracker_dir)
    root = Path(repo_root) if repo_root is not None else d.parent.parent
    counts = {g: 0 for g in GROUPS}
    rows: list[dict] = []
    if not d.is_dir():
        return {"tracker_dir": str(d), "repo_root": str(root), "population": None,
                "counts": counts, "rows": rows, "corpus": None,
                "unmeasured_reason": f"каталога трекера нет: {d}"}

    refs, cstat = corpus_references(root, globs=globs)
    corpus_read = cstat["files"] > 0
    if not corpus_read:
        refs_or_none = None
        corpus_reason = (f"корпус ссылок НЕ ПРОЧИТАН: файлов прочитано 0 "
                         f"(не открылось {cstat['failed']}, нет каталогов "
                         f"{cstat['dirs_missing'] or '—'})")
    else:
        refs_or_none = refs
        corpus_reason = None
    # Соседние карточки — ФАКТ строки, не группа (см. NEIGHBOUR_GLOBS).
    neighbours, nstat = corpus_references(root, globs=NEIGHBOUR_GLOBS)

    for p in sorted(d.glob("inbox-*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            # Карточку населения не отбрасываем молча: не прочитанная карточка — свой
            # третий исход, а не «её нет».
            counts[UNMEASURED] += 1
            rows.append({"card": p.name, "group": UNMEASURED, "title": "",
                         "body_chars": None, "twin_title": None, "named_by": [],
                         "named_by_neighbour": [],
                         "reason": f"карточка не прочитана ({exc.__class__.__name__})"})
            continue
        fm, body = ac.split_frontmatter(text)
        if not (ac.is_owner_task(fm) and ac.is_closed(fm)):
            continue
        if ac.answer_evidence(fm, "") is not None:
            continue
        group, why, where = classify(p, refs=refs_or_none, body=body)
        stem = p.name[:-3]
        counts[group] += 1
        rows.append({"card": p.name, "group": group,
                     "title": str(fm.get("title") or ""),
                     "body_chars": len(body.strip()),
                     "twin_title": None, "named_by": where,
                     "named_by_neighbour": sorted(set(neighbours.get(stem, [])
                                                      + neighbours.get(p.name, []))),
                     "reason": why})

    # Близнец по ЗАГОЛОВКУ — ФАКТ для человека, а не вердикт «мусор». Считается только
    # внутри населения: «такой же заголовок есть у открытой карточки» — другой вопрос.
    by_title: dict[str, list[str]] = {}
    for r in rows:
        t = (r["title"] or "").strip().lower()
        if t:
            by_title.setdefault(t, []).append(r["card"])
    for r in rows:
        t = (r["title"] or "").strip().lower()
        same = [c for c in by_title.get(t, []) if c != r["card"]]
        r["twin_title"] = same or None

    return {"tracker_dir": str(d), "repo_root": str(root),
            "population": sum(counts.values()), "counts": counts, "rows": rows,
            "corpus": {**cstat, "read": corpus_read, "references": len(refs)},
            "neighbours": {**nstat, "references": len(neighbours)},
            "unmeasured_reason": corpus_reason}


def needs_human_judgement(report: dict) -> list[dict]:
    """Карточки, у которых следа работы В КАРТОЧКЕ НЕТ, — ПОИМЁННО (заказ G882 п. 9(б)).

    Это :data:`NO_TRACE` и :data:`RECORD_OUTSIDE` вместе, и склейка здесь НАМЕРЕННАЯ:
    обе группы отвечают «в карточке ответа нет», а различает их лишь сила постороннего
    следа — упоминание в журнале или ADR ответом владельцу не является. Вердикта «долг»
    у модуля нет: «мусор» и «долг» машиной не различаются (см. docstring модуля),
    поэтому отдаются ФАКТЫ для человека, а не приговор.
    """
    return [r for r in (report.get("rows") or [])
            if r.get("group") in (NO_TRACE, RECORD_OUTSIDE)]


# ── эталон класса: сцены, отличающиеся РОВНО одним ───────────────────────────────────
DRIVE_CONFLATES, DRIVE_UNMEASURED, DRIVE_DISTINGUISHES = (
    "conflates", "unmeasured", "distinguishes")


def drive_exemplar() -> dict:
    """Поднять НАСТОЯЩИЙ :func:`measure` на одноразовом дереве из четырёх сцен.

    Сцены отличаются РОВНО одним наблюдением каждая, поэтому разный исход приписать
    нечему, кроме предмета:

    * ``body_record`` — в теле есть раздел, которого приём не писал;
    * ``outside`` — тела нет, но карточку называет журнал;
    * ``no_trace`` — не называет никто;
    * и то же дерево БЕЗ корпуса: ``no_trace`` обязан стать :data:`UNMEASURED`, а не
      остаться обвинением.

    Четвёртая сцена — несущая. Мера, которая при непрочитанном корпусе объявляет «следа
    нет», выводит обвинение из своего незнания; это тот же класс, что `pyflakes`,
    отвечающий нулём на отсутствие инструмента.
    """
    import shutil
    import tempfile

    tpl = ("---\ntrackerStatus:\n  type: inbox\ntitle: {title}\nstatus: done\n"
           "source: voice\n---\n\n## Задание (из Telegram)\n\nсделай штуку\n{tail}")
    scenes = {
        "body_record": ("следом в теле", "\n## Что сделано (цикл #1)\n\nсделано\n"),
        "outside": ("следом в журнале", ""),
        "no_trace": ("без следа", ""),
    }
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tr = root / "nimbalyst-local" / "tracker"
            jr = root / "docs" / "journal"
            tr.mkdir(parents=True)
            jr.mkdir(parents=True)
            for name, (title, tail) in scenes.items():
                (tr / f"inbox-{name}.md").write_text(
                    tpl.format(title=title, tail=tail), encoding="utf-8")
            # Авто-индекс называет ВСЕ карточки — и обязан быть исключён, иначе
            # `no_trace` оправдался бы сам.
            (tr / "_BOARD.md").write_text(
                "\n".join(f"- inbox-{n}" for n in scenes), encoding="utf-8")
            (jr / "2026-W01.md").write_text(
                "ответ по inbox-outside лёг сюда\n", encoding="utf-8")

            with_corpus = measure(tr, repo_root=root)
            shutil.rmtree(jr)
            shutil.rmtree(root / "docs")
            # Корпуса не осталось ВОВСЕ: каталог трекера исключён из корпуса для этой
            # сцены, иначе соседние карточки сами стали бы корпусом.
            without = measure(tr, repo_root=root, globs=("docs/journal/*.md",))
    except Exception as exc:  # noqa: BLE001
        return {"kind": DRIVE_UNMEASURED,
                "reason": f"сцену не удалось собрать: {type(exc).__name__}: {exc}"}

    got = {r["card"]: r["group"] for r in with_corpus["rows"]}
    blind = {r["card"]: r["group"] for r in without["rows"]}
    out = {"with_corpus": got, "without_corpus": blind,
           "counts": with_corpus["counts"],
           "corpus": with_corpus["corpus"],
           "unmeasured_reason": without["unmeasured_reason"]}
    expected = {"inbox-body_record.md": RECORD_IN_BODY,
                "inbox-outside.md": RECORD_OUTSIDE,
                "inbox-no_trace.md": NO_TRACE}
    blind_ok = (blind.get("inbox-no_trace.md") == UNMEASURED
                and blind.get("inbox-outside.md") == UNMEASURED
                and blind.get("inbox-body_record.md") == RECORD_IN_BODY)
    out["kind"] = (DRIVE_DISTINGUISHES if got == expected and blind_ok
                   else DRIVE_CONFLATES)
    return out


def main(argv=None) -> int:
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--tracker-dir", default=None)
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.tracker_dir is not None:
        tr = Path(a.tracker_dir)
    else:
        from spa_core.owner_queue import queue as q
        tr = Path(q.TRACKER_DIR)
    rep = measure(tr, repo_root=a.repo_root)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if rep["unmeasured_reason"] is None else 2

    if rep["population"] is None:
        print(f"НЕ ИЗМЕРЕНО: {rep['unmeasured_reason']}", file=sys.stderr)
        return 2
    c = rep["counts"]
    print(f"Закрытые задания владельца БЕЗ записанного ответа: {rep['population']} "
          f"(трекер {rep['tracker_dir']})")
    print(f"  след в самой карточке        {c[RECORD_IN_BODY]}")
    print(f"  след только в журнале/ADR    {c[RECORD_OUTSIDE]}  (упоминание — НЕ ответ)")
    print(f"  следа нет нигде              {c[NO_TRACE]}")
    print(f"  НЕ ИЗМЕРЕНО                  {c[UNMEASURED]}")
    print(f"  корпус: журнал+ADR {rep['corpus']['files']} файл(ов), названо карточек "
          f"{rep['corpus']['references']} · соседние карточки — ОТДЕЛЬНАЯ ось, не группа "
          f"({rep['neighbours']['files']} файл(ов))")
    if rep["unmeasured_reason"]:
        print(f"  ⚠️ {rep['unmeasured_reason']}")
    for r in needs_human_judgement(rep):
        twin = f" · близнец по заголовку: {', '.join(r['twin_title'])}" if r["twin_title"] else ""
        where = f" · назван: {', '.join(r['named_by'][:3])}" if r["named_by"] else ""
        nb = (f" · соседние карточки: {len(r['named_by_neighbour'])}"
              if r["named_by_neighbour"] else "")
        print(f"    [{r['group']}] {r['card']} — «{r['title']}», тело {r['body_chars']} "
              f"симв.{twin}{where}{nb}")
    print("  «мусор» группой НЕ является: машиной не решается — модуль отдаёт факты, "
          "а не вердикт (docstring модуля)")
    return 0 if rep["unmeasured_reason"] is None else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
