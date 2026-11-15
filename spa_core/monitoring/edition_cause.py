#!/usr/bin/env python3
"""ПРИЧИНА расхождения перемера: набор сдвинула РЕДАКЦИЯ или сдвинулись ДАННЫЕ.

:mod:`spa_core.monitoring.artifact_edition` (ADR-1020/1021) отвечает «тот ли КОД
вынес напечатанную находку, который лежит в дереве сегодня», и ответ у него
ДАТНЫЙ. :mod:`spa_core.monitoring.edition_remeasure` (ADR-1022) отвечает «ЖИВЁТ
ли напечатанная находка на сегодняшнем производителе», и ответ у него — набор
находок. Замер #1160: из восемнадцати членов класса набор РАЗОШЁЛСЯ у восьми.

Ни один из двух приборов не говорит, ПОЧЕМУ он разошёлся, а причин ровно две и
они требуют ПРОТИВОПОЛОЖНЫХ действий:

* сдвинулась **РЕДАКЦИЯ** — находку убрала (или создала) ПРАВКА производителя.
  Тогда «починка приехала» перестаёт быть надеждой: напечатанная строка мертва
  потому, что код больше так не считает;
* сдвинулись **ДАННЫЕ** — тот же самый прежний код на сегодняшних данных даёт
  уже другой набор. Тогда о починке не сказано НИЧЕГО: находка ушла сама и
  вернётся с данными.

Разделяет их ровно один замер — **прогон ПРЕЖНЕЙ редакции производителя на
СЕГОДНЯШНИХ данных** (заказ G1011 п. 1), и до этого модуля он не делался ни
разу: ADR-1022 § 10 называет его отдельным замером и в своём предмете
отказывается от него прямо.

## Три набора, и почему вопрос решается ТОЛЬКО третьим

| набор | чей код | чьи данные | откуда берётся |
|---|---|---|---|
| ``A`` | ПРЕЖНИЙ | прежние | напечатанный артефакт ``<прод>/data/<имя>.json`` |
| ``B`` | сегодняшний | сегодняшние | перемер ADR-1022 (:func:`edition_remeasure.remeasure_one`) |
| ``C`` | **ПРЕЖНИЙ** | **сегодняшние** | ЭТОТ модуль |

``A != B`` — это и есть расхождение, измеренное #1160. Третий набор разводит его
причины: ``C == A`` значит, что данные набор не двигают, и весь сдвиг произвела
РЕДАКЦИЯ; ``C == B`` — наоборот, прежний код на новых данных УЖЕ даёт сегодняшний
ответ, то есть сдвиг произвели ДАННЫЕ.

## Исходов ЧЕТЫРЕ, а не три, и четвёртый найден замером, а не придуман

Заказ G1011 п. 1 назвал три («РЕДАКЦИЯ · ДАННЫЕ · не измеряется с причиной»), и
в этом перечне нет места состоянию ``C != A and C != B`` — а оно наблюдаемо и
осмысленно: обе оси двигают набор, и приписать сдвиг одной из них было бы
ВЫДУМКОЙ. Поэтому объявлено :data:`BOTH`. Пятое значение :data:`NO_DIVERGENCE` —
это «измерено и равно нулю» (инв. #17): набор не расходился, и причины
расхождения нет не потому, что её не нашли.

## Что этот модуль НЕ утверждает (граница ОБЪЯВЛЕНА, а не умолчана)

Прежней редакцией подменяется **ОДИН файл** — тот, который объявлен
производителем артефакта у офиса (``consume_office_reports._PRODUCER``). Если за
то же время правился ПОМОЩНИК, которого производитель импортирует, то набор
``C`` снят на смеси «прежний производитель + сегодняшний помощник», и ось
«редакция» у такого члена НЕПОЛНА. Молчать об этом нельзя — вердикт остаётся,
но несёт :attr:`Outcome.changed_helpers` (имена, не число), и печать считает
таких членов ОТДЕЛЬНО. Подменять ещё и помощников значило бы собрать дерево,
которого не было ни одного дня: прежний помощник рядом с сегодняшним соседом —
это третья редакция, а не прежняя.

Причину не угадывает и не чинит: ни одного производителя этот модуль не правит.

## Почему подмена идёт в ПЕСОЧНИЦУ, и почему песочница проверяется ДВАЖДЫ

Модуль пишет чужие байты в дерево — ровно та форма, которой
``.claude/rules/deployment.md`` § «ОКНО МУТАЦИОННОГО ПРИБОРА» и § «БАЙТЫ, КОТОРЫЕ
НЕ ЯВЛЯЮТСЯ КОДОМ» обязаны своим появлением (авария #1000: на ``main`` уехал
``card_acceptance.py``, переписанный тестом). Поэтому:

* корень песочницы в ПРОД-дереве — отказ (:func:`edition_remeasure.refuse_prod_root`,
  дом величины один и он не здесь);
* корень песочницы, совпавший с ДЕРЕВОМ ДОСТАВКИ этого модуля, — отказ
  (:func:`refuse_delivery_tree`). Прежняя редакция, забытая в дереве доставки,
  уехала бы на ``main`` как код — и выглядела бы кодом;
* байты производителя снимаются ДО подмены и возвращаются ПОСЛЕ прогона, а
  возврат **СВЕРЯЕТСЯ побайтно**. Не сошлось ⇒ :data:`UNMEASURED` с этой
  причиной: песочница с чужим производителем внутри соврёт следующему замеру,
  и молчать об этом хуже, чем не измерить.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring import artifact_edition as ae  # noqa: E402
from spa_core.monitoring import edition_remeasure as er  # noqa: E402

#: Набор сдвинула ПРАВКА производителя: прежний код на сегодняшних данных даёт
#: РОВНО напечатанное.
EDITION = "edition"
#: Набор сдвинули ДАННЫЕ: прежний код на сегодняшних данных даёт РОВНО то же,
#: что сегодняшний, — о правке не сказано ничего.
DATA = "data"
#: Двигают ОБЕ оси: третий набор не совпал ни с напечатанным, ни с сегодняшним.
BOTH = "both"
#: Измерено и равно нулю: набор не расходился, объяснять нечего.
NO_DIVERGENCE = "no_divergence"
#: Замера нет, с названной причиной.
UNMEASURED = "unmeasured"

#: Роды, у которых ось НАЗВАНА. Остальное — либо пустой предмет, либо третий исход.
NAMED = (EDITION, DATA, BOTH)

#: Всё, из чего состоит ЧИСЛО внутри текста находки. Нужно ровно для одного
#: вопроса: расхождение наборов — это «находка пришла/ушла» или «та же находка с
#: другими числами»? Вопрос не косметический. Ключ находки (ADR-1022
#: :func:`edition_remeasure.finding_keys`) берёт текст ЦЕЛИКОМ и обрезать его
#: НЕЛЬЗЯ — иначе две находки, чьи первые сто символов совпали, склеились бы в
#: одну. Но живые производители печатают в текст суммы (`$1,710,980.85`), и
#: тогда ЛЮБОЙ сдвиг доллара делает набор «другим», а род `BOTH` оказывается
#: свойством КЛЮЧА, а не осей. Поэтому ось числовой слепоты объявлена ОТДЕЛЬНО и
#: НЕ подменяет ключ: она уточняет вердикт, а не заменяет его.
NUMERIC = re.compile(r"[\d.,%$\u00a0  ]+")


def numeric_blind(keys: Sequence[str]) -> tuple[str, ...]:
    """Ключи с затёртыми числами. Только для оси уточнения, НЕ для вердикта."""
    return tuple(sorted(NUMERIC.sub("#", k) for k in keys))


@dataclass(frozen=True)
class Outcome:
    """Исход по ОДНОМУ члену класса. ``reason`` обязателен у :data:`UNMEASURED`."""

    kind: str
    artifact: str
    producer: Optional[str] = None
    prior_commit: Optional[str] = None
    prior_committed_at: Optional[str] = None
    printed: Optional[int] = None
    today: Optional[int] = None
    prior_on_today: Optional[int] = None
    #: Находки, которые есть в НАПЕЧАТАННОМ наборе и которых НЕТ у прежней
    #: редакции на сегодняшних данных (и наоборот). Числа без имён повторили бы
    #: ровно тот дефект, которому обязан ADR-1021: печать считала 18, называла 12.
    #: У рода `BOTH` это ЕДИНСТВЕННОЕ, чем он отличим от совпадения размеров —
    #: `7 → 7 → 7` у `cio_architecture_constraints` суть ТРИ РАЗНЫХ набора.
    prior_gone: tuple[str, ...] = ()
    prior_arrived: tuple[str, ...] = ()
    #: То же расхождение, но между НАПЕЧАТАННЫМ и СЕГОДНЯШНИМ набором (его считает
    #: дверь ADR-1022, лишнего прогона здесь нет). Без него прибор называет ось, но
    #: не говорит, КАКАЯ находка умерла, — и на самый дорогой вопрос класса
    #: («жива ли CRITICAL об инварианте #3») приходилось бы отвечать вторым
    #: инструментом.
    today_gone: tuple[str, ...] = ()
    today_arrived: tuple[str, ...] = ()
    #: Наборы разошлись, но после затирания ЧИСЕЛ внутри текста совпали: ни одна
    #: находка не пришла и не ушла — у тех же находок сдвинулись суммы. Это
    #: уточнение вердикта, а не сам вердикт (см. :data:`NUMERIC`).
    numeric_only: bool = False
    changed_helpers: tuple[str, ...] = ()
    elapsed_s: Optional[float] = None
    reason: Optional[str] = None

    @property
    def partial(self) -> bool:
        """Ось «редакция» неполна: вместе с производителем правился помощник."""
        return bool(self.changed_helpers) and self.kind in NAMED


@dataclass
class Census:
    """Замер по переданным членам класса."""

    outcomes: list[Outcome] = field(default_factory=list)
    sandbox_root: Optional[str] = None
    repo: Optional[str] = None
    rejected: list[dict] = field(default_factory=list)
    reason: Optional[str] = None
    generated_at: Optional[str] = None

    @property
    def measured(self) -> bool:
        return self.reason is None

    def by_kind(self, kind: str) -> list[Outcome]:
        return [o for o in self.outcomes if o.kind == kind]


def refuse_delivery_tree(root: Path) -> None:
    """Песочница, совпавшая с деревом доставки ЭТОГО модуля, — ОТКАЗ.

    Соседний отказ :func:`edition_remeasure.refuse_prod_root` стои́т про ПРОД, и
    его одного мало: цикл работает из одноразового worktree, и прод-деревом тот
    не является. Подменить производителя прежней редакцией в дереве, из которого
    пойдёт пуш, — это авария #1000 дословно, только байты в ней выглядят кодом
    лучше, чем испорченный синтаксис: они компилируются.

    Сравниваются REALPATH: ссылка внутрь дерева доставки уводит запись туда же.
    """
    real = Path(root).resolve()
    mine = _REPO_ROOT.resolve()
    if real == mine or mine in real.parents or real in mine.parents:
        raise er.Refused(
            f"корень песочницы {real} совпадает с деревом доставки этого модуля "
            f"{mine} (или вложен с ним): подмена производителя прежней редакцией "
            f"оставила бы в дереве доставки чужой код, который КОМПИЛИРУЕТСЯ")


def refresh_sandbox_data(prod_data: Path, sandbox_root: Path) -> Optional[str]:
    """Заменить ``data/`` песочницы СВЕЖИМ клоном прод-каталога. Причина или ``None``.

    **Зачем, и это найдено замером, а не предусмотрено.** Первая редакция прибора
    держала ОДНУ песочницу на всех членов, а производитель пишет свой артефакт
    ИМЕННО туда — то есть каждый прогон менял «сегодняшние данные» для следующего.
    Два прогона одного прибора по одному перечню на одном снимке данных разошлись
    у `asset_registry_gap_price`: `both` против `data`. Прод при этом не двигался
    (md5 8 из 8), значит данные подменил сам прибор.

    Клон берётся `cp -Rc` (clonefile APFS: 2,1 ГиБ за 0,27 с, copy-on-write),
    поэтому «свежая копия на каждый прогон» стоит доли секунды. Флага ``-c`` нет
    вне macOS ⇒ отход на обычное копирование, и это ПЕЧАТАЕТСЯ причиной, а не
    молча: на чужой ФС цена замера другая.
    """
    data = Path(sandbox_root) / "data"
    if not Path(prod_data).is_dir():
        return f"каталог напечатанных артефактов не читается как каталог: {prod_data}"
    tmp = Path(sandbox_root) / "data.__refresh__"
    for victim in (tmp,):
        if victim.exists():
            subprocess.run(["rm", "-rf", str(victim)], check=False, timeout=600)
    for flags in (["-Rc"], ["-R"]):
        proc = subprocess.run(["cp", *flags, str(prod_data), str(tmp)],
                              capture_output=True, text=True, timeout=1800)
        if proc.returncode == 0:
            break
    else:
        return (f"свежая копия данных не сделана: cp -R вышел "
                f"{proc.returncode}: {proc.stderr.strip()[-200:]}")
    old = Path(sandbox_root) / "data.__stale__"
    subprocess.run(["rm", "-rf", str(old)], check=False, timeout=600)
    if data.exists():
        data.rename(old)
    tmp.rename(data)
    subprocess.run(["rm", "-rf", str(old)], check=False, timeout=600)
    return None


def prior_blob(repo: Path, producer_rel: str, *, at: dt.datetime,
               ref: str = ae.REF_DEFAULT) -> tuple[Optional[bytes], Optional[str],
                                                   Optional[str], Optional[str]]:
    """Байты производителя, какими они были В МОМЕНТ производства артефакта.

    Возвращает ``(байты, sha коммита, дата коммита, причина отказа)``.

    Вопрос задаётся УДАЛЁННОЙ ветке и ПОЛНОМУ клону — у усечённого клона
    ``git log`` отвечает пустотой с кодом 0 (`.claude/rules/deployment.md`
    § «глубина клона — дверь не только у ТЕСТА, но и у ПРИБОРА»), и клон здесь не
    выбирается заново: он приходит входом от :func:`run`, который берёт его у
    единственной двери :func:`acceptance_tree_lineage.pick_lineage_repo`.

    Пустой ответ — НЕ «правок не было»: так же выглядит и путь, которого на
    ветке нет, и опечатка в объявлении производителя. Поэтому пустота — названная
    причина, а не молчаливое «берём сегодняшние байты» (это подменило бы ``C``
    набором ``B`` и дало бы вердикт ДАННЫЕ у чего угодно).
    """
    stamp = at.isoformat()
    code, out = ae._git(repo, "rev-list", "-1", f"--before={stamp}", ref,
                        "--", producer_rel)
    if code != 0:
        return None, None, None, (f"git не ответил о истории {producer_rel} на "
                                  f"{ref} до {stamp} (код {code}): {out or 'пусто'}")
    sha = out.strip()
    if not sha:
        return None, None, None, (
            f"у {producer_rel} нет ни одного коммита на {ref} ДО момента "
            f"производства {stamp}: прежней редакции не существует, и «она та же» "
            f"из этого не следует")
    code, when = ae._git(repo, "log", "-1", "--format=%cI", sha)
    code2, _ = ae._git(repo, "cat-file", "-e", f"{sha}:{producer_rel}")
    if code2 != 0:
        return None, sha, (when or None), (
            f"в коммите {sha[:9]} объекта {producer_rel} нет: путь родился позже "
            f"либо переименован — байты прежней редакции взять НЕГДЕ")
    try:
        proc = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{producer_rel}"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, sha, (when or None), f"git show не ответил: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return None, sha, (when or None), (
            f"git show {sha[:9]}:{producer_rel} код {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace')[-200:]}")
    return proc.stdout, sha, (when or None), None


def imported_helpers(source: bytes, *, root: Path) -> tuple[str, ...]:
    """Относительные пути модулей ``spa_core``, которые импортирует производитель.

    Разбор AST, а не греп: ``import`` внутри строки или комментария помощником не
    является, а помощник, названный в ``from … import``, грепом по имени модуля
    не находится. Первого порядка — и только: транзитивное замыкание означало бы
    половину дерева, и граница объявлена в докстринге модуля вслух.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("spa_core."):
                    names.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("spa_core"):
                for a in node.names:
                    names.add(f"{node.module}.{a.name}")
                names.add(node.module)
    out: set[str] = set()
    for dotted in names:
        parts = dotted.split(".")
        for cut in (len(parts), len(parts) - 1):
            if cut < 2:
                continue
            rel = "/".join(parts[:cut]) + ".py"
            if (Path(root) / rel).is_file():
                out.add(rel)
                break
    return tuple(sorted(out))


def changed_helpers(repo: Path, source: bytes, *, since: dt.datetime,
                    root: Path, ref: str = ae.REF_DEFAULT) -> tuple[str, ...]:
    """Помощники производителя, правленные на ``ref`` ПОЗЖЕ момента производства.

    Это не находка, а ГРАНИЦА вердикта: у такого члена ось «редакция» снята на
    смеси, и печать обязана назвать его отдельно (см. докстринг модуля).
    """
    out: list[str] = []
    for rel in imported_helpers(source, root=root):
        stamp, _why = ae.changed_at(repo, rel, ref=ref)
        if stamp is not None and stamp > since:
            out.append(rel)
    return tuple(out)


def _keys_of(path: Path) -> tuple[Optional[tuple[str, ...]], Optional[str]]:
    """Сравнимый набор находок файла — ЕДИНСТВЕННОЙ дверью ADR-1022."""
    doc = er._read(path)
    if doc is None:
        return None, f"артефакт не прочитан: {path}"
    return er.finding_keys(doc)


def cause_one(artifact: str, *, prod_data: Path, sandbox_root: Path, repo: Path,
              moments: Mapping[str, Optional[dt.datetime]],
              producers: Mapping[str, str],
              entries: Optional[Mapping[str, er.Entry]] = None,
              budget_s: float = er.BUDGET_S,
              refresh: Optional[Callable[[], Optional[str]]] = None,
              ref: str = ae.REF_DEFAULT) -> Outcome:
    """Назвать ось расхождения у ОДНОГО члена класса.

    Порядок шагов обязателен и не переставляется: ``B`` снимается ПЕРВЫМ, потому
    что он пишет артефакт песочницы сегодняшним кодом; подмена производителя идёт
    ПОСЛЕ, иначе ``B`` оказался бы снят прежней редакцией и вопрос свёлся бы к
    сравнению ``C`` с самим собой.
    """
    producer = producers.get(artifact)
    # Та же поздняя привязка, что у соседа: умолчание читает ОБЪЯВЛЕННЫЙ дом
    # таблицы в момент зова, а не копию, связанную при импорте.
    table = er.ENTRY if entries is None else entries
    entry = table.get(artifact)
    if entry is None:
        return Outcome(UNMEASURED, artifact, producer=producer, reason=(
            "песочного входа у этого члена НЕ ОБЪЯВЛЕНО (ADR-1022): запускать "
            "производителя наугад значило бы рискнуть записью в прод-артефакт"))
    if entry.refusal:
        return Outcome(UNMEASURED, artifact, producer=producer, reason=entry.refusal)
    if producer is None:
        return Outcome(UNMEASURED, artifact, reason=(
            "производитель этого артефакта у офиса НЕ ОБЪЯВЛЕН — чьи байты брать "
            "прежней редакцией, сказать нечем"))
    produced_at = moments.get(artifact)
    if produced_at is None:
        return Outcome(UNMEASURED, artifact, producer=producer, reason=(
            "момент производства не прочитан — у прежней редакции нет границы, "
            "а «возьмём предпоследний коммит» было бы догадкой, не замером"))
    if produced_at.tzinfo is None:
        produced_at = produced_at.replace(tzinfo=dt.timezone.utc)

    # --- B: сегодняшний код на сегодняшних данных (единственной дверью ADR-1022)
    if refresh is not None:
        why = refresh()
        if why is not None:
            return Outcome(UNMEASURED, artifact, producer=producer,
                           reason=f"свежие данные перед прогоном B: {why}")
    today_outcome = er.remeasure_one(artifact, prod_data=prod_data,
                                     sandbox_root=sandbox_root, budget_s=budget_s,
                                     entries=entries)
    if today_outcome.kind == er.UNMEASURED:
        return Outcome(UNMEASURED, artifact, producer=producer,
                       elapsed_s=today_outcome.elapsed_s, reason=(
                           f"перемер сегодняшней редакции НЕ ИЗМЕРЕН, поэтому и "
                           f"причина расхождения не измеряется: {today_outcome.reason}"))
    printed_keys, why = _keys_of(prod_data / artifact)
    if printed_keys is None:
        return Outcome(UNMEASURED, artifact, producer=producer,
                       reason=f"напечатанный набор: {why}")
    sandbox_artifact = sandbox_root / "data" / artifact
    today_keys, why = _keys_of(sandbox_artifact)
    if today_keys is None:
        return Outcome(UNMEASURED, artifact, producer=producer,
                       reason=f"сегодняшний набор: {why}")
    if set(printed_keys) == set(today_keys):
        # `prior_on_today` остаётся None НАМЕРЕННО: третьего прогона не было,
        # и напечатать здесь число значило бы выдать невыполненный замер за
        # выполненный (инв. #17).
        return Outcome(NO_DIVERGENCE, artifact, producer=producer,
                       printed=len(printed_keys), today=len(today_keys),
                       elapsed_s=today_outcome.elapsed_s)

    # --- C: ПРЕЖНЯЯ редакция на сегодняшних данных
    blob, sha, when, why = prior_blob(repo, producer, at=produced_at, ref=ref)
    if blob is None:
        return Outcome(UNMEASURED, artifact, producer=producer, prior_commit=sha,
                       prior_committed_at=when, printed=len(printed_keys),
                       today=len(today_keys), reason=f"прежняя редакция: {why}")

    target = sandbox_root / producer
    if not target.is_file():
        return Outcome(UNMEASURED, artifact, producer=producer, prior_commit=sha,
                       prior_committed_at=when, reason=(
                           f"в песочнице нет файла производителя {producer}: "
                           f"подменять нечего, и создать его значило бы собрать "
                           f"дерево, которого не было ни одного дня"))
    original = target.read_bytes()
    helpers = changed_helpers(repo, original, since=produced_at,
                              root=sandbox_root, ref=ref)
    # Данные для `C` обязаны быть ТЕМИ ЖЕ, что для `B`, а не теми, что ОСТАЛИСЬ
    # ПОСЛЕ `B`: прогон `B` записал в песочницу свой артефакт, и производитель,
    # читающий соседний артефакт, получил бы вход, которого в проде нет.
    if refresh is not None:
        why = refresh()
        if why is not None:
            return Outcome(UNMEASURED, artifact, producer=producer,
                           prior_commit=sha, prior_committed_at=when,
                           changed_helpers=helpers,
                           reason=f"свежие данные перед прогоном C: {why}")
    stamp_before = er._mtime(sandbox_artifact)
    try:
        target.write_bytes(blob)
        elapsed, refusal, err = er._produce(entry, root=sandbox_root,
                                            data=sandbox_root / "data",
                                            budget_s=budget_s)
    finally:
        target.write_bytes(original)
    if target.read_bytes() != original:
        return Outcome(UNMEASURED, artifact, producer=producer, prior_commit=sha,
                       prior_committed_at=when, changed_helpers=helpers, reason=(
                           f"байты производителя {producer} НЕ ВЕРНУЛИСЬ в "
                           f"песочницу побайтно — дерево песочницы держит чужую "
                           f"редакцию и соврёт следующему замеру"))
    if refusal is not None:
        return Outcome(UNMEASURED, artifact, producer=producer, prior_commit=sha,
                       prior_committed_at=when, changed_helpers=helpers,
                       elapsed_s=elapsed, reason=f"прогон прежней редакции: {refusal}")
    if er._mtime(sandbox_artifact) == stamp_before:
        return Outcome(UNMEASURED, artifact, producer=producer, prior_commit=sha,
                       prior_committed_at=when, changed_helpers=helpers,
                       elapsed_s=elapsed, reason=(
                           "артефакт песочницы НЕ ОБНОВИЛСЯ прежней редакцией: "
                           "сравнивать было бы НЕЧЕГО"
                           + (f"; stderr: {err}" if err else "")))
    prior_keys, why = _keys_of(sandbox_artifact)
    if prior_keys is None:
        return Outcome(UNMEASURED, artifact, producer=producer, prior_commit=sha,
                       prior_committed_at=when, changed_helpers=helpers,
                       elapsed_s=elapsed, reason=f"набор прежней редакции: {why}")

    same_as_printed = set(prior_keys) == set(printed_keys)
    same_as_today = set(prior_keys) == set(today_keys)
    if same_as_printed:
        kind = EDITION
    elif same_as_today:
        kind = DATA
    else:
        kind = BOTH
    return Outcome(kind, artifact, producer=producer, prior_commit=sha,
                   prior_committed_at=when, printed=len(printed_keys),
                   today=len(today_keys), prior_on_today=len(prior_keys),
                   prior_gone=tuple(sorted(set(printed_keys) - set(prior_keys))),
                   prior_arrived=tuple(sorted(set(prior_keys) - set(printed_keys))),
                   today_gone=tuple(sorted(set(printed_keys) - set(today_keys))),
                   today_arrived=tuple(sorted(set(today_keys) - set(printed_keys))),
                   numeric_only=(numeric_blind(printed_keys) == numeric_blind(prior_keys)
                                 and set(printed_keys) != set(prior_keys)),
                   changed_helpers=helpers, elapsed_s=elapsed)


def run(*, prod_data: Path, sandbox_root: Path, only: Sequence[str] = (),
        budget_s: float = er.BUDGET_S, repos: Optional[Sequence[str]] = None,
        ref: str = ae.REF_DEFAULT, now: Optional[dt.datetime] = None,
        entries: Optional[Mapping[str, er.Entry]] = None,
        repo: Optional[Path] = None, fresh_data: bool = True,
        progress: bool = False) -> Census:
    """Назвать ось у перечня (по умолчанию — у ВСЕГО класса ADR-1020).

    Клон выбирается ЕДИНСТВЕННОЙ дверью и ПЕЧАТАЕТСЯ: усечённый клон отвечает о
    истории пустотой с кодом 0, и прибор, молча взявший его ответ, объявил бы
    «прежней редакции не существует» у всего класса.
    """
    er.refuse_prod_root(sandbox_root)
    refuse_delivery_tree(sandbox_root)
    out = Census(sandbox_root=str(sandbox_root))
    if repo is None:
        candidates = list(repos) if repos is not None else [str(_REPO_ROOT),
                                                            ae.MIRROR_DEFAULT]
        try:
            repo, rejected = ae.pick_lineage_repo(candidates)
        except ae.Unmeasured as exc:
            out.reason = f"клон не выбран: {exc}"
            return out
        out.rejected = rejected
    out.repo = str(repo)

    try:
        producers, moments = ae._office_moments(prod_data)
    except Exception as exc:  # всё, чем офис может не загрузиться
        out.reason = f"перечень артефактов и моментов не получен: {exc}"
        return out

    names = list(only)
    if not names:
        names, why = er.stale_members(prod_data, repos=repos, ref=ref)
        if why is not None:
            out.reason = why
            return out
    for i, name in enumerate(names, 1):
        if progress:
            print(f"[ось] {i}/{len(names)} {name} …", file=sys.stderr, flush=True)
        o = cause_one(name, prod_data=prod_data, sandbox_root=sandbox_root,
                      repo=repo, moments=moments, producers=producers,
                      entries=entries, budget_s=budget_s, ref=ref,
                      refresh=((lambda: refresh_sandbox_data(prod_data, sandbox_root))
                               if fresh_data else None))
        if progress:
            print(f"[ось] {i}/{len(names)} {name} → {o.kind}"
                  f"{'' if o.elapsed_s is None else f' ({o.elapsed_s} с)'}",
                  file=sys.stderr, flush=True)
        out.outcomes.append(o)
    out.generated_at = (now or dt.datetime.now(dt.timezone.utc)).isoformat()
    return out


def report(c: Census, *, max_rows: Optional[int] = 12) -> list[str]:
    """Печать. Умолчанный остаток КАЖДОГО рода объявляется числом (ADR-1021)."""
    if not c.measured:
        return [f"ОСЬ ПРИЧИНЫ НЕ ИЗМЕРЕНА: {c.reason}"]
    partial = [o for o in c.outcomes if o.partial]
    out = [f"ось причины расхождения (песочница {c.sandbox_root}, клон {c.repo}):",
           f"  членов измерено: {len(c.outcomes)}",
           f"  сдвинула РЕДАКЦИЯ: {len(c.by_kind(EDITION))}",
           f"  сдвинули ДАННЫЕ: {len(c.by_kind(DATA))}",
           f"  двигают ОБЕ оси: {len(c.by_kind(BOTH))}",
           f"  набор НЕ РАСХОДИЛСЯ (измерено и равно нулю): "
           f"{len(c.by_kind(NO_DIVERGENCE))}",
           f"  НЕ ИЗМЕРЕНО: {len(c.by_kind(UNMEASURED))}",
           f"  ⚠️ ось «редакция» НЕПОЛНА (правился и помощник): {len(partial)}",
           f"  ⓘ расхождение ТОЛЬКО В ЧИСЛАХ внутри текста находки (ни одна не "
           f"пришла и не ушла): {len([o for o in c.outcomes if o.numeric_only])}"]
    labels = ((EDITION, "РЕДАКЦИЯ"), (DATA, "ДАННЫЕ"), (BOTH, "ОБЕ"),
              (NO_DIVERGENCE, "НЕ РАСХОДИЛСЯ"), (UNMEASURED, "НЕ ИЗМЕРЕНО"))
    for kind, label in labels:
        rows = c.by_kind(kind)
        shown = rows if max_rows is None else rows[:max_rows]
        for o in shown:
            if kind == UNMEASURED:
                out.append(f"  [{label}] {o.artifact}: {o.reason}")
            else:
                tail = (f" · помощники правлены: {', '.join(o.changed_helpers)}"
                        if o.changed_helpers else "")
                if o.numeric_only:
                    tail += (" · расхождение ТОЛЬКО В ЧИСЛАХ текста: ни одна "
                             "находка не пришла и не ушла")
                out.append(
                    f"  [{label}] {o.artifact}: напечатано {o.printed} → сегодня "
                    f"{o.today} → прежняя редакция на сегодняшних данных "
                    f"{o.prior_on_today} · прежняя {(o.prior_commit or '?')[:9]}"
                    f" · {o.elapsed_s} с{tail}")
                out.extend(_named_diff(o, max_rows=max_rows))
        if max_rows is not None and len(rows) > len(shown):
            out.append(f"  … ещё {len(rows) - len(shown)} в роде «{label}» "
                       f"(полный перечень — `--all`)")
    return out


def _named_diff(o: Outcome, *, max_rows: Optional[int]) -> list[str]:
    """Имена расхождения «напечатано ↔ прежняя редакция на сегодняшних данных».

    Умолчанный остаток объявляется ЧИСЛОМ (ADR-1021): «ещё N» честнее молчания,
    потому что молчание неотличимо от «остатка нет». Размеры наборов могут
    СОВПАСТЬ при разном содержимом — тогда только эти имена и говорят, что
    наборы разные.
    """
    out: list[str] = []
    for label, items in (("УМЕРЛА у сегодняшней редакции", o.today_gone),
                         ("РОДИЛАСЬ у сегодняшней редакции", o.today_arrived),
                         ("нет у прежней редакции", o.prior_gone),
                         ("есть ТОЛЬКО у прежней редакции", o.prior_arrived)):
        if not items:
            continue
        shown = items if max_rows is None else items[:max_rows]
        for key in shown:
            out.append(f"      ({label}) {key}")
        if max_rows is not None and len(items) > len(shown):
            out.append(f"      … ещё {len(items) - len(shown)} в «{label}»")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    """0 — ось названа у каждого члена · 1 — есть НЕ ИЗМЕРЕНО · 2 — замера нет вовсе."""
    ap = argparse.ArgumentParser(
        description="Что сдвинуло набор находок: РЕДАКЦИЯ производителя или ДАННЫЕ")
    ap.add_argument("--data-dir", default=str(_REPO_ROOT / "data"),
                    help="каталог НАПЕЧАТАННЫХ артефактов (обычно <прод>/data)")
    ap.add_argument("--sandbox-root", required=True,
                    help="корень одноразового дерева: сегодняшний код + копия живого "
                         "`data/`. Прод-дерево и дерево доставки — ОТКАЗ")
    ap.add_argument("--only", action="append", default=[],
                    help="назвать ось у этого артефакта (можно повторять)")
    ap.add_argument("--budget", type=float, default=er.BUDGET_S,
                    help=f"бюджет ОДНОГО прогона, с (умолчание {er.BUDGET_S:.0f})")
    ap.add_argument("--repo", action="append", dest="repos")
    ap.add_argument("--ref", default=ae.REF_DEFAULT)
    ap.add_argument("--now", help="момент замера, ISO-8601 (вход, не стенные часы)")
    ap.add_argument("--all", action="store_true", help="печатать ВСЕ имена")
    ap.add_argument("--max-rows", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stale-data", action="store_true",
                    help="НЕ освежать `data/` песочницы перед каждым прогоном "
                         "(прогон B оставляет свой артефакт входом прогону C — "
                         "замер #1161 показал, что вердикт от этого МЕНЯЕТСЯ)")
    ap.add_argument("--quiet", action="store_true",
                    help="не печатать ход в stderr; молчащий лог делает "
                         "«работает» и «умер» неразличимыми — включать осознанно")
    args = ap.parse_args(argv)

    now = None
    if args.now:
        try:
            now = dt.datetime.fromisoformat(args.now)
        except ValueError:
            print(f"ОТКАЗ (код 2): --now не разобран: {args.now!r}", file=sys.stderr)
            return 2

    # ADR-1000 (транш 1 двери песочницы, ADR-999 § 3.1 форма А): умолчание
    # `--data-dir` достижимо у руки и ведёт в ПРОД-дерево, поэтому дверь ставится
    # сразу после `parse_args` и ДО первого чтения. Соседний отказ
    # `refuse_prod_root` сторожит ПЕСОЧНИЦУ (куда пишем), эта дверь — КАТАЛОГ
    # ДАННЫХ (откуда читаем): под маркером песочницы прод-каталог здесь означает,
    # что замер думает, будто мерит стенд, а мерит живой трек.
    from spa_core.utils.live_paths import refuse_if_sandbox_leaks
    refuse_if_sandbox_leaks(args.data_dir, who="edition_cause")

    try:
        c = run(prod_data=Path(args.data_dir), sandbox_root=Path(args.sandbox_root),
                only=args.only, budget_s=args.budget, repos=args.repos,
                ref=args.ref, now=now, fresh_data=not args.stale_data,
                progress=not args.quiet)
    except er.Refused as exc:
        print(f"ОТКАЗ (код 2): {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"sandbox_root": c.sandbox_root, "repo": c.repo,
                          "reason": c.reason, "generated_at": c.generated_at,
                          "outcomes": [o.__dict__ for o in c.outcomes]},
                         ensure_ascii=False, indent=2, default=str))
    else:
        for line in report(c, max_rows=None if args.all else args.max_rows):
            print(line)
    if not c.measured:
        return 2
    return 1 if c.by_kind(UNMEASURED) else 0


if __name__ == "__main__":
    raise SystemExit(main())
