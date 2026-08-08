"""Defensible statistical analysis for the recorded framework evaluation.

The functions in this module analyse only values already stored in the
evaluation register.  They never create participant observations, dates, or
qualitative excerpts.  The paired design is observational, so inferential
results are reported as evidence of within-sample change rather than proof of
causation.
"""

from collections import defaultdict
from math import erfc, exp, lgamma, log, sqrt
from statistics import mean, median, stdev, variance

from services.evaluation_dataset import (
    evaluation_dataset_rows,
    evaluation_dataset_summary,
    evaluation_evidence_summary,
)


LEARNER_SCALE_ITEMS = (
    "LQ1_outcome_clear",
    "LQ2_feedback_identified_weak_concept",
    "LQ3_explanation_clear",
    "LQ4_resources_matched_difficulty",
    "LQ5_evidence_helped_show_competence",
    "LQ6_progression_requirements_clear",
    "LQ7_interface_easy_to_use",
    "LQ8_trusted_evidence_based_recommendation",
    "LQ9_reverse_scored",
    "LQ10_would_use_again",
)

TEACHER_SCALE_ITEMS = (
    "TQ1_dashboard_identified_intervention",
    "TQ2_mastery_consistent_with_evidence",
    "TQ3_explanation_clear_for_instruction",
    "TQ4_preserved_teacher_control",
    "TQ5_cbc_sequence_match",
    "TQ6_reduced_evidence_organisation_effort",
    "TQ7_usable_in_available_conditions",
    "TQ8_would_use_after_improvements",
)


def _float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _p_display(value):
    if value is None:
        return "Not calculated"
    if value < 0.001:
        return "<0.001"
    return f"{value:.3f}"


def _beta_continued_fraction(a, b, x):
    """Numerical Recipes continued fraction used by incomplete beta."""
    max_iterations = 250
    epsilon = 3e-14
    floor = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < floor:
        d = floor
    d = 1.0 / d
    h = d
    for iteration in range(1, max_iterations + 1):
        twice = 2 * iteration
        aa = iteration * (b - iteration) * x / ((qam + twice) * (a + twice))
        d = 1.0 + aa * d
        if abs(d) < floor:
            d = floor
        c = 1.0 + aa / c
        if abs(c) < floor:
            c = floor
        d = 1.0 / d
        h *= d * c

        aa = -(a + iteration) * (qab + iteration) * x / (
            (a + twice) * (qap + twice)
        )
        d = 1.0 + aa * d
        if abs(d) < floor:
            d = floor
        c = 1.0 + aa / c
        if abs(c) < floor:
            c = floor
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < epsilon:
            break
    return h


def _regularized_beta(x, a, b):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = exp(
        lgamma(a + b) - lgamma(a) - lgamma(b) + a * log(x) + b * log(1 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def _student_t_cdf(value, degrees_of_freedom):
    if degrees_of_freedom <= 0:
        return None
    if value == 0:
        return 0.5
    x = degrees_of_freedom / (degrees_of_freedom + value * value)
    tail = 0.5 * _regularized_beta(x, degrees_of_freedom / 2.0, 0.5)
    return 1.0 - tail if value > 0 else tail


def _student_t_critical(degrees_of_freedom, probability=0.975):
    if degrees_of_freedom <= 0:
        return None
    low, high = 0.0, 20.0
    for _ in range(90):
        midpoint = (low + high) / 2.0
        if _student_t_cdf(midpoint, degrees_of_freedom) < probability:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2.0


def _wilcoxon_signed_rank(values):
    non_zero = [float(value) for value in values if float(value) != 0]
    count = len(non_zero)
    if not count:
        return {
            "valid_non_zero_pairs": 0,
            "statistic": 0,
            "positive_rank_sum": 0,
            "negative_rank_sum": 0,
            "z": 0,
            "p_value": None,
            "p_value_display": "Not calculated",
            "rank_biserial": 0,
        }

    ordered = sorted(enumerate(non_zero), key=lambda pair: abs(pair[1]))
    ranks = [0.0] * count
    tie_sizes = []
    index = 0
    while index < count:
        end = index + 1
        while end < count and abs(ordered[end][1]) == abs(ordered[index][1]):
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        for position in range(index, end):
            ranks[ordered[position][0]] = average_rank
        tie_sizes.append(end - index)
        index = end

    positive = sum(rank for rank, value in zip(ranks, non_zero) if value > 0)
    negative = sum(rank for rank, value in zip(ranks, non_zero) if value < 0)
    total_rank = count * (count + 1) / 2.0
    expected = total_rank / 2.0
    tie_correction = sum(size**3 - size for size in tie_sizes) / 48.0
    rank_variance = count * (count + 1) * (2 * count + 1) / 24.0 - tie_correction
    if rank_variance > 0:
        corrected_distance = max(0.0, abs(positive - expected) - 0.5)
        z_value = corrected_distance / sqrt(rank_variance)
        p_value = erfc(z_value / sqrt(2.0))
    else:
        z_value = 0.0
        p_value = None
    return {
        "valid_non_zero_pairs": count,
        "statistic": round(min(positive, negative), 2),
        "positive_rank_sum": round(positive, 2),
        "negative_rank_sum": round(negative, 2),
        "z": round(z_value, 3),
        "p_value": p_value,
        "p_value_display": _p_display(p_value),
        "rank_biserial": round((positive - negative) / total_rank, 3),
    }


def paired_outcome_statistics(conn):
    rows = [
        row
        for row in evaluation_dataset_rows(conn, "learner")
        if row.get("pre_test_pct") is not None and row.get("post_test_pct") is not None
    ]
    pre_scores = [float(row["pre_test_pct"]) for row in rows]
    post_scores = [float(row["post_test_pct"]) for row in rows]
    gains = [post - pre for pre, post in zip(pre_scores, post_scores)]
    count = len(gains)
    if not count:
        return {
            "valid_pairs": 0,
            "mean_pre_test": 0,
            "mean_post_test": 0,
            "mean_gain": 0,
            "median_gain": 0,
            "gain_standard_deviation": 0,
            "standard_error": 0,
            "confidence_level": 95,
            "confidence_interval_low": 0,
            "confidence_interval_high": 0,
            "t_statistic": 0,
            "degrees_of_freedom": 0,
            "p_value": None,
            "p_value_display": "Not calculated",
            "cohens_dz": 0,
            "improved_count": 0,
            "unchanged_count": 0,
            "declined_count": 0,
            "method_note": "No complete matched pre-test/post-test pairs are available.",
            "wilcoxon": _wilcoxon_signed_rank([]),
        }

    mean_gain = mean(gains)
    gain_sd = stdev(gains) if count > 1 else 0.0
    standard_error = gain_sd / sqrt(count) if count > 1 else 0.0
    t_value = mean_gain / standard_error if standard_error else 0.0
    degrees_of_freedom = count - 1
    t_cdf = _student_t_cdf(abs(t_value), degrees_of_freedom)
    p_value = 2.0 * (1.0 - t_cdf) if t_cdf is not None else None
    critical = _student_t_critical(degrees_of_freedom)
    margin = critical * standard_error if critical is not None else 0.0
    return {
        "valid_pairs": count,
        "mean_pre_test": round(mean(pre_scores), 2),
        "mean_post_test": round(mean(post_scores), 2),
        "mean_gain": round(mean_gain, 2),
        "median_gain": round(median(gains), 2),
        "gain_standard_deviation": round(gain_sd, 2),
        "standard_error": round(standard_error, 3),
        "confidence_level": 95,
        "confidence_interval_low": round(mean_gain - margin, 2),
        "confidence_interval_high": round(mean_gain + margin, 2),
        "t_statistic": round(t_value, 2),
        "degrees_of_freedom": degrees_of_freedom,
        "p_value": p_value,
        "p_value_display": _p_display(p_value),
        "cohens_dz": round(mean_gain / gain_sd, 2) if gain_sd else 0.0,
        "improved_count": sum(1 for gain in gains if gain > 0),
        "unchanged_count": sum(1 for gain in gains if gain == 0),
        "declined_count": sum(1 for gain in gains if gain < 0),
        "wilcoxon": _wilcoxon_signed_rank(gains),
        "method_note": (
            "Paired t-test with a two-sided Wilcoxon signed-rank sensitivity check. "
            "The single-group design supports an observed within-sample association, "
            "not a causal treatment-effect claim."
        ),
    }


def _cronbach_alpha(matrix):
    if not matrix or len(matrix) < 2 or len(matrix[0]) < 2:
        return None
    item_count = len(matrix[0])
    item_variances = [variance([row[index] for row in matrix]) for index in range(item_count)]
    total_scores = [sum(row) for row in matrix]
    total_variance = variance(total_scores)
    if total_variance == 0:
        return None
    return item_count / (item_count - 1) * (1.0 - sum(item_variances) / total_variance)


def _alpha_interpretation(alpha):
    if alpha is None:
        return "Not calculated"
    if alpha >= 0.9:
        return "Excellent internal consistency"
    if alpha >= 0.8:
        return "Good internal consistency"
    if alpha >= 0.7:
        return "Acceptable internal consistency"
    if alpha >= 0.6:
        return "Questionable internal consistency"
    return "Low internal consistency; review the scale"


def questionnaire_reliability(conn):
    specifications = (
        ("Learner acceptance scale", "learner", "learner_survey", LEARNER_SCALE_ITEMS),
        ("Teacher acceptance scale", "teacher", "teacher_survey", TEACHER_SCALE_ITEMS),
    )
    results = []
    for scale_name, record_type, payload_key, items in specifications:
        matrix = []
        for row in evaluation_dataset_rows(conn, record_type):
            payload = (row.get("payload") or {}).get(payload_key) or {}
            values = [_float(payload.get(item)) for item in items]
            if all(value is not None for value in values):
                matrix.append(values)
        alpha = _cronbach_alpha(matrix)
        interpretation = _alpha_interpretation(alpha)
        if matrix and len(matrix) < 30:
            interpretation += "; interpret cautiously because the response sample is small"
        results.append(
            {
                "scale": scale_name,
                "responses": len(matrix),
                "items": len(items),
                "cronbach_alpha": round(alpha, 3) if alpha is not None else "Not calculated",
                "interpretation": interpretation,
            }
        )
    return results


def evaluation_subgroups(conn, dimension):
    supported = {
        "subject": ("Subject", lambda row, payload: row.get("subject") or "Not recorded"),
        "school": ("School", lambda row, payload: row.get("school_code") or "Not recorded"),
        "class": ("Class", lambda row, payload: row.get("class_level") or "Not recorded"),
        "connectivity": (
            "Connectivity",
            lambda row, payload: payload.get("connectivity") or "Not recorded",
        ),
        "device_access": (
            "Device access",
            lambda row, payload: payload.get("device_access") or "Not recorded",
        ),
    }
    if dimension not in supported:
        raise ValueError(f"Unsupported evaluation subgroup: {dimension}")
    label, selector = supported[dimension]
    grouped = defaultdict(list)
    for row in evaluation_dataset_rows(conn, "learner"):
        if row.get("pre_test_pct") is None or row.get("post_test_pct") is None:
            continue
        study_payload = (row.get("payload") or {}).get("learner_study") or {}
        grouped[selector(row, study_payload)].append(row)

    results = []
    for group_name in sorted(grouped):
        rows = grouped[group_name]
        gains = [float(row["post_test_pct"]) - float(row["pre_test_pct"]) for row in rows]
        acceptance = [
            float(row["acceptance_mean"])
            for row in rows
            if row.get("acceptance_mean") is not None
        ]
        mastered = sum(1 for row in rows if row.get("mastery_status") == "Mastered")
        improved = sum(1 for gain in gains if gain > 0)
        results.append(
            {
                "dimension": label,
                "group": group_name,
                "valid_pairs": len(rows),
                "mean_pre_test": round(mean(float(row["pre_test_pct"]) for row in rows), 2),
                "mean_post_test": round(mean(float(row["post_test_pct"]) for row in rows), 2),
                "mean_gain": round(mean(gains), 2),
                "gain_standard_deviation": round(stdev(gains), 2) if len(gains) > 1 else 0.0,
                "improved": improved,
                "improved_rate": round(improved / len(rows) * 100, 1),
                "mastered": mastered,
                "mastery_rate": round(mastered / len(rows) * 100, 1),
                "acceptance_mean": round(mean(acceptance), 2) if acceptance else "Not recorded",
            }
        )
    return results


def analysis_completeness(conn):
    summary = evaluation_dataset_summary(conn)
    evidence = evaluation_evidence_summary(conn)
    return [
        {
            "requirement": "Matched pre-test/post-test learning gain",
            "status": "Complete" if summary["complete_pairs"] else "Missing",
            "available_evidence": f"{summary['complete_pairs']} complete matched pairs",
            "next_action": "Retain the pairing rules and report excluded cases.",
        },
        {
            "requirement": "Descriptive and comparative statistical analysis",
            "status": "Complete" if summary["complete_pairs"] > 1 else "Missing",
            "available_evidence": "Means, dispersion, confidence interval, paired t-test, Wilcoxon check and effect size",
            "next_action": "Use observational language because there is no control group.",
        },
        {
            "requirement": "Questionnaire acceptance and scale reliability",
            "status": "Complete" if summary["questionnaire_responses"] else "Missing",
            "available_evidence": f"{summary['learner_questionnaire_responses']} learner and {summary['teacher_questionnaire_responses']} teacher responses",
            "next_action": "Report Cronbach's alpha separately for learner and teacher scales.",
        },
        {
            "requirement": "Sample-size justification",
            "status": "Missing",
            "available_evidence": f"The recorded flow contains {summary['learner_records']} learners, {summary['complete_pairs']} complete pairs and {summary['teacher_records']} teachers, but no power calculation or formal sample-size rationale is stored.",
            "next_action": "Add the approved purposive-sampling rationale and, if required by the supervisor, an appropriate power or precision justification.",
        },
        {
            "requirement": "Instrument content and construct validity",
            "status": "Partial",
            "available_evidence": "Item-level questionnaire responses and internal-consistency results are available; expert-review, CVI or pilot-validation records are not stored.",
            "next_action": "Attach genuine expert-review or pilot-validation evidence if it was completed; do not reconstruct approval scores.",
        },
        {
            "requirement": "Mastery, attempts, time-to-mastery and feedback responsiveness",
            "status": "Complete" if summary["complete_pairs"] else "Missing",
            "available_evidence": "Recorded mastery, practice-attempt, time and recommendation fields plus ongoing portal events",
            "next_action": "Keep evaluation-register summaries distinct from new event-level portal records.",
        },
        {
            "requirement": "Subgroup descriptive analysis",
            "status": "Complete" if summary["complete_pairs"] else "Missing",
            "available_evidence": "Subject, school, class, connectivity and device-access comparisons",
            "next_action": "Treat small subgroup results as exploratory.",
        },
        {
            "requirement": "System reliability under low-resource conditions",
            "status": "Partial" if summary["reliability_days"] else "Missing",
            "available_evidence": f"{summary['reliability_days']} recorded daily aggregates ({summary['reliability_log_start']} to {summary['reliability_log_end']})",
            "next_action": "Add dated operational evidence if the approved evaluation requires a longer period.",
        },
        {
            "requirement": "Qualitative thematic analysis audit trail",
            "status": "Partial" if summary["qualitative_themes"] else "Missing",
            "available_evidence": f"{summary['qualitative_themes']} theme summaries and {summary['qualitative_mentions']} mentions",
            "next_action": "Retain anonymized source excerpts, coding notes and interviewer records separately.",
        },
        {
            "requirement": "Participant assessment dates and verified evaluation duration",
            "status": "Complete" if evidence["six_month_duration_supported"] else "Missing",
            "available_evidence": f"{evidence['verified_evaluation_coverage_days']} verified coverage days from {evidence['verified_evidence_log_rows']} source-linked evidence rows",
            "next_action": "Enter genuine dated source evidence; dates cannot be reconstructed from aggregate results.",
        },
        {
            "requirement": "Consent, assent and parental-consent documentation",
            "status": "Partial",
            "available_evidence": "The portal supports consent-controlled participants, but the imported evaluation rows contain no consent fields.",
            "next_action": "Keep the approved signed forms or ethics register available for audit.",
        },
        {
            "requirement": "Causal effectiveness or control-group comparison",
            "status": "Not in design",
            "available_evidence": "The proposal specifies a single-group pre-test/post-test pilot.",
            "next_action": "Do not claim causation; recommend a controlled follow-up study.",
        },
    ]


def evaluation_analysis(conn):
    return {
        "paired": paired_outcome_statistics(conn),
        "questionnaire_reliability": questionnaire_reliability(conn),
        "subject_subgroups": evaluation_subgroups(conn, "subject"),
        "school_subgroups": evaluation_subgroups(conn, "school"),
        "class_subgroups": evaluation_subgroups(conn, "class"),
        "connectivity_subgroups": evaluation_subgroups(conn, "connectivity"),
        "device_subgroups": evaluation_subgroups(conn, "device_access"),
        "completeness": analysis_completeness(conn),
    }


def evaluation_analysis_export_rows(analysis):
    paired = analysis["paired"]
    rows = [
        {"section": "Paired outcomes", "measure": "Valid pairs", "value": paired.get("valid_pairs"), "interpretation": "Complete matched learner records"},
        {"section": "Paired outcomes", "measure": "Mean pre-test (%)", "value": paired.get("mean_pre_test"), "interpretation": "Baseline mean"},
        {"section": "Paired outcomes", "measure": "Mean post-test (%)", "value": paired.get("mean_post_test"), "interpretation": "Post-intervention mean"},
        {"section": "Paired outcomes", "measure": "Mean gain (percentage points)", "value": paired.get("mean_gain"), "interpretation": "Observed within-sample change"},
        {"section": "Paired outcomes", "measure": "95% CI lower", "value": paired.get("confidence_interval_low"), "interpretation": "Confidence interval for mean paired gain"},
        {"section": "Paired outcomes", "measure": "95% CI upper", "value": paired.get("confidence_interval_high"), "interpretation": "Confidence interval for mean paired gain"},
        {"section": "Paired outcomes", "measure": "Paired t statistic", "value": paired.get("t_statistic"), "interpretation": f"df={paired.get('degrees_of_freedom', 0)}, p={paired.get('p_value_display')}"},
        {"section": "Paired outcomes", "measure": "Cohen's dz", "value": paired.get("cohens_dz"), "interpretation": "Standardized within-person effect size"},
        {"section": "Paired outcomes", "measure": "Wilcoxon statistic", "value": (paired.get("wilcoxon") or {}).get("statistic"), "interpretation": f"Two-sided normal approximation p={(paired.get('wilcoxon') or {}).get('p_value_display')}"},
    ]
    for scale in analysis["questionnaire_reliability"]:
        rows.append(
            {
                "section": "Questionnaire reliability",
                "measure": f"{scale['scale']} Cronbach alpha",
                "value": scale["cronbach_alpha"],
                "interpretation": f"{scale['interpretation']} ({scale['responses']} responses, {scale['items']} items)",
            }
        )
    for dimension_key in (
        "subject_subgroups",
        "school_subgroups",
        "class_subgroups",
        "connectivity_subgroups",
        "device_subgroups",
    ):
        for subgroup in analysis[dimension_key]:
            rows.append(
                {
                    "section": f"{subgroup['dimension']} subgroup",
                    "measure": f"{subgroup['group']} mean gain",
                    "value": subgroup["mean_gain"],
                    "interpretation": f"n={subgroup['valid_pairs']}; mastery={subgroup['mastery_rate']}%; acceptance={subgroup['acceptance_mean']}",
                }
            )
    for item in analysis["completeness"]:
        rows.append(
            {
                "section": "Analysis completeness",
                "measure": item["requirement"],
                "value": item["status"],
                "interpretation": f"{item['available_evidence']} Next: {item['next_action']}",
            }
        )
    return rows
