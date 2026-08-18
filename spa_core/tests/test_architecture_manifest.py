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


class DriftIsReadableByMachine(unittest.TestCase):
    """Цикл #264: диагноз обязан быть ДОСТУПЕН, а не только напечатан.

    Авария 16.08: прод-дерево не получает `launchd/` при автосинке (правило
    code_sync возит `spa_core/`·`scripts/`·`tests/`), из фактов пропал
    `com.spa.site_freshness`, генератор напечатал три строки DRIFT — а сторож
    `architecture_conformance` (B5) брал от него ОДИН код возврата и слал
    владельцу находку без единого факта, со ссылкой на несуществующий флаг.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.la = os.path.join(self.tmp.name, "LaunchAgents")
        self.repo = os.path.join(self.tmp.name, "repo_launchd")
        os.makedirs(self.la)
        os.makedirs(self.repo)
        self._orig_la = gen.LAUNCH_AGENTS_DIR
        gen.LAUNCH_AGENTS_DIR = self.la
        self.manifest_path = os.path.join(self.tmp.name, "manifest.json")

    def tearDown(self):
        gen.LAUNCH_AGENTS_DIR = self._orig_la
        self.tmp.cleanup()

    def _seed(self, labels):
        """Записать манифест, ровно соответствующий фактам этих plist'ов."""
        for lb in labels:
            _write_plist(self.la, lb)
        plists = gen._scan_plists([self.la, self.repo])
        m = gen.build({"schema_version": 1, "adr": "ADR-066", "agents": [],
                       "artifacts": [], "designed_architectures": []}, plists, {})
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            f.write(gen.dumps(m))
        return m

    def _measure(self):
        return gen.measure(self.manifest_path, os.path.join(self.tmp.name, "no_registry.json"),
                           [self.la, self.repo])

    def test_agent_vanished_from_facts_names_agent_and_fields(self):
        """Ровно авария site_freshness: plist пропал из дерева."""
        self._seed(["com.spa.keeper", "com.spa.site_freshness"])
        os.remove(os.path.join(self.la, "com.spa.site_freshness.plist"))
        drift = self._measure()["drift"]
        own = [d for d in drift if d.startswith("com.spa.site_freshness:")]
        self.assertTrue(own, drift)
        joined = " ".join(own)
        for field in ("plist_source", "schedule", "program"):
            self.assertIn(field, joined)
        self.assertIn("None", joined)
        self.assertFalse([d for d in drift if d.startswith("com.spa.keeper:")], drift)

    def test_measure_agrees_with_cli_verdict_both_ways(self):
        """ОДИН источник вердикта: пусто ⇔ CLI в режиме сверки вернул бы 0."""
        self._seed(["com.spa.keeper"])
        m = self._measure()
        self.assertEqual((m["problems"], m["drift"]), ([], []))
        self.assertEqual(self._cli(), 0)
        os.remove(os.path.join(self.la, "com.spa.keeper.plist"))
        m = self._measure()
        self.assertTrue(m["problems"] or m["drift"])
        self.assertEqual(self._cli(), 2)

    def _cli(self):
        return gen.main(["--manifest", self.manifest_path,
                         "--registry", os.path.join(self.tmp.name, "no_registry.json"),
                         "--plist-dir", self.la, "--plist-dir", self.repo])

    def test_missing_manifest_is_named_not_swallowed(self):
        self._seed(["com.spa.keeper"])
        os.remove(self.manifest_path)
        self.assertIn("манифест отсутствует — запустить --write", self._measure()["drift"])

    def test_measure_has_no_side_effects(self):
        """Замер не пишет и не печатает — иначе сторож не смог бы им пользоваться."""
        import io
        import contextlib
        self._seed(["com.spa.keeper"])
        before = open(self.manifest_path, encoding="utf-8").read()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self._measure()
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(open(self.manifest_path, encoding="utf-8").read(), before)

    def test_check_flag_does_not_exist(self):
        """Находка B5 три месяца советовала `--check`. Его НЕТ — и текст находки
        обязан был это учитывать. Если флаг когда-нибудь появится, тест краснеет
        и заставит перечитать формулировки, а не оставит их врать молча."""
        with self.assertRaises(SystemExit) as cm:
            gen.main(["--check"])
        self.assertEqual(cm.exception.code, 2)
        self.assertNotIn("--check (дефолт)", gen.__doc__)


class RepoPlistNotDeliveredHere(unittest.TestCase):
    """Цикл #267 — авария 16.08 на ПРОДЕ, дословно.

    Манифест объявляет `com.spa.site_freshness` как
    `repo:launchd/com.spa.site_freshness.plist`. На `origin/main` файл ЕСТЬ,
    в прод-дереве его нет — `code_sync_from_origin.sh` возит только
    `spa_core/ scripts/ tests/`. Сторож печатал три строки «→ None» и звучал
    как ДРЕЙФ МЕХАНИКИ, хотя мерил ГРАНИЦУ СИНХРОНИЗАЦИИ; находка кормит мост
    карточками владельцу, а ложная — тратит его внимание.

    Каждый тест ниже — либо этот инцидент, либо ОБРАТНЫЙ контроль: молчать
    можно только по положительному доказательству, во всех остальных случаях
    дрейф обязан остаться дрейфом.
    """

    LABELS = ("com.spa.keeper", "com.spa.site_freshness")
    REL = os.path.join("launchd", "com.spa.site_freshness.plist")

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.launchd = os.path.join(self.root, "launchd")
        self.la = os.path.join(self.root, "LaunchAgents")   # пустой: герметичность
        os.makedirs(self.launchd)
        os.makedirs(self.la)
        self.manifest_path = os.path.join(self.root, "architecture", "manifest.json")
        os.makedirs(os.path.dirname(self.manifest_path))
        self.registry_path = os.path.join(self.root, "no_registry.json")

        # `_scan_plists` строит `repo:<путь>` относительно gen.REPO_ROOT — чтобы
        # получить ровно ту форму, что в проде, корень на время теста наш.
        self._orig_root, self._orig_la = gen.REPO_ROOT, gen.LAUNCH_AGENTS_DIR
        gen.REPO_ROOT, gen.LAUNCH_AGENTS_DIR = self.root, self.la
        self.addCleanup(self._restore)

        for lb in self.LABELS:
            _write_plist(self.launchd, lb)
        self._seed_manifest()

    def _restore(self):
        gen.REPO_ROOT, gen.LAUNCH_AGENTS_DIR = self._orig_root, self._orig_la

    def _seed_manifest(self):
        plists = gen._scan_plists([self.la, self.launchd])
        m = gen.build({"schema_version": 1, "adr": "ADR-066", "agents": [],
                       "artifacts": [], "designed_architectures": []}, plists, {})
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            f.write(gen.dumps(m))
        return m

    def _git(self, *args):
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_CONFIG_SYSTEM=os.devnull,
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        return subprocess.run(["git", *args], cwd=self.root, env=env,
                              capture_output=True, text=True, check=True)

    def _commit_all(self, msg="seed", publish=True):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", msg)
        if publish:
            # ровно тот ref, которым живёт прод (`CURATION_REF`): remote-tracking,
            # а не ветка с похожим именем — иначе тест мерил бы не то, что сторож
            self._git("update-ref", "refs/remotes/origin/main", "HEAD")

    def _init_repo(self):
        self._git("init", "-q")
        self._commit_all()

    def _measure(self, ref=None):
        # позднее связывание НАМЕРЕННО: `ref=gen.CURATION_REF` в сигнатуре
        # вычисляется при СБОРКЕ модуля, и на дереве без правки это давало бы
        # ошибку коллекции — она отравляет весь прогон, и контроль перестал бы
        # мерить поведение (урок «collection error poisons the whole run»).
        ref = gen.CURATION_REF if ref is None else ref
        return gen.measure(self.manifest_path, self.registry_path,
                           [self.la, self.launchd], self.root, ref)

    def _own(self, lines):
        return [x for x in lines if x.startswith("com.spa.site_freshness:")]

    # ── сама авария ─────────────────────────────────────────────────────────

    def test_missing_here_but_present_on_ref_is_not_drift(self):
        """Файл есть на ref, нет в дереве ⇒ НЕ дрейф механики.

        ИЗМЕНЁН ЦИКЛОМ #236, намеренно (инв. #16), и это УЖЕСТОЧЕНИЕ, а не
        поблажка. Ядро утверждения — `drift == []`, «граница синхронизации не
        выдана за дрейф» — стоит на месте и проверяется здесь по-прежнему.
        Изменилась вторая половина: раньше утверждалось «и признайся, что не
        измерил», теперь — «и ИЗМЕРЬ там, где ответ есть». Признание #267 было
        верным, но необратимым: вердикт B5 в прод-дереве застревал на UNCHECKED
        навсегда, и настоящее «сошлось» становилось неотличимо от «нечем
        проверить». Прежнее поведение никуда не делось — оно проверяется
        `test_unreadable_on_ref_stays_unmeasured` (ref нечитаем) и всеми
        обратными контролями ниже.
        """
        self._init_repo()
        os.remove(os.path.join(self.root, self.REL))
        m = self._measure()
        self.assertEqual(m["drift"], [], "граница синхронизации выдана за дрейф")
        self.assertEqual(self._own(m["unmeasurable"]), [], m["unmeasurable"])
        prov = [p for p in m["measured_from_ref"]
                if p["label"] == "com.spa.site_freshness"]
        self.assertEqual(len(prov), 1, m["measured_from_ref"])
        # провенанс обязан быть ПОВТОРЯЕМЫМ читателем: путь + ref + вердикт
        self.assertEqual(prov[0]["plist"], self.REL.replace(os.sep, "/"))
        self.assertEqual(prov[0]["ref"], gen.CURATION_REF)
        self.assertIn("manifest.json", prov[0]["manifest"])
        self.assertTrue(prov[0]["agrees"])
        # сосед по каталогу не задет
        self.assertFalse([x for x in m["drift"] + m["unmeasurable"]
                          if x.startswith("com.spa.keeper:")], m)

    def test_ref_disagreement_is_named_as_drift(self):
        """Сторож стал строже, а не зеленее: расхождение НА ORIGIN обязано
        краснеть — до цикла #236 такой случай был неотличим от согласия,
        оба тонули в одном «не измерено»."""
        self._init_repo()
        # манифест на ref говорит одно, plist на ref — другое
        m0 = json.load(open(self.manifest_path))
        for a in m0["agents"]:
            if a["label"] == "com.spa.site_freshness":
                a["schedule"] = "interval:99999s"
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            f.write(gen.dumps(m0))
        self._commit_all("манифест на origin разошёлся с plist'ом")
        os.remove(os.path.join(self.root, self.REL))
        m = self._measure()
        own = [x for x in self._own(m["drift"]) if "schedule" in x]
        self.assertTrue(own, m)
        # находка обязана НАЗЫВАТЬ, чем мерили, — иначе читатель не повторит
        self.assertIn(gen.CURATION_REF, own[0])
        self.assertIn(self.REL.replace(os.sep, "/"), own[0])
        self.assertEqual(self._own(m["unmeasurable"]), [], m["unmeasurable"])
        self.assertFalse(m["measured_from_ref"][0]["agrees"])

    def test_unreadable_on_ref_stays_unmeasured(self):
        """Файл на ref ЕСТЬ, но разобрать его нечем (не plist) ⇒ «не измерено»,
        а НЕ «сошлось». Fail-CLOSED: замер #236 покупает зелёный вердикт только
        прочитанным содержимым, а не самим фактом присутствия пути."""
        self._init_repo()
        with open(os.path.join(self.root, self.REL), "w", encoding="utf-8") as f:
            f.write("это не plist")
        self._commit_all("на origin лежит мусор вместо plist")
        os.remove(os.path.join(self.root, self.REL))
        m = self._measure()
        own = self._own(m["unmeasurable"])
        self.assertEqual(len(own), 1, m)
        self.assertIn("НЕ ИЗМЕРЕНА", own[0])
        self.assertEqual(m["measured_from_ref"], [], m)
        self.assertEqual(self._own(m["drift"]), [], m)

    def test_manifest_absent_on_ref_stays_unmeasured(self):
        """Вторая сторона сравнения обязана быть с ТОГО ЖЕ ref. Манифеста на ref
        нет ⇒ судить не по чему ⇒ «не измерено». Без этого сторож молча
        сравнивал бы plist с origin против манифеста ЭТОГО дерева — а `architecture/`
        сюда тоже не синкается, и совпадение копий не гарантировано ничем."""
        self._init_repo()
        os.remove(self.manifest_path)
        self._commit_all("на origin манифеста нет")
        self._seed_manifest()          # локально манифест есть, на ref — нет
        os.remove(os.path.join(self.root, self.REL))
        m = self._measure()
        self.assertEqual(m["measured_from_ref"], [], m)
        self.assertEqual(len(self._own(m["unmeasurable"])), 1, m)

    def test_three_fields_collapse_into_one_line(self):
        """Три поля «→ None» имеют ОДНУ причину — и строка обязана быть одна,
        иначе шум просто переехал из находок в `unchecked`.

        Условие пришлось усилить (#236): случай «не измерено» теперь достигается
        только НЕПРОЧИТАННЫМ ref, поэтому проба стала точнее — она мерит ровно
        группировку, а не побочный эффект отсутствия файла."""
        self._init_repo()
        with open(os.path.join(self.root, self.REL), "w", encoding="utf-8") as f:
            f.write("это не plist")
        self._commit_all("на origin мусор")
        os.remove(os.path.join(self.root, self.REL))
        self.assertEqual(len(self._measure()["unmeasurable"]), 1)

    # ── обратные контроли: молчать только по доказательству ─────────────────

    def test_deleted_on_ref_too_stays_drift(self):
        """Файл удалён ВЕЗДЕ — это настоящая пропажа, и она обязана краснеть."""
        self._init_repo()
        os.remove(os.path.join(self.root, self.REL))
        self._commit_all("удалили по-настоящему")
        m = self._measure()
        own = self._own(m["drift"])
        self.assertTrue(own, m)
        joined = " ".join(own)
        for field in ("plist_source", "schedule", "program"):
            self.assertIn(field, joined)
        self.assertEqual(self._own(m["unmeasurable"]), [], m["unmeasurable"])

    def test_vanished_from_launch_agents_stays_drift(self):
        """Пропажа из ~/Library/LaunchAgents — факт о ФЛОТЕ, не о синхронизации:
        такой plist сюда никто и не «возит», его сняли."""
        self._init_repo()
        _write_plist(self.la, "com.spa.loaded")
        self._seed_manifest()
        os.remove(os.path.join(self.la, "com.spa.loaded.plist"))
        m = self._measure()
        self.assertTrue([x for x in m["drift"] if x.startswith("com.spa.loaded:")], m)
        self.assertEqual([x for x in m["unmeasurable"]
                          if x.startswith("com.spa.loaded:")], [], m)

    def test_bare_path_source_is_not_treated_as_repo_path(self):
        """Префикс `repo:` — часть КОНТРАКТА манифеста, а не украшение.

        Зонд условия 2 напрямую: источник без префикса, а путь на ref РАЗРЕШИМ.
        Уберут проверку префикса — молчание достанется чему угодно похожему на
        путь, включая `launch_agents` (пропажа из ~/Library = факт о ФЛОТЕ).
        """
        self._init_repo()
        os.remove(os.path.join(self.root, self.REL))
        bare = {"plist_source": self.REL.replace(os.sep, "/")}   # БЕЗ "repo:"
        self.assertIsNone(
            gen.unmeasurable_missing_plist(bare, {"plist_source": None},
                                           self.root, gen.CURATION_REF))
        # …а с префиксом тот же путь объясняется — контроль в другую сторону
        self.assertIsNotNone(
            gen.unmeasurable_missing_plist(
                {"plist_source": "repo:" + self.REL.replace(os.sep, "/")},
                {"plist_source": None}, self.root, gen.CURATION_REF))

    def test_no_git_no_silence(self):
        """Спросить не у кого (каталог не репозиторий) ⇒ дрейф остаётся.
        Fail-CLOSED: сторож не смеет зеленеть от того, что ему нечем проверить."""
        os.remove(os.path.join(self.root, self.REL))
        m = self._measure()
        self.assertTrue(self._own(m["drift"]), m)
        self.assertEqual(m["unmeasurable"], [], m)

    def test_unknown_ref_no_silence(self):
        """Репозиторий есть, а ref не разрешается — тот же отказ молчать.
        Без этого «нет ветки» стало бы неотличимо от «файл на месте»."""
        self._init_repo()
        os.remove(os.path.join(self.root, self.REL))
        m = self._measure(ref="origin/net-takogo-ref")
        self.assertTrue(self._own(m["drift"]), m)
        self.assertEqual(m["unmeasurable"], [], m)

    def test_file_in_place_but_field_edited_stays_drift(self):
        """Путь на месте, а механика разошлась (переписали расписание) —
        сужение не смеет глотать НАСТОЯЩЕЕ расхождение полей."""
        self._init_repo()
        m0 = json.load(open(self.manifest_path))
        for a in m0["agents"]:
            if a["label"] == "com.spa.site_freshness":
                a["schedule"] = "interval:99999s"
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            f.write(gen.dumps(m0))
        m = self._measure()
        self.assertTrue([x for x in self._own(m["drift"]) if "schedule" in x], m)
        self.assertEqual(m["unmeasurable"], [], m)

    def test_plist_found_elsewhere_stays_drift(self):
        """Репо-plist доехал до LaunchAgents: факт НАЙДЕН, судить есть по чему —
        `plist_source repo:… → launch_agents` обязано остаться дрейфом."""
        self._init_repo()
        os.replace(os.path.join(self.root, self.REL),
                   os.path.join(self.la, "com.spa.site_freshness.plist"))
        m = self._measure()
        self.assertTrue([x for x in self._own(m["drift"]) if "plist_source" in x], m)
        self.assertEqual(m["unmeasurable"], [], m)

    # ── вердикт целиком ─────────────────────────────────────────────────────

    def test_explained_difference_is_not_serialization_mystery(self):
        """Когда ВСЁ расхождение объяснено, запасная строка «недиагностированное
        расхождение сериализации» обязана молчать — иначе сторож выдумал бы
        себе находку ровно там, где только что честно признался в незнании."""
        self._init_repo()
        os.remove(os.path.join(self.root, self.REL))
        m = self._measure()
        self.assertEqual(m["drift"], [], m)
        self.assertFalse([x for x in m["unmeasurable"] if "сериализац" in x], m)

    def test_cli_says_one_for_unmeasurable_neither_zero_nor_two(self):
        """Все четыре исхода CLI по одному сценарию, в порядке ужесточения.

        ИЗМЕНЁН #236 намеренно (инв. #16): средняя ступень раньше была «файла
        нет здесь ⇒ 1», теперь этот случай ИЗМЕРИМ и честно даёт 0, а код 1
        остался ровно за тем, что не измеримо нигде (ref нечитаем). Проверка не
        сузилась, а выросла с трёх ступеней до четырёх.
        """
        self._init_repo()
        argv = ["--manifest", self.manifest_path, "--registry", self.registry_path,
                "--plist-dir", self.la, "--plist-dir", self.launchd]
        self.assertEqual(gen.main(argv), 0, "файл на месте — сошлось")
        os.remove(os.path.join(self.root, self.REL))
        self.assertEqual(gen.main(argv), 0, "нет здесь, но прочитан с ref — сошлось")
        with open(os.path.join(self.root, self.REL), "w", encoding="utf-8") as f:
            f.write("это не plist")
        self._commit_all("на origin мусор вместо plist")
        os.remove(os.path.join(self.root, self.REL))
        self.assertEqual(gen.main(argv), 1, "прочитать нечем — и не 0, и не 2")
        self._commit_all("удалили по-настоящему")   # рабочее дерево уже без файла
        self.assertEqual(gen.main(argv), 2, "пропал везде — расхождение")


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
