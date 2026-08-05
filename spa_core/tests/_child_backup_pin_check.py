"""Child-process check: the backup-dir pin survives a test that breaks it.

NOT collected by the normal suite (no ``test_`` filename prefix). It is run in a
subprocess, in declaration order, by
``test_backup_root_hermetic_and_responsive.py::test_pin_is_reinstalled_after_a_test_unsets_it``.

Why a child process: the property under test is *what the next test sees*, which
cannot be asserted from inside the test that breaks the environment, and must
not depend on collection order in the real suite (pytest-randomly shuffles it).
Here the order is fixed and the two tests are the only ones in the file.

``tests/test_backup.py::test_A2`` really does ``del os.environ["SPA_BACKUP_DIR"]``
in a ``finally``, so this is a live pattern, not a hypothetical one. Without the
autouse fixture re-installing the pin per test, every test collected after it
would resolve ``default_backup_dir()`` to the production iCloud root again.
"""
import os

from spa_core.persistence.backup import default_backup_dir


def test_1_a_test_deletes_the_pin_like_test_a2_does():
    """First: behave like the real test that unsets the variable."""
    os.environ.pop("SPA_BACKUP_DIR", None)
    assert "SPA_BACKUP_DIR" not in os.environ


def test_2_the_next_test_still_gets_a_sandbox():
    """Second: the pin must be back — nobody resolves the production root."""
    import sys

    guard = sys.modules["spa_backup_dir_guard"]
    assert os.environ.get("SPA_BACKUP_DIR") == str(guard.sandbox_root())
    assert default_backup_dir() == guard.sandbox_root()
