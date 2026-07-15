"""Files-first card queue — parse / list / mutate Nimbalyst-native tracker cards.

stdlib-only, deterministic. Cards live as markdown with YAML-ish frontmatter in
``nimbalyst-local/tracker/*.md``. We intentionally hand-parse the small, controlled
frontmatter (no external YAML dependency — runtime is stdlib-only per repo invariant).

Card frontmatter shape (see .nimbalyst/trackers/owner-decision.yaml)::

    ---
    trackerStatus:
      type: owner-decision        # or: inbox
    title: ...
    status: needs-owner           # needs-owner | owner-done | ingested (owner-decision)
    priority: medium
    owner: someone@example.com
    ...
    ---
    <markdown body>
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from spa_core.utils.atomic import atomic_save_text

# Repo-root-relative canonical location of the files-first queue.
_REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKER_DIR = Path(os.environ.get("SPA_TRACKER_DIR", _REPO_ROOT / "nimbalyst-local" / "tracker"))

# Owner-only terminal status the agent must never set (CLAUDE.md invariant #14).
OWNER_ONLY_STATUS = "owner-done"


class OwnerDoneForbidden(RuntimeError):
    """Raised when code attempts to set a card to ``owner-done`` (owner-only)."""


@dataclass
class Card:
    path: Path
    tracker_type: str = ""          # trackerStatus.type
    title: str = ""
    status: str = ""
    priority: str = ""
    owner: str = ""
    legacy_id: str = ""
    fields: dict = field(default_factory=dict)  # all other top-level frontmatter keys
    body: str = ""

    @property
    def id(self) -> str:
        return self.path.stem


def _split_frontmatter(text: str) -> tuple[list[str], str]:
    """Return (frontmatter_lines, body). Empty frontmatter list if none present."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm = lines[1:i]
            body = "\n".join(lines[i + 1:])
            return fm, body
    return [], text  # unterminated frontmatter → treat as no frontmatter


def _unquote(val: str) -> str:
    """Strip matching surrounding quotes and unescape (mirrors _yaml_escape)."""
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        inner = val[1:-1]
        if val[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return val


def _parse_frontmatter(fm_lines: list[str]) -> dict:
    """Minimal parser: top-level ``key: value`` plus one nested block ``trackerStatus.type``."""
    out: dict = {}
    current_block: str | None = None
    for raw in fm_lines:
        if not raw.strip():
            continue
        indented = raw[:1].isspace()
        stripped = raw.strip()
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = _unquote(val.strip())
        if not indented:
            if val == "":
                # start of a nested block (e.g. ``trackerStatus:``)
                current_block = key
                out.setdefault(key, {})
            else:
                current_block = None
                out[key] = val
        else:
            # nested line under current_block
            if current_block:
                if not isinstance(out.get(current_block), dict):
                    out[current_block] = {}
                out[current_block][key] = val
    return out


def load_card(path: str | Path) -> Card:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    fm_lines, body = _split_frontmatter(text)
    fm = _parse_frontmatter(fm_lines)
    tracker_status = fm.get("trackerStatus")
    tracker_type = ""
    if isinstance(tracker_status, dict):
        tracker_type = str(tracker_status.get("type", ""))
    top = {k: v for k, v in fm.items() if k != "trackerStatus" and not isinstance(v, dict)}
    return Card(
        path=p,
        tracker_type=tracker_type,
        title=str(top.get("title", "")),
        status=str(top.get("status", "")),
        priority=str(top.get("priority", "")),
        owner=str(top.get("owner", "")),
        legacy_id=str(top.get("legacy_id", "")),
        fields=top,
        body=body,
    )


def list_cards(
    tracker_type: str | None = None,
    status: str | None = None,
    tracker_dir: str | Path | None = None,
) -> list[Card]:
    """List cards, optionally filtered by trackerStatus.type and/or status."""
    d = Path(tracker_dir) if tracker_dir is not None else TRACKER_DIR
    if not d.exists():
        return []
    cards: list[Card] = []
    for p in sorted(d.glob("*.md")):
        try:
            c = load_card(p)
        except Exception:
            continue  # a malformed file must not break the whole scan (fail-open per-file)
        if tracker_type is not None and c.tracker_type != tracker_type:
            continue
        if status is not None and c.status != status:
            continue
        cards.append(c)
    return cards


def set_status(path: str | Path, new_status: str) -> None:
    """Atomically rewrite the top-level ``status:`` in a card's frontmatter.

    Refuses ``owner-done`` (owner-only). Only the ``status:`` line changes; the rest of
    the file is preserved byte-for-byte modulo that one line.
    """
    if new_status == OWNER_ONLY_STATUS:
        raise OwnerDoneForbidden(
            "Agents may not set status 'owner-done' — that transition is owner-only "
            "(CLAUDE.md invariant #14). Allowed agent targets: ingested / in-progress / done / needs-owner."
        )
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    fm_lines, _ = _split_frontmatter(text)
    if not fm_lines:
        raise ValueError(f"{p}: no frontmatter to update")

    lines = text.splitlines(keepends=True)
    # Locate frontmatter bounds in the raw (keepends) line list.
    start = None
    end = None
    seen = 0
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            seen += 1
            if seen == 1:
                start = i
            elif seen == 2:
                end = i
                break
    if start is None or end is None:
        raise ValueError(f"{p}: could not locate frontmatter bounds")

    replaced = False
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if stripped.startswith("status:") and not lines[i][:1].isspace():
            newline = "\n" if lines[i].endswith("\n") else ""
            lines[i] = f"status: {new_status}{newline}"
            replaced = True
            break
    if not replaced:
        raise ValueError(f"{p}: no top-level 'status:' line found in frontmatter")

    atomic_save_text("".join(lines), str(p))


def first_instruction_line(card: Card) -> str:
    """First meaningful instruction line for a Telegram notification.

    Prefers the first non-empty line under an '## Инструкция' / '## Instruction' heading;
    falls back to the first non-empty body line; then to the title.
    """
    body_lines = card.body.splitlines()
    in_instr = False
    for ln in body_lines:
        low = ln.strip().lower()
        if ln.strip().startswith("##"):
            in_instr = (
                low.startswith("## что от тебя нужно")   # §2.4 (amended format)
                or low.startswith("## инструкц")          # legacy format
                or low.startswith("## instruction")
                or low.startswith("## what")
            )
            continue
        if in_instr and ln.strip():
            return ln.strip().lstrip("0123456789.-) ").strip() or ln.strip()
    for ln in body_lines:
        if ln.strip() and not ln.strip().startswith("#"):
            return ln.strip()
    return card.title


def iter_cards(cards: Iterable[Card]) -> Iterable[Card]:
    return cards


def _slug(text: str, maxlen: int = 40) -> str:
    """ASCII-safe slug for a filename; falls back to 'note' if empty (e.g. Cyrillic-only)."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:maxlen].strip("-")) or "note"


def _yaml_escape(value: str) -> str:
    """Quote a scalar for the frontmatter if it contains YAML-significant chars."""
    v = str(value)
    if v == "" or re.search(r"""[:#\[\]{}&*!|>'"%@`]|^\s|\s$""", v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def create_card(
    tracker_type: str,
    title: str,
    body: str = "",
    *,
    status: str | None = None,
    source: str | None = None,
    extra_fields: dict | None = None,
    tracker_dir: str | Path | None = None,
    now: datetime | None = None,
) -> Path:
    """Create a new tracker card as a `trackerStatus`-frontmatter markdown file.

    Deterministic given ``now`` (pass one in tests). Filename:
    ``<tracker_type>-<UTCstamp>-<slug>.md`` in ``tracker_dir`` (default TRACKER_DIR).
    Never sets ``owner-done`` (owner-only) — callers create in an open state.
    """
    if status == OWNER_ONLY_STATUS:
        raise OwnerDoneForbidden("create_card must not set 'owner-done' (owner-only, invariant #14).")
    d = Path(tracker_dir) if tracker_dir is not None else TRACKER_DIR
    d.mkdir(parents=True, exist_ok=True)
    dt = now or datetime.now(timezone.utc)
    stamp = dt.strftime("%Y%m%d-%H%M%S")
    date_str = dt.strftime("%Y-%m-%d")

    base = f"{tracker_type}-{stamp}-{_slug(title)}"
    path = d / f"{base}.md"
    n = 1
    while path.exists():  # collision guard (same-second cards)
        path = d / f"{base}-{n}.md"
        n += 1

    lines = ["---", "trackerStatus:", f"  type: {tracker_type}", f"title: {_yaml_escape(title)}"]
    if status:
        lines.append(f"status: {status}")
    if source:
        lines.append(f"source: {source}")
    lines.append(f"created: {date_str}")
    for k, v in (extra_fields or {}).items():
        lines.append(f"{k}: {_yaml_escape(str(v))}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip("\n") if body else "")
    lines.append("")

    atomic_save_text("\n".join(lines), str(path))
    return path


# Repo-root inbox/ folder for loose Obsidian notes (Этап 6, path 2).
INBOX_NOTES_DIR = Path(os.environ.get("SPA_INBOX_NOTES_DIR", _REPO_ROOT / "inbox"))

# Knowledge-base dirs scanned for the owner's `#promote` tag (Этап 7.3).
PROMOTE_DIRS = (_REPO_ROOT / "docs" / "ideas", _REPO_ROOT / "docs" / "rules-draft")
# `#promote` as a whole tag, but NOT the already-processed `#promoted...`.
_PROMOTE_RE = re.compile(r"(?<![\w#])#promote(?![\w-])", re.IGNORECASE)


@dataclass
class Promotion:
    path: Path
    title: str
    snippet: str


def scan_promotions(dirs: Iterable[str | Path] | None = None) -> list[Promotion]:
    """Find notes tagged ``#promote`` in docs/ideas/ and docs/rules-draft/.

    Returns items the orchestrator must convert into a rule (.claude/rules / CLAUDE.md),
    an ADR (docs/decisions/), or a task card — then mark the source ``#promoted``
    (per docs/ORCHESTRATOR_PROTOCOL.md §Promotion). ``#promoted`` is NOT matched.
    """
    scan = [Path(d) for d in dirs] if dirs is not None else list(PROMOTE_DIRS)
    out: list[Promotion] = []
    for d in scan:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.md")):
            if p.name.lower() == "readme.md":
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            if not _PROMOTE_RE.search(text):
                continue
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            title = next((ln.lstrip("# ").strip() for ln in lines), p.stem)
            snippet = next((ln for ln in lines if _PROMOTE_RE.search(ln)), title)
            out.append(Promotion(path=p, title=title, snippet=snippet[:200]))
    return out


def ingest_notes(
    notes_dir: str | Path | None = None,
    tracker_dir: str | Path | None = None,
    now: datetime | None = None,
) -> list[Path]:
    """Convert loose Obsidian notes in ``notes_dir`` into Inbox cards.

    Each ``*.md`` / ``*.txt`` note (excluding README and the archive) becomes an
    ``inbox`` card (source=obsidian), then the original is moved to
    ``<notes_dir>/.ingested/`` so it is not processed twice. Returns created card paths.
    """
    d = Path(notes_dir) if notes_dir is not None else INBOX_NOTES_DIR
    if not d.exists():
        return []
    archive = d / ".ingested"
    created: list[Path] = []
    for p in sorted(list(d.glob("*.md")) + list(d.glob("*.txt"))):
        if p.name.lower() in ("readme.md", "readme.txt"):
            continue
        try:
            content = p.read_text(encoding="utf-8").strip()
            if not content:
                continue
            # If the note already has trackerStatus frontmatter, skip (it's a card, not a note).
            if content.startswith("---") and "trackerStatus" in content[:200]:
                continue
            title = next((ln.strip().lstrip("# ").strip() for ln in content.splitlines() if ln.strip()), p.stem)
            body = "\n".join([
                "## Задание (заметка Obsidian)", "", content, "",
                "---",
                "_Оркестратор: классифицируй (задача/идея/непонятно), закрой карточку со ссылкой на "
                "порождённую работу (§6.4)._",
            ])
            card = create_card("inbox", title, body, status="new", source="obsidian",
                               tracker_dir=tracker_dir, now=now)
            created.append(card)
            archive.mkdir(parents=True, exist_ok=True)
            p.replace(archive / p.name)
        except Exception:
            continue  # one bad note must not block the rest (fail-open per-file)
    return created
