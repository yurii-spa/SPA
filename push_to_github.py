#!/usr/bin/env python3
"""
push_to_github.py — универсальный пуш файлов в GitHub.
Читает PAT из переменной окружения GITHUB_PAT, файла ~/.spa_pat
или macOS Keychain (сервис GITHUB_PAT_SPA).
НЕ содержит hardcoded secrets.

ДОСТАВКА (что уезжает и как):
  * ОДИН файл  → Contents API, один PUT = один коммит (как было);
  * НЕСКОЛЬКО  → Git Data API (blobs → tree → commit → ref): весь набор
    приземляется ОДНИМ коммитом. Contents API принимает по одному файлу за
    вызов, поэтому раньше набор из N взаимозависимых файлов давал N коммитов
    и промежуточные состояния `main` были КРАСНЫМИ (карточка
    `agent-push-batch-per-file-commits`). Git Data API недоступен → честный
    отказ; файлы НЕ дошлются по одному молча.
  * неизменённые файлы пропускаются на обоих путях (пустых коммитов нет);
  * режим (x-бит) существующего файла сохраняется — снятый x-бит с
    bash-обёртки launchd = агент exit-78 (инвариант #12);
  * СТРАЖ ПЕРЕЗАПИСИ: если на remote путь изменился после базы рабочей копии,
    пуш либо накладывает нашу добавку на свежий remote (чистое дописывание),
    либо ОТКАЗЫВАЕТ — чужая правка не стирается молча (карточка
    `agent-shared-doc-whole-file-push-overwrites`). Осознанная перезапись —
    флаг `--allow-overwrite` / `SPA_PUSH_ALLOW_OVERWRITE=1`.

Использование:
  # Positional files (новый стиль):
  python3 scripts/push_to_github.py --repo yurii-spa/SPA --pat "$PAT" file1.py file2.py

  # --files флаг (старый стиль):
  python3 scripts/push_to_github.py --files file1.py file2.py --message "feat: описание"

  # --file одиночный (старый стиль):
  python3 scripts/push_to_github.py --file path/to/file.py --message "feat: описание"
"""
import os
import re
import sys
import json
import base64
import hashlib
import argparse
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

REPO = "yurii-spa/SPA"
API_BASE = "https://api.github.com"
PROJECT_ROOT = Path("/Users/yuriikulieshov/Documents/SPA_Claude")

# Режимы записей дерева. Git различает обычный файл и исполняемый; в этом репо
# 27 файлов — 100755, и среди них bash-обёртки launchd (`scripts/auto_push.sh`,
# `scripts/install_agents.sh`, …). Потерянный x-бит = агент падает exit-78
# (инвариант #12), поэтому режим существующего файла НИКОГДА не выдумывается.
BLOB_MODE = "100644"
EXEC_MODE = "100755"


class RepoPathError(ValueError):
    """Локальный путь не удалось отобразить в путь ВНУТРИ целевого репозитория.

    Раньше этот случай молча превращался в ``local.name`` — файл уезжал в КОРЕНЬ
    репо под своим basename, а инструмент печатал ``OK`` с настоящей sha
    (цикл #40: 6 файлов из worktree легли в корень). Теперь это жёсткая ошибка:
    fail-CLOSED, инвариант #2 — лучше отказать, чем доставить не туда.
    """


def _git_out(args: list, cwd) -> Optional[str]:
    """Один `git -C <cwd> <args>`; None на любой сбой (нет git / не репо / ошибка).

    Никогда не бросает: отсутствие git в PATH (launchd-окружение autopush!) —
    штатный сценарий, вызывающий код падает обратно на PROJECT_ROOT.
    """
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def _common_git_dir(start) -> Optional[Path]:
    """Разрешённый *общий* .git-каталог репозитория, содержащего ``start``.

    Все linked worktrees одного репозитория делят ОДИН common dir, поэтому это
    точный признак «тот же самый репозиторий», а не «просто какой-то git-репо».
    """
    out = _git_out(["rev-parse", "--git-common-dir"], start)
    if not out:
        return None
    p = Path(out)
    if not p.is_absolute():          # git отдаёт ".git" относительно cwd
        p = Path(start) / p
    try:
        return p.resolve()
    except OSError:
        return None


def repo_relative_path(local: Path, project_root: Optional[Path] = None) -> str:
    """Путь файла ВНУТРИ репозитория. Fail-CLOSED: никогда не возвращает basename.

    Корень определяется ПО ФАКТУ (`git rev-parse --show-toplevel`), а не по
    константе — поэтому файл из изолированного worktree (`/tmp/spa_wt_*/...`),
    в котором протокол оркестратора ОБЯЗЫВАЕТ работать (§3.4), релятивизируется
    правильно. Порядок:

      1. worktree/checkout, содержащий файл, принадлежит ТОМУ ЖЕ репозиторию,
         что и ``project_root`` (сверка по common git dir) → путь от его toplevel;
      2. иначе (git недоступен / не репо / сверку не провести) → путь от
         ``project_root``, как было исторически;
      3. иначе → :class:`RepoPathError`.

    Чужой репозиторий и путь вне любого репо дают ошибку, а не догадку.
    ``project_root=None`` берёт модульный :data:`PROJECT_ROOT` в момент ВЫЗОВА
    (а не в момент определения функции) — иначе константу нельзя подменить в тестах.
    """
    if project_root is None:
        project_root = PROJECT_ROOT
    local_res = Path(local).resolve()
    root_res = Path(project_root).resolve()

    parent = Path(local).parent
    top = _git_out(["rev-parse", "--show-toplevel"], parent) if parent.exists() else None
    if top:
        mine, theirs = _common_git_dir(parent), _common_git_dir(project_root)
        if mine is not None and theirs is not None and mine == theirs:
            try:
                return str(local_res.relative_to(Path(top).resolve()))
            except ValueError:
                pass  # ниже — попытка от project_root, затем честная ошибка

    try:
        return str(local_res.relative_to(root_res))
    except ValueError:
        raise RepoPathError(
            f"не могу определить путь внутри репозитория для {local}: путь вне "
            f"{project_root} и не принадлежит рабочей копии ЭТОГО же репозитория. "
            f"Пуш отменён (fail-CLOSED) — раньше здесь молча бралось имя файла и "
            f"файл уезжал в КОРЕНЬ репо. Передай путь внутри {project_root} либо "
            f"сделай worktree через `git worktree add`."
        )


# ── СВЕРКА ИНСТРУМЕНТА ДОСТАВКИ (карточка `agent-host-pusher-copy-is-stale`) ──
# Файлы этого репозитория, которые ВМЕСТЕ образуют доставку: пушер, batch-CLI,
# шим и owner-gate сайта. Копии всех пяти лежат в КАЖДОМ рабочем дереве, а
# протокол оркестратора ОБЯЗЫВАЕТ работать в изолированном worktree (§3.4) —
# значит «какую копию я сейчас запустил» перестаёт быть риторическим вопросом.
TOOLCHAIN_FILES = (
    "push_to_github.py",
    "push_to_github_batch.py",
    "scripts/push_to_github.py",
    "scripts/safe_site_push.py",
    "scripts/check_owner_gate.py",
)


class ToolchainMismatch(RuntimeError):
    """Запущенный инструмент доставки НЕ тот, что лежит в дереве отправляемых файлов.

    Измерено 2026-07-31 (цикл #53 → #59): копия пушера в хост-репо отстала на
    574 строки и не содержала `batch_push` вовсе, поэтому сессия, вызвавшая
    пушер СТРОКОЙ ИЗ `CLAUDE.md` (`python3 push_to_github.py --files ...`),
    получала до-#49 доставку — набор лёг на `main` ВОСЕМЬЮ коммитами вместо
    одного, и промежуточные состояния `main` могли быть красными. Хост-дерево
    дрейфует от `origin` ПО ПОСТРОЕНИЮ (пуши идут прямо в origin через API),
    поэтому разовая синхронизация лечит симптом, а не причину.

    Отказ — fail-CLOSED (инвариант #2): доставить не тем инструментом хуже, чем
    не доставить и получить внятную причину.
    """


def _tree_top(path) -> Optional[Path]:
    """Toplevel рабочего дерева, которому принадлежит путь (или None)."""
    parent = Path(path).parent
    if not parent.exists():
        return None
    top = _git_out(["rev-parse", "--show-toplevel"], parent)
    return Path(top).resolve() if top else None


def toolchain_verdict(runner_file, file_args: list) -> dict:
    """Сверить инструмент доставки, который РАБОТАЕТ, с копией в дереве файлов.

    Возвращает ``{"mismatch": [...], "unchecked": [...], "runner_top": Path|None,
    "trees": [Path, ...]}``. Ничего не печатает и не пушит — решение принимает
    вызывающий (:func:`enforce_delivery_toolchain`).

    Устройство измерения:

    * файлы из ТОГО ЖЕ дерева, что и запущенный пушер, сверять не с чем —
      расхождение невозможно по построению (``trees`` тогда пуст);
    * для каждого ЧУЖОГО дерева сверяются побайтово все файлы
      :data:`TOOLCHAIN_FILES`, существующие в ОБОИХ деревьях;
    * файл есть только с одной стороны / дерево не определяется / файл нечитаем
      → это **не измерено**, а не «совпало»: попадает в ``unchecked``
      вербатим-причиной. Молчаливого «всё в порядке» о непроверенном здесь нет
      (класс дефектов #29/#31/#35–#38/#40), но и отказа тоже — отказ только по
      ИЗМЕРЕННОМУ расхождению.
    """
    out: dict = {"mismatch": [], "unchecked": [], "runner_top": None, "trees": []}
    runner_top = _tree_top(runner_file)
    if runner_top is None:
        out["unchecked"].append(
            f"рабочее дерево запущенного пушера не определяется ({runner_file}) — "
            f"git недоступен или это не рабочая копия")
        return out
    out["runner_top"] = runner_top

    tops: list = []
    for f in file_args:
        top = _tree_top(f)
        if top is None:
            out["unchecked"].append(f"дерево файла не определяется: {f}")
            continue
        if top != runner_top and top not in tops:
            tops.append(top)
    out["trees"] = tops

    for top in tops:
        for rel in TOOLCHAIN_FILES:
            mine, theirs = runner_top / rel, top / rel
            if not mine.exists() or not theirs.exists():
                missing = mine if not mine.exists() else theirs
                out["unchecked"].append(f"{rel}: нечего сравнивать — нет {missing}")
                continue
            try:
                a, b = mine.read_bytes(), theirs.read_bytes()
            except OSError as e:
                out["unchecked"].append(f"{rel}: нечитаем ({e})")
                continue
            if a != b:
                out["mismatch"].append({
                    "rel": rel,
                    "runner": str(mine), "runner_sha": git_blob_sha(a),
                    "runner_lines": a.count(b"\n"),
                    "tree": str(theirs), "tree_sha": git_blob_sha(b),
                    "tree_lines": b.count(b"\n"),
                })
    return out


def enforce_delivery_toolchain(file_args: list, allow: bool = False,
                               runner_file: Optional[str] = None) -> dict:
    """Отказать, если запущенный инструмент доставки разошёлся с деревом файлов.

    Печатает в stderr и бросает :class:`ToolchainMismatch` при ИЗМЕРЕННОМ
    расхождении; «не измерено» печатается честной строкой и пуш продолжается
    (см. :func:`toolchain_verdict`). ``allow=True`` — осознанное продолжение.
    """
    verdict = toolchain_verdict(runner_file or __file__, file_args)
    if verdict["unchecked"] and verdict["trees"]:
        print("сверка инструмента доставки: НЕ ИЗМЕРЕНО "
              f"({len(verdict['unchecked'])}): " + "; ".join(verdict["unchecked"][:3]),
              file=sys.stderr)
    if not verdict["mismatch"]:
        return verdict

    lines = [
        "",
        "ОТКАЗ (сверка инструмента доставки): работает копия из "
        f"{verdict['runner_top']}, а файлы едут из "
        + ", ".join(str(t) for t in verdict["trees"]) + " — и инструмент там ДРУГОЙ:",
    ]
    for m in verdict["mismatch"]:
        lines.append(
            f"  · {m['rel']}: {m['runner']} ({m['runner_lines']} строк, "
            f"{m['runner_sha'][:8]}) ≠ {m['tree']} ({m['tree_lines']} строк, "
            f"{m['tree_sha'][:8]})")
    tree = verdict["trees"][0]
    lines += [
        "Зови инструмент ИЗ ТОГО ЖЕ дерева, которое ты собрал и протестировал:",
        f'  python3 {tree}/push_to_github.py --files <абс. пути> --message "..."',
        "Так цикл #53 доставил набор ВОСЕМЬЮ коммитами вместо одного: копия в "
        "хост-репо отстала на 574 строки и не знала batch-пути (карточка "
        "`agent-host-pusher-copy-is-stale`).",
        "Осознанно продолжить: --allow-toolchain-mismatch (или "
        "SPA_PUSH_ALLOW_TOOLCHAIN_MISMATCH=1).",
    ]
    msg = "\n".join(lines)
    if allow:
        print(msg + "\n(продолжаю: расхождение разрешено явно)", file=sys.stderr)
        return verdict
    print(msg, file=sys.stderr)
    raise ToolchainMismatch(msg)


def get_pat() -> str:
    """Читает PAT (никогда из hardcode).

    Порядок поиска:
      1. macOS Keychain (сервис GITHUB_PAT_SPA)
      2. Переменная окружения GITHUB_PAT_SPA
      3. Переменная окружения SPA_GITHUB_PAT
      4. Файл ~/.github_pat или рядом со скриптом
    """
    # 1. macOS Keychain
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-w"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            pat = result.stdout.strip()
            if pat:
                return pat
    except Exception:
        pass

    # 2–3. Переменные окружения
    for env_var in ("GITHUB_PAT_SPA", "SPA_GITHUB_PAT", "GITHUB_PAT"):
        pat = os.environ.get(env_var, "").strip()
        if pat:
            return pat

    # 4. Файл
    for pat_file in [
        Path.home() / ".github_pat",
        PROJECT_ROOT / ".github_pat",
        Path.home() / ".spa_pat",
    ]:
        if pat_file.exists():
            pat = pat_file.read_text().strip()
            if pat:
                return pat

    raise RuntimeError(
        "PAT не найден в Keychain (GITHUB_PAT_SPA).\n"
        "Добавь PAT командой:\n"
        "  security add-generic-password -s GITHUB_PAT_SPA -a yurii-spa -w ghp_ТОКЕН\n"
        "Или через setup_pat.sh:\n"
        "  bash scripts/setup_pat.sh ghp_ТОКЕН\n"
    )


def git_blob_sha(content: bytes) -> str:
    """Вычисляет git blob SHA-1 для байтов файла.

    Это в точности тот же хеш, что GitHub возвращает в поле ``sha`` Contents API
    (git хеширует blob как ``"blob <len>\\0" + content``). Детерминированно,
    stdlib-only. Позволяет сравнить локальное содержимое с тем, что уже лежит
    на remote, БЕЗ скачивания файла — и пропустить пуш, если они идентичны.
    """
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# СВЕРКА ДОСТАВЛЕННОГО
#
# ЗАЧЕМ (карточка `agent-pusher-does-not-verify-what-it-delivered`, найдено
# циклом #99). Пушер печатал `OK … pushed=N, skipped=0`, ни разу не сверив, что
# на remote легли именно наши байты: побайтовую проверку делала ДИСЦИПЛИНА
# вызывающего (`git show origin/main:<файл> | cmp - <файл>` вручную после пуша).
# Дубль хвоста `docs/journal/2026-W32.md` в цикле #95 поймала именно она —
# убери сверку из протокола, и порча уехала бы в общую память проекта под
# зелёным `OK`. Это ровно класс #29/#31/#35–#38/#40: утверждение об измерении,
# которого не было. Живые вызывающие (`com.spa.autopush` → `auto_push.sh`,
# дневной цикл, кастодиан сайта) в момент запуска никто не смотрит.
#
# ЧЕМ СВЕРЯЕМ И ПОЧЕМУ ИМЕННО ТАК. Второго GET после записи здесь НЕТ —
# намеренно. Contents API согласован в конечном счёте (тот же эффект уже
# измерен на refs, см. `_read_ref_with_404_retry`: только что созданная ветка
# отвечала 404), поэтому чтение сразу после PUT могло бы вернуть ПРЕЖНЕЕ
# содержимое ⇒ ложный красный на ровном месте, то есть тихо вставшая доставка —
# ровно та цена, от которой карточка и предостерегает. Вместо этого сверяем
# sha, которую вернул САМ ответ на нашу запись:
#   * PUT   `/contents/{path}`      → `content.sha`   (push_file)
#   * POST  `/git/blobs`            → `sha`           (create_blob_from_bytes)
#   * PATCH `/git/refs/heads/{br}`  → `object.sha`    (update_ref)
# Это ответ на нашу операцию, а не отдельное чтение: ни задержки согласованности,
# ни ретраев, ни лишних запросов — стоимость сверки РОВНО НОЛЬ дополнительных
# обращений к API на любом батче.
#
# ТРИ ИСХОДА, и «не измерено» НЕ выдаётся за совпадение (инвариант #2):
#   match      — sha ответа == git-blob-SHA отправленного;
#   mismatch   — обе sha прочитаны и РАЗНЫЕ → честный FAIL. Не «warning»:
#                предупреждение, которое никто не читает, — это fail-OPEN;
#   unmeasured — sha в ответе нет либо она не 40-hex → печатается явной строкой
#                (как ноты `guard_overwrite`) и доставку НЕ блокирует.
# ══════════════════════════════════════════════════════════════════════════════


class DeliveryUnverified(RuntimeError):
    """Доставленное не совпало с отправленным — доставка объявляется неуспешной.

    Отдельный тип (а не общий ``RuntimeError``), чтобы вызывающий мог отличить
    «не смогли доставить» от «доставили НЕ ТО»: второе означает, что на remote
    уже лежит чужое/испорченное содержимое по нашему пути, и следующий шаг —
    смотреть remote, а не повторять пуш.
    """


def _is_sha40(value) -> bool:
    """Строка ли это полной git-sha (40 hex). Всё остальное — «не измерено»."""
    if not isinstance(value, str) or len(value) != 40:
        return False
    return all(c in "0123456789abcdef" for c in value.lower())


def verify_sha_delivery(expected_sha: str, returned_sha, what: str) -> dict:
    """Сверить sha из ответа API с ожидаемой. Вернуть вердикт (не бросает).

    Возвращает ``{"state": "match"|"mismatch"|"unmeasured", "what", "expected",
    "returned", "note"}``. Решение (FAIL / печать строки) принимает вызывающий:
    у Contents API и Git Data API разная цена ошибки, а формулировка вердикта
    обязана быть одна — близнец такой же арифметики уже оставлял CI красным
    (цикл #37) и рассылал файлы в корень репо (цикл #40).
    """
    if not _is_sha40(returned_sha):
        return {"state": "unmeasured", "what": what,
                "expected": expected_sha, "returned": returned_sha,
                "note": (f"НЕ ИЗМЕРЕНО: {what} — в ответе API нет пригодной sha "
                         f"({returned_sha!r}), сверить доставленное не с чем; "
                         f"доставку не блокирую")}
    if returned_sha.lower() != expected_sha.lower():
        return {"state": "mismatch", "what": what,
                "expected": expected_sha, "returned": returned_sha,
                "note": (f"ДОСТАВЛЕНО НЕ ТО: {what} — отправляли {expected_sha[:8]}, "
                         f"а remote подтвердил {returned_sha[:8]}")}
    return {"state": "match", "what": what,
            "expected": expected_sha, "returned": returned_sha, "note": ""}


def verify_blob_delivery(sent: bytes, returned_sha, what: str) -> dict:
    """То же для содержимого: ожидаемое — git-blob-SHA ОТПРАВЛЕННЫХ байтов.

    Важно, что сверяются именно отправленные байты, а не файл с диска: страж
    перезаписи (`guard_overwrite`) может отправить «свежий remote + наш хвост»,
    и сверка с файлом краснела бы каждый раз, когда пере-база сработала по делу.
    """
    return verify_sha_delivery(git_blob_sha(sent), returned_sha, what)


def get_file_sha(pat: str, repo: str, repo_path: str, branch: str = "main") -> Optional[str]:
    """Возвращает SHA файла на GitHub (на указанной ветке)."""
    import urllib.request
    url = f"{API_BASE}/repos/{repo}/contents/{repo_path}?ref={branch}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            return data.get("sha")
    except Exception:
        return None


def get_file_content(pat: str, repo: str, repo_path: str, branch: str = "main") -> Optional[bytes]:
    """Содержимое файла на GitHub. None — если прочитать не удалось.

    Нужно ТОЛЬКО для пере-базы дописывания (см. :func:`rebase_append`): чтобы
    наложить нашу добавку на свежий remote, свежий remote надо иметь. Contents
    API не отдаёт `content` для файлов >1 МБ — это `None`, а не пустота, и
    пере-база тогда не делается (отказ вместо догадки).
    """
    url = f"{API_BASE}/repos/{repo}/contents/{repo_path}?ref={branch}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        if data.get("encoding") != "base64" or not isinstance(data.get("content"), str):
            return None
        return base64.b64decode(data["content"])
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# СТРАЖ ПЕРЕЗАПИСИ: доставка целыми файлами ≠ право стереть чужую правку
#
# ЗАЧЕМ (карточка `agent-shared-doc-whole-file-push-overwrites`, найдено #50):
# пушер отправляет СОДЕРЖИМОЕ файла и коммитит поверх текущего `main` — слияния
# нет. Для файлов, которые ДОПИСЫВАЮТ (недельный журнал, `docs/STATE.md`,
# `_BOARD.md`), это «последний писатель побеждает»: сессия с более старой базой
# молча сносит запись той, что успела запушить раньше. Протокол ОБЯЗЫВАЕТ
# каждый цикл дописывать ровно эти файлы (§«Шаг 3 — обновить память»), то есть
# пересечение неизбежно в КАЖДОМ цикле, а поймать потерю нечем: шаг 0b на общие
# документы работать не может (иначе занята любая карточка), шаг 0a увидит
# расхождение только СЛЕДУЮЩИМ циклом и без атрибуции, а пушер честно скажет
# `OK` — он доставил ровно то, что ему дали.
#
# ЧТО ДЕЛАЕМ. Перед PUT сравниваем ТРИ версии: база рабочей копии (`HEAD:<путь>`)
# · наша локальная · та, что сейчас на remote.
#   * remote == база                 → терять нечего, пуш как раньше;
#   * обе стороны — чистое ДОПИСЫВАНИЕ → наша добавка накладывается на свежий
#     remote (пере-база), обе записи выживают;
#   * иначе                          → ОТКАЗ (fail-CLOSED, инвариант #2).
# Содержимое «по смыслу» не сливается никогда — только дописывание либо отказ.
#
# ГРАНИЦА ПРИМЕНИМОСТИ измеряется, а не предполагается: база достоверна лишь
# если HEAD рабочей копии — предок ветки доставки (`refs/remotes/origin/<ветка>`).
# Так страж включается ровно в изолированных worktree протокола (§3.4) и НЕ
# трогает исторические пути доставки: autopush и дневной цикл пушат из хост-репо,
# который висит на своей ветке (на 30.07 — `env-setup-v3`, 23 441 коммит от
# `origin/main`) ⇒ база не устанавливается ⇒ поведение прежнее.
# ══════════════════════════════════════════════════════════════════════════════

DIVERGENCE_SAFE = "safe"
DIVERGENCE_DIVERGED = "diverged"
DIVERGENCE_UNMEASURED = "unmeasured"


class DivergenceRefused(RuntimeError):
    """Пуш стёр бы правку, которой нет в нашей базе. Отказ вместо перезаписи."""


def _git_rc(args: list, cwd) -> Optional[int]:
    """Код возврата `git -C <cwd> <args>`; None — git вообще не запустился."""
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args],
                           capture_output=True, timeout=10)
    except Exception:
        return None
    return r.returncode


def _git_bytes(args: list, cwd) -> Optional[bytes]:
    """stdout как БАЙТЫ (`cat-file blob` бинарно-безопасен); None на любом сбое."""
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args],
                           capture_output=True, timeout=10)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def base_version(abs_path, repo_path: str, branch: str = "main") -> tuple:
    """Версия пути в БАЗЕ рабочей копии → ``(state, blob_bytes, reason)``.

    ``state``:
      * ``"measured"``       — база прочитана, ``blob_bytes`` заполнен;
      * ``"absent_in_base"`` — база достоверна, но этого пути в ней НЕТ (новый файл);
      * ``"unmeasured"``     — базу установить нечем (нет git / не рабочая копия /
        HEAD не является предком ветки доставки). Это НЕ «всё в порядке».
    """
    parent = Path(abs_path).parent
    if not parent.exists():
        return "unmeasured", None, f"каталога {parent} нет"
    if _git_out(["rev-parse", "--verify", "HEAD"], parent) is None:
        return "unmeasured", None, "git недоступен или это не рабочая копия git"
    ref = f"refs/remotes/origin/{branch}"
    rc = _git_rc(["merge-base", "--is-ancestor", "HEAD", ref], parent)
    if rc is None:
        return "unmeasured", None, "git не запустился"
    if rc != 0:
        return "unmeasured", None, (
            f"HEAD рабочей копии не является предком {ref} — копия не основана на "
            f"ветке доставки, сравнивать не с чем")
    blob = _git_bytes(["cat-file", "blob", f"HEAD:{repo_path}"], parent)
    if blob is None:
        return "absent_in_base", None, f"пути {repo_path} нет в базовом коммите"
    return "measured", blob, ""


def divergence_verdict(abs_path, repo_path: str, remote_sha: Optional[str],
                       branch: str = "main") -> dict:
    """Что случится с ЧУЖИМИ правками, если запушить наш файл как есть."""
    state, base, reason = base_version(abs_path, repo_path, branch)
    if state == "unmeasured":
        return {"state": DIVERGENCE_UNMEASURED, "reason": reason, "base": None}
    if state == "absent_in_base":
        if remote_sha is None:
            return {"state": DIVERGENCE_SAFE, "base": None,
                    "reason": "файла нет ни в базе, ни на remote — он новый"}
        return {"state": DIVERGENCE_DIVERGED, "base": None,
                "reason": (f"пути нет в базе рабочей копии, но на remote он ЕСТЬ "
                           f"(sha {remote_sha[:8]}) — его завёл кто-то другой")}
    if remote_sha is None:
        # sha=None у get_file_sha значит и «нового файла нет», и «сеть отвалилась»,
        # и «файл удалили» — различить нельзя, поэтому «не измерено», а не «ок».
        return {"state": DIVERGENCE_UNMEASURED, "base": base,
                "reason": "sha файла на remote не прочитан — сравнивать не с чем"}
    base_sha = git_blob_sha(base)
    if base_sha == remote_sha:
        return {"state": DIVERGENCE_SAFE, "base": base,
                "reason": "remote совпадает с базой рабочей копии — терять нечего"}
    return {"state": DIVERGENCE_DIVERGED, "base": base,
            "reason": (f"содержимое {repo_path} на remote изменилось после нашей базы "
                       f"(база {base_sha[:8]} → remote {remote_sha[:8]}): наша копия "
                       f"стёрла бы чужую правку")}


def rebase_append(base: Optional[bytes], local: Optional[bytes],
                  remote: Optional[bytes]) -> Optional[bytes]:
    """Наложить НАШУ добавку на свежий remote. ``None`` — если это не дописывание.

    Дописывание распознаётся побайтово: и наша версия, и версия remote начинаются
    с общей базы. Тогда результат = remote + наш хвост, и обе записи выживают.
    Любая правка в СЕРЕДИНЕ (так меняется `docs/STATE.md`) ломает префикс — и
    функция честно отдаёт ``None``, чтобы вызывающий отказал. Слияния «по смыслу»
    здесь нет и быть не должно (карточка прямо это исключает).

    **Хвост считается от самого длинного ИЗВЕСТНОГО префикса, а не от базы**
    (карточка `agent-task-povtornoe-dopisyvanie-faila-v-odnom-tsik`, цикл #95).
    ``base`` — это git HEAD рабочего дерева, и за цикл он не двигается. Поэтому
    цикл, дописавший файл ВТОРОЙ раз (протокол требует и то и другое: §3.4
    изолированный worktree + «Шаг 3 — обновить память»), получал::

        base = B · remote = B+S1 (наш же первый пуш) · local = B+S1+S2
        tail = local[len(B):] = S1+S2   ⇒   remote+tail = B+S1+S1+S2

    Оба ``startswith(base)`` выполнены ⇒ отказа не было: расхождение считалось
    БЕЗОПАСНЫМ «чистым дописыванием», и пушер печатал ``OK … skipped=0`` о
    результате, которого не проверял. Измерено на `docs/journal/2026-W32.md`
    в цикле #95 (секция уехала на origin дважды).
    """
    if base is None or local is None or remote is None:
        return None
    if not local.startswith(base) or not remote.startswith(base):
        return None

    # Наша версия уже СОДЕРЖИТ всё, что лежит на remote (типовой случай: remote —
    # это наш же первый пуш этого цикла). Доливать нечего и не нужно ничего
    # склеивать: результат — ровно local. Проверка идёт ДО расчёта хвоста, иначе
    # вырожденный случай local == remote дал бы «пустой хвост» ⇒ ложный отказ.
    if local.startswith(remote):
        return local

    tail = local[len(_common_prefix_at_line_boundary(base, local, remote)):]
    if not tail:
        return None
    return remote + tail


def _common_prefix_at_line_boundary(base: bytes, local: bytes, remote: bytes) -> bytes:
    """Общий префикс ``local`` и ``remote``, обрезанный по границе СТРОКИ.

    Никогда не короче ``base`` (оба аргумента с него начинаются) — поэтому в
    худшем случае поведение ровно прежнее: хвост от базы. Длиннее базы он
    становится там, где между нашими двумя пушами дописала ЧУЖАЯ сессия: тогда
    ``remote = B+S1+X``, ``local = B+S1+S2``, общий префикс = ``B+S1``, и на
    remote накладывается только S2 — S1 не дублируется, а X не теряется.

    Обрезка по ``\\n`` обязательна и не косметическая: две РАЗНЫЕ записи легко
    совпадают первыми байтами (``### Цикл #98`` / ``### Цикл #99``), и «умный»
    побайтовый префикс склеил бы их в мусор посреди строки. Границей может быть
    только конец строки; не нашли её — откатываемся к базе (fail-CLOSED).
    """
    limit = min(len(local), len(remote))
    i = len(base)
    while i < limit and local[i] == remote[i]:
        i += 1
    cut = local.rfind(b"\n", len(base), i)
    if cut == -1:
        return base
    return local[:cut + 1]


# ══════════════════════════════════════════════════════════════════════════════
# ЗАПИСЬ, КОТОРАЯ ЕСТЬ НА REMOTE, НЕ ИСЧЕЗАЕТ МОЛЧА
#
# ЗАЧЕМ (карточка `inbox-zhurnal-tsiklov-molcha-teryaet-zapisi-pr`, замер #139):
# страж перезаписи выше отвечает на вопрос «не сотру ли я чужую правку», и
# отвечает честно — но ТОЛЬКО там, где у него есть база (`base_version`). Где
# базы нет, вердикт `DIVERGENCE_UNMEASURED` печатает ноту и пуш ПРОПУСКАЕТ:
# направление выбрано намеренно, чтобы не остановить autopush и дневной цикл,
# которые пушат из хост-репо. Цена этого решения измерена по истории самих
# файлов (проход по `git log`, набор записей на каждом коммите, разность):
#
#   docs/journal/2026-W31.md  3 события,  33 записи
#   docs/journal/2026-W32.md  4 события,  19 записей
#   docs/STATE.md             5 событий, 16 записей
#   ─────────────────────────────────────────────────
#   ИТОГО 12 событий на 277 переходов (4.3%), 68 стёртых записей
#
# Все 12 — ПОСЛЕ того, как страж перезаписи появился (41af9d987, 2026-07-31), и
# ни одно не сопровождалось отказом: пушер печатал `OK`, потому что доставил
# ровно то, что ему дали. Инвариант #16 требует, чтобы обоснование намеренной
# правки теста жило в журнале, — пропавшая запись делает его непроверяемым
# задним числом, а `CLAUDE.md` §4 («не записано — работа НЕ завершена») из
# гарантии превращается в пожелание.
#
# ЧТО ДЕЛАЕМ. Проверка НЕ ТРЕБУЕТ БАЗЫ и потому работает ровно там, где страж
# перезаписи слеп: сравниваем ЗАГОЛОВКИ ЗАПИСЕЙ на remote с теми, что в
# отправляемом содержимом. Запись с remote пропала ⇒ отказ (fail-CLOSED,
# инвариант #2). Осознанное сокращение — `--allow-overwrite`, как и раньше:
# решение остаётся возможным, но перестаёт быть умолчанием.
#
# ГРАНИЦЫ, измеренные а не предположенные:
#   * УРОВЕНЬ ЗАПИСИ, а не любой строки. Подзаголовки (`### Проверка`) — тело
#     записи; на них проверка даёт 9 лишних срабатываний из 155 переходов
#     только по журналам (замерено), а построчная сверка — 88 из 122 на
#     `STATE.md`. Обе отвергнуты замером, а не вкусом.
#   * НЕ ловит удаление ТЕЛА записи: `a3c015f05` снёс 1729 строк `STATE.md`,
#     не тронув ни одного заголовка, и остаётся невидимым. Это честная граница,
#     а не недосмотр: «запись не исчезает» ≠ «содержимое не теряется».
#   * Только объявленные ниже документы-«общие тетради». Всё прочее (код,
#     карточки, `_BOARD.md` — он пересобирается целиком) не трогаем.
#   * ПЕРЕИМЕНОВАНИЕ заголовка — не потеря (уточнение цикла #154 по замеру
#     #150). Если тело записи совпало с remote побайтово, запись на месте, как
#     бы ни изменился её заголовок: отказа нет, но случай НАЗЫВАЕТСЯ нотой.
#     Отказ остаётся за настоящей потерей содержимого —
#     см. `classify_missing_entries`.
#   * Список находок — по ВСЕМ отправляемым файлам, а не до первого сбойного:
#     решение «обходить или нет» принимают по этому списку, и список короче
#     правды опаснее отсутствия списка (см. `build_entries`).
# ══════════════════════════════════════════════════════════════════════════════

#: Документы, которые ДОПИСЫВАЮТ все сессии подряд (протокол §«Шаг 3»).
APPEND_ONLY_DOCS = ("docs/STATE.md",)
APPEND_ONLY_PREFIXES = ("docs/journal/",)

#: Заголовок ЗАПИСИ: `## …` в журнале и блок-цитата `> **…` в `docs/STATE.md`.
ENTRY_HEADER_RE = re.compile(rb"^(?:##[ \t]+\S.*|>[ \t]*\*\*.+)$", re.M)


class EntryLossRefused(DivergenceRefused):
    """Пуш стёр бы запись, которая есть на remote. Отказ вместо тихой потери."""


def is_append_only_doc(repo_path: str) -> bool:
    """Общая тетрадь, у которой запись — единица смысла (а не просто текст)."""
    if repo_path in APPEND_ONLY_DOCS:
        return True
    return (any(repo_path.startswith(p) for p in APPEND_ONLY_PREFIXES)
            and repo_path.endswith(".md"))


# ══════════════════════════════════════════════════════════════════════════════
# ОБЩАЯ ПАМЯТЬ: НЕИЗМЕРИМАЯ БАЗА = ОТКАЗ (решение владельца ADR-070 п.7)
#
# ЗАЧЕМ. Страж перезаписи выше по умолчанию НЕ блокирует `DIVERGENCE_UNMEASURED`
# — и это осознанный выбор: базу можно установить только для копии, основанной
# на ветке доставки, а исторические пути доставки (autopush, дневной цикл,
# кастодиан сайта) пушат из хост-репо. Останавливать их ради неприменимой к ним
# проверки нельзя.
#
# Но у этого выбора есть цена, и она не одинакова для всех файлов. Проверка
# записей (`guard_entry_loss`) закрывает неизмеренный путь лишь ЧАСТИЧНО — по
# своей объявленной границе она ловит исчезновение ЗАГОЛОВКА записи и НЕ ловит
# удаление её ТЕЛА (`a3c015f05` снёс 1729 строк `docs/STATE.md`, не тронув ни
# одного заголовка, и остался невидимым). Для трёх файлов общей памяти этой
# частичной защиты мало: по ним потом судят, что вообще было сделано, а
# `CLAUDE.md` §4 («не записано — работа НЕ завершена») и инвариант #16
# (обоснование правки теста живёт в журнале) опираются на них как на
# доказательство. Стёртая память делает оба непроверяемыми задним числом.
#
# ЧТО ДЕЛАЕМ. Для `docs/STATE.md`, `docs/journal/*.md` и `_BOARD.md` неизмеримая
# база — сама по себе ОТКАЗ (fail-CLOSED, инвариант #2), а не нота. Владелец
# выбрал «точечный» вариант сознательно: **остальное как есть**, поэтому набор
# перечислен поимённо и не расширяется «на всякий случай».
#
# ГРАНИЦЫ, измеренные а не предположенные (замер цикла #151):
#   * Ни один автоматический пушер этих трёх путей не отправляет: `push_v*.sh`,
#     autopush и дневной цикл трогают `CURRENT_STATE.md` (ДРУГОЙ файл, не в
#     наборе), сайт и данные. Пишут в общую память только циклы оркестратора —
#     а они по протоколу §3.4 работают из worktree от `origin/main`, где база
#     измерима и этот отказ невозможен по построению.
#   * Хост-репо на момент правки ТОЖЕ даёт измеримую базу (HEAD — предок
#     `origin/main`), хотя комментарий выше описывает состояние 30.07, когда оно
#     сидело на своей ветке. Проверка от этого не зависит: она смотрит на факт,
#     а не на предположение о том, кто её вызвал.
#   * Набор НАМЕРЕННО шире `APPEND_ONLY_DOCS`: `_BOARD.md` пересобирается
#     целиком, поэтому исчезновение записи для него нормально (проверка записей
#     его не трогает и трогать не должна) — но запушить его поверх чужой доски,
#     не зная базы, всё равно нельзя.
# ══════════════════════════════════════════════════════════════════════════════

#: Общая память проекта: по этим файлам судят, что было сделано.
SHARED_MEMORY_DOCS = ("docs/STATE.md", "nimbalyst-local/tracker/_BOARD.md")
SHARED_MEMORY_PREFIXES = ("docs/journal/",)


class UnmeasuredBaseRefused(DivergenceRefused):
    """Общая память, а базу пуша установить нечем. Отказ вместо слепой записи."""


def is_shared_memory_doc(repo_path: str) -> bool:
    """Файл общей памяти (ADR-070 п.7). Строго по списку — «остальное как есть»."""
    if repo_path in SHARED_MEMORY_DOCS:
        return True
    return (any(repo_path.startswith(p) for p in SHARED_MEMORY_PREFIXES)
            and repo_path.endswith(".md"))


def entry_headers(blob: Optional[bytes]) -> list:
    """Заголовки записей в порядке появления. ``None`` → пустой список.

    Кратность значима: одинаковые заголовки в разных записях встречаются, и
    пропажа ОДНОГО из двух — тоже пропажа записи. Поэтому сравнение идёт
    мультимножеством, а не множеством.
    """
    if not blob:
        return []
    return [m.group(0).strip() for m in ENTRY_HEADER_RE.finditer(blob)]


def entry_blocks(blob: Optional[bytes]) -> list:
    """``[(заголовок, тело)]`` в порядке появления; тело — до следующего заголовка.

    Нужно затем, чтобы отличить ПЕРЕИМЕНОВАНИЕ записи от её ИСЧЕЗНОВЕНИЯ: по
    одному заголовку эти два случая неразличимы, а последствия у них разные.
    Тело нормализуется ``strip()`` — пустые строки вокруг записи её содержимым
    не являются и прятать потерю не могут.
    """
    if not blob:
        return []
    heads = list(ENTRY_HEADER_RE.finditer(blob))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(blob)
        out.append((m.group(0).strip(), blob[m.end():end].strip()))
    return out


def classify_missing_entries(remote: Optional[bytes], ours: Optional[bytes]) -> tuple:
    """``(потеряно, переименовано)`` — записи remote, чьего заголовка у нас нет.

    Замер цикла #150: доставка отказала на двух строках `2026-W29.md`, которые
    НЕ исчезали — цикл дописал к их заголовкам номер цикла, а тела совпали с
    remote побайтово. Страж сравнивал только ТЕКСТ заголовка, поэтому
    переименование читалось как потеря.

    Две фазы, и порядок между ними значим:

    1. гасим по ЗАГОЛОВКУ, с кратностью (два одинаковых заголовка и один
       уцелевший — это потеря, и она обязана остаться потерей);
    2. у оставшихся смотрим ТЕЛО: если ровно то же тело лежит под другим,
       ещё не сопоставленным заголовком — запись на месте, это переименование.
       Пустое тело в кандидаты не берётся: оно совпало бы с чем угодно.

    Это НЕ ослабление проверки: отказ по-прежнему наступает всегда, когда
    исчезает содержимое записи. Сужается ровно тот случай, где содержимое
    доказанно на месте, — и он всё равно НАЗЫВАЕТСЯ (нота, а не молчание).
    """
    theirs = entry_blocks(remote)
    unmatched_mine = entry_blocks(ours)

    only_on_remote = []
    for header, body in theirs:
        for j, (h2, _) in enumerate(unmatched_mine):
            if h2 == header:
                unmatched_mine.pop(j)      # кратность: гасим ровно одно вхождение
                break
        else:
            only_on_remote.append((header, body))

    lost, renamed = [], []
    for header, body in only_on_remote:
        match = None
        if body:
            for j, (h2, b2) in enumerate(unmatched_mine):
                if b2 == body:
                    match = h2
                    unmatched_mine.pop(j)
                    break
        if match is None:
            lost.append(header)
        else:
            renamed.append((header, match))
    return lost, renamed


def dropped_entries(remote: Optional[bytes], ours: Optional[bytes]) -> list:
    """Записи, которые есть на remote и которых НЕ будет после нашего пуша.

    Переименование заголовка при побайтово уцелевшем теле сюда НЕ попадает —
    см. :func:`classify_missing_entries`.
    """
    return classify_missing_entries(remote, ours)[0]


def guard_entry_loss(repo_path: str, remote_bytes: Optional[bytes],
                     content_bytes: bytes, remote_sha: Optional[str],
                     allow_overwrite: bool = False) -> str:
    """Отказать, если пуш стирает запись с remote. Возвращает ноту (может быть пустой).

    Порядок проверок — fail-CLOSED:
      * не общая тетрадь / явное `--allow-overwrite` / файла на remote нет → нечего терять;
      * содержимое remote не прочитано, хотя файл там ЕСТЬ → это НЕ «всё в порядке»,
        а неизмеренная потеря: отказ (Contents API молчит про файлы >1 МБ, и
        именно на таком молчании потеря и осталась бы незамеченной).
    """
    if allow_overwrite or not is_append_only_doc(repo_path):
        return ""
    if remote_sha is None:
        return ""                    # файла на remote нет — терять нечего
    if remote_bytes is None:
        raise EntryLossRefused(
            f"{repo_path}: содержимое на remote НЕ ПРОЧИТАНО (sha {remote_sha[:8]} есть), "
            f"а это общая тетрадь — значит нельзя сказать, не стираем ли мы чужую "
            f"запись. Пуш отменён (fail-CLOSED, инвариант #2).\n"
            f"Что делать: повторить (Contents API не отдаёт содержимое файлов >1 МБ); "
            f"осознанная перезапись — `--allow-overwrite`.")

    lost, renamed = classify_missing_entries(remote_bytes, content_bytes)

    # Переименование НАЗЫВАЕТСЯ отдельным классом, а не молчит: тело записи на
    # месте побайтово, терять нечего — но заголовок общей тетради всё-таки
    # изменился, и увидеть это автор доставки обязан.
    renamed_note = ""
    if renamed:
        pairs = "\n".join(
            f"    - {a.decode('utf-8', 'replace')[:70]}  →  {b.decode('utf-8', 'replace')[:70]}"
            for a, b in renamed[:8])
        more_r = f"\n    … и ещё {len(renamed) - 8}" if len(renamed) > 8 else ""
        renamed_note = (f"🔤 {repo_path}: переименовано заголовков — {len(renamed)} "
                        f"(тело каждой записи совпало с remote побайтово, потери нет):\n"
                        f"{pairs}{more_r}")

    if not lost:
        return renamed_note

    shown = "\n".join(f"    - {h.decode('utf-8', 'replace')[:110]}" for h in lost[:8])
    more = f"\n    … и ещё {len(lost) - 8}" if len(lost) > 8 else ""
    tail = f"\n{renamed_note}" if renamed_note else ""
    raise EntryLossRefused(
        f"{repo_path}: пуш стёр бы {len(lost)} запис(ь/и), которые есть на "
        f"remote и которых нет в отправляемом содержимом:\n{shown}{more}\n"
        f"Так за неделю молча пропало 12 раз (замер #139) — пушер печатал OK, "
        f"потому что доставлял ровно то, что ему дали. Пуш отменён (fail-CLOSED).\n"
        f"Что делать: перечитать {repo_path} со свежего origin, перенести свою "
        f"запись на него и запушить снова; осознанное сокращение — `--allow-overwrite`.{tail}")


def guard_overwrite(pat: str, repo: str, branch: str, repo_path: str, abs_path,
                    local_bytes: bytes, remote_sha: Optional[str],
                    allow_overwrite: bool = False,
                    strict_unmeasured: bool = False) -> tuple:
    """``(content_to_push, note)``; :class:`DivergenceRefused` — если пушить нельзя.

    «Не измерено» по умолчанию НЕ блокирует — но и не выдаётся за «всё в порядке»:
    печатается явная строка «расхождение НЕ ИЗМЕРЕНО» с причиной. Направление
    выбрано намеренно и по измерению, а не из осторожности: базу можно установить
    только для копии, основанной на ветке доставки, а исторические пути доставки
    (autopush, дневной цикл, кастодиан сайта) пушат из ХОСТ-репо, который сидит на
    своей ветке. Блокировать их значило бы остановить живую доставку ради проверки,
    которая для них неприменима по построению — это домен владельца, не автономной
    правки. Защита действует там, где база ЕСТЬ, — в worktree протокола (§3.4).

    ``strict_unmeasured=True`` — явный опт-ин вызывающего: «работаю только там, где
    перезапись отслеживается». Ни от какой переменной окружения не зависит, чтобы
    поведение пушера не менялось от того, кто его запустил.
    """
    verdict = divergence_verdict(abs_path, repo_path, remote_sha, branch)
    state = verdict["state"]

    if state == DIVERGENCE_SAFE:
        # remote == база ⇒ содержимое remote у нас уже на руках, сеть не нужна.
        # Проверять всё равно надо: «чужого тут нет» не значит «своего не теряем»
        # (`f35ff96ed` уронил запись `STATE.md` ровно на этом пути).
        note = guard_entry_loss(repo_path, verdict.get("base"), local_bytes, remote_sha,
                                allow_overwrite=allow_overwrite)
        return local_bytes, note

    if state == DIVERGENCE_UNMEASURED:
        note = f"⚠️  расхождение НЕ ИЗМЕРЕНО для {repo_path}: {verdict['reason']}"
        if strict_unmeasured and not allow_overwrite:
            raise DivergenceRefused(
                f"{note}\nВызывающий потребовал измеримой базы (strict_unmeasured): "
                f"без неё перезапись чужой правки не отслеживается. "
                f"Пуш отменён (fail-CLOSED).")
        # ЗДЕСЬ И БЫЛА ДЫРА: базы нет ⇒ раньше уходило как есть. Проверка записей
        # базы не требует — только содержимого remote, и берёт его сама.
        if not allow_overwrite and is_append_only_doc(repo_path) and remote_sha is not None:
            entry_note = guard_entry_loss(repo_path,
                                          get_file_content(pat, repo, repo_path, branch),
                                          local_bytes, remote_sha,
                                          allow_overwrite=allow_overwrite)
            if entry_note:
                note = f"{note}\n{entry_note}"
        # Общая память (ADR-070 п.7). Стоит ПОСЛЕ проверки записей намеренно: обе
        # ведут к отказу, но та называет пропадающие записи поимённо — более
        # полезное сообщение должно побеждать. Сюда доходит то, что она пропустила
        # (потеря ТЕЛА записи — её объявленная граница) и `_BOARD.md`, которого она
        # не касается вовсе.
        if not allow_overwrite and is_shared_memory_doc(repo_path):
            raise UnmeasuredBaseRefused(
                f"{note}\n{repo_path} — общая память проекта, а базу пуша "
                f"установить нечем: сказать, не стираем ли мы чужую запись, "
                f"НЕЧЕМ. Пуш отменён (fail-CLOSED, инвариант #2, решение "
                f"владельца ADR-070 п.7).\n"
                f"Что делать: пушить общую память из рабочей копии, основанной "
                f"на ветке доставки (протокол §3.4 — worktree от `origin/{branch}`), "
                f"перенеся свою запись на свежее содержимое; осознанная "
                f"перезапись — `--allow-overwrite`.")
        return local_bytes, note

    # DIVERGENCE_DIVERGED
    if allow_overwrite:
        return local_bytes, (f"⚠️  ПЕРЕЗАПИСЬ РАЗРЕШЕНА ЯВНО для {repo_path}: "
                             f"{verdict['reason']}")

    remote_bytes = get_file_content(pat, repo, repo_path, branch)
    rebased = rebase_append(verdict.get("base"), local_bytes, remote_bytes)
    if rebased is not None:
        # Пере-база сохраняет remote целиком ПО ПОСТРОЕНИЮ (remote — префикс
        # результата). Проверка здесь бесплатна (remote уже прочитан) и стоит
        # ровно затем, чтобы регрессия `rebase_append` не проехала молча.
        entry_note = guard_entry_loss(repo_path, remote_bytes, rebased, remote_sha,
                                      allow_overwrite=allow_overwrite)
        rebase_note = (f"🔀 пере-база {repo_path}: наша добавка наложена на свежее "
                       f"содержимое remote (обе записи сохранены)")
        return rebased, (f"{rebase_note}\n{entry_note}" if entry_note else rebase_note)

    raise DivergenceRefused(
        f"{verdict['reason']}.\n"
        f"Чистым дописыванием это не разрешается (правка в середине файла либо "
        f"содержимое remote не прочитано), а сливать по смыслу пушер не будет. "
        f"Пуш отменён (fail-CLOSED, инвариант #2).\n"
        f"Что делать: перечитать {repo_path} со свежего `origin/{branch}`, перенести "
        f"свою правку на него и запушить снова; осознанная перезапись — "
        f"`--allow-overwrite`.")


def push_file(pat: str, local_path: str, message: str, repo: str, dry_run: bool = False,
              branch: str = "main", _stale_retries: int = 2,
              allow_overwrite: bool = False) -> dict:
    """Пушит один файл через GitHub Contents API.

    409 stale-sha auto-retry: если параллельный писатель обновил файл между нашим
    get_file_sha и PUT, GitHub вернёт 409 (sha не совпадает с HEAD). Тогда мы
    заново читаем актуальный remote sha и повторяем PUT — до ``_stale_retries`` раз.
    Детерминированно, fail-safe (исчерпали ретраи → честный FAIL).
    """
    import urllib.request
    import urllib.error

    local = Path(local_path)
    # Resolve relative to PROJECT_ROOT if not absolute
    if not local.is_absolute():
        local = PROJECT_ROOT / local
    if not local.exists():
        return {"ok": False, "error": f"Файл не найден: {local_path}", "path": local_path}

    # Путь внутри репо. Fail-CLOSED: не удалось определить → честный FAIL,
    # а НЕ basename в корень репо (см. repo_relative_path).
    try:
        repo_path = repo_relative_path(local)
    except RepoPathError as e:
        return {"ok": False, "error": str(e), "path": local_path}

    local_bytes = local.read_bytes()
    local_blob_sha = git_blob_sha(local_bytes)

    if dry_run:
        sha = get_file_sha(pat, repo, repo_path, branch)
        if sha is not None and sha == local_blob_sha:
            return {"ok": True, "dry_run": True, "path": repo_path, "action": "skip"}
        action = "update" if sha else "create"
        return {"ok": True, "dry_run": True, "path": repo_path, "action": action,
                "divergence": divergence_verdict(local, repo_path, sha, branch)["state"]}

    sha = get_file_sha(pat, repo, repo_path, branch)

    # Idempotency guard (fail-CLOSED): пропускаем PUT, только если remote SHA
    # ТОЧНО совпадает с локальным git-blob-SHA. Любая неопределённость
    # (sha=None из-за сетевой ошибки/нового файла) → пушим как обычно, чтобы
    # реальные изменения никогда не потерялись. Идентичный контент → no-op PUT
    # создаёт пустой коммит в Contents API — именно его мы и устраняем.
    if sha is not None and sha == local_blob_sha:
        return {"ok": True, "skipped": True, "path": repo_path, "sha": sha[:8]}

    # Страж перезаписи: доставка целыми файлами не даёт права стереть чужую
    # правку. Либо пуш безопасен, либо наша добавка ложится на свежий remote,
    # либо честный отказ (см. guard_overwrite).
    try:
        content_bytes, note = guard_overwrite(
            pat, repo, branch, repo_path, local, local_bytes, sha,
            allow_overwrite=allow_overwrite)
    except DivergenceRefused as e:
        return {"ok": False, "error": str(e), "path": repo_path, "diverged": True}
    if note:
        print(f"  {note}")
    content_b64 = base64.b64encode(content_bytes).decode()

    payload: dict = {
        "message": message,
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    url = f"{API_BASE}/repos/{repo}/contents/{repo_path}"
    data_bytes = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data_bytes, method="PUT", headers={
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            # Сверка доставленного: `content.sha` — ответ на НАШУ запись, а не
            # отдельное чтение (см. блок «СВЕРКА ДОСТАВЛЕННОГО»). Ноль лишних
            # запросов, никакой задержки согласованности.
            returned_sha = (result.get("content") or {}).get("sha")
            verdict = verify_blob_delivery(content_bytes, returned_sha, repo_path)
            if verdict["state"] == "mismatch":
                return {"ok": False, "error": verdict["note"], "path": repo_path,
                        "verified": "mismatch"}
            if verdict["state"] == "unmeasured":
                print(f"  {verdict['note']}")
            sha_short = (returned_sha or "")[:8]
            return {"ok": True, "path": repo_path, "sha": sha_short,
                    "verified": verdict["state"]}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code in (429, 403) and "rate limit" in body.lower():
            print(f"  Rate limit — ждём 60с...")
            time.sleep(60)
            return push_file(pat, local_path, message, repo, dry_run, branch,
                             _stale_retries, allow_overwrite)
        # 409 stale-sha: параллельный писатель сдвинул HEAD. Перечитываем свежий
        # remote sha и повторяем PUT (bounded). 422 тоже может означать рассинхрон
        # sha ("does not match") — обрабатываем так же.
        if (e.code == 409 or (e.code == 422 and "sha" in body.lower())) and _stale_retries > 0:
            print(f"  409 stale-sha — перечитываю remote sha и повторяю ({_stale_retries} осталось)...")
            time.sleep(0.5)
            return push_file(pat, local_path, message, repo, dry_run, branch,
                             _stale_retries - 1, allow_overwrite)
        return {"ok": False, "error": f"HTTP {e.code}: {body[:300]}", "path": repo_path}
    except Exception as e:
        return {"ok": False, "error": str(e), "path": repo_path}


# ══════════════════════════════════════════════════════════════════════════════
# Git Data API: N файлов = ОДИН коммит
#
# ЗАЧЕМ (карточка `agent-push-batch-per-file-commits`, найдено циклом #48):
# Contents API принимает по ОДНОМУ файлу за вызов, поэтому набор из N
# взаимозависимых файлов приземлялся N последовательными коммитами — и
# промежуточные состояния дерева НЕСОГЛАСОВАНЫ. Измерено на реальных прогонах
# Actions: из пяти коммитов одного пуша ДВА промежуточных дали `SPA Tests` /
# `SPA CI` = failure (тесты уже на `main`, а правки, которые они проверяют, —
# ещё нет). Регулярный «нормальный» красный main учит игнорировать сигнал
# (инвариант #16), ломает `git bisect` и отправляет следующую сессию искать
# несуществующий дефект (ровно этим занимался цикл #47).
#
# Реализация ОДНА на оба CLI: `push_to_github_batch.py` импортирует эти функции
# отсюда, своих копий не держит (близнец такой же логики — механизм, которым
# цикл #37 оставил CI красным, а цикл #40 разослал файлы в корень репо).
# ══════════════════════════════════════════════════════════════════════════════


class TreeModeError(RuntimeError):
    """Режим (x-бит) файла, уже лежащего на remote, определить не удалось.

    Fail-CLOSED: молча поставить `100644` значит СНЯТЬ исполняемый бит с
    bash-обёртки launchd — агент после такого падает exit-78 (инвариант #12),
    и увидеть это можно только по мёртвому агенту. Лучше отказать в пуше.
    """


def _api(pat: str, method: str, path: str, payload: Optional[dict] = None) -> dict:
    """Один вызов GitHub API. Бросает urllib.error.HTTPError (с телом) на ошибке."""
    url = f"{API_BASE}{path}"
    data_bytes = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data_bytes, method=method, headers={
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


# Чтение ТОЛЬКО ЧТО созданного ref'а может ответить 404: refs-API GitHub
# согласован в конечном счёте, и ветка, созданная секунду назад через
# `POST /git/refs`, ещё не видна точечному `GET /git/ref/heads/<branch>`.
# Наблюдалось дважды на противоположных операциях (цикл #81, карточка
# `agent-checkpoint-tool-crashes-on-first-use`): после POST — 404 на чтении
# созданной ветки; после DELETE — удалённая ветка ещё в списке.
#
# Цена была ровно обратна назначению инструмента: ПЕРВЫЙ чекпойнт сессии падал
# трейсбеком (`push_checkpoint` создаёт ветку, затем `batch_push` читает её
# базу), то есть страховка от смерти сессии не срабатывала именно там, где
# сессии и умирают — между «сделал» и «доставил» (циклы #79 и #80 подряд).
_REF_404_RETRIES = 3
_REF_404_BACKOFF = (0.5, 1.0, 2.0)


def _read_ref_with_404_retry(pat: str, repo: str, branch: str, sleep=None) -> dict:
    """Прочитать ref ветки, пережив «ещё не виден» после создания.

    404 — единственный код, который ретраится (и только он): ветка могла быть
    создана мгновение назад. Ретраев конечное число; исчерпав их, функция
    ПРОБРАСЫВАЕТ тот же `HTTPError` — «не смог прочитать ref» не превращается в
    «ветки нет» и не даёт пушу поехать от неверной базы (fail-CLOSED, инв. #2).
    Любой другой код (403/409/500) и обрыв сети бросаются СРАЗУ, без ретраев:
    недоступность API обязана валить команду.

    Отдельной функцией (а не телом цикла внутри `get_base_ref`), чтобы выход
    был только через `return` или `raise`: вариант с `ref = None` до цикла
    давал mypy `dict | None is not indexable` — то есть тип допускал ровно ту
    «базу из ниоткуда», которую здесь и запрещаем.

    `sleep` инъецируется тестами — сеть и часы в тестах не трогаются.
    """
    _sleep = sleep if sleep is not None else time.sleep
    for attempt in range(_REF_404_RETRIES + 1):
        try:
            return _api(pat, "GET", f"/repos/{repo}/git/ref/heads/{branch}")
        except urllib.error.HTTPError as e:
            if e.code != 404 or attempt == _REF_404_RETRIES:
                raise
            delay = _REF_404_BACKOFF[min(attempt, len(_REF_404_BACKOFF) - 1)]
            print(f"  ref heads/{branch}: HTTP 404 (попытка {attempt + 1}/"
                  f"{_REF_404_RETRIES + 1}) — свежесозданный ref мог быть ещё не "
                  f"виден, повтор через {delay}с")
            _sleep(delay)
    raise AssertionError("недостижимо: цикл выходит только через return или raise")


def get_base_ref(pat: str, repo: str, branch: str, sleep=None) -> tuple:
    """Шаги 1-2: вернуть (base_commit_sha, base_tree_sha)."""
    ref = _read_ref_with_404_retry(pat, repo, branch, sleep)
    base_commit_sha = str(ref["object"]["sha"])
    commit = _api(pat, "GET", f"/repos/{repo}/git/commits/{base_commit_sha}")
    base_tree_sha = str(commit["tree"]["sha"])
    return base_commit_sha, base_tree_sha


def resolve_files(file_args: list) -> list:
    """Преобразовать пути в [(repo_relative_path, abs_path)]. Бросает на отсутствующий файл."""
    resolved = []
    for fa in file_args:
        local = Path(fa)
        if not local.is_absolute():
            local = PROJECT_ROOT / local
        if not local.exists():
            raise RuntimeError(f"Файл не найден: {fa}")
        if not local.is_file():
            raise RuntimeError(f"Не файл (директории не поддерживаются): {fa}")
        try:
            repo_path = repo_relative_path(local)
        except RepoPathError as e:
            raise RuntimeError(str(e))   # fail-CLOSED: весь батч не уезжает
        resolved.append((repo_path, local))
    return resolved


def remote_tree_modes(pat: str, repo: str, tree_sha: str) -> tuple:
    """Карта `путь → режим` ветки. Вернуть (modes, truncated).

    Один рекурсивный GET на всё дерево. GitHub усекает ответ на очень больших
    деревьях и честно помечает это флагом ``truncated`` — тогда карта неполная,
    и ОТСУТСТВИЕ пути в ней уже НЕ значит «файла на remote нет» (см.
    :func:`tree_entry_mode`, который в этом случае отказывает, а не угадывает).
    """
    data = _api(pat, "GET", f"/repos/{repo}/git/trees/{tree_sha}?recursive=1")
    modes = {e["path"]: e["mode"] for e in data.get("tree", [])
             if e.get("type") == "blob" and e.get("path") and e.get("mode")}
    return modes, bool(data.get("truncated"))


def tree_entry_mode(repo_path: str, abs_path: Path, modes: dict, truncated: bool) -> str:
    """Режим записи дерева для файла.

    - файл уже есть на remote → его СОБСТВЕННЫЙ режим (x-бит сохраняется);
    - карта полная и пути в ней нет → файл новый, режим по правилу git:
      исполняемый локально → ``100755``, иначе ``100644``;
    - карта усечена и пути в ней нет → существование НЕ ИЗМЕРЕНО →
      :class:`TreeModeError` (fail-CLOSED, не догадка).
    """
    existing = modes.get(repo_path)
    if existing:
        return str(existing)
    if truncated:
        raise TreeModeError(
            f"дерево ветки пришло усечённым (GitHub `truncated: true`), и для "
            f"{repo_path} режим файла не измерен: если файл на remote исполняемый, "
            f"пуш снял бы x-бит молча. Пуш отменён (fail-CLOSED)."
        )
    return EXEC_MODE if os.access(abs_path, os.X_OK) else BLOB_MODE


def create_blob_from_bytes(pat: str, repo: str, data: bytes) -> str:
    """Шаг 3: создать blob из БАЙТОВ (base64, безопасно для бинарных и текстовых).

    Отдельно от :func:`create_blob`, потому что пере-база дописывания (страж
    перезаписи) отправляет не содержимое файла с диска, а «свежий remote + наш
    хвост»; читать это обратно из файла было бы неоткуда.
    """
    blob = _api(pat, "POST", f"/repos/{repo}/git/blobs",
                {"content": base64.b64encode(data).decode(), "encoding": "base64"})
    # Сверка ЗДЕСЬ, а не после коммита: blob — первое звено цепочки
    # (blob → tree → commit → ref), и расхождение на нём означает, что дерево
    # соберётся из НЕ НАШЕГО содержимого. Ветка ещё не сдвинута ⇒ отказ здесь
    # ничего не оставляет на remote наполовину (fail-CLOSED).
    verdict = verify_blob_delivery(data, blob.get("sha"), "blob")
    if verdict["state"] == "mismatch":
        raise DeliveryUnverified(verdict["note"])
    if verdict["state"] == "unmeasured":
        print(f"  {verdict['note']}")
    return str(blob["sha"])


def create_blob(pat: str, repo: str, abs_path: Path) -> str:
    """Шаг 3: создать blob из файла (base64, безопасно для бинарных и текстовых)."""
    return create_blob_from_bytes(pat, repo, Path(abs_path).read_bytes())


def create_tree(pat: str, repo: str, base_tree_sha: str, entries: list) -> str:
    """Шаг 4: новое дерево = base_tree + по записи на файл."""
    tree = _api(pat, "POST", f"/repos/{repo}/git/trees",
                {"base_tree": base_tree_sha, "tree": entries})
    return str(tree["sha"])


def create_commit(pat: str, repo: str, message: str, tree_sha: str, parent_sha: str) -> str:
    """Шаг 5: один коммит со всеми изменениями."""
    commit = _api(pat, "POST", f"/repos/{repo}/git/commits",
                  {"message": message, "tree": tree_sha, "parents": [parent_sha]})
    return str(commit["sha"])


def update_ref(pat: str, repo: str, branch: str, commit_sha: str, force: bool = False) -> dict:
    """Шаг 6: переместить ветку на новый коммит.

    Ответ PATCH — авторитетное состояние ref'а ПОСЛЕ нашей операции. Если он
    указывает не на наш коммит, ветку увёл кто-то другой, и `OK: 1 коммит …`
    было бы неправдой: файлы на `main` не появились. Сверка здесь замыкает
    цепочку доставки (blob → tree → commit → ref) и стоит ноль запросов.
    """
    ref = _api(pat, "PATCH", f"/repos/{repo}/git/refs/heads/{branch}",
               {"sha": commit_sha, "force": force})
    verdict = verify_sha_delivery(commit_sha, (ref.get("object") or {}).get("sha"),
                                  f"ветка {branch}")
    if verdict["state"] == "mismatch":
        raise DeliveryUnverified(verdict["note"])
    if verdict["state"] == "unmeasured":
        print(f"  {verdict['note']}")
    return ref


def split_unchanged(pat: str, repo: str, branch: str, files: list) -> tuple:
    """Разделить [(repo_path, abs)] на (changed, unchanged) по git-blob-SHA.

    Та же идемпотентность, что у :func:`push_file`, и с тем же направлением
    ошибки: пропускаем ТОЛЬКО при точном совпадении remote sha с локальным
    blob-SHA; любая неопределённость (sha=None — новый файл ИЛИ сетевая
    ошибка) → файл считается изменённым и уезжает. Реальные правки не теряются.

    ``changed`` — тройки ``(repo_path, abs_path, remote_sha)``: sha remote нужен
    стражу перезаписи ниже, и второй раз за ним в сеть ходить незачем
    (``remote_sha`` может быть ``None`` — новый файл либо сбой чтения).
    """
    changed, unchanged = [], []
    for repo_path, abs_path in files:
        local_sha = git_blob_sha(Path(abs_path).read_bytes())
        remote_sha = get_file_sha(pat, repo, repo_path, branch)
        if remote_sha is not None and remote_sha == local_sha:
            unchanged.append((repo_path, abs_path, remote_sha))
        else:
            changed.append((repo_path, abs_path, remote_sha))
    return changed, unchanged


def build_entries(pat: str, repo: str, branch: str, changed: list,
                  modes: dict, truncated: bool, allow_overwrite: bool = False) -> list:
    """``changed`` → записи дерева, каждая через стража перезаписи.

    Отдельной функцией, потому что на ретрае «база сдвинулась» (HTTP 409/422)
    записи надо собрать ЗАНОВО: свежая база могла получить чужую правку ровно в
    наших путях, и повторное использование старых blob'ов молча стёрло бы её —
    тот же дефект, что и в основном пути, только этажом ниже.
    :class:`DivergenceRefused` роняет ВЕСЬ батч (fail-CLOSED, как resolve_files).

    Сначала через стража проходят ВСЕ файлы, и только потом создаются blob'ы.
    Раньше отказ на первом же файле обрывал цикл — и сообщение об отказе, по
    которому человек решает «обходить или нет», перечисляло находки только до
    первого сбойного файла (замер цикла #150: переименование в `2026-W29.md`
    названо, такое же в `2026-W31.md` — нет). Список короче правды хуже, чем
    отсутствие списка: он выглядит полным. Побочно уходят и blob'ы-сироты,
    которые старый порядок успевал создать до отказа.
    """
    guarded, failures = [], []
    for repo_path, abs_path, remote_sha in changed:
        try:
            content, note = guard_overwrite(pat, repo, branch, repo_path, abs_path,
                                            Path(abs_path).read_bytes(), remote_sha,
                                            allow_overwrite=allow_overwrite)
        except DivergenceRefused as e:
            failures.append((repo_path, e))
            continue
        guarded.append((repo_path, abs_path, content, note))

    if len(failures) == 1:
        raise failures[0][1]          # один файл — сообщение стража дословно
    if failures:
        joined = "\n\n".join(f"[{i}/{len(failures)}] {e}"
                             for i, (_, e) in enumerate(failures, 1))
        cls = type(failures[0][1])
        if any(type(e) is not cls for _, e in failures):
            cls = DivergenceRefused   # разные причины — общий, не самый узкий класс
        raise cls(
            f"пуш отменён целиком: файлов с находкой — {len(failures)} из "
            f"{len(changed)} ({', '.join(p for p, _ in failures)}). Батч — один "
            f"коммит, поэтому решение принимается по ПОЛНОМУ списку:\n\n{joined}")

    entries = []
    for repo_path, abs_path, content, note in guarded:
        mode = tree_entry_mode(repo_path, abs_path, modes, truncated)
        if note:
            print(f"  {note}")
        blob_sha = create_blob_from_bytes(pat, repo, content)
        print(f"  blob {blob_sha[:8]}  {repo_path}"
              f"{'  (exec)' if mode == EXEC_MODE else ''}")
        entries.append({"path": repo_path, "mode": mode, "type": "blob", "sha": blob_sha})
    return entries


def batch_push(pat: str, file_args: list, message: str, repo: str, branch: str,
               dry_run: bool = False, allow_overwrite: bool = False) -> dict:
    """Собрать N файлов в ОДИН коммит через Git Data API.

    Порядок: разрешить пути (fail-CLOSED) → отсеять неизменённые → страж
    перезаписи → blobs → tree (с сохранением режимов) → commit → move ref.
    Ничего не изменилось → коммита НЕТ вовсе (пустые коммиты не создаются).
    """
    files = resolve_files(file_args)

    # Шаги 1-2: база
    base_commit_sha, base_tree_sha = get_base_ref(pat, repo, branch)
    print(f"  base commit: {base_commit_sha[:8]}  base tree: {base_tree_sha[:8]}")

    if dry_run:
        print(f"DRY RUN — закоммитил бы {len(files)} файл(ов) ОДНИМ коммитом:")
        for repo_path, _ in files:
            print(f"    + {repo_path}")
        return {"ok": True, "dry_run": True, "count": len(files),
                "base_commit": base_commit_sha}

    changed, unchanged = split_unchanged(pat, repo, branch, files)
    for repo_path, _, remote_sha in unchanged:
        print(f"  SKIP {repo_path} (unchanged, sha: {remote_sha[:8]})")
    if not changed:
        print("  всё содержимое уже на remote — коммит не создаётся")
        return {"ok": True, "count": 0, "commit": None, "skipped": len(unchanged),
                "files": [], "skipped_files": [p for p, _, _ in unchanged]}

    modes, truncated = remote_tree_modes(pat, repo, base_tree_sha)

    # Шаг 3: blobs (+ режим существующего файла сохраняется как есть,
    # + страж перезаписи: чужая правка не стирается молча)
    entries = build_entries(pat, repo, branch, changed, modes, truncated, allow_overwrite)

    # Шаг 4: tree
    new_tree_sha = create_tree(pat, repo, base_tree_sha, entries)
    print(f"  tree {new_tree_sha[:8]}")

    # Шаг 5: commit
    new_commit_sha = create_commit(pat, repo, message, new_tree_sha, base_commit_sha)
    print(f"  commit {new_commit_sha[:8]}")

    # Шаг 6: move ref, с одним ретраем на устаревшую базу.
    # Коды: 409 (conflict) И 422 — GitHub отвечает именно 422 «Update is not a
    # fast forward», когда параллельный писатель сдвинул ветку между нашим
    # чтением базы и PATCH (в этом репо такой писатель есть: autopush + дневной
    # цикл). Ветка только на 409 не срабатывала бы на реальном коде ошибки.
    try:
        update_ref(pat, repo, branch, new_commit_sha)
    except urllib.error.HTTPError as e:
        if e.code in (409, 422):
            body = e.read().decode(errors="replace")
            print(f"  HTTP {e.code} stale ref: {body[:200]} — пересобираю на свежей базе...")
            # Пересобираем коммит поверх свежего HEAD (база сдвинулась). Режимы
            # перечитываем на СВЕЖЕМ дереве: параллельный писатель мог менять и их.
            fresh_base_commit, fresh_base_tree = get_base_ref(pat, repo, branch)
            fresh_modes, fresh_truncated = remote_tree_modes(pat, repo, fresh_base_tree)
            # Содержимое пересобираем ТОЖЕ: параллельный писатель мог тронуть
            # наши пути, и старые blob'ы стёрли бы его правку (страж внутри).
            fresh_changed = [(rp, ap, get_file_sha(pat, repo, rp, branch))
                             for rp, ap, _ in changed]
            entries = build_entries(pat, repo, branch, fresh_changed,
                                    fresh_modes, fresh_truncated, allow_overwrite)
            new_tree_sha = create_tree(pat, repo, fresh_base_tree, entries)
            new_commit_sha = create_commit(pat, repo, message, new_tree_sha, fresh_base_commit)
            print(f"  recommit {new_commit_sha[:8]} (parent {fresh_base_commit[:8]})")
            update_ref(pat, repo, branch, new_commit_sha)
        else:
            raise

    return {"ok": True, "count": len(changed), "commit": new_commit_sha,
            "tree": new_tree_sha, "skipped": len(unchanged),
            "files": [p for p, _, _ in changed],
            "skipped_files": [p for p, _, _ in unchanged]}


ADR_INTERLOCK_EXIT = 7


class AdrNumberCollision(Exception):
    """Набор доставки берёт номер ADR, который уже занят другим решением."""


def enforce_adr_numbers(all_files, allow: bool = False,
                        runner_file: Optional[str] = None) -> bool:
    """Отказать, если уезжающие решения сталкиваются номерами. ОДНА реализация на ВСЕ CLI.

    Возвращает True, если интерлок отработал и претензий нет; False — если в наборе
    решений нет вовсе (сторожу нечего сказать). Бросает :class:`AdrNumberCollision`
    при находке; ``allow=True`` — осознанное продолжение (печатается, не молчит).

    **Почему функция, а не блок в `main()`.** До 2026-08-27 интерлок жил строками ВНУТРИ
    `push_to_github.py::main()`, а `push_to_github_batch.py::main()` — drop-in CLI на ту же
    `batch_push`, под которым стоит `safe_site_push.py`, — этих строк не имел. Замер
    (сухой прогон, один и тот же набор, origin/main `48c26e30f`): корневой CLI даёт
    ОТКАЗ rc=7, batch-CLI печатает «DRY OK: 1 файл попал бы в 1 коммит» и rc=0. Через
    эту дверь 26.08 и уехал второй `ADR-145`: `ADR-145-pr-ci-liveness-guard` приземлился
    в 20:35:47Z, `ADR-145-orchestrator-two-concurrent-cycles` — в 23:15:36Z, и с этого
    момента `main` красный (`test_adr_number_allocator.py`, два падения).

    Файл `push_to_github_batch.py` в собственной шапке объясняет, что реализация доставки
    у обоих CLI ОДНА, «поэтому x-бит и идемпотентность нельзя починить в одном пушере и
    забыть в другом». Ровно это и произошло — с проверкой, а не с доставкой: правило
    соблюдали для функций и не соблюдали для интерлоков. Поэтому здесь не «добавлена
    вторая копия блока», а вынесена одна реализация, и обе двери зовут её.

    Отбор `docs/decisions/ADR-` — ТРИГГЕР (пуш без решений интерлок не трогает), а порция
    сторожу отдаётся полная: см. :func:`adr_interlock_payload`.
    """
    adr = [f for f in all_files
           if "docs/decisions/ADR-" in str(f).replace("\\", "/")]
    if not adr:
        return False

    base = os.path.dirname(os.path.abspath(runner_file or __file__))
    guard = os.path.join(base, "scripts", "adr_number.py")
    if not os.path.isfile(guard):
        msg = (f"ОТКАЗ (номера ADR): сторож {guard} не найден — столкновение номеров "
               f"НЕ измерено, а решения в наборе есть (fail-CLOSED). "
               f"Осознанно продолжить: --allow-adr-collision.")
        if allow:
            print(msg + "\n(продолжаю: столкновение номеров разрешено явно)", file=sys.stderr)
            return True
        print(msg, file=sys.stderr)
        raise AdrNumberCollision(msg)

    rc = subprocess.run([sys.executable, guard, "check",
                         "--files", *adr_interlock_payload(all_files)]).returncode
    if rc == 0:
        return True

    msg = (f"ОТКАЗ (номера ADR, rc={rc}): набор не доставлен. Свободный номер — "
           f"`python3 scripts/adr_number.py next`; осознанно продолжить — "
           f"--allow-adr-collision (или SPA_PUSH_ALLOW_ADR_COLLISION=1).")
    if allow:
        print(msg + "\n(продолжаю: столкновение номеров разрешено явно)", file=sys.stderr)
        return True
    print(msg, file=sys.stderr)
    raise AdrNumberCollision(msg)


OWNER_CHOICE_INTERLOCK_EXIT = 8


class OwnerChoiceUnattributed(Exception):
    """Набор доставки пишет ответ владельца, под которым никто не подписан."""


def enforce_owner_choice_authorship(all_files, allow: bool = False,
                                    runner_file: Optional[str] = None) -> bool:
    """Отказать, если пуш ставит ``owner_choice`` без единого признака авторства.

    Возвращает True — интерлок отработал и претензий нет; False — карточек в наборе нет
    вовсе (сторожу нечего сказать). Бросает :class:`OwnerChoiceUnattributed` при находке;
    ``allow=True`` — осознанное продолжение (печатается, не молчит).

    **Зачем именно ЗДЕСЬ (цикл #439, карточка `inbox-agent-mozhet-napisat-owner-choice-otvet`).**
    ``owner_choice`` — запись ОТВЕТА ВЛАДЕЛЬЦА, и до сих пор написать в неё мог кто угодно.
    2026-08-29 сессия одним коммитом (``765363a8e``) поставила ``status: ingested`` и
    ``owner_choice: "2"`` карточке, которая стояла в ``needs-owner`` с пустым полем —
    владелец ответил кнопкой на 6 ч 20 мин ПОЗЖЕ и ответил **1**. Проза того же коммита
    говорит «Выбран вариант 1». Дальше обязательный шаг 0-офис прогон за прогоном звал
    человека разрешить спор, которого не было.

    **Двери посчитаны, а не выбраны.** В рантайме поле пишет ровно один модуль —
    ``spa_core/owner_queue/owner_answer.py``; ``queue.set_status`` трогает только строку
    ``status:``, остальные упоминания — чтение. Заслон на API был бы сторожем у двери, в
    которую никто не ходит. Авария прошла через ПУШ, значит проверка стоит на пуше.

    **Реализация одна, дверей две** — как у интерлока номеров ADR (см.
    :func:`enforce_adr_numbers`): ``push_to_github_batch.py`` зовёт эту же функцию, потому
    что 26.08 вторая дверь уже пропустила то, что первая отклоняла.

    Отбор карточек — ТРИГГЕР (пуш без карточек интерлок не будит), но порция сторожу
    отдаётся ПОЛНАЯ: тот же довод, что у :func:`adr_interlock_payload` — фильтровать
    вход за сторожа значит однажды скрыть от него нужный файл.
    """
    cards = [f for f in all_files
             if "nimbalyst-local/tracker/" in str(f).replace("\\", "/")
             and str(f).endswith(".md")]
    if not cards:
        return False

    base = os.path.dirname(os.path.abspath(runner_file or __file__))
    guard = os.path.join(base, "scripts", "check_owner_choice_authorship.py")
    if not os.path.isfile(guard):
        msg = (f"ОТКАЗ (запись ответа владельца): сторож {guard} не найден — подделку "
               f"записи измерить нечем, а карточки в наборе есть (fail-CLOSED). "
               f"Осознанно продолжить: --allow-owner-choice-write.")
        if allow:
            print(msg + "\n(продолжаю: запись owner_choice разрешена явно)", file=sys.stderr)
            return True
        print(msg, file=sys.stderr)
        raise OwnerChoiceUnattributed(msg)

    rc = subprocess.run([sys.executable, guard, "--root", base,
                         "--files", *[str(f) for f in all_files]]).returncode
    if rc == 0:
        return True

    msg = (f"ОТКАЗ (запись ответа владельца, rc={rc}): набор не доставлен. Ответ владельца "
           f"пишет ТОЛЬКО владелец — кнопкой, через "
           f"`owner_answer.record_owner_answer` (инвариант #14). Безымянное значение на "
           f"origin чинится названным маршрутом "
           f"(`spa_core/owner_queue/owner_answer.repair_unattributed_choice`), а не правкой "
           f"файла руками; осознанно продолжить — --allow-owner-choice-write "
           f"(или SPA_PUSH_ALLOW_OWNER_CHOICE_WRITE=1).")
    if allow:
        print(msg + "\n(продолжаю: запись owner_choice разрешена явно)", file=sys.stderr)
        return True
    print(msg, file=sys.stderr)
    raise OwnerChoiceUnattributed(msg)


def adr_interlock_payload(all_files):
    """Что именно ПОКАЗАТЬ сторожу номеров ADR: ВЕСЬ набор доставки, а не одни решения.

    Отбор `docs/decisions/ADR-*` — это ТРИГГЕР («есть ли в наборе решения»), и он остаётся
    узким: пуш без решений интерлок не трогает. А вот ПОРЦИЯ, отдаваемая сторожу, обязана
    быть полной, потому что вопрос сторожа — «что будет на origin ПОСЛЕ этого пуша», и
    ответ на него зависит от файлов, решениями не являющихся. Прежде всего от
    `docs/decisions/INDEX.md`: он уезжает тем же пушем, но под фильтр не подходил, сторож
    его не видел и читал реестр С ORIGIN — где строки нового решения ещё нет по построению.

    Замер 09.08 (карточка `inbox-strazh-adr-nomerov-lozhno-krasneet-ne-vi`): честная пара
    (ADR-078 + INDEX.md) получала «в INDEX.md нет ни одной строки ADR-078» и rc=7, хотя
    строка есть; ПРЯМОЙ вызов сторожа с той же парой давал 0 находок. Сессия обошла отказ
    флагом — а сторож, который краснеет на верную работу, обходят каждый раз, и тогда он не
    поймает настоящее столкновение (`.claude/rules/deployment.md`).

    Гипотеза карточки (сторожу передают АБСОЛЮТНЫЕ пути, и сравнение с `INDEX_REL` не
    срабатывает) замером ОПРОВЕРГНУТА: `check_push` приводит пути к relpath от корня, и с
    абсолютной парой он зелёный. Дефект был не в сторо́же, а в проводке к нему.

    Сам сторож к лишним файлам готов: набор без решений он возвращает пустым (`check_push`
    → `([], [])`), поэтому полная порция ничего не расширяет — она лишь перестаёт скрывать.
    """
    return [str(f) for f in all_files]


def main():
    parser = argparse.ArgumentParser(
        description="Пуш файлов в GitHub без hardcoded PAT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Новый стиль: positional file args
    parser.add_argument("files_pos", nargs="*", metavar="FILE", help="Файлы для пуша (positional)")
    # Старый стиль
    parser.add_argument("--file", help="Один файл (старый стиль)")
    parser.add_argument("--files", nargs="+", help="Несколько файлов (старый стиль)")
    # Общие опции
    parser.add_argument("--message", "-m", default=None, help="Commit message (авто-генерируется если не указан)")
    parser.add_argument("--repo", default=REPO, help=f"Репо (default: {REPO})")
    parser.add_argument("--branch", default="main", help="Целевая ветка (default: main)")
    parser.add_argument("--dry-run", action="store_true", help="Проверить без пуша")
    parser.add_argument("--pat", help="GitHub PAT (переопределяет Keychain/env/файл)")
    parser.add_argument("--allow-overwrite", action="store_true",
                        help="ОСОЗНАННО стереть правку, появившуюся на remote после нашей базы "
                             "(по умолчанию такой пуш отклоняется)")
    parser.add_argument("--allow-toolchain-mismatch", action="store_true",
                        help="ОСОЗНАННО пушить инструментом, который разошёлся с копией в дереве "
                             "отправляемых файлов (по умолчанию такой пуш отклоняется)")
    parser.add_argument("--allow-owner-choice-write", action="store_true",
                        help="ОСОЗНАННО доставить карточку, ставящую owner_choice без единого "
                             "признака авторства (по умолчанию такой пуш отклоняется)")
    parser.add_argument("--allow-adr-collision", action="store_true",
                        help="ОСОЗНАННО доставить решение под номером, уже занятым на origin, "
                             "или вне реестра INDEX.md (по умолчанию такой пуш отклоняется)")
    args = parser.parse_args()

    allow_overwrite = bool(args.allow_overwrite) or \
        os.environ.get("SPA_PUSH_ALLOW_OVERWRITE") == "1"
    allow_toolchain = bool(args.allow_toolchain_mismatch) or \
        os.environ.get("SPA_PUSH_ALLOW_TOOLCHAIN_MISMATCH") == "1"
    allow_adr = bool(args.allow_adr_collision) or \
        os.environ.get("SPA_PUSH_ALLOW_ADR_COLLISION") == "1"
    allow_owner_choice = bool(args.allow_owner_choice_write) or \
        os.environ.get("SPA_PUSH_ALLOW_OWNER_CHOICE_WRITE") == "1"

    # Собираем все файлы из всех источников
    all_files: list = []
    if args.files_pos:
        all_files.extend(args.files_pos)
    if args.file:
        all_files.append(args.file)
    if args.files:
        all_files.extend(args.files)

    if not all_files:
        parser.error("Укажи файлы (positional) или --file / --files")

    # Авто-сообщение если не указано
    message = args.message or f"chore: push {len(all_files)} file(s) via push_to_github.py"

    # ── СВЕРКА ИНСТРУМЕНТА ДОСТАВКИ — ДО owner-gate и до сети ────────────────
    # Стоит первой намеренно: owner-gate ниже зовёт `check_owner_gate.py`,
    # лежащий РЯДОМ с запущенным пушером, поэтому устаревший инструмент — это
    # ещё и устаревший гейт. Проверка идёт и в `--dry-run`: превью обязано
    # показывать тот же отказ, что и настоящий пуш.
    try:
        enforce_delivery_toolchain(all_files, allow=allow_toolchain)
    except ToolchainMismatch:
        sys.exit(5)

    # ── ИНТЕРЛОК НОМЕРОВ ADR — до сети, для ЛЮБОГО контекста ─────────────────────
    # Номер решения выбирается взглядом на каталог в НАЧАЛЕ работы, а приземляется через
    # час-два: 2026-08-08 две пары сессий столкнулись на ADR-073 и ADR-076 за один день.
    # Единственный момент, когда занятость номера ещё можно измерить и уже поздно не стало,
    # — этот. Здесь же ловится «решение уехало вне реестра»: сейчас это краснит main тестом
    # test_live_registry_of_decisions_is_intact уже ПОСЛЕ приземления, то есть по чужим следам.
    # Гейт судит ТОЛЬКО уезжающие решения (пуш без docs/decisions/ его не замечает), поэтому
    # предсуществующий дубль ADR-067 не запирает посторонние доставки. Не привязан к
    # SPA_AUTONOMOUS: столкновение номеров — объективное измерение, а не суждение владельца,
    # и attended-сессии сталкивались ровно так же.
    # Реализация — ОДНА (`enforce_adr_numbers`), её же зовёт push_to_github_batch.py:
    # блок строками жил здесь и только здесь, а вторая дверь пропускала столкновения.
    try:
        enforce_adr_numbers(all_files, allow=allow_adr)
    except AdrNumberCollision:
        sys.exit(ADR_INTERLOCK_EXIT)

    # ── ИНТЕРЛОК ЗАПИСИ ОТВЕТА ВЛАДЕЛЬЦА — до сети, для ЛЮБОГО контекста ─────────
    # `owner_choice` — запись ОТВЕТА ВЛАДЕЛЬЦА, и до цикла #439 написать в неё мог кто
    # угодно: 2026-08-29 коммит 765363a8e поставил `owner_choice: "2"` карточке, где
    # владелец ещё не отвечал (он ответил кнопкой 1 на 6 ч 20 мин позже). Единственная
    # дверь, через которую ручная правка попадает на origin, — этот пуш. Не привязан к
    # SPA_AUTONOMOUS: подпись именем владельца одинаково неверна в любом контексте, и
    # аварию совершила attended-сессия. Реализация ОДНА, её же зовёт batch-CLI.
    try:
        enforce_owner_choice_authorship(all_files, allow=allow_owner_choice)
    except OwnerChoiceUnattributed:
        sys.exit(OWNER_CHOICE_INTERLOCK_EXIT)

    # ── OWNER-GATE INTERLOCK (ADR-OWN-2026-07) — autonomous context ONLY ──────────
    # In the autonomous orchestrator (SPA_AUTONOMOUS=1) any push touching landing/ MUST
    # have passed the owner-gate guard via scripts/safe_site_push.py (which sets
    # SPA_SITE_PUSH_VERIFIED=1). If not, re-run the guard here and FAIL CLOSED. Attended
    # sessions and the deterministic custodian run WITHOUT SPA_AUTONOMOUS → unaffected.
    if (not args.dry_run and os.environ.get("SPA_AUTONOMOUS") == "1"
            and os.environ.get("SPA_SITE_PUSH_VERIFIED") != "1"):
        _site = [f for f in all_files if "landing/" in str(f).replace("\\", "/")]
        if _site:
            _guard = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "scripts", "check_owner_gate.py")
            _rc = subprocess.run([sys.executable, _guard, "--diff-mode", "files",
                                  "--files", *_site, "--commit-message", message]).returncode
            if _rc != 0:
                print(f"BLOCKED (owner-gate rc={_rc}): autonomous site push must go through "
                      f"scripts/safe_site_push.py → owner card. Not pushing.", file=sys.stderr)
                sys.exit(3)

    # PAT
    if args.pat and args.pat.strip():
        pat = args.pat.strip()
    else:
        try:
            pat = get_pat()
        except RuntimeError as e:
            print(str(e))
            sys.exit(2)

    if args.dry_run:
        print(f"DRY RUN — репо: {args.repo}, ветка: {args.branch}, файлов: {len(all_files)}")
        if len(all_files) > 1:
            print("  (реальный пуш уложил бы изменённые файлы в ОДИН коммит)")
    else:
        print(f"Пушу {len(all_files)} файл(ов) в {args.repo} ({args.branch})...")

    # ── НАБОР ФАЙЛОВ = ОДИН КОММИТ ───────────────────────────────────────────
    # Contents API берёт по одному файлу за вызов ⇒ N взаимозависимых файлов
    # приземлялись N коммитами, и промежуточные состояния `main` были красными
    # (измерено на реальных прогонах Actions, цикл #48). Набор уезжает атомарно.
    # Одиночный файл — прежним путём: один PUT = один коммит, менять нечего.
    # Отката «дошлю по одному» НЕТ по требованию карточки: Git Data API
    # недоступен → честный отказ, а не тихий возврат к рваной доставке.
    if len(all_files) > 1 and not args.dry_run:
        try:
            result = batch_push(pat, all_files, message, args.repo, args.branch,
                                allow_overwrite=allow_overwrite)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            print(f"\nFAIL HTTP {e.code}: {body[:500]}")
            print("Файлы НЕ досылались по одному: рваный набор на main — то, "
                  "что этот путь и устраняет (fail-CLOSED).", file=sys.stderr)
            sys.exit(1)
        except DivergenceRefused as e:
            print(f"\nОТКАЗ (страж перезаписи): {e}", file=sys.stderr)
            sys.exit(4)
        except DeliveryUnverified as e:
            # Отдельно от общего FAIL: это не «не доставили», а «доставили НЕ ТО».
            # Следующий шаг — смотреть remote, а не повторять пуш вслепую.
            print(f"\nОТКАЗ (сверка доставленного): {e}", file=sys.stderr)
            sys.exit(6)
        except Exception as e:
            print(f"\nFAIL: {e}")
            print("Файлы НЕ досылались по одному: рваный набор на main — то, "
                  "что этот путь и устраняет (fail-CLOSED).", file=sys.stderr)
            sys.exit(1)
        if result["count"] == 0:
            print(f"\nOK: {result['skipped']} файл(ов) уже на remote — коммита не потребовалось")
        else:
            print(f"\nOK: 1 коммит {result['commit'][:8]} — {result['count']} файл(ов) "
                  f"(skipped={result['skipped']})")
        sys.exit(0)

    results = []
    for f in all_files:
        r = push_file(pat, f, message, args.repo, dry_run=args.dry_run, branch=args.branch,
                      allow_overwrite=allow_overwrite)
        results.append(r)
        if r.get("ok"):
            if r.get("dry_run"):
                print(f"  {r['path']} → {r['action']}")
            elif r.get("skipped"):
                print(f"  SKIP {r['path']} (unchanged, sha: {r.get('sha', '?')})")
            else:
                # «сверено» видно в строке файла, а «не измерено» — не молчание:
                # OK без пометки означает, что remote подтвердил наши байты.
                mark = "" if r.get("verified") == "match" else "  [сверка НЕ ИЗМЕРЕНА]"
                print(f"  OK {r['path']} (sha: {r.get('sha', '?')}){mark}")
        else:
            print(f"  FAIL {r.get('path', f)}: {r.get('error', '?')}")
        time.sleep(0.3)  # avoid rate limit

    failed = [r for r in results if not r.get("ok")]
    skipped = [r for r in results if r.get("ok") and r.get("skipped")]
    pushed = [r for r in results if r.get("ok") and not r.get("skipped") and not r.get("dry_run")]
    if failed:
        print(f"\nFAIL: {len(failed)}/{len(results)}")
        sys.exit(1)
    else:
        # Итог не имеет права быть «зелёнее» замеров: если хоть у одного файла
        # сверку сделать не удалось, это стоит в той же строке, что и `OK`.
        unverified = [r for r in pushed if r.get("verified") != "match"]
        tail = f", сверка НЕ ИЗМЕРЕНА у {len(unverified)}" if unverified else ""
        print(f"\nOK: {len(results)} файл(ов) (pushed={len(pushed)}, "
              f"skipped={len(skipped)}{tail})")
        sys.exit(0)


if __name__ == "__main__":
    main()
