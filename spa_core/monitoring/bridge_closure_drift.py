"""bridge_closure_drift.py — карточка моста закрыта в проде, а на origin/main открыта.

Зеркальная половина уже закрытого класса
------------------------------------------------------------------------------
Мост находок (ADR-066) работает в ПРОД-дереве и там же закрывает карточку
(`set-status … done`). Пуша в нём нет ни строкой. Направление РОЖДЕНИЯ закрыто
карточкой `inbox-kartochki-mosta-nahodok-rozhdayutsya-v-p` (08.08): карточка,
рождённая в проде, на origin не попадает никогда.

Направление ЗАКРЫТИЯ оставалось открытым. Карточка, которая на `origin/main`
уже есть, закрывается мостом в проде — и закрытие наверх не возвращается ничем.
На origin она остаётся `new` навсегда, а очередь по протоколу §3.4 читается из
worktree на `origin/main`. То есть цикл видит живой находку, снятую недели назад.

**Замер цикла #480 (2026-09-04):** `gap:analyst_red:red_team` — `status: closed`,
`last_seen: 2026-08-11T07:03:01Z`; карточка `inbox-nahodka-petli-analitik-red-team-critical`
в проде `done`, на `origin/main` `new` (создана 2026-08-10). Цена измерена, а не
предположена: #480 взял её как открытую работу моста, прочитал тело, поднял два
gitignored-артефакта и только тогда установил, что работа сделана 25 дней назад.

Почему этого не называл никто
------------------------------------------------------------------------------
Шаг 0-офис печатает дрейф прод↔origin только для `owner-decision`; сторож ADR-208
работает лишь по карточкам с ОБЪЯВЛЕННОЙ пробой (их 5 на всю популяцию, эта в
их число не входила). Ключ в `findings_bridge_state.json` со `status: closed`,
чья карточка на `origin/main` в НЕтерминальном статусе, — величина механически
вычислимая, и ровно её здесь и считают.

Три исхода, и третий обязателен
------------------------------------------------------------------------------
`data/` в git-worktree нет ПО ПОСТРОЕНИЮ (gitignore), а `origin/main` не
разрешается в песочнице без репозитория. В обоих случаях «находок 0» было бы
fail-OPEN — тише красной строки и потому опаснее (класс #465). Поэтому:

* состояние моста прочитано И сверка с ref выполнилась ⇒ `ok` / `findings`;
* состояние не прочитано ЛИБО сверка не выполнилась ⇒ `unmeasured` С ПРИЧИНОЙ,
  и «расхождений нет» о таком входе не сказано — сказано «судить было нечем».

Что НЕ является предметом
------------------------------------------------------------------------------
`resolved_untouched` (находка исчезла, но карточку УЖЕ взял человек) — не
предмет: мост её не закрывал, и открытый статус наверху там законен. Это не
недосмотр, а граница: расширить её значило бы краснеть на верном состоянии.

`absent_on_origin` (мост закрыл карточку, которой на ref нет вовсе) называется
ОТДЕЛЬНЫМ списком и находкой не считается — это направление РОЖДЕНИЯ, закрытое
своей карточкой. Сложить два списка в одно число значило бы предъявить циклу
работу, которой нет.

Ось вторая: ЗНАМЕНАТЕЛЬ (ADR-806, цикл #929)
------------------------------------------------------------------------------
Всё выше меряет ОДИН вопрос: «дошло ли наверх закрытие, сделанное МОСТОМ».
Знаменатель у него — журнал моста (`findings` со `status: closed`), и читается
этот ответ как ответ на ДРУГОЙ вопрос: «не предъявляет ли очередь работу,
снятую ранее». Два вопроса совпадают ровно настолько, насколько мост —
единственная дверь закрытия. Он не единственная.

**Замер 2026-10-25 (цикл #929, живое дерево против `origin/main` 546687543):**

| вопрос | знаменатель | находок |
|---|---|---|
| дошло ли закрытие МОСТА? (ось ledger) | 52 записи журнала | **0** — сошлось 52/52 |
| закрыта в дереве, открыта на ref? (ось tracker) | 671 терминальная карточка | **41** |

Пересечение осей — ПУСТО, и это не случайность, а построение: из 41 карточки
журнал моста не знает НИ ОДНОЙ в состоянии `closed`. Пять были заведены мостом
и закрыты ИНТЕЙКОМ как дубли (`queue.set_status · closed_by:owner_queue.intake/
history_check`), шестая лежит в журнале как `carded` (мост всё ещё считает
находку живой), остальные 35 закрыты сессиями через `queue.set_status` — а
`TRACKER_DIR` по построению указывает в ЖИВОЕ дерево (`owner_queue.queue.
_resolve_tracker_dir`, карточка-призрак 22.08), и доставки у этой записи нет
ничьей: сеть под доставкой (`card_delivery.orphan_candidates`) пропускает
карточку строкой `if name in on_ref: continue`, то есть отвечает только про
РОЖДЕНИЕ файла, и про статус не спрашивает ни разу.

Старейшему непришедшему закрытию **54.5 суток**, медиане 37.7, младшему 0.7 —
класс ЖИВОЙ, а не исторический. Переоткрытий среди 41 — **ноль** (ни одна
origin-копия не несёт `status_trail` вовсе), то есть дрейф односторонний:
дерево впереди, ref позади, и «кто новее» здесь не вопрос.

Поэтому ось tracker спрашивает у ДИСКА, а не у журнала: терминальная карточка
дерева против своей же копии на ref. Старая ось СОХРАНЕНА и не ослаблена — она
дешевле и отвечает на свой законный вопрос («сам мост довозит?»); снять её
значило бы обменять одно слепое пятно на другое.

LLM_FORBIDDEN. Только stdlib (git — через `origin_view`, без сети).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from spa_core.monitoring.architecture_conformance import REPO_ROOT
from spa_core.monitoring.findings_bridge import STATE_REL

#: Вердикты. `unmeasured` — самостоятельный исход, а не разновидность `ok`.
VERDICT_OK = "ok"
VERDICT_FINDINGS = "findings"
VERDICT_UNMEASURED = "unmeasured"

#: Статус записи моста, при котором карточку закрыл САМ мост (findings_bridge:477).
#: Только он и есть предмет: `resolved_untouched` мост не закрывал.
SUBJECT_STATUS = "closed"

#: Статусы, при которых карточка на `origin/main` действительно закрыта.
#: Копия правила здесь СОЗНАТЕЛЬНА, а её расхождение с единственным другим
#: писателем (`scripts/build_tracker_board.TERMINAL_STATUSES`) краснит тест
#: `test_terminal_set_matches_the_board` — две молча разошедшиеся копии этого
#: правила и есть тот дефект, ради которого сторож написан.
#: `owner-accepted` здесь нет намеренно: владелец ответил, но работа впереди.
CLOSED_ON_ORIGIN = frozenset({"done", "ingested", "owner-done"})

#: Путь каталога очереди внутри репозитория.
TRACKER_REL = os.path.join("nimbalyst-local", "tracker")


def card_id_of(card: str) -> str:
    """`…/tracker/inbox-foo.md` → `inbox-foo`. Мост хранит АБСОЛЮТНЫЙ путь прод-дерева,
    а на ref карточка адресуется только идентификатором."""
    return os.path.splitext(os.path.basename(str(card)))[0]


def origin_lookup_for(root: str = REPO_ROOT) -> Callable[[set[str]], tuple[dict[str, str], str]]:
    """Сверка с `origin/main` для дерева `root`: {card_id: статус на ref} + sha ref.

    Импорт `origin_view` отложен внутрь: модуль-сторож обязан импортироваться
    и там, где очереди нет вовсе (CI-фикстура), — иначе «не измерено» превратится
    в падение импорта, то есть в молчание.
    """
    def lookup(card_ids: set[str]) -> tuple[dict[str, str], str]:
        from spa_core.owner_queue.origin_view import cards_by_id
        cards, sha = cards_by_id(Path(root) / TRACKER_REL, card_ids)
        return {cid: c.status for cid, c in cards.items()}, sha
    return lookup


def _unmeasured(reason: str) -> dict:
    return {"verdict": VERDICT_UNMEASURED, "unmeasured_reason": reason,
            "ref_sha": None, "checked": 0, "agreed": 0,
            "open_on_origin": [], "absent_on_origin": []}


def scan(findings: dict, origin_lookup: Callable | None, *,
         state_read: bool = True) -> dict:
    """Назвать ПОИМЁННО карточки моста, закрытые в проде и открытые на ref.

    `findings` — блок `findings` состояния моста. `origin_lookup` — сверка с ref
    (см. :func:`origin_lookup_for`); `None` означает, что вызывающий сверку не
    предоставил, и это `unmeasured`, а не «расхождений нет». `state_read=False` —
    состояние моста прочитать не удалось (в worktree его нет по построению).
    """
    if not state_read:
        return _unmeasured("состояние моста не прочитано (в worktree data/ нет "
                           "ПО ПОСТРОЕНИЮ) — сверять было нечего")
    if origin_lookup is None:
        return _unmeasured("вызывающий не передал сверку с origin/main")

    subject = {key: card_id_of(e["card"])
               for key, e in (findings or {}).items()
               if e.get("status") == SUBJECT_STATUS and e.get("card")}
    if not subject:
        # ИЗМЕРЕННАЯ пустота: состояние прочитано, закрытых мостом карточек в нём
        # нет. Это `ok`, а не `unmeasured`, — и разница названа вслух.
        return {"verdict": VERDICT_OK, "unmeasured_reason": None, "ref_sha": None,
                "checked": 0, "agreed": 0, "open_on_origin": [], "absent_on_origin": []}

    from spa_core.owner_queue.origin_view import Unmeasured
    try:
        statuses, sha = origin_lookup(set(subject.values()))
    except Unmeasured as exc:
        return _unmeasured(f"сверка с origin/main не выполнилась: {exc}")

    open_on_origin: list[dict] = []
    absent: list[dict] = []
    agreed = 0
    for key, cid in sorted(subject.items()):
        status = statuses.get(cid)
        if status is None:
            absent.append({"key": key, "card_id": cid})
        elif status in CLOSED_ON_ORIGIN:
            agreed += 1
        else:
            entry = (findings or {}).get(key) or {}
            open_on_origin.append({"key": key, "card_id": cid,
                                   "origin_status": status,
                                   "closed_at": entry.get("closed_at")})
    return {"verdict": VERDICT_FINDINGS if open_on_origin else VERDICT_OK,
            "unmeasured_reason": None, "ref_sha": sha,
            "checked": len(subject), "agreed": agreed,
            "open_on_origin": open_on_origin, "absent_on_origin": absent}


#: Файлы каталога очереди, которые карточками НЕ являются. `_BOARD.md` — общая
#: производная доска: у неё нет `status:`, и считать её «нечитаемой карточкой»
#: значило бы кормить третий исход мусором каждый прогон.
TRACKER_NOT_A_CARD = frozenset({"_BOARD.md"})


def _tracker_unmeasured(reason: str) -> dict:
    return {"verdict": VERDICT_UNMEASURED, "unmeasured_reason": reason,
            "ref_sha": None, "checked": 0, "agreed": 0,
            "open_on_ref": [], "absent_on_ref": [], "unreadable": []}


def read_tracker_statuses(root: str = REPO_ROOT) -> tuple[dict, list, bool]:
    """``({card_id: статус}, [нечитаемые card_id], прочитан ли каталог)``.

    Третий элемент — НЕ «каталог непустой»: очередь, которой в дереве нет
    (песочница, CI-фикстура), и очередь, прочитанная и пустая, дают РАЗНЫЕ
    вердикты, и схлопывание их в «находок 0» и есть fail-OPEN.

    Карточка без разбираемого `status:` попадает в СВОЙ список, а не молча
    выпадает: «не прочитали» не имеет права совпасть с «сошлось».
    """
    from spa_core.monitoring.findings_bridge import card_status

    tracker = os.path.join(root, TRACKER_REL)
    if not os.path.isdir(tracker):
        return {}, [], False
    try:
        names = sorted(n for n in os.listdir(tracker)
                       if n.endswith(".md") and n not in TRACKER_NOT_A_CARD)
    except OSError:
        return {}, [], False
    statuses: dict[str, str] = {}
    unreadable: list[str] = []
    for name in names:
        cid = os.path.splitext(name)[0]
        try:
            st = card_status(os.path.join(tracker, name))
        except Exception:  # noqa: BLE001 — нечитаемый файл это третий исход, не ноль
            st = None
        if st:
            statuses[cid] = str(st).strip().lower()
        else:
            unreadable.append(cid)
    return statuses, unreadable, True


def scan_tracker(tree_statuses: dict | None, origin_lookup: Callable | None, *,
                 tracker_read: bool = True, unreadable: list | None = None) -> dict:
    """Ось ЗНАМЕНАТЕЛЯ: терминальная карточка ДЕРЕВА против своей копии на ref.

    Предмет — не «довёз ли мост своё закрытие» (это :func:`scan`), а «не
    предъявляет ли очередь работу, снятую ранее». Спрашивается у ДИСКА, потому
    что дверей закрытия больше одной: замер #929 — 41 находка при нуле по оси
    журнала, пересечение осей пусто.

    Находка — только направление «дерево закрыто, ref ОТКРЫТ». Обратное
    («ref закрыт, дерево открыто») предметом НЕ является: прод-копия карточки
    отстаёт от origin по построению (замер #928 — 17 карточек `owner-done` в
    проде против `ingested` на origin, все 17 ЛОЖНЫЕ), и красить на нём значило
    бы краснеть на верном состоянии.
    """
    if not tracker_read:
        return _tracker_unmeasured("каталог очереди не прочитан — сверять было нечего")
    if origin_lookup is None:
        return _tracker_unmeasured("вызывающий не передал сверку с origin/main")

    closed_here = sorted(cid for cid, st in (tree_statuses or {}).items()
                         if st in CLOSED_ON_ORIGIN)
    unreadable = sorted(unreadable or [])
    if not closed_here:
        # ИЗМЕРЕННАЯ пустота: каталог прочитан, закрытых карточек в нём нет.
        return {"verdict": VERDICT_OK, "unmeasured_reason": None, "ref_sha": None,
                "checked": 0, "agreed": 0, "open_on_ref": [], "absent_on_ref": [],
                "unreadable": unreadable}

    from spa_core.owner_queue.origin_view import Unmeasured
    try:
        statuses, sha = origin_lookup(set(closed_here))
    except Unmeasured as exc:
        out = _tracker_unmeasured(f"сверка с origin/main не выполнилась: {exc}")
        out["unreadable"] = unreadable
        return out

    open_on_ref: list[dict] = []
    absent: list[str] = []
    agreed = 0
    for cid in closed_here:
        status = statuses.get(cid)
        if status is None:
            # Направление РОЖДЕНИЯ: файла на ref нет вовсе. Своя карточка, не
            # эта — складывать два списка значит предъявить работу, которой нет.
            absent.append(cid)
        elif status in CLOSED_ON_ORIGIN:
            agreed += 1
        else:
            open_on_ref.append({"card_id": cid,
                                "tree_status": (tree_statuses or {}).get(cid),
                                "ref_status": status})
    return {"verdict": VERDICT_FINDINGS if open_on_ref else VERDICT_OK,
            "unmeasured_reason": None, "ref_sha": sha,
            "checked": len(closed_here), "agreed": agreed,
            "open_on_ref": open_on_ref, "absent_on_ref": absent,
            "unreadable": unreadable}


def read_state(root: str = REPO_ROOT) -> tuple[dict, bool]:
    """(состояние моста, прочитано ли). Второй элемент — НЕ «состояние непустое»:
    пустое прочитанное состояние и непрочитанное дают разные вердикты."""
    try:
        with open(os.path.join(root, STATE_REL), encoding="utf-8") as fh:
            return json.load(fh), True
    except Exception:  # noqa: BLE001 — отсутствие файла законно, но это НЕ ноль находок
        return {}, False


def scan_both(findings: dict, tree_statuses: dict | None, origin_lookup: Callable | None,
              *, state_read: bool = True, tracker_read: bool = True,
              unreadable: list | None = None) -> dict:
    """Обе оси одним блоком: журнал моста (`scan`) + знаменатель очереди (`scan_tracker`).

    Ось tracker кладётся ВНУТРЬ блока, а не рядом: предмет у них один
    («закрытие не дошло наверх»), и разводить его по двум блокам значило бы
    дать читателю повод прочитать зелёную строку одной оси как ответ обеих —
    ровно та подмена, из-за которой ось tracker и понадобилась.
    """
    out = scan(findings, origin_lookup, state_read=state_read)
    out["tracker"] = scan_tracker(tree_statuses, origin_lookup,
                                  tracker_read=tracker_read, unreadable=unreadable)
    return out


def run(root: str = REPO_ROOT) -> dict:
    """Сверка для дерева `root`. Ничего не пишет: результат печатает читатель
    (шаг 0-офис) из `data/loop_health.json`, куда его кладёт `loop_health`."""
    state, state_read = read_state(root)
    tree, unreadable, tracker_read = read_tracker_statuses(root)
    return scan_both(state.get("findings") or {}, tree, origin_lookup_for(root),
                     state_read=state_read, tracker_read=tracker_read,
                     unreadable=unreadable)


def main(argv=None) -> int:
    """Ручной прогон: `python3 -m spa_core.monitoring.bridge_closure_drift`.

    Коды возврата: 0 — сошлось · 1 — есть находки · 2 — НЕ ИЗМЕРЕНО (fail-CLOSED).
    """
    import argparse
    ap = argparse.ArgumentParser(
        description="карточка моста закрыта в проде, а на origin/main открыта")
    ap.add_argument("--root", default=REPO_ROOT,
                    help="дерево, чьё состояние моста сверяем (по умолчанию прод)")
    args = ap.parse_args(argv)
    report = run(args.root)
    tracker = report.get("tracker") or _tracker_unmeasured("блок оси tracker не произведён")

    # Ось ЖУРНАЛА МОСТА — «довозит ли мост СВОИ закрытия».
    if report["verdict"] == VERDICT_UNMEASURED:
        print(f"⚠️  ось журнала моста НЕ ИЗМЕРЕНА: {report['unmeasured_reason']}")
    else:
        print(f"ось журнала моста — сверено с origin/main ({report['ref_sha']}): "
              f"закрытых мостом карточек {report['checked']}, сошлось {report['agreed']}")
        for row in report["absent_on_origin"]:
            print(f"   ℹ️ на origin/main нет вовсе: {row['card_id']} ({row['key']}) — "
                  "направление РОЖДЕНИЯ, своя карточка")
        for row in report["open_on_origin"]:
            print(f"   🔴 закрыта в проде, на origin/main `{row['origin_status']}`: "
                  f"{row['card_id']} ({row['key']}, закрыта {row['closed_at']})")

    # Ось ЗНАМЕНАТЕЛЯ — «не предъявляет ли очередь работу, снятую ранее».
    if tracker["verdict"] == VERDICT_UNMEASURED:
        print(f"⚠️  ось знаменателя НЕ ИЗМЕРЕНА: {tracker['unmeasured_reason']}")
    else:
        print(f"ось знаменателя — сверено с origin/main ({tracker['ref_sha']}): "
              f"терминальных карточек дерева {tracker['checked']}, сошлось "
              f"{tracker['agreed']}, на ref нет вовсе {len(tracker['absent_on_ref'])}"
              + (f", без разбираемого status: {len(tracker['unreadable'])}"
                 if tracker["unreadable"] else ""))
        for row in tracker["open_on_ref"]:
            print(f"   🔴 закрыта в дереве (`{row['tree_status']}`), на origin/main "
                  f"`{row['ref_status']}`: {row['card_id']}")

    # fail-CLOSED: «не измерено» ЛЮБОЙ оси важнее зелени другой.
    if VERDICT_UNMEASURED in (report["verdict"], tracker["verdict"]):
        return 2
    return 1 if (report["open_on_origin"] or tracker["open_on_ref"]) else 0


if __name__ == "__main__":  # pragma: no cover — точка входа
    raise SystemExit(main())
