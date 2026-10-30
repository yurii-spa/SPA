cd /private/tmp/spa_wt_autonomy_s1; python3 - <<'EOF'
from pathlib import Path
import re
def edit(path, pairs):
    p=Path(path); s=p.read_text()
    for old,new in pairs:
        assert s.count(old)==1,(path,old[:60]); s=s.replace(old,new,1)
    p.write_text(s)
M="# STUDIO-AUTONOMY-01 E2.6 (ADR-857): общий протокол записи карточки — та же блокировка, что у set_status.\n"
edit("spa_core/owner_queue/cockpit_loop.py",[("def _set_fields(path: Path, fields: dict) -> None:",
  M+"@__import__(\"spa_core.owner_queue.queue\", fromlist=[\"card_writer\"]).card_writer\ndef _set_fields(path: Path, fields: dict) -> None:")])
edit("spa_core/owner_queue/intake.py",[("def _stamp_seen(path, at: datetime) -> None:",
  M+"@__import__(\"spa_core.owner_queue.queue\", fromlist=[\"card_writer\"]).card_writer\ndef _stamp_seen(path, at: datetime) -> None:")])
edit("spa_core/owner_queue/owner_answer.py",[("def _write_answer(path, *, choice_num: str,",
  M+"@__import__(\"spa_core.owner_queue.queue\", fromlist=[\"card_writer\"]).card_writer\ndef _write_answer(path, *, choice_num: str,")])
edit("spa_core/telegram/owner_decisions.py",[
 ("def refresh_live_copy_from_ref(card_path: str | Path, *,",
  M+"@__import__(\"spa_core.owner_queue.queue\", fromlist=[\"card_writer\"]).card_writer\ndef refresh_live_copy_from_ref(card_path: str | Path, *,"),
 ("        target_dir.mkdir(parents=True, exist_ok=True)\n        atomic_save_text(card_path.read_text(encoding=\"utf-8\"), str(target))\n        return target",
  "        target_dir.mkdir(parents=True, exist_ok=True)\n        from spa_core.owner_queue.queue import card_write_lock\n        with card_write_lock(target):  # E2.6: общий протокол записи карточки\n            if not target.exists():\n                atomic_save_text(card_path.read_text(encoding=\"utf-8\"), str(target))\n        return target")])
edit("scripts/check_card_claim.py",[("def _atomic_write(path: Path, content: str) -> None:\n    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=\".tmp\")",
 "def _atomic_write(path: Path, content: str) -> None:\n    # STUDIO-AUTONOMY-01 E2.6 (ADR-857): та же блокировка карточки, что у queue.set_status. Модуль\n    # недоступен (скрипт вне репозитория) ⇒ запись без неё, и это сказано в stderr, а не молча.\n    try:\n        from spa_core.owner_queue.queue import card_write_lock\n    except ImportError:\n        print(f\"WARNING: общий протокол записи карточки недоступен — {path.name} пишется без блокировки\",\n              file=sys.stderr)\n        return _atomic_write_unlocked(path, content)\n    with card_write_lock(path):\n        return _atomic_write_unlocked(path, content)\n\n\ndef _atomic_write_unlocked(path: Path, content: str) -> None:\n    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=\".tmp\")")])
EOF
python3 -c "import sys;sys.path.insert(0,'.');import spa_core.telegram.owner_decisions, spa_core.owner_queue.intake, spa_core.owner_queue.cockpit_loop;print('import ok')"