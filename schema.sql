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

-- 2. Extracted knowledge base per subject (syllabus / notes / PYQ summaries)
create table if not exists subject_materials (
    id uuid primary key default gen_random_uuid(),
    subject_id uuid not null references subjects(id) on delete cascade,
    material_type text not null check (material_type in ('syllabus', 'notes', 'pyq')),
    source_filename text,
    extracted_summary text not null,      -- dense academic summary produced by Gemini
    created_at timestamptz not null default now()
);

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
