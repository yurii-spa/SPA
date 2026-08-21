#!/usr/bin/env python3
"""Отправитель вопросов владельцу считал очередь по ДЕРЕВУ ЗАПУСКА (авария 21.08, #330).

**Что произошло.** `data/owner_decision_pending.json` за 21.08: восемь карточек
`needs-owner` живут на `origin/main`, у каждой `delivered: false`, заведены 18–19.08.
Владелец не видел их НИ РАЗУ — четвёртый день. Сторож называл все восемь поимённо и был
прав; слеп был ОТПРАВИТЕЛЬ: он перечисляет очередь того дерева, из которого запущен
(прод), а автосинк прод-дерева возит только `spa_core/`·`scripts/`·`tests/` — каталог
`nimbalyst-local/tracker/` не возит никто (#193). Для отправителя этих вопросов не
существовало: `undelivered_count = 0` при восьми реально недоставленных.

Цена ошибки — не косметическая. Цикл #318 исполнял решение владельца «пришлите открытые
вопросы заново, по одному» и честно доложил «отправил 3 из 3»: счёт был починен, слепота —
нет, и восемь вопросов остались невидимыми ровно тем механизмом, который их и должен был
доставить.

**Зеркало уже известного класса.** `inbox-shtorm-prodolzhaetsya-kartochki-tolko-v-host-dereve`
— карточка живёт только в хост-дереве, невозможен ОТВЕТ. Здесь обратное плечо: карточка
живёт только на `origin`, невозможен ВОПРОС. Тот же корень (#231/#232), разные потерпевшие.

Каждый тест ниже — положительный контроль на эту аварию либо обратный контроль на
разрушительную сторону починки (разослать закрытое = воспроизвести жалобу владельца на
поток одинаковых сообщений, #215/#217/#228).

Тесты герметичны: настоящий git в ``tmp_path``, `refs/remotes/*` заводится плумбингом
(`update-ref`), сети нет, ни одна отправка наружу не выполняется.
"""

from __future__ import annotations

import importlib.util
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

NOW = datetime(2026, 8, 21, 9, 0, tzinfo=timezone.utc)
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
    env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "2026-08-21T09:00:00+0000"
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True, text=True, check=True, env=env,
    )


def _card_text(name: str, *, status: str = "needs-owner",
               card_type: str = "owner-decision", marker: str = "") -> str:
    return CARD_TMPL.format(type=card_type, title=f"Вопрос {name}", status=status,
                            marker=marker or f"Тестовая карточка {name}.")


class _Repo:
    """Репозиторий, в котором очередь на `origin/main` ШИРЕ очереди дерева.

    Ровно та конфигурация, что была в проде 21.08: часть карточек запушена сессиями на
    origin и в рабочее дерево не приезжала никогда.
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
        """Убрать карточку с ДИСКА, оставив её на ref — состояние прод-дерева 21.08."""
        for n in names:
            (self.tracker / f"{n}.md").unlink()


def _resend_module():
    from spa_core.owner_queue import resend as R

    return R


def _run(R, tracker: Path, *, dry_run: bool = False, report_path: Path | None = None):
    """Прогон рассылки с перехватом ОТПРАВКИ. Наружу не уходит ничего."""
    sent: list[tuple[str, str, bool]] = []

    def fake_notify(path, *, dry_run=False, owner_requested=False):
        p = Path(path)
        sent.append((p.stem, p.read_text(encoding="utf-8") if p.is_file() else "",
                     owner_requested))
        return "текст"

    with mock.patch("spa_core.owner_queue.notify.notify_needs_owner", fake_notify), \
         mock.patch.object(R, "_measure_delivery", return_value=(True, True, 1)):
        rep = R.resend_open_questions(tracker_dir=tracker, now=NOW, dry_run=dry_run,
                                      sleep=lambda s: None, report_path=report_path)
    return rep, sent


class OriginQueueTest(unittest.TestCase):
    """Ядро аварии: вопрос, которого нет в дереве, обязан дойти до владельца."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _Repo(Path(self._tmp.name) / "repo")
        self.R = _resend_module()

    def _standard_queue(self):
        """Дереву видна одна карточка, на origin — ещё три (живая, закрытая, чужого типа)."""
        self.repo.write("own-visible")
        self.repo.write("own-hidden", marker="ВОПРОС ТОЛЬКО НА ORIGIN")
        self.repo.write("own-closed-on-origin", status="ingested")
        self.repo.write("inbox-hidden", card_type="inbox")
        self.repo.commit_all()
        sha = self.repo.publish()
        self.repo.hide_from_tree("own-hidden", "own-closed-on-origin", "inbox-hidden")
        return sha

    def test_a_question_living_only_on_origin_reaches_the_owner(self):
        """АВАРИЯ 21.08: восемь вопросов `needs-owner` не существовали для отправителя."""
        self._standard_queue()
        rep, sent = _run(self.R, self.repo.tracker)
        self.assertIn("own-hidden", [s[0] for s in sent],
                      "вопрос, живущий только на origin, обязан попасть в рассылку — "
                      "иначе владелец не увидит его никогда")
        self.assertEqual(rep.total, 2)

    def test_a_question_closed_on_origin_is_not_resent(self):
        """Обратный контроль: починка не смеет превратиться в рассыльщика РЕШЁННОГО.

        Владелец жаловался на поток одинаковых сообщений трижды (#215/#217/#228); прислать
        ему закрытый вопрос — воспроизвести жалобу, исполняя его же решение.
        """
        self._standard_queue()
        _, sent = _run(self.R, self.repo.tracker)
        self.assertNotIn("own-closed-on-origin", [s[0] for s in sent])

    def test_only_owner_decision_cards_are_taken_from_origin(self):
        """Обратный контроль: задание (`inbox`) вопросом владельцу не является."""
        self._standard_queue()
        _, sent = _run(self.R, self.repo.tracker)
        self.assertNotIn("inbox-hidden", [s[0] for s in sent])

    def test_the_tree_copy_is_not_duplicated_by_the_origin_copy(self):
        """Карточка, видимая ОБЕИМ сторонам, уходит РОВНО ОДИН раз."""
        self._standard_queue()
        _, sent = _run(self.R, self.repo.tracker)
        ids = [s[0] for s in sent]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertEqual(ids.count("own-visible"), 1)

    def test_the_materialized_card_carries_the_origin_body_under_its_own_id(self):
        """Файл обязан нести ТЕКСТ С REF и имя `<card_id>.md`.

        Имя — не косметика: ключ журнала отправок и callback кнопки берётся из
        ``path.stem``, и любое другое имя развело бы отправку с ответом владельца.
        Текст — не косметика тем более: без тела карточки уедет сообщение без вариантов,
        то есть вопрос, на который нечем ответить с телефона.
        """
        self._standard_queue()
        _, sent = _run(self.R, self.repo.tracker)
        body = next(text for stem, text, _ in sent if stem == "own-hidden")
        self.assertIn("ВОПРОС ТОЛЬКО НА ORIGIN", body)
        self.assertIn("Вариант 1", body, "варианты ответа обязаны доехать целиком")

    def test_origin_card_goes_solicited_like_any_other(self):
        """Заслоны не ослаблены и не усилены: origin-карточка идёт тем же путём.

        `owner_requested` снимает дедуп/анти-шторм ТОЛЬКО потому, что владелец сам
        попросил прислать вопросы заново (решение 20.08, вариант 2).
        """
        self._standard_queue()
        _, sent = _run(self.R, self.repo.tracker)
        self.assertTrue(all(flag for _, _, flag in sent), sent)

    def test_report_names_the_origin_side_of_the_measurement(self):
        """«Сверено» обязано быть измерением: ref, его sha и число origin-only в отчёте."""
        sha = self._standard_queue()
        rep, _ = _run(self.R, self.repo.tracker)
        self.assertTrue(rep.queue_measured)
        self.assertEqual(rep.origin["ref"], REF)
        self.assertEqual(rep.origin["ref_sha"], sha)
        self.assertEqual(rep.origin["origin_only"], 1)
        self.assertIn("только на origin/main", self.R.summary_line(rep))


class QueueUnmeasuredTest(unittest.TestCase):
    """«Померить не смогли» обязано звучать, а не выглядеть как «вопросов нет»."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tracker = Path(self._tmp.name) / "tracker"
        self.tracker.mkdir()
        self.R = _resend_module()

    def _local_card(self):
        (self.tracker / "own-local.md").write_text(_card_text("own-local"),
                                                   encoding="utf-8")

    def test_unmeasured_queue_is_named_and_local_questions_still_go(self):
        """Каталог вне git: сверять не с чем. Молчать об этом нельзя.

        И терять при этом видимые дереву вопросы — тоже: отказ от рассылки был бы
        обменом одной немоты на другую.
        """
        self._local_card()
        rep, sent = _run(self.R, self.tracker)
        self.assertFalse(rep.queue_measured)
        self.assertIn("reason", rep.origin)
        self.assertEqual([s[0] for s in sent], ["own-local"])
        line = self.R.summary_line(rep)
        self.assertIn("НЕ СВЕРЕНА", line)
        self.assertIn("НЕПОЛОН", line)

    def test_empty_and_unmeasured_are_different_statements(self):
        """Пустая очередь без сверки не имеет права читаться как «вопросов нет»."""
        rep, sent = _run(self.R, self.tracker)
        self.assertEqual(sent, [])
        self.assertEqual(rep.total, 0)
        self.assertFalse(rep.queue_measured)
        self.assertIn("НЕ СВЕРЕНА", self.R.summary_line(rep))

    def test_report_on_disk_carries_the_verdict(self):
        """Отчёт на диске — читатель не человек, и ему нужен машинный признак."""
        self._local_card()
        report_path = self.tracker.parent / "report.json"
        rep, _ = _run(self.R, self.tracker, report_path=report_path)
        import json

        doc = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIs(doc["queue_measured"], False)
        self.assertIn("reason", doc["origin"])


class CliExitCodeTest(unittest.TestCase):
    """Код возврата — ЕДИНСТВЕННЫЙ канал недоставки для вызывающего (ADR-084)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        spec = importlib.util.spec_from_file_location("orchestrator_queue_c330", _CLI)
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)

    def _run_cli(self, tracker: Path, *extra: str) -> int:
        args = self.cli.build_parser().parse_args(
            ["resend-open", "--check", "--tracker-dir", str(tracker), *extra])
        return args.func(args)

    def test_exit_1_when_the_queue_could_not_be_measured(self):
        """Сухой прогон по несверённой очереди — НЕ зелёный.

        Зелёный код здесь означал бы «вопросов нет», а на деле означал «вопросов не
        видно»; именно эта неразличимость и держала восемь вопросов невидимыми.
        """
        tracker = self.root / "tracker"
        tracker.mkdir()
        self.assertEqual(self._run_cli(tracker), 1)

    def test_exit_0_when_the_queue_is_measured_and_empty(self):
        """Обратный контроль: сверено и пусто — это законный зелёный."""
        repo = _Repo(self.root / "repo")
        (repo.tracker / ".keep").write_text("", encoding="utf-8")
        repo.commit_all("пустая очередь")
        repo.publish()
        self.assertEqual(self._run_cli(repo.tracker), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
