-- ============================================================
-- Adaptive AI Mock Test Engine — Supabase Schema
-- Run this once in Supabase Dashboard -> SQL Editor -> New Query
-- ============================================================

-- 1. Subjects the student is tracking
create table if not exists subjects (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    created_at timestamptz not null default now()
);

-- 2. Extracted knowledge base per subject (syllabus / notes / PYQ)
-- The full extracted text of each upload lives in Supabase STORAGE
-- (bucket 'materials', see below) — this table only stores a pointer
-- (storage_path) plus small metadata and the dense AI summary, so a
-- subject's materials never threaten the 500 MB free Postgres quota
-- no matter how much text has been uploaded over time.
create table if not exists subject_materials (
    id uuid primary key default gen_random_uuid(),
    subject_id uuid not null references subjects(id) on delete cascade,
    material_type text not null check (material_type in ('syllabus', 'notes', 'pyq')),
    source_filename text,
    storage_path text not null,           -- path of the extracted .txt object in Storage
    file_size_bytes bigint not null default 0,  -- RAW uploaded file size (pre-OCR), for cap tracking
    char_count integer not null default 0,      -- length of the extracted text
    extracted_summary text not null,      -- dense academic summary produced by Gemini
    created_at timestamptz not null default now()
);

-- Storage bucket for extracted material text (.txt only). Private —
-- only accessible via the app's Supabase key, never publicly readable.
insert into storage.buckets (id, name, public, file_size_limit)
values ('materials', 'materials', false, 52428800)  -- 50 MB hard cap (Supabase free-tier max)
on conflict (id) do nothing;

-- Storage's own tables (storage.objects) have Row Level Security ON by
-- default, unlike the plain tables above — without these policies the
-- anon key gets silently denied on every upload/download/delete. This
-- app is a personal single-user tool authenticated only by possession
-- of the anon key, so these policies grant full access to that bucket
-- only (not to any other bucket you might add later).
drop policy if exists "materials_insert" on storage.objects;
create policy "materials_insert" on storage.objects
    for insert to anon with check (bucket_id = 'materials');

drop policy if exists "materials_select" on storage.objects;
create policy "materials_select" on storage.objects
    for select to anon using (bucket_id = 'materials');

drop policy if exists "materials_delete" on storage.objects;
create policy "materials_delete" on storage.objects
    for delete to anon using (bucket_id = 'materials');

-- 3. Generated mock tests (questions + hidden solution key persisted together)
create table if not exists mock_tests (
    id uuid primary key default gen_random_uuid(),
    subject_id uuid not null references subjects(id) on delete cascade,
    config jsonb not null,                -- {numericals: 2, derivations: 1, hots: 2, mcq: 3, override: "..."}
    grey_areas_used jsonb,                -- snapshot of grey areas at generation time
    test_markdown text not null,          -- full visible test (Sections A/B/C)
    solution_key text not null,           -- hidden solution key (never shown to student pre-submit)
    created_at timestamptz not null default now()
);

-- 4. Per-topic performance tracking -> drives the "grey area" retrieval
create table if not exists topic_analytics (
    id uuid primary key default gen_random_uuid(),
    subject_id uuid not null references subjects(id) on delete cascade,
    topic text not null,
    latest_score numeric,                 -- 0-10 scale, most recent attempt on this topic
    attempts_count integer not null default 0,
    running_avg_score numeric,            -- cumulative average, used for trend display
    is_grey_area boolean not null default false,  -- true when running_avg_score < 6
    last_feedback text,
    updated_at timestamptz not null default now(),
    unique (subject_id, topic)
);

-- 5. Individual evaluation attempts (one row per submitted mock test)
create table if not exists evaluations (
    id uuid primary key default gen_random_uuid(),
    mock_test_id uuid not null references mock_tests(id) on delete cascade,
    subject_id uuid not null references subjects(id) on delete cascade,
    submission_type text not null check (submission_type in ('text', 'camera', 'pdf')),
    transcribed_answer text,              -- Gemini Vision OCR output, if applicable
    result_json jsonb not null,           -- full grading JSON returned by Groq
    total_score numeric,
    max_score numeric,
    percentage numeric,
    created_at timestamptz not null default now()
);

-- 6. Tutor chat history (per subject, so context persists across sessions)
create table if not exists tutor_messages (
    id uuid primary key default gen_random_uuid(),
    subject_id uuid not null references subjects(id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    created_at timestamptz not null default now()
);

-- Helpful indexes
create index if not exists idx_materials_subject on subject_materials(subject_id);
create index if not exists idx_tests_subject on mock_tests(subject_id);
create index if not exists idx_topics_subject on topic_analytics(subject_id);
create index if not exists idx_topics_grey on topic_analytics(subject_id, is_grey_area);
create index if not exists idx_evals_subject on evaluations(subject_id);
create index if not exists idx_tutor_subject on tutor_messages(subject_id, created_at);
