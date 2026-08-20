"""Site Custodian публикует из СВЕЖЕЙ копии — авария 20.08 и её положительный контроль.

Что произошло 20.08 (решение владельца, вариант 1)
--------------------------------------------------
ADR-085 перенёс Site Custodian на Мак ровно затем, чтобы он МОГ снимать табличку
честности: из GitHub Actions это невозможно по построению — пушер по контракту
(`repo_relative_path`, fail-CLOSED) берёт файл только из живого дерева Мака.

На Маке снятие тоже не сработало. Причина ДРУГАЯ и так же структурная:

    `push_to_github.base_version` читает базу как `git cat-file blob HEAD:<путь>`
    в дереве отправляемого файла. Рабочая папка Мака отстаёт от origin на 665
    коммитов (автосинк возит только `spa_core/`, `scripts/`, `tests/` и указатель
    версии не двигает никогда). База — версия 665-коммитной давности, на remote
    лежит сегодняшняя ⇒ `divergence_verdict` = DIVERGED ⇒ пуш отказан.

Отказ был ВЕРНЫЙ: с такой базой мы действительно не знаем, чью правку затираем.
Мы поменяли одну невозможность на другую и до прогона 20.08 этого не знали.

Поэтому лечится не ослаблением стража, а тем, что у публикации появляется честная
база: считаем по живым данным Мака, отправляем из копии, чей HEAD — сегодняшний
origin.

Что честно теряется (проверено тестом `test_a_fresh_base_makes_the_divergence_check_vacuous`)
---------------------------------------------------------------------------------------------
База, равная remote ПО ПОСТРОЕНИЮ, делает проверку расхождения для этого файла
вырожденной: чужую правку в `track_snapshot.json` мы затрём молча. Терпимо ровно
потому, что файл целиком пересчитывается из наших же данных. Это записано тестом,
а не только словами: если однажды решим, что так нельзя, тест назовёт цену.

Устройство набора
-----------------
Здесь работает НАСТОЯЩИЙ git и НАСТОЯЩИЙ `push_to_github.divergence_verdict` —
подставного вердикта нет нигде. Ключевой тест ниже — положительный контроль:
он воспроизводит отставшее дерево 20.08 и краснеет на неисправленном коде.
Маршрут тревог (кому звонить при недоставке) проверяется отдельно —
`test_site_freshness_delivery_route.py` / `test_site_freshness_agent.py`.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]

SNAP_REL = "landing/src/data/track_snapshot.json"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(_REPO / rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=True)


class _StaleTreeFixture(unittest.TestCase):
    """Стенд аварии: origin ушёл вперёд, рабочая копия осталась на старом коммите.

    Это и есть форма Мака 20.08, только в миниатюре: `git fetch` в рабочей копии
    делается (иначе `refs/remotes/origin/main` не существовал бы вовсе), а вот
    HEAD НЕ двигается — ровно как автосинк, который возит каталоги кода и никогда
    не переставляет указатель версии.
    """

    OLD = {"degraded": True, "nav_usd": 100000.00}
    THIRD_PARTY = {"degraded": True, "nav_usd": 100863.31}
    LOCAL = {"degraded": False, "nav_usd": 100863.31}

    def setUp(self):
        self.mod = _load("site_freshness_monitor", "scripts/site_freshness_monitor.py")
        self.pusher = _load("push_probe", "push_to_github.py")
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.origin = root / "origin.git"
        _git(root, "init", "--bare", "-b", "main", str(self.origin))

        self.prod = root / "prod"
        _git(root, "clone", str(self.origin), str(self.prod))
        _git(self.prod, "config", "user.email", "t@example.com")
        _git(self.prod, "config", "user.name", "t")

        snap = self.prod / SNAP_REL
        snap.parent.mkdir(parents=True)
        snap.write_text(json.dumps(self.OLD), encoding="utf-8")
        # Инструмент доставки обязан лежать в копии — `make_fresh_checkout` это проверяет.
        (self.prod / "push_to_github_batch.py").write_text("# stub\n", encoding="utf-8")
        _git(self.prod, "add", "-A")
        _git(self.prod, "commit", "-m", "base")
        _git(self.prod, "push", "origin", "main")

        # ЧУЖАЯ правка приезжает на origin из другого места (у нас — второй клон).
        other = root / "other"
        _git(root, "clone", str(self.origin), str(other))
        _git(other, "config", "user.email", "o@example.com")
        _git(other, "config", "user.name", "o")
        (other / SNAP_REL).write_text(json.dumps(self.THIRD_PARTY), encoding="utf-8")
        _git(other, "add", "-A")
        _git(other, "commit", "-m", "third party")
        _git(other, "push", "origin", "main")

        # Рабочая копия узнаёт про origin, но НЕ переезжает на него.
        _git(self.prod, "fetch", "origin", "main")
        self.head_before = _git(self.prod, "rev-parse", "HEAD").stdout.strip()

        # Локально посчитанный снимок (то, что мы хотим опубликовать).
        snap.write_text(json.dumps(self.LOCAL), encoding="utf-8")
        self.snap = snap
        self.remote_sha = self.pusher.git_blob_sha(
            json.dumps(self.THIRD_PARTY).encode("utf-8"))
        self.dest = root / "publish"

    def _verdict(self, tree: Path) -> dict:
        return self.pusher.divergence_verdict(
            tree / SNAP_REL, SNAP_REL, self.remote_sha, "main")

    def _publish(self, rc: int = 0):
        """Настоящая публикация: git работает по-настоящему, подставной только пушер.

        `real_run` берётся ДО подмены намеренно. `self.mod.subprocess` — это тот же
        объект модуля `subprocess`, что и здесь, поэтому `mock.patch.object` меняет
        `run` глобально; вызов `subprocess.run` внутри side_effect после подмены
        ушёл бы в мок сам к себе. Первая версия этого стенда так и делала, и тест
        «копия убрана» проходил ДАЖЕ СО СНЯТОЙ УБОРКОЙ — поймано мутацией, а не
        глазами (класс «положительный контроль оказался украшением»).
        """
        seen = {}
        real_run = subprocess.run

        def _run(cmd, *a, **k):
            if len(cmd) > 1 and str(cmd[1]).endswith("push_to_github_batch.py"):
                seen["cmd"] = [str(c) for c in cmd]
                seen["cwd"] = str(k.get("cwd"))
                seen["bytes"] = Path(cmd[cmd.index("--files") + 1]).read_bytes()
                return mock.Mock(returncode=rc)
            return real_run(cmd, *a, **k)

        with mock.patch.object(self.mod.subprocess, "run", _run):
            res = self.mod.publish_from_fresh_checkout(
                self.snap, "msg", root=self.prod, dest=self.dest)
        return res, seen


class TestTheFailureOf20August(_StaleTreeFixture):
    """Положительный контроль: снимите починку — и этот класс краснеет."""

    def test_the_stale_working_copy_is_refused(self):
        """Так выглядела авария: отказ верный, и публиковать оттуда нечем."""
        v = self._verdict(self.prod)
        self.assertEqual(v["state"], self.pusher.DIVERGENCE_DIVERGED,
                         "рабочая папка отстала — база не сегодняшняя, отказ обязан быть")

    def test_a_fresh_checkout_is_safe_to_publish_from(self):
        """Починка: у копии база — сегодняшний origin, расхождения НЕТ."""
        info = self.mod.make_fresh_checkout(self.prod, self.dest)
        self.addCleanup(self.mod.drop_fresh_checkout, self.prod, self.dest)
        v = self._verdict(self.dest)
        self.assertEqual(v["state"], self.pusher.DIVERGENCE_SAFE,
                         "точка отсчёта = origin ⇒ терять нечего")
        self.assertEqual(
            info["head"],
            _git(self.prod, "rev-parse", "refs/remotes/origin/main").stdout.strip())

    def test_the_working_copy_head_is_not_moved(self):
        """Вариант 2 владелец отклонил: рабочую папку мы НЕ трогаем.

        Обратный контроль к самой починке — если бы мы «просто подтянули указатель»,
        сотни отсутствующих на Маке файлов начали бы числиться удалёнными.
        """
        self.mod.make_fresh_checkout(self.prod, self.dest)
        self.addCleanup(self.mod.drop_fresh_checkout, self.prod, self.dest)
        self.assertEqual(_git(self.prod, "rev-parse", "HEAD").stdout.strip(),
                         self.head_before)

    def test_a_fresh_base_makes_the_divergence_check_vacuous(self):
        """Цена починки, названная вслух (см. докстринг модуля).

        База копии равна remote ПО ПОСТРОЕНИЮ, поэтому вердикт «безопасно» здесь
        не означает «чужой правки не было» — он означает «мы её не увидим».
        Терпимо только потому, что файл машинно-генерируемый.
        """
        self.mod.make_fresh_checkout(self.prod, self.dest)
        self.addCleanup(self.mod.drop_fresh_checkout, self.prod, self.dest)
        base_state, base_blob, _ = self.pusher.base_version(
            self.dest / SNAP_REL, SNAP_REL, "main")
        self.assertEqual(base_state, "measured")
        self.assertEqual(self.pusher.git_blob_sha(base_blob), self.remote_sha)


class TestThePublishedBytesAreTheOnesWeComputed(_StaleTreeFixture):
    """Инвариант #8: в копию переносятся ПОСЧИТАННЫЕ числа, а не пересчитанные там."""

    def test_the_local_numbers_are_what_travels(self):
        _, seen = self._publish()
        self.assertEqual(json.loads(seen["bytes"]), self.LOCAL,
                         "опубликовать обязаны локальный расчёт, а не версию origin")

    def test_the_pusher_runs_from_the_fresh_copy(self):
        """Иначе сработает сверка инструмента доставки: деревья-то теперь разные."""
        _, seen = self._publish()
        self.assertEqual(seen["cwd"], str(self.dest))
        self.assertTrue(seen["cmd"][1].startswith(str(self.dest)),
                        f"пушер запущен не из копии: {seen['cmd'][1]}")

    def test_the_file_sent_lives_inside_the_fresh_copy(self):
        _, seen = self._publish()
        sent = seen["cmd"][seen["cmd"].index("--files") + 1]
        self.assertTrue(sent.startswith(str(self.dest)),
                        f"отправлен файл из отставшего дерева: {sent}")

    def test_a_zero_return_code_is_delivered(self):
        res, _ = self._publish(rc=0)
        self.assertTrue(res["delivered"])

    def test_a_refusal_is_reported_honestly(self):
        """Обратный контроль: отказ пушера остаётся отказом, а не тонет в починке."""
        res, _ = self._publish(rc=2)
        self.assertFalse(res["delivered"])
        self.assertEqual(res["reason"], "push_refused")
        self.assertEqual(res["rc"], 2)


class TestTheCopyDoesNotLeak(_StaleTreeFixture):
    """Утёкшая регистрация рабочего дерева каждые 6 ч — своя маленькая авария."""

    def test_the_copy_is_removed_after_publishing(self):
        res, seen = self._publish()
        self.assertTrue(seen, "стенд не дошёл до публикации — тест мерил бы пустоту")
        self.assertTrue(res["delivered"])
        self.assertFalse(self.dest.exists(), "копия осталась на диске")
        self.assertNotIn(str(self.dest),
                         _git(self.prod, "worktree", "list").stdout,
                         "регистрация рабочего дерева утекла в общий git-каталог")

    def test_a_leaked_copy_from_a_killed_run_is_reused_not_multiplied(self):
        """Имя копии стабильное — значит утечь может РОВНО одна, а не по одной за прогон."""
        self.mod.make_fresh_checkout(self.prod, self.dest)  # «убитый» прогон
        info = self.mod.make_fresh_checkout(self.prod, self.dest)  # следующий
        self.addCleanup(self.mod.drop_fresh_checkout, self.prod, self.dest)
        self.assertEqual(info["path"], self.dest)
        listed = _git(self.prod, "worktree", "list").stdout
        self.assertEqual(listed.count(str(self.dest)), 1)


class TestRefusalsAreNamedNotGuessed(_StaleTreeFixture):
    """Fail-CLOSED: чего не смогли — говорим, а не публикуем из отставшей папки."""

    def test_a_non_git_root_refuses(self):
        with TemporaryDirectory() as t:
            with self.assertRaises(self.mod.FreshCheckoutError):
                self.mod.make_fresh_checkout(Path(t), Path(t) / "pub")

    def test_a_file_outside_the_root_is_refused(self):
        with TemporaryDirectory() as t:
            stray = Path(t) / "track_snapshot.json"
            stray.write_text("{}", encoding="utf-8")
            res = self.mod.publish_from_fresh_checkout(
                stray, "msg", root=self.prod, dest=self.dest)
        self.assertFalse(res["delivered"])
        self.assertEqual(res["reason"], "file_outside_root")

    def test_a_failed_fetch_is_named_but_not_fatal(self):
        """Нет сети ⇒ база прошлая ⇒ пушер откажет как раньше. Это невезение, не дыра.

        Молчать об этом нельзя: иначе «база не сегодняшняя» опять станет невидимой —
        ровно тем, чем она была 665 коммитов подряд.
        """
        _git(self.prod, "remote", "set-url", "origin", str(self.prod / "nope.git"))
        info = self.mod.make_fresh_checkout(self.prod, self.dest)
        self.addCleanup(self.mod.drop_fresh_checkout, self.prod, self.dest)
        self.assertFalse(info["fetched"])
        self.assertTrue(info["notes"], "неудачный fetch обязан быть назван в отчёте")


if __name__ == "__main__":
    unittest.main()
