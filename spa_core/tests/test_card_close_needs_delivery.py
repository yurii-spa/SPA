"""Карточку нельзя закрыть по работе, которой нет на `origin/main`.

Положительный контроль аварии, а не украшение
------------------------------------------------------------------------------
Класс «осиротевшая работа» (карточка
`agent-orphaned-work-recurred-after-its-card-was-closed`): сессия умирает МЕЖДУ
работой и пушем, результат остаётся в её дереве, а карточка уже `done`. Вредит
именно закрытая карточка: следующая сессия читает доску, видит `done` и задачу
не берёт. Замер по журналу `data/tracker_status_audit.jsonl` (13–18.08.2026):
десять переходов `→ done` в этом дереве, и НИ ОДИН не виден на `origin/main`.

Каждый тест здесь — авария в обе стороны сразу:

* закрытие карточки, чья работа НЕ на origin, **краснеет** (rc 2, статус в файле
  не меняется);
* закрытие карточки с доставленной работой **проходит** (rc 0, статус меняется).

Это ровно та пара, которая ловит обе мутации: «пускать всегда» валит первый
тест, «отказывать всегда» — второй. Отдельно закреплено, что гейт НЕ превращён
в запрет закрывать карточки: захват (`claimed_by`) работой не считается,
карточка, которой на ref нет вовсе, закрывается, прочие статусы не гейтятся
вообще, а вне git-репозитория сверка честно называется НЕ ИЗМЕРЕННОЙ и работу
не роняет.

Инвариант #14 не ослаблен: `owner-done` по-прежнему отказывается — закреплено
здесь же, на доставленной карточке (то есть там, где новый гейт заведомо не
мешает и отказ может прийти только от старой проверки).

Герметично и офлайн: свой временный репозиторий, `origin/main` заводится
`git update-ref` — сеть не задействуется, и это тоже проверено.
"""
from __future__ import annotations

import importlib.util
import subprocess
import textwrap
from pathlib import Path

import pytest

from spa_core.owner_queue import delivery_gate, queue

_REPO = Path(__file__).resolve().parents[2]
_CLI = _REPO / "scripts" / "orchestrator_queue.py"

CARD_ID = "agent-proba-dostavki"
BASE_CARD = textwrap.dedent(
    """\
    ---
    trackerStatus:
      type: agent-task
    title: "Проба: карточка, по которой ведётся работа"
    status: backlog
    created: 2026-08-18
    ---

    ## Почему карточка заводится

    Тело на origin: одна строка.
    """
)
ACCEPTANCE = "\n## Сделано\n\nПриёмка, которой на origin ещё нет.\n"


def _load_cli():
    spec = importlib.util.spec_from_file_location("orchestrator_queue_cli_delivery", _CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> None:
    res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)}: {res.stderr}"


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    """Репозиторий с карточкой, доставленной на `origin/main`. → (корень, карточка)."""
    root = tmp_path / "tree"
    tracker = root / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)
    card = tracker / f"{CARD_ID}.md"
    card.write_text(BASE_CARD, encoding="utf-8")
    _git(root.parent, "init", "-q", str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "база")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root, card


def _deliver(root: Path) -> None:
    """Доставить текущее состояние дерева на `origin/main` (коммит + сдвиг ref)."""
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "доставка")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")


def _status_of(card: Path) -> str:
    for line in card.read_text(encoding="utf-8").splitlines():
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("в карточке нет строки status:")


def _set_status(cli, card: Path, status: str, *extra: str) -> int:
    return cli.main(["set-status", str(card), status, *extra])


# ── обе стороны аварии ───────────────────────────────────────────────────────

def test_close_refused_when_work_is_not_on_origin(tmp_path, capsys):
    """КРАСНАЯ сторона: тело карточки богаче, чем на origin ⇒ `done` отказан."""
    root, card = _repo(tmp_path)
    card.write_text(BASE_CARD + ACCEPTANCE, encoding="utf-8")

    rc = _set_status(_load_cli(), card, "done")

    assert rc == 2, "закрытие по недоставленной работе обязано отказывать"
    err = capsys.readouterr().err
    assert "REFUSED" in err
    assert "origin/main" in err
    assert _status_of(card) == "backlog", "статус НЕ должен меняться при отказе"


def test_close_allowed_when_work_is_delivered(tmp_path):
    """ЗЕЛЁНАЯ сторона: ту же работу доставили ⇒ та же команда закрывает карточку."""
    root, card = _repo(tmp_path)
    card.write_text(BASE_CARD + ACCEPTANCE, encoding="utf-8")
    _deliver(root)

    rc = _set_status(_load_cli(), card, "done")

    assert rc == 0
    assert _status_of(card) == "done"


# ── гейт не превращён в запрет закрывать карточки ────────────────────────────

def test_claim_bookkeeping_is_not_undelivered_work(tmp_path):
    """Захват карточки — бухгалтерия инструмента, а не работа: закрытие проходит.

    Без этого гейт краснел бы на КАЖДОЙ взятой по протоколу карточке (захват
    дописывает `claimed_by`/`claimed_at` в дерево, но не на origin) — то есть
    мешал бы по делу и был бы выключен в первый же день.
    """
    root, card = _repo(tmp_path)
    card.write_text(
        BASE_CARD.replace("created: 2026-08-18\n",
                          "created: 2026-08-18\nclaimed_by: cycle-1\n"
                          "claimed_at: 2026-08-18T10:00:00Z\n"),
        encoding="utf-8")

    assert _set_status(_load_cli(), card, "done") == 0
    assert _status_of(card) == "done"


def test_card_absent_on_ref_can_be_closed(tmp_path):
    """Карточки нет на ref вовсе ⇒ закрывать можно: `done` и тело уедут одним файлом."""
    root, card = _repo(tmp_path)
    fresh = card.with_name("agent-rodilas-v-etom-tsikle.md")
    fresh.write_text(BASE_CARD + ACCEPTANCE, encoding="utf-8")

    assert _set_status(_load_cli(), fresh, "done") == 0
    assert _status_of(fresh) == "done"


def test_other_statuses_are_not_gated(tmp_path):
    """Гейт — про `done`. Расходящаяся карточка спокойно едет в `in-progress`."""
    root, card = _repo(tmp_path)
    card.write_text(BASE_CARD + ACCEPTANCE, encoding="utf-8")

    assert _set_status(_load_cli(), card, "in-progress") == 0
    assert _status_of(card) == "in-progress"


def test_unmeasured_outside_repo_does_not_block(tmp_path, capsys):
    """Вне git-репозитория сверка НЕ ИЗМЕРЕНА и вслух — но работу не роняет."""
    tracker = tmp_path / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)
    card = tracker / f"{CARD_ID}.md"
    card.write_text(BASE_CARD, encoding="utf-8")

    assert _set_status(_load_cli(), card, "done") == 0
    assert "НЕ ИЗМЕРЕНА" in capsys.readouterr().err
    assert _status_of(card) == "done"


# ── осознанный обход: громкий и с причиной ───────────────────────────────────

def test_override_needs_a_reason_and_says_it_out_loud(tmp_path, capsys):
    root, card = _repo(tmp_path)
    card.write_text(BASE_CARD + ACCEPTANCE, encoding="utf-8")
    cli = _load_cli()

    assert _set_status(cli, card, "done", "--allow-undelivered", "") == 2, \
        "пустая причина — не причина: обход обязан оставаться осознанным"
    capsys.readouterr()

    assert _set_status(cli, card, "done", "--allow-undelivered", "карточка-бухгалтерия") == 0
    err = capsys.readouterr().err
    assert "ОСОЗНАННЫЙ ОБХОД" in err and "карточка-бухгалтерия" in err
    assert _status_of(card) == "done"


# ── инвариант #14 не ослаблен ────────────────────────────────────────────────

def test_owner_done_still_forbidden_for_agents(tmp_path, capsys):
    """Доставленная карточка — и всё равно `owner-done` отказан (инв. #14)."""
    root, card = _repo(tmp_path)

    rc = _set_status(_load_cli(), card, "owner-done")

    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err
    assert _status_of(card) == "backlog"
    with pytest.raises(queue.OwnerDoneForbidden):
        queue.set_status(card, "owner-done")


# ── сторож не ходит в сеть ───────────────────────────────────────────────────

def test_gate_never_goes_to_the_network(tmp_path, monkeypatch):
    """Ни один вызов git из гейта не является сетевым (`fetch`/`pull`/`ls-remote`).

    Та же проверка, что охраняет `origin_view`: вердикт обязан быть про ЛОКАЛЬНУЮ
    копию ref, иначе «сверено с origin» тихо превратится в «сходили в интернет».
    """
    root, card = _repo(tmp_path)
    seen: list[list[str]] = []
    real = delivery_gate._git

    def spy(root_arg, args, stdin_text=None):
        seen.append(list(args))
        return real(root_arg, args, stdin_text)

    monkeypatch.setattr(delivery_gate, "_git", spy)
    delivery_gate.check_card_delivered(card)

    assert seen, "гейт обязан хоть что-то измерить"
    forbidden = {"fetch", "pull", "remote", "ls-remote", "clone", "push"}
    for args in seen:
        assert not (set(args) & forbidden), f"сетевой вызов git из гейта: {args}"


# ── нормализация: исключается ровно бухгалтерия, тело не трогается ───────────

def test_normalizer_strips_only_bookkeeping_keys():
    body_changed = BASE_CARD + ACCEPTANCE
    assert delivery_gate.normalized_card(BASE_CARD) != \
        delivery_gate.normalized_card(body_changed), "правка тела обязана быть видна"

    with_claim = BASE_CARD.replace("status: backlog", "status: done\nclaimed_by: cycle-1")
    assert delivery_gate.normalized_card(BASE_CARD) == \
        delivery_gate.normalized_card(with_claim), "статус и захват работой не считаются"

    nested = BASE_CARD.replace("  type: agent-task", "  type: inbox")
    assert delivery_gate.normalized_card(BASE_CARD) != \
        delivery_gate.normalized_card(nested), "вложенные ключи исключать нельзя"
