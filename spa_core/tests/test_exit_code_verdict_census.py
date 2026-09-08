"""Перепись третьего носителя вердикта — КОДА ВОЗВРАТА (заказ ADR-266, цикл #530).

Заказ назван дословно: оба прежних прибора (#528 по печатям, #530 по
вердикт-данным) меряют ПРОИЗВОДИТЕЛЯ. Третий род носителя — вердикт, доезжающий
до решения кодом возврата, — не мерил никто, хотя именно им сторожа разговаривают
с launchd. Ловушка заказа: у кода возврата нет ключа находки, гистерезис-
потребитель здесь недоступен ПО ПОСТРОЕНИЮ, поэтому мерить надо У ПОТРЕБИТЕЛЯ.

ЧТО ЗДЕСЬ ЗАКРЕПЛЕНО.

1. Прибор видит ВСЁ объявленное население (80 активных агентов конституции) и
   не оставляет ни одного `UNRESOLVED`.
2. Прибор НЕ КРАСНЕЕТ НА ОБРАЗЦЕ: единственный починенный сайт класса
   (`com.spa.daily_cycle`, цикл #219) читается как `LEGIBLE`.
3. Контроль на НАСТОЯЩЕЙ регрессии: снятие поимённого разбора у потребителя
   переворачивает образец в `ILLEGIBLE` — и ТОЛЬКО его.
4. Список читаемых меток НЕ ЗАШИТ: вторая появившаяся метка видна прибору сама.
5. Шапка `launchctl list` (`label == "Label"`) меткой флота НЕ становится —
   наивный сбор объявил бы её меткой, и это измерено.
6. Общий вклад обёртки — ОДИН факт про флот, а не 68 приговоров агентам.
7. Пределы прибора названы и закреплены сценами: вычисленный код невидим,
   `UNRESOLVED` идёт в дефекты.

Литеральных дат и номеров процессов в файле нет: прибор — чистый разбор дерева.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from spa_core.tests import _exit_code_verdict_census as cen

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mirror(root: str, sandbox: str, *rewrite: str) -> None:
    """Песочница-зеркало дерева: всё симлинками, кроме переписываемых файлов.

    Копировать дерево целиком нельзя (оно огромно), а мерить контроль на
    синтетике — значит проверять не тот предмет. Поэтому каждый каталог,
    ведущий к переписываемому файлу, становится НАСТОЯЩИМ и наполняется
    симлинками на оригинал; сам файл кладётся копией, которую сцена правит.
    """
    real_dirs = {os.path.dirname(p) for p in rewrite}
    for path in list(real_dirs):
        parts = path.split(os.sep)
        for i in range(1, len(parts) + 1):
            real_dirs.add(os.sep.join(parts[:i]))
    real_dirs.discard("")

    def build(rel: str) -> None:
        src = os.path.join(root, rel) if rel else root
        dst = os.path.join(sandbox, rel) if rel else sandbox
        os.makedirs(dst, exist_ok=True)
        for name in os.listdir(src):
            child_rel = os.path.join(rel, name) if rel else name
            child_src = os.path.join(src, name)
            child_dst = os.path.join(dst, name)
            if os.path.exists(child_dst):
                continue
            if child_rel in real_dirs:
                build(child_rel)
            elif child_rel in rewrite:
                shutil.copy2(child_src, child_dst)
            else:
                os.symlink(child_src, child_dst)

    build("")


CONSUMER_REL = os.path.join("spa_core", "monitoring", "agent_health_monitor.py")
TEMPLATE_REL = os.path.join("scripts", "agent_template.sh")


class Population(unittest.TestCase):
    """Население — ОБЪЯВЛЕНИЕ конституции, и оно дочитывается целиком."""

    def test_census_covers_every_active_agent_of_the_manifest(self):
        manifest = json.load(open(os.path.join(ROOT, cen.MANIFEST), encoding="utf-8"))
        declared = [a["label"] for a in manifest["agents"] if a.get("intent") == "active"]
        measured = [s.label for s in cen.census(ROOT)]
        self.assertEqual(sorted(declared), sorted(measured),
                         "перепись и конституция расходятся населением")
        self.assertGreater(len(measured), 50, "население подозрительно мало")

    def test_population_is_the_manifest_not_the_agent_star_mask(self):
        """Образец класса под маску `agent_*.sh` не попадает — и это измерено.

        `com.spa.daily_cycle` запускается `run_daily_paper_cycle.sh`. Прибор,
        построенный на маске имени, не увидел бы единственный ПОЧИНЕННЫЙ сайт,
        то есть не смог бы доказать, что не краснеет на исправном.
        """
        site = self._site("com.spa.daily_cycle")
        self.assertFalse(site.program.startswith("agent_"),
                         "образец сменил обёртку — довод про маску надо перемерить")

    def test_no_site_is_unresolved(self):
        """«Не измерено» — громко. Молчаливое выпадение и есть тот дефект."""
        unresolved = [(s.label, s.why) for s in cen.census(ROOT)
                      if s.outcome == cen.UNRESOLVED]
        self.assertEqual(unresolved, [], f"неразобранные сайты: {unresolved}")

    def _site(self, label):
        for s in cen.census(ROOT):
            if s.label == label:
                return s
        self.fail(f"метки {label} нет в переписи")


class TheFixedSiteIsTheSample(unittest.TestCase):
    """Прибор обязан молчать на исправном и краснеть на его поломке."""

    def _site(self, rows, label):
        for s in rows:
            if s.label == label:
                return s
        self.fail(f"метки {label} нет в переписи")

    def test_the_one_fixed_site_reads_legible(self):
        site = self._site(cen.census(ROOT), "com.spa.daily_cycle")
        self.assertEqual(site.outcome, cen.LEGIBLE, site.why)
        self.assertGreaterEqual(len(site.own), 2,
                                "у образца меньше двух собственных кодов — "
                                "тогда он и не предмет этого класса")

    def test_removing_the_per_label_reading_turns_the_sample_illegible(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ НА НАСТОЯЩЕЙ РЕГРЕССИИ.

        Цикл #219 научил потребителя читать коды дневного цикла поимённо. Сцена
        отменяет ровно эту правку — и требует, чтобы прибор назвал образец
        дефектным, а всех остальных не тронул.
        """
        before = {s.label: s.outcome for s in cen.census(ROOT)}
        with tempfile.TemporaryDirectory() as box:
            sandbox = os.path.join(box, "tree")
            _mirror(ROOT, sandbox, CONSUMER_REL)
            path = os.path.join(sandbox, CONSUMER_REL)
            src = open(path, encoding="utf-8").read()
            self.assertIn("label == CYCLE_AGENT_LABEL", src,
                          "поимённого разбора у потребителя уже нет — "
                          "сцена изображала бы несуществующую правку")
            # Отменяется РОВНО правка #219 — поимённое чтение метки, — а не
            # способность потребителя быть прочитанным: подстановка неизвестного
            # ИМЕНИ дала бы `UNRESOLVED` у всех сразу, то есть сцена изображала
            # бы поломку прибора вместо регрессии предмета.
            open(path, "w", encoding="utf-8").write(
                src.replace("label == CYCLE_AGENT_LABEL", "isinstance(label, bytes)"))
            after = {s.label: s.outcome for s in cen.census(sandbox)}

        changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        self.assertEqual(changed,
                         {"com.spa.daily_cycle": (cen.LEGIBLE, cen.ILLEGIBLE)},
                         f"вердикт сменился не там, где правка: {changed}")

    def test_a_second_decoded_label_is_seen_without_touching_the_instrument(self):
        """Список читаемых меток ВЫВОДИТСЯ, а не зашит.

        Обратная сторона предыдущей сцены: научи потребителя читать вторую
        метку — и прибор обязан сам вывести её из класса, без единой правки
        в себе.
        """
        victim = next(s for s in cen.census(ROOT) if s.outcome == cen.ILLEGIBLE)
        with tempfile.TemporaryDirectory() as box:
            sandbox = os.path.join(box, "tree")
            _mirror(ROOT, sandbox, CONSUMER_REL)
            path = os.path.join(sandbox, CONSUMER_REL)
            src = open(path, encoding="utf-8").read()
            open(path, "w", encoding="utf-8").write(src.replace(
                "label == CYCLE_AGENT_LABEL",
                f'label == CYCLE_AGENT_LABEL or label == "{victim.label}"', 1))
            after = {s.label: s.outcome for s in cen.census(sandbox)}
        self.assertEqual(after[victim.label], cen.LEGIBLE,
                         "вторая метка потребителя прибору не видна — "
                         "значит список у него зашит")
        self.assertEqual(after["com.spa.daily_cycle"], cen.LEGIBLE,
                         "образец пострадал от чужой правки")


class ConsumerLabelsAreScopedByMeasurement(unittest.TestCase):
    """Метка ищется там, где код СТАНОВИТСЯ вердиктом, а не где угодно."""

    def test_launchctl_header_is_not_taken_for_a_fleet_label(self):
        """Наивный сбор объявил бы меткой слово из ШАПКИ `launchctl list`.

        Строка `if label == "Label"` в потребителе отбрасывает заголовок вывода.
        Она не имеет отношения к чтению кода возврата, и прибор обязан её не
        считать — иначе «Label» стала бы меткой флота.
        """
        labels, error = cen.consumer_labels(ROOT)
        self.assertIsNone(error, error)
        self.assertNotIn("Label", labels)
        self.assertIn("com.spa.daily_cycle", labels)

    def test_consumer_without_an_exit_code_reader_is_unmeasured_not_clean(self):
        """Нет функции, читающей `last_exit` ⇒ «не измерено», а не «чисто»."""
        with tempfile.TemporaryDirectory() as box:
            sandbox = os.path.join(box, "tree")
            _mirror(ROOT, sandbox, CONSUMER_REL)
            path = os.path.join(sandbox, CONSUMER_REL)
            open(path, "w", encoding="utf-8").write("X = 1\n")
            labels, error = cen.consumer_labels(sandbox)
            self.assertEqual(labels, set())
            self.assertIsNotNone(error)
            outcomes = {s.outcome for s in cen.census(sandbox)
                        if s.label in ("com.spa.daily_cycle", "com.spa.orchestrator")}
            self.assertIn(cen.UNRESOLVED, outcomes,
                          "непрочитанный потребитель обязан давать `UNRESOLVED`")


class MutingIsMeasuredWhereItIs(unittest.TestCase):
    """`|| true` на строке запуска гасит вердикт сторожа целиком."""

    def test_muted_sites_are_named_and_are_defects(self):
        muted = [s for s in cen.census(ROOT)
                 if s.outcome in (cen.MUTED, cen.MUTED_SIDECAR)]
        self.assertTrue(muted, "ни одного заглушённого сайта — сцену надо перемерить")
        for site in muted:
            self.assertTrue(site.own, "заглушать нечего, если своих кодов нет")
            self.assertTrue(site.is_defect)

    def test_two_wrappers_with_the_same_flag_get_DIFFERENT_verdicts(self):
        """Последствие `|| true` решает НЕ флаг, а место — измерено на живой паре.

        Обе обёртки несут `|| true`, и вердикты у них обязаны быть РАЗНЫМИ:
        `agent_swarm_health.sh` берёт `RC=$?` и заканчивается `exit $RC` — код
        основного сторожа доезжает, погашены лишь попутные запуски;
        `agent_aggressive_lab.sh` `$?` не берёт вовсе, и последней командой
        стои́т глушение — значит агент отдаёт launchd НОЛЬ всегда. Сложить их в
        один исход значило бы назвать верным словом две разные вещи.
        """
        rows = {s.label: s for s in cen.census(ROOT)}
        self.assertEqual(rows["com.spa.aggressive_lab"].outcome, cen.MUTED)
        self.assertEqual(rows["com.spa.swarm_health"].outcome, cen.MUTED_SIDECAR)
        self.assertEqual(rows["com.spa.aggressive_lab"].carried, set(),
                         "агент, отдающий ноль всегда, не несёт ни одного кода")
        self.assertTrue(rows["com.spa.swarm_health"].carried,
                        "код основного сторожа обязан доезжать")

    def test_preserving_the_rc_is_measured_by_form_not_by_name(self):
        self.assertTrue(cen._preserves_rc("RC=$?\nexit $RC\n"))
        self.assertTrue(cen._preserves_rc('exit "$rc"\n'))
        self.assertFalse(cen._preserves_rc("exit 0\n"))
        self.assertFalse(cen._preserves_rc("# exit $RC в комментарии\n"))

    def test_removing_the_muting_line_lifts_exactly_that_site(self):
        """Обратный контроль: убери `|| true` — сайт выходит из класса, один."""
        victim = next(s for s in cen.census(ROOT)
                      if s.outcome in (cen.MUTED, cen.MUTED_SIDECAR))
        wrapper_rel = os.path.join("scripts", victim.program)
        before = {s.label: s.outcome for s in cen.census(ROOT)}
        with tempfile.TemporaryDirectory() as box:
            sandbox = os.path.join(box, "tree")
            _mirror(ROOT, sandbox, wrapper_rel)
            path = os.path.join(sandbox, wrapper_rel)
            src = open(path, encoding="utf-8").read()
            self.assertIn("|| true", src)
            open(path, "w", encoding="utf-8").write(src.replace("|| true", ""))
            after = {s.label: s.outcome for s in cen.census(sandbox)}
        changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        self.assertEqual(list(changed), [victim.label],
                         f"вердикт сменился не только у правленого: {changed}")
        self.assertNotIn(after[victim.label], (cen.MUTED, cen.MUTED_SIDECAR))

    def test_comment_mentioning_the_flag_is_not_muting(self):
        """Гасит СТРОКА ЗАПУСКА, а не слово в комментарии рядом."""
        self.assertEqual(cen._muting("# запуск идёт с --exit-zero, но не здесь\n"
                                     "echo ok\n", "w.sh"), [])
        self.assertEqual(cen._muting('echo "нет --exit-zero"  # строка ничего не запускает\n',
                                     "w.sh"), [])
        self.assertEqual(
            cen._muting('python3 -m pkg --exit-zero\n', "w.sh"),
            ["w.sh:1 флаг --exit-zero гасит код у производителя"],
            "форма запуска перестала опознаваться — прибор ослеп на настоящем случае")


class ProseIsNotWiring(unittest.TestCase):
    """Упоминание запуска внутри строки-литерала — проза, а не проводка.

    Контроль на НАСТОЯЩЕЙ ложной находке, которую прибор однажды изготовил:
    `agent_orchestrator.sh` собирает промпт сессии многострочным `PROMPT="…"`,
    и внутри промпта ПРОЗОЙ написано `python3 scripts/consume_office_reports.py`.
    Первая редакция зачла это за запуск и приписала `com.spa.orchestrator` коды
    `[1, 3]`, которых обёртка не производит.
    """

    def test_prompt_text_does_not_become_an_invocation(self):
        src = open(os.path.join(ROOT, "scripts", "agent_orchestrator.sh"),
                   encoding="utf-8").read()
        self.assertIn("consume_office_reports.py", src,
                      "промпт изменился — сцена изображала бы несуществующий случай")
        targets = [t for _, t in cen._wrapper_targets(src)]
        self.assertNotIn("scripts/consume_office_reports.py", targets)
        self.assertFalse([t for t in targets if "consume_office_reports" in t],
                         f"проза промпта зачтена за проводку: {targets}")

    def test_narrowing_did_not_swallow_real_commands(self):
        """Обратная сторона той же починки, и она СВОЯ ЖЕ регрессия.

        Вторая редакция тянула состояние кавычки через весь файл и рассыпалась
        на комментариях: у `agent_template.sh` пропал его собственный `exit 75`.
        Починка ложной находки СОЗДАЛА пропуск настоящих — эта сцена держит обе
        стороны сразу.
        """
        src = open(os.path.join(ROOT, TEMPLATE_REL), encoding="utf-8").read()
        self.assertEqual(cen._bash_codes(src), {64, 75},
                         "коды общей обёртки потерялись — сужение съело команды")

    def test_multiline_assignment_and_heredoc_are_skipped_but_their_start_is_not(self):
        src = ('PROMPT="строка один\n'
               'python3 scripts/wrong.py\n'
               'конец"\n'
               'python3 scripts/right.py\n'
               'cat <<EOF\n'
               'exit 42\n'
               'EOF\n'
               'exit 7\n')
        targets = [t for _, t in cen._wrapper_targets(src)]
        self.assertEqual(targets, ["scripts/right.py"], targets)
        self.assertEqual(cen._bash_codes(src), {7},
                         "код из тела heredoc зачтён за собственный")


class SharedWrapperIsOneFactNotSixtyEightVerdicts(unittest.TestCase):
    """Групповой срез не превращается в приговор элементу."""

    def test_template_codes_are_not_charged_to_each_agent(self):
        rows = cen.census(ROOT)
        template_users = [s for s in rows if 75 in s.wrapper]
        self.assertGreater(len(template_users), 30,
                           "общую обёртку зовут единицы — довод надо перемерить")
        charged = [s.label for s in template_users
                   if s.outcome == cen.ILLEGIBLE and len(s.own) < 2]
        self.assertEqual(charged, [],
                         "общий вклад обёртки списан в актив отдельным агентам")

    def test_shared_contribution_is_reported_and_measures_its_own_claim(self):
        """Утверждение обёртки проверяется у потребителя, а не пересказывается.

        Рядом с `exit 75` в `agent_template.sh` написано, что мониторинг умеет
        отличить его от логической ошибки. Здесь считается, для скольких меток
        это сегодня верно.
        """
        report = cen.shared_wrapper_contribution(ROOT)
        self.assertIn(75, report["codes"])
        self.assertGreater(report["agents"], 30)
        self.assertIsInstance(report["decoded_labels"], list)


class LimitsAreNamedAndPinned(unittest.TestCase):
    """Каждый названный предел закреплён сценой, а не только прозой."""

    def test_defects_carry_unresolved_too(self):
        with tempfile.TemporaryDirectory() as box:
            sandbox = os.path.join(box, "tree")
            _mirror(ROOT, sandbox, os.path.join("architecture", "manifest.json"))
            open(os.path.join(sandbox, cen.MANIFEST), "w").write("{ не json")
            found = cen.defects(sandbox)
        self.assertEqual([s.outcome for s in found], [cen.UNRESOLVED])

    def test_computed_exit_code_is_invisible_and_the_limit_is_stated(self):
        """Предел: код, вычисленный из данных, прибору не виден."""
        with tempfile.TemporaryDirectory() as box:
            target = os.path.join(box, "t.py")
            open(target, "w").write(
                "def main():\n"
                "    return len(open('x').read())   # вычисленный код\n")
            codes, err = cen._python_codes(target)
        self.assertIsNone(err)
        self.assertEqual(codes, set(), "прибор увидел невидимое — предел назван неверно")
        self.assertIn("ЛИТЕРАЛЬНЫЕ коды", cen.census.__doc__)

    def test_bash_propagation_is_not_a_literal(self):
        """`exit "$rc"` — проброс чужого кода, а не собственный литерал."""
        self.assertEqual(cen._bash_codes('exit "$rc"\nexit $RC\n'), set())
        self.assertEqual(cen._bash_codes("exit 75\n"), {75})
        self.assertEqual(cen._bash_codes("exit 0\n"), set())
        self.assertEqual(cen._bash_codes("# exit 9 в комментарии\n"), set())


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
