#!/usr/bin/env python3
"""Приёмка прибора «содержимое без ВТОРОЙ копии» (ADR-1123, заказ G1087 п. 4).

Каждая сцена — либо настоящая авария, либо порванное звено с НАЗВАННОЙ причиной.

**Имя ветки — ВХОД сцены** (`.claude/rules/deployment.md`, § GIT-ОКРУЖЕНИЕ): одноразовый
репозиторий рождается `git init -b <имя>`, и это же имя читают все ссылки сцены. Без
этого сцена зелена на Маке (`init.defaultBranch=main` из системного конфига) и красна на
`ubuntu-latest`, где по умолчанию `master`.

**Часы — ВХОД, а не окружение.** Бюджет судится инъектированным монотонным счётчиком
(`now=`), поэтому сцена бюджета не зависит ни от календаря, ни от скорости машины.
FROZEN-DATE-OK: литеральных дат в файле нет вовсе — предмет меры есть ДОСТИЖИМОСТЬ
объекта, а не свежесть.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import subprocess
import unittest

from spa_core.monitoring import stranded_content as sc

BRANCH = "scene-main"          # ВХОД сцены, не умолчание хоста


def _run(cwd, *args):
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise AssertionError(f"{' '.join(args)} rc={r.returncode}: {r.stderr[:300]}")
    return r.stdout


def _repo(tmp, name="repo"):
    """Одноразовый репозиторий с ОДНИМ коммитом и НАЗВАННОЙ ветвью."""
    root = os.path.join(tmp, name)
    os.makedirs(root)
    _run(root, "git", "init", "-b", BRANCH, "-q")
    _run(root, "git", "config", "user.email", "scene@example.invalid")
    _run(root, "git", "config", "user.name", "scene")
    os.makedirs(os.path.join(root, "spa_core"), exist_ok=True)
    with open(os.path.join(root, "spa_core", "base.py"), "w", encoding="utf-8") as fh:
        fh.write("БАЗА\n")
    _run(root, "git", "add", "-A")
    _run(root, "git", "commit", "-q", "-m", "база")
    return root


def _write(root, rel, text):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)
    return full


def _object_count(root):
    """Сколько объектов в складе. Мера «прибор только ЧИТАЕТ»."""
    out = _run(root, "git", "count-objects", "-v")
    got = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            got[k.strip()] = v.strip()
    return int(got.get("count", 0)), int(got.get("in-pack", 0))


def _named(doc):
    return {n["path"] for n in doc["names"]}


class KnownMember(unittest.TestCase):
    """Форма настоящей аварии: работа #1242 лежала ЗАКОММИЧЕННОЙ В ИНДЕКС, но не в
    коммите, и связка вышла бы кодом 0 без неё."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_staged_but_uncommitted_is_named(self):
        """ИЗВЕСТНЫЙ ЧЛЕН: `git add` без коммита. Объект в складе ЕСТЬ, от рефа
        НЕ достижим — мера на существовании объекта назвала бы его сохранённым."""
        _write(self.root, "spa_core/work.py", "работа цикла\n")
        _run(self.root, "git", "add", "spa_core/work.py")
        doc = sc.measure(self.root)
        self.assertEqual(doc["verdict"], sc.FOUND, doc)
        self.assertIn("spa_core/work.py", _named(doc))

    def test_the_staged_blob_really_exists_in_the_store(self):
        """Положительный контроль РАЗЛИЧИЯ двух мер: объект существует, и мера на
        `cat-file -e` ответила бы «сохранено». Без этой сцены предыдущая не
        доказывает, что ось выбрана верно."""
        _write(self.root, "spa_core/work.py", "работа цикла\n")
        _run(self.root, "git", "add", "spa_core/work.py")
        sha = _run(self.root, "git", "rev-parse", ":spa_core/work.py").strip()
        r = subprocess.run(["git", "cat-file", "-e", sha], cwd=self.root,
                           capture_output=True)
        self.assertEqual(r.returncode, 0, "объект обязан СУЩЕСТВОВАТЬ в складе")
        self.assertNotIn(sha, sc.reachable_objects(self.root),
                         "и при этом быть НЕ достижим ни от одного рефа")

    def test_committed_work_is_not_named(self):
        """Обратная половина: та же работа в коммите на локальной ветви — связка её
        сохранит, членом она быть не должна."""
        _write(self.root, "spa_core/work.py", "работа цикла\n")
        _run(self.root, "git", "add", "spa_core/work.py")
        _run(self.root, "git", "commit", "-q", "-m", "работа")
        doc = sc.measure(self.root)
        self.assertEqual(doc["verdict"], sc.EMPTY, doc)
        self.assertEqual(doc["names"], [])


class LossAxis(unittest.TestCase):
    """Вторая ось: потеря ПОЛНАЯ против «под риском только правка». Чинится разным."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_untracked_file_is_whole_loss(self):
        _write(self.root, "docs/NEVER_COMMITTED.md", "документ, которого нет в git\n")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_loss"].get(sc.WHOLE), 1, doc["by_loss"])
        self.assertIsNone(doc["by_loss"].get(sc.DELTA))

    def test_staged_new_file_is_whole_loss_not_delta(self):
        """Дефект, найденный ПРОБОЙ приёмки, а не вычиткой: `git add` нового файла
        даёт статус `A `, а не `??`. Пути в коммите НЕТ ⇒ потеря ПОЛНАЯ; первая
        редакция оси спрашивала ровно `xy == "??"` и отвечала `delta`."""
        _write(self.root, "spa_core/work.py", "работа мёртвой сессии\n")
        _run(self.root, "git", "add", "spa_core/work.py")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_loss"].get(sc.WHOLE), 1, doc["by_loss"])
        self.assertIsNone(doc["by_loss"].get(sc.DELTA), doc["by_loss"])

    def test_staged_modification_of_a_tracked_file_is_delta(self):
        """Обратная половина той же оси: `git add` ПРАВКИ отслеживаемого файла даёт
        `M `, путь в коммите ЕСТЬ ⇒ потеря не полна. Ось, назвавшая всё
        проиндексированное полной потерей, здесь краснеет."""
        _write(self.root, "spa_core/base.py", "БАЗА\nправка\n")
        _run(self.root, "git", "add", "spa_core/base.py")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_loss"].get(sc.DELTA), 1, doc["by_loss"])
        self.assertIsNone(doc["by_loss"].get(sc.WHOLE), doc["by_loss"])

    def test_modified_tracked_file_is_delta_loss(self):
        _write(self.root, "spa_core/base.py", "БАЗА\nправка\n")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_loss"].get(sc.DELTA), 1, doc["by_loss"])
        self.assertIsNone(doc["by_loss"].get(sc.WHOLE))

    def test_the_two_losses_are_counted_apart(self):
        """Сцена, РАЗЛИЧАЮЩАЯ оси: оба рода сразу. Прибор, сложивший их в один
        счётчик, здесь краснеет."""
        _write(self.root, "docs/NEW.md", "новое\n")
        _write(self.root, "spa_core/base.py", "БАЗА\nправка\n")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_loss"].get(sc.WHOLE), 1, doc["by_loss"])
        self.assertEqual(doc["by_loss"].get(sc.DELTA), 1, doc["by_loss"])


class SecondStoreIsOrigin(unittest.TestCase):
    """Складов ДВА. Содержимое, лежащее на origin, не потеряно даже без связки."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_content_reachable_from_origin_is_not_named(self):
        head = _run(self.root, "git", "rev-parse", "HEAD").strip()
        _run(self.root, "git", "update-ref", f"refs/remotes/origin/{BRANCH}", head)
        # ветвь снимается: единственный путь к байтам теперь через origin-реф
        _run(self.root, "git", "checkout", "-q", "--detach", head)
        _run(self.root, "git", "branch", "-q", "-D", BRANCH)
        doc = sc.measure(self.root)
        self.assertEqual(doc["verdict"], sc.EMPTY, doc)

    def test_refs_present_but_an_empty_object_walk_is_unmeasured(self):
        """Вторая половина fail-CLOSED, найденная МУТАЦИЕЙ M03: рефы ЕСТЬ, а обход
        объектов вернул пусто. Пустое множество достижимых сделало бы членом КАЖДЫЙ
        файл, то есть выдало бы сломанный прибор за находку обо всём дереве."""
        def empty_walk(cwd, *args, **kw):
            if args[:1] == ("rev-list",):
                return ""
            return sc._git(cwd, *args, **kw)
        doc = sc.measure(self.root, git=empty_walk)
        self.assertEqual(doc["verdict"], sc.UNMEASURED, doc)
        self.assertEqual(doc["names"], [])
        self.assertTrue(any("вернул пусто" in r for _, r in doc["unmeasured"]),
                        doc["unmeasured"])

    def test_no_refs_at_all_is_unmeasured_not_everything_found(self):
        """fail-CLOSED: пустое множество рефов сделало бы членом КАЖДЫЙ файл, то есть
        выдало бы сломанный вопрос за находку обо всём дереве."""
        def no_refs(cwd, *args, **kw):
            if args[:1] == ("for-each-ref",):
                return ""
            return sc._git(cwd, *args, **kw)
        doc = sc.measure(self.root, git=no_refs)
        self.assertEqual(doc["verdict"], sc.UNMEASURED, doc)
        self.assertEqual(doc["names"], [], "НЕ ИЗМЕРЕНО не вправе называть членов")
        self.assertTrue(any("ни одного рефа" in r for _, r in doc["unmeasured"]),
                        doc["unmeasured"])


class KindSubtraction(unittest.TestCase):
    """Вычитание рода ОБЯЗАНО быть измеренным: это уменьшение предмета."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_data_is_state_not_work(self):
        _write(self.root, "data/live.json", "{}\n")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_kind"].get(sc.STATE), 1, doc["by_kind"])
        self.assertEqual(doc["verdict"], sc.EMPTY, "состояние предметом НЕ является")

    def test_sqlite_sidecar_is_state(self):
        _write(self.root, "spa_core/database/spa.db-shm", "x\n")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_kind"].get(sc.STATE), 1, doc["by_kind"])

    def test_declared_produced_path_is_derived_not_work(self):
        _write(self.root, "architecture/manifest.json",
               '{"produces": ["docs/GENERATED.md"]}\n')
        _run(self.root, "git", "add", "-A")
        _run(self.root, "git", "commit", "-q", "-m", "конституция")
        _write(self.root, "docs/GENERATED.md", "произведено\n")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_kind"].get(sc.DERIVED), 1, doc["by_kind"])
        self.assertEqual(doc["verdict"], sc.EMPTY, doc)

    def test_undeclared_path_is_work_so_the_measure_errs_toward_the_finding(self):
        """Та же сцена без объявления: путь обязан остаться РАБОТОЙ. Иначе вычитание
        рода `derived` сняло бы работу молча."""
        _write(self.root, "docs/GENERATED.md", "произведено\n")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_kind"].get(sc.WORK), 1, doc["by_kind"])
        self.assertEqual(doc["verdict"], sc.FOUND, doc)

    def test_a_root_file_outside_every_prefix_is_work_not_derived(self):
        """Дыра покрытия, найденная МУТАЦИЕЙ M12: запасной путь `kind_of` (корневой файл
        вне всех объявленных каталогов) не достигала ни одна сцена — все клали файл под
        `docs/` или `spa_core/`. Именно здесь объявлено «ошибаться в сторону находки»,
        и без сцены это было обещанием, а не поведением."""
        _write(self.root, "СЛУЧАЙНЫЙ_КОРНЕВОЙ.txt", "работа без объявленного рода\n")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_kind"].get(sc.WORK), 1, doc["by_kind"])
        self.assertIsNone(doc["by_kind"].get(sc.DERIVED), doc["by_kind"])
        self.assertEqual(doc["verdict"], sc.FOUND, doc)

    def test_no_constitution_read_means_derived_is_not_subtracted(self):
        """Конституции нет ⇒ род `derived` не вычитается ВООБЩЕ, и причина НАЗВАНА."""
        _write(self.root, "docs/GENERATED.md", "произведено\n")
        doc = sc.measure(self.root)
        self.assertIsNotNone(doc["produced_reason"])
        self.assertEqual(doc["by_kind"].get(sc.DERIVED), None)

    def test_deletion_is_not_the_subject(self):
        _run(self.root, "git", "rm", "-q", "spa_core/base.py")
        doc = sc.measure(self.root)
        self.assertEqual(doc["by_kind"].get(sc.DELETION), 1, doc["by_kind"])
        self.assertEqual(doc["verdict"], sc.EMPTY, "удаление обратимо — не предмет")


class StateReserveIsAsked(unittest.TestCase):
    """«У состояния есть своя копия» обязано быть НАБЛЮДЕНИЕМ, а не предположением."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_missing_backups_dir_is_unmeasured(self):
        res = sc.state_reserve(self.root)
        self.assertEqual(res["verdict"], sc.UNMEASURED, res)
        self.assertIn("backups", res["reason"])

    def test_empty_backups_dir_is_a_measured_zero(self):
        os.makedirs(os.path.join(self.root, "data", "backups"))
        res = sc.state_reserve(self.root)
        self.assertEqual(res["verdict"], sc.EMPTY, res)

    def test_present_archive_is_found_with_an_age(self):
        d = os.path.join(self.root, "data", "backups")
        os.makedirs(d)
        open(os.path.join(d, "spa_state_2026-01-02.tar.gz"), "wb").close()
        res = sc.state_reserve(self.root)
        self.assertEqual(res["verdict"], sc.FOUND, res)
        self.assertIsNotNone(res["age_hours"])

    def test_the_report_says_the_subtraction_is_unjustified_when_no_archive(self):
        _write(self.root, "data/live.json", "{}\n")
        doc = sc.measure(self.root)
        text = "\n".join(sc.report(doc))
        self.assertIn("НЕ ОБОСНОВАНО", text)


class ThirdOutcome(unittest.TestCase):
    """Инв. #17: «не спросили» обязано отличаться от «спросили, и пусто»."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_clean_repo_is_a_measured_zero(self):
        doc = sc.measure(self.root)
        self.assertEqual(doc["verdict"], sc.EMPTY, doc)
        self.assertIn("ИЗМЕРЕННЫЙ ноль", "\n".join(sc.report(doc)))

    def test_unmeasured_report_prints_no_population_zero(self):
        """Отчёт под НЕ ИЗМЕРЕНО не вправе печатать ни «ПРЕДМЕТ ПУСТ», ни «НАЙДЕНО»."""
        doc = sc.measure(self.root, git=lambda *a, **k: (_ for _ in ()).throw(
            sc.NotMeasured("git молчит")))
        self.assertEqual(doc["verdict"], sc.UNMEASURED, doc)
        text = "\n".join(sc.report(doc))
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertNotIn("ПРЕДМЕТ ПУСТ", text)
        self.assertNotIn("НАЙДЕНО", text)

    def test_unreadable_tree_is_named_not_counted_as_clean(self):
        extra = os.path.join(self.tmp, "gone")
        real_wt = sc.worktrees

        def with_a_ghost(root, git=sc._git):
            alive, miss = real_wt(root, git=git)
            return alive, miss + [(extra, "каталога нет на диске")]
        sc.worktrees = with_a_ghost
        self.addCleanup(setattr, sc, "worktrees", real_wt)
        doc = sc.measure(self.root)
        self.assertTrue(any(p == extra for p, _ in doc["unmeasured"]), doc["unmeasured"])

    def test_budget_exhausted_is_unmeasured_not_a_partial_answer(self):
        """Часы — ВХОД. Бюджет исчерпан ⇒ НЕ ИЗМЕРЕНО с названной причиной, а не
        «успели столько, вот ответ»."""
        _write(self.root, "docs/NEW.md", "новое\n")
        _write(self.root, "docs/SECOND.md", "второе\n")
        # 0.0 — старт · 0.0 — проверка перед деревом · 0.0 — первая запись проходит ·
        # 10_000.0 — ВТОРАЯ запись уже за бюджетом. То есть бюджет бьёт ВНУТРИ дерева,
        # а не только между деревьями: с одним деревом прежняя редакция не била никогда.
        ticks = iter([0.0, 0.0, 0.0, 10_000.0, 10_001.0, 10_002.0])
        doc = sc.measure(self.root, budget_s=1.0, now=lambda: next(ticks))
        self.assertEqual(doc["verdict"], sc.UNMEASURED, doc)
        self.assertTrue(any("бюджет" in r for _, r in doc["unmeasured"]),
                        doc["unmeasured"])
        self.assertEqual(doc["names"], [], "частичный список НАСЕЛЕНИЕМ не зовётся")

    def test_the_partial_observation_is_kept_not_thrown_away(self):
        """Зеркальный дефект инв. #17 (ADR-1079): выбросить состоявшееся наблюдение и
        доложить о нём «не измерено». Имя, которое успели увидеть, обязано остаться —
        но в ОТДЕЛЬНОМ поле и названное ЧАСТИЧНЫМ."""
        _write(self.root, "docs/NEW.md", "новое\n")
        _write(self.root, "docs/SECOND.md", "второе\n")
        ticks = iter([0.0, 0.0, 0.0, 10_000.0, 10_001.0, 10_002.0])
        doc = sc.measure(self.root, budget_s=1.0, now=lambda: next(ticks))
        self.assertEqual(len(doc["names_partial"]), 1, doc)
        text = "\n".join(sc.report(doc))
        self.assertIn("это НЕ население", text)

    def test_exit_codes_are_three(self):
        self.assertEqual(sc.main(["--repo-root", self.root]), 0)
        _write(self.root, "docs/NEW.md", "новое\n")
        self.assertEqual(sc.main(["--repo-root", self.root]), 1)
        self.assertEqual(sc.main(["--repo-root", os.path.join(self.tmp, "нет")]), 2)


class ReadOnly(unittest.TestCase):
    """Прибор только ЧИТАЕТ — это ПРОВЕРЯЕТСЯ, а не обещается в докстринге."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_the_prober_does_not_write_to_the_object_store(self):
        _write(self.root, "docs/NEW.md", "новое\n")
        _write(self.root, "spa_core/base.py", "БАЗА\nправка\n")
        before = _object_count(self.root)
        doc = sc.measure(self.root)
        after = _object_count(self.root)
        self.assertEqual(doc["verdict"], sc.FOUND, doc)
        self.assertEqual(before, after,
                         f"склад объектов вырос {before} → {after}: `hash-object` "
                         f"позвали с `-w`")

    def test_hash_object_is_called_without_dash_w(self):
        """Прямая проверка формы зова: `-w` среди аргументов запрещено."""
        seen = []
        def spy(cwd, *args, **kw):
            seen.append(args)
            return sc._git(cwd, *args, **kw)
        _write(self.root, "docs/NEW.md", "новое\n")
        sc.measure(self.root, git=spy)
        calls = [a for a in seen if a[:1] == ("hash-object",)]
        self.assertTrue(calls, "зова `hash-object` не было вовсе")
        for a in calls:
            self.assertNotIn("-w", a, a)


class CyrillicPathIsMeasured(unittest.TestCase):
    """Первая редакция замера потеряла 9 ИМЁН: `git status` экранирует не-ASCII в
    восьмеричное, и `os.path.isfile` по такому пути файла не находит — ЧИТАЕМЫЙ файл
    уходил в «НЕ ИЗМЕРЕНО». Лечит `core.quotepath=false`, и это сцена про него."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_a_file_with_a_cyrillic_name_is_measured_not_unmeasured(self):
        _write(self.root, "docs/Без названия 1.md", "работа\n")
        doc = sc.measure(self.root)
        self.assertEqual(doc["verdict"], sc.FOUND, doc)
        self.assertIn("docs/Без названия 1.md", _named(doc))
        self.assertEqual(doc["unmeasured"], [], doc["unmeasured"])


if __name__ == "__main__":
    unittest.main()


class BudgetNotNamed(unittest.TestCase):
    """`budget_s=None` есть «бюджет не назван», а не отсутствие ответа.

    Нашла сцена приёмки ПРОБЫ: сравнение `float > None` ронял меру в `TypeError`, и
    проводка честно докладывала «НЕ ИЗМЕРЕНО» — то есть неназванный ВХОД становился
    отсутствующим ОТВЕТОМ."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_none_budget_falls_back_to_the_default(self):
        _write(self.root, "docs/NEW.md", "новое\n")
        doc = sc.measure(self.root, budget_s=None)
        self.assertEqual(doc["verdict"], sc.FOUND, doc)
        self.assertEqual(doc["budget_s"], sc.DEFAULT_BUDGET_S)


# ══════════════════════════════════════════════════════════════════════════════
# СЦЕНЫ, КОТОРЫХ ПОТРЕБОВАЛИ ВЫЖИВШИЕ МУТАНТЫ ЦИКЛА #1269 (G1096 п. 4)
#
# Свой набор из 34 мутаций на ТЕХ ЖЕ байтах дал 26 убито / 8 ВЫЖИЛО — при том что
# набор автора (#1256) объявлял 30 из 30. Дефектом КОДА не был ни один выживший: все
# восемь — дыры СЦЕН, и выжившую записывают, а не замазывают.
# ══════════════════════════════════════════════════════════════════════════════


class ReachabilityIsNotDifferenceFromHead(unittest.TestCase):
    """ЦЕНТРАЛЬНОЕ утверждение прибора, у которого НЕ БЫЛО НИ ОДНОЙ сцены.

    Решающая ось объявлена ДОСТИЖИМОСТЬЮ, а не отличием от HEAD, и причина названа
    замером: прод-дерево отстаёт от origin на сотню коммитов, поэтому почти всё
    «изменённое» в нём УЖЕ лежит на origin и потеряться не может.

    Мутация «разбор строки `rev-list --objects` снят» (членом становится КАЖДЫЙ файл)
    ВЫЖИЛА, и причина структурная: во ВСЕХ прежних сценах, где вердикт `empty`, дерево
    ЧИСТО — `git status` пуст, и ни у одного файла sha в множестве достижимых не
    спрашивался ни разу. То есть зелёной была проводка, а не ось.

    Различающая сцена: файл ОТЛИЧАЕТСЯ от своей версии в HEAD (status ` M`), а его
    байты лежат в коммите ПО ДРУГОМУ пути. Отличие от HEAD сказало бы «член»,
    достижимость говорит «вторая копия есть» — и ответы РАСХОДЯТСЯ."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)
        _write(self.root, "spa_core/alpha.py", "АЛЬФА\n")
        _write(self.root, "spa_core/beta.py", "БЕТА\n")
        _run(self.root, "git", "add", "-A")
        _run(self.root, "git", "commit", "-q", "-m", "две версии")

    def test_a_modified_file_whose_bytes_live_in_another_commit_is_not_named(self):
        # alpha получает БАЙТЫ beta: от HEAD:alpha отличается, но объект достижим.
        _write(self.root, "spa_core/alpha.py", "БЕТА\n")
        rows = {xy: rel for xy, rel in sc._status_rows(self.root)}
        self.assertIn("spa_core/alpha.py", rows.values(),
                      "предпосылка сцены НЕ ОБЕСПЕЧЕНА: git не считает файл изменённым")
        doc = sc.measure(self.root)
        self.assertEqual(doc["verdict"], sc.EMPTY, doc)
        self.assertNotIn("spa_core/alpha.py", _named(doc),
                         "ось подменена отличием от HEAD: байты достижимы от рефа")

    def test_the_same_file_with_genuinely_new_bytes_is_named(self):
        """Обратная половина — без неё сцена выше зелена у прибора, который не
        называет НИКОГО."""
        _write(self.root, "spa_core/alpha.py", "НОВОЕ, ЧЕГО НЕТ НИ В ОДНОМ КОММИТЕ\n")
        doc = sc.measure(self.root)
        self.assertEqual(doc["verdict"], sc.FOUND, doc)
        self.assertIn("spa_core/alpha.py", _named(doc))


class NonRegularFileIsAThirdOutcome(unittest.TestCase):
    """`git status` называет путь, а обычным файлом он не является.

    Мутация «не обычный файл пропускается МОЛЧА» ВЫЖИЛА: ни одна сцена такого пути не
    имела, а на живом замере он есть РОВНО ОДИН — и именно он держит строку «НЕ
    ПРОЧИТАНО 1 — это НЕ ноль». Молчаливый `continue` превратил бы её в «чисто».

    **Форма сцены выведена ЗАМЕРОМ, а не придумана.** Первая редакция клала в дерево
    FIFO — и предпосылка НЕ ОБЕСПЕЧИВАЛАСЬ: `git status -uall` именованный канал не
    называет ВОВСЕ, поэтому до вопроса `os.path.isfile` дело не доходило и сцена падала
    на своём же `assertTrue`. Живой член класса — СИМВОЛИЧЕСКАЯ ССЫЛКА НА КАТАЛОГ
    (`.claude/worktrees/rnd-edge-56/data/aggressive_lab` → `data/aggressive_lab`): её
    git называет (`??`), а `isfile` по ней идёт в каталог и отвечает «нет». Сцена
    воспроизводит РОВНО эту форму."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_a_symlink_to_a_directory_is_named_unmeasured_not_skipped(self):
        target = os.path.join(self.root, "docs")
        os.makedirs(target, exist_ok=True)
        _write(self.root, "docs/внутри.md", "чтобы каталог не был пуст\n")
        link = os.path.join(self.root, "ссылка_на_каталог")
        os.symlink(target, link)
        self.assertFalse(os.path.isfile(link),
                         "предпосылка сцены: по ссылке на каталог isfile отвечает «нет»")
        rows = [rel for _, rel in sc._status_rows(self.root)]
        self.assertIn("ссылка_на_каталог", rows,
                      "предпосылка НЕ ОБЕСПЕЧЕНА: git не назвал ссылку")
        doc = sc.measure(self.root)
        self.assertTrue(any(p.endswith("ссылка_на_каталог") and "не обычный файл" in r
                            for p, r in doc["unmeasured"]),
                        f"путь обязан быть НАЗВАН, а не пропущен: {doc['unmeasured']}")
        self.assertNotIn("ссылка_на_каталог", _named(doc),
                         "непрочитанное не вправе попадать в население")


class RenameIsJudgedByItsNewName(unittest.TestCase):
    """Мутация «переименование судит СТАРОЕ имя» ВЫЖИЛА — сцены с переименованием не
    было ни одной. Имя важно по делу: старого пути на диске НЕТ, и `os.path.isfile`
    по нему отправил бы живой файл в «НЕ ПРОЧИТАНО»."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)
        _write(self.root, "spa_core/old_name.py", "СОДЕРЖИМОЕ\n")
        _run(self.root, "git", "add", "-A")
        _run(self.root, "git", "commit", "-q", "-m", "до переименования")

    def test_the_new_path_is_named_and_the_old_one_is_not(self):
        _run(self.root, "git", "mv", "spa_core/old_name.py", "spa_core/new_name.py")
        # байты тоже меняются: иначе объект достижим и членом быть не должен
        _write(self.root, "spa_core/new_name.py", "СОДЕРЖИМОЕ И ПРАВКА\n")
        doc = sc.measure(self.root)
        named = _named(doc)
        self.assertIn("spa_core/new_name.py", named, doc["names"])
        self.assertNotIn("spa_core/old_name.py", named,
                         "судить СТАРОЕ имя значит спрашивать диск о пути, которого нет")


class TreeListIsAskedFailClosed(unittest.TestCase):
    """Две мутации ВЫЖИЛИ на одной двери, и обе — бездействующий фильтр:

    * «дерево, которого нет на диске, назначено ПРОЧИТАННЫМ» — ни одна сцена не имела
      исчезнувшего дерева, хотя РОВНО это наблюдалось в жизни: за сутки между замерами
      деревьев в реестре стало 179 → 120;
    * «`git worktree list` без деревьев = чистый ноль» — защитная ветвь fail-CLOSED, у
      которой не было РАЗЛИЧАЮЩЕЙ сцены: деревья есть во всех прочих."""

    def setUp(self):
        self.tmp = __import__("tempfile").mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.root = _repo(self.tmp)

    def test_a_tree_missing_from_disk_is_unmeasured_not_read(self):
        ghost = os.path.join(self.tmp, "ушедшее-дерево")
        self.assertFalse(os.path.isdir(ghost), "предпосылка: каталога быть не должно")

        def with_a_ghost(cwd, *args, **kw):
            out = sc._git(cwd, *args, **kw)
            if args[:2] == ("worktree", "list"):
                out += f"worktree {ghost}\n"
            return out

        doc = sc.measure(self.root, git=with_a_ghost)
        self.assertEqual(doc["trees_declared"], doc["trees_read"] + 1, doc)
        self.assertTrue(any(p == ghost and "каталога нет на диске" in r
                            for p, r in doc["unmeasured"]), doc["unmeasured"])

    def test_no_worktrees_at_all_is_unmeasured_not_clean(self):
        def no_trees(cwd, *args, **kw):
            if args[:2] == ("worktree", "list"):
                return ""
            return sc._git(cwd, *args, **kw)

        doc = sc.measure(self.root, git=no_trees)
        self.assertEqual(doc["verdict"], sc.UNMEASURED, doc)
        self.assertEqual(doc["names"], [], "НЕ ИЗМЕРЕНО не вправе называть членов")
        self.assertTrue(any("не назвал ни одного дерева" in r
                            for _, r in doc["unmeasured"]), doc["unmeasured"])


class PrintedNumbersAreTheMeasuredOnes(unittest.TestCase):
    """ФОРМА, которую чужой набор пропускает чаще прочих: ПЕЧАТАЕМОЕ ЧИСЛО БЕЗ СЦЕНЫ.

    Три мутации ВЫЖИЛИ, подменив нулём ровно те числа, которые читает человек:
    достижимых объектов · объявленных производимых путей · «и ещё N дерев(о/а)».
    Отчёт — чистая функция от документа, поэтому сцена подаёт документ с ИЗВЕСТНЫМИ
    числами и требует их в тексте; и требует ОТСУТСТВИЯ подменного нуля, иначе
    утверждение прошло бы подстрокой (ADR-333)."""

    @staticmethod
    def _doc(trees, reachable, produced):
        names = [{"tree": f"/t/{i}", "path": f"docs/f{i}.md", "xy": "??",
                  "kind": sc.WORK, "loss": sc.WHOLE, "bytes": 10 + i, "sha": f"{i:040d}"}
                 for i in range(trees)]
        return {"root": "/t", "trees_declared": trees, "trees_read": trees,
                "rows_total": trees, "by_kind": {sc.WORK: trees},
                "by_loss": {sc.WHOLE: trees}, "names": names, "names_partial": [],
                "unmeasured": [], "produced_declared": produced,
                "produced_reason": None, "verdict": sc.FOUND, "budget_s": 1.0,
                "elapsed_s": 0.1, "reachable_objects": reachable,
                "state_reserve": {"verdict": sc.FOUND, "reason": None,
                                  "newest": "/t/data/backups/spa_state_x.tar.gz",
                                  "age_hours": 1.0}}

    def test_the_reachable_object_count_printed_is_the_measured_one(self):
        text = "\n".join(sc.report(self._doc(2, 166595, 279)))
        self.assertIn("достижимых объектов 166595", text)
        self.assertNotIn("достижимых объектов 0", text)

    def test_the_declared_produced_count_printed_is_the_measured_one(self):
        text = "\n".join(sc.report(self._doc(2, 10, 279)))
        self.assertIn("производимых путей в конституции: 279", text)
        self.assertNotIn("производимых путей в конституции: 0", text)

    def test_the_remainder_of_trees_printed_is_the_measured_one(self):
        """Перечень деревьев обрезан десятью, и ОСТАТОК обязан быть числом замера:
        «и ещё 0» прочиталось бы как «других деревьев нет»."""
        text = "\n".join(sc.report(self._doc(13, 10, 279)))
        self.assertIn("… и ещё 3 дерев", text)
        self.assertNotIn("… и ещё 0 дерев", text)
