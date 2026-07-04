"""
spa_core/academy/api/routes/quiz.py

Quiz delivery + grading for the Academy sub-application.

  GET  /quiz/{lesson_id}   — [auth]        questions WITHOUT correct answers
  POST /quiz/{lesson_id}   — [auth + csrf] grade answers, record the attempt

The correct answers live only in :mod:`spa_core.academy.content.quiz_bank` and
are NEVER serialised: GET returns ``{id, text, options}`` only, and the graded
POST response returns ``{score, passed, attempt_n, feedback}`` where feedback is
the pre-authored explanation strings — it never reveals a correct option index.

Grading does NOT move a user's progress. Progress (submitted/verified) is driven
solely by the verify router in a later stage; a passing quiz is recorded as an
attempt and surfaced, but the lesson is only completed through verification. M8
has an empty bank → :func:`grade_answers` auto-passes (score 100).

LLM FORBIDDEN in this module (deterministic delivery + grading).
Academy stage 4.
"""

from __future__ import annotations

import json
import sqlite3
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Query
from pydantic import BaseModel

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events
from spa_core.academy.content import quiz_bank
from spa_core.academy.api.deps import get_current_user, get_db, require_csrf

router = APIRouter(prefix="/quiz", tags=["academy-quiz"])


class QuizAnswers(BaseModel):
    answers: List[int]


def _client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    client = request.client
    return client.host if client else "unknown"


@router.get("/{lesson_id}")
def get_quiz(
    lesson_id: int = Path(..., ge=0, le=8),
    lang: str = Query("ru"),
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    """Return the module's questions without any server-side answer fields."""
    questions = quiz_bank.get_questions(lesson_id, lang=lang)
    return {"lesson_id": lesson_id, "questions": questions}


@router.post("/{lesson_id}")
def submit_quiz(
    body: QuizAnswers,
    request: Request,
    lesson_id: int = Path(..., ge=0, le=8),
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    """Grade the submitted answers, record the attempt, return the result."""
    result = quiz_bank.grade_answers(lesson_id, body.answers)
    uid = current_user["id"]

    answers_json = json.dumps(list(body.answers), separators=(",", ":"))
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(attempt_n), 0) AS n FROM quiz_results "
            "WHERE user_id = ? AND lesson_id = ?",
            (uid, lesson_id),
        ).fetchone()
        attempt_n = int(row["n"]) + 1
        conn.execute(
            "INSERT INTO quiz_results(user_id, lesson_id, score, answers_json, attempt_n) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid, lesson_id, result["score"], answers_json, attempt_n),
        )

    events.log_event(
        db,
        "quiz_submit",
        user_id=uid,
        payload={
            "lesson_id": lesson_id,
            "attempt_n": attempt_n,
            "score": result["score"],
            "passed": result["passed"],
        },
        ip=_client_ip(request),
    )
    # NOTE: passing the quiz does NOT advance progress — verification does.
    return {
        "ok": True,
        "lesson_id": lesson_id,
        "score": result["score"],
        "passed": result["passed"],
        "attempt_n": attempt_n,
        "feedback": result["feedback"],
    }
