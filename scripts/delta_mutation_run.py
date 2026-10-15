#!/usr/bin/env python3
# LLM_FORBIDDEN
"""scripts/delta_mutation_run.py — ВВЕЗЁННЫЙ прибор мутационного замера ПО ДЕЛЬТЕ.

ЗАЧЕМ ОН ЕСТЬ (заказ G724 п. 3 / G725 п. 3, ADR-726)
====================================================
Каждый цикл, доставляя правку, мерит её мутациями и пишет в ADR строку вида
«применено N · убито M · выжило K». Прибор, которым это измерено, цикл до сегодня
писал ЗАНОВО и клал в `/tmp`, то есть выбрасывал вместе с деревом.

ЗАМЕР 2026-10-15 (цикл #870), три оси, каждая читается у ПОТРЕБИТЕЛЯ числа:

  * одноразовых приборов в `/tmp` на сегодня (циклы #830…#869, четверо суток) — **25**,
    суммарно **3790** строк; ввезено в репозиторий — **0**;
  * ADR, заявляющих «убито N» — **40**; из них называют ввезённый прибор **1**, адрес
    в `/tmp` — **1** (файла уже нет), не называют НИКАК — **38**;
  * открытых карточек, чья приёмка указывает на прибор в `/tmp` — **3**; адрес
    разрешается сегодня у **0** из них.

Вред не в неудобстве: число «убито 12» **не может перемерить никто**, то есть у главного
доказательства приёмки нет второго читателя — ровно то, против чего написано
`.claude/rules/acceptance.md` («стало лучше нечем поверить, если мерку выбирают после
работы»).

ЧЕМ ЭТОТ ПРИБОР ОТЛИЧАЕТСЯ ОТ `scripts/mutation_gate.py`
--------------------------------------------------------
Сосед — ГЕЙТ над постоянным, курированным набором мутаций на денежном пути: его
население объявлено в коде и не меняется от цикла к циклу. Этот прибор — про ДЕЛЬТУ
ОДНОГО цикла: население приходит СПЕЦИФИКАЦИЕЙ-файлом, которую цикл кладёт рядом со
своим ADR. Отсюда и разные ответы на «что считать нормой»: у гейта порог выживших 0 и
он краснит CI, здесь выжившие — НАХОДКА цикла, которую цикл обязан разобрать и назвать.
Два прибора, два вопроса; сливать их значило бы заставить дельту одного дня жить в
коде вечно.

ЧТО ЭТОТ ПРИБОР ИСПРАВЛЯЕТ В САМОЙ ОДНОРАЗОВОЙ ФОРМЕ (замер по населению 25)
----------------------------------------------------------------------------
1. **Третий исход доезжает до КОДА ВОЗВРАТА.** «Мутация не применена» (якорь не найден
   или найден не однажды) печаталась у 10 приборов из 25, но код возврата от неё не
   зависел НИ У ОДНОГО: все три ненулевых выхода населения привязаны к контролю шума.
   Прогон, где ни одна мутация ничего не порвала, выходил нулём и читался как «все
   убиты» — инв. #17 наизнанку. Здесь это код **3**.
2. **Инертность обеспечена, а не обещана.** Возврат живёт в `finally` (у 13 приборов из
   25 его не было вовсе, `atexit` — ни у одного), и ПОСЛЕ прогона прибор СВЕРЯЕТ
   побайтовый слепок каждого тронутого файла со снятым ДО. Не совпало ⇒ громкий отказ,
   а не тихий успех: мутант, оставшийся в дереве, уже случался
   (`inbox-ubityi-progon-perepisi-ostavlyaet-mutant`).
3. **«Сломал сборку» ≠ «убит».** Вердикт у населения брался по коду возврата pytest, а
   синтаксически неверный мутант даёт ненулевой код БЕЗ единого провалившегося
   утверждения — и попадал в «убито», хотя его не поймал никакой тест. Здесь это
   отдельный исход `broke_collection`.
4. **Вердикт — по РАЗНОСТИ НАБОРОВ ИМЁН упавших тестов** (урок цикла #810), а не по коду
   возврата: иначе чужое красное в батарее делает убитыми всех мутантов разом.

ЧЕТЫРЕ ИСХОДА МУТАЦИИ (перечень ЗАКРЫТ, сумма равна населению — инв. #17)
------------------------------------------------------------------------
  ``killed``            — появились НОВЫЕ упавшие имена (их перечень печатается);
  ``survived``          — набор упавших имён не изменился: дыра покрытия;
  ``not_applied``       — якоря нет либо он не единственный: мутация НЕ ИЗМЕРЕНА;
  ``broke_collection``  — прогон не собрался: ни одно утверждение не судило.

КОДЫ ВОЗВРАТА (старшинство: 2 > 3 > 1 > 0)
------------------------------------------
  0 — ИЗМЕРЕНО: выживших нет, не применённых нет;
  1 — ИЗМЕРЕНО: есть выжившие (находка цикла, разобрать и назвать);
  2 — НЕ ИЗМЕРЕНО целиком: спецификация не читается · контроль шума не собрался ·
      pytest не отвечает · дерево после прогона НЕ восстановлено;
  3 — НЕ ИЗМЕРЕНО частично: есть мутации, которые ничего не порвали либо сломали сборку.

КОНТРАКТ
--------
  * прибор только ПРИМЕНЯЕТ и ВОЗВРАЩАЕТ: своих мутаций у него нет, и он ничего не чинит;
  * мутировать можно только файл ВНУТРИ дерева и только НЕ под `data/` (там живёт трек);
    символическая ссылка отвергается ГРОМКО — запись сквозь неё уходит наружу копии
    (измеренный механизм карточки `inbox-ubityi-progon-perepisi-ostavlyaet-mutant`);
  * окружение прогона закреплено (`SPA_ENV=ci`, `PYTHONHASHSEED=0`, `-p no:randomly`):
    иначе один и тот же мутант убивается или выживает от порядка обхода множеств;
  * только stdlib.

CLI::

    python3 scripts/delta_mutation_run.py --spec docs/mutations/ADR-726-c870.json
    python3 scripts/delta_mutation_run.py --spec <файл> --json

Формат спецификации (JSON)::

    {
      "title":     "ADR-726 — дельта цикла #870",
      "tests":     ["spa_core/tests/test_delta_mutation_run.py"],
      "mutations": [
        {"name": "<что ровно рвётся>", "file": "<путь от корня дерева>",
         "old": "<якорь — ровно одно вхождение>", "new": "<подмена>"}
      ]
    }
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Iterable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Исходы мутации. Перечень ЗАКРЫТ: сумма исходов обязана равняться населению
#: спецификации, иначе исчезнувшая мутация читалась бы как «ничего не нашли».
KILLED = "killed"
SURVIVED = "survived"
NOT_APPLIED = "not_applied"
BROKE_COLLECTION = "broke_collection"
OUTCOMES = (KILLED, SURVIVED, NOT_APPLIED, BROKE_COLLECTION)

#: Коды возврата (старшинство 2 > 3 > 1 > 0) — см. шапку модуля.
RC_MEASURED_CLEAN = 0
RC_MEASURED_SURVIVORS = 1
RC_UNMEASURED = 2
RC_PARTIALLY_UNMEASURED = 3

#: Окружение прогона закреплено ЗДЕСЬ, одной копией: вторая копия в тесте разъехалась
#: бы молча, и «тот же мутант» мерился бы в другом окружении.
#: `PYTHONDONTWRITEBYTECODE` — не украшение, а находка положительного контроля на
#: НАСТОЯЩЕМ pytest (цикл #870): мутант `return 1` → `return 2` РАВЕН исходнику по
#: длине, и когда прогоны укладываются в одну секунду, `.pyc` остаётся годным по своей
#: же мерке (mtime в секундах + размер) — импорт берёт КЭШ, мутант «выживает», и это
#: читается как дыра покрытия, которой нет. Запрет записи закрывает нашу половину;
#: чужой уже лежащий `.pyc` снимается отдельно (`_invalidate_bytecode`).
PINNED_ENV = {"SPA_ENV": "ci", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
PYTEST_ARGS = ("-q", "--tb=no", "-rfE", "-p", "no:randomly")

#: Коды возврата pytest, при которых НИ ОДНО утверждение не судило.
#: 2 — прерван (ошибка сборки), 3 — внутренняя ошибка, 5 — не собрано ни одного теста.
_PYTEST_NOTHING_JUDGED = (2, 3, 5)
#: 4 — ошибка употребления: это дефект СПЕЦИФИКАЦИИ, а не свойство мутанта.
_PYTEST_USAGE_ERROR = 4

_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.M)


class SpecError(Exception):
    """Спецификация не читается либо просит запрещённого. Громкий отказ, не вердикт."""


class TreeNotRestored(Exception):
    """После прогона дерево не совпало побайтово со снимком ДО. Самое важное из всего."""


@dataclass(frozen=True)
class Mutation:
    """Одна мутация: имя, файл, якорь и подмена.

    `name` — не украшение: он печатается в вердикте и попадает в ADR, поэтому он обязан
    называть, ЧТО ровно рвётся, а не «мутация 7».
    """

    name: str
    file: str
    old: str
    new: str


@dataclass(frozen=True)
class Spec:
    title: str
    tests: tuple[str, ...]
    mutations: tuple[Mutation, ...]


@dataclass
class MutationResult:
    mutation: Mutation
    outcome: str
    detail: str = ""
    new_failures: tuple[str, ...] = ()


@dataclass
class Report:
    """Вердикт прогона. `rc` производный — считается ОДНОЙ функцией (`exit_code`)."""

    spec: Spec
    baseline_failures: tuple[str, ...]
    results: list[MutationResult] = field(default_factory=list)
    unmeasured_reason: str | None = None

    def by_outcome(self, outcome: str) -> list[MutationResult]:
        return [r for r in self.results if r.outcome == outcome]

    @property
    def applied(self) -> int:
        """Применено = убито + выжило. Не применённые НЕ входят: иначе знаменатель
        растёт от мутаций, которые ничего не измерили, и «убито 12 из 13» врёт."""
        return len(self.by_outcome(KILLED)) + len(self.by_outcome(SURVIVED))

    def exit_code(self) -> int:
        if self.unmeasured_reason is not None:
            return RC_UNMEASURED
        if self.by_outcome(NOT_APPLIED) or self.by_outcome(BROKE_COLLECTION):
            return RC_PARTIALLY_UNMEASURED
        if self.by_outcome(SURVIVED):
            return RC_MEASURED_SURVIVORS
        return RC_MEASURED_CLEAN

    def to_dict(self) -> dict:
        return {
            "title": self.spec.title,
            "tests": list(self.spec.tests),
            "baseline_failures": list(self.baseline_failures),
            "population": len(self.spec.mutations),
            "applied": self.applied,
            "counts": {o: len(self.by_outcome(o)) for o in OUTCOMES},
            "unmeasured_reason": self.unmeasured_reason,
            "rc": self.exit_code(),
            "results": [
                {
                    "name": r.mutation.name,
                    "file": r.mutation.file,
                    "outcome": r.outcome,
                    "detail": r.detail,
                    "new_failures": list(r.new_failures),
                }
                for r in self.results
            ],
        }


# ─────────────────────────── спецификация ───────────────────────────


def load_spec(path: str) -> Spec:
    """Прочитать спецификацию. Любая беда — `SpecError`, а не пустой набор мутаций.

    Пустой набор прошёл бы весь прибор и напечатал «выживших нет» — подделка
    доказательства того самого рода, что ADR-468 назвал «НЕ ИЗМЕРЕНО под видом CLEAN».
    """
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise SpecError(f"спецификации нет: {path}")
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"спецификация {path} не читается: {type(exc).__name__}: {exc}")
    if not isinstance(doc, dict):
        raise SpecError(f"спецификация {path} — не объект, а {type(doc).__name__}")
    tests = doc.get("tests")
    if not isinstance(tests, list) or not tests or not all(
        isinstance(t, str) and t.strip() for t in tests
    ):
        raise SpecError("`tests` обязан быть непустым списком строк — без батареи "
                        "мутанта судить нечем")
    raw = doc.get("mutations")
    if not isinstance(raw, list) or not raw:
        raise SpecError("`mutations` обязан быть непустым списком: пустое население дало "
                        "бы «выживших нет», ничего не измерив")
    mutations = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SpecError(f"mutations[{i}] — не объект, а {type(item).__name__}")
        missing = [k for k in ("name", "file", "old", "new")
                   if not isinstance(item.get(k), str) or not item.get(k)]
        if missing:
            raise SpecError(f"mutations[{i}] без обязательных полей: {', '.join(missing)}")
        if item["old"] == item["new"]:
            raise SpecError(f"mutations[{i}] ({item['name']!r}): якорь равен подмене — "
                            f"такая «мутация» не рвёт ничего и выжила бы по построению")
        mutations.append(Mutation(item["name"], item["file"], item["old"], item["new"]))
    title = doc.get("title")
    return Spec(title if isinstance(title, str) and title else os.path.basename(path),
                tuple(t.strip() for t in tests), tuple(mutations))


def resolve_target(rel_path: str, repo_root: str) -> str:
    """Проверить, что файл мутации вообще можно трогать. Отказ — ГРОМКИЙ.

    Три запрета, и каждый написан по измеренной аварии, а не из осторожности:

    * **выход за дерево** — мутировать чужое дерево прибор не вправе;
    * **символическая ссылка** — запись сквозь неё уходит в НАСТОЯЩИЙ файл за пределами
      копии, и `finally` убитого прогона его не вернёт
      (`inbox-ubityi-progon-perepisi-ostavlyaet-mutant`, механизм измерен);
    * **`data/`** — там живёт трек, и правило доставки запрещает его трогать вовсе
      (`.claude/rules/deployment.md` п. 4).
    """
    if os.path.isabs(rel_path):
        raise SpecError(f"путь мутации обязан быть ОТНОСИТЕЛЬНЫМ корня дерева: {rel_path}")
    root = os.path.realpath(repo_root)
    target = os.path.join(root, rel_path)
    if os.path.islink(target):
        raise SpecError(f"{rel_path} — символическая ссылка: запись сквозь неё уходит "
                        f"наружу дерева, и возврат её не вернёт")
    # Корень уже разрешён (`realpath` выше), поэтому один вопрос закрывает и «путь
    # вверх через ..», и «ссылка внутри пути». Второго условия об этом же здесь НЕТ
    # намеренно: два условия об одном маскируют друг друга, и снятие любого не ловится
    # ничем (находка цикла #869, ADR-725).
    real = os.path.realpath(target)
    if real != root and not real.startswith(root + os.sep):
        raise SpecError(f"{rel_path} разрешается наружу дерева ({real})")
    head = os.path.relpath(real, root).split(os.sep)[0]
    if head == "data":
        raise SpecError(f"{rel_path} лежит под data/ — там живёт трек, мутировать его "
                        f"запрещено (.claude/rules/deployment.md п. 4)")
    if not os.path.isfile(real):
        raise SpecError(f"файла мутации нет: {rel_path}")
    return real


# ─────────────────────────── прогон батареи ───────────────────────────


def _digest(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _invalidate_bytecode(path: str) -> None:
    """Снять `.pyc` рядом с файлом, который сейчас подменяется.

    Годность `.pyc` меряется mtime В СЕКУНДАХ и размером исходника. Мутант, равный
    исходнику по длине (а флип цифры или оператора именно таков), внутри одной секунды
    проходит эту мерку — и импорт берёт КЭШ вместо подменённого файла. Вердикт тогда
    выходит МЯГЧЕ правды («выжил»), то есть прибор печатает дыру покрытия, которой нет.
    """
    base = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    cache = os.path.join(base, "__pycache__")
    if not os.path.isdir(cache):
        return
    for name in os.listdir(cache):
        if name.startswith(stem + ".") and name.endswith(".pyc"):
            try:
                os.unlink(os.path.join(cache, name))
            except OSError:
                pass


def _write_atomically(path: str, text: str) -> None:
    """Писать через tmp в ТОЙ ЖЕ директории + `os.replace` (инв. #5).

    Не ради долговечности: ради того, чтобы параллельный читатель никогда не увидел
    ПОЛОВИНУ файла. Мутант он в это окно увидеть всё равно может — это цена метода,
    и она названа вслух, а не спрятана.
    """
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".delta_mut_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def parse_failures(stdout: str) -> tuple[str, ...]:
    """Имена упавших/ошибочных тестов из короткой сводки pytest (`-rfE`).

    Имена, а не код возврата: чужое красное в батарее делает ненулевым КАЖДЫЙ прогон,
    и вердикт по коду объявил бы убитыми всех мутантов разом (урок цикла #810).
    """
    return tuple(sorted(set(_FAILED_LINE.findall(stdout or ""))))


def pytest_runner(tests: Iterable[str], *, repo_root: str) -> tuple[int, str]:
    """Прогон батареи. Возврат — (код pytest, stdout+stderr). Окружение закреплено."""
    cmd = [sys.executable, "-m", "pytest", *tests, *PYTEST_ARGS]
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True,
                          env={**os.environ, **PINNED_ENV})
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run(spec: Spec, *, repo_root: str | None = None,
        runner: Callable[..., tuple[int, str]] | None = None) -> Report:
    """Измерить дельту. Дерево после возврата обязано совпасть побайтово.

    `runner` — ВХОД, а не окружение: тест обязан уметь задать прогон, не поднимая
    настоящий pytest, иначе проверка самого прибора стоила бы минуты и жила бы на
    живых часах (`.claude/rules/deployment.md` § «ВРЕМЯ В ТЕСТАХ»).
    """
    root = os.path.realpath(repo_root or REPO_ROOT)
    do_run = runner or (lambda tests: pytest_runner(tests, repo_root=root))

    # Пути проверяются ДО первого прогона: отказ по спецификации не должен стоить
    # батареи, а главное — не должен случиться ПОСЛЕ того, как часть файлов тронута.
    targets = {m.file: resolve_target(m.file, root) for m in spec.mutations}
    before = {rel: _digest(real) for rel, real in targets.items()}
    originals = {rel: open(real, encoding="utf-8").read() for rel, real in targets.items()}

    rc, out = do_run(spec.tests)
    if rc == _PYTEST_USAGE_ERROR:
        return Report(spec, (), [], unmeasured_reason=(
            f"pytest отказал по употреблению (код {rc}): батарея {list(spec.tests)} "
            f"не прогоняется — измерять нечем"))
    if rc in _PYTEST_NOTHING_JUDGED:
        return Report(spec, (), [], unmeasured_reason=(
            f"КОНТРОЛЬ ШУМА не собрался (код pytest {rc}): ни одно утверждение не "
            f"судило ещё ДО мутаций — «выживших нет» здесь было бы подделкой"))
    baseline = parse_failures(out)
    report = Report(spec, baseline)

    try:
        for mut in spec.mutations:
            real = targets[mut.file]
            source = originals[mut.file]
            found = source.count(mut.old)
            if found != 1:
                report.results.append(MutationResult(
                    mut, NOT_APPLIED,
                    detail=(f"якорь встречается {found} раз(а), а не однажды — мутация "
                            f"НЕ ПРИМЕНЕНА и не измерила ничего")))
                continue
            try:
                _invalidate_bytecode(real)
                _write_atomically(real, source.replace(mut.old, mut.new))
                m_rc, m_out = do_run(spec.tests)
            finally:
                _write_atomically(real, source)
                _invalidate_bytecode(real)
            if m_rc == _PYTEST_USAGE_ERROR:
                report.results.append(MutationResult(
                    mut, BROKE_COLLECTION,
                    detail=f"pytest отказал по употреблению (код {m_rc})"))
                continue
            if m_rc in _PYTEST_NOTHING_JUDGED:
                report.results.append(MutationResult(
                    mut, BROKE_COLLECTION,
                    detail=(f"прогон не собрался (код pytest {m_rc}) — ни одно "
                            f"утверждение не судило, «убит» сказать НЕ О ЧЕМ")))
                continue
            fresh = tuple(n for n in parse_failures(m_out) if n not in baseline)
            if fresh:
                report.results.append(MutationResult(mut, KILLED, new_failures=fresh))
            else:
                gone = [n for n in baseline if n not in parse_failures(m_out)]
                detail = ("набор упавших имён не изменился — дыра покрытия"
                          if not gone else
                          f"новых падений нет, но ИСЧЕЗЛИ прежние: {', '.join(gone)} — "
                          f"мутант погасил чужое красное, разобрать отдельно")
                report.results.append(MutationResult(mut, SURVIVED, detail=detail))
    finally:
        after = {}
        for rel, real in targets.items():
            try:
                after[rel] = _digest(real)
            except OSError as exc:
                after[rel] = f"НЕ ПРОЧИТАН: {exc}"
        drifted = [rel for rel in targets if after.get(rel) != before[rel]]
        if drifted:
            raise TreeNotRestored(
                "дерево НЕ восстановлено после прогона — в нём остался мутант: "
                + ", ".join(sorted(drifted)))

    # Перечень исходов ЗАКРЫТ, и это проверяется, а не обещается.
    assert len(report.results) == len(spec.mutations), (
        f"исходов {len(report.results)} при населении {len(spec.mutations)} — "
        f"мутация исчезла из вердикта")
    return report


# ─────────────────────────── печать ───────────────────────────


_MARK = {KILLED: "✅ убит        ", SURVIVED: "❌ ВЫЖИЛ       ",
         NOT_APPLIED: "⚠️  НЕ ПРИМЕНЕНА", BROKE_COLLECTION: "⚠️  СЛОМАЛ СБОРКУ"}


def render(report: Report) -> str:
    lines = [f"ДЕЛЬТА: {report.spec.title}",
             f"батарея: {' '.join(report.spec.tests)}"]
    if report.unmeasured_reason:
        lines.append(f"🚫 НЕ ИЗМЕРЕНО — {report.unmeasured_reason}")
        return "\n".join(lines)
    lines.append(
        "КОНТРОЛЬ ШУМА: упавших имён нет — контур зелен" if not report.baseline_failures
        else ("КОНТРОЛЬ ШУМА: уже красны " + str(len(report.baseline_failures))
              + " имён (вердикт мутантов — по РАЗНОСТИ наборов): "
              + ", ".join(report.baseline_failures)))
    for r in report.results:
        tail = r.detail or (", ".join(r.new_failures) if r.new_failures else "")
        lines.append(f"  {_MARK[r.outcome]} {r.mutation.name} — {tail}")
    counts = {o: len(report.by_outcome(o)) for o in OUTCOMES}
    lines.append(
        f"\nМУТАЦИИ ПО ДЕЛЬТЕ: применено {report.applied} · убито {counts[KILLED]} · "
        f"выжило {counts[SURVIVED]} · НЕ ПРИМЕНЕНО {counts[NOT_APPLIED]} · "
        f"СЛОМАЛИ СБОРКУ {counts[BROKE_COLLECTION]} (население {len(report.spec.mutations)})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--spec", required=True, help="файл спецификации мутаций (JSON)")
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--json", action="store_true", help="машинный вердикт")
    args = ap.parse_args(argv)
    try:
        spec = load_spec(args.spec)
        report = run(spec, repo_root=args.repo_root)
    except SpecError as exc:
        print(f"🚫 НЕ ИЗМЕРЕНО — спецификация: {exc}", file=sys.stderr)
        return RC_UNMEASURED
    except TreeNotRestored as exc:
        print(f"🚫 {exc}", file=sys.stderr)
        return RC_UNMEASURED
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) if args.json
          else render(report))
    return report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
