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

Только stdlib. LLM_FORBIDDEN. Сеть — только у ``ls-remote``/``fetch``, с таймаутом и
``GIT_TERMINAL_PROMPT=0`` (без терминала запрос учётных данных превращается в
ждущий процесс, а не в честный отказ).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import re
import subprocess
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

    @property
    def ok(self) -> bool:
        return self.sha is not None

    def describe(self) -> str:
        if self.sha is None:
            return f"`{self.ref}` НЕ УСТАНОВЛЕН: {self.reason}"
        where = ("спрошен у сервера" if self.source == "server"
                 else "локальная ссылка, не кэш чужого fetch")
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


def pin_server_ref(repo: str, ref: str, *,
                   timeout: float = NETWORK_TIMEOUT_S) -> PinnedRef:
    """Закрепить значение ``ref``: у сервера для remote-tracking, локально — для прочих.

    Не бросает. Отказ на любом шаге — ``PinnedRef(sha=None, reason=…)``.
    """
    split = split_remote_ref(repo, ref)
    if isinstance(split, tuple) and split[0] is None:
        return PinnedRef(ref, None, "unmeasured", split[1])
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
