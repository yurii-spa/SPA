"""Чем ОБЪЯСНЯЕТСЯ локальная копия файла: её ли это база, или база другая.

Страж перезаписи (`push_to_github.guard_overwrite`) берёт базу из `HEAD:<путь>`
и на этом строит своё главное утверждение — «всё, чего нет в нашей копии, автор
видел и убрал сам». Утверждение верно ровно тогда, когда рабочая копия ПРИШЛА
из HEAD. `git reset --mixed origin/main` двигает HEAD и индекс, **не трогая
рабочее дерево**: после него база говорит «origin», а копия автора старше, и
автор не видел ничего. Оба обвала записаны — `6322d0d56` (ADR-346, унесло 20
строк проводки) и `5fb2ab5a` (ADR-351, откатило починку ADR-347).

Воспроизведение на настоящем репозитории (цикл #573): вердикт стража —
`safe` «remote совпадает с базой рабочей копии — терять нечего», нота ПУСТАЯ,
строка чужой сессии стёрта молча. Проверка потери ИМЁН на этом пути пропущена
намеренно, с доводом «по построению невозможно» — и довод опирается ровно на
опровергнутую посылку. То есть одна команда снимает ОБА стража сразу.

Прибор отвечает на вопрос, которого стражу не хватает: **какой предок HEAD
объясняет локальную копию.** Это ЗАМЕР, а не признак: сравниваются множества
строк записанных в git блобов, ничего не выводится из имён, времени файла или
текста reflog.

Четыре исхода, и они различимы (инвариант #17):

``consistent_with_head``
    в локальной копии есть всё, что есть в базе: терять нечего, вопрос закрыт
    формой данных.
``based_on_older``
    строки базы, которых нет в копии, **в точности** равны тем, что база
    набрала после предка ``candidate``. Копия согласуется с ``candidate`` и НЕ
    согласуется с HEAD. Точное равенство множеств выбрано намеренно: при
    осознанном удалении автор обычно убирает ЧАСТЬ добавленного коммитом, и
    равенства не будет — а слабое «подмножество» назвало бы старой копией любое
    удаление.
``unexplained``
    копия теряет строки базы, и ни один предок этого не объясняет. Это не
    «всё в порядке» и не находка — это НЕ ИЗМЕРЕНО с названной причиной.
``unmeasured``
    спросить было нечем (нет git, не рабочая копия, путь вне репозитория).

Граница названа вслух: прибор судит о СТРОКАХ. Копию, потерявшую чужую правку
внутри строки, которую сама же и трогает, он не отличит — и говорит об этом
``unexplained``, а не молчанием.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

CONSISTENT_WITH_HEAD = "consistent_with_head"
BASED_ON_OLDER = "based_on_older"
UNEXPLAINED = "unexplained"
UNMEASURED = "unmeasured"

# Сколько коммитов, тронувших путь, перебирать. Потолок нужен, чтобы прибор не
# ходил по всей истории файла на каждом пуше; исчерпание потолка — НЕ «предка
# нет», а названная причина в `unexplained` (иначе длинная история молча
# превращалась бы в «ничего не нашли»).
ANCESTOR_LIMIT = 200


def _git_bytes(args, cwd) -> Optional[bytes]:
    try:
        res = subprocess.run(["git"] + args, cwd=str(cwd),
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, ValueError):
        return None
    return res.stdout if res.returncode == 0 else None


def _lines(blob: Optional[bytes]) -> frozenset:
    """Множество непустых строк блоба. ``None`` ⇒ пустое множество.

    Пустые строки выброшены намеренно: они есть почти в каждом файле и, попадая
    в разность множеств, склеивали бы разные коммиты в «одинаковую добавку».
    """
    if not blob:
        return frozenset()
    return frozenset(ln for ln in blob.split(b"\n") if ln.strip())


def base_provenance(worktree, repo_path: str, local_bytes: bytes,
                    ancestor_limit: int = ANCESTOR_LIMIT) -> dict:
    """``{"verdict", "reason", "candidate", "missing"}`` — чем объясняется копия.

    ``worktree`` — каталог внутри рабочей копии; ``repo_path`` — путь файла от
    корня репозитория; ``local_bytes`` — то, что собираются отправить.
    """
    given = Path(worktree)
    given = given if given.is_dir() else given.parent
    if not given.is_dir():
        return _unmeasured(f"каталога {given} нет")
    if _git_bytes(["rev-parse", "--verify", "HEAD"], given) is None:
        return _unmeasured("git недоступен или это не рабочая копия git")

    # ДВЕ РАЗНЫЕ СИСТЕМЫ КООРДИНАТ, и они расходятся молча (#574).
    # `HEAD:<путь>` git разбирает ОТ КОРНЯ репозитория, а pathspec у `rev-list`
    # — ОТ ТЕКУЩЕГО КАТАЛОГА. Страж зовёт нас с `Path(abs_path).parent`, то есть
    # из каталога ФАЙЛА: база читалась верно, а перечисление предков молча
    # спрашивало про `docs/docs/STATE.md` и возвращало ПУСТО. Ноль предков
    # складывался в «ни один предок этого не объясняет» — «не посмотрели»,
    # выданное за «посмотрели и не нашли». Замер #574: тот же обвал в корне
    # репозитория даёт `based_on_older` (отказ), он же в `spa_core/monitoring/`
    # — `unexplained` (пуш идёт). Оба НАСТОЯЩИХ обвала, ради которых прибор
    # написан (`6322d0d56`, `5fb2ab5a`), лежат в подкаталогах.
    top = _git_bytes(["rev-parse", "--show-toplevel"], given)
    if top is None or not top.strip():
        return _unmeasured(f"git не назвал корень рабочей копии для {given}")
    root = Path(top.decode().strip())
    if not root.is_dir():
        return _unmeasured(f"корень рабочей копии {root} не каталог")

    head_blob = _git_bytes(["cat-file", "blob", f"HEAD:{repo_path}"], root)
    if head_blob is None:
        # Пути нет в HEAD ⇒ база ничего не несёт, и терять из неё нечего.
        return {"verdict": CONSISTENT_WITH_HEAD, "candidate": None,
                "missing": frozenset(),
                "reason": f"пути {repo_path} нет в HEAD — база ничего не теряет"}

    head_lines = _lines(head_blob)
    local_lines = _lines(local_bytes)
    missing = head_lines - local_lines
    if not missing:
        return {"verdict": CONSISTENT_WITH_HEAD, "candidate": None,
                "missing": frozenset(),
                "reason": "в копии есть всё, что есть в базе — терять нечего"}

    # Берём на ДВА больше потолка: один может оказаться самим HEAD, а ещё один
    # нужен, чтобы «предков больше, чем потолок» вообще стало наблюдаемым. При
    # `--max-count={limit+1}` ветка исчерпания потолка недостижима ПО
    # ПОСТРОЕНИЮ — список обрезан ровно до потолка, и «не нашли» неотличимо от
    # «не смотрели». Поймано собственным контролем при сборке (#573).
    listing = _git_bytes(
        ["rev-list", f"--max-count={ancestor_limit + 2}", "HEAD", "--", repo_path],
        root)
    if listing is None:
        return _unmeasured(f"git не перечислил коммиты, тронувшие {repo_path}")

    shas = [s.decode() for s in listing.split(b"\n") if s.strip()]
    head_sha = (_git_bytes(["rev-parse", "HEAD"], root) or b"").decode().strip()
    ancestors = [s for s in shas if s != head_sha]

    for sha in ancestors[:ancestor_limit]:
        cand_lines = _lines(_git_bytes(["cat-file", "blob", f"{sha}:{repo_path}"], root))
        gained = head_lines - cand_lines
        if not gained or gained != missing:
            continue
        # ВТОРАЯ ПОЛОВИНА СОБСТВЕННОГО УТВЕРЖДЕНИЯ (#574). Вердикт говорит
        # «копия СОГЛАСУЕТСЯ с candidate», а меряет только РАЗНОСТЬ. Этого мало:
        # у файла с ОГРАНИЧЕННЫМ ОКНОМ (катящийся журнал на 100 записей) полная
        # прокрутка выглядит точно так же — из базы пропали ровно те строки,
        # которые она набрала одним коммитом. Замер #574 на живом хост-дереве:
        # 21 отказ, и в 20 из них копия не содержала блоб предка ВОВСЕ (катящиеся
        # `data/*_log.json`). Согласованность — это вхождение: если копия
        # объясняется предком, блоб предка лежит в ней целиком, а сверху автор
        # дописал своё. Обвал `6322d0d56` эту форму имеет; прокрутка окна — нет.
        if not cand_lines <= local_lines:
            continue
        return {"verdict": BASED_ON_OLDER, "candidate": sha, "missing": missing,
                "reason": (f"строки базы, которых нет в копии ({len(missing)}), "
                           f"в точности равны тому, что база набрала после "
                           f"{sha[:8]}, И блоб {sha[:8]} лежит в копии целиком: "
                           f"копия согласуется с {sha[:8]}, а не с HEAD")}

    if len(ancestors) > ancestor_limit:
        return {"verdict": UNEXPLAINED, "candidate": None, "missing": missing,
                "reason": (f"перебрано {ancestor_limit} коммитов из "
                           f"{len(ancestors)}+, тронувших {repo_path} — потолок "
                           f"исчерпан, предок мог остаться за ним")}
    return {"verdict": UNEXPLAINED, "candidate": None, "missing": missing,
            "reason": (f"копия теряет {len(missing)} строк(и) базы, и ни один из "
                       f"{len(ancestors)} предков пути этого не объясняет")}


def _unmeasured(reason: str) -> dict:
    return {"verdict": UNMEASURED, "candidate": None, "missing": frozenset(),
            "reason": reason}


def describe(result: dict, repo_path: str, sample: int = 5) -> str:
    """Человеческая строка вердикта; пустая — когда сказать нечего."""
    verdict = result["verdict"]
    if verdict == CONSISTENT_WITH_HEAD:
        return ""
    missing = sorted(x.decode("utf-8", "replace") for x in result["missing"])
    shown = "\n".join(f"      - {ln.strip()[:110]}" for ln in missing[:sample])
    more = (f"\n      … и ещё {len(missing) - sample}" if len(missing) > sample else "")
    if verdict == BASED_ON_OLDER:
        return (f"🚨 БАЗА ОПРОВЕРГНУТА для {repo_path}: {result['reason']}.\n"
                f"   Пропадут строки, которых автор, по замеру, НЕ ВИДЕЛ:\n"
                f"{shown}{more}")
    if verdict == UNEXPLAINED:
        return (f"⚠️  провенанс базы {repo_path} НЕ ИЗМЕРЕН: {result['reason']}.\n"
                f"   Пропадающие строки базы:\n{shown}{more}")
    return f"⚠️  провенанс базы {repo_path} НЕ ИЗМЕРЕН: {result['reason']}"
