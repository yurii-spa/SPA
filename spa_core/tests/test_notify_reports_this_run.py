"""`notify` обязан отчитываться о СВОЁМ прогоне, а не о жизни карточки (цикл #447).

**Авария 2026-09-01, воспроизведена дословно.** Шаг 4 протокола велит завести карточку и
позвать `orchestrator_queue.py notify`. Я так и сделал — и получил::

    notify_needs_owner SUPPRESSED …: anti-storm: та же карточка уходила 5 мин назад
    OK: notified for … — доставлено, message_ids=[9491]      (код возврата 0)

Отправки в том прогоне НЕ БЫЛО: анти-шторм отказал ещё до сборки сообщения, а журнал
`data/telegram_owner_decisions.json` остался байт-в-байт прежним (`send_count` 1,
`pushed_at` не сдвинулся, число записей то же). «Доставлено» относилось к посылке ДРУГОГО
отправителя пятью минутами раньше: `cmd_notify` выбрасывал возврат `notify_needs_owner` и
судил об исходе одним `delivery_verdict`, который читает журнал и честно отвечает на свой
вопрос — «доезжала ли эта карточка КОГДА-НИБУДЬ».

Цена ровно та, против которой `delivery_verdict` и писался 26.08: сессия читает «OK» и
считает вопрос заданным. Здесь хуже — анти-шторм держит сообщение ШЕСТЬ ЧАСОВ намеренно,
и всё это время команда рапортует об успехе. Объявленный в docstring код 1 («НЕ отправлено
— заслон/отказ отправителя») был недостижим для всех трёх гейтов: `[skip]`, `[anti-storm]`,
`[переписана]`.

Класс известен и оплачен дважды: утренний дайджест (01.08) печатал «digest sent» поверх
`No route to host`; сама эта команда (26.08) печатала «OK» поверх дедупа отправителя.
Правило класса: зелёный ответ сторожа на СВОЙ вопрос никогда не есть ответ на нужный.

**Каждый тест ниже — положительный контроль:** он краснеет на коде до починки. Обратные
контроли обязательны рядом — «всегда код 1» достигается поломкой уведомления насовсем, и
потерять вопрос владельцу дороже, чем потерять оформление.

**Почему в дочернем процессе и с относительными отметками.** Живое состояние уводится
штатным `SPA_LIVE_ROOT` (тот же приём, что в `test_notify_dry_run_is_silent`) — иначе тест
писал бы в реестр решений владельца прода. Отметки в журнале считаются от `now`, а не
литералом: предмет проверки — окно свежести (6 ч), и фикстура с фиксированной датой
протухла бы по календарю, а не по поведению (правило `.claude/rules/deployment.md`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.owner_queue.notify import REFUSAL_PREFIXES, refusal_reason

_REPO_ROOT = Path(__file__).resolve().parents[2]

CARD_ID = "own-probe-447"

_CARD_TEMPLATE = (
    "---\n"
    "trackerStatus:\n"
    "  type: owner-decision\n"
    "title: {title}\n"
    "status: {status}\n"
    "---\n"
    "\n"
    "## Что случилось и почему это важно\n"
    "Контекст в двух строках.\n"
    "\n"
    "## Что от тебя нужно\n"
    "* **Вариант 1 (рекомендую) — сделать так.** Пояснение.\n"
    "* **Вариант 2 — сделать иначе.** Пояснение.\n"
)

# Дочерний прогон НАСТОЯЩЕЙ команды: бот подменён до первого импорта (иначе Keychain и
# живой чат), живой корень — песочница, PYTEST_CURRENT_TEST снят, чтобы исполнялась
# боевая ветка выбора пути состояния, а не её тестовый обход.
_CHILD = r'''
import sys, types
from pathlib import Path

sandbox, card_path, repo_root = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])

_bot_mod = types.ModuleType("spa_core.telegram.bot")


class _Bot:
    def send_message(self, text, **kw):
        with (sandbox / "sent.txt").open("a", encoding="utf-8") as fh:
            fh.write(text + "\n<<<END>>>\n")
        return {"result": {"message_id": 4242}}


_bot_mod.TelegramBot = _Bot
sys.modules["spa_core.telegram.bot"] = _bot_mod

import importlib.util

spec = importlib.util.spec_from_file_location(
    "orchestrator_queue_under_test", str(repo_root / "scripts" / "orchestrator_queue.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
sys.exit(mod.main(["notify", card_path]))
'''


class Run:
    """Исход прогона команды: код возврата, что напечатано, что стало с журналом."""

    def __init__(self, code: int, out: str, err: str,
                 journal_before: bytes, journal_after: bytes, sent: str):
        self.code = code
        self.out = out
        self.err = err
        self.journal_unchanged = journal_before == journal_after
        self.sent = sent

    def __repr__(self) -> str:  # pragma: no cover — только для сообщения об ошибке
        return (f"Run(code={self.code}, journal_unchanged={self.journal_unchanged}, "
                f"out={self.out!r}, err={self.err[-800:]!r})")


def _journal(sandbox: Path) -> Path:
    return sandbox / "data" / "telegram_owner_decisions.json"


def _run_cli(sandbox: Path, card: Path) -> Run:
    j = _journal(sandbox)
    before = j.read_bytes() if j.exists() else b""
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env["SPA_LIVE_ROOT"] = str(sandbox)
    env.pop("SPA_DATA_DIR", None)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(sandbox), str(card), str(_REPO_ROOT)],
        cwd=str(_REPO_ROOT), env=env, capture_output=True, text=True, timeout=180,
    )
    after = j.read_bytes() if j.exists() else b""
    sent_file = sandbox / "sent.txt"
    sent = sent_file.read_text(encoding="utf-8") if sent_file.exists() else ""
    return Run(proc.returncode, proc.stdout, proc.stderr, before, after, sent)


def _seed_journal(sandbox: Path, *, minutes_ago: int, delivered=True,
                  title: str = "Вопрос про доставку", options=None,
                  card_path: Path | None = None) -> None:
    """Запись о ПРЕЖНЕЙ посылке — та самая, которую команда принимала за свою."""
    pushed_at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    rec = {
        "pid": "prior001",
        "send_count": 1,
        "card": str(card_path or ""),
        "card_id": CARD_ID,
        "title": title,
        "pushed_at": pushed_at,
        "options": options if options is not None else [],
        "buttons": True,
        "choice": None,
        "delivered": delivered,
        "message_ids": [9491],
    }
    _journal(sandbox).write_text(
        json.dumps({"schema_version": 1, "pushes": [rec]}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    return tmp_path


def _card(tmp_path: Path, *, status: str = "needs-owner",
          title: str = "Вопрос про доставку") -> Path:
    src = tmp_path / "worktree"
    src.mkdir(exist_ok=True)
    p = src / f"{CARD_ID}.md"
    p.write_text(_CARD_TEMPLATE.format(title=title, status=status), encoding="utf-8")
    return p


# ── положительные контроли: три гейта, ни один не смеет читаться как успех ───


def test_anti_storm_refusal_is_not_reported_as_delivered(sandbox, tmp_path):
    """Авария 2026-09-01 дословно: заслон держит сообщение, команда рапортует «OK»."""
    card = _card(tmp_path)
    _seed_journal(sandbox, minutes_ago=9, card_path=card)

    run = _run_cli(sandbox, card)

    assert run.journal_unchanged, (
        "предпосылка теста не выполнена: анти-шторм обязан отказать ДО регистрации, "
        f"а журнал изменился — {run!r}"
    )
    assert not run.sent, f"сообщение уехало владельцу вопреки заслону — {run!r}"
    assert "OK: notified" not in run.out, (
        "команда объявила успехом прогон, в котором не отправляла НИЧЕГО — "
        f"это дефект #447 — {run!r}"
    )
    assert run.code == 1, f"заслон обязан давать код 1 («НЕ отправлено») — {run!r}"
    assert "НЕ ОТПРАВЛЕНО" in run.out


def test_anti_storm_refusal_names_the_reason(sandbox, tmp_path):
    """Отказ обязан назвать ПРИЧИНУ: «код 1» без причины нечем отличить от отказа бота."""
    card = _card(tmp_path)
    _seed_journal(sandbox, minutes_ago=9, card_path=card)

    run = _run_cli(sandbox, card)

    assert "anti-storm" in run.out, f"причина отказа не доехала до читателя — {run!r}"
    assert "в этом прогоне не отправлялось" in run.out


def test_prior_delivery_is_printed_as_past_not_as_outcome(sandbox, tmp_path):
    """Прежняя посылка — отдельный факт, а не оправдание молчания.

    Прятать её нельзя: у владельца на руках МОЖЕТ лежать копия вопроса, и сессии это
    важно знать. Но напечатана она обязана быть как ПРОШЛОЕ — иначе мы вернём ровно тот
    дефект, который чиним.
    """
    card = _card(tmp_path)
    _seed_journal(sandbox, minutes_ago=9, card_path=card)

    run = _run_cli(sandbox, card)

    assert "о ПРОШЛОМ, не об этом прогоне" in run.out, (
        f"прежняя доставка подана как исход этого прогона — {run!r}"
    )
    assert "message_ids=[9491]" in run.out, (
        f"прежняя доставка спрятана — сессия не узнает, что владелец уже видит вопрос — {run!r}"
    )


def test_skip_of_a_closed_card_is_not_reported_as_delivered(sandbox, tmp_path):
    """Второй гейт: карточка уже не ждёт владельца — отправки нет, «OK» быть не может."""
    card = _card(tmp_path, status="ingested")
    _seed_journal(sandbox, minutes_ago=9, card_path=card)

    run = _run_cli(sandbox, card)

    assert not run.sent, f"закрытая карточка уехала владельцу — {run!r}"
    assert "OK: notified" not in run.out, f"«skip» прочитан как успех — {run!r}"
    assert run.code == 1, f"{run!r}"
    assert "не ждёт владельца" in run.out


def test_rewritten_card_refusal_is_not_reported_as_delivered(sandbox, tmp_path):
    """Третий гейт: карточку переписали после отправки — кнопки у владельца от старого текста."""
    card = _card(tmp_path, title="НОВОЕ название после отправки")
    # В журнале — прежнее название, ответа нет: ровно случай, который гейт отклоняет.
    # Отметка СТАРАЯ (окно анти-шторма пройдено), иначе тест красил бы соседний гейт и
    # мы не узнали бы, работает ли этот (контроль — ровно ОДНА ось).
    _seed_journal(sandbox, minutes_ago=60 * 24, title="Вопрос про доставку", card_path=card)

    run = _run_cli(sandbox, card)

    assert not run.sent, f"переписанная карточка уехала владельцу — {run!r}"
    assert "OK: notified" not in run.out, f"«переписана» прочитан как успех — {run!r}"
    assert run.code == 1, f"{run!r}"


# ── обратные контроли: не потерять сам вопрос владельцу ──────────────────────


def test_a_real_send_still_reports_ok_and_zero(sandbox, tmp_path):
    """Без этого «всегда код 1» проходит: отказ уведомления навсегда — тоже «не соврал»."""
    card = _card(tmp_path)  # журнала нет вовсе — первая отправка

    run = _run_cli(sandbox, card)

    assert run.sent, f"настоящая отправка не дошла до бота — {run!r}"
    assert run.code == 0, f"настоящая доставка обязана давать код 0 — {run!r}"
    assert "OK: notified" in run.out
    assert not run.journal_unchanged, f"отправка не зарегистрировалась в журнале — {run!r}"


def test_answered_card_passes_the_storm_gate_and_is_sent(sandbox, tmp_path):
    """Заслон не ужесточён: карточка с ответом владельца — НОВАЯ жизнь, отправка идёт.

    Проверка того, что починка не превратилась в глухую стену: свежая отметка на месте,
    но `choice` заполнен, и гейт обязан пропустить.
    """
    card = _card(tmp_path)
    _seed_journal(sandbox, minutes_ago=9, card_path=card)
    doc = json.loads(_journal(sandbox).read_text(encoding="utf-8"))
    doc["pushes"][0]["choice"] = 1
    _journal(sandbox).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    run = _run_cli(sandbox, card)

    assert run.sent, f"отвеченная карточка не ушла — заслон ужесточён — {run!r}"
    assert run.code == 0, f"{run!r}"


# ── контракт маркеров: объявлен, а не выведен из прозы ───────────────────────


def test_refusal_reason_recognises_every_declared_gate():
    """Маркер и место его подстановки обязаны совпадать — иначе гейт молча «успешен».

    Литеральные копии в двух местах разъезжаются бесшумно: одноимённая строка правится в
    одном месте из двух, и проверка перестаёт видеть гейт, продолжая быть зелёной.
    """
    for prefix in REFUSAL_PREFIXES:
        reason = refusal_reason(f"{prefix} причина словами")
        assert reason == "причина словами", f"маркер {prefix!r} не опознан"


def test_refusal_reason_is_none_for_a_real_message():
    """Обратная сторона: настоящее сообщение владельцу отказом читаться не смеет."""
    assert refusal_reason("🟥 <b>Owner Decision — нужно решение</b>\nтекст") is None
    assert refusal_reason("") is None


def test_every_gate_of_notify_uses_a_declared_marker():
    """Ни один гейт не возвращает причину в обход объявленных маркеров.

    Сторож против будущего четвёртого гейта: добавить `return f"[что-то] …"` мимо
    контракта — значит вернуть дефект #447 в новой одежде, и никакой тест выше этого не
    заметит, потому что нового гейта в них нет.
    """
    import ast

    src = (_REPO_ROOT / "spa_core" / "owner_queue" / "notify.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "notify_needs_owner")
    declared = {"REFUSAL_SKIP", "REFUSAL_ANTI_STORM", "REFUSAL_REWRITTEN"}
    offenders = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        text = ast.unparse(node.value)
        if "[" in text and "]" in text and not (declared & set(text.split())):
            # Возврат с квадратной скобкой — почти наверняка маркер отказа.
            if any(f"{p}" in text for p in ("[skip", "[anti", "[переп")):
                offenders.append(text)
    assert not offenders, (
        "гейт возвращает маркер отказа литералом мимо объявленного контракта: "
        f"{offenders}"
    )
