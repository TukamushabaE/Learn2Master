import json
from pathlib import Path

from database import get_db, is_postgres_connection


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "evaluation_dataset5.json"
SUPPLIED_LABEL = "Recorded Learn2Master Evaluation Data"
SUPPLIED_CLASSIFICATION = "USER_SUPPLIED_RESEARCH_DATA"
SUPPLIED_AUTHENTICITY = "NOT_INDEPENDENTLY_VERIFIED"
SUPPLIED_DISCLAIMER = (
    "These participant reference records are the recorded Learn2Master evaluation dataset. "
    "The portal preserves the source values and keeps participant identities protected; "
    "dates or approvals that are absent from the source are not inferred."
)


def _table_sql(postgres=False):
    primary_key = "SERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return f"""
        CREATE TABLE IF NOT EXISTS evaluation_dataset_records (
            evaluation_record_id {primary_key},
            record_type TEXT NOT NULL CHECK (record_type IN ('learner', 'teacher')),
            participant_code TEXT NOT NULL,
            school_code TEXT,
            subject TEXT,
            class_level TEXT,
            study_status TEXT,
            pre_test_pct REAL,
            post_test_pct REAL,
            gain_points REAL,
            acceptance_mean REAL,
            mastery_status TEXT,
            payload_json TEXT NOT NULL,
            data_classification TEXT NOT NULL DEFAULT 'USER_SUPPLIED_RESEARCH_DATA',
            authenticity_status TEXT NOT NULL DEFAULT 'NOT_INDEPENDENTLY_VERIFIED',
            source_label TEXT NOT NULL,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (record_type, participant_code, source_label)
        )
    """


def _reliability_table_sql(postgres=False):
    primary_key = "SERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return f"""
        CREATE TABLE IF NOT EXISTS evaluation_reliability_records (
            reliability_record_id {primary_key},
            event_date TEXT NOT NULL,
            total_events INTEGER NOT NULL,
            successful_events INTEGER NOT NULL,
            error_events INTEGER NOT NULL,
            success_rate_pct REAL,
            average_latency_ms REAL,
            p95_latency_ms REAL,
            offline_queued_events INTEGER,
            successful_sync_events INTEGER,
            incident_category TEXT,
            source_label TEXT NOT NULL,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (event_date, source_label)
        )
    """


def _themes_table_sql(postgres=False):
    primary_key = "SERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return f"""
        CREATE TABLE IF NOT EXISTS evaluation_qualitative_themes (
            theme_record_id {primary_key},
            respondent_group TEXT NOT NULL,
            coded_theme TEXT NOT NULL,
            mention_count INTEGER NOT NULL,
            interpretation TEXT,
            source_label TEXT NOT NULL,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (respondent_group, coded_theme, source_label)
        )
    """


def ensure_evaluation_dataset_schema(conn):
    postgres = is_postgres_connection(conn)
    conn.execute(_table_sql(postgres=postgres))
    conn.execute(_reliability_table_sql(postgres=postgres))
    conn.execute(_themes_table_sql(postgres=postgres))
    conn.commit()


def _as_float(value):
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def load_evaluation_dataset(path=None):
    source_path = Path(path) if path else DATA_PATH
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") or {}
    if metadata.get("data_classification") != SUPPLIED_CLASSIFICATION:
        raise ValueError(
            "Evaluation import rejected: the dataset must be explicitly classified "
            "as USER_SUPPLIED_RESEARCH_DATA."
        )
    if metadata.get("authenticity_status") != SUPPLIED_AUTHENTICITY:
        raise ValueError(
            "Evaluation import rejected: this pathway cannot mark supplied data as independently verified."
        )
    return payload


def _upsert_record(conn, record):
    conn.execute(
        """
        INSERT INTO evaluation_dataset_records
        (record_type, participant_code, school_code, subject, class_level, study_status,
         pre_test_pct, post_test_pct, gain_points, acceptance_mean, mastery_status,
         payload_json, data_classification, authenticity_status, source_label, imported_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (record_type, participant_code, source_label) DO UPDATE SET
            school_code=excluded.school_code,
            subject=excluded.subject,
            class_level=excluded.class_level,
            study_status=excluded.study_status,
            pre_test_pct=excluded.pre_test_pct,
            post_test_pct=excluded.post_test_pct,
            gain_points=excluded.gain_points,
            acceptance_mean=excluded.acceptance_mean,
            mastery_status=excluded.mastery_status,
            payload_json=excluded.payload_json,
            data_classification=excluded.data_classification,
            authenticity_status=excluded.authenticity_status,
            imported_at=CURRENT_TIMESTAMP
        """,
        (
            record["record_type"],
            record["participant_code"],
            record.get("school_code"),
            record.get("subject"),
            record.get("class_level"),
            record.get("study_status"),
            record.get("pre_test_pct"),
            record.get("post_test_pct"),
            record.get("gain_points"),
            record.get("acceptance_mean"),
            record.get("mastery_status"),
            json.dumps(record["payload"], ensure_ascii=False, separators=(",", ":")),
            record["data_classification"],
            record["authenticity_status"],
            record["source_label"],
        ),
    )


def _upsert_reliability_record(conn, row, source_label):
    conn.execute(
        """
        INSERT INTO evaluation_reliability_records
        (event_date, total_events, successful_events, error_events, success_rate_pct,
         average_latency_ms, p95_latency_ms, offline_queued_events,
         successful_sync_events, incident_category, source_label, imported_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (event_date, source_label) DO UPDATE SET
            total_events=excluded.total_events,
            successful_events=excluded.successful_events,
            error_events=excluded.error_events,
            success_rate_pct=excluded.success_rate_pct,
            average_latency_ms=excluded.average_latency_ms,
            p95_latency_ms=excluded.p95_latency_ms,
            offline_queued_events=excluded.offline_queued_events,
            successful_sync_events=excluded.successful_sync_events,
            incident_category=excluded.incident_category,
            imported_at=CURRENT_TIMESTAMP
        """,
        (
            row.get("date"), int(row.get("total_events") or 0),
            int(row.get("successful_events") or 0), int(row.get("error_events") or 0),
            _as_float(row.get("success_rate_pct")), _as_float(row.get("average_latency_ms")),
            _as_float(row.get("p95_latency_ms")), int(row.get("offline_queued_events") or 0),
            int(row.get("successful_sync_events") or 0), row.get("incident_category"),
            source_label,
        ),
    )


def _upsert_qualitative_theme(conn, row, source_label):
    conn.execute(
        """
        INSERT INTO evaluation_qualitative_themes
        (respondent_group, coded_theme, mention_count, interpretation, source_label, imported_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (respondent_group, coded_theme, source_label) DO UPDATE SET
            mention_count=excluded.mention_count,
            interpretation=excluded.interpretation,
            imported_at=CURRENT_TIMESTAMP
        """,
        (
            row.get("respondent_group"), row.get("coded_theme"),
            int(row.get("mention_count") or 0), row.get("interpretation"), source_label,
        ),
    )


def import_evaluation_dataset(conn=None, path=None):
    owns_connection = conn is None
    conn = conn or get_db()
    try:
        ensure_evaluation_dataset_schema(conn)
        dataset = load_evaluation_dataset(path)
        metadata = dataset["metadata"]
        source_label = metadata.get("source_label") or "evaluation_dataset5.json"

        classification = metadata["data_classification"]
        authenticity_status = metadata["authenticity_status"]
        learner_surveys = {
            row.get("participant_code"): row
            for row in dataset["learner_survey"]
            if row.get("participant_code")
        }

        learner_count = 0
        for learner in dataset["learner_study"]:
            participant_code = learner.get("participant_code")
            if not participant_code:
                continue
            learner_survey = learner_surveys.get(participant_code)
            _upsert_record(
                conn,
                {
                    "record_type": "learner",
                    "participant_code": participant_code,
                    "school_code": learner.get("school_code"),
                    "subject": learner.get("subject"),
                    "class_level": learner.get("class_level"),
                    "study_status": learner.get("study_status"),
                    "pre_test_pct": _as_float(learner.get("pre_test_pct")),
                    "post_test_pct": _as_float(learner.get("post_test_pct")),
                    "gain_points": _as_float(learner.get("gain_points")),
                    "acceptance_mean": _as_float((learner_survey or {}).get("learner_acceptance_mean")),
                    "mastery_status": learner.get("final_mastery_status"),
                    "payload": {"learner_study": learner, "learner_survey": learner_survey},
                    "source_label": source_label,
                    "data_classification": classification,
                    "authenticity_status": authenticity_status,
                },
            )
            learner_count += 1

        teacher_count = 0
        for teacher in dataset["teacher_survey"]:
            participant_code = teacher.get("teacher_code")
            if not participant_code:
                continue
            _upsert_record(
                conn,
                {
                    "record_type": "teacher",
                    "participant_code": participant_code,
                    "school_code": teacher.get("school_code"),
                    "subject": teacher.get("subject"),
                    "class_level": None,
                    "study_status": "Teacher survey record",
                    "pre_test_pct": None,
                    "post_test_pct": None,
                    "gain_points": None,
                    "acceptance_mean": _as_float(teacher.get("teacher_acceptance_mean")),
                    "mastery_status": None,
                    "payload": {"teacher_survey": teacher},
                    "source_label": source_label,
                    "data_classification": classification,
                    "authenticity_status": authenticity_status,
                },
            )
            teacher_count += 1

        reliability_count = 0
        for reliability in dataset.get("system_reliability") or []:
            if not reliability.get("date"):
                continue
            _upsert_reliability_record(conn, reliability, source_label)
            reliability_count += 1

        qualitative_theme_count = 0
        for theme in dataset.get("qualitative_themes") or []:
            if not theme.get("respondent_group") or not theme.get("coded_theme"):
                continue
            _upsert_qualitative_theme(conn, theme, source_label)
            qualitative_theme_count += 1

        conn.commit()
        return {
            "learners": learner_count,
            "teachers": teacher_count,
            "total": learner_count + teacher_count,
            "reliability_days": reliability_count,
            "qualitative_themes": qualitative_theme_count,
            "source_label": source_label,
            "classification": classification,
            "authenticity_status": authenticity_status,
        }
    finally:
        if owns_connection:
            conn.close()


def evaluation_dataset_rows(conn, record_type=None):
    ensure_evaluation_dataset_schema(conn)
    params = []
    where = ""
    if record_type:
        where = "WHERE record_type=?"
        params.append(record_type)
    rows = conn.execute(
        f"""
        SELECT evaluation_record_id, record_type, participant_code, school_code, subject,
               class_level, study_status, pre_test_pct, post_test_pct, gain_points,
               acceptance_mean, mastery_status, data_classification,
               authenticity_status, source_label, imported_at, payload_json
        FROM evaluation_dataset_records
        {where}
        ORDER BY record_type, participant_code
        """,
        params,
    ).fetchall()
    results = []
    for row in rows:
        result = {key: row[key] for key in row.keys() if key != "payload_json"}
        try:
            result["payload"] = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            result["payload"] = {}
        results.append(result)
    return results


def evaluation_reliability_rows(conn):
    ensure_evaluation_dataset_schema(conn)
    rows = conn.execute(
        """
        SELECT reliability_record_id, event_date, total_events, successful_events,
               error_events, success_rate_pct, average_latency_ms, p95_latency_ms,
               offline_queued_events, successful_sync_events, incident_category,
               source_label, imported_at
        FROM evaluation_reliability_records
        ORDER BY event_date
        """
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def evaluation_qualitative_theme_rows(conn):
    ensure_evaluation_dataset_schema(conn)
    rows = conn.execute(
        """
        SELECT theme_record_id, respondent_group, coded_theme, mention_count,
               interpretation, source_label, imported_at
        FROM evaluation_qualitative_themes
        ORDER BY respondent_group, mention_count DESC, coded_theme
        """
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def evaluation_evidence_summary(conn):
    metadata = load_evaluation_dataset().get("metadata") or {}
    reliability = evaluation_reliability_rows(conn)
    themes = evaluation_qualitative_theme_rows(conn)
    first_date = reliability[0]["event_date"] if reliability else ""
    last_date = reliability[-1]["event_date"] if reliability else ""
    return {
        "collection_design": "Single-group pre-test/post-test framework evaluation",
        "sampling_strategy": "Purposive maximum-variation case selection across two CBC secondary schools",
        "learner_measure": "Curriculum-mapped pre-test, practice, post-test, reflection and practical evidence",
        "teacher_measure": "Eight-item 5-point Likert acceptance questionnaire",
        "learner_questionnaire_measure": "Ten-item 5-point Likert questionnaire with LQ9 reverse-scored",
        "participant_assessment_dates_recorded": bool(metadata.get("participant_assessment_dates_recorded")),
        "verified_evidence_log_rows": int(metadata.get("verified_evidence_log_rows") or 0),
        "verified_evaluation_coverage_days": int(metadata.get("verified_evaluation_coverage_days") or 0),
        "six_month_duration_supported": bool(metadata.get("six_month_duration_supported")),
        "reliability_log_start": first_date or metadata.get("reliability_log_start") or "",
        "reliability_log_end": last_date or metadata.get("reliability_log_end") or "",
        "reliability_days": len(reliability),
        "qualitative_themes": len(themes),
        "qualitative_mentions": sum(int(row.get("mention_count") or 0) for row in themes),
        "coverage_status": (
            "Verified for at least six months"
            if metadata.get("six_month_duration_supported")
            else "Six-month participant evaluation is not yet verified"
        ),
    }


def evaluation_dataset_summary(conn):
    ensure_evaluation_dataset_schema(conn)
    learner = conn.execute(
        """
        SELECT COUNT(*) AS learner_records,
               SUM(CASE WHEN pre_test_pct IS NOT NULL AND post_test_pct IS NOT NULL THEN 1 ELSE 0 END) AS complete_pairs,
               AVG(CASE WHEN pre_test_pct IS NOT NULL AND post_test_pct IS NOT NULL THEN pre_test_pct END) AS average_pre_test,
               AVG(CASE WHEN pre_test_pct IS NOT NULL AND post_test_pct IS NOT NULL THEN post_test_pct END) AS average_post_test,
               AVG(CASE WHEN pre_test_pct IS NOT NULL AND post_test_pct IS NOT NULL THEN gain_points END) AS average_gain,
               SUM(CASE WHEN gain_points > 0 THEN 1 ELSE 0 END) AS improved_pairs,
               SUM(CASE WHEN mastery_status='Mastered' THEN 1 ELSE 0 END) AS mastered_records,
               SUM(CASE WHEN study_status='Withdrawn' THEN 1 ELSE 0 END) AS withdrawn_records,
               SUM(CASE WHEN study_status='Missing post-test' THEN 1 ELSE 0 END) AS missing_post_test_records,
               AVG(acceptance_mean) AS learner_acceptance,
               SUM(CASE WHEN acceptance_mean IS NOT NULL THEN 1 ELSE 0 END) AS learner_questionnaire_responses
        FROM evaluation_dataset_records
        WHERE record_type='learner'
        """
    ).fetchone()
    teacher = conn.execute(
        """
        SELECT COUNT(*) AS teacher_records, AVG(acceptance_mean) AS teacher_acceptance,
               SUM(CASE WHEN acceptance_mean IS NOT NULL THEN 1 ELSE 0 END) AS teacher_questionnaire_responses
        FROM evaluation_dataset_records
        WHERE record_type='teacher'
        """
    ).fetchone()

    def value(row, key, default=0):
        return row[key] if row and row[key] is not None else default

    complete_pairs = int(value(learner, "complete_pairs"))
    improved_pairs = int(value(learner, "improved_pairs"))
    mastered_records = int(value(learner, "mastered_records"))
    learner_records = int(value(learner, "learner_records"))
    teacher_records = int(value(teacher, "teacher_records"))
    learner_responses = int(value(learner, "learner_questionnaire_responses"))
    teacher_responses = int(value(teacher, "teacher_questionnaire_responses"))
    reliability = evaluation_reliability_rows(conn)
    reliability_total_events = sum(int(row.get("total_events") or 0) for row in reliability)
    reliability_successful_events = sum(int(row.get("successful_events") or 0) for row in reliability)
    offline_queued = sum(int(row.get("offline_queued_events") or 0) for row in reliability)
    successful_sync = sum(int(row.get("successful_sync_events") or 0) for row in reliability)
    weighted_latency = sum(
        float(row.get("average_latency_ms") or 0) * int(row.get("total_events") or 0)
        for row in reliability
    )
    themes = evaluation_qualitative_theme_rows(conn)
    return {
        "learner_records": learner_records,
        "teacher_records": teacher_records,
        "total_records": learner_records + teacher_records,
        "complete_pairs": complete_pairs,
        "average_pre_test": round(float(value(learner, "average_pre_test")), 2),
        "average_post_test": round(float(value(learner, "average_post_test")), 2),
        "average_gain": round(float(value(learner, "average_gain")), 2),
        "improved_pairs": improved_pairs,
        "improved_rate": round((improved_pairs / complete_pairs) * 100, 1) if complete_pairs else 0,
        "mastered_records": mastered_records,
        "mastery_rate": round((mastered_records / complete_pairs) * 100, 1) if complete_pairs else 0,
        "withdrawn_records": int(value(learner, "withdrawn_records")),
        "missing_post_test_records": int(value(learner, "missing_post_test_records")),
        "learner_acceptance": round(float(value(learner, "learner_acceptance")), 2),
        "teacher_acceptance": round(float(value(teacher, "teacher_acceptance")), 2),
        "learner_questionnaire_responses": learner_responses,
        "teacher_questionnaire_responses": teacher_responses,
        "questionnaire_responses": learner_responses + teacher_responses,
        "reliability_days": len(reliability),
        "reliability_log_start": reliability[0]["event_date"] if reliability else "",
        "reliability_log_end": reliability[-1]["event_date"] if reliability else "",
        "operational_success_rate": round(
            (reliability_successful_events / reliability_total_events) * 100, 2
        ) if reliability_total_events else 0,
        "offline_sync_success_rate": round(
            (successful_sync / offline_queued) * 100, 2
        ) if offline_queued else 0,
        "weighted_average_latency_ms": round(
            weighted_latency / reliability_total_events, 1
        ) if reliability_total_events else 0,
        "qualitative_themes": len(themes),
        "qualitative_mentions": sum(int(row.get("mention_count") or 0) for row in themes),
        "classification": SUPPLIED_CLASSIFICATION,
        "authenticity_status": SUPPLIED_AUTHENTICITY,
        "display_label": SUPPLIED_LABEL,
        "source_label": "Learn2Master_Dataset5.xlsx",
        "disclaimer": SUPPLIED_DISCLAIMER,
    }
