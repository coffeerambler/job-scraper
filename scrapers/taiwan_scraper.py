"""
Taiwan job sources: Meet.jobs API, Tealit, Yourator, 104.com.tw (HTML scraping).
Each fetch returns dicts: url, title, company, description, source, country='taiwan'.
"""

from __future__ import annotations

import logging
import random
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

import config
import user_agents

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

REQUEST_TIMEOUT = getattr(config, "REQUEST_TIMEOUT", 30)
MEET_JOBS_API = "https://meet.jobs/api/v1/jobs"
TEALIT_LIST = "https://www.tealit.com/job_listings/"
YOURATOR_BASE = "https://www.yourator.co/jobs"
AREA_TAIPEI = "6001001000"


def _headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(user_agents.USER_AGENTS),
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
    }


def fetch_meet_jobs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        r = requests.get(
            MEET_JOBS_API,
            params={"location": "taiwan"},
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logging.warning("Meet.jobs API failed: %s", e)
        return out

    rows = data if isinstance(data, list) else data.get("data") or data.get("jobs") or []
    if not isinstance(rows, list):
        return out

    for item in rows:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("job_url") or item.get("link")
        title = (item.get("title") or item.get("name") or "").strip()
        company = (item.get("company") or item.get("company_name") or "").strip()
        if isinstance(company, dict):
            company = (company.get("name") or "").strip()
        desc = item.get("description") or item.get("content") or ""
        desc = str(desc).strip()
        if not url or not title:
            continue
        if not str(url).startswith("http"):
            url = urljoin("https://meet.jobs/", str(url).lstrip("/"))
        out.append(
            {
                "url": url,
                "title": title,
                "company": company or "Unknown",
                "description": desc,
                "source": "meet.jobs",
                "country": config.COUNTRY_TAIWAN,
            }
        )
    return out


def fetch_tealit() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        r = requests.get(TEALIT_LIST, headers=_headers(), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        logging.warning("Tealit scrape failed: %s", e)
        return out

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 4:
            continue
        if "/job" not in href.lower() and "job_listing" not in href.lower() and "position" not in href.lower():
            continue
        if href.startswith("/"):
            href = urljoin("https://www.tealit.com/", href)
        if not href.startswith("http"):
            continue
        out.append(
            {
                "url": href,
                "title": text[:500],
                "company": "Unknown",
                "description": "",
                "source": "tealit",
                "country": config.COUNTRY_TAIWAN,
            }
        )

    if not out:
        logging.warning("Tealit: no job links parsed (layout may have changed).")
    return out


def fetch_yourator() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        r = requests.get(
            YOURATOR_BASE,
            params={"category": "", "location": "taipei"},
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        logging.warning("Yourator scrape failed: %s", e)
        return out

    for a in soup.select('a[href*="/jobs/"]'):
        href = a.get("href", "").strip()
        if not href or "/jobs/" not in href:
            continue
        if href.count("/") < 3:
            continue
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        if href.startswith("/"):
            href = urljoin("https://www.yourator.co/", href)
        out.append(
            {
                "url": href,
                "title": title[:500],
                "company": "Unknown",
                "description": "",
                "source": "yourator",
                "country": config.COUNTRY_TAIWAN,
            }
        )

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for j in out:
        u = j["url"]
        if u in seen:
            continue
        seen.add(u)
        deduped.append(j)

    if not deduped:
        logging.warning("Yourator: no job links parsed (layout may have changed).")
    return deduped


def fetch_104_english() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    urls = [
        f"https://www.104.com.tw/jobs/search/?keyword={quote_plus('english')}&area={AREA_TAIPEI}",
    ]
    for kw in config.TAIWAN_SEARCH_QUERIES:
        urls.append(
            f"https://www.104.com.tw/jobs/search/?keyword={quote_plus(kw)}&area={AREA_TAIPEI}"
        )

    for page_url in urls:
        try:
            r = requests.get(page_url, headers=_headers(), timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            logging.warning("104 scrape failed for %s: %s", page_url[:80], e)
            continue

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "job" not in href.lower():
                continue
            if not re.search(r"104\.com\.tw/job", href):
                continue
            title = a.get_text(" ", strip=True)
            if not title:
                continue
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = urljoin("https://www.104.com.tw/", href)
            out.append(
                {
                    "url": href,
                    "title": title[:500],
                    "company": "Unknown",
                    "description": "",
                    "source": "104",
                    "country": config.COUNTRY_TAIWAN,
                }
            )

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for j in out:
        u = j["url"]
        if u in seen:
            continue
        seen.add(u)
        deduped.append(j)

    if not deduped:
        logging.warning("104: no job links parsed (site may require JS or blocked).")
    return deduped


def fetch_all_taiwan_jobs() -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []

    for fn in (fetch_meet_jobs, fetch_tealit, fetch_yourator, fetch_104_english):
        try:
            batch = fn()
        except Exception as e:
            logging.warning("Taiwan source %s crashed: %s", fn.__name__, e)
            continue
        for j in batch:
            u = (j.get("url") or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            merged.append(j)

    logging.info("Taiwan scrape total unique URLs: %s", len(merged))
    return merged


if __name__ == "__main__":
    import supabase_utils

    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
        logging.error("Supabase env not set.")
        raise SystemExit(1)

    jobs = fetch_all_taiwan_jobs()
    inserted = 0
    for job in jobs:
        if supabase_utils.insert_job_if_new(job):
            inserted += 1
    logging.info("Taiwan scrape finished; inserted %s new job(s).", inserted)
