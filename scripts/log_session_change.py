#!/usr/bin/env python3
"""
scripts/log_session_change.py — the shared multi-session ANNOUNCE log (PROJECT_CONTROL/16).

Parallel Claude sessions record every change here so nobody silently overwrites another's work and
the owner has one place to see "what moved". Append-only JSONL: each call writes ONE line in O_APPEND
mode (< PIPE_BUF ⇒ atomic on POSIX, so concurrent sessions never clobber each other). stdlib-only.

    # record a change:
    python3 scripts/log_session_change.py --summary "fix X" --files a.py b.ts --verified "pytest 66 green"
    # record a change AND say which tracker card it belongs to (step 0b reads this):
    python3 scripts/log_session_change.py --summary "..." --card agent-my-card --files ...
    python3 scripts/log_session_change.py --summary "delivered" --card agent-my-card --card-state done
    # see recent activity (run this at session start):
    python3 scripts/log_session_change.py --tail          # last 20
    python3 scripts/log_session_change.py --tail 50

**Announcing a tracker CARD FILE without ``--card`` is a REFUSAL** (``refuse_card_files_without_card``,
cycle #457): step 0b reads a card file in declared ownership as "this card is held", and a record
carrying no ``card:`` field gives it nothing to correct that with. Measured 2026-09-02: a cycle that
finished its work and left the NEXT cycle two cards for the named leftovers announced their files —
it was delivering them to origin — and by that very act locked both. For a pidless label
(``cycle-NNN``) the lock is INDEFINITE, not one freshness window: ``session_state`` returns UNKNOWN
irreversibly, so waiting never clears it. Name the card the work belongs to (``--card <id>``, plus ``--card-state done`` when you are
announcing a delivery rather than holding it).

``--card`` makes the announce↔card link EXPLICIT. Without it the link exists only in free text,
so "is this card already taken?" could only be answered by eye — and on 2026-07-30 that failed:
two sessions took `agent-ci-ignores-golive-gate-tests` an hour apart and did the same work twice
(card `agent-card-claim-collision-guard`). ``scripts/check_card_claim.py`` reads the field
deterministically; ``--card-state done`` releases the claim. Both fields are optional — entries
written without them keep parsing exactly as before.

**The log always lives in the MAIN working tree** (see ``_shared_log``): announcing from an
isolated worktree — which the protocol REQUIRES (§3.4) — used to write into that worktree's own
gitignored ``data/``, so the announcement died with the tree and every reader was blind to it.

**A session's activity is measurable only if the session says which process to look at**
(``durable_process``, card ``agent-durable-session-id``). The ``session`` id defaults to the pid of
this ONE-SHOT CLI process, which is dead the moment the command returns, so ``ps -p`` answered
"no such process" for every entry ever written — including one made a second ago by the session
asking. Steps 0a/0b therefore fell back to the announcement's AGE, and ids that carry no pid at
all (``cycle49``, ``cycle61`` …) were "NOT MEASURED" **for ever**, which on 2026-07-31 locked two
backlog cards out of the queue for 19h+ (card ``agent-weak-mention-locks-card-forever``).
A session that owns a long-lived process — ``scripts/agent_orchestrator.sh`` is one: that shell
waits for the whole cycle — exports ``SPA_SESSION_PID`` (and usually ``SPA_SESSION_ID``), and
every entry then carries ``session_pid`` + ``session_pid_start``, i.e. a process that can actually
be measured. Both keys are only ever ADDED; entries written without them parse exactly as before.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE_LOG = Path(__file__).resolve().parents[1] / "data" / "session_changes.jsonl"
_RESOLVER = Path(__file__).resolve().parent / "check_undelivered_work.py"
_UNSET = object()
_RESOLVER_MOD = _UNSET


def _load_resolver():
    """The sibling module (``check_undelivered_work``) or None — loaded once, never twice.

    It owns ``ps``/``lstart`` parsing and the "where is the shared state" answer; re-implementing
    either here would create the twin that cycle #47 had to hunt down (one copy fixed, the other
    left lying). None (no file / broken import) is a measurement too: callers degrade to the old
    behaviour instead of guessing."""
    global _RESOLVER_MOD
    if _RESOLVER_MOD is _UNSET:
        try:
            spec = importlib.util.spec_from_file_location("_lsc_resolver", _RESOLVER)
            if spec is None or spec.loader is None:
                _RESOLVER_MOD = None
            else:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _RESOLVER_MOD = mod
        except (OSError, ImportError, SyntaxError, AttributeError, ValueError, TypeError):
            _RESOLVER_MOD = None
    return _RESOLVER_MOD


def _shared_log(default: Path) -> Path:
    """The announce log in the MAIN working tree — never in a disposable worktree.

    The protocol REQUIRES autonomous cycles to work in an isolated git worktree (§3.4) and
    ``data/`` is gitignored, so a worktree has no ``data/session_changes.jsonl``: announcing
    from there creates a private one that dies with the tree. Measured 2026-07-31 on orphaned
    cycle #52 — it *did* announce ownership, into
    ``/private/tmp/spa_wt_c52/data/session_changes.jsonl``; the host log never saw it, so both
    step 0a and step 0b were blind to a whole cycle's work (card
    ``agent-claim-without-announce-is-invisible``).

    Resolution lives in ``check_undelivered_work.main_worktree`` — one answer to "where is the
    shared state", not two. Unresolvable (no git, not a repo, tests) → the old path, which is
    correct in the host repo and merely empty elsewhere: readers then say "NOT MEASURED"
    rather than "nothing to report" (fail-CLOSED)."""
    mod = _load_resolver()
    if mod is None:
        return default
    try:
        path, _ = mod.shared_log()
        return Path(path)
    except (OSError, AttributeError, ValueError, TypeError):
        return default


_LOG = _shared_log(_HERE_LOG)


def _session_id() -> str:
    # Stable within a process, distinct across parallel sessions. No secrets.
    return os.environ.get("SPA_SESSION_ID") or f"pid{os.getpid()}"


def durable_process(env=None, ps=None, cmd_probe=None):
    """``({"session_pid": N, "session_pid_start": "<ps lstart>"} , "")`` or ``({}, reason)``.

    The pid comes ONLY from an explicit ``SPA_SESSION_PID`` — never from ``os.getppid()``, and
    that is a deliberate choice, not an omission. The parent of this one-shot command is whatever
    shell happened to run it; for anyone working from a terminal (or a tmux pane) that shell
    outlives the work by days, so a ppid-derived "durable process" would report ACTIVE forever
    and step 0a — whose entire job is to notice work that never reached origin — would go quiet
    about it. That is the fail-OPEN direction (a claim of measurement nobody made, the class of
    #29/#31/#35–#38/#40), so only a session that *declares* its own long-lived process gets one.

    The start time is measured HERE, at write time, and stored verbatim. Without it a later
    reader can only ask "is some process holding this pid?", and a recycled pid would read as a
    live session; with it, "same pid AND same start" is an identity check.

    Returns ``({}, reason)`` — never a half-written pair — whenever the declared pid is not a
    process we can see right now: recording a pid we could not confirm would be exactly the
    plausible-looking number this repo keeps having to delete.

    BOTH probes are inputs, and the second one is why: ``ps`` answers "when did it start",
    ``cmd_probe`` answers "what IS it". Until #453 only the first was injectable, so a caller
    could pin the start time and still have the *command* fetched from the live machine — and
    that is precisely the literal-pid time bomb of `.claude/rules/deployment.md`: the verdict
    was decided by whatever process happened to hold that number today. ``None`` on either =
    ask the real OS, so production behaviour is unchanged."""
    env = os.environ if env is None else env
    raw = str(env.get("SPA_SESSION_PID") or "").strip()
    if not raw:
        return {}, "SPA_SESSION_PID не задан — долгоживущего процесса сессия не объявила"
    if not raw.isdigit():
        return {}, f"SPA_SESSION_PID={raw!r} — не число, долгоживущий процесс не записан"
    pid = int(raw)
    if pid <= 1:
        # pid 1 — init/launchd: живёт всегда и не принадлежит сессии ⇒ вечный ложный ACTIVE.
        return {}, f"SPA_SESSION_PID={pid} — это не процесс сессии, долгоживущий процесс не записан"

    mod = _load_resolver()
    probe = ps or (getattr(mod, "_ps_lstart", None) if mod else None)
    anchor_kind = getattr(mod, "anchor_kind", None) if mod else None
    ANCHOR_TIMER = getattr(mod, "ANCHOR_TIMER", "proves_nothing") if mod else "proves_nothing"
    ANCHOR_UNMEASURED = getattr(mod, "ANCHOR_UNMEASURED", "unmeasured") if mod else "unmeasured"
    if probe is None:
        return {}, "измерить старт процесса нечем (`check_undelivered_work` не загружен)"
    try:
        rc, out = probe(pid)
    except (OSError, ValueError, TypeError) as exc:                     # pragma: no cover
        return {}, f"`ps -p {pid}` не отработал: {exc.__class__.__name__}"
    if rc != 0 or not str(out).strip():
        return {}, (f"процесса pid{pid} сейчас нет (rc={rc}) — объявленный долгоживущий "
                    f"процесс не подтверждён, поле не записано")

    # Процесс есть — но СПОСОБЕН ЛИ он быть сессией? Довод абзацем выше («shell outlives the
    # work by days ⇒ вечный ложный ACTIVE») отвергает ppid, и ровно он же отвергает будильник:
    # фоновый `sleep 36000` живёт свои 10 часов независимо от того, работает сессия или умерла
    # ночью. Замер #393: сессии #390 и #391 объявили якорем именно такой `sleep`, их процессы
    # `claude` завершились, а шаг 0a ПРОПУСТИЛ оба дерева как «сессия подтверждённо активна» —
    # недоставленная работа (ADR-148, data_dir_guard) стала невидимой до истечения таймера.
    # Отказ здесь — тот же контракт `({}, причина)`, что и у неподтверждённого процесса: запись
    # просто уходит без якоря, а не с якорем, который лжёт.
    kind, cmd = (ANCHOR_UNMEASURED, "")
    if anchor_kind is not None:
        try:
            # Умолчание `cmd_probe=None` = спросить настоящую ОС (как было). Проброс нужен
            # ради тестов: до #453 инъекция была ПОЛОВИНЧАТОЙ — `ps` принимался параметром, а
            # команда бралась у живой машины, и `test_announce_refuses_to_record_a_timer_as_the_anchor`
            # краснел/зеленел от того, кто сегодня занял номер 42391, а не от кода.
            kind, cmd = (anchor_kind(pid) if cmd_probe is None
                         else anchor_kind(pid, cmd_probe=cmd_probe))
        except (OSError, ValueError, TypeError):                        # pragma: no cover
            kind, cmd = ANCHOR_UNMEASURED, ""
    if kind == ANCHOR_TIMER:
        return {}, (f"SPA_SESSION_PID={pid} указывает на `{cmd}` — процесс выходит ПО ТАЙМЕРУ, "
                    f"а не вместе с сессией, и живым читается ещё долго после её смерти "
                    f"(замер #393). Якорь не записан: объявляй СВОЙ процесс "
                    f"(`SPA_SESSION_PID=$$` из долгоживущей оболочки сессии)")
    return {"session_pid": pid, "session_pid_start": str(out).strip()}, ""


CARD_STATES = ("claim", "done")


class DroppedWithoutReason(ValueError):
    """`--dropped` без причины. Отказ, а не пустая запись — см. ``normalize_dropped``."""


class CardFileWithoutCard(ValueError):
    """Файл карточки трекера объявлен во владении, а `--card` не назван. См. ``tracker_cards_in``."""


def tracker_cards_in(files) -> list:
    """Объявленные пути, которые являются ФАЙЛАМИ КАРТОЧЕК трекера (в порядке объявления).

    Карточка — `*.md` НЕПОСРЕДСТВЕННО в каталоге `…/nimbalyst-local/tracker/`. Имена,
    начинающиеся с `_`, исключены: там живёт авто-индекс доски (`_BOARD.md`), он не карточка,
    и объявлять его без `--card` совершенно законно (замер 02.09: это единственный такой файл
    в каталоге). Проверка идёт по СТРОКЕ пути — файловая система не спрашивается: объявляют
    пути из чужого одноразового worktree, которого у читателя может уже не быть."""
    out = []
    for f in files or ():
        text = str(f).replace("\\", "/")
        parts = [p for p in text.split("/") if p]
        if len(parts) < 2 or not parts[-1].endswith(".md") or parts[-1].startswith("_"):
            continue
        if parts[-2] == "tracker" and "nimbalyst-local" in parts[:-1]:
            out.append(str(f))
    return out


def refuse_card_files_without_card(files, card) -> None:
    """Объявляешь файл карточки — назови карточку. Иначе ОТКАЗ (цикл #457, вариант 1).

    **Зачем.** Шаг 0b (`check_card_claim.entry_hit`) читает файл карточки в объявленном
    владении как признак того, что карточку ДЕРЖАТ. Запись без поля `card:` не даёт ему
    ничего, чем этот вывод можно поправить, и цена измерена: цикл, который довёл работу до
    конца и оставил СЛЕДУЮЩЕМУ циклу карточки на названные остатки, объявляет их файлы —
    он их везёт на origin — и этим же действием запирает их. У ярлыка без pid (`cycle-NNN`)
    замок БЕССРОЧНЫЙ, а не на окно свежести: `session_state` отдаёт UNKNOWN необратимо. Запись `cycle-84717` от 2026-09-02T04:22:01Z сделала неберущимися обе оставленные
    ею карточки; вердикт перебивали руками, то есть обесценивали сторожа.

    Это **единственная дверь**, через которую объявления пишутся (`check_card_claim.claim`
    ходит сюда же и всегда несёт `card=`), поэтому отказ здесь закрывает форму целиком —
    в отличие от правила «не забывай передавать `--card`», которое уже отказало трижды.

    Назвать нужно ОДНУ карточку — ту, которой принадлежит работа; `--card-state done` для
    объявления доставки. Остальные объявленные карточки после этого читаются слабым
    признаком автоматически (правило #262: «запись машинно называет ДРУГУЮ карточку»).

    Чинит только БУДУЩИЕ записи — уже написанные разбирает вторая половина той же доставки
    (`entry_hit(..., card_claimed=False)`)."""
    cards = tracker_cards_in(files)
    if not cards or str(card or "").strip():
        return
    names = ", ".join(Path(c).name for c in cards)
    raise CardFileWithoutCard(
        f"в --files объявлены файлы карточек трекера ({names}), а --card не назван. "
        f"Шаг 0b прочитает это как «карточку держат» и запрёт её — а у ярлыка без pid "
        f"(`cycle-NNN`) БЕССРОЧНО, не на окно свежести: `session_state` отдаёт UNKNOWN "
        f"необратимо. Запись не пишется (fail-CLOSED). Взял карточку в работу: --card <id>. "
        f"Довёз/создал для следующего цикла: --card <id> --card-state done")


def drop_non_paths(files) -> list:
    """Объявленные пути без того, что путём не является. Отброшенное — на stderr.

    **Зачем** (карточка `inbox-obyavlenie-s-pustym-spiskom-failov-rozhd`, замер #433).
    Писатель записывал в `files` что дали, не спрашивая, путь ли это. Пустая строка
    проходила насквозь, а читатель (`check_undelivered_work.py`) разрешает её в `.` —
    в КОРЕНЬ репозитория, — и получает находку `[отсутствует] .`, которую нельзя снять
    ничем: корень не появится на origin/main как файл ни при какой доставке.

    Объявление без файлов — состояние ЗАКОННОЕ (сессия сообщает о ходе работ), поэтому
    здесь не отказ, а отбрасывание. Но **не молчаливое**: признак, который можно поставить
    молчанием, ничего не даёт читателю — тот же довод, что у ``normalize_dropped``. Сессия
    обязана узнать сейчас, что объявила не то, а не обнаружить пропажу через сутки чужим
    шагом 0a.

    Сужение — РОВНО до не-пути (пустая строка, одни пробелы). Непустой относительный путь
    записывается как прежде: контракт «пути НЕ переписываются» не задет — переписывать
    нечего, речь о том, чтобы не записывать НЕ-путь.

    Форма записи при непустом `--files` остаётся байт в байт прежней (это контракт, его
    пиннят `test_card_claim_guard::TestAnnounceLogField` и
    `test_durable_session_id::TestWriterEntrySchema`).

    Чинит только БУДУЩИЕ записи; уже написанные разбирает вторая половина той же
    доставки — ``check_undelivered_work.announced_files``.
    """
    kept, dropped = [], []
    for f in files or ():
        (kept if str(f).strip() else dropped).append(f)
    if dropped:
        print(f"log_session_change: отброшено объявленных не-путей: {len(dropped)} "
              f"(пустая строка — не путь; читатель разрешил бы её в корень репозитория "
              f"и получил бы неснимаемую находку `[отсутствует] .`). "
              f"В записи остаётся файлов: {len(kept)}", file=sys.stderr)
    return kept


def normalize_dropped(pairs) -> list:
    """[(путь, причина)] → [{"path":…, "reason":…}]. Бросает ``DroppedWithoutReason``.

    **«Намеренно не доставлено» — это РЕШЕНИЕ, и оно обязано иметь автора и причину**
    (карточка `inbox-uborschik-ne-znaet-slova-namerenno-ne-dostavleno`, цикл #353).
    Уборщик деревьев и шаг 0a читают это поле, чтобы отличить «решено не везти, вот почему»
    от забывчивости, — и признак, который можно поставить молчанием, закрыл бы им что угодно.
    Поэтому пустая причина здесь ОТКАЗ (запись не пишется вовсе), а не поле-пустышка:
    молчание вердикта `dropped` не даёт ни на одном из читателей."""
    out = []
    for pair in pairs or ():
        path, reason = (list(pair) + ["", ""])[:2]
        path, reason = str(path).strip(), str(reason).strip()
        if not path:
            raise DroppedWithoutReason("--dropped: путь пуст")
        if not reason:
            raise DroppedWithoutReason(
                f"--dropped {path}: причина пуста. «Решено не доставлять» без причины "
                f"неотличимо от забывчивости — запись не пишется (fail-CLOSED)")
        out.append({"path": path, "reason": reason})
    return out


def record(summary: str, files: list, verified: str,
           card: str = "", card_state: str = "", log=None, session: str = "",
           process=None, dropped=()) -> dict:
    """Append ONE announce entry. ``log`` overrides the shared journal (tests, explicit --log);
    ``session`` overrides the writer's own id (a caller announcing on behalf of a session whose
    id it was given — otherwise the entry would carry this process's pid instead); ``process``
    overrides the durable-process probe (tests).

    Kept as the single writer of this schema: ``check_card_claim.claim`` announces through it
    so a claim can never exist without an announcement (card
    ``agent-claim-without-announce-is-invisible``).

    **The label and the durable anchor must agree about WHOSE entry this is** (card
    ``agent-claim-guard-blind-when-session-pid-is-set``). The whole point of the ``session``
    override is "this entry is not mine, I am only writing it down"; stamping this process's
    ``session_pid``/``session_pid_start`` onto it anyway said the opposite in the very same
    record. The downstream reader believes the anchor over the label — by design, because a
    label is a nickname and a confirmed (pid, start) pair is an identity
    (``check_card_claim.self_identities``) — so a foreign-labelled entry carrying my anchor was
    read back as MINE. Measured consequence: with ``SPA_SESSION_PID`` exported (i.e. exactly how
    ``scripts/agent_orchestrator.sh`` runs the autonomous cycle) step 0b answered ``free`` on a
    held card and ``claim_card`` did not refuse it — the collision guard of card
    ``agent-card-claim-collision-guard`` was silently off in the one mode where cards are taken.

    So the anchor is written only when the entry carries this process's OWN id. Announcing for
    somebody else yields no anchor, which is the fail-CLOSED direction: without it the reader
    falls back to matching by label, i.e. to the behaviour that predates anchors — a foreign
    entry stays foreign and the card reads BUSY. This does not undo
    ``agent-self-claim-blocked-by-own-second-identity``: that fix ties together the several
    auto-derived ``pid<N>`` labels of ONE process, and those entries pass ``session=""`` (or the
    session's own ``SPA_SESSION_ID``), so they keep their anchor and keep being recognised."""
    # ДО построения записи: отказ обязан случиться раньше, чем что-либо попадёт в журнал.
    refuse_card_files_without_card(files, card)
    files = drop_non_paths(files)
    own_id = _session_id()
    label = str(session).strip() or own_id
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": label,
        "summary": summary.strip(),
        "files": [str(f) for f in files],
        "verified": (verified or "").strip(),
    }
    # Optional and only ever ADDED: readers of older entries must keep working unchanged.
    # Пишется ТОЛЬКО когда среди объявленных путей есть относительный, т.е. когда поле
    # что-то добавляет: у абсолютного пути дерево названо им самим. Так форма записи для
    # правильно оформленного объявления остаётся БАЙТ В БАЙТ прежней (это контракт, и он
    # закреплён чужими тестами: `test_card_claim_guard::TestAnnounceLogField`,
    # `test_durable_session_id::TestWriterEntrySchema`).
    if any(not Path(str(f)).is_absolute() for f in entry["files"]):
        cwd = _announce_cwd()
        if cwd:
            entry["cwd"] = cwd
    if card:
        entry["card"] = str(card).strip()
        entry["card_state"] = (card_state or "claim").strip()
    dropped_rows = normalize_dropped(dropped)
    if dropped_rows:
        entry["dropped"] = dropped_rows
    if process is not None:
        proc, _why = process
    elif label == own_id:
        proc, _why = durable_process()
    else:
        proc, _why = {}, (f"объявление от имени другой сессии ({label!r} ≠ {own_id!r}) — "
                          f"долгоживущий процесс ЭТОЙ команды в чужую запись не пишется")
    entry.update(proc)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    target = Path(log) if log else _LOG
    target.parent.mkdir(parents=True, exist_ok=True)
    # O_APPEND: atomic for a single sub-PIPE_BUF write → safe under concurrent sessions.
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(line)
    return entry


def _announce_cwd() -> str:
    """Каталог, ИЗ КОТОРОГО сделано объявление — канонический путь (или "" если не читается).

    ``--files`` документирован как «absolute paths», но НИЧТО этого не проверяет, и 24.08
    сессия ``rnd-75-rearm`` объявила три пути относительными. Для шага 0a это не мелочь
    оформления: ``declaring_tree`` отвечает на вопрос «чьё это расхождение» ТОЛЬКО по дереву,
    названному в самой записи, и на относительном пути возвращает «дерево объявления не
    названо» — запись навсегда теряет право быть оправданной чужим деревом и висит в
    «НЕ ДОСТАВЛЕНО», даже когда своя работа доставлена.

    Каталог объявления отвечает на этот вопрос ФАКТОМ из записи, а не догадкой читателя —
    тот же принцип, что и для абсолютного пути. Пути НЕ переписываются: запись хранит ровно
    то, что передала сессия, плюс место, откуда это сказано. Поле только ДОБАВЛЯЕТСЯ —
    записи без него парсятся и судятся ровно как раньше (fail-CLOSED сохранён).

    Вызывается ТОЛЬКО при относительном пути среди объявленных: у абсолютного дерево названо
    им самим, и запись обязана остаться байт в байт прежней.
    """
    try:
        return os.path.realpath(os.getcwd())
    except OSError:
        # Каталог удалён из-под процесса — это измерение, а не повод выдумать место.
        return ""


def tail(n: int) -> list:
    if not _LOG.exists():
        return []
    lines = _LOG.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Shared multi-session change-announce log.")
    ap.add_argument("--summary", help="one-line description of the change + why")
    ap.add_argument("--files", nargs="*", default=[], help="absolute paths changed")
    ap.add_argument("--verified", default="", help="how it was verified (tests/build exit codes)")
    ap.add_argument("--card", default="",
                    help="tracker card this work belongs to (id or path). ОБЯЗАТЕЛЕН, если в "
                         "--files есть файл карточки трекера — иначе ОТКАЗ (шаг 0b прочитал бы "
                         "запись как захват и запер карточку)")
    ap.add_argument("--card-state", default="claim", choices=CARD_STATES,
                    help="claim = taking/holding the card (default); done = claim released")
    ap.add_argument("--tail", nargs="?", type=int, const=20, help="print the last N entries (default 20)")
    ap.add_argument("--dropped", nargs=2, action="append", metavar=("PATH", "REASON"),
                    default=[],
                    help="путь, который решено НЕ доставлять на origin, и ПОЧЕМУ "
                         "(дубль отвеченного вопроса, черновик, отменённая находка). Читают "
                         "уборщик деревьев и шаг 0a: без этого объявления путь навсегда "
                         "держит дерево и кормит «НЕ ДОСТАВЛЕНО». Причина обязательна")
    args = ap.parse_args(argv)

    if args.tail is not None:
        rows = tail(args.tail)
        if not rows:
            print("(no session changes recorded yet)")
            return 0
        for r in rows:
            files = ", ".join(Path(f).name for f in r.get("files", [])) or "-"
            card = r.get("card")
            print(f"{r.get('ts')}  [{r.get('session')}]  {r.get('summary')}")
            if card:
                print(f"    card: {card} ({r.get('card_state') or 'claim'})")
            print(f"    files: {files}   verified: {r.get('verified') or '-'}")
        return 0

    if not args.summary:
        ap.error("provide --summary (and --files/--verified), or --tail to read")
    proc, why = durable_process()
    try:
        e = record(args.summary, args.files, args.verified, args.card, args.card_state,
                   process=(proc, why), dropped=args.dropped)
    except (DroppedWithoutReason, CardFileWithoutCard) as exc:
        print(f"ОТКАЗ: {exc}", file=sys.stderr)
        return 2
    card = f" card={e['card']}({e['card_state']})" if e.get("card") else ""
    print(f"announced: {e['ts']} [{e['session']}]{card} {e['summary']}")
    for row in e.get("dropped") or ():
        print(f"    намеренно НЕ доставляется: {row['path']} — {row['reason']}")
    if proc:
        print(f"    долгоживущий процесс: pid{proc['session_pid']} "
              f"(старт {proc['session_pid_start']}) — активность сессии измерима")
    elif os.environ.get("SPA_SESSION_PID"):
        # Заявлен, но не подтверждён — молчать нельзя: сессия думает, что её видно.
        print(f"    ⚠️  долгоживущий процесс НЕ записан: {why}", file=sys.stderr)
    else:
        # Не заявлен вовсе. Раньше об этом молчали, и обе цены платились уже после —
        # чужими циклами: (1) шаги 0a/0b печатали «активность не измерена» о сессии,
        # которая просто не сказала, на какой процесс смотреть; (2) следующая команда той
        # же сессии объявлялась под ДРУГИМ ярлыком (pid однократной команды), и сессия
        # начинала отказывать сама себе — вплоть до «снять чужой захват можно только с
        # --force» на СВОЁМ захвате (карточка `agent-self-claim-blocked-by-own-second-identity`,
        # цикл #70). Опознание по якорю это чинит постфактум, но якорю неоткуда взяться,
        # если процесс не объявлен, — поэтому предупреждение, а не тишина.
        # stderr и код возврата 0: это подсказка, а не отказ.
        print(f"    ⚠️  сессия не объявила долгоживущий процесс: ярлык `{e['session']}` — pid "
              f"ОДНОКРАТНОЙ команды, он умрёт вместе с ней, а следующая команда объявится под "
              f"другим ярлыком. Перед первым объявлением: "
              f"export SPA_SESSION_ID=<имя> SPA_SESSION_PID=<pid долгоживущего процесса>",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
