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

from spa_core.utils.errors import SPAError
from spa_core.utils.observation import observed
from spa_core.utils.server_ref import one_pin_per_report, pin_server_ref

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


def _probe_owner_protocols_report_carries_every_record(
    arg: str | None,
    *,
    data_dir: str | None = None,
    now: "datetime | None" = None,
) -> tuple[str, str]:
    """Критерий: отчёт владельцу `/protocols` несёт КАЖДУЮ запись артефакта.

    Предмет — карточка `inbox-otchet-vladeltsu-protocols-pokazyvaet-2` и заказ
    **G709 п. 1** приказа `inbox-task-portfolio-cio-dynamic-capital-alloc`:
    «читатель обязан принимать и словарь, и список, а третий исход (раздел не
    той формы вовсе) остаться различимым». Замер 2026-10-12 (ADR-709): отчёт
    показывал **2 записи из 36**, потому что `_get_all_adapters` обходил
    `data["adapters"]` как СПИСОК, а живой артефакт несёт раздел СЛОВАРЁМ.

    **Меряется ИСХОД, а не структура.** Проба не спрашивает «принимает ли
    читатель словарь» — на этот вопрос можно ответить взглядом в код, и ровно
    такой взгляд три недели давал «да» у `unparsed_adapter_entries`, пока отчёт
    ронял всё. Она зовёт НАСТОЯЩИЙ `format_protocols_message` и считает строки
    протоколов в его выдаче.

    **Знаменатель независим от читателя — в этом вся проба.** Сколько записей
    ДОЛЖНО быть, считается здесь по сырому JSON (члены-записи раздела плюс
    легаси-блоки верхнего уровня без современного близнеца), а НЕ вызовом
    `_get_all_adapters`. Знаменатель, взятый у измеряемого читателя, равен
    числителю по построению: такая проба зелена и на полностью сломанном
    читателе — она сравнивает его с собой.

    **Подстрокой проба не проходит (ADR-333):** вердикт считается по ЧИСЛАМ,
    ни одна ветка не ищет текст в сообщении.

    Три исхода РАЗЛИЧИМЫ (инв. #17): артефакта нет / он не разобран / он протух
    (порог `ADAPTER_STATUS_MAX_AGE_H`, тот же, что у `adapter_status_live_apy`,
    и по той же причине — `data/` частично лежит в git, поэтому в worktree и на
    CI это ЗАМОРОЖЕННЫЙ канон, а не наблюдение) ⇒ `unmeasured`, НИКОГДА
    `not_satisfied`. Время — вход (`now`), каталог — вход (`data_dir`).
    """
    root = data_dir or os.path.join(REPO_ROOT, "data")
    path = os.path.join(root, "adapter_status.json")
    rel = os.path.relpath(path, REPO_ROOT) if path.startswith(REPO_ROOT) else path
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
        return UNMEASURED, (
            f"{rel} протух: возраст {age_h:.1f}ч при пределе "
            f"{ADAPTER_STATUS_MAX_AGE_H:.0f}ч (замороженный канон, не наблюдение) — "
            f"мерить надо из дерева с живым data/"
        )

    # ── знаменатель: СЫРОЙ артефакт, без участия измеряемого читателя ──────
    section = doc.get("adapters")
    if isinstance(section, dict):
        members: list[object] = list(section.values())
        section_ids = {
            str(k).strip().lower().replace("-", "_")
            for k, v in section.items()
            if isinstance(v, dict)
        }
    elif isinstance(section, list):
        members = list(section)
        section_ids = {
            str(
                v.get("protocol_key") or v.get("adapter_id") or v.get("name") or ""
            ).strip().lower().replace("-", "_")
            for v in section
            if isinstance(v, dict)
        }
    else:
        return UNMEASURED, (
            f"{rel}: раздел `adapters` не той формы вовсе "
            f"({type(section).__name__}) — население не измерено"
        )

    section_records = [m for m in members if isinstance(m, dict)]
    dropped = len(members) - len(section_records)

    legacy_ids: set[str] = set()
    for key, value in doc.items():
        if key == "adapters" or not isinstance(value, dict):
            continue
        if "tier" not in value and "apy" not in value and "apy_pct" not in value:
            continue
        ident = str(
            value.get("adapter_id") or value.get("protocol_key") or key
        ).strip().lower().replace("-", "_")
        if ident not in section_ids:
            legacy_ids.add(ident)
    expected = len(section_records) + len(legacy_ids)

    # ── числитель: НАСТОЯЩИЙ отчёт владельцу ──────────────────────────────
    try:
        from spa_core import telegram_protocols_reporter as reporter
    except ImportError as exc:  # pragma: no cover - модуль в дереве есть
        return UNMEASURED, f"читатель отчёта не ввезён: {type(exc).__name__}: {exc}"
    try:
        message = reporter.format_protocols_message(doc)
    except Exception as exc:  # noqa: BLE001 - вердикт обязан быть третьим исходом
        return UNMEASURED, (
            f"{reporter.__name__}.format_protocols_message упал: "
            f"{type(exc).__name__}: {exc} — отчёт не измерен"
        )
    shown = sum(1 for line in str(message).splitlines() if line.startswith("•"))

    detail = (
        f"{rel} (возраст {age_h:.1f}ч): записей раздела {len(section_records)} + "
        f"легаси без близнеца {len(legacy_ids)} = ждём {expected}; "
        f"отчёт печатает {shown}; уронено разделом {dropped}"
    )
    if dropped:
        return NOT_SATISFIED, (
            f"{detail} — члены раздела, не являющиеся записями, не доходят до владельца"
        )
    if shown != expected:
        return NOT_SATISFIED, (
            f"{detail} — отчёт владельцу теряет {expected - shown} запис(ей)"
            if shown < expected
            else f"{detail} — отчёт владельцу печатает лишние {shown - expected} строк(и)"
        )
    return SATISFIED, detail


def _live_adapter_status_for_the_door(
    now: "datetime | None", data_dir: str | None
) -> "tuple[dict, float, str] | tuple[None, None, str]":
    """Живой `adapter_status.json` под тем же возрастным гейтом, что у соседней пробы.

    Общей здесь сделана РУЧКА (`ADAPTER_STATUS_MAX_AGE_H`) — она и была одной копией
    до сегодня. Текст отказа у соседа (`_probe_owner_protocols_report_carries_every_record`)
    оставлен его собственным НАМЕРЕННО: его батарея пинит формулировки дословно, и
    переписать их прицепом к чужой правке значило бы менять чужой тест без своего
    обоснования (инв. #16). Разъехаться эти копии не могут молча в том, что решает
    вердикт: порог — одна константа на обе.

    Возврат: ``(doc, age_h, rel)`` когда артефакт жив, иначе ``(None, None, причина)``.
    """
    root = data_dir or os.path.join(REPO_ROOT, "data")
    path = os.path.join(root, "adapter_status.json")
    rel = os.path.relpath(path, REPO_ROOT) if path.startswith(REPO_ROOT) else path
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None, None, f"{rel} нет в этом дереве — предмет не измерен"
    except (OSError, ValueError) as exc:
        return None, None, f"{rel} не разобран: {type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return None, None, f"форма {rel} не разобрана ({type(doc).__name__})"
    stamp = doc.get("generated_at")
    if not stamp:
        return None, None, f"{rel} без generated_at — возраст не измерен, судить нечем"
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None, None, f"{rel}: generated_at {stamp!r} не разобран — возраст не измерен"
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age_h = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    if age_h > ADAPTER_STATUS_MAX_AGE_H:
        return None, None, (
            f"{rel} протух: возраст {age_h:.1f}ч при пределе "
            f"{ADAPTER_STATUS_MAX_AGE_H:.0f}ч (замороженный канон, не наблюдение) — "
            f"мерить надо из дерева с живым data/"
        )
    return doc, age_h, rel


#: Потолок раздувания синтетического артефакта в испытании населением. Нужен не
#: ради скорости, а ради ТРЕТЬЕГО ИСХОДА: если за столько удвоений сообщение так и
#: не перешагнуло предел одного сообщения, предпосылка испытания НЕ ОБЕСПЕЧЕНА, и
#: сказать об этом надо вслух, а не судить по неразогнанному входу.
_DOOR_STRESS_ROUNDS = 24


def _grown_adapter_doc(doc: dict, reporter) -> "tuple[dict | None, int, str]":
    """Копия артефакта, раздутая до сообщения, которое НЕ влезает в одно сообщение.

    Зачем вообще раздувать. Сегодняшний отчёт — 2501 символ, то есть один кусок, и
    дверь, которая УСЕКАЕТ вместо деления, на нём зелена. Ровно так и выглядела
    латентность, названная ADR-710: «сегодня не видно» ≠ «нет». Испытание подаёт
    двери население, при котором разница между делением и усечением НАБЛЮДАЕМА.

    Население растёт КОПИЯМИ живых записей под НОВЫМИ ключами раздела: ключ и есть
    последняя личность записи (`_adapter_section_records`), поэтому копии не
    сливаются дедупликацией, а сами числа остаются теми же — испытание меряет
    ДВЕРЬ, а не пересчитывает ставки.
    """
    section = doc.get("adapters")
    base = dict(section) if isinstance(section, dict) else {}
    if not base:
        return None, 0, "в живом артефакте нет раздела `adapters` словарём — раздувать нечего"
    grown = dict(doc)
    adapters: dict = dict(base)
    for round_no in range(1, _DOOR_STRESS_ROUNDS + 1):
        grown["adapters"] = adapters
        if len(reporter.split_message(reporter.format_protocols_message(grown))) > 1:
            return grown, len(adapters), ""
        for key, value in list(base.items()):
            adapters[f"{key}__door{round_no}"] = value
    grown["adapters"] = adapters
    if len(reporter.split_message(reporter.format_protocols_message(grown))) > 1:
        return grown, len(adapters), ""
    return None, len(adapters), (
        f"за {_DOOR_STRESS_ROUNDS} удвоений сообщение не перешагнуло предел одного "
        f"сообщения ({len(adapters)} записей) — предпосылка испытания НЕ ОБЕСПЕЧЕНА"
    )


def _probe_owner_protocols_report_reaches_the_owner(
    arg: str | None,
    *,
    now: "datetime | None" = None,
    data_dir: str | None = None,
) -> tuple[str, str]:
    """Критерий: отчёт `/protocols` ДОЕЗЖАЕТ до владельца целиком, включая сводку.

    Предмет карточки `inbox-otchet-protocols-pochinen-u-proizvoditel`: цикл #854
    поднял население отчёта с 2 записей до 34 и проверил это у ПРОИЗВОДИТЕЛЯ, а
    вопрос «кто это читает» задал после. Замер 13.10: читателя не было ни одного —
    ни planового звателя, ни команды бота (у типизированной команды мимо
    `COMMAND_TO_PATH` вердикт один: открыть домашнюю панель, то есть МОЛЧА), а
    единственная живая дверь (`_post_message` → дайджест) обрезала текст до 500
    символов, и блок `*System*` — последний в сообщении — переставал доживать вовсе.
    В нём `Capital`/`Deployed`/`Cash`/`Total adapters` и строка «НЕ РАЗОБРАНО»,
    которой ADR-709 сделал молчание отличимым (инв. #17).

    **Проба меряет ИСХОД у ДВЕРИ, а не наличие функции.** Она зовёт НАСТОЯЩИЙ
    обработчик бота (`TelegramBot.cmd_protocols`) и считает, сколько строк отчёта
    доезжает до отправки. Числитель берётся у двери, знаменатель — у производителя
    (`format_protocols_message` по сырому артефакту): знаменатель, взятый у
    измеряемой двери, равен числителю по построению и зелен на любой сломанной двери.

    **Усечение входит в замер, а не предполагается отсутствующим.** Каждый кусок
    прогоняется через НАСТОЯЩИЙ `bot._fit_telegram` — ту самую ступень, которая
    режет текст внутри `send_message`. Дверь, отдавшая отчёт ОДНИМ куском сверх
    предела, теряет на ней строки, и проба это видит ЧИСЛОМ.

    **Замеров ТРИ, и у каждого свой вопрос.**

    * `живой` — артефакт, названный `data_dir`, подан двери ВХОДОМ: доезжает ли
      сегодняшний отчёт целиком;
    * `раздутый` — тот же артефакт, раздутый до сообщения за пределом одного
      (`_grown_adapter_doc`). Без него критерий ЛАТЕНТЕН: сегодняшние 2501 символ
      влезают в одно сообщение, и разница между делением и усечением на них не
      наблюдаема — ровно та латентность, которую назвал ADR-710. Не удалось
      раздуть ⇒ `unmeasured` с причиной, НИКОГДА не `satisfied`;
    * `по умолчанию` — дверь зовётся БЕЗ подсказки и читает свой собственный
      источник (`bot.DATA_DIR`); знаменатель берётся у ТОГО ЖЕ источника. Разделить
      это с первым замером пришлось потому, что иначе числитель и знаменатель
      читали бы РАЗНЫЕ файлы, когда `data_dir` указывает на другое дерево, и
      «потеряно 14 строк» значило бы лишь «сравнили два разных артефакта». Дефект
      найден контролем этой же пробы, а не рассуждением.

    **Подстрокой проба не проходит (ADR-333):** все ветки считают СТРОКИ и КУСКИ;
    ни одна не ищет текст в сообщении. Поэтому она безразлична к разметке —
    дверь вправе печатать HTML там, где производитель дал Markdown, пока ни одна
    строка не исчезла.

    **Чего проба НЕ меряет** (сказано вслух, чтобы её зелёный не читался шире):
    дошло ли сообщение до чата Telegram (сеть не трогается по построению — это
    инертный замер), нажимал ли владелец команду хоть раз, и верны ли сами числа
    отчёта — последнее мерит соседняя проба
    `owner_protocols_report_carries_every_record`.

    Три исхода РАЗЛИЧИМЫ (инв. #17): артефакта нет / он протух / дверь не ввезена
    ⇒ `unmeasured`. Время — вход (`now`), каталог данных — вход (`data_dir`).
    Проба только ЧИТАЕТ: ни файла, ни сети, ни состояния бота она не меняет.
    """
    doc, age_h, rel = _live_adapter_status_for_the_door(now, data_dir)
    if doc is None:
        return UNMEASURED, rel

    try:
        from spa_core import telegram_protocols_reporter as reporter
    except ImportError as exc:
        return UNMEASURED, f"производитель отчёта не ввезён: {type(exc).__name__}: {exc}"
    try:
        from spa_core.telegram import bot as bot_mod
    except ImportError as exc:
        return UNMEASURED, f"дверь (бот) не ввезена: {type(exc).__name__}: {exc}"

    door_cls = getattr(bot_mod, "TelegramBot", None)
    if door_cls is None:
        return UNMEASURED, "в модуле бота нет класса TelegramBot — дверь не измерена"
    if not hasattr(door_cls, "cmd_protocols"):
        return NOT_SATISFIED, (
            "у бота НЕТ обработчика cmd_protocols: типизированная команда вне "
            "COMMAND_TO_PATH открывает домашнюю панель, то есть отчёт не доезжает "
            "до владельца НИКАК и молчание неотличимо от ответа"
        )
    try:
        # Инертно: конструктор читает смещение опроса с диска и НИЧЕГО не отправляет.
        door = door_cls(token="probe", chat_id="probe")
    except Exception as exc:  # noqa: BLE001 — вердикт обязан быть третьим исходом
        return UNMEASURED, f"дверь не построена: {type(exc).__name__}: {exc}"

    def _deliver(payload: dict | None) -> "tuple[list[str], str]":
        """Что доезжает до отправки. Перехват — на экземпляре, модуль не трогается."""
        seen: list[str] = []

        def _capture(text, chat_id=None, parse_mode="HTML", **_kw):
            seen.append(bot_mod._fit_telegram(text or "", parse_mode))
            return {"ok": True}

        door.send_message = _capture  # type: ignore[method-assign]
        try:
            if payload is None:
                door.cmd_protocols("probe")
            else:
                door.cmd_protocols("probe", data=payload)
        except Exception as exc:  # noqa: BLE001
            return [], f"{type(exc).__name__}: {exc}"
        return seen, ""

    def _lines(text: str) -> int:
        return len(text.split("\n"))

    # Три замера, и у каждого СВОЙ вопрос. Разделены они потому, что иначе
    # знаменатель и числитель читали бы РАЗНЫЕ артефакты: половина «по умолчанию»
    # берёт источник у самой двери (`bot.DATA_DIR`), а `data_dir` пробы может
    # указывать на другое дерево — и тогда «потеряно 14 строк» означало бы лишь,
    # что сравнили два разных файла. Дефект найден контролем этой же пробы.
    grown, population, why = _grown_adapter_doc(doc, reporter)
    if grown is None:
        return UNMEASURED, f"испытание населением не поставлено: {why}"
    try:
        own = reporter.load_adapter_data(bot_mod.DATA_DIR)
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, (
            f"источник самой двери ({bot_mod.DATA_DIR}) не прочитан: "
            f"{type(exc).__name__}: {exc}"
        )

    rows: list[str] = []
    verdicts: list[str] = []
    plan: list[tuple[str, dict | None, dict, str]] = [
        ("живой", doc, doc, f"{len(reporter.split_message(reporter.format_protocols_message(doc)))} куск(ов)"),
        ("раздутый", grown, grown, f"{population} записей"),
        ("по умолчанию", None, own, "источник самой двери"),
    ]
    for label, payload_doc, source_doc, pop_note in plan:
        produced = reporter.format_protocols_message(source_doc)

        parts, failure = _deliver(payload_doc)
        if failure:
            return UNMEASURED, f"дверь упала на {label} входе: {failure}"
        want = _lines(produced)
        got = sum(_lines(p) for p in parts)
        clipped = sum(1 for p in parts if p.endswith("… (сокращено)"))
        rows.append(
            f"{label} вход ({pop_note}, {len(produced)} симв.): дверь отдала "
            f"{len(parts)} куск(ов), строк {got} из {want}, усечено куск(ов) {clipped}"
        )
        if not parts:
            verdicts.append(f"{label}: дверь не отдала НИ ОДНОГО куска")
        elif clipped:
            verdicts.append(f"{label}: усечено куск(ов) {clipped} — сводка не доживает")
        elif got != want:
            verdicts.append(
                f"{label}: потеряно строк {want - got}" if got < want
                else f"{label}: лишних строк {got - want}"
            )

    detail = f"{rel} (возраст {age_h:.1f}ч) · " + " · ".join(rows)
    if verdicts:
        return NOT_SATISFIED, f"{detail} — {'; '.join(verdicts)}"
    return SATISFIED, detail


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


#: Имя переписи провенанса ставки в `sys.modules` (ADR-706). Скрипт лежит в `scripts/`
#: (не пакет) — грузится по пути; имя ФИКСИРОВАНО, чтобы положительный контроль мог
#: подменить модуль и увидеть: проба читает ПЕРЕПИСЬ, а не собственную копию её правил.
APY_PROVENANCE_MODULE_NAME = "_spa_apy_provenance_census_under_probe"


def _apy_provenance_module():
    """Перепись провенанса оси APY как модуль: один раз на процесс."""
    import importlib.util
    mod = sys.modules.get(APY_PROVENANCE_MODULE_NAME)
    if mod is not None:
        return mod
    path = os.path.join(REPO_ROOT, "scripts", "apy_provenance_census.py")
    spec = importlib.util.spec_from_file_location(APY_PROVENANCE_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path} не загружается как модуль")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[APY_PROVENANCE_MODULE_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(APY_PROVENANCE_MODULE_NAME, None)
        raise
    return mod


def _probe_apy_provenance_declared_in_the_door(arg: str | None) -> tuple[str, str]:
    """Критерий: ни один ОПРАШИВАЕМЫЙ адаптер не может подставить постоянную МОЛЧА.

    Предмет — пункт 2 карточки `inbox-tsikl-schitaet-pokrytie-fidov-100-zhivym`
    (29.08): «адаптер, чьё число пришло из статической записи, обязан считаться
    `static`, а не `live`; показатель "100 % живое" должен уметь быть неполным».
    Разобрано решением ADR-706: у оси TVL контракт провенанса был с ADR-053, у оси
    APY — не было ВООБЩЕ, поэтому «живость» ставки назначалась догадкой на трёх
    дверях, а приёмка владельца (ADR-364) читала по этой оси ровно тот штамп,
    который система ставит безусловно, — и её 100 % не могло упасть никогда.

    **Дверь одна намеренно** — опрашиваемый набор оркестратора: ровно оттуда
    приходит капитал книги (замер 12.10: все пять протоколов с деньгами, $95 000,
    приходят путём снимка) и ровно там провенанс не спрашивают. Справочная
    поверхность всех классов `adapters/*` — другой вопрос (адаптер попадает в дверь
    решением цикла, а не свойством кода), и у неё свой потолок в самом приборе.

    **Возраста у этого вопроса НЕТ, и это не упущение.** Операнд — ДЕРЕВО КОДА, а не
    артефакт: протухнуть ему нечем, и подставлять сюда проверку свежести значило бы
    задать вопрос, которого предмет не содержит. Проба только ЧИТАЕТ исходники:
    перепись не зовёт адаптеры и в сеть не ходит.
    """
    try:
        census = _apy_provenance_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"перепись не загружена: {type(exc).__name__}: {exc}"

    try:
        rep = census.measure()
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, f"перепись упала: {type(exc).__name__}: {exc}"

    door = rep.get("door") or {}
    if rep.get("door_refused"):
        return UNMEASURED, f"дверь не прочитана: {rep['door_refused']}"
    if not door.get("population"):
        return UNMEASURED, ("в двери НИ ОДНОГО адаптера — опрашиваемый набор не "
                            "прочитан, и доля у нуля не существует")
    rows = rep.get("door_rows") or []
    if door.get("unmeasured"):
        names = ", ".join(
            f"{r['class']}: {'; '.join(r['notes'])[:120]}"
            for r in rows if r.get("verdict") == "unmeasured")
        return UNMEASURED, f"выражение ставки НЕ РАЗОБРАНО у {door['unmeasured']}: {names}"
    if door.get("can_substitute"):
        names = ", ".join(
            f"{r['class']} ({'; '.join(r['notes'])[:80]})"
            for r in rows if r.get("verdict") == "can_substitute")
        return NOT_SATISFIED, (
            f"постоянная может ранжировать капитал под ярлыком наблюдения у "
            f"{door['can_substitute']} из {door['population']}: {names}")
    return SATISFIED, (
        f"в двери {door['population']} адаптер(ов): объявляют провенанс "
        f"{door['declared']}, постоянную до поля не допускают {door['live_only']}, "
        f"подставить молча не может ни один")


#: Имя переписи ПИСАТЕЛЕЙ второго артефакта в `sys.modules` (ADR-707). Скрипт
#: лежит в `scripts/` (не пакет) — грузится по пути; имя ФИКСИРОВАНО, чтобы
#: положительный контроль мог подменить модуль и увидеть: проба читает ПЕРЕПИСЬ,
#: а не собственную копию её правил.
WRITER_CENSUS_MODULE_NAME = "_spa_adapter_status_writer_census_under_probe"


def _writer_census_module():
    """Перепись писателей `adapter_status.json` как модуль: один раз на процесс."""
    import importlib.util
    mod = sys.modules.get(WRITER_CENSUS_MODULE_NAME)
    if mod is not None:
        return mod
    path = os.path.join(REPO_ROOT, "scripts", "adapter_status_writer_census.py")
    spec = importlib.util.spec_from_file_location(WRITER_CENSUS_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path} не загружается как модуль")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[WRITER_CENSUS_MODULE_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(WRITER_CENSUS_MODULE_NAME, None)
        raise
    return mod


def _probe_adapter_status_number_has_a_writer(arg: str | None) -> tuple[str, str]:
    """Критерий: ни одно ОПУБЛИКОВАННОЕ число второго артефакта не может быть
    литералом производителя, выданным за наблюдение.

    Предмет — пункт 1 карточки `inbox-tsikl-schitaet-pokrytie-fidov-100-zhivym`
    (29.08): «выяснить, откуда `adapter_status.json` получает запись
    `aave_arbitrum` — кто и когда её пишет (константа в коде производителя или
    ручная правка)». Ответ замером ADR-707: КОНСТАНТА, и ровно в производителе —
    теневой блок брал число как ``entry.get("apy", 4.1)`` (и ``6.5`` / ``8.0`` у
    двух соседей), а `aave_arbitrum_adapter.get_apy()` читал его назад, обещая в
    докстринге «наблюдения нет ⇒ None» со ссылкой на решение владельца
    2026-08-08, которым эта самая подстановка из адаптера и была УДАЛЕНА.

    **Проба судит ИСХОД, а не структуру:** сколько литералов способно доехать до
    опубликованного числа (потолок НОЛЬ — это предмет решения владельца) и
    сколько опубликованных чисел едут без СВОЕГО рода. Классы «писатель не
    объявляет себя» и «писатель в запрещённом домене» ИЗМЕРЕНЫ тем же прибором,
    но пробу не гейтят: их радиус больше этого заказа, они названы карточкой, и
    у каждого свой потолок в самом приборе.

    **ADR-708 расширил ПРЕДМЕТ этой же пробы, а не завёл вторую.** Вопрос
    «может ли литерал выдать себя за наблюдение» в системе ОДИН, и чисел, по
    которым решают, ДВА: `apy` ранжирует, `tvl_usd` ДОПУСКАЕТ (порог RiskPolicy
    $5 млн/пул, ADR-053 — только живой TVL). ADR-707 мерил одну ось, и прибор
    был зелёным и неправым о второй: `tvl_usd` лежал вне кортежа
    `PUBLISHED_NUMBER_KEYS`, литерал приезжал через МОДУЛЬНЫЙ словарь
    (`_TVL_ESTIMATES.get(key, 0.0)`) и пропускался молча, а род спрашивался у
    СЛОВАРЯ, из-за чего `apy_source`, добавленный ADR-707, начал ручаться за
    соседний `tvl_usd`. Проба усилилась ВМЕСТЕ с прибором и без своей правки —
    ровно потому, что читает ПРИБОР, а не копию его логики.

    **Возраста у этого вопроса НЕТ, и это не упущение** (тот же довод, что у
    `apy_provenance_declared_in_the_door`): операнд — ДЕРЕВО КОДА, а не артефакт,
    протухнуть ему нечем. Проба только читает исходники: ни сети, ни живого
    `data/`, ни вызова адаптеров.
    """
    try:
        census = _writer_census_module()
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"перепись не загружена: {type(exc).__name__}: {exc}"
    try:
        rep = census.measure()
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, f"перепись упала: {type(exc).__name__}: {exc}"

    c = rep.get("counts") or {}
    cl = rep.get("ceilings") or {}
    if not c.get("writers"):
        return UNMEASURED, ("писателей не найдено ВОВСЕ — у артефакта есть "
                            "`generated_by`, значит писатель существует; ноль "
                            "здесь есть отказ меры, а не чистота")
    for key, label in (("writer_unmeasured", "цель записи не раскрыта"),
                       ("literal_unmeasured", "значение числа не разобрано"),
                       ("caller_supplied", "цель приходит от вызывающего")):
        if c.get(key, 0) > cl.get(key, 0):
            return UNMEASURED, (f"НЕ ИЗМЕРЕНО ({label}): {c[key]} > потолок "
                                f"{cl.get(key)}")

    if c.get("literal_substitution", 0) > cl.get("literal_substitution", 0):
        names = " · ".join(
            f"{s['file']}:{s['line']} поле {s['field']} = .get({s['source_key']!r}, "
            f"{s['literal']})" for s in (rep.get("substitutions") or [])[:4])
        return NOT_SATISFIED, (
            f"ЛИТЕРАЛ производителя доезжает до опубликованного числа у "
            f"{c['literal_substitution']} площадки(ок): {names}")
    if c.get("provenance_absent", 0) > cl.get("provenance_absent", 0):
        names = " · ".join(
            f"{s['file']}:{s['line']} поле {s.get('field')} "
            f"(ждали {s.get('want')})"
            for s in (rep.get("provenance_absent") or [])[:4])
        return NOT_SATISFIED, (
            f"опубликованное число едет БЕЗ СВОЕГО рода у "
            f"{c['provenance_absent']} числа(ел) при потолке "
            f"{cl.get('provenance_absent')}: {names}")

    return SATISFIED, (
        f"писателей {c['writers']} (объявляется "
        f"{c['writers'] - c.get('undeclared', 0)}), литерал до опубликованного "
        f"числа не доезжает ни у одной площадки, чисел без рода "
        f"{c.get('provenance_absent')} при потолке {cl.get('provenance_absent')}")


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


class _PrFetchFailed(Exception):
    """`_probe_pr_work_arrived_on_main`'s `_fetch` closure signals "no response" —
    specific, not `RuntimeError`/`Exception` (gate #1/7 `pre_commit_check.sh`). Only
    ever caught by `except Exception` in `scripts/pr_delivery_census.py`."""


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
            # Специфичный класс, не generic Exception/RuntimeError (gate #1/7
            # `scripts/pre_commit_check.sh`, «No bare exceptions»). Поведение не
            # меняется: единственные читатели — `open_pulls`/`added_paths`
            # (`scripts/pr_delivery_census.py`), ловящие `except Exception` широко.
            raise _PrFetchFailed(why or "ответа нет")
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
        # Срок прогона — не отказ переписи: проглоченный здесь вердикт pytest-timeout
        # оставлял обходчика G16 без срока (≈1230 с при лимите 180, замер 22.10).
        from spa_core.monitoring.timeout_door_census import is_foreign_failure
        if not is_foreign_failure(exc):
            raise
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


#: Предел возраста последней записи ленты вердиктов для пробы
#: `shadow_brief_names_the_unweighed_hold`. Такт писателя — дневной цикл
#: (объявлено у `allocation_rationale_history*.jsonl`), поэтому 36 ч — сутки
#: плюс запас на дрожание расписания: без запаса проба краснела бы от задержки
#: прогона, а не от предмета (`.claude/rules/deployment.md`, замер порогов
#: ADR-646). Предел нужен потому, что ЗАМОРОЖЕННАЯ лента отвечает на вопрос о
#: прошлом: «владелец видит исход совета» — утверждение про сегодня.
_VACUOUS_ADVICE_MAX_AGE_H = 36.0


def _probe_shadow_brief_names_the_unweighed_hold(
        arg: str | None, *, now: "datetime | None" = None,
        data_dir: str | None = None,
        brief_fn=None) -> tuple[str, str]:
    """Критерий: ПУСТОЙ совет назван исходом, а не выдан за взвешенный HOLD.

    Предмет — карточка `inbox-ten-sovetnika-po-perekladke-v-knigah-bal`
    (заказ G764 п. 2 приказа «Portfolio CIO»). Замер 16.10: на лентах
    Balanced/Aggressive 706 и 707 записей из 725 сравнивают книгу С САМОЙ СОБОЙ
    побайтно — цель приходит от `hy_cycle`/`lp_cycle` как УЖЕ РЕШЁННАЯ книга
    дня (ADR-531). Слой отображения при этом печатал владельцу
    `verdict: HOLD`, `optimal_apy_pp == current_apy_pp`, `yield_gap_pp: 0.0`
    при `numbers_evidenced: true` и «323-й день подряд без изменений» на ленте
    возрастом 45 дней. То есть «взвешивать было нечего» читалось как
    «взвесили, разрыв нулевой», а серия считалась в ЗАПИСЯХ под словом «день».

    **Меряется ИСХОД у читателя, а не структура.** Проба не спрашивает «есть ли
    поле в коде» — она зовёт НАСТОЯЩИЙ `build_books_brief` через перепись
    (`spa_core.monitoring.vacuous_advice_census`) и сверяет ЗНАЧЕНИЕ полей
    `weighed` / `unchanged_days` со своим замером по ленте. Подстрокой в прозе
    проба не проходит (ADR-333): проза может сказать «ног нет» и при этом
    объявить взвешенный HOLD полем, которое читают API и дашборд.

    Три исхода разведены:

    * `satisfied` — у каждой измеренной книги исход совета объявлен полем, у
      непустого совета названа причина, серия сверена В ДНЯХ;
    * `not_satisfied` — есть книга, где пустой совет подан как взвешенный, где
      причина не названа, где `unchanged_days` не объявлен или расходится с
      замером — это находка;
    * `unmeasured` — ленты не прочитаны, выдача упала, запись протухла.
      «Не измерено» не выдаётся ни за находку, ни за разрешение закрыть
      карточку (инв. #17).

    Часы, каталог данных и САМА выдача (`brief_fn`) — ВХОДЫ, не окружение:
    иначе красную сторону проверки закрепить нечем, а положительный контроль
    обязан воспроизводить дособытийную форму выдачи. Проба только ЧИТАЕТ.
    """
    try:
        from spa_core.monitoring import vacuous_advice_census as census
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"перепись не импортируется: {type(exc).__name__}: {exc}"

    root = data_dir or os.path.join(REPO_ROOT, "data")
    try:
        report = census.run_census(_pathlib.Path(root), brief_fn=brief_fn)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, f"перепись упала: {type(exc).__name__}: {exc}"
    if not report.get("measured"):
        return UNMEASURED, f"перепись не измерила: {report.get('reason')}"

    when = now or datetime.now(timezone.utc)
    for book, data in sorted((report.get("books") or {}).items()):
        if not data.get("brief_available"):
            continue
        stamp = (data.get("tape") or {}).get("latest_generated_at")
        if not stamp:
            return UNMEASURED, (f"у последней записи ленты {book} нет "
                                f"`generated_at` — возраст НЕ измерен, судить "
                                f"о том, что владелец видит СЕГОДНЯ, нечем")
        try:
            made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            return UNMEASURED, (f"лента {book}: generated_at {stamp!r} не "
                                f"разобран — возраст НЕ измерен")
        if made.tzinfo is None:
            made = made.replace(tzinfo=timezone.utc)
        age_h = (when - made).total_seconds() / 3600.0
        if age_h > _VACUOUS_ADVICE_MAX_AGE_H:
            return UNMEASURED, (
                f"лента вердиктов книги {book} протухла: возраст {age_h:.1f}ч "
                f"при пределе {_VACUOUS_ADVICE_MAX_AGE_H:.0f}ч — это замороженный "
                f"канон, а не то, что владелец видит сегодня; мерить надо из "
                f"дерева с живым data/")

    findings = list(report.get("findings") or [])
    shape = ("книг измерено {}, записей {}, пустых {}"
             .format(report.get("books_measured"), report.get("records_total"),
                     report.get("vacuous_records")))
    if findings:
        return NOT_SATISFIED, (
            "исход совета назван не у каждой книги ({}): ".format(len(findings))
            + "; ".join("[{}] {}: {}".format(f["finding"], f["book"], f["detail"])
                        for f in findings[:4])
            + f" · {shape}")
    return SATISFIED, (
        "у каждой измеренной книги исход совета объявлен полем `weighed` с "
        f"названной причиной, серия сверена в ДНЯХ полем `unchanged_days`; {shape}")


#: Предел возраста артефакта переписи `ledger_day_unit_census`. Такт переписи —
#: 8 суток (`MEASUREMENT_TACT_DAYS`), и предел равен ему ровно затем, чтобы
#: «внутри такта» и «протухло» не наложились друг на друга: порог ниже такта
#: краснил бы пробу от расписания, а не от предмета; порог выше такта зачитывал
#: бы замер, пропустивший собственный срок. Предел нужен потому, что население
#: читателей и их код меняются каждый цикл, а старая перепись говорит о дереве,
#: которого уже нет.
_LEDGER_DAY_UNIT_MAX_AGE_H = 192.0


def _probe_ledger_day_unit_census_names_the_unit(
        arg: str | None, *, now: "datetime | None" = None,
        repo_root: str | None = None, data_dir: str | None = None,
        report: dict | None = None) -> tuple[str, str]:
    """Критерий: ни один читатель ленты не считает ЗАПИСИ под словом «день».

    Предмет — карточка `inbox-perepis-chitatelei-lent-verdiktov-kto-sc`
    (заказ G765 п. 3 приказа «Portfolio CIO»). Замер 16.10: лента рукава несёт
    **16.16** записи на день (727 / 45; за 15.10 — 24), лента Conservative —
    1.92. Цикл #881 починил ОДНОГО читателя, выдачу владельцу, и даже у неё
    серия осталась записью: на тех же днях с той же решающей строкой дня
    `unchanged_days` даёт **37** при одном прогоне в дне и **14** при двадцати
    четырёх.

    **Меряется ИСХОД, а не структура.** Проба не ищет `len(` в исходнике — она
    читает перепись (:mod:`spa_core.monitoring.ledger_day_unit_census`), которая
    зовёт КАЖДОГО читателя на двух стендах, различающихся РОВНО плотностью
    записей при тождественном составе дней и побайтно той же последней строке
    дня. Находка — координата ответа, чьё ИМЯ говорит «день» и чьё ЗНАЧЕНИЕ
    сдвинулось от одной лишь плотности; подстрокой в прозе проба не проходит
    (ADR-333).

    **Население пересчитывается ЗАНОВО, у живого дерева.** Записанный замер
    отвечает о том населении, какое было на его момент; читатель, добавленный
    после, в записи отсутствует, и зачесть его «наверное, чистым» значило бы
    сделать пробу fail-OPEN ровно там, где она нужна. Член живого населения без
    строки в отчёте — `unmeasured` с ИМЕНЕМ.

    **Строка в отчёте — ещё не исход (ADR-771, заказ G767 п. 3).** До этой
    правки проба спрашивала только «есть ли у члена населения строка», и строка
    с `outcome="unmeasured"` проходила у неё как оценённая: при пустых
    `findings` критерий возвращал `satisfied` при любом числе читателей, у
    которых предмет не наблюдён ВОВСЕ. Теперь строки `unmeasured` разложены по
    ПРЕДМЕТУ (:func:`~spa_core.monitoring.ledger_day_unit_census.partition_unmeasured`),
    и две кучи решают по-разному:

    * **отказ ЗВАТЬ** (`sweeps_a_reader_population`, `entry_would_act`,
      `the_instrument_itself`) критерий зелёным оставляет: точка входа есть, не
      приводится она по РЕШЕНИЮ, решение названо. Равнять осознанный отказ с
      неответом было бы ложным красным, который учит гасить пробу;
    * **неответ НА ПРЕДМЕТЕ** (бюджет — в том числе на урезанном окне, упавший
      импорт, плывущие координаты, непривёденная точка входа, непостроенный
      стенд) делает критерий `unmeasured`: что читатель ответил бы, не
      наблюдено, и «записи не считаются как дни» о нём НЕ СКАЗАНО.

    Причина, не названная ни одной из куч, — тоже `unmeasured`, и громко:
    словарь пробы отстал от прибора, а отнести строку к куче по умолчанию
    значило бы решить за замер (в одну сторону — fail-OPEN, в другую — ложный
    красный).

    Три исхода разведены:

    * `satisfied` — у каждого члена населения есть исход, предмет наблюдён у
      каждого, кого прибор звал, и ни одна координата с именем дня не движется
      от плотности;
    * `not_satisfied` — есть НАЗВАННЫЙ читатель, считающий записи под словом
      «день» (это находка; гасить её сужением имени координаты запрещено).
      Находка судится ПЕРВОЙ и слепотой не затирается: `not_satisfied` карточку
      не закрывает, поэтому зачесть здесь нечего, а названный дефект лучше
      перемеренного молчания;
    * `unmeasured` — артефакта нет / он старше предела / население расширилось
      после замера / перепись не измерила / предмет не наблюдён у члена
      населения / причина неответа неизвестна пробе. «Не измерено» не выдаётся
      ни за находку, ни за разрешение закрыть карточку (инв. #17).

    Часы, корень дерева, каталог данных и сам отчёт — ВХОДЫ, не окружение:
    иначе красную сторону проверки закрепить нечем.
    """
    if (arg or "").strip():
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): "
                            "предмет — ВСЁ население читателей ленты, пофайловой "
                            "формы у него нет намеренно")
    try:
        from spa_core.monitoring import ledger_day_unit_census as census
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"перепись не импортируется: {type(exc).__name__}: {exc}"

    root = repo_root or REPO_ROOT
    if report is None:
        path = os.path.join(data_dir or os.path.join(root, "data"), census.ARTIFACT)
        try:
            with open(path, encoding="utf-8") as fh:
                report = json.load(fh)
        except BaseException as exc:  # noqa: BLE001
            return UNMEASURED, (f"артефакта переписи нет или он не прочитан "
                                f"({census.ARTIFACT}): {type(exc).__name__}: {exc} — "
                                f"единица у читателей НЕ наблюдена")
    if not isinstance(report, dict) or not report.get("measured"):
        reason = (report or {}).get("reason") if isinstance(report, dict) else "не словарь"
        return UNMEASURED, f"перепись не измерила: {reason}"

    stamp = report.get("generated_at")
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return UNMEASURED, (f"у отчёта переписи нет читаемой отметки времени "
                            f"(generated_at={stamp!r}) — возраст записи НЕ ИЗМЕРЕН")
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    if age > _LEDGER_DAY_UNIT_MAX_AGE_H:
        return UNMEASURED, (f"перепись старше предела: {age:.1f}ч при пределе "
                            f"{_LEDGER_DAY_UNIT_MAX_AGE_H:.0f}ч — читатели и их код "
                            f"менялись, а запись говорит о дереве, которого уже нет")

    try:
        roads, _stats = census.reader_population(_pathlib.Path(root))
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"население живого дерева не разобрано: "
                            f"{type(exc).__name__}: {exc}")
    graded = {str(r.get("module")) for r in (report.get("readers") or [])}
    missing = sorted(set(roads) - graded)
    if missing:
        return UNMEASURED, (f"у {len(missing)} читател(я/ей) живого дерева исхода в "
                            f"переписи НЕТ: " + ", ".join(missing[:4])
                            + " — зачесть их чистыми значило бы судить по слепоте")

    findings = list(report.get("findings") or [])
    tally = report.get("tally") or {}
    shape = ("читателей {} · {} · плотность стенда {}"
             .format(len(graded),
                     " ".join(f"{k}={v}" for k, v in sorted(tally.items())),
                     report.get("factor")))
    if findings:
        return NOT_SATISFIED, (
            "записи считаются под словом «день» у {} читател(я/ей): ".format(len(findings))
            + "; ".join("{} :: {}".format(f.get("module"),
                                          ", ".join(f.get("coords") or []))
                        for f in findings[:4])
            + f" · {shape}")

    # Строка `unmeasured` ПОСТРОЧНО — не зачёт (ADR-771, заказ G767 п. 3).
    # Деление по ПРЕДМЕТУ объявлено у самих причин (`census.CAUSES_*`), а не
    # пересказано здесь: одна копия правила, и новая причина добавляется там же,
    # где живёт её смысл.
    parts = census.partition_unmeasured(report.get("readers") or [])
    unknown = parts[census.PARTITION_UNCLASSIFIED]
    if unknown:
        return UNMEASURED, (
            "у {} строк(и) переписи причина `unmeasured` НЕ НАЗВАНА ни отказом "
            "звать, ни неответом на предмете: ".format(len(unknown))
            + ", ".join("{}::{}".format(r.get("module"), r.get("cause"))
                        for r in unknown[:4])
            + " — словарь пробы отстал от прибора, и отнести строку к любой из "
              f"куч по умолчанию значило бы решить за замер · {shape}")
    blind = parts[census.PARTITION_UNOBSERVED]
    if blind:
        return UNMEASURED, (
            "предмет НЕ НАБЛЮДЁН у {} читател(я/ей) — «записи не считаются как "
            "дни» о них не сказано, сказано «судить было нечем»: ".format(len(blind))
            + "; ".join("{} :: {}".format(r.get("module"), r.get("cause"))
                        for r in blind[:4])
            + " · отказов звать (решение, а не слепота): "
            + str(len(parts[census.PARTITION_REFUSED]))
            + f" · {shape}")

    reading = report.get("needs_reading") or []
    tail = ("" if not reading else
            f"; чувствительны к плотности, но единицу не назвали {len(reading)} "
            f"(перечень к чтению, не находка)")
    refused = parts[census.PARTITION_REFUSED]
    tail += ("" if not refused else
             f"; не позваны по РЕШЕНИЮ {len(refused)} "
             f"({', '.join(sorted({str(r.get('cause')) for r in refused}))}) — "
             f"осознанный отказ, а не неответ")
    return SATISFIED, ("ни одна координата с именем дня не движется от плотности "
                       f"записей; {shape}{tail}")


def _probe_census_probe_refuses_unobserved_subject(
        arg: str | None, *, now: "datetime | None" = None,
        repo_root: str | None = None) -> tuple[str, str]:
    """Критерий: зелёный критерий переписи НЕВОЗМОЖЕН при ненаблюдённом предмете.

    Предмет — карточка `inbox-proba-perepisi-schitaet-postrochnoe-ne-i`
    (заказ G767 п. 3 приказа «Portfolio CIO», ADR-771). Дефект был fail-OPEN:
    проба `ledger_day_unit_census_names_the_unit` считала строку с
    `outcome="unmeasured"` оценённой, и при пустых `findings` возвращала
    `satisfied` при любом числе читателей, у которых предмет не наблюдён вовсе.

    **Меряется ИСХОД, а не структура.** Проба не ищет в исходнике ни имени
    кучи, ни `partition_unmeasured`: она ЗОВЁТ настоящую пробу переписи на
    настоящем живом населении тремя отчётами, различающимися РОВНО причиной
    одной строки, и сверяет три вердикта. Подстрокой в прозе она не проходит
    (ADR-333) — вердикт берётся значением, а не текстом.

    Контроль в обе стороны лежит внутри самой проверки, а не рядом с ней:

    * неответ на предмете (`entry_exceeded_budget`) ⇒ критерий `unmeasured` —
      порви это звено, и вернётся ровно дефект ADR-771;
    * осознанный отказ звать (`entry_would_act`) ⇒ критерий `satisfied` —
      порви это звено, и критерий покраснеет на РЕШЕНИИ, что учит гасить пробу
      (`.claude/rules/acceptance.md` §3);
    * причина, не названная ни одной кучей ⇒ критерий `unmeasured` — порви, и
      новая причина молча попадёт в кучу по умолчанию.

    Исход сверяется ПОИМЁННО, а не как «зелёный / не зелёный»: неответ,
    объявленный НАХОДКОЙ, — тот же инвариант #17 наизнанку (о читателе
    утверждается дефект, которого никто не наблюдал), и «не зелёный» зачёл бы
    эту подмену.

    Часы и корень дерева — ВХОДЫ, не окружение.
    """
    if (arg or "").strip():
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): "
                            "предмет — поведение пробы переписи, пофайловой "
                            "формы у него нет")
    try:
        from spa_core.monitoring import ledger_day_unit_census as census
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return UNMEASURED, f"перепись не импортируется: {type(exc).__name__}: {exc}"
    under = PROBES.get("ledger_day_unit_census_names_the_unit")
    if under is None:
        return UNMEASURED, ("пробы `ledger_day_unit_census_names_the_unit` в "
                            "реестре нет — предмет этой проверки отсутствует")

    root = repo_root or REPO_ROOT
    moment = now or datetime.now(timezone.utc)
    try:
        roads, _stats = census.reader_population(_pathlib.Path(root))
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, (f"население живого дерева не разобрано: "
                            f"{type(exc).__name__}: {exc}")
    names = sorted(roads)
    if len(names) < 2:
        return UNMEASURED, (f"населения мало ({len(names)}): отчёт, где ОДНА "
                            "строка отличается причиной, на нём не построить")

    def _with(cause: str | None) -> dict:
        """Отчёт, чистый во всём, кроме причины у ОДНОГО читателя."""
        rows = [{"module": m, "outcome": census.OUT_DAY_INVARIANT}
                for m in names]
        if cause is not None:
            rows[0] = {"module": names[0], "outcome": census.OUT_UNMEASURED,
                       "cause": cause, "reason": "стенд проверки"}
        return {"measured": True, "generated_at": moment.isoformat(),
                "factor": 24,
                "tally": {census.OUT_DAY_INVARIANT: len(rows)},
                "readers": rows, "findings": [], "needs_reading": []}

    # Нулевая проба: без единой строки `unmeasured` контур обязан быть зелёным.
    # Без неё красный на любом из трёх стендов нельзя было бы отнести к причине
    # строки — он мог бы приходить от самого отчёта.
    base, base_detail = under(None, now=moment, repo_root=root,
                              report=_with(None))
    if base != SATISFIED:
        return UNMEASURED, ("контрольный отчёт БЕЗ строк «не измерено» не зелен "
                            f"({base}): {base_detail} — на таком стенде вердикты "
                            "трёх проб не относятся к причине строки")

    # Вердикт сверяется ТОЧНО, а не «зелёный / не зелёный». Неответ, названный
    # НАХОДКОЙ (`not_satisfied`), — тот же инв. #17, только наизнанку: о
    # читателе утверждается дефект, которого никто не наблюдал. «Не зелёный» на
    # этом месте зачёл бы такую подмену, поэтому ожидаемый исход назван
    # поимённо.
    checks = (
        ("неответ на предмете", census.CAUSE_OVER_BUDGET, UNMEASURED),
        ("осознанный отказ звать", census.CAUSE_WOULD_ACT, SATISFIED),
        ("причина, неизвестная пробе",
         "cause_that_no_pile_names_yet", UNMEASURED),
    )
    broken: list[str] = []
    seen: list[str] = []
    for label, cause, want in checks:
        verdict, detail = under(None, now=moment, repo_root=root,
                                report=_with(cause))
        seen.append(f"{label} ⇒ {verdict}")
        if verdict != want:
            broken.append(
                "{} ({}): критерий {}, а обязан был быть {} — {}".format(
                    label, cause, verdict, want, detail[:160]))
    shape = "население {} · ".format(len(names)) + " · ".join(seen)
    if broken:
        return NOT_SATISFIED, "; ".join(broken) + f" · {shape}"
    return SATISFIED, ("строка «не измерено» судится ПО ПРЕДМЕТУ: неответ "
                       "критерий зелёным не оставляет, осознанный отказ "
                       "краснеть не заставляет, незнакомая причина названа "
                       f"вслух; {shape}")


#: Предел возраста записи прогона для пробы `no_regression_tests_pass`.
#: Восемь суток — тот же такт, что у соседних недельных приборов. Предел нужен
#: потому, что население может НЕ измениться, а код под ним — измениться: тогда
#: старая запись говорила бы «зелено» про дерево, которого уже нет. Проверка
#: покрытия населения этого не ловит по построению, и подменять одно другим
#: было бы ровно тем «зелёным ответом на свой вопрос», против которого проба
#: и написана.
_NO_REGRESSION_MAX_AGE_H = 192.0


def _no_regression_subject(said: dict, live_rev: dict, root: str, report: dict,
                           report_path: str | None) -> str:
    """Четыре раздельных факта предмета §49 (решение ARB 23.10, вариант А).

    Не одно «о чём отчёт», а четыре, и подменять одно другим нельзя: ревизия
    проверяемого кода · версия воркфлоу и прибора · источник отчёта · дерево,
    о котором вынесено решение. Неизвестное названо словом «не назван(о)».
    """
    src = report.get("source") if isinstance(report.get("source"), dict) else {}
    inv = report.get("invoked_by") if isinstance(report.get("invoked_by"), dict) else {}
    instr = inv.get("instrument") if isinstance(inv.get("instrument"), dict) else {}
    wf = said.get("workflow_sha")
    instrument = (f"{(instr.get('sha') or '?')[:12]}"
                  + ("" if instr.get("clean") is True else " (дерево прибора изменено или не измерено)")
                  if instr else "не назван")
    run = (f"прогон {src.get('run_id')} ({src.get('event') or '?'})"
           if src.get("run_id") is not None else "локальная запись")
    return (f"ПРЕДМЕТ: код {said['sha'][:12]} · воркфлоу "
            f"{wf[:12] if isinstance(wf, str) and wf else 'не назван'} · прибор {instrument} · "
            f"отчёт {report_path or 'передан вызывающим'} ({run}) · "
            f"решение о дереве {root} ({live_rev['sha'][:12]}, чистое) — "
            f"утверждение о {said['sha'][:12]}, не о другом дереве или текущем main")


def _probe_no_regression_tests_pass(
        arg: str | None, *, now: "datetime | None" = None,
        repo_root: str | None = None,
        report_dir: str | None = None,
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

    **Предмет вердикта — дерево `repo_root`, и только оно** (вариант А, решение ARB
    23.10). `report_dir` — каталог, где лежит отчёт (`no_regression_census.json`),
    отдельно от дерева решения: так решение выносится о чистом снимке ревизии S
    по отчёту о той же S. Вердикт — утверждение о S; о боевом дереве, другом
    checkout или текущем main он ничего не говорит, если их ревизия иная. Поэтому
    пояснение называет РАЗДЕЛЬНО: ревизию проверяемого кода, версию воркфлоу и
    прибора, источник отчёта и дерево, о котором вынесено решение.
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
    report_path = None
    if report is None:
        report_path = (os.path.join(report_dir, os.path.basename(census.REPORT_REL))
                       if report_dir else os.path.join(root, census.REPORT_REL))
        try:
            with open(report_path, encoding="utf-8") as fh:
                report = json.load(fh)
        except BaseException as exc:  # noqa: BLE001
            return UNMEASURED, (f"отчёта переписи нет или он не прочитан "
                                f"({report_path}): {type(exc).__name__}: {exc} — "
                                f"исход тестов не наблюдён")
    if not isinstance(report, dict) or not report.get("measured"):
        reason = (report or {}).get("reason") if isinstance(report, dict) else "не словарь"
        return UNMEASURED, f"перепись не измерила: {reason}"

    # Отчёт отвечает только о ЯВНО названной ревизии (решение ARB 23.10). Та же
    # ли это ревизия, что держит судимое дерево, и цело ли дерево, — спрашивается
    # у git, а не выводится из совпадения имён файлов или свежести отчёта.
    try:
        said = census.report_revision(report)
        live_rev = census.tree_revision(root)
    except BaseException as exc:  # noqa: BLE001
        return UNMEASURED, f"ревизия не сверена: {type(exc).__name__}: {exc}"
    if not said["sha"]:
        return UNMEASURED, f"отчёт не называет проверяемую ревизию: {said['reason']}"
    if said["clean"] is not True:
        return UNMEASURED, (f"отчёт о {said['sha'][:12]} снят не на целом дереве этой "
                            f"ревизии: {said['reason'] or 'дерево замера было изменено'}")
    if not live_rev["sha"]:
        return UNMEASURED, f"ревизия судимого дерева не измерена: {live_rev['reason']}"
    if live_rev["sha"] != said["sha"]:
        return UNMEASURED, (f"отчёт о ревизии {said['sha'][:12]}, судимое дерево на "
                            f"{live_rev['sha'][:12]} — за другую ревизию он не "
                            f"засчитывается (историческое свидетельство о "
                            f"{said['sha'][:12]}, не о текущем коде)")
    if live_rev["clean"] is not True:
        dirty = live_rev["dirty"]
        return UNMEASURED, ("судимое дерево изменено после коммита "
                            + (f"({len(dirty)}): {dirty[:3]}" if dirty else
                               f"(не измерено: {live_rev['reason']})")
                            + f" — отчёт о {said['sha'][:12]} не о нём")

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

    head = said["sha"][:12] + (f" (воркфлоу {said['workflow_sha'][:12]})"
                               if said.get("workflow_sha") and said["workflow_sha"] != said["sha"]
                               else "")
    where = " · ".join(
        f"{m.get('hostname') or 'хост не назван'} {m.get('timestamp') or ''}".strip()
        for m in (report.get("records_meta") or [])) or "происхождение записи не названо"
    tail = (f"население {total} тест-файл(ов), запись о {head}, снята на {where}, "
            f"возраст {age:.1f}ч; " + _no_regression_subject(
                said, live_rev, root, report, report_path))

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
        # Копия на `ref` читается по sha, закреплённому У СЕРВЕРА (ADR-361/362):
        # кэш `origin/main` после чужого fetch объявил бы чистой копию, на которую
        # проба уже доставлена (или наоборот). Не закреплён ⇒ третий исход.
        pin = pin_server_ref(root, ref)
        blob = (_git(["show", f"{pin.sha}:{TRACKER_REL}/{name}"], repo_root=root)
                if pin.ok else None)
        if not pin.ok:
            ref_unmeasured = (f"копия на `{ref}` не прочитана: значение не закреплено "
                              f"у сервера — {pin.describe()}")
        elif blob is None:
            ref_unmeasured = f"копия на `{ref}` ({pin.sha[:12]}) не прочитана"
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
    # Вердикт пробы НЕ меняется (инв. #16) — к нему добавляется то, что число
    # `without` РЕАЛЬНО меряет. Заказ G110 п. 2: «не оставили квитанции» есть
    # замер ДВЕРИ объявления, а не вопроса «спрашивали ли сторожа» — read-only
    # `check` следа не оставляет вовсе. Без этой приписки проба обвиняет сессии
    # в том, что предписывает им инструкция.
    doors = report.get("doors") if isinstance(report.get("doors"), dict) else {}
    instruction = (report.get("instruction_doors")
                   if isinstance(report.get("instruction_doors"), dict) else {})
    if doors.get("measured"):
        prompt = ((instruction.get("surfaces") or {}).get("prompt_orchestrator")
                  if isinstance(instruction.get("surfaces"), dict) else None)
        if isinstance(prompt, dict) and prompt.get("measured"):
            named = ("НАЗЫВАЕТ" if prompt.get("names_guard_claim") else "НЕ НАЗЫВАЕТ")
            instruction_note = (f"; промпт цикла ({prompt.get('path')}) дверь-квитанцию "
                                f"`claim` {named}")
        else:
            instruction_note = ("; называет ли дверь-квитанцию промпт цикла — "
                                "НЕ ИЗМЕРЕНО")
        door_note = (f" (дверью сторожа объявлено {doors.get('through_guard_door')}, "
                     f"писателем напрямую {doors.get('by_writer_door_only')} — число "
                     f"ниже меряет ДВЕРЬ объявления, а не обращение к сторожу"
                     f"{instruction_note})")
    else:
        door_note = (f" (какой ДВЕРЬЮ объявлены взятия — НЕ ИЗМЕРЕНО: "
                     f"{doors.get('reason')})")
    if without > 0:
        return NOT_SATISFIED, (
            f"{without} из {takings} взятий предмета за {receipts.get('window_days')} дн. "
            f"не оставили квитанции сторожа захвата{door_note}; цена класса на сегодня — "
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


def _probe_problem_absent(arg: str | None, *, data_dir: str | None = None) -> tuple[str, str]:
    """Критерий C6 (ADR-580 §C6, REVIEW_1 amendment): Problem `arg` (= `problem_id`,
    `spa_core.monitoring.problem_store`) ЗАКРЫТА — RCA записан И условие не наблюдалось
    `close_absent_streak` прогонов подряд.

    Три исхода:
    * `arg` пуст, либо `data/problems.json` не прочитан, либо в нём нет записи с таким
      `problem_id` ⇒ `unmeasured` (пустое/отсутствующее НЕ читается как «закрыто» —
      инвариант #17);
    * статус `INCIDENT`/`OPEN`/`MITIGATED` (условие живо и/или RCA не записан) ⇒
      `not_satisfied`;
    * статус `CLOSED` ⇒ `satisfied`.

    Сравнение id — точное (поиск по `problem_id`, не подстрокой, ADR-333).
    """
    if not arg:
        return UNMEASURED, ("пробе нужен id проблемы "
                            "(acceptance_probe: problem_absent:<problem_id>)")
    try:
        from spa_core.monitoring import problem_store
    except Exception as exc:  # noqa: BLE001 — нечем измерить ≠ «закрыто»
        return UNMEASURED, f"problem_store не импортирован: {type(exc).__name__}: {exc}"
    base = _pathlib.Path(data_dir) if data_dir else _pathlib.Path(REPO_ROOT) / "data"
    store = problem_store.load_store(base)
    problems = store.get("problems") if isinstance(store, dict) else None
    if not isinstance(problems, dict):
        return UNMEASURED, f"{base / problem_store.OUTPUT_FILENAME} не прочитан — НЕ ИЗМЕРЕНО"
    entry = next((p for p in problems.values()
                 if isinstance(p, dict) and p.get("problem_id") == arg), None)
    if entry is None:
        return UNMEASURED, (f"проблема {arg!r} не найдена в "
                            f"{base / problem_store.OUTPUT_FILENAME} — НЕ ИЗМЕРЕНО")
    status = entry.get("status")
    if status == problem_store.STATUS_CLOSED:
        return SATISFIED, (f"проблема {arg!r} CLOSED: rca записан, условие отсутствовало "
                           f"{entry.get('consecutive_absences')} прогон(ов) подряд")
    return NOT_SATISFIED, f"проблема {arg!r} в статусе {status!r} — не закрыта"


# ── проба: знаменатель ряда G78…G98 ИЗМЕРЕН и доехал до читателя ─────────────
def measure_series_denominator(root=None, artifact=None) -> dict:
    """Поправка к знаменателю ряда: ЖИВОЙ замер против того, что видит читатель.

    Возврат: ``{"measured": bool, "reason": str, "live": {...},
    "shelf": {...} | None}``. ``measured=False`` — замер не состоялся; это НЕ
    «поправки нет» и не «поправка применена».

    **Два вопроса, и ни один не отвечает за другого.** Первый — посчитан ли
    знаменатель НАСТОЯЩИМ прогоном по дереву, которое стои́т сейчас (артефакт
    мог быть написан кодом, которого в дереве уже нет). Второй — доехало ли
    число до ЧИТАТЕЛЯ: шаг 0-офис читает артефакт, и число, не попавшее в
    него, не прочитает никто (ровно форма ADR-208).

    ``root``/``artifact`` существуют ради КОНТРОЛЯ: обе двери к живому дереву
    обязаны закрываться, иначе тест судил бы о рабочей копии, а не о стенде.
    """
    try:
        from spa_core.monitoring import rule_second_copy_census as rsc
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": (f"перепись не импортируется: "
                           f"{type(exc).__name__}: {exc}")}
    base = _pathlib.Path(root) if root is not None else _pathlib.Path(REPO_ROOT)
    shelf_path = (_pathlib.Path(artifact) if artifact is not None
                  else base / "data" / rsc.ARTIFACT)
    try:
        neighbour = rsc.open_class_counter_census(base)
        live = rsc.sequence_members_of_the_whole_population(base, neighbour)
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": (f"живой замер не состоялся: "
                           f"{type(exc).__name__}: {exc}")}
    if str(live.get("status")) != "MEASURED":
        return {"measured": False,
                "reason": (f"живой замер отказал "
                           f"[{live.get('unmeasured_class')}]: "
                           f"{live.get('reason')}")}
    shelf = None
    if shelf_path.exists():
        try:
            doc = json.loads(shelf_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"measured": False,
                    "reason": (f"артефакт {shelf_path.name} не разобран: "
                               f"{type(exc).__name__}: {exc}")}
        shelf = observed(doc, "sequence_members_of_the_whole_population",
                         kind=dict)
        if shelf is None:
            shelf = {}
    return {"measured": True, "reason": "", "live": live, "shelf": shelf,
            "artifact": str(shelf_path)}


def _probe_series_denominator_measured(arg: str | None) -> tuple[str, str]:
    """Критерий карточки: перепись ПЕЧАТАЕТ поправку к знаменателю, и число
    ИЗМЕРЕНО, а не оценено (заказ G99 п. 1, ADR-568).

    Меряет ИСХОД, а не структуру, и ровно двумя половинами — каждая рвётся
    отдельно:

    1. **живой прогон по дереву, которое стои́т сейчас** даёт `MEASURED`,
       население сходится с соседним ЧИСЛОМ и с его КООРДИНАТАМИ, а головная
       клетка не содержит счётчиков самого прибора (иначе число молча зависело
       бы от того, доставлен прибор или нет — ADR-566);
    2. **число доехало до читателя**: шаг есть в артефакте, который читает
       шаг 0-офис, и население в артефакте то же, что в живом прогоне.
       Артефакт старее кода — это НЕ выполненный критерий: читатель держит
       вчерашнее число, и «поправка измерена» о нём неправда.

    Аргумента у пробы НЕТ намеренно: поправка — о ВСЁМ населении, и пофайловой
    формы у неё не существует. Переданный аргумент отвергается вслух.
    """
    if (arg or "").strip():
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): "
                            "критерий — о ВСЁМ населении ряда, пофайловой "
                            "формы у него нет")
    got = measure_series_denominator()
    if not got.get("measured"):
        return UNMEASURED, got.get("reason", "причина не названа")
    live = got["live"]
    if not live.get("coordinates_agree_with_the_neighbour"):
        return NOT_SATISFIED, ("координаты населения разошлись с соседними — "
                              "знаменатель считается не по тому населению")
    own = live.get("own_sites") or {}
    if own.get("in_the_false_cell"):
        return NOT_SATISFIED, (
            f"в ГОЛОВНОЙ клетке стои́т {own['in_the_false_cell']} счётчик(ов) "
            f"самого прибора ({own.get('producer')}) — головное число зависит "
            f"от того, доставлен прибор или нет (ADR-566)")
    least, most = live.get("correction_at_least"), live.get("correction_at_most")
    if not isinstance(least, int) or not isinstance(most, int) or least > most:
        return NOT_SATISFIED, (
            f"поправка объявлена промежутком {least}…{most} — границы не "
            "числа или нижняя больше верхней, и такой промежуток ничего не "
            "ограничивает")
    shelf = got.get("shelf")
    if shelf is None:
        return NOT_SATISFIED, (
            f"артефакта {got.get('artifact')} нет — число посчитано и до "
            "читателя не доехало (шаг 0-офис читает артефакт, а не функцию)")
    if not shelf:
        return NOT_SATISFIED, (
            "в артефакте шага нет вовсе: число посчитано живым прогоном и до "
            "читателя не доехало — ровно форма ADR-208")
    if str(shelf.get("status")) != "MEASURED":
        return NOT_SATISFIED, (
            f"в артефакте шаг стои́т со статусом {shelf.get('status')!r} "
            f"[{shelf.get('unmeasured_class')}] — читатель видит отказ, а не "
            f"поправку")
    if shelf.get("population") != live.get("population"):
        return NOT_SATISFIED, (
            f"читатель держит население {shelf.get('population')}, живой "
            f"прогон даёт {live.get('population')} — артефакт старее кода, и "
            f"«поправка измерена» о нём неправда")
    # Имена причин берутся у ПРОИЗВОДИТЕЛЯ: вторая копия имени разошлась бы с
    # оригиналом молча — ровно тот предмет, который перепись и ищет.
    from spa_core.monitoring import rule_second_copy_census as rsc
    causes = live.get("false_members_by_cause") or {}
    return SATISFIED, (
        f"население {live['population']} → знаменатель "
        f"{live['series_population_corrected']}: ложных членов "
        f"{live['false_members_union']} (последовательность "
        f"{causes.get(rsc.CAUSE_SEQUENCE)} · ключ-элемент перечня "
        f"{causes.get(rsc.CAUSE_ENUMERATION_INDEX)}, пересечение "
        f"{live['false_members_overlap']}), поправка от "
        f"{live['correction_at_least']} до {live['correction_at_most']}; "
        f"число доехало до читателя (артефакт держит то же население)")


def _probe_owner_control_plane_reachable(
        arg: str | None, *, data_dir: str | None = None,
        now: "datetime | None" = None,
        beacon_path: str | None = None) -> tuple[str, str]:
    """Критерий: владелец МОЖЕТ сейчас управлять системой через Telegram.

    Предмет пробы — ИСХОД, а не модуль: у бота есть живой маячок умений, и
    названное умение (``arg``, по умолчанию ``alert_actions``) в нём ОБЪЯВЛЕНО.
    «Модуль есть и тесты зелёные» этого не доказывает — именно поэтому проба
    спрашивает артефакт, который пишет ЖИВОЙ бот каждые ~30 с.

    **Порог берётся У МОДУЛЯ и не равняется порогу живости сторожа.** Кнопки
    гейтит ``alert_actions.BEACON_MAX_AGE_S`` (6 ч), а живость сторожа —
    ``telegram_health`` (300 с); это два РАЗНЫХ вопроса, и сравнять их значило
    бы вернуть «⚠️ Кнопки сейчас недоступны» на каждом перезапуске бота
    (ADR-400, строка ловушек `CLAUDE.md`). Число здесь не перепечатано: оно
    читается из модуля, и его изменение переедет в пробу само.

    Три исхода (инв. #17):

    * маячка нет · не разобран · нет отметки времени ⇒ ``unmeasured``
      (отсутствие маячка НЕ читается ни как «кнопки есть», ни как «их нет»);
    * отметка есть, но умение не объявлено ЛИБО возраст вне окна ⇒
      ``not_satisfied``;
    * умение объявлено и возраст в окне ⇒ ``satisfied``.

    Умение сравнивается ТОЧНО, а не подстрокой (ADR-333): ``alert_action`` не
    есть ``alert_actions``.

    Вердикт сверяется с ТЕМ ЖЕ гейтом, который вешает кнопки
    (``alert_actions.handler_available``). Проба обязана мерить исход, а не свой
    пересчёт того же условия: расхождение двух ⇒ ``unmeasured`` с названной
    причиной, потому что тогда неизвестно, какой из двух ответов верен.
    """
    capability = arg or "alert_actions"
    try:
        from spa_core.telegram import alert_actions
    except Exception as exc:  # noqa: BLE001 — нечем измерить ≠ «кнопки есть»
        return UNMEASURED, f"alert_actions не импортирован: {type(exc).__name__}: {exc}"
    if beacon_path:
        path = _pathlib.Path(beacon_path)
    elif data_dir:
        path = _pathlib.Path(data_dir) / "telegram_bot_capabilities.json"
    else:
        path = _pathlib.Path(alert_actions.BEACON_PATH)
    try:
        doc = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, f"маячок {path} не прочитан: {type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return UNMEASURED, f"маячок {path} не объект — НЕ ИЗМЕРЕНО"
    stamp = doc.get("updated_at")
    if not stamp:
        return UNMEASURED, (f"у маячка {path} нет отметки `updated_at` — возраст "
                            "НЕ ИЗМЕРЕН, и это не «свежо»")
    try:
        stamped = datetime.fromisoformat(str(stamp))
    except ValueError as exc:
        return UNMEASURED, f"отметка маячка не разобрана: {stamp!r} ({exc})"
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(timezone.utc)
    age = (moment - stamped).total_seconds()
    declared = doc.get("capabilities")
    declared = list(declared) if isinstance(declared, list) else []
    gate = alert_actions.handler_available(
        capability=capability, now=moment, beacon_path=path)
    window = (-alert_actions.BEACON_FUTURE_TOLERANCE_S
              <= age <= alert_actions.BEACON_MAX_AGE_S)
    mine = bool(capability in declared and window)
    if mine != gate:
        return UNMEASURED, (f"проба и гейт кнопок расходятся (проба {mine}, "
                            f"handler_available {gate}) — неизвестно, какой ответ "
                            "верен, и выдавать один из них за замер нельзя")
    if capability not in declared:
        return NOT_SATISFIED, (f"умение {capability!r} в маячке НЕ объявлено "
                               f"(объявлены: {declared or '—'}) — кнопок этого "
                               "класса владельцу не предложат")
    if not window:
        return NOT_SATISFIED, (f"маячок вне окна: возраст {age / 3600:.2f} ч при "
                               f"пределе {alert_actions.BEACON_MAX_AGE_S / 3600:.0f} ч "
                               f"(порог кнопок, НЕ 300-секундный порог сторожа)")
    return SATISFIED, (f"умение {capability!r} объявлено, маячок возрастом "
                       f"{age / 60:.1f} мин при пределе "
                       f"{alert_actions.BEACON_MAX_AGE_S / 3600:.0f} ч — владелец "
                       "может управлять системой через Telegram")


def _probe_office_hollow_counter_means_harm(arg: str | None) -> tuple[str, str]:
    """Счётчик «ПРОЧИТАН ВХОЛОСТУЮ» шага 0-офис снова значит ВРЕД, а не порядок.

    Предмет карточки `inbox-ofis-zovet-artefakt-prochitannym-vholost` (замер
    05.10, цикл #781): шаг 0-офис в ОДНОМ прогоне печатал числа
    `data/artifact_stamp_clock_doors.json` отдельной секцией хвоста И звал тот
    же файл «⚠️ ПРОЧИТАН ВХОЛОСТУЮ (ресит НЕ пишется)». Дорог было две, реестр
    знал про одну, квитанция не писалась — а на квитанции стоит проверка B3
    сторожа архитектуры. Вред был не в потерянном числе (оно доезжало), а в
    том, что одна и та же единица счётчика значила и вред, и порядок: гейтить
    такой счёт нельзя.

    Меряется ИСХОД — ЗАПУСКОМ разбора, а не подстрокой (ADR-333). Четыре
    звена, любое одно порванное даёт `not_satisfied` с ИМЕНЕМ звена:

    1. **разбор НЕ вхолостую** — `_summarize_json` на документе в форме
       производителя не возвращает `_HOLLOW_MARK` и печатает числа находок;
    2. **счётчик ещё КУСАЕТСЯ** — ветка вырезается из одноразовой копии
       исходника шага, и тот же документ становится «РАЗОБРАТЬ НЕЧЕМ». Без
       этого контроля п. 1 зеленел бы и у сторожа, который не краснеет ни на
       чём: «вхолостую 0» означало бы «проверка снята», а не «порядок»;
    3. **дорога ОДНА** — в исходнике шага ровно один зов отрисовщика. Вернётся
       вторая секция — вернётся и неоднозначность счёта;
    4. **схема объявлена ПРАВДИВО** — ключи `_READ_SCHEMA` суть подмножество
       того, что `build_report` действительно кладёт. Объявить ключ, которого
       отчёт не несёт, значит выдумать расхождение схемы.

    Проба НЕ утверждает, что находок в самом артефакте нет: их число — предмет
    ADR-562, а не этой пробы. Третий исход назван: нет исходника шага, не
    грузится модуль, не читается форма ⇒ `unmeasured` с причиной, никогда не
    «чисто».
    """
    if (arg or "").strip():
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): "
                            "предмет — счётчик шага целиком, пофайловой формы "
                            "у него нет")
    import datetime as _dt
    import importlib.util as _ilu
    import tempfile as _tf

    office_src_path = os.path.join(REPO_ROOT, "scripts",
                                   "consume_office_reports.py")
    if not os.path.isfile(office_src_path):
        return UNMEASURED, (f"исходника шага {office_src_path} нет в дереве — "
                            "счётчик НЕ ИЗМЕРЕН")
    try:
        from spa_core.monitoring import artifact_stamp_clock_doors as _doors
    except Exception as exc:                                  # noqa: BLE001
        return UNMEASURED, (f"производитель не ввозится ({type(exc).__name__}: "
                            f"{exc}) — счётчик НЕ ИЗМЕРЕН")
    name = _doors.ARTIFACT
    office_src = open(office_src_path, encoding="utf-8").read()

    def _load(text: str, tag: str):
        with _tf.TemporaryDirectory() as box:
            path = os.path.join(box, f"office_{tag}.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            spec = _ilu.spec_from_file_location(f"_office_probe_{tag}", path)
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

    # Момент — ВХОД, а не стенные часы: иначе вердикт пробы менялся бы от
    # календаря машины, то есть ровно от того, что меряет сам ADR-562.
    now = _dt.datetime(2035, 1, 1, tzinfo=_dt.timezone.utc)
    doc = {"generated_at": now.isoformat(),
           "counts": {_doors.REACHES: 48, _doors.WALL_CLOCK: 1},
           "rows": [{"artifact": "data/x.json", "module": "spa_core.x",
                     "verdict": _doors.WALL_CLOCK}]}
    try:
        whole = _load(office_src, "whole")
        lines = whole._summarize_json(f"data/{name}", doc, now=now,
                                      root=REPO_ROOT)
    except Exception as exc:                                  # noqa: BLE001
        return UNMEASURED, (f"разбор не выполнен ({type(exc).__name__}: {exc}) "
                            "— счётчик НЕ ИЗМЕРЕН")
    if any(str(ln).startswith(whole._HOLLOW_MARK) for ln in lines):
        return NOT_SATISFIED, (f"звено 1: {name} читается ВХОЛОСТУЮ — ни ветки "
                               "в `_summarize_json`, ни строки в `_READ_SCHEMA`; "
                               "квитанция не пишется, и проверка B3 считает "
                               "артефакт непрочитанным")
    if not any("находок" in str(ln) for ln in lines):
        return NOT_SATISFIED, ("звено 1: разбор не вхолостую, но числа находок "
                               "в контекст не попали — читать было нечего")

    # ── звено 2: а счётчик вообще кусается? ──────────────────────────────────
    head = office_src.find(f'    elif name == "{name}":')
    tail = office_src.find("    elif name == ", head + 10) if head >= 0 else -1
    if head < 0 or tail < 0:
        return UNMEASURED, ("ветку не удалось вырезать из копии исходника — "
                            "кусается ли счётчик, НЕ ИЗМЕРЕНО")
    try:
        torn = _load(office_src[:head] + office_src[tail:], "torn")
        torn_lines = torn._summarize_json(f"data/{name}", doc, now=now,
                                          root=REPO_ROOT)
    except Exception as exc:                                  # noqa: BLE001
        return UNMEASURED, (f"копия без ветки не загрузилась "
                            f"({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")
    if not any(str(ln).startswith(torn._HOLLOW_MARK) for ln in torn_lines):
        return NOT_SATISFIED, ("звено 2: ветку вырезали, а счётчик промолчал — "
                               "«вхолостую 0» значит «проверка снята», а не "
                               "«порядок»")

    # ── звено 3: дорога ОДНА ─────────────────────────────────────────────────
    import ast as _ast
    roads = [n for n in _ast.walk(_ast.parse(office_src))
             if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
             and n.func.id in ("_ascd_report", "office_section")]
    if len(roads) != 1:
        return NOT_SATISFIED, (f"звено 3: дорог отрисовки {len(roads)}, а не "
                               f"одна ({[n.func.id for n in roads]}) — счёт "
                               "снова значит и вред, и порядок")

    # ── звено 4: схема объявлена правдиво ────────────────────────────────────
    declared = tuple(whole._READ_SCHEMA.get(name, ()))
    if not declared:
        return NOT_SATISFIED, (f"звено 4: {name} не объявлен в `_READ_SCHEMA` — "
                               "переименование ключа пройдёт молча")
    carried = set(_doors.build_report({"rows": [], "counts": {}, "planned": 0},
                                      now))
    invented = [k for k in declared if k not in carried]
    if invented:
        return NOT_SATISFIED, (f"звено 4: объявлены ключи, которых отчёт не "
                               f"несёт ({', '.join(invented)}) — расхождение "
                               "схемы выдумано, а не измерено")
    return SATISFIED, (f"{name}: разбор не вхолостую (находки напечатаны), "
                       f"счётчик кусается на вырезанной ветке, дорога одна, "
                       f"схема {len(declared)} ключ(а/ей) — все несомые "
                       "производителем. Единица счётчика «ВХОЛОСТУЮ» снова "
                       "значит ровно вред")


def _probe_owner_command_surfaces_declared_once(
    arg: str | None,
    *,
    data_dir: str | None = None,
    now: "datetime | None" = None,
) -> tuple[str, str]:
    """Критерий: набор команд владельца объявлен РОВНО ОДИН раз, расхождения названы.

    Предмет — карточка `inbox-dva-obyavleniya-komand-bota-rashodyatsya` и
    пятый пункт заказа **G711** приказа
    `inbox-task-portfolio-cio-dynamic-capital-alloc`. Замер 13.10 (цикл #856):
    набор команд жил в дереве ТРИЖДЫ — `TelegramBot._COMMANDS` (13), карта
    `handlers` в `_dispatch` (13, побайтово то же множество) и нагрузка
    `setMyCommands` (16). Прибор органов владельца
    `cio_kill_switch_controls` читал ПЕРВОЕ и называл его «то, что бот
    публикует владельцу как меню» — а владелец видит ТРЕТЬЕ.

    **Проба НЕ требует, чтобы все три множества совпали, и это важно.**
    «Обещано» (меню ☰) и «достижимо» (набор ∪ перехват ∪ кнопка) — РАЗНЫЕ
    вопросы: `/pause` 30.09 намеренно убрали из меню и оставили кнопкой.
    Потребовать равенства значило бы вытереть `/pause` из переписи органов
    владельца — то есть ПОГАСИТЬ настоящую находку (вердикт `CONFLATED` у
    органа PAUSE) слепотой, а не исправностью. Сводить надо КОПИИ одного
    ответа; поэтому критерий — три условия:

    1. ни одно объявление не повторяет множество другой поверхности (копий 0);
    2. у каждой достижимой, но не обещанной команды названа ПРИЧИНА
       (`TelegramBot._UNADVERTISED_BY_DESIGN`), и ни одна причина не пережила
       свою дверь;
    3. в карте диспетчера нет записи, до которой не доходит ни кнопка, ни
       набор, ни перехват (мёртвых дверей 0).

    **Подстрокой проба не проходит (ADR-333):** вердикт считается по ЧИСЛАМ
    множеств, ни одна ветка не ищет текст в коде. Сама перепись снимает
    поверхности разбором дерева (`ast`), а не поиском подстроки.

    Третий исход РАЗЛИЧИМ (инв. #17): файл канала владельца или карты
    маршрутов не прочитан/не разобран ⇒ `unmeasured` с названной причиной,
    НИКОГДА `not_satisfied`. Дерево — вход (`root` переписи равен дереву этого
    модуля), поэтому в worktree проба судит о worktree, а в проде — о проде.
    """
    del arg, data_dir, now  # предмет — дерево, а не артефакт и не часы
    from spa_core.monitoring import owner_command_surfaces as ocs

    measurement = ocs.measure(REPO_ROOT)
    if measurement.get("unmeasured"):
        return UNMEASURED, f"перепись поверхностей не состоялась: {measurement['unmeasured']}"
    found = ocs.findings(measurement)
    if found:
        return NOT_SATISFIED, "; ".join(found)
    return SATISFIED, (
        f"объявлений-копий 0 · мёртвых дверей 0 · достижимо "
        f"{len(measurement['reachable'])}, обещано "
        f"{len(measurement['advertised'])}, из расхождения "
        f"{len(measurement['reachable_not_advertised'])} у каждой названа причина")

def _probe_owner_protocols_report_groups_by_canonical_tier(
    arg: str | None,
    *,
    data_dir: str | None = None,
    now: "datetime | None" = None,
) -> tuple[str, str]:
    """Критерий: КАЖДАЯ запись отчёта `/protocols` стоит под КАНОНИЧЕСКИМ тиром.

    Предмет — карточка `inbox-yarlyki-tirov-v-otchete-protocols-nazyva` и заказ
    **G712 п. 3** приказа `inbox-task-portfolio-cio-dynamic-capital-alloc`.
    Замер 2026-10-13 (цикл #855): поле `tier` живого артефакта несёт ЦЕЛОЕ `1`
    у 6 записей, `2` у 23, `3` у 4 и строку `"T1"` ровно у одной — то есть 33
    записи из 34 печатались владельцу заголовками `*1*`, `*2*`, `*3*`: без
    названия тира и ВНЕ канонического порядка (их порядок — порядок обхода
    словаря). Тир T1 при этом печатался ДВУМЯ разделами сразу.

    **Меряется ИСХОД у двери владельца, а не структура.** Проба зовёт
    настоящий `format_protocols_message` и разбирает ЕГО ВЫДАЧУ: заголовки
    (строка целиком в звёздочках) и строки записей (ведущая «•»). Вердикт
    считается ЧИСЛАМИ — сколько записей стои́т под неканоническим заголовком и
    совпадает ли порядок заголовков с `_TIER_ORDER`; ни одна ветка не ищет в
    сообщении текст (ADR-333).

    **Канон читается у производителя одной копией** (`_TIER_LABEL`/`_TIER_ORDER`
    модуля отчёта). Второй перечень тиров здесь был бы вторым объявлением того
    же контракта — он разошёлся бы с первым молча.

    **Население — одной копией, у соседней пробы.** Группировку записей,
    которые до владельца вообще не доехали, судить нечем: если
    `owner_protocols_report_carries_every_record` не `satisfied`, эта проба
    отвечает `unmeasured` её причиной, а не зелёным нулём по дошедшему остатку.

    **Чего проба НЕ меряет** (сказано вслух, чтобы зелёный не читался шире):
    верность РАЗМЕЩЕНИЯ записи (тот ли тир у протокола по сути) — это вопрос о
    самом ярлыке в артефакте и о канонe тиров (ADR, владелец), а не о
    группировке; и верность НАЗВАНИЙ тиров — переименуй `_TIER_LABEL`, и проба
    останется зелёной, потому что её вопрос про группировку и порядок. Правило
    чтения формы проверяет батарея `test_protocols_report_tier_grouping.py`.

    Три исхода РАЗЛИЧИМЫ (инв. #17): артефакта нет / он не разобран / он протух
    (порог `ADAPTER_STATUS_MAX_AGE_H`, одна константа с соседями) ⇒ `unmeasured`.
    Записей ноль ⇒ тоже `unmeasured`: ноль вне канона обязан быть ИЗМЕРЕННЫМ, а
    не полученным из пустого артефакта. Время и каталог — входы.
    """
    doc, age_h, rel = _live_adapter_status_for_the_door(now, data_dir)
    if doc is None:
        return UNMEASURED, rel

    population, population_detail = (
        _probe_owner_protocols_report_carries_every_record(
            arg, data_dir=data_dir, now=now
        )
    )
    if population != SATISFIED:
        return UNMEASURED, (
            f"население отчёта не подтверждено ({population}): {population_detail}"
            f" — группировку записей, которые до владельца не доехали, судить нечем"
        )

    try:
        from spa_core import telegram_protocols_reporter as reporter
    except ImportError as exc:  # pragma: no cover - модуль в дереве есть
        return UNMEASURED, f"читатель отчёта не ввезён: {type(exc).__name__}: {exc}"
    try:
        message = str(reporter.format_protocols_message(doc))
    except Exception as exc:  # noqa: BLE001 - вердикт обязан быть третьим исходом
        return UNMEASURED, (
            f"{reporter.__name__}.format_protocols_message упал: "
            f"{type(exc).__name__}: {exc} — группировка не измерена"
        )

    tier_of_label = {
        label: tier for tier, label in reporter._TIER_LABEL.items()
    }
    canonical_seen: list[str] = []
    outside: list[tuple[str, int]] = []
    current: str | None = None
    counted = 0
    for line in message.splitlines():
        stripped = line.strip()
        if len(stripped) > 2 and stripped.startswith("*") and stripped.endswith("*"):
            heading = stripped[1:-1]
            if heading == "System":
                current = None
                continue
            tier = tier_of_label.get(heading)
            if tier is None:
                outside.append((heading, 0))
                current = None
            else:
                canonical_seen.append(tier)
                current = tier
            continue
        if not stripped.startswith("•"):
            continue
        counted += 1
        if current is None and outside:
            heading, count = outside[-1]
            outside[-1] = (heading, count + 1)

    outside_records = sum(count for _heading, count in outside)
    order_expected = [t for t in reporter._TIER_ORDER if t in set(canonical_seen)]
    detail = (
        f"{rel} (возраст {age_h:.1f}ч): записей в отчёте {counted}; "
        f"канонических разделов {len(canonical_seen)} "
        f"({', '.join(canonical_seen) or 'нет'}); вне канона записей "
        f"{outside_records} в {len(outside)} раздел(ах)"
    )
    if counted == 0:
        return UNMEASURED, (
            f"{detail} — записей нет вовсе, ноль вне канона НЕ ИЗМЕРЕН"
        )
    if outside_records or outside:
        forms = ", ".join(f"{h!r}:{c}" for h, c in outside)
        return NOT_SATISFIED, (
            f"{detail} — заголовки вне канона: {forms}; владелец читает ярлык-сырьё "
            f"вместо названия тира, и канонический порядок на эти разделы не действует"
        )
    if canonical_seen != order_expected:
        return NOT_SATISFIED, (
            f"{detail} — порядок разделов {canonical_seen} не равен каноническому "
            f"{order_expected}"
        )
    return SATISFIED, detail


def _probe_delivery_door_refuses_cycle_record_loss(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: ДВЕРЬ ДОСТАВКИ отказывает доставке, стирающей записи цикла.

    Предмет — находка цикла #858 и ADR-714. Стоячий приказ владельца
    ``inbox-task-portfolio-cio-dynamic-capital-alloc`` — тетрадь, в которую каждый
    цикл дописывает запись о своей работе; по ней судят, что сделано. ЗАМЕР
    13.10 по всей истории трекера (1302 карточки, 2133 перехода): доставка
    ``359ce9406`` (08.10) принесла свою копию приказа поверх УСТАРЕВШЕЙ и унесла
    **56 записей** (#716…#806, 205 → 151); ``af88d6bfc`` (25.09) тем же способом
    унесла **9**. Ни одна проверка у двери об этом не сказала: карточки не
    входили ни в один охраняемый класс.

    **Меряется ИСХОД У ДВЕРИ, а не наличие функции.** Проба зовёт настоящую
    ``push_to_github.guard_content_loss`` на настоящей паре байт той аварии и
    смотрит, ОТКАЗЫВАЕТ ли она, называя пропавшие номера.

    **Контроль в обе стороны внутри самой пробы.** Сторож, отказывающий на
    ЧЁМ УГОДНО, пробу бы удовлетворил — поэтому второе условие обязательно:
    на ЧИСТОМ ДОПИСЫВАНИИ (та же пара в обратном порядке, объединением) дверь
    обязана МОЛЧАТЬ. Зелёный даётся только за оба свойства сразу.

    **Источник пары НАЗВАН** (инв. #17): сначала история git (``cat-file blob``);
    если её нет (CI клонирует на глубину 1), берутся фикстуры батареи
    ``spa_core/tests/fixtures/cycle_record_loss`` — заголовки записей оттуда
    побайтово из тех же блобов. Какой источник сработал, печатается в detail:
    зелёный на фикстуре не должен читаться как зелёный на истории.

    ТРИ ИСХОДА РАЗЛИЧИМЫ: пушер не ввезён / пары байт нет ни в истории, ни в
    фикстурах / в паре нет той самой потери ⇒ ``unmeasured`` с причиной, а не
    «выполнено».
    """
    import importlib.util as _ilu
    import subprocess as _sp

    root = repo_root or REPO_ROOT
    pusher_path = os.path.join(root, "push_to_github.py")
    if not os.path.exists(pusher_path):
        return UNMEASURED, f"{pusher_path} не найден — дверь доставки НЕ ИЗМЕРЕНА"
    try:
        spec = _ilu.spec_from_file_location("_probe_pusher", pusher_path)
        pusher = _ilu.module_from_spec(spec)
        spec.loader.exec_module(pusher)
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, f"пушер не ввезён ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО"

    card = ("nimbalyst-local/tracker/"
            "inbox-task-portfolio-cio-dynamic-capital-alloc.md")
    incident = "359ce9406"
    source = ""
    before = after = None
    try:
        r0 = _sp.run(["git", "-C", root, "cat-file", "blob", f"{incident}^:{card}"],
                     capture_output=True, timeout=30)
        r1 = _sp.run(["git", "-C", root, "cat-file", "blob", f"{incident}:{card}"],
                     capture_output=True, timeout=30)
        if r0.returncode == 0 and r1.returncode == 0 and r0.stdout and r1.stdout:
            before, after, source = r0.stdout, r1.stdout, "история git"
    except Exception:                               # noqa: BLE001 — источник не единственный
        before = after = None
    if before is None:
        fix = os.path.join(root, "spa_core", "tests", "fixtures", "cycle_record_loss")
        try:
            with open(os.path.join(fix, f"order_{incident}_before.md"), "rb") as fh:
                before = fh.read()
            with open(os.path.join(fix, f"order_{incident}_after.md"), "rb") as fh:
                after = fh.read()
            source = "фикстуры батареи (истории git нет — глубина клона)"
        except OSError as exc:
            return UNMEASURED, (f"пары байт аварии {incident} нет ни в истории git, ни в "
                                f"фикстурах ({exc}) — отказ двери НЕ ИЗМЕРЕН")

    # Предпосылка: в паре и правда лежит та потеря. Иначе зелёный был бы вакуумным.
    try:
        lost, _renamed = pusher.classify_missing_entries(
            before, after, pusher.CYCLE_RECORD_RE)
    except AttributeError as exc:
        return NOT_SATISFIED, (f"у пушера нет меры записей цикла ({exc}): дверь не может "
                               f"отказать тому, чего не умеет мерить — источник {source}")
    if len(lost) != 56:
        return UNMEASURED, (f"в паре байт {incident} потеряно {len(lost)} записей, а авария "
                            f"была на 56 — предпосылка пробы НЕ ОБЕСПЕЧЕНА (источник {source})")

    refused = ""
    try:
        note = pusher.guard_content_loss(card, before, after, f"{incident}aa")
        return NOT_SATISFIED, (f"дверь доставки ПРОПУСКАЕТ потерю 56 записей цикла приказа "
                               f"(нота: {note or 'пусто'}; источник {source})")
    except Exception as exc:                        # noqa: BLE001 — любой отказ двери
        refused = str(exc)
    if "#716" not in refused:
        return NOT_SATISFIED, (f"дверь отказала, но НЕ НАЗВАЛА пропавшие записи — по такому "
                               f"отказу не рассудить, потеря это или переименование "
                               f"(источник {source})")

    # Обратная сторона: чистое дописывание дверь обязана пропустить.
    union = _cycle_record_union(pusher, after, before)
    try:
        back = pusher.guard_content_loss(card, after, union, f"{incident}aa")
    except Exception as exc:                        # noqa: BLE001
        return NOT_SATISFIED, (f"дверь отказывает и ЧИСТОМУ ДОПИСЫВАНИЮ "
                               f"({type(exc).__name__}: {str(exc)[:160]}) — сторож, который "
                               f"говорит «нет» всему, не отличает потерю от работы")
    if back:
        return NOT_SATISFIED, (f"на чистом дописывании дверь не молчит: {back[:200]}")
    return SATISFIED, (f"дверь ОТКАЗЫВАЕТ доставке, стирающей 56 записей цикла "
                       f"(названы поимённо), и МОЛЧИТ на возврате тех же записей "
                       f"объединением; источник пары — {source}")


def _probe_drift_names_direction_of_record_loss(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: ПРИБОР расхождения копий называет НАПРАВЛЕНИЕ потери записей цикла.

    Предмет — находка цикла #859 и ADR-715, остаток заказа G714 п. 3. Дверь
    доставки с #858 не даёт СТЕРЕТЬ записи цикла (проба
    ``delivery_door_refuses_cycle_record_loss``), но УЖЕ СТОЯЩЕЕ расхождение двух
    копий дверь не видит по построению: она стои́т у доставки, а не у состояния.
    Прибор ``check_tracker_drift`` это состояние мерил и о памяти молчал — на
    тетради с 94 потерянными записями он печатал «кто новее — не измерено, нужна
    ручная сверка», строку из общего списка `РАЗОШЛИСЬ` длиной 185 позиций.

    **Меряется ИСХОД У ПРИБОРА, а не наличие функции.** Проба зовёт настоящую
    ``check_tracker_drift.record_memory`` на настоящей паре байт аварии 08.10 и
    смотрит, НАЗЫВАЕТ ли она направление и номера.

    **Контроль в обе стороны внутри самой пробы.** Прибор, объявляющий потерю
    памяти на ЧЁМ УГОДНО, был бы бесполезен так же, как слепой: почти вся разница
    двух копий — штатная переписка тела и поле захвата. Поэтому второе условие:
    на том же тексте с ДОПИСАННЫМ телом (набор номеров записей цел) вердикт обязан
    быть «память совпала» и находкой НЕ быть.

    **Источник пары НАЗВАН** (инв. #17) — история git, иначе фикстуры батареи;
    зелёный на фикстуре не должен читаться как зелёный на истории.

    ТРИ ИСХОДА РАЗЛИЧИМЫ: прибор не ввезён / пары байт нет ни в истории, ни в
    фикстурах / в паре нет той самой потери ⇒ ``unmeasured`` с причиной.
    """
    import hashlib as _hl
    import importlib.util as _ilu
    import subprocess as _sp

    root = repo_root or REPO_ROOT
    tool = os.path.join(root, "scripts", "check_tracker_drift.py")
    if not os.path.exists(tool):
        return UNMEASURED, f"{tool} не найден — прибор расхождения НЕ ИЗМЕРЕН"
    if root not in sys.path:
        sys.path.insert(0, root)
    scripts_dir = os.path.join(root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    # Имя уникально по дереву НАМЕРЕННО: проба обязана мерить прибор ИЗ `repo_root`,
    # иначе на двух деревьях она дала бы один и тот же вердикт и ничего не
    # дискриминировала. Регистрация в `sys.modules` обязательна — у модуля есть
    # `@dataclass`, а он ищет своё пространство имён именно там.
    mod_name = "_probe_drift_" + _hl.sha256(root.encode()).hexdigest()[:12]
    try:
        spec = _ilu.spec_from_file_location(mod_name, tool)
        drift = _ilu.module_from_spec(spec)
        sys.modules[mod_name] = drift
        try:
            spec.loader.exec_module(drift)
        except BaseException:
            sys.modules.pop(mod_name, None)
            raise
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, f"прибор не ввезён ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО"

    if not hasattr(drift, "record_memory"):
        return NOT_SATISFIED, ("у прибора расхождения нет оси памяти (`record_memory`): "
                               "о потере записей цикла он сказать не может, и на тетради с "
                               "94 пропавшими записями печатает «кто новее — не измерено»")

    card = ("nimbalyst-local/tracker/"
            "inbox-task-portfolio-cio-dynamic-capital-alloc.md")
    incident = "359ce9406"
    before = after = None
    source = ""
    try:
        r0 = _sp.run(["git", "-C", root, "cat-file", "blob", f"{incident}^:{card}"],
                     capture_output=True, timeout=30)
        r1 = _sp.run(["git", "-C", root, "cat-file", "blob", f"{incident}:{card}"],
                     capture_output=True, timeout=30)
        if r0.returncode == 0 and r1.returncode == 0 and r0.stdout and r1.stdout:
            before = r0.stdout.decode("utf-8", "replace")
            after = r1.stdout.decode("utf-8", "replace")
            source = "история git"
    except Exception:                               # noqa: BLE001 — источник не единственный
        before = after = None
    if before is None:
        fix = os.path.join(root, "spa_core", "tests", "fixtures", "cycle_record_loss")
        try:
            with open(os.path.join(fix, f"order_{incident}_before.md"), encoding="utf-8") as fh:
                before = fh.read()
            with open(os.path.join(fix, f"order_{incident}_after.md"), encoding="utf-8") as fh:
                after = fh.read()
            source = "фикстуры батареи (истории git нет — глубина клона)"
        except OSError as exc:
            return UNMEASURED, (f"пары байт аварии {incident} нет ни в истории git, ни в "
                                f"фикстурах ({exc}) — вердикт прибора НЕ ИЗМЕРЕН")

    # Копия дерева здесь — АМПУТИРОВАННАЯ (`after`): именно её принесла доставка.
    lost = drift.record_memory(after, before, "origin/main")
    if lost.missing_tree != 56:
        return UNMEASURED, (f"в паре байт {incident} копии дерева не хватает "
                            f"{lost.missing_tree} записей, а авария была на 56 — предпосылка "
                            f"пробы НЕ ОБЕСПЕЧЕНА (источник {source})")
    if lost.verdict not in getattr(drift, "MEMORY_FINDINGS", frozenset()):
        return NOT_SATISFIED, (f"прибор не считает потерю 56 записей расхождением памяти: "
                               f"вердикт `{lost.verdict}` — {lost.detail[:200]} "
                               f"(источник {source})")
    if "#716" not in lost.detail:
        return NOT_SATISFIED, (f"прибор назвал расхождение, но НЕ НАЗВАЛ пропавшие записи — "
                               f"по такой строке читатель не отличит её от сотни других в "
                               f"списке `РАЗОШЛИСЬ` (источник {source})")

    # Обратная сторона: штатная переписка тела карточки памятью НЕ является.
    kept = drift.record_memory(before + "\nштатная приписка к телу карточки\n",
                               before, "origin/main")
    if kept.verdict in getattr(drift, "MEMORY_FINDINGS", frozenset()):
        return NOT_SATISFIED, (f"прибор объявляет потерю памяти на ЧИСТОЙ ПРИПИСКЕ к телу "
                               f"(`{kept.verdict}`) — сторож, который говорит «нет» всему, "
                               f"не отличает потерю от работы")
    if kept.verdict != getattr(drift, "MEMORY_EQUAL", "records_equal"):
        return NOT_SATISFIED, (f"на чистой приписке вердикт `{kept.verdict}`, а обязан быть "
                               f"«память совпала»: {kept.detail[:200]}")
    return SATISFIED, (f"прибор НАЗЫВАЕТ направление потери: `{lost.verdict}`, дереву не "
                       f"хватает 56 записей (поимённо), origin — {lost.missing_origin}; "
                       f"и МОЛЧИТ на чистой приписке к телу; источник пары — {source}")


def _cycle_record_union(pusher, current: bytes, older: bytes) -> bytes:
    """``current`` + блоки записей цикла, которые есть только в ``older``.

    Одна копия операции восстановления: её же применяет цикл #858, возвращая
    записи, унесённые доставкой 08.10. Возврат СТАРОЙ копии вместо объединения
    восстановлением не является — он стирает запись, которую авария добавила
    (замер: доставка 25.09 унесла девять записей и добавила #697).
    """
    have = {int(x) for x in pusher.entry_headers(current, pusher.CYCLE_RECORD_RE)}
    heads = list(pusher.CYCLE_RECORD_RE.finditer(older))
    out = [current]
    for i, m in enumerate(heads):
        if int(m.group("id")) in have:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(older)
        out.append(b"\n" + older[m.start():end].rstrip() + b"\n")
    return b"".join(out)


def _probe_queue_reader_names_record_memory_loss(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: ЧИТАТЕЛЬ ОЧЕРЕДИ (шаг 1) называет потерю ЗАПИСЕЙ ЦИКЛА.

    Предмет — находка цикла #860 и ADR-716, остаток заказа G715 п. 3. Прибор
    расхождения копий мерит ось памяти с #859 (``record_memory``, ADR-715) и
    печатает её в СВОЙ stdout; артефакта у него нет, а шаги протокола читают
    ОЧЕРЕДЬ. Замер 13.10 на прод-дереве (origin/main ``6f8895373``): у карточки
    стоячего приказа владельца, копии которой расходятся на **94** записи цикла,
    шаг 1 отвечал ``origin_check=diverged_unmeasured`` и ``origin_order=unmeasured``,
    а о памяти не говорил ни в JSON, ни в девяти строках stderr. «Назвать
    расхождение» и «довести его до того, кто читает очередь» — два разных
    действия, и второго не делал никто.

    **Меряется ИСХОД У ЧИТАТЕЛЯ, а не наличие функции.** Проба собирает
    одноразовый репозиторий с карточкой-ТЕТРАДЬЮ, у которой копия дерева беднее
    на две записи, зовёт НАСТОЯЩУЮ команду шага 1 (``orchestrator_queue.cmd_list``
    с ``--json``) из ``repo_root`` и читает её выдачу. Подстрокой проба не
    проходит (ADR-333): требуются ПОЛЯ и ЧИСЛО пропавших записей, а не фраза.

    **Контроль в обе стороны внутри самой пробы.** Читатель, объявляющий потерю
    на ЧЁМ УГОДНО, бесполезен так же, как молчащий: почти вся разница двух копий —
    штатная переписка тела (мера «любая разница» дала бы 538 отказов из 2133 на
    живой популяции, замер #858). Поэтому второе условие: на карточке с
    ПЕРЕПИСАННЫМ телом и целым набором номеров записей читатель обязан молчать.

    ТРИ ИСХОДА РАЗЛИЧИМЫ (инв. #17): читателя нет / не ввезён / git недоступен или
    предпосылка репозитория не обеспечена ⇒ ``unmeasured`` с причиной, а не
    ``not_satisfied`` и уж точно не ``satisfied``.

    Оговорка названа вслух: ``orchestrator_queue`` ввозится из ``repo_root``, а
    пакет ``spa_core`` остаётся того дерева, в котором идёт сама проба (он уже в
    ``sys.modules``). Измеряемое свойство живёт в самом читателе, поэтому
    дискриминация на двух деревьях от этого не страдает; прибор расхождения
    (``check_tracker_drift``) правка #860 не трогает вовсе.
    """
    import contextlib as _ctx
    import hashlib as _hl
    import importlib.util as _ilu
    import io as _io
    import json as _json
    import subprocess as _sp
    import tempfile as _tf

    root = repo_root or REPO_ROOT
    reader_path = os.path.join(root, "scripts", "orchestrator_queue.py")
    if not os.path.exists(reader_path):
        return UNMEASURED, f"{reader_path} не найден — читателя очереди НЕ ИЗМЕРИТЬ"
    for _p in (root, os.path.join(root, "scripts")):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    mod_name = "_probe_queue_" + _hl.sha256(root.encode()).hexdigest()[:12]
    try:
        spec = _ilu.spec_from_file_location(mod_name, reader_path)
        reader = _ilu.module_from_spec(spec)
        sys.modules[mod_name] = reader
        try:
            spec.loader.exec_module(reader)
        except BaseException:
            sys.modules.pop(mod_name, None)
            raise
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, (f"читатель очереди не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    try:
        import check_tracker_drift as _drift        # мера памяти — у прибора, одной копией
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, f"прибор расхождения не ввезён ({exc}) — НЕ ИЗМЕРЕНО"

    ref = "main"

    def _git(cwd, *args):
        return _sp.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       timeout=60)

    def _notebook(records, body="тело приказа"):
        head = ("---\ntrackerStatus:\n  type: inbox\n"
                "title: \"TASK — стоячий приказ владельца\"\nstatus: in-progress\n---\n\n"
                f"{body}\n")
        return head + "".join(
            f"\n## Цикл #{n} (замер, ADR-{n})\n\nчто сделано в цикле {n}\n" for n in records)

    def _ask(tmp, cards_before, cards_after):
        """Собрать пару копий и спросить ЧИТАТЕЛЯ. → (карточки-JSON, stderr)."""
        rroot = os.path.join(tmp, "repo")
        tracker = os.path.join(rroot, _drift.TRACKER_REL)
        os.makedirs(tracker)
        for a in (["init", "-q", "-b", ref, rroot],
                  ["config", "user.email", "t@example.com"],
                  ["config", "user.name", "probe"]):
            r = _git(rroot if a[0] != "init" else tmp, *a)
            if r.returncode != 0:
                raise SPAError(f"git {' '.join(a)}: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
        for name, text in cards_before.items():
            with open(os.path.join(tracker, f"{name}.md"), "w", encoding="utf-8") as fh:
                fh.write(text)
        for a in (["add", "-A"], ["commit", "-q", "-m", "ref"]):
            r = _git(rroot, *a)
            if r.returncode != 0:
                raise SPAError(f"git {' '.join(a)}: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
        for name, text in cards_after.items():
            with open(os.path.join(tracker, f"{name}.md"), "w", encoding="utf-8") as fh:
                fh.write(text)
        argv = ["list", "--tracker-dir", tracker, "--ref", ref, "--json"]
        out, err = _io.StringIO(), _io.StringIO()
        with _ctx.redirect_stdout(out), _ctx.redirect_stderr(err):
            reader.cmd_list(reader.build_parser().parse_args(argv))
        return {c["id"]: c for c in _json.loads(out.getvalue())}, err.getvalue()

    try:
        with _tf.TemporaryDirectory() as tmp:
            # Авария: на ref записи #716…#718, в дереве — только #716.
            lost, lost_err = _ask(
                tmp,
                {"inbox-order": _notebook([716, 717, 718])},
                {"inbox-order": _notebook([716])})
        with _tf.TemporaryDirectory() as tmp:
            # Обратная сторона: тело переписано целиком, набор номеров ЦЕЛ.
            kept, kept_err = _ask(
                tmp,
                {"inbox-order": _notebook([716, 717, 718])},
                {"inbox-order": _notebook([716, 717, 718], body="тело переписано")})
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, (f"предпосылка пробы НЕ ОБЕСПЕЧЕНА ({type(exc).__name__}: {exc}) — "
                            f"вердикт читателя очереди НЕ ИЗМЕРЕН")

    card = lost.get("inbox-order")
    if card is None:
        return UNMEASURED, ("читатель не вернул карточку-тетрадь вовсе — предпосылка пробы "
                            "НЕ ОБЕСПЕЧЕНА, об оси памяти судить нечем")
    if "origin_memory" not in card:
        return NOT_SATISFIED, (
            "у читателя очереди (шаг 1) НЕТ оси памяти: в вердикте карточки только "
            f"`origin_check={card.get('origin_check')}` / "
            f"`origin_order={card.get('origin_order')}` — о пропавших записях цикла он "
            "молчит, как молчал 13.10 на тетради с 94 потерянными записями")
    if card["origin_memory"] not in getattr(_drift, "MEMORY_FINDINGS", frozenset()):
        return NOT_SATISFIED, (
            f"читатель не считает потерю двух записей расхождением памяти: "
            f"`{card['origin_memory']}` — {str(card.get('origin_memory_detail'))[:200]}")
    if card.get("origin_memory_missing_tree") != 2:
        return NOT_SATISFIED, (
            f"читатель не несёт ЧИСЛО пропавших записей: "
            f"`origin_memory_missing_tree={card.get('origin_memory_missing_tree')}` при "
            f"двух пропавших — выпарсивать его из прозы значит завести вторую мерку")
    if "#717" not in str(card.get("origin_memory_detail", "")):
        return NOT_SATISFIED, ("читатель назвал потерю, но НЕ НАЗВАЛ пропавшие записи "
                               "поимённо — такую строку не отличить от сотни других")
    if "inbox-order" not in lost_err or "ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ" not in lost_err:
        return NOT_SATISFIED, ("вердикт есть в JSON, но человек у терминала его не видит: "
                               "в stderr нет ни раздела памяти, ни имени карточки — два "
                               "выхода одного читателя разошлись")

    other = kept.get("inbox-order") or {}
    if other.get("origin_memory") in getattr(_drift, "MEMORY_FINDINGS", frozenset()):
        return NOT_SATISFIED, (
            f"читатель объявляет потерю памяти на ЧИСТОЙ ПЕРЕПИСКЕ ТЕЛА "
            f"(`{other.get('origin_memory')}`) — сторож, говорящий «нет» всему, не "
            f"отличает потерю от работы (538 отказов из 2133 на живой популяции)")
    if "origin_memory_note" in other or "ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ" in kept_err:
        return NOT_SATISFIED, ("на штатной переписке тела читатель обязан МОЛЧАТЬ, а он "
                               "печатает раздел памяти — раздел утонет в шуме")
    return SATISFIED, (
        f"шаг 1 НАЗЫВАЕТ потерю записей цикла: `{card['origin_memory']}`, дереву не "
        f"хватает {card['origin_memory_missing_tree']} записей (поимённо, "
        f"origin — {card.get('origin_memory_missing_origin')}), имя карточки видно и в "
        f"JSON, и в stderr; и МОЛЧИТ на чистой переписке тела "
        f"(`{other.get('origin_memory')}`)")


def _probe_queue_reader_names_unmeasured_memory(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: ЧИТАТЕЛЬ ОЧЕРЕДИ называет НЕ ИЗМЕРЕННУЮ память СВОЕЙ причиной.

    Предмет — находка цикла #861 и ADR-717, остаток заказа G716 п. 3. Цикл #860
    довёл ось памяти копий до шага 1 протокола, но ТОЛЬКО ПО ЗАПРОСУ прибора: во
    всех ветках, где сверка с `origin` не состоялась, вердикт уезжал БЕЗ полей
    ``origin_memory*``. А «полей нет» в контракте #860 означает ровно одно — «ось
    НЕ СПРАШИВАЛИ» (так у `hidden`/`undelivered`, где второй копии не существует).
    Два РАЗНЫХ состояния печатались одинаково, и самое тихое из них — «спросили, и
    узнать не удалось» — было неотличимо от штатного.

    ЗАМЕР ДО ПРАВКИ (одноразовый репозиторий, `--ref` неразрешим): stderr читателя —
    три строки про СОСТАВ списка и НОЛЬ про память; в JSON ``origin_check=unmeasured``
    и ни одного ключа ``origin_memory*``. Сессия, пришедшая дописать свою запись в
    прод-копию приказа, узнала бы столько же, сколько у карточки-задания без второй
    копии, — то есть ничего. Так уже дважды терялась память приказа (ADR-714: 56
    записей 08.10 и 9 записей 25.09).

    **Меряется ИСХОД У ЧИТАТЕЛЯ, а не наличие функции.** Проба собирает одноразовый
    репозиторий с карточкой-ТЕТРАДЬЮ, зовёт НАСТОЯЩУЮ команду шага 1
    (``orchestrator_queue.cmd_list`` с ``--json``) ДВАЖДЫ — с неразрешимым ref и с
    разрешимым — и читает оба ответа. Подстрокой проба не проходит (ADR-333):
    требуются ПОЛЕ вердикта и причина, говорящая о ЗАПИСЯХ ЦИКЛА, а не фраза.

    **Контроль в обе стороны внутри самой пробы.** Читатель, который штампует «не
    измерено» на ЧЁМ УГОДНО, бесполезен так же, как молчащий: он снова сделал бы
    неотличимыми состоявшийся замер и отказ. Поэтому второе условие: на СОСТОЯВШЕЙСЯ
    сверке тот же читатель обязан дать вердикт памяти ИЗ ИЗМЕРЕННЫХ (`MEMORY_FINDINGS`
    или `records_equal`), а не третий исход.

    ТРИ ИСХОДА РАЗЛИЧИМЫ (инв. #17): читателя нет / не ввезён / предпосылка
    репозитория не обеспечена ⇒ ``unmeasured`` с причиной, а не ``not_satisfied`` и
    уж точно не ``satisfied``.

    Оговорка названа вслух (та же, что у соседней пробы #860): ``orchestrator_queue``
    ввозится из ``repo_root``, а пакет ``spa_core`` остаётся того дерева, в котором
    идёт сама проба. Измеряемое свойство живёт в самом читателе, поэтому дискриминация
    на двух деревьях от этого не страдает.
    """
    import contextlib as _ctx
    import hashlib as _hl
    import importlib.util as _ilu
    import io as _io
    import json as _json
    import subprocess as _sp
    import tempfile as _tf

    root = repo_root or REPO_ROOT
    reader_path = os.path.join(root, "scripts", "orchestrator_queue.py")
    if not os.path.exists(reader_path):
        return UNMEASURED, f"{reader_path} не найден — читателя очереди НЕ ИЗМЕРИТЬ"
    for _p in (root, os.path.join(root, "scripts")):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    mod_name = "_probe_queue_unmeas_" + _hl.sha256(root.encode()).hexdigest()[:12]
    try:
        spec = _ilu.spec_from_file_location(mod_name, reader_path)
        reader = _ilu.module_from_spec(spec)
        sys.modules[mod_name] = reader
        try:
            spec.loader.exec_module(reader)
        except BaseException:
            sys.modules.pop(mod_name, None)
            raise
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, (f"читатель очереди не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    try:
        import check_tracker_drift as _drift        # вокабуляр оси — у прибора, одной копией
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, f"прибор расхождения не ввезён ({exc}) — НЕ ИЗМЕРЕНО"

    # Имя ветки сцены — ВХОД, а не умолчание хоста (`init.defaultBranch` на
    # `ubuntu-latest` даёт `master`): фикстура, назвавшая потом `main`, была бы зелена
    # на Маке и красна в CI (`.claude/rules/deployment.md`).
    ref = "scene-main"
    missing_ref = "refs/heads/no-such-ref-for-this-probe"

    def _git(cwd, *args):
        return _sp.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       timeout=60)

    def _notebook(records, body="тело приказа"):
        head = ("---\ntype: inbox\nstatus: in-progress\n"
                "title: \"TASK — стоячий приказ владельца\"\n---\n\n"
                f"{body}\n")
        return head + "".join(
            f"\n## Цикл #{n} (замер цикла {n})\n\nчто сделано в цикле {n}\n" for n in records)

    def _ask(tracker, which_ref):
        argv = ["list", "--tracker-dir", tracker, "--ref", which_ref, "--json"]
        out, err = _io.StringIO(), _io.StringIO()
        with _ctx.redirect_stdout(out), _ctx.redirect_stderr(err):
            reader.cmd_list(reader.build_parser().parse_args(argv))
        return {c["id"]: c for c in _json.loads(out.getvalue())}, err.getvalue()

    try:
        with _tf.TemporaryDirectory() as tmp:
            rroot = os.path.join(tmp, "repo")
            tracker = os.path.join(rroot, _drift.TRACKER_REL)
            os.makedirs(tracker)
            r = _git(tmp, "init", "-q", "-b", ref, rroot)
            if r.returncode != 0:
                raise SPAError(f"git init: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
            for a in (["config", "user.email", "probe@example.com"],
                      ["config", "user.name", "probe"]):
                r = _git(rroot, *a)
                if r.returncode != 0:
                    raise SPAError(f"git {' '.join(a)}: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
            card = os.path.join(tracker, "inbox-order.md")
            with open(card, "w", encoding="utf-8") as fh:
                fh.write(_notebook([716, 717, 718]))
            for a in (["add", "-A"], ["commit", "-q", "-m", "ref"]):
                r = _git(rroot, *a)
                if r.returncode != 0:
                    raise SPAError(f"git {' '.join(a)}: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
            with open(card, "w", encoding="utf-8") as fh:
                fh.write(_notebook([716]))          # дереву не хватает #717 и #718
            refused, refused_err = _ask(tracker, missing_ref)
            measured, _measured_err = _ask(tracker, ref)
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, (f"предпосылка пробы НЕ ОБЕСПЕЧЕНА ({type(exc).__name__}: {exc}) — "
                            f"вердикт читателя очереди НЕ ИЗМЕРЕН")

    card = refused.get("inbox-order")
    if card is None:
        return UNMEASURED, ("читатель не вернул карточку-тетрадь вовсе — предпосылка пробы "
                            "НЕ ОБЕСПЕЧЕНА, об оси памяти судить нечем")
    if "origin_memory" not in card:
        return NOT_SATISFIED, (
            "при ОТКАЗЕ сверки у читателя очереди НЕТ оси памяти: в вердикте только "
            f"`origin_check={card.get('origin_check')}` — «спросили и не узнали» "
            "неотличимо от «не спрашивали», то есть от карточки без второй копии")
    measured_verdicts = set(getattr(_drift, "MEMORY_FINDINGS", frozenset())) | {
        getattr(_drift, "MEMORY_EQUAL", "records_equal"),
        getattr(_drift, "MEMORY_NOT_A_NOTEBOOK", "not_a_notebook")}
    if card["origin_memory"] in measured_verdicts:
        return NOT_SATISFIED, (
            f"при отказе сверки читатель выдаёт ИЗМЕРЕННЫЙ вердикт "
            f"`{card['origin_memory']}` — самое успокоительное из значений выдумано, "
            f"а мерить было нечем")
    why = str(card.get("origin_memory_detail") or "")
    if "ЗАПИСЕЙ ЦИКЛА" not in why and "ЗАПИСИ ЦИКЛА" not in why:
        return NOT_SATISFIED, (
            f"у оси памяти нет СВОЕЙ причины — она пересказывает соседа и о записях "
            f"цикла не говорит: {why[:200] or '(причины нет вовсе)'}")
    if "НЕ ИЗМЕРЕНО" not in why:
        return NOT_SATISFIED, (
            f"причина не называет третий исход словами: {why[:200]}")
    if "ось ПАМЯТИ" not in refused_err:
        return NOT_SATISFIED, (
            "вердикт есть в JSON, но человек у терминала его не видит: в stderr нет ни "
            "строки про ось памяти — два выхода одного читателя разошлись")

    other = measured.get("inbox-order") or {}
    if other.get("origin_memory") not in measured_verdicts:
        return NOT_SATISFIED, (
            f"на СОСТОЯВШЕЙСЯ сверке читатель тоже отвечает «не измерено» "
            f"(`{other.get('origin_memory')}`) — сторож, штампующий третий исход на всё, "
            f"снова делает отказ неотличимым от замера, только с другой стороны")
    return SATISFIED, (
        f"при ОТКАЗЕ сверки шаг 1 называет третий исход СВОЕЙ причиной "
        f"(`{card['origin_memory']}`: о записях цикла, «НЕ ИЗМЕРЕНО», видно и в JSON, и "
        f"в stderr), а на СОСТОЯВШЕЙСЯ сверке той же тетради даёт измеренный вердикт "
        f"`{other.get('origin_memory')}` — отказ и замер различимы в обе стороны")


def _probe_queue_reader_names_uncompared_order(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: ЧИТАТЕЛЬ ОЧЕРЕДИ называет НЕ СПРОШЕННЫЙ порядок копий СВОИМ словом.

    Предмет — остаток заказа G717 п. 3 (ADR-718). Цикл #861 дал третий исход со своей
    причиной оси ПАМЯТИ копий и сам же назвал, что население класса «ось гаснет вместе
    с соседом» измерено ровно на ОДНОЙ оси из ТРЁХ: порядок по ОТМЕТКАМ (`mark_order`,
    ADR-220) и порядок по СЛЕДУ ПЕРЕХОДОВ (`trail_order`, ADR-544) не проверялся вовсе.

    ЗАМЕР ДО ПРАВКИ (одноразовый репозиторий, копии карточки расходятся, статусы разные,
    на состоявшейся сверке порядок УСТАНАВЛИВАЕТСЯ): дверей отказа ЧЕТЫРЕ, ось памяти
    назвала себя в 4 из 4, ось порядка — в 0 из 4. На живой популяции (прод-трекер, 779
    карточек, та же команда шага 1 с неразрешимым ref): `origin_order` несут 0 из 779.

    ЧЕМ ВРЕДНО. ОТСУТСТВИЕ `origin_order` в контракте читателя означает «порядок НЕ
    МЕРИЛСЯ» — так у `agrees`/`stale`/`hidden`/`undelivered`, где второй копии для
    упорядочивания не существует. Значит «упорядочить было что, да спросить не удалось»
    печаталось как «упорядочивать нечего».

    **Меряется ИСХОД У ЧИТАТЕЛЯ, а не наличие функции.** Проба собирает одноразовый
    репозиторий, зовёт НАСТОЯЩУЮ команду шага 1 (`cmd_list --json`) ДВАЖДЫ — с
    неразрешимым ref и с разрешимым — и читает оба ответа. Подстрокой не проходит
    (ADR-333): требуется ПОЛЕ вердикта, не равное ни одному имени порядка у прибора, и
    причина про СВОЙ вопрос («какая копия дальше продвинулась»), а не фраза.

    **Контроль в обе стороны внутри самой пробы.** Читатель, штампующий третий исход на
    ЧЁМ УГОДНО, бесполезен так же, как молчащий: на СОСТОЯВШЕЙСЯ сверке той же пары
    копий он обязан дать вердикт ИЗ ИМЁН ПРИБОРА, а не третий исход.

    ТРИ ИСХОДА РАЗЛИЧИМЫ (инв. #17): читателя нет / не ввезён / предпосылка
    репозитория не обеспечена ⇒ `unmeasured` с причиной, а не `not_satisfied` и уж
    точно не `satisfied`.

    Оговорка названа вслух (та же, что у соседних проб #860/#861): `orchestrator_queue`
    ввозится из `repo_root`, а пакет `spa_core` остаётся того дерева, в котором идёт
    сама проба. Измеряемое свойство живёт в самом читателе, поэтому дискриминация на
    двух деревьях от этого не страдает.
    """
    import contextlib as _ctx
    import hashlib as _hl
    import importlib.util as _ilu
    import io as _io
    import json as _json
    import subprocess as _sp
    import tempfile as _tf

    root = repo_root or REPO_ROOT
    reader_path = os.path.join(root, "scripts", "orchestrator_queue.py")
    if not os.path.exists(reader_path):
        return UNMEASURED, f"{reader_path} не найден — читателя очереди НЕ ИЗМЕРИТЬ"
    for _p in (root, os.path.join(root, "scripts")):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    mod_name = "_probe_queue_order_" + _hl.sha256(root.encode()).hexdigest()[:12]
    try:
        spec = _ilu.spec_from_file_location(mod_name, reader_path)
        reader = _ilu.module_from_spec(spec)
        sys.modules[mod_name] = reader
        try:
            spec.loader.exec_module(reader)
        except BaseException:
            sys.modules.pop(mod_name, None)
            raise
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, (f"читатель очереди не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    try:
        import check_tracker_drift as _drift        # вокабуляр порядка — у прибора
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, f"прибор расхождения не ввезён ({exc}) — НЕ ИЗМЕРЕНО"

    #: Полный набор имён порядка У ПРИБОРА — собирается обходом, а не парой из головы:
    #: заведут четвёртое имя, и проба увидит его без правки.
    asked = {v for k, v in vars(_drift).items()
             if k.startswith("ORDER_") and isinstance(v, str)}
    if not asked:
        return UNMEASURED, ("вокабуляр порядка у прибора не найден — предпосылка пробы "
                            "НЕ ОБЕСПЕЧЕНА, об оси порядка судить нечем")

    # Имя ветки сцены — ВХОД, а не умолчание хоста (`init.defaultBranch` на
    # `ubuntu-latest` даёт `master`): фикстура, назвавшая потом `main`, была бы зелена
    # на Маке и красна в CI (`.claude/rules/deployment.md`).
    ref = "scene-main"
    missing_ref = "refs/heads/no-such-ref-for-this-probe"
    # Отметки — ПРЕДМЕТ оси (`mark_order` сравнивает именно их), поэтому литеральные и к
    # настенным часам не привязаны ничем.
    earlier, later = "2026-09-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"

    def _git(cwd, *args):
        return _sp.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       timeout=60)

    def _card(records, status, trail):
        head = ["---", "type: inbox", f"status: {status}",
                'title: "TASK — стоячий приказ владельца"', "status_trail:"]
        head += [f'  - "{t}"' for t in trail]
        head += ["---", "", "тело приказа", ""]
        return "\n".join(head) + "".join(
            f"\n## Цикл #{n} (замер цикла {n})\n\nчто сделано в цикле {n}\n"
            for n in records)

    def _ask(tracker, which_ref):
        argv = ["list", "--tracker-dir", tracker, "--ref", which_ref, "--json"]
        out, err = _io.StringIO(), _io.StringIO()
        with _ctx.redirect_stdout(out), _ctx.redirect_stderr(err):
            reader.cmd_list(reader.build_parser().parse_args(argv))
        return {c["id"]: c for c in _json.loads(out.getvalue())}, err.getvalue()

    try:
        with _tf.TemporaryDirectory() as tmp:
            rroot = os.path.join(tmp, "repo")
            tracker = os.path.join(rroot, _drift.TRACKER_REL)
            os.makedirs(tracker)
            r = _git(tmp, "init", "-q", "-b", ref, rroot)
            if r.returncode != 0:
                raise SPAError(f"git init: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
            for a in (["config", "user.email", "probe@example.com"],
                      ["config", "user.name", "probe"]):
                r = _git(rroot, *a)
                if r.returncode != 0:
                    raise SPAError(f"git {' '.join(a)}: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
            card = os.path.join(tracker, "inbox-order.md")
            with open(card, "w", encoding="utf-8") as fh:
                fh.write(_card([716, 717, 718], "new",
                               [f"{earlier} new -> new · queue.set_status · cycle-1"]))
            for a in (["add", "-A"], ["commit", "-q", "-m", "ref"]):
                r = _git(rroot, *a)
                if r.returncode != 0:
                    raise SPAError(f"git {' '.join(a)}: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
            with open(card, "w", encoding="utf-8") as fh:
                fh.write(_card([716], "in-progress",
                               [f"{earlier} new -> new · queue.set_status · cycle-1",
                                f"{later} new -> in-progress · queue.set_status · cycle-2"]))
            refused, refused_err = _ask(tracker, missing_ref)
            measured, _measured_err = _ask(tracker, ref)
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, (f"предпосылка пробы НЕ ОБЕСПЕЧЕНА ({type(exc).__name__}: {exc}) — "
                            f"вердикт читателя очереди НЕ ИЗМЕРЕН")

    card = refused.get("inbox-order")
    if card is None:
        return UNMEASURED, ("читатель не вернул карточку вовсе — предпосылка пробы НЕ "
                            "ОБЕСПЕЧЕНА, об оси порядка судить нечем")
    other = measured.get("inbox-order") or {}
    if other.get("origin_order") not in asked:
        return UNMEASURED, (
            f"на СОСТОЯВШЕЙСЯ сверке порядок не устанавливается вовсе "
            f"(`{other.get('origin_order')}`) — предпосылка пробы НЕ ОБЕСПЕЧЕНА: "
            f"контроль в обратную сторону был бы пустым")
    if "origin_order" not in card:
        return NOT_SATISFIED, (
            "при ОТКАЗЕ сверки у читателя очереди НЕТ оси порядка: в вердикте только "
            f"`origin_check={card.get('origin_check')}` — «упорядочить было что, да "
            "спросить не удалось» неотличимо от «упорядочивать нечего»")
    if card["origin_order"] in asked:
        return NOT_SATISFIED, (
            f"при отказе сверки читатель выдаёт имя ПРИБОРА `{card['origin_order']}` — "
            f"потребитель прочтёт «спросили и не решили» вместо «не спрашивали вовсе»")
    why = str(card.get("origin_order_detail") or "")
    if "ДАЛЬШЕ ПРОДВИНУЛАСЬ" not in why:
        return NOT_SATISFIED, (
            f"у оси порядка нет СВОЕЙ причины — она не говорит о своём вопросе: "
            f"{why[:200] or '(причины нет вовсе)'}")
    if "НЕ ИЗМЕРЕНО" not in why:
        return NOT_SATISFIED, f"причина не называет третий исход словами: {why[:200]}"
    if "ось ПОРЯДКА" not in refused_err:
        return NOT_SATISFIED, (
            "вердикт есть в JSON, но человек у терминала его не видит: в stderr нет ни "
            "строки про ось порядка — два выхода одного читателя разошлись")
    if why == str(card.get("origin_memory_detail") or ""):
        return NOT_SATISFIED, (
            "причина оси порядка дословно совпала с причиной оси памяти — это и есть "
            "наследование от соседа, только теперь с текстом")
    return SATISFIED, (
        f"при ОТКАЗЕ сверки шаг 1 называет третий исход оси порядка СВОИМ словом "
        f"(`{card['origin_order']}`, ни одно из имён прибора: {sorted(asked)}) и СВОЕЙ "
        f"причиной (о том, какая копия дальше продвинулась; видно и в JSON, и в stderr), "
        f"а на СОСТОЯВШЕЙСЯ сверке той же пары копий даёт вердикт прибора "
        f"`{other.get('origin_order')}` — отказ и замер различимы в обе стороны")


def _probe_queue_reader_names_which_order_axis_spoke(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: ЧИТАТЕЛЬ ОЧЕРЕДИ называет, КАКАЯ из двух осей порядка говорила.

    Предмет — заказ G718 п. 1 (ADR-719). Осей порядка две и они независимы: отметка о
    движении (`mark_order`, ADR-220) и след переходов (`trail_order`, ADR-544). До цикла
    #863 до читателя доезжал ОДИН вердикт, а «какая мерка говорила, а какая молчала»
    читалось только из ПРОЗЫ `order_detail` — то есть разбором подстроки, который
    запрещён (ADR-333).

    ЗАМЕР ДО ПРАВКИ (живой прод-трекер, origin/main 55eb3db5c, 787 карточек, расошедшихся
    пар 170): вердикт `unmeasured` несли 112 карточек, и под ним стояли ДВА РАЗНЫХ
    состояния — `neither_decided` 108 (штатная тишина) и `axes_disagree` 4 (тревога
    fail-CLOSED, предмет ADR-544; одна из четырёх — карточка РЕШЕНИЯ ВЛАДЕЛЬЦА). Все 27
    вердиктов `tree_newer` стояли на `mark_only`, то есть на одной оси, и именно той,
    которая на 8 живых парах дала неверный `tree_newer` из джиттера писателя 68–175 мкс.
    Полей, называющих ось поимённо, не было ни одного.

    **Меряется ИСХОД У ЧИТАТЕЛЯ, а не наличие функции.** Проба собирает одноразовый
    репозиторий ДВАЖДЫ — на паре копий, где оси РАСХОДЯТСЯ, и на паре, где не решает ни
    одна, — зовёт НАСТОЯЩУЮ команду шага 1 (`cmd_list --json`) и сверяет два ответа.

    **Подстрокой не проходит (ADR-333):** требуется ПОЛЕ, значение которого — точный член
    вокабуляра базиса у прибора (вокабуляр собирается ОБХОДОМ, а не парой из головы), и
    это значение обязано НЕ содержаться в прозе того же вердикта.

    **Контроль в обе стороны внутри самой пробы.** Мало чтобы поле было: на двух парах с
    ОДНИМ вердиктом `unmeasured` базисы обязаны РАЗЛИЧАТЬСЯ (иначе поле есть, а ответа
    нет), и обратно — за дверью отказа сверки базис обязан быть словом ЧИТАТЕЛЯ, а не
    именем прибора (иначе «не спрашивали» снова читается как «спросили и не узнали»).

    ТРИ ИСХОДА РАЗЛИЧИМЫ (инв. #17): читателя нет / не ввезён / предпосылка репозитория
    не обеспечена ⇒ `unmeasured` с причиной, а не `not_satisfied` и уж точно не
    `satisfied`.

    Оговорка названа вслух (та же, что у соседних проб #860…#862): `orchestrator_queue`
    ввозится из `repo_root`, а пакет `spa_core` остаётся того дерева, в котором идёт сама
    проба. Измеряемое свойство живёт в самом читателе, поэтому дискриминация на двух
    деревьях от этого не страдает.
    """
    import hashlib as _hl
    import importlib.util as _ilu

    root = repo_root or REPO_ROOT
    reader_path = os.path.join(root, "scripts", "orchestrator_queue.py")
    if not os.path.exists(reader_path):
        return UNMEASURED, f"{reader_path} не найден — читателя очереди НЕ ИЗМЕРИТЬ"
    drift_path = os.path.join(root, "scripts", "check_tracker_drift.py")
    if not os.path.exists(drift_path):
        return UNMEASURED, f"{drift_path} не найден — прибор расхождения НЕ ИЗМЕРИТЬ"
    for _p in (root, os.path.join(root, "scripts")):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    mod_name = "_probe_queue_basis_" + _hl.sha256(root.encode()).hexdigest()[:12]

    # ── ПРИБОР — ИЗ ИЗМЕРЯЕМОГО ДЕРЕВА, а не тот, что уже в `sys.modules` ──────────
    #
    # Контур пробы — ДВА файла: читатель очереди и прибор расхождения (вокабуляр базиса
    # живёт у второго). Читателя проба грузит ПО ПУТИ, а прибор до цикла #863 ввозила
    # по ИМЕНИ — и этим мерила СОСЕДНЮЮ дверь: `import check_tracker_drift` отдаёт
    # копию, попавшую в `sys.modules` первой, то есть прибор ТОГО дерева, где идёт сама
    # проба. Дефект нашёл контроль собственной батареи (звенья 4, 7, 12 были зелены при
    # ПОЛНОСТЬЮ ослеплённом приборе) — ровно класс «тест мерит соседнюю дверь, потому
    # что в целевую ведёт тот же зов».
    #
    # Подменяется ИМЕННО имя `check_tracker_drift`: читатель ввозит прибор по нему же,
    # поэтому иначе проба и читатель смотрели бы на РАЗНЫЕ приборы. Прежнее значение
    # возвращается в `finally` — проба меряет, а не меняет окружение зовущего.
    _saved_drift = sys.modules.get("check_tracker_drift")
    try:
        try:
            _spec_d = _ilu.spec_from_file_location("check_tracker_drift", drift_path)
            _drift = _ilu.module_from_spec(_spec_d)
            sys.modules["check_tracker_drift"] = _drift
            _spec_d.loader.exec_module(_drift)
        except Exception as exc:                    # noqa: BLE001
            return UNMEASURED, (f"прибор расхождения не ввезён "
                                f"({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")
        try:
            spec = _ilu.spec_from_file_location(mod_name, reader_path)
            reader = _ilu.module_from_spec(spec)
            sys.modules[mod_name] = reader
            try:
                spec.loader.exec_module(reader)
            except BaseException:
                sys.modules.pop(mod_name, None)
                raise
        except Exception as exc:                    # noqa: BLE001
            return UNMEASURED, (f"читатель очереди не ввезён ({type(exc).__name__}: {exc}) — "
                                f"НЕ ИЗМЕРЕНО")

        #: Полный вокабуляр БАЗИСА у прибора — обходом, а не парой из головы: заведут
        #: шестое слово, и проба увидит его без правки.
        bases = {v for k, v in vars(_drift).items()
                 if k.startswith("BASIS_") and isinstance(v, str)}
        if not bases:
            return NOT_SATISFIED, (
                "у прибора расхождения НЕТ вокабуляра базиса (`BASIS_*`) — значит ответ на "
                "«какая из двух осей говорила» не производит никто, и читателю его взять "
                "негде: ровно замер до ADR-719")
        return _queue_order_basis_outcome(_drift, reader, bases)
    finally:
        if _saved_drift is None:
            sys.modules.pop("check_tracker_drift", None)
        else:
            sys.modules["check_tracker_drift"] = _saved_drift


def _queue_order_basis_outcome(_drift, reader, bases: set) -> tuple[str, str]:
    """Исход у читателя на ДВУХ парах копий + за дверью отказа (тело пробы ADR-719).

    Отдельная функция ровно затем, чтобы подмена прибора в `sys.modules` снималась
    `finally` у зовущего, а не повторялась на каждом `return` замера.
    """
    import contextlib as _ctx
    import io as _io
    import json as _json
    import subprocess as _sp
    import tempfile as _tf

    ref = "scene-main"
    missing_ref = "refs/heads/no-such-ref-for-this-probe"
    # Отметки — ПРЕДМЕТ оси (`mark_order` сравнивает именно их), поэтому литеральные и к
    # настенным часам не привязаны ничем.
    earlier, later = "2026-09-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"

    def _git(cwd, *args):
        return _sp.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       timeout=60)

    def _card(status, trail, body):
        head = ["---", "type: inbox", f"status: {status}",
                'title: "TASK — карточка сцены"']
        if trail:
            head.append("status_trail:")
            head += [f'  - "{t}"' for t in trail]
        head += ["---", "", body, ""]
        return "\n".join(head)

    #: Две пары копий, дающие ОДИН вердикт `unmeasured` и РАЗНЫЙ базис. Пары подобраны по
    #: самим мерам: оси расходятся, когда отметка дерева позже, а след говорит «впереди
    #: origin»; не решает ни одна, когда у копии ref отметок нет и статусы совпадают.
    scenes = {
        "РАСХОДЯТСЯ": (
            _card("in-progress",
                  [f"{later} new -> in-progress · queue.set_status · c1"], "дерево"),
            _card("done", [f"{earlier} new -> done · queue.set_status · c2"], "ref")),
        "НЕ РЕШИЛА НИ ОДНА": (
            _card("new", [f"{earlier} new -> new · queue.set_status · c1"], "дерево"),
            _card("new", [], "ref")),
    }

    def _ask(tracker, which_ref):
        argv = ["list", "--tracker-dir", tracker, "--ref", which_ref, "--json"]
        out, err = _io.StringIO(), _io.StringIO()
        with _ctx.redirect_stdout(out), _ctx.redirect_stderr(err):
            reader.cmd_list(reader.build_parser().parse_args(argv))
        return {c["id"]: c for c in _json.loads(out.getvalue())}, err.getvalue()

    answers: dict[str, dict] = {}
    errs: dict[str, str] = {}
    refused_card: dict = {}
    try:
        for name, (tree_text, origin_text) in scenes.items():
            with _tf.TemporaryDirectory() as tmp:
                rroot = os.path.join(tmp, "repo")
                tracker = os.path.join(rroot, _drift.TRACKER_REL)
                os.makedirs(tracker)
                r = _git(tmp, "init", "-q", "-b", ref, rroot)
                if r.returncode != 0:
                    raise SPAError(f"git init: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
                for a in (["config", "user.email", "probe@example.com"],
                          ["config", "user.name", "probe"]):
                    r = _git(rroot, *a)
                    if r.returncode != 0:
                        raise SPAError(f"git {' '.join(a)}: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
                card_path = os.path.join(tracker, "inbox-order.md")
                with open(card_path, "w", encoding="utf-8") as fh:
                    fh.write(origin_text)
                for a in (["add", "-A"], ["commit", "-q", "-m", "ref"]):
                    r = _git(rroot, *a)
                    if r.returncode != 0:
                        raise SPAError(f"git {' '.join(a)}: {r.stderr.strip()}", code="PROBE_SCENE_GIT_FAILED")
                with open(card_path, "w", encoding="utf-8") as fh:
                    fh.write(tree_text)
                got, err = _ask(tracker, ref)
                answers[name] = got.get("inbox-order") or {}
                errs[name] = err
                if name == "РАСХОДЯТСЯ":
                    door, _door_err = _ask(tracker, missing_ref)
                    refused_card = door.get("inbox-order") or {}
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, (f"предпосылка пробы НЕ ОБЕСПЕЧЕНА ({type(exc).__name__}: {exc}) — "
                            f"вердикт читателя очереди НЕ ИЗМЕРЕН")

    for name, card in answers.items():
        if not card:
            return UNMEASURED, (f"на сцене «{name}» читатель не вернул карточку вовсе — "
                                f"предпосылка пробы НЕ ОБЕСПЕЧЕНА")
        if card.get("origin_order") != _drift.ORDER_UNMEASURED:
            return UNMEASURED, (
                f"на сцене «{name}» вердикт порядка не `{_drift.ORDER_UNMEASURED}`, а "
                f"`{card.get('origin_order')}` — предпосылка пробы НЕ ОБЕСПЕЧЕНА: "
                f"различать базисом под ОДНИМ вердиктом было бы нечего")

    for name, card in answers.items():
        if "origin_order_basis" not in card:
            return NOT_SATISFIED, (
                f"на сцене «{name}» у читателя НЕТ поля `origin_order_basis`: вердикт "
                f"`{card.get('origin_order')}` один на «обе оси решили и РАСХОДЯТСЯ» и "
                f"«ни одна не решила» — чем он добыт, машинно не читается (замер 14.10: "
                f"112 карточек = 108 тишин + 4 тревоги)")
        if card["origin_order_basis"] not in bases:
            return NOT_SATISFIED, (
                f"на сцене «{name}» базис `{card['origin_order_basis']}` не входит в "
                f"вокабуляр прибора {sorted(bases)} — значение не объявлено, читать его "
                f"машинно нельзя")
        for axis in ("origin_order_mark", "origin_order_trail"):
            if axis not in card:
                return NOT_SATISFIED, (
                    f"на сцене «{name}» нет поля `{axis}` — базис есть, а вердикт самой "
                    f"оси назвать нечем")

    clash, quiet = answers["РАСХОДЯТСЯ"], answers["НЕ РЕШИЛА НИ ОДНА"]
    if clash["origin_order_basis"] == quiet["origin_order_basis"]:
        return NOT_SATISFIED, (
            f"базис ОДИН И ТОТ ЖЕ (`{clash['origin_order_basis']}`) на расхождении осей и "
            f"на их молчании — поле есть, а ответа на «какая мерка говорила» нет: тот же "
            f"дефект, только под новым именем")
    if clash["origin_order_mark"] == clash["origin_order_trail"]:
        return NOT_SATISFIED, (
            f"на сцене расхождения оси названы ОДНИМ вердиктом "
            f"(`{clash['origin_order_mark']}`) — расходиться им тогда нечем, значит поля "
            f"не несут вердикт КАЖДОЙ оси")
    if clash["origin_order_basis"] in str(clash.get("origin_order_detail") or ""):
        return NOT_SATISFIED, (
            "базис читается как подстрока прозы — значит носитель ответа по-прежнему "
            "проза, а её разбор запрещён (ADR-333)")
    if not refused_card:
        return UNMEASURED, ("за дверью отказа сверки читатель не вернул карточку — "
                            "обратный контроль НЕ ИЗМЕРЕН")
    door_basis = refused_card.get("origin_order_basis")
    if door_basis is None:
        return NOT_SATISFIED, (
            "за дверью отказа сверки базиса нет вовсе — отсутствие поля читается как "
            "«ось не спрашивают у этого класса», то есть как штатная тишина (ADR-718)")
    if door_basis in bases:
        return NOT_SATISFIED, (
            f"за дверью отказа читатель выдаёт базис ПРИБОРА `{door_basis}` — «ни одну "
            f"ось не спрашивали» прочтётся как «спросили обе и не узнали»")
    if "ОСИ РАСХОДЯТСЯ" not in errs["РАСХОДЯТСЯ"]:
        return NOT_SATISFIED, (
            "расхождение осей есть в JSON, но человек у терминала его не видит: в stderr "
            "нет строки про расхождение — два выхода одного читателя разошлись")
    if "ОСИ РАСХОДЯТСЯ" in errs["НЕ РЕШИЛА НИ ОДНА"]:
        return NOT_SATISFIED, (
            "строка про расхождение осей печатается и там, где оси не расходятся — "
            "сторож, кричащий всегда, молчит и тогда, когда тревога настоящая (урок #243)")
    return SATISFIED, (
        f"шаг 1 называет ЧЕМ добыт вердикт порядка: под одним `{_drift.ORDER_UNMEASURED}` "
        f"базисы РАЗНЫЕ (`{clash['origin_order_basis']}` против "
        f"`{quiet['origin_order_basis']}`, оба из вокабуляра прибора {sorted(bases)}), "
        f"вердикт каждой оси назван отдельно "
        f"(`{clash['origin_order_mark']}` / `{clash['origin_order_trail']}`), за дверью "
        f"отказа стои́т слово ЧИТАТЕЛЯ `{door_basis}`, а расхождение осей видно и в "
        f"stderr — и только там, где оно есть")


def _probe_card_claim_measures_the_worker(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: ЗАХВАТ КАРТОЧКИ мерит РАБОТНИКА, а не запускателя (ADR-721).

    Предмет — карточка `inbox-zahvat-kartochki-merit-zapuskatelya-a-ne` (находка цикла
    #864). ЗАМЕР ДО ПРАВКИ, живая очередь 14.10: держатель приказа Portfolio CIO
    `cycle-69075` МЁРТВ (`ps -p` rc=1), его РАБОТНИК `claude` pid 69661 ЖИВ (`ppid=1`) и
    правил своё дерево за 4 с до замера — а шаг 0a-ГОЛОД отвечал `stale` «держателя НЕТ»
    и выдавал ЖИВОЙ приказ владельца второй сессии. ADR-720 закрыл эту ось у ЗАМКА
    цикла; захват карточки остался на прежней, мёртвой оси.

    **Меряется ИСХОД У ЧИТАТЕЛЯ, а не наличие функции.** Проба собирает одноразовую
    сцену «ярлык держателя мёртв» ДВАЖДЫ и зовёт НАСТОЯЩИЙ `gather` шага 0b: один раз с
    живым носителем метки, другой — без него. Критерий выполнен, только если ответы
    РАЗЛИЧАЮТСЯ в нужную сторону (`claimed` против `stale`). Один ответ без второго
    ничего не доказывает: вердикт `claimed` можно получить и просто свежестью.

    **Подстрокой не проходит (ADR-333):** требуется ПОЛЕ `worker_axis`, значение которого
    — точный член вокабуляра ЧИТАТЕЛЯ, а вокабуляр собирается ОБХОДОМ (`W_*`), а не
    парой слов из головы.

    **Контроль в обе стороны внутри самой пробы.** Мало чтобы живой работник держал
    карточку: измеренно отсутствующий обязан её ОТДАВАТЬ (иначе защита — вечный замок),
    неизмеримость обязана быть третьим исходом (`unchecked`, инв. #17), а повисший
    работник обязан отпускать карточку по своему бюджету.

    ТРИ ИСХОДА РАЗЛИЧИМЫ: читателя нет / не ввезён / у него нет вокабуляра оси ⇒
    `unmeasured` или `not_satisfied` с названной причиной, и никогда `satisfied`.

    Оговорка названа вслух: живость работника здесь ВХОД (`worker=`), а не живая ОС.
    Иначе проба меняла бы вердикт от того, кто сегодня занял номер, и краснела бы на
    чужом хосте (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»). Сцена с настоящим
    живым носителем метки невозможна по измеренной причине: прибор ищет метку в выводе
    `ps -A -Ewww`, где окружение читается не у всех процессов (замер 14.10 на рабочем
    Маке: 74 строки из 644), и поднятый специально `/bin/sleep` метку не показывает.
    """
    import importlib.util as _ilu
    import tempfile as _tf
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    root = repo_root or REPO_ROOT
    guard_path = os.path.join(root, "scripts", "check_card_claim.py")
    if not os.path.exists(guard_path):
        return UNMEASURED, f"{guard_path} не найден — шаг 0b НЕ ИЗМЕРИТЬ"
    lock_path = os.path.join(root, "scripts", "orchestrator_cycle_lock.py")
    if not os.path.exists(lock_path):
        return UNMEASURED, f"{lock_path} не найден — бюджет работника НЕ ИЗМЕРИТЬ"
    try:
        spec = _ilu.spec_from_file_location("_probe_c865_card_claim", guard_path)
        guard = _ilu.module_from_spec(spec)          # type: ignore[arg-type]
        spec.loader.exec_module(guard)               # type: ignore[union-attr]
        spec_l = _ilu.spec_from_file_location("_probe_c865_cycle_lock", lock_path)
        lock = _ilu.module_from_spec(spec_l)         # type: ignore[arg-type]
        spec_l.loader.exec_module(lock)              # type: ignore[union-attr]
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"шаг 0b не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")

    #: Вокабуляр оси — ОБХОДОМ у читателя, а не парой из головы: заведут пятое слово,
    #: и проба увидит его без правки.
    axes = {v for k, v in vars(guard).items()
            if k.startswith("W_") and isinstance(v, str)}
    if not axes:
        return NOT_SATISFIED, (
            "у шага 0b НЕТ вокабуляра оси РАБОТНИКА (`W_*`) — значит ответ «кто именно "
            "жив, запускатель или работник» не производит никто: ровно замер до ADR-721")
    try:
        sibling = guard.load_sibling()
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сосед шага 0a не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    ttl = float(getattr(lock, "DEFAULT_WORKER_TTL_SEC", 0.0) or 0.0)
    if ttl <= 0.0:
        return NOT_SATISFIED, ("бюджет работника у замка не объявлен — без срока ось "
                               "РАБОТНИКА стала бы вечным замком, а не защитой")

    now = _dt.now(_tz.utc).replace(microsecond=0)
    label, mark = "cycle-69075", "orchestrator-69075-PROBE"

    #: Проза сцены НАМЕРЕННО не содержит самого слова оси: иначе проба прошла бы и у
    #: читателя, который слово оси лишь ПЕРЕСКАЗЫВАЕТ прозой, не несущей машинного поля.
    #: Ровно это условие и проверяется ниже сравнением поля с прозой (ADR-333).
    _SCENE_WHY = "проба приёмки: состояние носителя метки задано входом сцены"

    def _ask(axis):
        def _probe(run_id):
            if not str(run_id or "").strip():
                return "not_declared", "метки нет", None
            return axis, _SCENE_WHY, ttl
        return _probe

    try:
        with _tf.TemporaryDirectory(prefix="probe_c865_") as tmp:
            tracker = os.path.join(tmp, "tracker")
            os.makedirs(tracker)
            log = os.path.join(tmp, "session_changes.jsonl")
            with open(log, "w", encoding="utf-8") as fh:
                fh.write("")

            def _scene(age_sec, with_mark=True):
                at = (now - _td(seconds=age_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
                rows = ["---\n", "trackerStatus:\n", "  type: inbox\n",
                        "title: сцена приёмки\n", "status: in-progress\n",
                        f"claimed_by: {label}\n", f"claimed_at: {at}\n"]
                if with_mark:
                    rows.append(f"claimed_run_id: {mark}\n")
                rows += ["---\n", "\nтело\n"]
                with open(os.path.join(tracker, "inbox-scene.md"), "w",
                          encoding="utf-8") as fh:
                    fh.write("".join(rows))

            def _verdict(axis, age_sec, with_mark=True):
                _scene(age_sec, with_mark)
                return guard.gather("inbox-scene", log=log, tracker_dir=tracker,
                                    sibling=sibling, self_session="probe-c865", now=now,
                                    ps=lambda _pid: (1, ""), self_anchor=(41865, ""),
                                    shared_trees=(), worker=_ask(axis))

            #: Возраст сцены — СТАРШЕ окна свежести шага 0b: внутри окна сильный захват
            #: блокирует и без оси РАБОТНИКА, то есть сцена отвечала бы не на свой вопрос.
            stale_age = float(guard.DEFAULT_GRACE_HOURS) * 3600.0 + 1800.0
            alive = _verdict(guard.W_ALIVE, stale_age)
            gone = _verdict(guard.W_GONE, stale_age)
            unmeas = _verdict(guard.W_UNMEASURED, stale_age)
            over = _verdict(guard.W_ALIVE, ttl + 1.0)
            plain = _verdict(guard.W_ALIVE, stale_age, with_mark=False)
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сцена захвата не собралась ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")

    def _front(report):
        rows = [c for c in report.get("claims") or []
                if c.get("source") == "frontmatter"]
        return rows[0] if len(rows) == 1 else None

    rec = _front(alive)
    if rec is None:
        return NOT_SATISFIED, ("шаг 0b не выдал ровно одной находки по frontmatter на "
                               "сцене «держатель мёртв» — предмет пробы не найден")
    if alive["verdict"] != guard.CLAIMED:
        return NOT_SATISFIED, (
            f"ЖИВОЙ работник не держит карточку: вердикт `{alive['verdict']}` вместо "
            f"`{guard.CLAIMED}` — живая работа снова отдаётся второй сессии (замер 14.10)")
    if gone["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"работника измеренно НЕТ, а карточка не отдаётся: вердикт "
            f"`{gone['verdict']}` вместо `{guard.STALE}` — это вечный замок, а не защита")
    if unmeas["verdict"] != guard.UNCHECKED:
        return NOT_SATISFIED, (
            f"ось НЕ ИЗМЕРЕНА, а вердикт `{unmeas['verdict']}` вместо "
            f"`{guard.UNCHECKED}` — неизмеримость выдана за ответ (инв. #17)")
    if over["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"повисший работник держит карточку дольше своего бюджета "
            f"({ttl / 3600.0:.2f}ч): вердикт `{over['verdict']}` — очередь заморожена")
    if plain["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"карточка БЕЗ метки работника ведёт себя иначе, чем до правки: вердикт "
            f"`{plain['verdict']}` вместо `{guard.STALE}` — правка не дополняющая")
    axis_value = rec.get("worker_axis")
    if axis_value not in axes:
        return NOT_SATISFIED, (
            f"поле `worker_axis` несёт {axis_value!r} — вне вокабуляра читателя "
            f"{sorted(axes)}: ответ есть только в прозе, а разбор подстрокой запрещён")
    if str(axis_value) in str(rec.get("worker_detail") or ""):
        return NOT_SATISFIED, (
            "слово оси содержится в прозе того же вердикта — проба прошла бы подстрокой, "
            "то есть не проверяла бы поле (ADR-333)")
    if rec.get("worker_run_id") != mark:
        return NOT_SATISFIED, (
            f"метка держателя не доехала до находки: `worker_run_id`="
            f"{rec.get('worker_run_id')!r} при объявленной {mark!r}")
    writer = _front(plain)
    if writer is None or writer.get("worker_axis") != guard.W_NOT_DECLARED:
        return NOT_SATISFIED, (
            "карточка без метки не помечена `not_declared` — «ось не мерилась» "
            "неотличима от «спросили и работника нет»")
    if "claimed_run_id" not in tuple(getattr(guard, "_CLAIM_KEYS", ())):
        return NOT_SATISFIED, (
            "метка не объявлена строкой захвата (`_CLAIM_KEYS`) — она переживёт подъём, "
            "и мёртвый работник прежнего держателя будет читаться живым")
    return SATISFIED, (
        f"шаг 0b мерит РАБОТНИКА: на сцене «держатель `{label}` мёртв» живой носитель "
        f"метки даёт `{alive['verdict']}` (ось `{rec.get('worker_axis')}`, метка из "
        f"карточки), измеренное отсутствие — `{gone['verdict']}`, неизмеримость — "
        f"`{unmeas['verdict']}`, за бюджетом {ttl / 3600.0:.2f}ч — `{over['verdict']}`, "
        f"а запись без метки — `{plain['verdict']}` (ось `{guard.W_NOT_DECLARED}`, то "
        f"есть прежнее поведение); вокабуляр оси {sorted(axes)} собран обходом, подстрокой "
        f"проба не проходит")


def _probe_journal_claim_measures_the_worker(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: ЖУРНАЛЬНЫЙ захват мерит РАБОТНИКА, а не запускателя (ADR-722, G721 п. 1).

    Предмет — карточка `inbox-zhurnal-obyavlenii-merit-zapuskatelya-vt` (находка цикла
    #865). ADR-721 довёл ось РАБОТНИКА до `claimed_run_id` во frontmatter, но захват
    живёт в ТРЁХ записях, и третья — строка журнала объявлений — метки не несла вовсе:
    `log_session_change.record` её не писал. ЗАМЕР ДО ПРАВКИ: объявление цикла #864 легло
    как `[cycle-27063]` — pid ЗАПУСКАТЕЛЯ, хотя писал его работник 27717; объявление
    цикла #866 — `[cycle-24396]` при работнике 24942. Сессия, взявшая карточку объявлением
    (а такой захват инструмент читает как сильный), оставалась на мёртвой оси.

    **Меряется ИСХОД У ЧИТАТЕЛЯ на сцене, где захват есть ТОЛЬКО в журнале** (во
    frontmatter метки нет вовсе — иначе проба отвечала бы на вопрос ADR-721). Сцена
    собирается ПЯТЬ раз и каждый раз зовётся НАСТОЯЩИЙ `gather` шага 0b; критерий
    выполнен, только если ответы РАЗЛИЧАЮТСЯ в нужную сторону:

      живой носитель метки ⇒ `claimed` · измеренное отсутствие ⇒ `stale` ·
      неизмеримость ⇒ `unchecked` (инв. #17) · за бюджетом работника ⇒ `stale` ·
      запись БЕЗ метки ⇒ `stale` с осью `not_declared`, то есть прежнее поведение.

    **Писатель проверяется отдельно от читателя.** Мало, чтобы читатель УМЕЛ читать поле:
    если его никто не пишет, ось журнальных записей навсегда `not_declared`. Поэтому
    проба зовёт настоящий `log_session_change.record` и требует (а) метку на СВОЕЙ записи
    и (б) ОТСУТСТВИЕ метки на записи от имени ЧУЖОЙ сессии — штамп своей личности поверх
    чужого ярлыка уже стоил этому репозиторию выключенной защиты от коллизий
    (`agent-claim-guard-blind-when-session-pid-is-set`).

    **Имя поля — ОДНО.** Проба берёт его у писателя (`RUN_ID_FIELD`) и требует, чтобы
    читатель отдавал ровно его (`run_id_field()`): две копии строки переживут
    переименование молча, и ось тихо вернётся к прежнему поведению, которое выглядит как
    «так и было задумано».

    **Подстрокой не проходит (ADR-333):** требуется ПОЛЕ `worker_axis` со значением из
    вокабуляра ЧИТАТЕЛЯ, собранного ОБХОДОМ (`W_*`), и проза того же вердикта не вправе
    содержать слово оси.

    ТРИ ИСХОДА РАЗЛИЧИМЫ: читателя/писателя нет или не ввезли ⇒ `unmeasured` с названной
    причиной, и никогда `satisfied`.

    Оговорка названа вслух: живость работника здесь ВХОД (`worker=`), а не живая ОС —
    иначе проба меняла бы вердикт от того, кто сегодня занял номер
    (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»). Сцену с настоящим живым
    носителем метки воспроизвести нельзя по ИЗМЕРЕННОЙ причине: окружение в `ps -A -Ewww`
    читается у 74 строк из 651 (замер 14.10, `scripts/worker_axis_census.py`), и у
    специально поднятого `/bin/sleep` метка не видна.
    """
    import importlib.util as _ilu
    import json as _json
    import tempfile as _tf
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    root = repo_root or REPO_ROOT
    paths = {"guard": os.path.join(root, "scripts", "check_card_claim.py"),
             "lock": os.path.join(root, "scripts", "orchestrator_cycle_lock.py"),
             "writer": os.path.join(root, "scripts", "log_session_change.py")}
    for name, pth in paths.items():
        if not os.path.exists(pth):
            return UNMEASURED, f"{pth} не найден — ось журнального захвата НЕ ИЗМЕРИТЬ"
    mods = {}
    try:
        for name, pth in paths.items():
            spec = _ilu.spec_from_file_location(f"_probe_c866_{name}", pth)
            mod = _ilu.module_from_spec(spec)        # type: ignore[arg-type]
            spec.loader.exec_module(mod)             # type: ignore[union-attr]
            mods[name] = mod
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"модуль не ввезён ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")
    guard, lock, writer = mods["guard"], mods["lock"], mods["writer"]

    #: Имя поля — у ПИСАТЕЛЯ схемы. Своей копии строки у пробы нет по той же причине,
    #: по которой её нет у читателя.
    field = str(getattr(writer, "RUN_ID_FIELD", "") or "").strip()
    if not field:
        return NOT_SATISFIED, ("писатель журнала не объявил имя поля метки работника "
                               "(`RUN_ID_FIELD`) — журнальный захват мерить нечем")
    reader_field, reader_why = guard.run_id_field(announcer=writer)
    if reader_field != field:
        return NOT_SATISFIED, (
            f"читатель и писатель называют поле по-разному: {reader_field!r} против "
            f"{field!r} ({reader_why}) — вторая копия строки переживёт переименование молча")

    axes = {v for k, v in vars(guard).items()
            if k.startswith("W_") and isinstance(v, str)}
    if not axes:
        return NOT_SATISFIED, (
            "у шага 0b НЕТ вокабуляра оси РАБОТНИКА (`W_*`) — ответ «кто именно жив, "
            "запускатель или работник» не производит никто")
    try:
        sibling = guard.load_sibling()
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сосед шага 0a не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    ttl = float(getattr(lock, "DEFAULT_WORKER_TTL_SEC", 0.0) or 0.0)
    if ttl <= 0.0:
        return NOT_SATISFIED, ("бюджет работника у замка не объявлен — без срока ось "
                               "РАБОТНИКА стала бы вечным замком, а не защитой")

    now = _dt.now(_tz.utc).replace(microsecond=0)
    label, mark = "cycle-27063", "orchestrator-27063-PROBE"
    _SCENE_WHY = "проба приёмки: состояние носителя метки задано входом сцены"

    def _ask(axis):
        def _probe(run_id):
            if not str(run_id or "").strip():
                return "not_declared", "метки нет", None
            return axis, _SCENE_WHY, ttl
        return _probe

    try:
        with _tf.TemporaryDirectory(prefix="probe_c866_") as tmp:
            tracker = os.path.join(tmp, "tracker")
            os.makedirs(tracker)
            # Карточка БЕЗ захвата во frontmatter: предмет пробы — журнальная запись.
            card = os.path.join(tracker, "inbox-scene.md")
            with open(card, "w", encoding="utf-8") as fh:
                fh.write("---\ntrackerStatus:\n  type: inbox\ntitle: сцена приёмки\n"
                         "status: in-progress\n---\n\nтело\n")

            def _verdict(axis, age_sec, with_mark=True):
                at = (now - _td(seconds=age_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
                entry = {"ts": at, "session": label, "summary": "сцена приёмки",
                         "files": [], "verified": "", "card": "inbox-scene",
                         "card_state": "claim", "session_pid": 27063,
                         "session_pid_start": "Wed Oct 14 00:00:00 2026"}
                if with_mark:
                    entry[field] = mark
                log = os.path.join(tmp, f"log_{axis}_{int(age_sec)}_{with_mark}.jsonl")
                with open(log, "w", encoding="utf-8") as fh:
                    fh.write(_json.dumps(entry, ensure_ascii=False) + "\n")
                return guard.gather("inbox-scene", log=log, tracker_dir=tracker,
                                    sibling=sibling, self_session="probe-c866", now=now,
                                    ps=lambda _pid: (1, ""), self_anchor=(41866, ""),
                                    shared_trees=(), worker=_ask(axis))

            stale_age = float(guard.DEFAULT_GRACE_HOURS) * 3600.0 + 1800.0
            alive = _verdict(guard.W_ALIVE, stale_age)
            gone = _verdict(guard.W_GONE, stale_age)
            unmeas = _verdict(guard.W_UNMEASURED, stale_age)
            over = _verdict(guard.W_ALIVE, ttl + 1.0)
            plain = _verdict(guard.W_ALIVE, stale_age, with_mark=False)

            # ── ПИСАТЕЛЬ: метка на своей записи и НИКОГДА на чужой ──────────────
            # ОКРУЖЕНИЕ СЦЕНЫ ОБЪЯВЛЕНО, а не унаследовано от хоста, и это не
            # аккуратность, а условие осмысленности замера: у писателя решение «ставить
            # метку» зависит от наличия `SPA_RUN_ID`, которого в CI нет. Унаследуй проба
            # окружение — порванное звено «писатель метит ЧУЖУЮ запись» на машине БЕЗ
            # метки выглядело бы целым (метки нет ни на одной записи), то есть проба
            # меняла бы вердикт от хоста, а не от кода (`.claude/rules/deployment.md`
            # § «GIT-ОКРУЖЕНИЕ в тестах»). Найдено собственным прогоном в голом
            # окружении, а не рассуждением.
            wlog = os.path.join(tmp, "writer.jsonl")
            _saved = os.environ.get(writer.RUN_ID_VAR)
            os.environ[writer.RUN_ID_VAR] = mark
            try:
                own = writer.record("проба приёмки: своя запись", [], "", log=wlog)
                foreign = writer.record("проба приёмки: чужая запись", [], "", log=wlog,
                                        session="cycle-SOMEBODY-ELSE")
            finally:
                if _saved is None:
                    os.environ.pop(writer.RUN_ID_VAR, None)
                else:
                    os.environ[writer.RUN_ID_VAR] = _saved
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сцена захвата не собралась ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")

    def _row(report):
        rows = [c for c in report.get("claims") or []
                if c.get("source") == "announce-log"]
        return rows[0] if len(rows) == 1 else None

    rec = _row(alive)
    if rec is None:
        return NOT_SATISFIED, ("шаг 0b не выдал ровно одной находки по журналу на сцене "
                               "«захват только в журнале» — предмет пробы не найден")
    if alive["verdict"] != guard.CLAIMED:
        return NOT_SATISFIED, (
            f"ЖИВОЙ работник не держит карточку, взятую ОБЪЯВЛЕНИЕМ: вердикт "
            f"`{alive['verdict']}` вместо `{guard.CLAIMED}` — идущая работа отдаётся "
            f"второй сессии ровно так же, как до ADR-721 отдавалась по frontmatter")
    if gone["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"работника измеренно НЕТ, а карточка не отдаётся: вердикт "
            f"`{gone['verdict']}` вместо `{guard.STALE}` — это вечный замок, а не защита")
    if unmeas["verdict"] != guard.UNCHECKED:
        return NOT_SATISFIED, (
            f"ось НЕ ИЗМЕРЕНА, а вердикт `{unmeas['verdict']}` вместо "
            f"`{guard.UNCHECKED}` — неизмеримость выдана за ответ (инв. #17)")
    if over["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"повисший работник держит карточку дольше своего бюджета "
            f"({ttl / 3600.0:.2f}ч): вердикт `{over['verdict']}` — очередь заморожена")
    if plain["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"запись БЕЗ метки ведёт себя иначе, чем до правки: вердикт "
            f"`{plain['verdict']}` вместо `{guard.STALE}` — правка не дополняющая")
    axis_value = rec.get("worker_axis")
    if axis_value not in axes:
        return NOT_SATISFIED, (
            f"поле `worker_axis` несёт {axis_value!r} — вне вокабуляра читателя "
            f"{sorted(axes)}: ответ есть только в прозе, а разбор подстрокой запрещён")
    if str(axis_value) in str(rec.get("worker_detail") or ""):
        return NOT_SATISFIED, (
            "слово оси содержится в прозе того же вердикта — проба прошла бы подстрокой, "
            "то есть не проверяла бы поле (ADR-333)")
    if rec.get("worker_run_id") != mark:
        return NOT_SATISFIED, (
            f"метка из ЗАПИСИ ЖУРНАЛА не доехала до находки: `worker_run_id`="
            f"{rec.get('worker_run_id')!r} при объявленной {mark!r}")
    writer_row = _row(plain)
    if writer_row is None or writer_row.get("worker_axis") != guard.W_NOT_DECLARED:
        return NOT_SATISFIED, (
            "запись без метки не помечена `not_declared` — «ось не мерилась» неотличима "
            "от «спросили и работника нет»")
    if own.get(field) != mark:
        return NOT_SATISFIED, (
            f"ПИСАТЕЛЬ не поставил метку на свою запись (`{field}`={own.get(field)!r}) — "
            f"читать будет нечего, и ось журнальных записей останется `not_declared`")
    if field in foreign:
        return NOT_SATISFIED, (
            f"писатель поставил метку на запись от имени ЧУЖОЙ сессии "
            f"(`{field}`={foreign.get(field)!r}) — читатель верит личности, а не ярлыку, "
            f"и прочтёт чужой захват как МОЙ (замер `agent-claim-guard-blind-when-"
            f"session-pid-is-set`)")
    return SATISFIED, (
        f"журнальный захват мерит РАБОТНИКА: на сцене «захват только в объявлении, ярлык "
        f"`{label}` мёртв» живой носитель метки даёт `{alive['verdict']}` (ось "
        f"`{rec.get('worker_axis')}`, метка `{rec.get('worker_run_id')}` из записи), "
        f"измеренное отсутствие — `{gone['verdict']}`, неизмеримость — "
        f"`{unmeas['verdict']}`, за бюджетом {ttl / 3600.0:.2f}ч — `{over['verdict']}`, "
        f"запись без метки — `{plain['verdict']}` (ось `{guard.W_NOT_DECLARED}`); писатель "
        f"ставит поле `{field}` на свою запись и НЕ ставит на чужую; имя поля одно "
        f"(читатель и писатель согласны); вокабуляр {sorted(axes)} собран обходом, "
        f"подстрокой проба не проходит")


def _probe_file_overlap_claim_measures_the_worker(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: ТРЕТЬЯ запись захвата — пересечение по ФАЙЛАМ — мерит РАБОТНИКА (ADR-723).

    Предмет — карточка `inbox-tretya-zapis-zahvata-peresechenie-po-fai` (находка цикла
    #866). ADR-720 довёл ось РАБОТНИКА до ЗАМКА цикла, ADR-721 — до `claimed_by` во
    frontmatter, ADR-722 — до записи ЖУРНАЛА. Захват живёт в ТРЁХ записях, и третья —
    пересечение по объявленным файлам — судила о живости ТОЛЬКО через
    `sibling.durable_process_gone`, то есть по pid ЗАПУСКАТЕЛЯ, и метки работника не
    спрашивала вовсе. Цена: сессия, объявившая файлы и НЕ взявшая карточку ни одним из
    двух захватов, читалась по мёртвой оси, и две сессии могли править одни файлы.

    **Меряется ИСХОД У ЧИТАТЕЛЯ на сцене, где захвата НЕТ НИ ОДНОГО** — ни во
    frontmatter, ни записью `card:` в журнале. Только объявление ФАЙЛОВ. Иначе проба
    отвечала бы на вопрос ADR-721/722, а не на свой: вердикт пришёл бы от соседней
    записи, и порванное звено пересечения выглядело бы целым. Сцена собирается ПЯТЬ раз,
    каждый раз зовётся НАСТОЯЩИЙ `gather` шага 0b с `planned_files`, и критерий выполнен
    только если ответы РАЗЛИЧАЮТСЯ в нужную сторону:

      живой носитель метки ⇒ `claimed` и пересечение НЕ осиротевшее ·
      измеренное отсутствие ⇒ `stale` и осиротевшее (как до правки) ·
      неизмеримость ⇒ `unchecked` (инв. #17) ·
      за бюджетом работника ⇒ `stale` ·
      запись БЕЗ метки ⇒ `stale` с осью `not_declared`, то есть прежнее поведение.

    **Ярлык сцены МЁРТВ по оси запускателя во всех пяти прогонах** (`ps` отвечает rc=1 на
    любой pid), поэтому различие вердиктов не может прийти ниоткуда, кроме оси
    РАБОТНИКА. Это и есть предмет: до правки все пять сцен давали один и тот же `stale`.

    **Решение «чья метка» проверяется ОТДЕЛЬНО, а не подразумевается.** Метка обязана
    браться из ТОЙ ЖЕ записи, где объявлены файлы: сцена кладёт живую метку на
    РОДСТВЕННУЮ запись того же ярлыка (и НЕ кладёт на запись с файлами) — пересечение
    обязано остаться осиротевшим. Иначе переиспользованный ярлык отдавал бы живую метку
    мёртвой сессии (fail-OPEN внутри fail-CLOSED-сторожа), а у метки нет сужения
    `borrow_durable` «процесс стартовал не позже записи» — времени старта у неё нет.

    **Подстрокой не проходит (ADR-333):** требуется ПОЛЕ `worker_axis` со значением из
    вокабуляра ЧИТАТЕЛЯ, собранного ОБХОДОМ (`W_*`), и проза того же вердикта не вправе
    содержать слово оси.

    ТРИ ИСХОДА РАЗЛИЧИМЫ: читателя/прибора нет или не ввезли ⇒ `unmeasured` с названной
    причиной, и никогда `satisfied`.

    Оговорка названа вслух: живость работника здесь ВХОД (`worker=`), а не живая ОС —
    иначе проба меняла бы вердикт от того, кто сегодня занял номер
    (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»).
    """
    import importlib.util as _ilu
    import json as _json
    import tempfile as _tf
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    root = repo_root or REPO_ROOT
    paths = {"guard": os.path.join(root, "scripts", "check_card_claim.py"),
             "lock": os.path.join(root, "scripts", "orchestrator_cycle_lock.py"),
             "writer": os.path.join(root, "scripts", "log_session_change.py")}
    for name, pth in paths.items():
        if not os.path.exists(pth):
            return UNMEASURED, f"{pth} не найден — ось пересечения по файлам НЕ ИЗМЕРИТЬ"
    mods = {}
    try:
        for name, pth in paths.items():
            spec = _ilu.spec_from_file_location(f"_probe_c867_{name}", pth)
            mod = _ilu.module_from_spec(spec)        # type: ignore[arg-type]
            spec.loader.exec_module(mod)             # type: ignore[union-attr]
            mods[name] = mod
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"модуль не ввезён ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")
    guard, lock, writer = mods["guard"], mods["lock"], mods["writer"]

    #: Имя поля — у ПИСАТЕЛЯ схемы, своей копии строки у пробы нет (та же причина, что
    #: у читателя: вторая копия переживёт переименование и молча вернёт `not_declared`).
    field = str(getattr(writer, "RUN_ID_FIELD", "") or "").strip()
    if not field:
        return NOT_SATISFIED, ("писатель журнала не объявил имя поля метки работника "
                               "(`RUN_ID_FIELD`) — пересечение по файлам мерить нечем")
    reader_field, reader_why = guard.run_id_field(announcer=writer)
    if reader_field != field:
        return NOT_SATISFIED, (
            f"читатель и писатель называют поле по-разному: {reader_field!r} против "
            f"{field!r} ({reader_why}) — вторая копия строки переживёт переименование молча")

    axes = {v for k, v in vars(guard).items()
            if k.startswith("W_") and isinstance(v, str)}
    if not axes:
        return NOT_SATISFIED, (
            "у шага 0b НЕТ вокабуляра оси РАБОТНИКА (`W_*`) — ответ «кто именно жив, "
            "запускатель или работник» не производит никто")
    try:
        sibling = guard.load_sibling()
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сосед шага 0a не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    ttl = float(getattr(lock, "DEFAULT_WORKER_TTL_SEC", 0.0) or 0.0)
    if ttl <= 0.0:
        return NOT_SATISFIED, ("бюджет работника у замка не объявлен — без срока ось "
                               "РАБОТНИКА стала бы вечным замком, а не защитой")

    now = _dt.now(_tz.utc).replace(microsecond=0)
    label, mark = "cycle-31337", "orchestrator-31337-PROBE"
    mine = "/abs/tree/spa_core/overlap_scene.py"
    _SCENE_WHY = "проба приёмки: состояние носителя метки задано входом сцены"

    def _ask(axis):
        def _probe(run_id):
            if not str(run_id or "").strip():
                return "not_declared", "метки нет", None
            return axis, _SCENE_WHY, ttl
        return _probe

    try:
        with _tf.TemporaryDirectory(prefix="probe_c867_") as tmp:
            tracker = os.path.join(tmp, "tracker")
            os.makedirs(tracker)
            # Карточка БЕЗ захвата во frontmatter: предмет пробы — объявление ФАЙЛОВ.
            card = os.path.join(tracker, "inbox-scene.md")
            with open(card, "w", encoding="utf-8") as fh:
                fh.write("---\ntrackerStatus:\n  type: inbox\ntitle: сцена приёмки\n"
                         "status: in-progress\n---\n\nтело\n")

            def _verdict(axis, age_sec, *, with_mark=True, mark_on_kin=False,
                         grace_hours=None):
                """Один прогон сцены. `mark_on_kin` — метка на РОДСТВЕННОЙ записи."""
                at = (now - _td(seconds=age_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
                # Запись объявляет ФАЙЛЫ и НЕ объявляет карточку: ни поля `card:`, ни
                # файла карточки в списке — иначе это был бы захват, то есть предмет
                # ADR-722, и вердикт пришёл бы от него.
                entry = {"ts": at, "session": label, "summary": "сцена приёмки: файлы",
                         "files": [mine], "verified": "", "session_pid": 31337,
                         "session_pid_start": "Wed Oct 14 00:00:00 2026"}
                if with_mark and not mark_on_kin:
                    entry[field] = mark
                rows = [entry]
                if mark_on_kin:
                    # Родственная запись ТОГО ЖЕ ярлыка с ЖИВОЙ меткой, но БЕЗ файлов.
                    kin_row = dict(entry)
                    kin_row["files"] = []
                    kin_row["summary"] = "сцена приёмки: родственная запись"
                    kin_row[field] = mark
                    rows.append(kin_row)
                log = os.path.join(
                    tmp, f"log_{axis}_{int(age_sec)}_{with_mark}_{mark_on_kin}.jsonl")
                with open(log, "w", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(_json.dumps(row, ensure_ascii=False) + "\n")
                kw = ({} if grace_hours is None else {"grace_hours": grace_hours})
                return guard.gather("inbox-scene", log=log, tracker_dir=tracker,
                                    sibling=sibling, self_session="probe-c867", now=now,
                                    ps=lambda _pid: (1, ""), self_anchor=(41867, ""),
                                    shared_trees=(), worker=_ask(axis),
                                    planned_files=(mine,), **kw)

            fresh_age = 60.0
            alive = _verdict(guard.W_ALIVE, fresh_age)
            gone = _verdict(guard.W_GONE, fresh_age)
            unmeas = _verdict(guard.W_UNMEASURED, fresh_age)
            # ── ГРАНИЦА БЮДЖЕТА РАБОТНИКА ДОСТИЖИМА ТОЛЬКО С ПОДНЯТЫМ ОКНОМ ──────
            # Пересечение по файлам рассматривается ТОЛЬКО внутри окна свежести, и по
            # умолчанию это окно (3.00ч) КОРОЧЕ бюджета работника (4.17ч) ⇒ запись старше
            # бюджета в отчёт не попадает вовсе, и сцена отдаёт `free`, а не `stale`.
            # Это ИЗМЕРЕНО собственным прогоном пробы, а не предположено, и проверка
            # границы поэтому зовётся с поднятым окном: окно — флаг (`--grace-hours`),
            # значит при поднятом окне бюджет становится действующим, и сторож обязан
            # ответить ровно на этот случай. Молча опустить проверку значило бы оставить
            # повисшего работника без срока ровно там, где срок единственно и нужен.
            over = _verdict(guard.W_ALIVE, ttl + 1.0, grace_hours=ttl / 3600.0 + 1.0)
            plain = _verdict(guard.W_ALIVE, fresh_age, with_mark=False)
            kin_only = _verdict(guard.W_ALIVE, fresh_age, mark_on_kin=True)
            # Та же запись в том же поднятом окне, но ВНУТРИ бюджета ⇒ держит. Без этой
            # половины «за бюджетом ⇒ stale» прошло бы и от того, что ось не работает
            # вовсе в поднятом окне (контроль границы с ДВУХ сторон).
            under = _verdict(guard.W_ALIVE, ttl - 60.0, grace_hours=ttl / 3600.0 + 1.0)
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сцена пересечения не собралась ({type(exc).__name__}: "
                            f"{exc}) — НЕ ИЗМЕРЕНО")

    def _row(report):
        rows = report.get("overlaps") or []
        return rows[0] if len(rows) == 1 else None

    def _no_claims(report):
        """Находок-ЗАХВАТОВ на сцене быть не должно: иначе предмет пробы подменён."""
        return not (report.get("claims") or [])

    rec = _row(alive)
    if rec is None:
        return NOT_SATISFIED, ("шаг 0b не выдал ровно одного пересечения по файлам на "
                               "сцене «объявлены файлы, карточка не взята» — предмет "
                               "пробы не найден")
    for name, report in (("живой работник", alive), ("работника нет", gone),
                         ("не измерено", unmeas), ("за бюджетом", over),
                         ("в бюджете", under), ("без метки", plain),
                         ("метка у родни", kin_only)):
        if not _no_claims(report):
            return NOT_SATISFIED, (
                f"на сцене «{name}» появилась находка-ЗАХВАТ — вердикт пришёл бы от "
                f"записи захвата (предмет ADR-721/722), а не от пересечения по файлам")
    if alive["verdict"] != guard.CLAIMED:
        return NOT_SATISFIED, (
            f"ЖИВОЙ работник не держит ОБЪЯВЛЕННЫЕ ИМ ФАЙЛЫ: вердикт "
            f"`{alive['verdict']}` вместо `{guard.CLAIMED}` — две сессии правят одни "
            f"файлы, и шаг 0b об этом не говорит")
    if rec.get("orphaned") is not False:
        return NOT_SATISFIED, (
            f"пересечение живого работника помечено `orphaned`={rec.get('orphaned')!r} — "
            f"вердикт читает именно это поле, и через него «ЗАНЯТА» не доедет")
    # ── МАШИННОСТЬ ОТВЕТА спрашивается СРАЗУ за главным исходом ────────────────
    # Порядок не косметика: читатель, пересказывающий ось ПРОЗОЙ, портит ВСЕ сцены
    # разом, и при проверке в конце проба краснела бы на первой попавшейся из них —
    # верный отказ с неверной причиной. Предмет этих двух строк — «ответ есть поле из
    # закрытого перечня, а не слово в тексте» (ADR-333), и сказать это обязана та
    # сцена, которая и есть главный исход.
    axis_value = rec.get("worker_axis")
    if axis_value not in axes:
        return NOT_SATISFIED, (
            f"поле `worker_axis` несёт {axis_value!r} — вне вокабуляра читателя "
            f"{sorted(axes)}: ответ есть только в прозе, а разбор подстрокой запрещён")
    if str(axis_value) in str(rec.get("worker_detail") or ""):
        return NOT_SATISFIED, (
            "слово оси содержится в прозе того же вердикта — проба прошла бы подстрокой, "
            "то есть не проверяла бы поле (ADR-333)")
    if gone["verdict"] != guard.STALE or (_row(gone) or {}).get("orphaned") is not True:
        return NOT_SATISFIED, (
            f"работника измеренно НЕТ, а пересечение не осиротевшее: вердикт "
            f"`{gone['verdict']}`, orphaned={(_row(gone) or {}).get('orphaned')!r} — "
            f"это вечный замок на чужих файлах, а не защита")
    if unmeas["verdict"] != guard.UNCHECKED:
        return NOT_SATISFIED, (
            f"ось НЕ ИЗМЕРЕНА, а вердикт `{unmeas['verdict']}` вместо "
            f"`{guard.UNCHECKED}` — неизмеримость выдана за ответ (инв. #17)")
    if over["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"повисший работник держит чужие файлы дольше своего бюджета "
            f"({ttl / 3600.0:.2f}ч) при поднятом окне: вердикт `{over['verdict']}` — "
            f"очередь заморожена")
    if under["verdict"] != guard.CLAIMED:
        return NOT_SATISFIED, (
            f"в ТОМ ЖЕ поднятом окне работник ВНУТРИ бюджета файлы не держит: вердикт "
            f"`{under['verdict']}` вместо `{guard.CLAIMED}` — «за бюджетом ⇒ stale» "
            f"прошло бы и от неработающей оси (граница проверена с одной стороны)")
    # Запись БЕЗ метки судится осью ЗАПУСКАТЕЛЯ: ярлык сцены объявил якорь, `ps` его не
    # нашёл ⇒ пересечение ОСИРОТЕВШЕЕ ⇒ вердикт `stale`, и это ровно поведение до правки.
    plain_row = _row(plain)
    if plain_row is None or plain_row.get("worker_axis") != guard.W_NOT_DECLARED:
        return NOT_SATISFIED, (
            "пересечение без метки не помечено `not_declared` — «ось не мерилась» "
            "неотличима от «спросили и работника нет»")
    if plain_row.get("orphaned") is not True or plain["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"запись БЕЗ метки ведёт себя иначе, чем до правки: вердикт "
            f"`{plain['verdict']}`, orphaned={plain_row.get('orphaned')!r} вместо "
            f"`{guard.STALE}`/True — правка не дополняющая")
    kin_row = _row(kin_only)
    if kin_row is None or kin_row.get("orphaned") is not True:
        return NOT_SATISFIED, (
            f"метка лежит на РОДСТВЕННОЙ записи, а пересечение прочиталось живым "
            f"(orphaned={None if kin_row is None else kin_row.get('orphaned')!r}): "
            f"метка заимствуется у соседней записи, а сужения «процесс стартовал не "
            f"позже» у неё нет — переиспользованный ярлык отдаст живую метку мёртвой "
            f"сессии (fail-OPEN внутри fail-CLOSED-сторожа)")
    if kin_row.get("worker_axis") != guard.W_NOT_DECLARED:
        return NOT_SATISFIED, (
            f"ось пересечения при метке у родни — `{kin_row.get('worker_axis')}` вместо "
            f"`{guard.W_NOT_DECLARED}`: решение «метка берётся из ТОЙ ЖЕ записи» не "
            f"объявлено полем, и читателю нечем проверить, чью метку спросили")
    if rec.get("worker_run_id") != mark:
        return NOT_SATISFIED, (
            f"метка из ЗАПИСИ С ФАЙЛАМИ не доехала до пересечения: `worker_run_id`="
            f"{rec.get('worker_run_id')!r} при объявленной {mark!r}")
    if rec.get("launcher_orphaned") is not True:
        return NOT_SATISFIED, (
            f"вывод оси РАБОТНИКА затёр ИЗМЕРЕНИЕ оси запускателя "
            f"(`launcher_orphaned`={rec.get('launcher_orphaned')!r}) — отчёт выдал бы "
            f"вывод оси за замер pid, которого никто не делал")
    return SATISFIED, (
        f"пересечение по ФАЙЛАМ мерит РАБОТНИКА: на сцене «файлы объявлены, карточка НЕ "
        f"взята, ярлык `{label}` мёртв по оси запускателя» живой носитель метки даёт "
        f"`{alive['verdict']}` и orphaned=False (ось `{rec.get('worker_axis')}`, метка "
        f"`{rec.get('worker_run_id')}` из ТОЙ ЖЕ записи, замер запускателя сохранён в "
        f"`launcher_orphaned`), измеренное отсутствие — `{gone['verdict']}`/orphaned=True, "
        f"неизмеримость — `{unmeas['verdict']}`, за бюджетом {ttl / 3600.0:.2f}ч — "
        f"`{over['verdict']}`, запись без метки — `{plain['verdict']}` (ось "
        f"`{guard.W_NOT_DECLARED}`), метка у РОДСТВЕННОЙ записи пересечения НЕ оживляет; "
        f"захватов на сцене нет ни одного ⇒ вердикт пришёл от пересечения, а не от "
        f"соседней записи; вокабуляр {sorted(axes)} собран обходом, подстрокой проба не "
        f"проходит")


def _probe_card_claim_absent_worker_reaches_the_verdict(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: ИЗМЕРЕННОЕ отсутствие работника доезжает до вердикта ВНУТРИ окна (#868).

    Предмет — карточка `inbox-izmerennoe-otsutstvie-rabotnika-ne-doezz`. ADR-721 дал шагу
    0b ось РАБОТНИКА, но спрашивалась она только там, где ответ уже ничего не решал:
    внутри окна свежести свежий СИЛЬНЫЙ захват блокирует карточку ветвью ВЫШЕ, а
    измеренное отсутствие работника в вердикт не попадало вовсе.

    **ЗАМЕР ДО ПРАВКИ, живая очередь 14.10 19:45Z.** Приказ владельца
    `inbox-task-portfolio-cio-dynamic-capital-alloc`, держатель `cycle-79433` (#867),
    захвату 2.79ч. Обе измеримые оси говорят «мёртв»: `ps -p 79433` rc=1, `ps -p 79986`
    rc=1, живых носителей метки `orchestrator-79433-…` НОЛЬ при читаемом окружении у 73
    процессов. Вердикт шага 0b: `⛔ ЗАНЯТА — НЕ бери эту карточку`. Шаг 0a-ГОЛОД требовал
    взять приказ ПЕРВЫМ. Циклы идут раз в час, окно — 3ч ⇒ так заперт каждый цикл,
    стартовавший раньше трёх часов после мёртвого предшественника.

    **Почему ось ЗАПУСКАТЕЛЯ «и так не решит».** Довод, стоявший в коде («чаще всего
    скажет `stale`»), ИЗМЕРЕН по живому трекеру: из 192 захватов во frontmatter ярлык
    пид-измерим у 54 и НЕИЗМЕРИМ у 138 — и неизмерим именно у той формы, которую пишет
    сам оркестратор (`SPA_SESSION_ID=cycle-$$`: цифры есть, токена `pid` нет).

    **Меряется ИСХОД У ЧИТАТЕЛЯ.** Проба собирает одноразовые сцены ВНУТРИ окна свежести
    (это и есть предмет: снаружи окна ось уже спрашивалась) и зовёт НАСТОЯЩИЙ `gather`.
    Критерий выполнен, только если ответы РАЗЛИЧАЮТСЯ в нужную сторону: живой носитель
    метки — `claimed`, измеренное отсутствие — `stale`, неизмеримость — `unchecked`,
    запись БЕЗ метки — `claimed` (прежнее поведение, правка дополняющая), а измеренная
    ЖИЗНЬ оси запускателя перебивает отсутствие работника и держит карточку.

    **Новой двери к «свободна» проба НЕ принимает:** `stale` — «кандидат на ручной
    подъём», и отдельное звено требует, чтобы вердикт сцены «работника нет» не был
    `free`. `claim` на `stale` по-прежнему отказывает без письменной причины.

    **Подстрокой не проходит (ADR-333):** требуется ПОЛЕ `worker_axis` со значением из
    вокабуляра ЧИТАТЕЛЯ, собранного ОБХОДОМ (`W_*`), и слово оси не должно встречаться в
    прозе того же вердикта.

    ТРИ ИСХОДА РАЗЛИЧИМЫ: читателя нет / не ввезён / нет вокабуляра ⇒ `unmeasured` или
    `not_satisfied` с названной причиной, и никогда `satisfied`.

    Оговорка названа вслух: живость работника здесь ВХОД (`worker=`), а не живая ОС, —
    иначе проба меняла бы вердикт от того, кто сегодня занял номер
    (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»). Сторона `orphaned` (ось
    запускателя измерила СМЕРТЬ) здесь НЕ сцена намеренно: там вердикт `stale` и до
    правки, её держит существующая батарея шага 0b.
    """
    import importlib.util as _ilu
    import json as _json
    import tempfile as _tf
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    root = repo_root or REPO_ROOT
    guard_path = os.path.join(root, "scripts", "check_card_claim.py")
    if not os.path.exists(guard_path):
        return UNMEASURED, f"{guard_path} не найден — шаг 0b НЕ ИЗМЕРИТЬ"
    lock_path = os.path.join(root, "scripts", "orchestrator_cycle_lock.py")
    if not os.path.exists(lock_path):
        return UNMEASURED, f"{lock_path} не найден — бюджет работника НЕ ИЗМЕРИТЬ"
    try:
        spec = _ilu.spec_from_file_location("_probe_c868_card_claim", guard_path)
        guard = _ilu.module_from_spec(spec)          # type: ignore[arg-type]
        spec.loader.exec_module(guard)               # type: ignore[union-attr]
        spec_l = _ilu.spec_from_file_location("_probe_c868_cycle_lock", lock_path)
        lock = _ilu.module_from_spec(spec_l)         # type: ignore[arg-type]
        spec_l.loader.exec_module(lock)              # type: ignore[union-attr]
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"шаг 0b не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    #: Вокабуляр оси — ОБХОДОМ у читателя, а не парой из головы.
    axes = {v for k, v in vars(guard).items()
            if k.startswith("W_") and isinstance(v, str)}
    if not axes:
        return NOT_SATISFIED, (
            "у шага 0b НЕТ вокабуляра оси РАБОТНИКА (`W_*`) — ответ «кто именно жив» не "
            "производит никто: замер до ADR-721")
    try:
        sibling = guard.load_sibling()
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сосед шага 0a не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    ttl = float(getattr(lock, "DEFAULT_WORKER_TTL_SEC", 0.0) or 0.0)
    if ttl <= 0.0:
        return NOT_SATISFIED, ("бюджет работника у замка не объявлен — без срока ось "
                               "РАБОТНИКА стала бы вечным замком, а не защитой")
    grace_h = float(getattr(guard, "DEFAULT_GRACE_HOURS", 0.0) or 0.0)
    if grace_h <= 0.0:
        return NOT_SATISFIED, ("окно свежести шага 0b не объявлено — сцену «внутри окна» "
                               "задать нечем, а она и есть предмет пробы")

    now = _dt.now(_tz.utc).replace(microsecond=0)
    #: Ярлык НАМЕРЕННО без токена `pid`: ровно та форма, которую пишет оркестратор
    #: (`SPA_SESSION_ID=cycle-$$`), и ровно на ней ось ЗАПУСКАТЕЛЯ неизмерима.
    label, mark = "cycle-79433", "orchestrator-79433-PROBE"
    live_pid, live_start = 42868, "Wed Oct 14 10:00:00 2026"

    _SCENE_WHY = "проба приёмки: состояние носителя метки задано входом сцены"

    def _ask(axis):
        def _probe(run_id):
            if not str(run_id or "").strip():
                return "not_declared", "метки нет", None
            return axis, _SCENE_WHY, ttl
        return _probe

    try:
        with _tf.TemporaryDirectory(prefix="probe_c868_") as tmp:
            tracker = os.path.join(tmp, "tracker")
            os.makedirs(tracker)

            def _scene(age_sec, with_mark=True, anchored=False):
                at = (now - _td(seconds=age_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
                rows = ["---\n", "trackerStatus:\n", "  type: inbox\n",
                        "title: сцена приёмки\n", "status: in-progress\n",
                        f"claimed_by: {label}\n", f"claimed_at: {at}\n"]
                if with_mark:
                    rows.append(f"claimed_run_id: {mark}\n")
                rows += ["---\n", "\nтело\n"]
                with open(os.path.join(tracker, "inbox-scene.md"), "w",
                          encoding="utf-8") as fh:
                    fh.write("".join(rows))
                log = os.path.join(tmp, f"log_{int(age_sec)}_{int(anchored)}.jsonl")
                with open(log, "w", encoding="utf-8") as fh:
                    if anchored:
                        # Личность ЗАПУСКАТЕЛЯ объявлена и ЖИВА (`ps` ниже подтвердит):
                        # эта сцена проверяет, что измеренная жизнь сильнее измеренного
                        # отсутствия соседней оси.
                        fh.write(_json.dumps({
                            "ts": at, "session": label,
                            "summary": "сцена приёмки: голос держателя",
                            "files": [], "session_pid": live_pid,
                            "session_pid_start": live_start}, ensure_ascii=False) + "\n")
                return log

            def _verdict(axis, age_sec, with_mark=True, anchored=False):
                log = _scene(age_sec, with_mark, anchored)
                return guard.gather("inbox-scene", log=log, tracker_dir=tracker,
                                    sibling=sibling, self_session="probe-c868", now=now,
                                    ps=(lambda _pid: (0, live_start)) if anchored
                                    else (lambda _pid: (1, "")),
                                    self_anchor=(41868, ""), shared_trees=(),
                                    worker=_ask(axis))

            #: ВНУТРИ окна свежести — предмет пробы. Половина окна, а не «чуть меньше»:
            #: граница окна проверяется соседней батареей, здесь нужна заведомая середина.
            inside = grace_h * 3600.0 / 2.0
            alive = _verdict(guard.W_ALIVE, inside)
            gone = _verdict(guard.W_GONE, inside)
            unmeas = _verdict(guard.W_UNMEASURED, inside)
            plain = _verdict(guard.W_ALIVE, inside, with_mark=False)
            gone_live_launcher = _verdict(guard.W_GONE, inside, anchored=True)
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сцена захвата не собралась ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")

    def _front(report):
        rows = [c for c in report.get("claims") or []
                if c.get("source") == "frontmatter"]
        return rows[0] if len(rows) == 1 else None

    rec = _front(gone)
    if rec is None:
        return NOT_SATISFIED, ("шаг 0b не выдал ровно одной находки по frontmatter на "
                               "сцене «работника измеренно нет» — предмет пробы не найден")
    if gone["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"работника ИЗМЕРЕННО НЕТ, а карточка внутри окна не отдаётся: вердикт "
            f"`{gone['verdict']}` вместо `{guard.STALE}` — снятый замер не доезжает до "
            f"вердикта, и мёртвый держатель держит приказ владельца все {grace_h}ч "
            f"(живой замер 14.10 19:45Z на `cycle-79433`)")
    if gone["verdict"] == guard.FREE:
        return NOT_SATISFIED, (
            "сцена «работника нет» отдала `free` — это АВТО-захват, а не находка: подъём "
            "обязан требовать письменной причины (`claim --takeover`)")
    if alive["verdict"] != guard.CLAIMED:
        return NOT_SATISFIED, (
            f"ЖИВОЙ работник не держит карточку: вердикт `{alive['verdict']}` вместо "
            f"`{guard.CLAIMED}` — живая работа отдаётся второй сессии (замер 14.10)")
    if unmeas["verdict"] != guard.UNCHECKED:
        return NOT_SATISFIED, (
            f"ось НЕ ИЗМЕРЕНА, а вердикт `{unmeas['verdict']}` вместо "
            f"`{guard.UNCHECKED}` — неизмеримость выдана за ответ (инв. #17)")
    if plain["verdict"] != guard.CLAIMED:
        return NOT_SATISFIED, (
            f"захват БЕЗ метки работника внутри окна ведёт себя иначе, чем до правки: "
            f"вердикт `{plain['verdict']}` вместо `{guard.CLAIMED}` — правка не "
            f"дополняющая, а меняет поведение 138 из 192 захватов живого трекера")
    if gone_live_launcher["verdict"] != guard.CLAIMED:
        return NOT_SATISFIED, (
            f"ось ЗАПУСКАТЕЛЯ измерила ЖИЗНЬ, а карточка отдана: вердикт "
            f"`{gone_live_launcher['verdict']}` вместо `{guard.CLAIMED}` — измеренная "
            f"жизнь обязана быть сильнее измеренного отсутствия соседней оси")
    axis_value = rec.get("worker_axis")
    if axis_value not in axes:
        return NOT_SATISFIED, (
            f"поле `worker_axis` несёт {axis_value!r} — вне вокабуляра читателя "
            f"{sorted(axes)}: ответ есть только в прозе, а разбор подстрокой запрещён")
    if axis_value != guard.W_GONE:
        return NOT_SATISFIED, (
            f"находка сцены «работника нет» помечена осью {axis_value!r}, а не "
            f"{guard.W_GONE!r} — вердикт пришёл не от того измерения")
    if str(axis_value) in str(rec.get("worker_detail") or ""):
        return NOT_SATISFIED, (
            "слово оси содержится в прозе того же вердикта — проба прошла бы подстрокой, "
            "то есть не проверяла бы поле (ADR-333)")
    if rec.get("worker_run_id") != mark:
        return NOT_SATISFIED, (
            f"метка держателя не доехала до находки: `worker_run_id`="
            f"{rec.get('worker_run_id')!r} при объявленной {mark!r}")
    if rec.get("fresh") is not True:
        return NOT_SATISFIED, (
            f"сцена оказалась СНАРУЖИ окна свежести (`fresh`={rec.get('fresh')!r}) — "
            f"тогда проба отвечает на вопрос, уже закрытый ADR-721, а не на свой")
    if rec.get("orphaned") is not False:
        return NOT_SATISFIED, (
            f"ось ЗАПУСКАТЕЛЯ на сцене измерила смерть (`orphaned`="
            f"{rec.get('orphaned')!r}) — вердикт `stale` пришёл бы от неё, и предмет "
            f"пробы остался бы непроверенным")
    return SATISFIED, (
        f"измеренное отсутствие работника доезжает до вердикта ВНУТРИ окна ({grace_h}ч): "
        f"на сцене «ярлык `{label}` пид-неизмерим, захвату {rec.get('age_hours')}ч, "
        f"свежий (`fresh`={rec.get('fresh')}), ось запускателя смерти НЕ измерила "
        f"(`orphaned`={rec.get('orphaned')})» живой носитель метки даёт "
        f"`{alive['verdict']}`, измеренное отсутствие — `{gone['verdict']}` (ось "
        f"`{axis_value}`, метка `{rec.get('worker_run_id')}` из карточки), неизмеримость "
        f"— `{unmeas['verdict']}` (инв. #17), запись БЕЗ метки — `{plain['verdict']}` (то "
        f"есть прежнее поведение), а измеренная ЖИЗНЬ оси запускателя — "
        f"`{gone_live_launcher['verdict']}`; бюджет работника {ttl / 3600.0:.2f}ч взят у "
        f"замка, вокабуляр {sorted(axes)} собран обходом, подстрокой проба не проходит")


def _probe_card_claim_carries_the_launcher_anchor(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: якорь ЗАПУСКАТЕЛЯ доезжает до вердикта ИЗ САМОЙ КАРТОЧКИ (#869).

    Предмет — карточка `inbox-yakor-zapuskatelya-ne-doezzhaet-do-kar`. ADR-721 довёл до
    frontmatter метку РАБОТНИКА (`claimed_run_id`), и из двух осей захвата измеримой из
    карточки стала ровно одна. Якорь ЗАПУСКАТЕЛЯ (`session_pid` + `session_pid_start`)
    писатель захвата ИЗМЕРЯЕТ и без него работать ОТКАЗЫВАЕТСЯ
    (`measure_self_anchor` ⇒ `UnmeasurableClaim`), после чего не записывает его никуда:
    читатель берёт якорь ВЗАЙМЫ из журнала по ярлыку держателя (`_anchor_for` →
    `durable_by_session`).

    **Заём опирается на то, чего у карточки нет по построению.** Карточка уезжает на
    `origin`, журнал объявлений — НЕТ, и это сказано вслух в самом писателе (там же, где
    он пишет `claim_takeover_reason`: «карточка уезжает на origin, журнал — нет»).
    ЗАМЕР 14.10 по живому трекеру: из **192** захватов во frontmatter якорь не доезжает
    до **48** (25.0 %), а на ОТКРЫТЫХ карточках — до **6 из 15** (40.0 %).

    **Что ровно меняется — ИЗМЕРЕНО, а не выведено.** Внутри окна свежести свежий
    СИЛЬНЫЙ захват даёт `claimed`, и перебить его может ТОЛЬКО измеренная смерть
    запускателя (`durable_process_gone`). Без якоря такой смерти не измерить ничем, и
    карточка заперта все `DEFAULT_GRACE_HOURS` часа — ровно цена, которую заплатил #868.
    Контрольный замер той же сцены показал и ГРАНИЦУ правки: форма ярлыка (`cycle-$$`
    против `cycle-$$-pid$$`) вердикт НЕ меняет ни в одну сторону — pid из ярлыка
    смертью намеренно не считается (`durable_process_gone`: «это НЕ „`ps` не нашёл
    pid“»), поэтому лечить надо ЯКОРЬ, а не ярлык.

    **Адрес якоря проба НЕ знает литералом (ADR-333).** Она его ИЗМЕРЯЕТ: гоняет
    настоящий `claim_card` на одноразовой карточке с инъектированным якорем и смотрит,
    какие поля frontmatter появились и несут ли они измеренную пару. Поля, названного
    писателем, нет ⇒ `not_satisfied` с дословным «измерил и выбросил». Затем ТЕМИ ЖЕ
    именами собираются сцены читателя — то есть утверждение проверяется у обоих концов
    проводки, а совпадение имён не может разойтись с кодом.

    **Новой двери к «свободна» проба не принимает:** исход измеренной смерти — `stale`
    («кандидат на РУЧНОЙ подъём»), и отдельное звено требует, чтобы он не был `free`.
    Границы: якоря в карточке нет ⇒ вердикт прежний БАЙТ В БАЙТ (это 190+ существующих
    захватов) · якорь есть и запускатель ЖИВ ⇒ `claimed` (измеренная жизнь сильнее) ·
    pid переиспользован (старт ПОЗЖЕ захвата) ⇒ защита не выдаётся живому чужому
    процессу.

    ТРИ ИСХОДА РАЗЛИЧИМЫ: читателя/писателя нет, не ввезён, вокабуляра нет ⇒
    `unmeasured` либо `not_satisfied` с названной причиной, и никогда `satisfied`.

    Оговорка названа вслух: живость запускателя здесь ВХОД (`ps=`), а не живая ОС, —
    иначе проба судила бы о том, кто сегодня занял номер (`.claude/rules/deployment.md`
    § «ЛИЧНОСТЬ ПРОЦЕССА»). Единственная сцена, доходящая до живой ОС за РОДОМ якоря
    (`_anchor_verdict`), берёт `os.getpid()` — он жив на любой машине по построению и
    не является процессом-таймером.
    """
    import importlib.util as _ilu
    import tempfile as _tf
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    root = repo_root or REPO_ROOT
    guard_path = os.path.join(root, "scripts", "check_card_claim.py")
    if not os.path.exists(guard_path):
        return UNMEASURED, f"{guard_path} не найден — шаг 0b НЕ ИЗМЕРИТЬ"
    try:
        spec = _ilu.spec_from_file_location("_probe_c869_card_claim", guard_path)
        guard = _ilu.module_from_spec(spec)          # type: ignore[arg-type]
        spec.loader.exec_module(guard)               # type: ignore[union-attr]
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"шаг 0b не ввезён ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")
    try:
        sibling = guard.load_sibling()
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сосед шага 0a не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    #: Вокабуляр якоря — у ЧИТАТЕЛЯ (`DURABLE_KEYS`), а не парой из головы.
    durable_keys = tuple(getattr(sibling, "DURABLE_KEYS", ()) or ())
    if len(durable_keys) != 2:
        return NOT_SATISFIED, (
            f"у шага 0a НЕТ вокабуляра якоря (`DURABLE_KEYS` = {durable_keys!r}) — "
            f"«кто запускатель» не производит никто, и сцену задать нечем")
    grace_h = float(getattr(guard, "DEFAULT_GRACE_HOURS", 0.0) or 0.0)
    if grace_h <= 0.0:
        return NOT_SATISFIED, ("окно свежести шага 0b не объявлено — сцену «внутри окна» "
                               "задать нечем, а она и есть предмет пробы")
    for attr in ("claim_card", "gather", "frontmatter", "STALE", "CLAIMED", "FREE"):
        if not hasattr(guard, attr):
            return UNMEASURED, f"у шага 0b нет {attr!r} — проводку НЕ ИЗМЕРИТЬ"

    now = _dt.now(_tz.utc).replace(microsecond=0)
    #: Старт запускателя ЗАВЕДОМО раньше захвата: иначе сцена «жив» измеряла бы
    #: переиспользованный pid, а это ОТДЕЛЬНОЕ звено ниже.
    start_dt = now - _td(hours=2)
    START = start_dt.strftime("%a %b %d %H:%M:%S %Y")
    LATER = (now + _td(hours=1)).strftime("%a %b %d %H:%M:%S %Y")
    ALIVE_PID = os.getpid()
    DEAD_PID = 999_001

    def _dead(_pid):
        return (1, "")

    def _alive(_pid):
        return (0, START)

    try:
        with _tf.TemporaryDirectory(prefix="probe_c869_") as tmp:
            # ── (1) ПИСАТЕЛЬ: куда он кладёт измеренный якорь ────────────────
            w_tracker = os.path.join(tmp, "w_tracker")
            os.makedirs(w_tracker)
            w_card = os.path.join(w_tracker, "inbox-scene-writer.md")
            with open(w_card, "w", encoding="utf-8") as fh:
                fh.write("---\ntrackerStatus:\n  type: inbox\ntitle: сцена писателя\n"
                         "status: new\n---\n\nтело\n")
            w_log = os.path.join(tmp, "w_log.jsonl")
            open(w_log, "w", encoding="utf-8").close()
            before = set(guard.frontmatter(
                open(w_card, encoding="utf-8").read()) or {})
            try:
                guard.claim_card("inbox-scene-writer", log=w_log, session="cycle-probe869",
                                 tracker_dir=w_tracker, now=now, sibling=sibling,
                                 ps=_dead, self_anchor=(ALIVE_PID, START))
            except Exception as exc:                 # noqa: BLE001
                return UNMEASURED, (f"писатель захвата не отработал на одноразовой сцене "
                                    f"({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")
            after_meta = guard.frontmatter(open(w_card, encoding="utf-8").read()) or {}
            fresh = {k: str(after_meta.get(k) or "") for k in set(after_meta) - before}
            #: Адрес якоря ИЗМЕРЕН: поле, чьё значение несёт измеренный pid, и поле,
            #: несущее его verbatim-старт. Литерала имени у пробы нет.
            pid_field = next((k for k, v in fresh.items() if v.strip() == str(ALIVE_PID)), None)
            start_field = next((k for k, v in fresh.items() if v.strip() == START), None)
            if pid_field is None or start_field is None:
                return NOT_SATISFIED, (
                    f"писатель захвата ИЗМЕРИЛ якорь запускателя (pid{ALIVE_PID}, старт "
                    f"{START!r}) — и ВЫБРОСИЛ его: во frontmatter появились только "
                    f"{sorted(fresh)}, поля с pid{'' if pid_field else ' НЕТ'}"
                    f"{'' if start_field else ', поля со стартом НЕТ'}. Читателю остаётся "
                    f"заём из журнала, а журнал на origin не уезжает — замер 14.10: якорь "
                    f"не доезжает до 48 из 192 захватов (25.0 %), на открытых карточках — "
                    f"6 из 15")

            # ── (2) ЧИТАТЕЛЬ: теми же именами, ИЗМЕРЕННЫМИ у писателя ───────
            r_tracker = os.path.join(tmp, "r_tracker")
            os.makedirs(r_tracker)

            def _verdict(anchor, ps):
                """Сцена: захват во frontmatter ВНУТРИ окна, журнал ПУСТ (заём невозможен)."""
                at = (now - _td(seconds=grace_h * 3600.0 / 2.0)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
                rows = ["---\n", "trackerStatus:\n", "  type: inbox\n",
                        "title: сцена читателя\n", "status: in-progress\n",
                        "claimed_by: cycle-869000\n", f"claimed_at: {at}\n"]
                for key, value in (anchor or {}).items():
                    rows.append(f"{key}: {value}\n")
                rows += ["---\n", "\nтело\n"]
                with open(os.path.join(r_tracker, "inbox-scene-reader.md"), "w",
                          encoding="utf-8") as fh:
                    fh.write("".join(rows))
                log = os.path.join(tmp, "r_log.jsonl")
                open(log, "w", encoding="utf-8").close()
                return guard.gather("inbox-scene-reader", log=log, tracker_dir=r_tracker,
                                    sibling=sibling, self_session="probe-c869", now=now,
                                    ps=ps, self_anchor=None, shared_trees=())

            dead_anchor = {pid_field: DEAD_PID, start_field: START}
            gone = _verdict(dead_anchor, _dead)
            live = _verdict({pid_field: ALIVE_PID, start_field: START}, _alive)
            bare = _verdict(None, _dead)
            reused = _verdict({pid_field: ALIVE_PID, start_field: LATER}, _alive)
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сцена захвата не собралась ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")

    if gone["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"запускатель ИЗМЕРЕННО МЁРТВ, а его якорь объявлен В КАРТОЧКЕ — и вердикт "
            f"всё равно `{gone['verdict']}` вместо `{guard.STALE}`: из карточки ось "
            f"запускателя не измеряется, карточка заперта все {grace_h}ч (цена #868)")
    if gone["verdict"] == guard.FREE:
        return NOT_SATISFIED, ("измеренная смерть запускателя отдала карточку как "
                               "`free` — это новая дверь к авто-захвату, а не подъём")
    if live["verdict"] != guard.CLAIMED:
        return NOT_SATISFIED, (
            f"запускатель ЖИВ (якорь в карточке, старт сошёлся), а карточка отдаётся: "
            f"вердикт `{live['verdict']}` вместо `{guard.CLAIMED}` — измеренная жизнь "
            f"обязана быть сильнее")
    if bare["verdict"] != guard.CLAIMED:
        return NOT_SATISFIED, (
            f"захват БЕЗ якоря в карточке изменил вердикт: `{bare['verdict']}` вместо "
            f"`{guard.CLAIMED}` — правка обязана быть дополняющей, а это 190+ "
            f"существующих захватов живого трекера")
    if reused["verdict"] != guard.STALE:
        return NOT_SATISFIED, (
            f"pid запускателя ПЕРЕИСПОЛЬЗОВАН (старт {LATER!r} позже захвата), а вердикт "
            f"`{reused['verdict']}` вместо `{guard.STALE}` — защита выдана чужому живому "
            f"процессу по совпадению номера")
    return SATISFIED, (
        f"якорь запускателя доезжает до вердикта ИЗ КАРТОЧКИ: писатель кладёт его в "
        f"`{pid_field}`/`{start_field}` (адрес ИЗМЕРЕН у писателя, не литерал), и внутри "
        f"окна {grace_h}ч при ПУСТОМ журнале измеренная смерть даёт "
        f"`{gone['verdict']}`, измеренная жизнь — `{live['verdict']}`, захват без якоря — "
        f"`{bare['verdict']}` (прежнее поведение), переиспользованный pid — "
        f"`{reused['verdict']}`; вокабуляр {list(durable_keys)} взят у шага 0a, живость "
        f"запускателя — вход сцены")


def _probe_delta_mutation_instrument_is_re_measurable(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: прибор мутационного замера ВВЕЗЁН и перемеряем КОМАНДОЙ (#870).

    Предмет — карточка `inbox-pribor-mutatsionnogo-zamera-vybrasyvaets`. Каждый цикл
    пишет в ADR строку «применено N · убито M · выжило K», а прибор, которым это
    измерено, до сегодня писался заново и жил в `/tmp`. ЗАМЕР 15.10: одноразовых
    приборов в `/tmp` — **25** (3790 строк), ввезено в репозиторий — **0**; ADR с
    заявкой «убито N» — **40**, из них прибор назван ввезённым у **1**, адресом в
    `/tmp` — у **1** (файла нет), не назван НИКАК — у **38**; открытых карточек, чья
    приёмка указывает в `/tmp`, — **3**, и адрес разрешается сегодня у **0**.

    **Проба меряет ИСХОД, а не наличие файла.** Она поднимает прибор КОМАНДОЙ (ровно
    тем способом, которым его позовёт следующий цикл) на ОДНОРАЗОВОМ дереве и смотрит
    три сцены, у которых правильные ответы РАЗНЫЕ:

    * мутацию, которую батарея видит, прибор обязан объявить измеренной и чистой;
    * мутацию, которую батарея НЕ видит, — находкой (код возврата иной);
    * мутацию, чей якорь отсутствует, — НЕ ИЗМЕРЕННОЙ, и это обязано дойти до
      НЕНУЛЕВОГО кода возврата (инв. #17). Это и есть дефект, которого не было ни у
      одного из 25 одноразовых приборов: «не применена» печаталась у десяти, а код
      возврата от неё не зависел НИ У ОДНОГО.

    **Подстрокой проба не проходит (ADR-333):** исходник прибора она не читает вовсе,
    а вердикт берёт из машинного вывода (`--json`) и сверяет РАЗЛИЧИЕ трёх ответов, а
    не их словесные ярлыки. Ярлык можно переименовать, различие — нет.

    Отдельным звеном — инертность: файл одноразового дерева после всех трёх прогонов
    обязан совпасть ПОБАЙТОВО. Мутант, оставшийся в дереве, уже случался
    (`inbox-ubityi-progon-perepisi-ostavlyaet-mutant`).

    ТРИ ИСХОДА РАЗЛИЧИМЫ: прибора нет ⇒ `not_satisfied` (это и есть предмет карточки,
    а не «не измерено»); прибор есть, но pytest/дерево не отвечают ⇒ `unmeasured` с
    названной причиной; и никогда `satisfied` без всех трёх сцен.
    """
    import hashlib as _hl
    import json as _json
    import subprocess as _sp
    import tempfile as _tf

    root = repo_root or REPO_ROOT
    tool = os.path.join(root, "scripts", "delta_mutation_run.py")
    if not os.path.exists(tool):
        return NOT_SATISFIED, (
            "прибора мутационного замера по дельте нет в дереве "
            "(scripts/delta_mutation_run.py) — «убито N» из ADR не перемерит никто: "
            "замер 15.10 — 25 одноразовых приборов в /tmp, в репозитории 0")

    def _scene(tmp: str, name: str, mutations: list[dict]) -> tuple[int, dict, str]:
        """Одноразовое дерево + спецификация. Возврат: (код, вердикт, слепок файла)."""
        tree = os.path.join(tmp, name)
        os.makedirs(os.path.join(tree, "pkg"))
        os.makedirs(os.path.join(tree, "t"))
        mod = os.path.join(tree, "pkg", "mod.py")
        with open(mod, "w", encoding="utf-8") as fh:
            fh.write("def value():\n    return 1\n")
        with open(os.path.join(tree, "pkg", "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write("")
        with open(os.path.join(tree, "t", "test_x.py"), "w", encoding="utf-8") as fh:
            fh.write("import sys, os\n"
                     "sys.path.insert(0, os.path.dirname(os.path.dirname("
                     "os.path.abspath(__file__))))\n"
                     "from pkg.mod import value\n\n\n"
                     "def test_value():\n    assert value() == 1\n")
        spec = os.path.join(tree, "spec.json")
        with open(spec, "w", encoding="utf-8") as fh:
            _json.dump({"title": name, "tests": ["t/test_x.py"],
                        "mutations": mutations}, fh, ensure_ascii=False)
        before = _hl.sha256(open(mod, "rb").read()).hexdigest()
        proc = _sp.run([sys.executable, tool, "--spec", spec, "--repo-root", tree,
                        "--json"], capture_output=True, text=True, timeout=600)
        after = _hl.sha256(open(mod, "rb").read()).hexdigest()
        if before != after:
            raise AssertionError(f"сцена {name}: дерево НЕ восстановлено после прогона")
        try:
            verdict = _json.loads(proc.stdout)
        except ValueError:
            verdict = {}
        return proc.returncode, verdict, (proc.stdout + proc.stderr)

    try:
        with _tf.TemporaryDirectory(prefix="probe_c870_") as tmp:
            rc_seen, seen, out_seen = _scene(tmp, "видимая", [
                {"name": "батарея видит", "file": "pkg/mod.py",
                 "old": "return 1", "new": "return 2"}])
            rc_blind, blind, out_blind = _scene(tmp, "невидимая", [
                {"name": "батарея не видит", "file": "pkg/mod.py",
                 "old": "def value()", "new": "def value(_=0)"}])
            rc_none, none_doc, out_none = _scene(tmp, "безякоря", [
                {"name": "якоря нет", "file": "pkg/mod.py",
                 "old": "ТАКОГО-ЯКОРЯ-НЕТ", "new": "x"}])
    except AssertionError as exc:
        return NOT_SATISFIED, str(exc)
    except Exception as exc:                          # noqa: BLE001
        return UNMEASURED, (f"сцену прибора не поднять ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")

    if not seen or not blind or not none_doc:
        return UNMEASURED, ("прибор не отдал машинного вердикта — измерять нечем "
                            f"(видимая: {out_seen.strip()[-200:]!r})")
    if rc_seen != 0:
        return NOT_SATISFIED, (
            f"мутация, которую батарея ВИДИТ, не объявлена измеренной и чистой "
            f"(код {rc_seen}): {out_seen.strip()[-200:]}")
    if rc_blind == rc_seen:
        return NOT_SATISFIED, (
            f"выжившая мутация даёт ТОТ ЖЕ код {rc_blind}, что убитая — находка цикла "
            f"неотличима от чистого замера")
    if rc_none == 0:
        return NOT_SATISFIED, (
            "мутация, НЕ НАШЕДШАЯ якоря, даёт код 0 — «не измерено» выдаётся за "
            "«убито» (инв. #17); ровно этот дефект был у всех 25 одноразовых приборов")
    counts = none_doc.get("counts") or {}
    if not isinstance(counts, dict) or sum(
            v for v in counts.values() if isinstance(v, int)) != 1:
        return NOT_SATISFIED, (
            f"перечень исходов не ЗАКРЫТ: при населении 1 сумма исходов {counts!r} — "
            f"мутация исчезла из вердикта либо посчитана дважды")
    if none_doc.get("applied") != 0:
        return NOT_SATISFIED, (
            f"не применённая мутация вошла в знаменатель «применено» "
            f"({none_doc.get('applied')!r}) — «убито 1 из 1» врёт о том, что измерено")
    return SATISFIED, (
        f"прибор ввезён и перемеряем КОМАНДОЙ: видимая мутация → код {rc_seen}, "
        f"выжившая → {rc_blind}, без якоря → {rc_none} (три РАЗНЫХ ответа); "
        f"знаменатель честен (применено 0 из населения 1), дерево после каждой сцены "
        f"побайтово то же")


def _probe_card_claim_anchored_reports_the_write(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: поле `anchored` отчёта о захвате меряет ЗАПИСЬ, а не пересказывает вход (#872).

    Предмет — карточка `inbox-anchored-pereskazyvaet-vhod-a-ne-meryaet`. ADR-725 довёл
    якорь ЗАПУСКАТЕЛЯ до frontmatter карточки, и в ответе `claim_card` появилась пара
    сообщений об одной записи. Одно из них ИЗМЕРЯЕТ запись
    (`worker_run_id = fields.get("claimed_run_id")`, так сделано с ADR-721), второе —
    НЕТ: `anchored` считалось как `bool(self_anchor)`, то есть отвечало на вопрос «мне
    передали якорь», тогда как читает его тот, кому важно «якорь ДОЕХАЛ до карточки».

    **Разойтись они могли молча, и это не умозрение — у входа не было сторожа.**
    `claim_card` сужал вход выражением `isinstance(self_anchor, (tuple, list))`, и
    всё, что под сужение не попало, превращалось в пустую пару БЕЗ единого слова:
    якорь не писался, захват состоялся, а ответ объявлял `anchored: True`. Мутация
    этого сужения переживала весь набор (замер #869) ровно потому, что контракт входа
    не проверял никто.

    **Вход вне контракта правдоподобен, а не выдуман.** В ТОМ ЖЕ файле якорь живёт
    ВТОРОЙ формой — СЛОВАРЁМ в вокабуляре шага 0a (`card_claim_anchor` отдаёт
    `{"session_pid": …, "session_pid_start": …}`), и именно её естественно передать
    в `self_anchor=`. Цена ошибки — захват, который следующий цикл не измерит НИ ОДНОЙ
    осью (ось работника и ось запускателя обе молчат), с отчётом «якорь есть».

    **Проба меряет ИСХОД и адреса полей не знает литералом (ADR-333).** Сначала гоняет
    настоящий `claim_card` на одноразовой карточке с ПРАВИЛЬНОЙ парой и смотрит, куда
    писатель её положил; затем теми же именами судит две сцены:

    * вход вне контракта (словарь) ⇒ либо ОТКАЗ, либо якорь в карточке. Тихий успех с
      `anchored: True` и пустым frontmatter — `not_satisfied`;
    * пара измерена НЕ ЦЕЛИКОМ (`(pid, "")`) ⇒ пара не пишется (половина личностью не
      является) И `anchored` обязан быть False. Это третий исход, инв. #17.

    Граница названа отдельным звеном: правильная пара обязана по-прежнему давать
    `anchored: True` и запись в карточке — правка дополняющая, а не запрещающая.

    ТРИ ИСХОДА РАЗЛИЧИМЫ: файла нет, не ввозится, нет `claim_card`/`CLAIM_ANCHOR_KEYS`
    ⇒ `unmeasured` с названной причиной, и никогда `satisfied`.
    """
    import importlib.util as _ilu
    import tempfile as _tf
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    root = repo_root or REPO_ROOT
    guard_path = os.path.join(root, "scripts", "check_card_claim.py")
    if not os.path.exists(guard_path):
        return UNMEASURED, f"{guard_path} не найден — шаг 0b НЕ ИЗМЕРИТЬ"
    try:
        spec = _ilu.spec_from_file_location("_probe_c872_card_claim", guard_path)
        guard = _ilu.module_from_spec(spec)          # type: ignore[arg-type]
        spec.loader.exec_module(guard)               # type: ignore[union-attr]
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, f"шаг 0b не ввезён ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО"
    try:
        sibling = guard.load_sibling()
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сосед шага 0a не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    for attr in ("claim_card", "frontmatter", "CLAIM_ANCHOR_KEYS"):
        if not hasattr(guard, attr):
            return UNMEASURED, f"у шага 0b нет {attr!r} — проводку НЕ ИЗМЕРИТЬ"
    #: Вокабуляр ВТОРОЙ формы якоря берётся у соседа, а не парой из головы: сцена
    #: «вход вне контракта» обязана быть той самой формой, что живёт рядом в коде.
    durable_keys = tuple(getattr(sibling, "DURABLE_KEYS", ()) or ())
    if len(durable_keys) != len(tuple(guard.CLAIM_ANCHOR_KEYS or ())) or not durable_keys:
        return UNMEASURED, (f"вокабуляры якоря разошлись (`DURABLE_KEYS`={durable_keys!r} "
                            f"против {tuple(guard.CLAIM_ANCHOR_KEYS or ())!r}) — сцену "
                            f"«вход вне контракта» задать нечем, НЕ ИЗМЕРЕНО")

    now = _dt.now(_tz.utc).replace(microsecond=0)
    START = (now - _td(hours=2)).strftime("%a %b %d %H:%M:%S %Y")
    PID = os.getpid()                 # жив на любой машине по построению, не таймер

    def _dead(_pid):
        return (1, "")

    try:
        with _tf.TemporaryDirectory(prefix="probe_c872_") as tmp:
            def _scene(name, anchor):
                """Одноразовая карточка + пустой журнал; возвращает (ответ, исключение, поля)."""
                tracker = os.path.join(tmp, name)
                os.makedirs(tracker)
                card = os.path.join(tracker, f"inbox-{name}.md")
                with open(card, "w", encoding="utf-8") as fh:
                    fh.write("---\ntrackerStatus:\n  type: inbox\ntitle: сцена\n"
                             "status: new\n---\n\nтело\n")
                before = set(guard.frontmatter(open(card, encoding="utf-8").read()) or {})
                log = os.path.join(tmp, f"{name}.jsonl")
                open(log, "w", encoding="utf-8").close()
                res = err = None
                try:
                    res = guard.claim_card(f"inbox-{name}", log=log,
                                           session=f"cycle-probe872-{name}",
                                           tracker_dir=tracker, now=now, sibling=sibling,
                                           ps=_dead, self_anchor=anchor)
                except Exception as exc:             # noqa: BLE001
                    err = exc
                meta = guard.frontmatter(open(card, encoding="utf-8").read()) or {}
                fresh = {k: str(meta.get(k) or "") for k in set(meta) - before}
                return res, err, fresh

            # ── (1) ГРАНИЦА и АДРЕС: правильная пара, поля ИЗМЕРЯЮТСЯ у писателя ──
            ok_res, ok_err, ok_fresh = _scene("pair", (PID, START))
            if ok_err is not None or not isinstance(ok_res, dict):
                return UNMEASURED, (f"писатель захвата не отработал на ПРАВИЛЬНОЙ паре "
                                    f"({type(ok_err).__name__}: {ok_err}) — НЕ ИЗМЕРЕНО")
            pid_field = next((k for k, v in ok_fresh.items() if v.strip() == str(PID)), None)
            start_field = next((k for k, v in ok_fresh.items() if v.strip() == START), None)
            if pid_field is None or start_field is None:
                return NOT_SATISFIED, (
                    f"писатель не кладёт измеренную пару в карточку вовсе (появились "
                    f"{sorted(ok_fresh)}) — предмет ADR-725 не выполнен, судить о честности "
                    f"отчёта не о чем")
            if ok_res.get("anchored") is not True:
                return NOT_SATISFIED, (
                    f"пара ИЗМЕРЕНА и ЗАПИСАНА (`{pid_field}`/`{start_field}`), а ответ "
                    f"говорит `anchored: {ok_res.get('anchored')!r}` — правка обязана быть "
                    f"дополняющей, а не запрещающей")

            # ── (2) ВХОД ВНЕ КОНТРАКТА: вторая форма якоря, живущая в том же файле ──
            bad_res, bad_err, bad_fresh = _scene(
                "dict", {durable_keys[0]: PID, durable_keys[1]: START})
            wrote = bool(str(bad_fresh.get(pid_field) or "").strip()
                         and str(bad_fresh.get(start_field) or "").strip())
            if bad_err is None and not wrote:
                return NOT_SATISFIED, (
                    f"вход вне контракта ({dict.__name__} в вокабуляре "
                    f"{list(durable_keys)} — ВТОРАЯ форма якоря из того же файла) принят "
                    f"МОЛЧА: захват состоялся, `{pid_field}`/`{start_field}` в карточке "
                    f"нет, а ответ объявляет `anchored: "
                    f"{(bad_res or {}).get('anchored')!r}`. Следующий цикл не измерит этот "
                    f"захват ни одной осью и будет ждать окно целиком")

            # ── (3) ПАРА НЕ ЦЕЛИКОМ: третий исход вместо тихого успеха (инв. #17) ──
            half_res, half_err, half_fresh = _scene("half", (PID, ""))
            if half_err is None:
                if any(str(half_fresh.get(k) or "").strip()
                       for k in (pid_field, start_field)):
                    return NOT_SATISFIED, (
                        f"половина пары УЕХАЛА в карточку ({ {k: half_fresh.get(k) for k in (pid_field, start_field)} }) "
                        f"— `{pid_field}` без старта личностью не является, pid "
                        f"переиспользуется ОС")
                if (half_res or {}).get("anchored") is not False:
                    return NOT_SATISFIED, (
                        f"пара измерена НЕ ЦЕЛИКОМ, в карточку не записана — а ответ всё "
                        f"равно говорит `anchored: {(half_res or {}).get('anchored')!r}`. "
                        f"Это пересказ входа, а не замер записи: читатель поля узнаёт "
                        f"«якорь в карточке» о карточке, где его нет (инв. #17)")
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сцена захвата не собралась ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")

    return SATISFIED, (
        f"`anchored` меряет ЗАПИСЬ: адрес пары измерен у писателя "
        f"(`{pid_field}`/`{start_field}`, литерала у пробы нет) · правильная пара ⇒ "
        f"запись + `anchored: True` · вход вне контракта (словарь {list(durable_keys)}) ⇒ "
        f"{'ОТКАЗ ' + type(bad_err).__name__ if bad_err is not None else 'якорь всё равно записан'} "
        f"· пара не целиком ⇒ "
        f"{'ОТКАЗ ' + type(half_err).__name__ if half_err is not None else 'ни одной строки якоря и `anchored: False`'}")


def _probe_card_claim_anchor_contract_guards_every_reader(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: контракт `self_anchor` судит ОДИН, и его спрашивает КАЖДЫЙ читатель (#873).

    Предмет — карточка `inbox-kontrakt-yakorya-storozhit-odnu-dver-iz`. ADR-727 (#872)
    поставил сторожа контракта у ПИШУЩЕЙ двери (`claim_card`) и сам же назвал остаток
    вслух (заказ G727 п. 1): тот же `self_anchor` принимают ещё ДВА входа — `gather`
    (отчёт шага 0b) и `release_card`, — и у них сторожа нет. Замер #873 на чистой
    вершине `3b417db92` показал, что дверь не теоретическая, а стоит открытой у обоих,
    и цена у неё ровно та, ради которой написан `self_identities`:

    * `gather` со СЛОВАРЁМ вместо пары: `anchor_of(entry) == anchor` не совпадает НИКОГДА
      ⇒ опознание собственных объявлений МОЛЧА выключается, и захват, сделанный ЭТОЙ ЖЕ
      сессией под другим ярлыком, читается как ЧУЖОЙ. Измерено: пара ⇒ `free`
      (`self_sessions` = мой ярлык + ярлык захвата), словарь ⇒ `claimed` — то же, что
      `self_anchor=None`, то есть вход вне контракта НЕОТЛИЧИМ от ОБЪЯВЛЕННОГО отключения;
    * `release_card` со СЛОВАРЁМ: «снять чужой захват можно только с --force» о СВОЕЙ
      карточке — дословно дефект цикла #70, из-за которого `self_identities` и появился.

    Это зеркало fail-OPEN: не ложная свобода, а ложная занятость — но цена её измерена
    08.10 (ЧЕТЫРЕ карточки неберущимися, среди них критический приказ владельца, 634
    цикла мимо), и молчит она так же.

    **Проба меряет ИСХОД и строк отказа не знает литералом (ADR-333).** Сцена: карточка,
    захваченная ярлыком `HOLDER`, и запись журнала, написанная ТЕМ ЖЕ долгоживущим
    процессом под тем же ярлыком. По ней гоняются три формы входа, и судит РАЗНИЦА между
    ними, а не текст:

    * пара (`anchor_of`-форма) — положительный контроль сцены: без неё опознание не
      работает ни у кого, и судить о дверях не о чем ⇒ `unmeasured`;
    * `None` — ОБЪЯВЛЕННОЕ отключение опознания (так зовут герметичные тесты): поведение
      обязано остаться прежним, иначе правка запрещающая, а не дополняющая;
    * словарь в вокабуляре шага 0a — вход ВНЕ контракта. Он обязан ОТКАЗАТЬ с причиной,
      ОТЛИЧНОЙ от исхода `None`. Совпал с `None` ⇒ `not_satisfied`: это и есть тихий
      сброс, при котором «не измерено» выдано за измеренную занятость.

    ТРИ ИСХОДА РАЗЛИЧИМЫ: файла нет, не ввозится, нет `gather`/`release_card`/вокабуляра
    ⇒ `unmeasured` с названной причиной, и никогда `satisfied`.
    """
    import importlib.util as _ilu
    import json as _json
    import tempfile as _tf
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    root = repo_root or REPO_ROOT
    guard_path = os.path.join(root, "scripts", "check_card_claim.py")
    if not os.path.exists(guard_path):
        return UNMEASURED, f"{guard_path} не найден — шаг 0b НЕ ИЗМЕРИТЬ"
    try:
        spec = _ilu.spec_from_file_location("_probe_c873_card_claim", guard_path)
        guard = _ilu.module_from_spec(spec)          # type: ignore[arg-type]
        spec.loader.exec_module(guard)               # type: ignore[union-attr]
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, f"шаг 0b не ввезён ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО"
    try:
        sibling = guard.load_sibling()
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сосед шага 0a не ввезён ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")
    for attr in ("gather", "release_card", "CLAIM_ANCHOR_KEYS"):
        if not hasattr(guard, attr):
            return UNMEASURED, f"у шага 0b нет {attr!r} — проводку НЕ ИЗМЕРИТЬ"
    #: Вокабуляр ВТОРОЙ формы якоря берётся у соседа, а не парой из головы: сцена «вход
    #: вне контракта» обязана быть той самой формой, что живёт рядом в коде.
    durable_keys = tuple(getattr(sibling, "DURABLE_KEYS", ()) or ())
    if len(durable_keys) != len(tuple(guard.CLAIM_ANCHOR_KEYS or ())) or not durable_keys:
        return UNMEASURED, (f"вокабуляры якоря разошлись (`DURABLE_KEYS`={durable_keys!r} "
                            f"против {tuple(guard.CLAIM_ANCHOR_KEYS or ())!r}) — сцену "
                            f"«вход вне контракта» задать нечем, НЕ ИЗМЕРЕНО")

    now = _dt.now(_tz.utc).replace(microsecond=0)
    #: pid ЖИВ на любой машине по построению (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ
    #: ПРОЦЕССА», приём №2); ответ ОС за живость всё равно даёт инъекция `ps=`.
    PID = os.getpid()
    START = (now - _td(hours=2)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
    HOLDER = f"pid{PID}"
    MINE = f"cycle-probe873-{PID}"
    AT = (now - _td(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    PAIR = (PID, START)
    DICT = {durable_keys[0]: PID, durable_keys[1]: START}

    def _dead(_pid):
        return (1, "")

    class _MuteAnnouncer:
        """Объявлять снятие захвата НЕКУДА: сцена одноразовая, общий журнал не трогаем."""

        def record(self, *a, **k):
            return None

        def append(self, *a, **k):
            return None

    try:
        with _tf.TemporaryDirectory(prefix="probe_c873_") as tmp:
            def _scene(name):
                """Одноразовые карточка + журнал: ТОТ ЖЕ процесс объявил захват под HOLDER."""
                tracker = os.path.join(tmp, name)
                os.makedirs(tracker)
                with open(os.path.join(tracker, "inbox-scene.md"), "w",
                          encoding="utf-8") as fh:
                    fh.write("---\ntrackerStatus:\n  type: inbox\ntitle: сцена\n"
                             f"status: in-progress\nclaimed_by: {HOLDER}\n"
                             f"claimed_at: {AT}\n---\n\nтело\n")
                log = os.path.join(tmp, f"{name}.jsonl")
                with open(log, "w", encoding="utf-8") as fh:
                    fh.write(_json.dumps({
                        "ts": AT, "session": HOLDER, "card": "inbox-scene",
                        "summary": "[check_card_claim] claim inbox-scene",
                        durable_keys[0]: PID, durable_keys[1]: START}) + "\n")
                    # ВТОРАЯ запись — БЕЗ якоря и о ДРУГОЙ карточке. Она нужна звену
                    # (4): при `self_anchor=None` опознание обязано ВЫКЛЮЧАТЬСЯ рано, а
                    # не сравнивать `anchor_of(entry) == None` — иначе любая запись без
                    # якоря становится «моей». Без этой строки граница была бы заявлена,
                    # но не наблюдаема (замер мутациями #873: ветка выживала).
                    # Карточка намеренно ДРУГАЯ: о `inbox-scene` эта запись молчит,
                    # поэтому лишнего захвата в сцене не появляется.
                    fh.write(_json.dumps({
                        "ts": AT, "session": f"{HOLDER}-anchorless",
                        "card": "inbox-another",
                        "summary": "[check_card_claim] claim inbox-another"}) + "\n")
                return tracker, log

            def _read(name, anchor):
                """`gather` на сцене: (вердикт либо отказ, опознанные ярлыки)."""
                tracker, log = _scene(name)
                try:
                    r = guard.gather("inbox-scene", log=log, tracker_dir=tracker,
                                     sibling=sibling, self_session=MINE, now=now,
                                     ps=_dead, self_anchor=anchor, shared_trees=())
                except Exception as exc:             # noqa: BLE001
                    return f"ОТКАЗ:{type(exc).__name__}:{exc}", None
                return str(r.get("verdict")), sorted(r.get("self_sessions") or [])

            def _free(name, anchor):
                """`release_card` на сцене: исход словом (отпущена либо текст отказа)."""
                tracker, log = _scene(name)
                try:
                    res = guard.release_card("inbox-scene", log=log, session=MINE,
                                             tracker_dir=tracker, self_anchor=anchor,
                                             announcer=_MuteAnnouncer())
                except Exception as exc:             # noqa: BLE001
                    return f"ОТКАЗ:{type(exc).__name__}:{exc}"
                return f"ОТПУЩЕНА:{bool((res or {}).get('released'))}"

            # ── (1) ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ СЦЕНЫ: пара обязана опознавать HOLDER своим ──
            #
            # ЗАМЕР #873 про ЭТУ ветку, чтобы её не «чинили» заново: мутация
            # `if False:` на ней ВЫЖИВАЕТ, и выживший РАВНОСИЛЕН — при порванном
            # опознании вердикт пробы остаётся `unmeasured`, а состояние называет
            # соседняя предпосылка сцены снятия («опознание не работает и с
            # контрактным входом»). Ветка оставлена не для покрытия, а ради ДРУГОГО
            # исхода: `gather`, сломанный целиком, даёт `pair_selves is None`, и без
            # этой ветки такой случай ушёл бы в `not_satisfied` — то есть «не
            # измерено» было бы выдано за измеренный дефект (инв. #17).
            pair_verdict, pair_selves = _read("read_pair", PAIR)
            if pair_selves is None or HOLDER not in pair_selves:
                return UNMEASURED, (
                    f"сцена не способна двигать вердикт: с ПРАВИЛЬНОЙ парой "
                    f"`self_sessions`={pair_selves!r} не содержит ярлык захвата "
                    f"{HOLDER!r} (вердикт {pair_verdict!r}) — опознание не работает и с "
                    f"контрактным входом, судить о дверях НЕ О ЧЕМ")
            # Второго контроля «пара и `None` дают разный вердикт» здесь НЕТ
            # намеренно: он отвечает на тот же вопрос, что звено (1) выше, и замер
            # мутациями #873 показал ровно обещанное правилом — два условия об одном
            # МАСКИРУЮТ друг друга, после чего снятие любого перестаёт ловиться.
            # Опознание `HOLDER` контрактной парой есть ПРЕДПОСЫЛКА, а разность
            # вердиктов — её следствие (захват жив ⇒ свой не блокирует, чужой мёртвый
            # блокирует иначе), поэтому оставлен один — специфичный.
            none_verdict, none_selves = _read("read_none", None)

            # ── (2) ЧИТАЮЩАЯ ДВЕРЬ `gather` ──
            #
            # ЗАМЕР #873 про ЭТУ ветку, чтобы её не «чинили» заново: мутация `if False:`
            # на ней ВЫЖИВАЕТ, и выживший РАВНОСИЛЕН — снятие сторожа у `gather` ловит
            # ветка (2б) про СПИСОК (измерено двойной мутацией: вердикт остаётся
            # `not_satisfied`, причина названа). Ветка оставлена потому, что утверждения
            # РАЗНЫЕ: здесь «вход вне контракта обязан ОТКАЗАТЬ», там «контрактный, но
            # не приведённый, обязан дать ТОТ ЖЕ исход». Одна поломка трогает оба, но
            # поломки бывают и по отдельности.
            dict_verdict, dict_selves = _read("read_dict", DICT)
            if dict_verdict == none_verdict and dict_selves == none_selves:
                return NOT_SATISFIED, (
                    f"`gather`: вход вне контракта ({dict.__name__} в вокабуляре "
                    f"{list(durable_keys)} — ВТОРАЯ форма якоря из того же файла) принят "
                    f"МОЛЧА и НЕОТЛИЧИМ от объявленного отключения `None`: оба дают "
                    f"{dict_verdict!r} при `self_sessions`={dict_selves!r}, тогда как "
                    f"контрактная пара даёт {pair_verdict!r} при {pair_selves!r}. Захват "
                    f"ЭТОЙ ЖЕ сессии читается как ЧУЖОЙ, и об этом не сказано ни слова")

            # ── (2б) ВХОД КОНТРАКТНОЙ ФОРМЫ, НО НЕ ТОЙ: список ──
            #
            # Сторож его ПРОПУСКАЕТ (так же, как прежнее сужение
            # `isinstance(..., (tuple, list))`), поэтому отказа здесь не будет и быть не
            # должно — судить надо ИСХОД. `anchor_of(entry)` отдаёт ТУПЛ, а
            # `tuple != list` в Python никогда не равны: список, пропущенный БЕЗ
            # приведения к пáре, выключает опознание так же, как словарь, но МОЛЧА и без
            # отказа — то есть одна половина класса закрыта, а вторая стала незаметнее
            # прежней. Замер #873 на УЖЕ ИСПРАВЛЕННЫХ дверях: `[pid, старт]` ⇒ `stale`
            # при `(pid, старт)` ⇒ `free`.
            list_verdict, list_selves = _read("read_list", list(PAIR))
            if (list_verdict, list_selves) != (pair_verdict, pair_selves):
                return NOT_SATISFIED, (
                    f"`gather`: СПИСОК контрактной длины сторож пропускает, но пáрой не "
                    f"делает — исход расходится с туплом: список ⇒ {list_verdict!r} при "
                    f"`self_sessions`={list_selves!r}, тупл ⇒ {pair_verdict!r} при "
                    f"{pair_selves!r}. Контракт обязан ПРИВОДИТЬ вход, а не только "
                    f"проверять его форму: `anchor_of` отдаёт тупл, и `tuple != list` "
                    f"никогда не равны — опознание выключается БЕЗ отказа, то есть тише "
                    f"словаря")

            # ── (3) ПИШУЩАЯ ДВЕРЬ `release_card` — тот же вход, свой исход ──
            pair_release = _free("free_pair", PAIR)
            if not pair_release.startswith("ОТПУЩЕНА"):
                return UNMEASURED, (
                    f"сцена снятия не способна двигать исход: с КОНТРАКТНОЙ парой "
                    f"`release_card` дал {pair_release!r} вместо снятия — опознание не "
                    f"работает и с контрактным входом, судить о двери НЕ О ЧЕМ")
            none_release = _free("free_none", None)
            dict_release = _free("free_dict", DICT)
            if dict_release == none_release:
                return NOT_SATISFIED, (
                    f"`release_card`: вход вне контракта принят МОЛЧА и НЕОТЛИЧИМ от "
                    f"объявленного отключения `None` — оба дают {dict_release!r}, тогда "
                    f"как контрактная пара даёт {pair_release!r}. Это дословно дефект "
                    f"цикла #70: сессия отказывает САМА СЕБЕ в снятии своего захвата, и "
                    f"единственный выход — `--force`, который снимает и НАСТОЯЩИЙ чужой")

            # ── (4) ГРАНИЦА: объявленное отключение обязано работать как прежде ──
            if none_selves != [MINE]:
                return NOT_SATISFIED, (
                    f"`self_anchor=None` — ОБЪЯВЛЕННОЕ отключение опознания (им зовут "
                    f"герметичные тесты), а `self_sessions`={none_selves!r} вместо "
                    f"[{MINE!r}]: сторож контракта обязан быть дополняющим, а не менять "
                    f"прежнее поведение")
    except Exception as exc:                         # noqa: BLE001
        return UNMEASURED, (f"сцена захвата не собралась ({type(exc).__name__}: {exc}) — "
                            f"НЕ ИЗМЕРЕНО")

    return SATISFIED, (
        f"контракт `self_anchor` спрашивают ОБЕ читающие двери, и обе отвечают ОТЛИЧНО от "
        f"объявленного отключения: `gather` пара ⇒ {pair_verdict} ({pair_selves}) · `None` "
        f"⇒ {none_verdict} · словарь {list(durable_keys)} ⇒ {dict_verdict!r}; "
        f"`release_card` пара ⇒ {pair_release} · `None` ⇒ {none_release!r} · словарь ⇒ "
        f"{dict_release!r}. Литерала отказа у пробы нет — судит РАЗНИЦА исходов (ADR-333)")

def _probe_delivery_door_refuses_card_section_loss(
    arg: str | None, *, repo_root: str | None = None,
) -> tuple[str, str]:
    """Критерий: дверь доставки отказывает доставке, стирающей РАЗДЕЛЫ карточки.

    Предмет — находка цикла #874 и ADR-729, заказ G728. Сторож записей цикла
    (#858, ADR-714) закрыл карточки-ТЕТРАДИ: его единица смысла — запись цикла,
    и тождество у неё НОМЕР. Замер 15.10 поправил заказ в двух местах сразу:
    сторож на названном файле ЕСТЬ и ОТКАЗЫВАЕТ (заказ утверждал обратное), но
    его единица смысла живёт у ДВУХ карточек из 103, у которых живая копия
    короче origin, — на 101 он молчит по построению.

    По всей истории трекера (157 пар, где карточка существовала и в родителе;
    производная доска исключена) доставка стирала разделы в 14 парах, из них
    СЕМЬ — настоящая потеря, и прежняя мера видела ОДНУ из семи. Шесть молчащих —
    карточки ВЛАДЕЛЬЦА, коммит ``2427751a6`` (07.10), и содержимого их на origin
    нет по сей день.

    **Меряется ИСХОД У ДВЕРИ** на настоящей паре байт той потери, а не наличие
    функции: проба зовёт ``push_to_github.guard_content_loss``.

    **Предпосылка проверяется и в ОБРАТНУЮ сторону:** если прежняя мера (запись
    цикла) на этой же сцене уже отказывает, сцена ничего нового не измеряет ⇒
    ``unmeasured``. Зелёный обязан означать «виден НОВЫЙ класс», а не «виден
    хоть какой-то».

    **Три обратные стороны внутри самой пробы** (сторож, говорящий «нет» всему,
    пробу бы удовлетворил):

    * чистое ДОПИСЫВАНИЕ к той же карточке — дверь обязана молчать;
    * переписанный ЗАГОЛОВОК при ВЫРОСШЕЙ карточке (форма, измеренная в истории
      7 раз, 5 из них на стоячем приказе) — дверь обязана НЕ отказать, но
      НАЗВАТЬ: отказ здесь означал бы `--allow-overwrite` каждый цикл, то есть
      лазейку под рукой, а молчание — потерю, выданную за чистоту (инв. #17);
    * производная доска ``_BOARD.md`` при той же паре — дверь обязана молчать:
      в её заголовках стои́т живой счётчик, и тождество нестабильно по
      построению.

    **Источник пары НАЗВАН** (инв. #17): история git, иначе фикстуры батареи;
    зелёный на фикстуре не должен читаться как зелёный на истории.

    ТРИ ИСХОДА РАЗЛИЧИМЫ: пушер не ввезён / пары байт нет ни в истории, ни в
    фикстурах / в паре нет той самой потери либо её видит прежняя мера ⇒
    ``unmeasured`` с названной причиной, и никогда ``satisfied``.
    """
    import importlib.util as _ilu
    import subprocess as _sp

    root = repo_root or REPO_ROOT
    pusher_path = os.path.join(root, "push_to_github.py")
    if not os.path.exists(pusher_path):
        return UNMEASURED, f"{pusher_path} не найден — дверь доставки НЕ ИЗМЕРЕНА"
    try:
        spec = _ilu.spec_from_file_location("_probe_pusher_c874", pusher_path)
        pusher = _ilu.module_from_spec(spec)
        spec.loader.exec_module(pusher)
    except Exception as exc:                        # noqa: BLE001
        return UNMEASURED, f"пушер не ввезён ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО"
    #: Спрашивается РОВНО то, без чего не измерить ИСХОД У ДВЕРИ. Меру разделов
    #: (`CARD_SECTION_RE`) в этот список класть НЕЛЬЗЯ: на чистой вершине её нет
    #: ПО ОПРЕДЕЛЕНИЮ, и проба объявила бы «не измерено» там, где дефект
    #: измеряется прямо — дверь зовётся и потерю ПРОПУСКАЕТ. Это ровно подмена,
    #: против которой написан инв. #17 (урок цикла #465).
    for attr in ("guard_content_loss", "CYCLE_RECORD_RE", "classify_missing_entries"):
        if not hasattr(pusher, attr):
            return UNMEASURED, (f"у пушера нет {attr!r} — исход у двери НЕ ИЗМЕРИТЬ")

    card = ("nimbalyst-local/tracker/"
            "owner-decision-kritichnaya-nahodka-petli-com-spa-tier1-2.md")
    incident = "2427751a6"
    before = after = None
    source = ""
    try:
        r0 = _sp.run(["git", "-C", root, "cat-file", "blob", f"{incident}^:{card}"],
                     capture_output=True, timeout=30)
        r1 = _sp.run(["git", "-C", root, "cat-file", "blob", f"{incident}:{card}"],
                     capture_output=True, timeout=30)
        if r0.returncode == 0 and r1.returncode == 0 and r0.stdout and r1.stdout:
            before, after, source = r0.stdout, r1.stdout, "история git"
    except Exception:                               # noqa: BLE001 — источник не единственный
        before = after = None
    if before is None:
        fix = os.path.join(root, "spa_core", "tests", "fixtures", "card_section_loss")
        try:
            with open(os.path.join(fix, f"owner_{incident}_before.md"), "rb") as fh:
                before = fh.read()
            with open(os.path.join(fix, f"owner_{incident}_after.md"), "rb") as fh:
                after = fh.read()
            source = "фикстуры батареи (истории git нет — глубина клона)"
        except OSError as exc:
            return UNMEASURED, (f"пары байт потери {incident} нет ни в истории git, ни в "
                                f"фикстурах ({exc}) — отказ двери НЕ ИЗМЕРЕН")

    # Предпосылка №1: пара и правда укорачивает карточку. Число РАЗДЕЛОВ мерится
    # мерой ПУШЕРА, если она у него есть; её отсутствие — это не «не измерено», а
    # предмет самой пробы, и вердикт о нём выносится ниже, у двери.
    has_measure = hasattr(pusher, "CARD_SECTION_RE")
    lost = []
    if has_measure:
        lost, _renamed = pusher.classify_missing_entries(before, after,
                                                         pusher.CARD_SECTION_RE)
    delta = after.count(b"\n") - before.count(b"\n")
    if delta >= 0 or (has_measure and len(lost) != 4):
        return UNMEASURED, (f"в паре байт {incident} пропало {len(lost)} раздел(ов) при "
                            f"{delta:+d} строк(и) — потеря 07.10 была на 4 разделах и "
                            f"-75 строках; предпосылка пробы НЕ ОБЕСПЕЧЕНА "
                            f"(источник {source})")
    # Предпосылка №2 (обратная сторона предпосылки): прежняя мера эту сцену НЕ видит.
    # Иначе зелёный говорил бы «класс виден», не отвечая, НОВОЙ ли мерой.
    old_lost, _ = pusher.classify_missing_entries(before, after, pusher.CYCLE_RECORD_RE)
    if old_lost:
        return UNMEASURED, (f"сцену {incident} видит и ПРЕЖНЯЯ мера (записей цикла "
                            f"пропало {len(old_lost)}) — новый класс на ней НЕ ИЗМЕРИТЬ "
                            f"(источник {source})")

    try:
        note = pusher.guard_content_loss(card, before, after, f"{incident}aa")
        measure = ("мера разделов у пушера ЕСТЬ" if has_measure
                   else "меры разделов у пушера НЕТ ВОВСЕ")
        return NOT_SATISFIED, (f"дверь доставки ПРОПУСКАЕТ потерю разделов карточки "
                               f"ВЛАДЕЛЬЦА при {delta:+d} строк(и) — {measure} "
                               f"(нота: {note or 'пусто'}; источник {source})")
    except Exception as exc:                        # noqa: BLE001 — разбираем ниже
        #: ОТКАЗ и ПОЛОМКА — разные исходы, и смешать их значило бы зачесть
        #: падение двери за её защиту. Класс отказов у пушера объявлен
        #: (`DivergenceRefused`); всё прочее — дверь УПАЛА, ничего не рассудив.
        refusal_class = getattr(pusher, "DivergenceRefused", None)
        if refusal_class is None or not isinstance(exc, refusal_class):
            return NOT_SATISFIED, (f"дверь УПАЛА, а не отказала "
                                   f"({type(exc).__name__}: {str(exc)[:160]}) — "
                                   f"поломка защитой не является (источник {source})")
        refused = str(exc)
    if not has_measure:
        return NOT_SATISFIED, (f"дверь отказала, но меры РАЗДЕЛОВ у пушера нет — отказ "
                               f"пришёл от другого сторожа, и класс {incident} закрыт не "
                               f"им: {refused[:200]}")
    if not hasattr(pusher, "GENERATED_TRACKER_DOCS"):
        return NOT_SATISFIED, ("у пушера нет перечня производных индексов трекера — "
                               "исключение доски объявлено НИГДЕ, и отказ наступал бы на "
                               "каждой её перегенерации")
    #: Имя пропавшего раздела берётся ИЗ ЗАМЕРА, а не литералом (ADR-333).
    named = lost[0].decode("utf-8", "replace").lstrip("# ").strip()[:40]
    if named not in refused:
        return NOT_SATISFIED, (f"дверь отказала, но НЕ НАЗВАЛА пропавшие разделы "
                               f"(ожидался «{named}») — по такому отказу не рассудить, "
                               f"потеря это или переименование (источник {source})")

    # Обратная сторона 1: чистое дописывание дверь обязана пропустить.
    appended = before + "\n## Дописанный раздел\n\nтело\n".encode("utf-8")
    try:
        back = pusher.guard_content_loss(card, before, appended, f"{incident}aa")
    except Exception as exc:                        # noqa: BLE001
        return NOT_SATISFIED, (f"дверь отказывает и ЧИСТОМУ ДОПИСЫВАНИЮ "
                               f"({type(exc).__name__}: {str(exc)[:160]}) — сторож, "
                               f"который говорит «нет» всему, не отличает потерю от работы")
    if back:
        return NOT_SATISFIED, f"на чистом дописывании дверь не молчит: {back[:200]}"

    # Обратная сторона 2: переписанный заголовок при ВЫРОСШЕМ файле — нота, не отказ.
    # Тело тоже меняется: иначе это распознаётся как переименование, а в истории
    # менялись И заголовок, И тело (`### Что осталось по ТЗ (обновлено циклом #820)`).
    head = lost[0]
    #: Меняются И заголовок, И тело — ровно форма истории: `### Что осталось по ТЗ
    #: (обновлено этим циклом)` → `(обновлено циклом #820)` с новым перечнем внутри.
    #: Если бы тело совпало побайтово, сцена ушла бы в ветку переименования и о
    #: ветке «пропал, но файл вырос» не сказала бы ничего.
    grown = before.replace(
        head,
        head + " (обновлено циклом #874)".encode("utf-8")
        + "\n\nпереписанное тело раздела\n".encode("utf-8"), 1)
    grown = grown + ("дописанное тело\n" * 30).encode("utf-8")
    try:
        rewritten = pusher.guard_content_loss(card, before, grown, f"{incident}aa")
    except Exception as exc:                        # noqa: BLE001
        return NOT_SATISFIED, (f"дверь ОТКАЗЫВАЕТ переписанному заголовку при выросшей "
                               f"карточке ({type(exc).__name__}: {str(exc)[:160]}) — в "
                               f"истории это 7 случаев из 14, пять из них на стоячем "
                               f"приказе: такой отказ означает `--allow-overwrite` "
                               f"каждый цикл, то есть лазейку под рукой")
    if not rewritten.strip():
        return NOT_SATISFIED, ("переписанный заголовок при выросшей карточке дверь "
                               "ПРОМОЛЧАЛА — «не блокирует» не значит «не называть» "
                               "(инв. #17)")

    # Обратная сторона 3: производная доска — не тетрадь, памяти своей не имеет.
    board = ("nimbalyst-local/tracker/"
             + tuple(pusher.GENERATED_TRACKER_DOCS)[0])
    try:
        board_note = pusher.guard_content_loss(board, before, after, f"{incident}aa")
    except Exception as exc:                        # noqa: BLE001
        return NOT_SATISFIED, (f"дверь ОТКАЗЫВАЕТ производной доске {board} "
                               f"({type(exc).__name__}) — её заголовки несут живой "
                               f"счётчик, и отказ наступал бы на каждой перегенерации")
    if board_note.strip():
        return NOT_SATISFIED, (f"производная доска не исключена: дверь о ней говорит "
                               f"{board_note[:160]}")

    return SATISFIED, (f"дверь ОТКАЗЫВАЕТ доставке, стирающей {len(lost)} разделов "
                       f"карточки владельца при {delta:+d} строк(и) (разделы названы "
                       f"поимённо), и МОЛЧИТ на дописывании и на производной доске; "
                       f"переписанный заголовок при выросшей карточке НАЗЫВАЕТ, но не "
                       f"блокирует. Прежняя мера (записи цикла) на этой сцене молчит — "
                       f"класс измерен НОВОЙ мерой. Источник пары — {source}")


#: Разрешённые читатели отчёта тир-куратора — те, чью ЧИСТОТУ и мерит проба ниже.
#: Правило «кому читать можно» живёт у сторожа (`test_no_module_consumes_report_to_mutate_tiers`);
#: здесь — только адреса, по которым спрашивается признак.
TIER_REPORT_READERS = ("spa_core/monitoring/findings_bridge.py",
                       "spa_core/monitoring/card_acceptance.py")

#: Сторож, чьей мерой прибор обязан БЫТЬ. Прибор без зовущего — отчёт без читателя.
TIER_GUARD_FILE = "spa_core/tests/test_tier_curator.py"

#: Формы записи настоящего прикосновения к канону тира. Перечень ЗАКРЫТ и проверяется
#: целиком: подстрочный список ловил ровно первую строку таблицы и ни одной из
#: остальных — ложный зелёный, который никому не виден (карточка 02.10).
TIER_TOUCH_FORMS = (
    ("плоский ввоз модуля", "import spa_core.risk.policy\n"),
    ("ввоз имени из модуля", "from spa_core.risk.policy import RiskConfig\n"),
    ("ввоз под псевдонимом", "from spa_core.risk.policy import RiskConfig as RC\n"),
    ("модуль под псевдонимом", "import spa_core.adapters.registry as reg\n"),
    ("ввоз куратора", "from spa_core.analytics.tier_curator import curate\n"),
    # Две формы ниже прежний подстрочный список не ловил ВООБЩЕ: дословного
    # `risk.policy` / `analytics.tier_curator` в них нет ни разу (замер 15.10,
    # цикл #875) — это и есть измеренный ложный ЗЕЛЁНЫЙ, а не предположенный.
    ("ввоз модуля из пакета", "from spa_core.analytics import tier_curator\n"),
    ("модуль из пакета под псевдонимом", "from spa_core.risk import policy as pol\n"),
    ("голое имя канона", "x = tier_map[p]\n"),
    ("обращение к атрибуту", "v = cfg.PROTOCOL_RISK_SCORES\n"),
    ("динамический доступ строкой", 'c = getattr(mod, "RiskConfig")\n'),
    ("динамический ввоз строкой",
     'm = importlib.import_module("spa_core.adapters.registry")\n'),
)

#: Сцена ложного КРАСНОГО 2026-10-02 — дословная форма, которой сторож краснел
#: тринадцать суток: докстрока о ЧУЖОМ приборе плюс текст сообщения в f-строке.
TIER_PROSE_SCENE = (
    '\"\"\"прибор читает из `RiskConfig` (§22 приказа: «Не hardcode»).\"\"\"\n'
    'def report(n):\n'
    '    return f"из RiskConfig ({n} полей)"\n'
)


def _probe_tier_guard_judges_code_not_prose(
        arg: str | None, *, repo_root: str | None = None) -> tuple[str, str]:
    """Сторож канона тира судит о КОДЕ, а не о наборе байт — по исходу, не по структуре.

    Карточка `inbox-storozh-tira-sudit-podstrokoi-i-krasen-n` (02.10): сторож
    `test_no_module_consumes_report_to_mutate_tiers` спрашивал `forbidden not in text`
    и был КРАСЕН на верном состоянии — слово `RiskConfig` стои́т в `card_acceptance.py`
    дважды, и оба раза проза. У дефекта две стороны, и проба мерит обе: ложный красный
    видно, ложный зелёный (настоящий ввоз, записанный иначе) не видно никому.

    Пять звеньев; любое одно порванное даёт `not_satisfied` с ИМЕНЕМ звена:

    1. **прибор молчит на ЖИВЫХ разрешённых читателях** — прикосновений к канону у них
       нет, и это замер, а не доверие списку;
    2. **кусается на КАЖДОЙ форме записи** (`TIER_TOUCH_FORMS`, перечень закрыт) —
       прибор, слепой к псевдониму или к `getattr`, есть прежняя подстрока в новой
       одежде;
    3. **молчит на ПРОЗЕ** — воспроизводится дословная сцена 02.10;
    4. **неразбираемый исходник — третий исход, а не «чисто»** (`TierTouchUnmeasured`,
       инв. #17): прибор, проглотивший опечатку, отдаёт ложный зелёный;
    5. **сторож ЗОВЁТ прибор и не держит своей копии правила** — ввоз `tier_touch`
       проверяется разбором, а не подстрокой, и в файле сторожа не должно остаться
       литерального перечня канона: два перечня на одно правило разъехались бы молча.

    `repo_root` — вход: контроль в обе стороны подаёт одноразовое дерево и рвёт звенья
    поимённо. Живое дерево ничем не трогается: проба только ЧИТАЕТ.
    """
    if (arg or "").strip():
        return UNMEASURED, (f"проба не принимает аргумента (дано {arg!r}): предмет — "
                            "сторож канона целиком, пофайловой формы у него нет")
    import ast as _ast
    root = repo_root or REPO_ROOT
    try:
        from spa_core.monitoring import tier_touch as tt
    except ImportError as exc:
        return UNMEASURED, f"прибор tier_touch не ввезён ({exc}) — признак НЕ ИЗМЕРЕН"

    def _read(rel: str) -> "tuple[str | None, str]":
        path = os.path.join(root, rel)
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read(), ""
        except OSError as exc:
            return None, f"{rel} не прочитан ({exc})"

    # 1. живые читатели
    for rel in TIER_REPORT_READERS:
        text, why = _read(rel)
        if text is None:
            return UNMEASURED, f"{why} — чистота читателя НЕ ИЗМЕРЕНА"
        try:
            touches = tt.tier_touches(text)
        except tt.TierTouchUnmeasured as exc:
            return UNMEASURED, f"{rel}: {exc} — чистота читателя НЕ ИЗМЕРЕНА"
        if touches:
            return NOT_SATISFIED, (f"разрешённый читатель ТРОГАЕТ канон тира — "
                                   f"{tt.describe(rel, touches)}")

    # 2. кусается на каждой форме
    for label, source in TIER_TOUCH_FORMS:
        try:
            touches = tt.tier_touches(source)
        except tt.TierTouchUnmeasured as exc:
            return UNMEASURED, f"форма «{label}» не разобрана ({exc}) — прибор НЕ ИЗМЕРЕН"
        if not touches:
            return NOT_SATISFIED, (f"прибор НЕ КУСАЕТСЯ на форме «{label}»: "
                                   f"{source.strip()!r} прошло как чистое — это та же "
                                   "подстрока, только с разбором")

    # 3. молчит на прозе
    try:
        prose = tt.tier_touches(TIER_PROSE_SCENE)
    except tt.TierTouchUnmeasured as exc:
        return UNMEASURED, f"сцена прозы не разобрана ({exc}) — ложный красный НЕ ИЗМЕРЕН"
    if prose:
        return NOT_SATISFIED, ("прибор краснеет на ПРОЗЕ — сцена 02.10 не закрыта: "
                               + tt.describe("<проза>", prose))

    # 4. третий исход
    try:
        tt.tier_touches("def broken(:\n    tier_map\n")
    except tt.TierTouchUnmeasured:
        pass
    else:
        return NOT_SATISFIED, ("неразбираемый исходник НЕ стал третьим исходом — "
                               "прибор выдаёт опечатку за чистоту (инв. #17)")

    # 5. сторож зовёт прибор и не держит своей копии правила
    guard, why = _read(TIER_GUARD_FILE)
    if guard is None:
        return UNMEASURED, f"{why} — зовущий НЕ ИЗМЕРЕН"
    try:
        tree = _ast.parse(guard)
    except SyntaxError as exc:
        return UNMEASURED, f"{TIER_GUARD_FILE} не разобран ({exc}) — зовущий НЕ ИЗМЕРЕН"
    calls_instrument = False
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ImportFrom) and (node.module or "").endswith(
                "monitoring.tier_touch"):
            calls_instrument = True
        elif isinstance(node, _ast.ImportFrom) and (node.module or "").endswith(
                "monitoring") and any(a.name == "tier_touch" for a in node.names):
            calls_instrument = True
        elif isinstance(node, _ast.Import) and any(
                a.name.endswith("monitoring.tier_touch") for a in node.names):
            calls_instrument = True
    if not calls_instrument:
        return NOT_SATISFIED, (f"{TIER_GUARD_FILE} не ЗОВЁТ прибор — признак снова "
                               "живёт у сторожа своей копией, и прибор есть украшение")
    canon = set(tt.TIER_CANON_NAMES) | set(tt.TIER_CANON_MODULES)
    for node in _ast.walk(tree):
        if not isinstance(node, (_ast.Tuple, _ast.List, _ast.Set)):
            continue
        literal = {e.value for e in node.elts
                   if isinstance(e, _ast.Constant) and isinstance(e.value, str)}
        shared = literal & canon
        if len(shared) >= 2:
            return NOT_SATISFIED, (f"{TIER_GUARD_FILE}:{node.lineno} держит свою копию "
                                   f"перечня канона ({sorted(shared)}) — правило снова "
                                   "в двух местах, и разъедутся они молча")

    return SATISFIED, (f"сторож судит о коде: прибор молчит на {len(TIER_REPORT_READERS)} "
                       f"живых читателях, кусается на всех {len(TIER_TOUCH_FORMS)} формах "
                       f"записи, молчит на дословной прозе 02.10, неразбираемое называет "
                       f"третьим исходом, и {TIER_GUARD_FILE} зовёт именно его, своей "
                       f"копии перечня не держа")


#: DIRECTOR-OS-UX-02 (ADR-762): the fixed scene the owner-view probe is judged on — a read-only
#: snapshot of one real bundle, never re-read from production at probe time.
OWNER_VIEW_FIXTURE = os.path.join(REPO_ROOT, "spa_core", "tests", "fixtures", "owner_view",
                                  "mission_fixture.json")
OWNER_VIEW_SECTIONS = ("overview", "work", "money", "decisions", "protection")
_OWNER_VIEW_NOW = datetime(2026, 10, 9, 7, 15, tzinfo=timezone.utc)


def _probe_director_os_owner_view_section(arg: str | None, *,
                                          fixture: str | None = None) -> tuple[str, str]:
    """Критерий задач B/C DIRECTOR-OS-UX-02: раздел пульта `arg` (overview | work | money)
    ДОНОСИТ правду владельцу. Меряется ИСХОД на фиксированной сцене и фиксированных часах,
    а не наличие модуля:

    1. раздел построен из `owner_view.build` (нет раздела ⇒ не выполнено);
    2. у КАЖДОГО показателя есть source · measured_at · updated_at · unit · confidence, и
       confidence из закрытого словаря;
    3. в основных текстах нет жаргона (`owner_view.JARGON_PATTERNS`);
    4. «не измерено» не становится нулём: ячейка, объявленная NOT_MEASURED, читается
       словами «Не измерено», а не числом;
    5. (overview, money) реальные деньги берутся ТОЛЬКО из `capital.real_capital`: подставленная
       в канон метка-сумма видна в тексте, а убранный канон даёт «Не измерено», а не «$0».
    """
    sec = (arg or "").strip()
    if sec == "scenarios":
        return _probe_owner_view_scenarios(fixture=fixture)
    if sec not in OWNER_VIEW_SECTIONS:
        return UNMEASURED, (f"проба меряет раздел из {OWNER_VIEW_SECTIONS} или «scenarios», дано "
                            f"{arg!r} — вердикт без названного раздела был бы о чём-то другом")
    path = fixture or OWNER_VIEW_FIXTURE
    try:
        with open(path, encoding="utf-8") as fh:
            scene = json.load(fh)
    except Exception as exc:  # noqa: BLE001 — нет сцены ⇒ не измерено, а не «прошло»
        return UNMEASURED, f"сцена не прочитана ({type(exc).__name__}: {path})"
    try:
        from spa_core.studio_os import owner_view as ov
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, f"owner_view не импортируется ({type(exc).__name__})"
    import copy

    def _section(model):
        return (ov.build(model, _OWNER_VIEW_NOW).get("sections") or {}).get(sec)

    view = _section(copy.deepcopy(scene))
    if not isinstance(view, dict):
        return NOT_SATISFIED, f"раздел «{sec}» не построен"
    ms = ov.metrics(view)
    if not ms:
        return NOT_SATISFIED, f"в разделе «{sec}» нет ни одного показателя"
    need = ("source", "measured_at", "updated_at", "unit", "confidence")
    bad = [m.get("label") for m in ms if any(k not in m for k in need) or m.get("confidence") not in ov.CONFIDENCE]
    if bad:
        return NOT_SATISFIED, f"показатели без источника/времени/единиц/достоверности: {bad[:5]}"
    jar = [(p, ov.jargon_hits(t)) for p, t in ov.main_texts(view) if ov.jargon_hits(t)]
    if jar:
        return NOT_SATISFIED, f"жаргон в основных текстах: {jar[:3]}"
    # 4 — unknown never becomes a number: blank the book/tasks cells and look at the words
    sc = copy.deepcopy(scene)
    truth = sc.get("truth") or {}
    for cell in ((truth.get("capital") or {}).get("defi") or {}).get("books", {}).values():
        if isinstance(cell, dict):
            cell["state"] = "NOT_MEASURED"
    tasks = (truth.get("studio") or {}).get("tasks")
    if isinstance(tasks, dict):
        tasks["state"] = "NOT_MEASURED"
    for key in ("fleet", "machine", "problems"):          # protection reads these
        cell = (truth.get("studio") or {}).get(key)
        if isinstance(cell, dict):
            cell["state"] = "NOT_MEASURED"
    if sec == "decisions":                                  # decisions reads the queue itself
        (truth.get("decisions") or {}).pop("groups", None)
    v2 = _section(sc) or {}
    unk = [m for m in ov.metrics(v2) if m.get("confidence") == ov.NOT_MEASURED]
    if not unk or any(not str(m.get("text", "")).startswith("Не измерено") or re.search(r"\d+[,.]\d\d", str(m.get("text")))
                      for m in unk):
        return NOT_SATISFIED, "объявленное «не измерено» не дошло словами (или стало числом)"
    if sec in ("overview", "money"):
        sc = copy.deepcopy(scene)
        sc.setdefault("capital", {})["real_capital"] = {"state": "LIVE_NOT_APPROVED", "usd": 4242,
                                                       "basis": "probe", "observed_at": "2026-10-09T06:00:00Z"}
        real = (_section(sc) or {}).get("real") or ((_section(sc) or {}).get("money") or {}).get("real") or {}
        if "4\u00a0242" not in str(real.get("text")):
            return NOT_SATISFIED, "сумма реальных денег не взята из capital.real_capital"
        sc = copy.deepcopy(scene)
        sc.get("capital", {}).pop("real_capital", None)
        (sc.get("overview") or {}).get("capital", {}).pop("real_capital", None)
        real = (_section(sc) or {}).get("real") or ((_section(sc) or {}).get("money") or {}).get("real") or {}
        if real.get("confidence") != ov.NOT_MEASURED or "$" in str(real.get("text")):
            return NOT_SATISFIED, "без канона реальных денег показана сумма, а не «не измерено»"
    if sec == "decisions":
        bad = _owner_view_decisions_contour(ov, scene, _section)
        if bad:
            return NOT_SATISFIED, bad
    if sec == "protection":
        bad = _owner_view_protection_contour(ov, scene, _section)
        if bad:
            return NOT_SATISFIED, bad
    extra = {"overview": "; реальные деньги только из capital.real_capital",
             "money": "; реальные деньги только из capital.real_capital",
             "decisions": "; у вопросов есть версия, ответ только через действующий механизм, "
                          "неподготовленная и уже отвеченная карточка без кнопки",
             "protection": "; частично проверенное не называется «в порядке», есть резервная копия "
                           "и дата проверки восстановления"}.get(sec, "")
    return SATISFIED, (f"раздел «{sec}»: показателей {len(ms)}, у всех источник/время/единицы/"
                       "достоверность; жаргона нет; «не измерено» словами" + extra)


def _probe_owner_view_scenarios(*, fixture: str | None = None) -> tuple[str, str]:
    """Критерий задачи E DIRECTOR-OS-UX-02: пять сценариев владельца выполнимы на фиксированной
    сцене и фиксированных часах — меряется ИСХОД (что прочтёт человек), а не наличие полей."""
    path = fixture or OWNER_VIEW_FIXTURE
    try:
        with open(path, encoding="utf-8") as fh:
            scene = json.load(fh)
    except Exception as exc:  # noqa: BLE001 — нет сцены ⇒ не измерено, а не «прошло»
        return UNMEASURED, f"сцена не прочитана ({type(exc).__name__}: {path})"
    try:
        from spa_core.studio_os import owner_view as ov
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, f"owner_view не импортируется ({type(exc).__name__})"
    sections = ov.build(scene, _OWNER_VIEW_NOW).get("sections") or {}
    bad = owner_view_scenarios_contour(ov, sections)
    if bad:
        return NOT_SATISFIED, bad
    return SATISFIED, ("пять сценариев выполнимы: состояние студии и следующий шаг; вопрос владельцу "
                       "с последствиями и версией; реальные деньги отдельно от модели; причина остановки "
                       "работы или «не измерено»; резервные копии и дата проверки восстановления")


def owner_view_scenarios_contour(ov, s: dict) -> "str | None":
    """None = все пять сценариев выполнимы; иначе — НАЗВАННОЕ порванное звено."""
    def words(x):
        return isinstance(x, str) and x.strip() != "" and not ov.jargon_hits(x)
    o = s.get("overview") or {}
    # 1 — состояние студии: главное событие и следующий шаг словами, со временем
    hl = o.get("headline") or {}
    if not (words(hl.get("main")) and words(hl.get("next"))):
        return "сценарий 1: нет главного события или следующего шага словами"
    if not hl.get("updated_at_ru"):
        return "сценарий 1: у главного события нет времени обновления"
    # 2 — вопрос владельцу: из очереди, с предложением, последствиями, версией и ответом
    q_ids = [i.get("id") for i in ((o.get("questions") or {}).get("items") or [])]
    owner = (s.get("decisions") or {}).get("owner") or []
    if q_ids != [i.get("id") for i in owner]:
        return "сценарий 2: вопросы на обзоре не совпадают с очередью владельца"
    for it in owner:
        if not (words(it.get("proposal")) and words(it.get("consequences"))):
            return f"сценарий 2: у вопроса {it.get('id')} нет предложения или последствий словами"
        ver = it.get("version") or {}
        if not (ver.get("fingerprint") or ver.get("measured") is False):
            return f"сценарий 2: у вопроса {it.get('id')} нет версии"
        if (it.get("answer") or {}).get("kind") not in ("READY", "BLOCKED_UNPREPARED", "ANSWERED"):
            return f"сценарий 2: у вопроса {it.get('id')} не определено, можно ли отвечать"
    # 3 — реальные деньги отдельно от модели
    m = s.get("money") or {}
    real, paper, research = m.get("real") or {}, m.get("paper") or {}, m.get("research") or {}
    if not str(real.get("source") or "").startswith("capital.real_capital"):
        return "сценарий 3: реальные деньги взяты не из capital.real_capital"
    if "модел" not in str(paper.get("note") or "").lower():
        return "сценарий 3: расчётный портфель не назван моделью"
    if "не деньги" not in str(research.get("note") or "").lower():
        return "сценарий 3: исследования и бэктест не отделены от денег"
    # 4 — почему работа остановилась: причина или честное «не измерено», и следующий шаг
    w = s.get("work") or {}
    bl, nx = w.get("blocking") or {}, w.get("next") or {}
    if not words(bl.get("text")) or not words(nx.get("text")):
        return "сценарий 4: нет ответа «что мешает» или «что дальше» словами"
    stopped = bl.get("stopped") or []
    if bl.get("known_reason") is False and not stopped and "не измерено" not in bl["text"].lower():
        return "сценарий 4: неизвестная причина остановки не названа «не измерено»"
    # ARB 09.10: each stopped task says what its card says — the reason or «не указана в карточке»
    for x in stopped:
        if not words(x.get("title")):
            return "сценарий 4: у остановленной задачи нет названия словами"
        if x.get("reason") and x.get("reason") not in str(x.get("reason_text") or ""):
            return "сценарий 4: причина из карточки не показана"
        if not x.get("reason") and "не указана в карточке" not in str(x.get("reason_text") or ""):
            return "сценарий 4: отсутствие причины в карточке не названо"
    if stopped and bl.get("reason_state") == "known" and not all(x.get("reason") for x in stopped):
        return "сценарий 4: причина объявлена известной, хотя в карточке её нет"
    # 5 — резервные копии и проверка восстановления с датой
    b = (s.get("protection") or {}).get("backups") or {}
    for k in ("local", "off_host", "recovery"):
        if not words((b.get(k) or {}).get("text")):
            return f"сценарий 5: нет сведений о копии «{k}»"
    rec = b.get("recovery") or {}
    if rec.get("confidence") == ov.MEASURED and not rec.get("measured_at_ru"):
        return "сценарий 5: у проверки восстановления нет даты"
    return None


def _owner_view_decisions_contour(ov, scene, section) -> "str | None":
    """Решения (задача D): исход, а не наличие полей. None = контур цел, иначе — порванное звено."""
    import copy
    view = section(copy.deepcopy(scene)) or {}
    items = view.get("owner") or []
    groups = ((scene.get("truth") or {}).get("decisions") or {}).get("groups") or {}
    if len(items) != len([d for d in (groups.get("owner") or []) if isinstance(d, dict)]):
        return "в разделе не все вопросы из очереди владельца"
    for it in items:
        ver = it.get("version") or {}
        if not (re.fullmatch(r"[0-9a-f]{64}", str(ver.get("fingerprint") or "")) or ver.get("measured") is False):
            return f"у вопроса {it.get('id')} нет версии (и не сказано, что она не измерена)"
        ans = it.get("answer") or {}
        if ans.get("kind") == "READY" and not str(ans.get("link") or "").startswith("https://t.me/"):
            return "готовый к ответу вопрос ведёт не в действующий механизм ответа"
        if ans.get("kind") != "READY" and ans.get("link"):
            return "у неготового или отвеченного вопроса осталась кнопка ответа"
    if not groups.get("owner"):
        return None
    # 1 — version follows content: a changed card has a different fingerprint
    sc = copy.deepcopy(scene)
    first = sc["truth"]["decisions"]["groups"]["owner"][0]
    first["action_ru"] = str(first.get("action_ru") or "") + " (изменено)"
    # the cockpit now reads the WHOLE card (ARB 09.10): change the full text too — the same outcome
    # («a changed card has a different fingerprint»), measured on the content the owner reads
    for sec in (first.get("full_sections_ru") or [])[:1]:
        if isinstance(sec, dict):
            sec["text"] = str(sec.get("text") or "") + " (изменено)"
    a = (items[0].get("version") or {}).get("fingerprint")
    changed = [i for i in ((section(sc) or {}).get("owner") or []) if i.get("id") == first.get("id")]
    if not changed or (changed[0].get("version") or {}).get("fingerprint") == a:
        return "изменение карточки не меняет её версию"
    # 2 — unprepared (no proposal) ⇒ blocked, in words
    sc = copy.deepcopy(scene)
    first = sc["truth"]["decisions"]["groups"]["owner"][0]
    first["action_ru"] = None
    got = [i for i in ((section(sc) or {}).get("owner") or []) if i.get("id") == first.get("id")]
    if not got or (got[0].get("answer") or {}).get("kind") != "BLOCKED_UNPREPARED" or \
            not (got[0].get("answer") or {}).get("reason"):
        return "неподготовленная карточка не заблокирована словами"
    # 3 — already answered ⇒ no second confirmation
    sc = copy.deepcopy(scene)
    g = sc["truth"]["decisions"]["groups"]
    first = g["owner"][0]
    g.setdefault("answered", []).append({"id": first.get("id"), "title_ru": first.get("title_ru"),
                                          "owner_answer_ru": "1", "answered_at": "2026-10-09T06:00:00+00:00"})
    got = [i for i in ((section(sc) or {}).get("owner") or []) if i.get("id") == first.get("id")]
    if not got or (got[0].get("answer") or {}).get("kind") != "ANSWERED" or (got[0].get("answer") or {}).get("link"):
        return "уже отвеченная карточка предлагает ответить повторно"
    return None


def _owner_view_protection_contour(ov, scene, section) -> "str | None":
    """Защита (задача D): частичное ≠ «в порядке»; копии и проверка восстановления с датой."""
    import copy
    view = section(copy.deepcopy(scene)) or {}
    verdict = view.get("verdict") or {}
    checks = ov.metrics(view.get("checks") or [])
    if not checks or not verdict:
        return "нет итога или проверок доступности"
    if any(c.get("confidence") != ov.MEASURED or c.get("tone") not in ("ok", "neutral") for c in checks):
        if "в порядке" in str(verdict.get("text")).lower() or verdict.get("confidence") == ov.MEASURED:
            return "частично проверенная система названа «в порядке»"
    b = view.get("backups") or {}
    rec = b.get("recovery") or {}
    if rec.get("confidence") == ov.MEASURED and not rec.get("measured_at_ru"):
        return "у проверки восстановления нет даты"
    if not b.get("local") or not b.get("off_host") or not rec:
        return "нет сведений о резервных копиях и восстановлении"
    off = b.get("off_host") or {}
    if off.get("confidence") == ov.MEASURED and "не измерено" not in str(off.get("text")).lower():
        sc_remote = (((scene.get("truth") or {}).get("studio") or {}).get("backups") or {}).get("off_host") or {}
        if sc_remote.get("remote_upload") == "NOT_MEASURED":
            return "доставка копии на серверы iCloud не измерена, а показана как проверенная"
    # control: an all-healthy scene must be able to say «в порядке»
    sc = _owner_view_all_healthy(copy.deepcopy(scene))
    v2 = section(sc) or {}
    if "в порядке" not in str((v2.get("verdict") or {}).get("text")).lower():
        return "даже полностью проверенная система не может быть «в порядке» — итог сломан"
    return None


def _owner_view_all_healthy(sc: dict) -> dict:
    """The control scene: every check the protection section reads is measured and healthy."""
    sc.setdefault("overview", {}).setdefault("system", {}).update({"state": "HEALTHY", "reason": "", "alerts": []})
    st = sc.setdefault("truth", {}).setdefault("studio", {})
    fl = st.get("fleet") or {}
    fl.update({"state": "MEASURED", "ok": fl.get("declared", 1), "value": {"ok": fl.get("declared", 1),
               "declared": fl.get("declared", 1), "critical": 0, "warning": 0}, "failing": []})
    st["fleet"] = fl
    pr = st.get("problems") or {}
    pr.update({"state": "MEASURED", "open": 0, "items": [], "value": {"open": [], "open_count": 0}})
    st["problems"] = pr
    off = (st.get("backups") or {}).get("off_host")
    if isinstance(off, dict):
        off["remote_upload"] = "VERIFIED"
    wh = ((sc["truth"].get("product") or {}).get("website_health"))
    if isinstance(wh, dict):
        wh["value"] = {"status": "OK"}
    sc["generated_at"] = "2026-10-09T07:10:00Z"
    return sc

#: Синтетические метки сцены пробы перезагрузки. Имена заведомо не из флота: обёртка
#: судит и по `/tmp/spa_<имя>.log`, и метка флота читала бы живой лог хоста.
REBOOT_PROBE_RECEIPT_AGENT = "com.spa.zz_arb_probe_receipt"
REBOOT_PROBE_CALENDAR_AGENT = "com.spa.zz_arb_probe_calendar"
REBOOT_PROBE_HOURLY_AGENT = "com.spa.zz_arb_probe_hourly"


def _probe_agent_health_reboot_false_alarm(arg: str | None, *,
                                           now: "datetime | None" = None) -> tuple[str, str]:
    """Критерий: перезагрузка Mac больше не превращается в «критическую проблему»,
    а настоящий пропуск планового запуска — по-прежнему превращается. По ИСХОДУ.

    Карточка `inbox-arb-razobrat-trevogu-telegram-posle-pere` (тревога 15.10 21:21:20Z:
    30 «проблем» через 3 мин 22 с после загрузки, ни одна не сбой). На одноразовом
    дереве — настоящий `check_agent`, настоящий `format_alert`/`alert_fingerprint` и
    настоящий edge-trigger `push_policy.push_critical` (``send=False``: сеть не трогается):

    1. ПЕРЕЗАГРУЗКА: /tmp-логов нет, старый logs/<x>.log 110 сут., квитанция свежая;
       календарный и часовой агенты без лога. Через 3 мин после загрузки у каждого
       статус ``OK`` и названное доказательство (``receipt`` / ``awaiting_first_run``),
       сводный статус не CRITICAL, владельцу не уходит НИЧЕГО.
    2. ЗАГРУЗКА НЕ ИЗМЕРЕНА: тот же агент со свежей квитанцией и логом 110 сут. —
       ``OK`` по квитанции (старый лог не доказывает отсутствия работы).
    3. ПРОПУСК: окно после загрузки прошло, квитанция несвежая, у календарного агента
       ни одного запуска — оба ``CRITICAL``; тревога уходит ОДИН раз и не повторяется,
       когда к ней добавляется лишь новое предупреждение.
    4. ПРОЦЕСС БЕЗ РЕЗУЛЬТАТА: живой PID и свежий лог при несвежей квитанции — не ``OK``.

    Сравниваются ПОЛЯ отчёта (``status``, ``evidence``), а не текст (ADR-333). Живое
    `data/`, трекер и чат владельца не трогаются. Время — вход (`now`).
    """
    import shutil
    import tempfile
    from datetime import timedelta
    from spa_core.monitoring import agent_health_monitor as ahm
    from spa_core.telegram import push_policy

    t0 = now or datetime.now(timezone.utc)
    for lbl in (REBOOT_PROBE_RECEIPT_AGENT, REBOOT_PROBE_CALENDAR_AGENT,
                REBOOT_PROBE_HOURLY_AGENT):
        short = lbl[len("com.spa."):]
        if os.path.exists(f"/tmp/spa_{short}.log"):
            return (UNMEASURED, f"предпосылка НЕ ОБЕСПЕЧЕНА: на хосте есть /tmp/spa_{short}.log "
                                "— сцена читала бы чужой лог")
    root = tempfile.mkdtemp(prefix="spa_reboot_probe_")
    try:
        data = os.path.join(root, "data")
        logs_dir = os.path.join(root, "logs")
        os.makedirs(data)
        os.makedirs(logs_dir)
        receipts = {REBOOT_PROBE_RECEIPT_AGENT: ("probe_book.json", "last_cycle_at")}

        def plist(label, **sched):
            short = label[len("com.spa."):]
            return dict(sched, StandardOutPath=os.path.join(root, f"{short}.launchd.out"),
                        StandardErrorPath=os.path.join(root, f"{short}.launchd.err"))

        p_receipt = plist(REBOOT_PROBE_RECEIPT_AGENT, StartInterval=3600, RunAtLoad=False)
        p_cal = plist(REBOOT_PROBE_CALENDAR_AGENT, StartCalendarInterval={"Hour": 9, "Minute": 0},
                      RunAtLoad=False)
        p_hourly = plist(REBOOT_PROBE_HOURLY_AGENT, StartInterval=3600, RunAtLoad=False)

        def set_receipt(at):
            with open(os.path.join(data, "probe_book.json"), "w", encoding="utf-8") as fh:
                json.dump({"last_cycle_at": at.isoformat()}, fh)

        def touch(path, at):
            # Сцена пишет только внутри себя: путь вне `root` — отказ, а не
            # запись в чужое дерево. Цель строится от `root`, поэтому и
            # перепись писателей видит, ЧТО это за файл (ADR-707).
            rel = os.path.relpath(path, root)
            if rel == os.pardir or rel.startswith(os.pardir + os.sep):
                raise ValueError(f"сцена пробы пишет только внутри себя: {path}")
            target = os.path.join(root, rel)
            with open(target, "a", encoding="utf-8"):
                pass
            os.utime(target, (at.timestamp(), at.timestamp()))

        def clear_scene_logs():
            for name in os.listdir(root):
                if name.endswith((".launchd.out", ".launchd.err")):
                    os.remove(os.path.join(root, name))

        # Домиграционный журнал: 110 суток — та самая цифра тревоги.
        touch(os.path.join(logs_dir, "zz_arb_probe_receipt.log"), t0 - timedelta(days=110))

        def judge(label, pl, at, boot, pid=0):
            lc = {label: {"pid": pid, "exit": 0}}
            return ahm.check_agent(label, pl, True, lc, at, project_root=_pathlib.Path(root),
                                   data_dir=_pathlib.Path(data), boot_time=boot,
                                   receipts=receipts)

        # ── 1. перезагрузка ──────────────────────────────────────────────────
        boot = t0 - timedelta(minutes=3, seconds=22)
        set_receipt(boot - timedelta(minutes=7))
        clear_scene_logs()
        got = {lbl: judge(lbl, pl, t0, boot) for lbl, pl in (
            (REBOOT_PROBE_RECEIPT_AGENT, p_receipt), (REBOOT_PROBE_CALENDAR_AGENT, p_cal),
            (REBOOT_PROBE_HOURLY_AGENT, p_hourly))}
        want = {REBOOT_PROBE_RECEIPT_AGENT: ahm.EVIDENCE_RECEIPT,
                REBOOT_PROBE_CALENDAR_AGENT: ahm.EVIDENCE_AWAITING_FIRST_RUN,
                REBOOT_PROBE_HOURLY_AGENT: ahm.EVIDENCE_AWAITING_FIRST_RUN}
        for lbl, h in got.items():
            if h.status != ahm.OK or h.evidence != want[lbl]:
                return (NOT_SATISFIED,
                        f"перезагрузка: {lbl} → status={h.status}, evidence={h.evidence!r}, "
                        f"issue={h.issue!r}; ожидалось OK/{want[lbl]} — "
                        + ("квитанция не читается вердиктом" if lbl == REBOOT_PROBE_RECEIPT_AGENT
                           else "окно после загрузки не применено"))
        rep = ahm.build_report(list(got.values()), {}, ahm.OK, [], t0)
        if rep["overall_status"] == ahm.CRITICAL:
            return (NOT_SATISFIED, "перезагрузка: сводный статус CRITICAL")

        # ── 2. загрузка не измерена: решает квитанция ───────────────────────
        h = judge(REBOOT_PROBE_RECEIPT_AGENT, p_receipt, t0, None)
        if h.status != ahm.OK or h.evidence != ahm.EVIDENCE_RECEIPT:
            return (NOT_SATISFIED,
                    f"загрузка не измерена: {REBOOT_PROBE_RECEIPT_AGENT} → status={h.status}, "
                    f"evidence={h.evidence!r}, issue={h.issue!r} — квитанция успешного "
                    "выполнения не главнее старого журнала (110 сут.)")

        # ── 3. настоящий пропуск ────────────────────────────────────────────
        late = boot + timedelta(days=3)
        missed = {lbl: judge(lbl, pl, late, boot) for lbl, pl in (
            (REBOOT_PROBE_RECEIPT_AGENT, p_receipt), (REBOOT_PROBE_CALENDAR_AGENT, p_cal))}
        for lbl, h in missed.items():
            if h.status != ahm.CRITICAL:
                return (NOT_SATISFIED,
                        f"пропуск: {lbl} через 3 сут. после загрузки без работы → "
                        f"status={h.status}, issue={h.issue!r}; ожидалось CRITICAL — "
                        "настоящий пропуск планового запуска заглушён")
        tg = os.path.join(root, "push")
        os.makedirs(tg)

        def push(report):
            return bool(push_policy.push_critical(
                "agent_health_critical", "CRITICAL", "SPA Agent Health — CRITICAL",
                ahm.format_alert(report), dedup_key=ahm.alert_fingerprint(report),
                data_dir=_pathlib.Path(tg), now=late, send=False))

        rep3 = ahm.build_report(list(missed.values()), {}, ahm.OK, [], late)
        if rep3["overall_status"] != ahm.CRITICAL or not push(rep3):
            return (NOT_SATISFIED, "пропуск: тревога владельцу не ушла")
        extra = ahm.AgentHealth(label="com.spa.zz_arb_probe_warn", status=ahm.WARNING,
                                issue="last_exit=1")
        rep3b = ahm.build_report(list(missed.values()) + [extra], {}, ahm.OK, [], late)
        if push(rep3b):
            return (NOT_SATISFIED, "повтор: новое ПРЕДУПРЕЖДЕНИЕ при тех же критичных "
                                   "пунктах снова отправило ту же тревогу")

        # ── 4. процесс без результата ───────────────────────────────────────
        far = boot + timedelta(days=2)
        set_receipt(far - timedelta(hours=20))
        touch(p_receipt["StandardOutPath"], far - timedelta(minutes=1))
        h = judge(REBOOT_PROBE_RECEIPT_AGENT, p_receipt, far, boot, pid=4242)
        if h.status == ahm.OK:
            return (NOT_SATISFIED,
                    "процесс без результата: живой PID и свежий журнал при квитанции "
                    "20 ч приняты за успех — квитанция не главнее журнала")
        return (SATISFIED,
                f"перезагрузка: {', '.join(f'{k}={v}' for k, v in sorted(want.items()))}, "
                f"тревоги нет; загрузка не измерена → receipt; пропуск → CRITICAL×2, одна "
                f"тревога без повтора; процесс без результата → {h.status}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _probe_paused_agent_is_not_a_dead_agent(arg: str | None, *,
                                            now: "datetime | None" = None,
                                            manifest_path: str | None = None) -> tuple[str, str]:
    """Критерий: находка `B1:dead:com.spa.mission_tick` исчезает из вердикта сторожа
    БЕЗ ЕДИНОГО ДЕЙСТВИЯ НАД ФЛОТОМ — и положительный контроль краснеет в ОБРАТНУЮ
    сторону (ADR-769, карточка `inbox-obyavlenie-agenta-ne-umeet-skazat-namere`).

    Зачем. С 30.09 сторож 46 суток печатал CRITICAL «intent=active, но НЕ загружен во
    флоте», и находка была ВЕРНА: запись манифеста несла `active` рядом с прозой
    «paused by the owner». Единственная резолюция, закрывавшая находку, — загрузить
    агента, то есть ОТМЕНИТЬ решение владельца, который выключил его намеренно
    (`bootout` + `disable`). Поэтому критерий здесь двусторонний: мало чтобы находка
    ушла — её уход обязан происходить ОТ ОБЪЯВЛЕНИЯ ПАУЗЫ, а не от ослабления сторожа.

    Меряется ИСХОД настоящего `run_checks` на ЖИВОМ манифесте дерева, четырьмя
    сценами; флот и `launchctl` при этом не трогаются — обе двери к ОС поданы ВХОДОМ:

      1. ЖИВОЙ МАНИФЕСТ + измеренная пауза ⇒ ни одной находки B1 про этого агента;
      2. тот же агент, объявленный `active` ⇒ `B1:dead` CRITICAL возвращается
         (сторож не ослаблен — иначе сцена 1 ничего не доказывает);
      3. тот же агент `paused`, но ЗАГРУЖЕН ⇒ `B1:revived` CRITICAL (освобождение
         режет в обе стороны, то есть не является глушилкой);
      4. тот же агент `paused`, но ОС его в отключённых НЕ ВИДИТ ⇒ `B1:pause_unproven`
         CRITICAL (притязание записи сверяется замером, а не принимается на слово).

    Сравниваются ПОЛЯ вердикта (`key`, `severity`, `check`), а не текст (ADR-333).
    Манифеста нет / агента в нём нет ⇒ UNMEASURED с названной причиной: предпосылка
    сцены не обеспечена, и судить о ней нельзя.

    **Читается курация ТАК ЖЕ, как её читает прод** — с `origin/main`
    (`reconcile_curation`, ADR-066 B6: конституция живёт на origin, механика — локальна).
    Правка `intent` в рабочем дереве сторожа НЕ меняет: он возьмёт значение с origin.
    Поэтому проба, читавшая дерево, объявляла бы НЕДОСТАВЛЕННУЮ правку выполненным
    критерием — ровно тот класс, ради которого существует шаг 0a («объявил → доставил?»).
    Критерий карточки назван по ЖИВОМУ артефакту `data/architecture_conformance.json`,
    а его производит прод, значит и мерить надо доставленное состояние.
    """
    import copy
    from spa_core.monitoring import architecture_conformance as ac

    label = (arg or "com.spa.mission_tick").strip()
    t0 = now or datetime.now(timezone.utc)
    # Путь к конституции — ВХОД, а не окружение: иначе контроль самой пробы судил бы
    # о живом дереве и не мог бы порвать ни одного звена (правило о дверях,
    # `.claude/rules/deployment.md`). По умолчанию — настоящая конституция.
    path = manifest_path or os.path.join(REPO_ROOT, "architecture", "manifest.json")
    try:
        with open(path, encoding="utf-8") as fh:
            local = json.load(fh)
    except (OSError, ValueError) as exc:
        return (UNMEASURED, f"предпосылка НЕ ОБЕСПЕЧЕНА: architecture/manifest.json "
                            f"не прочитан ({type(exc).__name__}: {exc})")
    if manifest_path:
        # сцена контроля: своя копия конституции и есть доставленная
        manifest, curation_src = local, "сцена"
    else:
        origin, why = ac.origin_manifest()
        if origin is None:
            return (UNMEASURED, f"предпосылка НЕ ОБЕСПЕЧЕНА: конституция на "
                                f"{ac.CURATION_REF} не прочитана ({why}) — доставлено "
                                f"объявление или нет, НЕ ИЗМЕРЕНО")
        manifest, _prov = ac.reconcile_curation(local, origin, reason=why)
        curation_src = ac.CURATION_REF
    agents = [a for a in manifest.get("agents") or [] if isinstance(a, dict)]
    row = next((a for a in agents if a.get("label") == label), None)
    if row is None:
        return (UNMEASURED, f"предпосылка НЕ ОБЕСПЕЧЕНА: {label} в манифесте нет")
    if row.get("intent") != "paused":
        return (NOT_SATISFIED,
                f"{label}: intent={row.get('intent')!r}, а не 'paused' (курация прочитана "
                f"с `{curation_src}`) — объявление, которое читает прод, по-прежнему спорит "
                f"с прозой записи; правка в рабочем дереве сторожа не меняет")

    def verdict(man, fleet, disabled):
        rep = ac.run_checks(man, fleet, lambda rel: None, {}, t0,
                            disabled_labels=disabled)
        return ({(f["key"], f["severity"]) for f in rep["findings"]
                 if f["check"] == "B1" and f["key"].endswith(label)},
                {u["check"] for u in rep["unchecked"]
                 if str(u.get("check")).startswith("B1")})

    # 1. как есть: пауза измерена, агента во флоте нет
    seen, unchecked = verdict(manifest, set(), frozenset({label}))
    if seen or unchecked:
        return (NOT_SATISFIED, f"пауза подтверждена замером, а вердикт не пуст: "
                               f"находки={sorted(seen)} не измерено={sorted(unchecked)}")

    # 2. ОБРАТНАЯ СТОРОНА: ярлык снят ⇒ сторож обязан краснеть как прежде
    as_active = copy.deepcopy(manifest)
    next(a for a in as_active["agents"] if a.get("label") == label)["intent"] = "active"
    seen, _ = verdict(as_active, set(), frozenset({label}))
    if seen != {(f"B1:dead:{label}", "CRITICAL")}:
        return (NOT_SATISFIED, f"сторож ОСЛАБЛЕН: {label} с intent=active и без флота дал "
                               f"{sorted(seen)}, ожидалось ровно B1:dead/CRITICAL")

    # 3. ОБРАТНАЯ СТОРОНА: агента оживили против решения владельца
    seen, _ = verdict(manifest, {label}, frozenset({label}))
    if seen != {(f"B1:revived:{label}", "CRITICAL")}:
        return (NOT_SATISFIED, f"освобождение режет в одну сторону: {label} ЗАГРУЖЕН при "
                               f"intent=paused и дал {sorted(seen)}, ожидалось "
                               f"B1:revived/CRITICAL")

    # 4. ОБРАТНАЯ СТОРОНА: притязание паузы опровергнуто замером
    seen, _ = verdict(manifest, set(), frozenset())
    if seen != {(f"B1:pause_unproven:{label}", "CRITICAL")}:
        return (NOT_SATISFIED, f"пауза принята НА СЛОВО: {label} вне списка отключённых "
                               f"дал {sorted(seen)}, ожидалось B1:pause_unproven/CRITICAL")

    return (SATISFIED, f"{label}: intent=paused в курации с `{curation_src}` ⇒ находок B1 нет при "
                       f"измеренной паузе; обратные стороны краснеют все три "
                       f"(active→B1:dead · загружен→B1:revived · пауза опровергнута→"
                       f"B1:pause_unproven), флот не тронут")


#: Сквозной путь пульта (ADR-763): текст записи и проблема-предмет одноразовой сцены.
COCKPIT_LOOP_TEXT = "Сцена пробы: проверить сквозной путь записи из пульта"
COCKPIT_LOOP_PROBLEM = "probe-cockpit-voice-loop-scene"


def _probe_cockpit_voice_loop(arg: str | None, *, now: "datetime | None" = None) -> tuple[str, str]:
    """Критерий: сквозной путь «запись из пульта → карточка → исполнитель → ПРОВЕРЕННЫЙ результат →
    понятное уведомление» ЗАМКНУТ — по ИСХОДУ, на настоящем коде (карточка
    `inbox-skvoznoi-put-iz-pulta-golos-kartochka-is`, ADR-763).

    Одноразовая сцена (временный трекер, временный корень с исходящими, отправитель — список в
    памяти; живой трекер, живые исходящие и Telegram НЕ трогаются; `history_check` — шов приёма,
    за ним локальный `claude`, поэтому в сцене это объявленная заглушка «NEW»):

    1. пульт — настоящий `mission_intake.submit` дважды с ОДНИМ `submission_id` ⇒ ровно одна
       карточка `source: cockpit`, статус `new`;
    2. приём — настоящий `intake.run_note_intake` ⇒ метка `intake_seen`, карточка ОСТАЛАСЬ `new`
       (приём ≠ исполнение), владельцу ровно одно «Создал задачу»; повторный прогон — ни одного;
    3. исполнитель — взять без пробы ОТКАЗАНО очередью; `cockpit_loop.take_card` с настоящим
       захватом шага 0b (`check_card_claim.claim_card`) ⇒ `in-progress`; повторная доставка тем
       же исполнителем — no-op, другим — отказ (второго исполнения нет); повтор отправки и приёма
       карточку в работе не трогают;
    4. проверка — собственная проба карточки (`problem_absent` на данных сцены, настоящий
       `run_probe`) даёт `not_satisfied` ⇒ `close_verified` НЕ закрывает; «Мои записи»
       (настоящие `cockpit_records` → `my_records`) показывают `not_accepted` с причиной И
       следующим шагом; уведомление — одно на смену состояния, перемер без смены — ни одного;
    5. проблема закрыта ⇒ проба `satisfied` ⇒ карточка `done` с `verified_by_probe`, «Мои записи»
       — `done_verified`, владельцу ровно одно «сделано и проверено пробой <имя>»; повторное
       закрытие, дочистка и прогон приёма — ни одного дубля; исходящие пусты.

    Проверяются ПОЛЯ (статус, `state_kind`, `reason`, `next_step`, ключи исходящих, число
    сообщений), а не подстрока отчёта (ADR-333). Порвись звено — `not_satisfied` с его номером.
    Время — вход (`now`); живость исполнителей для захвата — вход сцены (`ps=`), не живая ОС.
    """
    import html as _html
    import importlib.util as _ilu
    import shutil
    import tempfile
    from datetime import timedelta

    try:
        from spa_core.owner_queue import cockpit_loop as cl
    except ImportError as exc:
        return NOT_SATISFIED, (f"звено 4–5 (закрытие пробой → уведомление) не построено: "
                               f"нет `spa_core.owner_queue.cockpit_loop` ({exc})")
    try:
        from spa_core.owner_queue import intake as oi
        from spa_core.owner_queue import queue as q
        from spa_core.studio_os import mission_control as mc
        from spa_core.studio_os import mission_intake as mi
        from spa_core.studio_os import owner_view as ov
        from spa_core.monitoring import problem_store
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, f"звенья пути не ввезены ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО"
    guard_path = os.path.join(REPO_ROOT, "scripts", "check_card_claim.py")
    try:
        spec_g = _ilu.spec_from_file_location("_probe_cockpit_card_claim", guard_path)
        guard = _ilu.module_from_spec(spec_g)          # type: ignore[arg-type]
        spec_g.loader.exec_module(guard)               # type: ignore[union-attr]
        sibling = guard.load_sibling()
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, f"шаг 0b (захват) не ввезён ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО"

    t0 = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    start = (t0 - timedelta(hours=2)).strftime("%a %b %d %H:%M:%S %Y")
    anchors = {"executor-a": (os.getpid(), start), "executor-b": (999_002, start)}
    spec = f"problem_absent:{COCKPIT_LOOP_PROBLEM}"
    sent: list = []

    def notify(text):
        sent.append(text)
        return True

    def no_history(_body):
        return {"verdict": "NEW", "response": ""}

    root = tempfile.mkdtemp(prefix="spa_cockpit_loop_probe_")
    try:
        tracker = os.path.join(root, "tracker")
        data = os.path.join(root, "data")
        os.makedirs(tracker)
        os.makedirs(data)
        obox = _pathlib.Path(data) / "intake_outbox.json"
        log = os.path.join(root, "session_changes.jsonl")
        open(log, "w", encoding="utf-8").close()

        def put_problem(status):
            # Писатель — сам `problem_store` (его атомарная запись), а не своя копия здесь.
            problem_store.save_store(data, {"problems": {COCKPIT_LOOP_PROBLEM: {
                "problem_id": COCKPIT_LOOP_PROBLEM, "status": status}}})

        def runner(s):
            return run_probe(s, data_dir=data)

        def claim(path, executor):
            guard.claim_card(_pathlib.Path(path).stem, log=log, session=executor, tracker_dir=tracker,
                             now=t0, sibling=sibling, ps=lambda _pid: (0, start),
                             self_anchor=anchors[executor])

        def no_classifier(_body):
            # Сцена — запись ВЛАДЕЛЬЦА (`author: owner` ниже), её маршрут — его пометка, и
            # классификатор не зовётся. Позовут — значит провенанс не прочитан; LLM в пробе
            # запрещён (инв. #3), поэтому вместо `claude` — детерминированный ответ.
            return "task", ""

        def intake_run(at):
            return oi.run_note_intake(at, tracker_dir=tracker, repo_root=root, notify=notify,
                                      history=no_history, ingest=False, classify=no_classifier)

        def fm_of(p):
            return parse_frontmatter(open(p, encoding="utf-8").read())

        def row_of(name):
            rec = mc.cockpit_records(mc._cards(_pathlib.Path(tracker)), t0, source="сцена пробы")
            view = ov.my_records({"intake": {"my_records": rec}}, None) or {}
            return next((r for r in view.get("rows") or []
                         if (r.get("technical") or {}).get("карточка") == name), None)

        # ── 1. пульт → карточка ─────────────────────────────────────────────────────────────
        body = json.dumps({"text": COCKPIT_LOOP_TEXT, "kind": "task",
                           "submission_id": "cockpit-loop-probe-0001"}).encode("utf-8")
        r1 = mi.submit(body, actor="probe", tracker_dir=tracker, now=t0)
        r2 = mi.submit(body, actor="probe", tracker_dir=tracker, now=t0)
        cards = sorted(n for n in os.listdir(tracker) if n.startswith("inbox-"))
        if len(cards) != 1 or not r2.get("duplicate") or r2.get("card") != r1.get("card"):
            return NOT_SATISFIED, (f"звено 1 (пульт → карточка): повтор отправки с тем же "
                                   f"submission_id дал карточек {len(cards)} ({cards}) — "
                                   f"идемпотентности нет")
        name = cards[0]
        card = os.path.join(tracker, name)
        if not fm_of(card).get("author"):        # старый пульт поля не пишет: сцена — запись владельца
            cl._set_fields(_pathlib.Path(card), {"author": "owner"})
        fm = fm_of(card)
        if fm.get("source") not in mi.COCKPIT_SOURCES or fm.get("status") != "new":
            return NOT_SATISFIED, (f"звено 1: карточка пульта родилась с source={fm.get('source')!r}, "
                                   f"status={fm.get('status')!r} — ожидались cockpit* и new")
        title = fm.get("title") or name

        # ── 2. приём ────────────────────────────────────────────────────────────────────────
        intake_run(t0)
        fm = fm_of(card)
        if fm.get("status") != "new":
            return NOT_SATISFIED, (f"звено 2 (приём): приём перевёл карточку в {fm.get('status')!r} — "
                                   f"приём не есть исполнение, карточка обязана остаться new")
        if not fm.get(oi._INTAKE_SEEN_FIELD):
            return NOT_SATISFIED, "звено 2 (приём): метки intake_seen нет — следующий прогон примет заново"
        accepted = [t for t in sent if _html.escape(title) in t]
        if len(sent) != 1 or len(accepted) != 1:
            return NOT_SATISFIED, (f"звено 2 (приём): уведомление о приёме не дошло владельцу "
                                   f"(отправлено {len(sent)}, о карточке {len(accepted)}) — "
                                   f"потеряно между отметкой и отправкой")
        intake_run(t0 + timedelta(minutes=1))
        if len(sent) != 1:
            return NOT_SATISFIED, (f"звено 2 (приём): повторный прогон приёма прислал ещё "
                                   f"{len(sent) - 1} сообщ. — повторная доставка не дедуплицирована")

        # ── 3. исполнитель ──────────────────────────────────────────────────────────────────
        try:
            q.set_status(card, "in-progress")
        except q.AcceptanceCriterionMissing:
            pass
        else:
            return NOT_SATISFIED, ("звено 3 (исполнитель): карточку взяли в работу БЕЗ пробы приёмки — "
                                   "очередь не отказала, «сделано» будет нечем проверить")
        put_problem("OPEN")
        try:
            ta = cl.take_card(card, spec, executor="executor-a", claim=claim)
        except cl.TakeRefused as exc:
            return NOT_SATISFIED, f"звено 3 (исполнитель): свободную карточку взять не удалось — {exc}"
        fm = fm_of(card)
        if (not ta.get("taken") or fm.get("status") != "in-progress"
                or fm.get("claimed_by") != "executor-a" or fm.get("acceptance_probe") != spec):
            return NOT_SATISFIED, (f"звено 3 (исполнитель): после взятия статус {fm.get('status')!r}, "
                                   f"захват {fm.get('claimed_by')!r}, проба {fm.get('acceptance_probe')!r}")
        second = []
        for ex in ("executor-b", "executor-a"):
            try:
                res = cl.take_card(card, spec, executor=ex, claim=claim)
            except cl.TakeRefused:
                continue
            if res.get("taken"):
                second.append(ex)
        if second:
            return NOT_SATISFIED, (f"звено 3 (исполнитель): повторная доставка запустила второе "
                                   f"исполнение той же карточки ({', '.join(second)}) — захват не "
                                   f"исключает исполнителей")
        r3 = mi.submit(body, actor="probe", tracker_dir=tracker, now=t0)
        intake_run(t0 + timedelta(minutes=2))
        if (not r3.get("duplicate") or len([n for n in os.listdir(tracker) if n.startswith("inbox-")]) != 1
                or fm_of(card).get("status") != "in-progress" or len(sent) != 1):
            return NOT_SATISFIED, ("звено 3: повтор отправки/приёма после взятия создал карточку, "
                                   "сбросил статус или прислал сообщение")

        # ── 4. проверка: проба НЕ выполнена ⇒ не «сделано», причина и шаг видны ─────────────
        t4 = t0 + timedelta(minutes=3)
        cl.close_verified(card, now=t4, runner=runner, outbox_path=obox, notify=notify)
        fm = fm_of(card)
        if fm.get("status") == "done" or fm.get("verified_by_probe"):
            return NOT_SATISFIED, (f"звено 4 (проверка): «сделано» поставлено до того, как проба "
                                   f"подтвердила результат (проба: {runner(spec)[0]}, статус "
                                   f"{fm.get('status')!r})")
        row = row_of(name)
        if (not row or row.get("state_kind") != "not_accepted" or row.get("verified")
                or not str(row.get("reason") or "").strip() or not str(row.get("next_step") or "").strip()):
            return NOT_SATISFIED, (f"звено 5 («Мои записи»): непринятый результат показан без причины "
                                   f"или без следующего шага: {row and {k: row.get(k) for k in ('state_kind', 'reason', 'next_step', 'verified')}}")
        if len(sent) != 2:
            return NOT_SATISFIED, (f"звено 5 (уведомление): на «не принято» отправлено "
                                   f"{len(sent) - 1} сообщ. вместо одного")
        cl.close_verified(card, now=t4 + timedelta(minutes=1), runner=runner, outbox_path=obox,
                          notify=notify)
        if len(sent) != 2:
            return NOT_SATISFIED, ("звено 5 (уведомление): перемер без смены состояния прислал "
                                   "сообщение ещё раз — спам владельцу")

        # ── 5. результат достигнут ⇒ проверено ⇒ одно «сделано» ─────────────────────────────
        put_problem("CLOSED")
        t5 = t0 + timedelta(minutes=5)
        rc = cl.close_verified(card, now=t5, runner=runner, outbox_path=obox, notify=notify)
        fm = fm_of(card)
        if fm.get("status") != "done" or fm.get("verified_by_probe") != spec or not rc.get("verified"):
            return NOT_SATISFIED, (f"звено 4 (проверка): проба выполнена, а карточка {fm.get('status')!r}, "
                                   f"verified_by_probe={fm.get('verified_by_probe')!r}")
        done_msgs = sent[2:]
        if len(done_msgs) != 1 or _html.escape(title) not in done_msgs[0] or spec not in done_msgs[0]:
            return NOT_SATISFIED, (f"звено 5 (уведомление): «сделано и проверено» дошло "
                                   f"{len(done_msgs)} раз(а) или без названия записи и пробы")
        cl.close_verified(card, now=t5, runner=runner, outbox_path=obox, notify=notify)
        cl.sweep_notices(tracker_dir=tracker, outbox_path=obox, now=t5)
        intake_run(t5 + timedelta(minutes=1))
        if len(sent) != 3:
            return NOT_SATISFIED, (f"звено 5 (уведомление): повторное закрытие/дочистка/приём прислали "
                                   f"ещё {len(sent) - 3} сообщ. «сделано»")
        row = row_of(name)
        if not row or row.get("state_kind") != "done_verified" or row.get("verified") is not True:
            return NOT_SATISFIED, (f"звено 5 («Мои записи»): проверенный результат показан как "
                                   f"{row and row.get('state_kind')!r}")
        left = oi._outbox_load(obox)
        if left:
            return NOT_SATISFIED, f"звено 5: в исходящих осталось {[i.get('key') for i in left]}"
    except Exception as exc:  # noqa: BLE001 — сцена не собралась = не измерено, не вердикт
        return UNMEASURED, f"сцена сквозного пути не собралась ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return SATISFIED, (f"путь пульта замкнут: 2 отправки → 1 карточка; приём → new + intake_seen + "
                       f"1 сообщение; без пробы взять ОТКАЗАНО; повторная доставка второго исполнения "
                       f"не дала; проба not_satisfied → «не принято» с причиной и шагом, 1 сообщение; "
                       f"проба satisfied → done + verified_by_probe={spec}, 1 «сделано и проверено»; "
                       f"дублей нет, исходящие пусты (всего сообщений {len(sent)})")


def _probe_read_only_view_parses_the_ledger_once(arg: str | None, *,
                                                 scope_removed: bool = False) -> tuple[str, str]:
    """Критерий: ЧИТАЮЩИЙ вид разбирает ленту ОДИН раз, и это свойство самого вида, а не
    того, кто его позвал (ADR-777, карточка
    `inbox-predpisannyi-priemochnyi-progon-vstaet-n`).

    Зачем. Предписанный приёмочный прогон вставал на одном тесте **26 мин 54 с**, и предмет
    был не в тесте: лекарство ADR-763 (stat-кэш чтения хеш-ленты) было вкручено ровно в
    ОДНУ точку входа — `mission_build.main()`, — а 4 958 разборов
    `data/research_factory/ledger.jsonl` (52 108 460 Б) делает ЧИТАЮЩАЯ МОДЕЛЬ
    `research_factory.read.latest()`. Поэтому все прочие её потребители (этот тест, вид
    `/capital` владельца в Телеграме, `investment_cio.research_universe`,
    `capital_shadow.readiness`) платили полную цену молча: замер на Маке владельца —
    **1 094.54 с / 2 281 разбор** против **7.95 с / 2 разбора**.

    Меряется ИСХОД на НАСТОЯЩЕЙ ленте в одноразовом каталоге, а не текст модуля:
    подстрокой эта проба не проходит по построению — она считает вызовы `HashLedger._parse`.

      • зелено: КАЖДАЯ точка входа из объявленного `read.VIEW_ENTRY_POINTS` разбирает файл
        ровно дважды (один свежий `verify()`, который кэш не обслуживает НИКОГДА — N3, плюс
        один разбор, который делят все помощники) И не оставляет кэш включённым;
      • красно, если: звено снято у любой точки входа · область не закрывается (кэш остался
        включён на весь процесс — ровно поведение прежнего вечного флага) · в объявленном
        населении появился вид, которого прибор не проверил.

    `scope_removed=True` — отрицательный контроль самой пробы: сцена та же, область снята,
    и проба ОБЯЗАНА сказать `not_satisfied`. Проба, никогда не видевшая поломки, украшение.
    """
    import contextlib
    import shutil
    import tempfile
    from datetime import datetime, timezone

    try:
        from spa_core.utils import hash_ledger as hl
        from spa_core.research_factory import read as rf_read
        from spa_core.research_factory._common import ledger_for
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, f"звенья пути не ввезены ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО"

    if hasattr(hl, "enable_read_cache"):
        return NOT_SATISFIED, ("вечный процессный выключатель кэша вернулся "
                               "(`hash_ledger.enable_read_cache`) — у правила снова две копии")

    allowed = 2
    tmp = tempfile.mkdtemp(prefix="probe_rf_")
    try:
        data = _pathlib.Path(tmp) / "data"
        led = ledger_for(data)
        at = "2026-10-17T00:00:00Z"
        led.append("run", ["r1"], {"generated_at": at}, at)
        for i in range(3):
            led.append("candidate", [f"c{i}"],
                       {"candidate_id": f"c{i}", "domain": "d", "mechanism": "m"}, at)

        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        calls = {"latest": lambda: rf_read.latest(data),
                 "cio_view": lambda: rf_read.cio_view(data, now)}
        declared = set(getattr(rf_read, "VIEW_ENTRY_POINTS", ()))
        if declared != set(calls):
            return (UNMEASURED, f"объявленное население видов {sorted(declared)} не совпало с "
                                f"проверяемым {sorted(calls)} — НЕ ИЗМЕРЕНО, а не «чисто»")

        orig_parse = hl.HashLedger._parse
        orig_scope = rf_read.read_cache
        if scope_removed:
            rf_read.read_cache = contextlib.nullcontext
        bad = []
        try:
            for name, call in calls.items():
                n = {"p": 0}

                def counting(path, _o=orig_parse, _n=n):
                    _n["p"] += 1
                    return _o(path)
                hl._READ_CACHE.clear()
                hl.HashLedger._parse = staticmethod(counting)
                try:
                    call()
                finally:
                    hl.HashLedger._parse = staticmethod(orig_parse)
                if n["p"] != allowed:
                    bad.append(f"{name}: разборов {n['p']} при допустимых {allowed}")
                if hl._READ_CACHE_ENABLED:
                    bad.append(f"{name}: кэш остался включён на весь процесс")
        finally:
            hl.HashLedger._parse = staticmethod(orig_parse)
            rf_read.read_cache = orig_scope
            # Флаг тут НЕ трогаем намеренно: сбросить его руками значило бы завести ВТОРУЮ
            # копию выключателя прямо в стороже, который за единственность и отвечает
            # (сторож `test_the_switch_has_exactly_one_door` это и нашёл — у себя же).
            # Область восстанавливает состояние сама; если не восстановила — это находка,
            # и она обязана быть ВИДНА, а не затёрта уборкой пробы.
            hl._READ_CACHE.clear()
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, f"сцена не построена ({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if bad:
        return NOT_SATISFIED, "; ".join(bad)
    return (SATISFIED, f"каждая из {len(calls)} объявленных точек входа читающей модели "
                       f"разбирает ленту {allowed} раз(а) (свежий verify + один общий разбор) "
                       f"и не оставляет кэш включённым")


PROBES: dict[str, Callable[[str | None], "tuple[str, str]"]] = {
    "cockpit_voice_loop_closed": _probe_cockpit_voice_loop,
    "card_claim_measures_the_worker": _probe_card_claim_measures_the_worker,
    "card_claim_absent_worker_reaches_the_verdict":
        _probe_card_claim_absent_worker_reaches_the_verdict,
    "card_claim_carries_the_launcher_anchor":
        _probe_card_claim_carries_the_launcher_anchor,
    "card_claim_anchored_reports_the_write":
        _probe_card_claim_anchored_reports_the_write,
    "card_claim_anchor_contract_guards_every_reader":
        _probe_card_claim_anchor_contract_guards_every_reader,
    "journal_claim_measures_the_worker": _probe_journal_claim_measures_the_worker,
    "file_overlap_claim_measures_the_worker":
        _probe_file_overlap_claim_measures_the_worker,
    "queue_reader_names_which_order_axis_spoke":
        _probe_queue_reader_names_which_order_axis_spoke,
    "director_os_owner_view_section": _probe_director_os_owner_view_section,
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
    "series_denominator_measured": _probe_series_denominator_measured,
    "second_artifact_tvl_agrees": _probe_second_artifact_tvl_agrees,
    "owner_protocols_report_carries_every_record":
        _probe_owner_protocols_report_carries_every_record,
    "owner_protocols_report_reaches_the_owner":
        _probe_owner_protocols_report_reaches_the_owner,
    "owner_command_surfaces_declared_once":
        _probe_owner_command_surfaces_declared_once,
    "owner_protocols_report_groups_by_canonical_tier":
        _probe_owner_protocols_report_groups_by_canonical_tier,
    "apy_provenance_declared_in_the_door":
        _probe_apy_provenance_declared_in_the_door,
    "adapter_status_number_has_a_writer":
        _probe_adapter_status_number_has_a_writer,
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
    "delivery_door_refuses_cycle_record_loss":
        _probe_delivery_door_refuses_cycle_record_loss,
    "delivery_door_refuses_card_section_loss":
        _probe_delivery_door_refuses_card_section_loss,
    "drift_names_direction_of_record_loss":
        _probe_drift_names_direction_of_record_loss,
    "queue_reader_names_record_memory_loss":
        _probe_queue_reader_names_record_memory_loss,
    "queue_reader_names_unmeasured_memory":
        _probe_queue_reader_names_unmeasured_memory,
    "queue_reader_names_uncompared_order":
        _probe_queue_reader_names_uncompared_order,
    "card_copies_agree": _probe_card_copies_agree,
    "named_cards_closed_at_origin": _probe_named_cards_closed_at_origin,
    "forbidden_import_gate_single_instrument":
        _probe_forbidden_import_gate_single_instrument,
    "ci_main_verdict_green": _probe_ci_main_verdict_green,
    "pr_work_arrived_on_main": _probe_pr_work_arrived_on_main,
    "owner_visibility_numbers_delivered":
        _probe_owner_visibility_numbers_delivered,
    "shadow_brief_names_the_unweighed_hold":
        _probe_shadow_brief_names_the_unweighed_hold,
    "ledger_day_unit_census_names_the_unit":
        _probe_ledger_day_unit_census_names_the_unit,
    "census_probe_refuses_unobserved_subject":
        _probe_census_probe_refuses_unobserved_subject,
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
    "problem_absent": _probe_problem_absent,
    "owner_control_plane_reachable": _probe_owner_control_plane_reachable,
    "office_hollow_counter_means_harm":
        _probe_office_hollow_counter_means_harm,
    "delta_mutation_instrument_is_re_measurable":
        _probe_delta_mutation_instrument_is_re_measurable,
    "tier_guard_judges_code_not_prose": _probe_tier_guard_judges_code_not_prose,
    "agent_health_reboot_false_alarm_closed": _probe_agent_health_reboot_false_alarm,
    "paused_agent_is_not_a_dead_agent": _probe_paused_agent_is_not_a_dead_agent,
    "read_only_view_parses_the_ledger_once":
        _probe_read_only_view_parses_the_ledger_once,
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
#:
#: `report_dir` добавлен решением ARB 23.10 (STUDIO-OS-NEXT-01, этап 8, вариант А §49):
#: каталог ОТЧЁТА — отдельный вход, а не производная от `repo_root`. Решение §49
#: выносится о чистом снимке ревизии S (`repo_root`), а отчёт о той же S лежит там,
#: куда его положил производитель (`--out-root`/data). Без отдельного входа отчёт
#: пришлось бы класть внутрь снимка (снимок перестал бы быть чистым) или читать
#: из боевого дерева (решение о другом дереве). Принимает его только проба,
#: объявившая параметр, — остальные критерии CIO своего предмета не меняют.
PROBE_TREE_INPUTS = ("repo_root", "data_dir", "tracker_dir", "report_dir")


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
              tracker_dir: str | None = None,
              report_dir: str | None = None) -> tuple[str, str]:
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
               "tracker_dir": tracker_dir, "report_dir": report_dir}
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


def cards_declaring_a_probe_on_ref(*, repo_root: str, ref: str = ORIGIN_REF,
                                   note: list | None = None):
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

    **Значение `ref` спрашивается у СЕРВЕРА и закрепляется sha** (ADR-361/362):
    `origin/main` — кэш последнего чужого fetch, и на нём популяция молча
    недосчитывала карточки, объявившие пробу после того fetch. Все чтения идут по
    одному sha; не закреплён ⇒ `None`, а причина дописывается в ``note`` (если
    передан) — тем же порядком, что и у прочих «не измерено».
    """
    pin = pin_server_ref(repo_root, ref)
    if note is not None:
        note.append(pin.describe())
    if not pin.ok:
        return None
    sha = pin.sha
    listing = _git(["grep", "-l", "^acceptance_probe:", sha, "--", TRACKER_REL + "/"],
                   repo_root=repo_root)
    if listing is None:
        return None
    out: dict = {}
    for line in listing.splitlines():
        # формат строки: `<sha>:<путь>`
        _, _, path = line.partition(":")
        if not path.endswith(".md") or os.path.basename(path).startswith("_"):
            continue
        blob = _git(["show", f"{sha}:{path}"], repo_root=repo_root)
        if blob is None:
            return None              # частично прочитанная популяция — не популяция
        out[os.path.basename(path)] = blob
    return out


def audit(tracker_dir: str | None = None, *, origin_readthrough: bool = True,
          ref: str = ORIGIN_REF, repo_root: str | None = None) -> dict:
    with one_pin_per_report():
        return _audit_in_one_pin(tracker_dir, origin_readthrough=origin_readthrough,
                                 ref=ref, repo_root=repo_root)


def _audit_in_one_pin(tracker_dir: str | None = None, *, origin_readthrough: bool = True,
                      ref: str = ORIGIN_REF, repo_root: str | None = None) -> dict:
    """Пройти карточки трекера и вынести вердикт по объявленным критериям.

    ОДИН ПРОХОД — ОДИН sha (``server_ref.one_pin_per_report``): дочитывание популяции
    и каждая проба, закрепляющая ``ref`` у сервера, внутри прохода получают ОДНО
    значение. Прежде проба многокритериального приказа спрашивала сервер на каждую
    карточку: ``ls-remote`` на элемент (при отрезанной сети — таймаут на элемент), и
    сервер, сдвинувшийся посреди прохода, судил первую карточку старым sha, вторую —
    новым.

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
        pin_note: list = []
        remote = cards_declaring_a_probe_on_ref(repo_root=repo_root, ref=ref,
                                                note=pin_note)
        if remote is None:
            origin = {"state": "unmeasured", "read": 0, "ref": ref,
                      "reason": f"популяцию с `{ref}` дочитать не удалось (нет git, "
                                f"значение ref не закреплено у сервера или чтение "
                                f"прервалось: {'; '.join(pin_note) or '?'}) — сколько "
                                f"карточек этому дереву невидимо, НЕ ИЗМЕРЕНО"}
        else:
            added = [(n, t) for n, t in sorted(remote.items()) if n not in local_names]
            sources.extend((n, t, True) for n, t in added)
            origin = {"state": "read", "read": len(added), "ref": ref,
                      "declared_on_ref": len(remote),
                      "pinned": "; ".join(pin_note)}

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


audit.__doc__ = _audit_in_one_pin.__doc__


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
