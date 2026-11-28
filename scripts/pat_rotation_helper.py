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


# ── СОСТОЯНИЕ ключа: наблюдение, которое спрашивают у GitHub (ADR-1094) ───────
#
# **Почему этот раздел появился 24.11 (цикл #1239, карточка
# `inbox-strazh-sroka-klyucha-ne-sprashivaet-github`, авария ADR-1093).** Всё, что
# стои́т выше, отвечает на ОДИН вопрос: «прошло ли 90 дней от даты, которую мы сами
# записали». 24.11 ключ умер, доставка встала, и сторож в ту же сборку честно сказал
# `WARNING "PAT rotation due soon: 2026-11-24 (0 days)"` — то есть ответил ВЕРНО на
# свой вопрос и мимо нужного: записанный срок совпал со смертью СЛУЧАЙНО, настоящий
# срок знает только GitHub, и за всю историю модуля его не спросили НИ РАЗУ (замер:
# `grep api.github|urlopen|Authorization|expiration` — 0 попаданий).
#
# «Жив ли ключ» и «прошло ли 90 дней от нашей записи» — РАЗНЫЕ наблюдения
# (инвариант #17), поэтому здесь не правится прежний вопрос, а добавляется второй, и
# у него СВОИ три исхода: принят · отклонён · НЕ ИЗМЕРЕНО с названной причиной.
# Ни один из трёх не похож на другой, и «не измерено» никогда не выдаётся за «принят».
#
# Связку ключей этот путь ЧИТАЕТ — в отличие от `--status`/`--check`, которые её не
# трогают и не будут (тест `test_keychain_read_never_called_during_status` жив с
# MP-071): читателю КАЛЕНДАРЯ секрет не нужен, а читателю СОСТОЯНИЯ без него нечего
# спросить. Сам токен не печатается, не записывается и не попадает ни в одну строку
# причины (инвариант #7) — наружу уходят только код ответа и объявленный сервисом срок.

TOKEN_PROBE_URL = "https://api.github.com/user"
TOKEN_EXPIRATION_HEADER = "github-authentication-token-expiration"
TOKEN_PROBE_TIMEOUT_S = 10.0

#: Три исхода наблюдения о СОСТОЯНИИ ключа. Значения — часть контракта с читателями
#: (`system_health_monitor._check_pat_token_alive`, `problem_store`), а не ярлыки.
TOKEN_ALIVE = "alive"
TOKEN_REJECTED = "rejected"
TOKEN_UNMEASURED = "unmeasured"

# Порог, с которого КАЛЕНДАРНЫЙ вопрос становится аварией. До 24.11 его роль играл
# `is_overdue = days_until < 0`, то есть CRITICAL приходил НА СЛЕДУЮЩИЙ день после
# смерти ключа — когда доставка уже стои́т. Трое суток — запас на то, чтобы владелец
# успел выпустить ключ, не останавливая доставку (решение ADR-1094).
CRITICAL_THRESHOLD_DAYS = 3


def _github_identity_probe(token: str, timeout: float = TOKEN_PROBE_TIMEOUT_S):
    """ЕДИНСТВЕННАЯ дверь к GitHub. Возвращает ``(status|None, headers, reason|None)``.

    Только stdlib (инвариант #4). Любой сбой сети, DNS, прокси или таймаут — это
    ОДИН вид исхода: кода ответа нет, значит состояние ключа НЕ ИЗМЕРЕНО. Отказ
    сервиса (401) кодом ответа ЯВЛЯЕТСЯ и возвращается как ответ, а не как сбой:
    `HTTPError` для нас — не ошибка, а вердикт сервиса.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        TOKEN_PROBE_URL,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "spa-pat-rotation-guard",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), dict(resp.headers.items()), None
    except urllib.error.HTTPError as exc:
        headers = dict(exc.headers.items()) if exc.headers else {}
        return int(exc.code), headers, None
    except Exception as exc:  # noqa: BLE001 — вид один: наблюдения нет
        return None, {}, (f"запрос к {TOKEN_PROBE_URL} не состоялся "
                          f"({exc.__class__.__name__}) — состояние ключа НЕ ИЗМЕРЕНО")


def _header(headers, name: str):
    """Регистронезависимое чтение заголовка; нет такого — ``None``.

    HTTP-заголовки регистронезависимы по RFC, и `dict` из `resp.headers.items()`
    сохраняет тот регистр, который прислал сервер. Спросить по точному имени значило
    бы отвечать «срок не объявлен» от того, что сервер написал имя иначе.
    """
    if not isinstance(headers, dict):
        return None
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return value
    return None


def declared_expiration_date(headers):
    """Срок, ОБЪЯВЛЕННЫЙ сервисом. Возвращает ``(date|None, raw|None)``.

    GitHub присылает его у fine-grained токена в виде
    ``2026-11-24 19:48:26 UTC``. Разобрать не вышло ⇒ дата `None`, но СЫРАЯ строка
    возвращается: «сервер прислал то, чего я не понял» и «сервер ничего не прислал»
    — разные состояния, и читатель вправе их различить.
    """
    raw = _header(headers, TOKEN_EXPIRATION_HEADER)
    if raw is None or not str(raw).strip():
        return None, None
    text = str(raw).strip()
    try:
        return date.fromisoformat(text[:10]), text
    except ValueError:
        return None, text


def probe_token_liveness(service: str = KEYCHAIN_SERVICE, secret_reader=None,
                         http_probe=None, recorded_next_rotation=None,
                         timeout: float = TOKEN_PROBE_TIMEOUT_S) -> dict:
    """Спрашивает у GitHub, принимает ли он наш ключ. Три исхода, инвариант #17.

    Обе двери наружу — ВХОДЫ (`secret_reader=`, `http_probe=`), как часы в
    `_compute_status`: сцена, которой нужен ответ «401», обязана его получить без
    настоящей сети и без настоящего ключа, иначе проверку такого сторожа можно было
    бы написать только с живым мёртвым ключом в руках.

    Ключи результата:

    · ``liveness`` — ``alive`` · ``rejected`` · ``unmeasured``;
    · ``reason``   — названная причина у `rejected` и `unmeasured`, `None` у `alive`;
    · ``http_status`` — код ответа либо `None` (не измерено);
    · ``declared_expiration`` — срок, объявленный СЕРВИСОМ (ISO-дата) либо `None`;
    · ``record_vs_declared`` — присутствует ТОЛЬКО когда сравнивать было с чем:
      наша запись против объявленного срока. Расхождение — отдельная НАХОДКА, а не
      повод тихо переписать запись: переписать значило бы потерять единственный
      след того, что наш календарь не про этот ключ.
    """
    reader = secret_reader or _read_keychain_secret
    secret, reason = reader(service)

    result = {
        "service": service,
        "probe_url": TOKEN_PROBE_URL,
        "http_status": None,
        "declared_expiration": None,
        "declared_expiration_raw": None,
    }

    if secret is None:
        result["liveness"] = TOKEN_UNMEASURED
        result["reason"] = f"состояние ключа НЕ ИЗМЕРЕНО — {reason}"
        return result

    probe = http_probe or _github_identity_probe
    status, headers, failure = probe(secret, timeout)
    del secret  # дальше токен не нужен ни одной строке (инвариант #7)

    if failure is not None or status is None:
        result["liveness"] = TOKEN_UNMEASURED
        result["reason"] = failure or (
            f"дверь к {TOKEN_PROBE_URL} не вернула кода ответа — "
            f"состояние ключа НЕ ИЗМЕРЕНО")
        return result

    status = int(status)
    result["http_status"] = status
    exp_date, exp_raw = declared_expiration_date(headers)
    result["declared_expiration"] = exp_date.isoformat() if exp_date else None
    result["declared_expiration_raw"] = exp_raw

    if status == 200:
        result["liveness"] = TOKEN_ALIVE
        result["reason"] = None
    elif status == 401:
        result["liveness"] = TOKEN_REJECTED
        result["reason"] = (
            f"GitHub ответил 401 на {TOKEN_PROBE_URL}: ключ `{service}` НЕ "
            f"аутентифицируется — доставка на origin, пуш сайта и заказ прогона CI "
            f"стоя́т до нового ключа")
    else:
        # Ни «принят», ни «отклонён»: 403 при лимите, 5xx у сервиса, 404 у чужого
        # маршрута. Назвать это отказом значило бы поднять тревогу на исправном
        # ключе, назвать принятием — проспать мёртвый.
        result["liveness"] = TOKEN_UNMEASURED
        result["reason"] = (
            f"GitHub ответил {status} — это ни «ключ принят», ни «ключ отклонён»; "
            f"состояние ключа НЕ ИЗМЕРЕНО")

    if exp_date is not None and recorded_next_rotation:
        try:
            recorded = date.fromisoformat(str(recorded_next_rotation)[:10])
        except (TypeError, ValueError):
            recorded = None
        if recorded is None:
            result["record_vs_declared"] = TOKEN_UNMEASURED
            result["record_vs_declared_detail"] = (
                f"записанный срок {recorded_next_rotation!r} не разбирается как дата")
        elif recorded == exp_date:
            result["record_vs_declared"] = "agrees"
        else:
            result["record_vs_declared"] = "differs"
            result["record_vs_declared_detail"] = (
                f"наша запись next_rotation={recorded.isoformat()}, а GitHub объявляет "
                f"срок {exp_date.isoformat()} — расхождение "
                f"{abs((exp_date - recorded).days)} дн.: наш календарь считает НЕ ПРО "
                f"ЭТОТ ключ")
    return result


# ── СПОСОБНОСТЬ ключа: третий вопрос о том же ключе (ADR-1128, 2026-11-28) ────
#
# Два вопроса выше про КАЛЕНДАРЬ («прошло ли 90 дней от НАШЕЙ записи») и про
# СОСТОЯНИЕ («принимает ли GitHub ключ прямо сейчас»). Третий вопрос —
# СПОСОБНОСТЬ: «а умеет ли ПРИНЯТЫЙ ключ то, ради чего он у нас есть».
#
# Замер 2026-11-28 на ЖИВОМ ключе, выпущенном владельцем 26.11, то есть при ОБОИХ
# прежних сторожах зелёных (`/user` → 200):
#
#   POST /repos/yurii-spa/SPA/actions/workflows/387027328/dispatches
#     → 403 "Resource not accessible by personal access token"
#
# Заказать контрольный прогон CI нельзя, и у каждого цикла «вердикт CI о моём
# коммите» выходит НЕ ИЗМЕРЕН — на том же ключе, про который оба сторожа говорят
# «жив». Причина названа и она НАША: карточка ротации
# (`own-klyuch-github-protuh-dostavka-ostanovlena`) и `docs/GITHUB_CREDENTIALS.md`
# просили у владельца `Contents RW` + `Workflows RW`, а `workflow_dispatch`
# гейтит РАЗРЕШЕНИЕ `Actions` — его не просил никто ни в одной строке.
#
# ⚠️ ПРОБА ПРАВА НА ЗАПИСЬ НЕ ИМЕЕТ ПРАВА ПИСАТЬ. Дверь здесь — запрос ТОЙ ЖЕ
# ФОРМЫ по ЗАВЕДОМО ОТСУТСТВУЮЩЕЙ цели: разрешение GitHub проверяет ДО
# существования цели, поэтому `403` ⇒ права НЕТ, а `422`/`404` «цели не
# существует» ⇒ право ЕСТЬ, и побочного действия нет ни в одном исходе. Ось
# ДОКАЗАНА на живом ключе двумя ПРОТИВОПОЛОЖНЫМИ ответами на запросы одной формы:
# `dispatches` → 403, `PATCH git/refs/heads/<отсутствующая>` → 422; ветка-зонд
# после обеих проб по-прежнему 404.
#
# ⚠️ И ВТОРОЕ, без чего замер был бы ложным: репозиторий ПУБЛИЧНЫЙ, поэтому
# ЧИТАЮЩИЕ двери отвечают `200` БЕЗ ВСЯКОГО ключа (замер того же дня: `GET
# /repos/.../contents/README.md` и `GET /repos/.../actions/runs` без заголовка
# авторизации → 200; с заведомо негодным ключом → 401). Значит `200` на читающей
# двери есть свойство ВИДИМОСТИ репозитория, а не грант нашего ключа, и выдавать
# его за «право на чтение есть» значило бы ровно то же, что «ключ ЕСТЬ» за «ключ
# ЖИВ» (ADR-1094). Такие двери НАЗВАНЫ и из знаменателя исключены.

CAPABILITY_REPO = "yurii-spa/SPA"

#: Тот же файл воркфлоу, которым заказывает прогон `scripts/ci_control_verdict.py`
#: (`WORKFLOW_FILE`). Спрашивать о праве надо у ТОЙ двери, которой пользуется
#: система, а не у любой: право может быть выдано на один воркфлоу и не на другой.
CAPABILITY_CI_WORKFLOW = "ci-control.yml"

#: Ветка, КОТОРОЙ НЕТ, — и в этом вся безвредность пробы о праве на запись.
#: Появись она когда-нибудь, запрос пошёл бы по НАСТОЯЩЕЙ цели; поэтому её
#: отсутствие СПРАШИВАЕТСЯ перед каждым замером, а не предполагается.
CAPABILITY_ABSENT_REF = "__spa_capability_probe_absent__"
CAPABILITY_ZERO_SHA = "0" * 40

#: Исходы о ОДНОЙ двери. Значения — часть контракта с читателями
#: (`system_health_monitor._check_pat_token_capable`), а не ярлыки.
CAP_CAN = "can"
CAP_CANNOT = "cannot"
CAP_UNMEASURED = "unmeasured"
#: Четвёртый и пятый исходы — НЕ разновидности «не измерено», а ОБЪЯВЛЕННЫЕ границы
#: самой меры: у двери нет пробы без побочного действия · на дверь отвечает
#: видимость репозитория, а не грант. Сложи их с «не измерено» — и вечное
#: предупреждение научит читателя не смотреть; выдай за «можно» — и мера врёт.
CAP_NO_SAFE_PROBE = "no_safe_probe"
CAP_ANSWERED_BY_VISIBILITY = "answered_by_repo_visibility"

#: ЗАМКНУТЫЙ перечень дверей, которыми система пользуется ключом доставки. Снят с
#: кода (`push_to_github.py`, `push_to_github_batch.py`, `scripts/safe_site_push.py`,
#: `scripts/ci_control_verdict.py`), а не из головы. Удаление строки отсюда краснит
#: сторожа: перечень, который можно укоротить молча, перестаёт быть знаменателем.
CAPABILITY_DOORS = (
    {
        "key": "contents_write",
        "need": "доставить коммит на origin (канонический пушер: git/blobs · "
                "git/trees · git/commits · PATCH git/refs)",
        "permission": "Contents: Read and write",
        "method": "PATCH",
        "path": "/repos/{repo}/git/refs/heads/" + CAPABILITY_ABSENT_REF,
        "body": {"sha": CAPABILITY_ZERO_SHA},
        "can_codes": (404, 422),
        "cannot_codes": (403,),
    },
    {
        "key": "actions_write",
        "need": "заказать контрольный прогон CI о своём коммите "
                "(scripts/ci_control_verdict.py → workflow_dispatch)",
        "permission": "Actions: Read and write",
        "method": "POST",
        "path": "/repos/{repo}/actions/workflows/" + CAPABILITY_CI_WORKFLOW + "/dispatches",
        "body": {"ref": "refs/heads/" + CAPABILITY_ABSENT_REF},
        "can_codes": (404, 422),
        "cannot_codes": (403,),
    },
    {
        "key": "workflows_write",
        "need": "доставить сам файл воркфлоу (.github/workflows/**)",
        "permission": "Workflows: Read and write",
        "state": CAP_NO_SAFE_PROBE,
        "reason": "право проверяется на СОДЕРЖИМОМ коммита, значит замер требовал бы "
                  "записать файл воркфлоу — пробы без побочного действия у этой "
                  "двери мы не знаем",
    },
    {
        "key": "contents_read",
        "need": "прочитать файл с origin (safe_site_push, сверка витрины)",
        "permission": "Contents: Read",
        "state": CAP_ANSWERED_BY_VISIBILITY,
        "reason": "репозиторий ПУБЛИЧНЫЙ: тот же GET отвечает 200 вовсе без ключа "
                  "(замер 2026-11-28), поэтому код ответа про грант не говорит ничего",
    },
    {
        "key": "actions_read",
        "need": "прочитать вердикт прогона CI и его артефакты",
        "permission": "Actions: Read",
        "state": CAP_ANSWERED_BY_VISIBILITY,
        "reason": "репозиторий ПУБЛИЧНЫЙ: GET /actions/runs отвечает 200 вовсе без "
                  "ключа (замер 2026-11-28) — это видимость, а не грант",
    },
)


def _github_door_probe(token: str, method: str, url: str, body=None,
                       timeout: float = TOKEN_PROBE_TIMEOUT_S):
    """ЕДИНСТВЕННАЯ дверь к GitHub для вопроса о СПОСОБНОСТИ. ``(status|None, reason|None)``.

    Только stdlib (инвариант #4). Как и у пробы состояния, отказ сервиса кодом
    ответа ЯВЛЯЕТСЯ: `HTTPError` — вердикт, а не сбой. Сбой сети/DNS/таймаут — один
    вид исхода: кода нет, значит способность НЕ ИЗМЕРЕНА.
    """
    import json as _json
    import urllib.error
    import urllib.request

    data = None if body is None else _json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "spa-pat-capability-guard",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), None
    except urllib.error.HTTPError as exc:
        return int(exc.code), None
    except Exception as exc:  # noqa: BLE001 — вид один: наблюдения нет
        return None, (f"{method} {url} не состоялся ({exc.__class__.__name__}) — "
                      f"способность НЕ ИЗМЕРЕНА")


def probe_token_capabilities(service: str = KEYCHAIN_SERVICE, secret_reader=None,
                             door_probe=None, doors=None, repo: str = None,
                             timeout: float = TOKEN_PROBE_TIMEOUT_S) -> dict:
    """Умеет ли ПРИНЯТЫЙ ключ то, ради чего он у нас есть. Исходы — по двери.

    Обе двери наружу — ВХОДЫ (`secret_reader=`, `door_probe=`), как часы в
    `_compute_status` и как сеть в `probe_token_liveness`: сцене, которой нужен
    ответ «403», незачем иметь на руках живой ключ без права.

    Ключи результата: ``repo`` · ``doors`` (по строке на дверь: ``key``, ``state``,
    ``reason``, ``http_status``, ``permission``, ``need``) · счётчики ``can`` /
    ``cannot`` / ``unmeasured`` / ``no_safe_probe`` / ``answered_by_visibility`` ·
    ``measured_doors`` (знаменатель — только двери с безвредной пробой) ·
    ``verdict``.

    Вердикт: хоть одна дверь ``cannot`` ⇒ ``cannot`` (находка НАЗВАНА, и
    неизмеренное рядом печатается как СКАЗАННАЯ нижняя граница) · иначе хоть одна
    ``unmeasured`` ⇒ ``unmeasured`` · иначе ``can``. «Не измерено» никогда не
    выдаётся за «умеет».
    """
    spec = tuple(doors if doors is not None else CAPABILITY_DOORS)
    slug = repo or CAPABILITY_REPO
    reader = secret_reader or _read_keychain_secret
    probe = door_probe or _github_door_probe

    result = {
        "service": service,
        "repo": slug,
        "probe_ref": CAPABILITY_ABSENT_REF,
        "doors": [],
    }

    def _row(door, state, reason=None, http_status=None):
        return {
            "key": door.get("key"),
            "need": door.get("need"),
            "permission": door.get("permission"),
            "state": state,
            "reason": reason,
            "http_status": http_status,
        }

    secret, secret_reason = reader(service)
    probing = [d for d in spec if d.get("state") is None]
    declared = [d for d in spec if d.get("state") is not None]

    if not probing:
        # Знаменатель пуст — спрашивать не о чем, и ветку-зонд трогать незачем:
        # лишний запрос к сервису ничего бы не измерил.
        pass
    elif secret is None:
        for door in probing:
            result["doors"].append(_row(
                door, CAP_UNMEASURED,
                f"способность НЕ ИЗМЕРЕНА — {secret_reason}"))
    else:
        # Безвредность пробы — НАБЛЮДЕНИЕ, а не допущение: обе пробы ниже бьют по
        # ветке-зонду, и если она существует, запрос пошёл бы по НАСТОЯЩЕЙ цели.
        # Поэтому спрашиваем ОДИН раз и, не получив 404, отказываемся мерить вовсе.
        ref_url = (f"https://api.github.com/repos/{slug}/git/ref/heads/"
                   f"{CAPABILITY_ABSENT_REF}")
        ref_status, ref_failure = probe(secret, "GET", ref_url, None, timeout)
        if ref_status != 404:
            why = ref_failure or (
                f"ветка-зонд {CAPABILITY_ABSENT_REF} ответила {ref_status}, а не 404: "
                f"проба перестала быть безвредной и НЕ ЗАПУСКАЛАСЬ")
            for door in probing:
                result["doors"].append(_row(door, CAP_UNMEASURED, why, ref_status))
        else:
            for door in probing:
                url = "https://api.github.com" + door["path"].format(repo=slug)
                status, failure = probe(secret, door["method"], url,
                                        door.get("body"), timeout)
                if failure is not None or status is None:
                    result["doors"].append(_row(
                        door, CAP_UNMEASURED,
                        failure or f"{door['method']} {url} не вернул кода ответа — "
                                   f"способность НЕ ИЗМЕРЕНА",
                        status))
                elif status in tuple(door["cannot_codes"]):
                    result["doors"].append(_row(
                        door, CAP_CANNOT,
                        f"GitHub ответил {status} на {door['method']} по ЗАВЕДОМО "
                        f"отсутствующей цели: права «{door['permission']}» у ключа "
                        f"`{service}` НЕТ, и значит не работает: {door['need']}",
                        status))
                elif status in tuple(door["can_codes"]):
                    result["doors"].append(_row(
                        door, CAP_CAN,
                        None, status))
                else:
                    # Ни «403», ни «цели не существует»: 401 у мёртвого ключа, 5xx у
                    # сервиса, 429 у лимита. Назвать это запретом значило бы поднять
                    # тревогу на исправном праве, назвать правом — проспать запрет.
                    result["doors"].append(_row(
                        door, CAP_UNMEASURED,
                        f"GitHub ответил {status} — это ни «права нет», ни «цели не "
                        f"существует»; способность НЕ ИЗМЕРЕНА",
                        status))
        del secret  # дальше токен не нужен ни одной строке (инвариант #7)

    for door in declared:
        result["doors"].append(_row(door, door["state"], door.get("reason")))

    counts = {CAP_CAN: 0, CAP_CANNOT: 0, CAP_UNMEASURED: 0,
              CAP_NO_SAFE_PROBE: 0, CAP_ANSWERED_BY_VISIBILITY: 0}
    for row in result["doors"]:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    result["can"] = counts[CAP_CAN]
    result["cannot"] = counts[CAP_CANNOT]
    result["unmeasured"] = counts[CAP_UNMEASURED]
    result["no_safe_probe"] = counts[CAP_NO_SAFE_PROBE]
    result["answered_by_visibility"] = counts[CAP_ANSWERED_BY_VISIBILITY]
    result["measured_doors"] = len(probing)
    result["declared_doors"] = len(spec)

    if result["cannot"]:
        result["verdict"] = CAP_CANNOT
    elif result["unmeasured"]:
        result["verdict"] = CAP_UNMEASURED
    elif result["can"]:
        result["verdict"] = CAP_CAN
    else:
        # Ни одной двери с безвредной пробой не осталось — это НЕ «всё умеет».
        result["verdict"] = CAP_UNMEASURED
    return result

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
    # Лестница сдвинута ADR-1094: до 24.11 авария начиналась ТОЛЬКО с `is_overdue`,
    # то есть на следующий день после смерти ключа. `is_critical_window` включает и
    # сам день срока, и трое суток до него — иначе читатель узнаёт об остановке
    # доставки ПОСЛЕ остановки.
    is_critical_window = days_until <= CRITICAL_THRESHOLD_DAYS

    status = {
        "today": now.isoformat(),
        "rotation_date_known": True,
        "last_rotation": state.get("last_rotation"),
        "next_rotation": next_rotation.isoformat(),
        "days_until_rotation": days_until,
        "is_overdue": is_overdue,
        "needs_rotation_soon": needs_rotation,
        "is_critical_window": is_critical_window,
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
    """--check: код возврата И названная ПРИЧИНА отказа в stderr (0=ок, 1=иначе).

    Проверка «известна ли дата» стоит ПЕРВОЙ и намеренно: пока её не было, отсутствие
    наблюдения давало 0 — тот самый зелёный ответ, которого никто не измерял.

    До 24.11 режим был ПОЛНОСТЬЮ молчаливым: возвращал 1 и не печатал ни одной строки
    (замер ADR-1093). Молчаливый ненулевой код неотличим от упавшего интерпретатора,
    поэтому причина теперь печатается — в stderr, чтобы stdout у тихого режима остался
    пустым для тех, кто его разбирает.
    """
    if not status.get("rotation_date_known"):
        print(f"НЕ ИЗМЕРЕНО: {status.get('unknown_reason')}", file=sys.stderr)
        return 1
    if status["is_overdue"]:
        print(f"ПРОСРОЧЕНО: срок ротации был {status['next_rotation']} "
              f"({abs(status['days_until_rotation'])} дн. назад)", file=sys.stderr)
        return 1
    if status["needs_rotation_soon"]:
        print(f"СРОК БЛИЗКО: ротация до {status['next_rotation']} "
              f"({status['days_until_rotation']} дн.)", file=sys.stderr)
        return 1
    return 0


def cmd_status(status: dict) -> int:
    """--status: JSON вывод статуса. Код 2, если дата НЕ ИЗМЕРЕНА (конвенция репозитория)."""
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0 if status.get("rotation_date_known") else 2


def cmd_probe_token(result: dict) -> int:
    """--probe-token: СОСТОЯНИЕ ключа по ответу GitHub. 0=принят · 1=отклонён · 2=НЕ ИЗМЕРЕНО.

    Код 2 у «не измерено» — конвенция репозитория и здесь особенно важна: сеть
    недоступна и ключ мёртв обязаны выглядеть РАЗНО, иначе первое молча закроет
    тревогу о втором.
    """
    liveness = result.get("liveness")
    service = result.get("service", KEYCHAIN_SERVICE)

    if liveness == TOKEN_ALIVE:
        declared = result.get("declared_expiration") or "сервисом не объявлен"
        print(f"✅  ключ `{service}` ПРИНЯТ GitHub (HTTP {result.get('http_status')})")
        print(f"    Срок, объявленный сервисом: {declared}")
        if result.get("record_vs_declared") == "differs":
            print(f"⚠️   {result.get('record_vs_declared_detail')}")
        return 0

    if liveness == TOKEN_REJECTED:
        print("⛔️  ДОСТАВКА ОСТАНОВЛЕНА: GitHub не принимает ключ")
        print()
        print(f"    Причина: {result.get('reason')}")
        print()
        _print_checklist(KEYCHAIN_SERVICE)
        return 1

    print("❓  СОСТОЯНИЕ КЛЮЧА НЕ ИЗМЕРЕНО — это отказ, а не «ключ в порядке»")
    print()
    print(f"    Причина: {result.get('reason')}")
    return 2


def cmd_probe_capabilities(result: dict) -> int:
    """--probe-capabilities: СПОСОБНОСТЬ ключа по дверям. 0=умеет · 1=не умеет · 2=НЕ ИЗМЕРЕНО.

    Печатается ВЫБОР знаменателя, а не только итог: двери, на которые отвечает
    видимость публичного репозитория, и двери без безвредной пробы названы отдельно
    — иначе «2 из 2 умеет» читалось бы как «ключ умеет всё», а это другое
    утверждение.
    """
    service = result.get("service", KEYCHAIN_SERVICE)
    print(f"Способность ключа `{service}` по дверям репозитория {result.get('repo')} "
          f"(ветка-зонд {result.get('probe_ref')}, побочного действия нет):")
    for row in result.get("doors", []):
        mark = {CAP_CAN: "✅ УМЕЕТ        ",
                CAP_CANNOT: "⛔️ НЕ УМЕЕТ     ",
                CAP_UNMEASURED: "❓ НЕ ИЗМЕРЕНО  ",
                CAP_NO_SAFE_PROBE: "⬜ НЕТ БЕЗВРЕДНОЙ ПРОБЫ",
                CAP_ANSWERED_BY_VISIBILITY: "⬜ ОТВЕЧАЕТ ВИДИМОСТЬ РЕПО",
                }.get(row.get("state"), row.get("state"))
        http = row.get("http_status")
        http_s = f" (HTTP {http})" if http is not None else ""
        print(f"  {mark} {row.get('key')}{http_s} — {row.get('permission')}")
        print(f"      нужно для: {row.get('need')}")
        if row.get("reason"):
            print(f"      {row['reason']}")
    print(f"  знаменатель: дверей объявлено {result.get('declared_doors')}, "
          f"с безвредной пробой {result.get('measured_doors')}; "
          f"умеет {result.get('can')} · НЕ умеет {result.get('cannot')} · "
          f"НЕ ИЗМЕРЕНО {result.get('unmeasured')} · без пробы "
          f"{result.get('no_safe_probe')} · отвечает видимость "
          f"{result.get('answered_by_visibility')}")

    verdict = result.get("verdict")
    if verdict == CAP_CANNOT:
        print()
        print("⛔️  У КЛЮЧА НЕТ ПРАВА, которым система пользуется — и ключ при этом ЖИВ")
        print("    Это действие ВЛАДЕЛЬЦА: права выдаются у токена, а не в коде.")
        print("    https://github.com/settings/personal-access-tokens → ключ "
              f"`{service}` → Repository permissions → добавить право, названное выше.")
        if result.get("unmeasured"):
            print(f"    И рядом НЕ ИЗМЕРЕНО {result['unmeasured']} двер(ь/и): число "
                  f"запретов выше — СКАЗАННАЯ нижняя граница, а не итог.")
        return 1
    if verdict == CAP_CAN:
        return 0
    print()
    print("❓  СПОСОБНОСТЬ НЕ ИЗМЕРЕНА — это отказ, а не «ключ умеет всё»")
    return 2


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
        "--probe-token",
        action="store_true",
        dest="probe_token",
        help=("Спросить у GitHub СОСТОЯНИЕ ключа: 0=принят, 1=отклонён, "
              "2=НЕ ИЗМЕРЕНО (это другой вопрос, чем календарь ротации)"),
    )
    group.add_argument(
        "--probe-capabilities",
        action="store_true",
        dest="probe_capabilities",
        help=("Спросить у GitHub СПОСОБНОСТЬ ключа по дверям, которыми система им "
              "пользуется: 0=умеет, 1=права НЕТ, 2=НЕ ИЗМЕРЕНО (третий вопрос — "
              "не календарь и не состояние)"),
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

    if args.probe_capabilities:
        return cmd_probe_capabilities(probe_token_capabilities())

    if args.probe_token:
        # Записанный срок передаётся ТОЛЬКО как второй операнд сравнения: вердикт о
        # состоянии ключа от него не зависит ни в одну сторону.
        return cmd_probe_token(probe_token_liveness(
            recorded_next_rotation=status.get("next_rotation")))


    if args.check:
        return cmd_check(status)
    elif args.status:
        return cmd_status(status)
    else:
        return cmd_default(status)


if __name__ == "__main__":
    sys.exit(main())
