#!/usr/bin/env python3
"""ССЫЛКА, а не каталог: `origin/main` есть КЭШ последнего fetch (ЗАКАЗ #582).

ADR-355 доказал, что `cd` исполняется. ADR-356 — что каталог, в который он
ведёт, есть КОРЕНЬ рабочей копии. ADR-360 — что это корень ТОГО САМОГО
репозитория. Вся цепь до сих пор отвечала на вопрос «ГДЕ исполняется зов» и
ни разу — на вопрос «ЧТО означает ссылка, которую зов называет».

Вопрос заказа дословно: **`origin/main` в `reset --hard` есть КЭШ последнего
`fetch`, а не вопрос к серверу; у скольких зовов доказано, что ссылка означает
ту ветку того удалённого репозитория, о которой зов говорит?**

## Почему это вообще вопрос

`refs/remotes/origin/main` — обычная локальная ссылка. Она хранит ЗНАЧЕНИЕ и
не хранит ни провенанса, ни возраста: кто её записал, когда и из какого URL,
по самой ссылке узнать нельзя. `git reset --hard origin/main` читает её так
же спокойно через десять секунд после `fetch` и через десять дней без него, и
разницы в поведении нет никакой.

Возраст кэша измерен на ЭТОЙ машине, а не оценён (`git reflog show
refs/remotes/origin/main`, прод-дерево, 2017 записей с 18.06 по 12.09.2026):
медиана промежутка между обновлениями **0.26 ч**, p90 — **1.46 ч**, максимум —
**224.5 ч (9.4 суток)**. За второй по величине промежуток (147.9 ч) мимо
ссылки прошло **163** коммита. То есть «кэш» здесь — не теоретическая
оговорка: на этом хосте он уже бывал девятидневным.

## Что объявлено ДОКАЗАТЕЛЬСТВОМ — заранее, как требует цепь

Утверждение зова разложено на ДВЕ независимые оси, и обе обязаны сойтись,
иначе «доказано» будет сказано про половину.

**Ось 1 — СВЕЖЕСТЬ: значение ссылки спрошено у сервера на этом пути.**
Доказывается господствующим обновителем (`git fetch` / `git pull` /
`git remote update`), который (а) пишет ИМЕННО эту ссылку, (б) господствует
над зовом в порядке ИСПОЛНЕНИЯ (не в порядке строк — см. ниже) и (в) чей
ОТКАЗ прекращает путь до зова. Пункт (в) не украшение: `fetch`, чей код
возврата не проверен, при недоступной сети оставляет ссылку ровно такой, какой
она была, и следующая строка читает кэш, ничего об этом не зная.

**Ось 2 — ЛИЧНОСТЬ УДАЛЁННОГО: о каком репозитории говорит зов.**
`git fetch origin` разрешает имя `origin` через `.git/config` В МОМЕНТ
ИСПОЛНЕНИЯ. ADR-360 уже замерил, что это имя врёт в обе стороны на этом самом
хосте (прод-дерево несёт `…/SPA.git`, зеркало — `…/SPA`), и что настроить
чужой клон на наш URL можно одной командой. Поэтому:

| основание | что доказано |
|---|---|
| `by_url` | удалённый назван в самом зове URL-литералом — утверждение о личности ПУТЕШЕСТВУЕТ вместе с кодом |
| `by_config` | удалённый назван ИМЕНЕМ — личность решает конфиг той копии, где зов исполнится; на этой машине это наш репозиторий, но доказано это конфигом машины, а не кодом |
| `by_var` | удалённый пришёл из переменной, значение которой прибор не разрешил — НЕ ИЗМЕРЕНО |

## Порядок ИСПОЛНЕНИЯ, а не порядок строк

Наивная мерка «был ли `fetch` выше по файлу» изготовила бы уверенную ложную
находку на первом же скрипте: в `code_sync_from_origin.sh` ссылку читают
строки 118/146/148, а `fetch` стои́т на 176-й — но 118/146/148 лежат В ТЕЛАХ
функций, которые `main` зовёт ПОСЛЕ 176-й. Господство поэтому считается по
дороге вызовов, тем же приёмом, что `dominating_cd` в ADR-355: либо обновитель
в той же области строкой выше, либо зов лежит в функции, КАЖДЫЙ вызов которой
сам господствуем.

## Три исхода, и третий не складывается в первый (инвариант #17)

| исход | что доказано |
|---|---|
| `asked_and_gated` | значение спрошено у сервера, и отказ спроса прекращает путь |
| `asked_not_gated` | спрос есть, но его отказ ничего не прекращает: при недоступной сети зов читает кэш неизмеренного возраста |
| `cache_only` | спроса на этом пути нет вовсе — читается кэш |
| `unmeasured` | прибор не разобрал ссылку, файл или удалённого; причина названа, код возврата ненулевой |

## Предмет храповика УЖЕ, чем ответ, и это осознанно

Ответ на заказ — по ОБЕИМ осям. Предмет храповика — только ось 1
(`asked_not_gated` + `cache_only` + `unmeasured`). Причина: `by_config` есть
обычная и почти неизбежная идиома git, и храповик, краснеющий на каждом новом
`origin/main`, научил бы дописывать в базу — ровно то, ради чего храповики и
существуют, только наизнанку (`.claude/rules/deployment.md`). Ось 2
ДОКЛАДЫВАЕТСЯ числом и поимённо, но вердикта не выносит — тем же порядком,
каким ADR-360 докладывает `remote get-url origin`, не пуская его в вердикт.

## Чего прибор НЕ меряет — сказано вслух

- **Python-поверхность.** `push_to_github.py` и родня тоже читают `origin/main`;
  здесь они не мерены вовсе. Цепь #574…#582 идёт по shell-скриптам, и молча
  расширять население значило бы сравнивать несравнимое.
- **Возраст кэша в момент зова.** Он не выводится статически: прибор отвечает,
  СПРОШЕНО ли значение, а не НАСКОЛЬКО оно устарело.
- **Успех обновителя в конкретном прогоне.** Речь о том, что код ДЕЛАЕТ при
  отказе, а не о том, отказал ли он сегодня.
"""

from __future__ import annotations

import re
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shell_git_cwd_census import (            # noqa: E402
    collect_calls, shell_files, _INVOCATIONS,
)
from shell_git_cd_target_census import assignments   # noqa: E402
from git_path_coordinate_census import _subcommand, DYNAMIC   # noqa: E402

# Обновители remote-tracking ссылок. `ls-remote` сюда НЕ входит намеренно: он
# спрашивает сервер, но НИЧЕГО не записывает, поэтому ссылку не освежает.
# (Он же — правильная форма для того, кто хочет спросить сервер и не трогать
# кэш: так написан `pre_push_check.sh` после аварии 29.08.)
UPDATERS = {"fetch", "pull"}

# Имя удалённого, известное по построению. Прочие имена добираются замером —
# из самих скриптов (см. `known_remotes`).
DEFAULT_REMOTES = {"origin"}

# Подкоманды, МЕНЯЮЩИЕ рабочее дерево или историю. Читающий зов на стухшем
# кэше печатает неверное число; мутирующий — переписывает дерево на чужую
# ревизию, и это разная цена.
MUTATORS = {"reset", "rebase", "checkout", "merge", "switch", "restore",
            "cherry-pick", "revert"}

URL_RE = re.compile(r"^(https?://|ssh://|git://|file://|git@|/)")
DYN = DYNAMIC        # чем `collect_calls` заменяет неразрешённую подстановку
VAR_RE = re.compile(r'"?\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?"?')


# ───────────────────────── разбор ссылок в аргументах ─────────────────────────

def ref_candidates(token: str):
    """Куски аргумента, которые МОГУТ быть ссылками.

    Разбираются три формы, и каждая встречается в нашем наборе:
    `origin/main` · `origin/main:docs/X.md` (`git show`) · `HEAD..origin/main`
    (`git rev-list --count`). Двоеточие режется только СЛЕВА: `refs/remotes/…`
    двоеточий не содержит, а путь справа ссылкой не является."""
    if not token or token.startswith("-"):
        return []
    head = token.split(":", 1)[0] if ":" in token else token
    parts = re.split(r"\.\.\.?", head)
    return [p for p in parts if p]


def remote_ref(token: str, remotes: set[str]):
    """(удалённый, ветка) — либо None, если это не remote-tracking ссылка.

    `refs/remotes/<имя>/<ветка>` признаётся всегда: форма самодостаточна.
    `<имя>/<ветка>` — только когда имя ЗАМЕРЕНО как имя удалённого; иначе
    прибор принял бы за ссылку любой путь со слэшем."""
    if token.startswith("refs/remotes/"):
        rest = token[len("refs/remotes/"):]
        if "/" not in rest:
            return None
        name, _, branch = rest.partition("/")
        return (name, branch)
    if "/" in token:
        name, _, branch = token.partition("/")
        if name in remotes and branch and not branch.startswith("/"):
            return (name, branch)
    return None


def known_remotes(all_calls) -> set[str]:
    """Имена удалённых, ЗАМЕРЕННЫЕ по скриптам, плюс `origin` по построению."""
    out = set(DEFAULT_REMOTES)
    for c in all_calls:
        sub = _subcommand(c["argv"])
        if sub in ("fetch", "pull", "push"):
            rest = [t for t in c["argv"][c["argv"].index(sub) + 1:]
                    if not t.startswith("-")]
            if rest and rest[0] != DYN and "/" not in rest[0] \
                    and not URL_RE.match(rest[0]):
                out.add(rest[0])
        if sub == "remote" and "get-url" in c["argv"]:
            tail = c["argv"][c["argv"].index("get-url") + 1:]
            if tail and tail[0] != DYN:
                out.add(tail[0])
    return out


# ───────────────────────── что именно пишет обновитель ─────────────────────────

def raw_call_text(text: str, line: int) -> str:
    """Сырой текст строки зова — нужен там, где argv потерял подстановку.

    `collect_calls` отдаёт `dyn` вместо `"$REMOTE_URL"`, и по argv нельзя
    сказать, URL это или имя. Вопрос об основании (ось 2) решается именно
    здесь, поэтому строка перечитывается."""
    lines = text.split("\n")
    return lines[line - 1] if 0 < line <= len(lines) else ""


def updater_target(call, text, assigns):
    """Что обновитель пишет и чем доказана личность его удалённого.

    Возвращает (имя-или-None, множество-веток-или-ALL, основание, пояснение).
    `имя` — под каким именем ссылка ЛЯЖЕТ в локальный кэш: либо имя
    удалённого (умолчательный refspec), либо то, что названо справа от
    двоеточия в refspec'е."""
    argv = call["argv"]
    sub = _subcommand(argv)
    rest = [t for t in argv[argv.index(sub) + 1:] if not t.startswith("-")]
    remote_tok = rest[0] if rest else None
    refspecs = rest[1:]

    basis, why = "by_config", None
    remote_name = remote_tok
    if remote_tok is None:
        basis, why = "by_config", "удалённый не назван — берётся умолчание конфига"
        remote_name = "origin"
    elif URL_RE.match(remote_tok):
        basis, why = "by_url", f"удалённый назван URL-литералом {remote_tok}"
        remote_name = None
    elif remote_tok == DYN:
        # argv потерял подстановку — перечитываем строку и разрешаем имя по
        # присваиваниям того же файла (до строки зова). Не разрешилось —
        # честное «не измерено», а не догадка.
        m = VAR_RE.search(raw_call_text(text, call["line"]))
        name_in_var, val = (m.group(1) if m else None), None
        if name_in_var:
            got = assigns.get(name_in_var)
            if got and got[1] < call["line"]:
                val = got[0].strip().strip('"').strip("'")
        if val and URL_RE.match(val):
            basis, why = "by_url", (f"удалённый из ${name_in_var} — URL-литерал "
                                    f"{val}, присвоенный в этом же файле")
            remote_name = None
        elif val:
            basis, why = "by_config", (f"удалённый из ${name_in_var} = {val!r} — "
                                       "имя, разрешаемое конфигом")
            remote_name = val
        else:
            basis, why = "by_var", ("удалённый пришёл из подстановки, значение "
                                    "которой прибор не разрешил")
            remote_name = None
    else:
        basis, why = "by_config", (f"удалённый назван ИМЕНЕМ {remote_tok!r} — "
                                   "личность решает .git/config в момент зова")

    # Куда ляжет значение. Умолчательный refspec удалённого-ИМЕНИ пишет
    # `refs/remotes/<имя>/*`; URL без refspec'а не пишет НИЧЕГО в кэш
    # (FETCH_HEAD и только), и это важное различение, а не придирка.
    writes = []
    if refspecs:
        for spec in refspecs:
            if spec == DYN:
                writes.append((None, None))
                continue
            src, _, dst = spec.partition(":")
            if dst:
                got = remote_ref(dst, set(DEFAULT_REMOTES) | ({remote_name} if remote_name else set()))
                writes.append(got if got else (None, None))
            elif remote_name:
                writes.append((remote_name, src))
            else:
                writes.append((None, None))
    elif remote_name:
        writes.append((remote_name, "*"))
    else:
        writes.append((None, None))
    return remote_name, writes, basis, why


# ───────────────────────── господство в порядке ИСПОЛНЕНИЯ ─────────────────────

def _sane(u, call):
    """Обновитель, который исполнится, если до него дошли.

    Те же три условия, что у `dominating_cd` (ADR-355): не в теле ветвления,
    не правый операнд `&&`/`||`, его подоболочка объемлет подоболочку зова.
    Команда в УСЛОВИИ `if` исполняется до всякого ветвления — парсер уже
    приводит её глубину к объемлющей, поэтому отдельной оговорки не нужно."""
    return (u["depth"] == 0 and not u["conditional"]
            and str(call.get("scope", "")).startswith(str(u.get("scope", "\x00"))))


def dominating_updater(updaters, call, invocations=(), _seen=None):
    """Обновитель, про который ДОКАЗАНО, что он исполнился до зова.

    Две дороги, ровно как у `dominating_cd`, и вторая обязательна: без неё
    `code_sync_from_origin.sh` дал бы уверенную ЛОЖНУЮ находку — его ссылки
    читаются строками 118/146/148, а `fetch` стои́т на 176-й, и всё же
    исполняется раньше, потому что читают их тела функций, зовомых из `main`
    ПОСЛЕ 176-й."""
    _seen = _seen or set()
    before = [u for u in updaters if u["line"] < call["line"]]
    same = [u for u in before if _sane(u, call) and u["func"] == call["func"]]
    if same:
        return same[-1], f"обновитель строкой {same[-1]['line']} в той же области"

    fn = call["func"]
    if fn and fn not in _seen:
        sites = [i for i in invocations if i["argv"] and i["argv"][0] == fn]
        if sites:
            chain = []
            for site in sites:
                got, _why = dominating_updater(updaters, site, invocations,
                                               _seen | {fn})
                if not got:
                    break
                chain.append((site, got))
            else:
                site, got = chain[0]
                return got, (f"обновитель строкой {got['line']}: {fn}() зовётся "
                             f"строкой {site['line']}, и каждый её зов "
                             f"({len(sites)}) господствуем")
    return None, None


# ───────────────────────── прекращает ли отказ путь ─────────────────────────

IF_RE = re.compile(r"(^|\s|;)if\s")
FI_RE = re.compile(r"(^|\s|;)fi(\s|;|$)")
ELSE_RE = re.compile(r"(^|\s|;)else(\s|;|$)")
NEG_RE = re.compile(r"(^|\s|;)if\s+!\s")


def _if_block(text: str, start_line: int):
    """(строка-`else`|None, строка-`fi`) для `if`, начатого на start_line.

    Счёт по словам `if`/`fi`: `fi` закрывает только `if`, поэтому `for`/`while`
    вложенность не путают. Не сошлось — None, и это «не измерено», а не «нет
    ветки»."""
    lines = text.split("\n")
    depth, else_line = 0, None
    for n in range(start_line, len(lines) + 1):
        ln = lines[n - 1].split("#", 1)[0]
        depth += len(IF_RE.findall(ln))
        closes = len(FI_RE.findall(ln))
        if depth == 1 and else_line is None and ELSE_RE.search(ln):
            else_line = n
        depth -= closes
        if depth <= 0 and n > start_line - 1 and closes:
            return else_line, n
    return None, None


def next_command(ordered, cmd):
    """Команда, стоящая СРАЗУ ЗА данной, — по месту, а не по номеру строки."""
    for i, c in enumerate(ordered):
        if c is cmd:
            return ordered[i + 1] if i + 1 < len(ordered) else None
    return None


def prev_command(ordered, cmd):
    for i, c in enumerate(ordered):
        if c is cmd:
            return ordered[i - 1] if i else None
    return None


def failure_terminates(updater, cmds, text) -> tuple[bool, str]:
    """Прекращает ли ОТКАЗ обновителя путь до зова.

    Три формы, и все три живут в нашем наборе:

    1. `cmd && <зов>` — зов есть правый операнд, при отказе не исполняется
       вовсе (`agent_system_briefing.sh`). Считается на стороне зова.
    2. `<обновитель> || exit|return` — терминатор правым операндом.
    3. `if ! <обновитель>; then … return|exit … fi` — ветка отказа
       прекращает путь (`code_sync_from_origin.sh`).

    Плюс `set -e`: при нём отказ команды, НЕ стоящей в условии и не левым
    операндом `||`, роняет скрипт сам. Форма редкая в нашем наборе, но
    пропустить её значило бы записать в дефекты верный код."""
    line = updater["line"]
    # Сосед берётся по МЕСТУ в последовательности, а не по номеру строки:
    # `git fetch … || exit 1` живёт на ОДНОЙ строке, и строгое «строка больше»
    # теряло бы самый частый вид терминатора.
    nxt = next_command(cmds, updater)
    if nxt and nxt["conditional"] and nxt["argv"] \
            and nxt["argv"][0] in ("exit", "return"):
        return True, f"отказ прекращает путь: `|| {nxt['argv'][0]}` строкой {nxt['line']}"

    if updater.get("in_condition"):
        raw = raw_call_text(text, line)
        negated = bool(NEG_RE.search(raw))
        else_line, fi_line = _if_block(text, line)
        if fi_line is None:
            return False, ("условие `if` не сошлось по `fi` — ветка отказа НЕ "
                           "ИЗМЕРЕНА, и это не «прекращает»")
        lo, hi = ((line, else_line or fi_line) if negated
                  else ((else_line, fi_line) if else_line else (None, None)))
        if lo is None:
            return False, ("условие не отрицано и ветки `else` нет — у отказа "
                           "нет пути, который бы что-то прекращал")
        term = [c for c in cmds
                if lo < c["line"] < hi and c["argv"]
                and c["argv"][0] in ("exit", "return")
                and c["depth"] == updater["depth"] + 1]
        if term:
            return True, (f"отказ прекращает путь: `{term[0]['argv'][0]}` строкой "
                          f"{term[0]['line']} в ветке отказа")
        return False, (f"ветка отказа (строки {lo}–{hi}) ничего не прекращает — "
                       "при недоступной сети путь идёт дальше на КЭШЕ")

    prologue = "\n".join(text.split("\n")[:30])
    if re.search(r"(^|\n)\s*set\s+-[a-z]*e", prologue):
        return True, "`set -e` в прологе: отказ роняет скрипт сам"
    return False, "код возврата обновителя не проверяется ничем"


# ─────────────────────────────── перепись ───────────────────────────────

def census(repo_root: Path) -> dict:
    repo_root = repo_root.resolve()
    files = shell_files(repo_root)
    if not files:
        return {"unmeasured_fatal": (
            f"в {str(repo_root)!r} не найдено ни одного shell-скрипта — "
            "пустое население НЕ есть «чисто»")}

    per_file, unread, all_calls = {}, [], []
    for p in files:
        got, _cds, err = collect_calls(p, repo_root)
        if err:
            unread.append(err)
            continue
        rel = str(p.relative_to(repo_root))
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unread.append(f"{rel} не прочитан: {exc}")
            continue
        per_file[rel] = {"calls": got, "text": text,
                         "invocations": _INVOCATIONS.get(rel, [])}
        all_calls.extend(got)

    remotes = known_remotes(all_calls)
    rows = []
    for rel, blob in sorted(per_file.items()):
        calls, text = blob["calls"], blob["text"]
        assigns = assignments(text)
        updaters = [c for c in calls if _subcommand(c["argv"]) in UPDATERS]
        # Порядок команд файла — для вопроса «что стои́т сразу после».
        ordered = sorted(calls + blob["invocations"], key=lambda c: c["line"])

        for call in calls:
            sub = _subcommand(call["argv"])
            refs = []
            for tok in call["argv"][1:]:
                if tok == DYN:
                    continue
                for cand in ref_candidates(tok):
                    got = remote_ref(cand, remotes)
                    if got:
                        refs.append((got, tok))
            if not refs:
                continue
            # Обновитель ЧИТАЕТ свой refspec только как имя назначения — сам
            # себе свежести он не доказывает, и считать его читателем значило
            # бы населить класс его же лекарством.
            if sub in UPDATERS:
                continue

            for (remote, branch), tok in refs:
                cand = []
                for u in updaters:
                    _name, writes, basis, why = updater_target(u, text, assigns)
                    hit = any(w[0] == remote and w[1] in (branch, "*")
                              for w in writes if w[0])
                    if hit:
                        cand.append((u, basis, why))
                row = {"file": rel, "line": call["line"], "ref": tok,
                       "remote": remote, "branch": branch,
                       "call": " ".join(call["argv"])[:70],
                       "mutating": sub in MUTATORS}
                if not cand:
                    rows.append({**row, "verdict": "cache_only", "basis": "n/a",
                                 "why": ("на этом пути нет ни одного `fetch`, "
                                         "пишущего эту ссылку — читается кэш "
                                         "неизмеренного возраста")})
                    continue

                # Форма `обновитель && зов`: зов есть ПРАВЫЙ ОПЕРАНД, и при
                # отказе обновителя не исполняется вовсе. Проверяется ПЕРВОЙ,
                # потому что сам обновитель здесь тоже условен (`cd && fetch
                # && reset`), и общее правило господства его бы отвергло —
                # верно для вопроса «исполнится ли он», но не для нашего:
                # нам довольно, что БЕЗ него не исполнится ЗОВ.
                prev = prev_command(ordered, call)
                chained = [u for u, _b, _w in cand if prev is u]
                if call.get("conditional") and chained:
                    u = chained[0]
                    _n, _wr, basis, why = updater_target(u, text, assigns)
                    rows.append({**row, "verdict": "asked_and_gated",
                                 "basis": basis,
                                 "why": (f"зов — правый операнд `&&` сразу за "
                                         f"обновителем строкой {u['line']}: при "
                                         f"отказе не исполняется вовсе. "
                                         f"Личность удалённого: {why}")})
                    continue

                proven = dwhy = pbasis = pwhy = None
                for u, basis, why in cand:
                    got, w = dominating_updater([u], call, blob["invocations"])
                    if got:
                        proven, dwhy, pbasis, pwhy = u, w, basis, why
                        break
                if proven is None:
                    u, basis, _why = cand[0]
                    rows.append({**row, "verdict": "cache_only", "basis": basis,
                                 "why": (f"`fetch` строкой {u['line']} эту ссылку "
                                         "пишет, но НЕ доказано, что он исполнится "
                                         "до зова (ветка, подоболочка или другой "
                                         "порядок вызовов)")})
                    continue
                gated, gwhy = failure_terminates(proven, ordered, text)
                rows.append({**row,
                             "verdict": "asked_and_gated" if gated else "asked_not_gated",
                             "basis": pbasis,
                             "why": f"{dwhy}; {gwhy}. Личность удалённого: {pwhy}"})
    return {"root": str(repo_root), "files": len(files), "rows": rows,
            "remotes": sorted(remotes), "unread": unread}


def subject_keys(rows) -> list[str]:
    """Предмет ЭТОГО прибора — ось СВЕЖЕСТИ, и только она.

    `by_config` в предмет НЕ входит: это обычная идиома git, и храповик,
    краснеющий на каждом `origin/main`, научил бы дописывать в базу. Ось
    личности докладывается числом и поимённо, но вердикта не выносит."""
    return sorted({f"{r['file']}:{r['line']}" for r in rows
                   if r["verdict"] in ("asked_not_gated", "cache_only",
                                       "unmeasured")})


ORDER = ["asked_and_gated", "asked_not_gated", "cache_only", "unmeasured"]
TITLE = {"asked_and_gated": "СПРОШЕНО У СЕРВЕРА, и отказ прекращает путь",
         "asked_not_gated": "спрос есть, но его ОТКАЗ ничего не прекращает "
                            "(при недоступной сети — кэш)",
         "cache_only": "спроса нет вовсе — читается КЭШ",
         "unmeasured": "НЕ ИЗМЕРЕНО"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ЗАКАЗ #582: ссылка — кэш или вопрос к серверу")
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--baseline", default=None,
                    help="храповик: файл с замороженным предметом")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    rep = census(root)

    if "unmeasured_fatal" in rep:
        msg = f"⛔ НЕ ИЗМЕРЕНО: {rep['unmeasured_fatal']}"
        print(json.dumps({"unmeasured": rep["unmeasured_fatal"]},
                         ensure_ascii=False) if args.json else msg)
        return 2

    rows = rep["rows"]
    subject = subject_keys(rows)
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["verdict"], []).append(r)
    by_basis = {b: sum(1 for r in rows if r["basis"] == b)
                for b in ("by_url", "by_config", "by_var")}
    proven_both = [f"{r['file']}:{r['line']}" for r in rows
                   if r["verdict"] == "asked_and_gated" and r["basis"] == "by_url"]

    frozen, ratchet_err = None, None
    if args.baseline:
        bp = Path(args.baseline)
        if not bp.is_file():
            ratchet_err = f"базы храповика нет: {args.baseline!r}"
        else:
            try:
                frozen = sorted(set(json.loads(bp.read_text("utf-8"))["subject"]))
            except Exception as exc:                      # noqa: BLE001
                ratchet_err = f"база храповика не разобрана ({exc})"

    # `--json` печатает РОВНО один документ. Человеческие строки — в stderr:
    # тот же дефект ловили у приборов ADR-356 и ADR-360, здесь он закреплён
    # тестом заранее.
    def say(msg):
        print(msg, file=sys.stderr if args.json else sys.stdout)

    if args.json:
        print(json.dumps({
            "root": rep["root"], "files": rep["files"], "remotes": rep["remotes"],
            "reads": len(rows),
            "by_verdict": {k: len(groups.get(k, [])) for k in ORDER},
            "by_basis": by_basis, "mutating": sum(1 for r in rows if r["mutating"]),
            "proven_both_axes": proven_both,
            "subject": subject, "unread": rep["unread"],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"ССЫЛКА: кэш или вопрос к серверу — мерено из {rep['root']!r}")
        print(f"  скриптов прочитано: {rep['files']} · имена удалённых: "
              f"{', '.join(rep['remotes'])}")
        print(f"  зовов, ЧИТАЮЩИХ remote-tracking ссылку: {len(rows)} "
              f"(из них мутирующих: {sum(1 for r in rows if r['mutating'])})\n")
        for key in ORDER:
            grp = groups.get(key, [])
            print(f"── {TITLE[key]}: {len(grp)}")
            for r in grp:
                mark = "МУТИРУЕТ" if r["mutating"] else "читает"
                print(f"   {r['file']}:{r['line']}  [{r['basis']}] {mark} "
                      f"{r['ref']} — {r['why'][:130]}")
            print()
        print(f"основание личности удалённого: by_url={by_basis['by_url']} "
              f"(путешествует) · by_config={by_basis['by_config']} (решает "
              f".git/config той копии) · by_var={by_basis['by_var']} (не измерено)")
        print(f"ДОКАЗАНО ПО ОБЕИМ ОСЯМ (спрошено, отказ прекращает путь, и "
              f"удалённый назван URL-литералом): {len(proven_both)} из {len(rows)}"
              + (" — " + ", ".join(proven_both) if proven_both else ""))

    if rep["unread"]:
        say(f"⛔ НЕ ИЗМЕРЕНО: {len(rep['unread'])} файл(ов) не прочитаны — "
            f"{rep['unread'][0]}")
        return 2
    if ratchet_err:
        say(f"\n⛔ НЕ ИЗМЕРЕНО: {ratchet_err} — «нет базы» не есть «чисто»")
        return 2

    if frozen is not None:
        new = [k for k in subject if k not in frozen]
        if new:
            say(f"\n🔴 ХРАПОВИК: предмет ВЫРОС на {len(new)} — " + ", ".join(new))
            return 3
        gone = [k for k in frozen if k not in subject]
        if gone:
            say(f"\n🟢 предмет сократился на {len(gone)}: " + ", ".join(gone)
                + " — обнови базу")
        say("\n✅ храповик: предмет не вырос")
        return 0

    if subject:
        say(f"\n🔴 ПРЕДМЕТ НЕПУСТ: {len(subject)} зов(ов) читают ссылку, "
            "свежесть которой не доказана")
        return 3
    say("\n✅ предмет пуст")
    return 0


if __name__ == "__main__":
    sys.exit(main())
