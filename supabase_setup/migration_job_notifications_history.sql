-- Prevent duplicate notifications across days/reruns by tracking sent URLs.
-- Safe to run multiple times.

CREATE TABLE IF NOT EXISTS public.job_notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_url text NOT NULL,
  country text NOT NULL,
  channel text NOT NULL DEFAULT 'discord',
  sent_at timestamptz NOT NULL DEFAULT now(),
  match_score smallint,
  job_id uuid
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_job_notifications_once
  ON public.job_notifications (job_url, country, channel);

CREATE INDEX IF NOT EXISTS idx_job_notifications_country_sent
  ON public.job_notifications (country, sent_at DESC);

ALTER TABLE public.job_notifications ENABLE ROW LEVEL SECURITY;

-- Service role policy: full access for backend scripts (idempotent create)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'job_notifications'
      AND policyname = 'job_notifications_service_role_all'
  ) THEN
    CREATE POLICY job_notifications_service_role_all
      ON public.job_notifications
      FOR ALL
      TO service_role
      USING (true)
      WITH CHECK (true);
  END IF;
END
$$;
