"""apy_composition.py — эта ставка ДОХОДНОСТЬ или РАЗДАЧА ТОКЕНА?

Вопрос, на который не отвечал ни один сторож
============================================
Про число адаптера уже спрашивают четырёх сторожей, и каждый честно отвечает на
СВОЙ вопрос:

| вопрос | кто отвечает | чего НЕ проверяет |
|---|---|---|
| фид вообще жив? | ``adapter_watchdog`` | что именно он принёс |
| число живое или литерал? | провенанс ``live_apy``/``tvl_source`` | из чего оно состоит |
| два артефакта говорят одно? | ``adapter_feed_divergence`` | что говорят они ОБА |
| два ключа — не один ли пул? | ``pool_identity_collision`` | чем платит этот пул |

Ни один не спрашивает: **из чего ставка СОСТОИТ.** DeFiLlama сообщает это в той
же записи, которую мы и так забираем: ``apyBase`` — доход от самой операции
(проценты заёмщиков, комиссии), ``apyReward`` — раздача токена протокола.
Итоговый ``apy`` их складывает, и после сложения «4 % с заёмщиков» неотличимы от
«4 % раздачей собственного токена». Это не оттенок: у второго другой актив (не
стейблкоин), своя цена, свой график и конец срока.

Замер 2026-09-05, живой фид (17 057 пулов), 23 разрешённых ключа
================================================================
Ровно ОДИН ключ платит эмиссией, и платит ею ВСЁ::

    spark_susds  пул 54e9b138…  apy 4.066 %  apyBase null  apyReward 4.066
                 poolMeta "SPK Farming Pool"  rewardTokens [SPK 0xc200…b066]

Остальные 22 — чистая база (``apyReward`` ноль либо не сообщён при базе, равной
итогу). То есть класс узкий, поимённый и измеренный, а не подозрение.

Почему это ДЕНЬГИ, а не любопытство
===================================
В тот же день инвест-офис предлагал ``spark_susds`` как возможность 4.0694 %
(evidence L2) и снял с цели **$4 737**; отказ состоялся по ПОСТОРОННЕЙ причине —
``tvl_unverified_policy_gate``, то есть потому, что TVL этого ключа ещё стоит
литералом. Реестр при этом объявляет ему **T1 и потолок 40 %**.

А открытая карточка ``inbox-ozhivit-fidy-vne-ethereum-put-k-snyatiyu`` (high,
08.08) просит ровно одного: закрепить пулы по UUID, чтобы TVL стал живым и
gate открылся. Исполнение её рецепта буквально — «закрепить пул, который
победил хинт» — закрепило бы SPK-ферму и впустило бы в книгу капитал по числу,
которое система считает кредитной ставкой стейблкоина. Единственное, что этому
мешало, — посторонний протухший гейт.

Второй род: тождество, решённое СЕГОДНЯШНИМ TVL
===============================================
Хинт выбирает пул правилом «побеждает крупнейший TVL». Комментарий самого
``adapter_status_generator`` называет это свойством «этой недели, а не правила», и
``_CANONICAL_UNDERLYING`` (сторож, поставленный ровно против чужого актива) здесь
не помогает: у ``spark_susds`` ОБА кандидата несут канонический USDS —

    54e9b138…  $562.9M  4.066 %  (эмиссия SPK)
    0ed981dc…  $260.2M  2.318 %  (кредитная ставка, без раздач)

1.75 пп между ними, и победитель решается тем, который сегодня больше. Поэтому
второй род находок — ``identity_by_tvl_only``: ключ разрешён хинтом, у победителя
есть соперники, и РАЗРЫВ ставок между ним и ближайшим по TVL существен.

**Мера — разрыв, а не число соперников.** У ``morpho_blue`` соперников 61, а разрыв
0.0145 пп: подмена победителя там не меняет ничего, и кричать о ней значило бы
учить читателя не читать. У ``euler_v2`` соперников 18 при разрыве 24.04 пп — это
другой предмет.

Что этот модуль НЕ делает
=========================
Не выбирает пул, не меняет ставку, не двигает капитал, не гейтит исполнение и не
трогает RiskPolicy. **Только называет состав.** Считать ли эмиссию доходностью и
какой из двух пулов есть ``spark_susds`` — money-path, решение владельца (карточка),
а не автономная правка.

Своей цены ошибки у сторожа нет — и это сказано вслух
=====================================================
Состав он **читает** из ``data/adapter_status.json``, а не добывает: числа туда
кладёт производитель (``adapter_status_generator``), и если тот прочтёт фид
неверно, сторож повторит ошибку слово в слово. Он отвечает на вопрос «сходится ли
записанное с тем, что мы называем доходностью», а НЕ «правильно ли снят фид» — на
второй отвечает сам производитель и его тесты.

Граница «не измерено» названа узко — иначе сторож молчал бы всегда
=================================================================
Ключей без разрешённого пула в реестре большинство (13 из 34 на 05.09 живут на
литерале ``fallback_apy``), и объявлять их состав «не измеренным» значило бы
держать сторожа в вечном ``UNCHECKED``, то есть выключить его. Состав спрашивается
только у ключей, у которых наблюдение ЭТОГО прогона есть (``live_apy_fresh``);
литеральные — предмет ``adapter_feed_divergence`` (род ``literal_vs_live``), и
дублировать его здесь незачем.

Память (ADR-206): «победитель сменился» — вопрос ВРЕМЕНИ, а не снимка
=====================================================================
Отчёт перезаписывается каждым прогоном, поэтому вопрос «менялся ли победитель
хинта за последние N суток» был бы неразрешим ПО ПОСТРОЕНИЮ. Журнал
``data/apy_composition_log.jsonl`` хранит по строке на снимок и ключ; ``history()``
отвечает ЧИСЛОМ: сколько раз у ключа сменился выбранный пул и на сколько при этом
менялась ставка. Единица счёта — СНИМОК (отметка ``generated_at`` входа), а не
прогон: сторожа зовёт ``com.spa.decision_loop`` часто, а вход пишет дневной цикл
раз в сутки, и без ключа снимка «сменился 24 раза» означало бы «мы 24 раза
посмотрели на одно наблюдение». Окно ответа обрезается возрастом журнала и об
обрезке ГОВОРИТСЯ.

Коды возврата: 0 — чисто · 1 — есть WARN · 2 — CRITICAL или UNCHECKED.
LLM_FORBIDDEN. Только stdlib. Читает read-only, пишет свой отчёт и свой журнал.
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

REPORT_REL = os.path.join("data", "apy_composition.json")
LOG_REL = os.path.join("data", "apy_composition_log.jsonl")
STATUS_REL = os.path.join("data", "adapter_status.json")
POSITIONS_REL = os.path.join("data", "current_positions.json")

CRITICAL, WARN, INFO, UNCHECKED, OK = "CRITICAL", "WARN", "INFO", "UNCHECKED", "OK"

#: Доля эмиссии, с которой ставка перестаёт быть «доходностью с примесью раздач».
#: Половина — не вкусовой порог: выше неё БОЛЬШАЯ часть числа, которым ранжируется
#: капитал, платится не тем активом, в котором номинирована книга. Замеренный случай
#: (``spark_susds``) стоит на 1.0, то есть вдвое выше порога, — порог выбран так,
#: чтобы ловить и менее крайние, а не подгонкой под единственное наблюдение.
EMISSION_DOMINANT_SHARE = 0.50

#: Разрыв ставок между победителем хинта и ближайшим по TVL, с которого подмена
#: победителя перестаёт быть безразличной, процентных пунктов. Замер 05.09 разводит
#: два предмета на порядок: ``morpho_blue`` 0.0145 пп (61 соперник, всё равно) против
#: ``spark_susds`` 1.7475 пп и ``euler_v2`` 24.0391 пп.
IDENTITY_SPREAD_PP = 1.0

#: Старше этого — сторож отказывается судить. 26 ч: такт дневного цикла плюс запас,
#: тот же порядок, что у соседних сторожей. Сторож не имеет права говорить в
#: настоящем времени о вчерашнем снимке.
MAX_AGE_S = 26 * 3600.0

#: Потолок журнала, строк. Ротация оставляет САМЫЕ СВЕЖИЕ.
LOG_MAX_LINES = 5000

#: Окно, за которое отчёт носит ответ «менялся ли победитель» с собой.
HISTORY_WINDOW_DAYS = 7.0


def _finding(adapter: str, kind: str, severity: str, message: str, **extra) -> dict:
    out = {"adapter": adapter, "kind": kind, "severity": severity, "message": message}
    out.update(extra)
    return out


def _usd(book: dict | None, key: str) -> float | None:
    """Сколько денег стоит на ключе — ``None``, если книга не прочитана.

    ``None`` и ``0.0`` различаются намеренно: «не знаем, профинансирован ли» и
    «точно не профинансирован» ведут к разной строгости вердикта, и слить их
    значило бы тихо понизить находку.
    """
    if book is None:
        return None
    value = book.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def measure(status_doc, *, book: dict | None = None,
            book_reason: str = "") -> dict:
    """Разобрать документ ``adapter_status`` и вернуть находки (без записи).

    Выделено из :func:`run`, чтобы тест мог подать документ прямо, не заводя
    каталог ``data/``: сторож, проверяемый только через диск, судит о ХОСТЕ.
    """
    findings: list[dict] = []
    unchecked: list[str] = []

    if not isinstance(status_doc, dict):
        return _report_shell(findings, [
            "adapter_status.json прочитан, но это не объект — судить не о чем"],
            [], book_reason)

    adapters = status_doc.get("adapters")
    if not isinstance(adapters, dict):
        return _report_shell(findings, [
            "в adapter_status.json нет секции `adapters` — состав ставок не измерен"],
            [], book_reason)

    observed: list[str] = []
    for key in sorted(adapters):
        entry = adapters[key]
        if not isinstance(entry, dict):
            continue
        # Спрашиваем состав ТОЛЬКО у наблюдения этого прогона — см. границу в
        # докстроке модуля. Литеральные ключи — предмет adapter_feed_divergence.
        if not entry.get("live_apy_fresh"):
            continue
        observed.append(key)

        share = entry.get("apy_reward_share")
        if not isinstance(share, (int, float)) or isinstance(share, bool):
            reason = entry.get("apy_composition_unmeasured")
            unchecked.append(
                f"{key}: наблюдение этого прогона есть, а состав ставки НЕ ИЗМЕРЕН — "
                f"{reason or 'производитель не назвал причину'}")
            continue

        usd = _usd(book, key)
        if share >= EMISSION_DOMINANT_SHARE:
            if usd is None:
                severity = WARN
                money = "профинансирован ли ключ — НЕ ИЗМЕРЕНО (книга не прочитана)"
            elif usd > 0:
                severity = CRITICAL
                money = f"на ключе уже стоит ${usd:,.0f}"
            else:
                severity = WARN
                money = "в книге ключа сегодня нет"
            tokens = entry.get("reward_tokens")
            tokens = tokens if isinstance(tokens, list) else []
            findings.append(_finding(
                key, "emission_dominated", severity,
                f"{key}: {round(share * 100, 1)} % ставки — раздача токена, а не доход "
                f"операции (apyBase {entry.get('apy_base')} пп, apyReward "
                f"{entry.get('apy_reward')} пп; токен(ы) {', '.join(tokens) or 'не названы'}). "
                f"Это другой актив с собственной ценой и концом срока, а после сложения "
                f"в `apy` он неотличим от кредитной ставки; {money}",
                reward_share=round(float(share), 4),
                apy=entry.get("apy"), apy_base=entry.get("apy_base"),
                apy_reward=entry.get("apy_reward"), reward_tokens=tokens,
                usd_held=usd, pool=entry.get("tvl_pool_id"),
            ))

        rivals = entry.get("hint_rivals")
        if entry.get("pool_match") == "hint" and isinstance(rivals, dict):
            spread = rivals.get("apy_spread_pp")
            if isinstance(spread, (int, float)) and not isinstance(spread, bool) \
                    and spread >= IDENTITY_SPREAD_PP:
                held = ("не измерено" if usd is None
                        else (f"${usd:,.0f}" if usd > 0 else "ключ не профинансирован"))
                findings.append(_finding(
                    key, "identity_by_tvl_only", WARN,
                    f"{key}: пул выбран правилом «побеждает крупнейший TVL», соперников "
                    f"{rivals.get('count')}, и ближайший по TVL "
                    f"({rivals.get('runner_up_pool')}) даёт "
                    f"{rivals.get('runner_up_apy')} пп против {entry.get('apy')} пп — "
                    f"разрыв {spread} пп. Тождество держится сегодняшним порядком TVL, "
                    f"а не признаком пула; в книге: {held}",
                    apy_spread_pp=round(float(spread), 4),
                    rivals=rivals.get("count"),
                    runner_up_pool=rivals.get("runner_up_pool"),
                    runner_up_apy=rivals.get("runner_up_apy"),
                    usd_held=usd,
                ))

    if not observed:
        unchecked.append(
            "ни у одного ключа нет наблюдения этого прогона — состав ставок "
            "измерять не на чем. Это НЕ чистый зачёт: сторож, которому нечего "
            "было разобрать, обязан отличаться от сторожа, который разобрал")

    return _report_shell(findings, unchecked, observed, book_reason)


def _report_shell(findings: list[dict], unchecked: list[str],
                  observed: list[str], book_reason: str) -> dict:
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == CRITICAL),
        "warn": sum(1 for f in findings if f["severity"] == WARN),
        "info": sum(1 for f in findings if f["severity"] == INFO),
        "unchecked": len(unchecked),
    }
    if counts["unchecked"]:
        overall = UNCHECKED
    elif counts["critical"]:
        overall = CRITICAL
    elif counts["warn"]:
        overall = WARN
    else:
        overall = OK
    return {
        "overall": overall,
        "counts": counts,
        "observed_adapters": observed,
        "findings": findings,
        "unchecked": unchecked,
        "book_note": book_reason or None,
    }


# ── Память: менялся ли выбранный пул ────────────────────────────────────────

def log_path(base: str) -> str:
    return os.path.join(base, os.path.basename(LOG_REL))


def _snapshot_key(stamp: dt.datetime | None, now: dt.datetime) -> str:
    """Отметка ВХОДА, а не прогона. Нет отметки ⇒ ключ прогона, и это сказано."""
    return stamp.isoformat() if stamp else f"run:{now.isoformat()}"


def _journal_records(report: dict, snapshot: str, now: dt.datetime,
                     adapters: dict) -> list[dict]:
    """По строке на ключ, разрешённый хинтом, плюс строка на каждую слепоту."""
    out: list[dict] = []
    # Прямое чтение, а не `.get(...) or []`: отчёт собирает `_report_shell`, ключи в нём
    # есть ВСЕГДА, и подстановка пустого списка означала бы «наблюдений не было» там,
    # где на самом деле «отчёт не тот» — то есть ровно fail-OPEN (инвариант #17).
    for key in report["observed_adapters"]:
        entry = adapters.get(key)
        if not isinstance(entry, dict) or entry.get("pool_match") != "hint":
            continue
        rivals = entry.get("hint_rivals")
        rivals = rivals if isinstance(rivals, dict) else {}
        out.append({
            "observed_at": now.isoformat(),
            "snapshot": snapshot,
            "kind": "hint_winner",
            "adapter": key,
            "pool": entry.get("pool_id"),
            "apy": entry.get("apy"),
            "reward_share": entry.get("apy_reward_share"),
            "runner_up_pool": rivals.get("runner_up_pool"),
            "apy_spread_pp": rivals.get("apy_spread_pp"),
        })
    for line in report["unchecked"]:
        out.append({
            "observed_at": now.isoformat(),
            "snapshot": snapshot,
            "kind": "unchecked",
            "adapter": line.split(":", 1)[0],
            "reason": line,
        })
    return out


def read_journal(base: str) -> tuple[list[dict], str]:
    path = log_path(base)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return [], "журнала нет на диске — памяти о смене победителя не существует"
    except OSError as e:  # noqa: BLE001
        return [], f"журнал не прочитан — {e}"
    records, broken = [], 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            broken += 1
            continue
        if isinstance(rec, dict):
            records.append(rec)
    if broken:
        return records, f"строк журнала не разобрано: {broken}"
    return records, ""


def append_history(report: dict, base: str, now: dt.datetime,
                   snapshot: str, adapters: dict) -> list[dict]:
    """Дописать строки СНИМКА, если этого снимка в журнале ещё нет."""
    fresh = _journal_records(report, snapshot, now, adapters)
    if not fresh:
        return []
    existing, _ = read_journal(base)
    seen = {(r.get("snapshot"), r.get("adapter"), r.get("kind"))
            for r in existing if isinstance(r, dict)}
    new = [r for r in fresh
           if (r["snapshot"], r["adapter"], r["kind"]) not in seen]
    if not new:
        return []
    lines = existing + new
    if len(lines) > LOG_MAX_LINES:
        lines = lines[-LOG_MAX_LINES:]
    path = log_path(base)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for rec in lines:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return new


def history(base: str, *, days: float = HISTORY_WINDOW_DAYS,
            now: dt.datetime | None = None) -> dict:
    """Сколько раз у ключа сменился ВЫБРАННЫЙ пул за окно и на сколько ставка."""
    now = now or dt.datetime.now(dt.timezone.utc)
    records, reason = read_journal(base)
    if reason and not records:
        return {"status": UNCHECKED, "reason": reason, "window_days": days,
                "by_adapter": {}, "records": 0, "covered_days": 0.0,
                "window_truncated": False, "blind_snapshots": 0}
    cutoff = now - dt.timedelta(days=days)
    kept, stamps = [], []
    for rec in records:
        stamp = _parse_iso(rec.get("observed_at"))
        if stamp is None:
            continue
        stamps.append(stamp)
        if stamp >= cutoff:
            kept.append((stamp, rec))
    oldest = min(stamps) if stamps else now
    covered = round(max(0.0, (now - oldest).total_seconds() / 86400.0), 2)
    by_adapter: dict[str, dict] = {}
    for adapter in sorted({r.get("adapter") for _, r in kept
                           if r.get("kind") == "hint_winner"}):
        rows = [r for _, r in kept
                if r.get("kind") == "hint_winner" and r.get("adapter") == adapter]
        pools = [r.get("pool") for r in rows]
        changes = sum(1 for a, b in zip(pools, pools[1:]) if a != b)
        apys = [r.get("apy") for r in rows
                if isinstance(r.get("apy"), (int, float))]
        by_adapter[adapter] = {
            "snapshots": len(rows),
            "winner_changes": changes,
            "distinct_pools": len({p for p in pools if p}),
            "apy_min": round(min(apys), 4) if apys else None,
            "apy_max": round(max(apys), 4) if apys else None,
        }
    return {
        "status": OK,
        "reason": reason or None,
        "window_days": days,
        "records": len(kept),
        "covered_days": covered,
        "window_truncated": covered < days,
        "blind_snapshots": len({r.get("snapshot") for _, r in kept
                                if r.get("kind") == "unchecked"}),
        "by_adapter": by_adapter,
    }


def run(root: str = REPO_ROOT, now: dt.datetime | None = None,
        write: bool = True, data_dir: str | None = None) -> dict:
    """Разобрать состав ставок и вернуть отчёт (он же пишется в ``REPORT_REL``)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    base = data_dir or os.path.join(root, "data")

    status_path = os.path.join(base, os.path.basename(STATUS_REL))
    status_doc, load_reason = None, ""
    try:
        with open(status_path, encoding="utf-8") as fh:
            status_doc = json.load(fh)
    except FileNotFoundError:
        load_reason = f"adapter_status.json нет на диске ({status_path})"
    except (OSError, ValueError) as e:  # noqa: BLE001
        load_reason = f"adapter_status.json не прочитан — {e}"

    stamp = _parse_iso(status_doc.get("generated_at")
                       if isinstance(status_doc, dict) else None)
    age_s = round((now - stamp).total_seconds(), 1) if stamp else None
    if not load_reason and stamp is None:
        load_reason = ("отметка `generated_at` входа не прочитана — сказать, о каком "
                       "такте идёт речь, НЕЧЕМ")
    elif not load_reason and age_s is not None and age_s > MAX_AGE_S:
        load_reason = (f"снимку {round(age_s / 3600, 1)} ч при потолке "
                       f"{round(MAX_AGE_S / 3600, 1)} ч — сторож отказывается судить "
                       f"о составе ставок по вчерашнему снимку (stale_input)")

    # Книга — вход НЕОБЯЗАТЕЛЬНЫЙ: без неё сторож не слепнет, он лишь не вправе
    # поднять находку до CRITICAL, и говорит об этом прямо.
    book, book_reason = None, ""
    pos_path = os.path.join(base, os.path.basename(POSITIONS_REL))
    try:
        with open(pos_path, encoding="utf-8") as fh:
            pos_doc = json.load(fh)
        positions = pos_doc.get("positions") if isinstance(pos_doc, dict) else None
        if isinstance(positions, dict):
            book = positions
        else:
            book_reason = "в current_positions.json нет секции `positions`"
    except FileNotFoundError:
        book_reason = f"книги нет на диске ({pos_path})"
    except (OSError, ValueError) as e:  # noqa: BLE001
        book_reason = f"книга не прочитана — {e}"

    if load_reason:
        report = _report_shell([], [load_reason], [], book_reason)
        adapters: dict = {}
    else:
        report = measure(status_doc, book=book, book_reason=book_reason)
        adapters = status_doc.get("adapters") if isinstance(status_doc, dict) else {}
        adapters = adapters if isinstance(adapters, dict) else {}

    report.update({
        "generated_at": now.isoformat(),
        "generated_by": "spa_core/monitoring/apy_composition.py",
        "schema_version": 1,
        "emission_dominant_share": EMISSION_DOMINANT_SHARE,
        "identity_spread_pp": IDENTITY_SPREAD_PP,
        "input": {
            "path": os.path.basename(STATUS_REL),
            "generated_at": stamp.isoformat() if stamp else None,
            "age_s": age_s,
        },
    })
    snapshot = _snapshot_key(stamp, now)
    report["history_appended"] = (
        len(append_history(report, base, now, snapshot, adapters)) if write else 0)
    report["history"] = history(base, days=HISTORY_WINDOW_DAYS, now=now)
    if write:
        atomic_save(report, os.path.join(base, os.path.basename(REPORT_REL)))
    return report


def exit_code(report: dict) -> int:
    """0 — чисто · 1 — WARN · 2 — CRITICAL/UNCHECKED (fail-CLOSED).

    Отчёта без счётчиков быть не должно, и потому именно здесь удобнее всего
    соврать: ``report.get("counts") or {}`` превратило бы «отчёта нет» в ноль
    находок, то есть в зачёт. Нет счётчиков ⇒ 2, а не 0.
    """
    counts = report.get("counts")
    if not isinstance(counts, dict):
        return 2
    if counts.get("unchecked") or counts.get("critical"):
        return 2
    if counts.get("warn"):
        return 1
    return 0


def _lines(report: dict) -> list[str]:
    """Печать отчёта. Отчёт не той формы — ОТКАЗ, а не ноль находок.

    Привычное `report.get("counts") or {}` напечатало бы «critical=None warn=None»
    и ноль строк находок, то есть благополучие, там где отчёта нет вовсе. Здесь
    ровно тот же довод, что в :func:`exit_code`.
    """
    c = report.get("counts")
    if not isinstance(c, dict):
        return ["состав ставок адаптеров: НЕ ИЗМЕРЕНО — отчёт без счётчиков "
                "(это не «находок ноль», а «судить не о чем»)"]
    out = [f"состав ставок адаптеров: {report.get('overall')} "
           f"(critical={c.get('critical')} warn={c.get('warn')} "
           f"unchecked={c.get('unchecked')}); ключей с наблюдением этого прогона: "
           f"{len(report['observed_adapters'])}"]
    for line in report["unchecked"]:
        out.append(f"   [НЕ ИЗМЕРЕНО] {line}")
    for f in report["findings"]:
        out.append(f"   [{f['severity']}] {f['message']}")
    if report.get("book_note"):
        out.append(f"   ℹ️ книга не прочитана ({report['book_note']}) — находки не "
                   f"поднимались до CRITICAL; это ограничение, а не зачёт")
    if report.get("overall") == OK:
        out.append("   ни одна наблюдённая ставка не держится на раздаче токена, и ни "
                   "одно тождество не решается сегодняшним TVL")
    return out


def main(argv=None, *, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="читать вход и писать отчёт в ЧУЖОЙ каталог (обычно <прод>/data)")
    ap.add_argument("--no-write", action="store_true", help="только печать, без артефакта")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    ap.add_argument("--history", action="store_true",
                    help="не разбирать, а ОТВЕТИТЬ ПО ПАМЯТИ: менялся ли победитель хинта")
    ap.add_argument("--days", type=float, default=HISTORY_WINDOW_DAYS)
    args = ap.parse_args(argv)

    if args.history:
        base = args.data_dir or os.path.join(args.root, "data")
        hist = history(base, days=args.days, now=now)
        if args.json:
            print(json.dumps(hist, ensure_ascii=False, indent=2))
            return 0 if hist["status"] == OK else 2
        if hist["status"] != OK:
            print(f"память состава: НЕ ИЗМЕРЕНО — {hist['reason']}")
            return 2
        print(f"память за {hist['window_days']} сут: строк {hist['records']}, покрыто "
              f"{hist['covered_days']} сут"
              + (" ⚠️ ОКНО ОБРЕЗАНО ВОЗРАСТОМ ЖУРНАЛА" if hist["window_truncated"] else ""))
        if hist["blind_snapshots"]:
            print(f"   [СЛЕПОТА] снимков со строкой «не измерено»: "
                  f"{hist['blind_snapshots']} — это НЕ «состав сходился»")
        for key, row in hist["by_adapter"].items():
            print(f"   {key}: снимков {row['snapshots']}, смен победителя "
                  f"{row['winner_changes']}, разных пулов {row['distinct_pools']}, "
                  f"ставка {row['apy_min']}…{row['apy_max']}")
        if not hist["by_adapter"] and not hist["blind_snapshots"]:
            print("   в памяти нет ни одного ключа, разрешённого хинтом")
        return 0

    report = run(root=args.root, now=now, write=not args.no_write,
                 data_dir=args.data_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code(report)
    for line in _lines(report):
        print(line)
    return exit_code(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
