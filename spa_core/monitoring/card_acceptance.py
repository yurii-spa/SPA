"""card_acceptance.py — открытая карточка, чей СОБСТВЕННЫЙ критерий уже выполнен (ADR-208).

Вопрос, на который до сих пор не отвечал НИКТО
---------------------------------------------
`findings_bridge` умеет закрывать карточку, которую САМ и завёл: у неё есть
`finding_key`, и когда находка исчезает из отчёта производителя дважды подряд,
мост карточку закрывает. Карточки, написанные СЕССИЕЙ руками (`source: ADR-154`,
`ADR-158`, разбор аварии, замер цикла), ключа не имеют — и потому вне петли
целиком. Их критерий живёт прозой в теле («после сведения `contract_manifest_parity`
обязан давать `agrees`»), и перемеряет его только тот, кто СЛУЧАЙНО возьмёт
карточку в работу.

Замер 2026-09-01 (цикл #450), популяция — типизированные `inbox`-карточки в статусе
`new` на `origin/main`: **три из шести** несли критерий, выполненный за 2–4 суток до
того. Цена не «неаккуратный учёт»: очередь показывает их как работу, и следующая
сессия идёт ДЕЛАТЬ УЖЕ СДЕЛАННОЕ (тот же класс, что измерен в #433 —
«фантомные задания владельца»).

Что делает этот модуль
----------------------
Читает карточки, у которых во frontmatter объявлена **проба из белого списка**
(`acceptance_probe: <имя>` либо `<имя>:<аргумент>`), гоняет пробу и печатает
карточки, у которых критерий выполнен, а статус — открытый.

Три решения, без которых модуль лгал бы
---------------------------------------
1. **Проба — ИМЯ из реестра, а не код из карточки.** Карточку правит кто угодно,
   в том числе мост; исполнять её содержимое значило бы открыть путь исполнения
   кода через текст карточки. Незнакомое имя → `unmeasured`, НИКОГДА не `satisfied`.
2. **Третий исход назван и считается.** Проба, которая не смогла измериться
   (упала, нет модуля, нет реестровой записи), даёт `unmeasured` — отдельный
   счётчик. Без него «критерий не выполнен» неотличимо от «нечем проверить», и
   сторож молча становится fail-OPEN.
3. **Модуль НИЧЕГО не закрывает.** Он называет; статус двигает сессия по
   протоколу. Карточки `needs-owner` не пробуются вовсе: вопрос владельцу не
   снимается измерением (инвариант #14 и ADR-084 — снимать вопрос молча нельзя).

Ответ едет в шаг 0-офис (`scripts/consume_office_reports.py`), а не в отдельную
команду: память, которую надо спрашивать отдельно, неотличима от отсутствия памяти
(урок ADR-207).

Предел, названный честно
------------------------
Проба меряет ТО ДЕРЕВО, в котором её запустили. Шаг 0-офис ходит из прод-дерева, а туда
синхронизация не возит ни `architecture/`, ни `docs/`, ни карточки — то есть проба может
судить о предмете по копии, отставшей от `origin/main` (класс #267: «дрейф механики»,
выдуманный из границы синхронизации; на 01.09 манифесты прода и origin совпадают побайтно,
но это состояние, а не гарантия). Опасная сторона тут одна — ложное `satisfied`; поэтому
сторож НИКОГДА не закрывает карточку сам: он приглашает перемерить, и перемер делает
сессия из worktree на свежем `origin/main`. Трекер, из которого читались карточки,
печатается в первой же строке отчёта — чтобы читатель знал, о ЧЬЕЙ очереди вердикт.

Только stdlib. LLM_FORBIDDEN — это учёт и сверка, не суждение.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Callable

SATISFIED = "satisfied"
NOT_SATISFIED = "not_satisfied"
UNMEASURED = "unmeasured"

#: Статусы, при которых карточка считается ОТКРЫТОЙ работой.
OPEN_STATUSES = frozenset({"new", "backlog", "in-progress", "blocked"})

#: Статусы, которые не пробуются НИКОГДА. `needs-owner` — сознательно: вопрос
#: владельцу закрывает владелец, а не измерение.
NEVER_PROBED_STATUSES = frozenset({"needs-owner", "owner-done"})

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.S)
#: Аргумент пробы — ключ, а не выражение: буквы, цифры, точка, тире, подчёркивание.
_ARG_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── пробы (белый список) ─────────────────────────────────────────────────────
# Каждая проба возвращает (verdict, detail). Проба ОБЯЗАНА быть детерминированной
# и не ходить в сеть/Keychain: иначе она мерила бы окружение прогона, а не предмет
# карточки, и на CI давала бы `unmeasured` по построению.

def _probe_contract_manifest_parity(arg: str | None) -> tuple[str, str]:
    """Критерий: `contract_manifest_parity` даёт `agrees` (дома сошлись)."""
    from spa_core.monitoring import contract_manifest_parity as m
    res = m.audit()
    verdict = res.get("verdict")
    detail = f"вердикт {verdict}, сопоставимо {res.get('compared')}, расхождений {len(res.get('findings') or [])}"
    return (SATISFIED if verdict == m.AGREES else NOT_SATISFIED), detail


def _probe_artifact_contract(arg: str | None) -> tuple[str, str]:
    """Критерий: у агента `arg` сверка контракта даёт `confirmed`."""
    if not arg:
        return UNMEASURED, "пробе нужен агент (acceptance_probe: artifact_contract_confirmed:<label>)"
    from spa_core.monitoring import artifact_contract as m
    rows = m.audit_fleet().get("rows") or []
    for row in rows:
        if row.get("label") == arg:
            v = row.get("verdict")
            return (SATISFIED if v == m.CONFIRMED else NOT_SATISFIED), f"{arg}: {v}"
    return UNMEASURED, f"агента {arg} нет среди сверенных ({len(rows)}) — предмет не измерен"


def _probe_lead_channel_wiring(arg: str | None) -> tuple[str, str]:
    """Критерий: обработчик заявки с сайта ДЕЙСТВИТЕЛЬНО зовёт уведомителя владельца.

    Берётся именно `probe_wiring` (разбор AST реального модуля), а не
    `probe_credentials`: связка ключей — окружение прогона, не предмет карточки.
    """
    from spa_core.monitoring import lead_channel_watch as m
    res = m.probe_wiring()
    status = getattr(res, "status", None)
    detail = getattr(res, "detail", "") or str(status)
    if status == m.OK:
        return SATISFIED, detail
    if status == m.UNCHECKED:
        return UNMEASURED, detail
    return NOT_SATISFIED, detail


PROBES: dict[str, Callable[[str | None], "tuple[str, str]"]] = {
    "contract_manifest_parity_agrees": _probe_contract_manifest_parity,
    "artifact_contract_confirmed": _probe_artifact_contract,
    "lead_channel_wiring_ok": _probe_lead_channel_wiring,
}


# ── разбор карточек ──────────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> dict:
    """Плоский разбор frontmatter карточки (ключ: значение). Без внешних зависимостей."""
    m = _FRONTMATTER_RE.match(text or "")
    if not m:
        return {}
    out: dict = {}
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not km:
            continue
        val = km.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[km.group(1)] = val
    return out


def run_probe(spec: str) -> tuple[str, str]:
    """Исполнить пробу по её ОБЪЯВЛЕНИЮ. Возврат — (вердикт, пояснение).

    Fail-CLOSED в обе стороны: незнакомое имя, кривой аргумент и любое исключение
    внутри пробы дают `unmeasured`, а не `not_satisfied` (не находка) и тем более
    не `satisfied` (не разрешение закрыть карточку).
    """
    spec = (spec or "").strip()
    if not spec:
        return UNMEASURED, "проба не объявлена"
    name, _, arg = spec.partition(":")
    name, arg = name.strip(), arg.strip() or None
    if arg is not None and not _ARG_RE.match(arg):
        return UNMEASURED, f"аргумент пробы отвергнут (не ключ): {arg!r}"
    fn = PROBES.get(name)
    if fn is None:
        return UNMEASURED, f"проба {name!r} не зарегистрирована — измерять нечем"
    try:
        verdict, detail = fn(arg)
    except Exception as exc:  # noqa: BLE001 — падение пробы это «не измерено», не вердикт
        return UNMEASURED, f"проба упала: {type(exc).__name__}: {exc}"
    if verdict not in (SATISFIED, NOT_SATISFIED, UNMEASURED):
        return UNMEASURED, f"проба вернула неизвестный вердикт {verdict!r}"
    return verdict, detail


def audit(tracker_dir: str | None = None) -> dict:
    """Пройти карточки трекера и вынести вердикт по объявленным критериям.

    Возврат: `{"tracker_dir", "scanned", "counts", "rows"}`. `rows` — только те
    карточки, у которых проба ОБЪЯВЛЕНА (остальные тут не предмет: у них критерия
    в машинной форме нет, и молчать о них честнее, чем считать их выполненными).
    """
    tracker_dir = tracker_dir or os.path.join(REPO_ROOT, "nimbalyst-local", "tracker")
    rows: list[dict] = []
    scanned = 0
    if os.path.isdir(tracker_dir):
        for name in sorted(os.listdir(tracker_dir)):
            if not name.endswith(".md") or name.startswith("_"):
                continue
            path = os.path.join(tracker_dir, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            scanned += 1
            fm = parse_frontmatter(text)
            spec = fm.get("acceptance_probe")
            if not spec:
                continue
            status = (fm.get("status") or "?").strip()
            if status in NEVER_PROBED_STATUSES:
                continue
            verdict, detail = run_probe(spec)
            rows.append({
                "card": name[:-3],
                "status": status,
                "open": status in OPEN_STATUSES,
                "probe": spec,
                "verdict": verdict,
                "detail": detail,
            })
    counts = {
        "declared": len(rows),
        "satisfied_but_open": sum(1 for r in rows if r["open"] and r["verdict"] == SATISFIED),
        "not_satisfied": sum(1 for r in rows if r["verdict"] == NOT_SATISFIED),
        "unmeasured": sum(1 for r in rows if r["verdict"] == UNMEASURED),
    }
    return {"tracker_dir": tracker_dir, "scanned": scanned, "counts": counts, "rows": rows}


def report_lines(result: dict) -> list[str]:
    """Строки для шага 0-офис. Пустой ответ невозможен: «проб не объявлено» —
    тоже состояние, и молчание о нём неотличимо от «всё сошлось»."""
    c = result.get("counts") or {}
    where = result.get("tracker_dir")
    out = [f"— критерии открытых карточек (трекер: {where}) —"]
    if not (result.get("rows") or []):
        out.append(f"   проб не объявлено ни на одной из {result.get('scanned', 0)} карточек "
                   f"— критерии живут прозой, машинно не перемеряются (ADR-208)")
        return out
    out.append(f"   объявлено проб {c.get('declared', 0)} · "
               f"КРИТЕРИЙ ВЫПОЛНЕН при открытой карточке {c.get('satisfied_but_open', 0)} · "
               f"ещё не выполнен {c.get('not_satisfied', 0)} · не измерено {c.get('unmeasured', 0)}")
    for r in result["rows"]:
        if r["open"] and r["verdict"] == SATISFIED:
            out.append(f"   🟩 КРИТЕРИЙ ВЫПОЛНЕН, а карточка открыта ({r['status']}): "
                       f"{r['card']} — {r['detail']}. Перемерить и закрыть, а не делать заново")
        elif r["verdict"] == UNMEASURED:
            out.append(f"   [НЕ ИЗМЕРЕНО] {r['card']}: {r['detail']}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tracker-dir", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    res = audit(args.tracker_dir)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for line in report_lines(res):
            print(line)
    # Код возврата: 1 — есть открытая карточка с выполненным критерием (находка);
    # 2 — что-то не измерено и находок нет (fail-CLOSED: «нечем проверить» ≠ «чисто»).
    c = res["counts"]
    if c["satisfied_but_open"]:
        return 1
    return 2 if c["unmeasured"] else 0


if __name__ == "__main__":
    sys.exit(main())
