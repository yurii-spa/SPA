"""Публичные по построению строки — не учётные данные (ADR-281).

Замер 2026-09-09, утренний отчёт владельцу. Первая строка сообщения была
«🔴 Система: КРИТИЧНО — сбой: целостность кода». Единственный CRITICAL во всём отчёте:
`d5.security.secrets` → «1 untracked file(s) hold a credential-shaped value», и файл —
КАРТОЧКА ВЛАДЕЛЬЦА `owner-decision-chetyre-tysyachi-dollarov-edut-v-token-f.md`.
Её единственное совпадение — публичный адрес контракта `0x…` (42 символа).

Ветка «длинная непрозрачная строка» ловит любой прогон из 32+ символов, а проект сам
пишет такие строки в карточки, ADR и журналы: адреса контрактов, `entry_hash`/`commitment_hash`
своих цепочек, `pool_id` из DeFiLlama. Будучи ЕДИНСТВЕННЫМ CRITICAL, находка красила весь
отчёт и заслоняла остальное — тот самый эффект, о котором предупреждает докстринг проверки.

Контроли идут в ОБЕ стороны: ни один настоящий ключ не перестаёт краснеть.

# FROZEN-DATE-OK: historical-incident — дата и содержимое конкретной карточки и есть
# предмет теста; живых часов в файле нет.
"""
from __future__ import annotations

import pytest

from spa_core.monitoring.system_health_monitor import SystemHealthMonitor


@pytest.fixture()
def mon(tmp_path):
    m = SystemHealthMonitor()
    m.project_root = str(tmp_path)
    return m


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return name


# ── публичные формы: НЕ учётные данные ────────────────────────────────────────────────
@pytest.mark.parametrize("label,body", [
    ("адрес контракта EVM (карточка владельца 09.09)",
     "четыре тысячи долларов едут в токен (`0xdC035D45d973E3EC169d2276DDab16f1e407384F`), поэтому"),
    ("хеш транзакции",
     "tx 0x" + "a1b2c3d4" * 8 + " подтверждён"),
    ("sha256 нашей же цепочки",
     'entry_hash: "57b9caeb23c476cc86bcaa63780cd08e3d4318f54df8418252f7feaaff7d5b42"'),
    ("pool_id из DeFiLlama",
     "pool_id 4438dabc-7f0c-430b-8136-2722711ae663 — тот же контракт под двумя именами"),
])
def test_public_by_construction_values_are_not_credentials(mon, tmp_path, label, body):
    name = _write(tmp_path, "owner-decision-token-card.md", body)
    assert mon._file_holds_secret_value(name) is False, label


def test_a_card_full_of_public_hashes_stays_clean(mon, tmp_path):
    """Реальная форма наших документов: несколько публичных строк подряд."""
    body = "\n".join([
        "commitment_hash: " + "0123456789abcdef" * 4,
        "адрес: 0x" + "9" * 40,
        "pool_id aa70268e-4b52-42bf-a116-608b370f9501",
    ])
    name = _write(tmp_path, "adr-token-notes.md", body)
    assert mon._file_holds_secret_value(name) is False


# ── контроли обратного направления: настоящий ключ обязан краснеть ────────────────────
@pytest.mark.parametrize("label,body", [
    ("GitHub PAT", "ghp_" + "A" * 36),
    ("присваивание token: <значение>", 'token: "s3cr3t-value-quite-long-here"'),
    ("api_key = <значение>", "api_key = 'abcdefghijklmnop1234'"),
    ("PEM-ключ", "-----BEGIN RSA PRIVATE KEY-----\nMIIEow==\n-----END RSA PRIVATE KEY-----"),
    ("непрозрачная строка base64 (не адрес, не хеш, не UUID)",
     "value: Zm9vYmFyYmF6cXV1eA_-Zm9vYmFyYmF6cXV1eA1234"),
])
def test_a_real_credential_still_trips(mon, tmp_path, label, body):
    name = _write(tmp_path, "leaked-secret.md", body)
    assert mon._file_holds_secret_value(name) is True, label


def test_a_credential_next_to_a_public_hash_still_trips(mon, tmp_path):
    """Вырезание публичных форм не смеет прятать ключ, лежащий рядом с ними."""
    body = ("адрес 0x" + "b" * 40 + "\n"
            "pool_id aa70268e-4b52-42bf-a116-608b370f9501\n"
            "GITHUB_PAT=ghp_" + "Z" * 36 + "\n")
    name = _write(tmp_path, "notes-with-token.md", body)
    assert mon._file_holds_secret_value(name) is True


def test_an_unreadable_file_is_still_unknown_not_clean(mon, tmp_path):
    """Третий исход сохранён: не прочитали ⇒ None, а не «чисто»."""
    assert mon._file_holds_secret_value("does-not-exist-secret.md") is None


def test_cutting_happens_before_the_search_not_after(mon, tmp_path):
    """Проводка: публичная форма должна исчезать ДО поиска.

    Если бы вырезание шло после, адрес сам дал бы совпадение и вердикт не изменился —
    именно так и вёл себя код до правки."""
    src = SystemHealthMonitor._PUBLIC_BY_CONSTRUCTION_RE
    import inspect
    body = inspect.getsource(SystemHealthMonitor._file_holds_secret_value)
    i_cut = body.find("_PUBLIC_BY_CONSTRUCTION_RE")
    i_search = body.find("_SECRET_VALUE_RE")
    assert -1 < i_cut < i_search, "вырезание публичных форм стоит ПОСЛЕ поиска — правка бессильна"
    assert src.search("0x" + "c" * 40)
