"""Privacy-conscious operational events used for dissertation reliability evidence."""

import hashlib
import json
import time
import uuid

from flask import current_app, g, request, session

from database import get_db


ENDPOINT_EVENT_TYPES = {
    "auth.login": "login",
    "auth.logout": "logout",
    "subjects.subject_detail": "subject_opened",
    "learning.pathway": "topic_or_pathway_opened",
    "learning.outcome": "learning_outcome_opened",
    "learning.submit_reflection": "reflection_submitted",
    "learning.submit_practical_evidence": "practical_evidence_submitted",
    "learning.submit_activity": "activity_evidence_submitted",
    "learning.submit_assessment": "assessment_submitted",
    "teacher.review_activity_submission": "teacher_feedback_given",
    "teacher.review_recommendation": "teacher_intervention_recorded",
    "teacher.mastery_decision": "mastery_reviewed",
    "offline.update_sync_queue": "offline_synchronization_attempted",
}

EXCLUDED_ENDPOINTS = {"static", "health", "version", "service_worker"}


def _session_identifier():
    identifier = session.get("research_session_identifier")
    if not identifier:
        identifier = uuid.uuid4().hex
        session["research_session_identifier"] = identifier
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:24]


def start_request_tracking():
    g.request_reference = uuid.uuid4().hex[:12].upper()
    g.request_started_at = time.perf_counter()
    g.request_actor_id = session.get("user_id")
    g.request_actor_role = session.get("role")
    g.request_session_identifier = (
        None if (request.endpoint or "unknown") in EXCLUDED_ENDPOINTS else _session_identifier()
    )
    g.request_error_category = None


def classify_request_event():
    endpoint = request.endpoint or "unknown"
    if endpoint in ENDPOINT_EVENT_TYPES:
        event_type = ENDPOINT_EVENT_TYPES[endpoint]
        if endpoint == "learning.submit_assessment":
            event_type = "assessment_submitted"
        return event_type
    if request.path.startswith("/research/export/"):
        return "export_generated"
    if request.path.startswith("/research/"):
        return "research_page_opened"
    return "page_request"


def request_entity():
    values = request.view_args or {}
    for key in (
        "outcome_id", "assessment_id", "questionnaire_id", "participant_id",
        "recommendation_id", "learner_id", "activity_id",
    ):
        if key in values:
            return key.removesuffix("_id"), str(values[key])
    return "endpoint", request.endpoint or request.path


def record_research_event(
    event_type,
    *,
    actor_id=None,
    actor_role=None,
    entity_type=None,
    entity_id=None,
    response_time_ms=None,
    event_status="Success",
    metadata=None,
    error_category=None,
    offline_status="Online",
    session_identifier=None,
):
    """Best-effort event recording that never exposes form data or credentials."""
    conn = None
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO research_events (
                actor_id, actor_role, event_type, entity_type, entity_id,
                session_identifier, response_time_ms, event_status,
                metadata_json, error_category, offline_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            actor_id,
            actor_role,
            event_type,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            session_identifier,
            response_time_ms,
            event_status,
            json.dumps(metadata or {}, separators=(",", ":"), sort_keys=True),
            error_category,
            offline_status,
        ))
        conn.commit()
    except Exception as exc:  # Logging must not break the learner journey.
        current_app.logger.warning(
            "research_event_record_failed event_type=%s exception_type=%s request_reference=%s",
            event_type,
            type(exc).__name__,
            getattr(g, "request_reference", "unavailable"),
        )
    finally:
        if conn is not None:
            conn.close()


def finish_request_tracking(response):
    endpoint = request.endpoint or "unknown"
    reference = getattr(g, "request_reference", uuid.uuid4().hex[:12].upper())
    response.headers["X-Request-ID"] = reference
    if endpoint in EXCLUDED_ENDPOINTS:
        return response

    started = getattr(g, "request_started_at", time.perf_counter())
    response_time_ms = round((time.perf_counter() - started) * 1000, 2)
    actor_id = session.get("user_id") or getattr(g, "request_actor_id", None)
    actor_role = session.get("role") or getattr(g, "request_actor_role", None)
    entity_type, entity_id = request_entity()
    status = "Success" if response.status_code < 400 else "Failure"
    error_category = getattr(g, "request_error_category", None)
    event_type = "application_error" if response.status_code >= 500 else classify_request_event()
    record_research_event(
        event_type,
        actor_id=actor_id,
        actor_role=actor_role,
        entity_type=entity_type,
        entity_id=entity_id,
        response_time_ms=response_time_ms,
        event_status=status,
        metadata={
            "method": request.method,
            "path": request.path,
            "status_code": response.status_code,
            "request_reference": reference,
        },
        error_category=error_category,
        session_identifier=getattr(g, "request_session_identifier", None),
    )
    return response
