# LLM_FORBIDDEN
"""Одобрение владельца обязано что-то РАЗРЕШАТЬ.

Механизм обхода owner-gate состоит из трёх частей, и он работает только если целы все три:

1. `check_owner_gate._approved_scope` находит карточку по трейлеру `Owner-Approved:`
   (опечатка `card_type=` вместо `tracker_type=` — починена 2026-08-08);
2. `_parse_approves` читает `approves:` как СПИСОК путей (плоский frontmatter —
   починено там же);
3. **карточку с полем `approves:` кто-то создаёт.**

Третьей части не было. `safe_site_push._route_to_owner_card` поле не писал, поэтому
карточка, даже переведённая владельцем в `owner-done`, снимала НОЛЬ нарушений: scope
пустой ⇒ ветка обхода не выполняется вовсе. Владельцу при этом обещано обратное —
и в теле карточки, и в `docs/OWNER_GATE.md`.

Замер 2026-08-09 (цикл #171): владелец одобрил правку `packages.astro` в 22:00Z
(вариант 1, telegram) — исполнить одобрение штатным путём было НЕЧЕМ.

Каждый тест ниже — положительный контроль: снимаем починку, тест краснеет.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.owner_queue import queue as ownq  # noqa: E402


def _load_safe_site_push():
    """Грузим по ПУТИ: scripts/ не пакет, обычный импорт его не видит."""
    path = _REPO_ROOT / "scripts" / "safe_site_push.py"
    spec = importlib.util.spec_from_file_location("safe_site_push_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _load_owner_gate():
    path = _REPO_ROOT / "scripts" / "check_owner_gate.py"
    spec = importlib.util.spec_from_file_location("check_owner_gate_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


_FLAGGED = "landing/src/pages/packages.astro"


def _report(files=(_FLAGGED,)):
    return {
        "violations": [
            {"file": f, "line": 48, "klass": "E", "rule": "honesty.token.removed",
             "matched_text": "status_en: 'RESEARCH · refused for live (by design)'"}
            for f in files
        ]
    }


@pytest.fixture()
def tracker(tmp_path, monkeypatch):
    """Изолированный трекер: настоящие карточки, но не в очереди владельца.

    Подменяем АТРИБУТ уже импортированного модуля, а не `SPA_TRACKER_DIR`.
    `TRACKER_DIR` читается из окружения на уровне модуля, то есть замерзает при
    первом импорте; путь через env потребовал бы выбрасывать модуль из кэша, а
    это ломает соседей — `test_safe_site_push.py` держит ССЫЛКУ на объект модуля
    (`from spa_core.owner_queue import queue as ownq`) и патчит его же атрибут.
    Переимпорт подсовывает другой объект, и патч соседа молча перестаёт
    действовать: свой набор зелёный, а роняет он чужой файл — и только при
    определённом порядке. Проверено в обе стороны (см. тест ниже).
    """
    d = tmp_path / "tracker"
    d.mkdir()
    monkeypatch.setattr(ownq, "TRACKER_DIR", d)
    return d


def _created_card(tracker_dir: Path) -> Path:
    cards = sorted(tracker_dir.glob("owner-decision-*.md"))
    assert cards, "safe_site_push обязан создать карточку owner-decision"
    return cards[-1]


# ── 1. поле вообще появляется ───────────────────────────────────────────────
def test_card_carries_approves_scope(tracker):
    """Без `approves:` одобрение владельца не разрешает ничего."""
    ssp = _load_safe_site_push()
    ssp._route_to_owner_card([str(_REPO_ROOT / _FLAGGED)], _report(), "msg")
    text = _created_card(tracker).read_text(encoding="utf-8")
    assert "approves:" in text, "карточка обязана нести scope одобрения"
    assert _FLAGGED in text.split("---")[1], "scope обязан быть во frontmatter, не только в теле"


# ── 2. путь repo-relative, а не абсолютный ──────────────────────────────────
def test_approves_is_repo_relative_not_absolute(tracker):
    """Абсолютный путь не совпал бы НИ С ОДНИМ нарушением — одобрение вхолостую.

    Гейт сообщает нарушения repo-relative; `--files` приходят абсолютными.
    Это ровно тот класс, где всё «работает», но не совпадает ни разу.
    """
    ssp = _load_safe_site_push()
    ssp._route_to_owner_card([str(_REPO_ROOT / _FLAGGED)], _report(), "msg")
    fm = _created_card(tracker).read_text(encoding="utf-8").split("---")[1]
    approves = [ln for ln in fm.splitlines() if ln.startswith("approves:")][0]
    assert str(_REPO_ROOT) not in approves, f"абсолютный путь в scope: {approves}"
    assert _FLAGGED in approves


# ── 3. round-trip через настоящий парсер очереди ────────────────────────────
def test_approves_round_trips_through_queue_parser(tracker):
    """Записали одним модулем — читает другой. Скобки/кавычки ломали бы совпадение."""
    ssp = _load_safe_site_push()
    ssp._route_to_owner_card([str(_REPO_ROOT / _FLAGGED)], _report(), "msg")
    gate = _load_owner_gate()
    from spa_core.owner_queue.queue import load_card  # type: ignore

    card = load_card(str(_created_card(tracker)))
    # `Card` держит прочие ключи frontmatter в `fields` — атрибута `frontmatter`
    # у него нет; чтение несуществующего поля и было третьей поломкой обхода.
    assert not hasattr(card, "frontmatter"), (
        "у Card появился `frontmatter` — сверить с _approved_scope, "
        "иначе поля снова разойдутся молча"
    )
    parsed = gate._parse_approves((card.fields or {}).get("approves"))
    assert parsed == [_FLAGGED], f"scope прочитан как {parsed!r}"


# ── 4. сквозной путь: обход открывается ТОЛЬКО на owner-done ────────────────
def _rewrite_status(card: Path, status: str) -> None:
    text = card.read_text(encoding="utf-8")
    head, rest = text.split("---", 2)[1], text.split("---", 2)[2]
    head = "\n".join(
        (f"status: {status}" if ln.startswith("status:") else ln) for ln in head.splitlines()
    )
    card.write_text(f"---{head}\n---{rest}", encoding="utf-8")


@pytest.mark.parametrize(
    "status,expect_bypass",
    [("owner-done", True), ("needs-owner", False), ("ingested", False)],
)
def test_bypass_only_for_owner_done(tracker, status, expect_bypass):
    """Обе стороны: одобрено — нарушение снято; не одобрено — по-прежнему заперто."""
    ssp = _load_safe_site_push()
    ssp._route_to_owner_card([str(_REPO_ROOT / _FLAGGED)], _report(), "msg")
    card = _created_card(tracker)
    _rewrite_status(card, status)

    gate = _load_owner_gate()
    scope = gate._approved_scope(f"fix\n\nOwner-Approved: {card.stem}", _REPO_ROOT)
    if expect_bypass:
        assert scope is not None, "owner-done карточка обязана давать scope"
        assert scope["approves"] == [_FLAGGED]
    else:
        assert scope is None, f"статус {status!r} НЕ должен открывать обход"


def test_trailer_accepts_the_id_the_gate_itself_generates(tracker):
    """Производитель и потребитель идентификатора обязаны совпадать.

    Гейт заводит карточки `owner-decision-…`, а шаблон трейлера принимал только
    `own-…`/`Q-OWN-…`. Ни одна МАШИННАЯ карточка не могла быть предъявлена как
    одобрение — при том что именно их гейт и создаёт.
    """
    gate = _load_owner_gate()
    ssp = _load_safe_site_push()
    ssp._route_to_owner_card([str(_REPO_ROOT / _FLAGGED)], _report(), "msg")
    card = _created_card(tracker)
    assert card.stem.startswith("owner-decision-"), "изменилась схема имён — сверить шаблон"
    _rewrite_status(card, "owner-done")
    scope = gate._approved_scope(f"fix\n\nOwner-Approved: {card.stem}", _REPO_ROOT)
    assert scope is not None, f"трейлер не принял собственный id гейта: {card.stem}"
    assert scope["card"].lower() == card.stem.lower()


def test_unknown_card_id_never_bypasses(tracker):
    """Расширение шаблона не должно открывать обход выдуманной карточке."""
    gate = _load_owner_gate()
    assert gate._approved_scope("fix\n\nOwner-Approved: owner-decision-net-takoi", _REPO_ROOT) is None
    assert gate._approved_scope("fix\n\nOwner-Approved: own-99-vydumka", _REPO_ROOT) is None
    assert gate._approved_scope("fix (без трейлера вовсе)", _REPO_ROOT) is None


# ── 5. нет нарушений ⇒ нет scope (fail-CLOSED) ──────────────────────────────
def test_no_violations_means_no_scope(tracker):
    """Пустой перечень не превращается в разрешение на пустой путь."""
    ssp = _load_safe_site_push()
    ssp._route_to_owner_card([str(_REPO_ROOT / _FLAGGED)], {"violations": []}, "msg")
    fm = _created_card(tracker).read_text(encoding="utf-8").split("---")[1]
    assert "approves:" not in fm, "без нарушений поле писать нельзя — это пустое разрешение"


# ── 6. одобряется РОВНО заблокированное, а не весь список --files ───────────
def test_scope_covers_only_flagged_files(tracker):
    """Чистый файл в той же пачке не должен получать одобрение заодно."""
    ssp = _load_safe_site_push()
    clean = "landing/src/pages/faq.astro"
    ssp._route_to_owner_card(
        [str(_REPO_ROOT / _FLAGGED), str(_REPO_ROOT / clean)], _report(), "msg"
    )
    fm = _created_card(tracker).read_text(encoding="utf-8").split("---")[1]
    approves = [ln for ln in fm.splitlines() if ln.startswith("approves:")][0]
    assert _FLAGGED in approves
    assert clean not in approves, "одобрен файл, который гейт не блокировал"
