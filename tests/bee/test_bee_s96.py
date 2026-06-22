"""
Тесты BEE S9.6: verify_integration.py + verifier/bee_verify.py
================================================================
EPIC-9 / ADR-043

Покрытие:
  - PIN/verify round trip (ok=True)
  - Tamper detection (изменение файла после PIN → ok=False)
  - Fail-closed: файл не найден → ok=False
  - Fail-closed: нет PIN при verify → ok=False, status='not_pinned'
  - Hash chain: построение, линковка блоков, исключение failed pins
  - Standalone verifier: verify_one / verify_all / verify_chain
  - LLM_FORBIDDEN: нет AI-зависимостей

LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_root():
    return _PROJECT_ROOT


@pytest.fixture
def vi(project_root, tmp_path, monkeypatch):
    """
    Импортирует verify_integration и перенаправляет _HASH_DIR / _PIN_DIR /
    _CHAIN_FILE в tmp_path чтобы тесты не трогали боевые data/bee/.
    """
    import spa_core.bee.verify_integration as vi_mod

    monkeypatch.setattr(vi_mod, "_HASH_DIR", tmp_path / "hashes")
    monkeypatch.setattr(vi_mod, "_PIN_DIR", tmp_path / "pinned")
    monkeypatch.setattr(vi_mod, "_CHAIN_FILE", tmp_path / "hash_chain.json")

    return vi_mod


@pytest.fixture
def bv(project_root, tmp_path, monkeypatch):
    """
    Импортирует verifier.bee_verify и перенаправляет _HASH_DIR / _PIN_DIR /
    _CHAIN_FILE в tmp_path.
    """
    import verifier.bee_verify as bv_mod

    monkeypatch.setattr(bv_mod, "_HASH_DIR", tmp_path / "hashes")
    monkeypatch.setattr(bv_mod, "_PIN_DIR", tmp_path / "pinned")
    monkeypatch.setattr(bv_mod, "_CHAIN_FILE", tmp_path / "hash_chain.json")

    return bv_mod


# ---------------------------------------------------------------------------
# TestPinVerifyRoundTrip — verify_integration.pin_file + verify_file
# ---------------------------------------------------------------------------

class TestPinVerifyRoundTrip:
    """PIN → verify round trip через verify_integration."""

    def test_pin_ok_returns_sha256(self, vi, tmp_path):
        """pin_file возвращает ok=True и sha256."""
        test_file = tmp_path / "output.json"
        test_file.write_text(json.dumps({"value": 42, "status": "ok"}))

        result = vi.pin_file(test_file, name="output")

        assert result["ok"] is True, f"Expected ok=True, got: {result}"
        assert "sha256" in result
        assert len(result["sha256"]) == 64  # hex SHA256

    def test_verify_after_pin_ok(self, vi, tmp_path):
        """verify_file после pin_file → ok=True, status='match'."""
        test_file = tmp_path / "report.json"
        test_file.write_text(json.dumps({"apy": 4.5, "protocol": "aave"}))

        vi.pin_file(test_file, name="report")
        result = vi.verify_file(test_file, name="report")

        assert result["ok"] is True, f"Expected ok=True, got: {result}"
        assert result["status"] == "match"

    def test_tamper_detected(self, vi, tmp_path):
        """Изменение файла после PIN → ok=False, status='tampered'."""
        test_file = tmp_path / "data.json"
        test_file.write_text(json.dumps({"value": 42}))
        vi.pin_file(test_file, name="data")

        # Подменяем содержимое
        test_file.write_text(json.dumps({"value": 99}))  # tampered!

        result = vi.verify_file(test_file, name="data")

        assert result["ok"] is False, f"Expected ok=False, got: {result}"
        assert result["status"] == "tampered"

    def test_pin_missing_file_fail_closed(self, vi, tmp_path):
        """pin_file несуществующего файла → ok=False с FAIL_CLOSED."""
        result = vi.pin_file(tmp_path / "nonexistent.json", name="missing")

        assert result["ok"] is False
        assert "FAIL_CLOSED" in result.get("error", ""), (
            f"Expected FAIL_CLOSED in error, got: {result}"
        )

    def test_verify_without_pin_not_pinned(self, vi, tmp_path):
        """verify_file без PIN → ok=False, status='not_pinned'."""
        test_file = tmp_path / "some.json"
        test_file.write_text("{}")

        result = vi.verify_file(test_file, name="some")

        assert result["ok"] is False
        assert result["status"] == "not_pinned"

    def test_canonical_form_deterministic(self, vi, tmp_path):
        """Два файла с одинаковым содержимым но разным порядком ключей → одинаковый хэш."""
        file_a = tmp_path / "a.json"
        file_b = tmp_path / "b.json"
        # Разный порядок ключей — canonical JSON должен дать одинаковый хэш
        file_a.write_text('{"z": 1, "a": 2}')
        file_b.write_text('{"a": 2, "z": 1}')

        vi.pin_file(file_a, name="a_test")
        # Верифицируем b против пина a — хэши должны совпасть (canonical sort_keys)
        result = vi.verify_file(file_b, name="a_test")
        assert result["ok"] is True, (
            f"Canonical form must be order-independent, got: {result}"
        )

    def test_hash_dir_created(self, vi, tmp_path):
        """pin_file создаёт hashes/ и pinned/ если их нет."""
        assert not (tmp_path / "hashes").exists()

        test_file = tmp_path / "x.json"
        test_file.write_text('{"x": 1}')
        vi.pin_file(test_file, name="x")

        assert (tmp_path / "hashes" / "x.json").exists()
        assert (tmp_path / "pinned" / "x.json").exists()


# ---------------------------------------------------------------------------
# TestHashChain — build_hash_chain
# ---------------------------------------------------------------------------

class TestHashChain:
    """Тесты hash chain построения и структуры."""

    def test_chain_built_and_saved(self, vi, tmp_path):
        """build_hash_chain создаёт hash_chain.json."""
        results = [
            {"ok": True, "name": "file1", "sha256": "abc123"},
            {"ok": True, "name": "file2", "sha256": "def456"},
        ]
        chain = vi.build_hash_chain(results)

        assert chain["chain_length"] == 2
        assert "chain_head" in chain
        assert chain["tamper_evident"] is True
        assert chain["LLM_FORBIDDEN"] is True
        assert (tmp_path / "hash_chain.json").exists()

    def test_chain_genesis_is_first_prev(self, vi, tmp_path):
        """Первый блок ссылается на GENESIS."""
        results = [{"ok": True, "name": "f1", "sha256": "aaa"}]
        chain = vi.build_hash_chain(results)

        assert chain["entries"][0]["prev_hash"] == "GENESIS"

    def test_chain_blocks_linked(self, vi, tmp_path):
        """Каждый блок ссылается на block_hash предыдущего."""
        results = [
            {"ok": True, "name": f"file{i}", "sha256": f"hash{i:03d}"}
            for i in range(3)
        ]
        chain = vi.build_hash_chain(results)
        entries = chain["entries"]

        assert entries[1]["prev_hash"] == entries[0]["block_hash"]
        assert entries[2]["prev_hash"] == entries[1]["block_hash"]

    def test_failed_pins_excluded_from_chain(self, vi, tmp_path):
        """Неудачные PIN (ok=False) не включаются в chain."""
        results = [
            {"ok": True, "name": "good", "sha256": "abc"},
            {"ok": False, "name": "bad", "error": "missing"},
            {"ok": True, "name": "also_good", "sha256": "def"},
        ]
        chain = vi.build_hash_chain(results)

        assert chain["chain_length"] == 2  # только good + also_good
        names = [e["name"] for e in chain["entries"]]
        assert "good" in names
        assert "also_good" in names
        assert "bad" not in names

    def test_empty_results_empty_chain(self, vi, tmp_path):
        """Пустые результаты → chain_length=0, chain_head='GENESIS'."""
        chain = vi.build_hash_chain([])

        assert chain["chain_length"] == 0
        assert chain["chain_head"] == "GENESIS"

    def test_chain_head_equals_last_block_hash(self, vi, tmp_path):
        """chain_head == block_hash последнего блока."""
        results = [
            {"ok": True, "name": "a", "sha256": "111"},
            {"ok": True, "name": "b", "sha256": "222"},
        ]
        chain = vi.build_hash_chain(results)

        assert chain["chain_head"] == chain["entries"][-1]["block_hash"]

    def test_previous_chain_hash_propagates(self, vi, tmp_path):
        """Если передан previous_chain_hash, первый блок ссылается на него."""
        results = [{"ok": True, "name": "r1", "sha256": "xyz"}]
        chain = vi.build_hash_chain(results, previous_chain_hash="prev_sentinel")

        assert chain["entries"][0]["prev_hash"] == "prev_sentinel"
        assert chain["genesis"] is False


# ---------------------------------------------------------------------------
# TestRunFullVerification — оркестратор
# ---------------------------------------------------------------------------

class TestRunFullVerification:
    """Тесты оркестратора run_full_verification."""

    def test_full_verification_with_real_files(self, vi, tmp_path):
        """Если файлы существуют → все пиннированы и верифицированы."""
        # Создаём все BEE output файлы
        (tmp_path / "data" / "bee").mkdir(parents=True)
        files = [
            "data/bee/safety_report.json",
            "data/bee/backtest_live_fit.json",
        ]
        for rel in files:
            p = tmp_path / rel
            p.write_text(json.dumps({"status": "ok", "file": rel}))

        summary = vi.run_full_verification(
            output_dir=tmp_path,
            files_to_verify=files,
        )

        assert summary["files_checked"] == 2
        assert summary["pinned_ok"] == 2
        assert summary["verified_ok"] == 2
        assert summary["missing_or_error"] == 0
        assert summary["all_verified"] is True
        assert summary["LLM_FORBIDDEN"] is True

    def test_missing_files_reported(self, vi, tmp_path):
        """Отсутствующие файлы → missing_or_error > 0, не исключение."""
        summary = vi.run_full_verification(
            output_dir=tmp_path,
            files_to_verify=[
                "data/bee/nonexistent_a.json",
                "data/bee/nonexistent_b.json",
            ],
        )

        assert summary["missing_or_error"] == 2
        assert summary["pinned_ok"] == 0
        assert summary["all_verified"] is False

    def test_verify_summary_written(self, vi, tmp_path, monkeypatch):
        """run_full_verification пишет verify_summary.json в data/bee/."""
        import spa_core.bee.verify_integration as vi_mod
        # Перенаправляем путь verify_summary в tmp
        verify_summary_path = tmp_path / "data" / "bee" / "verify_summary.json"
        monkeypatch.setattr(
            vi_mod,
            "_PROJECT_ROOT",
            tmp_path,
        )
        # Пересоздаём _CHAIN_FILE тоже
        monkeypatch.setattr(vi_mod, "_CHAIN_FILE", tmp_path / "data" / "bee" / "hash_chain.json")

        (tmp_path / "data" / "bee").mkdir(parents=True, exist_ok=True)

        vi_mod.run_full_verification(
            output_dir=tmp_path,
            files_to_verify=[],
        )

        assert verify_summary_path.exists(), "verify_summary.json not created"
        summary = json.loads(verify_summary_path.read_text())
        assert "verify_integration_version" in summary
        assert "run_at" in summary

    def test_chain_head_in_summary(self, vi, tmp_path):
        """Сводка содержит chain_head."""
        summary = vi.run_full_verification(
            output_dir=tmp_path,
            files_to_verify=[],
        )
        assert "chain_head" in summary


# ---------------------------------------------------------------------------
# TestIndependentVerifier — verifier/bee_verify.py
# ---------------------------------------------------------------------------

class TestIndependentVerifier:
    """Тесты standalone verifier (bee_verify.py) S9.6."""

    def test_verify_one_no_pin_returns_no_pin(self, bv, tmp_path):
        """verify_one без PIN → ok=False, status='no_pin'."""
        result = bv.verify_one("definitely_nonexistent_name_xyz")

        assert result["ok"] is False
        assert result["status"] == "no_pin"

    def test_verify_all_empty_dir_returns_list(self, bv, tmp_path):
        """verify_all с пустой директорией → пустой список."""
        results = bv.verify_all()
        assert isinstance(results, list)
        assert len(results) == 0

    def test_verify_all_with_hashes_returns_list(self, bv, tmp_path):
        """verify_all при наличии hash-файлов → список дикт."""
        # Создаём фиктивные hash-файлы
        hashes_dir = tmp_path / "hashes"
        hashes_dir.mkdir()
        (hashes_dir / "test_output.json").write_text(
            json.dumps({
                "name": "test_output",
                "file": str(tmp_path / "data" / "bee" / "test_output.json"),
                "sha256": "deadbeef" * 8,
                "pinned_at": "2026-06-22T00:00:00Z",
            })
        )

        results = bv.verify_all()
        assert isinstance(results, list)
        assert len(results) == 1

    def test_verify_chain_no_chain_returns_no_chain(self, bv, tmp_path):
        """verify_chain без hash_chain.json → ok=False, status='no_chain'."""
        result = bv.verify_chain()

        assert result["ok"] is False
        assert result["status"] == "no_chain"

    def test_verify_chain_intact(self, bv, tmp_path, project_root):
        """verify_chain после build_hash_chain → chain_intact."""
        import spa_core.bee.verify_integration as vi_mod

        # Строим chain через verify_integration
        vi_mod._CHAIN_FILE.__class__  # type check
        import importlib
        vi_mod2 = importlib.import_module("spa_core.bee.verify_integration")

        # Патчим _CHAIN_FILE в обоих модулях на tmp_path
        chain_path = tmp_path / "hash_chain.json"
        import spa_core.bee.verify_integration as vi2
        original_chain = vi2._CHAIN_FILE
        vi2._CHAIN_FILE = chain_path

        try:
            results = [{"ok": True, "name": "item1", "sha256": "a" * 64}]
            vi2.build_hash_chain(results)
        finally:
            vi2._CHAIN_FILE = original_chain

        # Верифицируем через bee_verify (уже патчен в bv fixture на tmp_path)
        result = bv.verify_chain()
        assert result["ok"] is True
        assert result["status"] == "chain_intact"

    def test_verify_one_round_trip_via_bv(self, bv, tmp_path):
        """verify_one после ручного создания корректного hash-файла → match."""
        import hashlib

        content = json.dumps({"protocol": "aave", "apy": 3.1}, sort_keys=True,
                             separators=(",", ":"), ensure_ascii=True)
        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Создаём pinned копию
        pinned_dir = tmp_path / "pinned"
        pinned_dir.mkdir()
        (pinned_dir / "aave_data.json").write_text(content)

        # Создаём hash файл
        hashes_dir = tmp_path / "hashes"
        hashes_dir.mkdir()
        (hashes_dir / "aave_data.json").write_text(json.dumps({
            "name": "aave_data",
            "file": str(tmp_path / "original" / "aave_data.json"),
            "sha256": file_hash,
            "pinned_at": "2026-06-22T00:00:00Z",
        }))

        result = bv.verify_one("aave_data")

        assert result["ok"] is True
        assert result["status"] == "match"


# ---------------------------------------------------------------------------
# TestLLMForbidden — структурные проверки
# ---------------------------------------------------------------------------

class TestLLMForbidden:
    """LLM_FORBIDDEN: никаких AI-зависимостей в BEE коде."""

    def test_verify_integration_has_llm_forbidden_marker(self, project_root):
        """verify_integration.py содержит маркер LLM_FORBIDDEN."""
        content = (
            project_root / "spa_core" / "bee" / "verify_integration.py"
        ).read_text()
        assert "LLM_FORBIDDEN" in content

    def test_bee_verify_has_llm_forbidden_marker(self, project_root):
        """verifier/bee_verify.py содержит маркер LLM_FORBIDDEN."""
        content = (project_root / "verifier" / "bee_verify.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_no_ai_libs_in_verify_integration(self, project_root):
        """verify_integration.py не импортирует AI-библиотеки."""
        content = (
            project_root / "spa_core" / "bee" / "verify_integration.py"
        ).read_text().lower()
        for term in ["openai", "anthropic", "gpt", "langchain", "llama"]:
            assert term not in content, (
                f"AI term '{term}' found in verify_integration.py"
            )

    def test_no_ai_libs_in_bee_verify(self, project_root):
        """verifier/bee_verify.py не импортирует AI-библиотеки."""
        content = (
            project_root / "verifier" / "bee_verify.py"
        ).read_text().lower()
        for term in ["openai", "anthropic", "gpt", "langchain", "llama"]:
            assert term not in content, (
                f"AI term '{term}' found in bee_verify.py"
            )

    def test_verify_integration_stdlib_only(self, project_root):
        """verify_integration.py использует только stdlib импорты."""
        content = (
            project_root / "spa_core" / "bee" / "verify_integration.py"
        ).read_text()
        forbidden_imports = [
            "import requests",
            "import numpy",
            "import pandas",
            "import scipy",
            "from requests",
        ]
        for fi in forbidden_imports:
            assert fi not in content, (
                f"Non-stdlib import '{fi}' found in verify_integration.py"
            )

    def test_atomic_writes_in_verify_integration(self, project_root):
        """verify_integration.py использует атомарные записи (os.replace)."""
        content = (
            project_root / "spa_core" / "bee" / "verify_integration.py"
        ).read_text()
        assert "os.replace" in content, (
            "Atomic writes (os.replace) not found in verify_integration.py"
        )

    def test_verify_integration_version_constant(self, project_root):
        """VERIFY_INTEGRATION_VERSION константа определена."""
        import spa_core.bee.verify_integration as vi
        assert hasattr(vi, "VERIFY_INTEGRATION_VERSION")
        assert "verify_integration" in vi.VERIFY_INTEGRATION_VERSION
