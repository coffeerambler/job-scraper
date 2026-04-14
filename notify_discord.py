"""
Post high-scoring unnotified jobs to Discord, then mark them notified.
Usage: python notify_discord.py uk | taiwan
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

import requests

import config
import supabase_utils

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _webhook_for_country(country: str) -> str | None:
    if country == config.COUNTRY_UK:
        return os.environ.get("DISCORD_WEBHOOK_UK")
    if country == config.COUNTRY_TAIWAN:
        return os.environ.get("DISCORD_WEBHOOK_TAIWAN")
    return None


def _format_scraped_at(val) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


def notify_country(country: str) -> None:
    webhook = _webhook_for_country(country)
    if not webhook:
        logging.error("Missing Discord webhook env for country %s.", country)
        return

    threshold = getattr(config, "MATCH_SCORE_THRESHOLD", 7)
    jobs = supabase_utils.get_unnotified_matches(country, threshold)
    if not jobs:
        logging.info("No unnotified matches for %s above threshold %s.", country, threshold)
        return

    cap = getattr(config, "MAX_DAILY_NOTIFICATIONS", 5)
    if cap <= 0:
        logging.info("MAX_DAILY_NOTIFICATIONS is %s; skipping Discord posts.", cap)
        return

    jobs_sorted = sorted(
        jobs,
        key=lambda j: (
            j.get("match_score") is None,  # scored jobs first
            -(j.get("match_score") or 0),
            -(j.get("priority_score") or 0),
        ),
    )
    jobs_to_notify = jobs_sorted[:cap]
    if len(jobs) > len(jobs_to_notify):
        logging.info(
            "Capping Discord notifications at %s/%s (highest match_score first; others remain unnotified).",
            cap,
            len(jobs),
        )

    ids: list[str] = []
    sent_records: list[dict] = []
    for job in jobs_to_notify:
        jid = job.get("job_id") or job.get("id")
        if not jid:
            continue
        url = job.get("url") or ""
        if not url:
            logging.warning("Job %s missing url; skipping Discord post.", jid)
            continue

        embed = {
            "embeds": [
                {
                    "title": (job.get("job_title") or job.get("title") or "Job")[:256],
                    "description": ((job.get("match_reason") or "")[:4090]),
                    "url": url,
                    "color": 5814783,
                    "fields": [
                        {"name": "Company", "value": (job.get("company") or "—")[:1024], "inline": True},
                        {
                            "name": "Score",
                            "value": (
                                f"{job.get('match_score')}/10"
                                if job.get("match_score") is not None
                                else f"Priority {job.get('priority_score') or 0}"
                            ),
                            "inline": True,
                        },
                        {"name": "Source", "value": (job.get("source") or "—")[:1024], "inline": True},
                    ],
                    "footer": {"text": f"Scraped {_format_scraped_at(job.get('scraped_at'))}"},
                }
            ]
        }
        try:
            r = requests.post(webhook, json=embed, timeout=30)
            r.raise_for_status()
            ids.append(str(jid))
            sent_records.append(
                {
                    "job_url": url,
                    "country": country,
                    "channel": "discord",
                    "match_score": job.get("match_score"),
                    "job_id": str(jid),
                }
            )
            logging.info("Posted Discord notification for job_id=%s", jid)
        except Exception as e:
            logging.warning("Discord post failed for job_id=%s: %s", jid, e)

    if ids:
        supabase_utils.mark_jobs_notified(ids)
    if sent_records:
        supabase_utils.record_job_notifications(sent_records)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logging.error("Usage: python notify_discord.py uk|taiwan")
        sys.exit(1)
    c = sys.argv[1].strip().lower()
    if c not in (config.COUNTRY_UK, config.COUNTRY_TAIWAN):
        logging.error("Country must be %s or %s.", config.COUNTRY_UK, config.COUNTRY_TAIWAN)
        sys.exit(1)
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
        logging.error("Supabase environment not configured.")
        sys.exit(1)
    notify_country(c)
