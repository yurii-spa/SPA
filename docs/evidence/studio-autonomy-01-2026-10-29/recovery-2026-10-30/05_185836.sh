cd /private/tmp/spa_wt_autonomy_s1; python3 - <<'EOF'
from pathlib import Path
p=Path("spa_core/owner_queue/queue.py"); s=p.read_text()
old='''@__import__("contextlib").contextmanager
def _card_write_lock(path: str | Path, expected_revision: str | None):
    import fcntl as _fcntl
    with open(_card_lock_path(Path(path)), "a+") as _lk:
        _fcntl.flock(_lk.fileno(), _fcntl.LOCK_EX)
        try:
            if expected_revision is not None and card_revision(path) != expected_revision:
                raise StaleCardRevision(
                    f"{Path(path).name}: карточка изменилась после чтения (ожидалась ревизия "
                    f"{expected_revision[:12]}) — запись статуса не сделана, перечитайте карточку")
            yield
        finally:
            _fcntl.flock(_lk.fileno(), _fcntl.LOCK_UN)
'''
new='''#: Блокировки карточек, которые ЭТОТ поток уже держит: вложенный писатель (например
#: ``set_status`` внутри заблокированного редактора) не ждёт сам себя.
_HELD_CARD_LOCKS = __import__("threading").local()


@__import__("contextlib").contextmanager
def _card_write_lock(path: str | Path, expected_revision: str | None):
    import fcntl as _fcntl
    key = str(_card_lock_path(Path(path)))
    held = getattr(_HELD_CARD_LOCKS, "keys", None)
    if held is None:
        held = _HELD_CARD_LOCKS.keys = {}
    if held.get(key):
        held[key] += 1
        try:
            if expected_revision is not None and card_revision(path) != expected_revision:
                raise StaleCardRevision(f"{Path(path).name}: карточка изменилась после чтения")
            yield
        finally:
            held[key] -= 1
        return
    with open(key, "a+") as _lk:
        _fcntl.flock(_lk.fileno(), _fcntl.LOCK_EX)
        held[key] = 1
        try:
            if expected_revision is not None and card_revision(path) != expected_revision:
                raise StaleCardRevision(
                    f"{Path(path).name}: карточка изменилась после чтения (ожидалась ревизия "
                    f"{expected_revision[:12]}) — запись статуса не сделана, перечитайте карточку")
            yield
        finally:
            held[key] = 0
            _fcntl.flock(_lk.fileno(), _fcntl.LOCK_UN)


def card_write_lock(path: str | Path):
    """Общая блокировка записи карточки (E2.2/E2.6) для редакторов frontmatter вне ``set_status``."""
    return _card_write_lock(path, None)


def card_writer(fn):
    """Декоратор: функция-писатель карточки (первый аргумент — путь) держит общую блокировку."""
    import functools as _functools

    @_functools.wraps(fn)
    def _wrapped(path, *args, **kwargs):
        with _card_write_lock(path, None):
            return fn(path, *args, **kwargs)
    _wrapped.__card_writer__ = True
    return _wrapped
'''
assert s.count(old)==1; s=s.replace(old,new,1); p.write_text(s)
EOF
grep -n "def _set_fields\|def _stamp_seen\|def _write_answer\|def materialize_card\|def refresh_live_copy_from_ref" spa_core/owner_queue/cockpit_loop.py spa_core/owner_queue/intake.py spa_core/owner_queue/owner_answer.py spa_core/telegram/owner_decisions.py; grep -n "def _set_claim_fields\|^import\|^from\|sys.path" scripts/check_card_claim.py | head -12