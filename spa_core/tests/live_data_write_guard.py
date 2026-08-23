"""Сторож: прогон тестов НЕ переписывает живое git-tracked состояние в `data/`.

## Зачем он есть

Три независимых замера одного класса существуют, и **ни один не сходится с
другими**: закрытая карточка `#225/#226` говорит «три файла», замер облачной
сессии 20.08 — «сорок», собственный счёт `main` (`4a98fd7`) — «восемьдесят три».
Мерили в разных деревьях, на разных sha и разными инструментами, поэтому ни один
из трёх не опровергает остальные.

Общее у всех трёх ровно одно и оно же главное: **писателя не мерил никто.**
Какой тест какой файл трогает — было неизвестно, поэтому любое из трёх чисел
оставалось свойством прогона, а не системы. Этот модуль и есть недостающий
замер: он называет ФАЙЛЫ, которые прогон переписал, а по требованию — и ТЕСТ,
который каждый из них переписал.

## Почему существующая изоляция это не ловит

`tests/conftest.py::_isolate_data_dir` подменяет `SPA_DATA_DIR` на tmp-каталог
на каждый тест. Это закрывает всех, кто резолвит каталог данных через эту
переменную, и не закрывает никого, кто считает путь от своего `__file__`, — ровно
та же дыра, ради которой написан `push_state_guard`. Analytics-писатели журналов
во второй группе. Там же и `data/live_execution_log.json` — файл домена
ИСПОЛНЕНИЯ, которого read-only тест не имеет права касаться вовсе (инвариант #6,
`.claude/rules/deployment.md`).

## Чем он отличается от соседа `_package_data_guard`

Тот сторож смотрит на `spa_core/data/` и ловит ПОЯВЛЕНИЕ файла (сравнивает
имена). Этот смотрит на живое состояние и ловит ИЗМЕНЕНИЕ — а именно оно и
описано в карточке: `alert_log.json` не появляется, у него переписывается
`updated_at` и дописываются тестовые тревоги. Сравнение имён такую правку не
видит по построению.

## Почему сторож ПРОГОНА, а не каждого теста — цена измерена

Первая версия снимала состояние вокруг КАЖДОГО теста: так виновник называется
сразу. Замер: один снимок 428 путей — **3.9 мс**, два на тест, 96 492 теста ⇒
**+12,7 минуты** к прогону, который целиком идёт 13,3 минуты. Сторож, удваивающий
CI, будет отключён при первом же неудобном дне — это тот самый «крик волком»,
за который проект уже платил.

Поэтому по умолчанию снимков ДВА на весь прогон (начало и конец сессии, ~8 мс):
падает не тест, а прогон, и в отчёте названы файлы. Приёмка карточки
сформулирована ровно на этой высоте — «после прогона `git status --porcelain --
data/` обязан быть ПУСТ», — и сторож стоит на ней же.

Имя ВИНОВНИКА достаётся отдельным заходом: `SPA_DATA_WRITE_AUDIT=1` включает
снимок вокруг каждого теста и пишет `{nodeid, paths}` в JSONL. Это дороже, зато
даёт карту «файл → тест» целиком за один прогон. Режим НИЧЕГО не гасит: прогон
падает в обоих режимах, замер только ДОБАВЛЯЕТ атрибуцию.

## Что под наблюдением: git-tracked, но по mtime, а не по содержимому

Наблюдаются только пути, которые ЗНАЕТ git (`tracked_paths`): runtime-осадок есть
на машине автора и отсутствует на свежем чекауте CI, и сторож с такой базой краснел
бы у соседа на ровном месте.

А вот сравнение — по mtime, а не по содержимому, и это ловит то, чего приёмка
карточки увидеть НЕ МОЖЕТ. Замер: полный прогон переписывает `data/golive_status.json`
— git-tracked артефакт гейта go-live — тем же самым содержимым. `git status` про него
молчит навсегда, mtime говорит сразу. Тест, который довёл прод-код до записи в артефакт
гейта, опасен независимо от того, совпало ли содержимое в этот раз.

## Почему храповик, а не запрет

Прямой запрет покрасил бы прогон на 76 путях в первый же день — и был бы снят
раньше, чем починен хоть один писатель. Поэтому у сторожа есть КОММИТНУТАЯ база
(`live_data_write_baseline.json`): пути, которые прогон пишет сегодня. Новый путь
= красный прогон немедленно; база может ТОЛЬКО уменьшаться
(`test_live_data_write_ratchet.py`). Дописать путь в базу, чтобы погасить
падение, — запрещено: чинить писателя. Ровно тот же приём и та же причина, что у
`test_frozen_date_ratchet` (346 файлов в классе, запрет в лоб научил бы всех его
отключать).

Нечитаемая база читается как ПУСТАЯ: сломанный файл делает сторожа строже, а не
слепее.

Сторож НАЗЫВАЕТ и НЕ убирает улику: откатить файл значило бы починить отчёт
вместо дефекта — и заодно стереть чужую настоящую правку, если она там была.

Только stdlib. Импорт без побочных эффектов; хуки сессии и фикстура
регистрируются из ОБОИХ корней conftest одним и тем же модулем (`sys.modules`),
как три сторожа-соседа, иначе у двух корней было бы две независимые базы
прогона — и вторая затёрла бы первую вместе с уликой.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

#: Корень репозитория — этот файл лежит в `<root>/spa_core/tests/`.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Каталоги с живым состоянием. `data/` — трек и журналы тревог;
#: `spa_core/data/` — git-tracked фикстуры пакета (сосед `_package_data_guard`
#: ловит там ПОЯВЛЕНИЕ файла, но не правку существующего, а замер `main`
#: насчитал два таких пути); `spa_core/database/` — sqlite, который оба замера
#: нашли грязным и ни один не считал частью `data/`.
WATCHED = (
    REPO_ROOT / "data",
    REPO_ROOT / "spa_core" / "data",
    REPO_ROOT / "spa_core" / "database",
)

#: Переключатель режима замера и адрес его отчёта.
AUDIT_ENV = "SPA_DATA_WRITE_AUDIT"
AUDIT_OUT_ENV = "SPA_DATA_WRITE_AUDIT_OUT"
#: Отчёт по умолчанию лежит ВНЕ репозитория намеренно: отчёт, записанный в
#: дерево, сам пачкает то, что измеряет.
DEFAULT_AUDIT_OUT = Path("/tmp/spa_data_write_audit.jsonl")

#: Список путей, которые прогон пишет СЕГОДНЯ. Храповик: он может только
#: уменьшаться (`test_live_data_write_ratchet.py`). Почему список вообще есть —
#: в докстринге раздела «Почему храповик, а не запрет».
BASELINE_PATH = Path(__file__).resolve().parent / "live_data_write_baseline.json"

#: База прогона, набор git-tracked путей и отметка «уже отчитались» — один
#: экземпляр на сессию, потому что модуль общий для обоих корней conftest.
_session_before = None
_tracked = None
_reported = False


def tracked_paths(roots=WATCHED):
    """Пути под наблюдением, которые ЗНАЕТ git. Считается один раз за прогон.

    Почему именно git-tracked, а не всё подряд. Замер приёмки цикла #352: полный
    прогон трогает ещё 16 путей, которых git не видит вовсе (`audit_chain.jsonl`,
    `consumption_receipts.jsonl`, `bee/verify_summary.json` …) — это runtime-осадок,
    он есть на Маке и его нет на свежем чекауте CI. Сторож, чья база зависит от
    того, что валялось в каталоге у автора, краснел бы у соседа на ровном месте.
    Git-tracked набор ОДИН И ТОТ ЖЕ везде, и именно про него говорит приёмка
    карточки («`git status --porcelain -- data/` пуст»). Untracked-осадок — предмет
    соседней карточки и соседнего сторожа (`_package_data_guard`).

    Если git недоступен, возвращается None и наблюдение идёт по ВСЕМУ каталогу:
    ошибаться сторож обязан в сторону строгости.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--"] + [str(r) for r in roots],
            cwd=str(REPO_ROOT), capture_output=True, timeout=30, check=True,
        ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None
    names = frozenset(n for n in out.split("\0") if n)
    return names or None


def load_baseline(path=None):
    """Разрешённые (пока) пути. Нечитаемая база = ПУСТАЯ: сторож строже, а не слепее."""
    try:
        raw = json.loads(Path(path or BASELINE_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    paths = raw.get("paths", []) if isinstance(raw, dict) else raw
    return frozenset(p for p in paths if isinstance(p, str))


def audit_enabled():
    """Режим замера включён? (`SPA_DATA_WRITE_AUDIT=1`)"""
    return os.environ.get(AUDIT_ENV) == "1"


def audit_out_path():
    raw = os.environ.get(AUDIT_OUT_ENV)
    return Path(raw) if raw else DEFAULT_AUDIT_OUT


def _iter_files(root):
    """Все обычные файлы под *root*, `__pycache__` не в счёт.

    `.pyc`, рождённый импортом модуля пакета, — артефакт сборки, а не состояние;
    считать его значило бы краснеть на первом же импорте прогона.
    """
    stack = [Path(root)]
    while stack:
        cur = stack.pop()
        try:
            entries = list(os.scandir(cur))
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for e in entries:
            if e.is_dir(follow_symlinks=False):
                if e.name != "__pycache__":
                    stack.append(Path(e.path))
            elif e.is_file(follow_symlinks=False):
                yield Path(e.path)


def snapshot(roots=WATCHED):
    """`{путь относительно корня: (mtime_ns, размер)}` по всем наблюдаемым файлам.

    Правка на месте той же длины ловится по mtime (`atomic_save` всегда делает
    `os.replace`), удаление — по исчезновению ключа. Хеш содержимого был бы
    строже, но стоил бы ~400 чтений файлов на каждый тест, а авария, ради которой
    сторож написан (проставленный `updated_at`), mtime двигает всегда.
    """
    out = {}
    for root in roots:
        for p in _iter_files(root):
            try:
                st = p.stat()
            except OSError:
                continue
            try:
                rel = str(p.relative_to(REPO_ROOT))
            except ValueError:  # pragma: no cover — WATCHED всегда внутри корня
                rel = str(p)
            out[rel] = (st.st_mtime_ns, st.st_size)
    return out


def changed(before, after):
    """Отсортированные пути, которые появились, исчезли или изменились."""
    seen = {rel for rel, sig in after.items() if before.get(rel) != sig}
    seen.update(rel for rel in before if rel not in after)
    return tuple(sorted(seen))


def failure_message(test_id, paths):
    """Текст отказа: кто, что и почему это не косметика.

    *test_id* — nodeid теста, если он известен (режим замера), иначе слово
    «прогон»: сторож не имеет права называть виновником того, кого не измерил.
    """
    listed = ", ".join(paths)
    return (
        f"{test_id} изменил живое состояние: {listed}.\n"
        "Это git-tracked файлы прода: трек, журналы тревог и журнал исполнения. "
        "Прогон, который их переписывает, (а) подсовывает свежесть, которой в "
        "системе нет — самообновляющаяся фикстура протухнуть не может, и любой "
        "сторож свежести после прогона видит «всё свежее»; (б) делает «чистое "
        "дерево» бессмысленным сигналом перед пушем, и подмену трека можно "
        "закоммитить вместе со своей работой.\n"
        "Починка: подменить каталог/путь состояния на tmp в фикстуре этого "
        "тест-файла (образцы — spa_core/tests/test_protocol_maturity_scorer.py и "
        "соседи), а время передавать входом (`now=`), как велит "
        ".claude/rules/deployment.md.\n"
        "Пометка `live_data` СЮДА НЕ ПОДХОДИТ: она про тесты, которые живое "
        "состояние ЧИТАЮТ (`tests/conftest.py`), и права записывать не даёт "
        "никому — сторож её намеренно не признаёт.\n"
        f"ЧЕЙ ЭТО ТЕСТ — переспросить прогоном с `{AUDIT_ENV}=1`: он пишет "
        f"`{{nodeid, paths}}` в {DEFAULT_AUDIT_OUT} (адрес меняется "
        f"`{AUDIT_OUT_ENV}`).\n"
        "Карточка: inbox-progon-testov-perepisyvaet-sorok-otslezhivaemyh-failov-data."
    )


def session_finish(session):
    """Отчитаться за ВЕСЬ прогон и уронить его, если живое состояние поехало.

    Идемпотентна: хук стоит в обоих корнях conftest, и оба его позовут.
    """
    global _reported
    if _reported or _session_before is None:
        return ()
    _reported = True
    allowed = load_baseline()
    touched = tuple(p for p in changed(_session_before, watched_snapshot()) if p not in allowed)
    if not touched:
        return ()
    print("\n" + failure_message("прогон", touched), file=sys.stderr)
    if getattr(session, "exitstatus", 0) == 0:
        session.exitstatus = 1
    return touched


def watched_snapshot():
    """Снимок, суженный до git-tracked путей (или полный, если git недоступен)."""
    snap = snapshot()
    if _tracked is None:
        return snap
    return {rel: sig for rel, sig in snap.items() if rel in _tracked}


def session_start():
    """Снять базу прогона. Идемпотентна по той же причине, что и `session_finish`."""
    global _session_before, _reported, _tracked
    if _session_before is None:
        _tracked = tracked_paths()
        _session_before = watched_snapshot()
        _reported = False
    return _session_before


def record(nodeid, paths, out_path=None):
    """Дописать строку замера в JSONL-отчёт. Ошибку записи не поднимает."""
    line = json.dumps({"nodeid": nodeid, "paths": list(paths)}, ensure_ascii=False)
    try:
        out = Path(out_path) if out_path else audit_out_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass  # замер диагностический; ронять тест из-за его отчёта нельзя
    return line


@pytest.fixture(autouse=True)
def _live_data_stays_clean(request):
    """Атрибуция: чей это тест. Работает ТОЛЬКО в режиме замера.

    Вне режима замера фикстура не делает НИЧЕГО — ни одного снимка, — и её цена
    равна нулю: сама проверка живёт на уровне прогона (`session_finish`), где
    стоит 8 мс вместо 12,7 минуты.

    Пометки `live_data` здесь нет намеренно. Она означает «этот тест ЧИТАЕТ
    настоящий `data/`» и снимает изоляцию каталога ради чтения; права ПИСАТЬ в
    живое состояние она не даёт, поэтому помеченный писатель называется наравне
    со всеми.
    """
    if not audit_enabled():
        yield
        return
    before = watched_snapshot()
    yield
    touched = changed(before, watched_snapshot())
    if touched:
        record(request.node.nodeid, touched)


# ---------------------------------------------------------------------------
# Хуки сессии. Живут ЗДЕСЬ, а не только в conftest, потому что положительный
# контроль подключает этот модуль плагином (`-p live_data_write_guard`) — тогда
# проверяется тот же код, который работает в настоящем прогоне, а не его копия.
# Оба conftest зовут те же функции; повторный вызов безвреден (`_reported`).
# ---------------------------------------------------------------------------
def pytest_sessionstart(session):                # noqa: D401 — хук pytest
    """База прогона — до первого теста."""
    session_start()


def pytest_sessionfinish(session, exitstatus):   # noqa: D401 — хук pytest
    """Отчёт за прогон; красит его, если живое состояние поехало."""
    session_finish(session)
