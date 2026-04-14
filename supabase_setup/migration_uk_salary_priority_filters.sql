-- Add UK filtering/scoring support fields to jobs.
-- Safe to run multiple times.

ALTER TABLE public.jobs
  ADD COLUMN IF NOT EXISTS salary_min numeric,
  ADD COLUMN IF NOT EXISTS salary_max numeric,
  ADD COLUMN IF NOT EXISTS salary_currency text,
  ADD COLUMN IF NOT EXISTS salary_period text,
  ADD COLUMN IF NOT EXISTS priority_score integer DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_jobs_salary_max ON public.jobs (salary_max);
CREATE INDEX IF NOT EXISTS idx_jobs_priority_score ON public.jobs (priority_score DESC);

ALTER TABLE public.jobs
  DROP CONSTRAINT IF EXISTS jobs_salary_nonnegative_chk;

ALTER TABLE public.jobs
  ADD CONSTRAINT jobs_salary_nonnegative_chk
  CHECK (
    (salary_min IS NULL OR salary_min >= 0)
    AND (salary_max IS NULL OR salary_max >= 0)
  );
