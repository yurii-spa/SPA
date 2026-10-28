"""Сравнение сохранённых выходов двух прогонов по ЯВНОМУ перечню допустимых различий (ARB O3-01).

python3 dl_compare2.py <out_before> <out_after> [--selftest]

Правило — (файл, путь-регулярка по ОБОБЩЁННОМУ пути `a.b[].c`, класс, основание[, проверка]).
Различие, не покрытое правилом, остаётся РАЗЛИЧИЕМ. Пороги, сроки действия, свежесть, границы окон и
значимые времена событий общим правилом не снимаются: возрасты разрешены только поимённо и только если
их приращение согласуется с разницей моментов прогонов. Классы:
  STAMP        — метка формирования/наблюдения = момент прогона;
  RUN_PATH     — путь временного каталога стенда;
  PID          — идентификатор процесса;
  ELAPSED      — измеренная длительность (цена), а не порог;
  AGE          — возраст входа = «сейчас» − метка ЗАМОРОЖЕННОГО входа; проверка: приращение в пределах
                 разницы прогонов (DELTA_MIN…DELTA_MAX);
  AGE_TEXT     — текст, отличающийся ТОЛЬКО числом-возрастом в названном месте (маска одного токена);
  SELF_SCAN    — переписи исходников: +1 файл (`stand_copy.py`), сдвиг строк в изменённых модулях;
  MACHINE      — состояние машины вне стенда (деревья /tmp, объекты git, аптайм);
  CONTROLLED   — различие, причина которого доказана отдельным адресным контролем (ссылка в основании);
  UNCONFIRMED  — отнесено к часам/машине по построению, но ОТДЕЛЬНО НЕ ПЕРЕМЕРЕНО: печатается как различие
                 со статусом «не подтверждено», в «равно» не засчитывается.
"""
import json
import os
import re
import sys

# Разница моментов прогонов: старты 09:10Z и 10:51Z (101 мин); прогон «после» короче на 18,6 мин, поэтому
# один и тот же шаг шёл позже на 82…101 мин. Допуск с запасом на позицию шага внутри прогона.
DELTA_MIN_H, DELTA_MAX_H = 1.2, 1.8

GEN = re.compile(r"\[\d+\]")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
TMP = re.compile(r"/(private/)?(var/folders|tmp)/\S+?(?=[\s,;)»\"]|$)")


def _iso(a, b):
    return bool(ISO.match(str(a))) and bool(ISO.match(str(b)))


def _age(unit_h):
    def check(a, b):
        try:
            d = (float(b) - float(a)) * unit_h
        except (TypeError, ValueError):
            return False
        return DELTA_MIN_H <= d <= DELTA_MAX_H
    return check


def _text_mask(pattern):
    rx = re.compile(pattern)

    def check(a, b):
        ma, mb = rx.sub("<AGE>", str(a)), rx.sub("<AGE>", str(b))
        return ma == mb and ma != str(a)
    return check


def _tmp_text(a, b):
    return TMP.sub("<tmp>", str(a)) == TMP.sub("<tmp>", str(b))


def _plus_one(a, b):
    try:
        return int(b) - int(a) == 1
    except (TypeError, ValueError):
        return False


def _shift_lines(a, b):
    try:
        return -8 <= int(b) - int(a) <= -7
    except (TypeError, ValueError):
        return False


H, S_, D = 1.0, 1 / 3600.0, 24.0
RULES = [
    # (файл-регулярка, путь-регулярка, класс, основание, проверка или None)
    (r".*", r"^\.generated_at$|^\.axis_b_cost\.provenance\.generated_at$", "STAMP", "метка формирования отчёта", _iso),
    (r".*\.jsonl$", r"^\[\]\.(observed_at|consumed_at)$", "STAMP", "метка наблюдения/квитанции = момент прогона", _iso),
    (r"adapter_feed_divergence\.json", r"^\.history\.by_key\..*\.last_seen$", "STAMP", "последнее наблюдение = этот прогон", _iso),
    (r"judge_alone_price\.json", r"^\.stand_root$", "RUN_PATH", "временный каталог стенда", _tmp_text),
    (r"judge_alone_price\.json", r"^\.stand_disposal_reason$", "RUN_PATH", "текст с путём временного стенда", _tmp_text),
    (r"heir_all_rows_price\.json", r"^\.stand\.s_\w+$", "RUN_PATH", "пути временных стендов", _tmp_text),
    (r"(claim_guard_receipt_readers|receipt_channel_cost)\.json", r"\.anchor\.pid$", "PID", "pid процесса прогона", None),
    (r"foreign_done_cost\.json", r"^\.door\.(holder\.pid|stranger_label)$", "PID", "pid процесса прогона", None),
    (r"s49_tally_tact\.json", r"^\.tally_cost_s$", "ELAPSED", "измеренная длительность подсчёта", None),
    (r"rule_second_copy_census\.json", r"cost_s_measured$|^\.reader_cost_of_test_channel\.combined_cost_s$", "ELAPSED", "измеренная цена", None),
    (r"history_door_price\.json", r"\.outcome\.latency_seconds$", "ELAPSED", "измеренная задержка", None),
    # AGE — поимённо, с проверкой приращения
    (r"house_view_gap\.json", r"\.age_s$", "AGE", "возраст замороженного входа, сек", _age(S_)),
    (r"apy_composition\.json", r"^\.input\.age_s$", "AGE", "возраст входа, сек", _age(S_)),
    (r"capital_evidence_coverage\.json", r"book_age_s$", "AGE", "возраст книги, сек", _age(S_)),
    (r"(book_oscillation_census|gain_persistence_census)\.json", r"\[\]\.age_hours$", "AGE", "возраст хода/наблюдения, ч", _age(H)),
    (r"evidence_staleness\.json", r"^\.protocols\[\]\.age_hours$", "AGE", "возраст наблюдения, ч", _age(H)),
    (r"claim_release_census\.json", r"^\.open_claims\.age_hours\.(max|min|p50)$", "AGE", "возраст захватов, ч", _age(H)),
    (r"decision_audit_trail\.json", r"^\.moves\[\]\.age_days$", "AGE", "возраст хода, дни", _age(D)),
    (r"declared_source_live_parity\.json", r"^\.operand_age_hours$", "AGE", "возраст операнда, ч", _age(H)),
    (r"rebalance_cost_evidence\.json", r"^\.observed_gas\.chains\.\w+\.age_hours$", "AGE", "возраст наблюдения газа, ч", _age(H)),
    (r"loop_retro\.json", r"^\.analysts\[\]\.stale_h$", "AGE", "возраст аналитика, ч", _age(H)),
    (r"slo_keepability\.json", r"(mtime|stamp)_age_hours$", "AGE", "возраст артефакта, ч", _age(H)),
    (r"unknown_class_in_the_artifact\.json", r"(oldest_artifact_hours|artifact_age_hours)$", "AGE", "возраст артефакта, ч", _age(H)),
    (r"(adapter_feed_divergence|apy_composition)\.json", r"^\.history\.covered_days$", "AGE", "охват истории до «сейчас», дни", _age(D)),
    # AGE_TEXT — маска ОДНОГО числа-возраста в названном месте
    (r"evidence_staleness\.json", r"^\.protocols\[\]\.reason$", "AGE_TEXT", "«(X ч ≤ 36 ч)» — маскируется только X", _text_mask(r"(?<=\()[\d.]+(?= ч ≤)")),
    (r"slo_keepability\.json", r"\.note$", "AGE_TEXT", "«записан X ч назад», «отметка артефакта (X ч)» — маскируется только X", _text_mask(r"(?<=записан )[\d.]+(?= ч назад)|(?<=отметка артефакта \()[\d.]+(?= ч\))")),
    (r"slo_keepability\.json", r"\.(rows|findings)\[\]\.(periods|runs|span_hours|observed_max_hours|observed_median_hours|records)$|\.(rows|findings)\[\]\.periods\[\]$", "UNCONFIRMED", "такт агентов по ЖИВЫМ журналам запусков машины (не по стенду): между прогонами агенты отработали — отдельно не перемерено", None),
    (r"rebalance_cost_evidence\.json", r"^\.findings\[\]\.message$", "AGE_TEXT", "«чтение X ч назад» — только X", _text_mask(r"(?<=чтение )[\d.]+(?= ч назад)")),
    (r"declared_source_live_parity\.json", r"^\.what_it_does_not_prove\[\]$", "AGE_TEXT", "«(Xч назад)» — только X", _text_mask(r"(?<=\()[\d.]+(?=ч назад\))")),
    (r"house_view_gap\.json", r"^\.gaps\[\]\.message$", "AGE_TEXT", "«постура X ч назад · книга Y ч назад» — только X и Y", _text_mask(r"(?<=постура )[\d.]+(?= ч назад)|(?<=книга )[\d.]+(?= ч назад)")),
    (r"adapter_feed_divergence\.json", r"^\.inputs\.\w+\.age_s$", "AGE", "возраст входа, сек", _age(S_)),
    (r"rebalance_cost_evidence\.json", r"^\.verdict_freshness\.age_hours$", "AGE", "возраст вердикта, ч", _age(H)),
    (r"heir_all_rows_price\.json", r"^\.stand_disposal_reason$", "RUN_PATH", "текст с путём временного стенда", _tmp_text),
    (r"decision_audit_trail\.json", r"^\.snapshot_id_probe\.samples\[\]$", "NONDET_BY_DESIGN", "выборка НЕ контент-адресованных id; сама проба меряет same_input_same_output=False, и это поле равно в обоих прогонах", None),
    # SELF_SCAN — предмет правки: +1 файл, сдвиг строк на −7…−8
    (r"(foreign_markup_reader_census|mutation_application_census)\.json", r"^\.files_scanned$", "SELF_SCAN", "+1 файл stand_copy.py", _plus_one),
    (r"cio_architecture_constraints\.json", r"^\.modules_parsed$", "SELF_SCAN", "+1 модуль", _plus_one),
    (r"(hand_truncation_census|tact_gate_census|truncated_input_census)\.json", r"^\.scanned$", "SELF_SCAN", "+1 файл", _plus_one),
    (r"weak_axis_mapping_origin\.json", r"^\.files_parsed$", "SELF_SCAN", "+1 файл", _plus_one),
    (r"hand_truncation_census\.json", r"^\.(call_sites|counts\.no_hand_cut|rows#len)$", "SELF_SCAN", "+1 место вызова в stand_copy.py", _plus_one),
    (r"tact_gate_census\.json", r"^\.counts\.no_gate$", "SELF_SCAN", "+1 место в stand_copy.py", _plus_one),
    (r"rule_second_copy_census\.json", r"^\.(classified|executors|name_channel\.files_read)$", "SELF_SCAN", "+1 файл", _plus_one),
    (r"(hand_truncation_census|tact_gate_census|rule_second_copy_census|census_consumer_census)\.json",
     r"(\.line|\.cut_line|\.lines\[\])$", "SELF_SCAN", "номер строки сдвинут на −7…−8 (цикл копирования стал короче)", _shift_lines),
    # MACHINE
    (r"unannounced_span\.json", r"^\.sources\.registered_trees$", "MACHINE", "число деревьев в /tmp меняют другие сессии", None),
    (r"history_door_price\.json", r"\.price\.(loose_kib|loose_objects|total_kib)$", "MACHINE", "общий объектный каталог git пополняют другие сессии", None),
    (r"tree_lifetime_census\.json", r"(uptime_hours|survived_hours|longest_survival_hours|window_hours)$", "MACHINE", "аптайм и деревья /tmp машины", None),
    # CONTROLLED — доказано адресным контролем
    (r"asset_registry_gap_price\.json", r".*", "CONTROLLED",
     "21↔22 латентных координат воспроизводится на НЕИЗМЕНЁННОМ main при одних данных и часах сменой одного PYTHONHASHSEED (seed 3,7 → 21; 0,1,2,4,5,6 → 22); стенд seed не закреплял", None),
    (r"run_identity_key_price\.json", r".*", "CONTROLLED",
     "читатель /api/agents/registry: при одних данных, часах, seed и кеше (флот не спрошен) old/clone/fallback дают одинаковую строку (rikp_ctl_*.json)", None),
    # UNCONFIRMED — по построению часы, но отдельно не перемерено
    (r"duplicate_subject_census\.json", r".*", "UNCONFIRMED", "окно `window_from` сдвинуто вместе с часами на 82 мин; ±1 в счётчиках окна — отдельно не перемерено", None),
    (r"claim_release_census\.json", r"would_close_dead_holder$", "UNCONFIRMED", "лестница истечений: +1 захват перешёл порог по возрасту — отдельно не перемерено", None),
    (r"rule_second_copy_census\.json", r"^\.reader_cost_of_test_channel\.blind\[\]$", "UNCONFIRMED", "текст с измеренной ценой — отдельно не разобран", None),
]


def classify(rel, path, a, b):
    g = GEN.sub("[]", path)
    for frx, prx, cls, why, check in RULES:
        if re.fullmatch(frx, rel) and re.search(prx, g):
            if check is not None and not check(a, b):
                return "DIFFERENT", f"правило {cls} не выполнено: {why}"
            return cls, why
    return "DIFFERENT", "нет правила"


def walk(a, b, p, out):
    if type(a) != type(b):
        out.append((p, a, b)); return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            walk(a.get(k, "<absent>"), b.get(k, "<absent>"), f"{p}.{k}", out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((p + "#len", len(a), len(b)))
        for i, (u, v) in enumerate(zip(a, b)):
            walk(u, v, f"{p}[{i}]", out)
    elif a != b:
        out.append((p, a, b))


def load(p):
    raw = open(p, "rb").read()
    try:
        t = raw.decode("utf-8")
        return [json.loads(l) for l in t.splitlines() if l.strip()] if p.endswith(".jsonl") else json.loads(t)
    except Exception:
        return ("RAW", raw)


def compare_docs(rel, x, y):
    out = []
    if isinstance(x, tuple) or isinstance(y, tuple):
        if x != y:
            out.append(("<raw>", "bytes", "bytes"))
    else:
        walk(x, y, "", out)
    return [(p, a, b) + classify(rel, p, a, b) for p, a, b in out]


def selftest():
    """Отрицательные контроли ARB: пороги, срок действия и возраст НЕ равны по умолчанию."""
    base = {"generated_at": "2026-10-28T10:00:00Z", "freshness_limit_s": 60, "decision_ttl_s": 600, "data_age_s": 10}
    for key, new in (("freshness_limit_s", 15), ("decision_ttl_s", 900), ("data_age_s", 600)):
        after = dict(base, **{key: new}, generated_at="2026-10-28T11:30:00Z")
        rows = compare_docs("pre_trade_recheck_census.json", base, after)
        cls = {r[0]: r[3] for r in rows}
        assert cls.get("." + key) == "DIFFERENT", (key, cls)
        assert cls.get(".generated_at") == "STAMP", cls
    # возраст, разрешённый поимённо, НЕ проходит при приращении вне разницы прогонов
    rows = compare_docs("house_view_gap.json", {"inputs": {"x": {"age_s": 100}}}, {"inputs": {"x": {"age_s": 100 + 600}}})
    assert rows[0][3] == "DIFFERENT", rows
    rows = compare_docs("house_view_gap.json", {"inputs": {"x": {"age_s": 100}}}, {"inputs": {"x": {"age_s": 100 + 6000}}})
    assert rows[0][3] == "AGE", rows
    # маска текста трогает только число-возраст, порог в тексте остаётся предметом
    rows = compare_docs("evidence_staleness.json", {"protocols": [{"reason": "наблюдение свежее (4.8 ч ≤ 36 ч)"}]},
                        {"protocols": [{"reason": "наблюдение свежее (6.2 ч ≤ 24 ч)"}]})
    assert rows[0][3] == "DIFFERENT", rows
    print("selftest OK: freshness_limit_s 60→15, decision_ttl_s 600→900, data_age_s 10→600 — DIFFERENT; "
          "возраст вне разницы прогонов — DIFFERENT; порог в тексте — DIFFERENT")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    A, B = sys.argv[1], sys.argv[2]
    fa = json.load(open(os.path.join(A, "result.json")))["changed_files"]
    fb = json.load(open(os.path.join(B, "result.json")))["changed_files"]
    summary = {"files": len(fa), "only_before": sorted(set(fa) - set(fb)), "only_after": sorted(set(fb) - set(fa))}
    per_class, per_file, different = {}, {}, []
    for rel in sorted(set(fa) & set(fb)):
        rows = compare_docs(rel, load(os.path.join(A, "data", rel)), load(os.path.join(B, "data", rel)))
        classes = sorted({r[3] for r in rows})
        per_file[rel] = classes or ["EQUAL"]
        for r in rows:
            per_class[r[3]] = per_class.get(r[3], 0) + 1
            if r[3] == "DIFFERENT":
                different.append([rel, r[0], str(r[1])[:120], str(r[2])[:120], r[4]])
    files_by_worst = {}
    for rel, cl in per_file.items():
        worst = ("DIFFERENT" if "DIFFERENT" in cl else "UNCONFIRMED" if "UNCONFIRMED" in cl
                 else "CONTROLLED" if "CONTROLLED" in cl else "EXPLAINED" if cl != ["EQUAL"] else "EQUAL")
        files_by_worst[worst] = files_by_worst.get(worst, 0) + 1
    summary.update(fields_by_class=per_class, files_by_worst_class=files_by_worst, different=different)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
