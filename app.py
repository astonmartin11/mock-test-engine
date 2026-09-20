"""
Adaptive AI Mock Test Engine & Personal Tutor
Entry point — run with: streamlit run app.py
"""

import streamlit as st
from pypdf import PdfReader
import io

import db
import ai_clients
import pdf_utils

st.set_page_config(page_title="Adaptive Mock Test Engine", page_icon="📘", layout="wide")


# =================================================================
# Sidebar — Module A: Subject & Memory Management
# =================================================================
def sidebar_subject_manager():
    st.sidebar.title("📘 Subjects")

    subjects = db.list_subjects()
    subject_names = [s["name"] for s in subjects]

    if subjects:
        default_idx = 0
        if "active_subject_id" in st.session_state:
            ids = [s["id"] for s in subjects]
            if st.session_state["active_subject_id"] in ids:
                default_idx = ids.index(st.session_state["active_subject_id"])

        chosen_name = st.sidebar.selectbox("Active subject", subject_names, index=default_idx)
        chosen = next(s for s in subjects if s["name"] == chosen_name)
        st.session_state["active_subject_id"] = chosen["id"]
        st.session_state["active_subject_name"] = chosen["name"]
    else:
        st.sidebar.info("No subjects yet — add one below.")
        st.session_state.pop("active_subject_id", None)
        st.session_state.pop("active_subject_name", None)

    with st.sidebar.expander("➕ Add subject"):
        new_name = st.text_input("Subject name", key="new_subject_name")
        if st.button("Add", key="add_subject_btn"):
            if new_name.strip():
                db.add_subject(new_name)
                st.rerun()
            else:
                st.warning("Enter a name first.")

    if subjects:
        with st.sidebar.expander("🗑️ Delete subject"):
            del_name = st.selectbox("Subject to delete", subject_names, key="del_subject_select")
            if st.button("Delete permanently", key="del_subject_btn"):
                target = next(s for s in subjects if s["name"] == del_name)
                db.delete_subject(target["id"])
                st.session_state.pop("active_subject_id", None)
                st.rerun()

    # Grey area snapshot in sidebar
    if st.session_state.get("active_subject_id"):
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔴 Current Grey Areas")
        grey = db.get_grey_areas(st.session_state["active_subject_id"])
        if grey:
            for g in grey:
                st.sidebar.markdown(f"- **{g['topic']}** — avg {g['running_avg_score']}/10")
        else:
            st.sidebar.caption("None recorded yet. Take a mock test to build this up.")


# =================================================================
# Helpers
# =================================================================
def read_uploaded_text(uploaded_file) -> tuple[bytes, str, str]:
    """Returns (raw_bytes, extracted_text_or_empty, mime_type)."""
    raw = uploaded_file.read()
    mime = uploaded_file.type or "application/octet-stream"
    text = ""
    if uploaded_file.name.lower().endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            text = ""
    elif uploaded_file.name.lower().endswith((".txt", ".md")):
        text = raw.decode("utf-8", errors="ignore")
    return raw, text, mime


# =================================================================
# Tab 1 — Module B: Upload materials + Generate mock test
# =================================================================
def tab_generate(subject_id: str, subject_name: str):
    st.header("📥 Course Material Upload")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Syllabus**")
        syl_file = st.file_uploader("Upload syllabus", type=["pdf", "txt", "md"], key="syl_upl")
        if syl_file and st.button("Extract syllabus", key="syl_btn"):
            with st.spinner("Gemini is reading the syllabus..."):
                raw, text, mime = read_uploaded_text(syl_file)
                if text.strip():
                    summary = ai_clients.extract_document_summary(text, "syllabus", subject_name)
                else:
                    summary = ai_clients.extract_from_file(raw, mime, "syllabus", subject_name)
                db.save_material(subject_id, "syllabus", syl_file.name, summary)
            st.success("Syllabus extracted and saved.")

    with col2:
        st.markdown("**Notes / PPTs**")
        notes_file = st.file_uploader("Upload notes", type=["pdf", "txt", "md"], key="notes_upl")
        if notes_file and st.button("Extract notes", key="notes_btn"):
            with st.spinner("Gemini is reading the notes..."):
                raw, text, mime = read_uploaded_text(notes_file)
                if text.strip():
                    summary = ai_clients.extract_document_summary(text, "notes", subject_name)
                else:
                    summary = ai_clients.extract_from_file(raw, mime, "notes", subject_name)
                db.save_material(subject_id, "notes", notes_file.name, summary)
            st.success("Notes extracted and saved.")

    with col3:
        st.markdown("**Previous Year Questions**")
        pyq_file = st.file_uploader("Upload PYQs", type=["pdf", "txt", "md"], key="pyq_upl")
        if pyq_file and st.button("Extract PYQs", key="pyq_btn"):
            with st.spinner("Gemini is reading the PYQs..."):
                raw, text, mime = read_uploaded_text(pyq_file)
                if text.strip():
                    summary = ai_clients.extract_document_summary(text, "pyq", subject_name)
                else:
                    summary = ai_clients.extract_from_file(raw, mime, "pyq", subject_name)
                db.save_material(subject_id, "pyq", pyq_file.name, summary)
            st.success("PYQs extracted and saved.")

    with st.expander("View extracted material library"):
        for mtype, label in [("syllabus", "Syllabus"), ("notes", "Notes"), ("pyq", "PYQs")]:
            materials = db.get_materials(subject_id, mtype)
            st.markdown(f"**{label}** ({len(materials)} uploaded)")
            for m in materials:
                st.caption(f"{m['source_filename']} — {m['created_at'][:10]}")

    st.markdown("---")
    st.header("⚙️ Mock Test Configuration")

    c1, c2, c3, c4 = st.columns(4)
    num_numericals = c1.number_input("Numericals", min_value=0, max_value=6, value=2)
    num_derivations = c2.number_input("Derivations", min_value=0, max_value=4, value=1)
    num_hots = c3.number_input("HOTS / Design", min_value=0, max_value=4, value=2)
    num_mcq = c4.number_input("Conceptual / MCQ", min_value=0, max_value=8, value=3)

    override = st.text_area(
        "Critical Override (optional steering instruction)",
        placeholder='e.g. "Make a numerical on backpropagation instead of forward propagation"',
    )

    if st.button("🚀 Generate Adaptive Mock Test", type="primary"):
        with st.spinner("Retrieving grey areas and generating your exam..."):
            grey_areas = db.get_grey_areas(subject_id)
            material_summary = db.get_combined_material_summary(subject_id)
            full_markdown = ai_clients.generate_mock_test(
                subject_name=subject_name,
                grey_areas=grey_areas,
                course_material_summary=material_summary,
                num_numericals=num_numericals,
                num_derivations=num_derivations,
                num_hots=num_hots,
                num_mcq=num_mcq,
                critical_override=override,
            )
            visible_test, solution_key = ai_clients.split_test_and_solution(full_markdown)
            saved = db.save_mock_test(
                subject_id=subject_id,
                config={
                    "numericals": num_numericals,
                    "derivations": num_derivations,
                    "hots": num_hots,
                    "mcq": num_mcq,
                    "override": override,
                },
                grey_areas_used=grey_areas,
                test_markdown=visible_test,
                solution_key=solution_key,
            )
            st.session_state["active_test_id"] = saved["id"]
        st.success("Mock test generated!")
        st.rerun()

    # Show the most recently generated test for this subject, if any
    tests = db.list_mock_tests(subject_id)
    if tests:
        st.markdown("---")
        st.header("📝 Generated Tests")
        test_labels = [f"{t['created_at'][:16].replace('T',' ')}" for t in tests]
        idx = st.selectbox("Select a test to view", range(len(tests)), format_func=lambda i: test_labels[i])
        selected_id = tests[idx]["id"]
        full_test = db.get_mock_test(selected_id)

        st.markdown(full_test["test_markdown"])

        pdf_bytes = pdf_utils.markdown_to_pdf_bytes(subject_name, full_test["test_markdown"])
        st.download_button(
            "⬇️ Download as PDF",
            data=pdf_bytes,
            file_name=f"{subject_name.replace(' ', '_')}_mock_test.pdf",
            mime="application/pdf",
        )
        st.session_state["active_test_id"] = selected_id


# =================================================================
# Tab 2 — Module C: Submit + grade answers
# =================================================================
def tab_evaluate(subject_id: str, subject_name: str):
    st.header("✅ Submit & Grade Your Answers")

    tests = db.list_mock_tests(subject_id)
    if not tests:
        st.info("Generate a mock test first (see the Generate tab).")
        return

    test_labels = [f"{t['created_at'][:16].replace('T',' ')}" for t in tests]
    default_idx = 0
    if "active_test_id" in st.session_state:
        ids = [t["id"] for t in tests]
        if st.session_state["active_test_id"] in ids:
            default_idx = ids.index(st.session_state["active_test_id"])

    idx = st.selectbox("Which test are you submitting for?", range(len(tests)),
                        format_func=lambda i: test_labels[i], index=default_idx)
    selected_test = db.get_mock_test(tests[idx]["id"])

    with st.expander("View test questions again"):
        st.markdown(selected_test["test_markdown"])

    submission_mode = st.radio("Submission method", ["Type answers", "Camera photo", "Upload scanned PDF"], horizontal=True)

    student_submission_text = None
    submission_type_db = "text"

    if submission_mode == "Type answers":
        student_submission_text = st.text_area("Paste / type your answers here", height=300)
        submission_type_db = "text"

    elif submission_mode == "Camera photo":
        img = st.camera_input("Take a photo of your handwritten answers")
        submission_type_db = "camera"
        if img is not None:
            with st.spinner("Transcribing handwriting with Gemini Vision..."):
                student_submission_text = ai_clients.transcribe_handwritten_answer(img.getvalue(), "image/jpeg")
            st.text_area("Transcribed answer (edit if OCR made mistakes)", value=student_submission_text, height=300, key="transcribed_edit")
            student_submission_text = st.session_state.get("transcribed_edit", student_submission_text)

    else:  # Upload scanned PDF
        pdf_img = st.file_uploader("Upload scanned answer sheet (PDF or image)", type=["pdf", "jpg", "jpeg", "png"])
        submission_type_db = "pdf"
        if pdf_img is not None:
            with st.spinner("Transcribing handwriting with Gemini Vision..."):
                raw = pdf_img.getvalue()
                mime = pdf_img.type or "application/pdf"
                if mime == "application/pdf":
                    # Gemini can read PDFs natively too
                    model = ai_clients._gemini_model()
                    response = model.generate_content([
                        {"mime_type": "application/pdf", "data": raw},
                        "Transcribe all handwritten answers in this scanned PDF into clean digital text, preserving question numbers and mathematical notation.",
                    ])
                    student_submission_text = response.text
                else:
                    student_submission_text = ai_clients.transcribe_handwritten_answer(raw, mime)
            st.text_area("Transcribed answer (edit if OCR made mistakes)", value=student_submission_text, height=300, key="transcribed_edit_pdf")
            student_submission_text = st.session_state.get("transcribed_edit_pdf", student_submission_text)

    if st.button("📤 Submit for Grading", type="primary", disabled=not student_submission_text):
        with st.spinner("Grading against the hidden solution key..."):
            reference = selected_test["test_markdown"] + "\n\n## Hidden Solution Key\n" + selected_test["solution_key"]
            result = ai_clients.grade_submission(reference, student_submission_text)

            if result.get("_parse_error"):
                st.error("Grading failed to parse — see raw output below. Try resubmitting.")
                st.code(result["overall_summary"])
                return

            db.save_evaluation(
                mock_test_id=selected_test["id"],
                subject_id=subject_id,
                submission_type=submission_type_db,
                transcribed_answer=student_submission_text,
                result_json=result,
            )

            # Update grey-area memory per topic
            for q in result.get("question_evaluations", []):
                if q.get("max_marks", 0) > 0:
                    score_out_of_10 = round((q["marks_awarded"] / q["max_marks"]) * 10, 2)
                    db.upsert_topic_score(
                        subject_id=subject_id,
                        topic=q.get("topic_tag", "Unknown"),
                        score_out_of_10=score_out_of_10,
                        feedback=q.get("missing_concepts_or_errors", ""),
                    )

            st.session_state["last_result"] = result
        st.success("Graded! Scroll down for your report.")
        st.rerun()

    if st.session_state.get("last_result"):
        result = st.session_state["last_result"]
        st.markdown("---")
        st.header("📊 Grading Report")
        st.metric("Score", f"{result.get('total_score','?')} / {result.get('max_score','?')}",
                   f"{result.get('percentage','?')}%")

        for q in result.get("question_evaluations", []):
            grey_tag = " 🔴 GREY AREA" if q.get("is_grey_area") else ""
            with st.expander(f"Q{q.get('question_number')} — {q.get('topic_tag')} — {q.get('marks_awarded')}/{q.get('max_marks')}{grey_tag}"):
                st.markdown(f"**Strengths:** {q.get('strengths','')}")
                st.markdown(f"**Errors/Gaps:** {q.get('missing_concepts_or_errors','')}")
                st.markdown(f"**Remedial action:** {q.get('remedial_action','')}")

        st.markdown(f"**Overall summary:** {result.get('overall_summary','')}")

        report_pdf = pdf_utils.evaluation_to_pdf_bytes(f"{subject_name} — Evaluation Report", result)
        st.download_button("⬇️ Download report as PDF", data=report_pdf,
                            file_name=f"{subject_name.replace(' ', '_')}_evaluation.pdf", mime="application/pdf")


# =================================================================
# Tab 3 — Module D: Personal tutor chat
# =================================================================
def tab_tutor(subject_id: str, subject_name: str):
    st.header(f"🎓 Personal Tutor — {subject_name}")

    grey = db.get_grey_areas(subject_id)
    grey_topics = [g["topic"] for g in grey]
    if grey_topics:
        st.caption(f"Currently reinforcing: {', '.join(grey_topics)}")

    history = db.get_tutor_history(subject_id)
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_msg = st.chat_input("Ask your tutor anything about this subject...")
    if user_msg:
        with st.chat_message("user"):
            st.markdown(user_msg)
        db.save_tutor_message(subject_id, "user", user_msg)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply = ai_clients.tutor_reply(subject_name, grey_topics, history, user_msg)
            st.markdown(reply)
        db.save_tutor_message(subject_id, "assistant", reply)


# =================================================================
# Tab 4 — Module A extra: Analytics dashboard
# =================================================================
def tab_analytics(subject_id: str, subject_name: str):
    st.header(f"📈 Topic Analytics — {subject_name}")
    topics = db.get_all_topics(subject_id)
    if not topics:
        st.info("No graded attempts yet.")
        return

    for t in topics:
        color = "🔴" if t["is_grey_area"] else "🟢"
        st.markdown(f"{color} **{t['topic']}** — avg {t['running_avg_score']}/10 "
                     f"over {t['attempts_count']} attempt(s). Latest: {t['latest_score']}/10")
        if t.get("last_feedback"):
            st.caption(t["last_feedback"])

    st.markdown("---")
    st.subheader("Evaluation history")
    evals = db.list_evaluations(subject_id)
    for e in evals:
        st.write(f"{e['created_at'][:16].replace('T',' ')} — {e['total_score']}/{e['max_score']} ({e['percentage']}%) via {e['submission_type']}")


# =================================================================
# Main
# =================================================================
def main():
    st.title("📘 Adaptive AI Mock Test Engine & Personal Tutor")

    sidebar_subject_manager()

    subject_id = st.session_state.get("active_subject_id")
    subject_name = st.session_state.get("active_subject_name")

    if not subject_id:
        st.info("👈 Add and select a subject in the sidebar to get started.")
        return

    tabs = st.tabs(["📥 Generate Test", "✅ Evaluate", "🎓 Tutor", "📈 Analytics"])
    with tabs[0]:
        tab_generate(subject_id, subject_name)
    with tabs[1]:
        tab_evaluate(subject_id, subject_name)
    with tabs[2]:
        tab_tutor(subject_id, subject_name)
    with tabs[3]:
        tab_analytics(subject_id, subject_name)


if __name__ == "__main__":
    main()
