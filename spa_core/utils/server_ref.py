"""Значение удалённой ветки — спросить у СЕРВЕРА и закрепить sha (ADR-361/362, инв. #17).

ЗАЧЕМ. `refs/remotes/origin/main` — обычная локальная ссылка: она хранит значение
последнего ЧУЖОГО `fetch` и не хранит ни возраста, ни провенанса (ADR-361). Python-зов
`git show origin/main:<путь>` поэтому отвечает о том, что было на сервере когда-то, и
выдаёт это за ответ о сервере сейчас. На девятидневном кэше (максимум, замеренный
ADR-361 по reflog хоста) удаление, уехавшее на origin позавчера, выглядит
«недоставленным», а функция, исчезнувшая вчера, — «на месте».

ФОРМА ОТВЕТА — одна на все читатели:

1. ``git ls-remote --exit-code <удалённый> refs/heads/<ветка>`` — значение спрашивается у
   сервера, кэш не читается вовсе (``ls-remote`` ничего не пишет и ничего локального не
   читает);
2. полученный sha ЗАКРЕПЛЯЕТСЯ: если объекта коммита нет локально, он добирается
   ``git fetch <удалённый> refs/heads/<ветка>``; код возврата `fetch` проверяется, и
   после него объект проверяется ещё раз (``cat-file -e``);
3. все дальнейшие чтения идут ПО ЭТОМУ sha, а не по имени ссылки. Сервер, ушедший
   вперёд между шагами 1 и 3, не делает чтения рваным: читается ровно то состояние,
   которое сервер назвал в шаге 1, и его sha печатается рядом с ответом.

ТРИ ИСХОДА (инв. #17). ``PinnedRef.sha`` — закреплённый sha; ``None`` — значение
НЕ УСТАНОВЛЕНО, и ``reason`` называет почему (сеть, нет удалённого, ветки нет на
сервере, объект не добирается). Пустая строка и «прочитаем кэш на всякий случай»
не возвращаются никогда: устаревшая ссылка не есть ответ сервера.

Ссылка, которая НЕ является remote-tracking (sha, ``HEAD``, локальная ветка), не кэш
чужого `fetch`: она разрешается локально (``rev-parse --verify``) и помечается
``source="local"`` — сцены и вызывающие, передающие явный sha, работают как прежде.

ОДИН ОТЧЁТ — ОДИН sha (стоимость и согласованность). Отчёт, который судит много
элементов (проход ``audit()`` по карточкам, сводка §49, лента Director OS), обязан
судить их ОДНИМ значением сервера: иначе сервер, сдвинувшийся посреди отчёта, делает
его рваным (первая карточка судится старым sha, вторая — новым), а цена растёт как
``ls-remote`` на элемент (при отрезанной сети — таймаут на элемент). Для этого
:func:`one_pin_per_report`: внутри области повторный вопрос о той же ссылке того же
репозитория отвечается ТЕМ ЖЕ закреплённым значением, включая отказ.

ТРИ РОДА ЗНАЧЕНИЯ, и смешивать их запрещено (решение ARB 22.10):

* ``source="server"`` — :func:`pin_server_ref`: ТЕКУЩЕЕ состояние сервера;
* ``source="cache"`` — :func:`cached_ref`: локальный кэш remote-tracking ссылки,
  прочитанный ЯВНО как снимок прошлого, с возрастом последнего обновления. Только для
  читателей, у которых устаревание по построению безопасно в одну сторону (бэкап
  исключает по кэшу — бандл лишь больше) или проверяется дальше живым сервером;
* ``source="snapshot"`` — :func:`fetch_head_snapshot`: что сервер сказал при
  последнем fetch этого клона (``FETCH_HEAD``) и когда — для витрин, чей предмет
  «что видит зеркало», а не «что на сервере сейчас».

Снимок НИКОГДА не выдаёт себя за ответ сервера: :meth:`PinnedRef.describe` называет
род и возраст, а ``server_fresh`` истинно только у ``source="server"``.

Только stdlib. LLM_FORBIDDEN. Сеть — только у ``ls-remote``/``fetch``, с таймаутом и
``GIT_TERMINAL_PROMPT=0`` (без терминала запрос учётных данных превращается в
ждущий процесс, а не в честный отказ).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import contextvars
import os
import re
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

_SHA = re.compile(r"^[0-9a-f]{40}$")

#: Таймаут сетевого шага по умолчанию. Не «поднимать, чтобы позеленело»: отказ по
#: таймауту — это исход «не установлено», а не ошибка вызывающего.
NETWORK_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class PinnedRef:
    """Закреплённое значение ссылки. ``sha is None`` ⇔ значение НЕ установлено."""

    ref: str
    sha: Optional[str]
    source: str              # "server" | "local" | "unmeasured"
    reason: str
    remote: Optional[str] = None
    branch: Optional[str] = None
    #: Когда значение НАБЛЮДЕНО (unix-время) — у снимка/кэша; ``None`` у ответа
    #: сервера (он наблюдён сейчас) и там, где возраст НЕ ИЗМЕРЕН (тогда это
    #: сказано в ``reason``, а не подразумевается).
    observed_at: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.sha is not None

    @property
    def server_fresh(self) -> bool:
        """Значение — ответ сервера в этом пути (а не кэш/снимок/локальная ссылка)."""
        return self.sha is not None and self.source == "server"

    def age_s(self, now: Optional[float] = None) -> Optional[float]:
        if self.observed_at is None:
            return None
        return max(0.0, (time.time() if now is None else now) - self.observed_at)

    def describe(self) -> str:
        if self.sha is None:
            return f"`{self.ref}` НЕ УСТАНОВЛЕН: {self.reason}"
        if self.source == "server":
            where = "спрошен у сервера"
        elif self.source in ("cache", "snapshot"):
            age = self.age_s()
            kind = ("КЭШ последнего fetch, не ответ сервера" if self.source == "cache"
                    else "СНИМОК последнего fetch (FETCH_HEAD), не ответ сервера")
            where = (f"{kind}; возраст {age / 3600:.1f} ч" if age is not None
                     else f"{kind}; возраст НЕ ИЗМЕРЕН")
        else:
            where = "локальная ссылка, не кэш чужого fetch"
        return f"`{self.ref}` = {self.sha[:12]} ({where})"


def _git(repo: str, args: list, timeout: float):
    """``(rc, stdout, stderr)``; ``rc is None`` — git не запустился или вышел таймаут."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                           text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return None, "", f"таймаут {timeout:g} с"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", f"{type(exc).__name__}: {exc}"
    return r.returncode, r.stdout, r.stderr


def split_remote_ref(repo: str, ref: str, *, timeout: float = 20.0):
    """``(удалённый, ветка)`` для remote-tracking ссылки; ``None`` — ссылка не такая.

    Классифицируется ИМЕНЕМ, а не значением: форма ``refs/remotes/…``, полное имя
    ссылки (``rev-parse --symbolic-full-name`` — печатает имя, значение кэша не
    нужно) и список удалённых (``git remote``). Ссылка ``refs/remotes/origin/main``
    остаётся кэшем и тогда, когда удалённый ``origin`` в конфиге не объявлен: такой
    кэш классифицируется как remote-tracking, и сервер о нём не ответит — это
    «не установлено», а не повод читать его локально.
    ``(None, причина)`` — классификация НЕ установлена.
    """
    ref = (ref or "").strip()
    if ref.startswith("refs/remotes/"):
        rest = ref[len("refs/remotes/"):]
        remote, _, branch = rest.partition("/")
        return (remote, branch) if remote and branch else None
    if "/" not in ref or ref.startswith(("refs/", "/")):
        return None
    head, _, branch = ref.partition("/")
    if not branch:
        return None
    rc, out, err = _git(repo, ["remote"], timeout)
    if rc != 0:
        return (None, f"список удалённых не прочитан: {(err or '').strip()[:160]}")
    remotes = {ln.strip() for ln in out.splitlines() if ln.strip()}
    if head in remotes:
        return (head, branch)
    rc, out, _err = _git(repo, ["rev-parse", "--symbolic-full-name", ref], timeout)
    full = (out or "").strip()
    if rc == 0 and full.startswith("refs/remotes/"):
        remote, _, branch = full[len("refs/remotes/"):].partition("/")
        if remote and branch:
            return (remote, branch)
    return None


def _has_commit(repo: str, sha: str, timeout: float) -> Optional[bool]:
    rc, _out, _err = _git(repo, ["cat-file", "-e", f"{sha}^{{commit}}"], timeout)
    if rc is None:
        return None
    return rc == 0


#: Область «один отчёт — один sha». ``None`` — области нет (каждый вопрос идёт к серверу).
_REPORT_SCOPE: "contextvars.ContextVar[Optional[dict]]" = contextvars.ContextVar(
    "server_ref_report_scope", default=None)


@contextmanager
def one_pin_per_report():
    """Внутри области каждая ссылка каждого репозитория закрепляется ОДИН раз.

    Повторный :func:`pin_server_ref` той же ``(репозиторий, удалённый, ветка)``
    возвращает тот же :class:`PinnedRef` — и успех, и отказ: отчёт, в котором часть
    элементов судилась сервером, а часть получила «не установлено» после нового
    таймаута, был бы рваным так же, как отчёт по двум разным sha. Вложенная область
    использует внешнюю (отчёт, зовущий другой отчёт, остаётся одним отчётом).
    Отдаёт словарь закреплённого (для печати/тестов).
    """
    outer = _REPORT_SCOPE.get()
    if outer is not None:
        yield outer
        return
    token = _REPORT_SCOPE.set({})
    try:
        yield _REPORT_SCOPE.get()
    finally:
        _REPORT_SCOPE.reset(token)


def one_pin_per_call(fn):
    """Декоратор: весь вызов ``fn`` — один отчёт (:func:`one_pin_per_report`)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with one_pin_per_report():
            return fn(*args, **kwargs)
    return wrapper


def _scope_key(repo: str, *parts) -> tuple:
    try:
        where = os.path.realpath(str(repo))
    except (OSError, ValueError):
        where = str(repo)
    return (where, *parts)


def pin_server_ref(repo: str, ref: str, *,
                   timeout: float = NETWORK_TIMEOUT_S) -> PinnedRef:
    """Закрепить значение ``ref``: у сервера для remote-tracking, локально — для прочих.

    Не бросает. Отказ на любом шаге — ``PinnedRef(sha=None, reason=…)``.
    Внутри :func:`one_pin_per_report` повторный вопрос отвечается первым ответом.
    """
    split = split_remote_ref(repo, ref)
    if isinstance(split, tuple) and split[0] is None:
        return PinnedRef(ref, None, "unmeasured", split[1])
    scope = _REPORT_SCOPE.get()
    key = _scope_key(repo, *(split if split is not None else ("local", ref)))
    if scope is not None and key in scope:
        got = scope[key]
        return got if got.ref == ref else PinnedRef(
            ref, got.sha, got.source, got.reason, got.remote, got.branch, got.observed_at)
    pinned = _pin_uncached(repo, ref, split, timeout)
    if scope is not None:
        scope[key] = pinned
    return pinned


def _pin_uncached(repo: str, ref: str, split, timeout: float) -> PinnedRef:
    if split is None:
        rc, out, err = _git(repo, ["rev-parse", "--verify", "--quiet",
                                   f"{ref}^{{commit}}"], 20.0)
        sha = (out or "").strip()
        if rc == 0 and _SHA.match(sha):
            return PinnedRef(ref, sha, "local", "локальная ссылка разрешена rev-parse")
        return PinnedRef(ref, None, "unmeasured",
                         f"ссылка не разрешается в этом репозитории "
                         f"({(err or '').strip()[:160] or f'rc={rc}'})")

    remote, branch = split
    head_ref = f"refs/heads/{branch}"
    rc, out, err = _git(repo, ["ls-remote", "--exit-code", remote, head_ref], timeout)
    if rc != 0:
        why = ("ветки нет на сервере" if rc == 2 else
               (err or "").strip()[:200] or f"rc={rc}")
        return PinnedRef(ref, None, "unmeasured",
                         f"сервер `{remote}` не ответил о {head_ref}: {why} — "
                         f"локальная `{ref}` есть кэш чужого fetch и ответом не является",
                         remote, branch)
    sha = None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == head_ref and _SHA.match(parts[0]):
            sha = parts[0]
            break
    if sha is None:
        return PinnedRef(ref, None, "unmeasured",
                         f"ответ сервера о {head_ref} не разобран: {out.strip()[:160]!r}",
                         remote, branch)

    have = _has_commit(repo, sha, 20.0)
    if have is None:
        return PinnedRef(ref, None, "unmeasured",
                         f"наличие объекта {sha[:12]} не проверено (git не ответил)",
                         remote, branch)
    if not have:
        rc, _out, err = _git(repo, ["fetch", "--quiet", "--no-tags", remote, head_ref],
                             timeout)
        if rc != 0:
            return PinnedRef(ref, None, "unmeasured",
                             f"сервер назвал {sha[:12]}, но fetch его не добрал: "
                             f"{(err or '').strip()[:200] or f'rc={rc}'}",
                             remote, branch)
        if _has_commit(repo, sha, 20.0) is not True:
            return PinnedRef(ref, None, "unmeasured",
                             f"сервер назвал {sha[:12]}, но после fetch объекта нет "
                             f"(ветку переписали между вопросом и fetch?) — значение "
                             f"НЕ закреплено", remote, branch)
    return PinnedRef(ref, sha, "server", f"ls-remote {remote} {head_ref}",
                     remote, branch)


# ───────────────────── явные снимки: кэш и FETCH_HEAD ─────────────────────

_REFLOG_TS = re.compile(r"@\{(\d{9,})\}")


def cached_ref(repo: str, ref: str) -> PinnedRef:
    """Значение remote-tracking ссылки ИЗ ЛОКАЛЬНОГО КЭША — ЯВНО как снимок прошлого.

    Сети не трогает и ничего не пишет. ``source="cache"`` для remote-tracking ссылки
    (``observed_at`` — время последнего обновления ссылки по её reflog; reflog нет ⇒
    возраст НЕ ИЗМЕРЕН и это сказано в ``reason``), ``source="local"`` для прочих.
    Назначение — читатели, чей предмет ПО ЗАМЫСЛУ «что этот клон знал»: бэкап,
    исключающий уже известное серверу (устаревание даёт лишь больший бандл), или
    отбор кандидатов, которых дальше сверяет живой сервер. Ответом о сервере сейчас
    этот результат НЕ является (``server_fresh is False``).
    """
    split = split_remote_ref(repo, ref)
    if isinstance(split, tuple) and split[0] is None:
        return PinnedRef(ref, None, "unmeasured", split[1])
    rc, out, err = _git(repo, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], 20.0)
    sha = (out or "").strip()
    if rc != 0 or not _SHA.match(sha):
        return PinnedRef(ref, None, "unmeasured",
                         f"кэш `{ref}` не разрешается ({(err or '').strip()[:160] or f'rc={rc}'})")
    if split is None:
        return PinnedRef(ref, sha, "local", "локальная ссылка разрешена rev-parse")
    remote, branch = split
    full = f"refs/remotes/{remote}/{branch}"
    rc, out, _err = _git(repo, ["reflog", "show", "--date=unix", "-n", "1", full], 20.0)
    m = _REFLOG_TS.search(out or "") if rc == 0 else None
    observed = float(m.group(1)) if m else None
    why = (f"кэш {full}: значение последнего fetch этого клона"
           + ("" if observed is not None else " — возраст НЕ ИЗМЕРЕН (reflog ссылки пуст)"))
    return PinnedRef(ref, sha, "cache", why, remote, branch, observed)


def fetch_head_snapshot(repo: str, branch: str = "main") -> PinnedRef:
    """Что СЕРВЕР назвал при последнем fetch этого клона — по ``FETCH_HEAD``, с возрастом.

    Сети не трогает и ничего не пишет. Ищется строка ``<sha> … branch '<ветка>' of
    <url>``; возраст — mtime файла. Нет файла, нет строки ветки (последний fetch был
    о другой ветке) или объекта нет локально ⇒ ``sha=None`` с причиной: снимок, о
    котором нельзя сказать, когда и про что он снят, снимком не является.
    """
    rc, out, err = _git(repo, ["rev-parse", "--git-path", "FETCH_HEAD"], 20.0)
    rel = (out or "").strip()
    name = f"FETCH_HEAD[{branch}]"
    if rc != 0 or not rel:
        return PinnedRef(name, None, "unmeasured",
                         f"путь FETCH_HEAD не получен ({(err or '').strip()[:160] or f'rc={rc}'})")
    path = rel if os.path.isabs(rel) else os.path.join(str(repo), rel)
    try:
        observed = os.stat(path).st_mtime
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        return PinnedRef(name, None, "unmeasured",
                         f"FETCH_HEAD не прочитан ({type(exc).__name__}: {exc}) — fetch "
                         f"этого клона не наблюдался")
    marker = f"branch '{branch}' of "
    sha = None
    for line in lines:
        head, _, desc = line.partition("\t")
        if marker in desc and _SHA.match(head.strip()):
            sha = head.strip()
            break
    if sha is None:
        return PinnedRef(name, None, "unmeasured",
                         f"в FETCH_HEAD нет строки ветки {branch!r} — последний fetch "
                         f"был не о ней, снимка ветки нет", None, branch, observed)
    if _has_commit(repo, sha, 20.0) is not True:
        return PinnedRef(name, None, "unmeasured",
                         f"FETCH_HEAD называет {sha[:12]}, но объекта в клоне нет",
                         None, branch, observed)
    return PinnedRef(name, sha, "snapshot",
                     f"FETCH_HEAD: значение ветки {branch!r} при последнем fetch клона",
                     None, branch, observed)
