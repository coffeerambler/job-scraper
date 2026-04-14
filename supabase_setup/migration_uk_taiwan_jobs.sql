-- UK/Taiwan scoring columns only. For full alignment (uuid PK, resumes, storage, url unique),
-- run migration_align_jobs_for_python.sql instead or in addition.

ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS country text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS url text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS match_score smallint;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS match_reason text;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS notified boolean DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_jobs_country_match ON public.jobs (country, match_score);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON public.jobs (url);
