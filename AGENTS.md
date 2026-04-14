# Job Scraper Agent Instructions

## Project Overview
Forked from anandanair/job-scraper. Modified for UK and Taiwan job hunting.
Python scripts running on GitHub Actions, not a web app.

## Key Decisions
- Two bots: UK (Adzuna, Reed, Arbeitnow) and Taiwan (104.com.tw, Meet.jobs, Tealit, Yourator)
- Single Supabase `jobs` table with `country` column (`uk` | `taiwan`), `url`, `match_score` (1–10), `match_reason`, `notified`
- Notifications via Discord webhooks, not email
- AI matching via Gemini through `llm_client.py` (LiteLLM)
- CV generation is manual only — workflow `generate_cv.yml` (`workflow_dispatch` with `job_id` input)
- CV target: max 2 pages A4 (enforced in `pdf_generator.py` with 11pt then 10pt fallback)

## What We Kept From Fork
- llm_client.py — do not modify
- models.py — only add fields, don't remove
- resume_parser.py — do not modify
- supabase_utils.py — extend only
- user_agents.py — do not modify
- GitHub Actions: `score_jobs.yml`, `job_manager.yml`, `parse_resume.yml` unchanged

## What We Replaced / Added
- `scrapers/uk_scraper.py`, `scrapers/taiwan_scraper.py` — country scrapers (insert via `__main__` using `insert_job_if_new`)
- `hourly_resume_customization.yml` — replaced by `generate_cv.yml`
- `scrape_uk.yml` / `scrape_taiwan.yml` — daily 07:00 UTC: scrape → `score_jobs.py <country>` → `notify_discord.py <country>`
- `notify_discord.py` — Discord embeds for high scores
- `supabase_setup/migration_uk_taiwan_jobs.sql` — adds `country`, `url`, `match_score`, `match_reason`, `notified` if missing

## Supabase
- Run `supabase_setup/init.sql` for base schema; run `migration_uk_taiwan_jobs.sql` for UK/Taiwan matching columns.
- Use service role key for all operations (never anon key).

## Environment Variables (GitHub Secrets)

**Shared**
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `LLM_API_KEY` (Gemini / LiteLLM)

**Discord**
- `DISCORD_WEBHOOK_UK`
- `DISCORD_WEBHOOK_TAIWAN`

**UK scrape only**
- `ADZUNA_APP_ID`
- `ADZUNA_API_KEY` (Adzuna app key; also readable as `ADZUNA_API_KEY` in env)
- `REED_API_KEY` (Reed API key; HTTP Basic username)

**Taiwan scrape**
- No extra API keys (HTML + Meet.jobs public API only).

**Manual CV workflow (`generate_cv.yml`)**
- Same as shared: `SUPABASE_*`, `LLM_API_KEY`.
