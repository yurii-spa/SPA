"""spa_core.audit.proof_of_track — Proof-of-Track Merkle core (MP-406, OFFLINE).

Делает дневной трек решений (audit trail MP-310) криптографически
фиксируемым: ежедневный Merkle root поверх событий
``data/audit_trail.jsonl`` + персистентная очередь якорей «pending
on-chain publication». Трек нельзя переписать задним числом: расхождение
пересчитанного root с уже заякоренным фиксируется как discrepancy,
старый root НИКОГДА не перезаписывается.

ВАЖНО — границы спринта (SPA-V426):
* RPC-ключей нет (MP-017 не выполнен) → on-chain публикация в этом
  спринте НЕВОЗМОЖНА и НЕ выполняется. Модуль строго offline.
* Каждый якорь пишется с ``published: false``, ``tx_hash: null`` и
  ``note: "on-chain publication pending MP-017 RPC keys"``. Публикация
  в сеть — отдельным спринтом после MP-017.
* Advisory only: модуль ничего не решает по капиталу, не трогает
  risk/execution/allocator/cycle_runner; audit_trail.py только читается.
* Pure stdlib (hashlib/json/os/...), без web3, без requests, без LLM SDK.

Криптографические правила (детерминированные, задокументированы для
независимой верификации):

1. Канонизация события: ``json.dumps(event, sort_keys=True,
   separators=(",", ":"), ensure_ascii=False)`` → UTF-8 байты.
   Сортировка ключей и компактные сепараторы дают единственное
   каноническое представление; ensure_ascii=False сохраняет юникод
   как есть (байты UTF-8 детерминированы).
2. Лист: ``sha256(canonical_bytes).hexdigest()`` (64 hex-символа).
3. Родитель: ``sha256((left_hex + right_hex).encode("ascii")).hexdigest()``
   — конкатенация ДЕТЕЙ КАК HEX-СТРОК (не raw bytes), порядок строго
   left||right.
4. Нечётное число узлов на уровне → последний узел ДУБЛИРУЕТСЯ
   (правило Bitcoin-style): [a, b, c] хэшируется как [a, b, c, c].
5. Пустой день (0 событий) → честный ``root = None``. Никаких
   плейсхолдеров и «пустых хэшей» не выдумывается.

Принадлежность события дате: UTC ``timestamp`` события начинается с
``YYYY-MM-DD`` (audit_trail пишет ISO-8601 UTC). Читается основной
``audit_trail.jsonl`` И ротационные архивы ``audit_trail_*.jsonl``
(архивы первыми, в лексикографическом порядке = хронологическом),
т.к. ротация MP-310 может разнести события одного дня по двум файлам.
Битые строки/файлы молча пропускаются (fail-safe, как в MP-310).

Персист: ``data/proof_of_track_anchors.json`` — атомарная запись
(tmp + os.replace, паттерн capital_ladder/audit_trail), записи::

    {"date": "YYYY-MM-DD", "merkle_root": "<hex>|null", "leaf_count": N,
     "computed_at": "...+00:00", "published": false, "tx_hash": null,
     "note": "on-chain publication pending MP-017 RPC keys"}

Идемпотентность: повторный прогон того же дня с тем же root не
дублирует запись и не меняет её. Расхождение root → к note якоря
добавляется честная пометка discrepancy (один раз на каждый новый
конфликтующий root), исходный merkle_root сохраняется. Ротация
истории якорей ≤ 500 (старейшие вытесняются). Битый/отсутствующий
файл якорей толерантно трактуется как пустой.

CLI (offline, exit 0, без трейсбеков)::

    python3 -m spa_core.audit.proof_of_track --check [--date YYYY-MM-DD]
    python3 -m spa_core.audit.proof_of_track --run   [--date YYYY-MM-DD]
    python3 -m spa_core.audit.proof_of_track --verify <leaf_hash> [--date ...]

``--check`` вычисляет и печатает root, НИЧЕГО не пишет. ``--run``
вычисляет и атомарно персистит якорь. ``--verify`` строит
inclusion-proof для листа и проверяет его против root дня.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from spa_core.utils.atomic import atomic_save

ANCHORS_FILENAME = "proof_of_track_anchors.json"
AUDIT_FILENAME = "audit_trail.jsonl"      # как в audit_trail.py (MP-310)
ARCHIVE_GLOB = "audit_trail_*.jsonl"      # ротационные архивы MP-310
HISTORY_MAX = 500                          # ротация очереди якорей
PENDING_NOTE = "on-chain publication pending MP-017 RPC keys"
SCHEMA_VERSION = 1

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


# ─── Канонизация и листья (чистые функции) ───────────────────────────────────


def canonicalize_event(event: Any) -> str:
    """Каноническое детерминированное JSON-представление события.

    ``sort_keys=True`` + ``separators=(",", ":")`` + ``ensure_ascii=False``:
    одинаковые по содержимому dict'ы (включая event_id/correlation_id,
    если они есть) дают байт-в-байт одинаковую строку независимо от
    порядка вставки ключей. Чистая функция; для не-JSON-сериализуемых
    объектов честно поднимает TypeError (события audit trail приходят
    из ``json.loads`` и сериализуемы всегда).
    """
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def leaf_hash(event: Any) -> str:
    """sha256-лист события: sha256(canonical_utf8_bytes).hexdigest()."""
    return hashlib.sha256(canonicalize_event(event).encode("utf-8")).hexdigest()


def _parent_hash(left_hex: str, right_hex: str) -> str:
    """Родительский узел: sha256 от ASCII-конкатенации hex-строк детей."""
    return hashlib.sha256((left_hex + right_hex).encode("ascii")).hexdigest()


# ─── Merkle-дерево (чистые функции, pure stdlib) ─────────────────────────────


def merkle_levels(leaves: List[str]) -> List[List[str]]:
    """Все уровни дерева снизу вверх: ``[leaves, ..., [root]]``.

    Правило нечётного уровня — дублирование последнего узла (см.
    докстринг модуля, правило 4). Пустой ввод → ``[]``.
    """
    if not leaves:
        return []
    levels: List[List[str]] = [list(leaves)]
    while len(levels[-1]) > 1:
        current = levels[-1]
        if len(current) % 2 == 1:
            current = current + [current[-1]]  # дублируем последний
        nxt = [
            _parent_hash(current[i], current[i + 1])
            for i in range(0, len(current), 2)
        ]
        levels.append(nxt)
    return levels


def merkle_root(leaves: List[str]) -> Optional[str]:
    """Merkle root списка hex-листьев.

    * 0 листьев → честный ``None`` (пустой день не «выдумывается»);
    * 1 лист → root == сам лист;
    * нечётный уровень → последний узел дублируется.
    """
    levels = merkle_levels(leaves)
    if not levels:
        return None
    return levels[-1][0]


def generate_proof(leaf: str, leaves: List[str]) -> Optional[List[dict]]:
    """Inclusion-proof для ``leaf`` в дереве над ``leaves``. Чистая.

    Возвращает список шагов ``{"position": "left"|"right", "hash": hex}``
    снизу вверх (position — где стоит SIBLING относительно текущего
    узла), либо ``None``, если листа в наборе нет. Для дерева из одного
    листа доказательство — пустой список. При дубликатах листа берётся
    первое вхождение.
    """
    if leaf not in leaves:
        return None
    levels = merkle_levels(leaves)
    proof: List[dict] = []
    index = leaves.index(leaf)
    for level in levels[:-1]:
        padded = level + [level[-1]] if len(level) % 2 == 1 else level
        if index % 2 == 0:
            sibling = padded[index + 1]
            proof.append({"position": "right", "hash": sibling})
        else:
            sibling = padded[index - 1]
            proof.append({"position": "left", "hash": sibling})
        index //= 2
    return proof


def verify_proof(leaf: str, proof: List[dict], root: Optional[str]) -> bool:
    """Проверка inclusion-proof. Чистая функция, исключений не бросает.

    Складывает лист с сёстрами по шагам ``proof`` (правило 3 модуля)
    и сравнивает результат с ``root``. Любой мусор во входе → False.
    """
    if not isinstance(leaf, str) or not leaf or root is None:
        return False
    if not isinstance(proof, list):
        return False
    current = leaf
    for step in proof:
        if not isinstance(step, dict):
            return False
        sibling = step.get("hash")
        position = step.get("position")
        if not isinstance(sibling, str) or position not in ("left", "right"):
            return False
        if position == "left":
            current = _parent_hash(sibling, current)
        else:
            current = _parent_hash(current, sibling)
    return current == root


# ─── Чтение audit trail (read-only, fail-safe) ───────────────────────────────


def _get_data_dir(data_dir: Optional[str]) -> Path:
    return Path(data_dir) if data_dir else _DEFAULT_DATA_DIR


def _iter_trail_files(ddir: Path) -> List[Path]:
    """Файлы трека в детерминированном порядке: архивы (старые) → текущий."""
    archives = sorted(p for p in ddir.glob(ARCHIVE_GLOB) if p.is_file())
    current = ddir / AUDIT_FILENAME
    files = list(archives)
    if current.is_file():
        files.append(current)
    return files


def load_events_for_date(date: str, *, data_dir: Optional[str] = None) -> List[dict]:
    """Все события audit trail за UTC-дату ``date`` (YYYY-MM-DD).

    Событие принадлежит дате, если его ``timestamp`` начинается с
    ``date``. Порядок — порядок строк в файлах (архивы первыми) —
    детерминирован, т.к. JSONL append-only. Битые строки и нечитаемые
    файлы молча пропускаются (fail-safe, паттерн MP-310).
    """
    ddir = _get_data_dir(data_dir)
    events: List[dict] = []
    for path in _iter_trail_files(ddir):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    ts = record.get("timestamp")
                    if isinstance(ts, str) and ts.startswith(date):
                        events.append(record)
        except OSError:
            continue
    return events


def build_daily_root(date: str, *, data_dir: Optional[str] = None) -> dict:
    """Merkle root дня поверх событий audit trail за ``date``.

    Листья — sha256 канонизированных полных событий (включая
    event_id/correlation_id/snapshot_id/timestamp/data — всё, что
    записал MP-310). Возвращает::

        {"date", "merkle_root" (hex | None), "leaf_count", "leaves": [...]}

    Пустой день → ``merkle_root = None``, ``leaf_count = 0``.
    """
    _validate_date(date)
    events = load_events_for_date(date, data_dir=data_dir)
    leaves = [leaf_hash(ev) for ev in events]
    return {
        "date": date,
        "merkle_root": merkle_root(leaves),
        "leaf_count": len(leaves),
        "leaves": leaves,
    }


def _validate_date(date: str) -> None:
    """YYYY-MM-DD или ValueError (честная ошибка вместо тихого мусора)."""
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError(f"invalid date {date!r}, expected YYYY-MM-DD")


# ─── Персист очереди якорей (атомарно, идемпотентно) ─────────────────────────


def _anchors_path(data_dir: Optional[str]) -> Path:
    return _get_data_dir(data_dir) / ANCHORS_FILENAME


def load_anchors(*, data_dir: Optional[str] = None) -> dict:
    """Состояние очереди якорей; битый/отсутствующий файл → пустое."""
    path = _anchors_path(data_dir)
    empty = {"schema_version": SCHEMA_VERSION, "anchors": []}
    if not path.is_file():
        return empty
    try:
        with path.open("r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return empty
    if not isinstance(state, dict) or not isinstance(state.get("anchors"), list):
        return empty
    state["anchors"] = [a for a in state["anchors"] if isinstance(a, dict)]
    state.setdefault("schema_version", SCHEMA_VERSION)
    return state


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _new_anchor(date: str, root: Optional[str], leaf_count: int) -> dict:
    return {
        "date": date,
        "merkle_root": root,
        "leaf_count": leaf_count,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "published": False,           # on-chain публикация невозможна без MP-017
        "tx_hash": None,
        "note": PENDING_NOTE,
    }


def persist_daily_anchor(date: str, *, data_dir: Optional[str] = None) -> dict:
    """Вычислить root дня и идемпотентно заякорить его в очереди.

    Поведение:
    * якоря за ``date`` нет → добавить новую запись (published=false,
      tx_hash=null, note=pending MP-017), ротация ≤ HISTORY_MAX;
    * якорь есть и root совпадает → НИЧЕГО не менять (идемпотентность);
    * якорь есть и root НЕ совпадает → исходный merkle_root сохраняется,
      в note добавляется честная discrepancy-пометка (один раз на каждый
      новый конфликтующий root) — трек нельзя переписать задним числом.

    Возвращает ``{"status": "anchored"|"unchanged"|"discrepancy",
    "anchor": <запись>, "computed_root": ..., "leaf_count": ...}``.
    """
    result = build_daily_root(date, data_dir=data_dir)
    computed_root = result["merkle_root"]
    leaf_count = result["leaf_count"]

    state = load_anchors(data_dir=data_dir)
    anchors: List[dict] = state["anchors"]
    existing = next((a for a in anchors if a.get("date") == date), None)

    if existing is None:
        anchor = _new_anchor(date, computed_root, leaf_count)
        anchors.append(anchor)
        if len(anchors) > HISTORY_MAX:
            del anchors[: len(anchors) - HISTORY_MAX]
        status = "anchored"
    elif existing.get("merkle_root") == computed_root:
        # Идемпотентность: ни дубля, ни изменения записи.
        return {
            "status": "unchanged",
            "anchor": existing,
            "computed_root": computed_root,
            "leaf_count": leaf_count,
        }
    else:
        # Расхождение: старый root НЕ перезаписывается, фиксируем честно.
        marker = f"discrepancy: recomputed root {computed_root!r} != anchored root"
        note = existing.get("note") or ""
        if marker not in note:
            stamp = datetime.now(timezone.utc).isoformat()
            existing["note"] = f"{note}; {marker} at {stamp}".lstrip("; ")
        anchor = existing
        status = "discrepancy"

    state["anchors"] = anchors
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(_anchors_path(data_dir), state)
    return {
        "status": status,
        "anchor": existing if existing is not None else anchor,
        "computed_root": computed_root,
        "leaf_count": leaf_count,
    }


# ─── CLI (offline, advisory, exit 0, без трейсбеков) ─────────────────────────


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _print_day(result: dict) -> None:
    root = result["merkle_root"]
    print(f"proof_of_track: date={result['date']} leaf_count={result['leaf_count']} "
          f"merkle_root={root if root else 'None (empty day)'}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m spa_core.audit.proof_of_track",
        description=(
            "Proof-of-Track Merkle core (MP-406, OFFLINE): дневной Merkle root "
            "audit trail + очередь якорей pending on-chain publication "
            "(публикация — после MP-017). Advisory only."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="вычислить и напечатать root дня, НИЧЕГО не писать")
    mode.add_argument("--run", action="store_true",
                      help="вычислить root дня и атомарно заякорить в "
                           "data/proof_of_track_anchors.json")
    mode.add_argument("--verify", metavar="LEAF_HASH",
                      help="построить и проверить inclusion-proof для листа")
    parser.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                        help="дата (UTC), по умолчанию сегодня")
    parser.add_argument("--data-dir", default=None,
                        help="каталог data/ (по умолчанию <repo>/data)")
    args = parser.parse_args(argv)

    date = args.date or _today_utc()
    try:
        if args.verify:
            result = build_daily_root(date, data_dir=args.data_dir)
            leaves = result["leaves"]
            proof = generate_proof(args.verify, leaves)
            _print_day(result)
            if proof is None:
                print(f"proof_of_track: leaf {args.verify} NOT FOUND in {date} "
                      f"({result['leaf_count']} leaves)")
            else:
                ok = verify_proof(args.verify, proof, result["merkle_root"])
                print(f"proof_of_track: leaf {args.verify} proof_steps={len(proof)} "
                      f"verify={'VALID' if ok else 'INVALID'}")
        elif args.run:
            outcome = persist_daily_anchor(date, data_dir=args.data_dir)
            _print_day({"date": date,
                        "merkle_root": outcome["computed_root"],
                        "leaf_count": outcome["leaf_count"]})
            anchor = outcome["anchor"]
            print(f"proof_of_track: status={outcome['status']} "
                  f"anchored_root={anchor.get('merkle_root')} "
                  f"published={anchor.get('published')} tx_hash={anchor.get('tx_hash')}")
            print(f"proof_of_track: note={anchor.get('note')}")
        else:
            # --check (и режим по умолчанию): только вычислить и напечатать.
            result = build_daily_root(date, data_dir=args.data_dir)
            _print_day(result)
            print("proof_of_track: --check is read-only, nothing persisted "
                  "(advisory; on-chain publication pending MP-017)")
    except Exception as exc:  # advisory: никаких трейсбеков, exit 0
        print(f"proof_of_track: ERROR — {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
