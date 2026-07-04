"""Proposal-to-system alignment utilities for Learn2Master.

This module keeps the prototype defensible by mapping each implemented
feature to the proposal components and evaluation indicators.
"""

PROPOSAL_COMPONENTS = [
    {
        "component": "Learner Profiling Module",
        "implemented_as": "Authenticated learner account, learning history, attempts, concept mastery records, mastery records, activity logs",
        "status": "Implemented / improving",
        "evidence": "users, assessment_attempts, concept_mastery, mastery_records, activity_logs",
    },
    {
        "component": "Sequential Content Adaptation Engine",
        "implemented_as": "Locked learning outcomes; next LO opens only when previous LO is Mastered",
        "status": "Implemented",
        "evidence": "learning_outcomes.sequence_order + mastery_records.mastery_status",
    },
    {
        "component": "Assessment and Feedback Module",
        "implemented_as": "Pre-test, adaptive practice, post-test, concept-level feedback, weak-concept detection",
        "status": "Implemented",
        "evidence": "assessments, questions, attempt_answers, concept_mastery",
    },
    {
        "component": "Recommendation System",
        "implemented_as": "Weak-concept recommendations, adaptive notes, videos, remedial practice and teacher review status",
        "status": "Implemented",
        "evidence": "adaptive_notes, adaptive_videos, recommendations",
    },
    {
        "component": "Teacher Support Dashboard",
        "implemented_as": "Teacher decision-support dashboard showing at-risk learners, weak concepts, AI recommendations and mastery reports",
        "status": "Implemented / extendable",
        "evidence": "teacher route + recommendations + mastery_records",
    },
    {
        "component": "Explainable AI / Trust Layer",
        "implemented_as": "Every recommendation includes reason, weak concepts, evidence and teacher review state",
        "status": "Implemented / improving",
        "evidence": "recommendations.recommendation_reason, concept_mastery",
    },
    {
        "component": "Learning Analytics Module",
        "implemented_as": "Mastery rate, average mastery, attempt counts, weak concept frequency, activity logs",
        "status": "Implemented / improving",
        "evidence": "framework alignment dashboard, teacher dashboard, activity_logs",
    },
    {
        "component": "Offline Functionality and Resource Optimization Layer",
        "implemented_as": "Offline-ready design placeholder, cache service worker skeleton and local SQLite prototype database",
        "status": "Prototype layer added",
        "evidence": "static/js/offline.js, service-worker.js, SQLite local DB",
    },
]

EVALUATION_INDICATORS = [
    {"indicator": "Mastery Attainment Rate", "source": "mastery_records", "implemented": True},
    {"indicator": "Learning Gain", "source": "pre-test and post-test records", "implemented": True},
    {"indicator": "Time-to-Mastery", "source": "activity_logs and attempt timestamps", "implemented": "Partial"},
    {"indicator": "Feedback Responsiveness", "source": "recommendations + repeated practice attempts", "implemented": "Partial"},
    {"indicator": "Teacher Oversight Effectiveness", "source": "teacher dashboard + recommendation review status", "implemented": True},
    {"indicator": "User Acceptance", "source": "questionnaire/interview outside prototype", "implemented": "Evaluation instrument"},
    {"indicator": "System Reliability", "source": "logs and offline/local operation", "implemented": "Partial"},
]


def get_alignment_matrix():
    return PROPOSAL_COMPONENTS


def get_evaluation_matrix():
    return EVALUATION_INDICATORS
