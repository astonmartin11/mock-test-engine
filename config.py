"""
Central place for every tunable limit in the app: upload size caps,
the Supabase Storage bucket name, and how much extracted text gets
sent to Groq per generation call.

--- Free-tier reality check (verified against current provider docs) ---
- Supabase Storage (free tier): hard cap of 50 MB per SINGLE uploaded
  object, cannot be raised on the free plan; ~1 GB total storage;
  ~500 MB total Postgres database, shared across your whole project.
- Because this app stores only the OCR'd/extracted TEXT of each
  upload (not the original PDF/image), the caps below govern the
  raw file a user is allowed to upload — the resulting .txt saved to
  Storage is almost always a tiny fraction of that size, so it
  comfortably fits the 50 MB per-object cap even for a "full size"
  notes upload. Cumulative caps below track the RAW uploaded bytes,
  not the stored text size, so they reflect what you actually asked
  for as input limits.
- Streamlit Cloud's own global upload widget cap (server.maxUploadSize
  in .streamlit/config.toml) must be >= the largest single-file cap
  below (200 MB for notes) or the browser will reject the upload
  before your app code ever sees it.
"""

# ---------------------------------------------------------------
# Upload caps (bytes) — as specified
# ---------------------------------------------------------------
SYLLABUS_MAX_BYTES = 1 * 1024 * 1024                     # 1 MB, single file, replaces previous
NOTES_MAX_FILE_BYTES = 200 * 1024 * 1024                 # 200 MB per single upload
NOTES_MAX_TOTAL_BYTES_PER_SUBJECT = 500 * 1024 * 1024    # 500 MB cumulative (raw) per subject
PYQ_MAX_FILE_BYTES = 50 * 1024 * 1024                    # 50 MB per single upload

# Accepted upload types for the material uploaders (objective: png/pdf/txt in, txt stored)
ACCEPTED_MATERIAL_TYPES = ["pdf", "png", "jpg", "jpeg", "txt", "md"]

# ---------------------------------------------------------------
# Supabase Storage
# ---------------------------------------------------------------
MATERIALS_BUCKET = "materials"   # created by schema.sql; holds extracted .txt only

# ---------------------------------------------------------------
# Prompt-size safety valve
# ---------------------------------------------------------------
# Groq free-tier models have per-minute AND per-day token ceilings.
# Even though the full extracted text of every material is stored in
# Supabase Storage in full, only a bounded slice of the DENSE SUMMARY
# per material is concatenated into the mock-test generation prompt,
# so one huge notes upload can't blow the whole request's token budget.
MAX_SUMMARY_CHARS_PER_MATERIAL = 15_000   # ~4,000 tokens per material, generous for a summary

# ---------------------------------------------------------------
# OCR behavior
# ---------------------------------------------------------------
# If a PDF's embedded text layer yields fewer than this many characters
# per page on average, we treat it as a scanned/image PDF and fall back
# to rendering each page and running Tesseract OCR on it.
OCR_FALLBACK_CHARS_PER_PAGE_THRESHOLD = 40
OCR_RENDER_DPI = 200

# ---------------------------------------------------------------
# Handwriting routing (Evaluate tab): local Tesseract OCR vs Gemini
# Vision. Tesseract is free/unlimited but reads handwriting poorly;
# Gemini Vision handles handwriting and math notation far better but
# has a daily quota. Tesseract runs FIRST on every submission (free);
# its own per-word confidence score is used to decide whether the
# result is trustworthy (typed/printed content) or needs escalating
# to Gemini Vision (handwritten/messy content) — this keeps Gemini
# quota reserved for the submissions that actually need it.
HANDWRITING_CONFIDENCE_THRESHOLD = 60.0   # Tesseract avg word confidence (0-100) below this -> escalate
HANDWRITING_MIN_CHARS_LOCAL = 20          # too little text read locally -> escalate regardless of confidence
