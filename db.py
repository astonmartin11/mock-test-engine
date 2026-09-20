"""
All Supabase reads/writes live here. Nothing else in the app should
import the supabase client directly — go through these functions so
the schema only has to be known in one place.
"""

from __future__ import annotations
import streamlit as st
from supabase import create_client, Client
from datetime import datetime, timezone


@st.cache_resource
def get_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


# ---------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------
def list_subjects() -> list[dict]:
    sb = get_client()
    res = sb.table("subjects").select("*").order("name").execute()
    return res.data or []


def add_subject(name: str) -> dict:
    sb = get_client()
    res = sb.table("subjects").insert({"name": name.strip()}).execute()
    return res.data[0] if res.data else {}


def delete_subject(subject_id: str) -> None:
    sb = get_client()
    sb.table("subjects").delete().eq("id", subject_id).execute()


# ---------------------------------------------------------------
# Subject materials (extracted summaries from Syllabus/Notes/PYQ)
# ---------------------------------------------------------------
def save_material(subject_id: str, material_type: str, filename: str, summary: str) -> None:
    sb = get_client()
    sb.table("subject_materials").insert({
        "subject_id": subject_id,
        "material_type": material_type,
        "source_filename": filename,
        "extracted_summary": summary,
    }).execute()


def get_materials(subject_id: str, material_type: str | None = None) -> list[dict]:
    sb = get_client()
    q = sb.table("subject_materials").select("*").eq("subject_id", subject_id)
    if material_type:
        q = q.eq("material_type", material_type)
    res = q.order("created_at", desc=True).execute()
    return res.data or []


def get_combined_material_summary(subject_id: str) -> str:
    """Concatenate the latest summaries of each material type into one block
    for feeding into the mock-test generation prompt."""
    parts = []
    for mtype, label in [("syllabus", "SYLLABUS"), ("notes", "CLASS NOTES / SLIDES"), ("pyq", "PREVIOUS YEAR QUESTIONS")]:
        materials = get_materials(subject_id, mtype)
        if materials:
            joined = "\n\n".join(m["extracted_summary"] for m in materials)
            parts.append(f"=== {label} ===\n{joined}")
    return "\n\n".join(parts) if parts else "No course material uploaded yet."


# ---------------------------------------------------------------
# Grey areas / topic analytics
# ---------------------------------------------------------------
def get_grey_areas(subject_id: str, limit: int = 5) -> list[dict]:
    sb = get_client()
    res = (
        sb.table("topic_analytics")
        .select("*")
        .eq("subject_id", subject_id)
        .eq("is_grey_area", True)
        .order("running_avg_score")  # worst first
        .limit(limit)
        .execute()
    )
    return res.data or []


def get_all_topics(subject_id: str) -> list[dict]:
    sb = get_client()
    res = (
        sb.table("topic_analytics")
        .select("*")
        .eq("subject_id", subject_id)
        .order("running_avg_score")
        .execute()
    )
    return res.data or []


def upsert_topic_score(subject_id: str, topic: str, score_out_of_10: float, feedback: str) -> None:
    """Called after grading each question: updates the running average for
    that topic and recomputes whether it's a grey area (< 6/10 avg)."""
    sb = get_client()
    existing = (
        sb.table("topic_analytics")
        .select("*")
        .eq("subject_id", subject_id)
        .eq("topic", topic)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        n = row["attempts_count"] + 1
        new_avg = ((row["running_avg_score"] or 0) * row["attempts_count"] + score_out_of_10) / n
        sb.table("topic_analytics").update({
            "latest_score": score_out_of_10,
            "attempts_count": n,
            "running_avg_score": round(new_avg, 2),
            "is_grey_area": new_avg < 6.0,
            "last_feedback": feedback,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", row["id"]).execute()
    else:
        sb.table("topic_analytics").insert({
            "subject_id": subject_id,
            "topic": topic,
            "latest_score": score_out_of_10,
            "attempts_count": 1,
            "running_avg_score": score_out_of_10,
            "is_grey_area": score_out_of_10 < 6.0,
            "last_feedback": feedback,
        }).execute()


# ---------------------------------------------------------------
# Mock tests
# ---------------------------------------------------------------
def save_mock_test(subject_id: str, config: dict, grey_areas_used: list, test_markdown: str, solution_key: str) -> dict:
    sb = get_client()
    res = sb.table("mock_tests").insert({
        "subject_id": subject_id,
        "config": config,
        "grey_areas_used": grey_areas_used,
        "test_markdown": test_markdown,
        "solution_key": solution_key,
    }).execute()
    return res.data[0] if res.data else {}


def get_mock_test(test_id: str) -> dict | None:
    sb = get_client()
    res = sb.table("mock_tests").select("*").eq("id", test_id).execute()
    return res.data[0] if res.data else None


def list_mock_tests(subject_id: str) -> list[dict]:
    sb = get_client()
    res = (
        sb.table("mock_tests")
        .select("id, created_at, config")
        .eq("subject_id", subject_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


# ---------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------
def save_evaluation(mock_test_id: str, subject_id: str, submission_type: str,
                     transcribed_answer: str | None, result_json: dict) -> dict:
    sb = get_client()
    res = sb.table("evaluations").insert({
        "mock_test_id": mock_test_id,
        "subject_id": subject_id,
        "submission_type": submission_type,
        "transcribed_answer": transcribed_answer,
        "result_json": result_json,
        "total_score": result_json.get("total_score"),
        "max_score": result_json.get("max_score"),
        "percentage": result_json.get("percentage"),
    }).execute()
    return res.data[0] if res.data else {}


def list_evaluations(subject_id: str) -> list[dict]:
    sb = get_client()
    res = (
        sb.table("evaluations")
        .select("*")
        .eq("subject_id", subject_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


# ---------------------------------------------------------------
# Tutor chat history
# ---------------------------------------------------------------
def get_tutor_history(subject_id: str) -> list[dict]:
    sb = get_client()
    res = (
        sb.table("tutor_messages")
        .select("*")
        .eq("subject_id", subject_id)
        .order("created_at")
        .execute()
    )
    return res.data or []


def save_tutor_message(subject_id: str, role: str, content: str) -> None:
    sb = get_client()
    sb.table("tutor_messages").insert({
        "subject_id": subject_id,
        "role": role,
        "content": content,
    }).execute()
