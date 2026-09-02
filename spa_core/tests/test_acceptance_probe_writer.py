"""test_acceptance_probe_writer.py — положительные контроли к ADR-209.

Каждый тест воспроизводит настоящее состояние 2026-09-02, в котором сторож ADR-208
прожил свои первые сутки, ЛИБО способ, которым писатель проб мог бы соврать:

* реестр проб есть, а писателя нет — поле `acceptance_probe` не пишет никто;
* писательский путь, который ЕСТЬ (`--field k=v`), принимает любую строку, и опечатка
  в имени пробы даёт `unmeasured` НАВСЕГДА, читаясь как «нечем проверить сегодня»;
* все объявленные пробы стоят на ЗАКРЫТЫХ карточках — открытых предметов ноль, а отчёт
  об этом молчал (печатал счётчики, из которых ноль предметов не следует);
* `data/adapter_status.json` в worktree ЕСТЬ (он частично в git) и на 2026-09-02 отстаёт
  на 111ч: замороженный канон объявлял `aave_v3` `live_apy=null`, тогда как живой прод в
  ту же секунду показывал 3.319. Проба без проверки возраста выносила бы
  ПРОТИВОПОЛОЖНЫЕ вердикты в двух деревьях.

Время — вход (`now=`), отметки в фикстурах относительные: тест не обязан краснеть оттого,
что сдвинулся календарь (.claude/rules/deployment.md).
"""
# FROZEN-DATE-OK: injected-clock — литерал ровно один (`NOW`), и он не «сегодня», а ЯКОРЬ:
# каждая отметка в фикстурах строится из него же (`_stamp(hours_ago=...)`), и он же уезжает
# в пробу параметром `now=`. Обе стороны сравнения пришпилены к одному числу, поэтому
# движение календаря на вердикт не влияет вовсе — предпочтение №1 правила доставки.
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from spa_core.monitoring import card_acceptance as ca
from spa_core.owner_queue.queue import set_acceptance_probe

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CLI = os.path.join(_REPO, "scripts", "orchestrator_queue.py")

NOW = datetime(2026, 9, 2, 1, 0, tzinfo=timezone.utc)


def _stamp(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _card(tmp: str, name: str, *, status: str, probe: str | None = None) -> str:
    fm = ["type: agent", f'title: "карточка {name}"', f"status: {status}"]
    if probe is not None:
        fm.append(f"acceptance_probe: {probe}")
    path = os.path.join(tmp, f"{name}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\n" + "\n".join(fm) + "\n---\n\n## тело\n\nстрока тела\n")
    return path


def _status_file(tmp: str, *, age_h: float, adapters: dict) -> str:
    """Копия `data/adapter_status.json` в изолированном дереве."""
    data_dir = os.path.join(tmp, "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "adapter_status.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": 1, "generated_at": _stamp(age_h),
                   "adapters": adapters}, fh)
    return path


class ProbeRegistryHasExactlyOneCopy(unittest.TestCase):
    """Писатель и читатель обязаны спорить об ОДНОМ списке.

    Класс «два реестра под одним именем» уже стоил дня: валидация разрешала бы имя,
    которого у читателя нет, и карточка рождалась бы с критерием, не измеримым никогда.
    """

    def test_validator_accepts_exactly_the_registered_names(self):
        for name in sorted(ca.PROBES):
            with self.subTest(probe=name):
                self.assertIsNone(ca.validate_spec(name))

    def test_unregistered_name_is_refused_and_names_the_alternatives(self):
        reason = ca.validate_spec("adapter_status_liveapy:pendle")
        self.assertIsNotNone(reason)
        self.assertIn("не зарегистрирована", reason)
        for name in ca.PROBES:
            self.assertIn(name, reason, "отказ обязан назвать, что ЖЕ известно")

    def test_argument_that_is_not_a_key_is_refused(self):
        self.assertIsNotNone(ca.validate_spec("adapter_status_live_apy:rm -rf /"))
        self.assertIsNotNone(ca.validate_spec("adapter_status_live_apy:../../etc/passwd"))

    def test_empty_spec_is_refused_not_silently_accepted(self):
        self.assertIsNotNone(ca.validate_spec(""))
        self.assertIsNotNone(ca.validate_spec("   "))


class WriterRefusesAnUnmeasurableCriterionAtBirth(unittest.TestCase):
    """Опечатка обязана стоить ОТКАЗА при рождении, а не `unmeasured` через сутки."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _create(self, *extra):
        return subprocess.run(
            [sys.executable, _CLI, "create", "--type", "inbox", "--title", "проверочная",
             "--tracker-dir", self.tmp, *extra],
            capture_output=True, text=True, timeout=180)

    def test_unregistered_probe_via_flag_refuses_with_code_2(self):
        res = self._create("--acceptance-probe", "adapter_status_liveapy:pendle")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("REFUSED", res.stderr)
        self.assertEqual([f for f in os.listdir(self.tmp)
                          if f.endswith(".md") and not f.startswith("_")], [],
                         "отказ обязан НЕ оставить карточку")

    def test_the_older_door_field_kv_is_validated_too(self):
        """Дверь, которая уже существовала, — та самая, через которую опечатка и въезжала."""
        res = self._create("--field", "acceptance_probe=nonesuch")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("REFUSED", res.stderr)

    def test_registered_probe_is_written_into_the_frontmatter(self):
        res = self._create("--acceptance-probe", "adapter_status_live_apy:pendle")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        made = [f for f in os.listdir(self.tmp) if f.endswith(".md") and not f.startswith("_")]
        self.assertEqual(len(made), 1, made)
        # Сверяем не подстроку, а КРУГ: писатель экранирует значение с двоеточием в
        # кавычки, читатель их снимает. Совпадение байтов тут ничего не доказывало бы —
        # доказывает то, что читатель получает РОВНО объявленную пробу.
        text = open(os.path.join(self.tmp, made[0]), encoding="utf-8").read()
        self.assertEqual(ca.parse_frontmatter(text).get("acceptance_probe"),
                         "adapter_status_live_apy:pendle")
        self.assertIsNone(ca.validate_spec(ca.parse_frontmatter(text)["acceptance_probe"]))

    def test_a_card_without_a_probe_is_still_creatable(self):
        """Проба необязательна — иначе правило превратилось бы в налог на любую карточку."""
        self.assertEqual(self._create().returncode, 0)


class WriterReachesCardsThatAlreadyExist(unittest.TestCase):
    """Бэклог написан ДО правила: без этой двери 85 открытых карточек остаются
    вне машинной приёмки навсегда — тот самый «читатель без писателя»."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_probe_is_added_and_body_survives_byte_for_byte(self):
        path = _card(self.tmp, "старая", status="backlog")
        before = open(path, encoding="utf-8").read()
        previous = set_acceptance_probe(path, "adapter_status_live_apy:pendle")
        after = open(path, encoding="utf-8").read()
        self.assertIsNone(previous)
        self.assertEqual(ca.parse_frontmatter(after).get("acceptance_probe"),
                         "adapter_status_live_apy:pendle")
        self.assertEqual(before.split("---", 2)[2], after.split("---", 2)[2],
                         "тело карточки обязано остаться побайтно тем же")

    def test_existing_probe_is_replaced_not_duplicated(self):
        path = _card(self.tmp, "старая", status="backlog", probe="lead_channel_wiring_ok")
        previous = set_acceptance_probe(path, "contract_manifest_parity_agrees")
        text = open(path, encoding="utf-8").read()
        self.assertEqual(previous, "lead_channel_wiring_ok")
        self.assertEqual(text.count("acceptance_probe:"), 1)
        self.assertEqual(ca.parse_frontmatter(text).get("acceptance_probe"),
                         "contract_manifest_parity_agrees")

    def test_cli_refuses_an_unregistered_probe_and_leaves_the_card_untouched(self):
        path = _card(self.tmp, "старая", status="backlog")
        before = open(path, encoding="utf-8").read()
        res = subprocess.run([sys.executable, _CLI, "probe", path, "nonesuch"],
                             capture_output=True, text=True, timeout=180)
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertEqual(open(path, encoding="utf-8").read(), before)


class ZeroOpenSubjectsIsSaidOutLoud(unittest.TestCase):
    """Состояние, в котором сторож прожил первые сутки: пробы объявлены, но ВСЕ на
    закрытых карточках. Счётчики при этом печатались, и ноль предметов из них не читался."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        ca.PROBES["_выполнен"] = lambda _a: (ca.SATISFIED, "выполнено")

    def tearDown(self):
        self._tmp.cleanup()
        ca.PROBES.pop("_выполнен", None)

    def test_all_probes_on_closed_cards_is_named_not_summarised(self):
        _card(self.tmp, "закрытая", status="done", probe="_выполнен")
        lines = "\n".join(ca.report_lines(ca.audit(self.tmp)))
        self.assertIn("открытых предметов НОЛЬ", lines)
        self.assertIn("ADR-209", lines)

    def test_a_single_open_subject_switches_the_report_back_to_counters(self):
        _card(self.tmp, "закрытая", status="done", probe="_выполнен")
        _card(self.tmp, "живая", status="backlog", probe="_выполнен")
        res = ca.audit(self.tmp)
        lines = "\n".join(ca.report_lines(res))
        self.assertNotIn("открытых предметов НОЛЬ", lines)
        self.assertEqual(res["counts"]["declared_open"], 1)
        self.assertEqual(res["counts"]["declared_closed"], 1)

    def test_a_closed_card_is_not_probed_at_all(self):
        """Не «прогнали и промолчали», а НЕ ЗВАЛИ: проба-ловушка обязана не сработать."""
        def _trap(_arg):
            raise AssertionError("пробу закрытой карточки звать нельзя")
        ca.PROBES["_ловушка"] = _trap
        try:
            _card(self.tmp, "закрытая", status="done", probe="_ловушка")
            res = ca.audit(self.tmp)
        finally:
            ca.PROBES.pop("_ловушка", None)
        self.assertEqual(res["counts"]["declared_closed"], 1)
        self.assertEqual(res["rows"][0]["verdict"], ca.NOT_PROBED)
        self.assertEqual(res["counts"]["unmeasured"], 0,
                         "снятый вопрос не имеет права разбавлять счётчик «не измерено»")


class StaleArtifactCannotConvictTheSubject(unittest.TestCase):
    """Авария-прообраз: канон в worktree от 28.08 объявлял `aave_v3` live_apy=null,
    живой прод в ту же секунду — 3.319. Возраст артефакта обязан быть частью вопроса."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self._root = ca.REPO_ROOT
        ca.REPO_ROOT = self.tmp

    def tearDown(self):
        ca.REPO_ROOT = self._root
        self._tmp.cleanup()

    def test_frozen_canon_is_unmeasured_never_not_satisfied(self):
        _status_file(self.tmp, age_h=111.0, adapters={"aave_v3": {"live_apy": None,
                                                                  "fallback_apy": 3.5}})
        verdict, detail = ca._probe_adapter_status_live_apy("aave_v3", now=NOW)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("протух", detail)

    def test_fresh_artifact_convicts_a_key_that_has_no_live_number(self):
        _status_file(self.tmp, age_h=1.4, adapters={"pendle": {"live_apy": None,
                                                               "fallback_apy": 8.0,
                                                               "tvl_source": "static"}})
        verdict, detail = ca._probe_adapter_status_live_apy("pendle", now=NOW)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("8.0", detail, "отказ обязан назвать литерал, который предъявляется")

    def test_fresh_artifact_can_also_say_yes(self):
        """Проба, которая не умеет сказать «да», — украшение: контроль в обе стороны."""
        _status_file(self.tmp, age_h=1.4, adapters={"aave_v3": {"live_apy": 3.319,
                                                                "pool_match": "hint"}})
        verdict, _ = ca._probe_adapter_status_live_apy("aave_v3", now=NOW)
        self.assertEqual(verdict, ca.SATISFIED)

    def test_the_boundary_is_the_declared_limit_not_a_guess(self):
        _status_file(self.tmp, age_h=ca.ADAPTER_STATUS_MAX_AGE_H - 0.1,
                     adapters={"aave_v3": {"live_apy": 3.3}})
        self.assertEqual(ca._probe_adapter_status_live_apy("aave_v3", now=NOW)[0], ca.SATISFIED)
        _status_file(self.tmp, age_h=ca.ADAPTER_STATUS_MAX_AGE_H + 0.1,
                     adapters={"aave_v3": {"live_apy": 3.3}})
        self.assertEqual(ca._probe_adapter_status_live_apy("aave_v3", now=NOW)[0], ca.UNMEASURED)

    def test_absent_artifact_is_unmeasured(self):
        """`data/` отсутствует в дереве ПО ПОСТРОЕНИЮ — это не «критерий не выполнен»."""
        verdict, detail = ca._probe_adapter_status_live_apy("aave_v3", now=NOW)
        self.assertEqual(verdict, ca.UNMEASURED, detail)

    def test_artifact_without_a_timestamp_is_unmeasured(self):
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)
        with open(os.path.join(self.tmp, "data", "adapter_status.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"adapters": {"aave_v3": {"live_apy": 3.3}}}, fh)
        verdict, detail = ca._probe_adapter_status_live_apy("aave_v3", now=NOW)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("generated_at", detail)

    def test_unknown_key_is_unmeasured_not_a_verdict(self):
        _status_file(self.tmp, age_h=1.0, adapters={"aave_v3": {"live_apy": 3.3}})
        verdict, _ = ca._probe_adapter_status_live_apy("no_such", now=NOW)
        self.assertEqual(verdict, ca.UNMEASURED)


class MultiKeyCriterionIsSatisfiedOnlyWhenEveryKeyIs(unittest.TestCase):
    """Критерий карточки часто называет НЕСКОЛЬКО ключей (pendle И pendle_pt; семь
    протоколов без фида). Проба на один из них была бы зелёной ложью об остальных."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self._root = ca.REPO_ROOT
        ca.REPO_ROOT = self.tmp
        _status_file(self.tmp, age_h=1.0, adapters={
            "live_key": {"live_apy": 3.3, "pool_match": "pinned"},
            "second_live": {"live_apy": 4.8, "pool_match": "pinned"},
            "dead_key": {"live_apy": None, "fallback_apy": 8.0},
        })

    def tearDown(self):
        ca.REPO_ROOT = self._root
        self._tmp.cleanup()

    def _v(self, arg):
        return ca._probe_adapter_status_live_apy(arg, now=NOW)

    def test_all_keys_live_is_satisfied(self):
        self.assertEqual(self._v("live_key+second_live")[0], ca.SATISFIED)

    def test_one_dead_key_sinks_the_whole_criterion(self):
        verdict, detail = self._v("live_key+dead_key")
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("live_key", detail)
        self.assertIn("dead_key", detail)

    def test_not_satisfied_outranks_unmeasured(self):
        """Иначе неизвестный ключ прятал бы НАЗВАННЫЙ отказ за «нечем проверить»."""
        self.assertEqual(self._v("dead_key+no_such")[0], ca.NOT_SATISFIED)

    def test_unmeasured_outranks_satisfied(self):
        """Половина критерия, о которой ничего не известно, не даёт объявить его закрытым."""
        self.assertEqual(self._v("live_key+no_such")[0], ca.UNMEASURED)

    def test_the_multi_key_form_passes_the_writer_validator(self):
        self.assertIsNone(ca.validate_spec("adapter_status_live_apy:live_key+second_live"))


class TheProbeIsDeclaredOnARealOpenCard(unittest.TestCase):
    """Сторож без предмета — украшение. У ADR-209 обязан быть ХОТЯ БЫ один открытый
    предмет в самом репозитории, иначе правило снова превращается в мёртвую букву."""

    def test_at_least_one_open_card_declares_a_registered_probe(self):
        tracker = os.path.join(_REPO, "nimbalyst-local", "tracker")
        if not os.path.isdir(tracker):
            self.skipTest("трекера нет в этом дереве")
        res = ca.audit(tracker)
        self.assertGreaterEqual(
            res["counts"]["declared_open"], 1,
            "ни одна открытая карточка не объявляет пробу — сторож ADR-208 снова без предмета")
        for row in res["rows"]:
            with self.subTest(card=row["card"]):
                self.assertIsNone(ca.validate_spec(row["probe"]),
                                  f"карточка {row['card']} объявила пробу, которой нет в реестре")


if __name__ == "__main__":
    unittest.main()
