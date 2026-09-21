# Adaptive AI Mock Test Engine & Personal Tutor

## Folder structure
```
mock_test_engine/
├── app.py                          # Streamlit entry point (run this)
├── config.py                       # Every tunable limit: upload caps, bucket name, prompt truncation
├── ocr_utils.py                    # NEW: converts every upload (image/PDF/txt) to plain text
├── storage_utils.py                # NEW: Supabase Storage helpers (the extracted .txt files)
├── db.py                           # All Supabase Postgres reads/writes
├── ai_clients.py                   # Gemini + Groq wrappers
├── prompts.py                      # Every system prompt, centralized
├── pdf_utils.py                    # Markdown/JSON -> downloadable PDF (now Unicode-safe)
├── schema.sql                      # Run once in Supabase SQL editor (creates tables + Storage bucket)
├── requirements.txt
├── packages.txt                    # NEW: apt packages for Streamlit Cloud (installs Tesseract OCR)
└── .streamlit/
    ├── config.toml                 # NEW: raises Streamlit's global upload size cap to 200 MB
    └── secrets.toml.example        # Copy -> secrets.toml, fill in keys (NEVER commit the real one)
```

## What changed in this version

1. **Fixed the PDF crash** (`FPDFUnicodeEncodingException`). fpdf2's core fonts only
   support Latin-1; AI-generated exams contain real Unicode math symbols (θ, ≤, ≥, °,
   superscripts). `pdf_utils.py` now sanitizes every string through a symbol map
   (θ→"theta", ≤→"<=", etc.) before it reaches fpdf, with a safe fallback for anything
   else. This also means downloadable PDFs work for both the mock test AND the
   evaluation report (objective 3) — same fix covers both.

2. **Persistent, cascade-safe storage per subject.** Deleting a subject now:
   - fetches every Storage object path for that subject's materials
   - deletes those Storage objects explicitly (Postgres's `ON DELETE CASCADE` only
     covers Postgres rows — it has no idea Storage objects exist)
   - deletes the subject row, which cascades through `subject_materials`,
     `mock_tests`, `topic_analytics`, `evaluations`, and `tutor_messages` automatically

3. **OCR-first pipeline** (`ocr_utils.py`). Every upload — PNG, JPG, or PDF — is
   converted to plain text BEFORE anything else touches it:
   - `.txt` / `.md` → read directly
   - images → Tesseract OCR via Pillow
   - PDFs → tries `pypdf`'s embedded text layer first (fast, for "born-digital" PDFs);
     if that yields too little text per page, falls back to rendering each page with
     PyMuPDF and OCR'ing the rendered image (for scanned/photographed material)

   The extracted text is what gets saved and what gets fed to any AI model — Gemini
   never receives raw file bytes for course materials anymore.

   **The Evaluate tab now offers both OCR engines, picked by suitability**
   (`ai_clients.transcribe_answer`):
   - **Gemini Vision** — genuinely reads handwriting, understands messy
     strikethroughs/math notation. Costs a Gemini API call against your free-tier
     daily quota. Default for camera photos (usually handwritten).
   - **Tesseract OCR** — free, unlimited, local. Strong on typed/printed scans,
     noticeably weaker on real handwriting. Default option for uploaded scans, since
     those could be either.
   - **Auto** — tries Gemini first, silently falls back to Tesseract if the Gemini
     call fails for any reason (quota exhausted, network error), so a submission is
     never blocked. The UI shows a small caption confirming which engine actually ran.

4. **Multi-file upload, txt-only storage.** All three uploaders accept PNG, PDF, or
   TXT, and Notes/PYQs accept multiple files at once. Whatever format you upload, only
   the extracted `.txt` is ever stored — in a private Supabase Storage bucket
   (`materials`), not inline in Postgres.

5. **Syllabus replaces, Notes/PYQs accumulate**, exactly as specified. Uploading a new
   syllabus deletes the previous one (DB row + Storage object) first. Notes and PYQs
   keep every file you've ever uploaded for that subject.

6. **Upload caps**, enforced in the app before OCR even runs (see `config.py`):

   | Material | Per-file cap | Cumulative cap |
   |---|---|---|
   | Syllabus | 1 MB | n/a (replaces) |
   | Notes | 200 MB | 500 MB per subject |
   | PYQs | 50 MB | none specified |

## Free-tier verification (objective 7) — what I checked and what it means

**Supabase Storage, free tier:**
- Hard cap of **50 MB per single uploaded object** — cannot be raised on the free
  plan no matter what your app or bucket settings say.
- **~1 GB total Storage, ~500 MB total Postgres database**, shared across your whole
  project (all subjects combined).

This is why the caps above are enforced on the **raw uploaded file**, not on what
ends up stored. Because only the OCR'd text is saved (not the original PDF/image),
even a "full size" 200 MB notes upload typically produces a `.txt` object well under
a few MB — comfortably inside the 50 MB per-object cap. A subject would need an
enormous, unrealistic amount of *extracted text* (not source file size) to meaningfully
threaten the 1 GB total Storage quota. Postgres itself only ever stores a pointer
(`storage_path`) plus small metadata per material — never the full text — so the
500 MB database cap isn't touched by material volume at all.

**Practical implication:** the numbers you asked for (1 MB / 200 MB / 500 MB / 50 MB)
work as *input* limits on the free tier. If you ever hit the 1 GB total Storage
ceiling in practice (unlikely for personal use, but possible with many subjects over
a long time), the fix is either deleting old subjects you no longer need (which now
correctly frees the Storage too) or upgrading to Supabase Pro ($25/mo, 100 GB storage).

**Groq, free tier** (`gpt-oss-120b`): 30 requests/min, 14,400 requests/day,
1,000,000 tokens/day — generous for personal-scale test generation and grading.
`config.MAX_SUMMARY_CHARS_PER_MATERIAL` (15,000 chars ≈ 4,000 tokens per material)
keeps a single generation request from blowing the per-request token budget even if
a subject has many large materials uploaded.

**Google AI Studio (Gemini), free tier**: used only for (a) summarizing extracted
material text into a dense academic summary, and (b) OCR of handwritten answer
submissions in the Evaluate tab. Check your current model's exact daily quota at
aistudio.google.com — Google's free-tier numbers vary by model and do change.

**Streamlit Community Cloud**: free for personal apps, no card required. Its own
global upload-size setting (`.streamlit/config.toml`, `maxUploadSize`) is now set to
200 to match the largest per-file cap (notes) — without this, the browser would
reject a 200 MB notes upload before your app code ever ran, independent of the caps
in `config.py`.

## Setup

### 1. Supabase
1. Create a project at supabase.com (or use the fresh one you just made).
2. **SQL Editor → New query** → paste the entire contents of `schema.sql` → Run.
   This creates all 6 tables AND the private `materials` Storage bucket with its
   access policies in one step — no separate dashboard clicking needed.
3. **Project Settings → API** → copy the Project URL and the `anon public` key.

### 2. API keys
- Google AI Studio: https://aistudio.google.com/apikey
- Groq Cloud: https://console.groq.com/keys

### 3. Local development
```bash
# Tesseract must be installed locally too (it's a system binary, not a pip package)
# Mac:   brew install tesseract
# Linux: sudo apt install tesseract-ocr
# Windows: https://github.com/UB-Mannheim/tesseract/wiki (installer)

cd mock_test_engine
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml and fill in your real keys

streamlit run app.py
```

### 4. Deploy to Streamlit Community Cloud
1. Push this whole folder to a GitHub repo (`packages.txt` and `.streamlit/config.toml`
   are safe to commit — neither contains secrets).
2. On share.streamlit.io: **New app** → point at your repo → Main file path `app.py`
   (or `mock_test_engine/app.py` if the repo has the folder nested one level).
3. **Advanced settings → Secrets**: paste your real keys (same format as
   `secrets.toml.example`).
4. Deploy. Streamlit Cloud reads `packages.txt` automatically and installs
   `tesseract-ocr` via apt before your app starts — no manual step needed.

## How the modules map to the code

| Module | Where it lives |
|---|---|
| A. Subject & Memory Management (incl. cascade delete) | `sidebar_subject_manager()` in app.py; db.py; storage_utils.py |
| B. Mock Test Engine (OCR-first uploads, caps, generation) | `tab_generate()` in app.py; ocr_utils.py; storage_utils.py; `generate_mock_test`/`split_test_and_solution` in ai_clients.py |
| C. Evaluation Engine | `tab_evaluate()` in app.py; `transcribe_handwritten_answer`, `grade_submission` in ai_clients.py |
| D. Personal AI Tutor | `tab_tutor()` in app.py; `tutor_reply` in ai_clients.py |
