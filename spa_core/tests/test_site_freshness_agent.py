"""Site Custodian получил ТЕЛО на Маке — иначе работала ровно половина правила честности.

Что было измерено (14.08, карточка `owner-decision-stranitsa-treka-chetvertyi-den-pryachet`)
--------------------------------------------------------------------------------------------
На `earn-defi.com/track-record/` четвёртый день висела табличка «живые данные временно
недоступны». Повесил её наш собственный сторож `site_freshness_monitor` — и правильно
повесил. А вот СНЯТЬ её было некому: launchd-агента у монитора не было вовсе, жил он
только в GitHub Actions (`.github/workflows/site_freshness.yml`, каждые 6 ч).

Из облака снятие невозможно НЕ ПО ПОЛОМКЕ, А ПО ПОСТРОЕНИЮ. Обе стороны таблички
доставляются пушером, а `push_to_github.repo_relative_path` по контракту (fail-CLOSED)
отдаёт путь внутри репозитория только для файла из живого дерева Мака или его worktree.
В раннере дерево лежит по `/home/runner/work/SPA/SPA` — контракт не выполняется никогда,
ни при какой погоде. То есть система умела ПОВЕСИТЬ табличку и не умела СНЯТЬ её вообще:
при каждом срабатывании сайт замирал бы ровно так же надолго.

Решение владельца 2026-08-14T12:26:56Z (telegram), вариант 1: «дать снятие таблички Маку».
Облачный прогон при этом остаётся вторым, независимым глазом — на случай спящего Мака.

Почему тесты именно такие
-------------------------
Проверять здесь надо ПРОВОДКУ, а не части: логика самого монитора закрыта
`test_site_freshness_monitor.py`, а недоставка из CI — `test_site_freshness_delivery_route.py`.
Оба набора были ЗЕЛЁНЫМИ всё то время, пока табличка висела: они отвечали на свои вопросы
(«верно ли сторож судит?», «молчит ли он, когда доставить нечем?») и ни один — на нужный
(«а есть ли вообще, кому это запустить оттуда, где доставка возможна?»). Ровно тот класс,
что описан в `.claude/rules/deployment.md`.

Каждый тест ниже — положительный контроль: сними починку (удали plist · сними бит с обёртки ·
убери её из установщика · оберни код возврата в ноль · выкинь облачный глаз) — и он краснеет.
"""
from __future__ import annotations

import importlib.util
import json
import plistlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
_PLIST = _REPO / "launchd" / "com.spa.site_freshness.plist"
_WRAPPER = _REPO / "scripts" / "agent_site_freshness.sh"
_MONITOR = _REPO / "scripts" / "site_freshness_monitor.py"
_INSTALLER = _REPO / "scripts" / "install_all_agents.sh"
_WORKFLOW = _REPO / ".github" / "workflows" / "site_freshness.yml"

# launchd читает АБСОЛЮТНЫЙ путь прод-дерева, а тесты гоняются из worktree и из CI —
# поэтому содержимое plist сверяется с прод-путём как со строкой, а существование и
# права — с файлом того дерева, в котором тест запущен. Смешать эти два вопроса
# значит получить тест, зелёный в CI и бессмысленный в проде.
_PROD_ROOT = "/Users/yuriikulieshov/Documents/SPA_Claude"
_PROD_WRAPPER = f"{_PROD_ROOT}/scripts/agent_site_freshness.sh"
_PROD_MONITOR = f"{_PROD_ROOT}/scripts/site_freshness_monitor.py"

# Кадэнс облачного прогона — раз в 6 часов. Мак обязан ходить не реже: он ЕДИНСТВЕННЫЙ,
# кто способен доставить обе стороны таблички.
_SIX_HOURS = 21600


def _uncommented(text: str):
    """Строки shell/yml без комментариев. Урок цикла #227: упоминание в комментарии
    вызовом не является, и сканер, который их путает, снимает проводку с учёта молча."""
    for line in text.splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            yield code


def _plist_doc() -> dict:
    with open(_PLIST, "rb") as fh:
        return plistlib.load(fh)


# ---------------------------------------------------------------------------
# 1. Агент существует и способен стартовать
# ---------------------------------------------------------------------------
class TestTheAgentExists(unittest.TestCase):

    def test_the_plist_is_present_and_valid(self):
        self.assertTrue(
            _PLIST.is_file(),
            "у Site Custodian снова нет тела на Маке — снимать табличку честности "
            "будет некому, ровно как 11–14.08")
        self.assertEqual(_plist_doc().get("Label"), "com.spa.site_freshness")

    def test_launchd_is_given_a_bash_wrapper_not_python(self):
        """Инвариант #12: `python3 -m` прямо из plist = exit 78, агент не стартует вовсе."""
        args = _plist_doc().get("ProgramArguments") or []
        self.assertEqual(args[:1], ["/bin/bash"], f"ProgramArguments={args}")
        self.assertEqual(args[1], _PROD_WRAPPER)

    def test_the_entrypoint_is_executable(self):
        """Авария 2026-08-04: режим 100644 у точки входа = exit 126 и мёртвый агент,
        невидимый ни по одному пульсу. Права — часть доставки."""
        import os
        self.assertTrue(_WRAPPER.is_file(), "обёртки нет — launchd не запустит ничего")
        self.assertTrue(
            os.access(_WRAPPER, os.X_OK),
            f"{_WRAPPER} не исполняем: launchd вышел бы с кодом 126 молча")

    def test_deployment_acceptance_sees_this_entrypoint(self):
        """Новый агент обязан попасть под ту же приёмку, что и остальные 81."""
        from spa_core.monitoring.deployment_acceptance import _entrypoints_from_plists

        found = [e for e in _entrypoints_from_plists(_PLIST.parent)
                 if e.get("label") == "com.spa.site_freshness"]
        self.assertEqual(len(found), 1, "приёмка деплоя не видит точку входа агента")
        self.assertEqual(found[0]["script"], _PROD_WRAPPER)
        self.assertEqual(found[0]["interval_sec"], _SIX_HOURS)


# ---------------------------------------------------------------------------
# 2. Проводка: агент запускает ИМЕННО сторожа сайта, и не реже облака
# ---------------------------------------------------------------------------
class TestTheWiring(unittest.TestCase):

    def test_the_wrapper_actually_runs_the_site_custodian(self):
        code = "\n".join(_uncommented(_WRAPPER.read_text(encoding="utf-8")))
        self.assertIn("agent_template.sh", code, "обёртка обязана идти через канонический шаблон")
        self.assertIn(
            _PROD_MONITOR, code,
            "обёртка не зовёт site_freshness_monitor.py — агент был бы пустышкой "
            "(упоминание в комментарии вызовом не является)")
        self.assertTrue(_MONITOR.is_file(), "сам сторож сайта пропал из дерева")

    def test_the_mac_runs_at_least_as_often_as_the_cloud(self):
        interval = _plist_doc().get("StartInterval")
        self.assertIsNotNone(interval, "агент без расписания не запустится никогда")
        self.assertLessEqual(
            int(interval), _SIX_HOURS,
            "Мак — единственный, кто может СНЯТЬ табличку; ходить реже облака он не вправе")

    def test_the_installer_knows_about_it(self):
        """Иначе агент не переживёт reboot/переустановку — и половина правила
        честности тихо вернётся в исходное состояние."""
        code = "\n".join(_uncommented(_INSTALLER.read_text(encoding="utf-8")))
        self.assertIn("com.spa.site_freshness.plist", code)
        self.assertIn('"com.spa.site_freshness"', code)

    def test_the_cloud_eye_is_not_removed(self):
        """Условие владельца: облачный прогон остаётся ВТОРЫМ, независимым глазом.
        Мак спит / у него легла сеть ⇒ красный job всё ещё виден."""
        self.assertTrue(_WORKFLOW.is_file(), "облачный глаз ADR-YL-011 снят — так нельзя")
        self.assertIn("site_freshness_monitor.py", _WORKFLOW.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 2b. Операнд такта витрины — ВХОД ХАРНЕССА (ADR-788)
#
# Положительный контроль у этих четырёх тестов — настоящая авария, а не выдумка.
# Замер цикла #910 (Actions API, 11 разобранных артефактов): job `site-freshness`
# красен 68 прогонов ПОДРЯД (последний зелёный 2026-10-03T05:12Z), и с 07.10
# `SHELF_OVERDUE` — ЕДИНСТВЕННАЯ причина в 9 прогонах из 9. Причина не в сайте:
# `cadence.read_published()` (ADR-630) ищет опубликованную витрину по МЕСТУ —
# явный путь → `$SPA_PUBLISHED_SHELF` → зеркало `~/Documents/SPA_mirror`
# (ADR-152), — а в облаке зеркала нет и быть не может. Отказ был ВЕРНЫЙ
# (инв. #17: «не измерено» не выдаётся за «в такте»), но отвечал на вопрос
# ОКРУЖЕНИЯ, и владельцу ушло 68 тревог об окружении.
#
# Цена не в шуме. `OVERSTATED_METRIC` — публичное число ВЫШЕ живого API, то, ради
# чего сторож и написан, — сделал бы job ровно таким же красным, и 69-я тревога
# была бы неотличима от предыдущих 68.
#
# Поведенческая половина класса уже закреплена соседями и здесь НЕ дублируется:
# `test_site_shelf_is_the_operand.py` держит «неизмеренный такт ⇒ SHELF_OVERDUE»,
# `test_publication_truth.py::test_no_mirror_means_not_measured_never_the_local_copy`
# — «без зеркала операнда нет». Непроверенной оставалась ПРОВОДКА: что облачная
# джоба предпосылку ОБЪЯВЛЯЕТ. Ровно тот же порядок, что у `fetch-depth: 0` в
# `.claude/rules/deployment.md`: лечит не понижение проверки, а объявление входа.
# ---------------------------------------------------------------------------
class TestTheCloudJobDeclaresThePublishedShelf(unittest.TestCase):

    def setUp(self):
        self.code = "\n".join(_uncommented(_WORKFLOW.read_text(encoding="utf-8")))

    def test_the_job_declares_the_published_shelf_operand(self):
        """Авария 07–23.10 дословно: переменной не объявлял никто, и такт был
        «НЕ ИЗМЕРЕН» на каждом облачном прогоне. Снять объявление ⇒ этот тест красный."""
        self.assertIn("SPA_PUBLISHED_SHELF", self.code,
                      "облачная джоба не объявляет операнд такта витрины — такт станет "
                      "«НЕ ИЗМЕРЕН» на КАЖДОМ прогоне (авария 07–23.10, 68 красных подряд)")
        self.assertIn("GITHUB_ENV", self.code,
                      "объявление обязано дойти до шага монитора — через $GITHUB_ENV, "
                      "а не остаться в своём шаге")

    def test_the_operand_is_origin_not_the_checked_out_tree(self):
        """`cadence.py` запрещает подменять опубликованную копию своей: на другой ветке
        (`workflow_dispatch`) рабочее дерево НЕ опубликовано. Поэтому операнд берётся
        из `origin/main` под СВОИМ однозначным именем ref'а."""
        resolve = [ln for ln in self.code.splitlines() if "SPA_PUBLISHED_SHELF=" in ln]
        self.assertTrue(resolve, "строка, выставляющая операнд, не найдена")
        self.assertIn("refs/spa/published", self.code,
                      "операнд обязан читаться из ОТДЕЛЬНО названного ref'а origin/main: "
                      "FETCH_HEAD зависит от соседнего шага, а refs/remotes/origin/main "
                      "уже выставлен checkout'ом для ТЕКУЩЕЙ ветки")
        self.assertIn("git fetch --depth=1 origin +refs/heads/main:refs/spa/published", self.code,
                      "ref операнда обязан приходить из origin/main — иначе «опубликованная "
                      "витрина» снова станет тем, что оказалось под рукой")
        # Прямое чтение файла дерева в операнд — ровно запрещённая подмена.
        for ln in resolve:
            self.assertNotIn("$GITHUB_WORKSPACE/landing", ln)
            self.assertNotIn("./landing", ln)

    def test_the_declaration_comes_before_the_monitor_runs(self):
        """Шаг, объявленный ПОСЛЕ монитора, не объявляет ничего: `$GITHUB_ENV` действует
        на СЛЕДУЮЩИЕ шаги. Порядок здесь и есть предмет проверки, а не оформление."""
        decl = self.code.find("SPA_PUBLISHED_SHELF=")
        run = self.code.find("python scripts/site_freshness_monitor.py")
        self.assertNotEqual(decl, -1)
        self.assertNotEqual(run, -1)
        self.assertLess(decl, run,
                        "операнд объявлен ПОСЛЕ прогона монитора — $GITHUB_ENV до него не дойдёт")

    def test_a_failure_to_resolve_does_not_gag_the_critical_checks(self):
        """Жёсткий выход шага-резолвера снял бы с прогона `OVERSTATED_METRIC` — публичное
        число выше живого API, самую критичную проверку сторожа — из-за недоступности git.
        Поэтому отказ fail-soft и НАЗВАННЫЙ: причина печатается, переменная не выставляется,
        монитор сам скажет «НЕ ИЗМЕРЕНО» (инв. #17).

        ⚠️ Притязание мерится ВНУТРИ своего блока, а не по всему файлу. Первая редакция
        этого теста спрашивала `"::warning::" in self.code` — и мутация, снявшая обе
        названные причины у резолвера, ВЫЖИЛА: утверждение удовлетворял `::warning::`
        СОСЕДНЕГО шага (`funnel_link_check`). Дыру нашёл прибор мутаций по дельте, а не
        глаз автора; это тот же класс, что «строки контракта сверяются сами с собой»."""
        block = self.code[self.code.find("refs/spa/published"):self.code.find("python scripts/site_freshness_monitor.py")]
        self.assertTrue(block, "блок резолвера операнда не найден")
        self.assertIn("::warning::", block,
                      "недостача операнда обязана быть НАЗВАНА в логе СВОИМ шагом, "
                      "а не промолчать под чужим предупреждением")
        self.assertIn("SPA_PUBLISHED_SHELF", block.split("::warning::", 1)[1],
                      "причина обязана называть, ЧЕГО не хватает — иначе «операнд не "
                      "достали» неотличимо от любого другого предупреждения джобы")
        self.assertNotIn("exit 1", block,
                         "резолвер операнда не вправе снимать с прогона OVERSTATED_METRIC")
        self.assertIn("exit 0", block,
                      "ветка «операнд не достали» обязана БЫТЬ и обязана пускать монитор дальше")


# ---------------------------------------------------------------------------
# 3. Код возврата — последний канал недоставки. Гасить его запрещено
# ---------------------------------------------------------------------------
class TestTheExitCodeIsNotGagged(unittest.TestCase):
    """Тревога владельцу для направления «не уехало СНЯТИЕ» запрещена осознанно
    (ADR-084: гасится МАРШРУТ, не проверка). После этого у недоставки остался ровно
    один канал — ненулевой код возврата, о чём прямо сказано в `exit_code()` монитора.
    Обернуть его в ноль = вернуть аварию, где «снять табличку отсюда нечем» выглядело
    как чистый прогон: отчёт `ok`, код 0, и табличка не снималась никогда."""

    def test_the_wrapper_does_not_swallow_the_exit_code(self):
        code = "\n".join(_uncommented(_WRAPPER.read_text(encoding="utf-8")))
        for gag in ("--exit-zero", "|| true", "exit 0"):
            self.assertNotIn(
                gag, code,
                f"обёртка гасит исход через `{gag}`: недоставка таблички снова станет "
                f"неотличима от чистого прогона")

    def test_the_monitor_still_reports_undelivered_work_as_nonzero(self):
        mod = _load_monitor()
        self.assertEqual(mod.exit_code(True, [{"delivered": True}]), 0)
        self.assertEqual(
            mod.exit_code(True, [{"delivered": False}]), 1,
            "проверки прошли, но табличка не уехала — это НЕ чистый прогон")


# ---------------------------------------------------------------------------
# 4. Ради чего всё затевалось: с Мака снятие ДОЕЗЖАЕТ
# ---------------------------------------------------------------------------
def _load_monitor():
    spec = importlib.util.spec_from_file_location(
        "site_freshness_monitor_agent_test", str(_MONITOR))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestFromTheMacTheePlaqueActuallyComesDown(unittest.TestCase):
    """Зеркало `TestRecoveryFromAnUndeliverableEnvironment`: там среда доставить не может
    и модуль обязан МОЛЧАТЬ, здесь может — и обязан ДЕЙСТВОВАТЬ. Ветка, которая в
    проде не исполнялась ни разу: агента не существовало."""

    def setUp(self):
        self.mod = _load_monitor()
        del self.mod._DELIVERY_NOTES[:]

    def _clear(self, *, rc: int = 0):
        alerts, pushes = [], []
        with TemporaryDirectory() as t:
            path = Path(t) / "track_snapshot.json"
            path.write_text(json.dumps({"degraded": True, "nav_usd": 100863.31}),
                            encoding="utf-8")
            self._last_snap = path

            # Шов доставки с 20.08 — `publish_from_fresh_checkout` (решение владельца,
            # вариант 1: публикуем из свежей копии, а не из отставшей рабочей папки).
            # Раньше подменялся `subprocess.run`: доставка была ровно одним вызовом
            # пушера, теперь их несколько (git + пушер). Утверждения тестов ниже не
            # менялись; настоящий git-механизм проверяет
            # `test_site_custodian_fresh_checkout.py` (там положительный контроль 20.08).
            def _fake_publish(local_file, message, **k):
                pushes.append([str(local_file), message])
                if rc == 0:
                    return {"delivered": True, "reason": "", "rc": 0, "detail": "база deadbeef"}
                return {"delivered": False, "reason": "push_refused", "rc": rc,
                        "detail": "база deadbeef"}

            with mock.patch.object(self.mod, "_SNAP", path), \
                 mock.patch.object(self.mod, "_delivery_possible", lambda *a, **k: (True, "")), \
                 mock.patch.object(self.mod, "_alert", lambda r: alerts.append(r)), \
                 mock.patch.object(self.mod, "publish_from_fresh_checkout", _fake_publish):
                self.mod._clear_degrade()
            written = json.loads(path.read_text(encoding="utf-8"))
        return alerts, pushes, written

    def test_the_flag_is_lifted(self):
        _, _, written = self._clear()
        self.assertIs(written["degraded"], False,
                      "проверки проходят, дерево живое — табличка обязана сняться")

    def test_the_snapshot_is_actually_deployed(self):
        _, pushes, _ = self._clear()
        self.assertEqual(len(pushes), 1, "локальный флаг без доставки = сайт не изменился")
        # Публикуется РОВНО посчитанный локально снимок — числа в копию переносятся,
        # а не пересчитываются там (инв. #8; в свежей копии лежит версия origin).
        self.assertEqual(pushes[0][0], str(self._last_snap))

    def test_no_numbers_are_invented_on_the_way(self):
        """Инвариант #8: снятие таблички возвращает УЖЕ посчитанные числа, а не новые."""
        _, _, written = self._clear()
        self.assertEqual(written["nav_usd"], 100863.31)

    def test_a_successful_lift_leaves_a_delivered_note(self):
        self._clear()
        notes = [n for n in self.mod._DELIVERY_NOTES if n["what"] == "снятие таблички честности"]
        self.assertTrue(notes)
        self.assertTrue(notes[0]["delivered"])

    def test_a_refused_push_here_is_a_real_anomaly_and_does_page(self):
        """Граница маршрута ADR-084 проходит НЕ по «снятие молчит всегда».

        Замерено на живом коде (ассерт этого теста сначала утверждал обратное и
        покраснел): молчит ровно `delivery_impossible_here` — среда, где доставка
        невозможна по построению и подавить повтор нечем. Отказ пушера ОТСЮДА —
        другой вид: дерево живое, значит есть и дедуп, и журнал канала, а сам отказ
        означает поломку инструмента доставки, а не свойство среды. Петля 14.08
        (4 одинаковых сообщения в сутки мимо дедупа) этим путём не воспроизводится."""
        alerts, _, _ = self._clear(rc=1)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["failures"][0]["code"], "HONESTY_PLAQUE_UNDELIVERED")
        notes = [n for n in self.mod._DELIVERY_NOTES if not n["delivered"]]
        self.assertTrue(notes, "отказ доставки обязан остаться в отчёте")
        self.assertEqual(notes[0]["reason"], "push_refused")

    def test_the_environmental_silence_is_still_intact(self):
        """Контроль в обратную сторону: тот класс, который спамил, по-прежнему молчит."""
        alerts = []
        with TemporaryDirectory() as t:
            path = Path(t) / "track_snapshot.json"
            path.write_text(json.dumps({"degraded": True}), encoding="utf-8")
            with mock.patch.object(self.mod, "_SNAP", path), \
                 mock.patch.object(self.mod, "_delivery_possible",
                                   lambda *a, **k: (False, "дерева нет")), \
                 mock.patch.object(self.mod, "_alert", lambda r: alerts.append(r)):
                self.mod._clear_degrade()
        self.assertEqual(alerts, [])


if __name__ == "__main__":
    unittest.main()
