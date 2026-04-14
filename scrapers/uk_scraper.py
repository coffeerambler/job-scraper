"""
UK job sources: Adzuna API, Reed API, Arbeitnow API.
Fetch functions return dicts: url, title, company, description, source, country='uk'.
"""

from __future__ import annotations

import logging
import os
import random
from typing import Any
import requests

import config
import user_agents

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

REQUEST_TIMEOUT = getattr(config, "REQUEST_TIMEOUT", 30)
ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/gb/search/1"
REED_SEARCH = "https://www.reed.co.uk/api/1.0/search"
ARBEITNOW_API = "https://www.arbeitnow.com/api/job-board-api"


def _headers() -> dict[str, str]:
    return {"User-Agent": random.choice(user_agents.USER_AGENTS), "Accept": "application/json"}


def fetch_adzuna_jobs(query: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_API_KEY")
    if not app_id or not app_key:
        logging.warning("Adzuna: missing ADZUNA_APP_ID or ADZUNA_API_KEY; skipping.")
        return out
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": query,
        "results_per_page": 20,
        "content-type": "application/json",
    }
    try:
        r = requests.get(ADZUNA_BASE, params=params, headers=_headers(), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logging.warning("Adzuna request failed for query %r: %s", query, e)
        return out

    for item in data.get("results") or []:
        url = item.get("redirect_url") or item.get("adref")
        title = (item.get("title") or "").strip()
        company = (item.get("company", {}).get("display_name") if isinstance(item.get("company"), dict) else None) or (
            item.get("company") or ""
        )
        if isinstance(company, dict):
            company = company.get("display_name") or ""
        company = str(company).strip()
        desc = item.get("description") or ""
        if isinstance(desc, dict):
            desc = desc.get("text") or str(desc)
        desc = str(desc).strip()
        if not url or not title:
            continue
        out.append(
            {
                "url": url,
                "title": title,
                "company": company or "Unknown",
                "description": desc,
                "source": "adzuna",
                "country": config.COUNTRY_UK,
            }
        )
    return out


def fetch_reed_jobs(query: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    api_key = os.environ.get("REED_API_KEY")
    if not api_key:
        logging.warning("Reed: missing REED_API_KEY; skipping.")
        return out
    try:
        r = requests.get(
            REED_SEARCH,
            params={"keywords": query},
            headers=_headers(),
            auth=(api_key, ""),
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logging.warning("Reed request failed for query %r: %s", query, e)
        return out

    for item in data.get("results") or []:
        url = item.get("jobUrl") or item.get("url")
        title = (item.get("jobTitle") or item.get("title") or "").strip()
        company = (item.get("employerName") or item.get("company") or "").strip()
        desc = item.get("jobDescription") or item.get("description") or ""
        desc = str(desc).strip()
        if not url or not title:
            continue
        out.append(
            {
                "url": url,
                "title": title,
                "company": company or "Unknown",
                "description": desc,
                "source": "reed",
                "country": config.COUNTRY_UK,
            }
        )
    return out


_UK_CITIES = (
    "london",
    "manchester",
    "birmingham",
    "leeds",
    "glasgow",
    "liverpool",
    "bristol",
    "edinburgh",
    "cardiff",
    "belfast",
    "oxford",
    "cambridge",
    "reading",
    "nottingham",
    "sheffield",
)


def _arbeitnow_is_uk(job: dict[str, Any]) -> bool:
    loc = (job.get("location") or job.get("city") or "") or ""
    if isinstance(loc, str):
        s = loc.lower()
        if "united kingdom" in s or s.endswith(" uk") or s == "uk":
            return True
        if "england" in s or "scotland" in s or "wales" in s or "northern ireland" in s:
            return True
        for c in _UK_CITIES:
            if c in s:
                return True
    tags = job.get("tags") or []
    if isinstance(tags, list):
        for t in tags:
            tl = str(t).lower()
            if tl in ("uk", "united kingdom", "britain", "gb"):
                return True
    desc = (job.get("description") or "")[:4000].lower()
    if "united kingdom" in desc and ("remote" in desc or "uk" in desc):
        return True
    return False


def fetch_arbeitnow_uk_jobs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in (1, 2, 3):
        try:
            r = requests.get(
                ARBEITNOW_API,
                params={"page": page},
                headers=_headers(),
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            logging.warning("Arbeitnow request failed (page %s): %s", page, e)
            break

        items = payload.get("data") if isinstance(payload, dict) else []
        if not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            if not _arbeitnow_is_uk(item):
                continue
            url = item.get("url") or item.get("apply_url") or item.get("link")
            title = (item.get("title") or item.get("name") or "").strip()
            company = (item.get("company_name") or item.get("company") or "").strip()
            desc = item.get("description") or item.get("body") or ""
            desc = str(desc).strip()
            if not url or not title:
                continue
            out.append(
                {
                    "url": url,
                    "title": title,
                    "company": company or "Unknown",
                    "description": desc,
                    "source": "arbeitnow",
                    "country": config.COUNTRY_UK,
                }
            )
    return out


def fetch_all_uk_jobs() -> list[dict[str, Any]]:
    """Aggregate all UK sources and deduplicate by URL."""
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []

    for query in config.UK_SEARCH_QUERIES:
        for batch in (fetch_adzuna_jobs(query), fetch_reed_jobs(query)):
            for j in batch:
                u = (j.get("url") or "").strip()
                if not u or u in seen:
                    continue
                seen.add(u)
                merged.append(j)

    for j in fetch_arbeitnow_uk_jobs():
        u = (j.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        merged.append(j)

    logging.info("UK scrape total unique URLs: %s", len(merged))
    return merged


if __name__ == "__main__":
    import supabase_utils

    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
        logging.error("Supabase env not set.")
        raise SystemExit(1)

    jobs = fetch_all_uk_jobs()
    inserted = 0
    for job in jobs:
        if supabase_utils.insert_job_if_new(job):
            inserted += 1
    logging.info("UK scrape finished; inserted %s new job(s).", inserted)
