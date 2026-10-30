cd /private/tmp/spa_wt_autonomy_s1; cat >> spa_core/tests/test_goal_graph_s1_e2e3.py <<'EOF'


# ── E2.6 редакторы frontmatter на общем протоколе ───────────────────────────────────────────────
def _slow_editor(card, out):
    from spa_core.owner_queue import cockpit_loop as cl
    import time
    real = cl.atomic_save_text if hasattr(cl, "atomic_save_text") else None
    try:
        with q.card_write_lock(card):                                   # держим, как редактор между чтением и записью
            text = Path(card).read_text()
            time.sleep(0.6)
            Path(card).write_text(text.replace("title: t", "title: t\ndispatch: taken"))
        out.put("edited")
    except Exception as exc:  # noqa: BLE001
        out.put(f"err {exc}")
    del real


def _status_writer(card, out):
    import time
    time.sleep(0.2)                                                     # стартует, пока редактор держит карточку
    q.set_status(card, "in-progress")
    out.put("status")


def test_editor_and_set_status_in_two_processes_lose_no_update(tmp_path):
    card = tmp_path / "agent-z.md"
    card.write_text(_CARD)
    ctx = mp.get_context("fork")
    out = ctx.Queue()
    ps = [ctx.Process(target=_slow_editor, args=(str(card), out)),
          ctx.Process(target=_status_writer, args=(str(card), out))]
    for p in ps:
        p.start()
    for p in ps:
        p.join(30)
    assert sorted(out.get(timeout=5) for _ in ps) == ["edited", "status"]
    text = card.read_text()
    assert "dispatch: taken" in text and "status: in-progress" in text   # обе правки на месте


def test_nested_write_in_the_same_thread_does_not_deadlock(tmp_path):
    card = tmp_path / "agent-n.md"
    card.write_text(_CARD)
    with q.card_write_lock(card):
        q.set_status(card, "in-progress")                               # вложенный писатель
    assert "status: in-progress" in card.read_text()


def test_every_mapped_card_editor_carries_the_shared_lock():
    import inspect
    from spa_core.owner_queue import cockpit_loop, intake, owner_answer
    from spa_core.telegram import owner_decisions
    for fn in (cockpit_loop._set_fields, intake._stamp_seen, owner_answer._write_answer,
               owner_decisions.refresh_live_copy_from_ref):
        assert getattr(fn, "__card_writer__", False), fn.__name__
    assert "card_write_lock(target)" in inspect.getsource(owner_decisions.materialize_card)
    src = (REPO / "scripts" / "check_card_claim.py").read_text(encoding="utf-8")
    assert "with card_write_lock(path):" in src
    assert "_card_write_lock(path, expected_revision)" in inspect.getsource(q.set_status)
EOF
SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_goal_graph_s1_e2e3.py -q -p no:randomly --tb=short 2>&1 | grep -E "^E |FAILED|passed|failed" | head