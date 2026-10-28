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
