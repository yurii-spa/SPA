"""Разбор семи сирот, вскрытых стриппером строк-СООБЩЕНИЙ (#258): по каждому — след.

Коммит 8519e2e научил детектор не считать проводкой упоминание имени в тексте (`help=`,
фраза в JSON-ответе API, подсказка в f-строке) — и семь скриптов, всё это время
числившихся подключёнными, остались без единого вызывающего. Дописать их в
`unwired_scripts_baseline.json` запрещает сам храповик, поэтому каждый разобран поштучно
(образец — `test_unwired_seven_verdicts.py`, цикл #248).

| скрипт | вердикт | что стережёт этот файл |
|---|---|---|
| `findings_to_cards` | СПИСАН | дубль входа: логику гоняет агент `com.spa.decision_loop` |
| `defenses_exercised_report` | ПОДКЛЮЧЁН | шаг 7 дневного цикла — у артефакта ЕСТЬ читатель |
| `optimizer_ab` | ПОДКЛЮЧЁН | шаг 8 дневного цикла — ручка API отдавала отказ всегда |
| `verify_riskwire` | ПОДКЛЮЧЁН | шаг 9: свой верификатор мы гоняем САМИ (как `verify_spa`) |
| `verify_dfb_pool` | ПОДКЛЮЧЁН | там же |
| `build_dd_snapshot` | ПОДКЛЮЧЁН | внутри `refresh_published_proof` — вместе с DD_PACK |
| `find_defillama_sources` | ОСТАВЛЕН КРАСНЫМ | решение владельца, карточка заведена |

**Отдельно — гипотеза, которую замер ОТВЕРГ.** Коммит 8519e2e предположил, что
`verify_riskwire` / `verify_dfb_pool` — ЧЕТВЁРТЫЙ вычитаемый класс: верификаторы
«не верь нам, проверь нас», у которых вызывающего нет ПО УСТРОЙСТВУ, потому что их
запускает третья сторона. Проверка гипотезы — ниже, `TestThirdPartyVerifierIsNotAClass`:
у СТАРШЕГО брата этого же семейства, `scripts/verify_spa.py`, вызывающих ТРИ, и все —
наши. Значит «третья сторона» — не устройство, а невыполненная работа: правило дома
ровно обратное — свой верификатор дом гоняет сам. Класс не заведён; заведи мы его,
он вычёл бы из-под храповика ровно те скрипты, которые надо было подключить.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CYCLE = _ROOT / "scripts" / "run_daily_paper_cycle.sh"


def _uncommented(text: str) -> str:
    """Строки shell без комментариев — упоминание в комментарии вызовом не является."""
    return "\n".join(
        line.split("#", 1)[0] for line in text.splitlines() if line.split("#", 1)[0].strip()
    )


def _cycle_commands() -> str:
    return _uncommented(_CYCLE.read_text(encoding="utf-8"))


# ───────────────────────────────────────────────────────────────────────────────
# 1. findings_to_cards — СПИСАН: дубль входа над живым мостом
# ───────────────────────────────────────────────────────────────────────────────
class TestFindingsToCardsWasADuplicateEntry(unittest.TestCase):
    """Три следа смерти входа `scripts/findings_to_cards.py` (образец #227/#248).

    1. вызывающего нет — это и сказал храповик 17.08;
    2. ЛОГИКА исполняется каждые 6 часов: развёрнутый агент `com.spa.decision_loop`
       зовёт `spa_core.monitoring.findings_bridge --run` НАПРЯМУЮ (обёртка
       `scripts/agent_decision_loop.sh`), и дневной цикл отдельно оговаривает, что
       дублировать этот шаг нельзя — два писателя за один `data/house_view_gap.json`;
    3. удалённый файл не добавлял НИЧЕГО: он был шимом в семь строк, который
       импортировал `main` того самого модуля и подставлял `--run` по умолчанию —
       то есть ровно ту команду, которую агент и так передаёт явно.

    Мёртв был дубль входа, а не мост ADR-066.
    """

    def test_the_shim_entrypoint_is_gone(self):
        self.assertFalse((_ROOT / "scripts" / "findings_to_cards.py").exists(),
                         "вход-дубль вернулся — либо подключи его, либо он снова сирота")

    def test_the_deployed_agent_still_runs_the_bridge(self):
        wrapper = (_ROOT / "scripts" / "agent_decision_loop.sh").read_text(encoding="utf-8")
        self.assertIn("spa_core.monitoring.findings_bridge", _uncommented(wrapper))
        self.assertIn("--run", _uncommented(wrapper))

    def test_the_bridge_keeps_its_own_cli(self):
        """Вход не исчез — он остался там, где его и зовут: у самого модуля."""
        src = (_ROOT / "spa_core" / "monitoring" / "findings_bridge.py").read_text(encoding="utf-8")
        self.assertIn("def main(", src)
        tree = ast.parse(src)
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertIn("main", names)

    def test_the_cycle_still_refuses_to_duplicate_the_bridge(self):
        """Отрицательное плечо: удаление шима не имеет права протащить шаг в цикл."""
        self.assertNotIn("findings_bridge", _cycle_commands(),
                         "мост попал в дневной цикл — это второй писатель house_view_gap.json")


# ───────────────────────────────────────────────────────────────────────────────
# 2. defenses_exercised_report — ПОДКЛЮЧЁН: у артефакта ЕСТЬ читатель
# ───────────────────────────────────────────────────────────────────────────────
class TestDefensesExercisedIsWiredToItsReader(unittest.TestCase):
    """Отчёт «тормоза срабатывают» производителя не имел, а ЧИТАТЕЛЬ у него был всегда.

    `spa_core/api/routers/readiness.py` грузит `data/defenses_exercised.json` и
    `data/defenses_exercised_rtmr.json` и строит на них довод «governance defenses FIRE».
    Оба файла не производил никто: у обоих скриптов не было ни агента, ни шага цикла.
    То есть публичная страница готовности ссылалась на доказательство, которого в дереве
    не существовало. Теперь их производит шаг 7 дневного цикла.
    """

    def test_the_reader_exists_and_names_both_artifacts(self):
        src = (_ROOT / "spa_core" / "api" / "routers" / "readiness.py").read_text(encoding="utf-8")
        self.assertIn("defenses_exercised.json", src)
        self.assertIn("defenses_exercised_rtmr.json", src)

    def test_both_producers_are_steps_of_the_daily_cycle(self):
        cmds = _cycle_commands()
        self.assertIn("scripts/defenses_exercised_report.py", cmds)
        self.assertIn("scripts/defenses_exercised_rtmr.py", cmds)

    def test_the_step_is_non_fatal(self):
        """Находка «защита не сработала» не имеет права стоить дня трека."""
        for line in _cycle_commands().splitlines():
            if "defenses_exercised" in line:
                self.assertTrue(line.rstrip().endswith("\\") or "||" in line,
                                f"шаг сделан фатальным: {line}")

    def test_the_report_is_inert_by_construction(self):
        """Он гоняет НАСТОЯЩИЙ kill-switch, но в одноразовой песочнице."""
        src = (_ROOT / "scripts" / "defenses_exercised_report.py").read_text(encoding="utf-8")
        self.assertIn("from spa_core.governance.kill_switch import", src)
        self.assertIn("tempfile", src)


# ───────────────────────────────────────────────────────────────────────────────
# 3. optimizer_ab — ПОДКЛЮЧЁН: ручка API отдавала отказ ВСЕГДА
# ───────────────────────────────────────────────────────────────────────────────
class TestOptimizerAbIsWiredToItsEndpoint(unittest.TestCase):
    """`GET /api/optimizer-ab` читает `data/optimizer_ab.json`, а писать его было некому.

    Роутер честно отвечал `optimizer_ab_artifact_missing` и советовал «запустите
    scripts/optimizer_ab.py» — но у харнесса не было ни агента, ни шага цикла, так что
    совет был единственным, что вообще происходило. Теперь его гоняет шаг 8.
    """

    def test_the_endpoint_reads_the_artifact(self):
        src = (_ROOT / "spa_core" / "api" / "routers" / "optimizer.py").read_text(encoding="utf-8")
        self.assertIn("optimizer_ab.json", src)
        self.assertIn("optimizer_ab_artifact_missing", src)

    def test_the_harness_is_a_step_of_the_daily_cycle(self):
        self.assertIn("scripts/optimizer_ab.py", _cycle_commands())

    def test_wiring_did_NOT_flip_the_cycle_default(self):
        """Отрицательное плечо: подключён ЗАМЕР, а не переключение аллокатора.

        Харнесс — shadow-replay за флагом. Если бы проводка заодно включила оптимизатор
        в цикле, это была бы правка money-path под видом уборки сирот.
        """
        src = (_ROOT / "scripts" / "optimizer_ab.py").read_text(encoding="utf-8")
        self.assertIn("SPA_OPTIMIZER_CYCLE_DEFAULT", src)
        self.assertNotIn("SPA_OPTIMIZER_CYCLE_DEFAULT", _cycle_commands(),
                         "дневной цикл начал выставлять флаг оптимизатора — это не уборка сирот")


# ───────────────────────────────────────────────────────────────────────────────
# 4+5. verify_riskwire / verify_dfb_pool — ПОДКЛЮЧЕНЫ, и это НЕ новый класс
# ───────────────────────────────────────────────────────────────────────────────
class TestThirdPartyVerifierIsNotAClass(unittest.TestCase):
    """Гипотеза «у верификатора вызывающего нет ПО УСТРОЙСТВУ» — ОТВЕРГНУТА замером.

    Семейство одно: `verify_spa.py` (surfaces A–G), `verify_dfb_pool.py` (per-pool),
    `verify_riskwire.py` (measurements + day30). Все трое — standalone, zero-dependency,
    «скачай один файл и перепроверь нас». Если бы отсутствие вызывающего было свойством
    УСТРОЙСТВА, сиротой был бы и старший брат. Он не сирота: его грузят и исполняют три
    наших собственных файла. Значит дом обязан гонять свой верификатор сам, а молчание
    вокруг двух младших было не устройством, а невыполненной работой.

    Цена ошибки, если бы класс всё-таки завели: он вычел бы из-под храповика ровно те
    два скрипта, которые надо было подключить, — то есть узаконил бы «публикуем и не
    перепроверяем» на всём продуктовом семействе RISKWIRE и DFB.
    """

    def test_the_elder_sibling_has_real_callers(self):
        callers = []
        for rel in ("scripts/smoke.py", "scripts/drill_restore.py",
                    "scripts/refresh_published_proof.py"):
            src = (_ROOT / rel).read_text(encoding="utf-8")
            if "verify_spa.py" in src and "spec_from_file_location" in src:
                callers.append(rel)
        self.assertGreaterEqual(len(callers), 2, (
            "у verify_spa.py не осталось наших вызывающих — тогда гипотеза «третья "
            f"сторона» перестала быть опровергнутой и класс надо пересмотреть: {callers}"))

    def test_both_junior_verifiers_are_now_run_by_us(self):
        cmds = _cycle_commands()
        self.assertIn("scripts/verify_riskwire.py", cmds)
        self.assertIn("scripts/verify_dfb_pool.py", cmds)

    def test_they_are_verified_AFTER_the_cycle_publishes(self):
        """Порядок — часть смысла: сверяется свежеопубликованное, а не вчерашнее."""
        cmds = _cycle_commands()
        self.assertLess(cmds.index("cycle_runner"), cmds.index("scripts/verify_riskwire.py"))
        self.assertLess(cmds.index("cycle_runner"), cmds.index("scripts/verify_dfb_pool.py"))

    def test_the_verifiers_stay_zero_dependency(self):
        """Подключение не имеет права превратить их в наш код: `spa_core` они не импортируют.

        Весь смысл «проверь нас» в том, что скептик кладёт ОДИН файл на чистую машину.
        Импорт `spa_core` сюда — тихая потеря продукта.
        """
        for name in ("verify_riskwire.py", "verify_dfb_pool.py"):
            src = (_ROOT / "scripts" / name).read_text(encoding="utf-8")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        self.assertFalse(a.name.startswith("spa_core"), f"{name}: {a.name}")
                elif isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or "").startswith("spa_core"),
                                     f"{name}: {node.module}")

    def test_no_fourth_subtracted_class_was_introduced(self):
        """Храповик обязан вычитать РОВНО три класса — четвёртый мимо строки равенства.

        `test_unwired_scripts_ratchet::test_the_ratchet_watches_the_delivered_and_dead_set`
        сверяет «под храповиком = сырое минус вычитаемое» поимённо; здесь то же названо
        со стороны намерения этого разбора.
        """
        from spa_core.tests import _unwired
        src = (_ROOT / "spa_core" / "tests" / "_unwired.py").read_text(encoding="utf-8")
        subtracted = [n for n in ("registry_recorded_scripts", "protocol_commanded_scripts",
                                  "generated_artifact_scripts")
                      if f"- {n}(base)" in src]
        self.assertEqual(len(subtracted), 3, "набор вычитаемых классов изменился")
        self.assertNotIn("verifier", _unwired.unwired_scripts.__doc__ or "")


# ───────────────────────────────────────────────────────────────────────────────
# 6. build_dd_snapshot — ПОДКЛЮЧЁН: DD_PACK обещал снимок, которого не было
# ───────────────────────────────────────────────────────────────────────────────
class TestDdSnapshotIsRefreshedWithTheBundle(unittest.TestCase):
    """Публикованный DD_PACK велит funder'у собрать снимок — а собрать его было нечем.

    Шаг 7 пакета (`generate_dd_pack.py`) печатает в опубликованный документ команду
    `python3 scripts/build_dd_snapshot.py` → `data/dd_snapshot/` + SNAPSHOT_MANIFEST.json,
    и отдельную команду офлайн-реплея по этому манифесту. Вызывающего у сборщика не было
    ни одного, то есть обещание не исполнялось никогда — тот же класс, что «якорение,
    не работавшее 43 дня» (#248).

    Дом — `refresh_published_proof`, а НЕ дневной цикл, и это измеримое различие:
    манифест ПРИШПИЛИВАЕТ голову цепи решений (`expected_decision_head`), а часовой тик
    rates-desk эту голову двигает. Суточный снимок протух бы через час — ровно тот
    самозабитый гол, ради которого `refresh_published_proof` и написан для DD_PACK.
    """

    def test_the_published_pack_promises_the_snapshot(self):
        src = (_ROOT / "scripts" / "generate_dd_pack.py").read_text(encoding="utf-8")
        self.assertIn("build_dd_snapshot.py", src)
        self.assertIn("SNAPSHOT_MANIFEST.json", src)

    def test_the_refresher_builds_it(self):
        src = (_ROOT / "scripts" / "refresh_published_proof.py").read_text(encoding="utf-8")
        self.assertIn("build_dd_snapshot.py", src)
        self.assertIn("dd_snapshot", src)

    def test_the_source_root_is_an_input_not_a_constant(self):
        """Положительный контроль ПОЧИНКИ, а не украшение.

        До правки `build()` читала поверхности из модульной константы `ROOT`, а писала
        в переданный `out_dir`. Герметичный прогон рефрешера (`--data-dir <песочница>`,
        так гоняются его собственные тесты) заморозил бы ЖИВОЙ трек в песочный манифест:
        снимок утверждал бы, что пришпилил построенное тестом, а пришпилил бы продакшн.
        Тест ниже строит снимок из ЗАВЕДОМО пустого корня и требует, чтобы ни одна
        поверхность не подтянулась со стороны.
        """
        import tempfile
        spec = importlib.util.spec_from_file_location(
            "_bds_probe", str(_ROOT / "scripts" / "build_dd_snapshot.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as td:
            empty_root = Path(td) / "empty"
            (empty_root / "data" / "rates_desk").mkdir(parents=True)
            from_empty = mod.build(out_dir=Path(td) / "snap_empty", root=empty_root)

            # …и встречное плечо: подсунутый корень обязан быть ПРОЧИТАН, а не проигнорирован.
            seeded_root = Path(td) / "seeded"
            (seeded_root / "data" / "rates_desk").mkdir(parents=True)
            (seeded_root / "data" / "rates_desk" / "exit_nav.json").write_text(
                '{"rows": []}', encoding="utf-8")
            from_seeded = mod.build(out_dir=Path(td) / "snap_seeded", root=seeded_root)

        self.assertTrue(all(f.get("absent") for f in from_empty["files"]), (
            "снимок из пустого корня подтянул поверхности со стороны — значит корень "
            f"по-прежнему константа: {from_empty['files']}"))
        self.assertEqual(from_empty["expected_surfaces"], [])
        self.assertEqual(from_seeded["expected_surfaces"], ["B"], (
            "переданный корень не прочитан — поверхность B из него не попала в снимок: "
            f"{from_seeded['files']}"))

    def test_the_snapshot_is_built_after_the_self_verify(self):
        """Никогда не замораживаем непроверенную голову."""
        src = (_ROOT / "scripts" / "refresh_published_proof.py").read_text(encoding="utf-8")
        self.assertLess(src.index("post-refresh self-verify FAILED"),
                        src.index("build_dd_snapshot.py"))

    def test_a_hermetic_refresh_really_mints_a_snapshot_on_the_same_head(self):
        """Поведенческое плечо: не «в файле есть строка», а «прогон даёт снимок».

        Полный `refresh()` в песочнице с заведомо валидной цепью из одной строки:
        снимок обязан появиться, пришпилить ТУ ЖЕ голову, что рефрешер только что
        перепроверил, и сам воспроизвестись офлайн-верификатором. Живой `data/` при
        этом не читается и не пишется — весь прогон заперт под `data_dir`.
        """
        import hashlib
        import sys
        import tempfile

        spec = importlib.util.spec_from_file_location(
            "_rp_probe", str(_ROOT / "scripts" / "refresh_published_proof.py"))
        rp = importlib.util.module_from_spec(spec)
        if str(_ROOT) not in sys.path:
            sys.path.insert(0, str(_ROOT))
        spec.loader.exec_module(rp)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rd = root / "data" / "rates_desk"
            rd.mkdir(parents=True)
            gen0, payload = "0" * 64, {"kind": "ENTRY", "approved": True,
                                       "underlying": "susde", "as_of": "2026-06-28"}
            canon = json.dumps({"seq": 0, "ts": "t", "event_type": "rates_desk_decision",
                                "payload": payload, "prev_hash": gen0},
                               sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            head = hashlib.sha256(canon.encode()).hexdigest()
            (rd / "decision_log.jsonl").write_text(
                json.dumps({"seq": 0, "ts": "t", "entry_hash": head,
                            "prev_hash": gen0, **payload}) + "\n")
            (root / "docs").mkdir()

            summary = rp.refresh(data_dir=root / "data",
                                 dd_pack_path=root / "docs" / "DD_PACK.md")
            manifest_path = root / "data" / "dd_snapshot" / "SNAPSHOT_MANIFEST.json"
            self.assertTrue(manifest_path.exists(),
                            f"снимок не собрался: {summary['errors']}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertTrue(summary["dd_snapshot_ok"], summary["errors"])
        self.assertEqual(summary["dd_snapshot_head"], head)
        self.assertEqual(manifest["expected_decision_head"], summary["head"])
        self.assertTrue(manifest["verifier_ok"], manifest["verifier_errors"])
        self.assertFalse((_ROOT / "data" / "dd_snapshot").exists(),
                         "герметичный прогон дотянулся до живого data/dd_snapshot")


# ───────────────────────────────────────────────────────────────────────────────
# 7. find_defillama_sources — ОСТАВЛЕН КРАСНЫМ (решение владельца)
# ───────────────────────────────────────────────────────────────────────────────
class TestFindDefillamaSourcesStaysRed(unittest.TestCase):
    """Седьмая сирота НЕ погашена — и это записанное решение, а не забытый хвост.

    Замер: инструмент ЖИВ по содержанию (30 юнит-тестов в `tests/`), но
    (1) вызывающего нет; (2) у его продукта `data/source_discovery.json` нет НИ ОДНОГО
    читателя в дереве; (3) единственный документированный потребитель,
    `spa_core/analytics/source_integration_helper.py`, сам без вызывающего и печатает
    ЧЕЛОВЕКУ пятишаговый чек-лист; (4) ту же ручку DeFiLlama `/pools` уже опрашивает
    живой, кэширующий, ежедневно исполняемый `spa_core/adapters/defillama_feed.py`.

    Подключить его «шагом цикла» значило бы завести артефакт БЕЗ ПОТРЕБИТЕЛЯ — ровно то,
    что ловит сторож соответствия ADR-066. Завести признак «ручной инструмент» флагом в
    коде запрещает сам детектор (модульный докстринг `_unwired.py`: «Опт-аут-флага здесь
    намеренно НЕТ: флаг научил бы сторожа отключать»). Остаётся выбор — расписание с
    настоящим читателем (это установка агента, то есть деплой) или списание тестируемого
    рабочего инструмента. И то и другое — владельца (CLAUDE.md, стоп-правило).

    Дописать его в базу, чтобы храповик позеленел, запрещает сама база.
    """

    def test_it_is_NOT_in_the_baseline(self):
        base = json.loads(
            (_ROOT / "spa_core" / "tests" / "unwired_scripts_baseline.json").read_text("utf-8"))
        self.assertNotIn("find_defillama_sources", base["scripts"], (
            "имя дописали в базу, чтобы погасить падение — это запрещено самой базой"))
        self.assertNotIn("find_defillama_sources", base["revealed_by_stricter_detector"])

    def test_the_owner_card_exists_and_follows_the_format(self):
        cards = list((_ROOT / "nimbalyst-local" / "tracker").glob("own-*istochnik*.md"))
        self.assertTrue(cards, "решение оставлено без карточки владельцу (CLAUDE.md §2.4)")
        body = cards[0].read_text(encoding="utf-8")
        for section in ("## Что случилось и почему это важно", "## Что от тебя нужно",
                        "## Как понять, что готово", "## Что будет после"):
            self.assertIn(section, body, f"карточка без секции «{section}»")
        self.assertIn("find_defillama_sources", body)

    def test_the_documented_command_now_at_least_STARTS(self):
        """Отдельно от вердикта: документированный запуск падал на импорте.

        `python3 scripts/find_defillama_sources.py` кладёт на `sys.path` каталог
        `scripts/`, а не корень репозитория, поэтому `from spa_core.utils.atomic import …`
        валился `ModuleNotFoundError` — то есть «ручной инструмент» нельзя было запустить
        руками ни разу. Тесты этого не видели: они импортируют модуль из корня.
        """
        import os
        import subprocess
        import sys
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        r = subprocess.run([sys.executable, "scripts/find_defillama_sources.py", "--help"],
                           cwd=str(_ROOT), env=env, capture_output=True, text=True, timeout=120)
        self.assertNotIn("ModuleNotFoundError", r.stderr, r.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
