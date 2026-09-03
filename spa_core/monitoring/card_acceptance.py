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


PROBES: dict[str, Callable[[str | None], "tuple[str, str]"]] = {
    "contract_manifest_parity_agrees": _probe_contract_manifest_parity,
    "artifact_contract_confirmed": _probe_artifact_contract,
    "lead_channel_wiring_ok": _probe_lead_channel_wiring,
    "adapter_status_live_apy": _probe_adapter_status_live_apy,
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
