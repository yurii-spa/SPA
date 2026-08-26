#!/usr/bin/env python3
"""scripts/check_card_claim.py — «эту карточку уже кто-то взял?» (шаг 0b протокола).

**Зачем.** 30.07 две автономные сессии независимо взяли ОДНУ карточку
(`agent-ci-ignores-golive-gate-tests`): `pid6621` в 14:04Z, `pid17579` в 15:16Z. Обе проделали
одну и ту же работу, обе правили `.github/workflows/ci.yml` и `test.yml`; доставлена была одна,
работа второй осталась в `/private/tmp/spa_wt_cycle46`. Протокол ОБЯЗЫВАЕТ объявлять владение
файлами, но `log_session_change.py` — журнал, а не проверка: он ничего не отвечает на вопрос
«эту карточку уже держат?». Ответ оставался на внимательность сессии — и ровно она отказала.
Радиус шире потерянного цикла: доставь обе сессии свои правки одних и тех же файлов, вторая
перезаписала бы первую (пуш идёт через Contents API по sha — гонка даёт 409 либо молчаливую
потерю чужой правки).

**Что делает.** Детерминированно, read-only, только stdlib, **без сети**:

1. читает frontmatter карточки — явный захват `claimed_by` / `claimed_at`;
2. читает `data/session_changes.jsonl` и ищет объявления, относящиеся к ЭТОЙ карточке:
   поле ``card:`` в записи (сильный признак) · файл карточки в списке объявленного владения
   (сильный) · упоминание идентификатора карточки в тексте (слабый);
3. по каждому найденному захвату измеряет активность объявившей сессии тем же кодом, что и
   шаг 0a (`check_undelivered_work.session_state`: `ps -p <pid> -o lstart=`) и возраст записи;
4. отдельно — **пересечение по файлам** (`--files`): свежие объявления других сессий,
   которые держат те же файлы, что я собираюсь править;
5. печатает вердикт и **отдельно** всё, что измерить не удалось.

**Вердикты.** ``free`` — захватов не найдено (и всё измерено) · ``claimed`` — карточку держит
другая сессия (свежо либо активность ПОДТВЕРЖДЕНА) ⇒ **брать НЕЛЬЗЯ, взять следующую** ·
``stale`` — сильный захват старше окна ожидания без подтверждённой активности ⇒ кандидат на
подъём осиротевшей работы, порядок прежний: **сверить вручную**, отчёту не верить, перепроверить
прогонами (авто-захвата чужой работы здесь нет и не будет) · ``unchecked`` — что-то не измерено.

**fail-CLOSED (инв. #2).** «Не смог измерить» никогда не сворачивается в «карточка свободна»:
нет карточки / нет журнала объявлений / битая метка времени захвата / `ps` не отработал у
старого захвата → раздел «НЕ ИЗМЕРЕНО» и код возврата 2. Коды: **0** — свободна (всё измерено);
**1** — есть захват (claimed/stale); **2** — что-то не измерено (перебивает 1). У `claim` тот же
код 2 означает ещё один исход: захват под ярлыком без объявленного долгоживущего процесса —
`UnmeasurableClaim`, карточка НЕ взята (цикл #387).

**Осознанные границы (это проверка ПЕРЕД взятием, не блокировка):**
- захват в карточке — кооперативный контроль: файл держится честной записью, а не lock'ом ядра.
  Критическая секция самой записи защищена `O_EXCL`-файлом, но ничто не мешает править карточку
  мимо инструмента;
- **слабый признак (упоминание в тексте) сам по себе НЕ блокирует — ни старый, ни свежий.**
  Упоминание уходит в раздел «история», а не в находку: иначе любая когда-либо НАЗВАННАЯ
  карточка была бы занята. Старая НЕдоставленная работа — домен шага 0a
  (`check_undelivered_work.py`), который сверяет файлы с origin; дублировать его здесь значит
  спорить с ним же.
  Правило вводилось в два приёма, оба раза по ЗАМЕРУ голодающей очереди:
  **(1) старое упоминание** (31.07, `agent-weak-mention-locks-card-forever`) — `session_state`
  отдаёт `UNKNOWN` для идентификатора без pid (`cycle49`, `cycle55` …) детерминированно и
  **необратимо**, поэтому старение не наступало никогда, и одно упоминание запирало карточку
  до конца существования журнала (так на 19 часов выпали из очереди `agent-durable-session-id`
  и `agent-idea21-verdict-data-drift` — обе упомянуты циклом #49 В ОТРИЦАНИИ, «обе НЕ беру»);
  **(2) свежее упоминание** (01.08, `agent-fresh-weak-mention-deadlocks-queue`) — окно свежести
  не истекает, потому что его перезаряжает сам отчёт: шаг 0b обязывает называть карточки
  поимённо, циклы идут раз в час, окно — 3ч. Замерено: `cycle66` и `cycle66i` заперли ОБЕ
  оставшиеся карточки бэклога ровно тем, что доложили об их занятости, и автономная очередь
  встала целиком.
  **fail-CLOSED при этом не ослаблен:** СИЛЬНЫЙ признак (`claimed_by` / поле `card:` /
  файл карточки во владении) работает как прежде — свежий блокирует, старый с неизмеримой
  активностью даёт «не измерено», старый с мёртвой сессией — `stale`; настоящий захват всегда
  несёт сильный признак (`announce_claim`, цикл #54). Подтверждённо ЖИВАЯ сессия блокирует
  по ЛЮБОМУ признаку, включая слабый. И главное: **пересечение по объявленным файлам
  (`--files`) — независимое измерение, оно по-прежнему даёт `claimed`**, а это и есть защита
  от сессии, взявшей карточку в обход инструмента (работая над карточкой, она объявляет файлы);
- **личность сессии — это измерение, а не ярлык** (01.08, `agent-self-claim-blocked-by-own-second-identity`).
  Идентификатор в журнале выдаётся из pid ОДНОКРАТНОЙ CLI-команды, поэтому у `claim` и
  `release` одной сессии он разный, и сессия отказывала сама себе. «Моё ли это объявление»
  решает совпадение долгоживущего процесса (`session_pid` + `session_pid_start`) —
  подтверждённая пара, а не самозаявление; чужой якорь (или его отсутствие) блокирует как
  прежде. **С цикла #387 профилактика не «остаётся главной», а ОБЯЗАТЕЛЬНА:** захват под
  ярлыком без объявленного долгоживущего процесса не состоится вовсе (`UnmeasurableClaim`,
  код возврата 2) — совет вместо отказа 26.08 не удержал, и карточка с недоставленной
  работой стала неберущейся навсегда. Выставить `SPA_SESSION_ID` и `SPA_SESSION_PID` ДО
  первого объявления (`scripts/agent_orchestrator.sh` это делает сам);
- «объявленный файл» ≠ «файл, который сессия реально изменила» (владение объявляется авансом),
  поэтому пересечение по файлам — сигнал к сверке, а не доказательство конфликта;
- направление ошибки выбрано намеренно: ложная занятость стоит одной карточки (взять следующую),
  ложная свобода стоит цикла работы и рискует потерей чужой правки.

**Общее состояние — в ГЛАВНОМ рабочем дереве, не в worktree (31.07, карточка
`agent-claim-without-announce-is-invisible`).** Протокол ОБЯЗЫВАЕТ работать в изолированном
worktree (§3.4), а `data/` в `.gitignore` ⇒ журнал объявлений внутри worktree свой и пустой:
запущенный оттуда шаг 0b отвечал «НЕ ИЗМЕРЕНО» о ЛЮБОЙ карточке. Поэтому умолчание `--log`
разрешается в главное дерево (`check_undelivered_work.shared_log`). А сам захват теперь ВСЕГДА
сопровождается записью в этом журнале (`announce_claim`): `claimed_by` во frontmatter лежит в
дереве сессии и до пуша не виден никому, запись же видна отовсюду сразу — «взял, но не
объявил» перестало быть возможным состоянием.

    python3 scripts/check_card_claim.py check agent-card-claim-collision-guard
    python3 scripts/check_card_claim.py check <карточка> --files /abs/a.py /abs/b.py --json
    python3 scripts/check_card_claim.py check <карточка> --session pid72474   # моё объявление
    python3 scripts/check_card_claim.py claim   <карточка>      # взять (пишет claimed_by/at)
    python3 scripts/check_card_claim.py claim   <карточка> --takeover "чем сверил"  # ПОДЪЁМ осиротевшего захвата
    python3 scripts/check_card_claim.py release <карточка>      # отпустить
    python3 scripts/check_card_claim.py list                    # все занятые карточки
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "data" / "session_changes.jsonl"
DEFAULT_TRACKER = ROOT / "nimbalyst-local" / "tracker"
SIBLING = ROOT / "scripts" / "check_undelivered_work.py"
ANNOUNCER = ROOT / "scripts" / "log_session_change.py"

_UNMEASURABLE_CLAIM_TEXT = (
    "захват НЕ записан: у ярлыка {session!r} нет объявленного долгоживущего процесса, "
    "поэтому активность этой сессии не сможет измерить НИКТО — ни следующий цикл, ни она "
    "сама.\nТакой захват не стареет: `session_state` отдаёт UNKNOWN необратимо, вердикт "
    "уходит в `unchecked`, а подъём (`--takeover`) разрешён только на `stale` ⇒ карточка "
    "{card} осталась бы занятой навсегда (живой случай 26.08, цикл #386).\n"
    "Лечится одной строкой ДО первого объявления:\n"
    "  export SPA_SESSION_PID=<pid долгоживущего процесса этой сессии>   "
    "# scripts/agent_orchestrator.sh делает это сам\n"
    "  export SPA_SESSION_ID=<ярлык сессии>                              "
    "# один и тот же на ВСЕ объявления цикла\n"
    "Интерактивная оболочка: `export SPA_SESSION_PID=$$` — захват будет считаться "
    "живым ровно пока жива ЭТА оболочка, и это сказано вслух, а не подразумевается.")

DEFAULT_GRACE_HOURS = 3.0          # то же окно, что у шага 0a — одна семантика «свежести»
LOCK_STALE_SEC = 300               # старше — считаем брошенным, но НЕ удаляем молча
DEFAULT_BASE_REF = "origin/main"   # запасной источник карточки, которой нет в рабочем дереве

FREE, CLAIMED, STALE, UNCHECKED = "free", "claimed", "stale", "unchecked"
STRONG, WEAK = "strong", "weak"
_SEVERITY = {FREE: 0, STALE: 1, CLAIMED: 2, UNCHECKED: 3}

# Статусы, при которых карточку никто не «держит» по определению: работа закрыта.
# Благодаря этому забытый claimed_by не блокирует карточку вечно и его не нужно вычищать.
TERMINAL_STATUSES = {"done", "ingested", "owner-done"}

#: Строки frontmatter, которыми распоряжается ИМЕННО захват. Основание подъёма
#: (`claim_takeover_reason`) стоит здесь, а не рядом: оно ставится вместе с захватом и
#: обязано сниматься вместе с ним — иначе на карточке навсегда осталось бы объяснение
#: подъёма, которого больше нет (утверждение без предмета — тот самый класс).
_CLAIM_KEYS = ("claimed_by", "claimed_at", "claim_takeover_reason")

# «Якорь не передан» ≠ «якоря нет»: умолчание меряет свой долгоживущий процесс из окружения,
# явный None выключает опознание собственных объявлений (герметичные тесты). См. `self_identities`.
_ENV_ANCHOR = object()

# То же различие для ОБЩИХ рабочих деревьев (родство по дереву, #303): умолчание меряет
# главное дерево через `git worktree list`, явный None означает «не измерено» и выключает
# признак целиком. Пустой кортеж — тоже измерение («общих деревьев нет»), и он не равен None.
_MEASURE_TREES = object()


class ClaimError(RuntimeError):
    """Захват не выполнен (карточку держит другой / идёт чужая запись). Fail-CLOSED."""


class AnnounceError(ClaimError):
    """Захват не объявлен в общем журнале ⇒ карточка НЕ взята (см. `announce_claim`)."""


class UnmeasurableClaim(ClaimError):
    """Захват под ярлыком, чью активность НИКТО не сможет измерить ⇒ карточка НЕ взята.

    **Предупреждение здесь уже было — и оно не удержало.** Цикл #263 назвал класс верно
    («захват без личности процесса неизмерим НАВСЕГДА») и выбрал предупреждение на stderr:
    `claim` брал карточку и печатал совет выставить `SPA_SESSION_PID`. 26.08 предсказанное
    сбылось дословно: сессия #386 взяла карточку под ярлыком `cycle-386` без объявленного
    долгоживущего процесса, через сорок минут умерла, не доставив ничего, — и карточка с
    настоящей недоставленной работой стала НЕБЕРУЩЕЙСЯ:

    * шаг 0a: «на origin/main файла нет, но он ЛЕЖИТ в /private/tmp/spa_c386 — это настоящая
      недоставленная работа, её надо поднять»;
    * шаг 0b в ту же минуту: `⛔ ЗАНЯТА — НЕ бери эту карточку`;
    * `--takeover` отказал: подъём разрешён только на вердикте `stale`.

    Само по себе время не лечит: `session_state` для ярлыка без pid отдаёт `UNKNOWN`
    детерминированно и НЕОБРАТИМО, поэтому по истечении окна свежести вердикт уходит не в
    `stale`, а в `unchecked` — где подъём запрещён так же. Ни один из двух признаков родства
    до такой пары не дотягивается ПО ПОСТРОЕНИЮ: `pid_tokens('cycle-386')` пусто (#293), а
    дерево читается только из АБСОЛЮТНЫХ путей, тогда как запись-якорь объявила
    ОТНОСИТЕЛЬНЫЕ (#303).

    **Почему отказ, а не более умное чтение.** Починка на стороне читателя пробовалась в этом
    же цикле и была ОТВЕРГНУТА собственными обратными контролями: связывать ярлыки «по одному
    событию захвата» (та же карточка, тот же момент) значит принять за одну сессию и две
    РАЗНЫЕ, взявшие одну карточку в одну минуту, — а это гонка, ради которой инструмент и
    написан. Ложная свобода отдаёт карточку живой сессии и стоит дороже ложной занятости
    (`test_card_claim_tree_kin.py::TestStep0bAgreesWithStep0aAboutDeath`). Информации, чтобы
    отличить эти два случая, в записи НЕТ — потому что её туда не положили. Значит чинить
    надо запись, а не догадку о ней.

    Отказ ничего не стоит тому, кто прав: `SPA_SESSION_PID` — одна переменная окружения,
    `scripts/agent_orchestrator.sh` выставляет её сам. Прецедент формы — `DroppedWithoutReason`
    в `log_session_change`: признак, который можно поставить молчанием, закрывает что угодно.
    """


# ── общий код со шагом 0a (единственный источник правды про активность сессии) ──

def load_sibling(path=SIBLING):
    """Модуль `check_undelivered_work` по явному пути (`scripts/` — не пакет).

    Логика «жива ли сессия» намеренно НЕ копируется: два расходящихся ответа на один вопрос
    хуже, чем отсутствие второго. Не загрузился — это «не измерено», а не «свободна»."""
    p = Path(path)
    if not p.exists():
        raise ImportError(f"нет соседнего модуля шага 0a: {p}")
    spec = importlib.util.spec_from_file_location("_card_claim_sibling", p)
    if spec is None or spec.loader is None:
        raise ImportError(f"не удалось загрузить {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for attr in ("session_state", "read_entries", "_parse_ts", "ACTIVE", "UNKNOWN",
                 "shared_log", "main_worktree", "worktree_of"):
        if not hasattr(mod, attr):
            raise ImportError(f"{p}: нет ожидаемого символа {attr!r}")
    return mod


def load_announcer(path=ANNOUNCER):
    """Модуль `log_session_change` — ЕДИНСТВЕННЫЙ писатель журнала объявлений.

    Схему записи не копируем: два расходящихся формата одного журнала читались бы вразнобой.
    Не загрузился — захват не выполняется (см. `announce_claim`), а не выполняется молча."""
    p = Path(path)
    if not p.exists():
        raise ImportError(f"нет модуля объявлений: {p}")
    spec = importlib.util.spec_from_file_location("_card_claim_announcer", p)
    if spec is None or spec.loader is None:
        raise ImportError(f"не удалось загрузить {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "record"):
        raise ImportError(f"{p}: нет ожидаемого символа 'record'")
    return mod


# ── карточка ─────────────────────────────────────────────────────────────────

def card_path(card, tracker_dir=DEFAULT_TRACKER):
    """Идентификатор карточки ИЛИ путь к ней → путь. Существование не проверяется."""
    p = Path(str(card))
    if p.suffix == ".md" and (p.is_absolute() or os.sep in str(card)):
        return p
    name = p.name
    if not name.endswith(".md"):
        name += ".md"
    return Path(tracker_dir) / name


def card_id(path) -> str:
    return Path(path).stem


def frontmatter(text: str) -> dict:
    """Плоские top-level `key: value` из YAML-frontmatter. Вложенные блоки пропускаются.

    Свой минимальный парсер (как в `build_tracker_board.py`): скрипт остаётся
    самодостаточным и stdlib-only, без импорта `spa_core`."""
    out: dict = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        if not raw.strip() or raw[:1].isspace():
            continue
        if ":" not in raw:
            continue
        key, _, val = raw.partition(":")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key.strip()] = val
    return out


def read_card(path):
    """(meta, None) либо (None, причина). Отсутствие карточки — причина, а не пустой словарь."""
    p = Path(path)
    if not p.exists():
        return None, f"карточки нет: {p}"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"карточка нечитаема ({exc.__class__.__name__}): {p}"
    return frontmatter(text), None


def read_card_from_base(path, base_ref=DEFAULT_BASE_REF, git=None):
    """(meta, источник) либо (None, причина) — карточка читается с базового ref.

    **Зачем.** Трекер рабочего дерева и `origin/main` расходятся по построению: пуш идёт
    прямо в origin через API, а карточка создаётся в трекере ТОГО дерева, чья копия
    `orchestrator_queue.py` запущена. На момент замера цикла #140 десять карточек жили
    ТОЛЬКО на origin — и шаг 0b отвечал о каждой `НЕ ИЗМЕРЕНО`, то есть взять их было
    нельзя никогда: fail-CLOSED-вердикт над неизвестным, который сам не может рассосаться
    (ровно класс «необратимое „не измерено“ морит очередь»).

    **Граница, названная вслух:** с origin читается ОПУБЛИКОВАННОЕ состояние захвата.
    Захват, записанный в чужом рабочем дереве и не запушенный, отсюда невидим — но он
    невидим и сегодня (сегодня невидима вся карточка), а второе плечо проверки (журнал
    объявлений, общий для всех деревьев) продолжает работать в полную силу.
    Сети проверка по-прежнему не касается: `git show` читает локальный ref, `fetch` не зовётся.
    """
    p = Path(path)
    git = git or load_sibling()._git
    rc, top, err = git(str(p.parent if p.parent.is_dir() else ROOT), "rev-parse", "--show-toplevel")
    if rc != 0 or not top.strip():
        return None, (f"карточки нет в дереве ({p}), и репозиторий для чтения с {base_ref} "
                      f"не определён: `git rev-parse --show-toplevel` rc={rc} {err.strip()[:120]!r}")
    root = Path(top.strip())
    try:
        rel = p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None, (f"карточки нет в дереве ({p}), и путь не принадлежит репозиторию {root} — "
                      f"с {base_ref} читать нечего")
    rc, out, err = git(str(root), "show", f"{base_ref}:{rel}")
    if rc != 0:
        return None, (f"карточки нет ни в дереве ({p}), ни на {base_ref} "
                      f"(`git show {base_ref}:{rel}` rc={rc} {err.strip()[:120]!r})")
    return frontmatter(out), f"{base_ref}:{rel}"


def read_card_measured(path, base_ref=DEFAULT_BASE_REF, git=None):
    """(meta, причина-если-не-прочиталась, источник). Дерево главнее базы: локальная карточка —
    рабочее состояние, база — запасной источник ровно для карточек, которых в дереве нет."""
    meta, err = read_card(path)
    if meta is not None:
        return meta, None, None
    if not Path(path).exists():
        base_meta, note = read_card_from_base(path, base_ref=base_ref, git=git)
        if base_meta is not None:
            return base_meta, None, note
        return None, note, None
    return None, err, None


# ── разбор объявлений ────────────────────────────────────────────────────────

def _norm_path(value) -> str:
    return os.path.normpath(str(value))


def _tail2(value) -> str:
    p = Path(_norm_path(value))
    return (Path(p.parent.name) / p.name).as_posix()


def repo_relative(value, root=ROOT, cache=None):
    """Путь объявления → путь ОТНОСИТЕЛЬНО репозитория, либо None, если не разрешается.

    Берётся САМЫЙ ДЛИННЫЙ хвост компонентов, существующий в текущем репо. Объявления пишут
    абсолютные пути из разных корней (`/tmp/spa_wt_c91/spa_core/tests/x.py`,
    `/Users/…/SPA_Claude/spa_core/tests/x.py`), и после снятия дерева от чужого корня не
    остаётся ничего — но хвост `spa_core/tests/x.py` в репо есть, и он ОДНОЗНАЧЕН.
    Самый длинный: у `…/spa_core/tests/x.py` существуют И `tests/x.py` (другой файл!), И
    `spa_core/tests/x.py` — правильный ответ второй.

    Хвост из ОДНОГО компонента (голое имя файла) разрешением не считается — это граница
    исходного правила («слишком много `__init__.py`»), и снимать её нельзя: в корне репо
    лежит свой `__init__.py`, поэтому `/a/one/__init__.py` и `/b/two/__init__.py` иначе
    разрешились бы в ОДИН файл. Поймано собственным обратным контролем
    `test_same_basename_alone_is_not_overlap` — правился код, не тест."""
    key = _norm_path(value)
    if cache is not None and key in cache:
        return cache[key]
    parts = Path(key).parts
    found = None
    for i in range(len(parts) - 1):                # от самого ДЛИННОГО хвоста к «каталог/имя»
        rel = Path(*parts[i:])
        if rel.is_absolute():
            continue
        if (Path(root) / rel).exists():
            found = rel.as_posix()
            break
    if cache is not None:
        cache[key] = found
    return found


def paths_overlap(a, b, root=ROOT, cache=None) -> bool:
    """Один и тот же файл в двух объявлениях.

    Порядок: полный нормализованный путь → путь относительно репо (`repo_relative`) → хвост
    «каталог/имя». Объявления пишут абсолютные host-пути, но одна и та же работа может
    объявляться из разных корней (хост-репо / worktree), поэтому хвост нужен. Совпадение
    только по имени файла намеренно НЕ считается совпадением (слишком много `__init__.py`).

    **Почему хвоста мало (замер цикла #91, воспроизведён #262).** В репозитории ДВА каталога
    тестов, и одноимённые файлы в них — норма, а не исключение: замер 16.08 даёт **35
    сталкивающихся хвостов на 72 файла** (`tests/test_signal_aggregator.py` против
    `spa_core/tests/test_signal_aggregator.py` — разные файлы с разным содержимым; тот же
    класс у `api/auth.py`, `routes/admin.py`, `adapters/__init__.py`). Хвост объявлял их
    ОДНИМ файлом, и сессия, объявившая один, запирала работу по другому на все 3 часа.
    Комментарий выше показывает, что риск осознавали, но границу провели на уровень короче.

    Сужение узкое: путь относительно репо решает исход ТОЛЬКО когда разрешились ОБА пути —
    тогда мы знаем оба файла поимённо и вправе сказать, что это разные файлы. Если хоть один
    не разрешается (файла в репо уже нет, объявлен относительный путь, чужая структура) —
    поведение прежнее, вплоть до хвоста: непонятность не покупается тишиной."""
    if _norm_path(a) == _norm_path(b):
        return True
    ra = repo_relative(a, root, cache)
    rb = repo_relative(b, root, cache)
    if ra is not None and rb is not None:
        return ra == rb
    return _tail2(a) == _tail2(b)


def is_release(entry) -> bool:
    """Объявление «работа по карточке закрыта» (`--card-state done`).

    Единственное место, где это читается: и снятие захвата карточки, и пересечение по
    файлам должны понимать терминальность ОДИНАКОВО — расхождение двух ответов на один
    вопрос и есть дефект, который чинит эта карточка."""
    return str(entry.get("card_state") or "").strip() == "done"


def releases_by_session(entries, parse_ts) -> dict:
    """Сессия → время её ПОСЛЕДНЕГО объявления `card_state: done`.

    Нужен именно максимум: сессия могла закрыть одну карточку и тут же взять следующую
    (`done` в 10:00, `claim` в 10:05) — тогда более позднее взятие остаётся живым.
    `parse_ts` — разбор времени шага 0a (та же семантика, логика не копируется)."""
    out: dict = {}
    for entry in entries or []:
        if not is_release(entry):
            continue
        session = str(entry.get("session") or "")
        ts = parse_ts(entry.get("ts"))
        if not session or ts is None:
            continue
        if session not in out or ts > out[session]:
            out[session] = ts
    return out


def entry_hit(entry, cid) -> tuple:
    """(сила, чем именно) — относится ли объявление к этой карточке. ("", "") — нет.

    **Явное поле главнее косвенного признака.** Настоящий захват ВСЕГДА несёт поле `card:`
    (`claim_card` → `announce_claim` его пишет; не смог объявить ⇒ карточка не взята,
    fail-CLOSED). Поэтому запись, которая машинно называет ДРУГУЮ карточку, захватом ЭТОЙ не
    является — что бы ни лежало в её списке файлов.

    Почему это не косметика: протокол ОБЯЗЫВАЕТ дописывать в чужие карточки (подъём
    осиротевшей работы, «независимое подтверждение», ссылки §6.4), и каждая такая дописка
    делала файл карточки СИЛЬНЫМ признаком её захвата. Живой замер (цикл #262): карточка
    `agent-card-file-in-ownership-locks-a-card-it-doesnt-claim` читалась как захваченная
    **329 часов подряд** из записи цикла #91, у которой `card:` указывает на
    `agent-signal-aggregator-tier-tests-red-after-blindness-fix`; снятие (`card_state: done`)
    ушло по тому же полю на ТУ ЖЕ другую карточку, поэтому замок не снимался НИКОГДА, а не
    «до конца окна». Обходили его вручную — то есть обесценивали сторожа.

    Ослаблением это не является, и граница проведена узко:
    - запись БЕЗ поля `card:` — не тронута вовсе (прежний СИЛЬНЫЙ признак);
    - запись с `card:` на ЭТУ карточку — прежний СИЛЬНЫЙ признак;
    - запись с `card:` на другую — признак становится СЛАБЫМ: он не исчезает из отчёта, и у
      сессии, чья жизнь ПОДТВЕРЖДЕНА, по-прежнему даёт `claimed` (слабые признаки блокируют,
      пока сессия жива — та же политика, что у упоминания в тексте: правящий файл моей
      карточки живой сосед — это настоящий конфликт по файлу, а не фантом);
    - пересечение по `--files` — независимое измерение, оно не затронуто.
    """
    card_field = str(entry.get("card") or "").strip()
    named_other = ""
    if card_field:
        if card_id(card_field) == cid:
            return STRONG, "поле `card:` в объявлении"
        named_other = card_id(card_field)
    for f in entry.get("files") or []:
        if Path(str(f)).name == f"{cid}.md":
            if named_other:
                return WEAK, ("файл карточки объявлен во владении, но запись машинно называет "
                              f"ДРУГУЮ карточку (`card: {named_other}`) — захватом ЭТОЙ "
                              "не считается")
            return STRONG, "файл карточки объявлен во владении"
    if cid and cid in str(entry.get("summary") or ""):
        return WEAK, "упоминание идентификатора в тексте объявления"
    return "", ""


# ── сборка отчёта ────────────────────────────────────────────────────────────

def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_report(cid, path, entries, self_session, sibling, *, now=None,
                 grace_hours=DEFAULT_GRACE_HOURS, ps=None, planned_files=(),
                 log_path=None, log_error=None, malformed_lines=0, card_meta=None,
                 card_error=None, self_anchor=None, card_source=None, repo_root=ROOT,
                 shared_trees=None):
    """Полный отчёт о занятости карточки. Чистая функция: ни git, ни файлов — всё на входе.

    `self_anchor` — пара (`session_pid`, `session_pid_start`) МОЕГО долгоживящего процесса или
    None. Через неё записи, сделанные этой же сессией под другими ярлыками, опознаются как свои
    (`self_identities`); None ⇒ «своей» считается ровно одна строка, как было до 01.08."""
    now = now or datetime.now(timezone.utc)
    grace = timedelta(hours=grace_hours)
    ps = ps or getattr(sibling, "_ps_lstart")
    # Считается ОДИН раз и по ВСЕМУ журналу: и захваты, и пересечение по файлам должны отвечать
    # на «моё ли это?» одинаково — иначе собственное второе объявление, не блокируя как захват,
    # блокировало бы как пересечение по файлам (один дефект, починенный наполовину).
    selves = self_identities(entries, self_session, self_anchor, sibling)
    # Личность держателя карточки берётся из ТОГО ЖЕ журнала: `claim` объявляет захват, и в
    # записи лежит долгоживущий процесс. Без этого захват из frontmatter под ярлыком без pid
    # уходил в «не измерено» навсегда — см. `durable_by_session`. Родня по ярлыку (#293) —
    # потому что у записи-захвата под переданным флагом ярлыком якоря нет по построению.
    # Ярлык держателя из frontmatter спрашивается ОТДЕЛЬНО: в журнале он есть почти всегда
    # (`claim` объявляет захват), но сторож, верный «почти», — это дыра, о которой не сказано.
    durables, kin = anchors_with_kin(
        entries, sibling,
        extra_labels=[str((card_meta or {}).get("claimed_by") or "").strip()],
        shared_trees=shared_trees)

    def _anchor_for(session, ts_raw):
        """Поля долгоживущего процесса для ярлыка — свои либо родственные, либо None.

        **Правка строго ДОПОЛНЯЮЩАЯ.** Ярлык, у которого якорь есть свой, отвечает ровно как
        до #293 — тем же выражением `durables.get`, без новых условий: это поведение защищено
        починкой #238, и трогать его здесь нечем (первая попытка провела через общее сужение
        и ОДИН существующий тест честно покраснел — `test_frontmatter_holder_measured_dead_is_stale`,
        где старт якоря фикстуры лежит позже захвата). Новый путь — только там, где раньше не
        было НИЧЕГО: у родственного ярлыка.

        Родня идёт через `borrow_durable` шага 0a, а не своим выражением: там живёт сужение
        «процесс стартовал НЕ ПОЗЖЕ записи» (родившийся после захвата написать его не мог —
        это переиспользованный ярлык, и заимствование дало бы ложный ACTIVE). Своя копия этого
        правила разошлась бы молча."""
        if session not in kin:
            return durables.get(session)
        borrowed, _why = sibling.borrow_durable({"session": session, "ts": ts_raw},
                                                durables, kin)
        return sibling.durable_fields(borrowed) or None

    report = {
        "card": cid,
        "card_path": str(path) if path else None,
        # Откуда прочитана карточка: None — из рабочего дерева; строка `<ref>:<путь>` —
        # с базового ref, потому что в дереве её НЕТ (это факт о доставке, и он говорится вслух).
        "card_source": card_source,
        "card_status": None,
        "self_session": self_session,
        "self_sessions": sorted(selves),
        "grace_hours": grace_hours,
        "now": _fmt_ts(now),
        "log": str(log_path) if log_path else None,
        "entries_scanned": 0,
        "claims": [],       # находки: кто держит карточку
        "self_claims": [],  # мои собственные захваты — не находки
        "overlaps": [],     # пересечение по объявленным файлам
        "history": [],      # информационно: старые слабые упоминания, снятые захваты
        "unmeasured": [],   # fail-CLOSED
        "verdict": FREE,
    }

    def _unmeasured(source, reason):
        report["unmeasured"].append({"source": source, "reason": reason})

    def _classify(session, ts, source, strength, detail, process=None):
        """Захват → находка / история / «не измерено». Одинаково для карточки и журнала.

        `process` — поля долгоживущего процесса ИЗ ТОЙ ЖЕ записи журнала (`session_pid` /
        `session_pid_start`). Запись сюда приходит разобранной на (session, ts), поэтому без
        явной передачи основной критерий активности (карточка `agent-durable-session-id`) до
        шага 0b просто не доехал бы — ровно тот способ «починить одного близнеца из двух»,
        которым цикл #37 оставил CI красным. Захвату из frontmatter процесс приходит из
        ЖУРНАЛА по ярлыку держателя (`durable_by_session`): в карточке лежит только ярлык, но
        `claim` объявляет захват, и личность процесса есть в той же строке журнала. Ровно тот
        же близнец: до цикла #146 «там всё как раньше» означало вечное «не измерено»."""
        rec = {"source": source, "session": session, "strength": strength, "detail": detail,
               "ts": _fmt_ts(ts) if ts else None}
        if session and session in selves:
            rec["state"] = "self"
            rec["session_state"] = ("это текущая сессия" if session == self_session else
                                    f"это текущая сессия под другим ярлыком "
                                    f"(тот же долгоживущий процесс, что у {self_session})")
            report["self_claims"].append(rec)
            return
        state, why = sibling.session_state({"session": session, "ts": rec["ts"],
                                            **(process or {})}, self_session, ps=ps)
        # Заимствование НАЗЫВАЕТСЯ вслух. Иначе отчёт про ярлык `pid64051` пишет «завершился
        # pid64036» — число из другой записи, и читателю нечем проверить вывод (живой замер
        # #303). В `kin` попадают только ярлыки, у которых СВОЕГО якоря нет нигде, поэтому
        # условие не может пометить чужим родством запись с собственной личностью.
        if process and session in kin:
            rec["kin_source"] = kin[session]
            why = (f"{why} [личность взята по РОДСТВЕННОМУ ярлыку {kin[session]!r} той же "
                   f"сессии — у {session!r} своего якоря в журнале нет]")
        rec["session_state"] = why
        age = (now - ts).total_seconds() / 3600.0 if ts else None
        rec["age_hours"] = round(age, 2) if age is not None else None
        fresh = age is not None and age <= grace.total_seconds() / 3600.0
        rec["fresh"] = fresh
        # Ждать НЕКОГО: сессия САМА объявила долгоживущий процесс, и его измеренно больше нет.
        # Тогда окно свежести отвечает не на тот вопрос — оно меряет ВРЕМЯ («может, она ещё
        # работает»), а здесь работать уже нечему. См. `durable_process_gone`: условие узкое
        # намеренно, «`ps` не нашёл pid» смертью НЕ считается (в журнале лежит pid ОДНОКРАТНОЙ
        # CLI-команды, он мёртв всегда), «не измерено» — тоже не смерть.
        orphaned = bool(sibling.durable_process_gone({"ts": rec["ts"], **(process or {})},
                                                     ps=ps))
        rec["orphaned"] = orphaned
        # Блокирует: подтверждённо ЖИВАЯ сессия (любой признак) либо свежий СИЛЬНЫЙ признак.
        # Свежий СЛАБЫЙ признак сам по себе больше НЕ блокирует — карточка
        # `agent-fresh-weak-mention-deadlocks-queue`. Причина измерена, а не предположена:
        # честный отчёт по шагу 0b обязан называть карточки поимённо («карточку X НЕ беру»),
        # циклы идут раз в час, окно свежести — 3ч ⇒ каждый отчёт перезаряжает замок раньше,
        # чем истекает предыдущий, и «блокирует только пока свеж» не наступает НИКОГДА
        # (замерено 01.08: cycle66 и cycle66i заперли ОБЕ оставшиеся карточки бэклога ровно
        # тем, что доложили об их занятости — очередь встала целиком).
        # Основание — структурная гарантия самого инструмента, та же, которой докстринг ниже
        # обосновывает старение старого слабого признака: настоящий захват ВСЕГДА несёт
        # сильный признак (`claim_card` → `announce_claim` пишет поле `card:`, не смог
        # объявить ⇒ карточка не взята, fail-CLOSED, цикл #54). Свежесть не добавляет прозе
        # доказательной силы — она лишь откладывала разблокировку.
        #
        # `not orphaned` — починка ВТОРОГО близнеца (цикл #238, карточка
        # `agent-dead-pid-still-holds-files-for-3h`). Шаг 0a получил это основание циклом #233
        # (`durable_process_gone`), шаг 0b переиспользовал у соседа `session_state` и
        # `durable_process_gone` не звал НИ РАЗУ ⇒ знание о смерти доезжало до ТЕКСТА отчёта
        # («активность: долгоживущий процесс сессии pidN завершился») и не доезжало до
        # ВЕРДИКТА («⛔ ЗАНЯТА»). Обе строки печатались в одном отчёте, и про ту же сессию в ту
        # же минуту шаг 0a говорил противоположное. Цена измерена: подъём осиротевшей работы
        # запрещался ЧЕТЫРЕ цикла подряд (#231→#232, #236, #237, #238 — замер 04:0xZ 15.08:
        # три захвата, все три `durable_process_gone`), и каждый раз запрет перебивали руками.
        # Сторож, который блокирует верное действие, учит себя игнорировать.
        #
        # Ослаблением это НЕ является: ACTIVE (подтверждённая жизнь) проверяется ПЕРВЫМ и
        # сильнее прежнего, старый сильный захват по-прежнему `stale`, «не измерено» —
        # по-прежнему код 2. Меняется ровно один исход: свежий сильный захват сессии, чья
        # смерть ИЗМЕРЕНА, становится `stale` — «кандидат на ручной подъём», а не «свободна»
        # и не «занята». Авто-захвата тут нет и не появляется.
        if state == sibling.ACTIVE or (fresh and strength == STRONG and not orphaned):
            rec["state"] = "fresh"
            report["claims"].append(rec)
            return
        if state == sibling.UNKNOWN and strength == STRONG:
            # Старый СИЛЬНЫЙ захват + активность НЕ измерена ⇒ сказать «свободна» нельзя.
            # Слабый признак сюда НЕ попадает намеренно — см. ниже.
            _unmeasured(source, f"{session}: {why}; захват от {rec['ts']} "
                                f"({rec['age_hours']}ч назад) — занятость не измерена")
            return
        if strength == STRONG:
            rec["state"] = "stale"
            report["claims"].append(rec)
        else:
            # СЛАБЫЙ признак (упоминание карточки в свободном тексте) при неподтверждённой
            # активности — в историю, независимо от возраста и от того, удалось ли измерить
            # активность. Иначе обмолвка запирает карточку: `session_state` отдаёт UNKNOWN
            # для id без pid детерминированно и необратимо, поэтому у СТАРОГО упоминания
            # старение не наступало никогда (карточка `agent-weak-mention-locks-card-forever`:
            # так были заперты `agent-durable-session-id` и `agent-idea21-verdict-data-drift`),
            # а у СВЕЖЕГО окно перезаряжалось отчётами следующих циклов
            # (`agent-fresh-weak-mention-deadlocks-queue`, замер 01.08).
            # Настоящий захват всегда несёт СИЛЬНЫЙ признак (`card:` / файл карточки во
            # владении, `announce_claim`), а старая недоставленная работа — домен шага 0a.
            # Защита от сессии, взявшей карточку в обход инструмента, при этом НЕ снята:
            # пересечение по объявленным файлам (`--files`) — независимое измерение и
            # по-прежнему даёт `CLAIMED` (см. `report["overlaps"]` в вердикте ниже).
            rec["state"] = "history"
            if state == sibling.UNKNOWN:
                rec["unmeasured_activity"] = why
            report["history"].append(rec)

    # 1. карточка ────────────────────────────────────────────────────────────
    if card_error:
        _unmeasured("card", card_error)
    else:
        meta = card_meta or {}
        report["card_status"] = meta.get("status")
        holder = str(meta.get("claimed_by") or "").strip()
        at_raw = str(meta.get("claimed_at") or "").strip()
        if holder:
            if report["card_status"] in TERMINAL_STATUSES:
                report["history"].append({
                    "source": "frontmatter", "session": holder, "ts": at_raw or None,
                    "state": "released", "strength": STRONG,
                    "detail": f"захват игнорируется: статус карточки `{report['card_status']}` "
                              f"— работа закрыта"})
            else:
                ts = sibling._parse_ts(at_raw)
                if ts is None:
                    _unmeasured("frontmatter",
                                f"claimed_by={holder!r}, но claimed_at не разобран: "
                                f"{at_raw!r} — возраст захвата не измерен")
                else:
                    _classify(holder, ts, "frontmatter", STRONG, "поле claimed_by в карточке",
                              _anchor_for(holder, at_raw))

    # 2. журнал объявлений ───────────────────────────────────────────────────
    if log_error:
        _unmeasured("announce-log", log_error)
    else:
        rows = entries or []
        report["entries_scanned"] = len(rows)
        if malformed_lines:
            _unmeasured("announce-log",
                        f"{malformed_lines} нечитаемых строк журнала — часть объявлений "
                        f"не разобрана")
        latest = {}          # сессия → последний захват этой карточки
        rel_cache = {}       # путь → путь относительно репо (одна проверка ФС на путь)
        # Сессия, объявившая `card_state: done`, работу закончила — её файлы больше не
        # «держатся» до конца окна свежести (карточка agent-card-claim-file-overlap-ignores-done).
        released_at = releases_by_session(rows, sibling._parse_ts)
        for entry in rows:
            session = str(entry.get("session") or "")
            strength, detail = entry_hit(entry, cid)
            ts = sibling._parse_ts(entry.get("ts"))
            if strength:
                if ts is None:
                    _unmeasured("announce-log",
                                f"{session or '?'}: запись относится к карточке "
                                f"({detail}), но метка времени не разобрана: "
                                f"{entry.get('ts')!r} — возраст захвата не измерен")
                elif is_release(entry):
                    latest.pop(session, None)
                    report["history"].append({
                        "source": "announce-log", "session": session, "ts": _fmt_ts(ts),
                        "state": "released", "strength": strength,
                        "detail": "объявление `card_state: done` — захват снят"})
                else:
                    latest[session] = (session, ts, strength, detail,
                                       sibling.durable_fields(entry)
                                       or _anchor_for(session, entry.get("ts")))
            # пересечение по файлам — отдельное измерение, не зависит от карточки
            if planned_files and session and session not in selves and ts is not None:
                if (now - ts) <= grace:
                    shared = sorted({str(f) for f in (entry.get("files") or [])
                                     for mine in planned_files
                                     if paths_overlap(f, mine, repo_root, rel_cache)})
                    if shared:
                        done_at = released_at.get(session)
                        if done_at is not None and done_at >= ts:
                            # Сессия объявила `done` не раньше этой записи ⇒ она закончила, а
                            # не «держит файлы ещё три часа». Ложная занятость учит игнорировать
                            # вердикт — ровно то, от чего шаг 0b и защищает.
                            report["history"].append({
                                "source": "announce-log-files", "session": session,
                                "ts": _fmt_ts(ts), "state": "released", "strength": WEAK,
                                "detail": f"пересечение по файлам ({', '.join(shared)}) не "
                                          f"считается: сессия объявила `card_state: done` "
                                          f"в {_fmt_ts(done_at)} — работа закрыта"})
                        else:
                            # Тот же вопрос, что и у захвата: ждать ли конца окна. Пересечение
                            # по файлам мерило ТОЛЬКО возраст, поэтому мёртвая сессия держала
                            # чужие файлы ровно три часа и блокировала подъём собственной же
                            # недоставленной работы. Осиротевшее пересечение не исчезает из
                            # отчёта — оно НАЗЫВАЕТСЯ отдельно (это домен шага 0a), но
                            # вердикта «ЗАНЯТА» больше не даёт.
                            # Заимствование личности нужно и здесь: пересечение по файлам —
                            # НЕЗАВИСИМОЕ измерение, и если бы оно осталось судить по голой
                            # записи, одна и та же мёртвая сессия читалась бы захватом как
                            # осиротевшая, а файлами — как живая (вердикт берёт худшее ⇒
                            # ЗАНЯТА). Починка одного близнеца из двух, #37.
                            kin_entry, _why = sibling.borrow_durable(entry, durables, kin)
                            report["overlaps"].append({
                                "session": session, "ts": _fmt_ts(ts), "files": shared,
                                "orphaned": bool(sibling.durable_process_gone(kin_entry, ps=ps)),
                                "summary": str(entry.get("summary") or "")[:160]})
        for session, ts, strength, detail, process in latest.values():
            if report["card_status"] in TERMINAL_STATUSES:
                # Закрытую карточку взять нельзя по определению ⇒ «занятость» по ней —
                # шум, который учит игнорировать вердикт. Снятие захвата объявлением
                # (`card_state: done`) работает только для ТОЙ ЖЕ сессии, а идентификатор
                # сессии сегодня не переживает CLI-команду (agent-durable-session-id) —
                # без этой ветки собственная закрытая карточка осталась бы «занятой».
                report["history"].append({
                    "source": "announce-log", "session": session, "ts": _fmt_ts(ts),
                    "state": "released", "strength": strength,
                    "detail": f"{detail}; захват не действует: статус карточки "
                              f"`{report['card_status']}` — работа закрыта"})
                continue
            _classify(session, ts, "announce-log", strength, detail, process)

    # 3. вердикт ─────────────────────────────────────────────────────────────
    verdict = FREE
    # Осиротевшее пересечение (сессия объявила долгоживущий процесс, и его нет) — это НЕ
    # «свободна»: где-то может лежать недоставленная работа по этим же файлам, и порядок
    # ровно тот же, что у старого захвата — ручная сверка по шагу 0a. Поэтому STALE, а не
    # тишина; блокировать оно перестало, исчезнуть из отчёта — не имеет права.
    live_overlaps = [o for o in report["overlaps"] if not o.get("orphaned")]
    orphaned_overlaps = [o for o in report["overlaps"] if o.get("orphaned")]
    if any(c["state"] == "stale" for c in report["claims"]) or orphaned_overlaps:
        verdict = STALE
    if any(c["state"] == "fresh" for c in report["claims"]) or live_overlaps:
        verdict = CLAIMED
    if report["unmeasured"]:
        verdict = UNCHECKED
    report["verdict"] = verdict
    return report


def exit_code(report) -> int:
    return {FREE: 0, STALE: 1, CLAIMED: 1, UNCHECKED: 2}[report["verdict"]]


_VERDICT_LINE = {
    FREE: "✅ СВОБОДНА — захватов не найдено, всё измерено. Карточку можно брать.",
    CLAIMED: "⛔ ЗАНЯТА — держит другая сессия. НЕ бери эту карточку, возьми следующую.",
    STALE: "🟡 СТАРЫЙ ЗАХВАТ — активность не подтверждена. Это кандидат на подъём "
           "осиротевшей работы: сверить ВРУЧНУЮ (шаг 0a + прогоны), отчёту не верить.",
    UNCHECKED: "❓ НЕ ИЗМЕРЕНО — занятость не установлена. Молчаливого «свободна» здесь нет.",
}


def render(report) -> str:
    out = [f"Карточка `{report['card']}` (статус: {report['card_status'] or '?'}) · "
           f"записей журнала просмотрено: {report['entries_scanned']} · "
           f"окно свежести: {report['grace_hours']}ч",
           _VERDICT_LINE[report["verdict"]]]

    if report.get("card_source"):
        out.append(f"ℹ️  карточка прочитана с `{report['card_source']}` — в рабочем дереве её НЕТ. "
                   "Захват виден ОПУБЛИКОВАННЫЙ; незапушенный захват чужого дерева отсюда "
                   "не виден (журнал объявлений проверен полностью).")

    if report["claims"]:
        out.append("")
        out.append(f"🔒 захваты ({len(report['claims'])}):")
        for c in report["claims"]:
            mark = ("осиротел" if c.get("orphaned") and c["state"] == "stale"
                    else "свежий" if c["state"] == "fresh" else "старый")
            age = f", {c['age_hours']}ч назад" if c.get("age_hours") is not None else ""
            out.append(f"  - [{mark}] {c['session']} ({c['ts']}{age}) — {c['detail']} "
                       f"[{'сильный' if c['strength'] == STRONG else 'слабый'} признак]")
            out.append(f"      активность: {c['session_state']}")
            if c.get("orphaned") and c.get("fresh"):
                out.append("      окно свежести не действует: ждать некого — объявленный "
                           "долгоживущий процесс завершился (порядок подъёма — шаг 0a)")

    live = [o for o in report["overlaps"] if not o.get("orphaned")]
    orphaned = [o for o in report["overlaps"] if o.get("orphaned")]
    if live:
        out.append("")
        out.append(f"⚠️  пересечение по объявленным файлам ({len(live)}) — "
                   f"свежие объявления других сессий держат те же файлы:")
        for o in live:
            out.append(f"  - {o['session']} ({o['ts']}): {', '.join(o['files'])}")
            out.append(f"      объявляла: {o['summary']}")
    if orphaned:
        out.append("")
        out.append(f"🕳 пересечение по файлам, но ждать некого ({len(orphaned)}) — сессия "
                   f"объявила долгоживущий процесс, и его больше нет; это НЕ занятость, а "
                   f"кандидат на ручную сверку по шагу 0a:")
        for o in orphaned:
            out.append(f"  - {o['session']} ({o['ts']}): {', '.join(o['files'])}")
            out.append(f"      объявляла: {o['summary']}")

    if report["unmeasured"]:
        out.append("")
        out.append(f"❓ НЕ ИЗМЕРЕНО ({len(report['unmeasured'])}) — "
                   f"молчаливого «свободна» здесь не будет:")
        for u in report["unmeasured"]:
            out.append(f"  - [{u['source']}] {u['reason']}")

    others = [s for s in report.get("self_sessions", []) if s != report["self_session"]]
    if others:
        # Опознание чужого ЯРЛЫКА как своего — не находка, но и не молчаливая поблажка:
        # по какому измерению это решено, должно быть видно в отчёте.
        out.append("")
        out.append(f"ℹ️  мои же объявления под другими ярлыками ({len(others)}) — опознаны по "
                   f"совпадению долгоживущего процесса (pid + время старта): "
                   f"{', '.join(others)}")

    if report["self_claims"]:
        out.append("")
        out.append("ℹ️  собственные захваты (не находки):")
        for c in report["self_claims"]:
            out.append(f"  - {c['session']} ({c['ts']}) — {c['detail']}")

    if report["history"]:
        out.append("")
        out.append("🕓 история (не находки):")
        for h in report["history"]:
            out.append(f"  - {h['session']} ({h.get('ts') or '-'}) — {h['detail']}")
    return "\n".join(out)


# ── чтение окружения ─────────────────────────────────────────────────────────

def self_session_id() -> str:
    return os.environ.get("SPA_SESSION_ID") or f"pid{os.getpid()}"


_SIBLING_CACHE = []          # список-на-один-элемент: загруженный модуль шага 0a


def _sibling_cached(loader=None):
    """Соседний модуль шага 0a, загруженный ОДИН раз на процесс.

    `load_sibling` исполняет файл заново при каждом вызове (это не `import` — `scripts/` не
    пакет), а `anchor_of` зовётся по записи журнала: без кэша разбор 908 записей означал бы
    908 исполнений 1700-строчного модуля. Ошибку загрузки не глотаем — она и раньше означала
    «не измерено», а не «свободна»."""
    if not _SIBLING_CACHE:
        _SIBLING_CACHE.append((loader or load_sibling)())
    return _SIBLING_CACHE[0]


def anchor_of(entry, sibling=None):
    """``(pid, «старт verbatim»)`` или None — ИЗМЕРЕННАЯ личность процесса, написавшего запись.

    **Определение ОДНО и живёт у шага 0a** (`check_undelivered_work.anchor_of`); здесь —
    делегирование. Раньше пара `anchor_of`/`durable_by_session` жила только тут, а шаг 0a
    задать тот же вопрос не мог и уводил запись без якоря в необратимое «не измерено»
    (цикл #265). Копировать разбор во второй файл было нельзя: копии расходятся молча, а
    зависимость между модулями односторонняя — `check_card_claim` грузит соседа, не наоборот.

    Смысл измерения не изменился: требуются ОБА поля, `session_pid` без `session_pid_start`
    личностью не считается (pid переиспользуется ОС, «тот же номер» без времени старта — не
    «тот же процесс»). Здесь пара отвечает на вопрос «эта запись моя?», у соседа — «жива ли
    сессия»; измерение одно."""
    return (sibling or _sibling_cached()).anchor_of(entry)


def measure_self_anchor(announcer=None, env=None):
    """Мой собственный якорь или None. Меряет ТОТ ЖЕ код, что пишет его в журнал.

    `log_session_change.durable_process` отдаёт пару только когда объявленный `SPA_SESSION_PID`
    — процесс, существующий В МОМЕНТ ВЫЗОВА, и записывает его время старта вербатим. Не
    объявлен / не подтверждён / модуль не загрузился ⇒ None, и всё поведение остаётся ровно
    прежним: «наверное, это я» здесь не появляется ни в одной ветке."""
    try:
        announcer = announcer or load_announcer()
        proc, _why = announcer.durable_process(env)
    except (ImportError, OSError, SyntaxError, AttributeError, TypeError, ValueError):
        return None
    return anchor_of(proc)


def self_identities(entries, self_session, anchor, sibling=None):
    """Все идентификаторы, под которыми объявлялась ЭТА ЖЕ сессия (множество, ≥1 элемент).

    **Дефект, который это закрывает** (карточка `agent-self-claim-blocked-by-own-second-identity`,
    найден догфудом цикла #67, независимо воспроизведён циклом #70). Идентификатор сессии — это
    ЯРЛЫК: без `SPA_SESSION_ID` его выдаёт `log_session_change._session_id()` из pid ОДНОКРАТНОЙ
    CLI-команды, поэтому у каждой команды одной и той же сессии он свой. «Своей» же признавалась
    ровно одна строка (`session == self_session`), и любое второе объявление той же сессии
    читалось как ЧУЖОЙ захват. Замерено дословно:

    * `claim … --session cycle67` → отказ по захвату `pid72203` **(это тоже я)**;
      `claim … --session pid72203` → отказ по захвату `cycle67` **(и это я)** — круговая
      блокировка, из которой нет выхода флагом: у `claim` нет `--force`;
    * штатной пары `claim` … `release` (её предписывает протокол) достаточно и без двух
      объявлений: это две разные CLI-команды ⇒ два разных ярлыка (цикл #70: взял `pid15267`,
      снять пытался `pid17106` — «снять чужой захват можно только с --force»).

    **Решение — не самозаявление, а измерение.** Ярлык нестабилен, а долгоживущий процесс
    сессии — нет: пара (`session_pid`, `session_pid_start`) записывается только после того, как
    процесс подтверждён, и время старта делает её личностью, а не номером. Две записи с
    ОДИНАКОВЫМ якорем написаны одним и тем же процессом — это факт, а не допущение, поэтому
    ярлыки таких записей — мои.

    **Почему это не ослабляет защиту от коллизии #46** (положительные контроли — в тестах):
    чужая запись несёт ДРУГОЙ якорь либо не несёт его вовсе ⇒ блокирует как прежде; тот же pid
    с другим временем старта (переиспользованный номер) — НЕ я; без подтверждённого
    `SPA_SESSION_PID` якоря нет, и поведение побайтово прежнее. Присвоить себе чужой ярлык можно
    было бы только объявив ЧУЖОЙ живой процесс своим — то есть солгав в `SPA_SESSION_PID`; это
    тот же уровень доверия, что и существующий `release --force`, и он ничего не обходит молча:
    все распознанные ярлыки печатаются в отчёте (`self_sessions`).

    Дешёвая профилактика при этом остаётся главной: выставить `SPA_SESSION_ID` и
    `SPA_SESSION_PID` ДО первого объявления (это делает `scripts/agent_orchestrator.sh`) —
    тогда ярлык один и якорь есть у каждой записи цикла."""
    selves = {str(self_session)} if self_session else set()
    if not anchor:
        return selves
    sibling = sibling or _sibling_cached()          # один разбор на прогон, см. `anchor_of`
    for entry in entries or ():
        if anchor_of(entry, sibling) == anchor:
            label = str((entry or {}).get("session") or "").strip()
            if label:
                selves.add(label)
    return selves


def durable_by_session(entries, sibling):
    """сессия → её поля долгоживущего процесса, ТОЛЬКО когда они однозначны. Иначе ключа нет.

    **Определение ОДНО и живёт у шага 0a** (`check_undelivered_work.durable_by_session`,
    перенесено циклом #265 — тому же вопросу понадобился и сосед); здесь — делегирование,
    сигнатура не тронута ради вызывающих.

    **Дефект, который это закрывает** (найден догфудом цикла #146). Захват из frontmatter
    классифицировался с `process=None`, а `session_state` для ярлыка без pid (`cycle-20906`,
    `cycle-63608`) отдаёт `UNKNOWN` детерминированно и НЕОБРАТИМО ⇒ старый СИЛЬНЫЙ захват
    навсегда уходил в «не измерено» (fail-CLOSED, код 2, «брать нельзя»). Замерено 07.08:
    так были заперты `inbox-kartochka-sozdannaya-posredi-tsikla-ne-d` (8.7ч),
    `inbox-tier-c-171-iz-180-modulei-ne-otvechayut` (14.7ч) и
    `agent-fleet-parity-guard-never-scheduled` (44ч) — вердикт, который не может проясниться
    сам, потому что захватившая сессия мертва, а её личность инструмент не спрашивал.

    **Личность при этом БЫЛА** — в том же журнале, который инструмент уже читает: `claim`
    объявляет захват (`announce_claim`), и запись несёт `session_pid` + `session_pid_start`.
    Прочитать их — не ослабление сторожа, а недостающее ИЗМЕРЕНИЕ: живой процесс теперь даёт
    `ACTIVE` и блокирует СИЛЬНЕЕ прежнего (раньше живой держатель тоже читался как «не
    измерено»), мёртвый — честный `stale`, то есть кандидат на ручной подъём по шагу 0a, а не
    разрешение забрать работу. Класс — зеркало fail-OPEN: необратимое «не измерено» над
    познаваемым фактом это вечный замок (карточка `agent-weak-mention-locks-card-forever`).

    **Однозначность обязательна.** Ярлык — не идентификатор процесса, и один и тот же ярлык
    в принципе может нести разные якоря (перезапуск цикла под тем же `SPA_SESSION_ID`).
    Разные пары ⇒ ключа нет ⇒ поведение побайтово прежнее (fail-CLOSED): угадывать, который
    из процессов держит карточку, инструмент не станет."""
    return sibling.durable_by_session(entries)


def anchors_with_kin(entries, sibling, extra_labels=(), shared_trees=None):
    """То же, плюс родня по ярлыку: `(ярлык → поля, ярлык → откуда взято)`.

    **Определение ОДНО и живёт у шага 0a** (`check_undelivered_work.anchors_with_kin`) — здесь
    делегирование, как и у `durable_by_session` выше.

    **Зачем шагу 0b именно родня (цикл #293).** Протокол сам велит держателю передавать свой
    идентификатор флагом (`--session pidN`, карточка `agent-durable-session-id`), а
    `log_session_change.record` намеренно НЕ ставит якорь на переданный ярлык — иначе чужая
    запись читалась бы как своя. Оба правила верны, а вместе дают запись-захват, у которой
    якоря нет ПО ПОСТРОЕНИЮ: `durable_by_session` для неё пуст, `session_state` отдаёт вечный
    `UNKNOWN`, и захват висит «занята», пока свеж, — а ждать уже некого. Якорь той же сессии
    при этом лежит секундами позже под ярлыком `cycle-N-pidN`.

    Точность важна: у ГОЛОГО ярлыка `pidN` активность читается прямо из ярлыка, поэтому
    состарившийся захват уходил в `stale` и без родства (измерено, а не предположено) — дефект
    жил ровно в окне свежести. Вечное «не измерено» тот же разрыв даёт у СОСТАВНОГО ярлыка.

    `shared_trees` — деревья, общие для многих сессий (главное рабочее дерево): в них «то же
    дерево» не значит «та же сессия». `None` = не измерено ⇒ родство по дереву выключено
    (цикл #303, второй признак родства — см. докстринг шага 0a)."""
    return sibling.anchors_with_kin(entries, extra_labels, shared_trees=shared_trees)


def _log_entries(log, sibling=None, last=None):
    """Записи журнала или `[]` — тем же читателем, что и `gather`.

    `[]` при любой неудаче чтения — это НЕ «журнал пуст»: единственный потребитель
    (`release_card`) от этого лишь теряет дополнительные ярлыки и остаётся при прежнем,
    отказывающем поведении. Направление fail-CLOSED."""
    try:
        sibling = sibling or load_sibling()
        path = Path(log)
        if not path.exists():
            return []
        entries, _malformed = sibling.read_entries(path, last)
        return entries
    except (ImportError, OSError, SyntaxError, AttributeError, TypeError, ValueError):
        return []


def gather(card, *, log=DEFAULT_LOG, tracker_dir=DEFAULT_TRACKER, sibling=None,
           self_session=None, now=None, grace_hours=DEFAULT_GRACE_HOURS,
           planned_files=(), last=None, ps=None, self_anchor=_ENV_ANCHOR,
           base_ref=DEFAULT_BASE_REF, repo_root=ROOT, shared_trees=_MEASURE_TREES):
    """Прочитать карточку + журнал и собрать отчёт (файловый слой над `build_report`).

    `self_anchor` — мой долгоживущий процесс (`anchor_of`-пара) для опознания собственных
    объявлений под другими ярлыками; умолчание меряет его из окружения
    (`measure_self_anchor`), `None` отключает опознание (герметичные тесты)."""
    sibling = sibling or load_sibling()
    path = card_path(card, tracker_dir)
    meta, card_error, card_source = read_card_measured(path, base_ref=base_ref,
                                                       git=getattr(sibling, "_git", None))

    entries, malformed, log_error = [], 0, None
    log_path = Path(log)
    if not log_path.exists():
        log_error = f"{log_path}: журнала объявлений нет — занятость по журналу НЕ проверена"
    else:
        try:
            entries, malformed = sibling.read_entries(log_path, last)
        except OSError as exc:
            log_error = f"{log_path}: журнал нечитаем ({exc.__class__.__name__})"

    if self_anchor is _ENV_ANCHOR:
        self_anchor = measure_self_anchor()

    if shared_trees is _MEASURE_TREES:
        # Главное рабочее дерево общее для ВСЕХ сессий (журнал: 101 ярлык, 17 разных якорей) —
        # родством оно быть не может. Не измерилось ⇒ None ⇒ признак выключен, а не «нет общих».
        main_tree, _err = sibling.main_worktree(repo_root)
        shared_trees = (str(main_tree),) if main_tree else None

    return build_report(card_id(path), path, entries,
                        self_session or self_session_id(), sibling,
                        now=now, grace_hours=grace_hours, ps=ps,
                        planned_files=planned_files, log_path=log_path,
                        log_error=log_error, malformed_lines=malformed,
                        card_meta=meta, card_error=card_error, self_anchor=self_anchor,
                        card_source=card_source, repo_root=repo_root,
                        shared_trees=shared_trees)


# ── взятие / освобождение карточки ───────────────────────────────────────────

def _atomic_write(path: Path, content: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _set_claim_fields(text: str, values) -> str:
    """Проставить/убрать `claimed_by`/`claimed_at` во frontmatter.

    `values=None` — убрать. Всё остальное содержимое сохраняется байт-в-байт (как
    `queue.set_status`): карточка — источник правды, инструмент трогает ровно свои строки."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ClaimError("во frontmatter карточки нет открывающего `---` — не трогаю файл")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ClaimError("frontmatter карточки не закрыт `---` — не трогаю файл")

    kept = []
    for i, ln in enumerate(lines):
        if 0 < i < end and not ln[:1].isspace():
            key = ln.partition(":")[0].strip()
            if key in _CLAIM_KEYS:
                continue
        kept.append(ln)
    if values is None:
        return "".join(kept)

    end = next(i for i in range(1, len(kept)) if kept[i].strip() == "---")
    insert = [f"claimed_by: {values['claimed_by']}\n",
              f"claimed_at: {values['claimed_at']}\n"]
    reason = str(values.get("claim_takeover_reason") or "").strip()
    if reason:
        # Однострочно и без переводов строки: frontmatter здесь разбирается построчно,
        # многострочное значение развалило бы его у КАЖДОГО читателя карточки.
        insert.append("claim_takeover_reason: " + " ".join(reason.split()) + "\n")
    return "".join(kept[:end] + insert + kept[end:])


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".claimlock")


def _acquire_lock(path: Path):
    """`O_EXCL`-файл на время правки карточки. Занят — отказ (а не ожидание и не снос)."""
    lock = _lock_path(path)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        try:
            age = datetime.now(timezone.utc).timestamp() - lock.stat().st_mtime
        except OSError:
            age = 0.0
        hint = (f" Файл блокировки старше {LOCK_STALE_SEC}с ({age:.0f}с) — похоже, брошен; "
                f"проверь и удали вручную: {lock}" if age > LOCK_STALE_SEC else "")
        raise ClaimError(f"карточку сейчас правит другая сессия (есть {lock.name}).{hint}")
    os.write(fd, f"{self_session_id()}\n".encode())
    return fd, lock


def _release_lock(fd, lock: Path) -> None:
    os.close(fd)
    try:
        os.unlink(lock)
    except OSError:
        pass


def announce_claim(cid, path, session, state, log, announcer=None, summary=""):
    """Записать захват/освобождение в ОБЩИЙ журнал объявлений. Не смог — бросить.

    **Зачем.** Захват (`claimed_by` во frontmatter) живёт в файле карточки, а файл карточки —
    в рабочем дереве сессии. Пока сессия не запушила, с origin и из хост-репо карточка выглядит
    СВОБОДНОЙ, и следующий цикл честно проходит шаг 0b, получает `free` и делает ту же работу
    второй раз (ровно столкновение #46, только с другого входа). Журнал же живёт в главном
    дереве (`log_session_change._shared_log`) — запись в нём видна отовсюду немедленно, без
    пуша, и её читает `entry_hit` как СИЛЬНЫЙ признак (поле `card:`).

    **Почему это делается ДО правки карточки.** Если упасть между двумя записями, безопасное
    направление — «в журнале захват есть, во frontmatter нет»: следующая сессия увидит
    занятость и возьмёт другую карточку. Обратный порядок дал бы захват, о котором не знает
    никто, — то самое состояние, которое эта функция и закрывает."""
    announcer = announcer or load_announcer()
    announcer.record(
        summary=summary or (f"[check_card_claim] захват карточки {cid}" if state == "claim"
                            else f"[check_card_claim] захват карточки {cid} снят"),
        files=[str(path)], verified="", card=cid, card_state=state, log=log,
        session=session)


def _unannounce_claim(cid, path, session, log, announcer=None):
    """Снять УЖЕ объявленный захват, если сама карточка взята не была.

    **Зачем.** Объявление идёт ДО правки карточки (см. `announce_claim`) — это защита от смерти
    посередине. Но если правка потом отказала (карточку успела взять другая сессия), в общем
    журнале остаётся запись «cycle NNN держит карточку» о карточке, которой сессия НЕ владеет:
    следующий цикл пропустит СВОБОДНУЮ карточку по ложной занятости. Направление ошибки
    безопасное (ложная занятость дешевле ложной свободы), но это ровно тот класс, который
    проект и вычищает, — утверждение о состоянии, которого нет. Компенсируем `card_state: done`
    (в схеме журнала — «захват снят»).

    Не смогли компенсировать — молчать нельзя, но и отказ по этой причине не усиливаем: вызов
    и так завершается отказом, а ложная занятость сама истечёт по окну свежести. Причина
    дописывается в предупреждение на stderr, чтобы её было видно в логе цикла."""
    try:
        announce_claim(cid, path, session, "done", log, announcer,
                       summary=f"[check_card_claim] захват карточки {cid} НЕ состоялся "
                               f"(карточку держит другая сессия) — объявленный захват снят")
    except (ImportError, OSError, SyntaxError, AttributeError, TypeError, ValueError) as exc:
        print(f"⚠️  захват {cid} объявлен, но отказ не компенсирован в журнале ({log}): "
              f"{exc.__class__.__name__}: {exc}. До конца окна свежести карточка будет "
              f"читаться занятой сессией {session}.", file=sys.stderr)


def claim_card(card, *, log, session=None, tracker_dir=DEFAULT_TRACKER, now=None,
               grace_hours=DEFAULT_GRACE_HOURS, sibling=None, ps=None,
               announcer=None, self_anchor=_ENV_ANCHOR, takeover_reason=""):
    """Взять карточку. Отказ, если её держит другая сессия или занятость не измерена.

    Захват всегда сопровождается записью в общем журнале объявлений: «взял, но не объявил» —
    состояние, из-за которого работа цикла #52 была невидима, — здесь невозможно по
    построению. Не удалось объявить ⇒ карточка НЕ берётся (fail-CLOSED, инв. #2).

    ``takeover_reason`` — ПОДЪЁМ осиротевшего захвата (вердикт ``stale``) с названной
    причиной. Зачем отдельное слово (замер цикла #358, живой случай)
    ------------------------------------------------------------------------------
    Протокол называет ``stale`` «кандидатом на ручной подъём осиротевшей работы» — то есть
    ПРЯМО предписывает взять такую карточку, сверив работу вручную. Инструмент же отказывал
    без единого способа согласиться: `claim` на `stale` бросал `ClaimError`, флага не было.
    Сессия, которая всё сделала по протоколу, оставалась без пометки на карточке — и
    следующий цикл видел тот же осиротевший захват умершей сессии, а не живой. Ровно тот
    класс, что цикл #354 закрыл словом ``dropped`` у уборщика: **у законного действия не
    было имени, поэтому оно выглядело нарушением.**

    Ослаблением это НЕ является, и направление ошибки не меняется:

    * подъём разрешён ТОЛЬКО при вердикте ``stale``. ``claimed`` (подтверждённо живая
      сессия) и ``unchecked`` (занятость не измерена) отказывают как прежде — там подъём и
      был бы кражей работы либо решением без измерения;
    * причина ОБЯЗАТЕЛЬНА и непустая: «подъём» без основания закрыл бы что угодно, и это
      единственное, чем он отличается от молчаливого перехвата;
    * причина уезжает в ОБЩИЙ журнал объявлений и во frontmatter карточки — подъём
      становится видимым событием, а не отсутствием записи.

    `log` — ОБЯЗАТЕЛЬНЫЙ аргумент, см. `release_card`."""
    sibling = sibling or load_sibling()
    session = session or self_session_id()
    now = now or datetime.now(timezone.utc)
    path = card_path(card, tracker_dir)
    if not path.exists():
        # `check` умеет прочитать карточку с базового ref, а взятие — правка ФАЙЛА, и
        # молча материализовать чужой файл в дереве захват не вправе (это доставка, а не
        # захват). Поэтому отказ, но с названной причиной и готовой командой — иначе
        # сообщение «карточки нет» противоречило бы `check`, который её только что прочёл.
        on_base, _ = read_card_from_base(path, git=getattr(sibling, "_git", None))
        if on_base is not None:
            raise ClaimError(
                f"карточки нет в этом дереве ({path}), но она ЕСТЬ на {DEFAULT_BASE_REF}. "
                f"Забери её в своё дерево и пушь вместе с работой:\n"
                f"  git show {DEFAULT_BASE_REF}:nimbalyst-local/tracker/{path.name} > {path}")
        raise ClaimError(f"карточки нет: {path}")

    if self_anchor is _ENV_ANCHOR:
        self_anchor = measure_self_anchor()
    if not self_anchor:
        raise UnmeasurableClaim(_UNMEASURABLE_CLAIM_TEXT.format(session=session, card=card))
    report = gather(card, log=log, tracker_dir=tracker_dir, sibling=sibling,
                    self_session=session, now=now, grace_hours=grace_hours, ps=ps,
                    self_anchor=self_anchor)
    selves = set(report.get("self_sessions") or [session])
    takeover_reason = str(takeover_reason or "").strip()
    stale_holders = {c.get("session") for c in report.get("claims") or []
                     if c.get("state") == "stale"}
    lifting = bool(takeover_reason) and report["verdict"] == STALE
    if report["verdict"] in (CLAIMED, UNCHECKED) or (report["verdict"] == STALE and not lifting):
        hint = ""
        if report["verdict"] == STALE:
            # Отказ обязан НАЗЫВАТЬ выход: иначе следующая сессия сделает ровно то, что
            # сделала эта — обойдёт инструмент руками, и захват снова останется невидимым.
            hint = ("\nЭто осиротевший захват. Протокол разрешает ПОДЪЁМ после ручной сверки "
                    "(шаг 0a + свои прогоны, отчёту умершей сессии не верить):\n"
                    f"  python3 scripts/check_card_claim.py claim {card_id(path)} "
                    "--takeover \"<чем сверил, что работа не потеряна>\"")
        raise ClaimError(f"вердикт `{report['verdict']}` — карточка не взята.\n"
                         + render(report) + hint)

    try:
        summary = ""
        if lifting:
            summary = (f"[check_card_claim] ПОДЪЁМ осиротевшего захвата карточки "
                       f"{card_id(path)} (было: {', '.join(sorted(h for h in stale_holders if h)) or '?'}) "
                       f"— основание: {takeover_reason}")
        announce_claim(card_id(path), path, session, "claim", log, announcer, summary=summary)
    except (ImportError, OSError, SyntaxError, AttributeError, TypeError, ValueError) as exc:
        raise AnnounceError(
            f"захват НЕ объявлен в журнале ({log}): {exc.__class__.__name__}: {exc}. "
            f"Карточка не взята — необъявленный захват невидим для следующего цикла "
            f"(это и есть дефект, который правило закрывает).") from exc

    fd, lock = _acquire_lock(path)
    try:
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        holder = str(meta.get("claimed_by") or "").strip()
        # Правило «держит ли кто-то карточку» здесь ДОЛЖНО совпадать с вердиктом `gather`:
        # на карточке в терминальном статусе захват не действует (это уже действующее правило,
        # цикл #50 — `TERMINAL_STATUSES`). Иначе одна функция противоречит сама себе: вердикт
        # говорит «СВОБОДНА», а запись отказывает «успела взять» — измерено 31.07 на этой самой
        # карточке (status `done`, `claimed_by` умершей pid94637).
        if str(meta.get("status") or "").strip() in TERMINAL_STATUSES:
            holder = ""
        if holder and lifting and holder in stale_holders:
            # Подъём перебивает ИМЕННО тот захват, который отчёт назвал осиротевшим, и
            # только его. Появившийся между проверкой и правкой ЧУЖОЙ живой захват (гонка)
            # ниже по-прежнему отказывает — иначе флаг подъёма стал бы отмычкой.
            holder = ""
        if holder and holder not in selves:
            # Гонка: захват появился между проверкой и правкой. `selves` — не только мой
            # текущий ярлык: карточку могла взять ЭТА ЖЕ сессия предыдущей командой под другим
            # ярлыком (`self_identities`), и тогда это не гонка, а собственный захват.
            _unannounce_claim(card_id(path), path, session, log, announcer)
            raise ClaimError(f"карточку успела взять сессия {holder} — не перезаписываю")
        fields = {"claimed_by": session, "claimed_at": _fmt_ts(now)}
        if lifting:
            # Основание подъёма живёт В КАРТОЧКЕ, а не только в журнале: карточка уезжает
            # на origin, журнал — нет. Без этой строки следующий читатель видит смену
            # владельца без объяснения, то есть снова «утверждение без измерения».
            fields["claim_takeover_reason"] = takeover_reason
        new = _set_claim_fields(text, fields)
        _atomic_write(path, new)
    finally:
        _release_lock(fd, lock)
    out = {"card": card_id(path), "path": str(path), "claimed_by": session,
           "claimed_at": _fmt_ts(now), "anchored": bool(self_anchor)}
    if lifting:
        out["takeover_from"] = sorted(h for h in stale_holders if h)
        out["takeover_reason"] = takeover_reason
    return out


def release_card(card, *, log, session=None, tracker_dir=DEFAULT_TRACKER, force=False,
                 announcer=None, sibling=None, self_anchor=_ENV_ANCHOR):
    """Отпустить карточку. Чужой захват без `--force` не снимается.

    **`log` — ОБЯЗАТЕЛЬНЫЙ аргумент, у пишущих путей умолчания нет** (карточка
    `agent-claim-guard-tests-write-a-real-announce-journal`, цикл #106). Раньше здесь стояло
    `log=DEFAULT_LOG`, и «забыть `log=`» означало не ошибку, а ТИХУЮ запись в настоящий
    журнал координации — тот самый, который читают шаги 0a и 0b протокола. Замерено на
    четырёх вызовах в `spa_core/tests/test_card_claim_guard.py`: файла
    `data/session_changes.jsonl` в свежем worktree не было вовсе, один прогон набора создавал
    его и клал туда 2 записи (`pid1` и `pid999`, карточка `agent-x`), каждый следующий прогон
    добавлял ещё 2 — монотонно.

    Обоих последствий по отдельности достаточно, чтобы умолчания не было:

    * **запись не туда.** Оба кандидата в умолчание неверны, и это ЗАМЕР, а не вкус:
      `DEFAULT_LOG` — дерево ЭТОГО файла, то есть из worktree захват уезжает в журнал,
      которого не видит никто (а `announce_claim` существует ровно затем, чтобы захват был
      виден немедленно и без пуша); `shared_log()` (умолчание CLI) — ГЛАВНОЕ дерево, то есть
      прогон набора из любого worktree писал бы выдуманные захваты прямо в живой журнал
      хост-репо (394 записи на момент замера). Вариант «просто поменять умолчание» делает
      тестовое загрязнение строго хуже, а не лучше;
    * **вердикт зависит от истории, а не от кода.** `selves` строится из `log`, поэтому
      содержимое файла меняет ответ функции. Воспроизведено на неизменном коде: одна и та же
      карточка (`claimed_by: pid999`) при пустом журнале даёт отказ, а при одной записи с
      ярлыком `pid999` под якорем текущего процесса — НЕ даёт. Проверка, утверждающая то,
      чего не измеряла, — тот же класс, что и сама карточка.

    Теперь «забыть `log=`» — `TypeError` в точке вызова, а не тихая запись в чужой файл
    (fail-CLOSED). Единственный не-тестовый вызывающий — CLI `main()` — журнал задаёт явно
    (`sibling.shared_log()[0]`), поэтому поведение прода не меняется; гейт против возврата
    умолчания — `spa_core/tests/test_claim_guard_writes_are_hermetic.py`.

    «Чужой» решается по `self_identities`, а не по одному ярлыку: `claim` и `release` — ДВЕ
    разные CLI-команды, поэтому без `SPA_SESSION_ID` у них разные ярлыки, и сессия отказывала
    сама себе (цикл #70: взял `pid15267`, снять пытался `pid17106`). Обход существовал —
    `--force`, — но он снимает и НАСТОЯЩИЙ чужой захват, то есть «просто пользоваться --force»
    обесценивает саму проверку. Журнал не прочитался ⇒ ярлык остаётся один и отказ прежний.

    Освобождение тоже объявляется (`card_state: done` — в схеме журнала это и означает
    «захват снят», см. докстринг `log_session_change`): иначе снятый захват остался бы в
    журнале живым до конца окна свежести и карточка выглядела бы занятой после release.
    Порядок здесь обратный захвату — сначала карточка, потом журнал: направление ошибки при
    падении посередине то же самое (карточка выглядит занятой, а не свободной)."""
    session = session or self_session_id()
    path = card_path(card, tracker_dir)
    if not path.exists():
        raise ClaimError(f"карточки нет: {path}")
    if self_anchor is _ENV_ANCHOR:
        self_anchor = measure_self_anchor()
    # Без якоря журнал не читается ВООБЩЕ: опознавать нечем, а лишнее чтение общего файла
    # сделало бы поведение `release` зависящим от чужих записей. Нет якоря ⇒ ровно старый путь.
    selves = ({session} if not self_anchor
              else self_identities(_log_entries(log, sibling), session, self_anchor))
    fd, lock = _acquire_lock(path)
    try:
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        holder = str(meta.get("claimed_by") or "").strip()
        if not holder:
            return {"card": card_id(path), "path": str(path), "released": False,
                    "detail": "захвата не было"}
        if holder not in selves and not force:
            raise ClaimError(f"карточку держит {holder}, а не {session}; "
                             f"снять чужой захват можно только с --force")
        _atomic_write(path, _set_claim_fields(text, None))
    finally:
        _release_lock(fd, lock)
    try:
        announce_claim(card_id(path), path, holder, "done", log, announcer)
    except (ImportError, OSError, SyntaxError, AttributeError, TypeError, ValueError) as exc:
        # Карточка уже отпущена; не объявленным осталось только снятие ⇒ в журнале захват
        # доживёт окно свежести и карточка будет выглядеть ЗАНЯТОЙ. Направление безопасное,
        # но молчать об этом нельзя — иначе следующая сессия не поймёт, почему `claimed`.
        raise AnnounceError(
            f"карточка {card_id(path)} ОТПУЩЕНА, но снятие захвата не объявлено в журнале "
            f"({log}): {exc.__class__.__name__}: {exc}. До конца окна свежести она будет "
            f"читаться занятой — объяви `--card-state done` вручную.") from exc
    return {"card": card_id(path), "path": str(path), "released": True, "was": holder}


def list_claimed(tracker_dir=DEFAULT_TRACKER):
    """Все карточки с непустым `claimed_by` (терминальные статусы отмечаются, но не скрываются)."""
    out = []
    d = Path(tracker_dir)
    if not d.exists():
        return out
    for p in sorted(d.glob("*.md")):
        meta, err = read_card(p)
        if err or not meta:
            continue
        holder = str(meta.get("claimed_by") or "").strip()
        if not holder:
            continue
        status = meta.get("status", "")
        out.append({"card": p.stem, "claimed_by": holder,
                    "claimed_at": meta.get("claimed_at", ""), "status": status,
                    "stale": status in TERMINAL_STATUSES})
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Шаг 0b: занята ли карточка другой сессией (детерминированно, read-only).")
    ap.add_argument("--tracker-dir", default=str(DEFAULT_TRACKER))
    # Умолчание разрешается в ГЛАВНОЕ рабочее дерево (`shared_log`), а не в дерево этого файла:
    # запущенный из worktree — а протокол §3.4 обязывает работать именно там — шаг 0b иначе
    # читает свой пустой журнал и отвечает «НЕ ИЗМЕРЕНО» о ЛЮБОЙ карточке. Явный флаг главнее.
    ap.add_argument("--log", default=None, help="журнал объявлений (JSONL)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="проверить занятость (ничего не пишет)")
    c.add_argument("card", help="идентификатор карточки или путь к ней")
    c.add_argument("--files", nargs="*", default=[],
                   help="файлы, которые я собираюсь править — проверить пересечение")
    c.add_argument("--grace-hours", type=float, default=DEFAULT_GRACE_HOURS)
    c.add_argument("--last", type=int, default=None, help="сколько последних записей журнала")
    # Своя же сессия иначе читается как чужая: `log_session_change.py` пишет pid ОДНОКРАТНОГО
    # CLI-процесса, поэтому у каждой команды сессии он свой (карточка `agent-durable-session-id`).
    c.add_argument("--session", default=None,
                   help="идентификатор МОЕЙ сессии из объявления (напр. pid72474) — "
                        "иначе собственное объявление читается как чужой захват")

    k = sub.add_parser("claim", help="взять карточку (пишет claimed_by/claimed_at)")
    k.add_argument("card")
    k.add_argument("--session", default=None)
    k.add_argument("--grace-hours", type=float, default=DEFAULT_GRACE_HOURS)
    k.add_argument("--takeover", metavar="ПРИЧИНА", default="",
                   help="ПОДЪЁМ осиротевшего захвата (только при вердикте `stale`): чем "
                        "сверил, что работа умершей сессии не потеряна. Пустая причина не "
                        "принимается; `claimed`/`unchecked` этот флаг НЕ снимает.")

    r = sub.add_parser("release", help="отпустить карточку")
    r.add_argument("card")
    r.add_argument("--session", default=None)
    r.add_argument("--force", action="store_true", help="снять ЧУЖОЙ захват")

    sub.add_parser("list", help="все карточки с активным захватом")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        rows = list_claimed(args.tracker_dir)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        elif not rows:
            print("захваченных карточек нет")
        else:
            for row in rows:
                tail = "  (статус терминальный — захват не действует)" if row["stale"] else ""
                print(f"{row['card']}: {row['claimed_by']} с {row['claimed_at']} "
                      f"[{row['status']}]{tail}")
        return 0

    try:
        sibling = load_sibling()
    except (ImportError, OSError, SyntaxError) as exc:
        payload = {"verdict": UNCHECKED, "card": str(args.card),
                   "unmeasured": [{"source": "sibling", "reason": str(exc)}]}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json
              else f"❓ НЕ ИЗМЕРЕНО — не загрузился {SIBLING}: {exc}")
        return 2

    log = Path(args.log) if args.log else sibling.shared_log()[0]

    if args.cmd == "check":
        report = gather(args.card, log=log, tracker_dir=args.tracker_dir,
                        sibling=sibling, self_session=args.session,
                        grace_hours=args.grace_hours,
                        planned_files=args.files, last=args.last)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
        return exit_code(report)

    try:
        if args.cmd == "claim":
            res = claim_card(args.card, session=args.session, tracker_dir=args.tracker_dir,
                             grace_hours=args.grace_hours, sibling=sibling, log=log,
                             takeover_reason=args.takeover)
            if args.json:
                print(json.dumps(res, ensure_ascii=False))
            elif res.get("takeover_reason"):
                print(f"ПОДНЯТА: {res['card']} → {res['claimed_by']} ({res['claimed_at']}); "
                      f"осиротевший захват {', '.join(res.get('takeover_from') or []) or '?'} "
                      f"перебит с основанием: {res['takeover_reason']}")
            else:
                print(f"взята: {res['card']} → {res['claimed_by']} ({res['claimed_at']})")
            # Предупреждения «захват без личности процесса» здесь больше нет и быть не
            # может: с цикла #387 такой захват НЕ состоится вовсе (`UnmeasurableClaim`).
            # Совет, который печатали вместо отказа, 26.08 не удержал — карточка с настоящей
            # недоставленной работой стала неберущейся навсегда. Поле `anchored` остаётся в
            # ответе: оно и есть то самое утверждение, только теперь всегда True.
        else:
            res = release_card(args.card, session=args.session,
                               tracker_dir=args.tracker_dir, force=args.force, log=log)
            print(json.dumps(res, ensure_ascii=False) if args.json
                  else (f"отпущена: {res['card']}" if res.get("released")
                        else f"{res['card']}: {res['detail']}"))
    except UnmeasurableClaim as exc:
        # Код 2, а не 1: это «не измерено», а не «занято» — та же семантика, что у вердикта
        # `unchecked` (см. коды возврата в докстринге модуля).
        print(f"ОТКАЗ: {exc}")
        return 2
    except ClaimError as exc:
        print(f"ОТКАЗ: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
