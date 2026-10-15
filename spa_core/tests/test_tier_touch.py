"""Контроль в обе стороны для признака «трогает ли файл канон тира» и для его приёмки.

Предмет — карточка `inbox-storozh-tira-sudit-podstrokoi-i-krasen-n` (02.10): сторож
`test_tier_curator::test_no_module_consumes_report_to_mutate_tiers` судил ПОДСТРОКОЙ и
потому был красен на верном состоянии тринадцать суток, а настоящий ввоз, записанный
иначе, не видел ВООБЩЕ. Прибор `spa_core/monitoring/tier_touch.py` отвечает на тот же
вопрос разбором; проба `tier_guard_judges_code_not_prose` меряет исход.

Каждое звено проверяется с ОБЕИХ сторон, и у каждой обратной стороны НАЗВАНО звено:
прибор, который не кусается, — украшение; прибор, который кусается на прозе, — прежний
ложный красный; проглоченная опечатка — ложный зелёный, которого не видно никому.
"""
from __future__ import annotations

import os
import shutil

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import tier_touch as tt

PROBE = "tier_guard_judges_code_not_prose"


# ─── Прибор: кусается на КАЖДОЙ форме записи ─────────────────────────────────

@pytest.mark.parametrize("label,source", ca.TIER_TOUCH_FORMS)
def test_every_declared_form_is_caught(label, source):
    """Положительный контроль по закрытому перечню форм — ни одна не проходит мимо."""
    touches = tt.tier_touches(source)
    assert touches, f"форма «{label}» не поймана: {source.strip()!r}"


def test_the_form_list_covers_every_kind_the_instrument_can_report():
    """Перечень форм пробы не вправе быть УЖЕ набора родов, которые прибор различает.

    Иначе проба зелена на приборе, слепом к целому роду записи: `dynamic` выпал бы
    из перечня, и `getattr(m, "RiskConfig")` снова проходил бы молча.
    """
    kinds = set()
    for _label, source in ca.TIER_TOUCH_FORMS:
        kinds |= {t.kind for t in tt.tier_touches(source)}
    assert kinds == {"import", "name", "attribute", "dynamic"}, (
        f"перечень форм покрывает только роды {sorted(kinds)}")


#: ДОСЛОВНЫЙ перечень прежнего подстрочного сторожа (объединение двух его списков,
#: `origin/main` fe5ab084c). Нужен затем, чтобы «прибор сильнее подстроки» было
#: ЗАМЕРОМ, а не прозой: перечень прогоняется по тем же исходникам рядом.
LEGACY_SUBSTRINGS = ("PROTOCOL_RISK_SCORES", "ADAPTER_REGISTRY", "tier_map",
                     "RiskConfig", "risk.policy", "adapters.registry",
                     "protocol_risk_map", "from spa_core.analytics.tier_curator import")


def test_the_instrument_sees_what_a_substring_could_not():
    """Дифференциальный контроль: у прежнего признака ЕСТЬ слепые формы, у прибора нет.

    Без этого теста утверждение «перешли с подстроки на разбор» осталось бы прозой:
    зелёный прибор сам по себе не доказывает, что он видит БОЛЬШЕ.
    """
    blind = []
    for label, source in ca.TIER_TOUCH_FORMS:
        assert tt.tier_touches(source), f"прибор не поймал форму «{label}»"
        if not any(tok in source for tok in LEGACY_SUBSTRINGS):
            blind.append(label)
    assert blind, ("ни одна объявленная форма не слепа для подстроки — контроль "
                   "ничего не доказывает, перечень форм надо пополнить")


def test_plain_import_of_the_module_is_caught_without_the_name():
    """`import spa_core.risk.policy` не несёт ни одного запрещённого ИМЕНИ.

    Подстрочный список ловил его случайно — хвостом `risk.policy`; у прибора это
    отдельное утверждение о модуле, и оно проверено отдельно.
    """
    touches = tt.tier_touches("import spa_core.risk.policy\n")
    assert [t.token for t in touches] == ["risk.policy"]
    assert touches[0].kind == "import"


# ─── Прибор: молчит на ПРОЗЕ ─────────────────────────────────────────────────

def test_prose_is_not_a_touch():
    """Дословная сцена 02.10: докстрока о ЧУЖОМ приборе плюс сообщение в f-строке."""
    assert tt.tier_touches(ca.TIER_PROSE_SCENE) == []


def test_message_in_an_ordinary_call_is_not_a_touch():
    """Строка-СООБЩЕНИЕ в обычном вызове прозой и остаётся.

    Если бы строкой в аргументе ЛЮБОГО вызова считалось обращение, прибор краснел бы
    на `_log("из RiskConfig (N полей)")` — то есть вернул бы подстроку под видом разбора.
    """
    assert tt.tier_touches('_log("из RiskConfig (N полей)")\n') == []
    assert tt.tier_touches('raise ValueError("tier_map не выбран")\n') == []


def test_dot_boundary_is_respected():
    """Хвост модуля сверяется по ГРАНИЦЕ ТОЧКИ, а не подстрокой."""
    assert tt.tier_touches("import myrisk.policy\n") == []
    assert tt.tier_touches("import vendor.risk.policy\n"), (
        "настоящий хвост `risk.policy` обязан ловиться на любой приставке")


def test_comment_is_not_a_touch():
    """Комментарий в разборе не существует вовсе — это и есть смысл перехода на AST."""
    assert tt.tier_touches("# тут мог бы быть RiskConfig и tier_map\nX = 1\n") == []


# ─── Прибор: третий исход назван, а не подменён ──────────────────────────────

def test_unparseable_source_is_the_third_outcome():
    """Опечатка — НЕ «чисто» (инв. #17). Пустой список здесь был бы ложным зелёным."""
    with pytest.raises(tt.TierTouchUnmeasured):
        tt.tier_touches("def broken(:\n    tier_map\n")


def test_touches_are_deduplicated_and_ordered():
    """Отчёт устойчив: порядок обхода дерева не вправе менять текст падения."""
    source = ("from spa_core.risk.policy import RiskConfig\n"
              "y = RiskConfig\n"
              "z = RiskConfig\n")
    touches = tt.tier_touches(source)
    assert touches == sorted(touches, key=lambda t: (t.token, t.kind, t.line))
    assert len(touches) == len(set(touches)), "повторы не свёрнуты"


# ─── Проба приёмки: зелена на целом контуре, красна на КАЖДОМ порванном звене ──

def _scene(tmp_path) -> str:
    """Одноразовое дерево из РОВНО тех файлов, которые проба читает."""
    root = str(tmp_path / "tree")
    for rel in ca.TIER_REPORT_READERS + (ca.TIER_GUARD_FILE,):
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(ca.REPO_ROOT, rel), dst)
    return root


def _verdict(root, **kw):
    return ca.PROBES[PROBE].__wrapped__(None, repo_root=root, **kw) \
        if hasattr(ca.PROBES[PROBE], "__wrapped__") else \
        ca.PROBES[PROBE](None, repo_root=root, **kw)


def test_probe_is_green_on_the_live_tree():
    status, detail = ca.PROBES[PROBE](None)
    assert status == ca.SATISFIED, detail


def test_probe_is_green_on_the_disposable_copy(tmp_path):
    status, detail = _verdict(_scene(tmp_path))
    assert status == ca.SATISFIED, detail


def test_probe_refuses_an_argument():
    status, detail = ca.PROBES[PROBE]("some_file.py")
    assert status == ca.UNMEASURED and "аргумента" in detail


def test_link_live_reader_touches_the_canon(tmp_path):
    """Звено 1 порвано: в разрешённого читателя подсаживается НАСТОЯЩИЙ ввоз."""
    root = _scene(tmp_path)
    target = os.path.join(root, ca.TIER_REPORT_READERS[1])
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("\nfrom spa_core.risk.policy import RiskConfig as _RC\n")
    status, detail = _verdict(root)
    assert status == ca.NOT_SATISFIED
    assert "ТРОГАЕТ канон" in detail and "RiskConfig" in detail
    assert ca.TIER_REPORT_READERS[1] in detail, "звено не НАЗВАНО"


def test_link_prose_in_a_reader_stays_green(tmp_path):
    """Обратная сторона звена 1: ПРОЗА в читателе зелена — иначе вернулся бы 02.10."""
    root = _scene(tmp_path)
    target = os.path.join(root, ca.TIER_REPORT_READERS[1])
    with open(target, "a", encoding="utf-8") as fh:
        fh.write('\n\ndef _note(n):\n    """читает из `RiskConfig` — ЧУЖОЙ прибор."""\n'
                 '    return f"из RiskConfig ({n} полей)"\n')
    status, detail = _verdict(root)
    assert status == ca.SATISFIED, detail


def test_link_instrument_never_bites(tmp_path, monkeypatch):
    """Звено 2 порвано: прибор, который не краснеет ни на чём, — украшение."""
    monkeypatch.setattr(tt, "tier_touches", lambda source, **kw: [])
    status, detail = _verdict(_scene(tmp_path))
    assert status == ca.NOT_SATISFIED
    assert "НЕ КУСАЕТСЯ" in detail
    assert any(label in detail for label, _ in ca.TIER_TOUCH_FORMS), "форма не НАЗВАНА"


def test_link_instrument_bites_on_prose(tmp_path, monkeypatch):
    """Звено 3 порвано: прибор краснеет на прозе — прежний ложный красный."""
    real = tt.tier_touches

    def bites_on_prose(source, **kw):
        if source == ca.TIER_PROSE_SCENE:
            return [tt.Touch("RiskConfig", "name", 1)]
        return real(source, **kw)

    monkeypatch.setattr(tt, "tier_touches", bites_on_prose)
    status, detail = _verdict(_scene(tmp_path))
    assert status == ca.NOT_SATISFIED and "ПРОЗЕ" in detail


def test_link_unparseable_is_swallowed(tmp_path, monkeypatch):
    """Звено 4 порвано: прибор отдаёт опечатку за чистоту (инв. #17)."""
    real = tt.tier_touches

    def swallow(source, **kw):
        try:
            return real(source, **kw)
        except tt.TierTouchUnmeasured:
            return []

    monkeypatch.setattr(tt, "tier_touches", swallow)
    status, detail = _verdict(_scene(tmp_path))
    assert status == ca.NOT_SATISFIED and "третьим исходом" in detail


def test_link_guard_does_not_call_the_instrument(tmp_path):
    """Звено 5 порвано: сторож прибор не зовёт — признак снова живёт своей копией."""
    root = _scene(tmp_path)
    guard = os.path.join(root, ca.TIER_GUARD_FILE)
    with open(guard, encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace("from spa_core.monitoring.tier_touch import "
                        "describe, tier_touches", "describe = tier_touches = None")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write(text)
    status, detail = _verdict(root)
    assert status == ca.NOT_SATISFIED and "не ЗОВЁТ прибор" in detail


def test_link_mention_of_the_instrument_in_prose_is_not_a_call(tmp_path):
    """Проба НЕ проходит подстрокой (ADR-333): упоминание имени прибора — не зов."""
    root = _scene(tmp_path)
    guard = os.path.join(root, ca.TIER_GUARD_FILE)
    with open(guard, encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace("from spa_core.monitoring.tier_touch import "
                        "describe, tier_touches",
                        '"""здесь когда-то звали spa_core.monitoring.tier_touch."""\n'
                        "describe = tier_touches = None")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write(text)
    status, detail = _verdict(root)
    assert status == ca.NOT_SATISFIED and "не ЗОВЁТ прибор" in detail


def test_link_guard_keeps_its_own_copy_of_the_canon(tmp_path):
    """Звено 5, вторая половина: два перечня на одно правило разъехались бы молча."""
    root = _scene(tmp_path)
    guard = os.path.join(root, ca.TIER_GUARD_FILE)
    with open(guard, "a", encoding="utf-8") as fh:
        fh.write('\nFORBIDDEN = ("RiskConfig", "tier_map", "protocol_risk_map")\n')
    status, detail = _verdict(root)
    assert status == ca.NOT_SATISFIED
    assert "свою копию перечня" in detail and "RiskConfig" in detail


def test_link_file_absent_is_unmeasured_not_clean(tmp_path):
    """Нечитаемый файл — «не измерено» с причиной, а не «чисто» (инв. #17)."""
    root = _scene(tmp_path)
    os.remove(os.path.join(root, ca.TIER_REPORT_READERS[0]))
    status, detail = _verdict(root)
    assert status == ca.UNMEASURED and "НЕ ИЗМЕРЕНА" in detail


def test_guard_file_absent_is_unmeasured(tmp_path):
    root = _scene(tmp_path)
    os.remove(os.path.join(root, ca.TIER_GUARD_FILE))
    status, detail = _verdict(root)
    assert status == ca.UNMEASURED and "зовущий НЕ ИЗМЕРЕН" in detail
