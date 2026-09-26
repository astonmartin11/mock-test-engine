"""
Adaptive AI Mock Test Engine & Personal Tutor
Entry point — run with: streamlit run app.py
"""

import streamlit as st

import db
import ai_clients
import pdf_utils
import ocr_utils
import storage_utils
import config

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
                with st.spinner("Deleting subject and all associated data..."):
                    # Storage objects (extracted .txt files) live outside
                    # Postgres, so they must be cleaned up explicitly —
                    # the DB's ON DELETE CASCADE only covers Postgres rows
                    # (subject_materials, mock_tests, topic_analytics,
                    # evaluations, tutor_messages).
                    storage_paths = db.get_all_storage_paths(target["id"])
                    storage_utils.delete_objects(storage_paths)
                    db.delete_subject(target["id"])
                st.session_state.pop("active_subject_id", None)
                st.success(f"Deleted '{del_name}' and all its data (materials, tests, scores, chat history).")
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
def _process_and_save_material(subject_id: str, subject_name: str, material_type: str,
                                filename: str, raw_bytes: int | bytes) -> bool:
    """OCR/extract -> upload text to Storage -> summarize -> save DB row.
    Returns True on success. All materials go through this single path:
    PDFs and images are OCR'd to plain text FIRST (ocr_utils), and only
    that extracted text is ever stored or sent to an AI model."""
    raw = raw_bytes
    try:
        text = ocr_utils.extract_text_from_upload(raw, filename)
    except ocr_utils.OCRError as e:
        st.error(f"'{filename}': {e}")
        return False

    if not text.strip():
        st.warning(f"No extractable text found in '{filename}' — skipped.")
        return False

    try:
        storage_path = storage_utils.upload_text(subject_id, material_type, filename, text)
    except Exception as e:
        # Most common cause: the 'materials' Storage bucket doesn't exist
        # yet (schema.sql's storage section wasn't run) — surfaced here
        # instead of crashing the whole app.
        st.error(f"Couldn't save '{filename}' to storage: {type(e).__name__}: {e}")
        return False

    try:
        summary = ai_clients.extract_document_summary(text, material_type, subject_name)
    except Exception as e:
        # Most common cause: GEMINI_MODEL in secrets is set to a
        # deprecated/unavailable model name.
        st.error(f"Couldn't summarize '{filename}' (saved to storage, but no AI summary yet): "
                 f"{type(e).__name__}: {e}")
        return False

    try:
        db.save_material(subject_id, material_type, filename, storage_path, len(raw), len(text), summary)
    except Exception as e:
        st.error(f"Couldn't save '{filename}' to the database: {type(e).__name__}: {e}")
        return False

    return True


def _replace_syllabus(subject_id: str) -> None:
    """Syllabus is replace-not-accumulate: wipe any existing syllabus
    material (DB row + its Storage object) before a new one is saved."""
    existing = db.get_materials(subject_id, "syllabus")
    for m in existing:
        if m.get("storage_path"):
            storage_utils.delete_objects([m["storage_path"]])
        db.delete_material_row(m["id"])


# =================================================================
# Tab 1 — Module B: Upload materials + Generate mock test
# =================================================================
def tab_generate(subject_id: str, subject_name: str):
    st.header("📥 Course Material Upload")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(f"**Syllabus** (max {config.SYLLABUS_MAX_BYTES // (1024*1024)} MB, replaces previous)")
        syl_file = st.file_uploader("Upload syllabus", type=config.ACCEPTED_MATERIAL_TYPES, key="syl_upl")
        if syl_file and st.button("Process syllabus", key="syl_btn"):
            raw = syl_file.getvalue()
            if len(raw) > config.SYLLABUS_MAX_BYTES:
                st.error(f"'{syl_file.name}' is {len(raw)/1e6:.2f} MB — syllabus cap is "
                         f"{config.SYLLABUS_MAX_BYTES/1e6:.0f} MB.")
            else:
                with st.spinner("Extracting text and replacing previous syllabus..."):
                    _replace_syllabus(subject_id)
                    ok = _process_and_save_material(subject_id, subject_name, "syllabus", syl_file.name, raw)
                if ok:
                    st.success("Syllabus processed and saved (previous syllabus, if any, was replaced).")

    with col2:
        cap_file_mb = config.NOTES_MAX_FILE_BYTES // (1024*1024)
        cap_total_mb = config.NOTES_MAX_TOTAL_BYTES_PER_SUBJECT // (1024*1024)
        st.markdown(f"**Notes / PPTs** (max {cap_file_mb} MB/file, {cap_total_mb} MB total/subject, accumulates)")
        notes_files = st.file_uploader("Upload notes (multiple files allowed)",
                                        type=config.ACCEPTED_MATERIAL_TYPES, key="notes_upl",
                                        accept_multiple_files=True)
        if notes_files and st.button("Process notes", key="notes_btn"):
            running_total = db.get_notes_total_bytes(subject_id)
            for f in notes_files:
                raw = f.getvalue()
                if len(raw) > config.NOTES_MAX_FILE_BYTES:
                    st.error(f"'{f.name}' is {len(raw)/1e6:.1f} MB — per-file cap is {cap_file_mb} MB. Skipped.")
                    continue
                if running_total + len(raw) > config.NOTES_MAX_TOTAL_BYTES_PER_SUBJECT:
                    st.error(f"Adding '{f.name}' would exceed this subject's {cap_total_mb} MB "
                             f"cumulative notes cap. Skipped.")
                    continue
                with st.spinner(f"Extracting text from '{f.name}'..."):
                    ok = _process_and_save_material(subject_id, subject_name, "notes", f.name, raw)
                if ok:
                    running_total += len(raw)
            st.success("Notes upload batch processed.")

    with col3:
        cap_pyq_mb = config.PYQ_MAX_FILE_BYTES // (1024*1024)
        st.markdown(f"**Previous Year Questions** (max {cap_pyq_mb} MB/file, accumulates)")
        pyq_files = st.file_uploader("Upload PYQs (multiple files allowed)",
                                      type=config.ACCEPTED_MATERIAL_TYPES, key="pyq_upl",
                                      accept_multiple_files=True)
        if pyq_files and st.button("Process PYQs", key="pyq_btn"):
            for f in pyq_files:
                raw = f.getvalue()
                if len(raw) > config.PYQ_MAX_FILE_BYTES:
                    st.error(f"'{f.name}' is {len(raw)/1e6:.1f} MB — PYQ cap is {cap_pyq_mb} MB. Skipped.")
                    continue
                with st.spinner(f"Extracting text from '{f.name}'..."):
                    _process_and_save_material(subject_id, subject_name, "pyq", f.name, raw)
            st.success("PYQ upload batch processed.")

    with st.expander("View extracted material library"):
        for mtype, label in [("syllabus", "Syllabus"), ("notes", "Notes"), ("pyq", "PYQs")]:
            materials = db.get_materials(subject_id, mtype)
            st.markdown(f"**{label}** ({len(materials)} uploaded)")
            for m in materials:
                size_mb = (m.get("file_size_bytes") or 0) / 1e6
                st.caption(f"{m['source_filename']} — {size_mb:.2f} MB raw, "
                           f"{m.get('char_count', 0):,} chars extracted — {m['created_at'][:10]}")

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
        try:
            with st.spinner("Retrieving grey areas and generating your exam..."):
                grey_areas = db.get_grey_areas(subject_id)
                material_summary = db.get_combined_material_summary(
                    subject_id, config.MAX_SUMMARY_CHARS_PER_MATERIAL
                )
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
        except Exception as e:
            # Surfaced in-page instead of crashing the whole script — a
            # failed Groq/Gemini call, a Supabase write error, etc. now
            # shows here rather than taking down the entire app.
            st.error(f"Test generation failed: {type(e).__name__}: {e}")

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

        try:
            pdf_bytes = pdf_utils.markdown_to_pdf_bytes(subject_name, full_test["test_markdown"])
            st.download_button(
                "⬇️ Download as PDF",
                data=pdf_bytes,
                file_name=f"{subject_name.replace(' ', '_')}_mock_test.pdf",
                mime="application/pdf",
            )
        except Exception as e:
            # PDF rendering failure no longer crashes the whole page —
            # the test is still visible above, just not downloadable
            # until this is fixed.
            st.error(f"Couldn't generate the PDF for this test: {type(e).__name__}: {e}")
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
        engine_choice = st.radio(
            "Answer type",
            ["Handwritten (Gemini Vision — most accurate)",
             "Typed / printed (Tesseract OCR — free & unlimited)",
             "Auto (try Gemini, fall back to Tesseract)"],
            index=0, horizontal=True, key="engine_camera",
        )
        engine = {"Handwritten (Gemini Vision — most accurate)": "gemini",
                  "Typed / printed (Tesseract OCR — free & unlimited)": "tesseract",
                  "Auto (try Gemini, fall back to Tesseract)": "auto"}[engine_choice]

        img = st.camera_input("Take a photo of your answers")
        submission_type_db = "camera"
        if img is not None:
            with st.spinner("Transcribing..."):
                try:
                    text, engine_used = ai_clients.transcribe_answer(
                        img.getvalue(), "photo.jpg", "image/jpeg", engine=engine
                    )
                    student_submission_text = text
                    st.caption(f"Transcribed using: {engine_used}")
                except Exception as e:
                    st.error(f"Transcription failed: {e}")
                    student_submission_text = None
            if student_submission_text is not None:
                st.text_area("Transcribed answer (edit if OCR made mistakes)", value=student_submission_text, height=300, key="transcribed_edit")
                student_submission_text = st.session_state.get("transcribed_edit", student_submission_text)

    else:  # Upload scanned PDF or image
        engine_choice = st.radio(
            "Answer type",
            ["Handwritten (Gemini Vision — most accurate)",
             "Typed / printed (Tesseract OCR — free & unlimited)",
             "Auto (try Gemini, fall back to Tesseract)"],
            index=2, horizontal=True, key="engine_upload",
        )
        engine = {"Handwritten (Gemini Vision — most accurate)": "gemini",
                  "Typed / printed (Tesseract OCR — free & unlimited)": "tesseract",
                  "Auto (try Gemini, fall back to Tesseract)": "auto"}[engine_choice]

        pdf_img = st.file_uploader("Upload scanned answer sheet (PDF or image)", type=["pdf", "jpg", "jpeg", "png"])
        submission_type_db = "pdf"
        if pdf_img is not None:
            raw = pdf_img.getvalue()
            mime = pdf_img.type or "application/octet-stream"
            with st.spinner("Transcribing..."):
                try:
                    text, engine_used = ai_clients.transcribe_answer(
                        raw, pdf_img.name, mime, engine=engine
                    )
                    student_submission_text = text
                    st.caption(f"Transcribed using: {engine_used}")
                except Exception as e:
                    st.error(f"Transcription failed: {e}")
                    student_submission_text = None
            if student_submission_text is not None:
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
