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
import inspect
import json
import os
import re
import sys
import pathlib as _pathlib
from datetime import datetime, timezone
from typing import Callable

from spa_core.utils.observation import observed

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

#: Статусы, в которых карточка считается ЗАКРЫТОЙ. Копия списка очереди
#: (`orchestrator_queue._TERMINAL_ON_ORIGIN`) заведена намеренно узко — проба
#: спрашивает только «закрыта ли», и расширять её до правил очереди нельзя.
_TERMINAL_HERE = ("ingested", "done", "owner-done-archived")

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



#: Имя переписи в `sys.modules`. Скрипт лежит в `scripts/` (не пакет) — грузится по пути;
#: имя ФИКСИРОВАНО, чтобы положительный контроль мог подменить модуль и увидеть, что
#: проба читает ИМЕННО перепись, а не собственную копию её логики.
CENSUS_MODULE_NAME = "_spa_capital_census_under_probe"
#: Старше этого — книга уже не наблюдение, а снимок. Производитель переписывает
#: `current_positions.json` каждым дневным циклом; сутки = «пропущен хотя бы один».
#: То же число и та же причина, что у `ADAPTER_STATUS_MAX_AGE_H`: спор МЕЖДУ двумя
#: артефактами имеет смысл, только пока свежи оба.
CENSUS_MAX_AGE_H = 24.0


def _census_module():
    """Перепись наблюдаемости капитала как модуль: один раз на процесс."""
    import importlib.util
    mod = sys.modules.get(CENSUS_MODULE_NAME)
    if mod is not None:
        return mod
    path = os.path.join(REPO_ROOT, "scripts", "capital_observability_census.py")
    spec = importlib.util.spec_from_file_location(CENSUS_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path} не загружается как модуль")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[CENSUS_MODULE_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(CENSUS_MODULE_NAME, None)
        raise
    return mod


def _probe_second_artifact_tvl_agrees(arg: str | None, *,
                                      now: "datetime | None" = None,
                                      data_dir: str | None = None) -> tuple[str, str]:
    """Критерий: второй артефакт НЕ спорит с поверхностью решения по оси TVL.

    Предмет — ровно тот, что у карточки `inbox-vtoroi-artefakt-neset-literaly-tvl-tam-g`:
    про один и тот же профинансированный протокол в один и тот же цикл система держит
    ДВА снимка, и 12.09 они расходились — `current_positions.json → feed_coverage`
    объявлял TVL наблюдением, а `data/adapter_status.json` в ту же секунду нёс литерал
    (`aave_v3` $12B против $206.1M, ×58.2). Гейт финансирования при этом не обманут: он
    судит по первому. Обманут ОТЧЁТ ВЛАДЕЛЬЦУ и советательные стратегии — шесть
    потребителей читают именно второй файл.

    **Ось здесь одна намеренно.** Перепись возвращает код 1 ещё и от доли APY, от
    расхождения суммы книги с объявленным `deployed_usd`, от нечитаемого второго
    артефакта и от спора ВНУТРИ первого файла — это соседние предметы с другими
    владельцами, и вердикт по ним ответил бы не на вопрос карточки (её раздел
    «Границы»: «Задача целиком в производителе второго артефакта»). Считается спор по
    оси TVL плюс протокол, которого во втором артефакте НЕТ ВОВСЕ: про его TVL этот
    файл тоже не наблюдает ничего, и молчание здесь не согласие.

    **Возраст — часть вопроса, а не предположение.** `data/` частично лежит в git,
    поэтому в worktree и на CI оба файла ЕСТЬ — но это замороженный канон origin, и
    спор двух снимков неизвестного возраста ничего не говорит о живом производителе.
    Протухшая книга ⇒ `unmeasured`, НИКОГДА не `not_satisfied`. Время — вход (`now`),
    а не окружение: обе стороны сравнения закрепляются в тесте.

    Каталог данных — тоже ВХОД (`data_dir`), по той же причине, что и часы: иначе
    вердикт решала бы переменная окружения `SPA_DATA_DIR`, а не предмет. Умолчание —
    `data/` того дерева, из которого пробу позвали (шаг 0-офис ходит из прод-дерева).

    Проба только ЧИТАЕТ: перепись ничего не пишет и ничего не чинит.
    """
    try:
        census = _census_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"перепись не загружена: {type(exc).__name__}: {exc}"

    try:
        res = census.measure(data_dir or os.path.join(REPO_ROOT, "data"))
    except census.NotMeasured as exc:
        return UNMEASURED, f"перепись отказалась мерить: {exc}"
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, f"перепись упала: {type(exc).__name__}: {exc}"

    stamp = res.get("as_of")
    if not stamp:
        return UNMEASURED, ("у снимка книги нет `generated_at` — возраст не измерен, "
                            "судить о споре двух снимков нечем")
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return UNMEASURED, (f"снимок книги: generated_at {stamp!r} не разобран — "
                            f"возраст не измерен")
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age_h = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    if age_h > CENSUS_MAX_AGE_H:
        return UNMEASURED, (f"снимок книги протух: возраст {age_h:.1f}ч при пределе "
                            f"{CENSUS_MAX_AGE_H:.0f}ч (замороженный канон, не наблюдение) — "
                            f"мерить надо из дерева с живым data/")

    second = res.get("second_artifact") or {}
    if not second.get("read"):
        return UNMEASURED, ("сверка со вторым артефактом НЕ СОСТОЯЛАСЬ: "
                            f"{second.get('reason') or 'причина не названа'}")

    rows = [r for r in (second.get("disagreements") or [])
            if r.get("axis") == "tvl" or r.get("kind") == "absent_from_second_artifact"]
    if not rows:
        return SATISFIED, (f"спора по оси TVL нет: развёрнуто ${res['deployed_usd']:,.2f} "
                           f"в {res['protocols']} протокол(ах), второй артефакт согласен "
                           f"по каждому (снимок {str(stamp)[:19]}, возраст {age_h:.1f}ч)")

    details = []
    for r in rows:
        if r.get("kind") == "absent_from_second_artifact":
            details.append(f"{r['protocol']} (${r['usd']:,.2f}): протокола нет во втором "
                           f"артефакте вовсе")
            continue
        sv, tv = r.get("surface_value"), r.get("second_value")
        extra = ""
        if isinstance(sv, (int, float)) and isinstance(tv, (int, float)) and sv:
            extra = f" — ${tv:,.0f} против ${sv:,.0f}, ×{tv / sv:,.1f}"
        details.append(f"{r['protocol']} (${r['usd']:,.2f}): поверхность — {r['surface']}, "
                       f"adapter_status.json — {r['second']}{extra}")
    return NOT_SATISFIED, " · ".join(details)


#: Имя переписи доминирования KEEP в `sys.modules`. Модуль ПАКЕТНЫЙ, поэтому его
#: подмена в `sys.modules` доходит до пробы — контроль этим и пользуется, чтобы
#: увидеть: проба читает ПРИБОР, а не собственную копию его логики.
KEEP_DOMINANCE_MODULE = "spa_core.monitoring.keep_dominance_census"
#: Журнал вердиктов получает запись КАЖДЫМ дневным циклом на каждую книгу. Новее
#: этого числа дней — наблюдение; старше — замороженный канон `data/` из git
#: (в worktree и на CI журнала нет вовсе, но он МОЖЕТ там быть и быть старым, и
#: тогда вердикт относился бы не к живой системе). Два дня, а не один: одна
#: пропущенная книгой дата — обычный сдвиг такта, две — журнал не живой.
DECISION_JOURNAL_MAX_AGE_D = 2.0


def _keep_dominance_module():
    """Перепись доминирования KEEP. Импорт, а не загрузка по пути: модуль пакетный."""
    import importlib
    return importlib.import_module(KEEP_DOMINANCE_MODULE)


def _probe_economics_net_return_dominates_keep(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None) -> tuple[str, str]:
    """Критерий §49 `Economics` приказа CIO: «Решения используют net expected return, а не raw APY».

    До этой пробы критерий был ИЗМЕРЕН прибором и НЕ ИЗМЕРЕН сводкой. Перепись
    `keep_dominance_census` живёт с цикла #702, её артефакт пишется в такте и свеж —
    а запись «этот прибор есть мера этого критерия» лежала ПРОЗОЙ в заметке
    `architecture/manifest.json`, и сводный замер (`scripts/cio_acceptance_rollup.py`)
    честно отвечал «машинной пробы, объявившей себя мерой этого критерия, в реестре
    НЕТ». Десять таких строк читались как десять одинаковых дыр, а цена у них была
    разная (ADR-506): здесь не хватало ОДНОГО поля. Заказ владельца G94 п. 1 требует
    перенести привязку в поле — но по одной пробе и каждую со своим контролем в обе
    стороны (`.claude/rules/acceptance.md`, п. 3), иначе появится пять объявлений и
    ни одного наблюдения.

    Вердикт — ПЕРЕНОС вердикта прибора, а не второе правило
    ---------------------------------------------------------------------------
    `OK` → `satisfied` · `WARNING`/`CRITICAL` → `not_satisfied` · третий исход
    прибора → `unmeasured`. Своего порога у пробы нет НИ ОДНОГО: «много ли находок»
    и «считается ли находка свежей» решено внутри переписи, обосновано её
    докладом и закреплено её тестами. Второе правило здесь было бы вторым местом
    для числа — тот самый дефект, против которого написано
    `.claude/rules/site-numbers.md`.

    Почему находка = «критерий НЕ выполнен», а не «предупреждение»
    ---------------------------------------------------------------------------
    Порода `dominated_by_keep` (`gain_pp < 0`) есть НАБЛЮДАЕМОЕ доказательство,
    что KEEP не входит в ранжирование: решение ничего не делать доступно всегда и
    стои́т $0, поэтому оптимизатор по чистой ожидаемой доходности отрицательного
    прироста выдать не может. Порода `net_negative_missed_by_gate` — тот же ответ с
    другой стороны: чистый исход за горизонт владельца отрицателен, а собственный
    гейт записи сказал `True`. И то, и другое — прямое «нет» на вопрос §49.

    Прибор гоняется НАСТОЯЩИЙ
    ---------------------------------------------------------------------------
    Проба зовёт `run_census` на живых журналах, а не читает готовый артефакт: артефакт
    неизвестного возраста ответил бы о том дне, когда его писали. Каталог данных —
    ВХОД (`data_dir`), часы — ВХОД (`now`); иначе вердикт решали бы переменная
    окружения и стенные часы, а не предмет (`.claude/rules/deployment.md`).

    Чего проба НЕ докладывает (назвать слепоту — часть замера)
    ---------------------------------------------------------------------------
    * **Записи третьего исхода вердикт не меняют.** `records_unmeasured` (запись
      нечитаема, пересчёт не сошёлся) и `net_gate_unchecked` (старая схема без
      гейта окупаемости) НАЗЫВАЮТСЯ в пояснении числом, но статус книги решает
      перепись, и переигрывать её здесь значило бы завести второе правило.
      Замер 29.09 (прод): `net_gate_unchecked` 12 у книги `conservative`.
    * **Правду объявления.** Что перепись мерит ИМЕННО этот критерий — утверждение
      её собственного доклада (`CRITERION`), и проба его СВЕРЯЕТ (ниже), а не
      принимает на веру. Полноту же критерия не докладывает никто: «net expected
      return» шире одного знака прироста, и зазор назван здесь.
    * **Ничего не чинит.** Только читает; ни строки аллокатора, RiskPolicy,
      стоп-крана или живого трека.
    """
    try:
        census = _keep_dominance_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, (f"перепись доминирования KEEP не загружена: "
                            f"{type(exc).__name__}: {exc}")

    # Прибор обязан сам объявлять себя мерой ЭТОГО критерия. Совпадение имени
    # критерия проверяется ПО ЯКОРЮ (`§49 Economics`), а не подстрокой «Economics»:
    # подстрока совпала бы и с чужой заметкой, и объявление стало бы украшением.
    anchor = "§49 Economics"
    declared = str(getattr(census, "CRITERION", "") or "")
    if not declared.startswith(anchor):
        return UNMEASURED, (f"перепись не объявляет себя мерой {anchor!r} "
                            f"(её CRITERION: {declared[:80]!r}) — привязка не сходится, "
                            f"и считать её мерой этого критерия нельзя")

    data = data_dir or os.path.join(REPO_ROOT, "data")
    try:
        report = census.run_census(_pathlib.Path(data), now=now)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"перепись доминирования KEEP упала: "
                            f"{type(exc).__name__}: {exc}")

    if not report.get("measured"):
        return UNMEASURED, (f"перепись отказалась мерить: "
                            f"{report.get('reason') or 'причина не названа'}")

    books = [b for b in (report.get("books") or []) if b.get("measured")]
    dates = [b.get("latest_cycle_date") for b in books if b.get("latest_cycle_date")]
    if not dates:
        return UNMEASURED, ("ни у одной измеренной книги нет `latest_cycle_date` — "
                            "возраст журнала вердиктов не измерен, и судить о живой "
                            "системе нечем")
    newest = max(str(d) for d in dates)
    ref = (now or datetime.now(timezone.utc)).date()
    try:
        age_d = (ref - datetime.fromisoformat(newest).date()).days
    except ValueError:
        return UNMEASURED, (f"`latest_cycle_date` {newest!r} не разобран как дата — "
                            f"возраст журнала вердиктов НЕ ИЗМЕРЕН")
    if age_d > DECISION_JOURNAL_MAX_AGE_D:
        return UNMEASURED, (f"журнал вердиктов протух: свежайшая дата цикла {newest} — "
                            f"{age_d} дн назад при пределе "
                            f"{DECISION_JOURNAL_MAX_AGE_D:.0f} (замороженный канон "
                            f"`data/`, не наблюдение) — мерить надо из дерева с живым "
                            f"data/")

    where = (f"книг {len(books)}, свежайший цикл {newest}, пороги "
             f"{report['policy']['version']}/{report['policy']['mode']}, "
             f"горизонт {report['horizon_days']:.0f} дн")
    blind = (f"третий исход записей: нечитаемых {report.get('records_unmeasured', 0)}, "
             f"без гейта окупаемости {report.get('net_gate_unchecked', 0)}")

    status = report.get("status")
    if status == census.STATUS_OK:
        return SATISFIED, (f"находок нет ни в одной книге: предъявленный оптимум нигде "
                           f"не проигрывает решению ничего не делать, и ни один "
                           f"отрицательный чистый исход не прошёл мимо гейта "
                           f"окупаемости ({where}; {blind})")
    if status in (census.STATUS_CRITICAL, census.STATUS_WARNING):
        fresh = report.get("fresh_findings", 0)
        kinds = {}
        for f in report.get("findings") or []:
            kinds[f.get("kind")] = kinds.get(f.get("kind"), 0) + 1
        by_kind = ", ".join(f"{k}: {v}" for k, v in sorted(kinds.items())) or "порода не названа"
        when = ("в свежайшем цикле" if fresh else
                "только в истории — в свежайшем цикле находок нет")
        return NOT_SATISFIED, (f"решения НЕ ранжируются по чистой ожидаемой "
                               f"доходности: материальных находок "
                               f"{report.get('findings_material', 0)} ({by_kind}), "
                               f"{when}; максимум выведенного из оборота "
                               f"${report.get('dedeployed_usd_max', 0.0):,.2f} "
                               f"({where}; {blind})")
    return UNMEASURED, (f"перепись вернула статус {status!r}, который не переносится в "
                        f"вердикт критерия — молчать об этом нельзя")

#: Имя переписи сроков жизни преимущества в `sys.modules`. Модуль ПАКЕТНЫЙ, поэтому
#: его подмена в `sys.modules` доходит до пробы — контроль этим и пользуется, чтобы
#: увидеть: проба читает ПРИБОР, а не собственную копию его логики.
GAIN_PERSISTENCE_MODULE = "spa_core.monitoring.gain_persistence_census"

#: Ряд наблюдённых ставок (`apy_series_daily.json`) пишется ТЕМ ЖЕ дневным циклом,
#: что и журнал вердиктов, поэтому предел возраста у него ТОТ ЖЕ. Это ССЫЛКА, а не
#: второй литерал: два числа на один такт были бы вторым местом для числа
#: (`.claude/rules/site-numbers.md`). Своё имя — потому что артефакт другой, и
#: спрашивать о его возрасте приходится отдельным вопросом.
OBSERVED_SERIES_MAX_AGE_D = DECISION_JOURNAL_MAX_AGE_D


def _gain_persistence_module():
    """Перепись сроков жизни преимущества. Импорт, а не загрузка по пути: модуль пакетный."""
    import importlib
    return importlib.import_module(GAIN_PERSISTENCE_MODULE)


def _probe_persistence_advantage_outlives_horizon(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None) -> tuple[str, str]:
    """Критерий §49 `Persistence` приказа CIO: «Transient APY spikes не вызывают ненужные trades».

    Вторая привязка заказа владельца G95 п. 1 — и снова ОДНА, а не пакетом: пять
    объявлений и ни одного наблюдения были бы переписью, а не работой (запрет
    самого G94). Перепись `gain_persistence_census` живёт с цикла #702, её артефакт
    пишется в такте и свеж (замер 29.09: 1,5 ч при объявленном пределе 12 ч) — а
    запись «этот прибор есть мера этого критерия» лежала ПРОЗОЙ в заметке
    `architecture/manifest.json`, и сводный замер (`scripts/cio_acceptance_rollup.py`)
    честно отвечал «машинной пробы, объявившей себя мерой этого критерия, в реестре
    НЕТ». Цена этой строки измерена ADR-506 как `TRANSCRIPTION`: не хватает ОДНОГО
    поля.

    Вердикт — ПЕРЕНОС вердикта прибора, а не второе правило
    ---------------------------------------------------------------------------
    `OK` → `satisfied` · `WARNING`/`CRITICAL` → `not_satisfied` · третий исход
    прибора → `unmeasured`. Своего порога у пробы нет НИ ОДНОГО: «сколько дней
    считается достаточным» решено колонкой владельца (`min_hold_days`,
    `max_payback_days`, ADR-060 §3), которую прибор читает сам и без которой
    ОТКАЗЫВАЕТ мерить. Второе правило здесь было бы вторым местом для числа.

    **`WARNING` переносится в «не выполнен», а не в «предупреждение».** Эта порода
    означает: ход с умершим преимуществом в журнале ЕСТЬ, но он старше горизонта
    владельца. «Сегодня тихо» не есть «такого не бывало» — доктрина самого прибора,
    и читать её как исполненный критерий значило бы дать тишине силу
    доказательства.

    Почему умерший срок = «критерий НЕ выполнен»
    ---------------------------------------------------------------------------
    Критерий владельца говорит о ВРЕДЕ: спайк не должен вызывать НЕНУЖНЫЙ ход.
    Порода `died_before_min_hold` есть наблюдаемое доказательство вреда в чистом
    виде — преимущество, которым ход оправдан, кончилось раньше, чем истёк
    минимальный срок удержания: выходить запрещено, а выходить уже не из чего.
    `died_within_payback_horizon` — тот же вред мягче: утверждение «цена окупится
    за N дней» стояло на ставке, которой через день не стало.

    Прибор гоняется НАСТОЯЩИЙ
    ---------------------------------------------------------------------------
    Проба зовёт `run_census` на живых журналах, а не читает готовый артефакт:
    артефакт неизвестного возраста ответил бы о том дне, когда его писали.
    Каталог данных — ВХОД (`data_dir`), часы — ВХОД (`now`); иначе вердикт решали
    бы переменная окружения и стенные часы, а не предмет
    (`.claude/rules/deployment.md`).

    Свежесть спрашивается у РЯДА, а не у журнала ходов — и это не деталь
    ---------------------------------------------------------------------------
    У Economics ту же роль играл журнал вердиктов: он получает запись КАЖДЫМ
    дневным циклом, поэтому его возраст и есть признак живого наблюдения. Здесь
    так спрашивать НЕЛЬЗЯ: журнал ходов (`trades.json`) пополняется только когда
    ход был, и «две недели без ребаланса» — обычное состояние, а не протухший
    источник. Требовать свежести от него значило бы превратить спокойную неделю в
    «НЕ ИЗМЕРЕНО». Ежедневно пишется РЯД наблюдённых ставок
    (`apy_series_daily.json`), и его возраст спрашивается ниже.

    Дверь, которую этот вопрос закрывает, названа точно: в worktree и на CI ряда
    нет вовсе (файл не версионируется), и перепись там отказывает САМА. Опасен
    другой случай — ряд ЕСТЬ, но накопитель перестал его писать: тогда без этого
    вопроса вердикт о «сегодня» выносился бы по материалу прошлого месяца молча.

    Чего проба НЕ докладывает (назвать слепоту — часть замера)
    ---------------------------------------------------------------------------
    * **Ходы без материала вердикт не меняют.** `unmeasured_no_material` (ряда у
      ключа нет / ход раньше начала ряда / форвардных дней с полным материалом
      нет) и `not_a_transfer` (ход ничего не переносит) НАЗЫВАЮТСЯ в пояснении
      числом, но статус решает перепись, и переигрывать её здесь значило бы
      завести второе правило. Замер 29.09 (прод): из 34 ходов измеримы 12.
    * **Второй операнд.** Прибор мерит ставку цели против ставки ПОКИНУТОГО
      источника («стоило ли перекладывать»), а не против ставки самой цели в день
      хода («был ли у цели спайк»). Выбор назван в самом приборе; буква критерия
      ближе ко второму, вред — к первому, и зазор здесь не спрятан.
    * **§-тест 2 приказа не воспроизводим целиком:** в записи исполненного хода
      нет ни цены, ни ожидаемого выигрыша, ни срока окупаемости. Это третий исход
      прибора, а не ноль, и он тоже назван в пояснении.
    * **Правду объявления** проба СВЕРЯЕТ (ниже) по якорю, а не принимает на веру.
      Доклад прибора ссылается на ту же константу, поэтому второй, «докладной»
      сверки здесь нет: она была бы тавтологичной по построению, и молчать об этом
      нельзя.
    * **Ничего не чинит.** Только читает; ни строки аллокатора, RiskPolicy,
      стоп-крана, `TriggerParams` или живого трека.
    """
    try:
        census = _gain_persistence_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, (f"перепись сроков жизни преимущества не загружена: "
                            f"{type(exc).__name__}: {exc}")

    # Прибор обязан сам объявлять себя мерой ЭТОГО критерия, и объявление читается
    # ДО прогона — потому что на отказном пути доклад поля `criterion` не несёт
    # вовсе, и сверять там было бы нечего. Совпадение проверяется ПО ЯКОРЮ
    # (`§49 Persistence`), а не подстрокой «Persistence»: подстрока совпала бы и с
    # чужой заметкой про устойчивость ставки, и объявление стало бы украшением.
    anchor = "§49 Persistence"
    declared = str(getattr(census, "CRITERION", "") or "")
    if not declared.startswith(anchor):
        return UNMEASURED, (f"перепись не объявляет себя мерой {anchor!r} "
                            f"(её CRITERION: {declared[:80]!r}) — привязка не сходится, "
                            f"и считать её мерой этого критерия нельзя")

    data = data_dir or os.path.join(REPO_ROOT, "data")
    try:
        report = census.run_census(_pathlib.Path(data), now=now)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"перепись сроков жизни преимущества упала: "
                            f"{type(exc).__name__}: {exc}")

    if not report.get("measured"):
        return UNMEASURED, (f"перепись отказалась мерить: "
                            f"{report.get('reason') or 'причина не названа'}")

    series = report.get("series") or {}
    last_day = series.get("last_day")
    if not last_day:
        return UNMEASURED, ("у ряда наблюдённых ставок нет последнего дня — возраст "
                            "материала НЕ ИЗМЕРЕН, и судить о живой системе нечем")
    ref = (now or datetime.now(timezone.utc)).date()
    try:
        age_d = (ref - datetime.fromisoformat(str(last_day)).date()).days
    except ValueError:
        return UNMEASURED, (f"последний день ряда {last_day!r} не разобран как дата — "
                            f"возраст материала НЕ ИЗМЕРЕН")
    if age_d > OBSERVED_SERIES_MAX_AGE_D:
        return UNMEASURED, (f"ряд наблюдённых ставок протух: последний день {last_day} — "
                            f"{age_d} дн назад при пределе "
                            f"{OBSERVED_SERIES_MAX_AGE_D:.0f} (накопитель ряда молчит "
                            f"либо это замороженный канон `data/`, а не наблюдение) — "
                            f"мерить надо из дерева с живым data/")

    counts = report.get("counts") or {}
    pol = report.get("policy") or {}
    where = (f"ходов {counts.get('moves', 0)}, измеримы "
             f"{counts.get('measurable', 0)}, ряд "
             f"{series.get('first_day')}..{last_day}, горизонты владельца "
             f"{pol.get('min_hold_days')}/{pol.get('max_payback_days')} дн "
             f"({pol.get('mode')}/{pol.get('version')})")
    blind = (f"третий исход ходов: без материала о ставках "
             f"{counts.get('unmeasured_no_material', 0)}, ничего не переносят "
             f"{counts.get('not_a_transfer', 0)}; срок окупаемости в записи хода "
             f"отсутствует, поэтому §-тест 2 приказа целиком не воспроизводим")

    status = report.get("status")
    if status == census.STATUS_OK:
        return SATISFIED, (f"каждый измеримый ход пережил горизонт владельца: ходов с "
                           f"умершим преимуществом нет ни одного, пережили горизонт "
                           f"{counts.get('outlived_horizon', 0)} ({where}; {blind})")
    if status in (census.STATUS_CRITICAL, census.STATUS_WARNING):
        dead = (counts.get("died_before_min_hold", 0)
                + counts.get("died_within_payback_horizon", 0))
        recent = counts.get("recent_dead_within_horizon", 0)
        when = (f"внутри горизонта владельца от now таких ходов {recent}"
                if recent else
                "в свежайшем горизонте таких ходов нет — только в истории, и это НЕ "
                "«такого не бывало»")
        return NOT_SATISFIED, (
            f"преимущество, которым ход был оправдан, УМЕРЛО раньше горизонта "
            f"владельца у {dead} ход(ов) (раньше минимального удержания "
            f"{counts.get('died_before_min_hold', 0)}, внутри срока окупаемости "
            f"{counts.get('died_within_payback_horizon', 0)}), пережили горизонт "
            f"{counts.get('outlived_horizon', 0)}; {when}; из них преимущества не "
            f"было уже в день хода у {counts.get('advantage_negative_at_move', 0)}, "
            f"на умершем преимуществе внутри горизонта "
            f"${report.get('usd_on_dead_advantage_recent', 0.0):,.2f} "
            f"({where}; {blind})")
    return UNMEASURED, (f"перепись вернула статус {status!r}, который не переносится в "
                        f"вердикт критерия — молчать об этом нельзя")


#: Имя переписи прыжков книги в `sys.modules`. Модуль ПАКЕТНЫЙ, поэтому его подмена
#: в `sys.modules` доходит до пробы — контроль этим и пользуется, чтобы увидеть: проба
#: читает ПРИБОР, а не собственную копию его логики.
BOOK_OSCILLATION_MODULE = "spa_core.monitoring.book_oscillation_census"


def _book_oscillation_module():
    """Перепись прыжков книги. Импорт, а не загрузка по пути: модуль пакетный."""
    import importlib
    return importlib.import_module(BOOK_OSCILLATION_MODULE)


def _standing_book_liveness(data: "_pathlib.Path", *,
                            now: "datetime | None", tail: str
                            ) -> "tuple[str | None, object]":
    """Живо ли дерево, о котором выносится вердикт: возраст СТОЯЩЕЙ книги.

    Возврат: `(None, (отметка, возраст_в_днях, документ))`, когда книга прочитана, отметка
    разобрана и возраст в пределе; `(UNMEASURED, причина)`, когда ответить нечем.
    Вердикта «не выполнен» отсюда не выходит НИ ОДНОГО: вопрос здесь не о
    предмете критерия, а о том, о живом ли дереве речь.

    Почему чтение ОДНО, а объяснение — у звавшего
    ---------------------------------------------------------------------------
    Вопрос «а живо ли это дерево» задают уже три пробы §49 (`Risk`, `Anti-churn`
    и `Pre-trade safety`), и предел с именем файла у них ОДИН — константы
    :data:`STANDING_BOOK_MAX_AGE_D` и :data:`STANDING_BOOK_FILE`. Само чтение до
    цикла #729 лежало двумя рукописными копиями; третья копия и была бы тем
    «одним правилом в трёх местах», которое расходится молча.

    А вот ПОСЛЕДСТВИЕ тишины мёртвого дерева у каждого критерия своё, и общего
    текста для него не существует: у `Anti-churn` молчание читалось бы как
    «книга больше не прыгает», у `Pre-trade safety` — как «ходы перепроверяются».
    Поэтому объяснение приходит от звавшего параметром `tail`, а не выдумывается
    здесь.
    """
    path = data / STANDING_BOOK_FILE
    try:
        standing = json.loads(path.read_text(encoding="utf-8"))
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"книга, которая стои́т сегодня, не прочитана ({path}): "
                            f"{type(exc).__name__}: {exc} — проверить, о живом ли "
                            f"дереве вердикт, НЕЧЕМ")
    stamp = observed(standing, "generated_at", kind=str)
    if stamp is None:
        return UNMEASURED, (f"у {STANDING_BOOK_FILE} нет отметки `generated_at` — "
                            f"возраст стоящей книги НЕ ИЗМЕРЕН, и отличить живое "
                            f"дерево от замороженного канона `data/` нечем")
    ref = now or datetime.now(timezone.utc)
    try:
        age_d = (ref - datetime.fromisoformat(stamp)).total_seconds() / 86400.0
    except (ValueError, TypeError) as exc:
        return UNMEASURED, (f"отметка стоящей книги {stamp!r} не разобрана как дата "
                            f"({type(exc).__name__}) — её возраст НЕ ИЗМЕРЕН")
    if age_d > STANDING_BOOK_MAX_AGE_D:
        return UNMEASURED, (f"стоящая книга протухла: {STANDING_BOOK_FILE} снята "
                            f"{stamp} — {age_d:.1f} дн назад при пределе "
                            f"{STANDING_BOOK_MAX_AGE_D:.0f} (дневной цикл её не "
                            f"переписывает либо это замороженный канон `data/`, а не "
                            f"наблюдение) — {tail}")
    #: Документ возвращается ЗДЕСЬ, а не читается звавшим заново: второе чтение
    #: того же файла могло бы застать уже ДРУГУЮ книгу, и вердикт относился бы к
    #: одной, а возраст — к другой.
    return None, (stamp, age_d, standing)


def _standing_book_agrees_with_journal_tail(
        report: dict, data: "_pathlib.Path", census,
        *, now: "datetime | None" = None) -> "tuple[str | None, str]":
    """Та ли это книга и тот ли это журнал — или мы судим о замороженном каноне.

    Возвращает `(None, "")`, когда вердикт переписи законно относится к живой
    системе, и `(UNMEASURED, причина)`, когда ответить нечем. Вердикта «не
    выполнен» отсюда не выходит НИ ОДНОГО: вопрос здесь не о прыжках книги, а о
    том, о чём вообще речь, — и смешать «книга прыгала» с «мы смотрим не на ту
    книгу» значило бы завести второе правило.

    Почему дверь именно ЭТА — и почему рассуждение своё, а не переписанное
    ---------------------------------------------------------------------------
    Урок ADR-508/ADR-510 применяется, а не копируется: адрес вопроса о свежести
    у каждого предмета СВОЙ, и здесь он получился третьим по счёту и по смыслу.

    Спрашивать возраст у журнала ходов НЕЛЬЗЯ: он пополняется, только когда ход
    БЫЛ. Замер 29.09 — последний ход `T034` от 11.09, восемнадцать дней назад, и
    это спокойная неделя, а не протухший источник; спросив у него, проба
    объявила бы исправную систему «НЕ ИЗМЕРЕНО».

    Но и молчать нельзя, и опасность здесь ОБРАТНАЯ вердикту `Risk`. Там ложь
    была бы о книге, которой уже нет; здесь — ЛОЖНАЯ ЗЕЛЁНАЯ: «возвратов от now
    нет» звучит одинаково и у системы, которая перестала прыгать, и у
    замороженного канона `data/` (в нём ходов 7 против 34 живых), и у книги,
    которая двигалась МИМО журнала — ход без записи не породит возврата ни у
    какого прибора, сверяющего состояния по записям.

    Все три случая закрывает ОДИН вопрос, и он не о возрасте журнала: сходится
    ли СОСТАВ состояния, на котором журнал кончается, с книгой, которая стои́т
    сегодня. Стоящая книга переписывается КАЖДЫМ дневным циклом, поэтому её
    свежесть отвечает за живость дерева, а совпадение состава — за полноту
    журнала. Тихая неделя при этом проходит: восемнадцать дней без ходов
    законны ровно до тех пор, пока книга и хвост журнала говорят одно и то же.

    Нормализует чужую сторону ТА ЖЕ `canonical_state` прибора, которой он судил
    сами возвраты, и теми же псевдонимами и тем же порогом существенности:
    вторая копия правила «что считать позицией» разошлась бы молча, а
    переименование ключа (`fluid_usdc` → `fluid_fusdc`, ход T034) развело бы
    стороны на 42 % книги без единой настоящей разницы.
    """
    verdict, payload = _standing_book_liveness(
        data, now=now,
        tail="«возвратов от now нет» отсюда было бы тишиной мёртвого дерева, а "
             "не ответом о системе")
    if verdict is not None:
        return verdict, str(payload)
    stamp, _age_d, standing = payload

    present = observed(report, "present", kind=dict)
    tail = observed(present or {}, "positions", kind=dict)
    if tail is None:
        return UNMEASURED, ("перепись не назвала СОСТАВ состояния, на котором кончается "
                            "журнал — сверить его с сегодняшней книгой НЕЧЕМ")

    aliases = report.get("aliases") or {}
    try:
        min_usd = float(report.get("materiality_usd"))
    except (TypeError, ValueError):
        return UNMEASURED, ("перепись не назвала порог существенности — привести "
                            "стоящую книгу к тому же виду, в каком прибор судил "
                            "состояния, НЕЧЕМ")
    standing_positions = census.canonical_state(
        standing.get("positions"), aliases, min_usd)
    if standing_positions != tail:
        only_tail = sorted(set(tail) - set(standing_positions))
        only_standing = sorted(set(standing_positions) - set(tail))
        moved = sorted(k for k in set(tail) & set(standing_positions)
                       if tail[k] != standing_positions[k])
        return UNMEASURED, (
            f"журнал ходов кончается состоянием {present.get('trade_id')} от "
            f"{present.get('day')}, а сегодня стои́т ДРУГАЯ книга "
            f"({STANDING_BOOK_FILE} от {stamp}): только в хвосте журнала "
            f"{only_tail or '—'}, только в стоящей {only_standing or '—'}, "
            f"разошлись суммой {moved or '—'} — книга двигалась мимо записи либо "
            f"журнал не тот, и «возвратов от now нет» доказывало бы лишь неполноту "
            f"журнала")
    return None, ""


def _probe_book_does_not_oscillate_between_opportunities(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None) -> tuple[str, str]:
    """Критерий §49 `Anti-churn` приказа CIO: «Система не прыгает между одинаковыми
    opportunities» (+ §22 — защита от формы `A → B → A → B`).

    Четвёртая привязка заказа владельца — и снова ОДНА, а не пакетом: пять
    объявлений и ни одного наблюдения были бы переписью, а не работой (запрет
    G94). Перепись `book_oscillation_census` живёт с цикла #701, её артефакт
    пишется ступенью моста в такте и свеж (замер 29.09: 4,7 ч при объявленном
    пределе 12 ч) — а запись «этот прибор есть мера этого критерия» лежала
    ПРОЗОЙ в заметке `architecture/manifest.json`, и сводный замер
    (`scripts/cio_acceptance_rollup.py`) честно отвечал «машинной пробы,
    объявившей себя мерой этого критерия, в реестре НЕТ». Цена этой строки
    измерена ADR-506 как `TRANSCRIPTION`: не хватает ОДНОГО поля.

    Вердикт — ПЕРЕНОС вердикта прибора, а не второе правило
    ---------------------------------------------------------------------------
    `OK` → `satisfied` · `CRITICAL`/`WARNING` → `not_satisfied` · третий исход
    прибора → `unmeasured`. Своего порога у пробы нет НИ ОДНОГО: существенность
    ноги и окно разворота прибор читает из `TriggerParams.for_mode()` — той же
    колонки владельца (ADR-060 §3), которой судит живой путь, — и без неё
    ОТКАЗЫВАЕТ мерить (§22 приказа: «Не hardcode»). Второе правило здесь было бы
    вторым местом для числа.

    **`WARNING` переносится в «не выполнен», а не в «предупреждение».** Эта
    порода означает: внутри окна разворота от `now` возвратов нет, но в истории
    они ЕСТЬ — книга уже возвращалась в состояние, которое сама покинула, при
    работавших на тот момент защитах. Критерий владельца говорит о свойстве
    СИСТЕМЫ («не прыгает»), а не о погоде на этой неделе, и «сейчас тихо» его не
    доказывает.

    Зазор этого выбора назван, а не спрятан
    ---------------------------------------------------------------------------
    История не меняется: возврат, состоявшийся в августе, состоялся навсегда, —
    поэтому `WARNING` держится, пока в журнале лежит хоть один возврат, и
    погасить его «подождав неделю» нельзя. Сам прибор развёл замер и вердикт
    ИМЕННО чтобы не быть красным навсегда (`.claude/rules/deployment.md`:
    сторожа, краснеющего на верное состояние, чинят, а не терпят), и здесь это
    разведение сохранено — красным становится КРИТЕРИЙ, а не прибор.

    Различие существенно, и вот почему оно честно: у красного есть ДВЕ разные
    цены, и прибор их уже посчитал. `visible_to_check` — возврат за два хода:
    гистерезис его видел, ход всё равно состоялся, значит вопрос в ВЕЛИЧИНЕ
    порога, и порог — колонка владельца. `invisible_by_construction` — возврат
    за три и более хода: гистерезис сравнивает ноги с ходом НЕПОСРЕДСТВЕННО
    предыдущим (`last_move_legs`), и такой возврат ему нечем увидеть не по
    ошибке порога, а по ПРЕДМЕТУ сравнения. Второе чинится кодом и после починки
    гаснет по-настоящему; первое — решением владельца. Замер 29.09: возвратов 12,
    из них невидимых по построению 7.

    Чего проба НЕ докладывает (назвать слепоту — часть замера)
    ---------------------------------------------------------------------------
    * **Что возврат был НЕВЕРЕН.** Мир умеет разворачиваться по-настоящему:
      ставка выросла и упала, и вернуться тогда — правильное решение. Прибор
      говорит лишь, что возврат СОСТОЯЛСЯ, и называет его цену; верность каждого
      решения он не пересчитывает, и проба не добавляет к этому ничего.
    * **Односторонность доказательства.** Отсутствие возвратов НЕ доказывает,
      что система прыгать не может: прибор судит ЗАПИСАННЫЕ состояния книги, а
      не пути кода, и о ходах вне журнала не знает ничего. Дверь к этой слепоте
      закрыта отдельным вопросом (совпадение хвоста журнала со стоящей книгой),
      но закрыта она лишь на СЕГОДНЯ и лишь по составу.
    * **Правду объявления** проба СВЕРЯЕТ (ниже) по якорю, а не принимает на
      веру. Доклад прибора ссылается на ту же константу, поэтому второй,
      «докладной» сверки здесь нет: она была бы тавтологичной по построению, и
      молчать об этом нельзя.
    * **Ничего не чинит.** Только читает; ни строки `TriggerParams`, демпфера
      частоты, гистерезиса, RiskPolicy, стоп-крана, аллокатора или живого трека.
    """
    try:
        census = _book_oscillation_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, (f"перепись прыжков книги не загружена: "
                            f"{type(exc).__name__}: {exc}")

    # Прибор обязан сам объявлять себя мерой ЭТОГО критерия, и объявление читается
    # ДО прогона — потому что на отказном пути прогон до доклада может не дойти
    # вовсе. Совпадение проверяется ПО ЯКОРЮ (`§49 Anti-churn`), а не подстрокой
    # «Anti-churn»: подстрока совпала бы с любой заметкой про демпфер частоты, и
    # объявление стало бы украшением (ADR-333).
    anchor = "§49 Anti-churn"
    declared = str(getattr(census, "CRITERION", "") or "")
    if not declared.startswith(anchor):
        return UNMEASURED, (f"перепись не объявляет себя мерой {anchor!r} "
                            f"(её CRITERION: {declared[:80]!r}) — привязка не сходится, "
                            f"и считать её мерой этого критерия нельзя")

    data = data_dir or os.path.join(REPO_ROOT, "data")
    try:
        report = census.run_census(_pathlib.Path(data), now=now)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"перепись прыжков книги упала: "
                            f"{type(exc).__name__}: {exc}")

    if not report.get("measured"):
        return UNMEASURED, (f"перепись отказалась мерить: "
                            f"{report.get('reason') or 'причина не названа'}")

    verdict, why = _standing_book_agrees_with_journal_tail(
        report, _pathlib.Path(data), census, now=now)
    if verdict is not None:
        return verdict, why

    counts = observed(report, "counts", kind=dict)
    if counts is None:
        return UNMEASURED, ("перепись объявила себя измеренной, но сводки `counts` в "
                            "отчёте нет — считать нечего, и подставить нули здесь "
                            "значило бы выдать НЕ ИЗМЕРЕНО за измеренный ноль")

    pol = report.get("policy") or {}
    present = report.get("present") or {}
    where = (f"ходов {(report.get('journal') or {}).get('moves', 0)}, хвост журнала "
             f"{present.get('trade_id')} от {present.get('day')}, окно разворота "
             f"{pol.get('reversal_window_days')} дн и существенность ноги "
             f"{pol.get('min_leg_frac')} — из TriggerParams владельца "
             f"({pol.get('mode')}/{pol.get('version')}), порог существенности "
             f"${report.get('materiality_usd', 0.0):,.2f} от книги "
             f"${report.get('book_scale_usd', 0.0):,.2f}")
    blind = (f"псевдонимов ключей выведено {len(report.get('aliases') or {})}; прибор "
             f"судит ЗАПИСАННЫЕ состояния, а не пути кода, и о ходах вне журнала не "
             f"знает ничего; верность каждого возврата он не пересчитывает")

    status = report.get("status")
    if status == census.STATUS_OK:
        return SATISFIED, (f"книга не возвращалась в состояние, которое сама покинула, "
                           f"ни разу за весь журнал: возвратов {counts.get('returns_total', 0)} "
                           f"({where}; {blind})")
    if status in (census.STATUS_CRITICAL, census.STATUS_WARNING):
        recent = counts.get("recent_within_window_from_now", 0)
        when = (f"внутри окна разворота от now таких возвратов {recent}"
                if recent else
                "внутри окна разворота от now возвратов нет — только в истории, и это "
                "НЕ «такого не бывало»")
        return NOT_SATISFIED, (
            f"книга возвращалась в состояние, которое сама покинула, "
            f"{counts.get('returns_within_window', 0)} раз(а) внутри окна разворота "
            f"(всего возвратов {counts.get('returns_total', 0)}); из них НЕВИДИМЫ "
            f"гистерезису по построению {counts.get('invisible_by_construction', 0)} "
            f"(вопрос ПРЕДМЕТА сравнения — чинится кодом), видел и пропустил "
            f"{counts.get('visible_to_check', 0)} (вопрос ВЕЛИЧИНЫ порога — колонка "
            f"владельца); {when}; оборот по непересекающимся "
            f"${report.get('turnover_usd_disjoint', 0.0):,.2f} при остатке — книга "
            f"кончила там, где начала ({where}; {blind})")
    return UNMEASURED, (f"перепись вернула статус {status!r}, который не переносится в "
                        f"вердикт критерия — молчать об этом нельзя")


#: Имя переписи связывающих потолков в `sys.modules`. Модуль ПАКЕТНЫЙ, поэтому его
#: подмена в `sys.modules` доходит до пробы — контроль этим и пользуется, чтобы
#: увидеть: проба читает ПРИБОР, а не собственную копию его логики.
POLICY_BINDING_MODULE = "spa_core.monitoring.policy_binding_census"

#: Книга, которая СТОИТ сегодня. Переписывается КАЖДЫМ дневным циклом, поэтому
#: предел возраста у неё ТОТ ЖЕ, что у журнала вердиктов. Это ССЫЛКА, а не второй
#: литерал: два числа на один такт были бы вторым местом для числа
#: (`.claude/rules/site-numbers.md`). Своё имя — потому что артефакт другой, и
#: спрашивать о его возрасте приходится отдельным вопросом.
STANDING_BOOK_MAX_AGE_D = DECISION_JOURNAL_MAX_AGE_D
#: Файл стоящей книги. Одно имя на ОБА вопроса к ней — возраст и тождество.
STANDING_BOOK_FILE = "current_positions.json"


def _policy_binding_module():
    """Перепись связывающих потолков. Импорт, а не загрузка по пути: модуль пакетный."""
    import importlib
    return importlib.import_module(POLICY_BINDING_MODULE)


def _probe_risk_policy_unbypassable_in_executed_states(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None,
        repo_root: str | None = None) -> tuple[str, str]:
    """Критерий §49 `Risk` приказа CIO: «Risk Policy невозможно обойти».

    Третья привязка заказа владельца (G96 п. 1) — и снова ОДНА, а не пакетом:
    пять объявлений и ни одного наблюдения были бы переписью, а не работой
    (запрет G94). Перепись `policy_binding_census` живёт с цикла #705, её
    артефакт пишется в такте и свеж (замер 29.09: 3,1 ч при объявленном пределе
    26 ч) — а запись «этот прибор есть мера этого критерия» лежала ПРОЗОЙ в
    заметке `architecture/manifest.json`, и сводный замер
    (`scripts/cio_acceptance_rollup.py`) честно отвечал «машинной пробы,
    объявившей себя мерой этого критерия, в реестре НЕТ». Цена этой строки
    измерена ADR-506 как `TRANSCRIPTION`: не хватает ОДНОГО поля.

    Вердикт — ПЕРЕНОС вердикта прибора, а не второе правило
    ---------------------------------------------------------------------------
    `OK` → `satisfied` · `WARNING`/`CRITICAL` → `not_satisfied` · третий исход
    прибора → `unmeasured`. Своего порога у пробы нет НИ ОДНОГО: все потолки
    прибор читает из `RiskConfig` (§22 приказа: «Не hardcode») и без них
    ОТКАЗЫВАЕТ мерить. Второе правило здесь было бы вторым местом для числа.

    **`WARNING` переносится в «не выполнен», а не в «предупреждение».** Эта
    порода означает: книга, стоящая сейчас, чиста, но в истории есть состояние,
    нарушавшее потолок, и/или копии ярлыка тира спорят — то есть ответ «нарушен
    ли потолок» сегодня не определён. Критерий владельца говорит о
    НЕВОЗМОЖНОСТИ обхода; «сейчас чисто» её не доказывает.

    Почему спор ЯРЛЫКА — это тоже «критерий не выполнен»
    ---------------------------------------------------------------------------
    Вердикт гейта неоспорим, но потолок на протокол выбирается ТИРОМ, а тир —
    ВХОД гейта, а не его решение. Ярлык, сдвинувшийся в одной копии из пяти,
    меняет связывающий потолок вдвое (T1 40 % → T2 20 %), не породив ни одного
    `approved=False`. Потолок обходят не доводом, а ярлыком — доктрина самого
    прибора, и переносится она целиком.

    Прибор гоняется НАСТОЯЩИЙ
    ---------------------------------------------------------------------------
    Проба зовёт `run_census` на живых журналах, а не читает готовый артефакт:
    артефакт неизвестного возраста ответил бы о том дне, когда его писали.
    Каталог данных и дерево — ВХОДЫ (`data_dir`, `repo_root`), часы — ВХОД
    (`now`); иначе вердикт решали бы переменная окружения и стенные часы, а не
    предмет (`.claude/rules/deployment.md`). Дерево нужно прибору не для кода, а
    для ИСТОРИИ: дата рождения порога меряется по истории файла политики, и
    поверхностный клон даёт у прибора третий исход, а не дату границы обрезки.

    Свежесть спрашивается у СТОЯЩЕЙ КНИГИ, а не у журнала ходов
    ---------------------------------------------------------------------------
    Урок ADR-508 применён к новому предмету и дал ДРУГОЙ адрес. Журнал ходов
    (`trades.json`) пополняется только когда ход был: замер 29.09 — последнее
    исполненное состояние `T034` от 11.09, восемнадцать дней назад, и это
    нормальная спокойная неделя, а не протухший источник. Спросить возраст у
    него значило бы объявить исправную систему «НЕ ИЗМЕРЕНО».

    Опасность здесь ОБРАТНАЯ и сильнее: перепись судит ПОСЛЕДНЕЕ ИСПОЛНЕННОЕ
    состояние и называет его настоящим. Если книга с тех пор изменилась мимо
    журнала, вердикт «сейчас чисто» относился бы к книге, которой уже нет.
    Поэтому спрашивается ежедневно переписываемая `current_positions.json`, и
    спрашивается дважды: СВЕЖА ли она и ТА ЖЕ ли это книга, которую судила
    перепись. Дверь названа замером: на 29.09 состав сходится ключ в ключ
    (`maple`, `fluid_fusdc`, `morpho_blue_base`, `compound_v3`, `aave_v3`) при
    разнице дат в 18 дней — то есть сегодня вердикт о настоящем законен, и
    законен он ИЗМЕРЕННО, а не по умолчанию.

    Чего проба НЕ докладывает (назвать слепоту — часть замера)
    ---------------------------------------------------------------------------
    * **Односторонность доказательства.** Отсутствие нарушений в журнале НЕ
      доказывает, что политику обойти нельзя: прибор судит СОСТОЯНИЯ книги, а не
      пути кода, и о сделках вне журнала не знает ничего. Это сказано в
      пояснении каждый раз, а не только здесь.
    * **Состояния третьего исхода вердикт не меняют.** `unmeasured` (тир не
      назван ни одной копией), `rule_postdates_state` (порог младше состояния) и
      `violation_rule_birth_unmeasured` (порог нарушен, но существовал ли он в
      тот день — неизвестно) НАЗЫВАЮТСЯ числом, но статус решает перепись, и
      переигрывать её здесь значило бы завести второе правило.
    * **Правду объявления** проба СВЕРЯЕТ (ниже) по якорю, а не принимает на
      веру. Доклад прибора ссылается на ту же константу, поэтому второй,
      «докладной» сверки здесь нет: она была бы тавтологичной по построению, и
      молчать об этом нельзя.
    * **Ничего не чинит.** Только читает; ни строки RiskPolicy, стоп-крана,
      аллокатора, ярлыка тира или живого трека. Спор ярлыков — предмет
      владельца (тир меняется ADR-ом), и подправить копию «заодно» было бы ровно
      тем молчаливым сдвигом, который прибор ищет.
    """
    try:
        census = _policy_binding_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, (f"перепись связывающих потолков не загружена: "
                            f"{type(exc).__name__}: {exc}")

    # Прибор обязан сам объявлять себя мерой ЭТОГО критерия, и объявление
    # читается ДО прогона — потому что на отказном пути доклад тоже строится, но
    # прогон до него может не дойти вовсе. Совпадение проверяется ПО ЯКОРЮ
    # (``§49 `Risk` ``), а не подстрокой «Risk»: подстрока совпала бы с любой
    # заметкой про риск, и объявление стало бы украшением.
    anchor = "§49 `Risk`"
    declared = str(getattr(census, "CRITERION", "") or "")
    if not declared.startswith(anchor):
        return UNMEASURED, (f"перепись не объявляет себя мерой {anchor!r} "
                            f"(её CRITERION: {declared[:80]!r}) — привязка не сходится, "
                            f"и считать её мерой этого критерия нельзя")

    root = repo_root or REPO_ROOT
    data = data_dir or os.path.join(REPO_ROOT, "data")
    try:
        report = census.run_census(_pathlib.Path(root), _pathlib.Path(data), now=now)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"перепись связывающих потолков упала: "
                            f"{type(exc).__name__}: {exc}")

    if not report.get("measured"):
        return UNMEASURED, (f"перепись отказалась мерить: "
                            f"{report.get('reason') or 'причина не названа'}")

    verdict, why = _standing_book_agrees_with_present(
        report, _pathlib.Path(data), now=now)
    if verdict is not None:
        return verdict, why

    counts = observed(report, "counts", kind=dict)
    if counts is None:
        return UNMEASURED, ("перепись объявила себя измеренной, но сводки `counts` "
                            "в отчёте нет — считать нечего, и подставить нули здесь "
                            "значило бы выдать НЕ ИЗМЕРЕНО за измеренный ноль")

    present = report.get("present") or {}
    where = (f"исполненных состояний {len(report.get('states') or [])}, настоящее "
             f"{present.get('trade_id')} от {present.get('day')}, копий ярлыка тира "
             f"{len(report.get('label_sources') or {})}, гейт читает "
             f"{', '.join(report.get('gate_reads') or []) or 'не названо'}, потолки "
             f"из RiskConfig ({len(report.get('thresholds') or {})} полей)")
    blind = (f"третий исход состояний: тир не назван ни одной копией "
             f"{counts.get('unmeasured', 0)}, потолок младше состояния "
             f"{counts.get('rule_postdates_state', 0)}, нарушен-но-срок-потолка-не-измерен "
             f"{counts.get('violation_rule_birth_unmeasured', 0)}; отсутствие нарушений "
             f"НЕ доказывает, что политику обойти нельзя — доказательство одностороннее, "
             f"и о сделках вне журнала прибор не знает ничего")

    status = report.get("status")
    if status == census.STATUS_OK:
        return SATISFIED, (f"ни одно исполненное состояние книги не нарушало потолка, "
                           f"который на тот день существовал, и ни один ярлык тира не "
                           f"спорит между копиями: чисто {counts.get('clean', 0)} "
                           f"({where}; {blind})")
    if status in (census.STATUS_CRITICAL, census.STATUS_WARNING):
        disputed = sorted(report.get("label_disagreement") or {})
        unknown = sorted(report.get("tier_unknown") or [])
        gate = report.get("gate_binding") or {}
        when = ("книга, которая СТОИТ сейчас, сама нарушает потолок либо её вердикт "
                "не определён"
                if status == census.STATUS_CRITICAL else
                "сегодняшнее состояние чисто, но это НЕ «такого не бывало» — находка "
                "лежит в истории и/или копии ярлыка спорят")
        return NOT_SATISFIED, (
            f"потолок, связывавший книгу, обойдён или не определён: нарушений "
            f"{counts.get('violation', 0)} (по копиям, которые читает ГЕЙТ — "
            f"{gate.get('violating_count', 0)}), вердикт зависит от копии ярлыка у "
            f"{counts.get('undetermined', 0)} состояний, спорят ярлыки у "
            f"{len(disputed)} ключ(ей) {disputed or '—'}, тир неизвестен у "
            f"{len(unknown)}; {when} ({where}; {blind})")
    return UNMEASURED, (f"перепись вернула статус {status!r}, который не переносится в "
                        f"вердикт критерия — молчать об этом нельзя")


def _standing_book_agrees_with_present(
        report: dict, data: "_pathlib.Path", *,
        now: "datetime | None" = None) -> "tuple[str | None, str]":
    """Относится ли вердикт переписи к книге, которая стои́т СЕГОДНЯ.

    Возвращает `(None, "")`, когда относится, и `(UNMEASURED, причина)`, когда
    ответить нечем. Вердикта «не выполнен» отсюда не выходит НИ ОДНОГО: вопрос
    здесь не о политике, а о том, о чём вообще речь, — и смешать «политику
    обошли» с «мы смотрим не на ту книгу» значило бы завести второе правило.
    """
    verdict, payload = _standing_book_liveness(
        data, now=now, tail="мерить надо из дерева с живым data/")
    if verdict is not None:
        return verdict, str(payload)
    stamp, _age_d, standing = payload

    judged = observed(report.get("present") or {}, "positions", kind=dict)
    if judged is None:
        return UNMEASURED, ("перепись не назвала СОСТАВ состояния, которое считает "
                            "настоящим — сверить его с сегодняшней книгой НЕЧЕМ")

    # Нормализуется чужая сторона ТОЙ ЖЕ функцией прибора, которая нормализовала
    # судимую: «что считать позицией» (округление, нулевые ноги) — правило
    # прибора, и вторая его копия здесь разошлась бы молча.
    census = _policy_binding_module()
    standing_positions = census._positions(standing.get("positions"))
    if standing_positions != judged:
        only_judged = sorted(set(judged) - set(standing_positions))
        only_standing = sorted(set(standing_positions) - set(judged))
        moved = sorted(k for k in set(judged) & set(standing_positions)
                       if judged[k] != standing_positions[k])
        present = report.get("present") or {}
        return UNMEASURED, (
            f"перепись судит состояние {present.get('trade_id')} от "
            f"{present.get('day')}, а сегодня стои́т ДРУГАЯ книга "
            f"({STANDING_BOOK_FILE} от {stamp}): только в судимой "
            f"{only_judged or '—'}, только в стоящей {only_standing or '—'}, "
            f"разошлись суммой {moved or '—'} — вердикт относится к книге, которой "
            f"уже нет, и выдать его за ответ о сегодня нельзя")
    return None, ""


#: Перепись повторной проверки перед исполнением (цикл #708). Модуль ПАКЕТНЫЙ,
#: поэтому его подмена в `sys.modules` доходит до пробы — контроль этим и
#: пользуется, чтобы увидеть: проба читает ПРИБОР, а не свою копию его логики.
PRE_TRADE_RECHECK_MODULE = "spa_core.monitoring.pre_trade_recheck_census"


def _pre_trade_recheck_module():
    """Перепись повторной проверки. Импорт, а не загрузка по пути: модуль пакетный."""
    import importlib
    return importlib.import_module(PRE_TRADE_RECHECK_MODULE)


def _chain_covers_the_books_moves(
        report: dict, data: "_pathlib.Path") -> "tuple[str | None, str]":
    """Знает ли цепочка аудита ВСЕ ходы, которые книга записала за собой.

    Возврат: `(None, "")` — знает; `(UNMEASURED, причина)` — ответить нечем.
    Вердикта «не выполнен» отсюда не выходит ни одного: неполнота ЗАПИСИ и
    отсутствие повторной проверки — разные находки, и слить их значило бы
    объявить дыру в журнале нарушением критерия владельца.

    Почему вопрос здесь про ПОКРЫТИЕ, а не про возраст
    ---------------------------------------------------------------------------
    Три предыдущие привязки §49 учили, что адрес вопроса «законен ли вердикт» у
    каждого критерия свой (ADR-508/510/511). Здесь он оказался и не возрастом, и
    не тождеством книги: прибор судит ЦЕПОЧКУ АУДИТА, а цепочка — отдельная
    запись, и вопрос к ней один: а все ли ходы книги в неё попали. Ход, о котором
    цепочка не знает, не порождает ни одного исполнения без второго наблюдения —
    он просто не осматривается, и «у каждого хода была повторная проверка»
    сказано было бы о ВЫБОРКЕ.

    Население берётся у журнала ходов, а его имя — ССЫЛКОЙ на константу переписи
    прыжков книги (`JOURNAL_NAME`): второй литерал того же имени был бы вторым
    местом для имени. Состав цепочки берётся у САМОГО прибора
    (`identity.labels`), а не собирается здесь вторым чтением: «что считать
    исполнением» — правило прибора, и вторая его копия разошлась бы молча.
    """
    try:
        book = _book_oscillation_module()
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"перепись прыжков книги не загружена, а у неё объявлено "
                            f"имя журнала ходов: {type(exc).__name__}: {exc} — "
                            f"население для сверки покрытия взять неоткуда")
    name = getattr(book, "JOURNAL_NAME", None)
    if not isinstance(name, str) or not name:
        return UNMEASURED, ("имя журнала ходов не объявлено переписью прыжков книги — "
                            "подставить своё значило бы завести второе место для "
                            "имени файла")
    path = data / name
    try:
        moves = json.loads(path.read_text(encoding="utf-8"))
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"журнал ходов не прочитан ({path}): "
                            f"{type(exc).__name__}: {exc} — сверить, все ли ходы "
                            f"книги попали в цепочку аудита, НЕЧЕМ")
    if not isinstance(moves, list) or not moves:
        return UNMEASURED, (f"журнал ходов {name} пуст или не является списком — "
                            f"населения, по которому мерится покрытие, нет, и считать "
                            f"его нулём значило бы выдать НЕ ИЗМЕРЕНО за покрытие")
    rows = [m for m in moves if isinstance(m, dict)]
    labelled = [m.get("trade_id") for m in rows
                if isinstance(m.get("trade_id"), str) and m.get("trade_id")]
    if len(labelled) != len(rows):
        return UNMEASURED, (f"у {len(rows) - len(labelled)} из {len(rows)} ходов "
                            f"журнала нет ярлыка `trade_id` — сверять покрытие "
                            f"нечем, и «цепочка знает все ходы» отсюда было бы "
                            f"утверждением, а не замером")
    identity = observed(report, "identity", kind=dict)
    if identity is None or identity.get("measured") is not True:
        return UNMEASURED, (f"перепись не измерила ось ярлыков исполнений "
                            f"({(identity or {}).get('reason') or 'причина не названа'})"
                            f" — состав цепочки взять неоткуда")
    labels = observed(identity, "labels", kind=list)
    if labels is None:
        return UNMEASURED, ("перепись не назвала СОСТАВ ярлыков цепочки (`identity."
                            "labels`) — сверить покрытие ходов книги НЕЧЕМ, а счёт "
                            "различных ярлыков отвечает на другой вопрос")
    known = set(labels)
    missing = [t for t in labelled if t not in known]
    if missing:
        shown = ", ".join(missing[:6]) + ("…" if len(missing) > 6 else "")
        return UNMEASURED, (
            f"цепочка аудита знает не все ходы книги: из {len(labelled)} записанных "
            f"ходов ({name}) исполнения нет у {len(missing)} — {shown}; «у каждого "
            f"хода была повторная проверка» относилось бы к ВЫБОРКЕ, а не к книге, "
            f"и ход, о котором цепочка не знает, не осматривается вовсе")
    return None, ""


def _probe_trade_is_rechecked_immediately_before_execution(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None,
        repo_root: str | None = None) -> tuple[str, str]:
    """Критерий §49 `Pre-trade safety` приказа CIO: «Каждый trade пересчитывается
    непосредственно перед execution».

    ПЯТАЯ и последняя привязка цены `TRANSCRIPTION` — и снова ОДНА, а не пакетом
    (запрет G94). Перепись `pre_trade_recheck_census` живёт с цикла #708, её
    артефакт пишется ступенью моста и свеж (замер 29.09: 6,2 ч при объявленном
    пределе 12 ч) — а запись «этот прибор есть мера этого критерия» лежала
    ПРОЗОЙ, и сводный замер (`scripts/cio_acceptance_rollup.py`) честно отвечал
    «машинной пробы, объявившей себя мерой этого критерия, в реестре НЕТ».

    Вердикт — ПЕРЕНОС вердикта прибора, а не второе правило
    ---------------------------------------------------------------------------
    `OK` → `satisfied` · `WARNING`/`CRITICAL` → `not_satisfied` · третий исход
    прибора → `unmeasured`. Своего порога у пробы нет НИ ОДНОГО, и передать
    прибору `tolerance_s` она не имеет права: допуск свежести входа — ручка
    ВЛАДЕЛЬЦА (§22 «Не hardcode»), и её в колонке `TriggerParams` сегодня нет
    вовсе. Прибор объявляет этот вопрос третьим исходом
    (`freshness_judgeable=False`) — проба это НАЗЫВАЕТ, а не закрашивает.

    Законность вердикта спрошена АСИММЕТРИЧНО — и это находка цикла
    ---------------------------------------------------------------------------
    Три предыдущие привязки спрашивали «о живом ли материале вердикт» ДО всякого
    переноса. Здесь такой порядок был бы вреден, и вот почему: доказательство
    прибора ОДНОСТОРОННЕЕ. `WARNING` означает «нашлось исполнение, у которого
    второго наблюдения входов не было» — утверждение существования, и ни дыра в
    записи, ни возраст дерева его не отменяют: исполнение, стоявшее на том же
    наблюдении, что и предложение, стояло на нём навсегда. А `OK` означает «ни
    одного такого не нашлось» — утверждение обо ВСЕХ, и оно рушится от любой
    неполноты материала.

    Поэтому вопрос о законности задаётся ТОЛЬКО на зелёном пути. Задать его
    раньше значило бы превратить измеренную находку владельца (46 исполнений из
    46 без второго наблюдения, замер 29.09) в «НЕ ИЗМЕРЕНО» из-за гигиены
    материала — то есть спрятать красное за правилом о чистоте, зеркальный
    дефект к «не измерено, выданному за чисто».

    Зазор назван: `WARNING` держится, пока в цепочке лежит хоть одно такое
    исполнение, и «подождав неделю» его не погасить — история не меняется.
    Красным при этом становится КРИТЕРИЙ, а не прибор: сам прибор развёл замер и
    вердикт именно затем, чтобы не быть красным навсегда
    (`.claude/rules/deployment.md`). Честно это ещё и потому, что у красного есть
    ВТОРАЯ, сегодняшняя опора, которую прибор меряет по ЭТОМУ дереву:
    `gate_readers` — у модуля повторной проверки
    (`spa_core/execution/safety_checks.py`) нет ни одного читателя на денежном
    пути, и по инварианту #6 быть не может. Проба печатает это число рядом с
    вердиктом, чтобы «находка только в истории» не пришлось принимать на веру.

    Чего проба НЕ докладывает (назвать слепоту — часть замера)
    ---------------------------------------------------------------------------
    * **Верность самих проверок.** Что `PreExecutionSafety` проверяет правильно —
      вопрос не этого прибора и не этой пробы.
    * **Восемь из девяти предметов §27 по отдельности.** Мерится ПРИЗНАК второго
      взгляда на мир (ярлык наблюдения изменился либо в цепочке есть событие
      повторной проверки), а не покрытие каждого предмета.
    * **Ходы вне цепочки.** О них прибор не знает ничего; дверь закрыта вопросом
      о покрытии — и закрыта лишь на зелёном пути и лишь по СОСТАВУ ярлыков.
    * **Ничего не чинит.** Только читает; ни строки `TriggerParams`, RiskPolicy,
      стоп-крана, аллокатора, гейта исполнения или живого трека.
    """
    try:
        census = _pre_trade_recheck_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, (f"перепись повторной проверки не загружена: "
                            f"{type(exc).__name__}: {exc}")

    # Прибор обязан сам объявлять себя мерой ЭТОГО критерия, и объявление читается
    # ДО прогона: на отказном пути прогон до доклада может не дойти вовсе.
    # Совпадение — ПО ЯКОРЮ, а не подстрокой «Pre-trade safety»: подстрока совпала
    # бы с любой заметкой о предпусковых проверках (ADR-333).
    anchor = "§49 Pre-trade safety"
    declared = str(getattr(census, "CRITERION", "") or "")
    if not declared.startswith(anchor):
        return UNMEASURED, (f"перепись не объявляет себя мерой {anchor!r} "
                            f"(её CRITERION: {declared[:80]!r}) — привязка не сходится, "
                            f"и считать её мерой этого критерия нельзя")

    data = data_dir or os.path.join(REPO_ROOT, "data")
    root = repo_root or REPO_ROOT
    try:
        report = census.run_census(_pathlib.Path(data), now=now,
                                   repo_root=_pathlib.Path(root))
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"перепись повторной проверки упала: "
                            f"{type(exc).__name__}: {exc}")

    if not report.get("measured"):
        return UNMEASURED, (f"перепись отказалась мерить: "
                            f"{report.get('reason') or 'причина не названа'}")

    gate = report.get("gate_readers") or {}
    money = gate.get("money_path_callers")
    today = (f"читателей модуля повторной проверки на денежном пути "
             f"{len(money)} (по замеру ЭТОГО дерева)" if isinstance(money, list)
             else f"читатели модуля повторной проверки НЕ измерены: "
                  f"{gate.get('reason') or 'причина не названа'}")
    where = (f"исполнений {report.get('executions')} (измеримых "
             f"{report.get('executions_measurable')}), окно "
             f"{report.get('window_s_min')}…{report.get('window_s_max')}с, срок "
             f"годности решения объявлен у {report.get('ttl_declared_count')}; "
             f"{today}; замер снят {report.get('generated_at')}")
    blind = ("прибор судит ЗАПИСАННЫЕ исполнения, а не пути кода; верность самих "
             "проверок и восемь из девяти предметов §27 по отдельности он не "
             "докладывает")
    if not report.get("freshness_judgeable"):
        blind += (f"; вопрос «вход был слишком стар» НЕ ИЗМЕРЕН — "
                  f"{report.get('freshness_unjudgeable_reason')}")

    status = report.get("status")
    if status in (census.STATUS_CRITICAL, census.STATUS_WARNING):
        return NOT_SATISFIED, (
            f"ход перед исполнением заново не пересчитывается: без второго "
            f"наблюдения входов {report.get('no_recheck')} исполнени(й) из "
            f"{report.get('executions_measurable')} измеримых, с повторной "
            f"проверкой {report.get('recheck_present')}, старше объявленного "
            f"владельцем допуска {report.get('stale_beyond_tolerance')}; вопрос о "
            f"полноте записи здесь НЕ задаётся — находка существования от неё не "
            f"зависит ({where}; {blind})")
    if status == census.STATUS_OK:
        verdict, why = _standing_book_liveness(
            _pathlib.Path(data), now=now,
            tail="«ни одного исполнения без второго наблюдения» отсюда было бы "
                 "тишиной мёртвого дерева, а не ответом о системе")
        if verdict is not None:
            return verdict, str(why)
        verdict, why = _chain_covers_the_books_moves(report, _pathlib.Path(data))
        if verdict is not None:
            return verdict, why
        return SATISFIED, (
            f"у каждого записанного исполнения входы наблюдались ЗАНОВО: без "
            f"второго наблюдения 0, с повторной проверкой "
            f"{report.get('recheck_present')}, и цепочка аудита знает все ходы "
            f"журнала ({where}; {blind})")
    return UNMEASURED, (f"перепись вернула статус {status!r}, который не переносится "
                        f"в вердикт критерия — молчать об этом нельзя")


#: Прибор стоимости перекладки (цикл #501, ADR-243). Модуль ПАКЕТНЫЙ, поэтому его
#: подмена в `sys.modules` доходит до пробы — контроль этим и пользуется, чтобы
#: увидеть: проба читает ПРИБОР, а не свою копию его логики.
COST_EVIDENCE_MODULE = "spa_core.monitoring.rebalance_cost_evidence"


def _cost_evidence_module():
    """Прибор стоимости перекладки. Импорт, а не загрузка по пути: модуль пакетный."""
    import importlib
    return importlib.import_module(COST_EVIDENCE_MODULE)


def _probe_costs_are_accounted_for_in_the_decision(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None,
        repo_root: str | None = None) -> tuple[str, str]:
    """Критерий §49 `Costs` приказа CIO: «Gas, fees, slippage accounted for in decision».

    ПЕРВАЯ привязка цены `WORDING` — и снова ОДНА, а не пакетом (запрет G94).
    Прибор `rebalance_cost_evidence` живёт с цикла #501, артефакт свеж (замер
    29.09: 2,1 ч при объявленном пределе 7 ч) — а запись «этот прибор есть мера
    этого критерия» лежала ПРОЗОЙ, и притом НЕ канонической формулировкой:
    конституция писала `§49 ТЗ «Portfolio CIO» (Costs: …)`, то есть форму
    `paren`, и читателю оставалось угадывать. Сводный замер
    (`scripts/cio_acceptance_rollup.py`) честно отвечал «машинной пробы,
    объявившей себя мерой этого критерия, в реестре НЕТ».

    Вердикт — ПЕРЕНОС вердикта прибора, а не второе правило
    ---------------------------------------------------------------------------
    Берётся поле `criterion.status`, которое прибор теперь публикует сам:
    `SATISFIED` → `satisfied` · `NOT_SATISFIED` → `not_satisfied` ·
    `UNMEASURED` → `unmeasured`. Своего порога у пробы нет НИ ОДНОГО: и срок
    годности наблюдения газа (1,5 ч), и срок годности записанного вердикта
    (26 ч) читаются прибором из манифеста, а полоса выгоды и горизонт
    окупаемости — из `TriggerParams` владельца.

    Почему переносится НЕ `overall` — находка цикла
    ---------------------------------------------------------------------------
    `overall` у этого прибора есть лестница ТЯЖЕСТИ, и третий исход стои́т в ней
    ВЫШЕ `CRITICAL` намеренно (`test_unchecked_outranks_critical`): иначе «не
    измерено» тонет в находках. Для здоровья артефакта это верно, а для вердикта
    критерия было бы ложью в другую сторону — находка расхождения есть
    утверждение СУЩЕСТВОВАНИЯ, и непрочитанный рядом снимок её не отменяет.
    Перенести `overall` значило бы спрятать измеренное красное за «не измерено»,
    то есть вывернуть инвариант #17 наизнанку. Поэтому прибор получил отдельное
    поле, читающее свои находки ПО ОСИ (`FINDING_AXIS`), а таблица осей живёт у
    него: виды находок порождает он, и вторая её копия здесь разъехалась бы
    молча.

    Чего проба НЕ докладывает (назвать слепоту — часть замера)
    ---------------------------------------------------------------------------
    * **Верность самих чисел стоимости.** Что литералы `cost_model` верны — не
      вопрос этой пробы; прибор как раз и меряет их расхождение с наблюдением.
    * **Комиссии и слиппедж НАБЛЮДЕНИЕМ.** Наблюдается ровно одна компонента из
      трёх — газ; слиппедж сверяется МОДЕЛЬЮ над наблюдённым TVL, и прибор
      никогда не поднимает это выше допущения. Критерий владельца шире, чем
      сегодняшняя мера, и это сказано вслух здесь, а не спрятано в зелёном.
    * **Тихий день.** Прибор умеет измерить отношение заряженного газа к
      наблюдённому и тогда, когда перекладка не предложена, — но находкой это не
      становится: находки сравнивают ошибку с ЗАЗОРОМ ГЕЙТА, а зазора без
      предложенной перекладки нет. Число печатается рядом (`unjudged`), потому
      что порога «во сколько раз уже много» вне зазора гейта владелец не
      объявлял, и назначить его пробой значило бы завести порог вне его дома.
    * **Ничего не чинит.** Прибор зовётся с `write=False`: проба не переписывает
      даже его собственный артефакт. Ни строки `TriggerParams`, `cost_model`,
      RiskPolicy, стоп-крана, аллокатора или живого трека.
    """
    try:
        meter = _cost_evidence_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, (f"прибор стоимости перекладки не загружен: "
                            f"{type(exc).__name__}: {exc}")

    # Прибор обязан сам объявлять себя мерой ЭТОГО критерия, и объявление читается
    # ДО прогона: на отказном пути прогон до доклада может не дойти вовсе.
    # Совпадение — ПО ЯКОРЮ, а не подстрокой «Costs»: подстрока совпала бы с
    # любой заметкой о стоимости (ADR-333).
    anchor = "§49 Costs"
    declared = str(getattr(meter, "CRITERION", "") or "")
    if not declared.startswith(anchor):
        return UNMEASURED, (f"прибор не объявляет себя мерой {anchor!r} "
                            f"(его CRITERION: {declared[:80]!r}) — привязка не "
                            f"сходится, и считать его мерой этого критерия нельзя")

    root = repo_root or REPO_ROOT
    data = data_dir or os.path.join(root, "data")
    try:
        report = meter.run(root=root, write=False, data_dir=data, now=now)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"прибор стоимости перекладки упал: "
                            f"{type(exc).__name__}: {exc}")

    block = observed(report, "criterion", kind=dict)
    if block is None:
        return UNMEASURED, ("прибор не вынес вердикта о критерии (поля `criterion` "
                            "в отчёте нет) — переносить нечего, и молчать об этом "
                            "нельзя")

    fresh = report.get("verdict_freshness") or {}
    where = (f"находок расхождения {len(block.get('found') or [])}, "
             f"ненаблюдённого {len(block.get('unobserved') or [])}, допущений "
             f"{len(block.get('assumption') or [])}, непрочитанного "
             f"{len(report.get('unchecked') or [])}; записанный вердикт снят "
             f"{fresh.get('stamp')} ({fresh.get('age_hours')} ч при пределе "
             f"{fresh.get('slo_hours')} ч, {fresh.get('slo_provenance')})")
    blind = ("наблюдается ОДНА компонента стоимости из трёх — газ; слиппедж "
             "сверяется МОДЕЛЬЮ над наблюдённым TVL и выше допущения не "
             "поднимается, комиссии не наблюдаются вовсе")
    unjudged = block.get("unjudged")
    if isinstance(unjudged, dict):
        blind += (f"; ИЗМЕРЕНО, НО НЕ СУЖДЕНО: заряженный газ ×"
                  f"{unjudged.get('gas_ratio_charged_over_observed')} от "
                  f"наблюдённого — {unjudged.get('reason')}")

    status = block.get("status")
    reason = block.get("reason") or "причина не названа"
    if status == meter.CRITERION_NOT_SATISFIED:
        return NOT_SATISFIED, f"{reason} ({where}; {blind})"
    if status == meter.CRITERION_UNMEASURED:
        return UNMEASURED, f"{reason} ({where}; {blind})"
    if status == meter.CRITERION_SATISFIED:
        return SATISFIED, f"{reason} ({where}; {blind})"
    return UNMEASURED, (f"прибор вернул вердикт критерия {status!r}, который не "
                        f"переносится — молчать об этом нельзя")


#: Прибор предельной доходности (цикл #493). Модуль ПАКЕТНЫЙ, поэтому его подмена
#: в `sys.modules` доходит до пробы — контроль этим и пользуется, чтобы увидеть:
#: проба читает ПРИБОР, а не свою копию его логики.
MARGINAL_RETURN_MODULE = "spa_core.monitoring.marginal_apy_at_size"


def _marginal_return_module():
    """Прибор предельной доходности. Импорт, а не загрузка по пути: модуль пакетный."""
    import importlib
    return importlib.import_module(MARGINAL_RETURN_MODULE)


def _probe_marginal_return_size_changes_expected_yield(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None) -> tuple[str, str]:
    """Критерий §49 `Marginal return` приказа CIO: «Position size влияет на expected yield».

    Вторая привязка цены `WORDING` — и снова ОДНА, а не пакетом (запрет G94).
    Прибор `marginal_apy_at_size` живёт с цикла #493, артефакт свеж (замер 29.09:
    4,0 ч при объявленном пределе 7 ч) — а запись «этот прибор есть мера этого
    критерия» лежала ПРОЗОЙ и не канонической формулировкой: конституция писала
    `§49 «Marginal return»`, то есть форму `quoted`. Сводный замер
    (`scripts/cio_acceptance_rollup.py`) честно отвечал «машинной пробы,
    объявившей себя мерой этого критерия, в реестре НЕТ».

    Почему перенос ПРОЗЫ был бы здесь особенно дорог — находка цикла #731
    ---------------------------------------------------------------------------
    Главный ответ прибора («ранжирующая ставка от нашего размера не зависит»)
    до этого цикла был НАПЕЧАТАННЫМ предложением: находка
    `objective_is_linear_in_rate` добавлялась в отчёт БЕЗУСЛОВНО, с готовым
    текстом, при любом снимке. Претензия верна и сегодня — но её не спрашивали у
    кода ни разу, и она пережила бы свой предмет молча. Поэтому цикл сперва
    сделал её ЗАМЕРОМ (`objective_size_sensitivity` спрашивает живой доходностный
    член целевой функции дважды — при крошечной позиции и при наибольшей
    разрешённой политикой), и только потом привязал к критерию.

    Вердикт — ПЕРЕНОС вердикта прибора, а не второе правило
    ---------------------------------------------------------------------------
    Берётся поле `criterion.status`, которое прибор публикует сам. Своего порога
    у пробы нет ни одного: границы сцены задаёт `TunerConstraints` владельца
    (потолок концентрации, TVL-floor), полосу выгоды — `TriggerParams`.

    Почему переносится НЕ `overall` — тот же урок, что у `Costs` (ADR-513)
    ---------------------------------------------------------------------------
    `overall` есть лестница ТЯЖЕСТИ, где третий исход стои́т выше `CRITICAL`
    намеренно: для здоровья артефакта верно, для вердикта критерия — ложь в
    другую сторону. Находка «размер не учитывается» есть утверждение
    СУЩЕСТВОВАНИЯ, и непрочитанный рядом пул её не отменяет. Прибор поэтому
    читает свои находки ПО ОСИ (`FINDING_AXIS`), а таблица осей живёт у него.

    Чего проба НЕ докладывает (назвать слепоту — часть замера)
    ---------------------------------------------------------------------------
    * **Верность самой ставки.** Сцена замера синтетическая: спрашивается
      СВОЙСТВО целевой функции, а не сегодняшняя доходность книги.
    * **Пути мимо объявленной двери.** Считай кто-нибудь ожидаемую доходность
      своей копией в обход `_weighted_apy` — замер об этом не знает.
    * **Величину вреда.** Из трёх величин разбавления фактом является только
      `error_pp_definitional`; остальное — названное вслух допущение MP-911.
    * **Ничего не чинит.** Прибор зовётся с `write=False`; ранжирующее число —
      money-path и решение владельца, здесь только замер.

    Почему `repo_root` НЕ объявлен входом дерева
    ---------------------------------------------------------------------------
    Объявить его значило бы соврать о проводке. Вердикт этой пробы зависит от
    ДВУХ вещей: от каталога материала (`data_dir`) и от КОДА целевой функции — а
    код приходит импортом по `sys.path`, а не из `repo_root`. Прибор пользуется
    `root` ровно для записи артефакта, которая здесь выключена. Вход, который
    физически не может изменить исход, объявленный входом, читался бы как
    «дерево замера дошло», и `scripts/cio_acceptance_rollup.py` напечатал бы это
    про дерево, которого проба не видела.
    """
    try:
        meter = _marginal_return_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, (f"прибор предельной доходности не загружен: "
                            f"{type(exc).__name__}: {exc}")

    # Прибор обязан сам объявлять себя мерой ЭТОГО критерия, и объявление читается
    # ДО прогона: на отказном пути прогон до доклада может не дойти вовсе.
    # Совпадение — ПО ЯКОРЮ, а не подстрокой «Marginal return»: подстрока совпала
    # бы с любой заметкой о предельной доходности (ADR-333).
    anchor = "§49 Marginal return"
    declared = str(getattr(meter, "CRITERION", "") or "")
    if not declared.startswith(anchor):
        return UNMEASURED, (f"прибор не объявляет себя мерой {anchor!r} "
                            f"(его CRITERION: {declared[:80]!r}) — привязка не "
                            f"сходится, и считать его мерой этого критерия нельзя")

    data = data_dir or os.path.join(REPO_ROOT, "data")
    try:
        report = meter.run(root=REPO_ROOT, write=False, data_dir=data, now=now)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"прибор предельной доходности упал: "
                            f"{type(exc).__name__}: {exc}")

    block = observed(report, "criterion", kind=dict)
    if block is None:
        return UNMEASURED, ("прибор не вынес вердикта о критерии (поля `criterion` "
                            "в отчёте нет) — переносить нечего, и молчать об этом "
                            "нельзя")

    sens = block.get("sensitivity") or {}
    if sens.get("measured"):
        asked = (f"целевую функцию спросили дважды ({sens.get('objective')}): "
                 f"{sens.get('rate_at_small_pp')} пп при ${sens.get('small_usd')} "
                 f"против {sens.get('rate_at_large_pp')} пп при "
                 f"${sens.get('large_usd')}, Δ {sens.get('delta_pp')} пп при "
                 f"разбавлении модели {sens.get('reference_dilution_pp')} пп на "
                 f"той же сцене")
    else:
        asked = (f"целевую функцию о размере СПРОСИТЬ НЕ ВЫШЛО: "
                 f"{sens.get('reason') or 'причина не названа'}")
    where = (f"{asked}; развёрнуто ${report.get('deployed_usd')} из капитала "
             f"${report.get('capital_usd')}, знаменатель разбавления не наблюдён у "
             f"${report.get('unmeasured_capital_usd')}; непрочитанного "
             f"{len(report.get('unchecked') or [])}")
    blind = ("сцена замера синтетическая — спрашивается СВОЙСТВО целевой функции, "
             "а не сегодняшняя доходность книги; о путях мимо объявленного "
             "доходностного члена прибор не знает ничего, а из трёх величин "
             "разбавления фактом является только определительная")

    status = block.get("status")
    reason = block.get("reason") or "причина не названа"
    if status == meter.CRITERION_NOT_SATISFIED:
        return NOT_SATISFIED, f"{reason} ({where}; {blind})"
    if status == meter.CRITERION_UNMEASURED:
        return UNMEASURED, f"{reason} ({where}; {blind})"
    if status == meter.CRITERION_SATISFIED:
        return SATISFIED, f"{reason} ({where}; {blind})"
    return UNMEASURED, (f"прибор вернул вердикт критерия {status!r}, который не "
                        f"переносится — молчать об этом нельзя")


#: Прибор воспроизводимости расчёта (цикл #501). Модуль ПАКЕТНЫЙ, поэтому его
#: подмена в `sys.modules` доходит до пробы — контроль этим и пользуется, чтобы
#: увидеть: проба читает ПРИБОР, а не свою копию его правила.
DETERMINISM_MODULE = "spa_core.monitoring.decision_reproducibility"


def _determinism_module():
    """Прибор воспроизводимости. Импорт, а не загрузка по пути: модуль пакетный."""
    import importlib
    return importlib.import_module(DETERMINISM_MODULE)


def _probe_determinism_recomputation_is_reproducible(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None,
        repo_root: str | None = None,
        subjects=None, census=None) -> tuple[str, str]:
    """Критерий §49 `Determinism` приказа CIO: «Calculations reproducible».

    ТРЕТЬЯ и последняя привязка цены `WORDING` — и снова ОДНА, а не пакетом
    (запрет G94). Прибор `decision_reproducibility` живёт с цикла #501, артефакт
    свеж (замер 29.09: 5,8 ч при объявленном пределе 7 ч) — а запись «этот прибор
    есть мера этого критерия» лежала в конституции ПРОЗОЙ и притом формой
    `paren`: `§49 ТЗ «Portfolio CIO» (Determinism: …)`. Сводный замер
    (`scripts/cio_acceptance_rollup.py`) честно отвечал «машинной пробы,
    объявившей себя мерой этого критерия, в реестре НЕТ».

    Почему перенос ПРОЗЫ был бы здесь особенно дорог — находка цикла #732
    ---------------------------------------------------------------------------
    Прибор отвечает «один снимок — один ответ», и ответ этот ПРАВДА: замер 29.09
    даёт `distinct_outputs = 1` у обоих субъектов. Но читатель сводки понимает
    его как утверждение ВСЕОБЩЕЕ — «расчёты системы воспроизводимы», — а
    спрашивается он у населения из двух субъектов, набранного руками, и с
    поверхностью, которая на самом деле решает книги, это население не сверял
    никто. Замер: `portfolio_rebalancer` пишет ту же книгу, что аллокатор, и
    спрошен НЕ БЫЛ; `hy_cycle` и `lp_cycle` решают ещё $199 905,40 и не спрошены
    тоже. **Капитал, чья решающая поверхность спрошена целиком, — $0,00 из
    $301 352,65.** Перенеси проба зелёный ответ прибора как есть — критерий
    владельца стал бы `ВЫПОЛНЕН` по одной трети книги, измеренной на треть.

    Поэтому прибор сперва получил ЗАМЕР покрытия (`decider_coverage`): знаменатель
    в долларах приходит от переписи решателей (`cio_decision_owner_census`), а
    «кого спрашивали» выводится РАЗБОРОМ кода субъектов, а не запиской рядом.

    Вердикт — ПЕРЕНОС вердикта прибора, а не второе правило
    ---------------------------------------------------------------------------
    Берётся поле `criterion.status`, и правило его вычисления живёт у прибора
    (`criterion_verdict`). Проба считает его по ПРОЧИТАННОМУ артефакту — тем же
    кодом, но без повторного подъёма процессов: дословный опыт владельца («100
    запусков») стоит минуты, и звать его из приёмки карточки значило бы сделать
    приёмку дороже работы. Артефакт при этом не проза, а ЗАМЕР: его пишет
    ежечасный мост (`com.spa.decision_loop`).

    Свежесть артефакта судится ЕГО ЖЕ паспортом
    ---------------------------------------------------------------------------
    Порог берётся из манифеста ОДНИМ читателем, который спрашивает ОБА дома
    объявления (`rebalance_cost_evidence.declared_slo_hours`, находка #730:
    `artifacts[]` и `agents[].produces[]`; общий `manifest_slo` видит один дом —
    это отдельная карточка). Своего «24 часа» проба не назначает: порог не
    измерение, а решение, и жить он обязан в конституции.

    Почему переносится НЕ `overall` — тот же урок, что у `Costs` (ADR-513)
    ---------------------------------------------------------------------------
    `overall` есть лестница ТЯЖЕСТИ, где третий исход стои́т выше `CRITICAL`
    намеренно (`test_unchecked_outranks_critical_in_the_overall_verdict`). Для
    здоровья артефакта верно, для вердикта критерия — ложь в другую сторону:
    находка «один снимок дал разные ответы» есть утверждение СУЩЕСТВОВАНИЯ, и
    непрочитанный рядом субъект её не отменяет. Таблица осей живёт у прибора.

    Чего проба НЕ докладывает (назвать слепоту — часть замера)
    ---------------------------------------------------------------------------
    * **Транзитивную цепочку.** «Спрошен» значит «субъект зовёт этот модуль по
      имени». Модуль, до которого расчёт доходит внутри, спрошенным не
      объявляется: иначе спрошенным оказалось бы всё, к чему прикоснулся вызов.
    * **Верность самого сравнения.** Что из сравнения вычтены ИМЕННО часы
      производителя, держат сторожа прибора, а не эта проба.
    * **Полноту населения книг.** Книги перечисляет перепись решателей; о книге,
      которой нет в ней, проба не знает ничего.
    * **«Не спрошен» ≠ «не воспроизводим».** Про решателя, которого не
      спрашивали, не известно НИЧЕГО, и проба говорит это словами в каждом
      вердикте (инв. #17).
    * **Ничего не чинит.** Читаются артефакт и дерево; ни строки RiskPolicy,
      стоп-крана, аллокатора, `hy_cycle`/`lp_cycle` или живого трека.
    """
    try:
        meter = _determinism_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, (f"прибор воспроизводимости не загружен: "
                            f"{type(exc).__name__}: {exc}")

    # Прибор обязан сам объявлять себя мерой ЭТОГО критерия, и объявление читается
    # ДО чтения артефакта. Совпадение — ПО ЯКОРЮ, а не подстрокой «Determinism»:
    # подстрока совпала бы с любой заметкой о детерминизме (ADR-333).
    anchor = "§49 Determinism"
    declared = str(getattr(meter, "CRITERION", "") or "")
    if not declared.startswith(anchor):
        return UNMEASURED, (f"прибор не объявляет себя мерой {anchor!r} "
                            f"(его CRITERION: {declared[:80]!r}) — привязка не "
                            f"сходится, и считать его мерой этого критерия нельзя")

    root = repo_root or REPO_ROOT
    data = data_dir or os.path.join(root, "data")
    rel = str(getattr(meter, "REPORT_REL", "") or "")
    if not rel:
        return UNMEASURED, ("прибор не называет адрес своего артефакта "
                            "(`REPORT_REL`) — читать нечего")
    path = os.path.join(data, os.path.basename(rel))

    def _read(where: str):
        with open(where, "r", encoding="utf-8") as handle:
            return json.load(handle)

    try:
        doc = _read(path)
    except (OSError, ValueError) as exc:
        return UNMEASURED, (f"артефакт {path} не прочитан ({exc}) — о "
                            f"воспроизводимости НЕ СКАЗАНО НИЧЕГО")
    if not isinstance(doc, dict):
        return UNMEASURED, (f"артефакт {path} — не объект "
                            f"({type(doc).__name__}), вердикта в нём нет")

    # Свежесть: порог из конституции, возраст печатается всегда.
    try:
        slo, slo_prov = _cost_evidence_module().declared_slo_hours(root, _read, rel)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"срок годности {rel} не прочитан: "
                            f"{type(exc).__name__}: {exc}")
    stamp = observed(doc, "generated_at", kind=str)
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        made = None
    if made is not None and made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    if made is None:
        return UNMEASURED, (f"артефакт не пишет разбираемый `generated_at` "
                            f"({stamp!r}) — возраст НЕ ИЗМЕРЕН, и `slo_hours` при "
                            f"нём украшение")
    age = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    if slo is None:
        return UNMEASURED, (f"артефакту {age:.1f} ч, а срок годности взять неоткуда: "
                            f"{slo_prov} — свежесть НЕ СУЖДЕНА")
    if age > float(slo):
        return UNMEASURED, (f"артефакт протух: {age:.1f} ч при объявленном пределе "
                            f"{float(slo):g} ч ({slo_prov}) — сегодняшнего ответа "
                            f"прибора нет, а вчерашний за него не выдаётся")

    # `subjects` и `census` — ВХОДЫ, а не окружение, и ровно по той причине, по
    # которой входом объявлены часы (`.claude/rules/deployment.md`): контроль
    # обязан закрепить ОБЕ стороны сравнения — и население субъектов, и
    # знаменатель в долларах. Умолчание — живая перепись и живой список прибора;
    # `run_probe` их не предлагает и предложить не может (он знает только про
    # дерево), так что боевой путь всегда идёт по умолчанию.
    try:
        block = meter.criterion_verdict(doc, root=root, data_dir=data, now=now,
                                        subjects=subjects, census=census)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"вердикт критерия не вынесен: "
                            f"{type(exc).__name__}: {exc}")

    cov = block.get("coverage") or {}
    if cov.get("measured"):
        where = (f"спрошена целиком решающая поверхность "
                 f"${cov['fully_asked_usd']:,.2f} из ${cov['total_capital_usd']:,.2f} "
                 f"(частично ${cov['partly_asked_usd']:,.2f} · не спрошена "
                 f"${cov['unasked_usd']:,.2f} · решатель не назван "
                 f"${cov['no_decider_usd']:,.2f}); спрошены "
                 f"{', '.join(cov['asked_modules']) or '—'}, из них не решают ни "
                 f"одной книги {', '.join(cov['asked_modules_deciding_nothing']) or '—'}")
    else:
        where = f"покрытие решающей поверхности НЕ ИЗМЕРЕНО: {cov.get('reason')}"
    where += (f"; прогонов {doc.get('runs')}, субъектов "
              f"{len(doc.get('subjects_measured') or [])}, находок "
              f"{len(doc.get('findings') or [])}, непрочитанного "
              f"{len(doc.get('unchecked') or [])}; артефакт снят {stamp} "
              f"({age:.1f} ч при пределе {float(slo):g} ч, {slo_prov})")
    blind = ("«не спрошен» это НЕ «не воспроизводим»: про такого решателя не "
             "известно ничего; спрошенным объявляется модуль, который субъект "
             "зовёт ПО ИМЕНИ, транзитивную цепочку проба не обходит, а книги "
             "перечисляет перепись решателей — о книге вне неё проба не знает")

    status = block.get("status")
    reason = block.get("reason") or "причина не названа"
    if status == meter.CRITERION_NOT_SATISFIED:
        return NOT_SATISFIED, f"{reason} ({where}; {blind})"
    if status == meter.CRITERION_UNMEASURED:
        return UNMEASURED, f"{reason} ({where}; {blind})"
    if status == meter.CRITERION_SATISFIED:
        return SATISFIED, f"{reason} ({where}; {blind})"
    return UNMEASURED, (f"прибор вернул вердикт критерия {status!r}, который не "
                        f"переносится — молчать об этом нельзя")


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


# ── проба: класс «отсутствия наблюдения» закрыт (инв. #17) ────────────────────
#: Потолки в ЧЛЕНАХ класса. Читаются у сторожа, а не набираются здесь второй
#: копией: два числа одного закона — ровно тот молчаливый спор, который уже
#: стоил лестнице CIO трёх циклов (ADR-384 §«правило живёт второй копией»).
def measure_absent_observation_class(root=None, baseline_path=None) -> dict:
    """Члены класса инв. #17 в дереве ПРОТИВ базы. Только чтение, только AST.

    Возврат: ``{"measured": bool, "reason": str, "new": [...], "over_ceiling":
    {...}, "tree": {...}, "baseline": {...}}``. ``measured=False`` — прибора нет
    или он не отработал; это НЕ «класс закрыт» и не «класс открыт».

    ``root``/``baseline_path`` существуют ради КОНТРОЛЯ: обе двери к живому
    дереву обязаны закрываться, иначе тест судил бы о рабочей копии, а не о
    стенде, и вердикт зависел бы от того, что кто-то рядом правит.
    """
    try:
        from spa_core.tests import _absent_observation as ao
        from spa_core.tests import test_absent_observation_ratchet as ratchet
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"сторож класса не импортируется: {type(exc).__name__}: {exc}"}
    try:
        found = ao.scan_tree(root if root is not None else ao.REPO_ROOT)
        raw = (ao.load_baseline() if baseline_path is None
               else ao.load_baseline(baseline_path))
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"замер не состоялся: {type(exc).__name__}: {exc}"}

    new: list = []
    tree: dict = {}
    base: dict = {}
    over: dict = {}
    for signal in ao.SIGNALS:
        base_keys = ao.keys_of(ao.baseline_places(raw, signal))
        places = ao.places_of(found, signal)
        tree[signal] = len(places)
        base[signal] = len(base_keys)
        ceiling = ratchet.CEILINGS.get(signal)
        if ceiling is not None and len(base_keys) > ceiling:
            over[signal] = (len(base_keys), ceiling)
        for place in places:
            if ao.place_key(place) in base_keys:
                continue
            new.append(place)
    return {"measured": True, "reason": "", "new": sorted(new),
            "over_ceiling": over, "tree": tree, "baseline": base}


def _probe_absent_observation_class_closed(arg: str | None) -> tuple[str, str]:
    """Критерий: храповик инв. #17 зелен, и база при этом НЕ выросла.

    Меряет ИСХОД, а не структуру: члена класса ищет сам сторож
    (`spa_core/tests/_absent_observation.py`) в ЖИВОМ дереве, и вердикт
    выносится по сравнению с базой. Второй копии признака здесь нет намеренно —
    она разошлась бы с оригиналом молча.

    Две половины, и обе обязаны держаться, иначе «починка» была бы разменом:

    1. **новых членов НЕТ** — то, ради чего храповик и стои́т;
    2. **база не выросла** — иначе первую половину можно было бы «выполнить»
       дописыванием в базу, то есть ровно тем, что запрещает инв. #16.

    Аргумента у пробы НЕТ, и это решение, а не упущение: «класс закрыт в моём
    файле» при выросшем соседе есть зелёный ответ на свой вопрос, выданный за
    ответ на нужный. Переданный аргумент отвергается вслух, а не глотается.
    """
    if (arg or "").strip():
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): "
                            "критерий — о ВСЁМ дереве, и пофайловой формы у "
                            "него нет намеренно")
    got = measure_absent_observation_class()
    if not got.get("measured"):
        return UNMEASURED, got.get("reason", "причина не названа")
    over = got.get("over_ceiling") or {}
    if over:
        names = " · ".join(f"{sig}: в базе {n} при потолке {c}"
                           for sig, (n, c) in sorted(over.items()))
        return NOT_SATISFIED, (
            f"база класса ВЫРОСЛА ({names}) — падение погашено дописыванием, "
            "а не починкой писателя (инв. #16)")
    new = got.get("new") or []
    if new:
        return NOT_SATISFIED, (
            f"новых мест класса {len(new)}: {', '.join(new[:6])}"
            + (" …" if len(new) > 6 else "")
            + " — отсутствие наблюдения по-прежнему выходит наружу нулём "
              "или пустотой (инв. #17)")
    counts = " · ".join(f"{sig}: дерево {got['tree'][sig]}, база "
                        f"{got['baseline'][sig]}" for sig in sorted(got["tree"]))
    return SATISFIED, f"новых мест класса нет и база не выросла ({counts})"


def _probe_journal_reader_census_reaches_http_routes(arg: str | None) -> tuple[str, str]:
    """Перепись читателей журнала ДОХОДИТ до обработчиков HTTP-маршрутов (заказ G27).

    Критерий карточки дословно: *«`unmeasured_causes.http_route_handler` упало ниже 20,
    и у каждого переведённого модуля есть вердикт по ИСХОДУ на трёх стендах»*. Проба
    меряет его НАСТОЯЩИМ контуром на одноразовых стендах, а не чтением вчерашнего
    артефакта: артефакт мог быть написан кодом, которого в дереве уже нет.

    Три звена, и каждое рвётся отдельно:

    1. **Каталог стенда доходит до чужого процесса.** Партия зова возвращает ответы.
       Рвётся снятием пина ``SPA_DATA_DIR`` — тогда процесс-зовущий отказывает
       (fail-CLOSED), партия пуста, и проба это видит.
    2. **Модуль получает вердикт ПО МАРШРУТАМ.** У живого роутера появляется разбор
       ``routes`` с исходом у каждого пути — то есть он вышел из общей причины
       ``http_route_handler``. Рвётся возвратом к вердикту на целом модуле.
    3. **Стенд ДОКАЗАННО дошёл до обработчика.** Хотя бы один маршрут несёт
       ``reaches_stand``, то есть его ответ на ПУСТОМ каталоге ОТЛИЧАЛСЯ. Без этого
       звена «нечувствителен к стенду» было бы утверждением о читателе, которого
       стенд не касался, — та же слепота, только потише.

    Живой ``data/`` не открывается: журнал стенда синтетический, две строки, и обе
    строит сама проба.
    """
    import json as _json
    import tempfile
    from pathlib import Path as _Path

    from spa_core.monitoring import run_identity_key_price as census

    if arg:
        # Пофайловой формы у критерия нет намеренно: «у моего роутера чисто» при
        # слепом соседе — зелёный ответ на свой вопрос, выданный за нужный.
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): критерий "
                            "про ВСЮ партию маршрутов, а не про один модуль")

    #: Именной, а не по образцу: роутер, читающий стенд (`tier1`), и роутер,
    #: который его не открывает (`redteam`) — второй нужен, чтобы звено 3 не
    #: оказалось истинным по построению на любом наборе.
    names = ["spa_core.api.routers.tier1", "spa_core.api.routers.redteam"]
    try:
        with tempfile.TemporaryDirectory(prefix="spa_g27_probe_") as tmp:
            root = _Path(tmp)
            src = root / "src" / "data"
            src.mkdir(parents=True)
            rows = [{"cycle_date": "2026-09-10", "verdict": "HOLD",
                     "decision_id": "adr060-shadow-2026-09-10",
                     "generated_at": "2026-09-10T06:00:00+00:00"},
                    {"cycle_date": "2026-09-11", "verdict": "HOLD",
                     "decision_id": "adr060-shadow-2026-09-11",
                     "generated_at": "2026-09-11T06:00:00+00:00"}]
            (src / census.HISTORY_FILENAME).write_text(
                "\n".join(_json.dumps(r, sort_keys=True) for r in rows) + "\n",
                encoding="utf-8")
            # Файл, который живой роутер РЕАЛЬНО читает, с отличимым значением.
            # Без него стенд отличается от пустого каталога только журналом,
            # которого `tier1` не читает, — и звено 3 краснело бы на ЦЕЛОМ
            # контуре (замер: так и было в первой редакции пробы). Значение
            # намеренно не похоже на умолчание обработчика.
            (src / "tier1_verdict.json").write_text(
                _json.dumps({"probe_marker": "g27-stand-reached"}), encoding="utf-8")
            stands, why = census.build_stands(src, root / "stands")
            if stands is None:
                return UNMEASURED, f"стенды не построены: {why}"
            tree = _Path(census.__file__).resolve().parents[2]
            answers, meta = census.http_probe_batch(stands, names, tree)
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"контур не отработал: {type(exc).__name__}: {exc}"

    if not answers:
        return NOT_SATISFIED, (f"звено 1: партия зова маршрутов пуста — "
                               f"{meta.get('reason') or 'причина не названа'}")
    rows_out = {n: census.classify_http_reader(n, answers[n]) for n in names if n in answers}
    live = rows_out.get("spa_core.api.routers.tier1") or {}
    if not (live.get("routes") or {}):
        return NOT_SATISFIED, ("звено 2: у живого роутера нет разбора по маршрутам — "
                               f"вердикт {live.get('outcome')} / {live.get('cause')}")
    reached = [p for p, v in (live.get("routes") or {}).items() if v.get("reaches_stand")]
    if not reached:
        return NOT_SATISFIED, ("звено 3: ни один маршрут не доказал, что стенд до него "
                               "дошёл — «нечувствителен» было бы утверждением ни о чём")
    return SATISFIED, (f"маршрутов у tier1 {len(live['routes'])}, стенда достигли "
                       f"{len(reached)}; причина http_route_handler с него снята")


def _probe_journal_reader_census_verdict_under_injected_clock(
        arg: str | None) -> tuple[str, str]:
    """Вердикт читателю получается при ПРОВЕДЁННЫХ часах прогона (заказ G28).

    Критерий карточки дословно: *«у каждого либо есть вердикт по ИСХОДУ на трёх
    стендах при ИНЪЕКТИРОВАННЫХ часах, либо названа причина, по которой инъекция
    невозможна; счётчик `unmeasured_causes.verdict_rests_on_unstable_coords`
    убывает, а не переименовывается»*.

    Меряется НАСТОЯЩИЙ контур переписи на одноразовых стендах — так же, как у
    соседней пробы G27, и по той же причине: артефакт мог быть написан кодом,
    которого в дереве уже нет. Живой ``data/`` не открывается ни одним звеном:
    журнал стенда синтетический, обе строки строит сама проба.

    Четыре звена, и каждое рвётся отдельно:

    1. **Часы доходят до читателя.** Читатель возвращает полученное время;
       сверяется ЗНАЧЕНИЕ, а не наличие параметра. Рвётся потерей часов в
       ``module_driver`` — то есть ровно тем состоянием, что было до G28.
    2. **Без часов вердикта НЕТ.** Тот же читатель на тех же стендах уходит в
       ``verdict_rests_on_unstable_coords``. Без этого звена звено 3 было бы
       истинным по построению и доказывало бы только само себя.
    3. **С часами вердикт ЕСТЬ.** Исход, а не структура.
    4. **Инъекция не красит всех подряд.** Схлопывающий читатель остаётся
       схлопывающим: иначе счётчик «убыл» бы враньём — самый дешёвый способ
       погасить класс, и он обязан краснеть.

    Население (счётчик в артефакте) — РИДЕР, а не гейт, и это сказано вслух:
    артефакт пишет дневной цикл, а не проба. Строка ``clock_injected`` в нём
    доказывает, что артефакт написан НОВЫМ кодом; пока её нет, население
    честно отвечает «не измерено», а вердикт пробы решают звенья 1–4.
    """
    import tempfile
    from datetime import timedelta
    from pathlib import Path as _Path

    from spa_core.monitoring import run_identity_key_price as census

    if arg:
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): критерий "
                            "про класс целиком, а не про один модуль")

    #: Читатель-стенд, воспроизводящий дефект ДЕТЕРМИНИРОВАННО: без часов его
    #: координата бежит на каждом зове (счётчик, а не стенные часы — иначе
    #: звено 2 держалось бы на везении планировщика), с часами стоит.
    reader_src = (
        "_N=[0]\n"
        "def measure(data_dir, now=None):\n"
        "    if now is None:\n"
        "        _N[0]+=1\n"
        "        age=_N[0]\n"
        "    else:\n"
        "        age=int(now.timestamp())\n"
        "    return {'answer': 'журнала не читаю', 'age_s': age}\n")
    collapsing_src = (
        "_N=[0]\n"
        "def measure(data_dir, now=None):\n"
        "    import json\n"
        "    if now is None:\n"
        "        _N[0]+=1\n"
        "        age=_N[0]\n"
        "    else:\n"
        "        age=int(now.timestamp())\n"
        "    rows=[json.loads(l) for l in (data_dir/'h.jsonl').read_text().splitlines() if l.strip()]\n"
        "    by={}\n"
        "    for r in rows: by[r['cycle_date']]=r\n"
        "    return {'age_s': age, 'verdicts': sorted((d, v['verdict']) for d, v in by.items())}\n")

    try:
        with tempfile.TemporaryDirectory(prefix="spa_g28_probe_") as tmp:
            root = _Path(tmp)
            pkg = root / "stubs"
            pkg.mkdir()
            (pkg / "g28probe_deaf.py").write_text(reader_src, encoding="utf-8")
            (pkg / "g28probe_last.py").write_text(collapsing_src, encoding="utf-8")
            stands = {}
            for stand, rows in (("s1", [{"cycle_date": "2026-09-11", "verdict": "HOLD"}]),
                                ("s2", [{"cycle_date": "2026-09-11", "verdict": "ACT"},
                                        {"cycle_date": "2026-09-11", "verdict": "HOLD"}]),
                                ("s3", [{"cycle_date": "2026-09-11", "verdict": "ACT"}])):
                data = root / stand / "data"
                data.mkdir(parents=True)
                (data / "h.jsonl").write_text(
                    "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n",
                    encoding="utf-8")
                stands[stand] = root / stand
            now = datetime(2026, 9, 11, 15, 0, 0, tzinfo=timezone.utc) + timedelta(0)
            sys.path.insert(0, str(pkg))
            try:
                import importlib
                deaf = importlib.import_module("g28probe_deaf")
                _entry, call = census.module_driver(deaf, now=now)
                if call is None:
                    return NOT_SATISFIED, "звено 1: прибор не умеет привести читателя"
                got = call(stands["s1"]).get("age_s")
                if got != int(now.timestamp()):
                    return NOT_SATISFIED, (f"звено 1: часы до читателя не дошли — "
                                           f"он ответил {got!r}, а ждали "
                                           f"{int(now.timestamp())!r}")
                bare = census.classify_reader("g28probe_deaf", stands)
                if bare.get("cause") != census.CAUSE_RESTS_ON_UNSTABLE:
                    return NOT_SATISFIED, (
                        "звено 2: БЕЗ часов тот же читатель получил вердикт "
                        f"{bare.get('outcome')}/{bare.get('cause')} — значит зелёное "
                        "звено 3 ничего про инъекцию не доказывает")
                lit = census.classify_reader("g28probe_deaf", stands, now=now)
                if lit.get("outcome") == census.READER_UNMEASURED:
                    return NOT_SATISFIED, (
                        f"звено 3: с часами вердикта всё равно нет — "
                        f"{lit.get('cause')}: {lit.get('reason')}")
                if lit.get("clock_injected") is not True:
                    return NOT_SATISFIED, ("звено 3: строка не признаёт, что часы "
                                           "проведены — улучшение было бы неотличимо "
                                           "от везения")
                coll = census.classify_reader("g28probe_last", stands, now=now)
                if coll.get("outcome") != census.READER_LAST:
                    return NOT_SATISFIED, (
                        "звено 4: схлопывающий читатель под проведёнными часами "
                        f"стал {coll.get('outcome')} — инъекция гасит РАЗНИЦУ, а не "
                        "шум, и класс убыл бы враньём")
            finally:
                sys.path.remove(str(pkg))
                for name in list(sys.modules):
                    if name.startswith("g28probe_"):
                        del sys.modules[name]
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"контур не отработал: {type(exc).__name__}: {exc}"

    #: Замер населения ДО работы: 2026-09-16, ПОЛНЫЙ прогон переписи (785 с) на
    #: живом `data/` и на ЭТОМ дереве, часы стенные. Число с датой, а не
    #: константа; меряет его сама перепись.
    #:
    #: Именно 13, а не 26 из вчерашнего артефакта: тот написан кодом ДО заказа
    #: G27 (в нём `http_route_handler` = 20, у нас 2). Сравнивать с ним значило
    #: бы сложить два разных изменения в одно число и приписать G28 чужую
    #: заслугу. База берётся у КОНТРОЛЬНОГО прогона того же дерева.
    baseline = 13
    tail = ""
    doc = None
    try:
        art = os.path.join(REPO_ROOT, "data", census.ARTIFACT)
        with open(art, encoding="utf-8") as fh:
            doc = json.load(fh)
    except BaseException:  # noqa: BLE001 — население тут РИДЕР, а не гейт
        doc = None
    rows = ((doc or {}).get("readers") or {}).get("modules") or []
    if not rows:
        tail = " · население НЕ ИЗМЕРЕНО: артефакт переписи не прочитан"
    elif not any("clock_injected" in r for r in rows):
        tail = (" · население НЕ ИЗМЕРЕНО: артефакт написан ещё СТАРЫМ кодом "
                "(строки не несут clock_injected) — счётчик обновит ближайший "
                "прогон переписи в дневном цикле")
    else:
        now_n = int(((doc.get("readers") or {}).get("unmeasured_causes")
                     or {}).get(census.CAUSE_RESTS_ON_UNSTABLE, 0))
        tail = (f" · население: {now_n} против {baseline} на замере 16.09 "
                f"({'убыло' if now_n < baseline else 'НЕ убыло'})")
    return SATISFIED, ("контур переписи доказан исходом: без часов "
                       "verdict_rests_on_unstable_coords, с часами вердикт есть, "
                       "схлопывающий читатель схлопывающим и остался" + tail)


# ── earn-defi: своя реализованная цена вместо лицензии (ADR-286 §6) ──────────
#: Порог расхождения своей серии с эталоном, %. Тот же, что у shadow-сверки движка
#: (earn-defi DECISIONS D-23): расхождение выше — это ошибка данных, а не шум.
OWN_REALIZED_MAX_DIFF_PCT = 3.0
#: Сколько последних общих дней обязаны сойтись. Год — чтобы серия прошла хотя бы
#: одну смену режима рынка, а не совпала на спокойном месяце.
OWN_REALIZED_MIN_DAYS = 365
#: Допуск на пропуски внутри этого окна, календарных дней сверх числа точек.
OWN_REALIZED_MAX_HOLE_DAYS = 5
#: Старше этого своя серия уже не «движок читает живое», а снимок.
OWN_REALIZED_MAX_AGE_DAYS = 3
#: Расхождение меньше этого на ВСЁМ окне — не точность, а копия эталона: независимый
#: расчёт из блокчейна побайтно с поставщиком не совпадает никогда.
OWN_REALIZED_COPY_EPS_PCT = 1e-9
#: Имена в `market_data` — контракт между пробой и расчётом в earn-defi.
OWN_REALIZED_SOURCE = "own_chain"
OWN_REALIZED_METRIC = "RealizedPriceUSD"
_EARN_DEFI_DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), "Documents", "earn-defi")


def _probe_earn_defi_own_realized_price(arg: str | None, *, root: str | None = None,
                                        now: "datetime | None" = None) -> tuple[str, str]:
    """Критерий ADR-286 §6: «наши числа совпадают с эталонными на истории» — и движок
    читает СВОИ числа, а не поставщика с лицензией «не для коммерции».

    Меряется ИСХОД по базе движка (`data/earn_defi.db`, только чтение), а не наличие
    модуля: четыре звена, каждое называется по имени, когда рвётся.

    1. своя серия `market_data(source=own_chain, metric=RealizedPriceUSD)` существует;
    2. на последних 365 ОБЩИХ с эталоном днях (эталон = CapMrktCurUSD / CapMVRVCur /
       SplyCur поставщика, как его считает сам движок) расхождение ≤ 3 % в КАЖДЫЙ день,
       окно без дыр, и серия не является копией эталона;
    3. серия свежая (не старше трёх суток от `now`);
    4. последняя запись сигналов движка СОСЛАЛАСЬ на свою серию и несёт её число.

    Репозитория, базы или таблиц нет ⇒ `unmeasured` с причиной (на CI earn-defi нет
    по построению): «не измерено» не выдаётся ни за «выполнено», ни за «не выполнено».
    """
    import sqlite3
    from datetime import date as _date

    root = root or os.environ.get("EARN_DEFI_ROOT") or _EARN_DEFI_DEFAULT_ROOT
    db_path = os.path.join(root, "data", "earn_defi.db")
    if not os.path.isdir(root):
        return UNMEASURED, f"репозитория earn-defi нет по адресу {root} — предмет не измерен"
    if not os.path.isfile(db_path):
        return UNMEASURED, f"базы движка нет: {db_path} — предмет не измерен"
    now = now or datetime.now(timezone.utc)
    try:
        # ЧУЖАЯ база (движок earn-defi, отдельный репозиторий), а не БД SPA: в postgres-миграцию она
        # не входит, и открыть её надо строго на чтение — URI `mode=ro` есть только у родного sqlite3.
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)  # allow-raw-sqlite-connect
    except sqlite3.Error as exc:
        return UNMEASURED, f"база движка не открылась: {exc}"
    try:
        try:
            own = dict(conn.execute(
                "SELECT date, value FROM market_data WHERE source=? AND metric=?",
                (OWN_REALIZED_SOURCE, OWN_REALIZED_METRIC)).fetchall())
            ref_parts: dict = {}
            for d, m, v in conn.execute(
                    "SELECT date, metric, value FROM market_data WHERE source='coinmetrics' "
                    "AND metric IN ('CapMrktCurUSD','CapMVRVCur','SplyCur')"):
                ref_parts.setdefault(d, {})[m] = v
            last_signal = conn.execute(
                "SELECT date, payload FROM signals ORDER BY id DESC LIMIT 1").fetchone()
        except sqlite3.Error as exc:
            return UNMEASURED, f"база движка не прочиталась (нет таблиц?): {exc}"
    finally:
        conn.close()

    # звено 1 — серия есть
    if not own:
        return NOT_SATISFIED, (f"звено 1: своей серии нет — в market_data ноль строк "
                               f"{OWN_REALIZED_SOURCE}/{OWN_REALIZED_METRIC}")

    # звено 2 — сходится с эталоном
    ref: dict = {}
    for d, parts in ref_parts.items():
        mc, mv, sp = parts.get("CapMrktCurUSD"), parts.get("CapMVRVCur"), parts.get("SplyCur")
        if mc and mv and sp and mv > 0 and sp > 0:
            ref[d] = mc / mv / sp
    common = sorted(d for d in own if d in ref and own[d] and own[d] > 0)
    if not ref:
        return UNMEASURED, "эталона нет: в базе ни одного полного дня поставщика — сверять не с чем"
    if len(common) < OWN_REALIZED_MIN_DAYS:
        return NOT_SATISFIED, (f"звено 2: общих с эталоном дней {len(common)} "
                               f"< {OWN_REALIZED_MIN_DAYS}")
    window = common[-OWN_REALIZED_MIN_DAYS:]
    span = (_date.fromisoformat(window[-1]) - _date.fromisoformat(window[0])).days + 1
    if span - len(window) > OWN_REALIZED_MAX_HOLE_DAYS:
        return NOT_SATISFIED, (f"звено 2: окно {window[0]}…{window[-1]} с дырами — "
                               f"{len(window)} точек на {span} календарных дней")
    diffs = {d: abs(own[d] / ref[d] - 1.0) * 100.0 for d in window}
    worst_day = max(diffs, key=lambda d: diffs[d])
    worst = diffs[worst_day]
    if worst > OWN_REALIZED_MAX_DIFF_PCT:
        over = sum(1 for v in diffs.values() if v > OWN_REALIZED_MAX_DIFF_PCT)
        return NOT_SATISFIED, (f"звено 2: расхождение {worst:.2f} % > {OWN_REALIZED_MAX_DIFF_PCT} % "
                               f"({worst_day}); дней выше порога {over} из {len(window)}")
    if worst < OWN_REALIZED_COPY_EPS_PCT:
        return NOT_SATISFIED, ("звено 2: серия побайтно равна эталону на всём окне — это копия "
                               "поставщика, а не расчёт из блокчейна")

    # звено 3 — свежесть
    own_last = max(own)
    age = (now.date() - _date.fromisoformat(own_last)).days
    if age > OWN_REALIZED_MAX_AGE_DAYS:
        return NOT_SATISFIED, (f"звено 3: своя серия кончается {own_last} — {age} сут. назад "
                               f"(> {OWN_REALIZED_MAX_AGE_DAYS}); расчёт не идёт")

    # звено 4 — движок читает своё
    if last_signal is None:
        return NOT_SATISFIED, "звено 4: у движка нет ни одной записи сигналов"
    sig_date, payload_raw = last_signal
    try:
        payload = json.loads(payload_raw)
    except (TypeError, ValueError) as exc:
        return UNMEASURED, f"последняя запись сигналов не разобралась: {exc}"
    src = str(((payload.get("inputs") or {}).get("source")) or "")
    if OWN_REALIZED_SOURCE not in src.split("+"):
        return NOT_SATISFIED, (f"звено 4: последняя запись сигналов ({sig_date}) считана из "
                               f"{src or '—'!s} — движок всё ещё читает поставщика")
    sig_rp = (payload.get("signals") or {}).get("realized_price_usd")
    own_at = own.get(sig_date)
    if sig_rp is None or own_at is None or abs(float(sig_rp) / own_at - 1.0) > 1e-6:
        return NOT_SATISFIED, (f"звено 4: запись сигналов {sig_date} называет источник "
                               f"{OWN_REALIZED_SOURCE}, но несёт {sig_rp} при своей серии {own_at}")
    return SATISFIED, (f"своя серия {len(own)} дн., окно {window[0]}…{window[-1]}: макс. "
                       f"расхождение {worst:.3f} % ({worst_day}); свежесть {age} сут.; "
                       f"запись сигналов {sig_date} читает {src}")



#: Имя карточки решения, названное в теле находки. Обратные кавычки ОБЯЗАТЕЛЬНЫ:
#: проба не вправе собирать имена из вольного текста и зеленеть на том, чего не
#: разбирала (ADR-333 — «не проходит подстрокой»).
_NAMED_CARD_RE = re.compile(r"`(ow(?:n|ner-decision)-[a-z0-9][a-z0-9-]*)`")

#: Статусы, означающие «решение владельца записано в канон» (`.nimbalyst/trackers/owner-decision.yaml`,
#: `category: done`). Список берётся отсюда, а не угадывается строкой у каждого читателя.
_CLOSED_AT_ORIGIN = frozenset({"ingested", "done"})


def _probe_named_cards_closed_at_origin(arg: str | None, *, tracker_dir: str | None = None,
                                        ref: str | None = None) -> tuple[str, str]:
    """Критерий: каждая карточка решения, НАЗВАННАЯ в теле находки `arg`, закрыта на `origin/main`.

    ЗАЧЕМ (ADR-544, цикл #757). Находка вида «N ответов владельца не доехали до канона»
    закрывается не прозой и не перечитыванием, а вопросом к ИСТОЧНИКУ ПРАВДЫ — git, —
    по КАЖДОМУ названному имени. Замер 03.10 на
    ``inbox-dvenadtsat-otvetov-vladeltsa-stoyat-v-ow``: все двенадцать названных карточек
    на ``origin/main`` стоят в ``ingested``, то есть находка ЛОЖНА, и ложной её сделал
    прод-трекер, куда инжест не возвращается НИКОГДА (ADR-152).

    Проба меряет ИСХОД, а не структуру: она зелена ровно тогда, когда утверждение находки
    перестало быть верным — потому ли, что работу сделали, потому ли, что её и не было.
    Обе причины суть закрытие, и обе проверяются одним вопросом к origin.

    ТРИ ИСХОДА РАЗЛИЧИМЫ:

    * имён в теле НЕТ ⇒ ``unmeasured``. Пустое множество обошло бы пробу «вакуумно
      зелёной» — ровно тот дефект, против которого написан инв. #17;
    * нет репозитория / ``origin/main`` не прочитан / карточка не прочитана ⇒ ``unmeasured``
      с названной причиной;
    * хоть одно названное имя открыто на origin (или его там нет вовсе) ⇒ ``not_satisfied``
      с перечнем.
    """
    if not arg:
        return UNMEASURED, ("пробе нужна карточка-находка "
                            "(acceptance_probe: named_cards_closed_at_origin:<имя-карточки>)")
    tracker = tracker_dir or os.path.join(REPO_ROOT, TRACKER_REL)
    root = _repo_root_for(tracker)
    if not _is_git_repo(root):
        return UNMEASURED, f"в {root} нет репозитория — закрытость на origin НЕ ИЗМЕРЕНА"
    card_id = arg[:-3] if arg.endswith(".md") else arg
    card_path = os.path.join(tracker, f"{card_id}.md")
    if not os.path.isfile(card_path):
        return UNMEASURED, f"карточки {card_id} нет в дереве — предмет НЕ ИЗМЕРЕН"
    try:
        body = _pathlib.Path(card_path).read_text(encoding="utf-8")
    except OSError as exc:
        return UNMEASURED, f"карточка {card_id} не прочитана ({exc}) — НЕ ИЗМЕРЕНО"

    names = sorted(set(_NAMED_CARD_RE.findall(body)))
    if not names:
        return UNMEASURED, (f"в теле {card_id} не названо ни одной карточки решения — "
                            f"пустое множество НЕ читается как «всё закрыто»")

    import subprocess as _subprocess

    use_ref = ref or "origin/main"
    opened: list[str] = []
    for name in names:
        rel = f"{TRACKER_REL}/{name}.md"
        try:
            out = _subprocess.run(["git", "-C", root, "show", f"{use_ref}:{rel}"],
                                  capture_output=True, text=True, timeout=30)
        except (OSError, _subprocess.SubprocessError) as exc:
            return UNMEASURED, f"git не ответил про {name} ({exc}) — НЕ ИЗМЕРЕНО"
        if out.returncode != 0:
            opened.append(f"{name}: на {use_ref} файла нет")
            continue
        status = ""
        for line in out.stdout.splitlines():
            if line.startswith("status:"):
                status = line.split(":", 1)[1].strip()
                break
        if status not in _CLOSED_AT_ORIGIN:
            shown = status or "не прочитан"
            opened.append(f"{name}: на {use_ref} статус '{shown}'")

    where = f"названо {len(names)}, ref {use_ref}"
    if opened:
        return NOT_SATISFIED, (f"НЕ закрыты на {use_ref}: {len(opened)} из {len(names)} — "
                               + "; ".join(opened[:6]) + f" ({where})")
    return SATISFIED, (f"все {len(names)} названных карточек закрыты на {use_ref} "
                       f"(статус из {sorted(_CLOSED_AT_ORIGIN)}) ({where})")


def _probe_card_copies_agree(arg: str | None, *, tracker_dir: str | None = None,
                             ref: str | None = None) -> tuple[str, str]:
    """Критерий: у карточки `arg` НЕТ закрытия, которое существует только здесь.

    ЗАЧЕМ. Карточка живёт в двух копиях — в рабочем дереве и на ``origin/main``, —
    и закрытие, поставленное только в дереве, не есть работа сделанная. Замер
    04.09 и он же 18.09: стоячий приказ владельца
    ``inbox-task-portfolio-cio-dynamic-capital-alloc`` помечен в прод-дереве
    ``done`` (след `new -> done`, 31.08), а на ``origin/main`` стоит
    ``in-progress`` с ``priority: critical`` и блоком «УКАЗАНИЕ ВЛАДЕЛЬЦА», какого
    в прод-копии нет вовсе. Шаг 0a-ГОЛОД читает origin и зовёт приказ голодающим;
    любой прибор, читающий прод-копию, считает его выполненным. Два ответа об одной
    карточке, и оба выглядят измеренными.

    ПРАВИЛО НЕ КОПИРУЕТСЯ: и класс расхождения, и ПОРЯДОК отметок берутся у того
    сторожа, который их меряет (``scripts/check_tracker_drift``), а не считаются
    здесь вторым экземпляром — две копии одной мерки расходятся молча (ADR-220).

    ТРИ ИСХОДА РАЗЛИЧИМЫ. Нет репозитория, не прочитан ``origin/main``, карточки нет
    ни в дереве, ни среди разошедшихся ⇒ ``unmeasured`` с названной причиной, а не
    «выполнено». Дерево и ref названы в detail отдельно: проба, запущенная из
    worktree ОТ ``origin/main``, сравнивает копию саму с собой и зеленеет ни о чём,
    и зелёный из worktree не должен читаться как зелёный в проде.
    """
    if not arg:
        return UNMEASURED, ("пробе нужна карточка "
                            "(acceptance_probe: card_copies_agree:<имя-карточки>)")
    tracker = tracker_dir or os.path.join(REPO_ROOT, TRACKER_REL)
    root = _repo_root_for(tracker)
    if not _is_git_repo(root):
        return UNMEASURED, f"в {root} нет репозитория — расхождение копий НЕ ИЗМЕРЕНО"
    scripts_dir = os.path.join(root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import check_tracker_drift as drift
    except ImportError as exc:                       # pragma: no cover — защита ввоза
        return UNMEASURED, f"сторож расхождения не ввезён ({exc}) — НЕ ИЗМЕРЕНО"
    card_id = arg[:-3] if arg.endswith(".md") else arg
    try:
        report = drift.analyze(_pathlib.Path(tracker), ref or drift.DEFAULT_REF)
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, f"сверка с origin не удалась ({exc}) — НЕ ИЗМЕРЕНО"
    where = (f"дерево {root}, ref {report.ref} {(report.ref_sha or '?')[:9]}, "
             f"в дереве {report.tree_count} / на ref {report.origin_count}")
    if not report.origin_count:
        return UNMEASURED, f"копия трекера на ref не прочитана — НЕ ИЗМЕРЕНО ({where})"
    mine = [f for f in report.findings if f.card_id == card_id]
    if not mine:
        if not os.path.isfile(os.path.join(tracker, f"{card_id}.md")):
            return UNMEASURED, (f"карточки {card_id} нет ни в дереве, ни среди "
                                f"разошедшихся — предмет НЕ ИЗМЕРЕН ({where})")
        # Пустая находка бывает НАБЛЮДЕНИЕМ и бывает СВОЙСТВОМ ДЕРЕВА, и спрашивать
        # об этом надо ровно здесь: если находка ЕСТЬ, сравнение доказало свою
        # содержательность собой, и тавтологию мерить незачем (ADR-504, заказ G38 п. 1).
        taut, why = _tracker_comparison_tautological(
            root, os.path.join(tracker, f"{card_id}.md"), report.ref_sha)
        if taut is None:
            return UNMEASURED, (f"содержательность сверки НЕ УСТАНОВЛЕНА ({why}) — "
                                f"пустая находка не читается как «сошлись» ({where})")
        if taut:
            return UNMEASURED, (f"сверка ТАВТОЛОГИЧНА ({why}) — расхождение копий "
                                f"НЕ ИЗМЕРЕНО; мерить из прод-дерева ({where})")
        return SATISFIED, f"копии сошлись: расхождения по {card_id} нет ({where})"
    f = mine[0]
    # Первый конъюнкт СЕГОДНЯ избыточен и это ИЗМЕРЕНО, а не предположено:
    # дифференциальная батарея цикла #629 показала, что его подмена на `True`
    # не роняет ни одной проверки — `order` по контракту сторожа заполняется
    # ТОЛЬКО у класса `diverged`, у `stale`/`hidden`/`undelivered` второй копии
    # нет вовсе. Оставлен намеренно как fail-CLOSED пояс на случай, если этот
    # контракт изменится; выживший мутант назван здесь, а не закрашен тестом,
    # который проверял бы сам себя.
    closed_here_only = (f.kind == drift.KIND_DIVERGED
                        and f.order == drift.ORDER_TREE_NEWER
                        and f.tree_status in _TERMINAL_HERE
                        and f.origin_status not in _TERMINAL_HERE)
    detail = (f"{card_id}: здесь `{f.tree_status or '?'}`, на {report.ref} "
              f"`{f.origin_status or '?'}`, класс {f.kind}/"
              f"{f.order or 'порядок не мерился'} ({where})")
    if closed_here_only:
        return NOT_SATISFIED, "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ — " + detail
    return SATISFIED, "закрытия только здесь нет — " + detail


def _probe_forbidden_import_gate_single_instrument(arg: str | None) -> tuple[str, str]:
    """Гейт запрещённых импортов ЗАМКНУТ: один прибор, он кусается, и его зовут.

    Меряет ИСХОД на одноразовом дереве, а не структуру прибора: три вопроса
    задаются самому `scripts/lint_forbidden_imports.py` через запуск, четвёртый —
    проводке. Любое одно порванное звено даёт `not_satisfied` с ИМЕНЕМ звена:

    1. **прибор МЕРЯЕТ живое дерево** — код возврата не 2 (третий исход есть, но
       сегодня он не сработал: «не измерено» никогда не выдаётся за «чисто»);
    2. **кусается на настоящем импорте** — во временное дерево кладётся
       `import anthropic`, ожидается код 1. Прибор, который не краснеет ни на
       чём, — украшение;
    3. **не кусается на ОБРАЗЦЕ кода в строке** — воспроизводится авария 23.09:
       `spa_core/monitoring/cio_architecture_constraints.py` держит образец
       нарушения строковым литералом, и подстрочный прибор краснил на нём
       `SPA CI-Lite` с 07.09;
    4. **прибор ПОЗВАН** — шаг `ci-lite.yml` зовёт именно его и не держит своей
       копии правила (`FORBIDDEN_LIBS`). Прибор без зовущего — отчёт без
       читателя, ровно тот класс, ради которого написан ADR-333.

    Проба НЕ подтверждает, что нарушений в дереве нет вовсе: известные и
    названные живут в `scripts/forbidden_import_baseline.json`, и их число
    печатается в detail, чтобы «ноль» и «один известный» не выглядели одинаково.
    """
    if (arg or "").strip():
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): "
                            "предмет — гейт целиком, пофайловой формы у него нет")
    import subprocess as _sp
    import tempfile as _tf
    script = os.path.join(REPO_ROOT, "scripts", "lint_forbidden_imports.py")
    workflow = os.path.join(REPO_ROOT, ".github", "workflows", "ci-lite.yml")
    if not os.path.isfile(script):
        return UNMEASURED, f"прибора {script} нет в дереве — гейт НЕ ИЗМЕРЕН"

    def _run(root: str):
        try:
            return _sp.run([sys.executable, script, "--root", root, "--json"],
                           capture_output=True, text=True, timeout=300)
        except (OSError, _sp.SubprocessError) as exc:      # pragma: no cover
            return exc

    live = _run(REPO_ROOT)
    if not hasattr(live, "returncode"):
        return UNMEASURED, f"прибор не запустился ({live}) — гейт НЕ ИЗМЕРЕН"
    if live.returncode == 2:
        return NOT_SATISFIED, ("прибор НЕ ИЗМЕРИЛ живое дерево (код 2): "
                               + (live.stdout or live.stderr or "").strip()[:200])
    try:
        known = sum(1 for v in json.loads(live.stdout or "{}").get("violations", [])
                    if v.get("known"))
    except ValueError:
        return UNMEASURED, "машинный вывод прибора не разобран — гейт НЕ ИЗМЕРЕН"

    with _tf.TemporaryDirectory() as tmp:
        try:
            import lint_forbidden_imports as _lfi                  # noqa: F401
            domains = _lfi.DOMAINS
        except ImportError:
            sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
            try:
                import lint_forbidden_imports as _lfi
                domains = _lfi.DOMAINS
            except ImportError as exc:
                return UNMEASURED, f"прибор не ввезён ({exc}) — гейт НЕ ИЗМЕРЕН"
        for domain in domains:
            os.makedirs(os.path.join(tmp, domain), exist_ok=True)
            with open(os.path.join(tmp, domain, "_ok.py"), "w", encoding="utf-8") as fh:
                fh.write("import json\n")
        real = os.path.join(tmp, domains[0], "real.py")
        with open(real, "w", encoding="utf-8") as fh:
            fh.write("import anthropic\n")
        bites = _run(tmp)
        os.remove(real)
        with open(os.path.join(tmp, domains[0], "sample.py"), "w", encoding="utf-8") as fh:
            fh.write('SAMPLES = {"sdk": "import anthropic\\n"}\n')
        on_sample = _run(tmp)

    if getattr(bites, "returncode", None) != 1:
        return NOT_SATISFIED, ("прибор НЕ КУСАЕТСЯ: на дереве с настоящим "
                               f"`import anthropic` код {getattr(bites, 'returncode', '?')}, "
                               "ожидался 1")
    if getattr(on_sample, "returncode", None) != 0:
        return NOT_SATISFIED, ("прибор краснеет на ОБРАЗЦЕ кода в строке "
                               f"(код {getattr(on_sample, 'returncode', '?')}) — "
                               "авария 23.09 не закрыта")
    try:
        with open(workflow, encoding="utf-8") as fh:
            wf = fh.read()
    except OSError as exc:
        return UNMEASURED, f"{workflow} не прочитан ({exc}) — зовущий НЕ ИЗМЕРЕН"
    if "python3 scripts/lint_forbidden_imports.py" not in wf:
        return NOT_SATISFIED, "CI-Lite не зовёт прибор — отчёт без читателя"
    if "FORBIDDEN_LIBS" in wf:
        return NOT_SATISFIED, ("в ci-lite.yml вернулась своя копия правила "
                               "(FORBIDDEN_LIBS) — правило снова в двух местах")
    return SATISFIED, (f"гейт замкнут: прибор измерил дерево (код {live.returncode}, "
                       f"известных нарушений в базе {known}), кусается на настоящем "
                       "импорте, молчит на образце в строке, и зовёт его CI-Lite")


#: Рабочий процесс, чей вердикт о вершине `main` и есть приёмка. Имя файла, а не
#: отображаемое имя: отображаемое меняют правкой одной строки, путь — нет.
CI_WORKFLOW_FILE = "test.yml"

#: Ветка, о вершине которой задаётся вопрос. Вердикт о PR-ветке на него не отвечает.
CI_BRANCH = "main"

#: Сколько последних прогонов просматривать в поисках ВЕРДИКТА. Окно нужно потому,
#: что отменённые прогоны вердиктом не являются (см. `_ci_latest_verdict`), и подряд
#: их бывает много: группа `concurrency` в test.yml гасит устаревшие пуш-прогоны.
CI_VERDICT_WINDOW = 30


def _github_slug(repo_root: str) -> str | None:
    """`owner/repo` по адресу origin. `None` — адрес не прочитан (это НЕ «нет репозитория»)."""
    url = _git(["remote", "get-url", "origin"], repo_root=repo_root)
    if not url:
        return None
    url = url.strip()
    for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/"):
        if url.startswith(prefix):
            slug = url[len(prefix):]
            break
    else:
        return None
    if slug.endswith(".git"):
        slug = slug[:-4]
    return slug.strip("/") or None


def _github_json(url: str, *, timeout: float = 20.0):
    """GET к API GitHub. `(данные, None)` либо `(None, причина)`.

    Токен берётся из Keychain, если он там есть, и его ОТСУТСТВИЕ не есть отказ:
    репозиторий читается и анонимно, просто с меньшим лимитом. Отличать «ответа не
    было» от «ответ пуст» обязан вызывающий — поэтому причина возвращается строкой,
    а не проглатывается в `None`.
    """
    import json as _json
    import subprocess
    import urllib.error
    import urllib.request

    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "spa-card-acceptance"}
    try:
        tok = subprocess.run(
            ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-w"],
            capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        tok = ""
    if tok:
        headers["Authorization"] = f"token {tok}"
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=timeout) as fh:
            return _json.loads(fh.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:                                   # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _ci_latest_verdict(slug: str, *, fetch=None) -> tuple[dict | None, str]:
    """Последний прогон `test.yml` о `main`, который ВЫНЕС вердикт.

    `cancelled` вердиктом НЕ является и пропускается со счётом: группа
    `concurrency` в `test.yml` гасит устаревшие пуш-прогоны пачками, и принять
    отмену за «не падало» значило бы выдать НЕ ИЗМЕРЕНО за чистоту (инвариант #17).
    Окно, где вердикта нет вовсе, — тоже третий исход, а не зелёный.
    """
    url = (f"https://api.github.com/repos/{slug}/actions/workflows/"
           f"{CI_WORKFLOW_FILE}/runs?branch={CI_BRANCH}&per_page={CI_VERDICT_WINDOW}")
    data, why = (fetch or _github_json)(url)
    if data is None:
        return None, f"история прогонов не прочитана ({why})"
    runs = data.get("workflow_runs")
    if not isinstance(runs, list):
        return None, "ответ API без списка прогонов"
    if not runs:
        return None, f"о ветке {CI_BRANCH} прогонов {CI_WORKFLOW_FILE} нет вовсе"
    skipped = 0
    for run in runs:
        if run.get("status") != "completed":
            skipped += 1
            continue
        if run.get("conclusion") in (None, "cancelled", "skipped"):
            skipped += 1
            continue
        return run, f"пропущено без вердикта: {skipped}"
    return None, (f"во всех {len(runs)} последних прогонах вердикта нет "
                  f"(отменены/не завершены) — НЕ ИЗМЕРЕНО")


def _probe_ci_main_verdict_green(arg: str | None, *, repo_root: str | None = None,
                                 fetch=None) -> tuple[str, str]:
    """Критерий: у ВЕРШИНЫ `main` есть вердикт `SPA Tests`, и он `success`.

    ЗАЧЕМ. Замер 24.09 (цикл #692): последний зелёный `SPA Tests` о `main` —
    **26.08**, а за 29 суток после него 627 `failure`, 82 `cancelled` и НИ ОДНОГО
    `success`. Не заметил этого никто, и механизм незамечания назван в самой
    карточке: каждый цикл докладывал «соседи N passed» по СВОЕМУ набору файлов, а
    предписанный прогон четырёх каталогов — тот, что гейтит CI, — не запускал никто.
    Зелёный ответ прибора на СВОЙ вопрос не есть ответ на нужный.

    ПОЧЕМУ ПРОБА ХОДИТ НА ORIGIN, А НЕ МЕРИТ ДЕРЕВО. Критерий карточки записан
    именно так: «завершается `success`, и это подтверждено прогоном на origin, а не
    локальным „у меня зелено“». Локальный прогон отвечает на вопрос о ЛОКАЛЬНОЙ
    машине; он не видит ни второй версии Python матрицы, ни замедления раннера, на
    котором и ломается бюджет таймаута.

    ТРИ ИСХОДА РАЗЛИЧИМЫ, И ЧЕТВЁРТОГО НЕТ.
      * `satisfied` — вердикт есть, он `success`, и он О ВЕРШИНЕ `main`;
      * `not_satisfied` — вердикт есть и он не `success` (назван sha и вывод);
      * `unmeasured` — сети/репозитория/вердикта нет, ЛИБО последний вердикт
        относится к УСТАРЕВШЕМУ sha. Последнее — не придирка: зелёный о позавчерашнем
        коммите ничего не говорит о вершине, а выглядит как разрешение закрыть
        карточку. Это ровно подделка доказательства, а не слабое доказательство.
    """
    root = repo_root or REPO_ROOT
    # Сеть НЕ опрашивается из тестового окружения, и это НАЗВАННЫЙ третий исход, а не
    # молчаливая попытка: набор гоняет каждую зарегистрированную пробу без инъекции
    # (`test_every_registered_probe_returns_a_known_verdict`), и живой вызов оттуда
    # отвечал бы на вопрос «что сегодня на origin», а не на вопрос теста — ровно то,
    # что запрещает `.claude/rules/adapters.md`. Предмет пробы меряется из ПРОД-дерева
    # шагом 0-офис, где `SPA_ENV` не выставлен; с инъекцией (`fetch=`) отказа нет.
    if fetch is None and os.environ.get("SPA_ENV") == "ci":
        return UNMEASURED, ("сеть в тестовом окружении не опрашивается (SPA_ENV=ci) — "
                            "вердикт CI меряется из прод-дерева шагом 0-офис")
    get = fetch or _github_json
    if not _is_git_repo(root):
        return UNMEASURED, f"в {root} нет репозитория — вердикт CI НЕ ИЗМЕРЕН"
    slug = _github_slug(root)
    if not slug:
        return UNMEASURED, "адрес origin не разобран как GitHub — вердикт НЕ ИЗМЕРЕН"
    run, note = _ci_latest_verdict(slug, fetch=get)
    if run is None:
        return UNMEASURED, f"{note} ({slug})"
    sha = str(run.get("head_sha") or "")
    concl = str(run.get("conclusion"))
    when = str(run.get("created_at") or "?")
    where = f"{slug} {CI_WORKFLOW_FILE}@{CI_BRANCH}, прогон {sha[:9]} от {when}, {note}"
    head, why = get(f"https://api.github.com/repos/{slug}/commits/{CI_BRANCH}")
    if head is None:
        return UNMEASURED, f"вершина {CI_BRANCH} не прочитана ({why}) — {where}"
    head_sha = str(head.get("sha") or "")
    if not head_sha:
        return UNMEASURED, f"ответ о вершине {CI_BRANCH} без sha — {where}"
    if concl != "success":
        return NOT_SATISFIED, (f"вердикт `{concl}`: {where}. "
                               f"Вершина сейчас {head_sha[:9]}")
    if sha != head_sha:
        return UNMEASURED, (f"последний вердикт `success`, но он о {sha[:9]}, "
                            f"а вершина {CI_BRANCH} — {head_sha[:9]}: о ВЕРШИНЕ "
                            f"вердикта ещё нет — НЕ ИЗМЕРЕНО ({where})")
    return SATISFIED, f"вершина {CI_BRANCH} зелена: {where}"


PR_DELIVERY_MODULE_NAME = "_spa_pr_delivery_census"


def _pr_delivery_module():
    """Перепись доставки PR как модуль: один раз на процесс."""
    import importlib.util
    mod = sys.modules.get(PR_DELIVERY_MODULE_NAME)
    if mod is not None:
        return mod
    path = os.path.join(REPO_ROOT, "scripts", "pr_delivery_census.py")
    spec = importlib.util.spec_from_file_location(PR_DELIVERY_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path} не загружается как модуль")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[PR_DELIVERY_MODULE_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(PR_DELIVERY_MODULE_NAME, None)
        raise
    return mod


def _probe_pr_work_arrived_on_main(arg: str | None, *, repo_root: str | None = None,
                                   fetch=None, now: "datetime | None" = None,
                                   exists_on_base=None) -> tuple[str, str]:
    """Критерий: ни один долго открытый PR не держит в себе не доехавшую работу (ADR-477).

    ЗАЧЕМ. Замер 25.09: приказ владельца «Portfolio CIO» состоит из 52 разделов, а на
    `main` тело якорной карточки обрывалось на середине §5 — §6–52 и аудит
    `RS-portfolio-cio-audit-2026-08-29.md` 28 дней жили только в ЧЕРНОВОМ PR #50.
    Сторож `pr-ci-liveness` был по этому PR ЗЕЛЁН и был ПРАВ: прогонов у head'а три.
    Он отвечал на свой вопрос — «а прогон БЫЛ?» — и нужный никто не задавал.

    ПОЧЕМУ КРИТЕРИЙ ИМЕННО ТАКОЙ. Он выполняется ДВУМЯ законными путями, и это
    намеренно: содержимое перенесено на `main` (пути появились) ЛИБО PR закрыт и из
    населения вышел. Требуй критерий именно появления ИМЕННО ЭТИХ путей — и карточка
    стала бы незакрываемой там, где верный исход иной: ADR-088/089 из PR #10 сталкиваются
    номерами с уже существующими на `main`, то есть их содержимое обязано лечь под
    ДРУГИМИ именами. Критерий меряет ИСХОД («работа не потеряна»), а не форму правки.

    ТРИ ИСХОДА РАЗЛИЧИМЫ.
      * `satisfied`     — не доехавших нет; PR вне досягаемости прибора названы числом;
      * `not_satisfied` — есть PR старше порога, чьи добавляемые пути на `main`
        отсутствуют. Номера и пути названы;
      * `unmeasured`    — сеть/репозиторий/база не прочитаны. НЕ «чисто»: молчание
        прибора обязано отличаться от его одобрения (инв. #17).

    Аргумент пробы — порог в днях (`pr_work_arrived_on_main:14`); по умолчанию берётся
    порог самого прибора.
    """
    root = repo_root or REPO_ROOT
    # Сеть НЕ опрашивается из тестового окружения — названный третий исход, а не
    # молчаливая попытка (та же причина, что у `_probe_ci_main_verdict_green`).
    if fetch is None and os.environ.get("SPA_ENV") == "ci":
        return UNMEASURED, ("сеть в тестовом окружении не опрашивается (SPA_ENV=ci) — "
                            "доставка PR меряется из прод-дерева шагом 0-офис")
    try:
        M = _pr_delivery_module()
    except Exception as exc:                                   # noqa: BLE001
        return UNMEASURED, f"прибор переписи не загружен: {type(exc).__name__}: {exc}"

    max_age = M.DEFAULT_MAX_AGE_DAYS
    if (arg or "").strip():
        try:
            max_age = float(arg.strip())
        except ValueError:
            return UNMEASURED, f"порог {arg!r} не число — доставка НЕ ИЗМЕРЕНА"

    if not _is_git_repo(root):
        return UNMEASURED, f"в {root} нет репозитория — доставка PR НЕ ИЗМЕРЕНА"
    slug = _github_slug(root)
    if not slug:
        return UNMEASURED, "адрес origin не разобран как GitHub — НЕ ИЗМЕРЕНО"

    def _fetch(url):
        data, why = (fetch or _github_json)(url)
        if data is None:
            raise RuntimeError(why or "ответа нет")
        return data

    door = exists_on_base or M.git_base_door(root)
    when = now or datetime.now(timezone.utc)
    report = M.census(slug, _fetch, door, when, max_age)

    bad = [v for v in report["pulls"] if v["state"] == M.NOT_ARRIVED]
    if bad:
        named = "; ".join(f"PR #{v['pr']} ({v['age_days']:g} дн): "
                          + ", ".join(v["missing"][:3])
                          + (f" … ещё {len(v['missing']) - 3}" if len(v["missing"]) > 3 else "")
                          for v in bad)
        return NOT_SATISFIED, f"работа не доехала у {len(bad)} PR — {named}"
    blind = [v for v in report["pulls"] if v["state"] == M.UNMEASURED]
    if blind or report["state"] == M.UNMEASURED and not any(
            v["state"] == M.UNMEASURED_SCOPE for v in report["pulls"]):
        why = blind[0]["reason"] if blind else report.get("reason") or "причина не названа"
        return UNMEASURED, f"{len(blind) or 1} PR не измерен(ы): {why}"
    out_of_reach = sum(1 for v in report["pulls"] if v["state"] == M.UNMEASURED_SCOPE)
    return SATISFIED, (f"не доехавших нет: открытых PR {len(report['pulls'])}, "
                       f"порог {max_age:g} дн, вне досягаемости прибора {out_of_reach} "
                       f"(PR без добавляемых файлов)")



#: Свежее этого — запись журнала решений ещё наблюдение живого производителя.
#: Писатель (`write_shadow_rationale`) отрабатывает каждым дневным циклом, поэтому
#: 24 ч ловили бы ОДНУ пропущенную свечу и превращали критерий в «не измерено» от
#: шума. 48 ч = молчали ДВА цикла подряд: тогда доставка полей, померенная по такой
#: записи, говорит о канонe в git, а не о том, что владелец видит сегодня. Часть
#: вопроса, а не предположение: `data/` частично лежит в git, и в worktree/на CI
#: журнал ЕСТЬ — замороженный. Протухло ⇒ `unmeasured`, НИКОГДА не `satisfied`.
OWNER_VISIBILITY_MAX_AGE_H = 48.0


def _probe_owner_visibility_numbers_delivered(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None,
        repo_root: str | None = None) -> tuple[str, str]:
    """Критерий: все четыре предмета §49 доходят до владельца ПОЛЕМ.

    Предмет — ровно тот, что у карточки `inbox-tri-chisla-iz-prikaza-cio-ne-dohodyat-do`
    и у приказа `inbox-task-portfolio-cio-dynamic-capital-alloc` (§49 `Owner
    visibility`): «Owner видит current/optimal APY, Yield Gap и recommendation».
    Замер #709 (ADR-488): журнал решений нёс все четыре предмета своими полями,
    выдача слоя отображения оставляла ОДИН — три числа терялись на последнем
    шаге, 9 предметов из 12 «записано, но не доставлено».

    **Меряется ИСХОД, а не структура.** Проба не спрашивает «есть ли модуль
    отображения» и «есть ли у него читатель» — на оба вопроса система отвечала
    ДА, пока числа не доходили. Она зовёт перепись
    (`spa_core.monitoring.owner_visibility_census`), а та гоняет НАСТОЯЩИЙ
    `build_books_brief` и сверяет ЗНАЧЕНИЕ каждого предмета с записью журнала.

    **Подстрокой проба не проходит (ADR-333).** Зачёт у переписи — равенство
    значений в поле; найденная в прозе форма числа даёт `prose_only`, и это
    считается потерей, а не зачётом. Третья ось (#710) идёт на шаг дальше: поле,
    которое выдача несёт, обязано ЧИТАТЬСЯ поверхностью владельца — иначе
    предмет дошёл до выдачи и не дошёл до владельца, а прежние две оси обе
    зелены.

    Три исхода разведены:

    * `satisfied` — 12 предметов из 12 полем, ни одного потерянного и ни одного
      непрочитанного поверхностью;
    * `not_satisfied` — есть предмет, записанный журналом и не доставленный
      (или доставленный, но поверхностью не читаемый) — это находка;
    * `unmeasured` — журнал/выдача/ось поверхностей не прочитаны, запись
      протухла, или предмет не записан вовсе. «Не измерено» никогда не выдаётся
      ни за находку, ни за разрешение закрыть карточку (инв. #17).

    Часы и каталог данных — ВХОДЫ, не окружение: иначе вердикт решала бы
    переменная среды, а положительный контроль не мог бы закрепить обе стороны
    сравнения (`.claude/rules/deployment.md`). Проба только ЧИТАЕТ: перепись
    ничего не чинит и ничего не двигает.
    """
    try:
        from spa_core.monitoring import owner_visibility_census as census
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"перепись не импортируется: {type(exc).__name__}: {exc}"

    root = repo_root or REPO_ROOT
    try:
        report = census.run_census(
            _pathlib.Path(data_dir or os.path.join(root, "data")),
            now=now, repo_root=_pathlib.Path(root))
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, f"перепись упала: {type(exc).__name__}: {exc}"

    if not report.get("measured"):
        return UNMEASURED, f"перепись не измерила: {report.get('reason')}"

    # Возраст записи — часть вопроса. Мерится у КАЖДОЙ книги, чья доставка
    # попала в вердикт: протухла одна — утверждение о ней уже не наблюдение.
    when = now or datetime.now(timezone.utc)
    books = report.get("books") or {}
    if not books:
        return UNMEASURED, "перепись не вернула ни одной книги — мерить нечего"
    for book, data in sorted(books.items()):
        stamp = (data or {}).get("generated_at")
        if not stamp:
            return UNMEASURED, (f"у записи книги {book} нет `generated_at` — возраст "
                                f"не измерен, судить о доставке нечем")
        try:
            made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            return UNMEASURED, (f"книга {book}: generated_at {stamp!r} не разобран — "
                                f"возраст НЕ измерен")
        if made.tzinfo is None:
            made = made.replace(tzinfo=timezone.utc)
        age_h = (when - made).total_seconds() / 3600.0
        if age_h > OWNER_VISIBILITY_MAX_AGE_H:
            return UNMEASURED, (
                f"журнал решений книги {book} протух: возраст {age_h:.1f}ч при "
                f"пределе {OWNER_VISIBILITY_MAX_AGE_H:.0f}ч — это замороженный "
                f"канон, а не то, что владелец видит сегодня; мерить надо из "
                f"дерева с живым data/")

    total = int(report.get("subjects_total") or 0)
    as_field = int(report.get("delivered_as_field") or 0)
    lost = int(report.get("recorded_but_not_delivered") or 0)
    not_rendered = list(report.get("fields_not_rendered") or [])
    blind = int(report.get("subjects_unmeasured") or 0)
    surfaces = report.get("surfaces") or {}
    callers = list(surfaces.get("callers") or [])

    if report.get("status") == census.STATUS_UNMEASURED:
        sfields = report.get("surface_fields") or {}
        why = (surfaces.get("reason") if not surfaces.get("measured")
               else sfields.get("reason")) or "причина не названа"
        return UNMEASURED, f"ось поверхностей владельца не измерена: {why}"
    if lost:
        return NOT_SATISFIED, (
            f"записано, но НЕ доставлено {lost} предмет(ов) из {total}: журнал "
            f"несёт число, выдача слоя отображения его роняет")
    if not_rendered:
        return NOT_SATISFIED, (
            f"доставлено полем, но поверхность владельца НЕ читает "
            f"{len(not_rendered)} пол(е/я): {', '.join(not_rendered)} — до выдачи "
            f"предмет дошёл, до владельца нет")
    if blind:
        return UNMEASURED, (
            f"{blind} предмет(ов) из {total} НЕ записаны журналом решений — "
            f"доставка не измерена, и это не «владелец их видит»")
    if not callers:
        return UNMEASURED, ("поверхностей-читателей эндпоинта выдачи не найдено — "
                            "полю некуда доходить")
    if total == 0 or as_field != total:
        return UNMEASURED, (f"перепись дала нечитаемый расклад: предметов {total}, "
                            f"полем {as_field} — вердикт не выводится")
    return SATISFIED, (
        f"доходит полем {as_field} из {total} (три книги × четыре предмета §49), "
        f"потеряно 0, поверхность читает все поля: {', '.join(callers)}")


def _probe_portfolio_decision_owner_covers_capital(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None,
        repo_root: str | None = None) -> tuple[str, str]:
    """Критерий §49 `Architecture`: владелец решения на уровне ВСЕГО портфеля.

    Предмет — дословный критерий владельца из приказа
    `inbox-task-portfolio-cio-dynamic-capital-alloc`: «Portfolio-level decision
    owner существует». Главное слово — **portfolio-level**: цель §1 того же
    приказа сформулирована как «доходность ВСЕГО ПОРТФЕЛЯ», значит вопрос не
    «есть ли аллокатор» и не «решает ли кто-нибудь состав книги», а покрывает ли
    чьё-то решение весь капитал.

    **Меряется ИСХОД, а не структура.** Проба не спрашивает «существует ли
    модуль аллокации» — на этот вопрос система отвечает ДА с самого начала, при
    том что две трети капитала лежат в книгах, которых этот модуль не видит.
    Она зовёт перепись
    (:mod:`spa_core.monitoring.cio_decision_owner_census`), а та считает ДОЛЛАРЫ:
    население книг выводится разбором дерева, капитал каждой берётся из живого
    ``data/``, и доля самого широкого производителя сравнивается с единицей.

    Три исхода разведены:

    * `satisfied` — решение одного производителя (или межкнижного решателя)
      покрывает 100 % капитала: критерий владельца ВЫПОЛНЕН;
    * `not_satisfied` — покрытие неполное: у каждой книги свой решатель, портфель
      целиком не решает никто — это находка;
    * `unmeasured` — население книг не разобрано, книга не прочитана, знаменателя
      нет, либо роль модуля, видящего ВСЕ книги, не установлена. «Не измерено»
      не выдаётся ни за находку, ни за разрешение закрыть карточку (инв. #17).

    Часы и каталоги — ВХОДЫ, не окружение: иначе вердикт решала бы переменная
    среды, а положительный контроль не мог бы закрепить обе стороны сравнения
    (`.claude/rules/deployment.md`). Проба только ЧИТАЕТ.
    """
    try:
        from spa_core.monitoring import cio_decision_owner_census as census
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"перепись не импортируется: {type(exc).__name__}: {exc}"

    root = repo_root or REPO_ROOT
    try:
        report = census.run_census(
            _pathlib.Path(data_dir or os.path.join(root, "data")),
            repo_root=_pathlib.Path(root), now=now)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, f"перепись упала: {type(exc).__name__}: {exc}"

    if not report.get("measured"):
        return UNMEASURED, f"перепись не измерила: {report.get('reason')}"

    widest = report["widest_share"]
    detail = (f"{report['widest_producer']} решает "
              f"${report['widest_covered_usd']:,.2f} = {widest * 100:.2f}% из "
              f"${report['total_capital_usd']:,.2f}; книг {len(report['books'])}, "
              f"межкнижных решателей {len(report['cross_book_deciders'])}")
    if report["verdict"] == census.OWNER_EXISTS:
        return SATISFIED, "владелец решения покрывает весь портфель: " + detail
    out_of_scope = report.get("books_out_of_scope") or []
    return NOT_SATISFIED, (
        f"портфель целиком не решает никто: книг вне самого широкого решения "
        f"{len(out_of_scope)} ({', '.join(out_of_scope) or '—'}), капитала вне него "
        f"${report['uncovered_usd']:,.2f}; " + detail)


#: Предел возраста записи прогона для пробы `no_regression_tests_pass`.
#: Восемь суток — тот же такт, что у соседних недельных приборов. Предел нужен
#: потому, что население может НЕ измениться, а код под ним — измениться: тогда
#: старая запись говорила бы «зелено» про дерево, которого уже нет. Проверка
#: покрытия населения этого не ловит по построению, и подменять одно другим
#: было бы ровно тем «зелёным ответом на свой вопрос», против которого проба
#: и написана.
_NO_REGRESSION_MAX_AGE_H = 192.0


def _probe_no_regression_tests_pass(
        arg: str | None, *, now: "datetime | None" = None,
        repo_root: str | None = None,
        report: dict | None = None) -> tuple[str, str]:
    """Критерий §49 `No regression`: проходят ли существующие risk/security/architecture-тесты.

    Предмет — дословный критерий владельца из приказа
    `inbox-task-portfolio-cio-dynamic-capital-alloc`: «Existing
    risk/security/architecture tests проходят».

    **Меряется ИСХОД, а не цвет джобы.** «CI красный» ≠ «тесты падают» (ADR-474),
    и «CI зелёный» ≠ «эти тесты прошли». Проба берёт население трёх объявленных
    поверхностей у переписи
    (:mod:`spa_core.monitoring.no_regression_census`) — разбором дерева, а не по
    имени файла, — и спрашивает у ЗАПИСИ прогона исход КАЖДОГО члена.

    **Покрытие проверяется ЗАНОВО, у живого дерева.** Записанный отчёт
    отвечает о том населении, какое было на момент замера; тест, добавленный
    после, в записи отсутствует, и зачесть его «наверное, зелёным» значило бы
    сделать пробу fail-OPEN ровно там, где она нужна. Поэтому население
    пересчитывается здесь, и член населения без исхода в отчёте — `unmeasured`
    с ИМЕНЕМ.

    Три исхода разведены:

    * `satisfied` — у каждого члена населения есть исход, и все исходы зелёные;
    * `not_satisfied` — есть НАЗВАННАЯ поломка (это находка, и гасить её
      правкой теста запрещено — инв. #16);
    * `unmeasured` — отчёта нет / он старше предела / население расширилось
      после замера / перепись не измерила. «Не измерено» не выдаётся ни за
      находку, ни за разрешение закрыть карточку (инв. #17).

    Часы, корень дерева и сам отчёт — ВХОДЫ, не окружение: иначе вердикт решала
    бы переменная среды, а положительный контроль не мог бы закрепить обе
    стороны сравнения (`.claude/rules/deployment.md`).
    """
    if (arg or "").strip():
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): "
                            "критерий — о ТРЁХ поверхностях целиком, и пофайловой "
                            "формы у него нет намеренно")
    try:
        from spa_core.monitoring import no_regression_census as census
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"перепись не импортируется: {type(exc).__name__}: {exc}"

    root = repo_root or REPO_ROOT
    if report is None:
        path = os.path.join(root, census.REPORT_REL)
        try:
            with open(path, encoding="utf-8") as fh:
                report = json.load(fh)
        except BaseException as exc:  # noqa: BLE001
            return UNMEASURED, (f"отчёта переписи нет или он не прочитан "
                                f"({census.REPORT_REL}): {type(exc).__name__}: {exc} — "
                                f"исход тестов не наблюдён")
    if not isinstance(report, dict) or not report.get("measured"):
        reason = (report or {}).get("reason") if isinstance(report, dict) else "не словарь"
        return UNMEASURED, f"перепись не измерила: {reason}"

    stamp = report.get("generated_at")
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return UNMEASURED, (f"у отчёта переписи нет читаемой отметки времени "
                            f"(generated_at={stamp!r}) — возраст записи НЕ ИЗМЕРЕН, "
                            f"а старая запись говорит о дереве, которого уже нет")
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    if age > _NO_REGRESSION_MAX_AGE_H:
        return UNMEASURED, (f"запись прогона старше предела: {age:.1f}ч при пределе "
                            f"{_NO_REGRESSION_MAX_AGE_H:.0f}ч — население могло не "
                            f"измениться, а код под ним измениться")

    try:
        live = census.population(root)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, f"население живого дерева не разобрано: {type(exc).__name__}: {exc}"
    if live["unparsed"]:
        return UNMEASURED, (f"{len(live['unparsed'])} тест-файл(ов) живого дерева не "
                            f"разобран(ы) — принадлежность НЕИЗВЕСТНА: "
                            + ", ".join(u["file"] for u in live["unparsed"][:4]))

    surfaces = report.get("surfaces") or {}
    if set(surfaces) != set(live["surfaces"]):
        return UNMEASURED, (f"поверхности отчёта {sorted(surfaces)} разошлись с "
                            f"объявленными {sorted(live['surfaces'])} — отчёт отвечает "
                            f"на другой вопрос")

    failed: list[str] = []
    missing: list[str] = []
    total = 0
    for name, live_surface in live["surfaces"].items():
        got = surfaces.get(name) or {}
        green = set(got.get("files_passed") or [])
        bad = {row.get("file") for row in (got.get("files_failed") or [])}
        unknown = {row.get("file") for row in (got.get("files_unmeasured") or [])}
        if not live_surface["files"]:
            return UNMEASURED, (f"население поверхности {name!r} ПУСТО — сторож без "
                                f"населения зелен по построению, и эта зелень ничего "
                                f"не значит")
        for rel in live_surface["files"]:
            total += 1
            # Порядок проверок — часть меры: отчёт, назвавший один файл сразу в
            # двух корзинах, сам себе противоречит, и молча выбрать из них
            # зелёную значило бы сделать пробу fail-OPEN на испорченной записи.
            where = [bucket for bucket, names in
                     (("упал", bad), ("зелен", green), ("без вердикта", unknown))
                     if rel in names]
            if len(where) > 1:
                missing.append(f"{name}:{rel} (отчёт противоречит сам себе: "
                               f"{', '.join(where)})")
            elif rel in bad:
                failed.append(f"{name}:{rel}")
            elif rel in green:
                continue
            elif rel in unknown:
                missing.append(f"{name}:{rel} (вердикта не получил)")
            else:
                missing.append(f"{name}:{rel} (в отчёте отсутствует — появился "
                               f"после замера)")

    head = (report.get("repo_head") or "дерево не названо")[:9]
    where = " · ".join(
        f"{m.get('hostname') or 'хост не назван'} {m.get('timestamp') or ''}".strip()
        for m in (report.get("records_meta") or [])) or "происхождение записи не названо"
    tail = (f"население {total} тест-файл(ов), запись о {head}, снята на {where}, "
            f"возраст {age:.1f}ч")

    if failed:
        return NOT_SATISFIED, (
            f"существующие тесты объявленных поверхностей НЕ проходят: "
            f"{len(failed)} файл(ов) — " + " · ".join(failed[:6])
            + (" …" if len(failed) > 6 else "") + f"; {tail}")
    if missing:
        return UNMEASURED, (
            f"вердикт получили не все члены населения: {len(missing)} без исхода — "
            + " · ".join(missing[:6]) + (" …" if len(missing) > 6 else "")
            + f"; {tail}")
    return SATISFIED, (f"каждый член населения получил вердикт, и все вердикты "
                       f"зелёные: {tail}")


def _probe_no_single_criterion_probe_on_a_multi_criterion_order(
        arg: str | None, *, tracker_dir: str | None = None,
        repo_root: str | None = None, ref: str = "origin/main") -> tuple[str, str]:
    """Критерий: у МНОГОКРИТЕРИАЛЬНОГО приказа не объявлена проба ОДНОГО критерия.

    Предмет — находка цикла #710
    (`inbox-proba-odnogo-kriteriya-49-obyavlena-na-k`): на карточке стоячего приказа
    `inbox-task-portfolio-cio-dynamic-capital-alloc`, несущего ТРИНАДЦАТЬ критериев
    §49, стояла проба одного из них. После доставки ADR-489 она давала `satisfied`,
    и шаг 0-офис печатал у приказа «КРИТЕРИЙ ВЫПОЛНЕН» — читается это как «приказ
    исполнен», хотя критерии оставались открытыми, да и приказ по инв. #14 не
    закрывается вовсе. Зелёный ответ на СВОЙ вопрос, подписанный именем чужого,
    более широкого.

    Аргумент — ключ карточки (имя файла без `.md`). Меряется ИСХОД: карточка НЕ
    производит вердикта приёмки. Условие этого исхода ровно одно и оно
    структурное — отсутствие `acceptance_probe` во frontmatter, потому что
    :func:`audit` строит строку ровно по нему; связь закреплена отдельным тестом
    (проба не зовёт `audit` сама: `audit` зовёт пробы, и вызов был бы рекурсией).

    **Спрашиваются ОБЕ копии карточки.** Вред жил в ПРОД-дереве, а `nimbalyst-local/`
    туда не синхронизируется (ADR-152): копия на `origin/main` строки не несла
    никогда, и проба, спросившая только origin, объявила бы чистым дерево, где
    вред и находится.

    Три исхода: `satisfied` — ни одна найденная копия пробы не объявляет;
    `not_satisfied` — объявляет (с именем копии); `unmeasured` — карточки не нашли
    ни локально, ни на `ref`, либо чтение `ref` прервалось.
    """
    key = (arg or "").strip()
    if not key:
        return UNMEASURED, "проба требует ключ карточки аргументом"
    name = key if key.endswith(".md") else key + ".md"

    tracker_dir = tracker_dir or os.path.join(REPO_ROOT, TRACKER_REL)
    root = repo_root or _repo_root_for(tracker_dir)

    copies: list[tuple[str, str]] = []
    local = os.path.join(tracker_dir, name)
    if os.path.isfile(local):
        try:
            copies.append((f"дерево {tracker_dir}", open(
                local, encoding="utf-8", errors="replace").read()))
        except OSError as exc:
            return UNMEASURED, f"локальная копия не прочитана: {exc}"

    ref_unmeasured = ""
    if _is_git_repo(root):
        blob = _git(["show", f"{ref}:{TRACKER_REL}/{name}"], repo_root=root)
        if blob is None:
            ref_unmeasured = f"копия на `{ref}` не прочитана"
        else:
            copies.append((ref, blob))

    if not copies:
        return UNMEASURED, (f"карточка {name} не найдена ни локально, ни на `{ref}`"
                            + (f"; {ref_unmeasured}" if ref_unmeasured else ""))

    carrying = [where for where, text in copies
                if (parse_frontmatter(text).get("acceptance_probe") or "").strip()]
    if carrying:
        return NOT_SATISFIED, (
            f"{name}: проба одного критерия объявлена у многокритериального приказа "
            f"в копи(и/ях) " + ", ".join(carrying)
            + " — офис напечатает вердикт одного критерия как вердикт приказа")
    if ref_unmeasured:
        return UNMEASURED, (f"{name}: прочитанные копии чисты, но {ref_unmeasured} — "
                            f"«чисто» и «не измерено» смешивать запрещено")
    return SATISFIED, (f"{name}: ни одна из {len(copies)} копи(и/й) пробы не объявляет "
                       f"— вердикта приёмки у приказа не будет")


#: Предел возраста артефакта переписи «две сессии на одном предмете».
#: 48 ч — ЗАМЕР, а не вкус: производитель `com.spa.decision_loop` ходит раз в
#: 6 ч (`StartInterval` 21600 в его plist), у артефакта объявлен SLO 12 ч, и
#: 48 ч это четыре пропущенных такта. Предел нужен потому, что население
#: (журнал объявлений) растёт каждый день: старая запись говорила бы «квитанции
#: есть у всех» про взятия, которых в ней ещё нет.
_SUBJECT_RECEIPT_MAX_AGE_H = 48.0


def _probe_subject_taking_leaves_a_guard_receipt(
        arg: str | None, *, now: "datetime | None" = None,
        repo_root: str | None = None,
        report: dict | None = None) -> tuple[str, str]:
    """Заказ G38 п. 3: оставляет ли ВЗЯТИЕ предмета квитанцию сторожа захвата.

    Предмет — класс «две сессии на одном предмете» (ADR-413), который лежал
    остатком примерно пятьдесят заказов подряд. Цена класса измерена переписью
    :mod:`spa_core.monitoring.duplicate_subject_census`; закрывается же карточка
    не ценой (она потрачена и задним числом не меняется), а ПРОВОДКОЙ: пока у
    взятия предмета нет наблюдаемого следа обращения к сторожу, ни одно будущее
    столкновение не будет отличимо от передачи.

    Три исхода разведены:

    * `satisfied` — в окне есть взятия, и у каждого есть квитанция;
    * `not_satisfied` — есть взятия без квитанции (это находка);
    * `unmeasured` — артефакта нет / он старше предела / перепись не измерила /
      **в окне нет ни одного взятия**. Последнее — не «чисто»: «у всех взятий
      есть квитанция» при нуле взятий верно ПО ПОСТРОЕНИЮ и ответом не является.

    Часы, корень дерева и сам отчёт — ВХОДЫ, не окружение.
    """
    if (arg or "").strip():
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): предмет — "
                            "порядок взятия работы целиком, пофайловой формы у него нет")
    try:
        from spa_core.monitoring import duplicate_subject_census as census
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"перепись не импортируется: {type(exc).__name__}: {exc}"

    root = repo_root or REPO_ROOT
    rel = os.path.join("data", census.ARTIFACT_NAME)
    if report is None:
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                report = json.load(fh)
        except BaseException as exc:  # noqa: BLE001
            return UNMEASURED, (f"артефакта переписи нет или он не прочитан ({rel}): "
                                f"{type(exc).__name__}: {exc} — порядок взятия работы "
                                f"НЕ НАБЛЮДЁН")
    if not isinstance(report, dict) or not report.get("measured"):
        reason = (report or {}).get("reason") if isinstance(report, dict) else "не словарь"
        return UNMEASURED, f"перепись не измерила: {reason}"

    stamp = report.get("generated_at")
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return UNMEASURED, (f"у артефакта нет читаемой отметки времени "
                            f"(generated_at={stamp!r}) — возраст записи НЕ ИЗМЕРЕН")
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    if age > _SUBJECT_RECEIPT_MAX_AGE_H:
        return UNMEASURED, (f"артефакт старше предела: {age:.1f}ч при пределе "
                            f"{_SUBJECT_RECEIPT_MAX_AGE_H:.0f}ч — за это время в журнале "
                            f"появились взятия, о которых запись не говорит")

    receipts = report.get("receipts")
    if not isinstance(receipts, dict):
        return UNMEASURED, "в артефакте нет раздела `receipts` — проводка не измерена"
    takings = receipts.get("window_takings")
    without = receipts.get("window_takings_without_receipt")
    if not isinstance(takings, int) or not isinstance(without, int):
        return UNMEASURED, ("в артефакте нет чисел взятий — измерено это или нет, "
                            "сказать нечем")
    if takings == 0:
        return UNMEASURED, (f"в окне {receipts.get('window_days')} дн. ни одного взятия "
                            f"предмета: «квитанция есть у всех» верно по построению")
    price = report.get("price") if isinstance(report.get("price"), dict) else {}
    if without > 0:
        return NOT_SATISFIED, (
            f"{without} из {takings} взятий предмета за {receipts.get('window_days')} дн. "
            f"не оставили квитанции сторожа захвата; цена класса на сегодня — "
            f"{price.get('lost_coordinates')} координат(ы), сделанных двумя и более "
            f"сессиями и не доехавших ни до одной, {price.get('sessions_on_lost_coordinates')} "
            f"сессий(я)")
    return SATISFIED, (f"все {takings} взятий предмета за {receipts.get('window_days')} дн. "
                       f"оставили квитанцию сторожа захвата")


#: Такт производителя G17 — ступень `findings_bridge` (6 ч). Предел вдвое
#: шире такта: пропущенный прогон ещё не «не измерено», два подряд — уже да.
_G17_MAX_AGE_H = 12.0


def _probe_g17_subject_state_is_measured(
        arg: str | None, *, now: "datetime | None" = None,
        repo_root: str | None = None,
        report: dict | None = None) -> tuple[str, str]:
    """[ADR-499]: говорит ли прибор G17 о своём ПРЕДМЕТЕ измеренно.

    Предмет прибора — цена схлопывания дня; [ADR-395] снял схлопывание у
    самого ``load_history``, и с 16.09 прибор печатал на живом дереве
    ``UNMEASURED`` «схлопывающих наследников не найдено». За этой строкой
    прятались СРАЗУ ТРИ разных состояния: измеренный пустой класс, спор
    переписи с источником и настоящее «не измерено». Инвариант #17 требует
    их различать.

    Критерий — ИСХОД в живом артефакте, а не наличие кода:

    * `satisfied` — артефакт свеж, раздел ``subject`` называет состояние
      источника ИЗМЕРЕННЫМ, и при пустом населении вердикт этого не скрывает;
    * `not_satisfied` — раздела нет либо пустое население снова объявлено
      неизмеренным (регресс к слитой форме);
    * `unmeasured` — артефакта нет / он старше предела / состояние источника
      само не измерено. «Не измерено» за «чисто» не выдаётся.

    Часы, корень дерева и сам отчёт — ВХОДЫ, не окружение.
    """
    if (arg or "").strip():
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): предмет — "
                            "ответ прибора о самом себе, пофайловой формы у него нет")
    try:
        from spa_core.monitoring import heir_all_rows_price as g17
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"прибор не импортируется: {type(exc).__name__}: {exc}"

    root = repo_root or REPO_ROOT
    rel = os.path.join("data", g17.ARTIFACT)
    if report is None:
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                report = json.load(fh)
        except BaseException as exc:  # noqa: BLE001
            return UNMEASURED, (f"артефакта прибора нет или он не прочитан ({rel}): "
                                f"{type(exc).__name__}: {exc} — про предмет НЕ "
                                f"ИЗМЕРЕНО ничего")
    if not isinstance(report, dict):
        return UNMEASURED, "артефакт прибора не словарь — судить нечем"

    stamp = report.get("generated_at")
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return UNMEASURED, (f"у артефакта нет читаемой отметки времени "
                            f"(generated_at={stamp!r}) — возраст записи НЕ ИЗМЕРЕН")
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    if age > _G17_MAX_AGE_H:
        return UNMEASURED, (f"артефакт старше предела: {age:.1f}ч при пределе "
                            f"{_G17_MAX_AGE_H:.0f}ч — сегодняшнего ответа прибора нет")

    subject = report.get("subject")
    if not isinstance(subject, dict) or not subject.get("state"):
        return NOT_SATISFIED, ("в артефакте нет раздела `subject`: у ИСТОЧНИКА не "
                               "спрашивали, схлопывает ли он день, и молчание "
                               "наследников неотличимо от их отсутствия")
    state = str(subject.get("state"))
    if state == g17.SUBJECT_UNMEASURED:
        return UNMEASURED, (f"состояние источника само не измерено: "
                            f"{subject.get('reason')}")
    if state not in (g17.SUBJECT_COLLAPSES, g17.SUBJECT_NO_COLLAPSE):
        return UNMEASURED, (f"состояние источника названо словом вне закрытого "
                            f"перечня ({state!r}) — что оно значит, сказать нечем")
    status = str(report.get("status"))
    pop = report.get("heirs_population")
    if pop == 0 and status == g17.STATUS_UNMEASURED:
        return NOT_SATISFIED, (
            f"источник измерен ({state}), а пустое население всё равно объявлено "
            f"неизмеренным: {report.get('unmeasured_reason')} — это возврат к "
            f"слитой форме, ради которой писан ADR-499")
    measured = report.get("census_measured")
    unmeasured = report.get("census_unmeasured")
    if not isinstance(measured, int) or not isinstance(unmeasured, int):
        return NOT_SATISFIED, ("разбора переписи в артефакте нет: «наследников "
                               "ноль» напечатан без того, у скольких читателей "
                               "это вообще измерено")
    return SATISFIED, (f"источник измерен: {state}; наследников {pop} при переписи "
                       f"ИЗМЕРЕНО {measured} / НЕ ИЗМЕРЕНО {unmeasured}; вердикт "
                       f"прибора {status}")


def _probe_carried_release_is_one_condition(
        arg: str | None, *, repo_root: str | None = None) -> tuple[str, str]:
    """[ADR-501]: читают ли исполнитель и сторож ОДНУ копию условия `carried_to`.

    Критерий назван ДО работы и НЕ этой сессией: он стоит в теле карточки
    `inbox-hrapovik-priemki-krasen-na-ispravnom-sos`, написанном циклом #627 —
    «зелёный на чистом `origin/main` И красный на карточке с поддельным
    `carried_to`». Проба его лишь МЕХАНИЗИРУЕТ, а не выбирает задним числом.

    Меряется ИСХОД, а не структура: у сторожа спрашивают его собственный вердикт
    на заведомо законном и заведомо поддельном носителе, в одноразовом дереве.
    Подстрокой проба не проходит — вердикты сравниваются как значения.

    * `satisfied` — обе стороны сошлись И обе двери ведут в одну функцию;
    * `not_satisfied` — законный носитель не освобождён, поддельный освобождён,
      либо у исполнителя снова своя редакция условия;
    * `unmeasured` — условие не импортируется (кода нет / сломан): про предмет
      не измерено НИЧЕГО, и за «чисто» это не выдаётся.
    """
    import tempfile
    from pathlib import Path as _P
    try:
        from spa_core.owner_queue.queue import carried_release, set_status
        import spa_core.tests.test_inbox_acceptance_ratchet as _ratchet
    except Exception as exc:  # noqa: BLE001 — отсутствие прибора это третий исход
        return "unmeasured", (f"условие carried_release не импортируется ({exc.__class__.__name__}: "
                              f"{exc}) — про предмет НЕ ИЗМЕРЕНО ничего")

    # 1. Одна ли это функция у обоих читателей — вопрос о ПРОВОДКЕ, не о зелени.
    if _ratchet.carried_release is not carried_release:
        return "not_satisfied", "сторож читает НЕ ту функцию, что исполнитель — снова две копии"
    try:
        import inspect
        if "carried_release(" not in inspect.getsource(set_status):
            return "not_satisfied", "исполнитель завёл свою редакцию условия — возврат к двум копиям"
    except OSError as exc:
        return "unmeasured", f"исходник set_status не прочитан ({exc}) — проводка НЕ ИЗМЕРЕНА"

    # 2. Исход на законном и на поддельном носителе — в одноразовом дереве.
    with tempfile.TemporaryDirectory() as t:
        tmp = _P(t)
        tracker = tmp / "nimbalyst-local" / "tracker"
        tracker.mkdir(parents=True)
        card = tracker / "inbox-nositel.md"
        card.write_text("---\nstatus: done\n---\n", encoding="utf-8")
        (tracker / "inbox-cel.md").write_text("цель", encoding="utf-8")
        legit, _ = carried_release("nimbalyst-local/tracker/inbox-cel.md", card,
                                   repo_root=tmp, tracker_dir=tracker)
        fake, why = carried_release("nimbalyst-local/tracker/net-takoi.md", card,
                                    repo_root=tmp, tracker_dir=tracker)
        itself, _ = carried_release(card, card, repo_root=tmp, tracker_dir=tracker)
    if legit is None:
        return "not_satisfied", "законный носитель НЕ освобождён — условие строже правила"
    if fake is not None:
        return "not_satisfied", "обещанный путь освободил носителя — это опт-аут, а не приёмка"
    if itself is not None:
        return "not_satisfied", "карточка освободила сама себя — тавтологичное освобождение"
    return "satisfied", ("одна копия условия у исполнителя и сторожа; законный носитель "
                         f"освобождён, обещанный отклонён ({why[:60]}…), тавтологичный отклонён")


def _probe_research_evidence_tail_closed(arg: str | None, *, now: "datetime | None" = None) -> tuple[str, str]:
    """Критерий карточки `inbox-hvost-adr-564-…`: пять дефектов фабрики исследований, названных
    повторным разбором ADR-564, закрыты — по ИСХОДУ, на настоящем коде, в одноразовом каталоге.

    Шесть сцен, каждая — своё звено (имя звена в вердикте):
    1. `lapse_period` (N4): допущенный кандидат с засчитанным наблюдением ЭТОГО прогона, затем
       настоящий `run._route_sherlock_outcome` с не-ADMIT в тот же момент ⇒ период этого прогона
       НЕ засчитан (`forward.forward_periods` не вырос);
    2. `reviewer_allow_list`: запись проверки от имени, которого нет в
       `evidence_contract.FACT_REVIEWERS`, с ВЕРНЫМ хэшем ⇒ факт непригоден;
    3. `observed_role_binding`: OBSERVED для `custodian` по цитате `bytecode` ⇒ отказ; по `balance` ⇒ принят;
    4. `initial_url_normalised`: `https://usyc.hashnote.com/api/../admin` ⇒ отказ ДО обращения к транспорту;
    5. `effective_until`: факт с `effective_until` в прошлом относительно `now` ⇒ не годен на `now`;
       у факта без поля хэш содержимого не зависит от появления поля в контракте;
    6. `contract_computed_return`: ставка LENDING из `chain:` + перекрёстная проверка API протокола ⇒ STRONG;
       та же пара у TOKENISED_TREASURY ⇒ не STRONG.

    Время — вход (`now`); живое `data/` и сеть не трогаются."""
    import json as _json
    import shutil
    import tempfile
    from datetime import timedelta
    from pathlib import Path as _Path

    t0 = now or datetime.now(timezone.utc)
    broken: list[str] = []
    root = tempfile.mkdtemp(prefix="spa_evidence_tail_probe_")
    try:
        from spa_core.research_factory import (contract as c1, evidence_contract as ec, forward,
                                               grades, http_client, lifecycle, registry_loader)
        from spa_core.research_factory import failure_matrix_v2 as fm2
        from spa_core.research_factory import run as rf_run
        from spa_core.research_factory import bundle as bundle_mod

        # 1. lapse_period
        tmp = _Path(root) / "lapse"
        tmp.mkdir()
        cand = fm2._base_candidate()
        cid = cand["candidate_id"]
        fm2._admit_to_paper_active_v2(tmp, cand, t0)
        # a period confirmed by a COMPLETED run (a run row after it) — must survive the pause below
        t_conf = t0 + timedelta(minutes=30)
        forward.record(tmp, cid, {"period": "p0", "backfill": False, "realised_index": None,
                                  "observed_return": c1.cell(c1.MEASURED, 0.05, source_ref="probe",
                                                             source_class=c1.PRIMARY_PROTOCOL,
                                                             source_root="chain:1", as_of=t_conf.isoformat(),
                                                             now=t_conf)}, t_conf)
        from spa_core.research_factory._common import iso as _iso, ledger_for as _ledger_for
        _ledger_for(tmp).append_idempotent("run", ["run", _iso(t_conf)], {"generated_at": _iso(t_conf)},
                                           _iso(t_conf))
        t1 = t0 + timedelta(hours=1)
        forward.record(tmp, cid, {"period": "p1", "backfill": False, "realised_index": None,
                                  "observed_return": c1.cell(c1.MEASURED, 0.05, source_ref="probe",
                                                             source_class=c1.PRIMARY_PROTOCOL,
                                                             source_root="chain:1", as_of=t1.isoformat(),
                                                             now=t1)}, t1)
        before = forward.forward_periods(tmp, cid)
        b = bundle_mod.latest_bundle(tmp, cid)
        # the review happens at a LATER moment than the recording (re-review M1: a run that crashed between
        # recording and review is re-run later) — the unconfirmed period must still be voided
        t2 = t0 + timedelta(hours=2)
        rf_run._route_sherlock_outcome(tmp, cid, cand, lifecycle.current_state(tmp, cid), b, b,
                                       {"decision": ec.NEEDS_MORE_EVIDENCE, "rationale": ["probe: evidence lapsed"],
                                        "failed_gates": ["fees_measured"], "unknowns": []}, False, t2)
        after = forward.forward_periods(tmp, cid)
        if not (before >= 2 and after == before - 1):
            broken.append(f"lapse_period(before={before}, after={after})")

        # 2. reviewer_allow_list
        reg = _Path(root) / "reg"
        (reg / "fact_reviews").mkdir(parents=True)
        fact = {"schema": ec.SCHEMA_FACT, "fact_id": "f1", "entity": "X", "candidate_ids": ["c1"], "role": None,
                "claim_type": "fee", "value": 1.0, "origin": "issuer:acme", "channel": ec.CHANNEL_OFFICIAL_API,
                "ref": "https://acme.example/page", "quote": None, "retrieved_at": t0.isoformat(),
                "effective_from": None, "page_sha256": None, "fact_sha256": None, "curated_by": "curator-a",
                "reviewed_by": "probe-unlisted-reviewer", "supersedes": None, "expires_at": None,
                "subject_to_change": False}
        fact["fact_sha256"] = ec.fact_content_sha256(fact)
        (reg / "facts.jsonl").write_text(_json.dumps(fact) + "\n")
        (reg / "fact_reviews" / "r.json").write_text(_json.dumps({
            "schema": ec.SCHEMA_FACT_REVIEW, "reviewer": "probe-unlisted-reviewer", "reviewed_at": t0.isoformat(),
            "facts": [{"fact_id": "f1", "fact_sha256": fact["fact_sha256"], "verdict": "CONFIRMED",
                       "method": "probe", "evidence": "probe", "issue": None}]}))
        usable = registry_loader.load_facts(reg / "facts.jsonl",
                                            origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}})
        if usable:
            broken.append("reviewer_allow_list(unlisted reviewer accepted)")

        # 3. observed_role_binding
        def _obs(claim):
            cit = ec.citation(origin="chain:1", channel=ec.CHANNEL_ON_CHAIN, ref=f"chain:1:0x00:{claim}",
                              retrieved_at=t0.isoformat(), claim_type=claim)
            return ec.role_entry(ec.CP_OBSERVED, role="custodian", identity="Probe Custody", citations=[cit],
                                 registry={"chain:1": {"group": "onchain"}})
        try:
            _obs("bytecode")
            broken.append("observed_role_binding(bytecode made a custodian OBSERVED)")
        except ValueError:
            pass
        try:
            _obs("balance")
        except ValueError as exc:
            broken.append(f"observed_role_binding(balance refused: {str(exc)[:60]})")
        try:  # re-review M4: an issuer POSTING on-chain is the issuer speaking, never a chain observation
            ec.role_entry(ec.CP_OBSERVED, role="custodian", identity="Probe Custody", citations=[
                ec.citation(origin="issuer:probe", channel=ec.CHANNEL_ON_CHAIN, ref="chain:1:0x00:probe",
                            retrieved_at=t0.isoformat(), claim_type="balance")],
                registry={"issuer:probe": {"group": "probe_issuer"}})
            broken.append("observed_role_binding(issuer on-chain posting made a custodian OBSERVED)")
        except ValueError:
            pass

        # 4. initial_url_normalised
        calls = []

        def _transport(request, timeout_s):
            calls.append(request)
            raise OSError("probe transport — never a real socket")
        try:
            http_client.fetch("https://usyc.hashnote.com/api/../admin", now=t0, transport=_transport)
            broken.append("initial_url_normalised(fetch returned)")
        except http_client.HttpRefused:
            if calls:
                broken.append("initial_url_normalised(transport reached before refusal)")
        except Exception as exc:  # noqa: BLE001 — anything but a refusal BEFORE the transport is a broken link
            broken.append(f"initial_url_normalised({type(exc).__name__}, transport_calls={len(calls)})")

        # 5. effective_until
        # re-review M2: recompute the hash INDEPENDENTLY over the required fields only — a fact without the
        # optional field must hash exactly as it did before the field existed in the contract
        import hashlib as _hashlib
        body = {k: fact[k] for k in ec.FACT_FIELDS if k not in ec.FACT_HASH_EXCLUDED_FIELDS}
        independent = _hashlib.sha256(_json.dumps(body, sort_keys=True, separators=(",", ":"),
                                                  ensure_ascii=False).encode("utf-8")).hexdigest()
        ended = dict(fact, effective_until=(t0 - timedelta(days=1)).isoformat())
        if ec.fact_content_sha256(fact) != independent:
            broken.append("effective_until(hash of a fact without the field changed)")
        if registry_loader.facts_for([ended], "c1", now=t0):
            broken.append("effective_until(ended fact still usable)")

        # 6. contract_computed_return
        greg = {"chain:1": {"group": "onchain"}, "issuer:proto": {"group": "proto"}}
        v2 = {"return_family": "rate", "return_last_change_at": t0.isoformat(), "return_primary_origin": "chain:1",
              "return_cross_checks": [{"origin": "issuer:proto", "value": 0.05}]}
        cand_rate = {"base_return": c1.cell(c1.MEASURED, 0.05, source_ref="probe", source_class=c1.PRIMARY_CHAIN,
                                             source_root="chain:1", as_of=t0.isoformat(), now=t0)}
        lend = grades.grade_return(cand_rate, "LENDING", v2, t0, registry=greg)
        tsy = grades.grade_return(cand_rate, "TOKENISED_TREASURY", v2, t0, registry=greg)
        if lend != ec.STRONG or tsy == ec.STRONG:
            broken.append(f"contract_computed_return(LENDING={lend}, TOKENISED_TREASURY={tsy})")
    except Exception as exc:  # noqa: BLE001 — a scene that cannot even run is NOT MEASURED, named
        return UNMEASURED, f"сцена не исполнилась: {type(exc).__name__}: {str(exc)[:160]}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if broken:
        return NOT_SATISFIED, "разорваны звенья: " + "; ".join(broken)
    return SATISFIED, ("хвост ADR-564 закрыт: период дня истечения не засчитан; непрописанный проверяющий "
                       "отвергнут; OBSERVED связан с ролью; начальный URL нормализуется; effective_until "
                       "действует; вычисленная контрактом ставка независима")


def _probe_curated_facts_usable(arg: str | None, *, facts_path: "str | None" = None) -> tuple[str, str]:
    """Критерий: каждый НАЗВАННЫЙ курируемый факт (`arg` = id через `+`) ГОДЕН как доказательство —
    по исходу, настоящим загрузчиком `research_factory.registry_loader.load_facts` (независимая проверка,
    привязанная к хэшу содержимого; издатель ссылки совпадает с источником; не истёк). Не «строка есть в
    файле»: факт без записи проверяющего, с правкой после проверки или с чужим хостом — не годен, и
    причина отказа загрузчика названа. Сравнение id — точное, не подстрокой."""
    if not arg:
        return UNMEASURED, "не названо ни одного id факта (arg пуст)"
    wanted = [w for w in arg.split("+") if w]
    try:
        from pathlib import Path as _Path
        from spa_core.research_factory import registry_loader
        path = _Path(facts_path) if facts_path else None
        refused: list = []
        usable = registry_loader.load_facts(path, origins=registry_loader.load_origins(), refused_out=refused)
    except Exception as exc:  # noqa: BLE001 — a registry that cannot be loaded is NOT MEASURED, named
        return UNMEASURED, f"реестр фактов не загрузился: {type(exc).__name__}: {str(exc)[:160]}"
    usable_ids = {f.get("fact_id") for f in usable}
    refused_by_id = {r.get("fact_id"): r.get("reason") for r in refused}
    # range form `fact-043..fact-055` (an id list outgrows the 128-char argument): EVERY index in the range
    # must exist as exactly one fact — a gap or a duplicate is named, never skipped
    import re as _re
    rng = _re.fullmatch(r"fact-(\d{3})\.\.fact-(\d{3})", arg)
    if rng:
        lo, hi = int(rng.group(1)), int(rng.group(2))
        if lo > hi:
            return UNMEASURED, f"диапазон {arg!r} пуст"
        all_ids = usable_ids | set(refused_by_id)
        wanted = []
        for n in range(lo, hi + 1):
            hits = sorted(i for i in all_ids if i and i.startswith(f"fact-{n:03d}-"))
            wanted.extend(hits if len(hits) == 1 else [f"fact-{n:03d}-<{len(hits)} в реестре>"])
    missing = []
    for fid in wanted:
        if fid in usable_ids:
            continue
        if fid in refused_by_id:
            missing.append(f"{fid}: {str(refused_by_id[fid])[:90]}")
        else:
            missing.append(f"{fid}: нет в реестре")
    if missing:
        return NOT_SATISFIED, "не годны: " + "; ".join(missing)
    return SATISFIED, f"годны все {len(wanted)} названных фактов (проверены независимо, привязаны к содержимому)"


PROBES: dict[str, Callable[[str | None], "tuple[str, str]"]] = {
    "carried_release_is_one_condition": _probe_carried_release_is_one_condition,
    "contract_manifest_parity_agrees": _probe_contract_manifest_parity,
    "artifact_contract_confirmed": _probe_artifact_contract,
    "lead_channel_wiring_ok": _probe_lead_channel_wiring,
    "adapter_status_live_apy": _probe_adapter_status_live_apy,
    "tier_promotion_loop_closed": _probe_tier_promotion_loop,
    "candidate_discovery_loop_closed": _probe_candidate_discovery_loop,
    "free_move_priced_as_free": _probe_free_move_priced_as_free,
    "decision_journal_keeps_every_run": _probe_decision_journal_keeps_every_run,
    "absent_observation_class_closed": _probe_absent_observation_class_closed,
    "second_artifact_tvl_agrees": _probe_second_artifact_tvl_agrees,
    "economics_net_return_dominates_keep":
        _probe_economics_net_return_dominates_keep,
    "persistence_advantage_outlives_horizon":
        _probe_persistence_advantage_outlives_horizon,
    "risk_policy_unbypassable_in_executed_states":
        _probe_risk_policy_unbypassable_in_executed_states,
    "book_does_not_oscillate_between_opportunities":
        _probe_book_does_not_oscillate_between_opportunities,
    "trade_is_rechecked_immediately_before_execution":
        _probe_trade_is_rechecked_immediately_before_execution,
    "earn_defi_own_realized_price_reconciles": _probe_earn_defi_own_realized_price,
    "journal_reader_census_reaches_http_routes":
        _probe_journal_reader_census_reaches_http_routes,
    "journal_reader_census_verdict_under_injected_clock":
        _probe_journal_reader_census_verdict_under_injected_clock,
    "card_copies_agree": _probe_card_copies_agree,
    "named_cards_closed_at_origin": _probe_named_cards_closed_at_origin,
    "forbidden_import_gate_single_instrument":
        _probe_forbidden_import_gate_single_instrument,
    "ci_main_verdict_green": _probe_ci_main_verdict_green,
    "pr_work_arrived_on_main": _probe_pr_work_arrived_on_main,
    "owner_visibility_numbers_delivered":
        _probe_owner_visibility_numbers_delivered,
    "portfolio_decision_owner_covers_capital":
        _probe_portfolio_decision_owner_covers_capital,
    "no_single_criterion_probe_on_a_multi_criterion_order":
        _probe_no_single_criterion_probe_on_a_multi_criterion_order,
    "costs_are_accounted_for_in_the_decision":
        _probe_costs_are_accounted_for_in_the_decision,
    "marginal_return_size_changes_expected_yield":
        _probe_marginal_return_size_changes_expected_yield,
    "determinism_recomputation_is_reproducible":
        _probe_determinism_recomputation_is_reproducible,
    "no_regression_tests_pass": _probe_no_regression_tests_pass,
    "g17_subject_state_is_measured": _probe_g17_subject_state_is_measured,
    "subject_taking_leaves_a_guard_receipt":
        _probe_subject_taking_leaves_a_guard_receipt,
    "research_evidence_tail_closed": _probe_research_evidence_tail_closed,
    "curated_facts_usable": _probe_curated_facts_usable,
}


# --- Объявление предмета: какая проба меряет какой критерий §49 приказа CIO ------
#
# Объявление лежит У САМОЙ ПРОБЫ (атрибут функции), а не в отдельном списке рядом.
# Список рядом разъехался бы с реестром МОЛЧА: пробу переименовали бы, а строка в
# списке продолжала бы указывать на старое имя и читалась бы как «критерий измерен».
# Атрибут переезжает вместе с телом пробы, потому что он и есть часть тела.
#
# Объявление — НЕ доказательство. Оно говорит «эта проба претендует мерить этот
# критерий»; правда ли она его мерит, решает её собственный контроль в обе стороны
# (`.claude/rules/acceptance.md`, п. 3). Сводный замер (`scripts/cio_acceptance_rollup.py`)
# сверяет имя критерия с населением, прочитанным из §49 САМОЙ карточки приказа, —
# объявление, указывающее мимо населения, становится находкой, а не тихим нулём.
_probe_portfolio_decision_owner_covers_capital.s49_criterion = "Architecture"
_probe_economics_net_return_dominates_keep.s49_criterion = "Economics"
_probe_persistence_advantage_outlives_horizon.s49_criterion = "Persistence"
_probe_risk_policy_unbypassable_in_executed_states.s49_criterion = "Risk"
_probe_book_does_not_oscillate_between_opportunities.s49_criterion = "Anti-churn"
_probe_trade_is_rechecked_immediately_before_execution.s49_criterion = "Pre-trade safety"
_probe_costs_are_accounted_for_in_the_decision.s49_criterion = "Costs"
_probe_marginal_return_size_changes_expected_yield.s49_criterion = "Marginal return"
_probe_determinism_recomputation_is_reproducible.s49_criterion = "Determinism"
_probe_owner_visibility_numbers_delivered.s49_criterion = "Owner visibility"
_probe_no_regression_tests_pass.s49_criterion = "No regression"


def probes_by_s49_criterion() -> dict:
    """Какие зарегистрированные пробы объявляют себя мерой критерия §49.

    Возврат: критерий → **СПИСОК** имён проб. Список, а не имя: две пробы, объявившие
    один критерий, есть столкновение объявлений, и выбрать из них одну молча значило бы
    спрятать его. Разрешает столкновение читатель, а не эта функция.

    Обходится РЕЕСТР (`PROBES`), а не модуль: проба, потерявшая регистрацию, измерять
    уже ничего не может, и считать её объявление действующим значило бы записать
    критерий в измеренные по мёртвой ссылке.
    """
    out: dict = {}
    for name, fn in PROBES.items():
        crit = getattr(fn, "s49_criterion", None)
        if isinstance(crit, str) and crit.strip():
            out.setdefault(crit.strip(), []).append(name)
    return {k: sorted(v) for k, v in sorted(out.items())}


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


#: Входы, которыми пробе можно указать ЧУЖОЕ дерево вместо своего.
#:
#: `tracker_dir` добавлен циклом #755 (заказ G92 п. 1, ADR-542). До него проба,
#: читающая КАРТОЧКИ, объявляла свою зависимость от дерева только параметром в
#: сигнатуре — и этого объявления не видел никто: :func:`probe_tree_inputs`
#: отвечала про `card_copies_agree` пустым кортежем, то есть «дерева не
#: принимает», хотя дерево для неё и есть предмет. Замер того же цикла:
#: `orchestrator_queue.py probe` писал пробу в карточку одного дерева и в
#: следующей строке печатал вердикт о другом — «карточки нет ни в дереве», о
#: карточке, которую сам только что создал.
PROBE_TREE_INPUTS = ("repo_root", "data_dir", "tracker_dir")


def probe_tree_inputs(name: str) -> tuple:
    """Какие из :data:`PROBE_TREE_INPUTS` проба `name` принимает ВХОДОМ.

    Существует затем, чтобы читатель `run_probe(..., repo_root=…, data_dir=…)` мог
    напечатать ПРАВДУ о том, дошло ли до пробы чужое дерево. Проб, читающих своё
    дерево жёстко, в реестре большинство; позвать такую с чужим деревом и промолчать
    значило бы выдать вердикт об ОДНОМ дереве за вердикт о другом — ровно та
    «половина инъекции», про которую написано в `.claude/rules/deployment.md`.

    Возврат — кортеж принятых имён (пустой, если проба не принимает ни одного или
    имя не зарегистрировано). Пустота здесь не ошибка, а ответ.
    """
    fn = PROBES.get((name or "").strip())
    if fn is None:
        return ()
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return ()
    return tuple(p for p in PROBE_TREE_INPUTS if p in params)


def run_probe(spec: str, *, repo_root: str | None = None,
              data_dir: str | None = None,
              tracker_dir: str | None = None) -> tuple[str, str]:
    """Исполнить пробу по её ОБЪЯВЛЕНИЮ. Возврат — (вердикт, пояснение).

    Fail-CLOSED в обе стороны: незнакомое имя, кривой аргумент и любое исключение
    внутри пробы дают `unmeasured`, а не `not_satisfied` (не находка) и тем более
    не `satisfied` (не разрешение закрыть карточку).

    `repo_root`, `data_dir` и `tracker_dir` доходят ТОЛЬКО до тех проб, которые
    объявили их входом; остальные читают своё дерево. Узнать, что именно дошло, —
    :func:`probe_tree_inputs`; спрашивать обязан читатель, потому что молчание
    здесь неотличимо от ответа.

    `tracker_dir` — каталог КАРТОЧЕК, и он отдельный вход, а не производная от
    `repo_root`: у пробы, читающей обе копии карточки, дверей к дереву ДВЕ
    (локальный файл берётся по `tracker_dir`, копия на `ref` — через git в
    `repo_root`), и провести одну, оставив вторую на умолчании, значило бы собрать
    один вердикт из двух деревьев — та самая «половина инъекции»
    (`.claude/rules/deployment.md`).
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
    offered = {"repo_root": repo_root, "data_dir": data_dir,
               "tracker_dir": tracker_dir}
    accepted = probe_tree_inputs(name)
    kw = {k: v for k, v in offered.items() if v and k in accepted}
    try:
        verdict, detail = fn(arg, **kw)
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


def _tracker_comparison_tautological(root: str, card_path: str,
                                     ref_sha: str) -> tuple[bool | None, str]:
    """Сравнение каталога карточек с `ref` ТАВТОЛОГИЧНО? Третий исход — `None`.

    ЗАЧЕМ. Проба `card_copies_agree` спрашивает «нет ли у карточки закрытия,
    которое существует только здесь». Ответ «нет» бывает ДВУХ разных родов, и до
    ADR-504 они выглядели одинаково:

    * **наблюдение** — копии сверили и они правда сошлись (так отвечает прод-дерево,
      чей `HEAD` по построению отстаёт от `origin/main`);
    * **свойство дерева** — сверять было нечего. Когда `HEAD` И ЕСТЬ `ref`, а в
      каталоге трекера нет незакоммиченных правок, содержимое дерева совпадает с
      `ref` побайтово ПО ПОСТРОЕНИЮ, и ни один из пяти классов расхождения
      (`stale`/`diverged`/`hidden`/`undelivered`/`deleted_on_origin`) физически не
      может сработать НИ ДЛЯ ОДНОЙ карточки. Пустая находка тогда не говорит о
      карточке ничего.

    Замер 29.09 (цикл #722), ради которого функция и написана: из worktree на чистом
    `fd3a509a5` проба отвечала `satisfied` «копии сошлись» про тот самый стоячий
    приказ владельца, чьи копии в проде РАСХОДЯТСЯ, — зелёный, гарантированный
    независимо от предмета. Прежняя редакция называла эту опасность прозой в
    docstring и печатала дерево с ref в `detail`, но вердиктом оставляла «выполнено»;
    названная в тексте ловушка вердиктом не становится (инв. #17).

    ГРАНУЛЯРНОСТЬ — ПОКАРТОЧНАЯ, и это не стилистика. Предмет пробы — ОДНА
    названная карточка, поэтому спрашивать надо про её файл, а не про каталог:
    при грязном каталоге и чистой спрошенной карточке сверка тавтологична ИМЕННО
    для неё, а вопрос «есть ли в каталоге хоть одна правка» ответил бы
    «содержательно» и вернул бы тот самый зелёный, ради которого всё написано.
    Мерка по каталогу отказывает ШИРЕ там, где не надо, и МОЛЧИТ там, где надо.

    Различать «не установлено» и «не тавтологично» обязательно: `git`, который не
    ответил, — не разрешение считать сравнение содержательным.
    """
    if not ref_sha:
        return None, "sha ref не прочитан"
    head_out = _git(["rev-parse", "HEAD"], repo_root=root)
    if head_out is None:
        return None, "HEAD дерева не прочитан"
    head = head_out.strip()
    if not head:
        return None, "HEAD дерева пуст (репозиторий без коммитов?)"
    if head != ref_sha:
        return False, f"HEAD {head[:9]} != ref {ref_sha[:9]} — сравнение содержательно"
    dirty = _git(["status", "--porcelain", "--", card_path], repo_root=root)
    if dirty is None:
        return None, f"состояние файла {card_path} не прочитано"
    if [ln for ln in dirty.splitlines() if ln.strip()]:
        return False, (f"HEAD и ref суть один коммит {head[:9]}, но копия карточки в дереве "
                       f"правлена и не закоммичена — сравнение содержательно")
    return True, (f"HEAD и ref суть один коммит {head[:9]}, а копия карточки в дереве не "
                  f"правлена: она сверяется САМА С СОБОЙ, и «сошлись» вышло бы при любом "
                  f"предмете")


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
                # Каталог карточек и дерево ДОХОДЯТ до пробы (заказ G92 п. 1,
                # ADR-542). `audit` их знает — он только что прочитал карточку
                # именно отсюда, — и не передать их значило бы вынести вердикт о
                # дереве, в котором лежит МОДУЛЬ, под заголовком про дерево,
                # которое назвал читатель. Карточка `from_origin` при этом своего
                # файла в `tracker_dir` не имеет; проба отвечает об этом ТРЕТЬИМ
                # исходом («карточки нет ни в дереве, ни среди разошедшихся»), и
                # это верно: читать её локальную копию действительно негде.
                verdict, detail = run_probe(spec, tracker_dir=tracker_dir,
                                            repo_root=repo_root)
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
