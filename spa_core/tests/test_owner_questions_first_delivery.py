#!/usr/bin/env python3
"""У ПЕРВОЙ доставки вопроса владельцу не было маршрута (авария 22.08, #345).

**Что произошло.** ``data/owner_decision_pending.json`` @ 2026-08-22T12:52Z:

```
queue_gap_count: 3 — все три `delivered: false`, НИ РАЗУ не отправлены
  owner-decision-kesh-sistemy-tot-zhe-usdc-zamer-pokazal    (Protection Lab, PR #30)
  owner-decision-maple-15-knigi-defolt-prihodit-bez-predu   (PR #30; хвост −$12 000)
  owner-decision-test-prizrak-ne-rozhdaetsya                (наш собственный тест-зонд)
```

Три вопроса `needs-owner` живут на ``origin/main`` (616706151) и отсутствуют в живом
дереве. Цикл #330 починил отправителя — ``resend.open_questions`` читает обе стороны
очереди и умеет отправить origin-only карточку. Но **у этого пути нет ни одного
вызывающего**: ``resend-open`` существует только как подкоманда CLI. Вопрос, попавший на
``origin`` не через живую сессию (merge ветки / PR / другая машина), доезжает до владельца
ровно тогда, когда кто-то наберёт команду руками.

Позвать ``resend-open`` вместо починки было нельзя: он ставит ``owner_requested=True``,
что снимает дедуп и анти-шторм ВСЕМУ набору — то есть присылает владельцу заново всё
открытое. Ровно на этот поток он жаловался трижды (#215/#217/#228, ADR-084).

Каждый тест ниже — положительный контроль на эту аварию либо обратный контроль на
разрушительную сторону починки (повторная отправка · снятие заслонов · молчаливое
усечение очереди потолком).

Тесты герметичны: настоящий git в ``TemporaryDirectory``, ``refs/remotes/*`` заводится
плумбингом, сети нет, наружу не уходит ни одно сообщение.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[2]
_CLI = _REPO / "scripts" / "orchestrator_queue.py"

NOW = datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc)
REF = "origin/main"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: очередь читается с ref плумбингом, без сети",
)

CARD_TMPL = """---
trackerStatus:
  type: {type}
title: {title}
status: {status}
---

## Что случилось и почему это важно

{marker}

## Что от тебя нужно

**Вариант 1 — сделать так.** (⭐ рекомендация агента)

**Вариант 2 — сделать иначе.**

## Как понять, что готово

Ответ записан.

## Что будет после

Беру в работу.
"""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(cwd)
    env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "2026-08-22T13:00:00+0000"
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True, text=True, check=True, env=env,
    )


def _card_text(name: str, *, status: str = "needs-owner",
               card_type: str = "owner-decision", marker: str = "") -> str:
    return CARD_TMPL.format(type=card_type, title=f"Вопрос {name}", status=status,
                            marker=marker or f"Тестовая карточка {name}.")


class _Repo:
    """Репозиторий, в котором очередь на ``origin/main`` ШИРЕ очереди дерева.

    Ровно конфигурация прода 22.08: две карточки приехали на origin merge-ем ветки
    (PR #30) и в рабочее дерево не попадали никогда.
    """

    def __init__(self, root: Path):
        self.root = root
        self.tracker = root / "nimbalyst-local" / "tracker"
        self.tracker.mkdir(parents=True)
        _git(root.parent, "init", "-q", "-b", "main", str(root))

    def commit_all(self, msg: str = "карточки") -> str:
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", msg)
        return _git(self.root, "rev-parse", "HEAD").stdout.strip()

    def publish(self, ref: str = REF) -> str:
        sha = _git(self.root, "rev-parse", "HEAD").stdout.strip()
        _git(self.root, "update-ref", f"refs/remotes/{ref}", sha)
        return sha

    def write(self, name: str, **kw) -> Path:
        p = self.tracker / f"{name}.md"
        p.write_text(_card_text(name, **kw), encoding="utf-8")
        return p

    def hide_from_tree(self, *names: str) -> None:
        """Убрать карточку с ДИСКА, оставив её на ref — состояние прод-дерева 22.08."""
        for n in names:
            (self.tracker / f"{n}.md").unlink()


def _module():
    from spa_core.owner_queue import first_delivery as F

    return F


def _journal(tmp: Path, *card_ids: str) -> Path:
    """Журнал отправок, в котором названные карточки владельцу УЖЕ уходили."""
    path = tmp / "owner_decision_pushes.json"
    path.write_text(json.dumps({"pushes": [
        {"card_id": cid, "delivered": True, "buttons": True,
         "message_ids": [100 + i], "pushed_at": "2026-08-20T10:00:00+00:00"}
        for i, cid in enumerate(card_ids)
    ]}), encoding="utf-8")
    return path


def _run(F, tracker: Path, *, dry_run: bool = False, limit=None,
         state_path: Path | None = None, report_path: Path | None = None):
    """Прогон доставки с перехватом ОТПРАВКИ. Наружу не уходит ничего."""
    sent: list[tuple[str, str, bool]] = []

    def fake_notify(path, *, dry_run=False, owner_requested=False):
        p = Path(path)
        sent.append((p.stem, p.read_text(encoding="utf-8") if p.is_file() else "",
                     owner_requested))
        return "текст"

    with mock.patch("spa_core.owner_queue.notify.notify_needs_owner", fake_notify), \
         mock.patch("spa_core.owner_queue.resend._measure_delivery",
                    return_value=(True, True, 1)):
        rep = F.deliver_new_questions(tracker_dir=tracker, now=NOW, dry_run=dry_run,
                                      sleep=lambda s: None, limit=limit,
                                      state_path=state_path, report_path=report_path)
    return rep, sent


class FirstDeliveryTest(unittest.TestCase):
    """Ядро аварии: вопрос, которого владелец не видел ни разу, обязан уехать сам."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repo = _Repo(self.tmp / "repo")
        self.F = _module()

    def _prod_22_08(self):
        """Дереву видна одна отправленная карточка; на origin — ещё три из PR #30."""
        self.repo.write("own-seen")
        self.repo.write("own-kesh", marker="ВОПРОС ТОЛЬКО НА ORIGIN (PR #30)")
        self.repo.write("own-maple", marker="Хвост −$12 000 (PR #30)")
        self.repo.write("own-closed-on-origin", status="ingested")
        self.repo.write("inbox-hidden", card_type="inbox")
        self.repo.commit_all()
        sha = self.repo.publish()
        self.repo.hide_from_tree("own-kesh", "own-maple", "own-closed-on-origin",
                                 "inbox-hidden")
        return sha, _journal(self.tmp, "own-seen")

    def test_a_never_seen_question_from_origin_reaches_the_owner(self):
        """АВАРИЯ 22.08: три вопроса на origin не уезжали владельцу НИЧЕМ."""
        _, state = self._prod_22_08()
        rep, sent = _run(self.F, self.repo.tracker, state_path=state)
        self.assertEqual(sorted(s[0] for s in sent), ["own-kesh", "own-maple"],
                         "вопрос, живущий только на origin и не отправленный ни разу, "
                         "обязан уехать владельцу сам — иначе он не увидит его никогда")
        self.assertEqual(rep.delivered, 2)

    def test_a_question_the_owner_already_saw_is_not_sent_again(self):
        """Обратный контроль: первая доставка не смеет стать вторым путём повторов.

        Владелец жаловался на поток одинаковых сообщений трижды (#215/#217/#228);
        рутинный повтор уже виденного воспроизвёл бы жалобу нашими же руками.
        """
        _, state = self._prod_22_08()
        rep, sent = _run(self.F, self.repo.tracker, state_path=state)
        self.assertNotIn("own-seen", [s[0] for s in sent])
        self.assertIn("own-seen", rep.attempted_before)

    def test_an_attempted_but_undelivered_question_is_named_not_resent(self):
        """Запись есть, `delivered: false` — это «пробовали и не доехало», ДРУГОЙ вид.

        Повторять её обязан анти-шторм со своим окном. Тихо досылать её отсюда значило бы
        завести второй, неподотчётный путь повторов — и он бы шёл мимо потолка анти-шторма.
        """
        self.repo.write("own-tried")
        self.repo.commit_all()
        self.repo.publish()
        state = self.tmp / "pushes.json"
        state.write_text(json.dumps({"pushes": [
            {"card_id": "own-tried", "delivered": False, "buttons": False,
             "message_ids": [], "pushed_at": "2026-08-21T10:00:00+00:00"}]}),
            encoding="utf-8")
        rep, sent = _run(self.F, self.repo.tracker, state_path=state)
        self.assertEqual(sent, [])
        self.assertEqual(rep.attempted_before, ["own-tried"])
        self.assertEqual(rep.never_sent, [])

    def test_a_question_closed_on_origin_is_never_delivered(self):
        """Обратный контроль: закрытое (`ingested`) вопросом уже не является."""
        _, state = self._prod_22_08()
        _, sent = _run(self.F, self.repo.tracker, state_path=state)
        self.assertNotIn("own-closed-on-origin", [s[0] for s in sent])

    def test_only_owner_decision_cards_are_taken(self):
        """Обратный контроль: задание (`inbox`) вопросом владельцу не является."""
        _, state = self._prod_22_08()
        _, sent = _run(self.F, self.repo.tracker, state_path=state)
        self.assertNotIn("inbox-hidden", [s[0] for s in sent])

    def test_guards_are_not_lifted_on_a_first_send(self):
        """`owner_requested` обязан остаться False — иначе тихо снимутся ВСЕ заслоны.

        Флаг существует ровно для просьбы владельца «пришлите заново» (20.08, вар. 2).
        Наша собственная инициатива права снимать дедуп и анти-шторм не имеет.
        """
        _, state = self._prod_22_08()
        _, sent = _run(self.F, self.repo.tracker, state_path=state)
        self.assertTrue(sent)
        self.assertTrue(all(flag is False for _, _, flag in sent), sent)

    def test_the_delivered_card_carries_the_origin_body_under_its_own_id(self):
        """Файл обязан нести ТЕКСТ С REF и имя ``<card_id>.md``.

        Имя — ключ журнала отправок и callback кнопки (``path.stem``); другое имя развело
        бы отправку с ответом владельца. Текст — варианты ответа: без них уедет вопрос,
        на который нечем ответить с телефона.
        """
        _, state = self._prod_22_08()
        _, sent = _run(self.F, self.repo.tracker, state_path=state)
        body = next(text for stem, text, _ in sent if stem == "own-kesh")
        self.assertIn("ВОПРОС ТОЛЬКО НА ORIGIN", body)
        self.assertIn("Вариант 1", body)

    def test_the_cap_defers_the_rest_by_name_instead_of_truncating_silently(self):
        """Потолок за прогон обязан НАЗЫВАТЬ остаток. Молчаливое усечение читается как
        «доставили всё» — тот же класс, из-за которого вопросы и терялись."""
        _, state = self._prod_22_08()
        rep, sent = _run(self.F, self.repo.tracker, state_path=state, limit=1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(rep.deferred), 1)
        self.assertIn(rep.deferred[0], ("own-kesh", "own-maple"))
        self.assertIn("отложено до следующего прогона",
                      self.F.summary_line(rep))

    def test_default_cap_is_small_enough_not_to_be_a_storm(self):
        """Потолок по умолчанию — не украшение: восемь ПЕРВЫХ отправок подряд и есть шторм."""
        self.assertLessEqual(self.F.FIRST_DELIVERY_PER_RUN, 3)

    def test_dry_run_sends_nothing_and_registers_nothing(self):
        """Сухой прогон обязан быть НЕМЫМ: нажимать в нём нечего, регистрировать пуш нельзя."""
        _, state = self._prod_22_08()
        rep, sent = _run(self.F, self.repo.tracker, state_path=state, dry_run=True)
        self.assertTrue(all(o.reason == "dry_run" for o in rep.outcomes), rep.outcomes)
        self.assertEqual(rep.delivered, 0)
        self.assertEqual(sorted(s[0] for s in sent), ["own-kesh", "own-maple"])

    def test_report_names_the_origin_side_of_the_measurement(self):
        """«Сверено» обязано быть измерением: ref, sha и число origin-only в отчёте."""
        sha, state = self._prod_22_08()
        report_path = self.tmp / "report.json"
        rep, _ = _run(self.F, self.repo.tracker, state_path=state,
                      report_path=report_path)
        self.assertTrue(rep.queue_measured)
        self.assertEqual(rep.origin["ref_sha"], sha)
        self.assertEqual(rep.origin["origin_only"], 2)
        doc = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIs(doc["queue_measured"], True)
        self.assertEqual(sorted(doc["never_sent"]), ["own-kesh", "own-maple"])


class QueueUnmeasuredTest(unittest.TestCase):
    """«Померить не смогли» обязано звучать, а не выглядеть как «новых вопросов нет»."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.tracker = self.tmp / "tracker"
        self.tracker.mkdir()
        self.F = _module()

    def test_unmeasured_queue_is_named_and_visible_questions_still_go(self):
        """Каталог вне git: сверять не с чем. Молчать об этом нельзя — и терять при этом
        видимые дереву вопросы тоже нельзя (обмен одной немоты на другую)."""
        (self.tracker / "own-local.md").write_text(_card_text("own-local"),
                                                   encoding="utf-8")
        rep, sent = _run(self.F, self.tracker,
                         state_path=self.tmp / "empty-journal.json")
        self.assertFalse(rep.queue_measured)
        self.assertEqual([s[0] for s in sent], ["own-local"])
        line = self.F.summary_line(rep)
        self.assertIn("НЕ СВЕРЕНА", line)
        self.assertIn("НЕПОЛОН", line)

    def test_empty_and_unmeasured_are_different_statements(self):
        """Пустая очередь без сверки не имеет права читаться как «новых вопросов нет»."""
        rep, sent = _run(self.F, self.tracker,
                         state_path=self.tmp / "empty-journal.json")
        self.assertEqual(sent, [])
        self.assertFalse(rep.queue_measured)
        self.assertIn("НЕ СВЕРЕНА", self.F.summary_line(rep))


class CliExitCodeTest(unittest.TestCase):
    """Код возврата — ЕДИНСТВЕННЫЙ канал недоставки для обёртки цикла (ADR-084)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        spec = importlib.util.spec_from_file_location("orchestrator_queue_c345", _CLI)
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)

    def _run_cli(self, tracker: Path, *extra: str) -> int:
        args = self.cli.build_parser().parse_args(
            ["deliver-new", "--check", "--tracker-dir", str(tracker), *extra])
        return args.func(args)

    def test_the_subcommand_exists_and_is_wired(self):
        """Проводка при рождении: без подкоманды обёртка цикла звала бы пустоту."""
        args = self.cli.build_parser().parse_args(["deliver-new", "--check"])
        self.assertTrue(callable(args.func))

    def test_exit_1_when_the_queue_could_not_be_measured(self):
        """Сухой прогон по несверённой очереди — НЕ зелёный: «новых нет» и «новых не
        видно» снаружи одинаковы, и стоила эта неразличимость восьми вопросов (#330)."""
        tracker = self.root / "tracker"
        tracker.mkdir()
        self.assertEqual(self._run_cli(tracker), 1)

    def test_exit_0_when_the_queue_is_measured_and_empty(self):
        """Обратный контроль: сверено и пусто — законный зелёный."""
        repo = _Repo(self.root / "repo")
        (repo.tracker / ".keep").write_text("", encoding="utf-8")
        repo.commit_all("пустая очередь")
        repo.publish()
        self.assertEqual(self._run_cli(repo.tracker), 0)


class WrapperWiringTest(unittest.TestCase):
    """Скрипт без вызывающего — украшение (класс `new-script-must-be-wired-at-birth`)."""

    WRAPPER = _REPO / "scripts" / "agent_orchestrator.sh"

    def test_the_cycle_wrapper_calls_the_first_delivery(self):
        text = self.WRAPPER.read_text(encoding="utf-8")
        self.assertIn("deliver-new", text,
                      "обёртка цикла обязана звать первую доставку — иначе вопрос, "
                      "рождённый на ветке, снова доедет только руками")

    def test_the_call_cannot_kill_the_cycle(self):
        """Урок #221: секция, способная уронить обёртку, гасит агента молча."""
        text = self.WRAPPER.read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines()
                    if "deliver-new" in ln and "$PYTHON" in ln)
        self.assertIn("|| true", line,
                      "вызов обязан быть неспособен уронить цикл")

    def test_the_wrapper_says_out_loud_when_the_script_is_missing(self):
        """Прод отстаёт от origin по построению — пропавшая доставка обязана звучать."""
        text = self.WRAPPER.read_text(encoding="utf-8")
        self.assertIn("первая доставка вопросов владельцу НЕ выполнялась", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
