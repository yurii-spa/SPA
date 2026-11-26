#!/usr/bin/env python3
"""Перепись класса «производный артефакт уехал без перемера».

Заказ G1061 п. 2 приказа владельца «Portfolio CIO», карточка
`inbox-izmerit-naselenie-klassa-proizvodnyi-art`. Правило —
`.claude/rules/deployment.md` § «ПРОИЗВОДНАЯ ПЕРЕПИСЬ, ОТ КОТОРОЙ СЧИТАЕТСЯ
ЗНАМЕНАТЕЛЬ» (одиннадцатая дверь, ADR-1073), последний абзац: «население класса
„производный индекс уехал без пересборки“ за пределами доски, реестра решений и
этой переписи НЕ ИЗМЕРЕНО — нулём это не считается».

ЧТО ЗА КЛАСС И ПОЧЕМУ ЕГО НЕЛЬЗЯ МЕРИТЬ ПРОЗОЙ
─────────────────────────────────────────────────────────────────────────────
Производный артефакт (перепись, доска, реестр, индекс) обязан пересобираться,
когда меняется НАБОР файлов-источников. Сторож такого артефакта перечисляет
каталог исходников и сверяет диск с артефактом, то есть **его вердикт зависит от
набора файлов, а не от содержимого любого из них**. Доставка нового файла без
пересборки артефакта краснит `main` у ЧУЖОГО цикла.

Трижды это уже найдено поимённо: доска очереди (ADR-1060), реестр решений
(ADR-889), перепись `_untiered_census` (ADR-1073). Каждый раз — ПОСЛЕ того, как
красное уехало.

Урок #1217, ради которого прибор и написан: цикл #1216 объявил свою доставку
чистой, померив красноту на **ПАРЕ** сторожей, НАЗВАННОЙ прозой заказа, —
покраснел ТРЕТИЙ. Мерка, выбранная прозой, отвечает на вопрос прозы.

ЧИСЛО «652» ЗАКАЗА НАЗЫВАЛО НЕ ЭТУ ПОВЕРХНОСТЬ — ЗАМЕР 23.11
─────────────────────────────────────────────────────────────────────────────
Заказ G1061 п. 2 назвал поверхностью «652 из 2587 тест-файлов перечисляют
каталог». Число воспроизводится (**653** на 2fc564a0e), и оно НЕ про эту
поверхность: оно снято совпадением по ИМЕНИ МЕТОДА, поэтому в него вошли **547**
зовов `ast.walk(tree)` — обход синтаксического дерева, каталогов не
перечисляющий вовсе. По ФАЙЛАМ: 653 → **458**, то есть **195 файлов (29,9 %)**
попали в «поверхность» ни одним каталогом. Мерка, выбранная по имени метода,
отвечала на вопрос «как называется метод».

Это та же форма, что урок #1217, с которого заказ и начался: мерка, выбранная
прозой, отвечает на вопрос прозы, — только здесь прозой была СВОЯ.

ФОРМА «ТЕСТ САМ ПЕРЕЧИСЛЯЕТ КАТАЛОГ» ОПРОВЕРГНУТА ЗАМЕРОМ, И ЭТО ГЛАВНОЕ
─────────────────────────────────────────────────────────────────────────────
Из ТРЁХ артефактов, у которых класс уже найден поимённо, форма «тест сам несёт
перечисляющий зов» нашла РОВНО ОДИН (`test_adr_index_titles`). Два других —
`test_untiered_census` (ADR-1073) и `test_tracker_board_matches_cards`
(ADR-1060) — перечисляют каталог ЧЕРЕЗ ПОМОЩНИКА
(`scripts/audit_untiered_analytics.py`, `scripts/build_tracker_board.py`).
Форма, теряющая 2 из 3 известных членов, не сужает класс — она подменяет его.

Поэтому поверхность считается с **ОДНИМ ХОПОМ** через помощника (ниже), а
`KNOWN_MEMBERS` стои́т положительным контролем: потерян хоть один ⇒ перепись
ОТКАЗЫВАЕТ (код 2) и число предмета населением класса НЕ называет.

Сужение идёт РАЗБОРОМ ПУТИ, а не чтением глазами: перечисляемый путь
прослеживается по привязкам модуля до неподвижной точки и классифицируется.

    ┌─ `source_dir`   путь разрешается в каталог ИСХОДНИКОВ репозитория
    │                 ⇒ ПРЕДМЕТ замера: набор на диске может вырасти доставкой
    ├─ `state_dir`    путь разрешается в `data/` ⇒ НЕ предмет: это runtime-
    │                 состояние, доставкой кода оно не растёт
    ├─ `sandbox`      путь — одноразовая сцена (`mkdtemp`, `TemporaryDirectory`,
    │                 `tmp_path`, литерал под `/tmp`) ⇒ НЕ предмет: сцена сама
    │                 кладёт свои файлы, от набора репозитория не зависит
    └─ `unresolved`   путь НЕ РАЗОБРАН ⇒ **третий исход** (инв. #17): это
                      `unmeasured` с названной причиной и ненулевым кодом, а НЕ
                      ноль и НЕ «не предмет».

**Ошибка сужения выбрана в сторону БОЛЬШЕЙ поверхности.** Файл с хотя бы одним
`source_dir`-зовом попадает в предмет целиком, даже если девять его других зовов
смотрят в песочницу: мера, ошибающаяся в сторону МЕНЬШЕЙ, умеет сказать
«поверхность исчерпана» про поверхность, которой не видела.

ДИФФЕРЕНЦИАЛ ПОДКЛАДЫВАЕТ ФАЙЛ В **САМ** ПЕРЕЧИСЛЯЕМЫЙ КАТАЛОГ
─────────────────────────────────────────────────────────────────────────────
Заказ предложил «подложить в пакет новый публичный файл». Прибор делает точнее и
дешевле: для кандидата, перечисляющего каталог `D`, новый публичный файл
кладётся **в `D`**, и гоняется ТОЛЬКО этот кандидат. Один общий файл отвечал бы
на вопрос «краснеет ли сторож от файла в ОДНОМ каталоге», а предмет класса —
«краснеет ли он от роста СВОЕГО каталога».

**Предмет — тот, у кого ЗЕЛЁНЫЙ стал НЕ ЗЕЛЁНЫМ, а не тот, у кого изменилась
строка вердикта.** Первая редакция сличала строку состава и записала в предмет
три файла, у которых выросло одно число `passed` (160→165, 127→129, 2875→2876):
это сторожа, параметризованные по НАБОРУ, которые новый файл УВИДЕЛИ и ПРИНЯЛИ —
противоположность класса. Зависимость от набора сохранена отдельным ярлыком
`set_dependent_green`: сведение полезное, членством не являющееся. Переход в
`skipped` и ПАДЕНИЕ числа пройденных считаются предметом наравне с красным
(урок #465: такой тест не краснеет и не проходит — он ИСЧЕЗАЕТ).

Прогон идёт в ОТДЕЛЬНОМ одноразовом дереве (`--repo-root`), не в дереве
доставки: правило `.claude/rules/deployment.md` § «БАЙТЫ, КОТОРЫЕ НЕ ЯВЛЯЮТСЯ
КОДОМ» п. 1 запрещает долгому прогону жить там, откуда уезжают байты. Дерево —
ВХОД, умолчание ПЕЧАТАЕТСЯ, нечитаемое названное дерево даёт код 2.

ОКНО ПОДЛОЖЕННОГО ФАЙЛА — `finally` НЕ ОБЕСПЕЧЕН ДЛЯ СМЕРТИ ПРОЦЕССА
─────────────────────────────────────────────────────────────────────────────
Измерено на себе (цикл #1218): убитый первый прогон оставил подложенный файл в
`landing/src/pages/admin`, и второй прогон ОТКАЗАЛ по этому каталогу вместо того,
чтобы судить о дереве с чужими байтами. Та же форма, что § «ОКНО МУТАЦИОННОГО
ПРИБОРА» правила доставки: возврат в `finally` обеспечен для исключения и НЕ
обеспечен для `SIGKILL`. Уборка — ОТДЕЛЬНОЕ действие (`--clean-planted`), и она
печатает, что сняла; имя подкладываемого файла одно и известно по построению,
поэтому «ничего не нашлось» означает «дерево чисто», а не «неизвестно».

ЧЕТВЁРТЫЙ ИЗВЕСТНЫЙ ЧЛЕН И ДВЕ ДВЕРИ, КОТОРЫХ НЕ ХВАТАЛО — ЗАМЕР #1259
─────────────────────────────────────────────────────────────────────────────
`KNOWN_MEMBERS` — ЗАКРЫТЫЙ перечень, и он сам не растёт. Четвёртый член класса
(ADR-1112, храповик провенанса чтений `origin/<ветка>`) найден 26.11, через три
дня после первой редакции прибора, и в перечень не попал. Строка «✅ все 3
известных члена ВНУТРИ предмета» оставалась ПРАВДОЙ и отвечала на вопрос о
СПИСКЕ, а не о КЛАССЕ: **контроль, не знающий о члене, не может быть им
опровергнут — он зелен ПО ПОСТРОЕНИЮ.** Та же граница, что у сторожа претензии
`injected-clock` (§ девятая дверь правила доставки), только с другой стороны.

Замер, которым дверь выведена (дерево `fbb0fa45a`, один и тот же прибор):

    редакция поверхности          предмет  НЕ РАЗОБРАНО  известные члены
    ───────────────────────────── ───────  ────────────  ───────────────
    ADR-1074 (как было)              121           132   член 4 ВНЕ (ОПРОВЕРГНУТА)
    + только дверь 1                 123           132   член 4 ВНЕ (ОПРОВЕРГНУТА)
    + только дверь 2                 401           106   член 4 ВНЕ (ОПРОВЕРГНУТА)
    обе двери                        412           106   4 из 4 ВНУТРИ

**Ни одна дверь в одиночку члена не возвращает** — это замер, а не рассуждение,
и он же есть положительный контроль каждой из двух:

  1. **Помощник, ввезённый БАРЕ-ИМЕНЕМ после `sys.path.insert`.** Поиск
     помощников знал только ПУНКТИРНУЮ форму (`spa_core.x` / `scripts.x`), а
     идиома этого дерева — `sys.path.insert(0, str(REPO / "scripts"))` плюс
     `from python_git_ref_provenance import main`. Голова такого ввоза не
     называет каталог вовсе. Дверь — `_sys_path_dirs` (каталоги берутся у ТОГО
     ЖЕ файла и ТЕМ ЖЕ разборщиком). Форму несут **51** тест-файла из четырёх
     объявленных каталогов (замер #1259, НЕ РАЗОБРАНО 0).
  2. **Корень репозитория ЕСТЬ каталог исходников.** `_named_source_dirs`
     отбрасывал путь с пустыми `parts`, то есть отвечал на вопрос «назван ли
     ПОДКАТАЛОГ». Сторож, чей помощник перечисляет `REPO.rglob("*.py")`,
     краснеет от ЛЮБОГО нового `*.py` — это самый сильный член класса, а не
     исключение. Ошибка шла в сторону «чисто».

Число «121 → 412» есть рост КАНДИДАТОВ, а не доказанных членов: сужение
намеренно ошибается в сторону большей поверхности (выше), и разрешает кандидата
ДИФФЕРЕНЦИАЛ. Сколько из 280 новых кандидатов — предмет, **НЕ ИЗМЕРЕНО**
(дифференциал стоит два прогона pytest на кандидата) и нулём не считается.

ГРАНИЦА ДИФФЕРЕНЦИАЛА: ЗОНД ИНЕРТЕН — см. `PLANTED_INERT`
─────────────────────────────────────────────────────────────────────────────
Член 4 дифференциалом НЕ РАЗРЕШАЕТСЯ, и причин ДВЕ, обе измерены:

  * его сторож КРАСЕН на чистом `main` сегодня (долг храповика 80 против базы
    50 — ADR-1112 назвал это верным), поэтому премиса «зелёный ДО» не
    обеспечена, и прибор честно даёт `already_red`, а не «не предмет»;
  * даже при зелёной премисе инертный зонд его вердикта не сдвинул бы:
    предмет храповика решает СОДЕРЖИМОЕ набора. Замер — в `PLANTED_INERT`
    (80 → 80 инертным, 80 → 81 содержательным).

ADVISORY: прибор только ЧИТАЕТ дерево, которое мерит статически. Байты
подкладывает ТОЛЬКО в дифференциальном режиме и ТОЛЬКО в названном `--repo-root`.
RiskPolicy, стоп-кран, живой трек и `landing/` не трогаются ничем.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import subprocess
import sys
from dataclasses import dataclass, field, asdict

# ─── ярлыки исходов: один ярлык — один ответ, и каждый употребляется ниже ────
SOURCE_DIR = "source_dir"
STATE_DIR = "state_dir"
SANDBOX = "sandbox"
UNRESOLVED = "unresolved"

# ─── ярлыки дифференциала ───────────────────────────────────────────────────
SUBJECT = "subject"            # зелёный стал НЕ зелёным от подложенного файла
SET_DEPENDENT_GREEN = "set_dependent_green"   # состав вердикта вырос, но он зелен
NOT_SUBJECT = "not_subject"    # вердикт тот же
ALREADY_RED = "already_red"    # красен ДО подкладывания — зелёным не был
DIFF_UNMEASURED = "diff_unmeasured"   # прогон не дошёл до вердикта

# ─── ИЗВЕСТНЫЕ ЧЛЕНЫ КЛАССА: форма, потерявшая любого, ОПРОВЕРГНУТА ─────────
# Три артефакта найдены поимённо ДО этого прибора, каждый — после того, как
# красное уехало на `main`. Они и есть положительный контроль поверхности:
# перепись, не нашедшая известного члена, печатала бы «предмет 50» про
# поверхность, которой не видела (дословно порядок `_population_verdict_surface`).
KNOWN_MEMBERS = {
    "spa_core/tests/test_untiered_census.py": "ADR-1073 — перепись `_untiered_census`",
    "spa_core/tests/test_tracker_board_matches_cards.py": "ADR-1060 — строка доски очереди",
    "spa_core/tests/test_adr_index_titles.py": "ADR-889 — колонка реестра решений",
    # ЧЕТВЁРТЫЙ член найден 26.11, через три дня после первой редакции прибора,
    # и список НЕ был дочитан. Это и есть дефект цикла #1259: закрытый перечень
    # положительного контроля не растёт сам, поэтому строка «все 3 из 3 внутри
    # предмета» оставалась ПРАВДОЙ и отвечала на вопрос о СПИСКЕ, а не о КЛАССЕ.
    # Контроль, не знающий о члене, не может быть им опровергнут — он зелен ПО
    # ПОСТРОЕНИЮ, ровно как сторож претензии `injected-clock` (§ девятая дверь).
    "spa_core/tests/test_python_git_ref_provenance.py":
        "ADR-1112 — храповик провенанса чтений `origin/<ветка>`",
}

ENUMERATING = frozenset({"glob", "rglob", "iterdir", "listdir", "walk", "scandir", "iglob"})

# Зовы, у которых путь лежит в АРГУМЕНТЕ, а не в получателе (`os.listdir(p)`).
ARG_FORM = frozenset({"listdir", "walk", "scandir", "glob", "iglob"})

# ─── ВАЖНО: имя метода мерой НЕ является ────────────────────────────────────
# Первая редакция этого прибора (и число «652» заказа G1061, снятое тем же
# наивным совпадением по имени) считала перечисляющим зовом ЛЮБОЙ `.walk(...)`.
# Замер 23.11: из 653 файлов поверхности 547 попали в неё через `ast.walk(tree)`
# — обход СИНТАКСИЧЕСКОГО ДЕРЕВА, который каталогов не перечисляет вовсе.
# Мерка, выбранная по имени метода, отвечала на вопрос «как называется метод»,
# а не «зависит ли вердикт от набора файлов на диске» — ровно тот класс, против
# которого написан весь прибор. Поэтому получатель СПРАШИВАЕТСЯ:
# `ast`/`os.path`/`re`/`itertools` путями не бывают.
NON_PATH_RECEIVERS = frozenset({"ast", "re", "itertools", "json", "collections",
                                "textwrap", "inspect", "typing", "shutil"})

# Имена-фикстуры pytest: это ФАКТ о харнессе, а не догадка по имени.
PYTEST_TMP_FIXTURES = frozenset({"tmp_path", "tmpdir", "tmp_path_factory"})

# Каталоги-состояния: доставкой КОДА их набор не растёт.
STATE_PREFIXES = ("data",)

# Признаки одноразовой сцены в тексте пути.
SANDBOX_MARKERS = (
    "mkdtemp", "TemporaryDirectory", "tmp_path", "tmpdir", "tmp_dir",
    "TMPDIR", "gettempdir", "mkstemp", "NamedTemporaryFile",
)

TESTS_REL = pathlib.PurePosixPath("spa_core/tests")


class NotMeasured(RuntimeError):
    """Третий исход: перепись не состоялась, и причина НАЗВАНА."""


# ════════════════════════════════════════════════════════════════════════════
#  РАЗБОР ПУТИ — привязки модуля прослеживаются до неподвижной точки
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class EnumCall:
    """Один перечисляющий зов: где стои́т, что перечисляет, как разобран."""
    lineno: int
    attr: str
    kind: str
    rel_dir: str | None = None     # repo-relative каталог, когда разобран
    reason: str = ""               # почему именно этот ярлык


@dataclass
class FileEntry:
    path: str                      # repo-relative путь тест-файла
    calls: list[EnumCall] = field(default_factory=list)

    @property
    def kind(self) -> str:
        """Ярлык ФАЙЛА: ошибаемся в сторону БОЛЬШЕЙ поверхности (см. докстринг)."""
        kinds = {c.kind for c in self.calls}
        if SOURCE_DIR in kinds:
            return SOURCE_DIR
        if UNRESOLVED in kinds:
            return UNRESOLVED
        if STATE_DIR in kinds:
            return STATE_DIR
        return SANDBOX

    @property
    def source_dirs(self) -> list[str]:
        out: list[str] = []
        for c in self.calls:
            if c.kind == SOURCE_DIR and c.rel_dir and c.rel_dir not in out:
                out.append(c.rel_dir)
        return out


class _PathResolver:
    """Прослеживает выражение пути по привязкам ОДНОГО модуля.

    Привязкой считается `Name = <выражение>` на любом уровне (модуль, класс,
    функция). Контейнер привязкой НЕ является — тот же выбор, что у
    `_injected_clock` (§ «Время в тестах» правила доставки): считать «RHS
    содержит имя» происхождением значило бы оправдать ложную привязку.
    """

    def __init__(self, tree: ast.AST, self_rel: pathlib.PurePosixPath) -> None:
        self._bind: dict[str, ast.expr] = {}
        self._attr: dict[str, ast.expr] = {}     # `self.<имя> = …`
        self.aliases: set[str] = set()           # `import ast as _ast`
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        self._bind.setdefault(tgt.id, node.value)
                    elif (isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name)
                          and tgt.value.id in {"self", "cls"}):
                        self._attr.setdefault(tgt.attr, node.value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                if isinstance(node.target, ast.Name):
                    self._bind.setdefault(node.target.id, node.value)
                elif (isinstance(node.target, ast.Attribute) and isinstance(node.target.value, ast.Name)
                      and node.target.value.id in {"self", "cls"}):
                    self._attr.setdefault(node.target.attr, node.value)
            elif isinstance(node, ast.Import):
                # `import ast as _ast` — тот же не-путь под другим именем.
                # Без этого 20 зовов `_ast.walk`/`pyast.walk` числились
                # неразобранными путями, а путями они не были вовсе.
                for alias in node.names:
                    if alias.name in NON_PATH_RECEIVERS and alias.asname:
                        self.aliases.add(alias.asname)
            elif isinstance(node, ast.With):
                # `with tempfile.TemporaryDirectory() as td:` — настоящая привязка,
                # и без неё 69 имён (`td`, `tmp`, `d`) читались как неразобранные.
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name):
                        self._bind.setdefault(item.optional_vars.id, item.context_expr)
        self._self_rel = self_rel

    # ── вход ────────────────────────────────────────────────────────────────
    def bindings(self) -> dict[str, ast.expr]:
        """Привязки модуля — читает поиск помощников, своей копии у него нет."""
        return self._bind

    def as_rel_public(self, expr: ast.expr) -> pathlib.PurePosixPath | None:
        """Разбор пути БЕЗ классификации: нужен поиску помощников по `.py`."""
        return self._as_rel(expr, depth=0)

    def resolve(self, expr: ast.expr) -> tuple[str, str | None, str]:
        """→ (ярлык, repo-relative каталог или None, причина)."""
        try:
            rel = self._as_rel(expr, depth=0)
        except _Sandbox as exc:
            return SANDBOX, None, str(exc)
        except _Unresolved as exc:
            return UNRESOLVED, None, str(exc)
        if rel is None:
            return UNRESOLVED, None, f"путь не привязан к корню репозитория: {_unparse(expr)[:90]}"
        parts = rel.parts
        if parts and parts[0] in STATE_PREFIXES:
            return STATE_DIR, str(rel), f"каталог состояния (`{parts[0]}/`), доставкой кода не растёт"
        return SOURCE_DIR, str(rel), "каталог исходников репозитория"

    # ── рекурсивный разбор ──────────────────────────────────────────────────
    def _as_rel(self, expr: ast.expr, depth: int) -> pathlib.PurePosixPath | None:
        if depth > 12:
            raise _Unresolved("разбор не сошёлся за 12 шагов (циклическая привязка?)")

        # Признак одноразовой сцены спрашивается НА КАЖДОМ шаге, а не только у
        # исходного выражения: `with tempfile.TemporaryDirectory() as td` даёт
        # получателя `td`, и в ЕГО тексте маркера нет — маркер живёт в привязке.
        # Первая редакция спрашивала один раз и записала 130 таких зовов в
        # «НЕ РАЗОБРАН», то есть завысила вилку на разобранном материале.
        text = _unparse(expr)
        for marker in SANDBOX_MARKERS:
            if marker in text:
                raise _Sandbox(f"одноразовая сцена: в выражении «{marker}»")

        # ── `<левое> / "сегмент"` ──
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
            left = self._as_rel(expr.left, depth + 1)
            seg = _str_const(expr.right)
            if seg is None:
                raise _Unresolved(f"сегмент пути не литерал: {_unparse(expr.right)[:70]}")
            if left is None:
                raise _Unresolved(f"левая часть пути не привязана: {_unparse(expr.left)[:70]}")
            if seg.startswith("/"):
                raise _Unresolved(f"абсолютный сегмент вне репозитория: {seg}")
            return left / seg

        # ── имя: идём по привязке ──
        if isinstance(expr, ast.Name):
            if expr.id in PYTEST_TMP_FIXTURES:
                raise _Sandbox(f"фикстура pytest `{expr.id}` — одноразовый каталог харнесса")
            bound = self._bind.get(expr.id)
            if bound is None:
                raise _Unresolved(f"имя `{expr.id}` в модуле не привязано (параметр/фикстура/импорт)")
            return self._as_rel(bound, depth + 1)

        # ── `Path(__file__)` и его якоря ──
        if isinstance(expr, ast.Call):
            return self._call_as_rel(expr, depth)

        # ── `X.parent` / `X.parents[N]` / `self.<имя>` ──
        if isinstance(expr, ast.Attribute):
            if expr.attr == "parent":
                base = self._as_rel(expr.value, depth + 1)
                return _up(base, 1)
            if isinstance(expr.value, ast.Name) and expr.value.id in {"self", "cls"}:
                bound = self._attr.get(expr.attr)
                if bound is None:
                    raise _Unresolved(f"`self.{expr.attr}` в модуле не присваивается")
                return self._as_rel(bound, depth + 1)
            if expr.attr == "name":
                # `X.name` у `TemporaryDirectory()` ЕСТЬ путь каталога (а у
                # `Path` это строка-имя, перечислять которую нечем). Спрашиваем
                # ПОЛУЧАТЕЛЯ: сцена ответит `_Sandbox`, и это ОТВЕТ. 75 зовов
                # шли через эту форму и числились неразобранными.
                self._as_rel(expr.value, depth + 1)
                raise _Unresolved("`.name` у получателя, который сценой не оказался")
            raise _Unresolved(f"неизвестное свойство пути `.{expr.attr}`")

        if isinstance(expr, ast.Subscript):
            # `X.parents[N]`
            if isinstance(expr.value, ast.Attribute) and expr.value.attr == "parents":
                n = _int_const(expr.slice)
                if n is None:
                    raise _Unresolved(f"индекс `parents[...]` не литерал: {_unparse(expr.slice)[:50]}")
                base = self._as_rel(expr.value.value, depth + 1)
                return _up(base, n + 1)
            raise _Unresolved(f"индексация не по `parents`: {_unparse(expr)[:70]}")

        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            s = expr.value
            if s.startswith("/"):
                raise _Unresolved(f"абсолютный литерал вне репозитория: {s[:60]}")
            # Относительный литерал зависит от cwd прогона — это НЕ разобрано.
            raise _Unresolved(f"относительный литерал зависит от cwd: {s[:60]}")

        raise _Unresolved(f"форма выражения не разбирается: {type(expr).__name__}")

    def _call_as_rel(self, call: ast.Call, depth: int) -> pathlib.PurePosixPath | None:
        func = call.func
        # `X.resolve()` / `X.absolute()` — путь не меняют
        if isinstance(func, ast.Attribute) and func.attr in {"resolve", "absolute", "expanduser"}:
            return self._as_rel(func.value, depth + 1)
        # `os.path.dirname(X)` — то же, что `.parent`
        if isinstance(func, ast.Attribute) and func.attr == "dirname" and call.args:
            return _up(self._as_rel(call.args[0], depth + 1), 1)
        # `str(X)` / `os.fspath(X)` — обёртки, путь не меняют
        if isinstance(func, ast.Name) and func.id == "str" and len(call.args) == 1:
            return self._as_rel(call.args[0], depth + 1)
        if isinstance(func, ast.Attribute) and func.attr == "fspath" and len(call.args) == 1:
            return self._as_rel(call.args[0], depth + 1)
        # `X.joinpath("a", "b")`
        if isinstance(func, ast.Attribute) and func.attr == "joinpath":
            base = self._as_rel(func.value, depth + 1)
            if base is None:
                raise _Unresolved("joinpath: основание не привязано")
            for a in call.args:
                seg = _str_const(a)
                if seg is None:
                    raise _Unresolved(f"joinpath: сегмент не литерал: {_unparse(a)[:60]}")
                base = base / seg
            return base
        # `os.path.join(a, b)`
        if isinstance(func, ast.Attribute) and func.attr == "join":
            if not call.args:
                raise _Unresolved("join без аргументов")
            base = self._as_rel(call.args[0], depth + 1)
            if base is None:
                raise _Unresolved("join: основание не привязано")
            for a in call.args[1:]:
                seg = _str_const(a)
                if seg is None:
                    raise _Unresolved(f"join: сегмент не литерал: {_unparse(a)[:60]}")
                base = base / seg
            return base
        # `Path(...)` / `pathlib.Path(...)`
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name == "Path":
            if len(call.args) != 1:
                raise _Unresolved(f"Path() с {len(call.args)} аргументами не разбирается")
            arg = call.args[0]
            if isinstance(arg, ast.Name) and arg.id == "__file__":
                return self._self_rel           # САМ тест-файл, repo-relative
            return self._as_rel(arg, depth + 1)
        raise _Unresolved(f"зов не является построением пути: {_unparse(call)[:70]}")


class _Unresolved(RuntimeError):
    """Путь не разобран — несёт НАЗВАННУЮ причину."""


class _Sandbox(RuntimeError):
    """Путь разобран и ведёт в одноразовую сцену — это ОТВЕТ, а не отказ."""


def _up(base: pathlib.PurePosixPath | None, n: int) -> pathlib.PurePosixPath:
    if base is None:
        raise _Unresolved("подъём по дереву от непривязанного основания")
    cur = base
    for _ in range(n):
        if str(cur) in {".", ""}:
            raise _Unresolved("подъём выше корня репозитория")
        cur = cur.parent
    return cur


def _str_const(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    return None


def _int_const(expr: ast.expr) -> int | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int):
        return expr.value
    return None


def _unparse(expr: ast.AST) -> str:
    try:
        return ast.unparse(expr)
    except Exception:                                    # pragma: no cover - защита формы
        return f"<{type(expr).__name__}>"


# ════════════════════════════════════════════════════════════════════════════
#  ПОВЕРХНОСТЬ
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Surface:
    root: str
    tests_total: int
    entries: list[FileEntry]
    unmeasured_reason: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        out = {SOURCE_DIR: 0, STATE_DIR: 0, SANDBOX: 0, UNRESOLVED: 0}
        for e in self.entries:
            out[e.kind] += 1
        return out

    @property
    def subject(self) -> list[FileEntry]:
        return [e for e in self.entries if e.kind == SOURCE_DIR]

    @property
    def lost_known_members(self) -> dict[str, str]:
        """Известные члены класса, не попавшие в ПРЕДМЕТ. Непусто ⇒ форма врёт."""
        inside = {e.path for e in self.subject}
        return {p: why for p, why in KNOWN_MEMBERS.items() if p not in inside}

    @property
    def code(self) -> int:
        if self.unmeasured_reason:
            return 2
        # Форма, потерявшая известного члена, ОПРОВЕРГНУТА: печатать при ней
        # «предмет N» значило бы отвечать о дереве, которого перепись не видела.
        if self.lost_known_members:
            return 2
        return 1 if self.counts[UNRESOLVED] else 0


def measure_surface(root: pathlib.Path) -> Surface:
    """Статический замер поверхности. Каталог не прочитан ⇒ НЕ ИЗМЕРЕНО."""
    tests_dir = root / "spa_core" / "tests"
    if not tests_dir.is_dir():
        raise NotMeasured(f"каталог тестов не найден: {tests_dir}")
    try:
        files = sorted(tests_dir.glob("test_*.py"))
    except OSError as exc:
        raise NotMeasured(f"каталог тестов не прочитан: {exc}") from exc
    if not files:
        raise NotMeasured(f"ни одного `test_*.py` в {tests_dir} — пустота мерой не является")

    entries: list[FileEntry] = []
    helper_cache: dict[str, list[EnumCall]] = {}
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            entries.append(FileEntry(rel, [EnumCall(0, "-", UNRESOLVED, None, f"файл не прочитан: {exc}")]))
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            entries.append(FileEntry(rel, [EnumCall(exc.lineno or 0, "-", UNRESOLVED, None, f"не разбирается: {exc.msg}")]))
            continue

        resolver = _PathResolver(tree, TESTS_REL / path.name)
        calls = _enumerating_calls(tree, resolver)
        calls += _helper_calls(root, tree, resolver, cache=helper_cache)
        if calls:
            entries.append(FileEntry(rel, calls))

    return Surface(str(root), len(files), entries)


def _enumerating_calls(tree: ast.AST, resolver: "_PathResolver") -> list[EnumCall]:
        calls: list[EnumCall] = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            attr = node.func.attr
            if attr not in ENUMERATING:
                continue
            recv = node.func.value
            # Получатель СПРАШИВАЕТСЯ: `ast.walk(tree)` обходит синтаксическое
            # дерево и каталогов не перечисляет (см. NON_PATH_RECEIVERS выше).
            if isinstance(recv, ast.Name) and (recv.id in NON_PATH_RECEIVERS
                                               or recv.id in resolver.aliases):
                continue
            if (isinstance(recv, ast.Attribute) and isinstance(recv.value, ast.Name)
                    and recv.value.id in NON_PATH_RECEIVERS):
                continue
            # `os.listdir(X)` / `os.walk(X)` / `glob.glob(X)` — путь в аргументе;
            # `X.glob(...)` / `X.iterdir()` — путь в получателе.
            module_form = isinstance(recv, ast.Name) and recv.id in {"os", "glob", "os.path"}
            if attr in ARG_FORM and module_form:
                if not node.args:
                    continue
                target = node.args[0]
            elif attr in {"listdir", "scandir"} and node.args:
                target = node.args[0]
            else:
                target = recv
            kind, rel_dir, reason = resolver.resolve(target)
            calls.append(EnumCall(node.lineno, attr, kind, rel_dir, reason))
        return calls


# ════════════════════════════════════════════════════════════════════════════
#  ОДИН ХОП ЧЕРЕЗ ПОМОЩНИКА — иначе форма теряет 2 известных члена из 3
# ════════════════════════════════════════════════════════════════════════════
#
# Замер 23.11, и он ОПРОВЕРГАЕТ первую редакцию этого прибора: из трёх
# артефактов, у которых класс уже найден поимённо, в поверхность «тест САМ
# перечисляет каталог» попал РОВНО ОДИН (`test_adr_index_titles`). Два других
# перечисляют каталог ЧЕРЕЗ ПОМОЩНИКА:
#
#   `test_untiered_census.py`            → `scripts/audit_untiered_analytics.py`
#                                           `.modules_on_disk()`
#   `test_tracker_board_matches_cards.py`→ `scripts/build_tracker_board.py`
#
# Это ровно та граница, о которую спотыкается сторож претензии `injected-clock`
# (`.claude/rules/deployment.md` § девятая дверь, «Чего это НЕ закрывает»):
# разбор ОДНОГО файла не видит зова, ушедшего в общего помощника, и числит файл
# ВНЕ поверхности. Поверхность без хопа отвечает на вопрос «кто перечисляет
# каталог СВОИМИ руками», а не на вопрос класса.
#
# Хоп ОДИН намеренно: второй и третий потребовали бы графа зовов всего дерева, и
# ошибка пошла бы в сторону МЕНЬШЕЙ уверенности, а не большей поверхности.
# Сколько членов теряет граница одного хопа — НЕ ИЗМЕРЕНО, и это сказано вслух.

def _sys_path_dirs(root: pathlib.Path, tree: ast.AST,
                   resolver: "_PathResolver") -> list[pathlib.PurePosixPath]:
    """Каталоги репозитория, которые файл САМ кладёт на `sys.path`.

    Зачем отдельный вопрос. Ввоз помощника БАРЕ-ИМЕНЕМ (`from
    python_git_ref_provenance import main`) по тексту неотличим от ввоза чужого
    пакета: имя не несёт ни `scripts`, ни `spa_core`. Отличает их ровно одно —
    тот же файл ПОЛОЖИЛ каталог репозитория на путь поиска. Пока этот вопрос не
    задавался, поиск помощников видел только ПУНКТИРНУЮ форму ввоза, и
    `_repo_helpers` возвращал пустой список у члена класса, чей помощник лежит
    в `scripts/` (замер #1259: `test_python_git_ref_provenance.py` → `[]`).

    Путь разбирается ТЕМ ЖЕ разборщиком (`as_rel_public`) — своей копии правил
    здесь нет намеренно: разойдись она с разборщиком, поиск помощников принимал
    бы ровно те каталоги, из-за которых дверь понадобилась (ADR-220).
    """
    out: list[pathlib.PurePosixPath] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Получатель обязан быть `….path` — `sys.path.insert(...)` /
        # `sys.path.append(...)`. Спрашивается ПОЛУЧАТЕЛЬ, а не имя метода:
        # `insert`/`append` носят десятки списков, и совпадение по имени метода
        # мерой не является (урок ADR-1074, § «имя метода мерой НЕ является»).
        if not (isinstance(func, ast.Attribute)
                and func.attr in {"insert", "append"}
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "path"):
            continue
        for arg in node.args:
            try:
                rel = resolver.as_rel_public(arg)
            except (_Unresolved, _Sandbox):
                # Каталог не разобран либо ведёт в одноразовую сцену — это НЕ
                # каталог репозитория, и молчание здесь верно: вопрос задаётся
                # поимённо у каждого аргумента.
                continue
            if rel is None:
                continue
            if (root / rel).is_dir() and rel not in out:
                out.append(rel)
    return out


def _repo_helpers(root: pathlib.Path, tree: ast.AST,
                  resolver: "_PathResolver") -> list[pathlib.Path]:
    """Модули репозитория, которые файл ввозит или грузит ПО ПУТИ."""
    out: list[pathlib.Path] = []

    def _add(rel: str) -> None:
        p = root / rel
        if p.is_file() and p not in out:
            out.append(p)

    for node in ast.walk(tree):
        # `from spa_core.monitoring import card_acceptance` / `import scripts.x`
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            head = node.module.split(".")[0]
            if head in {"spa_core", "scripts"}:
                base = node.module.replace(".", "/")
                _add(f"{base}.py")
                for alias in node.names:
                    _add(f"{base}/{alias.name}.py")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in {"spa_core", "scripts"}:
                    _add(alias.name.replace(".", "/") + ".py")
    # Идиома этого дерева №2: `sys.path.insert(0, str(REPO / "scripts"))` плюс
    # ввоз БАРЕ-ИМЕНЕМ. Голова такого ввоза не называет каталог вовсе, поэтому
    # перечень `{"spa_core", "scripts"}` выше его не видит — а это ровно та
    # форма, которой ввезён помощник ЧЕТВЁРТОГО известного члена класса
    # (ADR-1112). Каталоги берутся у `_sys_path_dirs`, то есть у ТОГО ЖЕ файла:
    # «кто-то когда-то положил `scripts` на путь» основанием не является.
    on_path = _sys_path_dirs(root, tree, resolver)
    if on_path:
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods.append(node.module)
            elif isinstance(node, ast.Import):
                mods.extend(alias.name for alias in node.names)
            for mod in mods:
                if mod.split(".")[0] in {"spa_core", "scripts"}:
                    continue        # пунктирную форму разобрала ветка выше
                for base in on_path:
                    _add(f"{base}/{mod.replace('.', '/')}.py")

    # Идиома этого дерева: `TOOL = REPO_ROOT / "scripts" / "foo.py"` + загрузка
    # по файлу (`scripts/` в `sys.path` не ставят). Путь разбирается ТЕМ ЖЕ
    # разборщиком — своей копии правил здесь нет.
    for expr in list(resolver.bindings().values()):
        try:
            rel = resolver.as_rel_public(expr)
        except (_Unresolved, _Sandbox):
            continue
        if rel is not None and str(rel).endswith(".py"):
            _add(str(rel))
    return out


def _helper_calls(root: pathlib.Path, tree: ast.AST, resolver: "_PathResolver",
                  cache: dict[str, list[EnumCall]]) -> list[EnumCall]:
    out: list[EnumCall] = []
    for helper in _repo_helpers(root, tree, resolver):
        key = helper.as_posix()
        if key not in cache:
            try:
                htree = ast.parse(helper.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                cache[key] = [EnumCall(0, "-", UNRESOLVED, None,
                                       f"помощник {helper.name} не разобран: {exc}")]
            else:
                hres = _PathResolver(htree, pathlib.PurePosixPath(
                    helper.relative_to(root).as_posix()))
                cache[key] = _enumerating_calls(htree, hres)
        hrel = helper.relative_to(root).as_posix()
        for call in cache[key]:
            if call.kind == SOURCE_DIR:
                out.append(EnumCall(call.lineno, f"{call.attr}@{helper.name}",
                                    SOURCE_DIR, call.rel_dir,
                                    f"через помощника {hrel}"))
                continue
            if call.kind != UNRESOLVED:
                continue
            # Помощник перечисляет каталог, ПОЛУЧЕННЫЙ аргументом (`tracker.glob`),
            # то есть каталог назначает ВЫЗЫВАЮЩИЙ. Если сам тест ИМЕНУЕТ каталог
            # исходников своей привязкой, перечисляется он. Без этой половины
            # хопа форма теряет `test_tracker_board_matches_cards` (ADR-1060):
            # `TRACKER_DIR = REPO_ROOT / "nimbalyst-local" / "tracker"` стои́т в
            # тесте, а `glob` — в сборщике доски.
            for rel_dir in _named_source_dirs(root, resolver):
                out.append(EnumCall(call.lineno, f"{call.attr}@{helper.name}",
                                    SOURCE_DIR, rel_dir,
                                    f"каталог НАЗВАН в тесте, перечисляет {hrel} по аргументу"))
    return out


def _named_source_dirs(root: pathlib.Path, resolver: "_PathResolver") -> list[str]:
    """Каталоги ИСХОДНИКОВ, которые файл именует своими привязками.

    Ошибка идёт в сторону БОЛЬШЕЙ поверхности нарочно (см. докстринг модуля):
    названный каталог может и не дойти до помощника, и тогда член предмета
    окажется лишним кандидатом. Обратная ошибка объявила бы работу законченной.
    """
    out: list[str] = []
    for expr in resolver.bindings().values():
        try:
            rel = resolver.as_rel_public(expr)
        except (_Unresolved, _Sandbox):
            continue
        if rel is None:
            continue
        parts = rel.parts
        # ── КОРЕНЬ РЕПОЗИТОРИЯ (пустые `parts`) ЕСТЬ каталог исходников ──────
        # До #1259 здесь стоял отказ `not parts`, и он отвечал на вопрос «назван
        # ли ПОДКАТАЛОГ», а не на вопрос класса «может ли моя доставка вырастить
        # этот набор». Корень — МАКСИМАЛЬНЫЙ каталог исходников: сторож, чей
        # помощник перечисляет `REPO.rglob("*.py")`, краснеет от ЛЮБОГО нового
        # `*.py` в дереве, то есть является самым сильным членом класса, а не
        # исключением из него. Отбрасывая его, мерка ошибалась в сторону
        # «чисто» — ровно та сторона, против которой написан весь прибор.
        # Замер #1259: ЧЕТВЁРТЫЙ известный член (ADR-1112) привязывает
        # `REPO = Path(__file__).resolve().parents[2]`, то есть именно корень.
        if parts and parts[0] in STATE_PREFIXES:
            continue
        if (root / rel).is_dir() and str(rel) not in out:
            out.append(str(rel))
    return out


# ════════════════════════════════════════════════════════════════════════════
#  ДИФФЕРЕНЦИАЛ — новый публичный файл в САМ перечисляемый каталог
# ════════════════════════════════════════════════════════════════════════════

PLANTED_STEM = "zz_derived_artifact_census_probe"

# ─── РАСШИРЕНИЕ ПОДКЛАДЫВАЕМОГО ФАЙЛА ЕСТЬ ЧАСТЬ МЕРКИ ──────────────────────
# Замер 23.11: прогон, подкладывавший ТОЛЬКО `.py`, нашёл 1 известного члена из
# 3. Два промаха объясняются НЕ поверхностью, а расширением: доска очереди
# (ADR-1060) перечисляет `tracker.glob("*.md")`, реестр решений (ADR-889) —
# тоже markdown. Файл `.py` их набор не растит, и «не предмет» был ответом про
# расширение зонда, а не про сторожа. Поэтому в каждый каталог кладётся по файлу
# на КАЖДОЕ расширение, и вердикт берётся по ХУДШЕМУ исходу: один зонд нашёл
# предмет ⇒ предмет.
PLANTED_SUFFIXES = (".py", ".md", ".json")

PLANTED_PY = '''"""Подложен прибором `scripts/derived_artifact_census.py` (заказ G1061 п. 2).

Публичный модуль-пустышка: его задача — вырастить НАБОР файлов каталога на один,
чтобы стало видно, чей вердикт зависит от набора. Файл снимается прибором же.
"""


def declared_probe_marker() -> str:
    """Публичное имя: модуль без него читался бы как приватный."""
    return "derived-artifact-census-probe"
'''

PLANTED_MD = """---
trackerStatus:
  type: inbox
title: "Подложен прибором scripts/derived_artifact_census.py (заказ G1061 п. 2)"
status: new
---

Файл-пустышка: растит НАБОР файлов каталога на один, чтобы стало видно, чей
вердикт зависит от набора. Снимается прибором же (`--clean-planted`).
"""

PLANTED_JSON = """{
  \"planted_by\": \"scripts/derived_artifact_census.py\",
  \"why\": \"растит НАБОР файлов каталога на один; снимается прибором же\"
}
"""

PLANTED_BODY = {".py": PLANTED_PY, ".md": PLANTED_MD, ".json": PLANTED_JSON}

# ─── СОДЕРЖИМОЕ ЗОНДА ЕСТЬ ЧАСТЬ МЕРКИ, как и его РАСШИРЕНИЕ ────────────────
# Цикл #1218 уже выучил половину этого урока: прогон, подкладывавший только
# `.py`, нашёл 1 известного члена из 3, потому что доска и реестр перечисляют
# markdown (см. PLANTED_SUFFIXES). Замер #1259 нашёл ВТОРУЮ половину, и она
# глубже: тела зондов выше ИНЕРТНЫ — они растят ЧИСЛО файлов каталога и не
# несут ничего, о чём сторож мог бы судить. Сторож, чей вердикт решает
# СОДЕРЖИМОЕ набора, инертным зондом неотличим от «не предмета».
#
# Замер на ЧЕТВЁРТОМ известном члене (ADR-1112, храповик провенанса чтений
# `origin/<ветка>`), дерево `fbb0fa45a`, прибор `python_git_ref_provenance.py`:
#
#   без зонда                      предмет 80
#   ИНЕРТНЫЙ `.py` в корне         предмет 80   ← вердикт не сдвинулся
#   `.py` с `git show origin/main` предмет 81   ← сдвинулся
#
# Поэтому «не предмет» у такого сторожа есть ответ О ЗОНДЕ, а не о стороже, и
# граница ПЕЧАТАЕТСЯ строкой отчёта. Сделать зонд универсально содержательным
# нельзя: содержимое пришлось бы выдумывать под предмет КАЖДОГО сторожа, то
# есть мерка стала бы прозой. Названная граница честнее выдуманного зонда.
PLANTED_INERT = ("зонд растит ЧИСЛО файлов и СОДЕРЖИМОГО не несёт — сторож, "
                 "чей вердикт решает содержимое набора, им НЕ разрешается; "
                 "замер #1259 на ADR-1112: инертный зонд 80→80, содержательный 80→81")


@dataclass
class DiffEntry:
    path: str
    enumerated_dir: str
    kind: str
    before: str = ""
    after: str = ""
    reason: str = ""


@dataclass
class Differential:
    root: str
    entries: list[DiffEntry]
    leftovers: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {SUBJECT: 0, SET_DEPENDENT_GREEN: 0, NOT_SUBJECT: 0,
               ALREADY_RED: 0, DIFF_UNMEASURED: 0}
        for e in self.entries:
            out[e.kind] += 1
        return out

    @property
    def code(self) -> int:
        if self.leftovers:
            return 2
        if self.counts[DIFF_UNMEASURED]:
            return 2
        return 1 if self.counts[SUBJECT] else 0


def _verdict(root: pathlib.Path, rel_test: str, timeout: int) -> tuple[str, str]:
    """Вердикт ОДНОГО тест-файла: («passed=N,…» либо `unmeasured`, подробность).

    Переход в `skipped` меряется наравне с красным (урок #465): такой тест не
    краснеет и не проходит — он ИСЧЕЗАЕТ, и глазами это читается как порядок.
    """
    env = dict(os.environ, SPA_ENV="ci", PYTHONHASHSEED="0")
    cmd = [sys.executable, "-m", "pytest", rel_test, "-q", "--tb=no",
           "-p", "no:randomly", "--rootdir", str(root)]
    try:
        proc = subprocess.run(cmd, cwd=str(root), env=env, timeout=timeout,
                              capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return "unmeasured", f"прогон не дошёл до вердикта за {timeout} с"
    except OSError as exc:
        return "unmeasured", f"pytest не запущен: {exc}"
    out = proc.stdout + proc.stderr
    tail = [ln for ln in out.splitlines() if ln.strip()]
    summary = next((ln for ln in reversed(tail)
                    if (" passed" in ln or " failed" in ln or " error" in ln
                        or " skipped" in ln or "no tests ran" in ln)), "")
    if not summary:
        return "unmeasured", f"сводки pytest в выводе нет (код {proc.returncode})"
    # Состав вердикта, а не код возврата: код 1 бывает и у `error`, и у `failed`.
    parts = []
    for word in ("failed", "error", "errors", "passed", "skipped", "xfailed", "deselected"):
        import re
        m = re.search(rf"(\d+) {word}\b", summary)
        if m:
            parts.append(f"{word}={m.group(1)}")
    if "no tests ran" in summary:
        parts.append("collected=0")
    return (",".join(parts) or summary.strip()), summary.strip()


def _counts_of(verdict: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in verdict.split(","):
        if "=" in part:
            k, _, v = part.partition("=")
            try:
                out[k] = int(v)
            except ValueError:
                pass
    return out


def _classify(before: str, after: str) -> tuple[str, str]:
    """Ось вердикта: «зелёный стал НЕ зелёным» — и ТОЛЬКО это есть предмет.

    Первая редакция сличала СТРОКУ состава и записала в предмет три файла, у
    которых выросло только число `passed` (160→165, 127→129, 2875→2876). Это
    параметризованные по НАБОРУ сторожа, которые новый файл УВИДЕЛИ и приняли —
    то есть ровно противоположность класса. Мерка «строка изменилась» отвечала
    на вопрос «зависит ли вердикт от набора», а предмет класса — «КРАСНЕЕТ ли он
    от роста набора». Зависимость от набора сохранена отдельным ярлыком, потому
    что она сама по себе сведение полезное, а не шум.
    """
    b, a = _counts_of(before), _counts_of(after)
    bad_before = b.get("failed", 0) + b.get("error", 0) + b.get("errors", 0)
    bad_after = a.get("failed", 0) + a.get("error", 0) + a.get("errors", 0)
    # «Зелёный стал НЕ зелёным» требует, чтобы ДО он был ЗЕЛЁНЫМ. Первая редакция
    # спрашивала только `bad_after` и записала в предмет ПЯТЬ файлов, красных в
    # ОБА прогона: они зелёными не были, и подложенный файл их вердикта не менял
    # ни на байт (`failed=1,passed=47` → `failed=1,passed=47`). Красное ДО меня
    # членством в классе не является — это отдельный род, и он НАЗВАН.
    if bad_before:
        return ALREADY_RED, (f"красен ДО подкладывания (failed/error {bad_before}) — зелёным "
                             "не был, о зависимости от набора этот прогон не говорит ничего")
    if bad_after:
        return SUBJECT, (f"зелёный стал НЕ зелёным: failed/error {bad_after} — "
                         "сторож краснеет от роста набора своего каталога")
    if a.get("skipped", 0) > b.get("skipped", 0):
        return SUBJECT, ("вердикт ИСЧЕЗ в `skipped` (урок #465): тест не краснеет и не "
                         "проходит, и глазами это читается как порядок")
    if a.get("passed", 0) < b.get("passed", 0):
        return SUBJECT, "число пройденных УПАЛО: часть проверок перестала собираться"
    if before != after:
        return SET_DEPENDENT_GREEN, ("состав вырос и остался зелёным: сторож параметризован "
                                     "по набору и новый файл ПРИНЯЛ")
    return NOT_SUBJECT, "вердикт тот же"


def measure_differential(root: pathlib.Path, surface: Surface, *,
                         limit: int | None = None, timeout: int = 300,
                         only: list[str] | None = None) -> Differential:
    """Гоняет предмет поверхности ДВАЖДЫ: как есть и с подложенным файлом."""
    subject = surface.subject
    if only:
        wanted = set(only)
        subject = [e for e in subject if e.path in wanted or pathlib.PurePosixPath(e.path).name in wanted]
    if limit is not None:
        subject = subject[:limit]

    entries: list[DiffEntry] = []
    leftovers: list[str] = []
    total = len(subject)
    for i, entry in enumerate(subject, 1):
        # Долгий прогон ОБЯЗАН быть виден (`.claude/rules/deployment.md`
        # § «ОКНО МУТАЦИОННОГО ПРИБОРА» п. 8): полностью буферизованный вывод
        # делает «работает» и «умер» неразличимыми, и ровно эта неразличимость
        # пригласила неверное действие в аварии #906.
        print(f"[прибор] {i}/{total} {entry.path}", file=sys.stderr, flush=True)
        for rel_dir in entry.source_dirs:
            target_dir = root / rel_dir
            if not target_dir.is_dir():
                entries.append(DiffEntry(entry.path, rel_dir, DIFF_UNMEASURED,
                                         reason=f"перечисляемый каталог не существует в дереве: {rel_dir}"))
                continue
            before, before_line = _verdict(root, entry.path, timeout)
            if before == "unmeasured":
                entries.append(DiffEntry(entry.path, rel_dir, DIFF_UNMEASURED,
                                         before=before, reason=f"первый прогон: {before_line}"))
                continue
            existing = [p for p in (target_dir / f"{PLANTED_STEM}{sfx}"
                                    for sfx in PLANTED_SUFFIXES) if p.exists()]
            if existing:
                # Измеренный случай (цикл #1218): убитый первый прогон оставил
                # подложенный файл в `landing/src/pages/admin`, и ВТОРОЙ прогон
                # честно отказал вместо того, чтобы судить о дереве с чужими
                # байтами. Это та же форма, что § «ОКНО МУТАЦИОННОГО ПРИБОРА»:
                # возврат живёт в `finally` и обеспечен для исключения, но НЕ для
                # смерти процесса. Несущая половина — запись на диске, и она ниже.
                entries.append(DiffEntry(entry.path, rel_dir, DIFF_UNMEASURED, before=before,
                                         reason="подкладываемое имя уже занято: "
                                                + ", ".join(p.name for p in existing)
                                                + " — наследство убитого прогона; снять "
                                                  "`--clean-planted` и перемерить"))
                continue
            # Один зонд на КАЖДОЕ расширение: вердикт берётся по ХУДШЕМУ исходу,
            # потому что сторож ключуется на своё расширение (см. PLANTED_SUFFIXES).
            probes: list[tuple[str, str, str]] = []
            for sfx in PLANTED_SUFFIXES:
                planted = target_dir / f"{PLANTED_STEM}{sfx}"
                try:
                    planted.write_text(PLANTED_BODY[sfx], encoding="utf-8")
                    after, after_line = _verdict(root, entry.path, timeout)
                finally:
                    try:
                        planted.unlink()
                    except OSError as exc:
                        leftovers.append(f"{planted}: {exc}")
                    for pyc in (target_dir / "__pycache__").glob(f"{PLANTED_STEM}.*"):
                        try:
                            pyc.unlink()
                        except OSError:
                            pass
                probes.append((sfx, after, after_line))

            unmeasured = [pr for pr in probes if pr[1] == "unmeasured"]
            graded = [(sfx, after, line) + _classify(before, after)
                      for sfx, after, line in probes if after != "unmeasured"]
            worst = next((g for g in graded if g[3] == SUBJECT), None) \
                or next((g for g in graded if g[3] == SET_DEPENDENT_GREEN), None) \
                or next((g for g in graded if g[3] == ALREADY_RED), None) \
                or (graded[0] if graded else None)
            if worst is None:
                entries.append(DiffEntry(entry.path, rel_dir, DIFF_UNMEASURED, before=before,
                                         reason="ни один зонд не дошёл до вердикта: "
                                                + "; ".join(f"{s}: {l}" for s, _, l in probes)))
                continue
            sfx, after, _line, kind, why = worst
            if unmeasured:
                why += (" · зонды БЕЗ вердикта: "
                        + ", ".join(pr[0] for pr in unmeasured))
            entries.append(DiffEntry(entry.path, rel_dir, kind, before=before, after=after,
                                     reason=f"[зонд {sfx}] {why}"))
    return Differential(str(root), entries, leftovers)


# ════════════════════════════════════════════════════════════════════════════
#  ПЕЧАТЬ
# ════════════════════════════════════════════════════════════════════════════

def render_surface(s: Surface, *, names: bool = False) -> str:
    c = s.counts
    lines = [
        f"ПОВЕРХНОСТЬ класса «производный артефакт уехал без перемера» (дерево {s.root}):",
        f"  `spa_core/tests/test_*.py` всего: {s.tests_total}",
        f"  из них несут перечисляющий зов: {len(s.entries)}",
        f"  ├─ ПРЕДМЕТ (каталог ИСХОДНИКОВ): {c[SOURCE_DIR]}",
        f"  ├─ каталог состояния `data/`:     {c[STATE_DIR]}",
        f"  ├─ одноразовая сцена:             {c[SANDBOX]}",
        f"  └─ НЕ РАЗОБРАН (третий исход):    {c[UNRESOLVED]}",
    ]
    if c[UNRESOLVED]:
        lines.append("  ⚠️ НЕ РАЗОБРАННОЕ нулём не считается: население предмета есть ВИЛКА")
        lines.append(f"     {c[SOURCE_DIR]} … {c[SOURCE_DIR] + c[UNRESOLVED]}")
    lost = s.lost_known_members
    if lost:
        lines.append("  ⛔ ФОРМА ОПРОВЕРГНУТА: известный член класса ВНЕ предмета —")
        for p, why in lost.items():
            lines.append(f"       {p} ({why})")
        lines.append("     число предмета НЕ ПЕЧАТАЕТСЯ как население класса (код 2)")
    else:
        lines.append(f"  ✅ все {len(KNOWN_MEMBERS)} известных члена класса ВНУТРИ предмета "
                     "(положительный контроль поверхности)")
    if names:
        lines.append("")
        lines.append("ПРЕДМЕТ ПОИМЁННО:")
        for e in s.subject:
            lines.append(f"  • {e.path} → {', '.join(e.source_dirs)}")
    return "\n".join(lines)


def render_differential(d: Differential) -> str:
    c = d.counts
    lines = [
        f"ДИФФЕРЕНЦИАЛ (дерево {d.root}): подложен новый публичный файл в САМ перечисляемый каталог",
        f"  ПРЕДМЕТ КЛАССА (зелёный стал НЕ зелёным): {c[SUBJECT]}",
        f"  зависит от набора, но ЗЕЛЕН:        {c[SET_DEPENDENT_GREEN]}",
        f"  КРАСЕН ДО подкладывания:            {c[ALREADY_RED]}",
        f"  не предмет (вердикт тот же):       {c[NOT_SUBJECT]}",
        f"  НЕ ИЗМЕРЕНО:                       {c[DIFF_UNMEASURED]}",
        # ── ГРАНИЦА ДИФФЕРЕНЦИАЛА ПЕЧАТАЕТСЯ, а не живёт в прозе ────────────
        # Иначе читатель примет «не предмет» за ответ о классе там, где зонд
        # ответить не способен ПО ПОСТРОЕНИЮ (замер #1259, см. PLANTED_INERT).
        f"  ⚠️ ЗОНД ИНЕРТЕН: {PLANTED_INERT}",
    ]
    for e in d.entries:
        if e.kind == SUBJECT:
            lines.append(f"  🔴 {e.path} ← {e.enumerated_dir}")
            lines.append(f"       было: {e.before}  →  стало: {e.after}")
        elif e.kind == DIFF_UNMEASURED:
            lines.append(f"  ⚠️ НЕ ИЗМЕРЕНО {e.path} ← {e.enumerated_dir}: {e.reason}")
    if d.leftovers:
        lines.append("  ⛔ ПОДЛОЖЕННЫЙ ФАЙЛ НЕ СНЯТ — дерево грязное:")
        for item in d.leftovers:
            lines.append(f"       {item}")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════

def clean_planted(root: pathlib.Path) -> list[str]:
    """Снять подложенные файлы, оставшиеся от УБИТОГО прогона.

    `finally` обеспечен для исключения и НЕ обеспечен для `SIGKILL` — поэтому
    уборка есть ОТДЕЛЬНОЕ действие, а не следствие прогона, и она ПЕЧАТАЕТ, что
    сняла. «Ничего не нашлось» означает «дерево чисто», а не «про дерево ничего
    не известно»: имя подкладываемого файла одно и известно по построению.
    """
    removed: list[str] = []
    for path in root.rglob(f"{PLANTED_STEM}.*"):
        try:
            path.unlink()
            removed.append(path.relative_to(root).as_posix())
        except OSError as exc:
            removed.append(f"НЕ СНЯТ {path}: {exc}")
    return removed


def _resolve_root(named: str | None) -> pathlib.Path:
    """Дерево — ВХОД. Умолчание ПЕЧАТАЕТСЯ, нечитаемое названное даёт отказ."""
    if named:
        root = pathlib.Path(named).expanduser()
        if not (root / "spa_core").is_dir():
            raise NotMeasured(f"названное дерево не похоже на репозиторий SPA: {root}")
        return root.resolve()
    root = pathlib.Path(__file__).resolve().parents[1]
    print(f"[дерево] --repo-root НЕ НАЗВАН, беру дерево прибора: {root}", file=sys.stderr)
    return root


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", help="дерево, которое мерить (ОДНОРАЗОВОЕ для --differential)")
    ap.add_argument("--surface", action="store_true", help="только статическая поверхность")
    ap.add_argument("--differential", action="store_true", help="прогнать предмет дважды")
    ap.add_argument("--names", action="store_true", help="печатать предмет поимённо")
    ap.add_argument("--limit", type=int, help="взять первые N членов предмета (для такта)")
    ap.add_argument("--only", nargs="*", help="мерить только названные файлы предмета")
    ap.add_argument("--timeout", type=int, default=300, help="предел одного прогона, с")
    ap.add_argument("--clean-planted", action="store_true",
                    help="снять подложенные файлы, оставшиеся от убитого прогона")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not args.surface and not args.differential and not args.clean_planted:
        args.surface = True

    if args.clean_planted:
        try:
            root = _resolve_root(args.repo_root)
        except NotMeasured as exc:
            print(f"⚠️ НЕ ИЗМЕРЕНО: {exc}")
            return 2
        removed = clean_planted(root)
        print(f"снято подложенных файлов: {len(removed)}")
        for item in removed:
            print(f"  {item}")
        return 1 if any(s.startswith("НЕ СНЯТ") for s in removed) else 0

    try:
        root = _resolve_root(args.repo_root)
        surface = measure_surface(root)
    except NotMeasured as exc:
        if args.json:
            print(json.dumps({"code": 2, "unmeasured_reason": str(exc)}, ensure_ascii=False))
        else:
            print(f"⚠️ НЕ ИЗМЕРЕНО: {exc}")
        return 2

    diff: Differential | None = None
    if args.differential:
        diff = measure_differential(root, surface, limit=args.limit,
                                    timeout=args.timeout, only=args.only)

    if args.json:
        doc = {
            "root": surface.root,
            "tests_total": surface.tests_total,
            "surface": len(surface.entries),
            "counts": surface.counts,
            "code": surface.code,
            "entries": [asdict(e) | {"kind": e.kind, "source_dirs": e.source_dirs}
                        for e in surface.entries],
        }
        if diff is not None:
            doc["differential"] = {"counts": diff.counts, "code": diff.code,
                                   "leftovers": diff.leftovers,
                                   "entries": [asdict(e) for e in diff.entries]}
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(render_surface(surface, names=args.names))
        if diff is not None:
            print()
            print(render_differential(diff))

    code = surface.code
    if diff is not None:
        code = max(code, diff.code)
    return code


if __name__ == "__main__":
    sys.exit(main())
