"""
Taiwan job sources: Meet.jobs API, Tealit, Yourator, 104.com.tw (HTML scraping).
Each fetch returns dicts: url, title, company, description, source, country='taiwan'.
"""

from __future__ import annotations

import logging
import random
import re
import json
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
JOBS_104_API = "https://www.104.com.tw/jobs/search/api/jobs"

TAIWAN_INCLUDE_TERMS_STRONG = (
    "geopolitical",
    "political risk",
    "security",
    "national security",
    "supply chain manager",
    "semiconductor",
    "wind power",
    "offshore wind",
)

TAIWAN_INCLUDE_TERMS = (
    "asia",
    "supply",
    "supply chain",
    "procurement",
    "commercial manager",
    "operations manager",
    "risk",
    "strategy",
)

TAIWAN_EXCLUDE_TERMS = (
    "retail",
    "recruitment",
    "recruiter",
    "talent acquisition",
)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(user_agents.USER_AGENTS),
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
    }


def _text_blob(title: str, description: str, company: str = "") -> str:
    return f"{title} {description} {company}".lower()


def _is_targeted_role(title: str, description: str, company: str = "") -> bool:
    # Hard block: exclude all teacher roles by title.
    if re.search(r"\bteacher\b", title.lower()):
        return False
    blob = _text_blob(title, description, company)
    if any(term in blob for term in TAIWAN_EXCLUDE_TERMS):
        return False
    return any(term in blob for term in TAIWAN_INCLUDE_TERMS_STRONG + TAIWAN_INCLUDE_TERMS)


def _priority_score(title: str, description: str, company: str = "") -> int:
    blob = _text_blob(title, description, company)
    score = 0
    for term in TAIWAN_INCLUDE_TERMS_STRONG:
        if term in blob:
            score += 3
    for term in TAIWAN_INCLUDE_TERMS:
        if term in blob:
            score += 2
    for term in TAIWAN_EXCLUDE_TERMS:
        if term in blob:
            score -= 4
    return score


def _extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # 1) Preferred metadata fields
    for selector, attr in (
        ('meta[property="og:description"]', "content"),
        ('meta[name="description"]', "content"),
    ):
        tag = soup.select_one(selector)
        if tag and tag.get(attr):
            text = str(tag.get(attr)).strip()
            if len(text) > 40:
                return text

    # 2) JSON-LD description
    for s in soup.select('script[type="application/ld+json"]'):
        raw = s.string or s.get_text() or ""
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for c in candidates:
            if isinstance(c, dict):
                d = c.get("description")
                if isinstance(d, str) and len(d.strip()) > 40:
                    return d.strip()

    # 3) Fallback body text (coarse)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]


def _enrich_description_from_url(url: str, current_desc: str) -> str:
    """Fetch job page and extract a readable description when source payload is empty."""
    if current_desc and len(current_desc.strip()) >= 40:
        return current_desc.strip()
    if not url:
        return current_desc or ""
    try:
        r = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        extracted = _extract_text_from_html(r.text)
        if extracted and len(extracted.strip()) >= 40:
            return extracted.strip()
    except Exception as e:
        logging.debug("Description enrichment failed for %s: %s", url, e)
    return current_desc or ""


def _extract_job_links_from_html(
    html: str, base_url: str, patterns: tuple[str, ...], limit: int = 300
) -> list[str]:
    """
    Generic fallback parser for sources that return bot/challenge HTML or changed layouts.
    Pulls candidate links from anchors and script text, then deduplicates.
    """
    out: list[str] = []
    seen: set[str] = set()
    soup = BeautifulSoup(html, "html.parser")

    def _push(url: str) -> None:
        u = (url or "").strip()
        if not u:
            return
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("/"):
            u = urljoin(base_url, u)
        if not u.startswith("http"):
            return
        ul = u.lower()
        if not any(p in ul for p in patterns):
            return
        if u in seen:
            return
        seen.add(u)
        out.append(u)

    for a in soup.find_all("a", href=True):
        _push(a.get("href", ""))
        if len(out) >= limit:
            return out

    for script in soup.find_all("script"):
        txt = script.string or script.get_text() or ""
        if not txt:
            continue
        for m in re.finditer(r'"((?:\/|https?:\/\/)[^"]*(?:job|jobs|position)[^"]*)"', txt):
            raw = m.group(1)
            try:
                raw = raw.encode("utf-8").decode("unicode_escape")
            except Exception:
                pass
            _push(raw)
            if len(out) >= limit:
                return out

    return out


def _title_from_url(url: str, default: str) -> str:
    """Build a readable fallback title from URL slug/path."""
    u = (url or "").strip()
    if not u:
        return default
    slug = u.rstrip("/").split("/")[-1]
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    if len(slug) >= 4:
        return slug[:160]
    return default


def fetch_meet_jobs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        r = requests.get(
            MEET_JOBS_API,
            params={"location": "taiwan"},
            headers={**_headers(), "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        try:
            data = r.json()
        except Exception:
            # Occasionally returns non-JSON pages (e.g., anti-bot/challenge).
            logging.warning("Meet.jobs API returned non-JSON response (status=%s).", r.status_code)
            fallback_links = _extract_job_links_from_html(
                r.text,
                "https://meet.jobs/",
                patterns=("/jobs/", "/job/"),
                limit=150,
            )
            for href in fallback_links:
                title = _title_from_url(href, "Meet.jobs role")
                desc = _enrich_description_from_url(href, "")
                if not _is_targeted_role(title, desc, "Unknown"):
                    continue
                out.append(
                    {
                        "url": href,
                        "title": title,
                        "company": "Unknown",
                        "description": desc,
                        "source": "meet.jobs",
                        "country": config.COUNTRY_TAIWAN,
                        "priority_score": _priority_score(title, desc, "Unknown"),
                    }
                )
            if out:
                logging.info("Meet.jobs fallback parsed %s candidate link(s).", len(out))
            return out
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
        if not _is_targeted_role(title, desc, company):
            continue
        if not str(url).startswith("http"):
            url = urljoin("https://meet.jobs/", str(url).lstrip("/"))
        desc = _enrich_description_from_url(str(url), desc)
        out.append(
            {
                "url": url,
                "title": title,
                "company": company or "Unknown",
                "description": desc,
                "source": "meet.jobs",
                "country": config.COUNTRY_TAIWAN,
                "priority_score": _priority_score(title, desc, company or "Unknown"),
            }
        )
    return out


def fetch_tealit() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    candidate_pages = [
        TEALIT_LIST,
        "https://www.tealit.com/jobs/",
        "https://www.tealit.com/",
    ]
    for page in candidate_pages:
        try:
            r = requests.get(page, headers=_headers(), timeout=REQUEST_TIMEOUT)
            if r.status_code >= 400:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception:
            continue

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(" ", strip=True)
            if not text or len(text) < 4:
                continue
            href_l = href.lower()
            if (
                "/job" not in href_l
                and "job_listing" not in href_l
                and "position" not in href_l
                and "tealit.com/job" not in href_l
            ):
                continue
            if href.startswith("/"):
                href = urljoin("https://www.tealit.com/", href)
            if not href.startswith("http"):
                continue
            desc = _enrich_description_from_url(href, "")
            if not _is_targeted_role(text, desc, "Unknown"):
                continue
            out.append(
                {
                    "url": href,
                    "title": text[:500],
                    "company": "Unknown",
                    "description": desc,
                    "source": "tealit",
                    "country": config.COUNTRY_TAIWAN,
                    "priority_score": _priority_score(text[:500], "", "Unknown"),
                }
            )

        if not out:
            fallback_links = _extract_job_links_from_html(
                r.text,
                "https://www.tealit.com/",
                patterns=("/job", "job_listing", "position"),
                limit=150,
            )
            for href in fallback_links:
                title = _title_from_url(href, "Tealit role")
                desc = _enrich_description_from_url(href, "")
                if not _is_targeted_role(title, desc, "Unknown"):
                    continue
                out.append(
                    {
                        "url": href,
                        "title": title,
                        "company": "Unknown",
                        "description": desc,
                        "source": "tealit",
                        "country": config.COUNTRY_TAIWAN,
                        "priority_score": _priority_score(title, desc, "Unknown"),
                    }
                )
        if out:
            break

    if not out:
        logging.warning("Tealit: no job links parsed (layout/URL likely changed).")
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
        html = r.text
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        logging.warning("Yourator scrape failed: %s", e)
        return out

    for a in soup.select('a[href*="/jobs/"], a[href*="/job/"], a[href*="/companies/"]'):
        href = a.get("href", "").strip()
        if not href:
            continue
        href_l = href.lower()
        if "/jobs/" not in href_l and "/job/" not in href_l:
            continue
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        if href.startswith("/"):
            href = urljoin("https://www.yourator.co/", href)
        desc = _enrich_description_from_url(href, "")
        if not _is_targeted_role(title, desc, "Unknown"):
            continue
        out.append(
            {
                "url": href,
                "title": title[:500],
                "company": "Unknown",
                "description": desc,
                "source": "yourator",
                "country": config.COUNTRY_TAIWAN,
                "priority_score": _priority_score(title[:500], "", "Unknown"),
            }
        )

    # Fallback: parse Next.js payload for job cards/links
    if not out:
        script = soup.find("script", id="__NEXT_DATA__")
        if script and script.string:
            try:
                payload = json.loads(script.string)
                payload_text = json.dumps(payload)
                for m in re.finditer(r'"url"\s*:\s*"(\/jobs\/[^"]+)"', payload_text):
                    rel = m.group(1).encode("utf-8").decode("unicode_escape")
                    out.append(
                        {
                            "url": urljoin("https://www.yourator.co/", rel),
                            "title": "Yourator job",
                            "company": "Unknown",
                            "description": _enrich_description_from_url(
                                urljoin("https://www.yourator.co/", rel), ""
                            ),
                            "source": "yourator",
                            "country": config.COUNTRY_TAIWAN,
                            "priority_score": _priority_score("Yourator job", "", "Unknown"),
                        }
                    )
            except Exception:
                pass

    # Final fallback: generic HTML/script link extractor for layout changes.
    if not out:
        fallback_links = _extract_job_links_from_html(
            html,
            "https://www.yourator.co/",
            patterns=("/jobs/", "/job/"),
            limit=200,
        )
        for href in fallback_links:
            title = _title_from_url(href, "Yourator role")
            desc = _enrich_description_from_url(href, "")
            if not _is_targeted_role(title, desc, "Unknown"):
                continue
            out.append(
                {
                    "url": href,
                    "title": title,
                    "company": "Unknown",
                    "description": desc,
                    "source": "yourator",
                    "country": config.COUNTRY_TAIWAN,
                    "priority_score": _priority_score(title, desc, "Unknown"),
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
    queries = ["english", *config.TAIWAN_SEARCH_QUERIES]
    for kw in queries:
        try:
            r = requests.get(
                JOBS_104_API,
                params={
                    "keyword": kw,
                    "area": AREA_TAIPEI,
                    "order": 15,  # latest
                    "page": 1,
                    "mode": "s",
                },
                headers={
                    **_headers(),
                    "Accept": "application/json, text/plain, */*",
                    "Referer": f"https://www.104.com.tw/jobs/search/?keyword={quote_plus(kw)}&area={AREA_TAIPEI}",
                },
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logging.warning("104 API failed for %r: %s", kw, e)
            continue

        rows = data.get("data") if isinstance(data, dict) else None
        rows = rows if isinstance(rows, list) else []
        for item in rows:
            if not isinstance(item, dict):
                continue
            job_no = item.get("jobNo")
            link = item.get("link", {}) if isinstance(item.get("link"), dict) else {}
            href = link.get("job") or (f"https://www.104.com.tw/job/{job_no}" if job_no else "")
            if href.startswith("//"):
                href = "https:" + href
            if not href.startswith("http"):
                continue

            title_obj = item.get("jobName")
            title = title_obj.get("label") if isinstance(title_obj, dict) else str(title_obj or "")
            title = title.strip()
            if not title:
                continue

            company_obj = item.get("custName")
            company = company_obj.get("label") if isinstance(company_obj, dict) else str(company_obj or "")
            company = company.strip() or "Unknown"

            desc = ""
            if isinstance(item.get("jobDescription"), str):
                desc = item.get("jobDescription", "").strip()
            desc = _enrich_description_from_url(href, desc)
            if not _is_targeted_role(title, desc, company):
                continue

            out.append(
                {
                    "url": href,
                    "title": title[:500],
                    "company": company,
                    "description": desc,
                    "source": "104",
                    "country": config.COUNTRY_TAIWAN,
                    "priority_score": _priority_score(title[:500], desc, company),
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
