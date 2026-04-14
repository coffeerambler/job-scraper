-- Align Supabase schema with the job-scraper Python code.
-- Intended for projects that already have public.jobs with primary key id uuid and canonical columns
-- (url unique, title, company, description, source, country, match_score, match_reason, scraped_at, notified).
-- Safe to re-run: uses IF NOT EXISTS / idempotent patterns where possible.
--
-- Run in the Supabase SQL editor (or psql) as a privileged role.

-- ---------------------------------------------------------------------------
-- Extensions (usually present on Supabase)
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

-- ---------------------------------------------------------------------------
-- customized_resumes (required for tailored CV + PDF pipeline)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.customized_resumes (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    name text NOT NULL,
    email text NOT NULL,
    phone text,
    location text,
    summary text,
    skills text[],
    education jsonb,
    experience jsonb,
    projects jsonb,
    certifications jsonb,
    languages text[],
    links jsonb,
    created_at timestamptz DEFAULT now(),
    last_updated timestamptz DEFAULT now(),
    resume_link text
);

CREATE OR REPLACE FUNCTION public.update_customized_resumes_last_updated()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.last_updated := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS update_customized_resumes_last_updated ON public.customized_resumes;
CREATE TRIGGER update_customized_resumes_last_updated
  BEFORE UPDATE ON public.customized_resumes
  FOR EACH ROW
  EXECUTE FUNCTION public.update_customized_resumes_last_updated();

-- ---------------------------------------------------------------------------
-- base_resume (optional: store parsed JSON instead of committing resume.json)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.base_resume (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    resume_data jsonb NOT NULL,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.update_base_resume_updated_at_column()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS update_base_resume_updated_at ON public.base_resume;
CREATE TRIGGER update_base_resume_updated_at
  BEFORE UPDATE ON public.base_resume
  FOR EACH ROW
  EXECUTE FUNCTION public.update_base_resume_updated_at_column();

-- ---------------------------------------------------------------------------
-- jobs: columns used by scrapers, scoring, Discord, and resume workflows
-- (skip any that already exist)
-- ---------------------------------------------------------------------------
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS url text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS title text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS company text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS description text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS country text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS match_score smallint;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS match_reason text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS scraped_at timestamptz DEFAULT now();
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS notified boolean DEFAULT false;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS level text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS location text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS status text DEFAULT 'new';
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS job_state text DEFAULT 'new';
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS resume_score smallint;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS resume_score_stage text DEFAULT 'initial' NOT NULL;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS last_checked timestamptz DEFAULT now();
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS customized_resume_id uuid;

-- Foreign key to customized_resumes (add only if missing)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'jobs_customized_resume_id_fkey'
  ) THEN
    ALTER TABLE public.jobs
      ADD CONSTRAINT jobs_customized_resume_id_fkey
      FOREIGN KEY (customized_resume_id)
      REFERENCES public.customized_resumes (id)
      ON UPDATE CASCADE
      ON DELETE SET NULL;
  END IF;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

-- Unique listing URL (required for upsert on_conflict=url in the scraper)
CREATE UNIQUE INDEX IF NOT EXISTS jobs_url_unique ON public.jobs (url);

CREATE INDEX IF NOT EXISTS idx_jobs_country_match ON public.jobs (country, match_score);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON public.jobs (scraped_at);
CREATE INDEX IF NOT EXISTS idx_jobs_resume_score ON public.jobs (resume_score);

-- ---------------------------------------------------------------------------
-- Storage buckets (PDF uploads)
-- ---------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public)
VALUES ('resumes', 'resumes', false)
ON CONFLICT (id) DO NOTHING;

INSERT INTO storage.buckets (id, name, public)
VALUES ('personalized_resumes', 'personalized_resumes', false)
ON CONFLICT (id) DO NOTHING;
