"""house_view_gap.py — сверка «офис говорит X, книга делает Y» (ADR-066, Фаза 3, C1).

Детерминированная СВЕРКА (только сверка — никаких действий с капиталом):
берёт house_view инвест-офиса и фактическую аллокацию книги и НАЗЫВАЕТ
расхождения. Выход — data/house_view_gap.json; потребитель — мост
findings_bridge (карточки) и Шаг 0-офис оркестратора.

Типы расхождений:
  opportunity_unheld  офис называет возможность (evidence-level сохранён),
                      книга её не держит, и отказ НЕ назван нигде:
                        - held в positions                       → нет гэпа
                        - в below_median_cap / warnings rationale → explained (INFO)
                        - протокола нет в ADAPTER_REGISTRY        → explained (INFO:
                          входа технически нет — нужен адаптер + промоушен)
                        - иначе                                   → WARN (безымянный
                          простой возможности — нарушение духа ADR-055)
  posture_vs_book     постура офиса RED, книга развёрнута (cash < 50%) → WARN
                      (YELLOW — информационно, гэпом не является)
  analyst_red         аналитик с posture/status RED|CRITICAL → WARN. В тексте находки
                      НАЗЫВАЕТСЯ ПРИЧИНА (`posture_reason` аналитика): без неё слово
                      CRITICAL от разведки читается как «нашли врага», хотя единственной
                      причиной может быть наша же остановка (замер цикла #195). Степень
                      НЕ ослабляется — WARN остаётся WARN; добавляется только имя причины.
                      Причины аналитик не назвал ⇒ это ГОВОРИТСЯ вслух, а не опускается.

Честность: недоступный вход ⇒ запись в unchecked, гэпы НЕ выдумываются
(refusal-first). Реестр недоступен ⇒ классификация возможностей честно
опускается до INFO/unclassified — карточек из неизмеримого не рождается.
LLM_FORBIDDEN. Только stdlib. Время — вход (now=).

ВОЗРАСТ ВХОДА — часть находки (#222, карточка «сторож расхождений судит по СТАРОМУ
снимку постуры»). Сверка пересчитывается РАЗ В 6 ЧАСОВ (`com.spa.decision_loop` →
`findings_bridge --run`, `StartInterval 21600`; в дневном цикле она НЕ дублируется),
а `chief_investment.json` пишется РАЗ В СУТКИ в 09:11 UTC. Замер #222 (14.08 22:5x UTC):
постура 13.7 ч, книга 1.6 ч, разрыв тактов 12.1 ч; замер #212 суткой раньше — 22.9 ч
против 1.2 ч. До этого обе стороны сравнивались молча и вердикт печатался в НАСТОЯЩЕМ
времени («постура офиса CRITICAL, но книга развёрнута»), поэтому строка в контексте
оркестратора могла быть неверна уже в момент чтения. Теперь:
  • возраст КАЖДОГО входа назван в самой находке и лежит в отчёте (`inputs`) машинно;
  • старше потолка офиса (`investment_os.health.FRESH_AGE_S`, 48 ч) ⇒ сверка
    ОТКАЗЫВАЕТСЯ судить (запись в unchecked), а не утверждает в настоящем времени;
  • возраст не измерен ⇒ это НАЗЫВАЕТСЯ в тексте, а не подразумевается свежим.
Потолок не изобретён здесь: он взят у монитора здоровья самого офиса — сверка не имеет
права быть увереннее в артефакте, чем его собственный сторож.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT

GAP_PATH = os.path.join(REPO_ROOT, "data", "house_view_gap.json")

_RED_TOKENS = ("RED", "CRITICAL")

#: Слова, поднимающие находку по АНАЛИТИКУ (не по постуре офиса). Шире `_RED_TOKENS` ровно на
#: `THREATS_PRESENT` — решение владельца 2026-08-26 «карточки закрывай сам», вариант А карточки
#: `own-red-team-nablyudennaya-ugroza-ne-doezzhaet` (ADR-146).
#
# Замер 18.08, четыре состояния подряд: разведка НАШЛА угрозу (`THREATS_PRESENT`) — карточка НЕ
# заводилась; мы сами остановлены выключателем (`kill_switch_already_active` ⇒ `CRITICAL`) —
# заводилась КАЖДЫЙ цикл. Канал был перевёрнут: эхо нашей же остановки шумело ежедневно, а
# настоящая наблюдённая угроза молчала. Это fail-OPEN в канале тревоги, а не косметика.
#
# ПОЧЕМУ ОТДЕЛЬНЫЙ НАБОР, А НЕ ОДНА СТРОКА В `_RED_TOKENS`. Тот кортеж читают ТРИ места, и
# второе из них — `posture_vs_book` над `overall_posture` ОФИСА. Офис синтезирует свою постуру
# из режима и угрозы (`_synthesise_posture`), поэтому `overall_posture` умеет быть буквально
# `THREATS_PRESENT` — а в таблице `_RANK` у него ранг **2**, наравне с `YELLOW`/`COMPRESSION`, и
# ниже `RED`/`CRITICAL` (ранг 3). Дописав слово в общий кортеж, мы молча приравняли бы ранг 2 к
# ранг-3 в ЧУЖОЙ лестнице и завели вторую находку, которой карточка не просила. Ровно тот класс,
# что мы чиним весь пакет: правка, сделанная не там, где её видно.
_ANALYST_RED_TOKENS = _RED_TOKENS + ("THREATS_PRESENT",)

#: Машинные коды причин красной постуры → человеческий русский. Незнакомый код НЕ выбрасывается,
#: а печатается ВЕРБАТИМ: сверка обязана быть ШИРЕ подопечного, иначе она его эхо (#197). Аналитик
#: волен назвать причину, о которой сверка не знает, — и читатель обязан её увидеть.
_REASON_RU = {
    "kill_switch_already_active": "остановка УЖЕ активна — это эхо нашего же выключателя, "
                                  "а не наблюдение разведки",
    "attack_surface_critical": "критические находки в симуляции атак",
    "threats_present": "наблюдаются угрозы",
    "threat_data_inconclusive": "данные об угрозах неполны — осторожный вердикт",
    "threat_data_missing_or_stale": "данных об угрозах нет / протухли — fail-closed",
}

#: Аналитик покраснел, но причину не назвал. Молчание НАЗЫВАЕТСЯ, а не опускается: «CRITICAL без
#: причины» — это отдельная находка (читателю нечем отличить врага в периметре от нашей же остановки).
NO_REASON_RU = "причина НЕ НАЗВАНА аналитиком"


def red_reasons(data) -> list[str]:
    """Машинные коды причин красной постуры аналитика (пустой список — причин не названо)."""
    if not isinstance(data, dict):
        return []
    raw = data.get("posture_reason")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(r).strip() for r in raw if str(r).strip()]


def humanize_reasons(reasons) -> str:
    """Причины → одна русская строка. Незнакомый код проходит ВЕРБАТИМ, пустой список → NO_REASON_RU."""
    parts = [_REASON_RU.get(r, r) for r in (reasons or [])]
    return "; ".join(parts) if parts else NO_REASON_RU


def cause_phrase(reasons) -> str:
    """Готовая вставка в текст находки: «причина: …» либо честное «причина НЕ НАЗВАНА аналитиком»."""
    codes = list(reasons or [])
    return f"причина: {humanize_reasons(codes)}" if codes else NO_REASON_RU


#: Потолок возраста входа. Берётся у монитора здоровья САМОГО офиса — одна константа на репо.
#: Импорт защищён: `health` тянет `atomic_save`/`swarm.common`, и падение соседа не имеет права
#: обесточить сверку. Провал импорта ⇒ ceiling `None` ⇒ отказа по возрасту нет, но возраст всё
#: равно НАЗЫВАЕТСЯ (и сам факт «потолок не прочитан» уезжает в unchecked).
try:
    from spa_core.investment_os.health import FRESH_AGE_S as MAX_INPUT_AGE_S
except Exception:  # pragma: no cover - защита от каскада импортов
    MAX_INPUT_AGE_S = None

#: Человеческие имена входов для текста находки.
_INPUT_RU = {
    "chief_investment": "постура",
    "current_positions": "книга",
    "allocation_rationale": "rationale",
}

AGE_UNMEASURED_RU = "возраст НЕ ИЗМЕРЕН"


def _norm(p) -> str:
    return str(p or "").strip().lower()


def _parse_iso(raw) -> dt.datetime | None:
    """ISO-строка → aware datetime (UTC). Ничего не угадывать: не разобралось ⇒ None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def snapshot_age(data, path: str, now: dt.datetime) -> dict:
    """Возраст входа: сперва ЗАЯВЛЕННЫЙ артефактом `generated_at`, иначе mtime файла.

    Почему в таком порядке: `generated_at` — время, на которое артефакт РАССУЖДАЛ, а mtime —
    время, когда его положили на диск. Совпадают они не всегда (перезапись без пересчёта,
    копирование дерева), и врёт в нашу пользу именно mtime — он молодит устаревшее содержимое.
    Ни одного источника нет ⇒ `age_s: None` = «не измерено», а не ноль.
    """
    meta: dict = {"input": os.path.basename(path)[:-5] if path.endswith(".json") else path,
                  "generated_at": None, "age_s": None, "age_source": None}
    stamp = _parse_iso((data or {}).get("generated_at") if isinstance(data, dict) else None)
    if stamp is not None:
        meta["age_source"] = "generated_at"
    else:
        try:
            stamp = dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)
            meta["age_source"] = "mtime"
        except OSError:
            return meta
    meta["generated_at"] = stamp.isoformat()
    meta["age_s"] = round((now - stamp).total_seconds(), 1)
    return meta


def bare_age(meta) -> str:
    """«1.2 ч назад» либо честное «возраст НЕ ИЗМЕРЕН» (ноль вместо неизвестного не подставляем)."""
    age_s = meta.get("age_s") if isinstance(meta, dict) else None
    return AGE_UNMEASURED_RU if age_s is None else f"{age_s / 3600.0:.1f} ч назад"


def age_phrase(meta) -> str:
    """«книга 1.2 ч назад» / «постура возраст НЕ ИЗМЕРЕН» — вставка в текст находки."""
    if not isinstance(meta, dict):
        return AGE_UNMEASURED_RU
    name = _INPUT_RU.get(meta.get("input"), meta.get("input") or "вход")
    return f"{name} {bare_age(meta)}"


def is_too_old(meta, ceiling_s=MAX_INPUT_AGE_S) -> bool:
    """Старше потолка? Неизмеренный возраст НЕ считается протухшим — иначе «не измерено»
    становится вечной остановкой сверки (урок: необратимое «не измерено» морит очередь).
    Оно НАЗЫВАЕТСЯ текстом находки, и этого достаточно."""
    if ceiling_s is None or not isinstance(meta, dict):
        return False
    age_s = meta.get("age_s")
    return age_s is not None and age_s > ceiling_s


def registry_protocol_keys() -> set[str] | None:
    """ИМЕНА протоколов из реестра адаптеров — либо `None` (не измерено), но НИКОГДА мусор.

    Авария #206: здесь стояло `{_norm(k) for k in ADAPTER_REGISTRY}`, а
    `spa_core.adapters.ADAPTER_REGISTRY` — это список КОРТЕЖЕЙ `(имя, тир, класс)`.
    `_norm` превращал в строку весь кортеж целиком, и множество наполнялось ключами вида
    `("moonwell_base", "t2", <class ...>)`. Ни одно имя протокола не совпадало с таким
    ключом НИКОГДА ⇒ обе ветки классификации возможности были мертвы, а офис
    систематически докладывал принимающему решение, что достижимые возможности
    недостижимы: `moonwell_base` 8.33 % и `fluid_fusdc` 4.85 % объявлялись «вне реестра
    адаптеров — входа технически нет», хотя адаптеры у обоих ЕСТЬ.

    Форма реестра НЕ фиксирована по построению: под именем `ADAPTER_REGISTRY` в репо живут
    два разных объекта — список кортежей (`spa_core.adapters`, 36 записей, ключи `aave_v3`)
    и dict метаданных (`spa_core.adapters.registry`, 22 записи, ключи `aave_usdc`).
    Поэтому читаем форму, а не предполагаем её; тот же приём, что в
    `governance_watcher.whitelisted_protocol_keys`.

    Fail-CLOSED: нечитаемый ИЛИ пустой результат ⇒ `None` = «не измерено» (ветка
    `opportunity_unclassified`). Пустое множество вернуть нельзя — оно означало бы
    «ни у одного протокола нет адаптера», то есть ту же ложь, только тише.
    """
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
    except Exception:
        return None
    try:
        entries = ADAPTER_REGISTRY.keys() if isinstance(ADAPTER_REGISTRY, dict) else ADAPTER_REGISTRY
        keys: set[str] = set()
        for entry in entries:
            if isinstance(entry, str):
                keys.add(_norm(entry))
            elif isinstance(entry, (tuple, list)) and entry:
                keys.add(_norm(entry[0]))
        keys.discard("")
        return keys or None
    except Exception:
        return None


def compute_gaps(chief: dict | None,
                 positions: dict | None,
                 rationale: dict | None,
                 registry_keys: set[str] | None,
                 analysts: dict[str, dict],
                 now: dt.datetime,
                 ages: dict[str, dict] | None = None) -> dict:
    gaps: list[dict] = []
    unchecked: list[dict] = []

    # Возраст входов (#212/#222). `ages=None` — путь без замера: судим как раньше, но КАЖДАЯ находка
    # честно говорит «возраст НЕ ИЗМЕРЕН» вместо молчаливого настоящего времени. Прод сюда не
    # попадает — `run()` всегда передаёт замер.
    ages = ages or {}
    chief_age = ages.get("chief_investment")
    book_age = ages.get("current_positions")
    chief_stale = is_too_old(chief_age)

    held: set[str] = set()
    cash_pct = None
    if positions:
        held = {_norm(k) for k in (positions.get("positions") or {})}
        cap = positions.get("capital_usd") or 0
        if cap:
            cash_pct = 100.0 * (positions.get("cash_usd") or 0) / cap
    else:
        unchecked.append({"input": "current_positions", "reason": "нет данных — гэпы по книге не измеримы"})

    # Регистры, в которых аллокатор НАЗЫВАЕТ отказ. Их три, и до 27.08 сверка читала
    # два: `below_median_cap` (потолок ниже медианы) и предупреждения теневого решения.
    # Третий — `cash.policy_refusals` — пишет тот же цикл и в тот же файл: там лежит
    # протокол, ПРИЧИНА и снятая с цели сумма. Замер 27.08 (цикл #394):
    # `spark_susds` числился «безымянным простоем» (WARN, мост завёл карточку), а в
    # `cash.policy_refusals` про него стояло `tvl_unverified_policy_gate`, $37 894.74
    # снято с цели — отказ был назван, просто НЕ ТАМ, куда смотрел сторож. Это ровно
    # тот класс, ради которого сторожей и разделяют: честный ответ на свой вопрос,
    # прочитанный как ответ на нужный. Ложная находка тратит внимание владельца.
    explained_protocols: dict = {}
    if rationale:
        for e in rationale.get("below_median_cap") or []:
            explained_protocols.setdefault(_norm(e.get("protocol")), "")
        # Чтение РАЗЛИЧАЕТ три исхода (инв. #17): раздела `cash` нет · раздел есть,
        # а отказов в нём нет · отказы есть. Форма `(… or {}).get(…) or []` склеила бы
        # первые два в один и была бы членом класса «отсутствия наблюдения не
        # существует» — храповик `test_absent_observation_ratchet` поймал её на первом
        # же прогоне подъёма (цикл #396). Здесь ветка «раздела нет» просто не даёт
        # объяснённых отказов, и это ЕДИНСТВЕННЫЙ читатель — уверенности она не
        # добавляет никому.
        cash_block = rationale.get("cash")
        refusals = cash_block.get("policy_refusals") if isinstance(cash_block, dict) else None
        for r in refusals if isinstance(refusals, list) else []:
            if not isinstance(r, dict):
                continue                     # мусор не выдаём за названный отказ
            proto = _norm(r.get("protocol"))
            reason = str(r.get("reason") or "").strip()
            if not proto or not reason:
                continue                     # отказ без ПРИЧИНЫ ничего не объясняет
            removed = r.get("usd_removed_from_target")
            if isinstance(removed, (int, float)) and not isinstance(removed, bool):
                # Разряды разделяем пробелом ТОЛЬКО внутри числа: `.replace` по всей
                # строке съел бы и запятую после причины (замерено на первом прогоне).
                amount = f"{removed:,.0f}".replace(",", " ")
                named = f"{reason}, снято с цели ${amount}"
            else:
                named = reason
            explained_protocols[proto] = named
        shadow = rationale.get("decision_shadow") or {}
        blob = json.dumps(shadow.get("warnings") or [], ensure_ascii=False).lower()
    else:
        blob = ""
        unchecked.append({"input": "allocation_rationale", "reason": "нет данных — именованные отказы не видны"})

    if chief and chief_stale:
        # ОТКАЗ, а не вердикт: снимок старше потолка офиса ⇒ утверждать по нему в настоящем
        # времени нельзя ни о постуре, ни о возможностях. Отказ НАЗВАН — молчания здесь нет.
        unchecked.append({
            "input": "chief_investment",
            "reason": f"снимок протух ({age_phrase(chief_age)}, потолок офиса "
                      f"{(MAX_INPUT_AGE_S or 0) / 3600.0:.0f} ч) — сверка ОТКАЗЫВАЕТСЯ судить о "
                      f"постуре и возможностях в настоящем времени",
        })
    elif chief:
        hv = chief.get("house_view") or {}
        posture = str(hv.get("overall_posture") or "").upper()
        # Такты входов НАЗВАНЫ в каждой находке: сверка идёт раз в 6 ч, house_view суточный, и до #222
        # 22-часовая разница молчала. Читатель обязан видеть, ЧТО с ЧЕМ сравнили и когда.
        ticks = f"{age_phrase(chief_age)} · {age_phrase(book_age)}"
        if posture in _RED_TOKENS:
            if positions and cash_pct is not None and cash_pct < 50.0:
                gaps.append({
                    "key": "gap:posture_vs_book",
                    "type": "posture_vs_book", "severity": "WARN",
                    "input_ages": {"chief_investment": chief_age, "current_positions": book_age},
                    "message": f"постура офиса {posture}, но книга развёрнута "
                               f"(cash {cash_pct:.1f}% < 50%) — офис кричит, книга не слышит "
                               f"[{ticks}]",
                })
            elif positions is None:
                unchecked.append({"input": "posture_vs_book",
                                  "reason": f"постура {posture}, но книга не измерима"})
        for opp in (hv.get("top_opportunities") or []):
            v = opp.get("value") or {}
            proto = _norm(v.get("protocol"))
            if not proto:
                continue
            if positions is None:
                continue  # уже в unchecked — не выдумывать
            if proto in held:
                continue
            base = {"protocol": proto, "apy_pct": v.get("apy_pct"),
                    "evidence_level": opp.get("evidence_level"),
                    "source": opp.get("source"),
                    "input_ages": {"chief_investment": chief_age,
                                   "current_positions": book_age}}
            if proto in explained_protocols or proto in blob:
                # Ключ НЕ трогать: он же был у этой ветки вчера. Меняется только ТЕКСТ —
                # в нём теперь стоит САМА причина, а не отсылка «см. rationale»: читатель
                # находки не обязан ходить в файл, чтобы узнать, чем отказ обоснован.
                named = explained_protocols.get(proto) or ""
                gaps.append({"key": f"gap:opportunity_explained:{proto}",
                             "type": "opportunity_unheld", "severity": "INFO",
                             "refusal": named or None,
                             "message": f"возможность {proto} {v.get('apy_pct')}% не в книге — "
                                        f"отказ НАЗВАН в rationale"
                                        + (f": {named}" if named else ""), **base})
            elif registry_keys is None:
                gaps.append({"key": f"gap:opportunity_unclassified:{proto}",
                             "type": "opportunity_unheld", "severity": "INFO",
                             "message": f"возможность {proto} не в книге; реестр адаптеров "
                                        f"недоступен — классификация не измерима", **base})
            elif proto not in registry_keys:
                gaps.append({"key": f"gap:opportunity_no_adapter:{proto}",
                             "type": "opportunity_unheld", "severity": "INFO",
                             "message": f"возможность {proto} {v.get('apy_pct')}% "
                                        f"(evidence {opp.get('evidence_level')}) вне реестра "
                                        f"адаптеров — входа технически нет (адаптер + промоушен)",
                             **base})
            else:
                gaps.append({"key": f"gap:opportunity_unnamed:{proto}",
                             "type": "opportunity_unheld", "severity": "WARN",
                             "message": f"возможность {proto} {v.get('apy_pct')}% "
                                        f"(evidence {opp.get('evidence_level')}) доступна книге, "
                                        f"не держится и отказ НЕ назван — безымянный простой "
                                        f"(дух ADR-055) [{ticks}]", **base})
    else:
        unchecked.append({"input": "chief_investment", "reason": "house_view недоступен — сверка невозможна"})

    for name, data in sorted(analysts.items()):
        tokens = {str(data.get(k) or "").upper() for k in ("posture", "status", "combined_posture")}
        if tokens & set(_ANALYST_RED_TOKENS):
            # Ключ НЕ трогать: `gap:analyst_red:<name>` — тот же, что вчера, иначе мост заведёт
            # карточку-дубль на ту же находку. Меняется только ТЕКСТ: в нём названа ПРИЧИНА (#197)
            # и — с #222 — ВОЗРАСТ снимка: «аналитик кричит CRITICAL» суточной давности читается
            # как сегодняшняя разведка ровно так же, как читалась постура.
            analyst_age = ages.get(f"analyst:{name}")
            reasons = red_reasons(data)
            if is_too_old(analyst_age):
                unchecked.append({
                    "input": f"analyst:{name}",
                    "reason": f"снимок протух ({age_phrase(analyst_age)}, потолок офиса "
                              f"{(MAX_INPUT_AGE_S or 0) / 3600.0:.0f} ч) — сверка ОТКАЗЫВАЕТСЯ "
                              f"объявлять красноту аналитика в настоящем времени",
                })
                continue
            gaps.append({"key": f"gap:analyst_red:{name}",
                         "type": "analyst_red", "severity": "WARN",
                         "posture_reason": reasons,
                         "input_ages": {f"analyst:{name}": analyst_age},
                         "message": f"аналитик {name}: {' / '.join(sorted(tokens & set(_ANALYST_RED_TOKENS)))} "
                                    f"({cause_phrase(reasons)}) "
                                    f"— требует реакции (карточка/решение), не пролистывания "
                                    f"[снимок {bare_age(analyst_age)}]"})

    return {"generated_at": now.isoformat(), "adr": "ADR-066",
            # Возраст входов — машинно, рядом с вердиктом: отчёт живёт дольше своих входов
            # (пересчёт раз в 6 ч, читают его позже — живой замер #222: отчёт 3.8 ч), и потребитель
            # обязан иметь чем это увидеть.
            "inputs": {k: v for k, v in sorted(ages.items()) if v},
            "input_age_ceiling_s": MAX_INPUT_AGE_S,
            "gaps": gaps, "unchecked": unchecked,
            "counts": {"warn": sum(1 for g in gaps if g["severity"] == "WARN"),
                       "info": sum(1 for g in gaps if g["severity"] == "INFO"),
                       "unchecked": len(unchecked)}}


def _load(rel: str, root: str):
    try:
        return json.load(open(os.path.join(root, rel)))
    except Exception:
        return None


def run(root: str = REPO_ROOT, now: dt.datetime | None = None,
        write: bool = True, receipts: bool = True) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    ages: dict[str, dict] = {}

    def _load_aged(rel: str, key: str):
        data = _load(rel, root)
        # Возраст меряем и у ОТСУТСТВУЮЩЕГО входа: `snapshot_age` вернёт `age_s: None`, и это
        # честнее, чем пропуск ключа (пропуск читается как «вход был свежий»).
        ages[key] = snapshot_age(data, os.path.join(root, rel), now)
        return data

    chief = _load_aged("data/investment_os/chief_investment.json", "chief_investment")
    positions = _load_aged("data/current_positions.json", "current_positions")
    rationale = _load_aged("data/allocation_rationale.json", "allocation_rationale")
    registry_keys = registry_protocol_keys()
    analysts = {}
    io_dir = os.path.join(root, "data", "investment_os")
    if os.path.isdir(io_dir):
        for fn in sorted(os.listdir(io_dir)):
            if fn.endswith(".json") and not fn.startswith("_") and fn != "chief_investment.json":
                d = _load(f"data/investment_os/{fn}", root)
                if isinstance(d, dict):
                    name = fn[:-5]
                    analysts[name] = d
                    ages[f"analyst:{name}"] = snapshot_age(
                        d, os.path.join(io_dir, fn), now)

    report = compute_gaps(chief, positions, rationale, registry_keys, analysts, now, ages=ages)

    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, os.path.join(root, "data", "house_view_gap.json"))
    if receipts:
        from spa_core.monitoring.consumption_receipts import write_receipt
        for rel, loaded in [("data/investment_os/chief_investment.json", chief),
                            ("data/current_positions.json", positions),
                            ("data/allocation_rationale.json", rationale)]:
            if loaded is not None:
                write_receipt(rel, "house_view_gap", root=root)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--root", default=REPO_ROOT)
    args = ap.parse_args(argv)
    if not args.run:
        ap.print_help()
        return 0
    r = run(root=args.root)
    c = r["counts"]
    print(f"house_view_gap: warn={c['warn']} info={c['info']} unchecked={c['unchecked']}")
    for g in r["gaps"]:
        print(f"  [{g['severity']}] {g['message']}")
    for u in r["unchecked"]:
        print(f"  [UNCHECKED] {u['input']}: {u['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
