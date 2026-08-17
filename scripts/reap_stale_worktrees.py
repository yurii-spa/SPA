#!/usr/bin/env python3
"""scripts/reap_stale_worktrees.py — «этот /tmp-worktree ещё держит работу, или это осадок?».

**Зачем.** Шаг 0a (`scripts/check_undelivered_work.py`) обязателен каждый цикл и обязан
читаться. К 14.08 он выдавал 6–7 одинаковых строк «НЕ ДОСТАВЛЕНО» цикл за циклом, и все они
указывали на `/tmp`-деревья мёртвых сессий (`git worktree list` — 70 регистраций, старейшая от
цикла #189). Работа при этом была доставлена: `docs/STATE.md` из дерева #227 «нет в истории
origin» ровно потому, что цикл #228 переписал файл ПОСЛЕ него. Сторож прав по своему контракту
и отвечает не на тот вопрос, который читают. Это тот самый механизм, которым сторожа глохнут:
следующая сессия учится пролистывать раздел, и настоящая находка проедет вместе с осадком
(класс «сторож отвечает не на тот вопрос», #146–#176).

**Чинится ПРИЧИНА — мёртвые деревья, а не проверка.** Сторож не ослабляется и не сужается:
здесь нет ни одной правки в `check_undelivered_work.py`.

**Правило снятия (все условия — И, иначе дерево ОСТАЁТСЯ):**

1. Это **линкованное** дерево, а не главное. Главное рабочее дерево не снимается никогда —
   и «главное» здесь берётся из порядка `git worktree list --porcelain` (главное первым),
   а НЕ из `--root`. До #234 щит сравнивал с `--root`, то есть с деревом, ОТКУДА запущен
   прогон: из worktree щит доставался одноразовому дереву сессии, а прод шёл в кандидаты
   на общих основаниях. Дерево самого прогона тоже не снимается — это второй, отдельный щит.
2. **Сессия молчит:** ни одного объявления в `data/session_changes.jsonl` про пути внутри
   этого дерева за окно ожидания, И ни одного файла в дереве, изменённого за то же окно
   (`--grace-hours`, по умолчанию 24). Не удалось прочитать журнал/файлы ⇒ дерево остаётся.
3. **Git в дереве отвечает.** `rev-parse` / `diff` / `status` дали ошибку ⇒ дерево остаётся
   как `unmeasured`, код возврата 2 (fail-CLOSED).
4. **Каждый непустой путь дерева объяснён.** По каждому пути, где содержимое дерева расходится
   с базой (`origin/main`), выносится вердикт:
   - ``delivered`` — точный blob этого содержимого ЕСТЬ в истории базы для этого пути. Пуш
     идёт прямо в origin через API, локально работа так и остаётся незакоммиченной правкой,
     поэтому «незакоммичено» ≠ «не доставлено»;
   - ``superseded`` — содержимого в истории нет, НО база продвинулась по этому пути после
     HEAD дерева (есть коммит, трогающий путь, не достижимый из HEAD). Перед нами промежуточное
     состояние уже перекрытой работы;
   - ``unique`` — содержимого в истории нет И база по этому пути с HEAD дерева не двигалась.
     Здесь может лежать НЕДОСТАВЛЕННАЯ работа ⇒ дерево остаётся, путь называется вслух;
   - ``absent`` — файла на базе нет вовсе. Всегда ``unique``-класс: отсутствие на базе
     самодостаточно.
5. **Перед снятием — архив.** Правка (`git diff <база>`) и копии неотслеживаемых файлов
   уезжают в `~/SPA_backups/worktree_reap/<имя>-<штамп>/` вместе с `manifest.json`. Работа не
   уничтожается, а перестаёт числиться рабочим деревом; восстановление — `git apply`.

**Общее состояние сессий живёт в ГЛАВНОМ дереве (#234).** Журнал объявлений и квитанция
снятия лежат в `data/`, а `data/` в `.gitignore` ⇒ в worktree их нет и не будет. Без `--root`
корнем берётся главное дерево (`git worktree list`), поэтому инструмент работает оттуда,
откуда его зовут по протоколу §3.4 — из изолированного worktree. Явный `--root`/`--log`
остаётся главнее. Отказ «журнал не прочитан» НЕ ослаблен: он по-прежнему отменяет снятие
целиком (fail-CLOSED), просто перестал срабатывать на пустом месте.

**`data/` из вопроса исключён — явно и вслух.** Живой цикл переписывает десятки `data/*.json`
в КАЖДОМ чекауте, где его запускали; это не работа сессии, а её след, и `CLAUDE.md` запрещает
возить `data/` доставкой. Исключение печатается в отчёте (количеством), а не молчит.

**Мёртвые регистрации** (`git worktree list` пометил `prunable`, каталога нет) — отдельный
класс: содержимого нет, мерить нечего, снимаются `git worktree prune`.

По умолчанию — сухой прогон (ничего не удаляется). Снятие — только `--apply`.

**`--worktree <путь>` — «я закончил, сними МОЁ дерево» (цикл #257).** Правило выше отвечает на
вопрос «дерево мёртвое?» — и для сессии, которая только что доставила работу и убирает за
собой, ответ ВСЕГДА «нет»: её объявление свежее, файлы изменены минуту назад (п. 2). То есть
измеренного способа убрать за собой не существовало, а `git worktree remove` руками оставляет
объявленные пути БЕЗ квитанции — и шаг 0a пишет о них «доставку измерить нечем» с кодом 2
НАВСЕГДА. Живой замер 16.08: дерево `/tmp/spa_c256` снято своей же сессией, работа лежит на
`origin/main` (HEAD `2adf5de8a`), а шаг 0a выдал **12 строк «НЕ ИЗМЕРЕНО» и код 2** — ровно тот
класс «необратимое „не измерено“ морит очередь», против которого писалась квитанция.

Явный режим снимает ТОЛЬКО п. 2 — признаки «сессия молчит». Их заменяет прямое утверждение
владельца дерева: он назвал дерево сам, и «жив ли тут кто-то» больше не гипотеза. Всё
остальное — щиты п. 1, ответ git п. 3, пофайловый вердикт п. 4 и архив+квитанция п. 5 — те же
самые, тем же кодом: **недоставленное по-прежнему ОТМЕНЯЕТ снятие**. Проверка «сессия молчит»
не ослабляется и не переписывается — обычный (подметающий) прогон её выполняет байт-в-байт как
раньше; появился второй вход, а не поблажка в старом.

**Второй реестр того же осадка — ЗАХВАТЫ КАРТОЧЕК (карточка
`agent-orphaned-work-recurred-after-its-card-was-closed`).** Мёртвая сессия оставляет не только
`/tmp`-дерево, но и строку `claimed_by`/`claimed_at` во frontmatter карточки. Эта строка живёт
в git и не истекает НИКОГДА, а шаг 0b по ней отвечает «занятость не измерена» (ярлык без pid —
`session_state` отдаёт UNKNOWN необратимо) ⇒ карточку нельзя взять, и рассосаться это не может:
держателя нет, спросить его личность не у кого. Замер трекера 16.08 — `cycle-28258` держит
`agent-fleet-parity-guard-never-scheduled` с 05.08 (11 суток), `cycle-87477` держит
`inbox-tier-c-pyat-nastoyaschih-otkazov-agregat` с 06.08. Подметающий прогон теперь их
**НАЗЫВАЕТ** (раздел «🔒 ПРОТУХШИЕ ЗАХВАТЫ КАРТОЧЕК», код возврата 1) — и только называет:
снятие чужого захвата остаётся ручным действием после сверки по шагу 0a, автоперехвата чужой
работы здесь нет и не будет, а вопрос «должен ли мёртвый захват блокировать подъём» открыт у
владельца (`owner-decision-otchet-o-zanyatosti-kartochki-bolshe-ne-sc`) и этой правкой не
трогается.

Коды возврата: **0** — всё измерено; **1** — есть деревья, которые остаются с недоставленным
(`unique`), либо протухшие захваты карточек; **2** — что-то измерить не удалось (перебивает 1).

    python3 scripts/reap_stale_worktrees.py                  # что снялось бы и почему
    python3 scripts/reap_stale_worktrees.py --json
    python3 scripts/reap_stale_worktrees.py --apply          # архив + снятие
    python3 scripts/reap_stale_worktrees.py --worktree /tmp/spa_cNNN           # сухой прогон
    python3 scripts/reap_stale_worktrees.py --worktree /tmp/spa_cNNN --apply   # убрать за собой
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Одно определение на репозиторий: «где живёт общее состояние сессий». Свою копию этого
# ответа заводить нельзя — два определения разойдутся, а вопрос буквально один и тот же
# (цикл #54 решил его для шага 0a, цикл #234 переносит сюда ИМПОРТОМ, не копией).
from check_undelivered_work import main_worktree  # noqa: E402
# Захват карточки читает и меряет ровно один модуль — шаг 0b. Своей копии правил «кто держит
# карточку» здесь нет и быть не может: два ответа на один вопрос — это и есть дефект.
import check_card_claim as card_claim  # noqa: E402

DEFAULT_BASE = "origin/main"
DEFAULT_GRACE_HOURS = 24.0
# Каталоги, чьё расхождение с базой не является работой сессии (см. докстринг).
CHURN_PREFIXES = ("data/",)
# Точечные пути с ИЗМЕРЕННЫМ писателем — их переписывает прогон тестов в любом чекауте, где
# его запускали (цикл #225 назвал ровно эти три, карточка `agent-test-run-dirties-tracked-fixtures`
# держит починку писателя). Список ЗАКРЫТЫЙ и поимённый: расширять его, чтобы «дерево наконец
# снялось», — то же самое, что гасить сторожа. Отсеянное считается и печатается.
CHURN_PATHS = frozenset({
    "spa_core/data/reward_harvesting_log.json",
    "spa_core/data/token_emission_log.json",
    "spa_core/database/spa.db",
})
ARCHIVE_ROOT = Path.home() / "SPA_backups" / "worktree_reap"

DELIVERED, SUPERSEDED, UNIQUE, ABSENT = "delivered", "superseded", "unique", "absent"
REAP, KEEP, UNMEASURED, PRUNABLE = "reap", "keep", "unmeasured", "prunable"

# Захват карточки: держится (свежий либо держатель жив) · протух (старше окна, активность не
# подтверждена) · не измерен (метка времени не разобрана — fail-CLOSED, а не «свободна»).
HELD, STALE_CLAIM, CLAIM_UNMEASURED = "held", "stale", "unmeasured"


def _git(cwd, *args: str):
    """(rc, stdout, stderr). Никогда не бросает — «git не отработал» это тоже измерение."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        p = subprocess.run(["git", "-C", str(cwd), *args],
                           capture_output=True, text=True, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", f"git недоступен: {exc}"
    return p.returncode, p.stdout, p.stderr


def _blob_sha(path):
    """git-хеш содержимого файла, посчитанный локально (без вызова git)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def list_registrations(root, git=_git):
    """([{path, prunable, reason}], причина-если-не-разрешилось).

    Разбор `git worktree list --porcelain`. Мёртвая регистрация (git сам сказал `prunable`)
    отделяется от живого дерева: это вердикт самого git о СВОЁМ реестре, содержимого там нет."""
    rc, out, err = git(root, "worktree", "list", "--porcelain")
    if rc != 0:
        return None, f"`git worktree list` завершился rc={rc}: {err.strip()[:200]!r}"

    regs, path, prunable = [], None, None

    def flush():
        if path is None:
            return
        regs.append({"path": str(path),
                     "prunable": prunable is not None,
                     "reason": (prunable or "").strip() or None,
                     "exists": path.is_dir(),
                     # `git worktree list --porcelain` перечисляет ГЛАВНОЕ дерево первым
                     # (документированный порядок) и делает это одинаково, откуда бы его ни
                     # звали. Признак берётся отсюда, а не из `--root`: см. `inspect`.
                     "main": not regs})

    for line in out.splitlines():
        if line.startswith("worktree "):
            flush()
            path, prunable = Path(line.split(" ", 1)[1].strip()), None
        elif line == "prunable" or line.startswith("prunable "):
            prunable = line[len("prunable"):]
    flush()
    return regs, None


def recent_declarations(log_path, grace_hours, now=None):
    """({корни объявленных путей, объявленные свежее окна}, причина-если-не-прочитано).

    Свежее объявление — единственный признак, по которому чужая работа видна ДО того, как
    в дереве что-то изменится (сессия могла объявить владение авансом)."""
    now = now or datetime.now(timezone.utc)
    path = Path(log_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"журнал объявлений не прочитан ({path}): {exc}"
    fresh = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue                      # битую строку журнала разбирает шаг 0a, не мы
        ts = obj.get("ts") or ""
        try:
            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if (now - when).total_seconds() <= grace_hours * 3600:
            fresh.extend(str(f) for f in (obj.get("files") or []))
    return fresh, None


def _declared_inside(wt_path, fresh_files):
    """Свежие объявления, чьи пути лежат внутри этого дерева."""
    prefix = str(Path(wt_path)) + os.sep
    hits = []
    for f in fresh_files:
        # /private/tmp и /tmp — один каталог на macOS; сравниваем оба написания.
        for cand in {f, f.replace("/private/tmp/", "/tmp/", 1), f.replace("/tmp/", "/private/tmp/", 1)}:
            if cand.startswith(prefix):
                hits.append(f)
                break
    return sorted(set(hits))


def newest_mtime(wt_path, grace_hours, now_ts=None, skip=(".git", "data", "__pycache__")):
    """(есть ли файл свежее окна, причина-если-не-измерено).

    Обход с ранним выходом: первый же свежий файл отвечает на вопрос. `data/` и `.git`
    пропускаются — их пишет не сессия (живой цикл и сам git)."""
    now_ts = now_ts if now_ts is not None else time.time()
    cutoff = now_ts - grace_hours * 3600
    try:
        for dirpath, dirnames, filenames in os.walk(wt_path):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                try:
                    if os.stat(os.path.join(dirpath, name)).st_mtime > cutoff:
                        return True, None
                except OSError:
                    continue              # исчезнувший файл не делает дерево свежим
    except OSError as exc:
        return None, f"обход дерева не удался: {exc}"
    return False, None


def _origin_blob_history(root, base_ref, rel, git=_git):
    """Множество blob-хешей всех версий пути в истории базы. None — прочитать не удалось."""
    rc, out, _ = git(root, "log", "--format=%H", "--raw", "--no-abbrev", "--no-renames",
                     base_ref, "--", rel)
    if rc != 0:
        return None
    shas = set()
    for line in out.splitlines():
        if line.startswith(":"):
            parts = line.split()
            if len(parts) >= 4:
                shas.add(parts[3])
    return shas


def _base_moved_since(root, base_ref, head, rel, git=_git):
    """Продвинулась ли база по этому пути ПОСЛЕ HEAD дерева. None — не измерено."""
    rc, out, _ = git(root, "log", "--format=%H", f"{head}..{base_ref}", "--", rel)
    if rc != 0:
        return None
    return bool(out.strip())


def classify_path(root, base_ref, head, wt_path, rel, git=_git):
    """(вердикт, объяснение) для одного расходящегося пути дерева."""
    rc, _, _ = git(root, "cat-file", "-e", f"{base_ref}:{rel}")
    if rc != 0:
        return ABSENT, f"на {base_ref} файла нет вовсе"

    sha = _blob_sha(Path(wt_path) / rel)
    history = _origin_blob_history(root, base_ref, rel, git=git)
    if history is None:
        return None, f"историю {base_ref} по пути прочитать не удалось"
    if sha is not None and sha in history:
        return DELIVERED, f"точное содержимое есть в истории {base_ref}"

    moved = _base_moved_since(root, base_ref, head, rel, git=git)
    if moved is None:
        return None, f"движение {base_ref} по пути измерить не удалось"
    if moved:
        return SUPERSEDED, f"содержимого в истории нет, но {base_ref} двигался по пути после HEAD дерева"
    return UNIQUE, f"содержимого нет в истории {base_ref}, и база по пути не двигалась с HEAD дерева"


def work_paths(wt_path, base_ref, git=_git):
    """(пути с работой, число отсеянных churn-путей, причина-если-не-измерено).

    Работа = пересечение «изменено в дереве» и «расходится с базой» (иначе заброшенное дерево
    на старом коммите расходится с origin в сотнях нетронутых файлов) ПЛЮС неотслеживаемые
    файлы, которых `git diff` не видит по построению."""
    rc, dirty, err = git(wt_path, "-c", "core.quotepath=false", "diff", "--name-only", "HEAD")
    if rc != 0:
        return None, 0, f"`git diff HEAD` rc={rc} {err.strip()[:120]!r}"
    rc, vs_base, err = git(wt_path, "-c", "core.quotepath=false", "diff", "--name-only", base_ref)
    if rc != 0:
        return None, 0, f"`git diff {base_ref}` rc={rc} {err.strip()[:120]!r}"
    rc, status, err = git(wt_path, "-c", "core.quotepath=false", "status", "--porcelain",
                          "--untracked-files=normal")
    if rc != 0:
        return None, 0, f"`git status` rc={rc} {err.strip()[:120]!r}"

    paths = ({ln for ln in dirty.split("\n") if ln} & {ln for ln in vs_base.split("\n") if ln})
    untracked = {ln[3:].strip() for ln in status.splitlines() if ln.startswith("??")}
    # Неотслеживаемый КАТАЛОГ git схлопывает в одну строку — разворачиваем в файлы.
    expanded = set()
    for u in untracked:
        full = Path(wt_path) / u
        if full.is_dir():
            for f in full.rglob("*"):
                if f.is_file():
                    expanded.add(str(f.relative_to(wt_path)))
        else:
            expanded.add(u)
    paths |= expanded

    churn = {p for p in paths if p.startswith(CHURN_PREFIXES) or p in CHURN_PATHS}
    return sorted(paths - churn), len(churn), None


def inspect(root, reg, base_ref, fresh_files, grace_hours, git=_git, now_ts=None,
            explicit=False):
    """Вердикт по одной регистрации: reap / keep / unmeasured / prunable + причины.

    ``explicit=True`` — дерево названо владельцем поимённо (`--worktree`, «я закончил»).
    Снимаются РОВНО признаки «сессия молчит» (свежее объявление и свежий mtime): они отвечают
    на вопрос «жив ли тут кто-то», а в явном режиме на него ответила сама сессия. Оба признака
    всё равно ИЗМЕРЯЮТСЯ и печатаются — чтобы в отчёте было видно, что именно перевесило
    прямое указание. Гарантия «недоставленное не будет похоронено» держится не ими, а
    пофайловым вердиктом ниже, и он в явном режиме тот же самый."""
    wt = reg["path"]
    out = {"path": wt, "verdict": None, "reasons": [], "paths": [], "churn": 0, "head": None,
           "explicit": bool(explicit)}

    if reg["prunable"] or not reg["exists"]:
        out["verdict"] = PRUNABLE
        out["reasons"].append(reg["reason"] or "каталога нет, регистрация осталась")
        return out

    # ДВА щита, а не один, и оба измеряются независимо от `--root`.
    #
    # До #234 щит был один и звучал как «главное рабочее дерево», а сравнивал с `--root` —
    # деревом, ОТКУДА запущен прогон. Из worktree (а §3.4 велит работать именно там) это
    # выдавало щит одноразовому дереву сессии, тогда как ПРОД шёл в кандидаты на общих
    # основаниях: замер 14.08 — прод уцелел только благодаря случайному свежему объявлению,
    # то есть по совпадению, а не по правилу. Классический «сторож отвечает не на тот вопрос».
    if reg.get("main"):
        out["verdict"] = KEEP
        out["reasons"].append("главное рабочее дерево — не снимается никогда")
        return out

    if Path(wt).resolve() == Path(root).resolve():
        out["verdict"] = KEEP
        out["reasons"].append("дерево этого прогона — не снимается (пилить сук под собой)")
        return out

    declared = _declared_inside(wt, fresh_files)
    if declared and not explicit:
        out["verdict"] = KEEP
        out["reasons"].append(f"свежее объявление владения ({len(declared)} путей, окно {grace_hours:g}ч)")
        return out

    recent, why = newest_mtime(wt, grace_hours, now_ts=now_ts)
    if recent is None:
        # «Обход дерева не удался» — это НЕ признак занятости, а неизмеримость, и явный режим
        # её не отменяет: снимать дерево, которое не читается, нельзя ни по чьей просьбе.
        out["verdict"] = UNMEASURED
        out["reasons"].append(why)
        return out
    if recent and not explicit:
        out["verdict"] = KEEP
        out["reasons"].append(f"в дереве есть файл, изменённый за последние {grace_hours:g}ч")
        return out

    if explicit:
        # Измерено и НАЗВАНО, а не пропущено молча: читатель отчёта видит, что перевесило.
        out["reasons"].append(
            "явное снятие своего дерева: признаки занятости измерены и перекрыты указанием "
            f"владельца дерева (свежих объявлений внутри: {len(declared)}; файл свежее "
            f"{grace_hours:g}ч: {'да' if recent else 'нет'}). Вердикт по путям — обычный")

    rc, head, err = git(wt, "rev-parse", "HEAD")
    if rc != 0:
        out["verdict"] = UNMEASURED
        out["reasons"].append(f"`rev-parse HEAD` rc={rc} {err.strip()[:120]!r}")
        return out
    out["head"] = head.strip()

    paths, churn, why = work_paths(wt, base_ref, git=git)
    out["churn"] = churn
    if paths is None:
        out["verdict"] = UNMEASURED
        out["reasons"].append(why)
        return out

    verdicts = []
    for rel in paths:
        state, why = classify_path(root, base_ref, out["head"], wt, rel, git=git)
        verdicts.append({"path": rel, "state": state, "why": why})
    out["paths"] = verdicts

    if any(v["state"] is None for v in verdicts):
        out["verdict"] = UNMEASURED
        out["reasons"].append("часть путей измерить не удалось: "
                              + "; ".join(f"{v['path']} — {v['why']}"
                                          for v in verdicts if v["state"] is None))
        return out

    risky = [v for v in verdicts if v["state"] in (UNIQUE, ABSENT)]
    if risky:
        out["verdict"] = KEEP
        out["reasons"].append("здесь может лежать НЕДОСТАВЛЕННАЯ работа: "
                              + ", ".join(f"{v['path']} ({v['state']})" for v in risky[:10])
                              + ("" if len(risky) <= 10 else f" и ещё {len(risky) - 10}"))
        return out

    out["verdict"] = REAP
    kinds = {}
    for v in verdicts:
        kinds[v["state"]] = kinds.get(v["state"], 0) + 1
    out["reasons"].append(
        "сессия молчит ≥ окна; работа объяснена вся: "
        + (", ".join(f"{k} {n}" for k, n in sorted(kinds.items())) if kinds else "правок нет")
        + (f"; отсеяно churn-путей: {churn}" if churn else ""))
    return out


def archive(wt, base_ref, verdicts, archive_root=ARCHIVE_ROOT, git=_git, stamp=None):
    """Сохранить правку дерева ДО снятия. Возвращает (путь архива, причина-если-не-удалось)."""
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = Path(archive_root) / f"{Path(wt).name}-{stamp}"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        rels = [v["path"] for v in verdicts]
        if rels:
            rc, patch, err = git(wt, "-c", "core.quotepath=false", "diff", base_ref, "--", *rels)
            if rc != 0:
                return None, f"`git diff {base_ref}` для архива rc={rc} {err.strip()[:120]!r}"
            (dest / "changes.patch").write_text(patch, encoding="utf-8")
        for v in verdicts:
            src = Path(wt) / v["path"]
            if src.is_file():
                copy_to = dest / "files" / v["path"]
                copy_to.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, copy_to)
        (dest / "manifest.json").write_text(json.dumps(
            {"worktree": str(wt), "base": base_ref, "archived_at": stamp, "paths": verdicts},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        return None, f"архив не записан ({dest}): {exc}"
    return str(dest), None


def reap(root, wt, git=_git):
    """`git worktree remove --force`. (успех, объяснение)."""
    rc, _, err = git(root, "worktree", "remove", "--force", str(wt))
    if rc != 0:
        return False, f"`git worktree remove` rc={rc} {err.strip()[:160]!r}"
    return True, "снято"


def record_reap(root, wt, base_ref, verdicts, churn, archive_dest, ledger=None, stamp=None):
    """Квитанция снятия — `data/worktree_reap_log.jsonl`. (путь журнала, причина-если-не-записано).

    **Без неё уборка меняет шило на мыло.** Шаг 0a про объявленный путь внутри исчезнувшего
    дерева говорит «рабочее дерево удалено вместе с объявленным путём — доставку измерить
    нечем» (код 2). То есть снятие само превращает разбираемую находку в НЕОБРАТИМОЕ «не
    измерено» — ровно тот класс, которым уже морили очередь. Квитанция несёт ИЗМЕРЕНИЕ,
    сделанное тогда, когда дерево ещё существовало: пофайловый вердикт и путь архива.
    Сторож от этого строже, а не слабее: пропуск даётся ровно тем путям, которые названы
    поимённо как `delivered`/`superseded`."""
    ledger = Path(ledger) if ledger else Path(root) / "data" / "worktree_reap_log.jsonl"
    row = {"ts": stamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "worktree": str(wt), "base": base_ref, "archive": archive_dest,
           "churn_paths": churn,
           "paths": {v["path"]: v["state"] for v in verdicts}}
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        return None, f"квитанция снятия не записана ({ledger}): {exc}"
    return str(ledger), None


def stale_claims(tracker_dir, log_path, grace_hours, now=None, ps=None, sibling=None):
    """([{card, holder, claimed_at, age_hours, state, why}], [причины-не-измеренного]).

    **Тот же осадок, только в другом реестре.** Мёртвая сессия оставляет после себя не только
    `/tmp`-дерево, но и **захват карточки**: строка `claimed_by`/`claimed_at` во frontmatter
    живёт в git и не истекает никогда. Замер трекера 16.08:

        agent-fleet-parity-guard-never-scheduled      — cycle-28258 с 2026-08-05T12:28:28Z (11 сут)
        inbox-tier-c-pyat-nastoyaschih-otkazov-agregat — cycle-87477 с 2026-08-06T18:43:13Z (10 сут)

    Обе сессии мертвы. Обе карточки шаг 0b читает как «занятость не измерена» (ярлык без pid —
    `session_state` отдаёт UNKNOWN детерминированно и необратимо) ⇒ код 2, «брать нельзя», и
    рассосаться это не может: держателя нет, а спросить его личность не у кого. Ровно тот
    механизм, которым карточка `agent-orphaned-work-recurred-after-its-card-was-closed`
    описывает рецидив: **защита от коллизий работает как защита от ПОДЪЁМА**.

    **Этот механизм ничего не снимает — он НАЗЫВАЕТ.** Снятие чужого захвата остаётся ручным
    действием (`check_card_claim.py release <карточка> --force`) и только после сверки по шагу
    0a; автоматический перехват чужой работы здесь не появляется, а вопрос «блокировать ли
    подъём мёртвым захватом» открыт у владельца
    (`owner-decision-otchet-o-zanyatosti-kartochki-bolshe-ne-sc`). Разница между «сторож молчит»
    и «сторож называет» и есть вся эта функция: молчащий осадок ждали одиннадцать суток.

    Меряет чужим кодом, своего не заводит: список захватов — `check_card_claim.list_claimed`,
    личность держателя — `durable_by_session` по журналу объявлений, активность —
    `session_state` шага 0a. `now` и `ps` — ВХОДЫ (время в тестах не берётся из окружения)."""
    now = now or datetime.now(timezone.utc)
    notes = []
    try:
        sibling = sibling or card_claim.load_sibling()
    except (ImportError, OSError, SyntaxError) as exc:
        return [], [f"захваты карточек не измерены: не загрузился шаг 0a ({exc})"]

    tracker = Path(tracker_dir)
    if not tracker.is_dir():
        return [], [f"каталог карточек не найден ({tracker}) — захваты карточек НЕ измерены"]

    entries = []
    log = Path(log_path) if log_path else None
    if log is None or not log.exists():
        notes.append(f"журнал объявлений не прочитан ({log}) — личность держателей захватов "
                     f"не измерена; возраст захвата измеряется по самой карточке")
    else:
        try:
            entries, _malformed = sibling.read_entries(log, None)
        except OSError as exc:
            notes.append(f"журнал объявлений нечитаем ({log}: {exc.__class__.__name__}) — "
                         f"личность держателей захватов не измерена")

    durables = card_claim.durable_by_session(entries, sibling)
    ps = ps or getattr(sibling, "_ps_lstart")

    rows = []
    for row in card_claim.list_claimed(tracker):
        if row["stale"]:
            # Терминальный статус: захват не действует по действующему правилу шага 0b
            # (`TERMINAL_STATUSES`). Это не находка и не осадок — работа закрыта.
            continue
        ts = sibling._parse_ts(row["claimed_at"])
        rec = {"card": row["card"], "holder": row["claimed_by"],
               "claimed_at": row["claimed_at"], "status": row["status"],
               "age_hours": None, "state": None, "why": ""}
        if ts is None:
            rec["state"] = CLAIM_UNMEASURED
            rec["why"] = (f"claimed_at не разобран ({row['claimed_at']!r}) — возраст захвата "
                          f"не измерен")
            rows.append(rec)
            continue
        state, why = sibling.session_state(
            {"session": row["claimed_by"], "ts": row["claimed_at"],
             **(durables.get(row["claimed_by"]) or {})}, None, ps=ps)
        rec["age_hours"] = round((now - ts).total_seconds() / 3600.0, 2)
        rec["why"] = why
        if state == sibling.ACTIVE:
            rec["state"] = HELD
            rec["why"] = f"держатель ЖИВ: {why}"
        elif rec["age_hours"] <= grace_hours:
            rec["state"] = HELD
            rec["why"] = f"захват свежее окна {grace_hours:g}ч: {why}"
        else:
            rec["state"] = STALE_CLAIM
        rows.append(rec)
    return rows, notes


def build_report(root, base_ref, log_path, grace_hours, git=_git, now=None, now_ts=None,
                 tracker_dir=None):
    regs, why = list_registrations(root, git=git)
    report = {"root": str(root), "base": base_ref, "grace_hours": grace_hours,
              "trees": [], "unmeasured_reasons": [], "claims": [], "claim_notes": []}
    # Захваты карточек считаются ДО разбора деревьев и переживают любой ранний выход: осадок
    # в реестре карточек не зависит от того, ответил ли `git worktree list`. `tracker_dir=None`
    # — «про карточки не спрашивали» (герметичные вызовы отчёта в тестах); CLI задаёт его всегда.
    if tracker_dir is not None:
        report["claims"], report["claim_notes"] = stale_claims(
            tracker_dir, log_path, grace_hours, now=now)
    if regs is None:
        report["unmeasured_reasons"].append(why)
        return report

    fresh, why = recent_declarations(log_path, grace_hours, now=now)
    if fresh is None:
        # Журнал не прочитан ⇒ «сессия молчит» доказать нечем ⇒ не снимаем НИЧЕГО.
        report["unmeasured_reasons"].append(why + " — снятие не выполняется (fail-CLOSED)")
        fresh = None

    for reg in regs:
        if fresh is None and not (reg["prunable"] or not reg["exists"]):
            report["trees"].append({"path": reg["path"], "verdict": UNMEASURED,
                                    "reasons": ["журнал объявлений не прочитан — занятость дерева не измерена"],
                                    "paths": [], "churn": 0, "head": None})
            continue
        report["trees"].append(inspect(root, reg, base_ref, fresh or [], grace_hours,
                                       git=git, now_ts=now_ts))
    return report


def _same_path(a, b) -> bool:
    """`/tmp` и `/private/tmp` на macOS — один каталог; сравниваем разрешённые пути."""
    try:
        return os.path.realpath(str(a)) == os.path.realpath(str(b))
    except OSError:
        return str(a) == str(b)


def build_self_report(root, base_ref, target, log_path, grace_hours, git=_git, now=None,
                      now_ts=None, cwd=None):
    """Отчёт по ОДНОМУ дереву, названному владельцем (`--worktree`).

    Не «ещё один уборщик», а тот же самый: регистрация ищется в `git worktree list`, вердикт
    выносит та же `inspect`. Отдельны здесь ровно два отказа, которых у подметающего прогона
    быть не может по построению:

    - **дерево не зарегистрировано** — просьба про каталог, которого git рабочим деревом не
      считает. Мерить нечего, снимать нечего, молчать нельзя ⇒ `unmeasured` (код 2);
    - **прогон идёт ИЗНУТРИ снимаемого дерева** — `git worktree remove` вынет каталог из-под
      собственного `cwd`, и всё, что сессия сделает следующей командой, произойдёт в
      несуществующем месте. Отказ с указанием, откуда звать (главное дерево).

    Журнал объявлений читается и здесь: он не решает исход (п. 2 снят), но число свежих
    объявлений внутри дерева печатается — «что перевесило» обязано быть видно."""
    report = {"root": str(root), "base": base_ref, "grace_hours": grace_hours,
              "trees": [], "unmeasured_reasons": [], "explicit_target": str(target)}

    regs, why = list_registrations(root, git=git)
    if regs is None:
        report["unmeasured_reasons"].append(why)
        return report

    reg = next((r for r in regs if _same_path(r["path"], target)), None)
    if reg is None:
        report["unmeasured_reasons"].append(
            f"{target} — git не считает этот каталог рабочим деревом этого репозитория "
            f"(`git worktree list` его не называет); снятие не выполняется (fail-CLOSED)")
        return report

    if reg.get("main"):
        # Щит «главное дерево не снимается никогда» (#234) не зависит ни от режима, ни от
        # того, откуда запущен прогон: прод — это не тот случай, где важно, где твой `cwd`.
        # Проверка «изнутри» стоит ПОСЛЕ него намеренно: иначе просьба про прод из самого
        # прода отвечала бы «перезапустись оттуда-то» вместо «этого не будет никогда».
        report["trees"].append(inspect(root, reg, base_ref, [], grace_hours, git=git,
                                       now_ts=now_ts, explicit=True))
        return report

    here = Path(cwd) if cwd is not None else Path.cwd()
    try:
        inside = _same_path(here, reg["path"]) or str(here.resolve()).startswith(
            os.path.realpath(reg["path"]).rstrip("/") + os.sep)
    except OSError:
        inside = False
    if inside:
        report["unmeasured_reasons"].append(
            f"прогон идёт изнутри снимаемого дерева ({here}) — снятие вынуло бы каталог "
            f"из-под собственного cwd; запусти из главного дерева: cd {root}")
        return report

    fresh, why = recent_declarations(log_path, grace_hours, now=now)
    if fresh is None:
        # Журнал не читается ⇒ печатать «что перевесило» нечем. Исход это не решает (п. 2 в
        # явном режиме снят), но неизмеренность называется вслух, как везде.
        report["unmeasured_reasons"].append(why + " — число свежих объявлений внутри дерева "
                                                  "не измерено (на вердикт не влияет)")
        fresh = []

    report["trees"].append(inspect(root, reg, base_ref, fresh, grace_hours, git=git,
                                   now_ts=now_ts, explicit=True))
    return report


def render(report) -> str:
    if report.get("explicit_target"):
        lines = [f"Явное снятие своего дерева {report['explicit_target']} "
                 f"(база {report['base']}); признаки «сессия молчит» сняты запросом, "
                 f"вердикт по путям — обычный"]
    else:
        lines = [f"Уборка рабочих деревьев (база {report['base']}, окно {report['grace_hours']:g}ч); "
                 f"регистраций: {len(report['trees'])}"]
    by = {}
    for t in report["trees"]:
        by.setdefault(t["verdict"], []).append(t)

    def block(key, title):
        rows = by.get(key) or []
        if not rows:
            return
        lines.append("")
        lines.append(f"{title} ({len(rows)}):")
        for t in rows:
            lines.append(f"  {t['path']}")
            for r in t["reasons"]:
                lines.append(f"      {r}")

    block(REAP, "🧹 СНИМАЕТСЯ — работа объяснена вся")
    block(PRUNABLE, "🗑  МЁРТВАЯ РЕГИСТРАЦИЯ — каталога нет, мерить нечего (git worktree prune)")
    block(KEEP, "🛑 ОСТАЁТСЯ")
    block(UNMEASURED, "❓ НЕ ИЗМЕРЕНО — молчаливого «всё в порядке» здесь не будет")

    stale = [c for c in report.get("claims") or [] if c["state"] == STALE_CLAIM]
    unmeasured_claims = [c for c in report.get("claims") or []
                         if c["state"] == CLAIM_UNMEASURED]
    if stale:
        lines.append("")
        lines.append(f"🔒 ПРОТУХШИЕ ЗАХВАТЫ КАРТОЧЕК ({len(stale)}) — держит сессия, чья "
                     f"активность не подтверждена; захват старше окна "
                     f"{report['grace_hours']:g}ч и сам не истечёт никогда:")
        for c in sorted(stale, key=lambda x: -(x["age_hours"] or 0)):
            lines.append(f"  {c['card']} [{c['status']}] — {c['holder']} "
                         f"с {c['claimed_at']} ({c['age_hours']}ч)")
            lines.append(f"      активность: {c['why']}")
        lines.append("  → снятие захвата — РУЧНОЕ действие после сверки по шагу 0a "
                     "(`check_card_claim.py release <карточка> --force`); уборщик захваты "
                     "не снимает и работу не перехватывает")
    if unmeasured_claims:
        lines.append("")
        lines.append(f"❓ ЗАХВАТЫ КАРТОЧЕК НЕ ИЗМЕРЕНЫ ({len(unmeasured_claims)}):")
        for c in unmeasured_claims:
            lines.append(f"  {c['card']} — {c['holder']}: {c['why']}")

    for r in report["unmeasured_reasons"]:
        lines.append(f"❓ {r}")
    for r in report.get("claim_notes") or []:
        lines.append(f"ℹ️  {r}")
    return "\n".join(lines)


def exit_code(report) -> int:
    if report["unmeasured_reasons"] or any(t["verdict"] == UNMEASURED for t in report["trees"]):
        return 2
    if any(c["state"] == CLAIM_UNMEASURED for c in report.get("claims") or []):
        return 2
    if any(t["verdict"] == KEEP and any("НЕДОСТАВЛЕННАЯ" in r for r in t["reasons"])
           for t in report["trees"]):
        return 1
    # Протухший захват — находка того же ранга, что оставшееся дерево с недоставленным: он
    # требует ручного разбора и сам не рассосётся. Молчаливого нуля здесь не будет.
    if any(c["state"] == STALE_CLAIM for c in report.get("claims") or []):
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Снятие мёртвых рабочих деревьев по правилу (причина осадка шага 0a)")
    ap.add_argument("--root", default=None,
                    help="рабочее дерево прогона (по умолчанию — ГЛАВНОЕ дерево репозитория, "
                         "потому что общее состояние сессий живёт только там)")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--log", default=None, help="журнал объявлений (по умолчанию data/session_changes.jsonl в --root)")
    ap.add_argument("--grace-hours", type=float, default=DEFAULT_GRACE_HOURS)
    ap.add_argument("--tracker-dir", default=None,
                    help="каталог карточек (по умолчанию nimbalyst-local/tracker в --root) — "
                         "в нём ищутся ПРОТУХШИЕ ЗАХВАТЫ мёртвых сессий; уборщик их только "
                         "называет, снятие остаётся ручным")
    ap.add_argument("--apply", action="store_true", help="архивировать и снять (по умолчанию — сухой прогон)")
    ap.add_argument("--worktree", default=None,
                    help="«я закончил, сними МОЁ дерево»: измерить и снять ОДНО названное "
                         "дерево. Снимает только признаки «сессия молчит» (её называет сам "
                         "запрос); недоставленное по-прежнему отменяет снятие")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    # `data/` в `.gitignore` ⇒ внутри worktree ни журнала объявлений, ни квитанции снятия НЕТ
    # и не будет: чтение даёт честный отказ (fail-CLOSED), а запись квитанции легла бы в
    # одноразовое дерево и исчезла вместе с ним — то самое «шило на мыло», от которого
    # квитанция и защищает. Поэтому по умолчанию корнем берётся ГЛАВНОЕ дерево. Явный
    # `--root` остаётся главнее: он и есть способ спросить про другое дерево.
    root_note = None
    if args.root:
        root = Path(args.root)
    else:
        resolved, why = main_worktree(ROOT)
        root = resolved or ROOT
        if resolved is None:
            # Не разрешилось ⇒ прежнее поведение (путь относительно этого файла). Молчаливым
            # «всё в порядке» это не станет: из worktree журнал не прочитается и снятие
            # не выполнится — отказ, а не пустой список кандидатов.
            root_note = f"главное рабочее дерево не определено ({why}) — корнем взят {ROOT}"

    log_path = args.log or (root / "data" / "session_changes.jsonl")
    tracker_dir = Path(args.tracker_dir) if args.tracker_dir else (
        root / "nimbalyst-local" / "tracker")
    if args.worktree:
        # Явный режим — «сними МОЁ дерево»; чужие захваты карточек тут не при чём, и мешать
        # их в ответ на конкретную просьбу значит учить пролистывать ответ.
        report = build_self_report(root, args.base, args.worktree, log_path, args.grace_hours)
    else:
        report = build_report(root, args.base, log_path, args.grace_hours,
                              tracker_dir=tracker_dir)
    if root_note:
        report["unmeasured_reasons"].append(root_note)

    if args.apply:
        for t in report["trees"]:
            if t["verdict"] == REAP:
                dest, why = archive(t["path"], args.base, t["paths"])
                if dest is None:
                    t["verdict"] = UNMEASURED
                    t["reasons"].append(f"{why} — снятие ОТМЕНЕНО (архив обязателен)")
                    continue
                # Квитанция пишется ДО снятия: дерева не станет, а измерение обязано пережить
                # его (иначе шаг 0a получит необратимое «нечем измерить»).
                ledger, why = record_reap(root, t["path"], args.base, t["paths"], t["churn"], dest)
                if ledger is None:
                    t["verdict"] = UNMEASURED
                    t["reasons"].append(f"{why} — снятие ОТМЕНЕНО (квитанция обязательна)")
                    continue
                ok, msg = reap(root, t["path"])
                t["archived"] = dest
                t["removed"] = ok
                t["reasons"].append(f"архив: {dest}; квитанция: {ledger}; {msg}")
                if not ok:
                    t["verdict"] = UNMEASURED
        if any(t["verdict"] == PRUNABLE for t in report["trees"]):
            rc, _, err = _git(root, "worktree", "prune")
            report["pruned"] = (rc == 0)
            if rc != 0:
                report["unmeasured_reasons"].append(f"`git worktree prune` rc={rc}: {err.strip()[:160]!r}")

    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
