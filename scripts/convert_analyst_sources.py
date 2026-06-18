#!/usr/bin/env python3
"""convert_analyst_sources.py — конвертация аналитических материалов в Markdown.

Поддерживает: PDF, DOCX, XLSX, PPTX, HTML, CSV, YouTube URL, изображения.
Требует: pip install 'markitdown[all]'

Использование:
  python3 scripts/convert_analyst_sources.py <файл_или_url> [файл2 ...]
  python3 scripts/convert_analyst_sources.py --dir ~/Downloads/reports/
  python3 scripts/convert_analyst_sources.py https://youtube.com/watch?v=...

Результат сохраняется в docs/analyst_sources/<имя_файла>.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OUTPUT_DIR = _REPO_ROOT / "docs" / "analyst_sources"
_LOG_FILE = _OUTPUT_DIR / "_conversion_log.json"

_SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".xlsm",
    ".pptx", ".ppt", ".html", ".htm", ".csv", ".txt",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp",
    ".mp3", ".wav",  # audio transcription if markitdown supports
}


def _ensure_markitdown():
    try:
        from markitdown import MarkItDown  # noqa: F401
    except ImportError:
        print("❌  markitdown не установлен. Установи:")
        print("    pip install 'markitdown[all]'")
        sys.exit(1)


def _is_youtube_url(src: str) -> bool:
    return any(d in src for d in ("youtube.com/watch", "youtu.be/", "youtube.com/shorts"))


def _safe_stem(src: str) -> str:
    """Derive a safe filename stem from a path or URL."""
    if src.startswith("http"):
        # Для YouTube — вытаскиваем video id
        for part in src.split("?")[1].split("&") if "?" in src else []:
            if part.startswith("v="):
                return "youtube_" + part[2:12]
        return "youtube_" + src.split("/")[-1][:20]
    return Path(src).stem


def _convert_one(src: str, md: object, output_dir: Path) -> dict:
    """Convert one source → .md file. Returns log entry."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stem = _safe_stem(src)
    out_path = output_dir / f"{stem}.md"

    # Avoid overwriting — add suffix
    counter = 1
    while out_path.exists():
        out_path = output_dir / f"{stem}_{counter}.md"
        counter += 1

    try:
        result = md.convert(src)
        content = result.text_content or ""
        if not content.strip():
            return {"source": src, "status": "empty", "ts": ts, "output": None}

        # Write with header
        header = textwrap.dedent(f"""\
            ---
            source: {src}
            converted: {ts}
            chars: {len(content)}
            ---

        """)
        out_path.write_text(header + content, encoding="utf-8")
        print(f"  ✅  {Path(src).name if not src.startswith('http') else src[:60]}")
        print(f"      → {out_path.relative_to(_REPO_ROOT)}")
        return {"source": src, "status": "ok", "ts": ts, "output": str(out_path), "chars": len(content)}

    except Exception as exc:  # noqa: BLE001
        print(f"  ❌  {src}: {exc}")
        return {"source": src, "status": f"error: {exc}", "ts": ts, "output": None}


def _update_log(entries: list[dict]) -> None:
    existing: list = []
    if _LOG_FILE.exists():
        try:
            existing = json.loads(_LOG_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing = []
    combined = existing + entries
    _LOG_FILE.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    _ensure_markitdown()
    from markitdown import MarkItDown

    parser = argparse.ArgumentParser(
        prog="convert_analyst_sources",
        description="Конвертация PDF/DOCX/XLSX/YouTube → Markdown в docs/analyst_sources/",
    )
    parser.add_argument(
        "sources",
        nargs="*",
        metavar="FILE_OR_URL",
        help="Файлы или URL для конвертации",
    )
    parser.add_argument(
        "--dir",
        metavar="DIR",
        help="Конвертировать все поддерживаемые файлы из папки",
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=str(_OUTPUT_DIR),
        help=f"Папка для результатов (по умолчанию: {_OUTPUT_DIR.relative_to(_REPO_ROOT)})",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    sources: list[str] = list(args.sources)

    if args.dir:
        d = Path(args.dir).expanduser()
        if not d.is_dir():
            print(f"❌  --dir: папка не найдена: {d}")
            sys.exit(1)
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in _SUPPORTED_EXTENSIONS:
                sources.append(str(f))

    if not sources:
        print("Использование:")
        print("  python3 scripts/convert_analyst_sources.py report.pdf")
        print("  python3 scripts/convert_analyst_sources.py https://youtube.com/watch?v=xxx")
        print("  python3 scripts/convert_analyst_sources.py --dir ~/Downloads/reports/")
        sys.exit(0)

    md = MarkItDown()
    print(f"\n📂  Результаты → {output_dir.relative_to(_REPO_ROOT)}\n")

    log_entries: list[dict] = []
    for src in sources:
        entry = _convert_one(src, md, output_dir)
        log_entries.append(entry)

    _update_log(log_entries)

    ok = sum(1 for e in log_entries if e["status"] == "ok")
    total = len(log_entries)
    print(f"\n📊  Готово: {ok}/{total} файлов сконвертировано")
    print(f"📝  Лог: {_LOG_FILE.relative_to(_REPO_ROOT)}\n")


if __name__ == "__main__":
    main()
