"""Публичный /changelog: у производителя обязан быть вызывающий, а у пустоты — честная фраза.

Замер 2026-08-09 (карточка `agent-changelog-generator-never-called`):
`scripts/generate_research_changelog.py` доставлен, покрыт зелёными тестами и НЕ ИМЕЕТ НИ ОДНОГО
вызывающего — ни агента во флоте, ни шага цикла, ни строки в обёртках. Публичная страница из-за
этого 23 дня показывала дайджест от 2026-07-11. Седьмой случай класса «код есть, никто не зовёт».

Старые тесты (`test_research_changelog.py`) остались зелёными весь этот месяц — они проверяли
ДЕТАЛЬ (шаблон дайджеста), а не то, включена ли деталь в проводку (урок цикла #144). Поэтому здесь
проверяется ровно то, чего не проверял никто:

1. **Проводка** — генератор вызывается из дневного цикла тем же механизмом, которым уже доставляется
   `track_snapshot.json` (шаг цикла → `safe_site_push.py`), и второго механизма не заведено.
2. **Накопительный файл не затирается вслепую** — `changelog.json` дописывается к версии с origin;
   origin не прочитан ⇒ НЕ публикуем (стереть опубликованные записи хуже, чем день не обновиться).
3. **Пустота названа словами** — статус проверки пишется в КАЖДОМ прогоне, включая отказной, и
   страница говорит «проверено тогда-то, изменений с такой-то даты нет» вместо немого пробела.
   Выдуманных записей при этом не появляется никогда.

Каждый тест — положительный контроль: снимаешь починку, и он краснеет ровно тем поведением, на
которое жаловалась карточка. Часов ни один тест не спрашивает: дата проверки — ВХОД генератора
(`--date`), поэтому файл детерминирован и календарь его не двигает.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
_CYCLE = _REPO / "scripts" / "run_daily_paper_cycle.sh"
_PAGE = _REPO / "landing" / "src" / "pages" / "changelog.astro"
_STATUS_FILE = _REPO / "landing" / "src" / "data" / "changelog_status.json"

rcg = importlib.import_module("scripts.generate_research_changelog")


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(_REPO / rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


# ── 1. Проводка ─────────────────────────────────────────────────────────────
class TestTheGeneratorHasACaller(unittest.TestCase):
    """Главное: раздел обновляется потому, что его КТО-ТО ЗОВЁТ."""

    def setUp(self):
        self.cycle = _CYCLE.read_text(encoding="utf-8")
        self.deploy = (_REPO / "scripts" / "deploy_research_changelog.py").read_text(encoding="utf-8")

    def test_daily_cycle_runs_the_changelog_custodian(self):
        self.assertIn("deploy_research_changelog.py", self.cycle,
                      "генератор снова без вызывающего — раздел замрёт, как замер на 23 дня")

    def test_the_custodian_actually_calls_the_generator(self):
        self.assertIn("generate_research_changelog.py", self.deploy,
                      "шаг цикла есть, а генератор в нём не зовётся — проводка мнимая")

    def test_the_cycle_step_is_non_fatal(self):
        """Сайт не имеет права уронить трек: шаг обязан быть в той же форме, что шаги 3-4."""
        step = self.cycle.split("deploy_research_changelog.py", 1)[1][:200]
        self.assertIn("non-fatal", step)

    def test_delivery_goes_through_the_sanctioned_path_only(self):
        """landing/** уезжает ТОЛЬКО через safe_site_push (owner-гейт + ресит доставки, §3.4)."""
        self.assertIn("safe_site_push.py", self.deploy)
        self.assertNotIn("push_to_github_batch.py", self.deploy,
                         "прямой batch-пушер для landing/** — обход owner-гейта")

    def test_no_second_mechanism_was_introduced(self):
        """Ни нового агента во флоте, ни нового workflow — механизм переиспользован."""
        plists = list((_REPO / "launchd").glob("*.plist")) if (_REPO / "launchd").exists() else []
        for p in plists:
            self.assertNotIn("research_changelog", p.read_text(encoding="utf-8", errors="ignore"),
                             f"{p.name}: заведён второй механизм вместо шага цикла")
        wf_dir = _REPO / ".github" / "workflows"
        for w in (wf_dir.glob("*.yml") if wf_dir.exists() else []):
            self.assertNotIn("research_changelog", w.read_text(encoding="utf-8", errors="ignore"),
                             f"{w.name}: заведён второй механизм вместо шага цикла")


# ── 2. Накопительная история не затирается вслепую ──────────────────────────
class _DeployHarness(unittest.TestCase):
    """Оснастка: дерево в темпе, генератор и пуш — под контролем."""

    def setUp(self):
        self.mod = _load("deploy_research_changelog", "scripts/deploy_research_changelog.py")
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        (root / "landing" / "src" / "data").mkdir(parents=True)
        p = mock.patch.object(self.mod, "_ROOT", root)
        p.start()
        self.addCleanup(p.stop)
        self.root = root
        self.changelog = root / self.mod._CHANGELOG_REL
        self.status = root / self.mod._STATUS_REL
        self.calls: list[list[str]] = []

    def _write_local(self, entries, status=None):
        self.changelog.write_text(json.dumps(entries), encoding="utf-8")
        self.status.write_text(json.dumps(status or {"checked_date": "2026-08-16"}), encoding="utf-8")

    def _run(self, *, origin, origin_status=("{}", "ok"), gen=None, push=None,
             generator_writes=None, after_generation=None):
        """origin — (text|None, kind) для changelog.json.

        `after_generation` срабатывает при чтении origin-версии статуса, то есть УЖЕ ПОСЛЕ того,
        как отпечатки собранного сняты, — так имитируется чужой писатель между генерацией и пушем.
        """
        gen = gen or _Result(0, "[changelog] no new entry: unchanged data", "")
        push = push or _Result(0, "pushed", "")

        def fake_run(cmd, *a, **kw):
            self.calls.append([str(c) for c in cmd])
            if str(cmd[1]).endswith("generate_research_changelog.py"):
                if generator_writes is not None:
                    generator_writes()
                return gen
            return push

        def fake_origin(rel, branch="main"):
            if rel == self.mod._CHANGELOG_REL:
                return origin
            if after_generation is not None:
                after_generation()
            return origin_status

        printed: list[str] = []
        with mock.patch.object(self.mod.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(self.mod, "_origin_text", side_effect=fake_origin), \
             mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(
                 " ".join(str(x) for x in a))):
            rc = self.mod.main(["--date", "2026-08-16"])
        return rc, "\n".join(printed)

    @property
    def push_cmd(self) -> list[str]:
        for c in self.calls:
            if str(c[1]).endswith("safe_site_push.py"):
                return c
        return []


class TestCumulativeHistoryIsNeverClobbered(_DeployHarness):
    """`changelog.json` НАКОПИТЕЛЬНЫЙ — в отличие от целиком генерируемого снимка трека."""

    _ORIGIN = json.dumps([{"slug": "changelog-2026-07-11", "date": "2026-07-11"}])

    def test_local_file_is_seeded_from_origin_before_generating(self):
        """Дерево дрейфует от origin: дописывать можно только к ОПУБЛИКОВАННОМУ."""
        self._write_local([])  # локально пусто — запись с origin здесь отсутствует
        self._run(origin=(self._ORIGIN, "ok"))
        self.assertEqual(json.loads(self.changelog.read_text())[0]["date"], "2026-07-11",
                         "опубликованная запись потерялась бы при первом же пуше")

    def test_refuses_to_publish_when_origin_is_unreadable(self):
        """Fail-CLOSED. Здесь НЕЛЬЗЯ «пушить на всякий случай», как со снимком трека:
        снимок пересобирается целиком, а тут перезапись стирает историю."""
        self._write_local([{"slug": "x", "date": "2026-08-16"}])
        rc, out = self._run(origin=(None, "error"))
        self.assertEqual(rc, 1)
        self.assertFalse(self.push_cmd, "публиковать поверх непрочитанного origin запрещено")
        self.assertIn("fail-CLOSED", out)

    def test_absent_on_origin_is_not_an_error(self):
        """Файла на origin ещё нет — это начало истории, а не сбой."""
        self._write_local([])
        rc, _ = self._run(origin=(None, "absent"))
        self.assertEqual(rc, 0)

    def test_no_push_when_origin_already_matches(self):
        self._write_local(json.loads(self._ORIGIN))
        origin_status = (self.status.read_text(), "ok")
        rc, out = self._run(origin=(self._ORIGIN, "ok"), origin_status=origin_status)
        self.assertEqual(rc, 0)
        self.assertFalse(self.push_cmd, "пустой деплой ради неизменного содержимого")
        self.assertIn("деплой не нужен", out)

    def test_refuses_when_files_change_after_generation(self):
        """Перезапись объявлена только для того, что собрали САМИ в этом прогоне.

        Тронул файл кто-то ещё — мы больше не знаем, ЧТО именно затираем на remote, и не
        затираем: у накопительного файла ценой ошибки была бы стёртая публичная история.
        """
        self._write_local([])

        def meddle():  # чужой писатель между генерацией и пушем
            self.status.write_text(json.dumps({"checked_date": "чужая правка"}), encoding="utf-8")

        rc, out = self._run(origin=(self._ORIGIN, "ok"), after_generation=meddle)
        self.assertEqual(rc, 1)
        self.assertFalse(self.push_cmd)
        self.assertIn("после генерации", out)

    def test_push_declares_the_intentional_overwrite(self):
        self._write_local([])
        self._run(origin=(self._ORIGIN, "ok"))
        self.assertIn("--allow-overwrite", self.push_cmd,
                      "без объявленного намерения страж расхождения запирает доставку навсегда")

    def test_generator_failure_blocks_publication(self):
        self._write_local([])
        rc, _ = self._run(origin=(self._ORIGIN, "ok"), gen=_Result(1, "", "boom"))
        self.assertEqual(rc, 1)
        self.assertFalse(self.push_cmd)

    def test_push_failure_reason_reaches_the_log(self):
        """Шаг non-fatal: без причины в журнале останется «push FAILED» без объяснения."""
        self._write_local([])
        rc, out = self._run(origin=(self._ORIGIN, "ok"),
                            push=_Result(2, "Batch-пуш 2 файла...", "ОТКАЗ (owner-гейт)"))
        self.assertEqual(rc, 1)
        self.assertIn("rc=2", out)
        self.assertIn("owner-гейт", out)


# ── 3. Пустота названа словами ──────────────────────────────────────────────
class TestSilenceIsSpokenNotShown(unittest.TestCase):
    """«Нечего публиковать» и «производителя не звали» обязаны РАЗЛИЧАТЬСЯ на странице."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        t = Path(self._tmp.name)
        self.out = t / "changelog.json"
        self.status = t / "changelog_status.json"
        self.ledger = t / "track_ledger.json"
        self.decisions = t / "decision_log.jsonl"
        for attr, val in (("_OUT", self.out), ("_STATUS", self.status),
                          ("_LEDGER", self.ledger), ("_DECISIONS", self.decisions)):
            p = mock.patch.object(rcg, attr, val)
            p.start()
            self.addCleanup(p.stop)

    def _live_data(self, days=19, last="2026-07-10"):
        self.ledger.write_text(json.dumps({
            "n_evidenced_days": days, "days_needed": 30, "cumulative_return_pct": 0.21,
            "max_drawdown_from_peak_pct": 0.0, "last_evidenced_date": last}))
        self.decisions.write_text(json.dumps({"approved": False}) + "\n")

    def test_status_is_written_when_a_digest_appears(self):
        self._live_data()
        rcg.generate(date="2026-08-16")
        s = json.loads(self.status.read_text())
        self.assertEqual(s["state"], rcg.STATE_NEW)
        self.assertEqual(s["checked_date"], "2026-08-16")
        self.assertEqual(s["last_entry_date"], "2026-08-16")

    def test_status_is_written_when_there_is_nothing_new(self):
        """Тот самый случай, который на странице выглядел как заброшенный продукт."""
        self._live_data()
        rcg.generate(date="2026-08-15")
        rcg.generate(date="2026-08-16")
        s = json.loads(self.status.read_text())
        self.assertEqual(s["state"], rcg.STATE_UNCHANGED)
        self.assertEqual(s["checked_date"], "2026-08-16", "дата ПРОВЕРКИ обязана двигаться")
        self.assertEqual(s["last_entry_date"], "2026-08-15", "дата ЗАПИСИ двигаться не имеет права")

    def test_status_is_written_even_when_the_generator_refuses(self):
        """Отказ — тоже проверка. Молчание отказного прогона и было неотличимо от простоя."""
        r = rcg.generate(date="2026-08-16")
        self.assertFalse(r["created"])
        s = json.loads(self.status.read_text())
        self.assertEqual(s["state"], rcg.STATE_NO_DATA)
        self.assertEqual(s["checked_date"], "2026-08-16")
        self.assertEqual(json.loads(self.out.read_text()) if self.out.exists() else [], [],
                         "выдуманной записи при отсутствии данных быть не должно")

    def test_status_asks_no_clock(self):
        """Дата — ВХОД, а не окружение: содержимое определено аргументом, а не часами.

        Литеральная дата здесь не бомба замедленного действия (правило `deployment.md`):
        сдвиг календаря на результат не влияет, потому что часов никто не спрашивает.
        """
        self._live_data()
        rcg.generate(date="2026-08-16")
        self.assertEqual(json.loads(self.status.read_text()), {
            "checked_date": "2026-08-16",
            "state": rcg.STATE_NEW,
            "last_entry_date": "2026-08-16",
            "n_entries": 1,
        })

    def test_generate_without_write_touches_nothing(self):
        self._live_data()
        rcg.generate(date="2026-08-16", write=False)
        self.assertFalse(self.status.exists())
        self.assertFalse(self.out.exists())


class TestThePageSpeaksTheState(unittest.TestCase):
    """Страница обязана ЧИТАТЬ статус и превращать его в человеческую фразу."""

    def setUp(self):
        self.page = _PAGE.read_text(encoding="utf-8")

    def test_page_reads_the_status_file(self):
        """Проверяется ИМПОРТ, а не упоминание имени.

        Первая редакция этого теста искала подстроку `changelog_status.json` — и осталась
        ЗЕЛЁНОЙ на мутации, которая увела импорт: имя файла продолжало стоять в соседнем
        комментарии. Ровно та слепота, которую проект уже лечил у храповика неподключённых
        скриптов (цикл #227): упоминание — не вызов. Поймано собственной мутацией.
        """
        self.assertIn("import('../data/changelog_status.json')", self.page,
                      "без статуса страница снова не отличит «нет изменений» от «никто не звал»")

    def test_page_states_since_when_nothing_changed(self):
        self.assertIn("has not changed since", self.page)
        self.assertIn("не менялись с", self.page)

    def test_page_admits_when_it_does_not_know(self):
        """Нет статуса ⇒ так и сказано. Молча выглядеть свежим — запрещено."""
        self.assertIn("cannot say when", self.page)
        self.assertIn("сказать нельзя", self.page)

    def test_page_is_bilingual_on_the_new_copy(self):
        self.assertIn("data-ru={noteRu}", self.page)

    def test_status_file_exists_and_parses(self):
        """Astro резолвит импорт на СБОРКЕ: отсутствующий файл — это падение билда сайта."""
        s = json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
        self.assertIn("state", s)
        self.assertIn("checked_date", s)

    def test_seed_status_does_not_invent_a_check_date(self):
        """Пока никто не звал генератор, честный ответ — «даты проверки нет»."""
        s = json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
        if s["state"] == "never_checked":
            self.assertIsNone(s["checked_date"])


if __name__ == "__main__":
    unittest.main()
