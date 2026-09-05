"""adapter_feed_divergence.py — два артефакта ОДНОГО цикла говорят о ОДНОМ протоколе разное.

Вопрос, на который не отвечал ни один сторож
============================================
Про адаптеры уже спрашивают трёх сторожей, и каждый честно отвечает на СВОЙ вопрос:

| вопрос | кто отвечает | чего НЕ проверяет |
|---|---|---|
| фид вообще жив? | `adapter_watchdog` | сходятся ли два фида между собой |
| число живое или литерал? | провенанс `tvl_source`/`live_apy` ВНУТРИ одного артефакта | второй артефакт |
| адаптер импортируется? | `deployment_acceptance` | что он отдаёт |

Ни один не спрашивает: **`data/adapter_status.json` и
`data/adapter_orchestrator_status.json` — говорят ли они об одном протоколе одно и
то же.** Замер 2026-08-26 22:0xZ (цикл #389), оба файла произведены с разницей
0.6 секунды одним дневным циклом:

    pendle:  adapter_status  apy 8.0    live_apy=null  tier 2   tvl $500 000 000 (static)
             orchestrator    apy 13.9673 live_data=true tier T3  tvl $6 151 592   (live)

Один протокол, один цикл, **1.75× по доходности и РАЗНЫЙ ТИР** — а тир решает
потолок концентрации (T2 20 % против T3). Это `pendle`, то есть 20 % книги, и
ровно то число, которое диагностика CIO (`docs/research/RS-portfolio-cio-diagnosis.md`)
назвала «единственные $20k, ранжированные по наблюдённому числу». Дефект D6 ADR-060
описан 02.08 и жив 25 дней спустя ДОСЛОВНО — потому что его никто не мерил повторно:
находка была записана в карточку, а не в сторожа.

Что этот модуль НЕ делает
=========================
Не выбирает победивший источник, не двигает капитал, не гейтит исполнение и не
трогает RiskPolicy. **Только называет расхождение.** Выбор источника для 20 % книги —
решение владельца (карточка), а не автономная правка.

Почему расхождения разделены по РОДУ (главное решение дизайна)
==============================================================
Свалить всё в «фиды разошлись» значило бы соврать в двух местах сразу.

* ``live_vs_live`` — **обе** стороны заявляют живое наблюдение ОДНОГО И ТОГО ЖЕ
  пула, а числа разные. Только это — противоречие двух наблюдений, и только оно
  поднимает инвариант 2 (fail-CLOSED при расхождении фидов). CRITICAL.
* ``apy_identity_mismatch`` — обе стороны наблюдали живое, но **РАЗНЫЕ ПУЛЫ**
  (ADR-233). Наблюдения при этом ВЕРНЫ ОБА, и «противоречие фидов» — неверный
  диагноз: чинится ЗАКРЕПЛЕНИЕМ пула за ключом, а fail-CLOSED не лечит ничего.
  CRITICAL — тяжесть та же, адрес починки другой.

  Замер 2026-09-05 (цикл #492), ``aave_v3`` — 40 % книги, крупнейшая позиция.
  У ключа в живом фиде ЧЕТЫРЕ кандидата ``aave-v3``/Ethereum/USDC::

      aa70268e…  $153.55M  3.587 пп  ядро рынка, underlying USDC
      6f00d46b…  $ 58.62M  5.247 пп  "Umbrella", underlying 0xD4fa… — НЕ USDC,
                                     1.66 пп из них — эмиссия (apyReward)
      effcb4a4…  $  1.53M  2.580 пп  "Prime Instance"
      27296bf9…  $  0.65M  4.372 пп  "Aave Horizon Market"

  Стороны отбирают из РАЗНЫХ множеств: генератор ``adapter_status`` фильтрует по
  каноническому underlying (``_CANONICAL_UNDERLYING``) и «Umbrella» отвергает,
  а путь адаптера (``DeFiLlamaFeed.get_pool``, точное совпадение символа) про
  underlying не спрашивает вовсе. Пока ядро рынка в снимке есть, побеждает оно у
  обоих и расхождения нет. Стоит ядру из снимка выпасть — генератор падает на
  ``effcb4a4…`` (2.58), адаптер на ``6f00d46b…`` (5.25). Воспроизведено удалением
  одного пула из живого фида ЧЕРЕЗ НАСТОЯЩИХ ВЫЗЫВАЮЩИХ: 2.58038 против 5.24713,
  разрыв 2.6668 пп — против записанных в снимке 06:00Z 2.5804 против 5.2651
  (2.6847 пп).

  **Прежний диагноз этого расхождения (цикл #470, 03.09) замером ОПРОВЕРГНУТ.**
  Он гласил: «числа расходятся ровно тогда, когда расходятся ОТМЕТКИ НАБЛЮДЕНИЯ»,
  и предлагал переименовать находку в ``apy_stale_copy_vs_live`` (WARN). В снимке
  05.09 06:00Z отметки наблюдения разошлись на 2.16 с у ВСЕХ ДЕВЯТИ общих
  протоколов, восемь из девяти сошлись до четвёртого знака, и разошёлся ровно
  один — ``aave_v3``. Разрыв отметок есть свойство пары АРТЕФАКТОВ (их пишет один
  дневной цикл), а не протокола, и объяснить им расхождение ОДНОГО из девяти
  нельзя. Переименование в WARN понизило бы тяжесть настоящего дефекта по
  неверной причине — поэтому не сделано.
* ``pool_identity_mismatch`` — пулы разные, а числа сегодня совпали. WARN: это
  совпадение, а не согласие, и завтрашний порядок TVL решит иначе.

**Личность едет ПОЛЕМ ``identity`` (``same``/``different``/``unchecked``), а не
новым именем рода.** Ключ журнала (ADR-207) — «протокол:род»; переименуй род для
артефактов без метки — и накопленный с 01.09 ряд ``aave_v3:apy_live_vs_live``
разорвался бы надвое, счётчик рецидива молча начался бы с нуля, а шаг 0-офис
перестал бы печатать ``↺``. Третий исход при этом не теряется: при
``identity="unchecked"`` сообщение прямо говорит, что адрес починки НЕ ИЗМЕРЕН,
потому что «личность не названа» и «пул тот же» — разные ответы.
* ``literal_vs_live`` — одна сторона живая, вторая подставила ``fallback``, потому
  что не получила чтения. Это **не** спор наблюдений: вторая сторона не наблюдала
  ничего. Ровно это уточнение стоит дословно в карточке D6
  (`agent-tuner-constraints-drift-and-feed-divergence`), и потерять его нельзя —
  иначе починка поедет не туда. WARN.
* ``both_literal`` — не наблюдал НИКТО, и потребитель видит два литерала. Числа могут
  совпасть до знака, и «сошлось» будет означать «одинаково выдумано». INFO, но
  вслух: молчание здесь неотличимо от согласия двух измерений.
* ``tier_mismatch`` — стороны кладут протокол в РАЗНЫЕ тиры. Отдельный род, потому
  что последствие другое: тир — это потолок концентрации, а не число в отчёте.

**TVL сравнивается ЧИСЛОМ только когда обе стороны заявили ``live``.** Иначе
сравнивались бы литерал и наблюдение, и сторож краснел бы каждый день на 6 из 8
протоколов — на состоянии, которое УЖЕ названо и УЖЕ решено (ADR-053: константа
порог TVL не проходит; карточка про $12B у aave_v3 открыта). Сторож, который каждый
день кричит о решённом, обучает себя игнорировать: расхождение провенанса пишется
как ``tvl_provenance`` (INFO), а не как противоречие.

Чем измеряется «один цикл» (иначе сравниваются два МОМЕНТА, а не два фида)
=========================================================================
Если артефакты произведены далеко друг от друга, разные числа — нормальная жизнь
рынка, а не расхождение фидов. Поэтому:

* разрыв отметок больше ``MAX_SKEW_S`` ⇒ вся сверка ``UNCHECKED`` (``snapshot_skew``),
  вердикт не выносится вовсе;
* любой вход старше ``MAX_AGE_S`` ⇒ ``UNCHECKED`` (``stale_input``) — сторож не имеет
  права говорить в настоящем времени о вчерашнем снимке (урок #222);
* возраст не измерен ⇒ это ГОВОРИТСЯ, а не подразумевается свежим.

Время — ВХОД (``now=``), а не окружение: правило `.claude/rules/deployment.md`.

Память о расхождениях (ADR-206): «мигает» и «живёт» — РАЗНЫЕ ответы
=================================================================
Отчёт ``data/adapter_feed_divergence.json`` перезаписывается каждым прогоном
(``atomic_save`` поверх). Пока это был единственный след, вопрос **«сколько раз за
последние N суток два ЖИВЫХ наблюдения одного пула разошлись и на сколько»** был
неразрешим ПО ПОСТРОЕНИЮ — не «мы не считали», а «считать нечем». Замер карточки
`inbox-critical-storozha-fidov-migaet-aave-v3-r` это и показал: 27.08 01:14Z у
``aave_v3`` было 1.69 пп, в 05:27Z — сошлись, 31.08 — 6.04 пп со СМЕНОЙ ЗНАКА,
01.09 — 6.23 пп. Три точки собраны РУКАМИ трёх разных циклов, каждый мерил заново,
и вывод «мигание само гаснет» дожил до опровержения только потому, что кто-то
случайно посмотрел в нужную секунду.

Поэтому каждая находка ``CRITICAL``/``WARN`` дописывается в append-only журнал
``data/adapter_feed_divergence_log.jsonl``; ``history()`` отвечает на вопрос карточки
ЧИСЛОМ. Три решения, без которых журнал врал бы:

* **Единица счёта — СНИМОК, а не прогон.** Оба входа пишет дневной цикл (раз в
  сутки), а сторожа зовёт ``com.spa.decision_loop`` (часто). Без ключа снимка
  «расходились 24 раза» означало бы «мы 24 раза посмотрели на ОДНО наблюдение».
  Ключ — пара отметок ``generated_at`` обоих входов; повтор того же снимка в журнал
  НЕ попадает.
* **Слепота записывается ОТДЕЛЬНОЙ строкой** (``kind: "unchecked"``). Иначе «за трое
  суток расхождений нет» было бы неотличимо от «трое суток сторож отказывался
  судить» — инвариант #17 ровно об этом. Согласие строки НЕ пишет (это условие
  приёмки карточки), а вот отказ судить — пишет.
* **Окно ответа обрезается возрастом журнала.** ``history(days=30)`` по журналу
  возрастом двое суток возвращает ``covered_days: 2`` и ``window_truncated: True``:
  «0 расхождений за 30 суток» на двухдневном журнале — не хорошая новость, а
  ненаблюдение, и оно обязано называться.

Ротация: ``LOG_MAX_LINES`` самых свежих строк, перезапись через tmp + ``os.replace``.

Fail-CLOSED
===========
Файла нет / JSON битый / нет секции адаптеров ⇒ ``UNCHECKED`` и код возврата 2.
**Пересечение пусто («ни одного общего протокола») ⇒ CRITICAL, а не чистый зачёт:**
сторож, которому нечего было сравнить, обязан отличаться от сторожа, который сравнил
и не нашёл расхождений.

Коды возврата: 0 — сошлось · 1 — есть WARN · 2 — CRITICAL или UNCHECKED.
LLM_FORBIDDEN. Только stdlib. Читает read-only, пишет ОДИН свой артефакт.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT, _parse_iso
from spa_core.utils.atomic import atomic_save

REPORT_REL = os.path.join("data", "adapter_feed_divergence.json")
LOG_REL = os.path.join("data", "adapter_feed_divergence_log.jsonl")
STATUS_REL = os.path.join("data", "adapter_status.json")
ORCH_REL = os.path.join("data", "adapter_orchestrator_status.json")

#: Максимальный разрыв между отметками двух артефактов, при котором они ещё считаются
#: снимками ОДНОГО такта. Замер 26.08: 0.6 с (оба пишет дневной цикл подряд). Потолок
#: взят с запасом на медленный опрос адаптеров (`duration_sec` оркестратора ~1.2 с,
#: полный опрос 34 адаптеров исполнения — минуты), но не настолько большим, чтобы
#: под него подлез снимок соседнего часа.
MAX_SKEW_S = 900.0

#: Старше этого — сверка отказывается судить. 26 ч: такт дневного цикла (24 ч) плюс
#: запас, тот же порядок, что `slo_hours: 26` у артефактов дневного цикла в манифесте.
MAX_AGE_S = 26 * 3600.0

#: Допуск сравнения доходности, процентных пунктов. Обе стороны печатают округлённое
#: до 4 знаков, поэтому шум округления — единицы 1e-4; порог на два порядка выше него
#: и на два порядка ниже наблюдённого расхождения (5.97 пп).
APY_TOLERANCE_PP = 0.01

#: Допуск сравнения TVL, доля. Живые TVL двух независимых опросов одного пула
#: расходятся на движении блока; 1 % — шум, больше — разные предметы.
TVL_TOLERANCE_FRAC = 0.01

CRITICAL, WARN, INFO, UNCHECKED = "CRITICAL", "WARN", "INFO", "UNCHECKED"

#: Потолок журнала расхождений, строк. При такте дневного цикла (1 снимок в сутки)
#: и 8-11 сверяемых протоколах это годы истории; ограничение стоит не ради места,
#: а чтобы файл не рос неограниченно на аварийном режиме (каждый прогон — новый
#: снимок). Ротация оставляет САМЫЕ СВЕЖИЕ строки.
LOG_MAX_LINES = 5000

#: Рода находок, попадающих в журнал. Согласие строки не пишет — это условие приёмки
#: карточки `inbox-critical-storozha-fidov-migaet-aave-v3-r`. INFO не пишется тоже:
#: `tvl_provenance` — состояние УЖЕ названное и решённое (ADR-053), и в журнале
#: рецидивов ему делать нечего.
LOGGED_SEVERITIES = (CRITICAL, WARN)

#: Окно, за которое отчёт носит ответ «сколько раз и на сколько» с собой. Семь суток —
#: тот же порядок, что `slo_hours: 7` у самого артефакта в манифесте: вопрос карточки
#: про «мигает или живёт», а такое различие видно на днях, не на часах.
HISTORY_WINDOW_DAYS = 7.0


def _load(rel: str, root: str):
    """``(data, reason)`` — ``reason`` непуст ⇒ вход НЕ прочитан (fail-CLOSED)."""
    path = os.path.join(root, rel)
    try:
        with open(path) as fh:
            return json.load(fh), ""
    except FileNotFoundError:
        return None, f"файла нет на диске: {rel}"
    except (OSError, ValueError) as e:  # noqa: BLE001
        return None, f"{rel} не прочитан: {e}"


def _norm_tier(value) -> str | None:
    """``1``/``"1"``/``"T1"`` → ``"T1"``. Неузнанное — ``None`` («не измерено»).

    Две стороны пишут тир РАЗНЫМ типом (исполнение — целым, оркестратор — строкой),
    и сравнение без нормализации объявило бы расхождением любую пару.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return f"T{int(value)}"
    text = str(value).strip().upper()
    if not text:
        return None
    if text.startswith("T") and text[1:].isdigit():
        return text
    if text.isdigit():
        return f"T{int(text)}"
    return None


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _observed_apy_status(entry: dict) -> tuple[float | None, float | None]:
    """Сторона `adapter_status.json`: ``(наблюдённое, предъявленное потребителю)``.

    Наблюдённым считается ТОЛЬКО ``live_apy``; ``apy`` может быть равен ему, а может
    быть ``fallback_apy`` — по самому ``apy`` эти два случая неразличимы, и именно на
    этой неразличимости построен fail-OPEN провенанс, найденный ADR-060 §1.2.
    """
    return _num(entry.get("live_apy")), _num(entry.get("apy"))


def _observed_apy_orch(entry: dict) -> tuple[float | None, float | None]:
    """Сторона оркестратора: наблюдённым считается ``apy_pct`` при ``live_data: true``."""
    shown = _num(entry.get("apy_pct"))
    return (shown if entry.get("live_data") is True else None), shown


def _resolved_pool(entry: dict) -> str | None:
    """Личность пула, РАЗРЕШЁННОГО этой стороной, или ``None`` («не измерено»).

    Обе стороны пишут её в поле ``pool_id``: ``adapter_status`` — с ADR-230,
    снимок оркестратора — с ADR-233. Пустая строка личностью не считается.
    """
    value = entry.get("pool_id")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _identity_verdict(s: dict, o: dict) -> tuple[str, str | None, str | None]:
    """``("same"|"different"|"unchecked", пул_status, пул_orchestrator)``.

    ``unchecked`` — когда ХОТЯ БЫ одна сторона личность не назвала. Это третий
    исход, а не «пул тот же»: молчание о личности неотличимо от согласия только
    для того, кто согласие и хотел увидеть.
    """
    s_pool, o_pool = _resolved_pool(s), _resolved_pool(o)
    if s_pool is None or o_pool is None:
        return "unchecked", s_pool, o_pool
    return ("same" if s_pool.lower() == o_pool.lower() else "different"), s_pool, o_pool


def _finding(protocol: str, kind: str, severity: str, message: str, **extra) -> dict:
    rec = {"protocol": protocol, "kind": kind, "severity": severity, "message": message}
    rec.update(extra)
    return rec


def _compare_protocol(protocol: str, s: dict, o: dict) -> list[dict]:
    """Все расхождения по одному протоколу. Нечитаемая сторона ⇒ ``UNCHECKED``-запись."""
    out: list[dict] = []

    # ── доходность ───────────────────────────────────────────────────────────
    s_live, s_shown = _observed_apy_status(s)
    o_live, o_shown = _observed_apy_orch(o)
    if s_shown is None or o_shown is None:
        out.append(_finding(
            protocol, "apy", UNCHECKED,
            f"{protocol}: доходность не измерена — "
            f"adapter_status={'нет числа' if s_shown is None else s_shown}, "
            f"orchestrator={'нет числа' if o_shown is None else o_shown}",
            adapter_status_apy=s_shown, orchestrator_apy=o_shown))
    elif s_live is not None and o_live is not None:
        delta = abs(s_live - o_live)
        # ADR-233. «Оба наблюдали и разошлись» — это ДВА разных дефекта с
        # ПРОТИВОПОЛОЖНОЙ починкой, и до сих пор они звались одним именем:
        #   • один пул, два числа  ⇒ противоречие наблюдений, инвариант 2, fail-CLOSED;
        #   • два пула, два числа  ⇒ наблюдения ВЕРНЫ ОБА, они о разных инструментах;
        #     чинится закреплением пула, а fail-CLOSED тут не лечит ничего.
        # Тяжесть у всех исходов одна (CRITICAL) — меняется адрес починки, а не
        # громкость. Ослабления здесь нет и быть не должно.
        identity, s_pool, o_pool = _identity_verdict(s, o)
        if delta > APY_TOLERANCE_PP:
            if identity == "different":
                out.append(_finding(
                    protocol, "apy_identity_mismatch", CRITICAL,
                    f"{protocol}: стороны наблюдали РАЗНЫЕ ПУЛЫ и потому разошлись — "
                    f"adapter_status {s_live} пп (пул {s_pool}) против orchestrator "
                    f"{o_live} пп (пул {o_pool}), разница {round(delta, 4)} пп. "
                    f"Это НЕ противоречие двух наблюдений: оба верны, но об разных "
                    f"инструментах. Починка — ЗАКРЕПИТЬ пул за ключом, а не выбрать "
                    f"число; fail-CLOSED здесь не лечит ничего",
                    adapter_status_apy=s_live, orchestrator_apy=o_live,
                    delta_pp=round(delta, 4), identity=identity,
                    adapter_status_pool=s_pool, orchestrator_pool=o_pool))
            else:
                # ИМЯ РОДА здесь НЕ меняется — ни при `same`, ни при `unchecked`.
                # Ключ журнала (ADR-207) — «протокол:род», и переименование рода
                # для непомеченных артефактов разорвало бы накопленный ряд
                # `aave_v3:apy_live_vs_live` (с 01.09) на два: счётчик рецидива
                # молча начался бы с нуля, а шаг 0-офис перестал бы печатать `↺`.
                # Сторож, чинящий диагноз ценой потери памяти о рецидиве, лечит
                # одно и ломает другое. Поэтому личность едет ПОЛЕМ, а третий
                # исход говорится СЛОВАМИ в том же сообщении.
                if identity == "same":
                    tail = (f"Стороны наблюдают ОДИН пул ({s_pool}), значит это "
                            f"противоречие ДВУХ наблюдений: инвариант 2 требует "
                            f"fail-CLOSED, а потребитель выбирает молча")
                else:
                    silent = "adapter_status" if s_pool is None else "orchestrator"
                    tail = (f"ЛИЧНОСТЬ ПУЛА не названа стороной {silent} ⇒ НЕ ИЗМЕРЕНО, "
                            f"об одном ли инструменте спор. Пока это не измерено, "
                            f"адрес починки (закрепить пул против fail-CLOSED) "
                            f"назвать нельзя — «не названа» и «пул тот же» это "
                            f"разные ответы")
                out.append(_finding(
                    protocol, "apy_live_vs_live", CRITICAL,
                    f"{protocol}: ОБА фида заявляют живое наблюдение и не сходятся — "
                    f"adapter_status {s_live} пп против orchestrator {o_live} пп "
                    f"(разница {round(delta, 4)} пп). {tail}",
                    adapter_status_apy=s_live, orchestrator_apy=o_live,
                    delta_pp=round(delta, 4), identity=identity,
                    adapter_status_pool=s_pool, orchestrator_pool=o_pool))
        elif identity == "different":
            # Числа сегодня сошлись, а пулы разные — совпадение, а не согласие:
            # ключ не закреплён, и завтрашний порядок TVL даст другое число.
            out.append(_finding(
                protocol, "pool_identity_mismatch", WARN,
                f"{protocol}: стороны разрешают ключ в РАЗНЫЕ пулы "
                f"(adapter_status {s_pool}, orchestrator {o_pool}), а числа сегодня "
                f"сошлись ({s_live} пп против {o_live} пп). Это совпадение, а не "
                f"согласие: ключ не закреплён, и порядок TVL решает за нас",
                adapter_status_apy=s_live, orchestrator_apy=o_live,
                delta_pp=round(delta, 4), identity=identity,
                adapter_status_pool=s_pool, orchestrator_pool=o_pool))
    elif s_live is None and o_live is None:
        out.append(_finding(
            protocol, "apy_both_literal", INFO,
            f"{protocol}: живого наблюдения доходности нет НИ У ОДНОЙ стороны — "
            f"потребителю предъявлены два литерала ({s_shown} пп и {o_shown} пп). "
            f"Совпадение чисел здесь означало бы «одинаково выдумано», а не согласие",
            adapter_status_apy=s_shown, orchestrator_apy=o_shown))
    else:
        live_side, live_val = ("orchestrator", o_live) if s_live is None else ("adapter_status", s_live)
        dead_side, dead_val = ("adapter_status", s_shown) if s_live is None else ("orchestrator", o_shown)
        delta = abs(live_val - dead_val)
        if delta > APY_TOLERANCE_PP:
            out.append(_finding(
                protocol, "apy_literal_vs_live", WARN,
                f"{protocol}: {live_side} наблюдает {live_val} пп, а {dead_side} "
                f"предъявляет литерал {dead_val} пп (разница {round(delta, 4)} пп). "
                f"Это НЕ спор двух наблюдений — вторая сторона не наблюдала ничего; "
                f"починка — дать ей фид, а не выбрать число",
                live_side=live_side, live_apy=live_val,
                literal_side=dead_side, literal_apy=dead_val,
                delta_pp=round(delta, 4)))

    # ── тир (потолок концентрации, а не строка в отчёте) ─────────────────────
    s_tier, o_tier = _norm_tier(s.get("tier")), _norm_tier(o.get("tier"))
    if s_tier is None or o_tier is None:
        out.append(_finding(
            protocol, "tier", UNCHECKED,
            f"{protocol}: тир не измерен — adapter_status={s.get('tier')!r}, "
            f"orchestrator={o.get('tier')!r}",
            adapter_status_tier=s.get("tier"), orchestrator_tier=o.get("tier")))
    elif s_tier != o_tier:
        out.append(_finding(
            protocol, "tier_mismatch", WARN,
            f"{protocol}: стороны кладут протокол в РАЗНЫЕ тиры — "
            f"adapter_status {s_tier}, orchestrator {o_tier}. Тир — это потолок "
            f"концентрации, а не подпись: два ответа означают два разных потолка "
            f"на один и тот же капитал",
            adapter_status_tier=s_tier, orchestrator_tier=o_tier))

    # ── TVL: числом — только когда ОБЕ стороны заявили живое ─────────────────
    s_tvl_live = str(s.get("tvl_source") or "").lower() == "live"
    o_tvl_live = str(o.get("tvl_source") or "").lower() == "live"
    s_tvl, o_tvl = _num(s.get("tvl_usd")), _num(o.get("tvl_usd"))
    if s_tvl_live and o_tvl_live:
        if s_tvl is None or o_tvl is None:
            out.append(_finding(
                protocol, "tvl", UNCHECKED,
                f"{protocol}: обе стороны заявили живой TVL, но числа нет — "
                f"adapter_status={s.get('tvl_usd')!r}, orchestrator={o.get('tvl_usd')!r}",
                adapter_status_tvl=s.get("tvl_usd"), orchestrator_tvl=o.get("tvl_usd")))
        else:
            base = max(abs(s_tvl), abs(o_tvl))
            if base > 0 and abs(s_tvl - o_tvl) / base > TVL_TOLERANCE_FRAC:
                out.append(_finding(
                    protocol, "tvl_live_vs_live", CRITICAL,
                    f"{protocol}: ОБА фида заявляют живой TVL и не сходятся — "
                    f"adapter_status ${s_tvl:,.0f} против orchestrator ${o_tvl:,.0f}. "
                    f"Порог TVL проверяется ТОЛЬКО живым числом (ADR-053), "
                    f"а живых чисел здесь два",
                    adapter_status_tvl=s_tvl, orchestrator_tvl=o_tvl))
    elif s_tvl_live != o_tvl_live:
        live_side = "orchestrator" if o_tvl_live else "adapter_status"
        out.append(_finding(
            protocol, "tvl_provenance", INFO,
            f"{protocol}: живой TVL есть только у стороны {live_side} "
            f"(adapter_status ${s_tvl if s_tvl is not None else float('nan'):,.0f} "
            f"[{s.get('tvl_source')}], orchestrator "
            f"${o_tvl if o_tvl is not None else float('nan'):,.0f} "
            f"[{o.get('tvl_source')}]). Состояние НАЗВАНО и решено (ADR-053: "
            f"константа порог не проходит) — здесь оно только зафиксировано, "
            f"противоречием наблюдений не является",
            adapter_status_tvl=s_tvl, orchestrator_tvl=o_tvl,
            adapter_status_tvl_source=s.get("tvl_source"),
            orchestrator_tvl_source=o.get("tvl_source")))
    return out


def _protocols(status_doc, orch_doc) -> tuple[dict, dict, list[str]]:
    """``(по_имени_из_adapter_status, по_имени_из_оркестратора, причины)``."""
    reasons: list[str] = []
    s_map: dict = {}
    raw_s = (status_doc or {}).get("adapters")
    if isinstance(raw_s, dict):
        s_map = {k: v for k, v in raw_s.items() if isinstance(v, dict)}
    else:
        reasons.append("adapter_status.json: секции `adapters` нет или она не объект — "
                       "сравнивать нечем")
    o_map: dict = {}
    raw_o = (orch_doc or {}).get("adapters")
    if isinstance(raw_o, list):
        for rec in raw_o:
            if isinstance(rec, dict) and rec.get("protocol"):
                o_map[str(rec["protocol"])] = rec
    else:
        reasons.append("adapter_orchestrator_status.json: секции `adapters` нет или она "
                       "не список — сравнивать нечем")
    return s_map, o_map, reasons


# ── Журнал расхождений: память, без которой «мигает» и «живёт» неразличимы ────────────


def log_path(base: str) -> str:
    return os.path.join(base, os.path.basename(LOG_REL))


def _snapshot_key(inputs: dict, now: dt.datetime) -> str:
    """Отпечаток НАБЛЮДЕНИЯ, а не прогона.

    Оба входа пишет дневной цикл; сторожа зовёт ``com.spa.decision_loop`` во много раз
    чаще. Ключ по паре отметок ``generated_at`` делает единицей счёта снимок: повторный
    взгляд на то же наблюдение в журнал не попадает, и «расходились N раз» отвечает на
    вопрос карточки, а не на «сколько раз мы смотрели».

    Отметку, которую прочитать не удалось, подменяет ``?<дата now>``: тогда единицей
    становится сутки, и слепота не размножается построчно, но и не исчезает.
    """
    parts = []
    for key in ("adapter_status", "orchestrator"):
        stamp = (inputs.get(key) or {}).get("generated_at")
        parts.append(str(stamp) if stamp else f"?{now.date().isoformat()}")
    return "|".join(parts)


def _journal_records(report: dict, now: dt.datetime) -> list[dict]:
    """Строки, которые этот отчёт обязан оставить в памяти.

    Пишутся ТОЛЬКО ``CRITICAL``/``WARN`` (``LOGGED_SEVERITIES``) — согласие строки не
    оставляет — плюс ОТДЕЛЬНАЯ строка ``unchecked``, когда сторож отказался судить.
    Без второй «за трое суток расхождений нет» было бы неотличимо от «трое суток мы
    были слепы», а это разные новости (инвариант #17).
    """
    key = _snapshot_key(report.get("inputs") or {}, now)
    stamp = now.isoformat()
    out: list[dict] = []
    for f in report.get("findings") or []:
        if f.get("severity") not in LOGGED_SEVERITIES:
            continue
        rec = {
            "observed_at": stamp,
            "snapshot_key": key,
            "protocol": f.get("protocol"),
            "kind": f.get("kind"),
            "severity": f.get("severity"),
            "message": f.get("message"),
        }
        for extra in ("delta_pp", "adapter_status_apy", "orchestrator_apy",
                      "adapter_status_tvl", "orchestrator_tvl",
                      "adapter_status_tier", "orchestrator_tier"):
            if extra in f:
                rec[extra] = f[extra]
        out.append(rec)
    if report.get("overall") == UNCHECKED:
        out.append({
            "observed_at": stamp,
            "snapshot_key": key,
            "protocol": "-",
            "kind": "unchecked",
            "severity": UNCHECKED,
            "message": "сверка не вынесена — сторож отказался судить",
            "reasons": list(report.get("unchecked") or []),
        })
    return out


def read_journal(base: str) -> tuple[list[dict], str]:
    """``(записи, причина_нечитаемости)``. Битые строки пропускаются ПОИМЁННО в причине."""
    path = log_path(base)
    records: list[dict] = []
    bad = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(rec, dict):
                    records.append(rec)
                else:
                    bad += 1
    except FileNotFoundError:
        return [], f"журнала нет на диске: {path}"
    except OSError as e:  # noqa: BLE001
        return [], f"журнал не прочитан: {e}"
    return records, (f"пропущено нечитаемых строк: {bad}" if bad else "")


def append_history(report: dict, base: str, now: dt.datetime) -> list[dict]:
    """Дописать память об ЭТОМ наблюдении. Возвращает реально записанные строки.

    Повтор того же снимка (тот же ``snapshot_key`` + протокол + род) не пишется —
    иначе счёт расхождений считал бы наши взгляды, а не наблюдения фидов.
    """
    fresh = _journal_records(report, now)
    known, _ = read_journal(base)
    path = log_path(base)
    if not os.path.exists(path):
        # ОТКРЫТИЕ журнала — отдельная запись, и она обязательна. Без неё пустой файл
        # («смотрим третью неделю, расхождений не было») был бы неотличим от файла,
        # которого нет («память тут никогда не работала»): обе картины дают ноль строк
        # и ноль суток покрытия. Дата открытия — единственное, чем эти два состояния
        # различаются, и она записывается ДО первой находки, а не выводится из неё.
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "observed_at": now.isoformat(), "snapshot_key": "-", "protocol": "-",
                "kind": "journal_opened", "severity": INFO,
                "message": "журнал расхождений открыт — с этой отметки считается "
                           "покрытие окна (ADR-207)"}, ensure_ascii=False) + "\n")
        known, _ = read_journal(base)
    if not fresh:
        return []
    seen = {(r.get("snapshot_key"), r.get("protocol"), r.get("kind")) for r in known}
    new = [r for r in fresh
           if (r["snapshot_key"], r["protocol"], r["kind"]) not in seen]
    if not new:
        return []
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:  # O_APPEND: короткие строки атомарны
        for rec in new:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    total = len(known) + len(new)
    if total > LOG_MAX_LINES:
        kept = (known + new)[-LOG_MAX_LINES:]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for rec in kept:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    return new


def history(base: str, *, days: float = 7.0, now: dt.datetime | None = None) -> dict:
    """Ответ ЧИСЛОМ на вопрос карточки: сколько раз за N суток и на сколько.

    Считаются РАЗНЫЕ снимки (``snapshot_key``), а не строки: один снимок, прочитанный
    сторожем двадцать раз, — одно расхождение.

    ``covered_days`` и ``window_truncated`` обязательны: «0 расхождений за 30 суток» по
    двухдневному журналу — не хорошая новость, а ненаблюдение, и оно обязано называться
    здесь, а не додумываться читателем.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    records, reason = read_journal(base)
    if reason and not records:
        return {"status": UNCHECKED, "reason": reason, "window_days": days,
                "covered_days": None, "window_truncated": None, "by_key": {},
                "blind_snapshots": 0, "records": 0}

    since = now - dt.timedelta(days=days)
    stamps = [_parse_iso(r.get("observed_at")) for r in records]
    stamps = [x for x in stamps if x]
    oldest = min(stamps) if stamps else None
    covered = round((now - oldest).total_seconds() / 86400.0, 2) if oldest else 0.0

    by_key: dict = {}
    blind: set = set()
    for rec in records:
        at = _parse_iso(rec.get("observed_at"))
        if at is None or at < since:
            continue
        if rec.get("kind") == "unchecked":
            blind.add(rec.get("snapshot_key"))
            continue
        if rec.get("severity") not in LOGGED_SEVERITIES:
            continue
        key = f"{rec.get('protocol')}:{rec.get('kind')}"
        slot = by_key.setdefault(key, {
            "protocol": rec.get("protocol"), "kind": rec.get("kind"),
            "severity": rec.get("severity"), "snapshots": set(), "deltas_pp": [],
            "first_seen": None, "last_seen": None})
        slot["snapshots"].add(rec.get("snapshot_key"))
        delta = _num(rec.get("delta_pp"))
        if delta is not None:
            slot["deltas_pp"].append(delta)
        iso = at.isoformat()
        slot["first_seen"] = min(slot["first_seen"] or iso, iso)
        slot["last_seen"] = max(slot["last_seen"] or iso, iso)

    summary = {}
    for key, slot in sorted(by_key.items()):
        deltas = sorted(slot["deltas_pp"])
        summary[key] = {
            "protocol": slot["protocol"], "kind": slot["kind"],
            "severity": slot["severity"],
            "snapshots_diverged": len(slot["snapshots"]),
            "first_seen": slot["first_seen"], "last_seen": slot["last_seen"],
            "delta_pp_min": deltas[0] if deltas else None,
            "delta_pp_max": deltas[-1] if deltas else None,
            "delta_pp_median": (deltas[len(deltas) // 2] if len(deltas) % 2
                                else round((deltas[len(deltas) // 2 - 1]
                                            + deltas[len(deltas) // 2]) / 2, 4))
            if deltas else None,
        }
    return {
        "status": "OK",
        "window_days": days,
        "covered_days": covered,
        "window_truncated": covered < days,
        "records": len(records),
        "blind_snapshots": len(blind),
        "by_key": summary,
        "note": (f"журнал моложе запрошенного окна: покрыто {covered} сут из {days} — "
                 f"«расхождений нет» здесь означает «нечем судить о более раннем»")
        if covered < days else "",
    }


def run(root: str = REPO_ROOT, now: dt.datetime | None = None,
        write: bool = True, data_dir: str | None = None) -> dict:
    """Сверить два артефакта и вернуть отчёт (он же пишется в ``REPORT_REL``)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    base = data_dir or os.path.join(root, "data")

    def _rel(rel: str) -> str:
        return os.path.join(base, os.path.basename(rel))

    findings: list[dict] = []
    unchecked: list[str] = []
    inputs: dict = {}

    docs = {}
    for key, rel in (("adapter_status", STATUS_REL), ("orchestrator", ORCH_REL)):
        path = _rel(rel)
        try:
            with open(path) as fh:
                docs[key] = json.load(fh)
        except FileNotFoundError:
            docs[key] = None
            unchecked.append(f"{os.path.basename(rel)}: файла нет на диске ({path})")
        except (OSError, ValueError) as e:  # noqa: BLE001
            docs[key] = None
            unchecked.append(f"{os.path.basename(rel)}: не прочитан — {e}")
        stamp = _parse_iso((docs[key] or {}).get("generated_at")
                           if isinstance(docs[key], dict) else None)
        inputs[key] = {
            "path": os.path.basename(rel),
            "generated_at": stamp.isoformat() if stamp else None,
            "age_s": round((now - stamp).total_seconds(), 1) if stamp else None,
        }

    stamps = {k: _parse_iso(v["generated_at"]) for k, v in inputs.items()}
    if all(docs.values()):
        for key, stamp in stamps.items():
            if stamp is None:
                unchecked.append(
                    f"{key}: отметка `generated_at` не прочитана — сказать, об одном ли "
                    f"такте идёт речь, НЕЧЕМ (сверка не выносится)")
            elif (now - stamp).total_seconds() > MAX_AGE_S:
                unchecked.append(
                    f"{key}: снимку {round((now - stamp).total_seconds() / 3600, 1)} ч "
                    f"при потолке {round(MAX_AGE_S / 3600, 1)} ч — сторож отказывается "
                    f"судить о фидах по вчерашнему снимку (stale_input)")
        if all(stamps.values()):
            skew = abs((stamps["adapter_status"] - stamps["orchestrator"]).total_seconds())
            if skew > MAX_SKEW_S:
                unchecked.append(
                    f"snapshot_skew: артефакты произведены с разрывом {round(skew, 1)} с "
                    f"при потолке {MAX_SKEW_S} с — разные числа означали бы разные МОМЕНТЫ, "
                    f"а не разные фиды; сверка не выносится")

    s_map = o_map = {}
    if not unchecked:
        s_map, o_map, reasons = _protocols(docs["adapter_status"], docs["orchestrator"])
        unchecked.extend(reasons)

    shared = sorted(set(s_map) & set(o_map)) if not unchecked else []
    if not unchecked and not shared:
        findings.append(_finding(
            "-", "no_overlap", CRITICAL,
            f"общих протоколов у двух артефактов НЕТ вовсе "
            f"(adapter_status: {len(s_map)}, orchestrator: {len(o_map)}) — "
            f"сравнивать было нечего. Это НЕ чистый зачёт: сторож, которому нечего "
            f"сравнить, обязан отличаться от сторожа, который сравнил и не нашёл"))

    for protocol in shared:
        findings.extend(_compare_protocol(protocol, s_map[protocol], o_map[protocol]))

    counts = {
        "critical": sum(1 for f in findings if f["severity"] == CRITICAL),
        "warn": sum(1 for f in findings if f["severity"] == WARN),
        "info": sum(1 for f in findings if f["severity"] == INFO),
        "unchecked": len(unchecked) + sum(1 for f in findings if f["severity"] == UNCHECKED),
    }
    if counts["unchecked"]:
        overall = UNCHECKED
    elif counts["critical"]:
        overall = CRITICAL
    elif counts["warn"]:
        overall = WARN
    else:
        overall = "OK"

    report = {
        "generated_at": now.isoformat(),
        "generated_by": "spa_core/monitoring/adapter_feed_divergence.py",
        "schema_version": 1,
        "overall": overall,
        "counts": counts,
        "compared_protocols": shared,
        "findings": findings,
        "unchecked": unchecked,
        "inputs": inputs,
    }
    # Память ДОПИСЫВАЕТСЯ до сборки ответа, чтобы сегодняшнее наблюдение уже входило
    # в него: отчёт, знающий о рецидиве меньше, чем журнал рядом, — третье мнение.
    report["history_appended"] = len(append_history(report, base, now)) if write else 0
    # Ответ на вопрос карточки едет В ЗАРЕГИСТРИРОВАННОМ артефакте, а не только в
    # журнале: у журнала нет обязательного читателя, у этого отчёта — есть (шаг
    # 0-офис каждого цикла). Сторож, чью память надо спрашивать отдельной командой,
    # неотличим от сторожа без памяти.
    report["history"] = history(base, days=HISTORY_WINDOW_DAYS, now=now)
    if write:
        atomic_save(report, os.path.join(base, os.path.basename(REPORT_REL)))
    return report


def exit_code(report: dict) -> int:
    """0 — сошлось · 1 — есть WARN · 2 — CRITICAL или UNCHECKED (fail-CLOSED).

    Отчёта без счётчиков быть не должно, и потому именно здесь — самое удобное место
    соврать. Привычное ``report.get("counts") or {}`` превратило бы «отчёт не тот /
    отчёта нет» в **ноль находок**, то есть в код возврата 0 — «сошлось». Это ровно тот
    класс, ради которого сторож и заведён (инвариант #17: отсутствие наблюдения обязано
    иметь СВОЁ значение, а не сливаться с благополучием), и храповик
    ``test_absent_observation_ratchet`` поймал его в первом же прогоне ЗДЕСЬ.
    Нет счётчиков ⇒ 2, а не 0.
    """
    counts = report.get("counts")
    if not isinstance(counts, dict):
        return 2
    if counts.get("unchecked") or counts.get("critical"):
        return 2
    if counts.get("warn"):
        return 1
    return 0


def main(argv=None, *, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="читать оба артефакта и писать отчёт в ЧУЖОЙ каталог "
                         "(обычно <прод>/data)")
    ap.add_argument("--no-write", action="store_true", help="только печать, без артефакта")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    ap.add_argument("--history", action="store_true",
                    help="не сверять, а ОТВЕТИТЬ ПО ПАМЯТИ: сколько раз за --days суток "
                         "два наблюдения одного пула разошлись и на сколько")
    ap.add_argument("--days", type=float, default=7.0,
                    help="окно вопроса для --history, суток (по умолчанию 7)")
    args = ap.parse_args(argv)

    if args.history:
        base = args.data_dir or os.path.join(args.root, "data")
        hist = history(base, days=args.days, now=now)
        if args.json:
            print(json.dumps(hist, ensure_ascii=False, indent=2))
            return 0 if hist["status"] == "OK" else 2
        if hist["status"] != "OK":
            print(f"память расхождений: НЕ ИЗМЕРЕНО — {hist['reason']}")
            return 2
        print(f"память расхождений за {hist['window_days']} сут: строк {hist['records']}, "
              f"покрыто {hist['covered_days']} сут"
              + (" ⚠️ ОКНО ОБРЕЗАНО ВОЗРАСТОМ ЖУРНАЛА" if hist["window_truncated"] else ""))
        if hist["blind_snapshots"]:
            print(f"   [СЛЕПОТА] снимков, о которых сторож отказался судить: "
                  f"{hist['blind_snapshots']} — это НЕ «расхождений не было»")
        for key, row in hist["by_key"].items():
            print(f"   [{row['severity']}] {key}: разошлись на {row['snapshots_diverged']} "
                  f"снимк(е/ах); разница пп мин {row['delta_pp_min']} · медиана "
                  f"{row['delta_pp_median']} · макс {row['delta_pp_max']}; "
                  f"впервые {row['first_seen']} · последний раз {row['last_seen']}")
        if not hist["by_key"] and not hist["blind_snapshots"]:
            print("   расхождений в памяти нет — и слепых снимков тоже нет")
        return 0

    report = run(root=args.root, now=now, write=not args.no_write,
                 data_dir=args.data_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code(report)

    c = report["counts"]
    print(f"сверка двух фидов адаптеров: {report['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"unchecked={c['unchecked']}); протоколов сверено: "
          f"{len(report['compared_protocols'])}")
    for line in report["unchecked"]:
        print(f"   [НЕ ИЗМЕРЕНО] {line}")
    for f in report["findings"]:
        print(f"   [{f['severity']}] {f['message']}")
    if report["overall"] == "OK":
        print("   расхождений нет — оба артефакта говорят о каждом общем протоколе одно и то же")
    return exit_code(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
