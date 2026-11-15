#!/usr/bin/env python3
"""Батарея прибора оси причины (:mod:`spa_core.monitoring.edition_cause`, ADR-1023).

Каждый тест — положительный контроль ОДНОГО звена: он краснеет, если это звено
порвать, и ни один из них не проходит подстрокой (`.claude/rules/acceptance.md`
п. 3). Предмет батареи — вопрос «набор находок сдвинула РЕДАКЦИЯ производителя
или сдвинулись ДАННЫЕ», и отвечает на него ТОЛЬКО третий прогон: прежний код на
сегодняшних данных.

Сцена собирается целиком из своих байтов: одноразовый git-клон с ДВУМЯ
редакциями поддельного производителя, отдельное дерево-песочница и отдельный
каталог «напечатанных» артефактов. Прод-дерева и дерева доставки сцена не
касается ни разу — у прибора на оба стои́т безусловный отказ, и он здесь
проверяется.

FROZEN-DATE-OK: injected-clock — литеральной даты в файле нет ни одной. Все
моменты сцены ВЫЧИСЛЯЮТСЯ от :data:`EPOCH` (``fromtimestamp(0, utc)``) и
передаются ОБЕИМ сторонам сравнения: даты коммитов — через
``GIT_COMMITTER_DATE``/``GIT_AUTHOR_DATE``, момент производства — входом
``moments``. Обе стороны закреплены одним якорем, поэтому календарь хоста на
вердикт не влияет ничем.

Имя ветки одноразового клона ОБЪЯВЛЕНО (``git init -b``): умолчание
``init.defaultBranch`` у Apple Git и у git на ``ubuntu-latest`` РАЗНОЕ
(`.claude/rules/deployment.md` § «GIT-ОКРУЖЕНИЕ в тестах»), и фикстура, назвавшая
потом ``main``, была бы зелена здесь и красна в CI.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring import edition_cause as ec  # noqa: E402
from spa_core.monitoring import edition_remeasure as er  # noqa: E402

#: Якорь сцены. Литерала даты здесь нет: все моменты происходят ОТСЮДА.
EPOCH = dt.datetime.fromtimestamp(0, tz=dt.timezone.utc)
#: Прежняя редакция закоммичена ДО момента производства, сегодняшняя — ПОСЛЕ.
PRIOR_AT = EPOCH + dt.timedelta(days=100)
PRODUCED_AT = EPOCH + dt.timedelta(days=200)
TODAY_AT = EPOCH + dt.timedelta(days=300)

ARTIFACT = "fake_office_member.json"
PRODUCER_REL = "spa_core/monitoring/fake_office_producer.py"
BRANCH = "main"

#: Поддельный производитель. ``TAG`` — его РЕДАКЦИЯ, ``data/input.json`` — его
#: ДАННЫЕ, и набор находок зависит ровно от этих двух величин. Иначе сцена не
#: смогла бы развести оси, а прибор отвечал бы о чём-то третьем.
PRODUCER_SRC = '''#!/usr/bin/env python3
"""Поддельный производитель сцены: находки = РЕДАКЦИЯ x ДАННЫЕ."""
# редакция сцены: {note}
import argparse, json, os
TAG = {tag!r}
{extra}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    items = json.loads(open(os.path.join(a.data, "input.json")).read())
    mark = os.path.join(a.data, "ran.marker")
    if {contaminate} and os.path.exists(mark):
        items = items + ["contaminated"]
    open(mark, "w").write("x")
    doc = {{"generated_at": "x", "findings": [
        {{"severity": "CRITICAL", "message": "%s:%s" % (TAG, it)} for it in items]}}
    open(os.path.join(a.data, {artifact!r}), "w").write(json.dumps(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _producer(tag: str, *, note: str, extra: str = "",
              contaminate: bool = False) -> str:
    # Фигурные скобки генератора набора находок держим вне `.format`, иначе
    # шаблон съел бы их как подстановку.
    body = PRODUCER_SRC.replace(
        '{{"severity": "CRITICAL", "message": "%s:%s" % (TAG, it)} for it in items]}}',
        '{{"severity": "CRITICAL", "message": "%s:%s" % (TAG, it)}} for it in items]}}')
    return body.format(tag=tag, extra=extra, artifact=ARTIFACT, note=note,
                       contaminate=contaminate)


def _git(repo: Path, *args: str, at: dt.datetime | None = None) -> None:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "scene", "GIT_AUTHOR_EMAIL": "scene@local",
                "GIT_COMMITTER_NAME": "scene", "GIT_COMMITTER_EMAIL": "scene@local"})
    if at is not None:
        env["GIT_AUTHOR_DATE"] = at.isoformat()
        env["GIT_COMMITTER_DATE"] = at.isoformat()
    proc = subprocess.run(["git", "-C", str(repo), *args], env=env,
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError(
            f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: git {' '.join(args)} → "
            f"{proc.returncode}: {proc.stderr.strip()}")


class Scene:
    """Клон с двумя редакциями + песочница + каталог напечатанных артефактов."""

    def __init__(self, stack: tempfile.TemporaryDirectory,
                 *, prior_tag: str, today_tag: str,
                 printed_items: list[str], today_items: list[str],
                 helper: str = "none", contaminate: bool = False) -> None:
        # `helper`: "none" — производитель не импортирует помощников вовсе ·
        # "untouched" — импортирует, но помощник НЕ правился после производства ·
        # "changed" — помощник правлен ПОЗЖЕ производства. Третья сцена и есть
        # предмет границы вердикта, а ВТОРАЯ — её РАЗЛИЧАЮЩИЙ контроль: без неё
        # мутация «называть помощника без сверки срока» ВЫЖИВАЕТ, потому что без
        # импорта тело цикла не исполняется ни разу (урок G1011 п. 9а).
        assert helper in ("none", "untouched", "changed"), helper
        base = Path(stack.name)
        self.repo = base / "clone"
        self.sandbox = base / "sandbox"
        self.prod_data = base / "printed"
        (self.repo / PRODUCER_REL).parent.mkdir(parents=True)
        self.prod_data.mkdir()
        (self.sandbox / "data").mkdir(parents=True)

        extra = ""
        self.helper_rel = None
        if helper != "none":
            helper_rel = "spa_core/monitoring/fake_office_helper.py"
            (self.repo / helper_rel).write_text("VALUE = 1\n")
            (self.sandbox / helper_rel).parent.mkdir(parents=True, exist_ok=True)
            (self.sandbox / helper_rel).write_text("VALUE = 1\n")
            extra = "from spa_core.monitoring import fake_office_helper  # noqa: F401"
            self.helper_rel = helper_rel

        # Имя ветки ОБЪЯВЛЕНО: умолчание хоста разное (см. докстринг модуля).
        _git(self.repo, "init", "-b", BRANCH, ".")
        (self.repo / PRODUCER_REL).write_text(
            _producer(prior_tag, note="prior", extra=extra,
                      contaminate=contaminate))
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-m", "prior edition", at=PRIOR_AT)
        (self.repo / PRODUCER_REL).write_text(
            _producer(today_tag, note="today", extra=extra,
                      contaminate=contaminate))
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-m", "today edition", at=TODAY_AT)
        if helper == "changed":
            (self.repo / self.helper_rel).write_text("VALUE = 2\n")
            _git(self.repo, "add", "-A")
            _git(self.repo, "commit", "-m", "helper moved too", at=TODAY_AT)

        # Песочница несёт СЕГОДНЯШНЮЮ редакцию и СЕГОДНЯШНИЕ данные.
        (self.sandbox / PRODUCER_REL).parent.mkdir(parents=True, exist_ok=True)
        (self.sandbox / PRODUCER_REL).write_text(
            _producer(today_tag, note="today", extra=extra,
                      contaminate=contaminate))
        # `input.json` лежит В ОБОИХ каталогах: песочница в бою есть КЛОН
        # прод-каталога, и свежая копия данных перед прогоном берётся оттуда.
        (self.sandbox / "data" / "input.json").write_text(json.dumps(today_items))
        (self.prod_data / "input.json").write_text(json.dumps(today_items))
        # Напечатанный артефакт — вывод ПРЕЖНЕЙ редакции на ПРЕЖНИХ данных.
        (self.prod_data / ARTIFACT).write_text(json.dumps({
            "generated_at": PRODUCED_AT.isoformat(),
            "findings": [{"severity": "CRITICAL", "message": f"{prior_tag}:{it}"}
                         for it in printed_items]}))

    @property
    def entries(self) -> dict[str, er.Entry]:
        return {ARTIFACT: er.Entry(("{root}/" + PRODUCER_REL, "--data", "{data}"))}

    def cause(self, **kw):
        kw.setdefault("moments", {ARTIFACT: PRODUCED_AT})
        kw.setdefault("producers", {ARTIFACT: PRODUCER_REL})
        return ec.cause_one(ARTIFACT, prod_data=self.prod_data,
                            sandbox_root=self.sandbox, repo=self.repo,
                            entries=self.entries, ref=BRANCH, budget_s=90.0, **kw)


class SceneMixin(unittest.TestCase):
    def scene(self, **kw) -> Scene:
        stack = tempfile.TemporaryDirectory()
        self.addCleanup(stack.cleanup)
        return Scene(stack, **kw)


class AxisTest(SceneMixin):
    """Какую ось прибор называет — и почему её нельзя назвать без ТРЕТЬЕГО прогона."""

    def test_only_the_producer_moved_is_named_edition(self):
        """Данные те же, редакция другая ⇒ сдвиг произвела РЕДАКЦИЯ."""
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause()
        self.assertEqual(o.kind, ec.EDITION, o.reason)
        # Третий прогон СОСТОЯЛСЯ и дал РОВНО напечатанное — на этом и стои́т вывод.
        self.assertEqual((o.printed, o.today, o.prior_on_today), (1, 1, 1))
        self.assertIsNotNone(o.prior_commit)

    def test_only_the_data_moved_is_named_data(self):
        """Редакции неразличимы по выводу, данные другие ⇒ сдвиг произвели ДАННЫЕ."""
        s = self.scene(prior_tag="same", today_tag="same",
                       printed_items=["a"], today_items=["b", "c"])
        o = s.cause()
        self.assertEqual(o.kind, ec.DATA, o.reason)
        self.assertEqual((o.printed, o.today, o.prior_on_today), (1, 2, 2))

    def test_both_axes_moving_is_its_own_kind_not_a_guess(self):
        """Третий набор не равен НИ ОДНОМУ из двух ⇒ ОБЕ, а не выдуманная одна."""
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["b"])
        o = s.cause()
        self.assertEqual(o.kind, ec.BOTH, o.reason)
        self.assertNotIn(o.kind, (ec.EDITION, ec.DATA))

    def test_a_set_that_did_not_diverge_is_measured_zero_not_unmeasured(self):
        """Инв. #17: «расхождения нет» — отдельное значение, и третьего прогона не было."""
        s = self.scene(prior_tag="same", today_tag="same",
                       printed_items=["a"], today_items=["a"])
        o = s.cause()
        self.assertEqual(o.kind, ec.NO_DIVERGENCE, o.reason)
        self.assertNotEqual(o.kind, ec.UNMEASURED)
        self.assertIsNone(
            o.prior_on_today,
            "третьего прогона не было — напечатать его число значило бы выдать "
            "невыполненный замер за выполненный")


class UnmeasuredTest(SceneMixin):
    """Третий исход: каждая дорога к нему НАЗЫВАЕТ свою причину (инв. #17)."""

    def test_member_without_a_declared_sandbox_entry(self):
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = ec.cause_one("nobody_declared_me.json", prod_data=s.prod_data,
                         sandbox_root=s.sandbox, repo=s.repo,
                         moments={}, producers={}, entries=s.entries, ref=BRANCH)
        self.assertEqual(o.kind, ec.UNMEASURED)
        self.assertIn("НЕ ОБЪЯВЛЕНО", o.reason)

    def test_entry_that_refuses_passes_its_own_reason_through(self):
        """Член, чей перемер не ЧИТАЮЩИЙ, не получает выдуманной оси."""
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = ec.cause_one(ARTIFACT, prod_data=s.prod_data, sandbox_root=s.sandbox,
                         repo=s.repo, moments={ARTIFACT: PRODUCED_AT},
                         producers={ARTIFACT: PRODUCER_REL},
                         entries={ARTIFACT: er.Entry(refusal="внешнее действие")},
                         ref=BRANCH)
        self.assertEqual(o.kind, ec.UNMEASURED)
        self.assertEqual(o.reason, "внешнее действие")

    def test_unread_production_moment_leaves_the_prior_edition_without_a_border(self):
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause(moments={ARTIFACT: None})
        self.assertEqual(o.kind, ec.UNMEASURED)
        self.assertIn("момент производства", o.reason)

    def test_producer_not_declared_by_the_office(self):
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause(producers={})
        self.assertEqual(o.kind, ec.UNMEASURED)
        self.assertIn("НЕ ОБЪЯВЛЕН", o.reason)

    def test_no_commit_before_the_moment_is_not_the_same_as_unchanged(self):
        """Пустой ответ git — названная причина, а не молчаливое «редакция та же».

        Это главный fail-OPEN класса: подставь здесь сегодняшние байты, и ось
        «ДАННЫЕ» получило бы ВСЁ, у чего прежней редакции не нашлось.
        """
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause(moments={ARTIFACT: EPOCH + dt.timedelta(days=1)})
        self.assertEqual(o.kind, ec.UNMEASURED)
        self.assertIn("нет ни одного коммита", o.reason)

    def test_todays_remeasure_unmeasured_blocks_the_cause_question(self):
        """Сегодняшний набор не снят ⇒ причину расхождения мерить НЕЧЕМ."""
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        (s.sandbox / "data" / "input.json").unlink()  # производитель упадёт
        o = s.cause()
        self.assertEqual(o.kind, ec.UNMEASURED)
        self.assertIn("перемер сегодняшней редакции НЕ ИЗМЕРЕН", o.reason)

    def test_producer_missing_from_the_sandbox_is_not_created(self):
        """Создать производителя в песочнице значило бы собрать небывшее дерево."""
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause(producers={ARTIFACT: "spa_core/monitoring/not_in_sandbox.py"})
        self.assertEqual(o.kind, ec.UNMEASURED)
        self.assertTrue(
            "нет файла производителя" in o.reason
            or "нет ни одного коммита" in o.reason, o.reason)


class SandboxSafetyTest(SceneMixin):
    """Прибор ПИШЕТ чужие байты в дерево — обе двери к беде закрыты безусловно."""

    def test_prod_tree_as_a_sandbox_is_refused(self):
        with self.assertRaises(er.Refused) as box:
            ec.run(prod_data=Path("/tmp"), sandbox_root=er.DEFAULT_LIVE_ROOT)
        self.assertIn("прод", str(box.exception).lower())

    def test_delivery_tree_as_a_sandbox_is_refused(self):
        """Прежняя редакция, забытая в дереве доставки, уехала бы на main как код."""
        with self.assertRaises(er.Refused) as box:
            ec.run(prod_data=Path("/tmp"), sandbox_root=_REPO_ROOT)
        self.assertIn("дерев", str(box.exception))

    def test_a_subtree_of_the_delivery_tree_is_refused_too(self):
        with self.assertRaises(er.Refused):
            ec.run(prod_data=Path("/tmp"),
                   sandbox_root=_REPO_ROOT / "spa_core" / "monitoring")

    def test_producer_bytes_return_to_the_sandbox_byte_for_byte(self):
        """Окно подмены закрывается, и закрытие СВЕРЯЕТСЯ, а не предполагается."""
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        before = (s.sandbox / PRODUCER_REL).read_bytes()
        o = s.cause()
        self.assertEqual(o.kind, ec.EDITION, o.reason)
        self.assertEqual((s.sandbox / PRODUCER_REL).read_bytes(), before,
                         "в песочнице осталась ПРЕЖНЯЯ редакция производителя — "
                         "следующий замер соврал бы на ней")

    def test_the_run_really_used_the_prior_bytes(self):
        """Контроль самой подмены: без неё третий набор равнялся бы сегодняшнему.

        Сцена различающая: напечатанное и сегодняшнее РАЗНЫЕ, а третий набор
        совпал с напечатанным — такое возможно только если прогон шёл прежними
        байтами. Подмену, которая не состоялась, этот тест называет `DATA`.
        """
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause()
        self.assertEqual(o.kind, ec.EDITION, o.reason)


class FreshDataTest(SceneMixin):
    """Данные прогона `C` — те же, что у `B`, а не те, что ОСТАЛИСЬ после `B`."""

    def test_a_stale_sandbox_lets_run_B_contaminate_run_C(self):
        """Положительный контроль НАСТОЯЩЕЙ находки #1161.

        Два прогона одного прибора по одному перечню на одном снимке данных
        разошлись у `asset_registry_gap_price` (`both` против `data`) при
        НЕПОДВИЖНОМ проде (md5 8 из 8). Данные подменил сам прибор: производитель
        пишет свой артефакт В ПЕСОЧНИЦУ, и прогон `B` становится входом прогону
        `C`. Сцена воспроизводит это буквально — и показывает, что свежая копия
        данных перед КАЖДЫМ прогоном меняет ВЕРДИКТ, а не только гигиену.
        """
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"], contaminate=True)
        dirty = s.cause(refresh=None)
        fresh = s.cause(refresh=lambda: ec.refresh_sandbox_data(s.prod_data, s.sandbox))
        self.assertEqual(fresh.kind, ec.EDITION, fresh.reason)
        self.assertEqual(dirty.kind, ec.BOTH, dirty.reason)
        self.assertNotEqual(
            dirty.kind, fresh.kind,
            "сцена перестала быть различающей: грязная песочница больше не "
            "меняет вердикт, и контроль свежих данных ничего не проверяет")

    def test_refresh_failure_is_unmeasured_with_a_reason(self):
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause(refresh=lambda: "каталог не читается")
        self.assertEqual(o.kind, ec.UNMEASURED)
        self.assertIn("свежие данные перед прогоном B", o.reason)

    def test_refresh_really_replaces_the_data_directory(self):
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        (s.sandbox / "data" / "ran.marker").write_text("x")
        self.assertIsNone(ec.refresh_sandbox_data(s.prod_data, s.sandbox))
        self.assertFalse((s.sandbox / "data" / "ran.marker").exists())
        self.assertTrue((s.sandbox / "data" / "input.json").is_file())

    def test_refresh_from_a_missing_directory_names_its_reason(self):
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        why = ec.refresh_sandbox_data(s.prod_data / "нет-такого", s.sandbox)
        self.assertIsNotNone(why)
        self.assertIn("не читается как каталог", why)


class NumericAxisTest(SceneMixin):
    """Расхождение «пришла/ушла находка» против «та же находка, другие числа».

    Ось нужна потому, что ключ находки (ADR-1022) берёт текст ЦЕЛИКОМ, а живые
    производители печатают в текст суммы: замер #1161 у `asset_registry_gap_price`
    нашёл ОДНУ И ТУ ЖЕ CRITICAL с разными долларами ($1,710,980.85 против
    $2,039,069.23). Без этой оси «набор разошёлся» читалось бы как «находка
    ушла», а не ушла НИ ОДНА.
    """

    def test_numbers_are_blinded_only_for_the_refinement(self):
        a = ("CRITICAL|поток $1,710,980.85 из 13 ключей",)
        b = ("CRITICAL|поток $2,039,069.23 из 13 ключей",)
        self.assertEqual(ec.numeric_blind(a), ec.numeric_blind(b))
        self.assertNotEqual(a, b, "ключ вердикта числа НЕ затирает")

    def test_a_different_finding_is_not_called_numeric_only(self):
        a = ("CRITICAL|ключ книги без актива",)
        b = ("CRITICAL|судья не отличает ноль от отсутствия",)
        self.assertNotEqual(ec.numeric_blind(a), ec.numeric_blind(b))

    def test_a_numeric_only_divergence_is_flagged_on_a_live_verdict(self):
        """Сквозной контроль: сцена, где РАЗНЫЕ только числа внутри текста."""
        s = self.scene(prior_tag="old", today_tag="old",
                       printed_items=["сумма 100"], today_items=["сумма 200"])
        o = s.cause()
        self.assertEqual(o.kind, ec.DATA, o.reason)
        self.assertTrue(o.numeric_only,
                        "ни одна находка не пришла и не ушла — сдвинулись суммы")

    def test_a_real_arrival_is_not_flagged_as_numeric_only(self):
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause()
        self.assertEqual(o.kind, ec.EDITION, o.reason)
        self.assertFalse(o.numeric_only)

    def test_the_refinement_is_printed_with_its_own_count(self):
        c = ec.Census(sandbox_root="/tmp/sb", repo="/tmp/clone", outcomes=[
            ec.Outcome(ec.BOTH, "a.json", producer="p.py", printed=5, today=5,
                       prior_on_today=5, prior_commit="deadbeefcafe",
                       prior_gone=("CRITICAL|x",), numeric_only=True,
                       elapsed_s=1.0)])
        lines = ec.report(c, max_rows=None)
        self.assertTrue(any("ТОЛЬКО В ЧИСЛАХ внутри текста находки (ни одна не "
                            "пришла и не ушла): 1" in s for s in lines), lines)
        self.assertTrue(any("расхождение ТОЛЬКО В ЧИСЛАХ текста" in s
                            for s in lines), lines)


class SandboxDoorTest(unittest.TestCase):
    """Дверь песочницы ADR-1000 на КАТАЛОГЕ ДАННЫХ — и она позвана ОТ ВХОДА.

    Соседний отказ `refuse_prod_root` сторожит песочницу (куда пишем). Эта дверь —
    про каталог, ОТКУДА читаем: под маркером песочницы прод-каталог здесь значит,
    что замер думает, будто мерит стенд, а мерит живой трек. Перепись
    `sandbox_data_dir_callers` поймала отсутствие двери у этого модуля красным —
    чинится ПРИЧИНА (дверь позвана), а не база переписи (инв. #16).
    """

    def test_the_marker_plus_a_prod_data_dir_refuses_with_code_2(self):
        from spa_core.utils import live_paths as lp
        os.environ[lp.SANDBOX_ENV] = "1"
        self.addCleanup(os.environ.pop, lp.SANDBOX_ENV, None)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as box:
                ec.main(["--data-dir", str(lp.DEFAULT_LIVE_ROOT / "data"),
                         "--sandbox-root", "/tmp/не-важно-дверь-раньше"])
        self.assertEqual(box.exception.code, 2)
        self.assertIn("edition_cause", err.getvalue())

    def test_the_door_is_called_from_the_entry_point_with_its_own_name(self):
        """Проводка, а не наличие: дверь, определённая но не позванная, — половина инъекции."""
        from spa_core.utils import live_paths as lp
        seen = []
        real = lp.refuse_if_sandbox_leaks
        lp.refuse_if_sandbox_leaks = lambda path, *, who, code=2: seen.append((str(path), who))
        self.addCleanup(setattr, lp, "refuse_if_sandbox_leaks", real)
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = ec.main(["--data-dir", tmp, "--sandbox-root", str(_REPO_ROOT),
                                "--quiet"])
        # Дверь позвана ДО отказа «песочница = дерево доставки», и отказ тоже случился.
        self.assertEqual(seen, [(tmp, "edition_cause")])
        self.assertEqual(code, 2)


class HelperBoundaryTest(SceneMixin):
    """Граница вердикта ОБЪЯВЛЕНА: помощник, правленный вместе с производителем."""

    def test_changed_helper_is_named_and_the_axis_is_marked_partial(self):
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"],
                       helper="changed")
        o = s.cause()
        self.assertEqual(o.kind, ec.EDITION, o.reason)
        self.assertIn(s.helper_rel, o.changed_helpers)
        self.assertTrue(o.partial,
                        "ось «редакция» снята на смеси, и печать обязана назвать "
                        "такого члена отдельно")

    def test_an_imported_helper_that_did_not_move_is_not_named(self):
        """РАЗЛИЧАЮЩИЙ контроль срока: помощник импортирован, но не правлен.

        Сцена без импорта вовсе этого звена не проверяет — в ней тело цикла по
        помощникам не исполняется ни разу, и мутация «называть помощника без
        сверки срока» в ней ВЫЖИВАЕТ (замер #1161, M6).
        """
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"],
                       helper="untouched")
        o = s.cause()
        self.assertEqual(o.kind, ec.EDITION, o.reason)
        self.assertNotEqual(
            ec.imported_helpers((s.sandbox / PRODUCER_REL).read_bytes(),
                                root=s.sandbox), (),
            "сцена перестала быть различающей: помощник больше не импортируется")
        self.assertEqual(o.changed_helpers, ())
        self.assertFalse(o.partial)

    def test_a_producer_without_helpers_names_none(self):
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause()
        self.assertEqual(o.changed_helpers, ())
        self.assertFalse(o.partial)

    def test_helpers_are_read_by_ast_not_by_grep(self):
        """`import` в строке или комментарии помощником не является."""
        src = (b'"""from spa_core.monitoring import artifact_edition"""\n'
               b'# import spa_core.monitoring.edition_remeasure\n'
               b'from spa_core.monitoring import edition_remeasure\n')
        got = ec.imported_helpers(src, root=_REPO_ROOT)
        self.assertIn("spa_core/monitoring/edition_remeasure.py", got)
        self.assertNotIn("spa_core/monitoring/artifact_edition.py", got)

    def test_unparsable_producer_yields_no_helper_claim(self):
        self.assertEqual(ec.imported_helpers(b"def (:\n", root=_REPO_ROOT), ())


class WiringTest(SceneMixin):
    """Инъекция таблицы входов доходит до ПРОВОДКИ, а не только до гейта."""

    def test_injected_entries_reach_todays_run_too(self):
        """Половина инъекции — та же бомба (`deployment.md` § ЛИЧНОСТЬ ПРОЦЕССА).

        Имени сцены в боевой таблице :data:`edition_remeasure.ENTRY` нет вовсе,
        поэтому любой исход, кроме «входа не объявлено», доказывает, что
        переданная таблица дошла и до перемера сегодняшней редакции.
        """
        self.assertNotIn(ARTIFACT, er.ENTRY,
                         "сцена перестала быть различающей: её имя попало в "
                         "боевую таблицу")
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause()
        self.assertEqual(o.kind, ec.EDITION, o.reason)

    def test_remeasure_one_still_defaults_to_the_live_table(self):
        """Боевой путь не меняется ни одним вызовом: умолчание — :data:`ENTRY`."""
        o = er.remeasure_one("nobody_declared_me.json", prod_data=Path("/tmp"),
                             sandbox_root=Path("/tmp"))
        self.assertEqual(o.kind, er.UNMEASURED)
        self.assertIn("НЕ ОБЪЯВЛЕНО", o.reason)

    def test_the_default_table_is_read_at_call_time_not_at_import(self):
        """Умолчание обязано читать ОБЪЯВЛЕННЫЙ дом таблицы, а не копию при импорте.

        Положительный контроль настоящей регрессии #1161: значение по умолчанию
        `entries = ENTRY` связывает ИМЕННО ТОТ словарь, что существовал в момент
        определения функции, и подмена `ENTRY` перестаёт доходить до проводки —
        десять проб соседней батареи ушли в красное молча, ничего не измерив.
        """
        name = "late_binding_scene.json"
        self.assertNotIn(name, er.ENTRY)
        er.ENTRY[name] = er.Entry(("-c", "pass"))
        self.addCleanup(er.ENTRY.pop, name, None)
        for who, outcome in (
                ("перемер", er.remeasure_one(name, prod_data=Path("/tmp"),
                                             sandbox_root=Path("/tmp"))),
                ("ось", ec.cause_one(name, prod_data=Path("/tmp"),
                                     sandbox_root=Path("/tmp"),
                                     repo=Path("/tmp"), moments={},
                                     producers={}))):
            self.assertNotIn(
                "песочного входа у этого члена НЕ ОБЪЯВЛЕНО", outcome.reason or "",
                f"{who}: умолчание прочитало копию таблицы, связанную при импорте")


class ReportTest(SceneMixin):
    """Печать: умолчанный остаток КАЖДОГО рода объявляется числом (ADR-1021)."""

    def _census(self, n: int) -> ec.Census:
        return ec.Census(sandbox_root="/tmp/sb", repo="/tmp/clone", outcomes=[
            ec.Outcome(ec.EDITION, f"a{i}.json", producer="p.py", printed=1,
                       today=1, prior_on_today=1, prior_commit="deadbeefcafe",
                       elapsed_s=0.1) for i in range(n)])

    def test_withheld_rows_are_counted_not_dropped(self):
        lines = ec.report(self._census(15), max_rows=3)
        self.assertTrue(any("ещё 12 в роде «РЕДАКЦИЯ»" in s for s in lines), lines)

    def test_all_rows_printed_when_no_limit(self):
        lines = ec.report(self._census(15), max_rows=None)
        self.assertFalse(any("ещё" in s for s in lines))
        self.assertEqual(sum(1 for s in lines if "[РЕДАКЦИЯ]" in s), 15)

    def test_unmeasured_census_prints_its_reason_and_nothing_else(self):
        lines = ec.report(ec.Census(reason="клон не выбран: усечён"))
        self.assertEqual(lines, ["ОСЬ ПРИЧИНЫ НЕ ИЗМЕРЕНА: клон не выбран: усечён"])

    def test_the_named_difference_is_printed_not_only_counted(self):
        """Размеры наборов могут СОВПАСТЬ при разном содержимом — только имена и
        отличают род ОБЕ от совпадения (`7 → 7 → 7` живого замера #1161)."""
        c = ec.Census(sandbox_root="/tmp/sb", repo="/tmp/clone", outcomes=[
            ec.Outcome(ec.BOTH, "a.json", producer="p.py", printed=7, today=7,
                       prior_on_today=7, prior_commit="deadbeefcafe",
                       prior_gone=("CRITICAL|ушла",),
                       prior_arrived=("INFO|пришла",), elapsed_s=1.0)])
        lines = ec.report(c, max_rows=None)
        self.assertTrue(any("(нет у прежней редакции) CRITICAL|ушла" in s
                            for s in lines), lines)
        self.assertTrue(any("есть ТОЛЬКО у прежней редакции) INFO|пришла" in s
                            for s in lines), lines)

    def test_the_withheld_part_of_the_named_difference_is_counted(self):
        c = ec.Census(sandbox_root="/tmp/sb", repo="/tmp/clone", outcomes=[
            ec.Outcome(ec.BOTH, "a.json", producer="p.py", printed=9, today=9,
                       prior_on_today=9, prior_commit="deadbeefcafe",
                       prior_gone=tuple(f"CRITICAL|{i}" for i in range(9)),
                       elapsed_s=1.0)])
        lines = ec.report(c, max_rows=2)
        self.assertTrue(any("ещё 7 в «нет у прежней редакции»" in s
                            for s in lines), lines)

    def test_the_printed_to_today_difference_is_named_too(self):
        """Ось без имён не говорит, КАКАЯ находка умерла — а это главный вопрос.

        Самая дорогая строка класса — CRITICAL об инварианте #3; «набор
        разошёлся» о её судьбе не говорит ничего. Лишнего прогона здесь нет:
        набор `B` уже снят дверью ADR-1022.
        """
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["a"])
        o = s.cause()
        self.assertEqual(o.today_gone, ("CRITICAL|old:a",))
        self.assertEqual(o.today_arrived, ("CRITICAL|new:a",))
        lines = ec.report(ec.Census(sandbox_root="x", repo="y", outcomes=[o]),
                          max_rows=None)
        self.assertTrue(any("УМЕРЛА у сегодняшней редакции) CRITICAL|old:a" in t
                            for t in lines), lines)
        self.assertTrue(any("РОДИЛАСЬ у сегодняшней редакции) CRITICAL|new:a" in t
                            for t in lines), lines)

    def test_a_named_difference_accompanies_a_live_both_verdict(self):
        """Сквозной контроль: род ОБЕ обязан прийти С ИМЕНАМИ, а не только числом."""
        s = self.scene(prior_tag="old", today_tag="new",
                       printed_items=["a"], today_items=["b"])
        o = s.cause()
        self.assertEqual(o.kind, ec.BOTH, o.reason)
        self.assertEqual(o.prior_gone, ("CRITICAL|old:a",))
        self.assertEqual(o.prior_arrived, ("CRITICAL|old:b",))

    def test_partial_members_are_counted_in_their_own_line(self):
        c = self._census(1)
        c.outcomes.append(ec.Outcome(ec.DATA, "b.json", producer="p.py",
                                     changed_helpers=("spa_core/x.py",)))
        lines = ec.report(c, max_rows=None)
        self.assertTrue(any("ось «редакция» НЕПОЛНА (правился и помощник): 1" in s
                            for s in lines), lines)
        self.assertTrue(any("помощники правлены: spa_core/x.py" in s
                            for s in lines), lines)


if __name__ == "__main__":
    unittest.main()
