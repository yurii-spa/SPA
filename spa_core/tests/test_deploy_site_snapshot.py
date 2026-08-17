"""Доставка снимка трека на публичный сайт — разбор простоя 2026-08-08.

Замер: `landing/src/data/track_snapshot.json` пересобирался каждым прогоном цикла и НЕ
уезжал ни разу. Публичный сайт стоял на `2026-08-06` (44 дня трека) при API `46.0`, а в
журнале цикла подряд стояло пятнадцать строк «push FAILED» без единого слова о причине —
шаг помечен non-fatal, поэтому цикл рапортовал успех. Правду сказал ровно один сторож —
Site Custodian, и то владельцу в Telegram («Это почини»).

Дефектов было ТРИ, и нужны были все три, чтобы простой прожил двое суток:

1. пуш `landing/**` шёл напрямую через `push_to_github_batch.py`, минуя `safe_site_push.py` —
   единственный санкционированный путь (протокол §3.4); попутно не писался ресит доставки,
   который умеет писать только обёртка (ADR-066 B3);
2. страж перезаписи отказывал (rc=4) на ЦЕЛИКОМ ГЕНЕРИРУЕМОМ артефакте: его версия на remote
   не чужая правка, а прошлое поколение того же генератора — страж честно краснел на верное
   состояние и запирал доставку навсегда;
3. `print(stdout or stderr)` выбрасывал текст отказа: stdout к тому моменту непустой
   («Batch-пуш … base commit …»), поэтому stderr не печатался НИКОГДА.

Каждый тест ниже — положительный контроль: снимаешь починку, и тест краснеет ровно тем
поведением, на которое жаловался владелец. Проверка, не видевшая настоящей поломки, —
украшение (правило `.claude/rules/deployment.md`).
"""
# FROZEN-DATE-OK: даты здесь — дословная полезная нагрузка аварии 2026-08-08 (снимок as_of
# 2026-08-08 / 46 дней против застрявшего на публичном сайте 2026-08-06 / 44 дня), то есть
# сама дата и есть предмет. Признаком свежести она НЕ является: ни один тест в файле не
# спрашивает часы — даты лежат внутри JSON-фикстуры и сравниваются на равенство содержимого,
# поэтому сдвиг календаря поведения не меняет.
from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]

_SNAPSHOT = {
    "as_of": "2026-08-08",
    "real_track_days": 46,
    "paper_apy_pct": 5.1927,
    "generated_at": "2026-08-08T14:31:53Z",
}
# Та же полезная нагрузка, что уже лежит на origin, но с ДРУГОЙ волатильной отметкой:
# по смыслу это тот же снимок, деплоить нечего.
_SAME_DATA_OLDER_STAMP = {**_SNAPSHOT, "generated_at": "2026-08-08T09:00:00Z"}
_ORIGIN_STALE = {**_SNAPSHOT, "as_of": "2026-08-06", "real_track_days": 44}


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(_REPO / rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Result:
    """Минимальный двойник CompletedProcess — нам важны только три поля."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class _DeployHarness(unittest.TestCase):
    """Общая оснастка: снимок в темпе, генератор и пуш — под контролем."""

    def setUp(self):
        self.mod = _load("deploy_site_snapshot", "scripts/deploy_site_snapshot.py")
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.snap = Path(self._tmp.name) / "track_snapshot.json"
        self.snap.write_text(json.dumps(_SNAPSHOT))
        patcher = mock.patch.object(self.mod, "_SNAP", self.snap)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Канон (ADR-070 п.2) — тоже в темпе: доставка проверяет его наличие и
        # неизменность, и делать это ПРОТИВ ЖИВОГО `data/` репозитория тест не имеет
        # права (герметичность; правило `.claude/rules/deployment.md` — data/ не трогаем).
        self.root = Path(self._tmp.name) / "root"
        for rel in self.mod._CANON:
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"fixture": rel}))
        root_patcher = mock.patch.object(self.mod, "_ROOT", self.root)
        root_patcher.start()
        self.addCleanup(root_patcher.stop)
        self.calls: list[list[str]] = []

    def _run_main(self, *, push=None, gen=None, origin=_ORIGIN_STALE, on_origin_read=None):
        """Прогоняет main(), подменив подпроцессы. Возвращает (rc, напечатанное)."""
        push = push or _Result(0, "pushed", "")
        gen = gen or _Result(0, "track_snapshot.json regenerated", "")

        def fake_run(cmd, *a, **kw):
            self.calls.append([str(c) for c in cmd])
            return gen if str(cmd[1]).endswith("generate_track_snapshot.py") else push

        def fake_origin():
            if on_origin_read is not None:
                on_origin_read()
            return origin

        printed: list[str] = []
        with mock.patch.object(self.mod.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(self.mod, "_origin_snapshot", side_effect=fake_origin), \
             mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(
                 " ".join(str(x) for x in a))):
            rc = self.mod.main()
        return rc, "\n".join(printed)

    @property
    def push_cmd(self) -> list[str]:
        """Команда доставки (второй подпроцесс). Пусто, если пуша не было."""
        for c in self.calls:
            if not str(c[1]).endswith("generate_track_snapshot.py"):
                return c
        return []

    @property
    def pushed_files(self) -> list[str]:
        """Аргументы `--files` — до следующего флага (иначе в список попадёт --message)."""
        cmd = self.push_cmd
        out = []
        for token in cmd[cmd.index("--files") + 1:]:
            if token.startswith("--"):
                break
            out.append(token)
        return out


class TestSanctionedDeliveryPath(_DeployHarness):
    """Дефект 1 — landing/** уезжал в обход единственного санкционированного пути."""

    def test_delivers_through_safe_site_push(self):
        rc, _ = self._run_main()
        self.assertEqual(rc, 0)
        self.assertTrue(self.push_cmd, "доставки не было вовсе")
        self.assertTrue(
            self.push_cmd[1].endswith("scripts/safe_site_push.py"),
            f"landing/** обязан уезжать через safe_site_push.py (owner-гейт + ресит доставки), "
            f"а команда была: {self.push_cmd[1]}",
        )

    def test_never_calls_the_batch_pusher_directly(self):
        """Прямой batch-пушер — это и обход owner-гейта, и отсутствие ресита доставки."""
        self._run_main()
        self.assertNotIn(
            "push_to_github_batch.py", self.push_cmd[1],
            "прямой вызов batch-пушера для landing/** запрещён протоколом §3.4",
        )

    def test_pushes_the_snapshot_and_only_its_canon(self):
        """Закрытый набор: снимок + РОВНО три файла канона, ничего сверх.

        ИЗМЕНЕНИЕ ТЕСТА (инвариант #16, обоснование). Раньше здесь стояло
        `pushed_files == [snapshot]` — «один файл, иначе деплой тянет чужие изменения».
        Проверяемое свойство — «в коммит сайта не попадает лишнее» — сохранено дословно;
        изменилось ЧТО считается лишним. По решению владельца 2026-08-16 (карточка
        `owner-decision-storozh-saita-ne-kladet-v-git-dannye-iz`, вариант 1 = ADR-070 п.2)
        канон трека едет в ТОМ ЖЕ коммите: без него owner-gate не может пересчитать
        изменившееся число и заворачивает честную ночную доставку, а числа сайта нельзя
        проверить из репозитория. Прежняя форма запрещала бы ровно исполнение решения.
        Ослабления нет: набор по-прежнему закрыт и сверяется поимённо, а «ничего лишнего
        из data/» отдельно держит `test_site_custodian_commits_canon.py`.
        """
        self._run_main()
        self.assertEqual(self.pushed_files[0], str(self.snap))
        self.assertEqual(
            [Path(p).name for p in self.pushed_files[1:]],
            [Path(rel).name for rel in self.mod._CANON],
            "в коммит сайта едут снимок и только его канон",
        )


class TestOverwriteIsDeclaredNotSilenced(_DeployHarness):
    """Дефект 2 — страж перезаписи запирал доставку целиком генерируемого артефакта."""

    def test_declares_intentional_overwrite(self):
        self._run_main()
        self.assertIn(
            "--allow-overwrite", self.push_cmd,
            "без объявленного намерения страж расхождения отказывает (rc=4) на КАЖДОМ прогоне: "
            "именно так сайт замёрз на 2026-08-06",
        )

    def test_refuses_when_snapshot_changed_after_generation(self):
        """Fail-CLOSED: перезапись разрешена только для того, что сгенерировали САМИ.

        Если файл на диске тронул кто-то ещё (параллельный писатель), мы больше не знаем,
        что именно затираем на remote, — и не затираем.
        """
        def touch():
            self.snap.write_text(json.dumps({**_SNAPSHOT, "real_track_days": 999}))

        rc, out = self._run_main(on_origin_read=touch)
        self.assertEqual(rc, 1)
        self.assertFalse(self.push_cmd, "затирать remote неизвестным содержимым нельзя")
        self.assertIn("changed after generation", out)

    def test_overwrite_flag_is_not_a_blanket_permission(self):
        """Флаг сопровождает ЗАКРЫТЫЙ набор: снимок + его канон, и ничего больше.

        ИЗМЕНЕНИЕ ТЕСТА (инвариант #16, обоснование). Было `len(pushed_files) == 1`.
        Смысл проверки — «осознанная перезапись не превращается в разрешение затирать
        что угодно» — сохранён: набор фиксирован (1 снимок + `_CANON`) и растёт только
        решением владельца. Число 1 стало неверным после ADR-070 п.2 (канон едет тем же
        коммитом); ровно на этих файлах перезапись остаётся осознанной, потому что их
        целиком производит тот же дневной цикл на той же машине.
        """
        self._run_main()
        self.assertEqual(len(self.pushed_files), 1 + len(self.mod._CANON))


class TestFailureReasonSurvives(_DeployHarness):
    """Дефект 3 — `stdout or stderr` выбрасывал ровно ту строку, ради которой читают лог."""

    # Дословно то, что печатал пушер 2026-08-08: stdout непустой, причина — в stderr.
    _STDOUT = "Batch-пуш 1 файл(ов) → yurii-spa/SPA (main) ОДНИМ коммитом...\n  base commit: e8dce81f"
    _STDERR = ("ОТКАЗ (страж перезаписи): содержимое landing/src/data/track_snapshot.json "
               "на remote изменилось после нашей базы")

    def test_refusal_reason_is_printed(self):
        rc, out = self._run_main(push=_Result(4, self._STDOUT, self._STDERR))
        self.assertEqual(rc, 1)
        self.assertIn(
            "страж перезаписи", out,
            "причина отказа обязана попасть в лог цикла: шаг non-fatal, и без неё в журнале "
            "остаётся «push FAILED» без объяснения — так и прожил простой двое суток",
        )

    def test_failure_line_carries_the_return_code(self):
        _, out = self._run_main(push=_Result(4, self._STDOUT, self._STDERR))
        self.assertIn("rc=4", out, "код возврата отличает отказ стража (4) от гейта (2/3)")

    def test_both_streams_are_kept(self):
        """Положительный контроль на сам помощник: старая форма вернула бы только stdout."""
        self.assertEqual(
            self.mod._both(_Result(4, "OUT", "ERR")), "OUT\nERR",
        )
        self.assertEqual(self.mod._both(_Result(0, "", "ERR")), "ERR")
        self.assertEqual(self.mod._both(_Result(0, "OUT", "")), "OUT")


class TestNoNeedlessDeploys(_DeployHarness):
    """Поведение, которое починка обязана СОХРАНИТЬ."""

    def test_no_push_when_origin_already_has_the_same_data(self):
        rc, out = self._run_main(origin=_SAME_DATA_OLDER_STAMP)
        self.assertEqual(rc, 0)
        self.assertFalse(self.push_cmd, "пустой деплой ради одной волатильной отметки времени")
        self.assertIn("no deploy needed", out)

    def test_pushes_when_origin_is_unreadable(self):
        """Не прочитали origin ⇒ пушим (молча пропустить доставку — худший исход)."""
        self._run_main(origin=None)
        self.assertTrue(self.push_cmd)

    def test_generator_failure_blocks_the_push(self):
        rc, _ = self._run_main(gen=_Result(1, "", "boom"))
        self.assertEqual(rc, 1)
        self.assertFalse(self.push_cmd, "нельзя публиковать снимок, который не собрался")


class TestSafeSitePushOverwritePassthrough(unittest.TestCase):
    """Обёртка обязана уметь пробросить намерение — и НЕ обязана ослаблять owner-гейт."""

    def setUp(self):
        self.mod = _load("safe_site_push", "scripts/safe_site_push.py")
        self.calls: list[list[str]] = []

    def _push(self, argv, guard_rc=0):
        def fake_run(cmd, *a, **kw):
            self.calls.append([str(c) for c in cmd])
            return _Result(0, "", "")

        with mock.patch.object(self.mod, "_run_guard", return_value=(guard_rc, {})), \
             mock.patch.object(self.mod, "_route_to_owner_card"), \
             mock.patch.object(self.mod.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(self.mod, "write_receipt", create=True):
            return self.mod.main(argv)

    def test_flag_reaches_the_batch_pusher(self):
        self._push(["--files", "landing/src/data/track_snapshot.json",
                    "--message", "m", "--allow-overwrite"])
        self.assertIn("--allow-overwrite", self.calls[0])

    def test_absent_by_default(self):
        """Флаг именно ОСОЗНАННЫЙ: для обычной правки сайта страж остаётся во весь рост."""
        self._push(["--files", "landing/src/pages/index.astro", "--message", "m"])
        self.assertNotIn("--allow-overwrite", self.calls[0])

    def test_overwrite_does_not_bypass_the_owner_gate(self):
        """Главное: намерение относится к стражу РАСХОЖДЕНИЯ, а не к праву публиковать.

        Owner-гейт проверяется РАНЬШЕ и отменить его этим флагом нельзя — иначе автономный
        цикл получил бы дорогу к числам доходности и legal-формулировкам в обход владельца.
        """
        rc = self._push(["--files", "landing/src/pages/index.astro",
                         "--message", "m", "--allow-overwrite"], guard_rc=2)
        self.assertEqual(rc, 2)
        self.assertEqual(self.calls, [], "owner-gated правка не имеет права уехать")


if __name__ == "__main__":
    unittest.main()
