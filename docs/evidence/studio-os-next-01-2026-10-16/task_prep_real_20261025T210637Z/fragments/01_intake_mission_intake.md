# Excerpt: spa_core/studio_os/mission_intake.py lines 1-39 (at 9a07f8998, unchanged)

"""spa_core/studio_os/mission_intake.py — the ONE write action of the owner cockpit (ADR-760).

Owner 15.10: «голосовой ввод с телефона — огромный плюс». The cockpit stays read-only for
everything else; this module is the only place a cockpit request may write, and it may write
exactly one thing: a NEW inbox card through the SAME intake path the Telegram ``/task`` and voice
messages use (``spa_core.telegram.inbox_intake.save_inbox_task`` → ``owner_queue.create_card``,
status ``new``). It never executes, approves, answers, moves money or touches any other file.

Two operations, each guarded by :class:`IntakeGate` (the server calls ``gate.check`` first):

* ``transcribe(audio_bytes, content_type)`` — the SAME local offline whisper the Telegram bot uses
  (``inbox_intake.transcribe_voice``); audio ≤ ``MAX_AUDIO_BYTES`` and ≤ ``MAX_AUDIO_SECONDS``
  (measured by ``ffprobe`` when present; absent ⇒ the duration is «не измерена» and only the size
  limit applies — said in the answer, never silently). Whisper absent ⇒ a NAMED refusal
  ``WHISPER_UNAVAILABLE``, never an empty transcript.
* ``submit(text, kind, transcript; provenance)`` — one inbox card; ``kind`` ∈ idea/task/note.
  ``submission_id`` (made by the page when the composer opens, kept across retries) makes the
  write IDEMPOTENT: a card already carrying that id (any status) is returned with
  ``duplicate: true`` instead of a second card. The check-and-write runs under one lock
  (an in-process lock + ``flock`` on the tracker directory itself — no marker file is written).
  With an id, idempotency is by that id ONLY: a NEW composer session (new id) with identical text is
  a deliberate second note and becomes a second card (the open-twin merge of ``create_card`` is
  bypassed); without an id (an old page) the open-twin guard stays.
  Every cockpit card records its PROVENANCE as three separate things (ARB 16.10, :class:`Provenance`):
  the channel of arrival, the ESTABLISHED author (only from a server-side verified identity — never a
  client-supplied field) and the fixed authority-boundary line :data:`AUTHORITY_NOTE` (ADR-285), which
  never names the author: a record is never a permission, whoever wrote it.

Whisper outcomes are NOT collapsed (inv. #17): timeout ⇒ 504 ``WHISPER_TIMEOUT``, the process failed
⇒ 503 ``WHISPER_FAILED``, nothing heard ⇒ 422 ``EMPTY_TRANSCRIPT``, a transcription already running
⇒ 429 ``WHISPER_BUSY`` (one whisper at a time — ``_WHISPER_SLOT``).

Guards (fail-CLOSED; any doubt ⇒ refusal, nothing written):
  * a per-process CSRF token (``csrf_token()``; the page fetches it with a same-origin GET — a
    cross-site page cannot read it) must be echoed in ``X-Intake-Token``;
  * ``Origin`` must equal the listener's own origin (loopback for the local listener, the
    Access-protected public host for the public one); missing ⇒ refused;
  * the body type must match the operation; size limits; a small rate limit per operation.
"""
