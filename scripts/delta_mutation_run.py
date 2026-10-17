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

ОКНО ПРИБОРА — ЧТО ВИДИТ ТОТ, КТО ПРИШЁЛ ПОСЛЕ (заказ G771 п. 4, ADR-772)
------------------------------------------------------------------------
Между подменой файла и его возвратом дерево держит МУТАНТА, и этот промежуток назван
«окном». Возврат живёт в `finally` — то есть обеспечен для исключения, но НЕ для смерти
процесса: `SIGKILL`, падение хоста и просто убитая сессия `finally` не исполняют.

ЗАМЕР 2026-10-17 (цикл #888), две оси:

  * деревьев на хосте, держащих мутанта ПРЯМО СЕЙЧАС — **1** (`/private/tmp/spa_c886`,
    `ledger_day_unit_census.py:336` = мутация №7 его же спецификации, сутки спустя);
  * **назвать этого мутанта было нечем.** Слепок исходных байтов жил ТОЛЬКО в памяти
    умершего процесса (`originals` — локальная переменная), а от git-вершины дерева тот
    же файл отличается и собственной работой сессии. Наивная сверка «якоря нет, подмена
    есть» дала 13 кандидатов, из которых **12 ложных** (в старых деревьях якорь ещё не
    существовал). Мутанта #886 опознал цикл #887 — только потому, что доставил ту же
    работу и получил эталон; без доставки опознавать было бы не с чем.

Отсюда ответ на вопрос заказа «восстановитель по выходу ИЛИ замок на дереве»: **нужны оба,
и несущая половина — ЗАПИСЬ.** Восстановитель по выходу (`finally` + обработчики
`SIGTERM/SIGINT/SIGHUP`) закрывает смерти, которые идут через стек; `SIGKILL` он не
закрывает ПО ПОСТРОЕНИЮ. Переживает смерть процесса только то, что легло на диск:

  * `.mutation_window/window.json` — запись окна: чьё, когда открыто, какие файлы тронуты
    и каков слепок КАЖДОГО до мутации;
  * `.mutation_window/pristine/<хеш пути>` — сами исходные байты, чтобы вернуть их мог
    КТО УГОДНО, а не только автор прогона.

Запись появляется ДО первой подмены и снимается ТОЛЬКО после побайтовой сверки возврата.
Поэтому «записи нет» означает «дерево чисто», а не «про дерево ничего не известно».
Три двери читают её ОДНИМ читателем (:func:`window_state`), и своей копии правила ни у
одной нет:

  * сам прибор — второй прогон в том же дереве ОТКАЗЫВАЕТ (`--window-check`), иначе он
    затёр бы слепок первого, и мутант стал бы вечным;
  * пушер (`push_to_github.py`, `push_to_github_batch.py`) — файл под открытым окном
    НЕ ДОСТАВЛЯЕТСЯ: ровно эта доставка едва не случилась в цикле #887;
  * `--window-restore` — возврат по записи, с проверкой слепка; это и есть путь наверх
    для дерева, доставшегося в наследство.

КОНТРАКТ
--------
  * прибор только ПРИМЕНЯЕТ и ВОЗВРАЩАЕТ: своих мутаций у него нет, и он ничего не чинит;
  * окно ОБЪЯВЛЕНО на диске ДО первой подмены и снято только после сверки возврата;
  * мутировать можно только файл ВНУТРИ дерева и только НЕ под `data/` (там живёт трек);
    символическая ссылка отвергается ГРОМКО — запись сквозь неё уходит наружу копии
    (измеренный механизм карточки `inbox-ubityi-progon-perepisi-ostavlyaet-mutant`);
  * окружение прогона закреплено (`SPA_ENV=ci`, `PYTHONHASHSEED=0`, `-p no:randomly`):
    иначе один и тот же мутант убивается или выживает от порядка обхода множеств;
  * только stdlib.

CLI::

    python3 scripts/delta_mutation_run.py --spec docs/mutations/ADR-726-c870.json
    python3 scripts/delta_mutation_run.py --spec <файл> --json
    python3 scripts/delta_mutation_run.py --window-check [--repo-root R] [--files ...]
    python3 scripts/delta_mutation_run.py --window-restore [--repo-root R]

КОДЫ ВОЗВРАТА ЧИТАТЕЛЯ ОКНА (`--window-check`, `--window-restore`)
------------------------------------------------------------------
  0 — ИЗМЕРЕНО: записи окна нет (дерево чисто) либо окно не задевает названный набор;
  1 — НАХОДКА: дерево держит мутанта либо набор доставки лежит под ОТКРЫТЫМ окном;
  2 — НЕ ИЗМЕРЕНО: запись есть, но прочитать её или слепок нечем (fail-CLOSED).

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
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

#: Запись ОКНА. Лежит в корне ТОГО дерева, чьи файлы тронуты: вопрос «держит ли это
#: дерево мутанта» задаётся о дереве, и ответ обязан лежать там же, а не в `/tmp` рядом
#: с процессом, который умрёт.
WINDOW_DIR = ".mutation_window"
WINDOW_RECORD_REL = WINDOW_DIR + "/window.json"
WINDOW_PRISTINE_REL = WINDOW_DIR + "/pristine"

#: Исходы читателя окна. Перечень ЗАКРЫТ, и третий исход — ПЕРВОКЛАССНЫЙ (инв. #17):
#: «запись есть, но слепка нет» не есть ни «чисто», ни «мутант».
WINDOW_NONE = "no_window"
WINDOW_HOLDS_MUTANT = "holds_mutant"
WINDOW_OPEN_PRISTINE = "open_pristine"
WINDOW_UNMEASURED = "unmeasured"
WINDOW_STATES = (WINDOW_NONE, WINDOW_HOLDS_MUTANT, WINDOW_OPEN_PRISTINE,
                 WINDOW_UNMEASURED)

#: Коды возврата читателя окна. «НЕ ИЗМЕРЕНО» делит код с замером (2) намеренно: вопрос
#: другой, а РОД ответа тот же, и у вызывающего одна ветка на оба.
RC_WINDOW_CLEAN = 0
RC_WINDOW_FINDING = 1

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


class OpenWindow(Exception):
    """В дереве УЖЕ открыто окно прибора (или его запись не читается).

    Второй прогон поверх первого затёр бы слепок исходных байтов — и мутант первого
    стал бы вечным, потому что вернуть его было бы нечем. Замер цикла #885: копия в
    дерево приёмочного прогона была снята ВНУТРИ окна, и предписанный прогон полчаса
    мерил мутанта. Отказ fail-CLOSED; путь наверх — `--window-restore`.
    """


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


# ─────────────────────────── ОКНО ПРИБОРА ───────────────────────────


def window_record_path(repo_root: str) -> str:
    """Путь записи окна у ЭТОГО дерева. Одна копия адреса на весь прибор."""
    return os.path.join(os.path.realpath(repo_root), *WINDOW_RECORD_REL.split("/"))


def _pristine_name(rel: str) -> str:
    """Имя слепка — хеш ПУТИ, а не путь с заменой разделителя.

    `a/b.py` и `a__b.py` при замене `/` → `__` дали бы ОДНО имя, и слепок одного файла
    молча стал бы слепком другого — возврат тогда записал бы чужие байты.
    """
    return hashlib.sha256(rel.encode("utf-8")).hexdigest()[:32] + ".pristine"


def _run_label(pid: int | None = None, label: str | None = None) -> str:
    """Личность прогона. Метка работника, если она объявлена, иначе pid+хост.

    Номер процесса сам по себе личностью НЕ является (`.claude/rules/deployment.md`
    § «ЛИЧНОСТЬ ПРОЦЕССА»): ОС доходит до него по кругу, и на следующий день тот же
    номер держит `siriactionsd`. Поэтому в записи хранятся ОБА — и метка, и номер.
    """
    if label:
        return label
    env = os.environ.get("SPA_RUN_ID") or os.environ.get("SPA_WORKER_LABEL")
    if env:
        return env
    return f"delta-mutation-{pid or os.getpid()}"


def read_window(repo_root: str) -> tuple[dict | None, str | None]:
    """Прочитать запись окна. Возврат — ``(запись | None, причина-НЕ-ИЗМЕРЕНО | None)``.

    Три исхода разведены У ЧИТАТЕЛЯ, а не у вызывающего: ``(None, None)`` — записи нет
    (дерево чисто), ``(запись, None)`` — окно объявлено, ``(None, причина)`` — запись
    есть, но сказать по ней нечего. Последнее НЕ выдаётся за первое: «неполная запись»
    молча зачлась бы как «чисто», и это ровно fail-OPEN инварианта #17.
    """
    path = window_record_path(repo_root)
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return None, (f"запись окна {WINDOW_RECORD_REL} есть, но не читается: "
                      f"{type(exc).__name__}: {exc} — какие файлы тронуты, НЕ ИЗМЕРЕНО")
    if not isinstance(doc, dict):
        return None, (f"запись окна {WINDOW_RECORD_REL} — не объект, а "
                      f"{type(doc).__name__}: перечень тронутых файлов НЕ ИЗМЕРЕН")
    files = doc.get("files")
    if not isinstance(files, list) or not files:
        return None, (f"в записи окна {WINDOW_RECORD_REL} нет непустого раздела `files` — "
                      f"какие файлы тронуты, НЕ ИЗМЕРЕНО")
    for i, item in enumerate(files):
        if not isinstance(item, dict) or not isinstance(item.get("file"), str) \
                or not item["file"]:
            return None, (f"в записи окна {WINDOW_RECORD_REL} files[{i}] без имени файла — "
                          f"перечень тронутого НЕПОЛОН")
    return doc, None


def open_window(repo_root: str, spec: "Spec", targets: dict, originals: dict, *,
                spec_path: str | None = None, now: str | None = None,
                pid: int | None = None, label: str | None = None,
                tool: str = "scripts/delta_mutation_run.py") -> dict:
    """Объявить окно НА ДИСКЕ: слепок каждого тронутого файла ДО первой подмены.

    `spec` здесь — КОНТРАКТ, а не класс: нужны ровно `.title` (как назвать прогон в
    записи) и `.mutations` (у каждой `.name` и `.file`). Это объявлено намеренно —
    окно есть свойство ДЕРЕВА, а не этого прибора, и второй мутирующий инструмент
    обязан писать ТУ ЖЕ запись, а не завести свою. Второй такой инструмент —
    `scripts/mutation_gate.py` (цикл #889, заказ G772 п. 2): он подменял на месте
    четыре money-path модуля, держа исходный текст в локальной переменной, и после
    `SIGKILL` дерево оставалось с отключённым APY-порогом RiskPolicy, о котором НЕ
    говорил никто. `tool` называет, КТО открыл окно: без этого поля наследник читал бы
    запись и искал спецификацию, которой у второго инструмента нет вовсе.

    Слепок кладётся файлом, а не только хешем, намеренно: хеш говорит «байты не те»,
    а вернуть байты по нему нельзя. Замер цикла #888: единственная копия исходных байтов
    жила в локальной переменной процесса, который умирает, — и назвать мутанта мёртвой
    сессии было нечем, пока ту же работу не доставил кто-то другой.

    Время, номер процесса и метка работника — ВХОДЫ: иначе запись нельзя закрепить
    тестом, не завязавшись на стенные часы и на номер, который ОС выдаст сегодня.
    """
    root = os.path.realpath(repo_root)
    existing, why = read_window(root)
    if why is not None:
        raise OpenWindow(f"в дереве {root}: {why}. Разобрать: "
                         f"`--window-check --repo-root {root}`; вернуть байты: "
                         f"`--window-restore --repo-root {root}`")
    if existing is not None:
        raise OpenWindow(
            f"в дереве {root} УЖЕ открыто окно прибора (открыто {existing.get('opened_at')}, "
            f"прогон {existing.get('run_label')}, pid {existing.get('pid')}, файлы: "
            + ", ".join(sorted(f["file"] for f in existing["files"]))
            + f"). Второй прогон затёр бы слепок первого, и его мутанта стало бы нечем "
              f"вернуть. Путь наверх: `--window-restore --repo-root {root}`")

    pdir = os.path.join(root, *WINDOW_PRISTINE_REL.split("/"))
    os.makedirs(pdir, exist_ok=True)
    files = []
    for rel in sorted(targets):
        real = targets[rel]
        name = _pristine_name(rel)
        copy = os.path.join(pdir, name)
        _write_atomically(copy, originals[rel])
        files.append({
            "file": rel,
            "real": real,
            "sha256": _digest(real),
            "pristine_copy": WINDOW_PRISTINE_REL + "/" + name,
            "copy_sha256": _digest(copy),
        })
    record = {
        "measured": True,
        "state": "open",
        "tool": tool,
        "opened_at": now or datetime.now(timezone.utc).isoformat(),
        "pid": pid if pid is not None else os.getpid(),
        "run_label": _run_label(pid, label),
        "hostname": socket.gethostname(),
        "repo_root": root,
        "spec_path": spec_path,
        "spec_title": spec.title,
        "mutations": [{"name": m.name, "file": m.file} for m in spec.mutations],
        "files": files,
    }
    _write_atomically(window_record_path(root),
                      json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


def close_window(repo_root: str) -> bool:
    """Снять запись окна и слепки. Возврат — была ли запись.

    **Порядок снятия — часть меры.** Запись снимается ПЕРВОЙ, слепки — после: смерть
    между этими двумя действиями оставит каталог слепков без записи, и читатель верно
    скажет «записи нет, дерево чисто» (байты к этому моменту уже сверены). Обратный
    порядок оставил бы запись, указывающую на исчезнувший слепок, — то есть громкое
    «НЕ ИЗМЕРЕНО» на дереве, с которым всё в порядке.
    """
    root = os.path.realpath(repo_root)
    path = window_record_path(root)
    had = os.path.exists(path)
    try:
        if had:
            os.unlink(path)
    except OSError:
        return had
    shutil.rmtree(os.path.join(root, WINDOW_DIR), ignore_errors=True)
    return had


def _asked_relative(root: str, files) -> set[str] | None:
    """Набор доставки в координатах дерева. ``None`` — набор не назван.

    Путь вне дерева отбрасывается молча НЕ бывает: он просто не о этом дереве, и
    пересечение с окном у него пустое по построению.
    """
    if files is None:
        return None
    out: set[str] = set()
    for f in files:
        s = str(f)
        real = os.path.realpath(s if os.path.isabs(s) else os.path.join(root, s))
        if real == root or real.startswith(root + os.sep):
            out.add(os.path.relpath(real, root).replace(os.sep, "/"))
    return out


def window_state(repo_root: str, *, files=None) -> dict:
    """Единственный читатель окна: «держит ли это дерево мутанта?».

    Возврат — словарь с полями ``state`` (из :data:`WINDOW_STATES`), ``rc``, ``detail``,
    ``mutants``, ``window_files``, ``touching``, ``record``.

    Четыре исхода, и ни один не подменяет другого:

    * :data:`WINDOW_NONE` — записи нет. Это ИЗМЕРЕННОЕ «чисто»: запись снимается только
      после побайтовой сверки возврата, поэтому её отсутствие есть утверждение;
    * :data:`WINDOW_HOLDS_MUTANT` — байты файла разошлись со слепком: в дереве лежит
      мутант, и он НАЗВАН вместе с мутацией, которая его объясняет;
    * :data:`WINDOW_OPEN_PRISTINE` — окно открыто, байты целы (прогон идёт либо сессия
      умерла между возвратом и уборкой). Само по себе это не вред, но доставка файла из
      такого дерева — гонка: прогон перепишет его в любую секунду;
    * :data:`WINDOW_UNMEASURED` — запись или слепок не прочитаны. Fail-CLOSED.

    ``files`` — набор доставки (ВХОД). Назван ⇒ находкой считается только пересечение с
    окном: мутант в чужом файле не повод запретить доставку соседнего, иначе сторож
    научит обходить себя.
    """
    root = os.path.realpath(repo_root)
    doc, why = read_window(root)
    base = {"state": WINDOW_NONE, "rc": RC_WINDOW_CLEAN, "detail": "",
            "mutants": [], "window_files": [], "touching": [], "record": None,
            "repo_root": root}
    if why is not None:
        base.update(state=WINDOW_UNMEASURED, rc=RC_UNMEASURED, detail=why)
        return base
    if doc is None:
        base["detail"] = (f"записи окна нет ({WINDOW_RECORD_REL}) — прибор в этом дереве "
                          f"не держит ни одного файла")
        return base

    window_files = sorted(str(item["file"]) for item in doc["files"])
    asked = _asked_relative(root, files)
    mutants: list[dict] = []
    unread: list[str] = []
    for item in doc["files"]:
        rel = str(item["file"])
        want = item.get("sha256")
        real = os.path.join(root, *rel.split("/"))
        if not isinstance(want, str) or not want:
            unread.append(f"{rel}: в записи нет слепка — разошлись байты или нет, "
                          f"сказать нечем")
            continue
        try:
            have = _digest(real)
        except OSError as exc:
            unread.append(f"{rel}: файл не прочитан ({exc})")
            continue
        if have != want:
            named = [m.get("name") for m in (doc.get("mutations") or [])
                     if isinstance(m, dict) and m.get("file") == rel]
            mutants.append({"file": rel, "expected": want, "found": have,
                            "mutations": [n for n in named if n]})
    if unread:
        base.update(state=WINDOW_UNMEASURED, rc=RC_UNMEASURED,
                    window_files=window_files, record=doc,
                    detail=("окно объявлено, но сверить байты нечем: "
                            + " · ".join(unread)))
        return base

    touching = sorted(set(window_files) & asked) if asked is not None else window_files
    # ИНСТРУМЕНТ назван вместе со спецификацией: запись окна пишут ДВА прибора
    # (`delta_mutation_run.py` и `mutation_gate.py`), и у второго спецификации-файла нет
    # вовсе — без имени инструмента наследник искал бы `--spec`, которого не существует.
    who = (f"прогон {doc.get('run_label')} (pid {doc.get('pid')}, хост "
           f"{doc.get('hostname')}), окно открыто {doc.get('opened_at')}, инструмент "
           f"{doc.get('tool') or 'НЕ НАЗВАН В ЗАПИСИ'}, спецификация "
           f"{doc.get('spec_path') or doc.get('spec_title')}")
    if mutants:
        hit = [m for m in mutants if asked is None or m["file"] in asked]
        # Мутации перечисляются ВСЕ и названы КАНДИДАТАМИ: читатель сверяет байты со
        # слепком и по ним не знает, какая именно мутация лежит. Прежняя форма печатала
        # `m['mutations'][0]`, то есть ОДНО имя из нескольких как установленный факт —
        # у спецификации с одной мутацией на файл это совпадало, а у кураторского набора
        # `mutation_gate.py` на `risk/policy.py` их ПЯТЬ (цикл #889), и названная первой
        # была бы догадкой в утвердительной форме.
        detail = ("дерево ДЕРЖИТ МУТАНТА: "
                  + " · ".join(f"{m['file']} (ожидался {m['expected'][:12]}, лежит "
                               f"{m['found'][:12]}"
                               + (("; мутация: " + m["mutations"][0])
                                  if len(m["mutations"]) == 1 else
                                  ("; одна из мутаций окна по этому файлу: "
                                   + ", ".join(m["mutations"]))
                                  if m["mutations"] else "")
                               + ")" for m in mutants)
                  + f"; {who}. Вернуть байты: `--window-restore --repo-root {root}`")
        if asked is not None and not hit:
            detail += (" — НО названный набор доставки этих файлов не содержит: "
                       + (", ".join(touching) if touching
                          else "пересечения с окном нет вовсе"))
        base.update(state=WINDOW_HOLDS_MUTANT, mutants=mutants, record=doc,
                    window_files=window_files, touching=touching, detail=detail,
                    rc=(RC_WINDOW_FINDING if (asked is None or touching)
                        else RC_WINDOW_CLEAN))
        return base

    detail = (f"окно ОТКРЫТО, байты целы: {who}. Файлы окна: "
              + ", ".join(window_files))
    if asked is not None and touching:
        detail += (" — и набор доставки их содержит ("
                   + ", ".join(touching)
                   + "): прогон перепишет файл в любую секунду, доставка из такого "
                     "дерева есть ГОНКА")
    base.update(state=WINDOW_OPEN_PRISTINE, record=doc, window_files=window_files,
                touching=touching, detail=detail,
                rc=(RC_WINDOW_FINDING if (asked is not None and touching)
                    else RC_WINDOW_CLEAN))
    return base


def restore_window(repo_root: str) -> dict:
    """Вернуть байты ПО ЗАПИСИ окна и снять её. Ничего не угадывает.

    Возврат — отчёт: ``measured``, ``restored``, ``already_clean``, ``failed``,
    ``closed``, ``reason``. Невосстановленный файл записи НЕ снимает: иначе дерево с
    мутантом стало бы «чистым» по мерке самого сторожа.
    """
    root = os.path.realpath(repo_root)
    doc, why = read_window(root)
    if why is not None:
        return {"measured": False, "reason": why, "restored": [], "already_clean": [],
                "failed": [], "closed": False, "repo_root": root}
    if doc is None:
        return {"measured": True, "reason": "записи окна нет — возвращать нечего",
                "restored": [], "already_clean": [], "failed": [], "closed": False,
                "repo_root": root}
    restored: list[str] = []
    already: list[str] = []
    failed: list[str] = []
    for item in doc["files"]:
        rel = str(item["file"])
        want = item.get("sha256")
        real = os.path.join(root, *rel.split("/"))
        copy_rel = item.get("pristine_copy")
        if not isinstance(want, str) or not want:
            failed.append(f"{rel}: в записи нет слепка — вернуть НЕ К ЧЕМУ")
            continue
        try:
            have = _digest(real)
        except OSError as exc:
            failed.append(f"{rel}: файл не прочитан ({exc})")
            continue
        if have == want:
            already.append(rel)
            continue
        if not isinstance(copy_rel, str) or not copy_rel:
            failed.append(f"{rel}: байты разошлись, а адреса слепка в записи нет")
            continue
        copy = os.path.join(root, *copy_rel.split("/"))
        try:
            text = open(copy, encoding="utf-8").read()
        except OSError as exc:
            failed.append(f"{rel}: слепок {copy_rel} не прочитан ({exc}) — "
                          f"мутант остаётся, и это сказано вслух")
            continue
        expect_copy = item.get("copy_sha256")
        if isinstance(expect_copy, str) and expect_copy and _digest(copy) != expect_copy:
            failed.append(f"{rel}: слепок {copy_rel} сам испорчен — записывать его "
                          f"значило бы доставить третьи байты")
            continue
        try:
            _invalidate_bytecode(real)
            _write_atomically(real, text)
            _invalidate_bytecode(real)
        except OSError as exc:
            failed.append(f"{rel}: возврат не записан ({exc})")
            continue
        if _digest(real) != want:
            failed.append(f"{rel}: после возврата слепок ВСЁ РАВНО не тот — "
                          f"разбирать руками")
            continue
        restored.append(rel)
    closed = False
    if not failed:
        close_window(root)
        closed = True
    return {"measured": True, "reason": None, "restored": restored,
            "already_clean": already, "failed": failed, "closed": closed,
            "repo_root": root, "record": doc}


def render_window(state: dict) -> str:
    """Печать вердикта окна. Третий исход виден словом, а не только кодом возврата."""
    mark = {WINDOW_NONE: "✅ ОКНА НЕТ", WINDOW_HOLDS_MUTANT: "🚫 МУТАНТ В ДЕРЕВЕ",
            WINDOW_OPEN_PRISTINE: "⚠️  ОКНО ОТКРЫТО",
            WINDOW_UNMEASURED: "🚫 НЕ ИЗМЕРЕНО"}[state["state"]]
    return (f"{mark} ({state['state']}, код {state['rc']}) — дерево "
            f"{state['repo_root']}\n   {state['detail']}")


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
        runner: Callable[..., tuple[int, str]] | None = None,
        spec_path: str | None = None, now: str | None = None,
        pid: int | None = None, label: str | None = None) -> Report:
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

    # ОКНО объявляется ЗДЕСЬ: после контроля шума (отказ по батарее не должен оставлять
    # записи) и ДО первой подмены (запись, сделанная после, не описывает тот миг, когда
    # мутант уже в дереве). Отказ открыть окно — громкий: он означает, что в дереве уже
    # лежит чужой слепок, и затирать его нельзя.
    open_window(root, spec, targets, originals, spec_path=spec_path, now=now,
                pid=pid, label=label)

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
            # Запись окна НЕ снимается: именно она делает оставшегося мутанта
            # называемым и возвращаемым — тем, кто придёт после, а не только автором
            # этого прогона.
            raise TreeNotRestored(
                "дерево НЕ восстановлено после прогона — в нём остался мутант: "
                + ", ".join(sorted(drifted))
                + f". Запись окна оставлена ({WINDOW_RECORD_REL}); вернуть байты: "
                  f"`python3 scripts/delta_mutation_run.py --window-restore "
                  f"--repo-root {root}`")
        # Байты сверены и совпали — только теперь окно закрывается. «Записи нет»
        # после этого есть ИЗМЕРЕННОЕ «дерево чисто», а не отсутствие сведений.
        close_window(root)

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


def _raise_on_signal(signum, _frame):
    """Сигнал обязан пройти через `finally`, а не убить прибор на месте.

    `SIGKILL` этим НЕ закрывается ПО ПОСТРОЕНИЮ — обработчика у него нет. Именно
    поэтому у прибора есть ЗАПИСЬ окна: восстановитель по выходу закрывает смерти,
    идущие через стек, а запись — все остальные.
    """
    raise SystemExit(f"прибор остановлен сигналом {signum}: дерево возвращается "
                     f"через finally, запись окна снимается только после сверки")


def install_signal_guard(handler=_raise_on_signal) -> list[int]:
    """Поставить сторожа на сигналы, которые можно перехватить. Возврат — какие встали.

    Обработчик — ВХОД: тест закрепляет ПРОВОДКУ (какие номера сигналов реально
    получили сторожа), не поднимая настоящий сигнал в процессе pytest.
    """
    armed: list[int] = []
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError, RuntimeError):
            continue
        armed.append(int(sig))
    return armed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--spec", default=None, help="файл спецификации мутаций (JSON)")
    ap.add_argument("--window-check", action="store_true",
                    help="прочитать окно прибора у дерева: держит ли оно мутанта "
                         "(0 — нет · 1 — находка · 2 — НЕ ИЗМЕРЕНО)")
    ap.add_argument("--window-restore", action="store_true",
                    help="вернуть байты по записи окна и снять её")
    ap.add_argument("--files", nargs="*", default=None,
                    help="набор доставки: с ним находкой считается только пересечение "
                         "с окном (для пушера)")
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--json", action="store_true", help="машинный вердикт")
    args = ap.parse_args(argv)

    modes = [bool(args.spec), bool(args.window_check), bool(args.window_restore)]
    if sum(modes) != 1:
        print("🚫 НЕ ИЗМЕРЕНО — назови РОВНО один режим: --spec <файл> либо "
              "--window-check либо --window-restore", file=sys.stderr)
        return RC_UNMEASURED

    if args.window_check:
        state = window_state(args.repo_root or REPO_ROOT, files=args.files)
        printable = {k: v for k, v in state.items() if k != "record"}
        print(json.dumps(printable, ensure_ascii=False, indent=2) if args.json
              else render_window(state))
        return int(state["rc"])

    if args.window_restore:
        out = restore_window(args.repo_root or REPO_ROOT)
        if args.json:
            print(json.dumps({k: v for k, v in out.items() if k != "record"},
                             ensure_ascii=False, indent=2))
        elif not out["measured"]:
            print(f"🚫 НЕ ИЗМЕРЕНО — {out['reason']}", file=sys.stderr)
        elif out["failed"]:
            print("🚫 возврат НЕ ПОЛОН, запись окна оставлена: "
                  + " · ".join(out["failed"]), file=sys.stderr)
        else:
            print(f"✅ окно снято: возвращено {len(out['restored'])} "
                  f"({', '.join(out['restored']) or '—'}), и так целы "
                  f"{len(out['already_clean'])}"
                  + (f" · {out['reason']}" if out["reason"] else ""))
        if not out["measured"]:
            return RC_UNMEASURED
        return RC_WINDOW_FINDING if out["failed"] else RC_WINDOW_CLEAN

    install_signal_guard()
    try:
        spec = load_spec(args.spec)
        report = run(spec, repo_root=args.repo_root, spec_path=args.spec)
    except SpecError as exc:
        print(f"🚫 НЕ ИЗМЕРЕНО — спецификация: {exc}", file=sys.stderr)
        return RC_UNMEASURED
    except OpenWindow as exc:
        print(f"🚫 НЕ ИЗМЕРЕНО — окно прибора: {exc}", file=sys.stderr)
        return RC_UNMEASURED
    except TreeNotRestored as exc:
        print(f"🚫 {exc}", file=sys.stderr)
        return RC_UNMEASURED
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) if args.json
          else render(report))
    return report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
