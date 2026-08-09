"""Сторож ЧЕТВЁРТОГО вопроса: исполняет ли живой процесс код из дерева?

Каждый тест здесь — авария, которая уже случилась, а не гипотеза:

* **08.08** — кнопки под алертами лежат в дереве с 07.08, бот работает с 05.08,
  владелец видит старый Телеграм. Три сторожа молчат, каждый честно отвечая на
  свой вопрос (`test_delivered_but_not_executing_is_named`).
* **09.08, первый же прогон на живом проде** — `com.spa.apiserver` работает
  22.5 суток на коде, которого в дереве давно нет, а его цель спрятана за
  `python -m uvicorn spa_core.api.server:app`: не разбери командную строку —
  и публичный live-API остался бы «чужим процессом»
  (`test_uvicorn_target_is_our_module_not_foreign`).
* **09.08, тот же прогон** — `com.spa.rtmr_sense` стартовал ПОЗЖЕ своей точки
  входа, но раньше модулей, которые она импортирует
  (`test_transitive_import_makes_it_stale`). Проверка «только точка входа»
  назвала бы его свежим.
* Зелёная сторона той же аварии — перезапущенный бот обязан молчать
  (`test_restarted_process_is_green`), иначе сторож станет вечно-жёлтым.

**Дат в фикстурах нет намеренно** (`.claude/rules/deployment.md`, «время в
тестах»): воспроизводится ФОРМА аварии — процесс старше своего кода на N суток, —
а не календарь августа. Обе стороны сравнения инъектируются, поэтому тесты
бессмертны.
"""
from __future__ import annotations

import os
import plistlib
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from spa_core.monitoring import agent_code_freshness as acf


# ── Стенд ───────────────────────────────────────────────────────────────────
def _lstart(dt: datetime) -> str:
    """Строка ``ps -o lstart=`` — ЛОКАЛЬНОЕ время, как её отдаёт настоящий ps."""
    return dt.strftime("%a %b %d %H:%M:%S %Y")


def _touch(path: Path, dt: datetime) -> None:
    epoch = time.mktime(dt.timetuple())
    os.utime(path, (epoch, epoch))


def _write_plist(agent_dir: Path, label: str, keep_alive) -> Path:
    doc = {"Label": label, "ProgramArguments": ["/bin/bash", "/x.sh"]}
    if keep_alive is not None:
        doc["KeepAlive"] = keep_alive
    p = agent_dir / "{}.plist".format(label)
    with open(p, "wb") as fh:
        plistlib.dump(doc, fh)
    return p


def _make_runner(*, launchctl: str = "", ps_table: str = "", lstarts=None):
    lstarts = lstarts or {}

    def run(argv):
        argv = list(argv)
        if argv[:2] == ["launchctl", "list"]:
            return launchctl
        if argv and argv[0] == "ps":
            if "-eo" in argv:
                return ps_table
            if "-p" in argv:
                return lstarts.get(int(argv[argv.index("-p") + 1]), "")
        return ""

    return run


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Крошечное дерево: точка входа + модуль, который она импортирует."""
    root = tmp_path / "repo"
    pkg = root / "spa_core" / "telegram"
    pkg.mkdir(parents=True)
    (root / "spa_core" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "bot.py").write_text(
        "from spa_core.telegram import humanize\nimport json\n")
    (pkg / "humanize.py").write_text("X = 1\n")
    return root


@pytest.fixture
def agent_dir(tmp_path: Path) -> Path:
    d = tmp_path / "LaunchAgents"
    d.mkdir()
    return d


def _bot_stand(repo: Path, agent_dir: Path, *, started: datetime,
               code_at: datetime, entry_at=None, label="com.spa.telegram_bot"):
    """Долгожитель `label`, запущенный `started`, с кодом возраста `code_at`."""
    _write_plist(agent_dir, label, True)
    pkg = repo / "spa_core" / "telegram"
    # `entry_at` состаривает ВСЮ обвязку точки входа (`bot.py` + `__init__`),
    # чтобы новейшим остался ровно тот файл, о котором тест: иначе «виноватым»
    # может оказаться `__init__.py`, и утверждение перестанет что-либо значить.
    _touch(pkg / "bot.py", entry_at or code_at)
    _touch(pkg / "__init__.py", entry_at or code_at)
    _touch(repo / "spa_core" / "__init__.py", entry_at or code_at)
    _touch(pkg / "humanize.py", code_at)
    runner = _make_runner(
        launchctl="9001\t0\t{}\n".format(label),
        ps_table=("9001 1 /bin/bash /x/scripts/agent_template.sh telegram_bot "
                  "spa_core.telegram.bot\n"
                  "9002 9001 /usr/bin/python3 -m spa_core.telegram.bot\n"),
        lstarts={9001: _lstart(started - timedelta(seconds=3)),
                 9002: _lstart(started)})
    return runner


def _only(doc: dict, label="com.spa.telegram_bot") -> dict:
    return next(a for a in doc["agents"] if a["label"] == label)


# ── 1. Сама авария 08.08 ────────────────────────────────────────────────────
def test_delivered_but_not_executing_is_named(repo, agent_dir):
    """Процесс старше своего кода на двое суток ⇒ сторож ГОВОРИT об этом.

    Положительный контроль аварии 2026-08-08: код доставлен, процесс его не
    исполняет, три существующих сторожа молчат. Проверяется не только флаг, но и
    СЛОВА — вердикт обязан назвать обе даты, иначе он неотличим от «что-то не так».
    """
    now = datetime.now()
    runner = _bot_stand(repo, agent_dir,
                        started=now - timedelta(days=4),
                        code_at=now - timedelta(days=2))

    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner)

    v = _only(doc)
    assert v["state"] == acf.STATE_STALE
    assert v["severity"] == acf.WARNING
    assert doc["status"] == acf.WARNING
    assert doc["stale_count"] == 1
    assert doc["issues"], "авария обязана порождать issue, а не только поле"
    assert v["gap_hours"] == pytest.approx(48.0, abs=1.5)
    # Слова: обе стороны сравнения названы человеческим языком.
    assert "работает с кодом" in v["detail"] and "а в дереве код" in v["detail"]
    assert "KeepAlive" in doc["issues"][0]


def test_restarted_process_is_green(repo, agent_dir):
    """Зелёная сторона той же аварии: перезапущенный бот молчит.

    Без этого теста сторож имел бы право краснеть ВСЕГДА — и был бы бесполезен
    ровно так же, как молчащий.
    """
    now = datetime.now()
    runner = _bot_stand(repo, agent_dir,
                        started=now - timedelta(hours=1),
                        code_at=now - timedelta(days=2))

    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner)

    v = _only(doc)
    assert v["state"] == acf.STATE_FRESH
    assert doc["status"] == acf.OK
    assert doc["issues"] == []
    assert v["files_checked"] >= 3, "замыкание импортов обязано что-то просмотреть"


# ── 2. Замыкание импортов, а не одна точка входа ────────────────────────────
def test_transitive_import_makes_it_stale(repo, agent_dir):
    """`rtmr_sense` 09.08: точка входа СТАРШЕ процесса, импортируемый модуль — новее.

    Проверка «сравнить процесс только с его точкой входа» назвала бы такой агент
    свежим. Он не свежий: в памяти у него старая версия импортированного модуля.
    """
    now = datetime.now()
    runner = _bot_stand(repo, agent_dir,
                        started=now - timedelta(days=2),
                        entry_at=now - timedelta(days=5),   # точка входа старая
                        code_at=now - timedelta(hours=3))   # импорт — свежий

    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner)

    v = _only(doc)
    assert v["state"] == acf.STATE_STALE
    assert v["severity"] == acf.WARNING
    assert v["newest_file"].endswith("humanize.py"), (
        "виноватый файл обязан быть назван поимённо — иначе вердикт непроверяем")


def test_relative_import_is_followed(repo, agent_dir):
    """`from . import x` — тот же импорт; не разберём — пропустим настоящий разрыв."""
    now = datetime.now()
    pkg = repo / "spa_core" / "telegram"
    (pkg / "bot.py").write_text("from . import sibling\n")
    (pkg / "sibling.py").write_text("Y = 2\n")

    _write_plist(agent_dir, "com.spa.telegram_bot", True)
    for f in (pkg / "bot.py", pkg / "__init__.py", repo / "spa_core" / "__init__.py"):
        _touch(f, now - timedelta(days=5))
    _touch(pkg / "sibling.py", now - timedelta(hours=2))
    runner = _make_runner(
        launchctl="9002\t0\tcom.spa.telegram_bot\n",
        ps_table="9002 1 /usr/bin/python3 -m spa_core.telegram.bot\n",
        lstarts={9002: _lstart(now - timedelta(days=3))})

    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner)

    assert _only(doc)["newest_file"].endswith("sibling.py")


# ── 3. Разбор командной строки живого процесса ──────────────────────────────
def test_uvicorn_target_is_our_module_not_foreign(repo):
    """`python -m uvicorn spa_core.api.server:app` — НАШ модуль, а не «чужой процесс».

    Замер 09.08: именно так запущен `com.spa.apiserver`, 22.5 суток на старом
    коде. Наивный разбор увидел бы `-m uvicorn` и списал бы публичный live-API
    в «не наше».
    """
    kind, value = acf.resolve_target(
        "/usr/bin/python3 -m uvicorn spa_core.api.server:app --host 127.0.0.1", repo)
    assert (kind, value) == ("module", "spa_core.api.server")


def test_foreign_process_is_measured_not_unchecked(repo, agent_dir):
    """`http.server` / cloudflared — ИЗМЕРЕНИЕ «не наш код», а не вечное «не измерено».

    Вечное `unchecked` по агенту, который никогда не станет нашим, — тот самый
    необратимый замок, что забивает очередь (память проекта). Здесь это ответ.
    """
    _write_plist(agent_dir, "com.spa.dashboard", True)
    runner = _make_runner(
        launchctl="7001\t0\tcom.spa.dashboard\n",
        ps_table="7001 1 /usr/bin/python3 -m http.server 8767\n",
        lstarts={7001: _lstart(datetime.now() - timedelta(days=30))})

    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner)

    v = _only(doc, "com.spa.dashboard")
    assert v["state"] == acf.STATE_FOREIGN
    assert v["severity"] == acf.OK
    assert doc["issues"] == []


def test_python_child_is_measured_not_the_bash_wrapper(repo, agent_dir):
    """Меряется python-потомок, а не bash-обёртка, которую видит launchd.

    Обёртка `agent_template.sh` до запуска python ждёт готовности дерева и
    синкает код (до ~16 с). Спутать их — приписать процессу лишний разрыв.
    """
    now = datetime.now()
    _write_plist(agent_dir, "com.spa.telegram_bot", True)
    pkg = repo / "spa_core" / "telegram"
    for f in (pkg / "bot.py", pkg / "humanize.py", pkg / "__init__.py",
              repo / "spa_core" / "__init__.py"):
        _touch(f, now - timedelta(days=3))
    runner = _make_runner(
        launchctl="9001\t0\tcom.spa.telegram_bot\n",
        ps_table=("9001 1 /bin/bash /x/scripts/agent_template.sh telegram_bot "
                  "spa_core.telegram.bot\n"
                  "9002 9001 /usr/bin/python3 -m spa_core.telegram.bot\n"),
        # Обёртка стартовала ДО правки кода, python — ПОСЛЕ.
        lstarts={9001: _lstart(now - timedelta(days=4)),
                 9002: _lstart(now - timedelta(days=2))})

    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner)

    v = _only(doc)
    assert v["pid"] == 9002, "вердикт обязан относиться к процессу, держащему код"
    assert v["state"] == acf.STATE_FRESH


# ── 4. Кто вообще попадает под вопрос ───────────────────────────────────────
def test_short_lived_agent_is_not_judged(repo, agent_dir):
    """Агент по расписанию перезапускается и подхватывает код сам — не наш случай."""
    _write_plist(agent_dir, "com.spa.digest_daily", False)
    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=_make_runner())
    assert doc["long_lived_total"] == 0
    assert doc["state"] == acf.STATE_NO_LONG_LIVED
    assert doc["status"] == acf.OK


def test_keepalive_dict_form_is_long_lived(repo, agent_dir):
    """`KeepAlive = {SuccessfulExit: false}` — тоже долгожитель.

    Проверяется ИСТИННОСТЬ значения, а не его тип: словарная форма законна в
    launchd, и агент с ней живёт ровно так же вечно.
    """
    _write_plist(agent_dir, "com.spa.apiserver", {"SuccessfulExit": False})
    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=_make_runner())
    assert doc["long_lived_total"] == 1


# ── 5. Fail-CLOSED: «не измерено» никогда не «в порядке» ────────────────────
def test_unreadable_plist_is_unchecked_not_skipped(repo, agent_dir):
    (agent_dir / "com.spa.broken.plist").write_bytes(b"not a plist at all")
    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=_make_runner())
    v = _only(doc, "com.spa.broken")
    assert v["state"] == acf.STATE_UNCHECKED
    assert doc["status"] == acf.WARNING
    assert doc["issues"]


def test_nothing_measured_is_not_reported_as_fresh(repo, agent_dir):
    """Итог всей проверки не имеет права быть `fresh`, когда мерить не удалось.

    Цикл #181. Ни один долгожитель не измерен (plist'ы нечитаемы), несвежих
    найдено ноль — и прежний код печатал `state: fresh` рядом со `stale_count: 0`.
    Вместе они читаются как «всех проверили, несвежих нет», хотя проверено НОЛЬ:
    та же подмена «не измерено» → «в порядке», от которой написан модуль.
    """
    (agent_dir / "com.spa.broken.plist").write_bytes(b"not a plist at all")
    (agent_dir / "com.spa.alsobroken.plist").write_bytes(b"still not a plist")
    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=_make_runner())

    assert doc["stale_count"] == 0            # несвежих действительно не нашли
    assert doc["unchecked_count"] == 2        # …потому что не смотрели вовсе
    assert doc["state"] == acf.STATE_UNCHECKED
    assert doc["state"] != acf.STATE_FRESH
    assert any("НЕ ИЗМЕРЕНО" in r for r in doc["reasons"])


def test_all_measured_and_clean_still_says_fresh(repo, agent_dir):
    """Обратная сторона: измерили всё и несвежих нет ⇒ по-прежнему `fresh`.

    Без этого плеча предыдущий тест закрывался бы вечным `unchecked`, и слово
    `fresh` перестало бы что-либо значить.
    """
    now = datetime.now()
    runner = _bot_stand(repo, agent_dir,
                        started=now - timedelta(hours=1),
                        code_at=now - timedelta(days=2))
    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner)

    assert doc["unchecked_count"] == 0
    assert doc["stale_count"] == 0
    assert doc["state"] == acf.STATE_FRESH


def test_unmeasurable_start_time_is_unchecked_not_fresh(repo, agent_dir):
    """ps молчит ⇒ `unchecked`. Молчание системы не равно «код свежий».

    Утверждение о ПРИЧИНЕ здесь не украшение (цикл #181). Снятая проверка
    `started is None` оставляет этот тест зелёным: `None` уезжает в арифметику,
    ловится общим `except` уровнем выше и даёт тот же `unchecked` — вердикт
    совпал, ИЗМЕРЕНИЕ пропало. Разницу видно только по словам, поэтому они и
    проверяются: сторож обязан назвать невзятое время старта, а не имя
    исключения.
    """
    _write_plist(agent_dir, "com.spa.telegram_bot", True)
    runner = _make_runner(
        launchctl="9002\t0\tcom.spa.telegram_bot\n",
        ps_table="9002 1 /usr/bin/python3 -m spa_core.telegram.bot\n",
        lstarts={})                                   # lstart недоступен
    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner)
    v = _only(doc)
    assert v["state"] == acf.STATE_UNCHECKED
    assert v["state"] != acf.STATE_FRESH
    assert doc["status"] == acf.WARNING
    assert "время старта" in v["detail"], v["detail"]
    assert "проверка упала" not in v["detail"], v["detail"]


def test_not_running_is_named_but_not_double_alarmed(repo, agent_dir):
    """Не запущен — забота `agent_health`; состояние названо, голос не повышен."""
    _write_plist(agent_dir, "com.spa.telegram_bot", True)
    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=_make_runner(launchctl=""))
    v = _only(doc)
    assert v["state"] == acf.STATE_NOT_RUNNING
    assert doc["status"] == acf.OK
    assert doc["issues"] == []


def test_missing_launchd_dir_and_empty_launchd_dir_differ(repo, tmp_path):
    """«Флота здесь нет» и «искали и не нашли ничего» — РАЗНЫЕ ответы.

    Слить их в один — либо покрасить каждый прогон на машине без launchd, либо
    (хуже) молча выдать чистый счёт там, где проверка ничего не проверила.
    """
    absent = acf.check_agent_code_freshness(
        agent_dir=tmp_path / "нет-такого", repo_root=repo, runner=_make_runner())
    assert absent["state"] == acf.STATE_NO_FLEET
    assert absent["status"] == acf.OK

    empty_dir = tmp_path / "LaunchAgents"
    empty_dir.mkdir()
    empty = acf.check_agent_code_freshness(
        agent_dir=empty_dir, repo_root=repo, runner=_make_runner())
    assert empty["state"] == acf.STATE_UNCHECKED
    assert empty["status"] == acf.WARNING


# ── 6. Порог: видно всегда, кричит после суток ──────────────────────────────
def test_gap_under_a_day_is_visible_but_quiet(repo, agent_dir):
    """Разрыв < 24 ч остаётся В ОТЧЁТЕ, но не кричит.

    Пуши идут ежедневно; кричи сторож на любой ненулевой разрыв — он был бы
    вечно-жёлтым, а вечное предупреждение перестают читать. Скрыть разрыв
    нельзя — поэтому `state=stale` есть, а `issue` нет.
    """
    now = datetime.now()
    runner = _bot_stand(repo, agent_dir,
                        started=now - timedelta(hours=10),
                        code_at=now - timedelta(hours=2))
    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner)
    v = _only(doc)
    assert v["state"] == acf.STATE_STALE          # видно
    assert v["severity"] == acf.OK                # но не кричит
    assert doc["issues"] == []
    assert doc["stale_count"] == 1


def test_alert_threshold_is_a_knob_not_a_wall(repo, agent_dir):
    """Тот же разрыв с порогом 1 ч обязан кричать — иначе тишина выше объяснена неверно."""
    now = datetime.now()
    runner = _bot_stand(repo, agent_dir,
                        started=now - timedelta(hours=10),
                        code_at=now - timedelta(hours=2))
    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner, alert_hours=1.0)
    assert _only(doc)["severity"] == acf.WARNING
    assert doc["issues"]


def test_closure_truncation_is_reported_not_silent(repo, agent_dir):
    """Упёрлись в потолок обхода ⇒ сказано вслух: часть дерева НЕ просмотрена."""
    now = datetime.now()
    runner = _bot_stand(repo, agent_dir,
                        started=now - timedelta(hours=1),
                        code_at=now - timedelta(days=2))
    doc = acf.check_agent_code_freshness(
        agent_dir=agent_dir, repo_root=repo, runner=runner, max_files=1)
    assert any("потолок" in n for n in _only(doc)["notes"])


# ── 7. ПРОВОДКА, а не только деталь ─────────────────────────────────────────
def test_wired_into_agent_health_for_the_host(tmp_path, monkeypatch):
    """Вердикт обязан ДОЕХАТЬ до `agent_health`, а не остаться в модуле.

    Урок цикла #144: функция без вызова оставляет все тесты зелёными и фичу
    мёртвой в проде. Здесь проверяется именно проводка.
    """
    from spa_core.monitoring import agent_health_monitor as ahm

    called = {"n": 0}

    def fake():
        called["n"] += 1
        return {"status": "WARNING", "stale_count": 2,
                "issues": ["доставлено, но НЕ исполняется: бот работает с кодом от вчера"]}

    checks, status, issues = ahm.check_system(
        tmp_path, datetime.now(), autopush_log="/nonexistent/x.log",
        code_freshness=fake)

    assert called["n"] == 1
    assert checks["stale_code_agents"] == 2
    assert status == ahm.WARNING
    assert any("НЕ исполняется" in i for i in issues)


def test_host_branch_calls_the_real_check_without_injection(tmp_path, monkeypatch):
    """Та самая проводка, которой предыдущий тест НЕ касается (цикл #181).

    Тест выше передаёт `code_freshness=` руками и потому зелен даже без условия
    `or _asked_about_host` — а в проде `agent_health` вызывается БЕЗ аргумента,
    и без этого условия сторож не запускался бы НИКОГДА. Ровно урок #144:
    проверять проводку, а не деталь. Здесь ветка берётся так, как её берёт прод:
    спросили про свой `data/` — и настоящая функция обязана быть позвана.
    """
    from spa_core.monitoring import agent_health_monitor as ahm
    from spa_core.monitoring import agent_code_freshness as real_acf

    called = {"n": 0}

    def fake(**_kw):
        called["n"] += 1
        return {"status": "WARNING", "stale_count": 3,
                "issues": ["доставлено, но НЕ исполняется: apiserver работает с кодом от 17 июля"]}

    # `data_dir` хоста подменён на песочницу, чтобы взять ветку, не читая прод.
    monkeypatch.setattr(ahm, "_DEFAULT_DATA_DIR", tmp_path)
    monkeypatch.setattr(real_acf, "check_agent_code_freshness", fake)

    checks, status, issues = ahm.check_system(
        tmp_path, datetime.now(), autopush_log="/nonexistent/x.log")

    assert called["n"] == 1, "спросили про хостовый data/ — настоящая проверка не позвана"
    assert checks["stale_code_agents"] == 3
    assert status == ahm.WARNING
    assert any("НЕ исполняется" in i for i in issues)


def test_not_measured_for_a_foreign_data_dir(tmp_path):
    """Спросили про песочницу — про ХОСТ не отвечаем, и это `None`, а не ноль.

    Ноль читался бы как «несвежих нет». Зеркало цикла #173: не судить дерево,
    о котором не спрашивали.
    """
    from spa_core.monitoring import agent_health_monitor as ahm

    checks, _status, _issues = ahm.check_system(
        tmp_path, datetime.now(), autopush_log="/nonexistent/x.log")

    assert checks["stale_code_agents"] is None


def test_broken_freshness_check_fails_closed_in_agent_health(tmp_path):
    """Проверка упала ⇒ WARNING и слова, а не тихий пропуск."""
    from spa_core.monitoring import agent_health_monitor as ahm

    def boom():
        raise RuntimeError("ps недоступен")

    _checks, status, issues = ahm.check_system(
        tmp_path, datetime.now(), autopush_log="/nonexistent/x.log",
        code_freshness=boom)

    assert status == ahm.WARNING
    assert any("UNCHECKED" in i for i in issues)
