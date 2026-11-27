"""Сторож ЧЕТЫРНАДЦАТОЙ двери доставки (ADR-1126): претензия о прогоне CI без своей личности.

Каждая проба — положительный контроль: она воспроизводит состояние, на котором
дверь ошиблась бы МОЛЧА (`.claude/rules/deployment.md`).

Главная из них — :meth:`IdentityIsTheClaimNotTheLine`. Личность претензии есть
САМ её сегмент, а не номер строки: вставь абзац выше — и дверь, опознающая
претензию по строке, объявила бы ростом сдвиг чужого текста, то есть отказывала
бы на ВЕРНОМ состоянии (урок ADR-1073). У этой сцены вердикт РАЗЛИЧАЕТСЯ: с
личностью-строкой она красна, с личностью-сегментом зелена.

Вторая несущая — :class:`DebtDoesNotHoldDelivery`. Предмет на `origin/main`
НЕПУСТ (журналы 5 из 429 замером 27.11), поэтому порог «безличных претензий быть
не должно» запер бы доставку ЧУЖОГО долга.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import tempfile
import unittest
import importlib.util as ilu
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Дверь доставки грузится ПО ПУТИ, а не импортом по имени: в дереве два файла
#: `push_to_github.py` (корень и тонкий шим в `scripts/`), и импорт по имени
#: отдал бы тот, чьё имя короче набрать, — знакомый класс (цикл #274).
_spec = ilu.spec_from_file_location("_p2g_for_ci_claim_gate",
                                    REPO / "push_to_github.py")
P2G = ilu.module_from_spec(_spec)
_spec.loader.exec_module(P2G)

RUNNER = str(REPO / "push_to_github.py")

#: Претензия БЕЗ личности прогона — ровно та форма, которую прибор ADR-1125
#: объявляет предметом (несёт ЧИСЛО упавших и не называет прогон).
BARE = "Контрольный прогон CI на `main`: RED, упавших 77."

#: Та же претензия с НАЗВАННЫМ прогоном (10…12 знаков) — обратная половина.
NAMED = "Контрольный прогон CI 45146707951 на `main`: RED, упавших 77."

#: Текст без претензии вовсе: носитель в наборе есть, предмета он не несёт.
PLAIN = "## цикл\n\nСделал доку, тесты зелёные.\n"

#: Та же претензия БЕЗ внутренних бэктиков. Нужна осям разметки, и это ДЕФЕКТ
#: СЦЕНЫ, найденный первым же прогоном батареи: в `BARE` стои́т `` `main` ``,
#: поэтому «обернуть претензию во вставку кода» её не оборачивает — бэктики
#: спариваются ВНУТРИ претензии, и ось цитаты честно отвечает «не цитата».
#: Сцена с таким текстом мерила бы разметку своего же литерала, а не дверь.
BARE_NB = "Контрольный прогон CI: RED, упавших 77."


def _git(cwd, *args, check=True):
    r = subprocess.run(["git", "-C", str(cwd), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} → {r.returncode}: {r.stderr}")
    return r


class Scene:
    """Одноразовая пара «сервер + рабочая копия» для одного вопроса.

    Имя ветки задаётся ВХОДОМ (`git init -b main`): умолчание
    `init.defaultBranch` решает хост, и фикстура, назвавшая потом
    `origin/main`, зелена на Маке и красна на `ubuntu-latest`
    (`.claude/rules/deployment.md`, § GIT-ОКРУЖЕНИЕ).
    """

    def __init__(self, origin_files: dict):
        self.tmp = Path(tempfile.mkdtemp(prefix="ciclaim_scene_"))
        self.server = self.tmp / "server"
        self.work = self.tmp / "work"
        self.server.mkdir()
        _git(self.server, "init", "--bare", "-b", "main", "-q")
        self.work.mkdir()
        _git(self.work, "init", "-b", "main", "-q")
        _git(self.work, "config", "user.email", "scene@example.invalid")
        _git(self.work, "config", "user.name", "scene")
        files = dict(origin_files) or {"README.md": "сцена\n"}
        for rel, text in files.items():
            self.place(rel, text)
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-qm", "сцена: основание")
        _git(self.work, "remote", "add", "origin", str(self.server))
        _git(self.work, "push", "-q", "origin", "main")

    def place(self, rel: str, text: str) -> str:
        """Положить байты в РАБОЧУЮ копию (не коммитя) и вернуть путь."""
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return str(p)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class _SceneCase(unittest.TestCase):
    def scene(self, origin_files=None):
        sc = Scene(origin_files or {})
        self.addCleanup(sc.close)
        return sc

    def gate(self, paths, **kw):
        kw.setdefault("runner_file", RUNNER)
        return P2G.enforce_delivery_ci_claim_identity(paths, **kw)

    def states(self, verdicts):
        return [v["state"] for v in verdicts]


class GateRefusesGrowth(_SceneCase):
    """Отказ — и его обратная половина на ТОЙ ЖЕ сцене.

    Без обратной половины мутация «отказывать всегда» пережила бы батарею
    молча: сцена-различитель и есть то, что отличает проверку от украшения
    (урок #1202/#1217).
    """

    def test_a_delivered_journal_that_adds_a_bare_claim_is_refused(self):
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place("docs/journal/2026-W48.md", PLAIN + "\n" + BARE + "\n")
        with self.assertRaises(P2G.DeliveryGrowsUnfalsifiableCiClaims) as cm:
            self.gate([path])
        self.assertIn("упавших 77", str(cm.exception))
        self.assertIn("ci_control_verdict", str(cm.exception),
                      "отказ обязан назвать, ГДЕ взять число и род")

    def test_the_same_claim_with_a_named_run_passes(self):
        """Обратная половина: личность прогона и есть то, что дверь спрашивает."""
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place("docs/journal/2026-W48.md", PLAIN + "\n" + NAMED + "\n")
        self.assertEqual(["clean"], self.states(self.gate([path])))

    def test_a_brand_new_carrier_file_with_a_bare_claim_is_refused(self):
        """Файла в вершине НЕТ: «претензий до — ноль» есть ЗАМЕР, а не его отсутствие."""
        sc = self.scene({"README.md": "сцена\n"})
        path = sc.place("docs/journal/2026-W48.md", BARE + "\n")
        with self.assertRaises(P2G.DeliveryGrowsUnfalsifiableCiClaims):
            self.gate([path])

    def test_a_tracker_card_is_a_carrier_too(self):
        """Носителей у прибора ДВА, и дверь судит оба — иначе класс уехал бы карточкой."""
        sc = self.scene({"nimbalyst-local/tracker/inbox-x.md": PLAIN})
        path = sc.place("nimbalyst-local/tracker/inbox-x.md",
                        PLAIN + "\n" + BARE + "\n")
        with self.assertRaises(P2G.DeliveryGrowsUnfalsifiableCiClaims):
            self.gate([path])

    def test_a_second_copy_of_a_known_claim_is_growth(self):
        """Множество с КРАТНОСТЬЮ: вторая такая же претензия — второй член класса.

        Считай дверь личности МНОЖЕСТВОМ без кратности — и повтор уехал бы
        бесплатно, а «одна безличная претензия» стала бы пропуском на любое их
        число.
        """
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN + "\n" + BARE + "\n"})
        path = sc.place("docs/journal/2026-W48.md",
                        PLAIN + "\n" + BARE + "\n\nи ещё раз:\n\n" + BARE + "\n")
        with self.assertRaises(P2G.DeliveryGrowsUnfalsifiableCiClaims) as cm:
            self.gate([path])
        self.assertIn("ДОБАВЛЯЕТ 1", str(cm.exception))


class IdentityIsTheClaimNotTheLine(_SceneCase):
    """Личность — САМ сегмент претензии, а не номер строки.

    Положительный контроль на дефект, которого дверь избежала по построению:
    личность-строка объявила бы ростом сдвиг чужого абзаца, то есть отказывала
    бы на ВЕРНОМ состоянии и запирала бы любую правку журнала выше претензии.
    """

    def test_shifting_an_existing_claim_down_is_not_growth(self):
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN + "\n" + BARE + "\n"})
        path = sc.place("docs/journal/2026-W48.md",
                        "## новый абзац ВЫШЕ\n\nтекст\n\n" + PLAIN + "\n"
                        + BARE + "\n")
        verdicts = self.gate([path])
        self.assertEqual(["debt"], self.states(verdicts))
        self.assertEqual(1, verdicts[0]["debt"])

    def test_reflowing_whitespace_inside_a_claim_is_not_growth(self):
        """Личность схлопнута по пробелам: перевод строки внутри претензии не
        делает её новой. Иначе переформатирование абзаца читалось бы как рост.
        """
        sc = self.scene({"docs/journal/2026-W48.md": BARE + "\n"})
        path = sc.place("docs/journal/2026-W48.md",
                        BARE.replace(": RED,", ":   RED,") + "\n")
        self.assertEqual(["debt"], self.states(self.gate([path])))


class DebtDoesNotHoldDelivery(_SceneCase):
    """Давний долг НАЗЫВАЕТСЯ и доставку НЕ держит.

    Это несущая половина мерки: порог «безличных претензий нет» краснел бы на
    ВЕРНОМ состоянии и запирал бы чужую починку (дословно урок ADR-1073).
    """

    def test_a_pre_existing_bare_claim_is_named_not_refused(self):
        sc = self.scene({"docs/journal/2026-W45.md": BARE + "\n"})
        path = sc.place("docs/journal/2026-W45.md", BARE + "\n\nдописал строку.\n")
        verdicts = self.gate([path])
        self.assertEqual(["debt"], self.states(verdicts))
        self.assertIn("давних претензий без прогона 1",
                      P2G.delivery_ci_claim_summary())

    def test_the_same_bytes_as_a_new_file_are_refused(self):
        """Сцена-РАЗЛИЧИТЕЛЬ к предыдущей: байты те же, вердикты
        ПРОТИВОПОЛОЖНЫЕ. Без неё мутация «всегда долг» выжила бы.
        """
        sc = self.scene({"README.md": "сцена\n"})
        path = sc.place("docs/journal/2026-W45.md", BARE + "\n\nдописал строку.\n")
        with self.assertRaises(P2G.DeliveryGrowsUnfalsifiableCiClaims):
            self.gate([path])


class QuotedClaimIsNotGrowth(_SceneCase):
    """Цитата чужой претензии ростом НЕ является (ось цитаты прибора)."""

    def test_a_claim_inside_a_fence_is_not_growth(self):
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place("docs/journal/2026-W48.md",
                        PLAIN + "\n```\n" + BARE + "\n```\n")
        self.assertEqual(["clean"], self.states(self.gate([path])))

    def test_a_claim_in_inline_code_is_not_growth(self):
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place("docs/journal/2026-W48.md",
                        PLAIN + "\nбыло напечатано `" + BARE_NB + "`\n")
        self.assertEqual(["clean"], self.states(self.gate([path])))


class SurfaceIsTheProbersCarrierSet(_SceneCase):
    """Поверхность объявляет ПРИБОР, а не литерал в пушере."""

    def test_a_non_carrier_file_short_circuits(self):
        sc = self.scene({"docs/STATE.md": PLAIN})
        path = sc.place("docs/STATE.md", PLAIN + "\n" + BARE + "\n")
        self.assertEqual([], self.gate([path]))
        self.assertIn("файлов носителей в наборе нет",
                      P2G.delivery_ci_claim_summary())

    def test_a_python_file_short_circuits(self):
        sc = self.scene({"mod.py": "x = 1\n"})
        path = sc.place("mod.py", "x = 1  # " + BARE + "\n")
        self.assertEqual([], self.gate([path]))

    def test_a_subdirectory_under_a_carrier_is_outside_the_surface(self):
        """Прибор перечисляет носителя `base.glob(mask)`, то есть НЕ рекурсивно.

        Это ЗАМЕР его охвата, а не описка: разойдись дверь с прибором — она
        судила бы файл, которого сторож не читает, и «что мерено» с «что
        охраняется» расползлись бы молча. `fnmatch` сам этого не различает:
        его `*` накрывает и `/`.
        """
        mod, why = P2G._ci_claim_prober(RUNNER)
        self.assertIsNone(why, why)
        self.assertEqual("journal",
                         P2G.ci_claim_carrier_of(mod, "docs/journal/w.md"))
        self.assertEqual("tracker",
                         P2G.ci_claim_carrier_of(mod,
                                                 "nimbalyst-local/tracker/i.md"))
        self.assertIsNone(P2G.ci_claim_carrier_of(
            mod, "nimbalyst-local/tracker/sub/deep.md"))
        self.assertIsNone(P2G.ci_claim_carrier_of(mod, "docs/journal/x.txt"))

    def test_the_door_names_no_carrier_path_of_its_own(self):
        """Литерал каталога носителя в двери = второе объявление населения.

        Меряется AST по строковым константам самой функции опознания: добавь
        прибор пятый носитель — и дверь обязана начать судить его САМА.
        """
        tree = ast.parse((REPO / "push_to_github.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "ci_claim_carrier_of")
        consts = [n.value for n in ast.walk(fn)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for bad in ("docs/journal", "nimbalyst-local/tracker", "*.md"):
            self.assertNotIn(bad, consts,
                             f"дверь объявила {bad!r} сама — перечень носителей "
                             f"обязан приходить из CARRIER_PATHS прибора")


class UnmeasuredIsNotClean(_SceneCase):
    """«Не измерено» не выдаётся ни за «чисто», ни за отказ (инв. #17)."""

    def test_a_prober_without_a_parsing_door_is_unmeasured(self):
        """Прибор без двери разбора: гейт обязан СКАЗАТЬ это, а не промолчать.

        Ни одна сцена не подавала прибор БЕЗ двери — ровно дыра покрытия,
        которую мутационный замер #1202 нашёл у соседней двери.
        """
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place("docs/journal/2026-W48.md", PLAIN + "\n" + BARE + "\n")
        shim = Path(tempfile.mkdtemp(prefix="ciclaim_shim_"))
        self.addCleanup(shim.rmtree if hasattr(shim, "rmtree")
                        else (lambda: shutil.rmtree(shim, ignore_errors=True)))
        target = shim / P2G.CI_CLAIM_PROBER_REL
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("CARRIER_PATHS = {}\n", encoding="utf-8")
        (shim / "push_to_github.py").write_text("", encoding="utf-8")
        verdicts = self.gate([path], runner_file=str(shim / "push_to_github.py"))
        self.assertEqual(["unmeasured"], self.states(verdicts))
        self.assertIn("не несёт двери", verdicts[0]["reason"])

    def test_a_missing_prober_is_unmeasured(self):
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place("docs/journal/2026-W48.md", PLAIN + "\n" + BARE + "\n")
        shim = Path(tempfile.mkdtemp(prefix="ciclaim_noprober_"))
        self.addCleanup(lambda: shutil.rmtree(shim, ignore_errors=True))
        (shim / "push_to_github.py").write_text("", encoding="utf-8")
        verdicts = self.gate([path], runner_file=str(shim / "push_to_github.py"))
        self.assertEqual(["unmeasured"], self.states(verdicts))
        self.assertIn("не ввезён", verdicts[0]["reason"])

    def test_an_unreachable_server_is_unmeasured_and_does_not_hold(self):
        """Вершину назвать нечем ⇒ третий исход с ПРИЧИНОЙ, а не молчание.

        Отказ здесь остановил бы доставку КОДА от сбоя сети, ничего не измерив;
        тишина сделала бы «не измерено» неотличимым от «сверено».
        """
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        _git(sc.work, "remote", "set-url", "origin",
             str(sc.tmp / "нет-такого-сервера"))
        path = sc.place("docs/journal/2026-W48.md", PLAIN + "\n" + BARE + "\n")
        verdicts = self.gate([path])
        self.assertEqual(["unmeasured"], self.states(verdicts))
        self.assertIn("вершина origin НЕ ИЗМЕРЕНА", verdicts[0]["reason"])
        self.assertIn("НЕ ИЗМЕРЕНО", P2G.delivery_ci_claim_summary())

    def test_undecided_quotation_growth_is_named_not_refused(self):
        """Ось цитаты НЕ ОТВЕТИЛА — это верхний край вилки, а не ноль и не отказ.

        Схлопни этот исход в «чисто» — и разметка стала бы дорогой мимо двери;
        сделай его отказом — дверь судила бы то, чего не измерила.
        """
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place("docs/journal/2026-W48.md",
                        PLAIN + "\nтут `незакрытый бэктик и " + BARE_NB + "\n")
        verdicts = self.gate([path])
        self.assertIn("grown_undecided", self.states(verdicts))
        self.assertNotIn("grown", self.states(verdicts))
        self.assertIn("ось цитаты молчит", P2G.delivery_ci_claim_summary())

    def test_undecided_axis_is_capable_of_firing_on_a_quiet_file(self):
        """Способность оси доказана ОТДЕЛЬНО: на тихом файле она молчит.

        Ось, отвечающая «не ответила» всегда, была бы тавтологией — её ноль
        стал бы свойством оси, а не файла (урок ADR-1125 о ложном нуле).
        """
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place("docs/journal/2026-W48.md", PLAIN + "\n" + NAMED + "\n")
        self.assertEqual(["clean"], self.states(self.gate([path])))


class ReasonIsPrintedNotOnlyReturned(_SceneCase):
    """«НЕ ИЗМЕРЕНО» обязано быть СКАЗАНО, а не только лежать в вердикте.

    Дыра покрытия, найденная мутационным замером: все сцены читали
    `verdicts[0]["reason"]`, и мутация, снявшая печать причины, выжила. Молчащее
    «не измерено» неотличимо от «сверено» для того, кто читает вывод пуша, —
    а читает его именно он (инв. #17).
    """

    def test_an_unmeasured_outcome_prints_its_reason(self):
        import contextlib
        import io

        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        _git(sc.work, "remote", "set-url", "origin",
             str(sc.tmp / "нет-такого-сервера"))
        path = sc.place("docs/journal/2026-W48.md", PLAIN + "\n" + BARE + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.gate([path])
        printed = out.getvalue()
        self.assertIn("НЕ ИЗМЕРЕНО", printed)
        self.assertIn("вершина origin НЕ ИЗМЕРЕНА", printed)

    def test_a_refusal_prints_the_claim_it_found(self):
        """Обратная половина: находка тоже обязана быть НАПЕЧАТАНА, а не только
        брошена исключением — вывод пуша и есть то, что читает человек.
        """
        import contextlib
        import io

        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place("docs/journal/2026-W48.md", PLAIN + "\n" + BARE + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(P2G.DeliveryGrowsUnfalsifiableCiClaims):
                self.gate([path])
        self.assertIn("РАСТИТ", out.getvalue())


class BytesThatDoNotDecodeAreUnmeasured(_SceneCase):
    """Нечитаемые байты — третий исход с ПРИЧИНОЙ, а не молчание.

    Дыра покрытия того же замера: ни одна сцена не подавала байты, которые не
    декодируются как UTF-8, и мутация, обнулившая причину, выжила.
    """

    def test_non_utf8_delivered_bytes_are_unmeasured_with_a_reason(self):
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        p = Path(sc.work) / "docs/journal/2026-W48.md"
        p.write_bytes(b"## \xff\xfe not utf-8 \xc0\xc1\n")
        verdicts = self.gate([str(p)])
        # «чисто» рядом с «не измерено» на ОДНОМ файле — дефект, который эта
        # сцена и нашла: без единого суждённого файла говорить «сверено»
        # нельзя (инв. #17).
        self.assertEqual(["unmeasured"], self.states(verdicts))
        self.assertIn("не декодируются", verdicts[0]["reason"])
        self.assertTrue(verdicts[0]["reason"].strip(),
                        "причина пуста — «не измерено» стало молчанием")


class ACauseWithoutANumberIsAlsoSubject(_SceneCase):
    """Претензия с РОДОМ падения и БЕЗ числа — тоже предмет.

    Найдено мутационным замером: мутант, бравший предмет своим литералом
    (`kind == "unfalsifiable" and count`), прошёл всю батарею, потому что ни
    одна сцена не несла претензии БЕЗ числа. Это и есть самый дорогой вид —
    непроверенный род без числа рядом выглядит скромнее, а перемерить его так
    же нечем.
    """

    def test_a_kind_only_claim_is_refused(self):
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place(
            "docs/journal/2026-W48.md",
            PLAIN + "\nКонтрольный прогон CI: RED, "
                    "худший — f-string SyntaxError ×3.\n")
        with self.assertRaises(P2G.DeliveryGrowsUnfalsifiableCiClaims):
            self.gate([path])

    def test_the_subject_set_comes_from_the_probers_finding_kinds(self):
        """Предмет берётся у ПРИБОРА (`doc["findings"]`), а не своим литералом.

        Меряется AST: строковая константа с именем рода внутри функции разбора
        есть второе объявление предмета рядом с первым.
        """
        tree = ast.parse((REPO / "push_to_github.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_ci_claims_of_text")
        consts = [n.value for n in ast.walk(fn)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertNotIn("unfalsifiable", consts,
                         "род предмета объявлен в двери — он обязан приходить "
                         "из FINDING_KINDS прибора")
        subs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        self.assertIn("QUOTATION_UNDECIDED", subs)


class BypassIsNamedAndPrinted(_SceneCase):
    """Осознанный обход существует, ПЕЧАТАЕТСЯ и находку не стирает."""

    def test_allow_lets_the_growth_through_and_keeps_the_verdict(self):
        sc = self.scene({"docs/journal/2026-W48.md": PLAIN})
        path = sc.place("docs/journal/2026-W48.md", PLAIN + "\n" + BARE + "\n")
        verdicts = self.gate([path], allow=True)
        self.assertEqual(["grown"], self.states(verdicts))
        self.assertIn("ДОБАВЛЯЕТ", P2G.delivery_ci_claim_summary())


class SingleDoorToTheBytes(unittest.TestCase):
    """К уезжающим байтам — та же ОДНА дверь, что у соседей (ADR-774)."""

    def test_the_delivered_side_is_read_through_read_delivery_bytes(self):
        """Своё чтение с диска вернуло бы предмет ADR-774 на новом месте.

        Меряется AST, а не подстрокой: упоминание имени в докстринге зачлось бы
        за зов (урок цикла #1217 — дефект был У МЕРКИ).
        """
        tree = ast.parse((REPO / "push_to_github.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "enforce_delivery_ci_claim_identity")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("read_delivery_bytes", called)
        self.assertNotIn("open", called)

    def test_the_before_side_comes_from_git_not_from_disk(self):
        """Сторона «до» берётся ИЗ GIT: рабочее дерево несёт незакоммиченное.

        Возьми её с диска — и «до» с «после» отличались бы не только моей
        доставкой, а рост приписался бы не тому (урок ADR-1112 п. 3).
        """
        src = (REPO / "push_to_github.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_tip_blob_text")
        text = ast.get_source_segment(src, fn) or ""
        self.assertIn("ls-tree", text)
        self.assertIn("cat-file", text)
        self.assertNotIn("read_text", text)
        self.assertNotIn("read_bytes", text)

    def test_the_tip_is_asked_of_the_server_and_fetch_is_forbidden(self):
        """Вершина спрашивается у СЕРВЕРА, и `fetch` в двери ЗАПРЕЩЁН.

        `fetch` сдвинул бы `refs/remotes/origin/main`, на которую в том же
        прогоне опираются соседние гейты: дверь, меняющая ответ соседям, хуже
        двери, молчащей о себе (ADR-1112 п. 4).
        """
        src = (REPO / "push_to_github.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "enforce_delivery_ci_claim_identity")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("origin_tip_sha", called)
        body = ast.get_source_segment(src, fn) or ""
        self.assertNotIn("fetch", body)
        self.assertNotIn("rev-parse", body)

    def test_the_missing_blob_is_told_apart_from_a_broken_git(self):
        """«Файла в вершине нет» и «git не ответил» — РАЗНЫЕ состояния.

        `ls-tree` на отсутствующем пути выходит НУЛЁМ и молчит, поэтому «пусто
        ⇒ файла нет» верно, а «пусто ⇒ git сломан» было бы подменой «не
        измерено» вердиктом — и ошибкой в сторону ОТКАЗА: сторона «до» стала бы
        пустой, и каждая претензия файла прочлась бы как рост.

        Сцена ЖИВАЯ, а не статическая. Первая редакция мерки спрашивала у AST
        «встречается ли `returncode` в функции» — и **мутация, снявшая само
        ветвление, ВЫЖИЛА**: имя осталось в тексте сообщения об отказе, и
        мерка зачла упоминание за проверку. Дословно урок цикла #1217, только
        вместо докстринга — f-строка. Поэтому вопрос задаётся настоящему
        каталогу, который git репозиторием не считает.
        """
        not_a_repo = Path(tempfile.mkdtemp(prefix="ciclaim_notrepo_"))
        self.addCleanup(lambda: shutil.rmtree(not_a_repo, ignore_errors=True))
        text, why = P2G._tip_blob_text(not_a_repo, "0" * 40,
                                       "docs/journal/2026-W48.md")
        self.assertIsNone(text, "сбой git выдан за «файла в вершине нет»")
        # «НЕ ИЗМЕРЕН» без хвоста: род у причины женский («сторона НЕ
        # ИЗМЕРЕНА»), и мерка, требующая среднего рода, краснела бы на ВЕРНОМ
        # сообщении.
        self.assertIn("НЕ ИЗМЕРЕН", why)
        self.assertIn("ls-tree", why)

    def test_a_path_absent_from_the_tip_is_a_measurement_not_a_failure(self):
        """Обратная половина той же пары: пути в вершине НЕТ — и это ЗАМЕР.

        Без неё мутация «любой ответ git считать сбоем» выжила бы: новый файл
        носителя перестал бы судиться вовсе.
        """
        sc = Scene({"README.md": "сцена\n"})
        self.addCleanup(sc.close)
        sha = _git(sc.work, "rev-parse", "HEAD").stdout.strip()
        text, why = P2G._tip_blob_text(sc.work, sha, "docs/journal/нет.md")
        self.assertEqual("", text)
        self.assertEqual("", why)


class BothDoorsCarryTheGate(unittest.TestCase):
    """Реализация ОДНА, дверей ДВЕ — и ни одного невывезенного имени."""

    BATCH = REPO / "push_to_github_batch.py"

    def test_the_batch_door_imports_the_single_implementation(self):
        src = self.BATCH.read_text(encoding="utf-8")
        self.assertIn("enforce_delivery_ci_claim_identity = "
                      "_root_push.enforce_delivery_ci_claim_identity", src)
        self.assertNotIn("def enforce_delivery_ci_claim_identity", src,
                         "у батча своя копия реализации — одна дверь "
                         "отказывала бы, вторая молча везла бы безличную "
                         "претензию")

    def test_both_clis_call_the_gate(self):
        for path in (REPO / "push_to_github.py", self.BATCH):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            called = {n.func.id for n in ast.walk(tree)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            self.assertIn("enforce_delivery_ci_claim_identity", called,
                          f"{path.name} гейт не зовёт")

    def test_every_handler_name_in_the_batch_door_resolves(self):
        """Урок цикла #1217: `except <Имя>`, которого в модуле НЕТ, даёт
        `NameError` вместо отказа — то есть ровно в миг находки код 1 вместо
        кода двери. Встроенные имена считаются разрешимыми: первая редакция
        этой мерки назвала `Exception` пропавшим, и дефект был У МЕРКИ.
        """
        import builtins

        src = self.BATCH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        bound = {t.id for n in ast.walk(tree)
                 if isinstance(n, ast.Assign)
                 for t in n.targets if isinstance(t, ast.Name)}
        bound |= {n.name for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for n in ast.walk(tree):
            if isinstance(n, ast.alias):
                bound.add((n.asname or n.name).split(".")[0])
        bound |= set(dir(builtins))
        missing = []
        for n in ast.walk(tree):
            if isinstance(n, ast.ExceptHandler) and isinstance(n.type, ast.Name):
                if n.type.id not in bound:
                    missing.append(n.type.id)
        self.assertEqual([], missing,
                         f"имена обработчиков не разрешаются: {missing}")

    def test_the_exit_code_is_its_own(self):
        """Код двери не совпадает ни с одним соседним: иначе «отказала эта
        дверь» было бы неотличимо от «отказала другая».
        """
        self.assertEqual(21, P2G.CI_CLAIM_IDENTITY_EXIT)
        others = {P2G.BYTES_DRIFT_EXIT, P2G.DELIVERY_TREE_EXIT,
                  P2G.NOT_PYTHON_EXIT, P2G.FAT_ADR_TITLE_EXIT,
                  P2G.CARDLESS_BOARD_EXIT, P2G.STALE_BOARD_STATUS_EXIT,
                  P2G.UNCENSUSED_MODULE_EXIT, P2G.UNGATED_REF_READ_EXIT,
                  P2G.ADR_INTERLOCK_EXIT, P2G.CHANGE_EVIDENCE_EXIT,
                  P2G.MUTATION_WINDOW_EXIT, P2G.PUBLICATION_GATE_EXIT}
        self.assertNotIn(P2G.CI_CLAIM_IDENTITY_EXIT, others)

    def test_both_clis_declare_the_bypass_flag(self):
        """Обход обязан СУЩЕСТВОВАТЬ в обоих CLI.

        Дыра покрытия того же замера: мутант, убравший флаг из argparse,
        прошёл батарею. Дверь без объявленного обхода становится
        неотключаемой, и первый же верный отказ научит обходить её правкой
        кода — то есть снятием, а не обходом.
        """
        for path in (REPO / "push_to_github.py", self.BATCH):
            src = path.read_text(encoding="utf-8")
            self.assertIn('"--allow-unfalsifiable-ci-claim"', src,
                          f"{path.name} не объявляет флаг обхода")
            self.assertIn("SPA_PUSH_ALLOW_UNFALSIFIABLE_CI_CLAIM", src,
                          f"{path.name} не читает переменную обхода")

    def test_the_summary_tells_never_called_from_nothing_to_judge(self):
        """Пустой перечень — НЕ один исход: «гейта не звали» и «носителей в
        наборе нет» разные состояния, и склеить их — тот же дефект, что
        склеить «не измерено» со «сверено».
        """
        P2G._CI_CLAIM_VERDICTS.clear()
        P2G._CI_CLAIM_GATE["called"] = False
        self.assertIn("не зван НИ РАЗУ", P2G.delivery_ci_claim_summary())
        P2G._CI_CLAIM_GATE["called"] = True
        self.assertIn("файлов носителей в наборе нет",
                      P2G.delivery_ci_claim_summary())


class ProducerStepIsDeclared(unittest.TestCase):
    """Починка — у ПРОИЗВОДИТЕЛЯ, и она объявлена в протоколе цикла.

    Дверь ловит уезд, а шаг протокола объясняет форму. Одна без другой —
    половина починки: прозой правило стояло три заказа подряд и не исполнялось,
    а дверь без формы не говорит, что писать вместо числа.
    """

    PROTO = REPO / "docs/ORCHESTRATOR_PROTOCOL.md"

    def test_the_journal_step_names_the_canonical_reader(self):
        src = self.PROTO.read_text(encoding="utf-8")
        self.assertIn("scripts/ci_control_verdict.py", src)
        self.assertIn("ci_claim_provenance", src)

    def test_the_journal_step_names_the_honest_form_without_a_run(self):
        src = self.PROTO.read_text(encoding="utf-8")
        self.assertIn("вердикт CI НЕ ИЗМЕРЕН", src)


if __name__ == "__main__":
    unittest.main()
