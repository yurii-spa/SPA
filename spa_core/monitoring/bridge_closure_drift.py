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


def read_state(root: str = REPO_ROOT) -> tuple[dict, bool]:
    """(состояние моста, прочитано ли). Второй элемент — НЕ «состояние непустое»:
    пустое прочитанное состояние и непрочитанное дают разные вердикты."""
    try:
        with open(os.path.join(root, STATE_REL), encoding="utf-8") as fh:
            return json.load(fh), True
    except Exception:  # noqa: BLE001 — отсутствие файла законно, но это НЕ ноль находок
        return {}, False


def run(root: str = REPO_ROOT) -> dict:
    """Сверка для дерева `root`. Ничего не пишет: результат печатает читатель
    (шаг 0-офис) из `data/loop_health.json`, куда его кладёт `loop_health`."""
    state, state_read = read_state(root)
    return scan(state.get("findings") or {}, origin_lookup_for(root),
                state_read=state_read)


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
    if report["verdict"] == VERDICT_UNMEASURED:
        print(f"⚠️  НЕ ИЗМЕРЕНО: {report['unmeasured_reason']}")
        return 2
    print(f"сверено с origin/main ({report['ref_sha']}): закрытых мостом карточек "
          f"{report['checked']}, сошлось {report['agreed']}")
    for row in report["absent_on_origin"]:
        print(f"   ℹ️ на origin/main нет вовсе: {row['card_id']} ({row['key']}) — "
              "направление РОЖДЕНИЯ, своя карточка")
    for row in report["open_on_origin"]:
        print(f"   🔴 закрыта в проде, на origin/main `{row['origin_status']}`: "
              f"{row['card_id']} ({row['key']}, закрыта {row['closed_at']})")
    return 1 if report["open_on_origin"] else 0


if __name__ == "__main__":  # pragma: no cover — точка входа
    raise SystemExit(main())
