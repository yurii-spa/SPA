"""Сторож ТРИНАДЦАТОЙ двери доставки (ADR-1112): растит ли пуш долг чтений кэша.

Каждая проба — положительный контроль: она воспроизводит состояние, на котором
дверь уже ошибалась или ошиблась бы молча (`.claude/rules/deployment.md`).

Главная из них — :meth:`ServerTipDecides.test_the_tip_is_asked_of_the_server`.
Первая редакция гейта спрашивала `origin/main` ПО ИМЕНИ (`rev-parse`,
`cat-file`, `archive`) и на первом же живом прогоне покраснела НА СЕБЕ: три
новых зова, читающих кэш, в двери, которая такие зовы и ловит. Поэтому вершина
спрашивается у СЕРВЕРА (`ls-remote`), а дальше читается НЕИЗМЕНЯЕМЫЙ sha, и у
этой сцены вердикт РАЗЛИЧАЕТСЯ: со стороны кэша она зелена, со стороны сервера —
красна.
"""

from __future__ import annotations

import ast
import json
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
_spec = ilu.spec_from_file_location("_p2g_for_ref_gate", REPO / "push_to_github.py")
P2G = ilu.module_from_spec(_spec)
_spec.loader.exec_module(P2G)

BASELINE_REL = "scripts/python_git_ref_provenance_baseline.json"

#: Зов, читающий ссылку БЕЗ доказанной свежести. Ровно та форма, которую
#: положительный контроль самого прибора (ADR-362) объявляет предметом.
UNGATED = ("import subprocess\n"
           "def look():\n"
           "    return subprocess.run(['git', 'show', 'origin/main:x'])\n")

#: Личность того же зова в терминах прибора — `файл::функция::подкоманда:ссылка`.
UNGATED_KEY = "новый.py::look::show:origin/main"

#: Безобидный модуль: `.py` в наборе есть, предмета он не несёт.
PLAIN = "def hello():\n    return 'привет'\n"


def _git(cwd, *args, check=True):
    r = subprocess.run(["git", "-C", str(cwd), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} → {r.returncode}: {r.stderr}")
    return r


def _baseline_doc(subject=(), unresolved=None):
    """База храповика в схеме, которую прибор ПРИНИМАЕТ.

    Схема берётся у прибора, а не перепечатывается: перепечатанная строка — это
    второе объявление оси личности рядом с первым.
    """
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import python_git_ref_provenance as P        # noqa: PLC0415
    return {"schema": P.BASELINE_SCHEMA,
            "subject": list(subject),
            "admitted_after_migration": {},
            "unresolved": dict(unresolved or {})}


class Scene:
    """Одноразовая пара «сервер + рабочая копия» для одного вопроса.

    Имя ветки задаётся ВХОДОМ (`git init -b main`): умолчание `init.defaultBranch`
    решает хост, и фикстура, назвавшая потом `origin/main`, зелена на Маке и
    красна на `ubuntu-latest` (`.claude/rules/deployment.md`, § GIT-ОКРУЖЕНИЕ).
    """

    def __init__(self, origin_files: dict, baseline_subject=()):
        self.tmp = Path(tempfile.mkdtemp(prefix="refprov_scene_"))
        self.server = self.tmp / "server"
        self.work = self.tmp / "work"
        self.server.mkdir()
        _git(self.server, "init", "--bare", "-b", "main", "-q")
        self.work.mkdir()
        _git(self.work, "init", "-b", "main", "-q")
        _git(self.work, "config", "user.email", "scene@example.invalid")
        _git(self.work, "config", "user.name", "scene")
        files = dict(origin_files)
        files[BASELINE_REL] = json.dumps(_baseline_doc(baseline_subject),
                                         ensure_ascii=False)
        for rel, text in files.items():
            p = self.work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
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

    def advance_server(self, rel: str, text: str):
        """Сдвинуть СЕРВЕР вперёд, оставив ссылку кэша на прежней вершине."""
        stale = _git(self.work, "rev-parse", "refs/remotes/origin/main").stdout.strip()
        self.place(rel, text)
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-qm", "сцена: сервер ушёл вперёд")
        _git(self.work, "push", "-q", "origin", "main")
        # Объект у клона ЕСТЬ (push его туда и положил), а remote-tracking
        # ссылка возвращается на прежнюю вершину: именно так «кэш отстал»
        # отличается от «объекта нет».
        _git(self.work, "update-ref", "refs/remotes/origin/main", stale)
        return stale

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class GateRefusesGrowth(unittest.TestCase):
    """Отказ — и его обратная половина на той же сцене."""

    def _scene(self, origin_files, baseline_subject=()):
        sc = Scene(origin_files, baseline_subject)
        self.addCleanup(sc.close)
        return sc

    def test_a_delivered_py_that_adds_an_ungated_read_is_refused(self):
        sc = self._scene({"mod_a.py": PLAIN})
        path = sc.place("новый.py", UNGATED)
        with self.assertRaises(P2G.DeliveryGrowsUngatedRefReads) as got:
            P2G.enforce_delivery_ref_provenance([path], runner_file=str(REPO / "push_to_github.py"))
        self.assertIn(UNGATED_KEY, str(got.exception))

    def test_the_same_call_already_on_origin_does_not_hold_the_delivery(self):
        """РАЗЛИЧАЮЩАЯ половина: тот же зов, но он уже на origin ⇒ долг не этой доставки.

        Без неё отказ был бы неотличим от «предмет непуст», и дверь запирала бы
        чужую починку из-за чужого долга — ровно то, от чего предупреждает
        ADR-1073.
        """
        sc = self._scene({"mod_a.py": PLAIN, "новый.py": UNGATED})
        path = sc.place("новый.py", UNGATED + "\n# правка, предмета не меняющая\n")
        verdicts = P2G.enforce_delivery_ref_provenance(
            [path], runner_file=str(REPO / "push_to_github.py"))
        self.assertEqual(["debt"], [v["state"] for v in verdicts])
        self.assertEqual(1, verdicts[0]["debt"])

    def test_a_key_declared_in_the_baseline_does_not_refuse(self):
        """Объявленный долг отказа не вызывает: храповик про него уже знает."""
        sc = self._scene({"mod_a.py": PLAIN}, baseline_subject=[UNGATED_KEY])
        path = sc.place("новый.py", UNGATED)
        verdicts = P2G.enforce_delivery_ref_provenance(
            [path], runner_file=str(REPO / "push_to_github.py"))
        self.assertNotIn("grown", [v["state"] for v in verdicts])

    def test_the_bypass_names_it_and_does_not_stop(self):
        sc = self._scene({"mod_a.py": PLAIN})
        path = sc.place("новый.py", UNGATED)
        verdicts = P2G.enforce_delivery_ref_provenance(
            [path], allow=True, runner_file=str(REPO / "push_to_github.py"))
        self.assertEqual(["grown"], [v["state"] for v in verdicts])
        self.assertIn("РАСТИТ", P2G.delivery_ref_provenance_summary())

    def test_the_shadow_is_taken_from_git_not_from_the_working_tree(self):
        """Незакоммиченный и НЕ доставляемый зов доставке не приписывается.

        Сторона «до» обязана стоять на git-основании: возьми её с диска — и
        рабочий мусор попал бы в обе стороны, а рост приписался бы не тому.
        Здесь зов лежит в рабочей копии третьим файлом, в наборе его нет.
        """
        sc = self._scene({"mod_a.py": PLAIN})
        sc.place("чужой.py", UNGATED)
        path = sc.place("mod_a.py", PLAIN + "\n# своя правка\n")
        verdicts = P2G.enforce_delivery_ref_provenance(
            [path], runner_file=str(REPO / "push_to_github.py"))
        self.assertNotIn("grown", [v["state"] for v in verdicts])


class ServerTipDecides(unittest.TestCase):
    """Вершина спрашивается у СЕРВЕРА, а не читается из кэша ссылки."""

    def test_the_tip_is_asked_of_the_server(self):
        sc = Scene({"mod_a.py": PLAIN, "новый.py": UNGATED})
        self.addCleanup(sc.close)
        # Сервер уходит вперёд КОММИТОМ, который зов УБИРАЕТ; ссылка кэша
        # остаётся на прежней вершине, где зов ещё есть.
        stale = sc.advance_server("новый.py", PLAIN)
        self.assertTrue(stale)
        path = sc.place("новый.py", UNGATED)
        # Со стороны КЭША роста нет (зов там был), со стороны СЕРВЕРА — есть.
        with self.assertRaises(P2G.DeliveryGrowsUngatedRefReads) as got:
            P2G.enforce_delivery_ref_provenance(
                [path], runner_file=str(REPO / "push_to_github.py"))
        self.assertIn(UNGATED_KEY, str(got.exception))

    def test_a_server_that_does_not_answer_is_unmeasured_not_cache(self):
        sc = Scene({"mod_a.py": PLAIN})
        self.addCleanup(sc.close)
        _git(sc.work, "remote", "set-url", "origin",
             str(sc.tmp / "нет-такого-репозитория"))
        path = sc.place("новый.py", UNGATED)
        verdicts = P2G.enforce_delivery_ref_provenance(
            [path], runner_file=str(REPO / "push_to_github.py"))
        self.assertEqual(["unmeasured"], [v["state"] for v in verdicts])
        # ПРИЧИНА внутри «НЕ ИЗМЕРЕНО» обязана быть ЗАМЕРОМ, а не любым текстом
        # со словом «НЕ ИЗМЕРЕНА» (ADR-1058). Без этой проверки мутация «код
        # возврата `ls-remote` путь НЕ прекращает» ВЫЖИВАЛА: отказ всё равно
        # случался — но от СЛЕДУЮЩЕЙ двери («сервер не назвал ветку»), а она
        # отвечает на ДРУГОЙ вопрос. Замер цикла #1258: M02 выжил, пока проба
        # смотрела на слово, а не на причину.
        self.assertIn("отказал (код", verdicts[0]["reason"])
        self.assertIn("НЕ ИЗМЕРЕНО", P2G.delivery_ref_provenance_summary())

    def test_a_server_that_answers_but_lacks_the_branch_names_its_own_cause(self):
        """Обратная половина: сервер ОТВЕТИЛ, а ветки у него нет — причина ДРУГАЯ.

        Пара нужна целиком: без неё «отказал (код …)» и «не назвал ветку»
        слиплись бы в один текст, и проба выше снова смотрела бы на слово.
        """
        sc = Scene({"mod_a.py": PLAIN})
        self.addCleanup(sc.close)
        sha, whence, why = P2G.origin_tip_sha(sc.work, "такой-ветки-нет")
        self.assertIsNone(sha)
        self.assertIn("не назвал", why)
        self.assertNotIn("отказал (код", why)

    def test_the_tip_probe_asks_the_return_code_not_the_output(self):
        """`cat-file -e` на успехе МОЛЧИТ: судить по выводу = «объекта нет» всегда."""
        sc = Scene({"mod_a.py": PLAIN})
        self.addCleanup(sc.close)
        sha, whence, why = P2G.origin_tip_sha(sc.work, "main")
        self.assertIsNone(why)
        self.assertEqual(40, len(sha or ""))
        self.assertIn("СЕРВЕРА", whence)


class ThirdOutcomeIsNamed(unittest.TestCase):
    """НЕ ИЗМЕРЕНО — значение с причиной, а не «чисто» и не молчание."""

    def test_a_missing_prober_is_unmeasured(self):
        sc = Scene({"mod_a.py": PLAIN})
        self.addCleanup(sc.close)
        path = sc.place("новый.py", UNGATED)
        lonely = sc.tmp / "без-прибора" / "push_to_github.py"
        lonely.parent.mkdir(parents=True, exist_ok=True)
        lonely.write_text("# не прибор\n", encoding="utf-8")
        verdicts = P2G.enforce_delivery_ref_provenance([path],
                                                       runner_file=str(lonely))
        self.assertEqual(["unmeasured"], [v["state"] for v in verdicts])
        self.assertIn("НЕ ИЗМЕРЕН", verdicts[0]["reason"])

    def test_a_prober_without_a_door_is_unmeasured_and_names_the_door(self):
        sc = Scene({"mod_a.py": PLAIN})
        self.addCleanup(sc.close)
        path = sc.place("новый.py", UNGATED)
        fake_root = sc.tmp / "полу-прибор"
        (fake_root / "scripts").mkdir(parents=True, exist_ok=True)
        (fake_root / "scripts" / "python_git_ref_provenance.py").write_text(
            "def main(argv=None):\n    return 0\n", encoding="utf-8")
        verdicts = P2G.enforce_delivery_ref_provenance(
            [path], runner_file=str(fake_root / "push_to_github.py"))
        self.assertEqual(["unmeasured"], [v["state"] for v in verdicts])
        self.assertIn("census", verdicts[0]["reason"])

    def test_a_set_without_python_is_not_judged(self):
        sc = Scene({"mod_a.py": PLAIN})
        self.addCleanup(sc.close)
        path = sc.place("заметка.md", "# просто текст\n")
        verdicts = P2G.enforce_delivery_ref_provenance(
            [path], runner_file=str(REPO / "push_to_github.py"))
        self.assertEqual([], verdicts)
        self.assertIn("в наборе нет", P2G.delivery_ref_provenance_summary())

    def test_not_called_is_distinct_from_nothing_to_judge(self):
        """Пустой перечень — ДВА разных исхода, и склеивать их нельзя."""
        P2G._REF_PROVENANCE_VERDICTS.clear()
        P2G._REF_PROVENANCE_GATE["called"] = False
        self.assertIn("не зван НИ РАЗУ", P2G.delivery_ref_provenance_summary())
        P2G._REF_PROVENANCE_GATE["called"] = True
        self.assertIn("в наборе нет", P2G.delivery_ref_provenance_summary())


class BaselineAfterDelivery(unittest.TestCase):
    """База берётся оттуда, где окажется ПОСЛЕ пуша, а не из дерева."""

    def test_a_baseline_riding_in_the_set_is_the_one_that_judges(self):
        sc = Scene({"mod_a.py": PLAIN})
        self.addCleanup(sc.close)
        path = sc.place("новый.py", UNGATED)
        base = sc.place(BASELINE_REL,
                        json.dumps(_baseline_doc([UNGATED_KEY]),
                                   ensure_ascii=False))
        verdicts = P2G.enforce_delivery_ref_provenance(
            [path, base], runner_file=str(REPO / "push_to_github.py"))
        self.assertNotIn("grown", [v["state"] for v in verdicts])
        self.assertIn("уезжает этим пушем", verdicts[0]["whence"])

    def test_a_baseline_only_in_the_tree_does_not_count(self):
        """Переморозить базу в дереве и не включить её в набор — не ответ.

        Обратная половина предыдущей пробы: те же байты базы, но в наборе их
        НЕТ ⇒ на origin уедет прежняя, и отказ обязан случиться. Без этой
        половины гейт зеленел бы ровно в том случае, ради которого написан.
        """
        sc = Scene({"mod_a.py": PLAIN})
        self.addCleanup(sc.close)
        path = sc.place("новый.py", UNGATED)
        sc.place(BASELINE_REL, json.dumps(_baseline_doc([UNGATED_KEY]),
                                          ensure_ascii=False))
        with self.assertRaises(P2G.DeliveryGrowsUngatedRefReads):
            P2G.enforce_delivery_ref_provenance(
                [path], runner_file=str(REPO / "push_to_github.py"))


class SingleDoorToTheBytes(unittest.TestCase):
    """К уезжающим байтам — та же ОДНА дверь, что у соседей (ADR-774)."""

    def test_the_shadow_is_filled_through_read_delivery_bytes(self):
        """Своё чтение с диска вернуло бы предмет ADR-774 на новом месте.

        Меряется AST, а не подстрокой: упоминание имени в докстринге зачлось бы
        за зов (урок цикла #1217).
        """
        src = (REPO / "push_to_github.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "enforce_delivery_ref_provenance")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("read_delivery_bytes", called)
        self.assertNotIn("open", called)


class UnmeasuredIsNotClean(unittest.TestCase):
    """«Прибор вердикта не вынес» — это НЕ «роста нет»."""

    def test_a_baseline_with_a_foreign_schema_is_unmeasured(self):
        """Чужая схема базы: прибор ВЕРНО отказывается судить.

        Если бы гейт читал этот отказ как пустой рост, «не измерено» уехало бы
        под видом «чисто» — тот самый fail-OPEN, который тише красного.
        """
        sc = Scene({"mod_a.py": PLAIN})
        self.addCleanup(sc.close)
        path = sc.place("новый.py", UNGATED)
        base = sc.place(BASELINE_REL,
                        json.dumps({"schema": "чужая/1", "subject": [],
                                    "admitted_after_migration": {},
                                    "unresolved": {}}, ensure_ascii=False))
        verdicts = P2G.enforce_delivery_ref_provenance(
            [path, base], runner_file=str(REPO / "push_to_github.py"))
        self.assertEqual(["unmeasured"], [v["state"] for v in verdicts])
        self.assertIn("храповика не вынес", verdicts[0]["reason"])


class BothDoorsCarryTheGate(unittest.TestCase):
    """Реализация ОДНА, дверей ДВЕ — и ни одного невывезенного имени."""

    BATCH = REPO / "push_to_github_batch.py"

    def test_the_batch_door_imports_the_single_implementation(self):
        src = self.BATCH.read_text(encoding="utf-8")
        self.assertIn("enforce_delivery_ref_provenance = "
                      "_root_push.enforce_delivery_ref_provenance", src)
        self.assertNotIn("def enforce_delivery_ref_provenance", src,
                         "у батча своя копия реализации — одна дверь отказывала "
                         "бы, вторая молча везла бы зов")

    def test_the_batch_door_calls_the_gate(self):
        tree = ast.parse(self.BATCH.read_text(encoding="utf-8"))
        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("enforce_delivery_ref_provenance", called)

    def test_every_handler_name_in_the_batch_door_resolves(self):
        """Урок цикла #1217: `except <Имя>`, которого в модуле НЕТ, даёт
        `NameError` вместо отказа — то есть ровно в миг находки код 1 вместо
        кода двери. Встроенные имена считаются разрешимыми: первая редакция
        этой мерки назвала `Exception` пропавшим, и дефект был У МЕРКИ.
        """
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
        import builtins
        missing = []
        for n in ast.walk(tree):
            if not isinstance(n, ast.ExceptHandler) or n.type is None:
                continue
            for name in ast.walk(n.type):
                if isinstance(name, ast.Name) and name.id not in bound \
                        and not hasattr(builtins, name.id):
                    missing.append(name.id)
        self.assertEqual([], sorted(set(missing)))

    def test_the_exit_code_is_its_own(self):
        """Код двери не совпадает ни с одним соседним: иначе читатель отказа
        не узнает, КТО отказал (урок ADR-897 про код 2)."""
        neighbours = {P2G.BYTES_DRIFT_EXIT, P2G.DELIVERY_TREE_EXIT,
                      P2G.NOT_PYTHON_EXIT, P2G.FAT_ADR_TITLE_EXIT,
                      P2G.CARDLESS_BOARD_EXIT, P2G.STALE_BOARD_STATUS_EXIT,
                      P2G.UNCENSUSED_MODULE_EXIT, P2G.MUTATION_WINDOW_EXIT}
        self.assertNotIn(P2G.UNGATED_REF_READ_EXIT, neighbours)


class TheGateHasNoSecondParser(unittest.TestCase):
    """Разбор — ЕДИНСТВЕННОЙ дверью прибора, своей копии правила нет."""

    def test_the_gate_calls_the_probers_own_main(self):
        src = (REPO / "push_to_github.py").read_text(encoding="utf-8")
        start = src.index("def _ratchet_verdict(")
        end = src.index("def enforce_delivery_ref_provenance(")
        body = src[start:end]
        self.assertIn("mod.main(", body)
        for forbidden in ("BASELINE_SCHEMA ==", "admitted_after_migration",
                          '"subject"'):
            self.assertNotIn(forbidden, body,
                             "правило принятия базы живёт у прибора; копия "
                             "здесь означала бы два правила рядом")


if __name__ == "__main__":
    unittest.main()
