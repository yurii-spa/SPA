"""`utils.data_dir.default_file` (ADR-849 §2): песочница `SPA_DATA_DIR` сильнее УМОЛЧАНИЯ модуля,
но не явно переданного пути; без переменной путь бит-в-бит прежний (в т. ч. относительный)."""
from pathlib import Path

from spa_core.utils.data_dir import default_file


def test_unset_env_keeps_the_path_bit_for_bit(monkeypatch):
    monkeypatch.delenv("SPA_DATA_DIR", raising=False)
    assert default_file("data/x.json", "data/x.json") == "data/x.json"
    p = Path("/repo/data/x.json")
    assert default_file(p, p) is p


def test_sandbox_replaces_only_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    assert default_file("data/x.json", "data/x.json") == str(tmp_path / "x.json")
    assert default_file(Path("/repo/data/x.json"), Path("/repo/data/x.json")) == tmp_path / "x.json"


def test_explicit_path_is_never_redirected(monkeypatch, tmp_path):
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    assert default_file("/explicit/x.json", "data/x.json") == "/explicit/x.json"


def test_empty_env_is_unset_not_cwd(monkeypatch):
    monkeypatch.setenv("SPA_DATA_DIR", "  ")
    assert default_file("data/x.json", "data/x.json") == "data/x.json"


# --------------------------------------------------------------------------
# ЯВНОЕ «лога не писать» (ADR-948, цикл #1066)
# --------------------------------------------------------------------------
# Положительный контроль РЕАЛЬНОЙ аварии: с 2026-11-02 пятнадцать модулей Tier-B,
# зовущих себя протокольным путём `analyze(_legacy, config={"log_path": None})`,
# падали `TypeError … not NoneType` КАЖДЫЙ часовой прогон (`failed` 0 → 15).
# Причина — `default_file` начиналась с `os.fspath(path)`, а `None` здесь значит
# «файла не заводить». Сосед у каждой пробы с ОБРАТНЫМ ответом: `None` против
# настоящего пути в том же окружении.

def test_none_means_do_not_write_and_is_returned_as_is(monkeypatch, tmp_path):
    """`None` — это «вызывающий сказал своё», и песочница его НЕ перебивает:
    завести файл там, где его просили не заводить, было бы хуже падения."""
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    assert default_file(None, "data/x.json") is None
    assert default_file(None, Path("/repo/data/x.json")) is None


def test_a_real_default_in_the_same_environment_is_still_redirected(monkeypatch, tmp_path):
    """СОСЕД предыдущей: то же окружение, настоящий путь — ответ ДРУГОЙ.
    Значит ответ принадлежит `None`, а не тому, что переменная выставлена."""
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    assert default_file("data/x.json", "data/x.json") == str(tmp_path / "x.json")


def test_none_is_returned_without_the_env_too(monkeypatch):
    monkeypatch.delenv("SPA_DATA_DIR", raising=False)
    assert default_file(None, "data/x.json") is None
