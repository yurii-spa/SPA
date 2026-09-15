"""Цена починки СУДЬИ отдельно от остальных наследников (заказ G18, хвост ADR-385).

Заказ цикла #605 поставлен дословно так:

> Рычаг измерен целиком: писатель ([ADR-383]), загрузчик ([ADR-384]) и наследники
> ([ADR-385]). Общая цена названа, и она складывается не в пользу правки
> загрузчика. Но у трёх ``recovers`` цена ОТРИЦАТЕЛЬНАЯ — им правка нужна, — а у
> семнадцати положительная, и среди семнадцати сам судья. Заказ G18: **измерить,
> что стоит починить СУДЬЮ отдельно от остальных.** ``shadow_trigger_eval`` —
> единственный из двадцати, чей ответ читает критерий взвода, и единственный, у
> кого «увидеть стёртый ACT» есть его прямая работа. Назвать по исходу: (а) какие
> именно ВЕЛИЧИНЫ внутри судьи раздуваются на повторе — поимённо; (б) для
> каждой — существует ли форма, нечувствительная к числу строк дня и при этом
> видящая ранний ACT; (в) сколько ACT-дней вернулось бы КРИТЕРИЮ, если починить
> одного судью и не трогать шестнадцать остальных.

Прибор только ЧИТАЕТ. Он не правит ни судью, ни загрузчик, ни писателя: он
называет ЦЕНУ правки, которой ещё не было, и НАЗЫВАЕТ ту её часть, которая
сегодня равна нулю.

## Три вопроса — три РАЗНЫХ замера, и сливать их нельзя

Заказ состоит из трёх, и у каждого свой стенд. Ответ на один не есть ответ на
другой, и именно на этом смешении держалась бы ложная бодрость «судью починили».

### (а) Что раздувается — меряется ПОВТОРОМ, а не правкой

Повтор побайтово равной строки дня не несёт НИ ОДНОГО нового сведения. Любая
величина, говорящая о СОСТОЯНИИ дня, обязана на нём не шелохнуться; величина,
которая поехала, считает СТРОКИ. Это и есть различитель [ADR-385], и здесь он
направлен внутрь одного-единственного наследника — судьи.

Население величин прибор НЕ выбирает: берутся ВСЕ скалярные листья отчёта судьи
(``evaluate_window``), кроме подённого журнала ``per_verdict`` и стенных полей.
Выбрать имена руками значило бы ответить за судью, какие из его чисел важны, —
ровно та ошибка, на которой ловился этот репозиторий (перепись, считающая не то
население).

**У величины может не быть СИГНАЛА, и это третий исход, а не «нечувствительна».**
Величина, которая на всех стендах одна и та же, неотличима от величины, которой
нечем шевельнуться: ``corrupt_history_lines`` равен нулю всегда не потому, что он
устойчив к повтору, а потому, что мусорных строк в журнале нет. Такие исходы
называются ``no_signal`` с причиной, и в «нечувствительные» НЕ записываются
(инв. #17).

Чтобы сигнал был у как можно большего числа величин, повтор ставится не на одном
дне, а на ЧЕТЫРЁХ семьях сразу — по одному представителю каждого класса дня,
который судья различает сам: оценённый существенный HOLD · тот же день с
вердиктом ACT (единственный источник сигнала для денежных величин — оценённых
ACT в журнале нет ни одного) · тривиальный день · неоценимый день. Величина
``inflates``, если поехала ХОТЬ В ОДНОЙ семье.

### (б) Есть ли форма — ПОЛОВИНА вопроса решается построением, и это сказано вслух

Форма, сворачивающая день в одну запись, нечувствительна к повтору ПО
ПОСТРОЕНИЮ: побайтово равные строки сворачиваются в ту же самую запись. Выдавать
это за измерение было бы украшением. Прибор всё равно проверяет свёртку повтором
(свёртка могла быть применена не там), но измеряемая половина вопроса другая:
**видит ли свёрнутая форма ранний ACT** — то есть меняется ли величина на стенде,
где ранняя строка ACT в дне ЕСТЬ.

Форм две, и они отвечают на разные вопросы о дне:

* ``any_act_last_row`` — «был ли за день ACT» (вердикт) + «чем день кончился»
  (всё остальное — из ПОСЛЕДНЕЙ строки). Образец, названный самим заказом.
* ``first_act_row`` — ранняя строка ACT берётся ЦЕЛИКОМ; предложение судится то,
  которое было принято, а не то, которым день кончился.

Разница между ними не стилистическая и видна в (в): день, чья ПОСЛЕДНЯЯ строка
тривиальна, у первой формы теряет существенность и до критерия не доходит.

**Нулевой контроль — третья форма** ``last_row``: свёртка, берущая последнюю
строку, то есть СЕГОДНЯШНЕЕ поведение. Под ней ни одна величина не имеет права
шевельнуться ни на одном стенде, и ни один ACT-день не имеет права дойти до
критерия. Контроль ловит ровно то, чем этот класс замеров и портится: свёртку,
которая «работает» оттого, что стенд построен в её пользу.

### (в) Сколько ACT-дней вернулось бы критерию — ДВА числа, и первое из них ноль

Первое число — **на сегодняшнем журнале, как он лежит**. Дней с ВТОРОЙ строкой в
нём ноль: писатель (``allocation_rationale.append_rationale_history``) не
схлопывает день при чтении, а УДАЛЯЕТ раннюю строку из файла при записи. Поэтому
починка судьи в одиночку не возвращает критерию ничего — не «мало», а ровно
ноль, и это измеряется, а не выводится.

Второе число — **ёмкость**: если писателя починить и день сможет нести обе
строки, на скольких из дней журнала восстановленный ранний ACT ДОЙДЁТ до
критерия? Это не то же самое, что «день стал ACT»: критерий ``net_bps_if_followed``
считает только ACT, попавшие в ``acts_scored``, а судья отказывает дню ещё и по
другим причинам — неоценимая нога вперёд, тривиальность, пустой горизонт. Ёмкость
меряется перебором ВСЕХ дней журнала: в день ``d`` подкладывается ранняя строка
ACT, сделанная из НАСТОЯЩЕЙ строки соседнего дня (материал вместо подделки), и
спрашивается исход у самого судьи.

**Что ёмкость НЕ доказывает.** Метка ``ACT`` на строке-близнеце наложена
прибором; настоящим в ней остаётся предложение (ноги, оборот, стоимость) дня-донора.
Поэтому ёмкость отвечает «дошёл бы ACT до критерия», а не «система приняла бы
такое решение». Знак ``net`` при этом — свойство настоящего предложения, а не
выдумка прибора, и он в отчёте называется отдельно.

## Починка судьи НЕ ЕСТЬ подмена ``load_history`` в его модуле

Ссылку на загрузчик достают из модуля судьи ЧУЖИЕ модули — атрибутом
``shadow_trigger_eval.load_history``. Их число меряется статически и печатается:
правка, сделанная переприсваиванием этого атрибута, потянула бы за собой их всех,
то есть «отдельно от остальных» не получилось бы. Отсюда вывод прибора: место
починки — ВНУТРИ ``evaluate_window`` (свёртка после вызова загрузчика), и это
утверждение структурное, помеченное как структурное.

Сам замер при этом подменяет атрибут — но зовёт ТОЛЬКО судью, поэтому ни один
сосед в замере не участвует. Достижимость подмены не предполагается, а
СЧИТАЕТСЯ: загрузчик обёрнут счётчиком, и если за прогон он не вызван ни разу,
исход ``unmeasured`` с причиной, а не спокойное «ничего не изменилось».

ADVISORY: ``hit_rate``, ``MIN_HIT_RATE``, ``TriggerParams``, писатель журнала и
его правило замены, ``load_history``, пороги RiskPolicy v1.0, стоп-кран, живой
трек и ``landing/`` НЕ трогаются. Прибор ничего не двигает и не предлагает
двигать капитал; взвод триггера — предмет №1 границы ADR-285.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("spa.monitoring.judge_alone_price")

VERSION = "judge-alone-price-v1"
ARTIFACT = "judge_alone_price.json"

HISTORY_FILENAME = "allocation_rationale_history.jsonl"
JUDGE_MODULE = "spa_core.paper_trading.shadow_trigger_eval"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: исходы величине (а)
VALUE_INFLATES = "inflates"
VALUE_REPEAT_SAFE = "repeat_insensitive"
VALUE_NO_SIGNAL = "no_signal"

#: исходы величине (б)
FORM_SEES_ACT = "sees_early_act"
FORM_BLIND = "blind_to_early_act"
FORM_UNMEASURED = "unmeasured"

#: формы свёртки дня
FORM_ANY_ACT = "any_act_last_row"
FORM_FIRST_ACT = "first_act_row"
FORM_NULL = "last_row"
FORMS = (FORM_ANY_ACT, FORM_FIRST_ACT, FORM_NULL)

#: стенные поля отчёта судьи — из населения величин исключаются поимённо
CLOCK_LEAVES = ("generated_at",)

#: ветви отчёта судьи, не дающие скалярного населения
SKIP_BRANCHES = ("per_verdict",)

STAND_EXCLUDE = ("backups",)

_ADVISORY = (
    "hit_rate", "MIN_HIT_RATE", "TriggerParams", "писатель журнала и его правило замены",
    "load_history", "пороги RiskPolicy v1.0", "стоп-кран", "живой трек", "landing/",
)

WHAT_IT_DOES_NOT_PROVE = (
    "метка ACT на строке-близнеце наложена прибором: ёмкость отвечает «дошёл бы ACT "
    "до критерия», а не «система приняла бы такое решение»",
    "нечувствительность свёртки к повтору верна ПО ПОСТРОЕНИЮ и измерением не является; "
    "измеряется вторая половина — видит ли свёрнутая форма ранний ACT",
    "прибор не пересчитывает правильность чисел судьи и не имеет чем",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── журнал и его дни ─────────────────────────────────────────────────────────
def read_history(data_dir: Path) -> Tuple[Optional[List[dict]], str]:
    """Строки журнала как они лежат. Не прочитано — ``None`` с причиной."""
    path = Path(data_dir) / HISTORY_FILENAME
    if not path.exists():
        return None, f"{HISTORY_FILENAME} нет в {data_dir}"
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return None, f"{HISTORY_FILENAME} не прочитан: {exc}"
    rows: List[dict] = []
    for line in raw:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("cycle_date"):
            rows.append(obj)
    if not rows:
        return None, f"{HISTORY_FILENAME} не содержит разбираемых строк"
    return rows, ""


def days_with_second_row(rows: Sequence[dict]) -> List[str]:
    """Дни, у которых в журнале ЕСТЬ вторая строка. Сегодня их ноль — и это (в)₁."""
    seen: Dict[str, int] = {}
    for r in rows:
        d = str(r.get("cycle_date"))
        seen[d] = seen.get(d, 0) + 1
    return sorted(d for d, n in seen.items() if n > 1)


# ── свёртка дня: три формы, третья — нулевой контроль ────────────────────────
def fold_day(rows: Sequence[dict], form: str) -> List[dict]:
    """Свернуть каждый день журнала в ОДНУ запись по названной форме.

    Все три формы идемпотентны на побайтовом повторе ПО ПОСТРОЕНИЮ — свёртка
    равных строк даёт ту же запись. Различаются они тем, ВИДЯТ ЛИ они раннюю
    строку ACT, и именно это в отчёте измеряется.
    """
    if form not in FORMS:
        raise ValueError(f"неизвестная форма свёртки: {form}")
    by: Dict[str, List[dict]] = {}
    for rec in rows:
        by.setdefault(str(rec.get("cycle_date")), []).append(rec)
    out: List[dict] = []
    for day in sorted(by):
        day_rows = by[day]
        if form == FORM_NULL:
            out.append(day_rows[-1])
            continue
        acts = [r for r in day_rows if str(r.get("verdict") or "").upper() == "ACT"]
        if not acts:
            out.append(day_rows[-1])
            continue
        if form == FORM_ANY_ACT:
            merged = dict(day_rows[-1])
            merged["verdict"] = "ACT"
            out.append(merged)
        else:  # FORM_FIRST_ACT — ранняя строка ACT целиком
            out.append(acts[0])
    return out


class _CountingLoader:
    """Загрузчик судьи в названной форме + СЧЁТЧИК достижимости.

    Счётчик существует потому, что «подмена не дотянулась» и «ничего не
    изменилось» дают одинаковый вид и разный смысл; ноль вызовов — это
    ``unmeasured``, а не спокойный ноль.
    """

    def __init__(self, form: Optional[str]) -> None:
        self.form = form
        self.calls = 0

    def __call__(self, data_dir, book_id=None):
        self.calls += 1
        from spa_core.monitoring.heir_all_rows_price import all_rows_loader
        rows, bad = all_rows_loader(data_dir, book_id)
        if self.form is None:
            return rows, bad
        return fold_day(rows, self.form), bad


# ── величины судьи: население берётся у САМОГО отчёта ────────────────────────
def judge_values(doc: dict) -> Dict[str, object]:
    """Все скалярные листья отчёта судьи, кроме подённого журнала и часов.

    Имя листа — путь через точку; элементы списка ``criteria`` адресуются по
    полю ``criterion``, а не по индексу: порядок в списке — не имя.
    """
    out: Dict[str, object] = {}

    def walk(node, prefix: str) -> None:
        if isinstance(node, dict):
            for key in sorted(node):
                if prefix == "" and key in SKIP_BRANCHES:
                    continue
                if key in CLOCK_LEAVES:
                    continue
                walk(node[key], f"{prefix}.{key}" if prefix else str(key))
            return
        if isinstance(node, list):
            for i, item in enumerate(node):
                label = None
                if isinstance(item, dict) and item.get("criterion"):
                    label = str(item["criterion"])
                walk(item, f"{prefix}[{label if label else i}]")
            return
        if isinstance(node, (str, int, float, bool)) or node is None:
            out[prefix] = node

    walk(doc, "")
    # Длина подённого журнала — величина о СОСТОЯНИИ набора, а сам журнал в
    # население не берётся: он список строк, и его повтор есть предмет замера.
    per = doc.get("per_verdict")
    if isinstance(per, list):
        out["per_verdict.__len__"] = len(per)
    return out


# ── стенды ───────────────────────────────────────────────────────────────────
def _copy_data(src: Path, dest_data: Path) -> None:
    dest_data.mkdir(parents=True, exist_ok=True)
    for item in sorted(Path(src).iterdir()):
        if item.name in STAND_EXCLUDE:
            continue
        dst = dest_data / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)


class _Carousel:
    """ОДНА копия ``data/``, у которой меняется только журнал.

    Пять стендов [ADR-385] копировали каталог целиком по разу на стенд; здесь
    стендов десятки, и копия одна: предмет замера — журнал, остальное неподвижно.
    Живой каталог не открывается на запись ни разу.
    """

    def __init__(self, source: Path, dest: Path, rows: Sequence[dict]) -> None:
        self.root = Path(dest)
        self.data = self.root / "data"
        self.rows = list(rows)
        _copy_data(Path(source), self.data)
        self.journal = self.data / HISTORY_FILENAME

    def set_day(self, idx: int, day_rows: Sequence[dict]) -> None:
        out: List[dict] = []
        for i, rec in enumerate(self.rows):
            if i == idx:
                out.extend(day_rows)
            else:
                out.append(rec)
        self.journal.write_text(
            "\n".join(json.dumps(r, sort_keys=True, default=str) for r in out) + "\n",
            encoding="utf-8")


def twin_act(donor: dict, day: str) -> dict:
    """Ранняя строка ACT из НАСТОЯЩЕЙ строки соседнего дня, перемеченной на ``day``."""
    twin = dict(donor)
    twin["cycle_date"] = day
    twin["decision_id"] = f"adr060-shadow-{day}"
    twin["generated_at"] = f"{day}T06:00:11.000000+00:00"
    twin["verdict"] = "ACT"
    return twin


def _ask_judge(data_dir: Path, form: Optional[str],
               *, patch: bool) -> Tuple[Optional[dict], str, int]:
    """Спросить судью. ``patch=False`` — сегодняшний судья, без подмены вовсе."""
    import sys
    judge = sys.modules.get(JUDGE_MODULE)
    if judge is None:
        from spa_core.paper_trading import shadow_trigger_eval as judge  # noqa: F811
    if not patch:
        try:
            return judge.evaluate_window(Path(data_dir), write=False), "", -1
        except BaseException as exc:  # noqa: BLE001
            return None, f"судья упал: {type(exc).__name__}: {exc}", -1
    original = judge.load_history
    loader = _CountingLoader(form)
    judge.load_history = loader
    try:
        doc = judge.evaluate_window(Path(data_dir), write=False)
    except BaseException as exc:  # noqa: BLE001
        return None, f"судья упал: {type(exc).__name__}: {exc}", loader.calls
    finally:
        judge.load_history = original
    if loader.calls == 0:
        return None, "подменённый загрузчик не вызван ни разу", 0
    return doc, "", loader.calls


# ── (а) что раздувается на повторе ───────────────────────────────────────────
#: классы дня, по одному представителю на семью; имя = чем семья даёт сигнал
FAMILY_SCORED_HOLD = "scored_hold"
FAMILY_ACT = "act_same_row"
FAMILY_TRIVIAL = "trivial_day"
FAMILY_UNCHECKED = "unchecked_day"


def pick_families(baseline: dict, rows: Sequence[dict]) -> Tuple[Dict[str, int], List[str]]:
    """По одному дню на класс, который различает САМ судья. Нет класса — назван."""
    per = {str(r.get("cycle_date")): r for r in (baseline.get("per_verdict") or [])}
    idx_of = {str(r.get("cycle_date")): i for i, r in enumerate(rows)}
    picked: Dict[str, int] = {}
    missing: List[str] = []

    def first(pred) -> Optional[int]:
        for day in sorted(per):
            if day not in idx_of or idx_of[day] == 0:
                continue  # у первого дня нет соседа-донора
            if pred(per[day]):
                return idx_of[day]
        return None

    wanted = {
        FAMILY_SCORED_HOLD: lambda r: (not r.get("trivial")
                                       and r.get("outcome") in ("hit", "miss")),
        FAMILY_ACT: lambda r: (not r.get("trivial")
                               and r.get("outcome") in ("hit", "miss")),
        FAMILY_TRIVIAL: lambda r: bool(r.get("trivial")),
        FAMILY_UNCHECKED: lambda r: r.get("outcome") == "UNCHECKED",
    }
    for name, pred in wanted.items():
        got = first(pred)
        if got is None:
            missing.append(name)
        else:
            picked[name] = got
    return picked, missing


def repeat_census(carousel: _Carousel, families: Dict[str, int],
                  *, form: Optional[str], patch: bool) -> Tuple[Dict[str, dict], List[str]]:
    """Ответы судьи на ×1 / ×2 / ×3 в каждой семье. Ключ — ``семья@повтор``."""
    answers: Dict[str, dict] = {}
    refusals: List[str] = []
    for family, idx in sorted(families.items()):
        row = dict(carousel.rows[idx])
        if family == FAMILY_ACT:
            row = dict(row)
            row["verdict"] = "ACT"
        for times in (1, 2, 3):
            carousel.set_day(idx, [row] * times)
            doc, why, _calls = _ask_judge(carousel.data, form, patch=patch)
            if doc is None:
                refusals.append(f"{family}×{times}: {why}")
                continue
            answers[f"{family}@{times}"] = judge_values(doc)
    return answers, refusals


def classify_values(answers: Dict[str, dict], families: Sequence[str]) -> List[dict]:
    """Вердикт каждой величине: раздувается · устойчива · сигнала нет."""
    names: set = set()
    for vals in answers.values():
        names.update(vals)
    rows: List[dict] = []
    for name in sorted(names):
        seen: List[object] = []
        moved_in: List[str] = []
        for family in sorted(families):
            base = answers.get(f"{family}@1", {})
            if name not in base:
                continue
            first = base[name]
            seen.append(first)
            for times in (2, 3):
                later = answers.get(f"{family}@{times}", {})
                if name not in later:
                    continue
                seen.append(later[name])
                if later[name] != first and family not in moved_in:
                    moved_in.append(family)
        if not seen:
            rows.append({"value": name, "outcome": VALUE_NO_SIGNAL,
                         "reason": "величина не наблюдалась ни на одном стенде"})
            continue
        distinct = {json.dumps(v, sort_keys=True, default=str) for v in seen}
        if moved_in:
            rows.append({"value": name, "outcome": VALUE_INFLATES,
                         "inflates_in": moved_in,
                         "reason": ("поехала на ПОВТОРЕ побайтово равной строки — "
                                    "считает строки, а не состояние дня")})
        elif len(distinct) == 1:
            rows.append({"value": name, "outcome": VALUE_NO_SIGNAL,
                         "reason": ("одно и то же значение на всех стендах: "
                                    "нечувствительность от отсутствия сигнала "
                                    "этим замером не отличима")})
        else:
            rows.append({"value": name, "outcome": VALUE_REPEAT_SAFE,
                         "reason": ("значение по семьям разное, а на повторе "
                                    "неподвижно — говорит о состоянии дня")})
    return rows


# ── (б) видит ли форма ранний ACT ────────────────────────────────────────────
def form_sees_act(carousel: _Carousel, idx: int, *, form: str,
                  values: Sequence[str]) -> Tuple[Dict[str, str], List[str], str]:
    """По каждой величине: сдвинулась ли она от появления РАННЕЙ строки ACT.

    Стенд ``s_one`` — день одной настоящей строкой; ``s_true`` — та же строка,
    но перед ней ранний ACT. Обе читаются ОДНОЙ формой, поэтому разница
    величины есть разница ДНЯ, а не формы.
    """
    day = str(carousel.rows[idx].get("cycle_date"))
    real = carousel.rows[idx]
    twin = twin_act(carousel.rows[idx - 1], day)

    carousel.set_day(idx, [real])
    one, why_one, _ = _ask_judge(carousel.data, form, patch=True)
    carousel.set_day(idx, [twin, real])
    true, why_true, _ = _ask_judge(carousel.data, form, patch=True)
    if one is None or true is None:
        return {}, [why_one or why_true], day
    v_one, v_true = judge_values(one), judge_values(true)
    out: Dict[str, str] = {}
    for name in values:
        if name not in v_one or name not in v_true:
            out[name] = FORM_UNMEASURED
        elif v_one[name] != v_true[name]:
            out[name] = FORM_SEES_ACT
        else:
            out[name] = FORM_BLIND
    return out, [], day


# ── (в) сколько ACT-дней дошло бы до критерия ────────────────────────────────
def capacity(carousel: _Carousel, *, form: str) -> dict:
    """Перебор ВСЕХ дней: дойдёт ли восстановленный ранний ACT до критерия.

    «Дошёл до критерия» = вердикт дня стал ``ACT`` И его исход попал в
    ``hit``/``miss``, то есть день вошёл в ``acts_scored`` — единственный набор,
    которым считается ``net_bps_if_followed``.
    """
    reached: List[dict] = []
    act_but_unscored: List[dict] = []
    not_act: List[str] = []
    refused: List[str] = []
    for idx in range(1, len(carousel.rows)):
        day = str(carousel.rows[idx].get("cycle_date"))
        twin = twin_act(carousel.rows[idx - 1], day)
        carousel.set_day(idx, [twin, carousel.rows[idx]])
        doc, why, _ = _ask_judge(carousel.data, form, patch=True)
        if doc is None:
            refused.append(f"{day}: {why}")
            continue
        row = next((r for r in (doc.get("per_verdict") or [])
                    if str(r.get("cycle_date")) == day), None)
        if row is None or str(row.get("verdict")) != "ACT":
            not_act.append(day)
            continue
        if row.get("outcome") in ("hit", "miss"):
            reached.append({"day": day, "outcome": row.get("outcome"),
                            "net_usd": row.get("net_usd"),
                            "material": not bool(row.get("trivial"))})
        else:
            act_but_unscored.append({"day": day,
                                     "reason": row.get("unchecked_reason")})
    material = [r for r in reached if r["material"]]
    positive = [r for r in material if isinstance(r.get("net_usd"), (int, float))
                and r["net_usd"] > 0]
    return {
        "form": form,
        "days_tested": len(carousel.rows) - 1,
        "reaches_criterion": len(reached),
        "reaches_criterion_material": len(material),
        "reaches_criterion_material_net_positive": len(positive),
        "act_but_unscored": len(act_but_unscored),
        "never_became_act": len(not_act),
        "refused": refused,
        "days": reached,
        "unscored_reasons": act_but_unscored,
    }


# ── где место починки: ссылку на загрузчик достают соседи ────────────────────
def _judge_aliases(tree: ast.AST) -> set:
    """Имена в ЭТОМ файле, связанные с МОДУЛЕМ судьи (а не с его функцией)."""
    aliases: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name != JUDGE_MODULE:
                    continue
                # `import a.b.judge` связывает имя `a`, но обращение идёт
                # цепочкой `a.b.judge.load_history`, и её основанием служит
                # ПОСЛЕДНЕЕ звено (см. `_base_name`). Первое звено сюда НЕ
                # кладётся намеренно: достижимым оно не бывает, а как алиас
                # судьи годится любому `spa_core.<что угодно>.load_history` —
                # то есть даёт ложные срабатывания и ни одного верного.
                aliases.add(a.asname or a.name.rsplit(".", 1)[1])
        elif isinstance(node, ast.ImportFrom):
            if node.module == JUDGE_MODULE.rsplit(".", 1)[0]:
                for a in node.names:
                    if a.name == JUDGE_MODULE.rsplit(".", 1)[1]:
                        aliases.add(a.asname or a.name)
    return aliases


def _base_name(node: ast.AST) -> Optional[str]:
    """``ste`` у ``ste.load_history``; ``_ste`` у ``_dep._ste.load_history``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def attribute_readers(tree_root: Path) -> dict:
    """Кто достаёт ``load_history`` АТРИБУТОМ модуля судьи (статика).

    Утверждение структурное и помечено таковым: оно о том, куда придёт правка,
    а не о том, что она посчитает. Правку, сделанную переприсваиванием атрибута
    ``shadow_trigger_eval.load_history``, увидят ВСЕ, кто читает его через
    модуль, — и не увидит никто, кто забрал себе копию ссылки
    (``from … import load_history``). Это РАЗНЫЕ населения, и они считаются
    порознь.

    Населений пять, и четвёртое с пятым существуют потому, что «обращение
    ``<что-то>.load_history``» само по себе о судье не говорит НИЧЕГО. Замер
    первой редакции дал 56 «читателей»; из них к судье относятся единицы, а
    большинство — ``self.load_history()``, собственный метод чужого класса.
    Записать их в читатели значило бы построить перепись не того населения.

    * ``via_judge_module`` — имя основания связано с модулем судьи В ЭТОМ файле;
    * ``via_judge_module_indirect`` — основание есть алиас судьи, взятый через
      ЧУЖОЙ модуль (``_dep._ste.load_history``, форма из [ADR-384]); алиасы
      собираются со всего дерева, поэтому это утверждение об имени, а не о
      тождестве, и оно помечено словом ``indirect``;
    * ``own_copy_of_reference`` — своя копия ссылки, правку атрибута НЕ увидит;
    * ``own_method`` — ``self``/``cls``: собственный метод, к судье отношения нет;
    * ``unresolved`` — третий исход: не привязано ни к чему из перечисленного.
    """
    judge_rel = "spa_core/paper_trading/shadow_trigger_eval.py"
    files: List[Tuple[str, ast.AST]] = []
    unparsed: List[str] = []
    for path in sorted(Path(tree_root).rglob("*.py")):
        rel = str(path.relative_to(tree_root))
        if "/tests/" in f"/{rel}" or rel.startswith("tests/"):
            continue
        if rel == judge_rel or path.name == Path(__file__).name:
            continue
        try:
            files.append((rel, ast.parse(path.read_text(encoding="utf-8"))))
        except (OSError, SyntaxError) as exc:
            unparsed.append(f"{rel}: {type(exc).__name__}")

    global_aliases: set = set()
    for _rel, tree in files:
        global_aliases |= _judge_aliases(tree)

    direct: List[str] = []
    indirect: List[str] = []
    own_copy: List[str] = []
    own_method: List[str] = []
    unresolved: List[str] = []
    for rel, tree in files:
        aliases = _judge_aliases(tree)
        kinds: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == JUDGE_MODULE \
                    and any(a.name == "load_history" for a in node.names):
                kinds.add("own_copy")
            if isinstance(node, ast.Attribute) and node.attr == "load_history":
                base = _base_name(node.value)
                if isinstance(node.value, ast.Name) and node.value.id in ("self", "cls"):
                    kinds.add("own_method")
                elif base is not None and base in aliases:
                    kinds.add("direct")
                elif base is not None and base in global_aliases:
                    kinds.add("indirect")
                else:
                    kinds.add("unresolved")
        if "own_copy" in kinds:
            own_copy.append(rel)
        if "direct" in kinds:
            direct.append(rel)
        elif "indirect" in kinds:
            indirect.append(rel)
        elif "unresolved" in kinds:
            unresolved.append(rel)
        elif "own_method" in kinds:
            own_method.append(rel)
    return {"kind": "structural",
            "via_judge_module": sorted(set(direct)),
            "via_judge_module_count": len(set(direct)),
            "via_judge_module_indirect": sorted(set(indirect)),
            "via_judge_module_indirect_count": len(set(indirect)),
            "own_copy_of_reference": sorted(set(own_copy)),
            "own_copy_count": len(set(own_copy)),
            "own_method": sorted(set(own_method)),
            "own_method_count": len(set(own_method)),
            "unresolved": sorted(set(unresolved)),
            "unresolved_count": len(set(unresolved)),
            "unresolved_note": ("основание обращения к судье не привязано ни к "
                                "алиасу, ни к self — ни в одно население не "
                                "засчитано (третий исход)"),
            "unparsed": unparsed}


# ── замер ────────────────────────────────────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            stand_root: Optional[Path] = None,
            tree_root: Optional[Path] = None,
            with_capacity: bool = True) -> dict:
    """Полный замер G18. Живой ``data/`` только читается; стенд — копия."""
    stamp = (now or _utcnow()).isoformat()
    doc: Dict[str, object] = {
        "version": VERSION,
        "generated_at": stamp,
        "data_dir": str(data_dir),
        "advisory": list(_ADVISORY),
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
    }
    rows, why = read_history(Path(data_dir))
    if rows is None:
        doc["status"] = STATUS_UNMEASURED
        doc["unmeasured_reason"] = f"журнал не прочитан: {why}"
        return doc
    if len(rows) < 3:
        doc["status"] = STATUS_UNMEASURED
        doc["unmeasured_reason"] = ("в журнале меньше трёх строк — ни семьи, ни "
                                    "донора для раннего ACT не построить")
        return doc

    tree = Path(tree_root) if tree_root else Path(__file__).resolve().parents[2]
    import tempfile
    tmp = Path(stand_root) if stand_root else Path(tempfile.mkdtemp(prefix="g18_"))
    tmp.mkdir(parents=True, exist_ok=True)

    doc["journal"] = {
        "rows": len(rows),
        "days": len({str(r.get("cycle_date")) for r in rows}),
        "days_with_second_row": days_with_second_row(rows),
    }
    doc["fix_site"] = attribute_readers(tree)

    carousel = _Carousel(Path(data_dir), tmp, rows)
    doc["stand_root"] = str(carousel.root)

    # Опора: сегодняшний судья на НЕТРОНУТОМ журнале — классы дней берутся у него.
    carousel.journal.write_text(
        "\n".join(json.dumps(r, sort_keys=True, default=str) for r in rows) + "\n",
        encoding="utf-8")
    baseline, why_base, _ = _ask_judge(carousel.data, None, patch=False)
    if baseline is None:
        doc["status"] = STATUS_UNMEASURED
        doc["unmeasured_reason"] = f"опорный ответ судьи не получен: {why_base}"
        return doc

    families, missing = pick_families(baseline, rows)
    doc["families"] = {name: str(rows[i].get("cycle_date"))
                       for name, i in sorted(families.items())}
    doc["families_missing"] = missing
    if not families:
        doc["status"] = STATUS_UNMEASURED
        doc["unmeasured_reason"] = ("ни одного класса дня не нашлось — повтор "
                                    "ставить не на чем")
        return doc

    # (а) — загрузчик отдаёт ВСЕ строки, судья не тронут.
    answers, refusals = repeat_census(carousel, families, form=None, patch=True)
    doc["repeat_refusals"] = refusals
    values = classify_values(answers, list(families))
    doc["values"] = values
    vcounts: Dict[str, int] = {}
    for row in values:
        vcounts[str(row["outcome"])] = vcounts.get(str(row["outcome"]), 0) + 1
    doc["value_outcomes"] = vcounts
    doc["values_population"] = len(values)

    inflating = [str(r["value"]) for r in values if r["outcome"] == VALUE_INFLATES]

    # (б) — обе формы плюс нулевой контроль.
    forms: Dict[str, object] = {}
    for form in FORMS:
        seen, form_refusals, day = form_sees_act(
            carousel, families.get(FAMILY_SCORED_HOLD, sorted(families.values())[0]),
            form=form, values=inflating)
        repeat_answers, rep_ref = repeat_census(carousel, families,
                                                form=form, patch=True)
        repeat_rows = classify_values(repeat_answers, list(families))
        moved_on_repeat = [str(r["value"]) for r in repeat_rows
                           if r["outcome"] == VALUE_INFLATES]
        forms[form] = {
            "day": day,
            "sees_early_act": sorted(k for k, v in seen.items() if v == FORM_SEES_ACT),
            "blind_to_early_act": sorted(k for k, v in seen.items() if v == FORM_BLIND),
            "unmeasured": sorted(k for k, v in seen.items() if v == FORM_UNMEASURED),
            "still_inflates_on_repeat": moved_on_repeat,
            "refusals": form_refusals + rep_ref,
        }
    doc["forms"] = forms

    # (в) — два числа: сегодня и ёмкость.
    doc["returns_today"] = {
        "act_days": 0 if not doc["journal"]["days_with_second_row"] else None,
        "reason": ("дней со ВТОРОЙ строкой в журнале ноль: писатель удаляет раннюю "
                   "строку при записи, и починка судьи в одиночку читать ей нечего")
        if not doc["journal"]["days_with_second_row"] else
        "в журнале есть дни со второй строкой — число считается перебором",
    }
    if with_capacity:
        doc["capacity"] = {form: capacity(carousel, form=form) for form in FORMS}
    else:
        doc["capacity"] = None
        doc["capacity_unmeasured_reason"] = "ёмкость не мерилась: with_capacity=False"

    doc.update(_verdict(doc))
    return doc


def _verdict(doc: dict) -> dict:
    """Статус. Нечитаемое — UNMEASURED, а не спокойный ноль."""
    from spa_core.utils.observation import observed

    counts = observed(doc, "value_outcomes", kind=dict)
    if counts is None:
        return {"status": STATUS_UNMEASURED,
                "unmeasured_reason": "исходы величин не измерены"}
    inflating = counts.get(VALUE_INFLATES, 0)
    returns = observed(doc, "returns_today", kind=dict) or {}
    today = returns.get("act_days")
    if today is None:
        return {"status": STATUS_UNMEASURED,
                "unmeasured_reason": "сколько ACT-дней возвращается сегодня — не измерено"}
    cap = observed(doc, "capacity", kind=dict)
    cap_line = ""
    if cap:
        null = cap.get(FORM_NULL, {})
        best = max((v.get("reaches_criterion_material", 0)
                    for k, v in cap.items() if k != FORM_NULL), default=0)
        cap_line = (f"; ёмкость при починенном писателе — {best} существенных "
                    f"ACT-дн. (нулевой контроль: {null.get('reaches_criterion', 0)})")
    if inflating:
        return {"status": STATUS_CRITICAL,
                "headline": (f"{inflating} из {doc.get('values_population')} величин судьи "
                             f"раздуваются на ПОВТОРЕ побайтово равной строки; "
                             f"сегодня починка судьи возвращает критерию "
                             f"{today} ACT-дн.{cap_line}")}
    return {"status": STATUS_WARNING,
            "headline": (f"ни одна величина судьи не поехала на повторе; "
                         f"сегодня починка судьи возвращает критерию {today} "
                         f"ACT-дн.{cap_line}")}


def format_report(doc: dict) -> List[str]:
    from spa_core.utils.observation import observed

    out: List[str] = []
    if doc.get("status") == STATUS_UNMEASURED:
        out.append(f"[НЕ ИЗМЕРЕНО] {doc.get('unmeasured_reason', 'причина не названа')}")
        return out
    journal = observed(doc, "journal", kind=dict) or {}
    out.append(f"[ЖУРНАЛ] строк {journal.get('rows')} · дней {journal.get('days')} · "
               f"дней со второй строкой {len(journal.get('days_with_second_row') or [])}")
    fams = observed(doc, "families", kind=dict) or {}
    out.append("[СЕМЬИ] " + " · ".join(f"{k}={v}" for k, v in sorted(fams.items()))
               + (f" · нет класса: {doc.get('families_missing')}"
                  if doc.get("families_missing") else ""))
    counts = observed(doc, "value_outcomes", kind=dict) or {}
    out.append(f"[А · ЧТО РАЗДУВАЕТСЯ] величин {doc.get('values_population')}: "
               + " · ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for row in observed(doc, "values", kind=list) or []:
        if row.get("outcome") == VALUE_INFLATES:
            out.append(f"   [РАЗДУВАЕТСЯ] {row.get('value')} "
                       f"(семьи: {', '.join(row.get('inflates_in') or [])})")
    forms = observed(doc, "forms", kind=dict) or {}
    for name in FORMS:
        f = forms.get(name) or {}
        tag = "НУЛЕВОЙ КОНТРОЛЬ" if name == FORM_NULL else "ФОРМА"
        out.append(f"[Б · {tag}] {name}: видит ранний ACT у "
                   f"{len(f.get('sees_early_act') or [])} величин(ы) · слепа у "
                   f"{len(f.get('blind_to_early_act') or [])} · раздувается на повторе "
                   f"у {len(f.get('still_inflates_on_repeat') or [])}")
        if f.get("blind_to_early_act"):
            out.append("      слепа у: " + ", ".join(f["blind_to_early_act"]))
    cap = observed(doc, "capacity", kind=dict)
    ret = observed(doc, "returns_today", kind=dict) or {}
    out.append(f"[В · СЕГОДНЯ] критерию возвращается {ret.get('act_days')} ACT-дн. — "
               f"{ret.get('reason')}")
    if cap is None:
        out.append("[В · ЁМКОСТЬ] НЕ ИЗМЕРЕНО: "
                   + str(doc.get("capacity_unmeasured_reason", "причина не названа")))
    else:
        for name in FORMS:
            c = cap.get(name) or {}
            tag = "НУЛЕВОЙ КОНТРОЛЬ" if name == FORM_NULL else "ЁМКОСТЬ"
            out.append(f"[В · {tag}] {name}: из {c.get('days_tested')} дн. до критерия "
                       f"доходит {c.get('reaches_criterion')} "
                       f"(существенных {c.get('reaches_criterion_material')}, из них с "
                       f"net>0 — {c.get('reaches_criterion_material_net_positive')}) · "
                       f"ACT без оценки {c.get('act_but_unscored')} · "
                       f"не стал ACT {c.get('never_became_act')}")
    site = observed(doc, "fix_site", kind=dict) or {}
    out.append(f"[ГДЕ ЧИНИТЬ] атрибутом модуля судьи загрузчик достают "
               f"{site.get('via_judge_module_count')} модул(ь/я/ей) "
               f"(признак структурный): "
               + ", ".join(site.get("via_judge_module") or ["—"]))
    out.append(f"   своя копия ссылки (правку атрибута НЕ увидят): "
               f"{site.get('own_copy_count')} — "
               + ", ".join(site.get("own_copy_of_reference") or ["—"]))
    out.append(f"   через ЧУЖОЙ алиас: {site.get('via_judge_module_indirect_count')} — "
               + ", ".join(site.get("via_judge_module_indirect") or ["—"]))
    out.append(f"   собственный метод (к судье отношения нет): "
               f"{site.get('own_method_count')}")
    out.append(f"   [НЕ ИЗМЕРЕНО] {site.get('unresolved_count')} файл(ов) — "
               + str(site.get("unresolved_note")))
    for line in doc.get("what_it_does_not_prove", []):
        out.append(f"[НЕ ДОКАЗЫВАЕТ] {line}")
    out.append("ADVISORY: " + ", ".join(doc.get("advisory", []))
               + " НЕ трогаются — прибор только ЧИТАЕТ")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, with_capacity: bool = True) -> dict:
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    doc = measure(base / "data", now=now, tree_root=base, with_capacity=with_capacity)
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(base / "data" / ARTIFACT))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--stand-root", default=None)
    #: Дерево, по которому считается «где чинить». Отдельным флагом, потому что
    #: обход дерева — самая дорогая часть замера, и без него CLI умел спрашивать
    #: ТОЛЬКО о своём репозитории: приёмка платила за полный обход 7500 файлов в
    #: каждом тесте, а спросить прибор о ЧУЖОМ дереве было нечем.
    ap.add_argument("--tree-root", default=None)
    ap.add_argument("--no-capacity", action="store_true",
                    help="не мерить третью часть заказа (ёмкость)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    base = Path(__file__).resolve().parents[2]
    tree = Path(args.tree_root) if args.tree_root else base
    data_dir = Path(args.data_dir) if args.data_dir else base / "data"
    doc = measure(data_dir, tree_root=tree,
                  stand_root=Path(args.stand_root) if args.stand_root else None,
                  with_capacity=not args.no_capacity)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    else:
        for line in format_report(doc):
            print(line)
    return {STATUS_OK: 0, STATUS_WARNING: 0, STATUS_CRITICAL: 1,
            STATUS_UNMEASURED: 2}.get(str(doc.get("status")), 2)


if __name__ == "__main__":
    raise SystemExit(main())
