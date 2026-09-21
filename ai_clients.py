"""
Thin wrappers around the two model providers:
- Gemini 1.5 Flash: document extraction (huge context) + vision OCR of
  handwritten answer sheets.
- Groq (Qwen-2.5-32B or Llama-3.3-70B): fast, accurate reasoning for
  test generation, grading, and the tutor chat.

Every function here returns plain Python types (str / dict) so the
rest of the app never touches SDK response objects directly.
"""

from __future__ import annotations
import json
import re
import streamlit as st
import google.generativeai as genai
from groq import Groq

from prompts import (
    EXTRACTION_PROMPT,
    MOCK_TEST_GENERATION_PROMPT,
    EVALUATION_PROMPT,
    build_tutor_system_prompt,
)
import ocr_utils


# ---------------------------------------------------------------
# Client setup (cached so we don't re-init on every rerun)
# ---------------------------------------------------------------
@st.cache_resource
def _gemini_model():
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Configurable via secrets so a future Gemini model rotation only needs
    # a secrets update, not a code change. gemini-1.5-flash was fully shut
    # down by Google in Sept 2025 — do not revert to it.
    model_name = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")
    return genai.GenerativeModel(model_name)


@st.cache_resource
def _groq_client() -> Groq:
    return Groq(api_key=st.secrets["GROQ_API_KEY"])


def _groq_model_name() -> str:
    return st.secrets.get("GROQ_MODEL", "llama-3.3-70b-versatile")


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------
def _strip_json_fences(text: str) -> str:
    """Groq/Gemini sometimes wrap JSON in ```json ... ``` fences despite
    instructions not to. Strip them defensively before parsing."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _groq_chat(system_prompt: str, user_prompt: str, temperature: float = 0.4,
               max_tokens: int = 8000, json_mode: bool = False) -> str:
    client = _groq_client()
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    completion = client.chat.completions.create(
        model=_groq_model_name(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return completion.choices[0].message.content


# ---------------------------------------------------------------
# Module B (part 1): Extraction via Gemini
# ---------------------------------------------------------------
def extract_document_summary(document_text: str, material_type: str, subject_name: str) -> str:
    """Takes already-OCR'd/extracted plain text (see ocr_utils.py) and asks
    Gemini to turn it into a dense academic summary for the generation
    prompt. Materials are always converted to text FIRST by ocr_utils —
    Gemini never receives raw PDF/image bytes for course materials
    (it's still used for handwriting OCR in the evaluation module)."""
    model = _gemini_model()
    prompt = EXTRACTION_PROMPT.format(
        material_type=material_type,
        subject_name=subject_name,
        document_text=document_text[:900_000],  # stay well within 1M token window
    )
    response = model.generate_content(prompt)
    return response.text


# ---------------------------------------------------------------
# Module C (part 1): Answer-sheet transcription — Gemini Vision AND
# Tesseract OCR, picked by suitability (or chosen automatically).
# ---------------------------------------------------------------
# Rule of thumb:
#   - Gemini Vision: genuinely reads handwriting, understands messy
#     strikethroughs/arrows/math notation, but costs a Gemini API call
#     against your free-tier daily quota.
#   - Tesseract (ocr_utils): free, unlimited, fast, local — but it's a
#     classical OCR engine tuned for PRINTED/TYPED text. It performs
#     noticeably worse on genuine cursive/messy handwriting.
# "auto" tries Gemini first (best quality) and transparently falls back
# to Tesseract if the Gemini call fails for any reason (quota exhausted,
# network error, API outage) so a submission is never blocked.

def _gemini_transcribe_image(image_bytes: bytes, mime_type: str) -> str:
    model = _gemini_model()
    prompt = (
        "Transcribe this handwritten engineering exam answer sheet into clean "
        "digital text. Preserve mathematical notation as closely as possible "
        "using plain text (e.g. x^2, dV/dt, integral signs as 'integral of'). "
        "Preserve question numbers exactly as written. Do not solve or correct "
        "anything — transcribe only what is written, including any errors."
    )
    response = model.generate_content([{"mime_type": mime_type, "data": image_bytes}, prompt])
    return response.text


def _gemini_transcribe_pdf(pdf_bytes: bytes) -> str:
    model = _gemini_model()
    prompt = (
        "Transcribe all handwritten answers in this scanned PDF into clean "
        "digital text, preserving question numbers and mathematical notation. "
        "Do not solve or correct anything — transcribe only what is written."
    )
    response = model.generate_content([{"mime_type": "application/pdf", "data": pdf_bytes}, prompt])
    return response.text


def transcribe_answer(raw_bytes: bytes, filename: str, mime_type: str,
                       engine: str = "auto") -> tuple[str, str]:
    """Transcribes a submitted answer sheet (image or PDF) to plain text.

    engine:
      "gemini"    -> Gemini Vision only (best for real handwriting)
      "tesseract" -> Tesseract OCR only (free/unlimited, best for typed/printed scans)
      "auto"      -> try Gemini first, silently fall back to Tesseract on any error

    Returns (extracted_text, engine_actually_used) so the UI can show
    which one ran — useful to notice when a fallback happened.
    """
    is_pdf = mime_type == "application/pdf" or filename.lower().endswith(".pdf")

    def _run_tesseract() -> str:
        if is_pdf:
            return ocr_utils.extract_text_from_pdf_bytes(raw_bytes)
        return ocr_utils.extract_text_from_image_bytes(raw_bytes)

    def _run_gemini() -> str:
        if is_pdf:
            return _gemini_transcribe_pdf(raw_bytes)
        return _gemini_transcribe_image(raw_bytes, mime_type)

    if engine == "tesseract":
        return _run_tesseract(), "tesseract"

    if engine == "gemini":
        return _run_gemini(), "gemini"

    # engine == "auto"
    try:
        return _run_gemini(), "gemini"
    except Exception:
        return _run_tesseract(), "tesseract (Gemini fell back automatically)"


# ---------------------------------------------------------------
# Module B (part 2): Mock test generation via Groq
# ---------------------------------------------------------------
def generate_mock_test(subject_name: str, grey_areas: list[dict], course_material_summary: str,
                        num_numericals: int, num_derivations: int, num_hots: int,
                        num_mcq: int, critical_override: str = "") -> str:
    grey_areas_json = json.dumps(
        [{"topic": g["topic"], "avg_score": g["running_avg_score"]} for g in grey_areas],
        indent=2,
    ) if grey_areas else "[]"

    user_prompt = MOCK_TEST_GENERATION_PROMPT.format(
        subject_name=subject_name,
        grey_areas_json=grey_areas_json,
        course_material_summary=course_material_summary,
        num_numericals=num_numericals,
        num_derivations=num_derivations,
        num_hots=num_hots,
        num_mcq=num_mcq,
        critical_override=critical_override.strip() or "None provided.",
    )
    system_prompt = "You are an expert postgraduate engineering professor and examiner. Follow the output format exactly."
    return _groq_chat(system_prompt, user_prompt, temperature=0.6, max_tokens=8000)


def split_test_and_solution(full_markdown: str) -> tuple[str, str]:
    """Split the generated markdown into the student-visible test and the
    hidden solution key, based on the HIDDEN_SOLUTION_KEY_START/END markers."""
    start_marker = "## HIDDEN_SOLUTION_KEY_START"
    end_marker = "## HIDDEN_SOLUTION_KEY_END"

    if start_marker in full_markdown:
        visible_part, rest = full_markdown.split(start_marker, 1)
        solution_key = rest.split(end_marker, 1)[0] if end_marker in rest else rest
    else:
        # Fallback: model didn't use markers — treat everything after
        # "Hidden Solution Key" heading (any casing) as the key.
        match = re.search(r"##\s*Hidden Solution Key.*", full_markdown, re.IGNORECASE | re.DOTALL)
        if match:
            visible_part = full_markdown[: match.start()]
            solution_key = match.group(0)
        else:
            visible_part = full_markdown
            solution_key = "[No solution key detected — regenerate the test.]"

    return visible_part.strip(), solution_key.strip()


# ---------------------------------------------------------------
# Module C (part 2): Grading via Groq
# ---------------------------------------------------------------
def grade_submission(mock_test_with_solutions: str, student_submission: str) -> dict:
    user_prompt = EVALUATION_PROMPT.format(
        mock_test_with_solutions=mock_test_with_solutions,
        student_submission=student_submission,
    )
    system_prompt = "You are a strict, fair academic evaluator. Return only valid JSON."
    raw = _groq_chat(system_prompt, user_prompt, temperature=0.2, max_tokens=6000, json_mode=True)
    cleaned = _strip_json_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Surface a structured error rather than crashing the UI
        return {
            "total_score": 0,
            "max_score": 0,
            "percentage": 0,
            "question_evaluations": [],
            "overall_summary": f"GRADING PARSE ERROR: {e}. Raw model output was:\n{raw[:2000]}",
            "_parse_error": True,
        }


# ---------------------------------------------------------------
# Module D: Tutor chat via Groq
# ---------------------------------------------------------------
def tutor_reply(subject_name: str, grey_topics: list[str], history: list[dict], user_message: str) -> str:
    system_prompt = build_tutor_system_prompt(subject_name, grey_topics)
    messages = [{"role": "system", "content": system_prompt}]
    for turn in history[-20:]:  # cap context to last 20 turns
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    client = _groq_client()
    completion = client.chat.completions.create(
        model=_groq_model_name(),
        messages=messages,
        temperature=0.5,
        max_tokens=2000,
    )
    return completion.choices[0].message.content
