"""Тесты манифеста архитектуры (ADR-066, Фаза 0).

Каждый positive control воспроизводит РЕАЛЬНУЮ находку аудита 2026-08-05
(правило .claude/rules/deployment.md: проверка, не видевшая настоящей поломки,
не принимается):

  - swarm_dwell / artifact_freshness: агент существует (plist), в манифесте
    отсутствует → check обязан краснеть;
  - auto_push / cpa_daily и ещё 5 репо-остатков: plist в репо ≠ работающий
    агент → сид обязан давать unresolved, НЕ active;
  - digest_weekly: retired с остаточным репо-plist — НЕ проблема; retired с
    персистентным plist в ~/Library/LaunchAgents — проблема;
  - идемпотентность: повторный --write без изменения фактов byte-identical
    (манифест — конституция, без timestamp-шума).

CI-безопасно: машинные факты синтезируются во временных каталогах, реальный
~/Library/LaunchAgents не читается. Реальный architecture/manifest.json
проверяется только машинонезависимо (схема/инварианты курации).
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GEN_PATH = os.path.join(REPO_ROOT, "scripts", "build_architecture_manifest.py")
MANIFEST_PATH = os.path.join(REPO_ROOT, "architecture", "manifest.json")

spec = importlib.util.spec_from_file_location("build_architecture_manifest", GEN_PATH)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def _repo_plists(repo_root: str = REPO_ROOT) -> dict[str, str]:
    """label -> путь к plist'у РЕПОЗИТОРИЯ, тем же приоритетом, что у генератора.

    Генератор сканирует [~/Library/LaunchAgents, launchd/, scripts/] и берёт первое
    вхождение label'а. Здесь ~/Library не читается (герметичность), поэтому порядок
    внутри репо тот же: `launchd/` раньше `scripts/`. Шесть label'ов лежат в обоих
    каталогах — без этого приоритета сверка ловила бы «расхождение» на копии,
    которую генератор и не смотрит.
    """
    out: dict[str, str] = {}
    for d in ("launchd", "scripts"):
        for path in sorted(glob.glob(os.path.join(repo_root, d, "com.spa.*.plist"))):
            if path.endswith(".bak"):
                continue
            try:
                with open(path, "rb") as f:
                    pl = plistlib.load(f)
            except Exception:
                continue
            label = pl.get("Label") or os.path.basename(path)[:-len(".plist")]
            out.setdefault(label, path)
    return out


def _repo_plist_mechanical_mismatches(by_label: dict, repo_root: str = REPO_ROOT) -> list[str]:
    """Расхождения механических полей манифеста с plist'ами самого репозитория.

    Сверяет ЗНАЧЕНИЯ, а не только «поле не null»: plist можно отредактировать
    (сменить час, переименовать скрипт), манифест при этом останется
    правдоподобным и непустым. Пустой список = совпало.

    Fail-CLOSED: если в репозитории не нашлось ни одного `com.spa.*.plist`,
    это НЕ чистый проход, а находка — сканер сломан (тот же принцип, что
    «не найдено ни одного entrypoint» = CRITICAL в `deployment_acceptance`).
    """
    plists = _repo_plists(repo_root)
    if not plists:
        return ["в репозитории не найдено ни одного com.spa.*.plist — "
                "сканер сломан, молчаливого «всё хорошо» тут не будет"]
    out: list[str] = []
    for label, path in sorted(plists.items()):
        rel = os.path.relpath(path, repo_root)
        with open(path, "rb") as f:
            pl = plistlib.load(f)
        a = by_label.get(label)
        if a is None:
            out.append(f"{label}: plist в репо ({rel}), записи в манифесте нет")
            continue
        src = a.get("plist_source")
        if src is None:
            out.append(f"{label}: plist в репо ({rel}), но манифест держит "
                       f"plist_source=null — механика не перегенерирована (--write)")
            continue
        if src == "launch_agents":
            # агент установлен ЕЩЁ И персистентно; ~/Library герметично не читаем,
            # поэтому здесь сверяется только то, что следует из самого plist_source
            if a.get("reboot_safe") is not True:
                out.append(f"{label}: plist_source=launch_agents, но "
                           f"reboot_safe={a.get('reboot_safe')!r}")
            continue
        if src != "repo:" + rel:
            out.append(f"{label}: plist_source={src!r}, а plist репозитория — {rel}")
            continue
        if a.get("reboot_safe") is not False:
            out.append(f"{label}: plist только в репо ({rel}), значит ребут его не "
                       f"переживёт, но манифест держит reboot_safe={a.get('reboot_safe')!r}")
        for field, expected in (("schedule", gen._parse_schedule(pl)),
                                ("program", gen._parse_program(pl))):
            if a.get(field) != expected:
                out.append(f"{label}: {field}={a.get(field)!r}, "
                           f"а plist {rel} даёт {expected!r}")
    return out


def _write_plist(directory: str, label: str, extra: dict | None = None) -> str:
    payload = {"Label": label,
               "ProgramArguments": ["/bin/bash", f"/tmp/{label}.sh"],
               "StartInterval": 300}
    payload.update(extra or {})
    path = os.path.join(directory, f"{label}.plist")
    with open(path, "wb") as f:
        plistlib.dump(payload, f)
    return path


class ScanAndSeed(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.la = os.path.join(self.tmp.name, "LaunchAgents")
        self.repo = os.path.join(self.tmp.name, "repo_launchd")
        os.makedirs(self.la)
        os.makedirs(self.repo)
        # генератор считает "персистентным" реальный ~/Library/LaunchAgents;
        # для теста подменяем константу на фикстурный каталог
        self._orig_la = gen.LAUNCH_AGENTS_DIR
        gen.LAUNCH_AGENTS_DIR = self.la

    def tearDown(self):
        gen.LAUNCH_AGENTS_DIR = self._orig_la
        self.tmp.cleanup()

    def _fresh(self):
        return {"schema_version": 1, "adr": "ADR-066", "agents": [],
                "artifacts": [], "designed_architectures": []}

    def test_la_plist_seeds_active_repo_plist_seeds_unresolved(self):
        """Инцидент auto_push 2026-08-05: репо-plist выглядел бы «живым»."""
        _write_plist(self.la, "com.spa.real_agent")
        _write_plist(self.repo, "com.spa.auto_push")
        plists = gen._scan_plists([self.la, self.repo])
        m = gen.build(self._fresh(), plists, {})
        by = {a["label"]: a for a in m["agents"]}
        self.assertEqual(by["com.spa.real_agent"]["intent"], "active")
        self.assertTrue(by["com.spa.real_agent"]["reboot_safe"])
        self.assertEqual(by["com.spa.auto_push"]["intent"], "unresolved")
        self.assertFalse(by["com.spa.auto_push"]["reboot_safe"])

    def test_registry_retired_wins_over_repo_plist(self):
        """digest_weekly: retired в реестре + остаточный репо-plist ⇒ retired."""
        _write_plist(self.repo, "com.spa.digest_weekly")
        plists = gen._scan_plists([self.la, self.repo])
        reg = {"com.spa.digest_weekly": {"label": "com.spa.digest_weekly",
                                         "retired": True, "role": "reporting"}}
        m = gen.build(self._fresh(), plists, reg)
        a = m["agents"][0]
        self.assertEqual(a["intent"], "retired")
        # …и это НЕ схемная проблема (plist не персистентный)
        self.assertEqual([p for p in gen.validate(m, plists) if "retired" in p], [])

    def test_retired_with_persistent_plist_is_flagged(self):
        _write_plist(self.la, "com.spa.zombie")
        plists = gen._scan_plists([self.la])
        reg = {"com.spa.zombie": {"label": "com.spa.zombie", "retired": True}}
        m = gen.build(self._fresh(), plists, reg)
        problems = gen.validate(m, plists)
        self.assertTrue(any("zombie" in p and "персистентный" in p for p in problems),
                        problems)

    def test_plist_without_manifest_entry_is_flagged(self):
        """Инцидент swarm_dwell: агент есть, в манифесте нет ⇒ красный."""
        _write_plist(self.la, "com.spa.swarm_dwell")
        plists = gen._scan_plists([self.la])
        problems = gen.validate(self._fresh(), plists)
        self.assertTrue(any("swarm_dwell" in p and "отсутствует" in p for p in problems),
                        problems)

    def test_active_without_any_plist_is_flagged(self):
        m = self._fresh()
        m["agents"] = [dict({"label": "com.spa.ghost"},
                            **{k: v for k, v in gen.CURATED_DEFAULTS.items()},
                            plist_source=None, reboot_safe=False,
                            schedule=None, program=None)]
        m["agents"][0]["intent"] = "active"
        problems = gen.validate(m, {})
        self.assertTrue(any("ghost" in p and "plist-файла нет" in p for p in problems))

    def test_consumer_required_without_produces_is_flagged(self):
        m = self._fresh()
        entry = dict({"label": "com.spa.io_mute"}, **gen.CURATED_DEFAULTS,
                     plist_source="launch_agents", reboot_safe=True,
                     schedule="daemon", program="x.sh")
        entry["intent"] = "active"
        entry["consumer_required"] = True
        m["agents"] = [entry]
        problems = gen.validate(m, {"com.spa.io_mute": {
            "plist_source": "launch_agents", "reboot_safe": True,
            "schedule": "daemon", "program": "x.sh"}})
        self.assertTrue(any("consumer_required" in p for p in problems), problems)

    def test_schedule_parsing(self):
        cases = [({"StartInterval": 300}, "interval:300s"),
                 ({"KeepAlive": True}, "daemon"),
                 ({"WatchPaths": ["/x"]}, "event:watchpaths"),
                 ({"StartCalendarInterval": {"Hour": 8, "Minute": 0}}, "calendar:08:00"),
                 ({"StartCalendarInterval": [{"Hour": 4, "Minute": 0, "Weekday": 2}]},
                  "calendar:wd2·04:00")]
        for extra, want in cases:
            pl = {"Label": "x", "ProgramArguments": ["/bin/true"]}
            pl.pop("StartInterval", None)
            pl.update(extra)
            if "StartInterval" not in extra:
                pl.pop("StartInterval", None)
            self.assertEqual(gen._parse_schedule(pl), want)

    def test_write_is_idempotent(self):
        """Конституция без шума: повторная сборка byte-identical."""
        _write_plist(self.la, "com.spa.a1")
        _write_plist(self.repo, "com.spa.a2")
        plists = gen._scan_plists([self.la, self.repo])
        m1 = gen.build(self._fresh(), plists, {})
        text1 = gen.dumps(m1)
        m2 = gen.build(json.loads(text1), plists, {})
        self.assertEqual(text1, gen.dumps(m2))

    def test_curation_survives_rebuild(self):
        """--write не смеет перетирать ручную правду."""
        _write_plist(self.la, "com.spa.a1")
        plists = gen._scan_plists([self.la])
        m = gen.build(self._fresh(), plists, {})
        m["agents"][0]["intent"] = "retired"
        m["agents"][0]["notes"] = "решение владельца"
        m["agents"][0]["produces"] = [{"artifact": "data/x.json", "slo_hours": 5}]
        m2 = gen.build(m, plists, {})
        a = m2["agents"][0]
        self.assertEqual(a["intent"], "retired")
        self.assertEqual(a["notes"], "решение владельца")
        self.assertEqual(a["produces"], [{"artifact": "data/x.json", "slo_hours": 5}])


class RealManifest(unittest.TestCase):
    """Машинонезависимые инварианты чекнутого architecture/manifest.json."""

    @classmethod
    def setUpClass(cls):
        cls.m = json.load(open(MANIFEST_PATH))
        cls.agents = cls.m["agents"]
        cls.by = {a["label"]: a for a in cls.agents}

    def test_schema_complete(self):
        self.assertEqual(self.m["schema_version"], 1)
        self.assertGreaterEqual(len(self.agents), 80)
        for a in self.agents:
            self.assertIn(a["intent"], gen.INTENTS, a["label"])
            self.assertIn(a["layer"], gen.LAYERS, a["label"])
            self.assertIn(a["curation"], gen.CURATION, a["label"])
            for f in gen.MECHANICAL_FIELDS + tuple(gen.CURATED_DEFAULTS):
                self.assertIn(f, a, f"{a['label']}: нет поля {f}")

    def test_unresolved_have_notes(self):
        """unresolved без объяснения — то же молчание, против которого манифест."""
        for a in self.agents:
            if a["intent"] == "unresolved":
                self.assertTrue(a["notes"].strip(), a["label"])

    def test_io_office_consumer_required(self):
        """Ядро находки 2026-08-05: 12 io_* обязаны иметь читателя."""
        io = [a for a in self.agents if a["label"].startswith("com.spa.io_")]
        self.assertEqual(len(io), 12)
        for a in io:
            self.assertTrue(a["consumer_required"], a["label"])
            self.assertTrue(a["produces"], a["label"])
            self.assertEqual(a["curation"], "complete", a["label"])

    def test_artifacts_reference_declared_agents(self):
        for art in self.m["artifacts"]:
            self.assertIn(art["status"], ("active", "planned"), art["path"])
            if art["producer"] is not None:
                self.assertIn(art["producer"], self.by, art["path"])
            if art["status"] == "active":
                self.assertGreater(art["slo_hours"], 0, art["path"])

    def test_registry_artifact_producer_is_declared_and_owns_it(self):
        """Инцидент 19-дневного реестра: производитель объявлен И правда его производит.

        НАМЕРЕННОЕ ИЗМЕНЕНИЕ ПРОВЕРКИ 2026-08-06 (инвариант #16, цикл #128, журнал
        `docs/journal/2026-W32.md`). Прежняя версия называлась
        `test_registry_artifact_declared_with_unknown_producer` и требовала
        `producer is None` — это фиксировало не правило, а **состояние инцидента**:
        производителя в расписании не было, и манифест честно писал `null`.
        Производитель появился (`com.spa.agent_health` → `agent_registry_refresh`),
        и с этого момента `null` стал бы ложью — тест краснел бы на ПОЧИНЕННОЕ.

        Охраняемое свойство осталось тем же — «манифест не врёт о том, кто производит
        реестр», — но проверка теперь СТРОЖЕ и держит обе стороны: мало назвать
        производителя, он обязан быть объявленным агентом И сам декларировать этот
        артефакт в `produces`. Сочинить производителя одной строкой больше нельзя.
        """
        reg = [a for a in self.m["artifacts"] if a["path"] == "data/agent_registry.json"]
        self.assertEqual(len(reg), 1)
        producer = reg[0]["producer"]
        self.assertIsNotNone(
            producer, "у реестра снова нет производителя — рецидив инцидента 2026-08-05")
        self.assertIn(producer, self.by, "производитель реестра не объявлен среди агентов")
        produced = {p["artifact"] for p in self.by[producer].get("produces", [])}
        self.assertIn(
            "data/agent_registry.json", produced,
            f"{producer} назначен производителем реестра, но сам его не декларирует")

    def test_designed_architectures_present(self):
        names = " ".join(d["name"] for d in self.m["designed_architectures"])
        self.assertIn("Head-of-Investment", names)
        self.assertIn("ADR-066", names)

    def test_repo_plist_agents_carry_their_mechanical_fields(self):
        """Дрейф 2026-08-06, положительный контроль: у `com.spa.morning_digest`
        plist лежал в `launchd/`, а `plist_source`/`schedule`/`program` в манифесте
        были `null` — генератор краснел на прод-хосте, а В CI ЭТОГО НЕ ВИДНО:
        соседний `test_generator_check_passes_on_this_machine_or_skips` честно
        скипается там, где нет `~/Library/LaunchAgents/com.spa.*`.

        Эта проверка герметична — читает ТОЛЬКО plist'ы репозитория и чекнутый
        манифест, поэтому класс дрейфа ловится и в CI. На манифесте до починки
        краснеет ровно одной записью.
        """
        labels = {os.path.basename(p)[:-len(".plist")]
                  for d in ("launchd", "scripts")
                  for p in glob.glob(os.path.join(REPO_ROOT, d, "com.spa.*.plist"))}
        self.assertTrue(labels, "в репозитории не найдено ни одного com.spa.*.plist — "
                                "сканер сломан, молчаливого «всё хорошо» тут не будет")
        for label in sorted(labels):
            self.assertIn(label, self.by, f"{label}: plist в репо, записи в манифесте нет")
            for field in ("plist_source", "schedule", "program"):
                self.assertIsNotNone(
                    self.by[label][field],
                    f"{label}: plist в репо, но манифест держит {field}=null — "
                    f"механическое поле не перегенерировано (--write)")

    def test_repo_plist_mechanical_fields_equal_the_plist(self):
        """Рецидив 2026-08-06 (третий за неделю) и то, чего соседняя проверка НЕ видит.

        Соседний `test_repo_plist_agents_carry_their_mechanical_fields` требует лишь
        «поле не null». Этого хватило, чтобы поймать `com.spa.morning_digest` (циклы
        #128/#130 чинили, следующая же сессия снова записывала null — манифест
        генерируется от СВОЕГО дерева и уезжает пофайлово поверх чужой починки), но
        не хватит на дрейф ЗНАЧЕНИЯ: поправили час в plist'е — манифест остаётся
        непустым и правдоподобным, а врёт. Здесь сверяются сами значения, и
        `reboot_safe` — тоже (репо-plist ребут не переживает).

        Герметично: читаются только plist'ы репозитория и чекнутый манифест,
        поэтому класс ловится в CI, а не только на прод-хосте.
        """
        self.assertEqual(
            _repo_plist_mechanical_mismatches(self.by), [],
            "механика манифеста разошлась с plist'ами репозитория — "
            "перегенерировать: python3 scripts/build_architecture_manifest.py --write")

    def test_generator_check_passes_on_this_machine_or_skips(self):
        """На прод-хосте --check обязан быть зелёным; в CI (нет ~/Library
        с com.spa.*) проверка честно скипается, НЕ красится."""
        import glob as _glob
        if not _glob.glob(os.path.join(gen.LAUNCH_AGENTS_DIR, "com.spa.*.plist")):
            self.skipTest("не прод-хост: ~/Library/LaunchAgents без com.spa.*")
        r = subprocess.run([sys.executable, GEN_PATH], capture_output=True,
                           text=True, cwd=REPO_ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class MechanicalMismatchControls(unittest.TestCase):
    """Положительные контроли сверки механики (правило .claude/rules/deployment.md:
    проверка, никогда не видевшая настоящей поломки, — украшение).

    Каждый контроль берёт РЕАЛЬНЫЙ манифест, вносит ровно одну порчу и требует,
    чтобы сверка назвала именно её. Последний контроль — в обратную сторону:
    нетронутый манифест обязан давать пустой список, иначе «краснеет всегда»
    ничего не доказывает.
    """

    @classmethod
    def setUpClass(cls):
        m = json.load(open(MANIFEST_PATH))
        cls.by = {a["label"]: a for a in m["agents"]}
        # подопытный: label, чей plist лежит ТОЛЬКО в репозитории
        cls.label = next(
            (lb for lb, a in cls.by.items()
             if isinstance(a.get("plist_source"), str)
             and a["plist_source"].startswith("repo:")),
            None)
        if cls.label is None:
            raise unittest.SkipTest("в манифесте нет ни одного агента с репо-plist")

    def _tampered(self, **fields):
        by = {lb: dict(a) for lb, a in self.by.items()}
        by[self.label].update(fields)
        return by

    def test_control_null_mechanical_field_is_reported(self):
        """Ровно инцидент 2026-08-06: plist в репо, а в манифесте null."""
        found = _repo_plist_mechanical_mismatches(
            self._tampered(plist_source=None, schedule=None, program=None))
        self.assertTrue(any(self.label in f and "null" in f for f in found), found)

    def test_control_stale_schedule_is_reported(self):
        """Класс, невидимый для проверки «не null»: значение расписания устарело."""
        found = _repo_plist_mechanical_mismatches(
            self._tampered(schedule="calendar:03:33"))
        self.assertTrue(any(self.label in f and "schedule" in f for f in found), found)

    def test_control_stale_program_is_reported(self):
        found = _repo_plist_mechanical_mismatches(
            self._tampered(program="agent_of_another_era.sh"))
        self.assertTrue(any(self.label in f and "program" in f for f in found), found)

    def test_control_reboot_safe_lie_is_reported(self):
        """Репо-plist ребут не переживает; reboot_safe=True тут — ложь о живучести."""
        found = _repo_plist_mechanical_mismatches(self._tampered(reboot_safe=True))
        self.assertTrue(any(self.label in f and "reboot_safe" in f for f in found), found)

    def test_control_missing_agent_entry_is_reported(self):
        by = {lb: dict(a) for lb, a in self.by.items() if lb != self.label}
        found = _repo_plist_mechanical_mismatches(by)
        self.assertTrue(any(self.label in f and "нет" in f for f in found), found)

    def test_control_empty_scan_is_not_a_clean_pass(self):
        """Fail-CLOSED: «не нашли ни одного plist'а» — находка, а не зелёный свет
        (тот же принцип, что «не найдено ни одного entrypoint» = CRITICAL)."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            found = _repo_plist_mechanical_mismatches({}, repo_root=d)
        self.assertTrue(found, "пустой скан выдал чистый проход — это молчание, не проверка")
        self.assertIn("сканер сломан", " ".join(found))

    def test_control_untampered_manifest_is_clean(self):
        """Обратная сторона: без порчи расхождений быть не должно."""
        self.assertEqual(_repo_plist_mechanical_mismatches(self.by), [])


if __name__ == "__main__":
    unittest.main()
