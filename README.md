# Adaptive AI Mock Test Engine & Personal Tutor

## File structure
```
mock_test_engine/
├── app.py                          # Streamlit entry point (run this)
├── db.py                           # All Supabase reads/writes
├── ai_clients.py                   # Gemini + Groq wrappers
├── prompts.py                      # Every system prompt, centralized
├── pdf_utils.py                    # Markdown/JSON -> downloadable PDF
├── schema.sql                      # Run once in Supabase SQL editor
├── requirements.txt
└── .streamlit/
    └── secrets.toml.example        # Copy -> secrets.toml, fill in keys
```

## 1. Supabase setup
1. Create a project at supabase.com.
2. Open **SQL Editor** → paste the entire contents of `schema.sql` → Run.
   This creates all 6 tables (`subjects`, `subject_materials`, `mock_tests`,
   `topic_analytics`, `evaluations`, `tutor_messages`) with the indexes
   the app relies on.
3. Go to **Project Settings → API** and copy the `Project URL` and the
   `anon public` key (or `service_role` key if you want to bypass RLS
   entirely for a single-user personal tool).

## 2. API keys
- **Google AI Studio**: https://aistudio.google.com/apikey → free Gemini 1.5
  Flash key.
- **Groq Cloud**: https://console.groq.com/keys → free API key. Pick a model
  string, e.g. `llama-3.3-70b-versatile` or a Qwen model currently listed
  under https://console.groq.com/docs/models.

## 3. Local development
```bash
cd mock_test_engine
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml and fill in your real keys

streamlit run app.py
```

## 4. Deploy to Streamlit Community Cloud
1. Push this folder to a GitHub repo.
2. On https://share.streamlit.io, click **New app**, point it at the repo
   and `app.py`.
3. In the app's **Settings → Secrets**, paste the same keys as in
   `secrets.toml.example` (do NOT commit your real secrets.toml to GitHub —
   it's already excluded by convention; add a `.gitignore` entry for
   `.streamlit/secrets.toml` if you keep one).

## How the modules map to the code

| Module | Where it lives |
|---|---|
| A. Subject & Memory Management | `sidebar_subject_manager()`, `tab_analytics()` in app.py; all of db.py |
| B. Mock Test Engine | `tab_generate()` in app.py; `extract_document_summary`, `generate_mock_test`, `split_test_and_solution` in ai_clients.py |
| C. Evaluation Engine | `tab_evaluate()` in app.py; `transcribe_handwritten_answer`, `grade_submission` in ai_clients.py |
| D. Personal AI Tutor | `tab_tutor()` in app.py; `tutor_reply`, `build_tutor_system_prompt` |

## Design notes / things you may want to tune
- **Grey-area math**: a topic becomes a grey area when its running average
  score drops below 6/10 (`db.upsert_topic_score`). Adjust the `6.0`
  threshold there if you want it stricter/looser.
- **Hidden solution key persistence**: the generation prompt asks the model
  to wrap the key between `## HIDDEN_SOLUTION_KEY_START` / `_END` markers so
  `split_test_and_solution()` can reliably separate the student-visible test
  from the key before storing both in `mock_tests`. If your model ever drops
  the markers, there's a regex fallback, but it's worth checking the raw
  output the first few times you run it.
- **Large PDFs**: `extract_from_file()` sends the raw PDF bytes straight to
  Gemini (leaning on its long context + native PDF understanding) instead of
  relying on `pypdf` text extraction, which is more robust for slide decks
  with lots of diagrams/scanned pages. `pypdf` is tried first as a cheaper
  path when the PDF has clean embedded text.
- **JSON grading reliability**: `ai_clients.grade_submission` uses Groq's
  `response_format: json_object` mode plus a defensive fence-stripper. If
  parsing still fails, the UI shows the raw model output instead of crashing
  so you can debug the prompt rather than losing the student's submission.
