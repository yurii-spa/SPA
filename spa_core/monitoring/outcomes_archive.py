"""outcomes_archive.py — правая половина hit-rate офиса (ADR-066 Ф4 / очередь ADR-067).

Архив вердиктов (что офис ГОВОРИЛ по дням) уже пишется; этот модуль копит
вторую половину пары — что ВЫШЛО на самом деле: append-only
`data/investment_os/outcomes.jsonl`, одна строка на календарный день:

    {"date", "equity_close", "daily_return_pct", "positions", "cash_usd",
     "apy_evidenced_pct", "posture_office", "sources"}

Правила честности:
  - строка дня пишется ОДИН раз (идемпотентно по date) и только из
    наблюдённых файлов; недостающее поле пишется null с именем причины в
    sources — никогда не выдумывается;
  - equity — только evidenced-бар кривой за этот день (фильтр трека);
  - постура — из архива вердиктов chief за этот день (если он молчал — null,
    и это видно);
  - пишет decision_loop (6ч, 4 шанса в день догнать) — money-path
    (cycle_runner) не тронут;
  - пропущенный день ежедневный писатель не догоняет НИКОГДА (он знает только
    «сегодня»); для дыр есть осознанная команда
    `python3 -m spa_core.monitoring.outcomes_archive --backfill [--since D --until D]`
    — намеренно РУЧНАЯ: автолечение стёрло бы находку об остановке записи
    раньше, чем её кто-нибудь прочитает.

Потребитель — loop_retro.analyze_outcomes: сопоставляет постуру дня d с
форвардной доходностью d+1..d+H и снимает вечные UNCHECKED hit-rate'а,
как только пар набирается достаточно. LLM_FORBIDDEN. stdlib. Время — вход.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile

from spa_core.monitoring.architecture_conformance import REPO_ROOT

OUTCOMES_REL = os.path.join("data", "investment_os", "outcomes.jsonl")


def _load(rel: str, root: str):
    try:
        return json.load(open(os.path.join(root, rel)))
    except Exception:
        return None


def load_outcomes(root: str = REPO_ROOT) -> list[dict]:
    path = os.path.join(root, OUTCOMES_REL)
    out: list[dict] = []
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return out


_NOT_MEASURED = "книга за этот день не наблюдена ни одним источником — null, не ноль"


def _resolve_book(root: str, day: str,
                  curve: dict | None) -> tuple[dict | None, float | None, str, str]:
    """Книга (позиции + кэш) на закрытии дня `day` — только из НАБЛЮДЁННОГО.

    Возвращает ``(positions, cash_usd, источник_позиций, источник_кэша)``.

    Почему источников два и именно в этом порядке (замер 2026-08-18, карточка
    «Книги за прошлый день нет в архиве»).

    * `data/current_positions.json` — снимок «прямо сейчас», датированный ровно
      одним полем `generated_at`. Он годится ТОЛЬКО для сегодняшнего дня и
      только пока цикл не отработал снова; для любого прошлого дня он
      структурно не годится, и до этой правки других кандидатов у сборки не
      было — поэтому КАЖДАЯ дозаписанная задним числом строка несла
      `positions: null` не по случайности, а по построению.
    * Дневной бар кривой (`data/equity_curve_daily.json`) — ДАТИРОВАННЫЙ архив
      той же самой величины: `cycle_runner` пишет в бар и в снимок ОДИН объект
      `effective_positions` одного прогона (`cycle_runner.py` → `_upsert_equity_point`
      / `POSITIONS_FILENAME`). Это не «похожая» книга и не намерение: у
      `allocation_rationale_history` лежит книга НА ВХОДЕ цикла и `target_positions`
      (намерение, которое 14.08 не исполнилось) — их брать нельзя, а бар это
      книга, с которой день закрылся. Кривая читается ТОЛЬКО на чтение.

    Кэш из бара НЕ восстанавливается: бар несёт позиции и equity, но не
    `cash_usd`. Вывести его как `capital − deployed` значило бы подставить
    константу капитала за наблюдение — ровно та подмена, которую архив себе
    запрещает. Кэш остаётся `null` с названной причиной.

    Fail-CLOSED разделение, ради которого правка и сделана: «не измерено»
    (`None` + причина) НИКОГДА не выглядит как «книга была пуста» (`{}` +
    причина) и никогда как «кэша было ноль» (`0.0`). До правки оба смешивались:
    `(pos.get("positions") or {})` превращало отсутствие поля в пустую книгу, а
    `float(pos.get("cash_usd") or 0.0)` — отсутствие кэша в измеренный ноль.
    """
    def _book(raw) -> dict | None:
        if not isinstance(raw, dict):
            return None
        out: dict[str, float] = {}
        for k, v in raw.items():
            try:
                out[str(k)] = round(float(v), 2)
            except (TypeError, ValueError):
                return None
        return out

    pos = _load("data/current_positions.json", root)
    same_day = isinstance(pos, dict) and str(pos.get("generated_at", ""))[:10] == day
    if same_day:
        book = _book(pos.get("positions"))
        if book is not None:
            raw_cash = pos.get("cash_usd")
            if raw_cash is None:
                return (book, None, "current_positions (тот же день)",
                        "поля cash_usd в снимке нет — null, не ноль")
            try:
                return (book, round(float(raw_cash), 2),
                        "current_positions (тот же день)",
                        "current_positions (тот же день)")
            except (TypeError, ValueError):
                return (book, None, "current_positions (тот же день)",
                        "cash_usd в снимке не число — null, не ноль")

    bars = []
    if isinstance(curve, dict) and isinstance(curve.get("daily"), list):
        bars = [b for b in curve["daily"]
                if isinstance(b, dict) and str(b.get("date")) == day]
    if bars:
        try:
            from spa_core.paper_trading.track_evidence import is_evidenced_bar
            ev = [b for b in bars if is_evidenced_bar(b)]
        except Exception as e:  # noqa: BLE001
            return (None, None, f"evidenced-признак бара не разобран: {e}", _NOT_MEASURED)
        if ev:
            book = _book(ev[-1].get("positions"))
            if book is not None:
                return (book, None,
                        "equity_curve_daily: книга закрытия из evidenced-бара дня "
                        "(тот же объект цикла, что и current_positions)",
                        "бар кривой не несёт cash_usd; выводить его из константы "
                        "капитала запрещено — null")
            return (None, None,
                    "в evidenced-баре дня нет разбираемых позиций — не измерено",
                    _NOT_MEASURED)
        return (None, None,
                "бар за день есть, но он не evidenced — книга не засчитывается",
                _NOT_MEASURED)

    return (None, None,
            ("current_positions не за этот день, бара за день в кривой нет"
             if not same_day else
             "снимок за этот день без разбираемых позиций, бара за день нет"),
            _NOT_MEASURED)


def build_outcome_line(root: str, day: str) -> dict:
    """Строка исхода за календарный день `day` — только из наблюдённого."""
    sources: dict[str, str] = {}

    equity_close = daily_return = None
    curve = _load("data/equity_curve_daily.json", root)
    if curve and isinstance(curve.get("daily"), list):
        try:
            from spa_core.paper_trading.track_evidence import is_evidenced_bar
            bars = [b for b in curve["daily"]
                    if isinstance(b, dict) and str(b.get("date")) == day]
            ev = [b for b in bars if is_evidenced_bar(b)]
            if ev:
                equity_close = float(ev[-1].get("close_equity") or ev[-1].get("equity"))
                dr = ev[-1].get("daily_return_pct")
                daily_return = float(dr) if dr is not None else None
                sources["equity"] = "equity_curve_daily:evidenced"
            elif bars:
                sources["equity"] = "бар дня не evidenced — не считается"
            else:
                sources["equity"] = "бара за день нет"
        except Exception as e:  # noqa: BLE001
            sources["equity"] = f"кривая не разобрана: {e}"
    else:
        sources["equity"] = "equity_curve_daily не прочитан"

    positions, cash, pos_src, cash_src = _resolve_book(root, day, curve)
    sources["positions"] = pos_src
    sources["cash"] = cash_src

    apy = None
    hist_path = os.path.join(root, "data", "allocation_rationale_history.jsonl")
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(rec.get("cycle_date")) == day and rec.get("apy_evidenced_pct"):
                        apy = rec["apy_evidenced_pct"]
            sources["apy"] = ("rationale_history (evidenced)" if apy
                              else "строки за день нет")
        except Exception as e:  # noqa: BLE001
            sources["apy"] = f"history не разобрана: {e}"
    else:
        sources["apy"] = "rationale_history отсутствует"

    posture = None
    vpath = os.path.join(root, "data", "investment_os", "chief_investment_verdicts.jsonl")
    if os.path.exists(vpath):
        try:
            with open(vpath, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(rec.get("date")) == day and rec.get("posture"):
                        posture = rec["posture"]
            sources["posture"] = ("chief_verdicts" if posture
                                  else "вердикта за день нет")
        except Exception as e:  # noqa: BLE001
            sources["posture"] = f"verdicts не разобраны: {e}"
    else:
        sources["posture"] = "архив вердиктов отсутствует"

    return {"schema": 1, "date": day, "equity_close": equity_close,
            "daily_return_pct": daily_return, "positions": positions,
            "cash_usd": cash, "apy_evidenced_pct": apy,
            "posture_office": posture, "sources": sources}


COMPLETENESS_SCHEMA = 1


def analyze_completeness(root: str = REPO_ROOT,
                         now: dt.datetime | None = None) -> dict:
    """Полнота архива по ЗАКРЫТЫМ дням — вопрос, на который возраст не отвечает.

    Возрастной бюджет B2 сторожа архитектуры судит о `outcomes.jsonl` по mtime, и
    для ЭТОГО артефакта это не тот вопрос: он не снимок, а append-only архив, где
    день без evidenced-бара НЕ занимается сознательно (`append_daily_outcome`:
    «дату не занимаем, догоним позже»). Значит возрастной бюджет обязан терпеть
    сутки ожидания + такт производителя (31ч) — и ровно столько же он терпит
    настоящую ОСТАНОВКУ записи. Здесь спрашивается другое: есть ли строка за
    каждый закрытый день, у которого был evidenced-бар. Такая проверка молчит на
    исправном ожидании (сегодняшний день ещё не закрыт; день без evidenced-бара
    строки не ждёт — 07-19/07-27 fail-closed by design) и краснеет в первые же
    часы после настоящего сбоя записи. Обе проверки остаются: зелёный ответ на
    свой вопрос не есть ответ на нужный.

    Время — ВХОД (`now=`), а не окружение: от него зависит, какой день закрыт.

    Якорь — ПЕРВЫЙ день архива: до него производителя не было, и требовать от
    него июньские дни значило бы сочинить находку. Цена якоря названа вслух и не
    замаскирована: усечение архива с головы двигает якорь вперёд и такую дыру
    скрывает — append-only-файл этого делать не должен, но проверка полноты
    сама по себе от усечения не защищает (`archived_days` печатается, чтобы
    сжавшийся архив был виден глазом).

    Вердикты: `measured: False` — мерить не от чего (пустой архив / кривая не
    прочитана), НИКОГДА не «полно». Молчаливого «всё в порядке» здесь нет.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(dt.timezone.utc).date()
    base = {"schema": COMPLETENESS_SCHEMA, "today": today.isoformat()}

    have = sorted({str(r.get("date")) for r in load_outcomes(root) if r.get("date")})
    if not have:
        return {**base, "measured": False, "archived_days": 0,
                "reason": "архив исходов пуст или отсутствует — якоря нет, полноту "
                          "мерить не от чего (на вопрос «файл вообще есть?» отвечает "
                          "возрастной бюджет B2, и это его вопрос)"}

    curve = _load("data/equity_curve_daily.json", root)
    if not curve or not isinstance(curve.get("daily"), list):
        return {**base, "measured": False, "archived_days": len(have),
                "anchor_date": have[0],
                "reason": "equity_curve_daily не прочитан — какие дни ОБЯЗАНЫ иметь "
                          "строку, неизвестно; «нет источника правды» это не «полно»"}

    try:
        from spa_core.paper_trading.track_evidence import is_evidenced_bar
        evidenced = sorted({str(b.get("date")) for b in curve["daily"]
                            if isinstance(b, dict) and b.get("date")
                            and is_evidenced_bar(b, today=today)})
    except Exception as e:  # noqa: BLE001
        return {**base, "measured": False, "archived_days": len(have),
                "anchor_date": have[0],
                "reason": f"evidenced-бары не измерены: {e}"}

    anchor = have[0]
    today_s = today.isoformat()
    # Закрытый день — строго РАНЬШЕ сегодняшнего: сегодняшний ещё может быть
    # дописан своим же тактом, и требовать его — та самая ложная тревога, из-за
    # которой возрастной бюджет пришлось растягивать до 31ч.
    expected = [d for d in evidenced if anchor <= d < today_s]
    present = set(have)
    missing = [d for d in expected if d not in present]
    return {**base, "measured": True, "anchor_date": anchor,
            "archived_days": len(have), "expected_days": len(expected),
            "present_days": len(expected) - len(missing),
            "missing_days": missing, "complete": not missing,
            "reason": ("за каждый закрытый evidenced-день с якоря архива есть строка"
                       if not missing else
                       f"строк нет за {len(missing)} закрыт(ых) evidenced-дн(я/ей): "
                       + ", ".join(missing[:10])
                       + (" …" if len(missing) > 10 else ""))}


def append_daily_outcome(root: str = REPO_ROOT,
                         now: dt.datetime | None = None) -> dict:
    """Дописать строку за СЕГОДНЯ, если её ещё нет. Идемпотентно по дате.

    Возвращает {"appended": bool, "date": ..., "line"| "reason"}.
    День без evidenced-equity НЕ пишется (пустая строка исхода бессмысленна и
    навсегда заняла бы дату) — decision_loop дозапишет позже тем же днём.

    Пропущенный день этот производитель НЕ догоняет по построению (он знает
    только «сегодня») — для дыр есть отдельная осознанная команда
    `backfill_outcomes`, см. ниже, почему она отдельная.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    day = now.date().isoformat()
    existing = {str(r.get("date")) for r in load_outcomes(root)}
    if day in existing:
        return {"appended": False, "date": day, "reason": "уже записан"}
    line = build_outcome_line(root, day)
    if line["equity_close"] is None:
        return {"appended": False, "date": day,
                "reason": f"нет evidenced-equity за день ({line['sources'].get('equity')}) — "
                          f"дату не занимаем, догоним позже"}
    path = os.path.join(root, OUTCOMES_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return {"appended": True, "date": day, "line": line}


# --- дозапись пропущенных дней (карточка #258 → цикл #271) -------------------
#
# Почему это ОТДЕЛЬНАЯ команда, а не шаг моста. Находка `retro:outcomes_incomplete`
# означает ОСТАНОВКУ записи. Автоматическая дозапись каждым прогоном затянула бы
# дыру раньше, чем её кто-нибудь увидит: находка исчезала бы сама, причина
# остановки — нет. Это ровно тот обмен, который правило класса запрещает
# (сторож, который сам себя лечит, перестаёт быть сторожом). Поэтому дозапись
# зовут руками/шагом разбора, а находка держится до тех пор.
#
# Что дозапись НЕ делает:
#   * не двигает якорь архива (дни РАНЬШЕ первой строки не сочиняются: до
#     появления производителя его и не было — требовать от него июнь значило бы
#     выдумать историю). Диапазон `--since` раньше якоря просто ничего не даёт;
#   * не трогает `data/equity_curve_daily.json` — живой трек, только чтение;
#   * не переписывает и не удаляет ни одной уже существующей строки: если слияние
#     хотя бы одну потеряло бы или изменило — отказ без записи (fail-CLOSED).

def _merge_sorted_by_date(raw_lines: list[str], new_lines: list[dict]) -> list[str]:
    """Слить старые строки (как есть, дословно) с новыми, по дате, устойчиво.

    Порядок дат в файле — свойство, на которое читатель вправе опереться, а дыра
    затыкается в СЕРЕДИНЕ, поэтому чистый append её бы нарушил. Устойчивость
    сортировки означает: строки с одной датой сохраняют исходный взаимный
    порядок, а новые встают ПОСЛЕ одноимённых старых (их и так быть не должно —
    дозапись идёт только по отсутствующим датам).
    """
    def _date_of(text: str) -> str:
        try:
            return str(json.loads(text).get("date") or "")
        except json.JSONDecodeError:
            return ""

    items = [(_date_of(t), 0, t) for t in raw_lines]
    items += [(str(ln["date"]), 1, json.dumps(ln, ensure_ascii=False))
              for ln in new_lines]
    # Битые/бездатные строки (date == "") ушли бы в начало и молча перемешались
    # с настоящими — оставляем их на исходных местах головой файла, а сортируем
    # только датированное.
    dated = sorted([i for i in items if i[0]], key=lambda i: (i[0], i[1]))
    undated = [i for i in items if not i[0]]
    return [t for _, _, t in undated + dated]


def backfill_outcomes(root: str = REPO_ROOT,
                      since: str | None = None,
                      until: str | None = None,
                      now: dt.datetime | None = None,
                      dry_run: bool = False) -> dict:
    """Дозаписать строки за пропущенные ЗАКРЫТЫЕ evidenced-дни. Идемпотентно.

    Диапазон задаётся явно (`since`/`until`, ISO-даты включительно); без него
    берутся все дыры, которые назвала `analyze_completeness`. Полнота — это и
    есть источник списка: другого определения «какие дни обязаны иметь строку»
    в репозитории нет, и заводить второе значило бы получить два ответа на один
    вопрос.

    Честность полей та же, что у ежедневной записи: недостающее остаётся `null`
    с причиной в `sources`. Замер 2026-08-17 на живом проде: за прошлый день
    восстанавливаются `equity_close`, `daily_return_pct` (кривая датирована),
    `apy_evidenced_pct` (`allocation_rationale_history` по `cycle_date`) и
    `posture_office` (архив вердиктов по `date`). Замер 2026-08-18 уточнил
    книгу: ПОЗИЦИИ на закрытии восстанавливаются из датированного evidenced-бара
    кривой — туда `cycle_runner` кладёт тот же объект `effective_positions`, что
    и в снимок `current_positions.json`; НЕ восстанавливается только `cash_usd`
    (бар его не несёт, а вывести из константы капитала — подмена наблюдения).
    Книга НА ВХОДЕ цикла из `allocation_rationale_history` и `target_positions`
    по-прежнему не берутся: это другая величина и намерение соответственно.

    `measured: False` — мерить не от чего (полнота не измерена): НИЧЕГО не
    пишем. «Не знаю, какие дни нужны» это не «нужных дней нет».
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    comp = analyze_completeness(root, now=now)
    base = {"schema": COMPLETENESS_SCHEMA, "today": comp["today"],
            "requested": {"since": since, "until": until},
            "dry_run": bool(dry_run)}
    if not comp.get("measured"):
        return {**base, "measured": False, "written": [], "skipped": [],
                "reason": "полнота не измерена, дозаписывать нечего: "
                          + str(comp.get("reason"))}

    missing = list(comp.get("missing_days") or [])
    targets = [d for d in missing
               if (since is None or d >= since) and (until is None or d <= until)]
    out_of_range = [d for d in missing if d not in targets]

    written: list[dict] = []
    skipped: list[dict] = []
    for day in targets:
        line = build_outcome_line(root, day)
        if line["equity_close"] is None:
            # Дню полагалась строка (он evidenced по кривой), а сборка equity не
            # дала — это расхождение двух чтений одной кривой, и молчать о нём
            # нельзя: дыра останется, причина будет названа.
            skipped.append({"date": day, "reason": str(line["sources"].get("equity"))})
            continue
        # Пометка дозаписи говорит, что вышло НА САМОМ ДЕЛЕ по этой строке, а не
        # заранее заготовленную фразу: раньше здесь стояло безусловное «позиции и
        # кэш не восстановимы», и после того как книга стала восстановимой из
        # датированного бара, эта фраза стала бы враньём в каждой строке.
        line["sources"]["backfill"] = (
            "дозапись задним числом; книга: "
            + ("восстановлена — " if line["positions"] is not None else "НЕ восстановлена — ")
            + str(line["sources"].get("positions"))
            + "; кэш: "
            + ("восстановлен" if line["cash_usd"] is not None else "НЕ восстановлен")
            + " — " + str(line["sources"].get("cash")))
        written.append(line)

    result = {**base, "measured": True, "anchor_date": comp.get("anchor_date"),
              "missing_before": missing, "out_of_range": out_of_range,
              "written": [ln["date"] for ln in written], "skipped": skipped,
              "lines": written}
    if not written or dry_run:
        result["reason"] = ("нечего дозаписывать: дыр в диапазоне нет"
                            if not written else
                            f"сухой прогон: дозаписал бы {len(written)} дн.")
        return result

    path = os.path.join(root, OUTCOMES_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw: list[str] = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            raw = [ln.rstrip("\n") for ln in f if ln.strip()]
    merged = _merge_sorted_by_date(raw, written)

    # fail-CLOSED: слияние обязано быть ЧИСТО ДОБАВЛЯЮЩИМ. Считаем по кратности,
    # а не по множеству: пропажа одного из двух одинаковых дублей — тоже потеря.
    from collections import Counter
    lost = Counter(raw) - Counter(merged)
    if lost:
        result["reason"] = ("отказ: слияние потеряло бы "
                            f"{sum(lost.values())} существующ(ую/их) строк(у/и) — "
                            "архив не тронут")
        result["written"] = []
        result["refused"] = True
        return result

    dir_ = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join(t + "\n" for t in merged))
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    after = analyze_completeness(root, now=now)
    result["missing_after"] = list(after.get("missing_days") or [])
    result["complete_after"] = bool(after.get("complete"))
    result["reason"] = (f"дозаписано {len(written)} дн.: "
                        + ", ".join(result["written"]))
    return result


def main(argv=None) -> int:  # pragma: no cover — тонкая обёртка над функциями
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--completeness", action="store_true",
                    help="напечатать отчёт о полноте архива и выйти")
    ap.add_argument("--backfill", action="store_true",
                    help="дозаписать строки за пропущенные закрытые evidenced-дни")
    ap.add_argument("--since", help="нижняя граница диапазона, ISO-дата (включительно)")
    ap.add_argument("--until", help="верхняя граница диапазона, ISO-дата (включительно)")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать, что было бы дозаписано, и не писать")
    args = ap.parse_args(argv)
    if args.completeness or not args.backfill:
        rep = analyze_completeness(args.root)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        if not args.backfill:
            return 0 if rep.get("complete") else 1
    rep = backfill_outcomes(args.root, since=args.since, until=args.until,
                            dry_run=args.dry_run)
    print(json.dumps({k: v for k, v in rep.items() if k != "lines"},
                     ensure_ascii=False, indent=2))
    if not rep.get("measured"):
        return 2
    return 0 if not rep.get("skipped") and not rep.get("refused") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
