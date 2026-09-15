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
from datetime import datetime, timezone
from typing import Callable

SATISFIED = "satisfied"
NOT_SATISFIED = "not_satisfied"
UNMEASURED = "unmeasured"
#: Карточка закрыта — пробу не гоняли ВОВСЕ. Это не «не измерено» (мерить было нечего:
#: вопрос снят) и не вердикт по критерию. Отдельное слово, чтобы счётчик `unmeasured`
#: не разбавлялся сведённой работой и не терял способность быть находкой.
NOT_PROBED = "not_probed"

#: Статусы, при которых карточка считается ОТКРЫТОЙ работой.
OPEN_STATUSES = frozenset({"new", "backlog", "in-progress", "blocked"})

#: Статусы, которые не пробуются НИКОГДА. `needs-owner` — сознательно: вопрос
#: владельцу закрывает владелец, а не измерение.
NEVER_PROBED_STATUSES = frozenset({"needs-owner", "owner-done"})

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.S)
#: Аргумент пробы — ключ, а не выражение: буквы, цифры, точка, тире, подчёркивание.
#: `+` разделяет НЕСКОЛЬКО ключей одного критерия («живое APY у pendle И у pendle_pt»):
#: критерий карточки часто называет пару, и проба на один ключ была бы зелёной ложью о
#: втором. Форма остаётся ключевой — ни пробелов, ни путей, ни метасимволов оболочки.
_ARG_RE = re.compile(r"^[A-Za-z0-9_.+\-]{1,128}$")

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
    """Критерий: у агента `arg` сверка контракта подтверждена ПО ВСЕМ продуктам.

    ЧАСТИЧНОЕ покрытие — `unmeasured`, а не «выполнено» и не «не выполнено».
    Замер 08.09: `com.spa.daily_cycle` объявляет 10 продуктов, запись видна у 3 —
    и до этой правки проба отвечала ВЫПОЛНЕНО, потому что вердикт сверки был на
    агента, а не на артефакт. Карточка `inbox-dnevnoi-tsikl-pishet-chetyre-
    artefakta-mimo-kontrakta` числилась принятой по свидетельству о трёх продуктах
    из десяти, а среди семи неизмеренных — `data/equity_curve_daily.json`.
    «Не выполнено» здесь было бы такой же неправдой: про эти семь не измерено
    НИЧЕГО, и сказать надо именно это.
    """
    if not arg:
        return UNMEASURED, "пробе нужен агент (acceptance_probe: artifact_contract_confirmed:<label>)"
    from spa_core.monitoring import artifact_contract as m
    rows = m.audit_fleet().get("rows") or []
    for row in rows:
        if row.get("label") == arg:
            v = row.get("verdict")
            if v == m.CONFIRMED:
                return SATISFIED, f"{arg}: {v}"
            if v == m.PARTIAL:
                cov = row.get("coverage") or {}
                unseen = cov.get("unmeasured") or []
                return UNMEASURED, (
                    f"{arg}: {v} — подтверждено {len(cov.get('confirmed') or [])} "
                    f"из {cov.get('declared')} объявленных продуктов; про "
                    f"{len(unseen)} не измерено ничего ({', '.join(unseen) or '—'})")
            return NOT_SATISFIED, f"{arg}: {v}"
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


#: Старше этого — `adapter_status.json` уже не наблюдение, а снимок. Производитель
#: обновляет его в каждом дневном цикле, поэтому сутки — это «пропущен хотя бы один».
ADAPTER_STATUS_MAX_AGE_H = 24.0


def _probe_adapter_status_live_apy(arg: str | None, *, now: "datetime | None" = None) -> tuple[str, str]:
    """Критерий: у ключа `arg` в `data/adapter_status.json` есть ЖИВОЕ APY.

    Разбор именно артефакта, а не адаптера: карточки этого класса спрашивают «доехал ли
    живой фид ДО потребителя», а не «умеет ли адаптер ходить в сеть». Живой запрос сюда
    не годится вдвойне — сеть мерила бы окружение прогона (докстринг реестра), и на CI
    проба давала бы `unmeasured` по построению.

    **Возраст артефакта — часть вопроса, и это измерено, а не предположено.** `data/`
    частично лежит в git, поэтому в worktree и на CI файл ЕСТЬ — но это замороженный
    канон origin. Замер 2026-09-02: копия в worktree от 28.08 объявляла `aave_v3`
    `live_apy=null`, тогда как живой прод в ту же секунду показывал 3.319. Проба без
    проверки возраста выдавала бы ПРОТИВОПОЛОЖНЫЕ вердикты в двух деревьях и краснела бы
    на почленённом — тот самый класс, из-за которого сторож судит о дереве, а не о
    предмете. Протухший артефакт ⇒ `unmeasured`, НИКОГДА не `not_satisfied`.

    Время — вход (`now`), а не окружение: обе стороны сравнения закрепляются в тесте.
    """
    if not arg:
        return UNMEASURED, "пробе нужен ключ адаптера (acceptance_probe: adapter_status_live_apy:<key>)"
    path = os.path.join(REPO_ROOT, "data", "adapter_status.json")
    rel = os.path.relpath(path, REPO_ROOT)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return UNMEASURED, f"{rel} нет в этом дереве — предмет не измерен"
    except (OSError, ValueError) as exc:
        return UNMEASURED, f"{rel} не разобран: {type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return UNMEASURED, f"форма {rel} не разобрана ({type(doc).__name__})"

    stamp = doc.get("generated_at")
    if not stamp:
        return UNMEASURED, f"{rel} без generated_at — возраст не измерен, судить нечем"
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return UNMEASURED, f"{rel}: generated_at {stamp!r} не разобран — возраст не измерен"
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age_h = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    if age_h > ADAPTER_STATUS_MAX_AGE_H:
        return UNMEASURED, (f"{rel} протух: возраст {age_h:.1f}ч при пределе "
                            f"{ADAPTER_STATUS_MAX_AGE_H:.0f}ч (снимок, не наблюдение) — "
                            f"мерить надо из дерева с живым data/")

    rows = doc.get("adapters")
    if rows is None:
        rows = doc
    if not isinstance(rows, (dict, list)):
        return UNMEASURED, f"форма {rel} не разобрана ({type(rows).__name__})"
    keys = [k for k in arg.split("+") if k]
    verdicts, details = [], []
    for key in keys:
        if isinstance(rows, dict):
            row = rows.get(key)
        else:
            row = next((r for r in rows if isinstance(r, dict) and r.get("key") == key), None)
        if not isinstance(row, dict):
            verdicts.append(UNMEASURED)
            details.append(f"{key}: ключа нет в {rel} — предмет не измерен")
            continue
        live = row.get("live_apy")
        if live is None:
            verdicts.append(NOT_SATISFIED)
            details.append(f"{key}: live_apy=null, предъявляется запасной литерал "
                           f"{row.get('fallback_apy')} (tvl_source={row.get('tvl_source')})")
        else:
            verdicts.append(SATISFIED)
            details.append(f"{key}: live_apy={live} (pool_match={row.get('pool_match')})")
    detail = " · ".join(details)
    # Порядок строгий и в этом весь смысл многоключевой формы: «не измерено» съедает
    # «выполнено» (нельзя объявить критерий закрытым, не проверив вторую половину), а
    # «не выполнено» съедает всё остальное. Критерий из двух ключей выполнен ТОЛЬКО
    # когда выполнены оба.
    if NOT_SATISFIED in verdicts:
        return NOT_SATISFIED, detail
    if UNMEASURED in verdicts:
        return UNMEASURED, detail
    return SATISFIED, detail



#: Имя модуля брифинга в `sys.modules`. Скрипт лежит в `scripts/` (не пакет), поэтому
#: грузится по пути; имя ФИКСИРОВАНО, чтобы положительный контроль мог подменить в нём
#: секцию через `sys.modules[...]` и увидеть, что проба это ЗАМЕЧАЕТ.
BRIEFING_MODULE_NAME = "_spa_briefing_under_probe"
#: Синтетический протокол пробы. Имени нет ни в одном реестре — столкновение с живым
#: отчётом куратора невозможно по построению.
TIER_PROBE_PROTO = "probe_t3_candidate"


def _briefing_module():
    """Скрипт брифинга как модуль: один раз на процесс, дальше — из `sys.modules`."""
    import importlib.util
    mod = sys.modules.get(BRIEFING_MODULE_NAME)
    if mod is not None:
        return mod
    path = os.path.join(REPO_ROOT, "scripts", "update_system_briefing.py")
    spec = importlib.util.spec_from_file_location(BRIEFING_MODULE_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[BRIEFING_MODULE_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(BRIEFING_MODULE_NAME, None)
        raise
    return mod


def _probe_tier_promotion_loop(arg: str | None, *, now: "datetime | None" = None) -> tuple[str, str]:
    """Критерий: контур подъёма T3→T2 ЗАМКНУТ до решения — по ИСХОДУ, не по модулю.

    Первая исходная проба реестра (карточка `inbox-mashinnaya-priemka-obyazatelna-
    ishodnaya`, разбор `docs/TIER_LIFECYCLE_AUDIT_2026-09-11.md`). Структурный сторож
    отвечает «у отчёта есть читатель»; эта проба спрашивает, СЛУЧИЛОСЬ ли то, ради чего
    читатель заведён, и делает это на настоящем коде:

    1. в одноразовом дереве кладётся отчёт куратора с `PROMOTE_CANDIDATE` для
       синтетического протокола и гоняется НАСТОЯЩИЙ `findings_bridge.run_bridge`
       (тот же код, что у `com.spa.decision_loop`) с настоящим гистерезисом:
       через `REQUIRED_SIGHTINGS` дневных замеров обязана родиться карточка с
       `finding_key` РОВНО `tier_promote:<proto>` (сравнение ключа, не подстроки
       текста) и статусом агента (`new`), не владельца;
    2. кандидат исчезает ⇒ через `REQUIRED_ABSENCES` молчаливых замеров карточка
       обязана закрыться сама (`done`);
    3. настоящая секция брифинга `build_tier_curator_section()` на том же отчёте
       обязана нести строку таблицы с этим протоколом и парой тиров — проверяются
       ЯЧЕЙКИ строки, не вхождение имени в текст (ADR-333: приёмка подстрокой оставалась
       зелёной при удалении ключа).

    Порвись цепочка где угодно — читатель снят, карточка не рождается или не
    закрывается, секция выпала из сборки — вердикт `not_satisfied` с названным звеном.
    Живое `data/` и живой трекер не трогаются: дерево одноразовое, очередь — в памяти.
    Настоящий дневной цикл здесь НЕ гоняется намеренно: он ходит в сеть, а проба обязана
    мерить предмет, а не окружение прогона (докстринг реестра). Мерится ровно тот шаг
    цикла, который производит названное следствие.

    Время — вход (`now`), обе стороны замера (часы моста и `generated_at` отчёта)
    идут от одного якоря: календарь пробе безразличен.
    """
    import shutil
    import tempfile
    from datetime import timedelta
    from spa_core.monitoring import findings_bridge as fb

    proto = TIER_PROBE_PROTO
    key = f"tier_promote:{proto}"
    t0 = now or datetime.now(timezone.utc)
    step = timedelta(days=1)
    root = tempfile.mkdtemp(prefix="spa_tier_probe_")
    try:
        data = os.path.join(root, "data")
        tracker = os.path.join(root, "tracker")
        os.makedirs(data)
        os.makedirs(tracker)

        def put_siblings(at):
            # Соседние источники моста — читаемые и пустые: нечитаемый источник мост
            # называет вслух и ничего не рождает (это верно, но здесь не предмет).
            for name, doc in (("architecture_conformance.json", {"generated_at": at.isoformat(), "findings": []}),
                              ("house_view_gap.json", {"gaps": []}),
                              ("loop_retro.json", {"findings": []})):
                with open(os.path.join(data, name), "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)

        def put_curator(candidate: bool, at):
            v = ({"current_tier": "T3", "verdict": "PROMOTE_CANDIDATE", "target_tier": "T2",
                  "owner_gated": False, "reasons": ["проба: синтетический кандидат"],
                  "evidence": {"tvl_usd": 31_000_000.0, "tvl_live": True, "apy_days": 21}}
                 if candidate else
                 {"current_tier": "T3", "verdict": "KEEP", "reasons": ["проба: кандидат исчез"],
                  "evidence": {}})
            doc = {"generated_at": at.isoformat(), "curator_version": "tier_curator_v1",
                   "verdicts": {proto: v},
                   "summary": {"total": 1, "promote_candidate": 1 if candidate else 0,
                               "held_flagged": []}}
            with open(os.path.join(data, "tier_curator_report.json"), "w", encoding="utf-8") as fh:
                json.dump(doc, fh)

        created: list = []

        def create(_root, finding):
            critical = finding.get("severity") == "CRITICAL"
            kind = "owner-decision" if critical else "inbox"
            status = "needs-owner" if critical else "new"
            path = os.path.join(tracker, f"card-{len(created) + 1}.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"---\ntrackerStatus:\n  type: {kind}\nstatus: {status}\n"
                         f"finding_key: \"{finding['key']}\"\n---\n{finding.get('message', '')}\n")
            created.append({"key": finding["key"], "path": path, "status": status})
            return path

        def close(_root, path):
            if not fb.card_is_untouched(path):
                return False
            text = open(path, encoding="utf-8").read()
            text = text.replace("status: new", "status: done").replace("status: needs-owner", "status: done")
            open(path, "w", encoding="utf-8").write(text)
            return True

        def noop(_root, _path):
            return True

        def run(at):
            put_siblings(at)
            return fb.run_bridge(root, now=at, create=create, close=close, notify=noop, retract=noop)

        # 1. кандидат ⇒ карточка через REQUIRED_SIGHTINGS замеров подряд
        n_sight = int(getattr(fb, "REQUIRED_SIGHTINGS", 2))
        for i in range(n_sight):
            put_curator(True, t0 + i * step)
            run(t0 + i * step)
        mine = [c for c in created if c["key"] == key]
        if not mine:
            keys = sorted(c["key"] for c in created)
            return NOT_SATISFIED, (f"контур разомкнут: после {n_sight} замеров подряд с PROMOTE_CANDIDATE "
                                   f"мост НЕ родил карточку с finding_key={key!r} (рождены: {keys or '—'})")
        card = mine[0]
        fm = parse_frontmatter(open(card["path"], encoding="utf-8").read())
        if fm.get("finding_key") != key:
            return NOT_SATISFIED, f"карточка родилась, но её finding_key={fm.get('finding_key')!r} ≠ {key!r}"
        if fm.get("status") != "new":
            return NOT_SATISFIED, (f"карточка кандидата родилась со статусом {fm.get('status')!r}, а не `new`: "
                                   f"подъём — вопрос агенту (ADR-285), не владельцу")

        # 2. кандидат исчез ⇒ закрытие через REQUIRED_ABSENCES молчаливых замеров
        n_abs = int(getattr(fb, "REQUIRED_ABSENCES", 2))
        t = t0 + n_sight * step
        for i in range(n_abs):
            put_curator(False, t + i * step)
            run(t + i * step)
        status_after = fb.card_status(card["path"])
        if status_after != "done":
            return NOT_SATISFIED, (f"кандидат исчез, прошло {n_abs} молчаливых замера, а карточка "
                                   f"всё ещё {status_after!r} — авто-закрытие не сработало")

        # 3. второй читатель — секция брифинга на том же отчёте (кандидат снова на месте)
        put_curator(True, t0)
        try:
            mod = _briefing_module()
        except Exception as exc:  # noqa: BLE001
            return UNMEASURED, f"скрипт брифинга не загрузился: {type(exc).__name__}: {exc}"
        saved = getattr(mod, "DATA_DIR", None)
        try:
            mod.DATA_DIR = data
            section = mod.build_tier_curator_section()
        finally:
            mod.DATA_DIR = saved
        row = None
        for line in (section or "").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
            if cells and cells[0] == proto:
                row = cells
                break
        if row is None:
            return NOT_SATISFIED, f"секция брифинга не несёт строки таблицы для {proto!r} — второй читатель выпал"
        if row[1:3] != ["T3", "T2"]:
            return NOT_SATISFIED, f"строка брифинга для {proto!r} несёт тиры {row[1:3]}, ожидалось ['T3', 'T2']"
        return SATISFIED, (f"карточка {key} родилась через {n_sight} замера, закрылась через {n_abs} "
                           f"молчаливых; секция брифинга несёт строку {proto} T3→T2")
    finally:
        shutil.rmtree(root, ignore_errors=True)



#: Синтетический протокол пробы поиска: имени нет ни в одном реестре — столкновение
#: с покрытием невозможно по построению.
DISCOVERY_PROBE_PROTO = "probe-newlend"


def _probe_candidate_discovery_loop(arg: str | None, *, now: "datetime | None" = None) -> tuple[str, str]:
    """Критерий: поиск новых протоколов ЗАМКНУТ до читателя — по ИСХОДУ (ADR-089 §6, вариант 1).

    На одноразовом дереве с инъектированным фидом (четыре пула: два новых стейбл-пула
    чужого протокола, один уже наш, один не-стейбл) гоняется НАСТОЯЩИЙ шаг цикла
    `discovery_step.run_discovery_step`, затем НАСТОЯЩИЙ читатель `alpha_agent.run_alpha_scan`
    на том же дереве и НАСТОЯЩАЯ секция брифинга. Обязано случиться:

    1. реестр записан, статус `ok`, среди кандидатов РОВНО чужой протокол (наш и не-стейбл
       отсеяны) — сравнение по полю `protocol`, не по вхождению имени в текст;
    2. `alpha_candidates.json` несёт `candidates_measured: true` и хотя бы одного кандидата
       (до 13.09 здесь стояло «не измерено», потому что писателя не было);
    3. секция брифинга несёт СТРОКУ ТАБЛИЦЫ с этим протоколом (ячейки, не подстрока);
    4. отказ фида ⇒ статус `refused`, реестр побайтно не тронут, статус шага записан.

    Живой `data/` не трогается; сеть не опрашивается. Время — вход (`now`).
    """
    import hashlib
    import shutil
    import tempfile
    from spa_core.adapter_sdk import discovery as d
    from spa_core.paper_trading import discovery_step as ds

    proto = DISCOVERY_PROBE_PROTO
    t0 = now or datetime.now(timezone.utc)
    now_ts = t0.timestamp()
    old = int(now_ts) - 400 * 86400
    pools = [
        {"pool": "probe-pool-1", "project": proto, "symbol": "USDC", "chain": "Ethereum",
         "tvlUsd": 42_000_000.0, "apy": 6.1, "listedAt": old},
        {"pool": "probe-pool-2", "project": proto, "symbol": "USDT", "chain": "Arbitrum",
         "tvlUsd": 12_000_000.0, "apy": 5.2, "listedAt": old},
        {"pool": "probe-pool-3", "project": "aave-v3", "symbol": "USDC", "chain": "Ethereum",
         "tvlUsd": 900_000_000.0, "apy": 4.0, "listedAt": old},
        {"pool": "probe-pool-4", "project": "probe-volatile", "symbol": "WETH", "chain": "Base",
         "tvlUsd": 50_000_000.0, "apy": 9.0, "listedAt": old},
    ]
    root = tempfile.mkdtemp(prefix="spa_discovery_probe_")
    try:
        data = os.path.join(root, "data")
        os.makedirs(data)
        # 1. шаг цикла с инъектированным фидом
        res = ds.run_discovery_step(data, fetch_fn=lambda: list(pools), now_ts=now_ts)
        if res.get("status") != ds.OK:
            return NOT_SATISFIED, f"шаг не дал `ok` на пригодном фиде: {res.get('status')} — {res.get('reason')}"
        reg_path = os.path.join(data, ds.REGISTRY_FILENAME)
        try:
            reg = json.load(open(reg_path, encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return NOT_SATISFIED, f"реестр не записан/нечитаем после `ok`: {type(exc).__name__}"
        got = sorted({str(c.get("protocol")) for c in (reg.get("candidates") or []) if isinstance(c, dict)})
        if got != [proto]:
            return NOT_SATISFIED, (f"реестр несёт протоколы {got}, ожидался ровно [{proto!r}] — "
                                   f"покрытие или пороги сканера порваны")
        # 2. настоящий читатель — alpha scan на том же дереве
        from spa_core.agents import alpha_agent as aa
        aa.run_alpha_scan(data_dir=data)
        try:
            alpha = json.load(open(os.path.join(data, aa.ALPHA_CANDIDATES_FILENAME), encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return NOT_SATISFIED, f"alpha_candidates.json не записан читателем: {type(exc).__name__}"
        if alpha.get("candidates_measured") is not True:
            return NOT_SATISFIED, (f"читатель говорит «не измерено» ({alpha.get('candidates_reason')!r}) "
                                   f"при записанном реестре — связка писатель→читатель порвана")
        if not (alpha.get("candidates") or []):
            return NOT_SATISFIED, "читатель измерил реестр, но кандидатов у него ноль — оценка порвана"
        # 3. секция брифинга — строка таблицы
        try:
            mod = _briefing_module()
        except Exception as exc:  # noqa: BLE001
            return UNMEASURED, f"скрипт брифинга не загрузился: {type(exc).__name__}: {exc}"
        saved = getattr(mod, "DATA_DIR", None)
        try:
            mod.DATA_DIR = data
            section = mod.build_candidate_registry_section(now=t0)
        finally:
            mod.DATA_DIR = saved
        row = None
        for line in (section or "").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
            if cells and cells[0] == proto:
                row = cells
                break
        if row is None:
            return NOT_SATISFIED, f"секция брифинга не несёт строки таблицы для {proto!r} — читатель выпал"
        # 4. отказ фида: реестр не тронут, статус записан
        before = hashlib.sha256(open(reg_path, "rb").read()).hexdigest()

        def boom():
            # Сторож SPAError (tests/test_spaerror_complete.py) не пускает голый RuntimeError в
            # spa_core/: отказ фида — предмет сканера, и его собственная ошибка здесь уместнее.
            raise d.DiscoveryError("проба: фид недоступен")

        res2 = ds.run_discovery_step(data, fetch_fn=boom, now_ts=now_ts + 86400)
        after = hashlib.sha256(open(reg_path, "rb").read()).hexdigest()
        if res2.get("status") != ds.REFUSED:
            return NOT_SATISFIED, f"недоступный фид дал {res2.get('status')!r}, а не `refused`"
        if before != after:
            return NOT_SATISFIED, "недоступный фид ПЕРЕПИСАЛ реестр — fake-fallback или затирание прошлого замера"
        try:
            stt = json.load(open(os.path.join(data, ds.STATUS_FILENAME), encoding="utf-8"))
        except (OSError, ValueError):
            return NOT_SATISFIED, "исход отказа не записан в статус шага — отказ проглочен"
        if stt.get("status") != ds.REFUSED:
            return NOT_SATISFIED, f"статус шага после отказа {stt.get('status')!r}, а не `refused`"
        return SATISFIED, (f"шаг записал реестр с {proto} (наш и не-стейбл отсеяны), alpha_scan измерил "
                           f"кандидатов, секция брифинга несёт строку; отказ фида — `refused`, реестр не тронут")
    finally:
        shutil.rmtree(root, ignore_errors=True)


#: Синтетический журнал пробы «бесплатный ход». Дни строятся от эпохи, а не от
#: календарной даты: судья (`evaluate_window`) детерминирован по файлам и часов не
#: читает вовсе, поэтому дата здесь — ключ ПОРЯДКА, а не отметка свежести, и
#: литеральной даты в пробе нет ни одной.
_FREE_MOVE_DAYS = 12
_FREE_MOVE_TURNOVER_USD = 50_000.0


def _free_move_journal(root: str, cost_usd: float | None) -> str:
    """Записать журнал решений, у каждого дня которого ЕСТЬ материальный ход.

    Контур намеренно однороден: цель платит больше текущей книги, ход существенен,
    все гейты кроме одного открыты. От варианта к варианту меняется РОВНО цена хода —
    поэтому расхождение счёта есть утверждение о ветке цены, а не о разнице контуров.
    """
    from datetime import timedelta
    base = datetime.fromtimestamp(0, timezone.utc).date()
    lines = []
    for i in range(_FREE_MOVE_DAYS):
        rec = {
            "cycle_date": (base + timedelta(days=i)).isoformat(),
            "decision_id": f"free-move-probe-{i}",
            "book_id": "conservative",
            "capital_usd": 100_000.0,
            "turnover_usd": _FREE_MOVE_TURNOVER_USD,
            "verdict": "HOLD",
            "reasons": ["gain_below_band"],
            "gates": {"has_legs": True, "gain_above_band": False,
                      "payback_within_horizon": True, "cooldown_ok": True,
                      "min_hold_ok": True, "move_turnover_ok": True,
                      "move_amount_ok": True, "week_turnover_ok": True,
                      "day_turnover_ok": True, "target_fully_evidenced": True},
            "current_positions": {"alpha": 0.0, "beta": _FREE_MOVE_TURNOVER_USD},
            "target_positions": {"alpha": _FREE_MOVE_TURNOVER_USD, "beta": 0.0},
            "apy_evidenced_pct": {"alpha": 8.0, "beta": 2.0},
            "legs": [{"protocol": "alpha", "delta_usd": _FREE_MOVE_TURNOVER_USD,
                      "direction": "increase"},
                     {"protocol": "beta", "delta_usd": -_FREE_MOVE_TURNOVER_USD,
                      "direction": "decrease"}],
        }
        if cost_usd is not None:
            rec["cost_usd"] = cost_usd
        lines.append(json.dumps(rec, ensure_ascii=False))
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "allocation_rationale_history.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _probe_free_move_priced_as_free(arg: str | None) -> tuple[str, str]:
    """Критерий владельца (ADR-392 реш. 1): ноль в цене хода — ЦЕНА, а не её отсутствие.

    Владелец назвал приёмку исходом, а не правкой: ``swap_existence_price``
    перестаёт печатать находку ``zero_price_is_read_as_absent_price``, то есть
    лучший счёт при НУЛЕВОЙ цене становится **не хуже**, чем при цене в один цент.
    Проба гоняет настоящий прибор (`zero_is_absent`) на СИНТЕТИЧЕСКОМ журнале —
    живой `data/` не трогается и в вердикт не входит: критерий про арифметику
    судьи, а не про то, какие дни сегодня лежат в книге.

    Мерятся ДВЕ стороны, и обе обязаны держаться, иначе «починка» была бы
    разменом одного дефекта на другой:

    1. **ноль — цена.** Лучший счёт при нулевой цене ≥ счёта при цене в цент
       (дешевле нуля не бывает ни в одной честной модели цены);
    2. **отсутствие — НЕ ноль.** Строка БЕЗ записанной цены по-прежнему берёт
       консервативное допущение ``ASSUMED_COST_BPS_OF_TURNOVER``, а не ноль.
       Без этой половины правка `cost_rec is not None` выглядела бы выполненной
       и одновременно разрешала бы бесплатные ходы там, где цену просто не
       записали, — то есть ровно инвариант #17 наизнанку.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from spa_core.monitoring import criterion_sign_price as csp
    from spa_core.monitoring import swap_existence_price as sep
    from spa_core.paper_trading import shadow_trigger_eval as ste

    root = tempfile.mkdtemp(prefix="spa_free_move_probe_")
    try:
        _free_move_journal(root, cost_usd=100.0)
        try:
            zero = sep.zero_is_absent(Path(root), horizon_days=ste.DEFAULT_HORIZON_DAYS,
                                      gates=csp._gate_names())
        except Exception as exc:  # noqa: BLE001 — нечем мерить ≠ критерий не выполнен
            return UNMEASURED, f"прибор `zero_is_absent` не отработал: {type(exc).__name__}: {exc}"
        net_zero, net_cent = zero.get("best_net_usd_zero"), zero.get("best_net_usd_one_cent")
        if net_zero is None or net_cent is None:
            return UNMEASURED, ("прибор не назвал один из счётов "
                                f"(ноль={net_zero!r}, цент={net_cent!r}) — сравнивать нечего")
        if zero.get("collides"):
            return NOT_SATISFIED, (
                f"ветки СЛИТЫ: лучший счёт при нулевой цене ${net_zero:,.2f}, при цене в цент "
                f"${net_cent:,.2f} (ACT-дней {zero.get('act_days_zero')} против "
                f"{zero.get('act_days_one_cent')}) — бесплатный ход дороже дешёвого")

        # Вторая сторона: строка БЕЗ цены обязана по-прежнему платить допущение.
        absent_root = tempfile.mkdtemp(prefix="spa_free_move_probe_absent_")
        try:
            _free_move_journal(absent_root, cost_usd=None)
            history, _bad = ste.load_history(Path(absent_root))
            if not history:
                return UNMEASURED, "синтетический журнал без цены не прочитался судьёй"
            row = ste._evaluate_verdict(history[0], history[1:], ste.DEFAULT_HORIZON_DAYS)
            source = str(row.get("cost_source") or "")
            used = row.get("cost_usd_used")
            if not source.startswith("assumption:"):
                return NOT_SATISFIED, (
                    f"строка БЕЗ записанной цены получила источник {source!r} (цена ${used!r}) — "
                    "отсутствие наблюдения снова слито с нулём, только в другую сторону (инв. #17)")
            if not isinstance(used, (int, float)) or used <= 0.0:
                return NOT_SATISFIED, (
                    f"допущение при отсутствующей цене дало ${used!r} — ход без записанной цены "
                    "оценён как бесплатный")
        finally:
            shutil.rmtree(absent_root, ignore_errors=True)

        return SATISFIED, (
            f"ноль — цена: лучший счёт ${net_zero:,.2f} против ${net_cent:,.2f} за цент "
            f"(ACT-дней {zero.get('act_days_zero')} против {zero.get('act_days_one_cent')}); "
            f"отсутствие цены по-прежнему платит допущение ${used:,.2f} ({source})")
    finally:
        shutil.rmtree(root, ignore_errors=True)


#: Проба ADR-395 строит журнал СВОИМ писателем, а не литералами: предмет критерия —
#: поведение писателя и читателя, и подсунуть им готовый файл значило бы проверить
#: разбор, а не правило замены. Даты идут ОТ ЭПОХИ и являются ключами порядка, а не
#: отметками свежести — литеральной даты в пробе нет ни одной, часов она не читает.
_RUN_KEEP_DAYS = 12
_RUN_KEEP_TURNOVER_USD = 50_000.0


def _run_keep_record(day_index: int, hour: int, verdict: str) -> dict:
    """Одна строка журнала: день ``day_index``, прогон в час ``hour``, вердикт ``verdict``.

    Ход существенен и оценим (обе ноги имеют наблюдённую ставку), поэтому вердикт
    попадает в ``scored`` знаменатель критерия, а не уходит в ``trivial``.
    """
    from datetime import timedelta
    base = datetime.fromtimestamp(0, timezone.utc).date()
    day = (base + timedelta(days=day_index)).isoformat()
    return {
        "schema": "shadow-hist-v2",
        "cycle_date": day,
        "decision_id": f"adr060-shadow-{day}",
        "generated_at": f"{day}T{hour:02d}:00:00+00:00",
        "book_id": "conservative",
        "capital_usd": 100_000.0,
        "turnover_usd": _RUN_KEEP_TURNOVER_USD,
        "cost_usd": 100.0,
        "verdict": verdict,
        "reasons": ["gain_below_band"],
        "current_positions": {"alpha": 0.0, "beta": _RUN_KEEP_TURNOVER_USD},
        "target_positions": {"alpha": _RUN_KEEP_TURNOVER_USD, "beta": 0.0},
        # Ставка РАСТЁТ по дням намеренно: на однородном контуре звено 4
        # неизмеримо — «семь форвардных ДНЕЙ» и «семь форвардных ЗАПИСЕЙ» дали бы
        # один и тот же счёт, и подмена оси не проявилась бы ничем.
        "apy_evidenced_pct": {"alpha": 8.0 + day_index, "beta": 2.0},
        "legs": [{"protocol": "alpha", "delta_usd": _RUN_KEEP_TURNOVER_USD,
                  "direction": "increase"},
                 {"protocol": "beta", "delta_usd": -_RUN_KEEP_TURNOVER_USD,
                  "direction": "decrease"}],
    }


def _probe_decision_journal_keeps_every_run(arg: str | None) -> tuple[str, str]:
    """Критерий владельца ([ADR-392] реш. 3-A): прогон дня не затирается, и ЧИТАТЕЛЬ это видит.

    Владелец назвал приёмку исходом и назвал её обе половины: *«что перезаписанный
    ход больше не затирается и что читатель отдаёт новое значение»*. Обоснование,
    принятое как правило: *«починка одного писателя — это работа, которая выглядит
    законченной и ничего не меняет, а такие починки опаснее, чем отсутствие
    починки»*. Поэтому вердикт пробы не складывается из двух частей — он требует
    ЧЕТЫРЁХ звеньев, и каждое рвётся отдельно:

    1. **Писатель хранит оба прогона.** Два вызова настоящей
       ``append_rationale_history`` с одной ``cycle_date`` и разными
       ``generated_at`` дают ДВЕ строки. Рвётся возвратом ключа к ``cycle_date``
       (замер ADR-383: единственный ACT за сорок дней стёрт повторным прогоном).
    2. **Читатель отдаёт НОВОЕ значение.** ``evaluate_window`` на журнале с двумя
       прогонами дня обязан ответить ИНАЧЕ, чем на журнале с одним поздним.
       Это половина, которую владелец назвал опаснее отсутствия починки: замер
       ``run_identity_key_price`` (заказ #602/G16) нашёл вторую копию правила
       замены у ``load_history`` и вынес вердикт ИСХОДОМ — не менее 25 читателей
       из 108 схлопывали день САМИ, среди них сам критерий взвода. Рвётся
       возвратом строки ``by_date[...] = obj``, и при целом писателе.
    3. **Идемпотентность цела.** Повторная запись ТОГО ЖЕ прогона (равны И дата,
       И ``generated_at``) не даёт третьей строки. Без этого звена «починка»
       выродилась бы в дописывание всегда, и каждый ручной повтор прогона
       удваивался бы в знаменателе критерия — дефект был бы разменян на другой.
    4. **Горизонт судьи остаётся в ДНЯХ.** Лишние прогоны дня не сокращают
       форвардное окно: ``observation_days`` считается по ДАТАМ, и день с двумя
       прогонами не уменьшает число оценённых дней. Без этого звена п.1–п.3
       выглядели бы выполненными, а судья на дне из 36 прогонов смотрел бы
       вперёд на ОДИН день вместо семи (``forward[:horizon_days]`` считал бы
       прогоны вместо дат).

    Живой ``data/`` не открывается и в вердикт не входит: критерий про правило
    журнала, а не про то, какие дни лежат в книге сегодня.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from spa_core.paper_trading.allocation_rationale import (
        append_rationale_history, history_filename,
    )
    from spa_core.paper_trading import shadow_trigger_eval as ste

    collapsed = tempfile.mkdtemp(prefix="spa_run_keep_one_")
    both = tempfile.mkdtemp(prefix="spa_run_keep_two_")
    sibling_free = tempfile.mkdtemp(prefix="spa_run_keep_sib_")
    try:
        # Оба стенда одинаковы во всём, кроме ОДНОГО: на втором у дня 0 есть
        # РАННИЙ прогон с другим вердиктом. Расхождение ответа поэтому есть
        # утверждение о правиле замены, а не о разнице контуров.
        try:
            for root, early in ((collapsed, False), (both, True)):
                if early:
                    append_rationale_history(
                        _run_keep_record(0, 9, "ACT"), Path(root))
                for day in range(_RUN_KEEP_DAYS):
                    append_rationale_history(
                        _run_keep_record(day, 23, "HOLD"), Path(root))
            lines_both = [ln for ln in (Path(both) / history_filename(None))
                          .read_text(encoding="utf-8").splitlines() if ln.strip()]
            lines_one = [ln for ln in (Path(collapsed) / history_filename(None))
                         .read_text(encoding="utf-8").splitlines() if ln.strip()]
            # п.3 — повтор ТОГО ЖЕ прогона поверх готового стенда
            after_rewrite = append_rationale_history(
                _run_keep_record(0, 9, "ACT"), Path(both))
            # Третий стенд для звена 4: у дня 0 ТОЛЬКО ранний прогон. Если
            # горизонт судьи считается в ДНЯХ, вердикт этого прогона обязан
            # совпасть с его же вердиктом на стенде `both` — поздний прогон
            # своего дня форвардным ДНЁМ не является. Если бы горизонт считался
            # в ЗАПИСЯХ, сосед вошёл бы в окно, вытеснил седьмой день, и счёт
            # разошёлся бы (ставка растёт по дням, поэтому разойдётся заметно).
            append_rationale_history(
                _run_keep_record(0, 9, "ACT"), Path(sibling_free))
            for day in range(1, _RUN_KEEP_DAYS):
                append_rationale_history(
                    _run_keep_record(day, 23, "HOLD"), Path(sibling_free))
            read_both, _bad_b = ste.load_history(Path(both))
            read_one, _bad_o = ste.load_history(Path(collapsed))
            eval_both = ste.evaluate_window(Path(both), write=False)
            eval_one = ste.evaluate_window(Path(collapsed), write=False)
            eval_sib = ste.evaluate_window(Path(sibling_free), write=False)
        except Exception as exc:  # noqa: BLE001 — нечем мерить != критерий не выполнен
            return UNMEASURED, (f"стенд журнала не отработал: "
                                f"{type(exc).__name__}: {exc}")

        # ── звено 1: писатель ─────────────────────────────────────────────────
        if len(lines_both) != len(lines_one) + 1:
            return NOT_SATISFIED, (
                f"писатель СТЁР прогон дня: строк со вторым прогоном {len(lines_both)}, "
                f"без него {len(lines_one)} — ожидалось ровно на одну больше "
                f"(ключ замены снова выведен из одной `cycle_date`, ADR-383)")

        # ── звено 3: идемпотентность ──────────────────────────────────────────
        if after_rewrite != len(lines_both):
            return NOT_SATISFIED, (
                f"повторная запись ТОГО ЖЕ прогона дала {after_rewrite} строк(и) вместо "
                f"{len(lines_both)} — писатель дописывает всегда, и каждый ручной повтор "
                f"прогона удвоится в знаменателе критерия")

        # ── звено 2: читатель отдаёт НОВОЕ значение ───────────────────────────
        if len(read_both) != len(read_one) + 1:
            return NOT_SATISFIED, (
                f"читатель СХЛОПНУЛ день: `load_history` отдала {len(read_both)} записей "
                f"против {len(read_one)} — вторая копия правила замены жива у читателя, и "
                f"починка писателя до критерия взвода НЕ ДОХОДИТ (заказ #602/G16)")
        act_both, act_one = (eval_both.get("counts") or {}).get("act"), \
                            (eval_one.get("counts") or {}).get("act")
        scored_both, scored_one = (eval_both.get("counts") or {}).get("scored"), \
                                  (eval_one.get("counts") or {}).get("scored")
        if act_both is None or act_one is None:
            return UNMEASURED, ("судья не назвал число ACT ни на одном стенде — "
                                "сравнивать нечего")
        if act_both == act_one or scored_both == scored_one:
            return NOT_SATISFIED, (
                f"вердикт критерия НЕ ИЗМЕНИЛСЯ от возвращённого прогона: ACT "
                f"{act_one} → {act_both}, scored {scored_one} → {scored_both}. Строка в "
                f"файле есть, а критерий взвода её не считает — ровно то, что владелец "
                f"назвал опаснее отсутствия починки")

        # ── звено 4: горизонт в ДНЯХ, а не в прогонах ─────────────────────────
        days_both, days_one = (eval_both.get("observation_days"),
                               eval_one.get("observation_days"))
        if days_both != days_one:
            return NOT_SATISFIED, (
                f"лишний ПРОГОН сдвинул счёт ДНЕЙ: observation_days {days_one} → "
                f"{days_both}. Ось дней и ось прогонов слиты, и горизонт судьи "
                f"схлопывается тем сильнее, чем чаще шёл цикл")

        def _earliest_act(doc: dict) -> dict | None:
            rows = [r for r in (doc.get("per_verdict") or [])
                    if str(r.get("verdict")).upper() == "ACT"]
            return rows[0] if rows else None

        act_row_both, act_row_sib = _earliest_act(eval_both), _earliest_act(eval_sib)
        if act_row_both is None or act_row_sib is None:
            return UNMEASURED, ("стенд звена 4 не дал ACT-строки ни на одном из двух "
                                "журналов — горизонт сравнивать не на чем")
        fw_both = act_row_both.get("forward_days_available")
        fw_sib = act_row_sib.get("forward_days_available")
        net_both, net_sib = act_row_both.get("net_usd"), act_row_sib.get("net_usd")
        if fw_both != fw_sib or net_both != net_sib:
            return NOT_SATISFIED, (
                f"ПОЗДНИЙ ПРОГОН ТОГО ЖЕ ДНЯ вошёл в форвардное окно: у раннего ACT "
                f"форвардных дней {fw_sib} → {fw_both}, счёт ${net_sib} → ${net_both}. "
                f"Горизонт считается в ЗАПИСЯХ, а объявлен в ДНЯХ — на дне из 36 "
                f"прогонов он схлопнется в один день молча")

        return SATISFIED, (
            f"прогон дня цел у обоих: писатель {len(lines_one)} → {len(lines_both)} строк "
            f"(повтор того же прогона оставляет {after_rewrite}), читатель "
            f"{len(read_one)} → {len(read_both)} записей, критерий ACT {act_one} → "
            f"{act_both} и scored {scored_one} → {scored_both} при неизменных "
            f"{days_both} дн. наблюдения; горизонт раннего ACT {fw_both} дн. и счёт "
            f"${net_both} не сдвинулись от позднего прогона того же дня")
    finally:
        shutil.rmtree(collapsed, ignore_errors=True)
        shutil.rmtree(both, ignore_errors=True)
        shutil.rmtree(sibling_free, ignore_errors=True)


PROBES: dict[str, Callable[[str | None], "tuple[str, str]"]] = {
    "contract_manifest_parity_agrees": _probe_contract_manifest_parity,
    "artifact_contract_confirmed": _probe_artifact_contract,
    "lead_channel_wiring_ok": _probe_lead_channel_wiring,
    "adapter_status_live_apy": _probe_adapter_status_live_apy,
    "tier_promotion_loop_closed": _probe_tier_promotion_loop,
    "candidate_discovery_loop_closed": _probe_candidate_discovery_loop,
    "free_move_priced_as_free": _probe_free_move_priced_as_free,
    "decision_journal_keeps_every_run": _probe_decision_journal_keeps_every_run,
}


def validate_spec(spec: str) -> str | None:
    """Разобрать ОБЪЯВЛЕНИЕ пробы, не исполняя её. Возврат: None — годится, иначе причина.

    Существует затем, чтобы отказ случился при РОЖДЕНИИ карточки, а не через сутки в
    отчёте. `run_probe` на незарегистрированное имя честно отвечает `unmeasured` — но
    `unmeasured` в отчёте выглядит как «нечем проверить сегодня», а на самом деле значит
    «этот критерий не будет измерен НИКОГДА». Разница видна только тому, кто помнит
    реестр наизусть, поэтому её ловит писатель, а не читатель.
    """
    spec = (spec or "").strip()
    if not spec:
        return "проба пуста"
    name, _, arg = spec.partition(":")
    name, arg = name.strip(), arg.strip()
    if not name:
        return "у пробы нет имени"
    if name not in PROBES:
        return (f"проба {name!r} не зарегистрирована. Известные: "
                f"{', '.join(sorted(PROBES))}")
    if arg and not _ARG_RE.match(arg):
        return f"аргумент пробы отвергнут (не ключ): {arg!r}"
    return None


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


#: Ветка доставки, с которой дочитывается невидимая часть популяции.
ORIGIN_REF = "origin/main"

#: Каталог карточек внутри репозитория — адрес один и тот же в любом дереве.
TRACKER_REL = "nimbalyst-local/tracker"


def _git(args: list, *, repo_root: str, timeout: float = 20.0):
    """`git` в указанном дереве. `None` — команда не удалась (это НЕ «пусто»)."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", repo_root] + args, capture_output=True,
                           text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _repo_root_for(tracker_dir: str) -> str:
    """Дерево, которому принадлежит этот каталог карточек (`…/nimbalyst-local/tracker`)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(tracker_dir)))


def _is_git_repo(path: str) -> bool:
    """Есть ли тут репозиторий вообще. Отличать от «есть, но не прочитался»."""
    return _git(["rev-parse", "--git-dir"], repo_root=path) is not None


def cards_declaring_a_probe_on_ref(*, repo_root: str, ref: str = ORIGIN_REF):
    """`{имя карточки: текст}` для карточек, объявивших пробу на `ref`. `None` ⇒ не измерено.

    ЗАЧЕМ ЭТО ЕСТЬ. `audit()` читал ТОЛЬКО каталог того дерева, в котором запущен, —
    а обязательный шаг 0-офис ходит из прод-дерева, куда `nimbalyst-local/` не
    синхронизируется. Замер 03.09: в проде 599 карточек, на `origin/main` — 882;
    283 сторож не видел ВООБЩЕ и о слепоте не говорил, называя число прочитанных
    как полное. Живое следствие: из пяти объявленных на origin проб прод-дерево
    видело ОДНУ. Тот же класс уже чинили в очереди (ADR-153).

    ПОЧЕМУ ТАК ДЁШЕВО. Дочитывать всю популяцию не нужно и вредно: сверка трекера
    с origin однажды стоила 107 с и ~1041 процесс git, и цена сторожа его же и
    выключила (ADR-211). Здесь предмет узкий — карточки, объявившие пробу, — и он
    добывается ОДНОЙ командой `git grep` по ref (замер 03.09: **0.17 с**, 5 файлов),
    после чего читается ровно столько блобов, сколько невидимо локально.

    `None` — «не измерено» (нет git, нет ref, сеть/индекс недоступны), и вызывающий
    ОБЯЗАН сказать это вслух: молчание здесь неотличимо от «все на месте».
    """
    listing = _git(["grep", "-l", "^acceptance_probe:", ref, "--", TRACKER_REL + "/"],
                   repo_root=repo_root)
    if listing is None:
        return None
    out: dict = {}
    for line in listing.splitlines():
        # формат строки: `<ref>:<путь>`
        _, _, path = line.partition(":")
        if not path.endswith(".md") or os.path.basename(path).startswith("_"):
            continue
        blob = _git(["show", f"{ref}:{path}"], repo_root=repo_root)
        if blob is None:
            return None              # частично прочитанная популяция — не популяция
        out[os.path.basename(path)] = blob
    return out


def audit(tracker_dir: str | None = None, *, origin_readthrough: bool = True,
          ref: str = ORIGIN_REF, repo_root: str | None = None) -> dict:
    """Пройти карточки трекера и вынести вердикт по объявленным критериям.

    Возврат: `{"tracker_dir", "scanned", "counts", "rows", "origin"}`. `rows` — только
    те карточки, у которых проба ОБЪЯВЛЕНА (остальные тут не предмет: у них критерия
    в машинной форме нет, и молчать о них честнее, чем считать их выполненными).

    `origin_readthrough` дочитывает с `ref` карточки, которых в этом дереве нет
    (см. :func:`cards_declaring_a_probe_on_ref`). Блок `origin` описывает исход
    дочитывания ТРЕМЯ состояниями: `read` (сколько добрано), `unmeasured`
    (дочитать не удалось — назвать вслух) и `off` (не просили). Слепота, о которой
    не сказано, — та же слепота.
    """
    tracker_dir = tracker_dir or os.path.join(REPO_ROOT, "nimbalyst-local", "tracker")
    # Дерево для дочитывания выводится ИЗ САМОГО tracker_dir, а не берётся у
    # живого репозитория. Первая редакция брала `REPO_ROOT` — и тогда вызов с
    # чужим каталогом карточек дочитывал популяцию НЕ ТОГО дерева: четыре
    # соседних теста, читавших временный каталог, получили пять живых карточек
    # с `origin/main`. Их герметичность была ЗАНЯТА у субъекта (он читал только
    # свой каталог) и исчезла вместе с этой правкой — класс известен, поэтому
    # чинится связь, а не тесты.
    repo_root = repo_root or _repo_root_for(tracker_dir)
    rows: list[dict] = []
    scanned = 0
    local_names: set = set()
    sources: list = []
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
            local_names.add(name)
            sources.append((name, text, False))

    origin: dict = {"state": "off", "read": 0, "ref": ref}
    if origin_readthrough and not _is_git_repo(repo_root):
        # ТРЕТИЙ исход, а не «не измерено»: у каталога карточек, лежащего вне
        # репозитория, ветки доставки нет ПО ПОСТРОЕНИЮ — дочитывать не с чего.
        # Смешать это с «репозиторий есть, а прочитать не вышло» значит либо
        # утопить настоящий отказ в шуме, либо (наоборот) промолчать о нём.
        origin = {"state": "no_repo", "read": 0, "ref": ref,
                  "reason": f"{repo_root} — не git-репозиторий: ветки `{ref}` "
                            f"здесь нет по построению, дочитывать не с чего"}
    elif origin_readthrough:
        remote = cards_declaring_a_probe_on_ref(repo_root=repo_root, ref=ref)
        if remote is None:
            origin = {"state": "unmeasured", "read": 0, "ref": ref,
                      "reason": f"популяцию с `{ref}` дочитать не удалось (нет git, "
                                f"нет ref или чтение прервалось) — сколько карточек "
                                f"этому дереву невидимо, НЕ ИЗМЕРЕНО"}
        else:
            added = [(n, t) for n, t in sorted(remote.items()) if n not in local_names]
            sources.extend((n, t, True) for n, t in added)
            origin = {"state": "read", "read": len(added), "ref": ref,
                      "declared_on_ref": len(remote)}

    for name, text, from_origin in sources:
            fm = parse_frontmatter(text)
            spec = fm.get("acceptance_probe")
            if not spec:
                continue
            status = (fm.get("status") or "?").strip()
            if status in NEVER_PROBED_STATUSES:
                continue
            is_open = status in OPEN_STATUSES
            # Пробу гоняем ТОЛЬКО у открытой карточки. Предмет модуля — «открытая
            # карточка, чей критерий уже выполнен»; у закрытой этот вопрос не стоит,
            # а вердикт по ней стоил бы времени и производил бы `[НЕ ИЗМЕРЕНО]` о
            # СВЕДЁННОЙ работе — шум, неотличимый по форме от настоящей находки.
            # Объявление при этом не теряется: закрытые считаются отдельно.
            if is_open:
                verdict, detail = run_probe(spec)
            else:
                verdict, detail = NOT_PROBED, f"карточка закрыта ({status}) — вопрос снят"
            rows.append({
                "card": name[:-3],
                "status": status,
                "open": is_open,
                "probe": spec,
                "verdict": verdict,
                "detail": detail,
                # Провенанс, а не украшение: строка про карточку, которой в этом
                # дереве нет, иначе читается как «файл рядом, посмотри» — и
                # следующая сессия идёт искать его на диске.
                "from_origin": from_origin,
            })
    counts = {
        "declared": len(rows),
        "declared_open": sum(1 for r in rows if r["open"]),
        "declared_closed": sum(1 for r in rows if not r["open"]),
        "satisfied_but_open": sum(1 for r in rows if r["open"] and r["verdict"] == SATISFIED),
        "not_satisfied": sum(1 for r in rows if r["verdict"] == NOT_SATISFIED),
        "unmeasured": sum(1 for r in rows if r["verdict"] == UNMEASURED),
    }
    counts["from_origin"] = sum(1 for r in rows if r.get("from_origin"))
    return {"tracker_dir": tracker_dir, "scanned": scanned, "counts": counts,
            "rows": rows, "origin": origin}


def report_lines(result: dict) -> list[str]:
    """Строки для шага 0-офис. Пустой ответ невозможен: «проб не объявлено» —
    тоже состояние, и молчание о нём неотличимо от «всё сошлось»."""
    c = result.get("counts") or {}
    where = result.get("tracker_dir")
    out = [f"— критерии открытых карточек (трекер: {where}) —"]
    # ПОПУЛЯЦИЯ — ПЕРВОЙ строкой, до любых вердиктов. До #467 сторож читал только
    # своё дерево и называл число прочитанных как ПОЛНОЕ: из прод-дерева, откуда
    # ходит обязательный шаг 0-офис, он видел 599 карточек из 882 и о 283
    # невидимых не говорил ничего. «Прочитано столько» и «столько и есть» — разные
    # утверждения, и подменять второе первым нельзя даже молча.
    origin = result.get("origin") or {}
    if origin.get("state") == "unmeasured":
        out.append(f"   [{'НЕ ИЗМЕРЕНО'}] {origin.get('reason')}")
    elif origin.get("state") == "read" and origin.get("read"):
        out.append(f"   популяция дочитана с `{origin.get('ref')}`: +{origin['read']} "
                   f"карточк(и) с объявленной пробой, которых в этом дереве НЕТ "
                   f"(на ref объявлено {origin.get('declared_on_ref')})")
    if not (result.get("rows") or []):
        out.append(f"   проб не объявлено ни на одной из {result.get('scanned', 0)} карточек "
                   f"— критерии живут прозой, машинно не перемеряются (ADR-208)")
        return out
    # «Проб 3, открытых 0» и «проб не объявлено» — РАЗНЫЕ состояния с одинаковым
    # следствием (сторож ничего не меряет). Не сказать этого вслух значит выдать
    # ноль предметов за здоровье: ровно так модуль прожил первые сутки (ADR-209).
    if not c.get("declared_open"):
        out.append(f"   ⚠️ проб объявлено {c.get('declared', 0)}, но ВСЕ на закрытых карточках "
                   f"— открытых предметов НОЛЬ, сторожу нечего мерить (ADR-209)")
        return out
    out.append(f"   объявлено проб {c.get('declared', 0)} (открытых {c.get('declared_open', 0)}, "
               f"на закрытых {c.get('declared_closed', 0)}) · "
               f"КРИТЕРИЙ ВЫПОЛНЕН при открытой карточке {c.get('satisfied_but_open', 0)} · "
               f"ещё не выполнен {c.get('not_satisfied', 0)} · не измерено {c.get('unmeasured', 0)}")
    for r in result["rows"]:
        where_from = " [дочитана с origin, файла в этом дереве нет]" if r.get("from_origin") else ""
        if r["open"] and r["verdict"] == SATISFIED:
            out.append(f"   🟩 КРИТЕРИЙ ВЫПОЛНЕН, а карточка открыта ({r['status']}): "
                       f"{r['card']}{where_from} — {r['detail']}. Перемерить и закрыть, "
                       f"а не делать заново")
        elif r["verdict"] == UNMEASURED:
            out.append(f"   [НЕ ИЗМЕРЕНО] {r['card']}{where_from}: {r['detail']}")
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
