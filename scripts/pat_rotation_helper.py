#!/usr/bin/env python3
"""
PAT Rotation Helper — SPA Project
Напоминает о ротации PAT и генерирует пошаговый checklist.
PAT НИКОГДА не читается и не хранится в коде — только Keychain.

**Почему модуль переписан (карточка `inbox-strazh-rotatsii-pat-sam-sochinyaet-datu`,
замер цикла #379, починка #383).** `_load_state()` при ОТСУТСТВУЮЩЕМ файле состояния
создавал его с `last_rotation = сегодня`. То есть первый же `--status` или `--check`
СОЧИНЯЛ факт, о котором отчитывался: «ротация была сегодня, до следующей 90 дней», и
`--check` возвращал 0 ровно потому, что его спросили впервые. Замер вживую 25.08: в
прод-дереве `data/pat_rotation_state.json` не существовало, один вызов `--status` создал
его с датой, в которую никакой ротации не было.

Это класс «fail-OPEN monitor»: страж, который не может покраснеть, потому что молчание
он сам превращает в благополучие. Инвариант проекта — refusal-first: нет наблюдения ⇒
ОТКАЗ, а не выдуманное значение.

**Что теперь:**

- `_load_state()` НИЧЕГО не пишет. Нет файла (или он нечитаем) ⇒ `None`, и это состояние
  называется своим именем: «дата последней ротации НЕ ИЗВЕСТНА».
- Дату ротации выставляет ТОЛЬКО `--mark-rotated` — человек, который её реально сделал.
- Время — ВХОД (`now=`), а не `date.today()` внутри (`.claude/rules/deployment.md`,
  раздел про фиксированные даты): обе стороны сравнения закрепляются тестом.
- В состоянии «не известно» словарь статуса НЕ СОДЕРЖИТ ключей-суждений
  (`days_until_rotation`, `is_overdue`, `needs_rotation_soon`, `last_rotation`,
  `next_rotation`) — намеренно. Ключ, который присутствует и ложен, — ровно то, чем этот
  дефект и держался: наивный `if status["needs_rotation_soon"]` прочитал бы `None` как
  «всё хорошо». `KeyError` громкий, `None` — нет.

**Что починено сверх этого (цикл #385, 26.08, инжест решения владельца 25.08 22:22Z,
вариант 1 «поменяю ключ сейчас»).** Чеклист, по которому владелец собрался действовать,
вёл ключ НЕ ТУДА:

- `KEYCHAIN_SERVICE` называл связку `spa-claude-pat`. Такой записи на машине нет вовсе,
  и это имя не читает НИКТО: `push_to_github.py:307`, `spa_core/utils/keychain.py`,
  `auto_push.py` и `scripts/setup_pat.sh` берут токен по имени `GITHUB_PAT_SPA`. Имя
  жило ровно в двух местах — в этом файле и в его собственных тестах, то есть страж
  сверялся сам с собой (класс «сторож отвечает не на тот вопрос»).
- Шаг 3 чеклиста печатал команду `security-update-keychain` — такой команды не
  существует ни в macOS, ни у нас.

Исполнение чеклиста ДОСЛОВНО клало новый токен под именем, которого никто не читает, а
шаг 6 («удали старый токен на GitHub») отбирал тот единственный, который работал: цена
ошибки — обесточенная доставка, и обнаружилась бы она первым же пушем ночью. Теперь имя
связки — то же, по которому токен ищет доставка, и оно закреплено тестом ПРОТИВ ИСТОЧНИКА
(разбор `push_to_github.py` / `keychain.py`, не копия константы).

**И «поменял» перестало быть словом.** `--mark-rotated` больше не записывает дату по
одному лишь утверждению человека: он читает связку и сверяет ОТПЕЧАТОК ключа
(`sha256[:16]`, необратим, секретом не является и в состоянии хранится вместо токена —
инвариант #7 цел). Отпечаток совпал с предыдущим ⇒ ротации НЕ БЫЛО ⇒ ОТКАЗ (код 2), а не
свежая дата. Ключа в связке нет / нет самой `security` ⇒ тоже ОТКАЗ: наблюдения нет.
Осознанный обход — `--allow-unverified-keychain`, и он ЗАПИСЫВАЕТ в состояние, что дата
не подтверждена (`rotation_evidence: unverified`), а не делает вид, что подтверждена.
Первая отметка при пустом состоянии честно помечается `baseline_fingerprint`: дата ещё
на слове человека, но отпечаток уже наблюдение — со следующей ротации ложь становится
невозможной.

`--status` и `--check` связку ключей НЕ ТРОГАЮТ (закреплено тестом с самого MP-071):
читателю статуса секрет не нужен.

Коды возврата: **0** — ротация не нужна · **1** — нужна ротация ИЛИ дата НЕ ИЗВЕСТНА
(`--check`, требование карточки) · **2** — `--status` при неизмеренном состоянии
(конвенция репозитория «2 = не измерено»: репортёр, отвечающий 0 на «я не знаю», — тот
же fail-OPEN, только тише) ИЛИ `--mark-rotated`, которому нечем подтвердить ротацию.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

# ── константы ────────────────────────────────────────────────────────────────
ROTATION_INTERVAL_DAYS = 90
WARNING_THRESHOLD_DAYS = 14

# Имя записи в связке ключей, под которым токен ищет НАСТОЯЩАЯ доставка
# (`push_to_github.py:307`, `spa_core/utils/keychain.py`, `auto_push.py`,
# `scripts/setup_pat.sh`). Менять это имя в одиночку нельзя: тест
# `test_keychain_service_matches_the_name_delivery_actually_reads` разбирает исходники
# читателей и требует совпадения. До 26.08 здесь стояло `spa-claude-pat` — имя, которого
# нет ни в связке, ни у одного читателя; чеклист ротации вёл владельца именно по нему.
KEYCHAIN_SERVICE = "GITHUB_PAT_SPA"

# Имя, под которым страж жил до 26.08. Хранится, чтобы старое состояние на диске было
# УЗНАНО и названо вслух, а не молча принято за истину.
LEGACY_KEYCHAIN_SERVICE = "spa-claude-pat"

# Длина отпечатка токена (hex-символов от sha256). Отпечаток — НЕ секрет: он необратим,
# а 64 бита от sha256 по случайному токену GitHub не дают ни восстановления, ни
# практической проверки догадок. В состоянии хранится он, токен — никогда (инвариант #7).
FINGERPRINT_CHARS = 16

# Путь к state-файлу относительно корня проекта (2 уровня вверх от scripts/)
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
STATE_FILE = _PROJECT_ROOT / "data" / "pat_rotation_state.json"


# ── helpers ───────────────────────────────────────────────────────────────────

def _atomic_write(path: Path, data: dict) -> None:
    """Атомарная запись: tmpfile → os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".pat_rotation_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_keychain_secret(service: str, runner=None):
    """Читает секрет из связки ключей. Возвращает ``(secret|None, reason|None)``.

    ЕДИНСТВЕННЫЙ вызывающий — `--mark-rotated`. Ни `--status`, ни `--check`, ни режим по
    умолчанию связку не трогают: читателю статуса секрет не нужен, и это закреплено
    тестом `test_keychain_read_never_called_during_status` с самого MP-071.

    Отсутствие записи, отсутствие самой `security` и любой сбой чтения — РАЗНЫЕ причины,
    но один вид: наблюдения нет. Причина возвращается словами, чтобы отказ было чем
    объяснить, а не «что-то пошло не так».
    """
    runner = runner or subprocess.run
    try:
        result = runner(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError:
        return None, ("команды `security` на этой машине нет (не macOS) — "
                      "связка ключей не наблюдаема отсюда")
    except Exception as exc:  # taймаут, права, что угодно — вид один: не измерено
        return None, f"чтение связки не удалось ({exc.__class__.__name__})"

    if getattr(result, "returncode", 1) != 0:
        return None, f"в связке ключей нет записи с именем сервиса `{service}`"
    value = (result.stdout or "").strip()
    if not value:
        return None, f"запись `{service}` в связке ключей пуста"
    return value, None


def _fingerprint(secret: str) -> str:
    """Отпечаток токена: первые ``FINGERPRINT_CHARS`` hex-символов sha256.

    Нужен ровно для одного вопроса: «ключ ДРУГОЙ, чем в прошлый раз?». Сам токен не
    хранится и не печатается никогда (инвариант #7); отпечаток необратим.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]


def _load_state(state_file: Path = None):
    """Читает state-файл. НИЧЕГО не пишет. Нет файла / нечитаем ⇒ ``None``.

    Раньше здесь стояла авто-запись `last_rotation = сегодня`, и она и была дефектом:
    отсутствие наблюдения превращалось в наблюдение «ротация была только что». Читатель
    обязан отличать «дата известна» от «даты нет», поэтому «нет» возвращается отдельным
    значением, а не подставляется.
    """
    path = state_file or STATE_FILE
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def _unknown_status(reason: str, now: date, state=None) -> dict:
    """Статус «дата ротации НЕ ИЗВЕСТНА» — без единого ключа-суждения.

    Ключи `days_until_rotation` / `is_overdue` / `needs_rotation_soon` здесь ОТСУТСТВУЮТ
    намеренно (см. модульный докстринг): присутствующий и ложный ключ — это и есть тот
    способ, которым «не измерено» бесшумно читается как «в порядке».
    """
    keychain = KEYCHAIN_SERVICE
    if isinstance(state, dict):
        keychain = state.get("keychain_service", KEYCHAIN_SERVICE)
    return {
        "today": now.isoformat(),
        "rotation_date_known": False,
        "unknown_reason": reason,
        "keychain_service": keychain,
    }


def _compute_status(state, now: date = None, state_file: Path = None) -> dict:
    """Сколько дней до следующей ротации и признак срочности — либо честное «не знаю».

    `now` — ВХОД (по умолчанию реальные часы): тест закрепляет обе стороны сравнения и
    не начинает падать от того, что сдвинулся календарь.
    """
    now = now or date.today()
    path = state_file or STATE_FILE

    if not state:
        if not path.exists():
            reason = (f"файла состояния нет ({path}) — дата последней ротации PAT НЕ ИЗВЕСТНА. "
                      f"Её выставляет только `--mark-rotated`, и только после настоящей ротации")
        else:
            reason = (f"файл состояния {path} не читается (нет JSON-объекта) — "
                      f"дата последней ротации PAT НЕ ИЗМЕРЕНА")
        return _unknown_status(reason, now)

    next_rotation_str = state.get("next_rotation")
    try:
        if next_rotation_str:
            next_rotation = date.fromisoformat(next_rotation_str)
        else:
            # Fallback: считаем от last_rotation
            next_rotation = (date.fromisoformat(state["last_rotation"])
                             + timedelta(days=ROTATION_INTERVAL_DAYS))
    except (KeyError, TypeError, ValueError):
        # Ни одной пригодной даты. Раньше здесь летел KeyError/ValueError наружу;
        # теперь это тот же вид, что и «файла нет»: наблюдения нет.
        return _unknown_status(
            f"в {path} нет пригодной даты ротации (next_rotation={state.get('next_rotation')!r}, "
            f"last_rotation={state.get('last_rotation')!r}) — НЕ ИЗМЕРЕНО", now, state)

    days_until = (next_rotation - now).days
    is_overdue = days_until < 0
    needs_rotation = days_until < WARNING_THRESHOLD_DAYS

    status = {
        "today": now.isoformat(),
        "rotation_date_known": True,
        "last_rotation": state.get("last_rotation"),
        "next_rotation": next_rotation.isoformat(),
        "days_until_rotation": days_until,
        "is_overdue": is_overdue,
        "needs_rotation_soon": needs_rotation,
        "keychain_service": state.get("keychain_service", KEYCHAIN_SERVICE),
    }
    # Основание даты показывается ТОЛЬКО если оно записано: состояние, отмеченное до
    # 26.08, основания не знает, и выдумывать ему «подтверждено» нельзя.
    if state.get("rotation_evidence"):
        status["rotation_evidence"] = state["rotation_evidence"]
    if state.get("token_fingerprint"):
        status["token_fingerprint"] = state["token_fingerprint"]
    return status


def _print_unknown(status: dict) -> None:
    """Печатает ОТКАЗ: даты нет, значит и ответа «всё хорошо» нет."""
    print("❓  ДАТА РОТАЦИИ PAT НЕ ИЗВЕСТНА — это отказ, а не «всё в порядке»")
    print()
    print(f"  Причина: {status['unknown_reason']}")
    print()
    print("  Что делать:")
    print("  1. Если ротацию делали — вспомнить когда её делали НА САМОМ ДЕЛЕ;")
    print("     файл состояния восстанавливается только настоящей датой.")
    print("  2. Если не делали (или дата потеряна) — сделать ротацию сейчас "
          "по чеклисту ниже.")
    print()
    _print_checklist(_delivery_service_or_warn(status.get("keychain_service")))
    print()
    print(f"  Ожидаемый файл состояния: {STATE_FILE}")


def _print_warning(status: dict) -> None:
    """Печатает WARNING с полным checklist."""
    days = status["days_until_rotation"]
    deadline = status["next_rotation"]
    service = _delivery_service_or_warn(status.get("keychain_service"))

    if status["is_overdue"]:
        header = f"🚨  PAT ROTATION OVERDUE BY {abs(days)} DAYS (was due: {deadline})"
    else:
        header = f"⚠️   PAT ROTATION DUE IN {days} DAYS (deadline: {deadline})"

    print(header)
    print()
    _print_checklist(service)
    print()
    print(f"  Last rotation: {status['last_rotation']}")
    print(f"  State file:    {STATE_FILE}")


def _delivery_service_or_warn(named: str = None) -> str:
    """Всегда возвращает имя связки, из которой токен берёт ДОСТАВКА; расхождение называет.

    Имя в файле состояния — не источник правды: состояние, записанное до 26.08, несёт
    `spa-claude-pat`, и если печатать чеклист по нему, страж продолжит диктовать владельцу
    имя, по которому доставка не смотрит, — сколько бы констант в коде мы ни починили.
    """
    if named and named != KEYCHAIN_SERVICE:
        legacy = " — имя стража до 26.08" if named == LEGACY_KEYCHAIN_SERVICE else ""
        print(f"⚠️   в файле состояния записана связка `{named}`{legacy}: "
              f"её не читает НИ ОДИН потребитель токена.")
        print(f"     Доставка (push_to_github.py, spa_core/utils/keychain.py, auto_push.py) "
              f"берёт `{KEYCHAIN_SERVICE}` — чеклист ниже именно про него.")
        print()
    return KEYCHAIN_SERVICE


def _print_checklist(service: str = None) -> None:
    """Чеклист ротации — ОДИН на все режимы печати.

    До 26.08 здесь стояли имя связки, которого нет ни у одного читателя токена, и
    несуществующая команда `security-update-keychain`. Исполнение шагов дословно клало
    новый токен туда, куда доставка не смотрит, а шаг «удали старый токен» отбирал
    работающий. Поэтому и имя, и команда закреплены тестами-положительными контролями.
    """
    service = service or KEYCHAIN_SERVICE
    print("Чеклист ротации:")
    print("  1. GitHub → Settings → Developer settings → Personal access tokens →")
    print("     Fine-grained tokens → Generate new token")
    print("  2. Права: Contents (read/write), Workflows (read/write); срок — 90 дней")
    print("  3. Положить токен в связку ключей Мака ИМЕННО под тем именем,")
    print("     по которому его ищет доставка:")
    print(f"     security add-generic-password -U -a \"$USER\" -s {service} -w '<новый токен>'")
    print(f"     (`{service}` — не украшение: под этим именем токен читают")
    print("      push_to_github.py, spa_core/utils/keychain.py и auto_push.py.")
    print("      Положить под другим именем = доставка останется со старым токеном")
    print("      и умрёт на шаге 6.)")
    print("  4. Проверить доставку ДО удаления старого токена:")
    print("     python3 push_to_github.py --dry-run")
    print("  5. Отметить ротацию: python3 scripts/pat_rotation_helper.py --mark-rotated")
    print("     (команда сама сверит отпечаток ключа — слову «поменял» она не верит)")
    print("  6. Только теперь удалить старый токен на GitHub")


# ── команды ───────────────────────────────────────────────────────────────────

def cmd_default(status: dict) -> int:
    """Основной режим: показывает статус, при необходимости — WARNING или ОТКАЗ."""
    if not status.get("rotation_date_known"):
        _print_unknown(status)
        return 1

    days = status["days_until_rotation"]
    if status["needs_rotation_soon"] or status["is_overdue"]:
        _print_warning(status)
        return 1
    else:
        print(f"✅  PAT rotation OK — {days} days until next rotation (due {status['next_rotation']})")
        print(f"    Last rotation: {status['last_rotation']}")
        return 0


def cmd_check(status: dict) -> int:
    """--check: тихий режим, только exit code (0=ok, 1=нужна ротация ЛИБО дата не известна).

    Проверка «известна ли дата» стоит ПЕРВОЙ и намеренно: пока её не было, отсутствие
    наблюдения давало 0 — тот самый зелёный ответ, которого никто не измерял.
    """
    if not status.get("rotation_date_known"):
        return 1
    return 1 if status["needs_rotation_soon"] or status["is_overdue"] else 0


def cmd_status(status: dict) -> int:
    """--status: JSON вывод статуса. Код 2, если дата НЕ ИЗМЕРЕНА (конвенция репозитория)."""
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0 if status.get("rotation_date_known") else 2


def cmd_mark_rotated(now: date = None, state_file: Path = None,
                     secret_reader=None, allow_unverified: bool = False) -> int:
    """--mark-rotated: ЕДИНСТВЕННЫЙ путь, которым дата ротации попадает в состояние.

    И этот путь больше не верит на слово. #383 закрыл сочинение даты СТРАЖЕМ; здесь
    закрывается сочинение даты ЧЕЛОВЕКОМ: «поменял» проверяется отпечатком ключа в
    связке. Отпечаток тот же, что был, ⇒ ротации не было ⇒ ОТКАЗ (код 2), потому что
    записанная сейчас дата отодвинула бы следующее напоминание на 90 дней — ровно то
    молчание, ради которого страж и существует.

    Виды исхода, каждый называется в состоянии ключом `rotation_evidence`:
      · `observed_change`      — отпечаток отличается от прошлого: ротация НАБЛЮДЕНА;
      · `baseline_fingerprint` — прошлого отпечатка не было; дата ещё на слове человека,
                                 но отпечаток записан, и следующая ложь уже невозможна;
      · `unverified`           — осознанный обход `--allow-unverified-keychain`:
                                 наблюдения нет, и состояние ГОВОРИТ об этом.
    """
    now = now or date.today()
    path = state_file or STATE_FILE
    next_rotation = now + timedelta(days=ROTATION_INTERVAL_DAYS)

    existing = _load_state(path) or {}
    named = existing.get("keychain_service")
    if named and named != KEYCHAIN_SERVICE:
        # Старое состояние могло сохранить имя, которого не читает никто (до 26.08 —
        # `spa-claude-pat`). Молча принять его значило бы починить константу и оставить
        # дефект в данных; поэтому имя доставки побеждает, а расхождение НАЗЫВАЕТСЯ.
        legacy = " (имя стража до 26.08)" if named == LEGACY_KEYCHAIN_SERVICE else ""
        print(f"ℹ️  в состоянии записано имя связки `{named}`{legacy}, "
              f"а доставка читает `{KEYCHAIN_SERVICE}` — сверяю по имени доставки")

    reader = secret_reader or _read_keychain_secret
    secret, reason = reader(KEYCHAIN_SERVICE)
    previous_fp = existing.get("token_fingerprint")

    if secret is None:
        if not allow_unverified:
            print("⛔️  ОТКАЗ: подтвердить ротацию нечем — ключ не наблюдаем")
            print(f"    Причина: {reason}")
            print()
            _print_checklist(KEYCHAIN_SERVICE)
            print()
            print("    Осознанный обход (дата ляжет с пометкой «не подтверждена»):")
            print("      python3 scripts/pat_rotation_helper.py --mark-rotated "
                  "--allow-unverified-keychain")
            return 2
        fingerprint, evidence = None, "unverified"
    else:
        fingerprint = _fingerprint(secret)
        if previous_fp and fingerprint == previous_fp and not allow_unverified:
            print("⛔️  ОТКАЗ: ротации НЕ БЫЛО — ключ в связке тот же самый")
            print(f"    Отпечаток под `{KEYCHAIN_SERVICE}` не изменился "
                  f"с прошлой отметки ({previous_fp}).")
            print(f"    Дата последней ротации остаётся прежней: "
                  f"{existing.get('last_rotation', 'НЕ ИЗВЕСТНА')}")
            print()
            print("    Если токен действительно новый — он лёг под ДРУГИМ именем.")
            print("    Правильное имя и команда:")
            print()
            _print_checklist(KEYCHAIN_SERVICE)
            return 2
        if allow_unverified and previous_fp and fingerprint == previous_fp:
            evidence = "unverified"
        elif previous_fp:
            evidence = "observed_change"
        else:
            evidence = "baseline_fingerprint"

    state = {
        "last_rotation": now.isoformat(),
        "next_rotation": next_rotation.isoformat(),
        "keychain_service": KEYCHAIN_SERVICE,
        "rotation_evidence": evidence,
    }
    if fingerprint:
        state["token_fingerprint"] = fingerprint
    if previous_fp:
        state["previous_token_fingerprint"] = previous_fp
    _atomic_write(path, state)

    verdicts = {
        "observed_change": "ротация НАБЛЮДЕНА: ключ в связке отличается от прошлого",
        "baseline_fingerprint": ("дата записана со слов, отпечаток ключа — записан "
                                 "впервые; со следующей ротации сверка станет доказательной"),
        "unverified": "дата записана БЕЗ подтверждения (обход) — так и помечена в состоянии",
    }
    print(f"✅  PAT rotation marked. Next rotation due: {next_rotation.isoformat()}")
    print(f"    Основание: {verdicts[evidence]}")
    print(f"    State file updated: {path}")
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="PAT Rotation Helper — SPA Project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/pat_rotation_helper.py              # показать статус / warning
  python3 scripts/pat_rotation_helper.py --check      # exit 0=ok, 1=rotation needed
  python3 scripts/pat_rotation_helper.py --status     # JSON вывод
  python3 scripts/pat_rotation_helper.py --mark-rotated  # записать дату ротации
""",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="Тихий режим: только exit code (0=ok, 1=нужна ротация)",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="Вывести JSON-статус",
    )
    group.add_argument(
        "--mark-rotated",
        action="store_true",
        dest="mark_rotated",
        help="Обновить дату ротации на сегодня",
    )
    parser.add_argument(
        "--allow-unverified-keychain",
        action="store_true",
        dest="allow_unverified_keychain",
        help=("Осознанный обход сверки отпечатка при --mark-rotated: дата будет "
              "записана с пометкой «не подтверждена» (rotation_evidence=unverified)"),
    )
    args = parser.parse_args(argv)

    if args.mark_rotated:
        return cmd_mark_rotated(allow_unverified=args.allow_unverified_keychain)

    state = _load_state()
    status = _compute_status(state)


    if args.check:
        return cmd_check(status)
    elif args.status:
        return cmd_status(status)
    else:
        return cmd_default(status)


if __name__ == "__main__":
    sys.exit(main())
