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
| Какой номер брать? | `next` | В начале работы — он же его и ЗАБИРАЕТ |
| Этот набор файлов можно доставлять? | `check --files …` | Интерлок пушера, до сети |
| Кто что застолбил? | `reservations` | Разбор висящих резервов |
| Снять брошенный резерв | `release <NNN>` | Подметание после отменённой работы |

`next` меряет занятость по СОЮЗУ origin/main и рабочего дерева. Смотреть только в дерево — это
и есть исходный дефект: параллельная сессия живёт на origin, а не у тебя на диске.

**Почему одного `next` мало (карточка 17.08, столкновения 067/091/087).** `next` меряет
занятость В МОМЕНТ ВЫПИСКИ и ничего не занимает. Две ветки, живущие сутки параллельно
(облачная сессия и автономный цикл Мака), спрашивают номер в разное время, получают один и тот
же свободный — и ОБЕ ПРАВЫ. Столкновение всплывает при слиянии, когда обе работы написаны и на
них уже сослались. За двое суток так трижды, а в реестре R&D то же устройство стоило потери
СОДЕРЖАНИЯ (запись #53 выпала при склейке).

**Чем закрыто — резерв на origin ДО начала работы (вариант 1 карточки).** Номер занимается
атомарно, ссылки не трогаются: `next` теперь не советует номер, а ЗАБИРАЕТ его, создавая на
origin ref `refs/adr-reserved/<NNN>`. Создание ref'а — compare-and-swap на СЕРВЕРЕ:
`git push --force-with-lease=<ref>: ` требует, чтобы ref'а не существовало, поэтому вторая ветка
получает отказ «stale info» (и берёт следующий номер), а не тихий fast-forward поверх чужого
резерва. Проверено замером: даже когда чужой резерв — предок твоего коммита, лизинг отвергает.

Почему ref, а не файл-заглушка `ADR-NNN-reserved.md`, как предлагала карточка: заглушка
резервирует только там, куда её приземлили, а параллельные ветки по построению не пишут в одну
и ту же ветку (облачная сессия пушит в `claude/…`, Мак — в `main` через API). Файл в своей ветке
не виден сопернику до слияния — то есть ровно та же авария. Ref живёт вне веток, виден обоим
СРАЗУ (`git ls-remote`), не участвует в слияниях и не ломает ни одной существующей ссылки.
Цена та же, что у заглушки: у брошенных работ остаются висящие резервы — их видно
(`reservations`) и можно подмести (`release`).

**Два контекста доставки — два транспорта, третьего нет (fail-CLOSED).** Облако пушит git'ом,
Мак — GitHub API с PAT из Keychain. `reserve_number` умеет оба (`--transport auto`: git, при
отказе транспорта — API) и, если не сработал НИ ОДИН, номер НЕ ВЫДАЁТСЯ (код 2). Молчаливое
«ну ладно, бери незарезервированным» — это и есть исходная авария.

**Почему `max+1`, а не «первый свободный».** В нумерации есть дыры (31–47, 49, 51, 52, 71), и
они не свободны: `ADR-071` уже назван в `docs/STATE.md` как «аудит-как-код» — решение, о котором
договорились раньше, чем написали файл. Выдать такой номер новому решению значит столкнуть его
с уже уехавшей ссылкой, то есть воспроизвести ровно ту аварию, которую этот модуль устраняет.
Карточка оставляла выбор реализации агенту; дыры дороже, чем плотность нумерации.

Коды возврата: **0** — свободно / находок нет · **1** — есть находки · **2** — что-то не
измерено (fail-CLOSED: «не измерено» никогда не сворачивается в «в порядке»).

stdlib-only. `check` по-прежнему без сети (git читает локальные ref'ы) — интерлок пушера обязан
судить до сети. `next` в сеть ХОДИТ по построению: резерв, видимый только у себя на диске, не
резервирует ничего; недоступная сеть здесь — «номер не выдан», а не «номер свободен».
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from check_undelivered_work import _git  # noqa: E402  (переиспользование, не копия)

DEFAULT_BASE = "origin/main"
DEFAULT_REMOTE = "origin"
DEFAULT_REPO = "yurii-spa/SPA"
DECISIONS_DIR = "docs/decisions"
INDEX_REL = f"{DECISIONS_DIR}/INDEX.md"

# Пространство резервов. Вне `refs/heads/*` намеренно: резерв не участвует в слияниях,
# не попадает в чекауты и не может «уехать вместе с веткой» — он виден обеим сторонам
# сразу и означает ровно одно: «этот номер занят, ищи следующий».
RESERVE_NS = "refs/adr-reserved"
RESERVE_ATTEMPTS = 5

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


def _reserve_ref(number) -> str:
    """Имя ref'а резерва. Номер нормализуется в три знака: `92` и `092` — один номер."""
    return f"{RESERVE_NS}/{int(number):03d}"


def _keys_from_ref_lines(lines):
    """Ключи из строк `…refs/adr-reserved/NNN` (и `ls-remote`, и `for-each-ref`)."""
    keys = set()
    for line in lines:
        name = line.strip().split()[-1] if line.strip() else ""
        if name.startswith(RESERVE_NS + "/"):
            tail = name[len(RESERVE_NS) + 1:]
            if _NUMERIC_KEY_RE.match(tail):
                keys.add(tail)
    return keys


def reserved_keys(root, remote=None, git=_git):
    """(зарезервированные ключи, не_измерено).

    Локальные ref'ы читаются всегда (бесплатно, это кэш ранее увиденных резервов), удалённые —
    только если назван `remote`. Недоступность remote — «не измерено», а не «резервов нет»:
    именно резерв соперника и есть то, чего у тебя на диске нет по построению.
    """
    keys, unchecked = set(), []
    rc, out, err = git(root, "for-each-ref", "--format=%(refname)", f"{RESERVE_NS}/")
    if rc != 0:
        unchecked.append(f"локальные ref'ы {RESERVE_NS}/ не читаются ({err.strip()})")
    else:
        keys |= _keys_from_ref_lines(out.splitlines())

    if remote:
        rc, out, err = git(root, "ls-remote", remote, f"{RESERVE_NS}/*")
        if rc != 0:
            unchecked.append(
                f"резервы номеров на {remote} не читаются ({err.strip() or 'rc=%d' % rc}) — "
                f"занятость НЕ измерена; выдать номер, не увидев чужих резервов, значит "
                f"воспроизвести столкновения 067/091/087")
        else:
            keys |= _keys_from_ref_lines(out.splitlines())
    return keys, unchecked


def taken_keys(root, base_ref=DEFAULT_BASE, git=_git, remote=None):
    """(занятые ключи, не_измерено). Союз origin, рабочего дерева и РЕЗЕРВОВ.

    Смотреть только в дерево — исходный дефект: параллельная сессия занимает номер НА ORIGIN,
    и её файла у тебя на диске нет по построению. Поэтому недоступность origin — не повод
    ответить «ну, по дереву свободно»: это отказ измерить (код 2).

    Резерв (`refs/adr-reserved/NNN`) — третий, самый ранний источник претензии: он появляется
    в НАЧАЛЕ чужой работы, когда ни файла, ни строки реестра ещё нет.
    """
    root = Path(root)
    taken: dict[str, set] = {}
    unchecked = []

    def claim(key, where):
        taken.setdefault(key, set()).add(where)

    res_keys, res_unchecked = reserved_keys(root, remote=remote, git=git)
    unchecked.extend(res_unchecked)
    for key in res_keys:
        claim(key, f"резерв:{RESERVE_NS}/{key}")

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


def next_number(root, base_ref=DEFAULT_BASE, git=_git, remote=None):
    """(следующий свободный номер | None, занятые, не_измерено).

    СОВЕТ, а не претензия: номер становится твоим только после `reserve_number` (см. `allocate`).
    Два вызова этой функции из двух веток честно вернут ОДНО И ТО ЖЕ — это и есть авария 087.
    """
    taken, unchecked = taken_keys(root, base_ref, git=git, remote=remote)
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


# ── резерв номера на origin: два транспорта, третьего нет ────────────────────

RESERVED, TAKEN, UNAVAILABLE = "reserved", "taken", "unavailable"


def _load_pusher(path):
    """Модуль доставки как модуль: весь его исполняемый код под `if __name__`.

    Загружается ПО ПУТИ и ЛЕНИВО (только когда git-транспорт отказал): у облачной сессии
    этого файла может не быть в дереве вовсе, и его отсутствие не должно ронять импорт
    распределителя.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("push_to_github_for_reserve", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"{path} не загружается")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _reserve_sha(root, base_ref, git=_git):
    """Коммит, на который смотрит ref резерва. Берём тот, что УЖЕ на origin.

    Смысл несёт ИМЯ ref'а, а не его цель, поэтому цель выбирается самая дешёвая: коммит
    базового ref'а уже лежит на сервере, и резерв не тащит туда ни одного объекта (а заодно
    не публикует недоделанную ветку тайком).
    """
    rc, out, _ = git(root, "rev-parse", f"{base_ref}^{{commit}}")
    if rc == 0 and out.strip():
        return out.strip()
    rc, out, _ = git(root, "rev-parse", "HEAD")
    return out.strip() if rc == 0 and out.strip() else None


def _reserve_object(root, number, base_ref, git=_git):
    """Уникальный коммит-метка резерва. -> (sha | None, причина).

    **Почему не просто `origin/main`.** Замерено тестом `…rival_whose_commit_is_an_ancestor`:
    две ветки одной базы отправили бы в ref ОДИН И ТОТ ЖЕ sha, git ответил бы «Everything
    up-to-date» с кодом 0 — и обе стороны прочитали бы это как «зарезервировал», то есть
    авария вернулась бы целиком, а лизинг не сработал бы ни разу (нечего сравнивать: значение
    не меняется). Уникальный объект делает любую вторую попытку РАЗНОЙ по значению, и
    compare-and-swap на сервере срабатывает.

    Побочно резерв перестаёт быть анонимным: `git log refs/adr-reserved/<NNN>` показывает, кто
    и когда его взял, — брошенные резервы становится кому предъявить.
    """
    rc, tree, _ = git(root, "rev-parse", f"{base_ref}^{{tree}}")
    if rc != 0 or not tree.strip():
        return None, f"дерево {base_ref} не читается — резерв не построить"
    parent = _reserve_sha(root, base_ref, git=git)
    _, branch, _ = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    msg = (f"adr-reserve {int(number):03d} · ветка {branch.strip() or '?'} · "
           f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} · "
           f"{os.getpid()}-{os.urandom(4).hex()}")
    args = ["-c", "user.name=adr-reserve", "-c", "user.email=adr-reserve@spa",
            "commit-tree", tree.strip()]
    if parent:
        args += ["-p", parent]              # привязка к истории: на сервер уедет один объект
    rc, out, err = git(root, *args + ["-m", msg])
    if rc != 0 or not out.strip():
        return None, f"commit-tree не отработал ({err.strip()[:200]})"
    return out.strip(), msg


def _reserve_via_git(root, number, remote, base_ref, git=_git):
    """Резерв через `git push` (контекст облачной сессии). -> (статус, подробность)."""
    sha, why = _reserve_object(root, number, base_ref, git=git)
    if not sha:
        return UNAVAILABLE, f"объект резерва не построен: {why}"
    ref = _reserve_ref(number)
    # `--force-with-lease=<ref>:` с ПУСТЫМ ожидаемым значением = «ref'а не должно
    # существовать». Без лизинга чужой резерв, оказавшийся предком нашего коммита, был бы
    # ТИХО перезаписан fast-forward'ом — то есть номер «зарезервировали» бы дважды.
    rc, out, err = git(root, "push", remote, f"--force-with-lease={ref}:", f"{sha}:{ref}")
    blob = f"{out}\n{err}"
    if rc == 0 and "up-to-date" in blob:
        # Оборона на случай, если объект резерва всё же совпал: «нечего пушить» — это НЕ
        # «зарезервировал», это «ref уже существует ровно с таким значением».
        return TAKEN, f"{ref} уже существует с тем же значением"
    if rc == 0:
        return RESERVED, ref
    if "stale info" in blob or "already exists" in blob:
        return TAKEN, f"{ref} уже застолблён на {remote}"
    return UNAVAILABLE, f"git push в {remote} не отработал (rc={rc}): {blob.strip()[:400]}"


def _reserve_via_api(root, number, repo, base_ref, git=_git, pusher=None):
    """Резерв через GitHub API (контекст Мака: PAT в Keychain, git-транспорт не настроен).

    Переиспользуется доставка, а не переписывается: PAT и вызов API берутся у `push_to_github`.
    `POST /git/refs` — тот же compare-and-swap: существующий ref даёт 422.
    """
    import urllib.error  # локально: у git-транспорта этой зависимости нет

    if pusher is None:
        try:
            pusher = _load_pusher(Path(root) / "push_to_github.py")
        except Exception as exc:                      # noqa: BLE001 — любая причина = «нет транспорта»
            return UNAVAILABLE, f"push_to_github.py не загружается ({exc})"
    try:
        pat = pusher.get_pat()
    except Exception as exc:                          # noqa: BLE001
        return UNAVAILABLE, f"PAT недоступен ({exc})"
    try:
        sha = pusher.get_base_ref(pat, repo, base_ref.split("/")[-1])[0]
    except Exception as exc:                          # noqa: BLE001
        return UNAVAILABLE, f"база {base_ref} на {repo} не читается через API ({exc})"
    ref = _reserve_ref(number)
    try:
        pusher._api(pat, "POST", f"/repos/{repo}/git/refs", {"ref": ref, "sha": sha})
        return RESERVED, ref
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:                             # noqa: BLE001
            pass
        if exc.code == 422 and "already exists" in body:
            return TAKEN, f"{ref} уже застолблён на {repo}"
        return UNAVAILABLE, f"POST /git/refs → HTTP {exc.code}: {body[:300]}"
    except Exception as exc:                          # noqa: BLE001
        return UNAVAILABLE, f"GitHub API недоступен ({exc})"


def reserve_number(root, number, remote=DEFAULT_REMOTE, base_ref=DEFAULT_BASE, git=_git,
                   transport="auto", repo=DEFAULT_REPO, pusher=None):
    """Атомарно застолбить номер на origin. -> (статус, подробность).

    `reserved` — номер твой · `taken` — соперник успел раньше (бери следующий) ·
    `unavailable` — НЕ ИЗМЕРЕНО, номер не выдаётся. Третьего исхода нет: «не смог
    зарезервировать, но номер всё равно бери» — это ровно та авария, ради которой всё это.
    """
    root = Path(root)
    if transport in ("auto", "git"):
        status, detail = _reserve_via_git(root, number, remote, base_ref, git=git)
        if status != UNAVAILABLE or transport == "git":
            return status, detail
        git_detail = detail
        status, detail = _reserve_via_api(root, number, repo, base_ref, git=git, pusher=pusher)
        if status == UNAVAILABLE:
            return UNAVAILABLE, f"git: {git_detail}; api: {detail}"
        return status, detail
    if transport == "api":
        return _reserve_via_api(root, number, repo, base_ref, git=git, pusher=pusher)
    return UNAVAILABLE, f"неизвестный транспорт резерва: {transport}"


def release_number(root, number, remote=DEFAULT_REMOTE, git=_git):
    """Снять резерв (брошенная работа). -> (ok, подробность)."""
    ref = _reserve_ref(number)
    rc, out, err = git(Path(root), "push", remote, "--delete", ref)
    return (rc == 0), (f"{ref} снят" if rc == 0 else f"{err.strip() or out.strip()}")


def allocate(root, base_ref=DEFAULT_BASE, remote=DEFAULT_REMOTE, git=_git,
             attempts=RESERVE_ATTEMPTS, transport="auto", repo=DEFAULT_REPO, pusher=None):
    """(номер | None, гонки, не_измерено) — выписать номер И ЗАБРАТЬ его.

    Цикл, а не один проход: `taken` от резерва означает, что соперник застолбил номер между
    нашим измерением и нашей записью — то самое окно, в котором и жили 067/091/087. Здесь оно
    закрывается не «не бывает», а «увидели и взяли следующий».
    """
    races = []
    for _ in range(max(1, int(attempts))):
        number, _taken, unchecked = next_number(root, base_ref, git=git, remote=remote)
        if unchecked:
            return None, races, unchecked
        status, detail = reserve_number(root, number, remote=remote, base_ref=base_ref, git=git,
                                        transport=transport, repo=repo, pusher=pusher)
        if status == RESERVED:
            return number, races, []
        if status == TAKEN:
            races.append(f"ADR-{number:03d}: {detail}")
            continue
        return None, races, [
            f"резерв ADR-{number:03d} НЕ выполнен ни одним транспортом — номер не выдаю "
            f"(fail-CLOSED): {detail}"]
    return None, races, [
        f"за {attempts} попыток номер не удалось застолбить — гонка не сходится: "
        f"{'; '.join(races)}"]


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


# Указатель на переехавшее решение. Признак машиночитаемый и УЖЕ соблюдён обоими
# существующими указателями (`ADR-067-golive-…`, `ADR-073-owner-decisions-in-telegram`):
# заголовок «# ADR-NNN (номер занят) → …» и строка статуса, называющая файл указателем.
# Достаточно ЛЮБОГО из двух: заголовок держит форму, статус — смысл, и они писались
# независимо. Литерального списка номеров здесь нет намеренно — иначе сторож пришлось бы
# править при каждом новом расхождении, а такие правят до тех пор, пока не отключат.
_POINTER_HEAD_RE = re.compile(r"^#\s*ADR-[0-9A-Za-z.-]+\s*\(номер занят\)", re.MULTILINE)
_POINTER_STATUS_RE = re.compile(r"^\*\*Статус:\*\*.*указател", re.MULTILINE | re.IGNORECASE)


def is_pointer_file(text: str) -> bool:
    """Файл — указатель на переехавшее решение, а не решение? Содержания в нём нет."""
    return bool(_POINTER_HEAD_RE.search(text) or _POINTER_STATUS_RE.search(text))


def file_duplicates(root, decisions_dir=DECISIONS_DIR):
    """{номер: [файлы]} — номера, под которыми лежит БОЛЬШЕ ОДНОГО настоящего решения.

    Отдельное измерение от `live_duplicates`, и намеренно из ДРУГОГО источника: тот судит по
    строкам реестра, этот — по самим файлам. Ровно на этой разнице и держалась авария 067:
    два принятых решения лежали файлами под одним номером, а реестр при этом «выглядел целым».
    Реестр пишет человек, файлы кладёт работа — сторож, читающий только реестр, стережёт
    описание вместо предмета.

    Указатель номер НЕ занимает (`is_pointer_file`): «указатель + решение» — это и есть принятый
    способ разойтись, и краснеть на нём значило бы требовать удалить указатель, то есть
    воскресить мёртвую ссылку. Нечитаемый файл — находка, а не пропуск (fail-CLOSED): «не
    измерено» здесь не сворачивается в «в порядке».
    """
    decisions = Path(root) / decisions_dir
    if not decisions.is_dir():
        return {}
    by_number: dict[str, list] = {}
    for p in sorted(decisions.glob("*.md")):
        key = file_key(p.name)
        if not key or not _NUMERIC_KEY_RE.match(key):
            continue          # именованные семейства (YL/OWN/TEST) — своё пространство имён
        try:
            pointer = is_pointer_file(p.read_text(encoding="utf-8"))
        except OSError:
            pointer = False   # не прочитали ⇒ считаем претензией на номер, а не «не в счёт»
        if not pointer:
            by_number.setdefault(f"{int(key):03d}", []).append(p.name)
    return {k: v for k, v in by_number.items() if len(v) > 1}


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
    root, remote = Path(args.root), (args.remote or None)
    if args.no_reserve:
        number, taken, unchecked = next_number(root, args.base, remote=remote)
        races = []
    else:
        number, races, unchecked = allocate(root, args.base, remote=remote,
                                            transport=args.transport)
        taken = {}
    if args.json:
        print(json.dumps({"next": number, "reserved": bool(number and not args.no_reserve),
                          "races": races, "taken": sorted(taken), "unchecked": unchecked},
                         ensure_ascii=False, indent=2))
    elif unchecked:
        print("❓ НЕ ИЗМЕРЕНО — номер не выдан (fail-CLOSED):")
        for u in unchecked:
            print(f"  - {u}")
    else:
        print(f"ADR-{number:03d}")
        for r in races:
            print(f"  гонка: {r} — взят следующий")
        if args.no_reserve:
            print(f"  занято номеров: {len(taken)} (союз {args.base}, дерева и резервов)")
            print("  ⚠️  номер НЕ зарезервирован: параллельная ветка вправе взять его же. "
                  "Резерв — `next` без --no-reserve.")
        else:
            print(f"  зарезервирован на {remote}: {_reserve_ref(number)} "
                  f"(снять — `release {number:03d}`)")
    return 2 if unchecked else 0


def _cmd_reservations(args) -> int:
    keys, unchecked = reserved_keys(Path(args.root), remote=(args.remote or None))
    if args.json:
        print(json.dumps({"reserved": sorted(keys), "unchecked": unchecked},
                         ensure_ascii=False, indent=2))
        return 2 if unchecked else 0
    if unchecked:
        print("❓ НЕ ИЗМЕРЕНО — резервы не перечислены (fail-CLOSED):")
        for u in unchecked:
            print(f"  - {u}")
        return 2
    print(f"резервов: {len(keys)}")
    for k in sorted(keys):
        print(f"  ADR-{k}")
    return 0


def _cmd_release(args) -> int:
    ok, detail = release_number(Path(args.root), args.number, remote=(args.remote or None)
                                or DEFAULT_REMOTE)
    print(("✅ " if ok else "❌ ") + str(detail))
    return 0 if ok else 2


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
    ap.add_argument("--remote", default=DEFAULT_REMOTE,
                    help="remote для резервов (пустая строка — не ходить на сеть)")
    ap.add_argument("--transport", default="auto", choices=["auto", "git", "api"],
                    help="как резервировать: git (облако) · api (Мак, PAT) · auto")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("next", help="выписать номер И ЗАБРАТЬ его резервом на origin")
    n.add_argument("--no-reserve", action="store_true",
                   help="только посмотреть, НЕ занимая (номер может увести соседняя ветка)")

    c = sub.add_parser("check", help="можно ли доставлять этот набор файлов")
    c.add_argument("--files", nargs="+", required=True, help="файлы набора доставки")

    sub.add_parser("reservations", help="кто что застолбил")

    r = sub.add_parser("release", help="снять брошенный резерв")
    r.add_argument("number", type=int, help="номер резерва, например 92")

    args = ap.parse_args(argv)
    return {"next": _cmd_next, "check": _cmd_check,
            "reservations": _cmd_reservations, "release": _cmd_release}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
