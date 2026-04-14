from supabase import create_client, Client
import config # Import configuration
from typing import Optional, Any, Dict
from models import Resume
import datetime # Import datetime module
import logging # Import logging
# --- Initialize Supabase Client ---
# Ensure URL and Key are provided
if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("Supabase URL and Key must be set in environment variables or config.")

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)


def _job_pk_col() -> str:
    return getattr(config, "SUPABASE_JOB_PK_COL", "id")


def normalize_job_row(row: Optional[dict]) -> Optional[dict]:
    """
    Map DB row (id, title, source, …) to keys expected by older code paths (job_id, job_title, provider).
    """
    if not row:
        return None
    pk = _job_pk_col()
    out = dict(row)
    rid = out.get(pk)
    if rid is not None:
        out["job_id"] = str(rid)
    if out.get("title") is not None and out.get("job_title") is None:
        out["job_title"] = out["title"]
    if out.get("source") is not None and out.get("provider") is None:
        out["provider"] = out["source"]
    if out.get("level") is None:
        out["level"] = "N/A"
    return out


# --- Supabase Functions ---
def get_existing_jobs_from_supabase(batch_size: int = 1000) -> tuple[set, set, set]:
    """
    Fetches primary keys, company|title pairs, and canonical job URLs (for deduping scrapers).
    Returns:
        - A set of primary key values (as strings)
        - A set of 'company|title' keys (both lowercased for consistency)
        - A set of lowercased `url` values (scrapers match on URL, not DB uuid)
    """
    existing_ids = set()
    existing_company_title_keys = set()
    existing_urls: set[str] = set()
    offset = 0
    pk = _job_pk_col()

    try:
        while True:
            response = (
                supabase.table(config.SUPABASE_TABLE_NAME)
                .select(f"{pk}, company, title, url")
                .range(offset, offset + batch_size - 1)
                .execute()
            )

            data = response.data

            if not data:
                break  # No more data to fetch

            for item in data:
                job_pk = item.get(pk)
                company = item.get("company")
                title = item.get("title")
                url = item.get("url")

                if job_pk:
                    existing_ids.add(str(job_pk))

                if company and title:
                    normalized_company = company.strip().lower()
                    normalized_title = title.strip().lower()
                    existing_company_title_keys.add((normalized_company, normalized_title))

                if url and str(url).strip():
                    existing_urls.add(str(url).strip().lower())

            offset += batch_size

        print(f"Fetched {len(existing_ids)} job IDs and {len(existing_company_title_keys)} company-title pairs.")

    except Exception as e:
        print(f"Error fetching existing jobs from Supabase: {e}")

    return existing_ids, existing_company_title_keys, existing_urls

def _scraper_job_to_row(job: dict) -> Optional[dict]:
    """Map legacy scraper output (job_id, job_title, provider, …) to canonical jobs columns."""
    jid = job.get("job_id")
    src = job.get("provider") or job.get("source") or ""
    url = (job.get("url") or "").strip()
    if not url and jid:
        if src == "careers_future":
            url = f"https://www.mycareersfuture.gov.sg/job/{jid}"
        else:
            url = f"https://www.linkedin.com/jobs/view/{jid}"
    if not url and job.get("uuid"):
        url = f"https://www.mycareersfuture.gov.sg/job/{job['uuid']}"
    if not url:
        return None
    title = job.get("job_title") or job.get("title") or ""
    return {
        "url": url,
        "title": title,
        "company": (job.get("company") or "").strip() or None,
        "description": job.get("description") or "",
        "source": job.get("provider") or job.get("source") or "scraper",
    }


def save_jobs_to_supabase(jobs_data: list):
    """
    Saves or updates job rows using unique `url` (canonical jobs schema).
    Accepts legacy dicts from scraper.py (job_id, job_title, provider, …).
    """
    if not jobs_data:
        print("No job data provided to save/update.")
        return

    processed_jobs_data = []
    for job in jobs_data:
        row = _scraper_job_to_row(job)
        if row:
            processed_jobs_data.append(row)
        else:
            print(f"Warning: Could not build row (need url or job_id/uuid). Skipping: {job}")

    if not processed_jobs_data:
        print("No valid job data remaining after processing.")
        return

    print(f"Attempting to upsert {len(processed_jobs_data)} jobs to Supabase...")

    try:
        data, count = supabase.table(config.SUPABASE_TABLE_NAME).upsert(
            processed_jobs_data, on_conflict="url"
        ).execute()

        # Check the actual response structure from your Supabase client version for upsert
        # It might differ slightly from insert's response structure
        if data and isinstance(data, tuple) and len(data) > 1:
             # The actual data returned might be in data[1] for upsert
             actual_data = data[1]
             print(f"Successfully upserted/updated {len(processed_jobs_data)} jobs. Supabase response count: {count}")
             # You might want to log the actual response data for debugging:
             # print(f"Supabase response data: {actual_data}")
        else:
             # Log raw response if structure is unexpected or for debugging
             print(f"Attempted to upsert {len(processed_jobs_data)} jobs. Supabase response: {data}")

    except Exception as e:
        print(f"Error upserting data to Supabase: {e}")
        # Consider logging the data that failed to upsert for debugging
        # print(f"Failed data: {processed_jobs_data}")


def get_jobs_to_score(limit: int) -> list:
    """
    Fetches jobs from the Supabase 'jobs' table that need scoring.
    Filters by is_active = true and resume_score = null.
    Selects only necessary fields (job_id, job_title, description).
    Orders by scraped_at ascending to process older jobs first.
    """
    if limit <= 0:
        logging.warning("Limit for jobs to score must be positive.")
        return []

    try:
        logging.info(f"Fetching up to {limit} jobs needing scoring...")
        pk = _job_pk_col()
        response = supabase.table(config.SUPABASE_TABLE_NAME)\
                           .select(f"{pk}, title, company, description, level")\
                           .eq("is_active", True)\
                           .is_("resume_score", None)\
                           .order("scraped_at", desc=False)\
                           .limit(limit)\
                           .execute()

        if response.data:
            logging.info(f"Successfully fetched {len(response.data)} jobs to score.")
            return [normalize_job_row(r) for r in response.data]
        else:
            logging.info("No jobs found needing scoring at this time.")
            return []

    except Exception as e:
        logging.error(f"Error fetching jobs to score from Supabase: {e}")
        return []

def get_top_scored_jobs_to_apply(limit: int) -> list:
    """
    Fetches the top-scored jobs from Supabase that are ready for application.
    Filters by is_active = true, resume_score is not null, and status is null.
    Orders by resume_score descending.
    Selects fields needed for the application process.
    """
    if limit <= 0:
        logging.warning("Limit for jobs to apply must be positive.")
        return []

    try:
        logging.info(f"Fetching up to {limit} top-scored jobs to apply for...")
        pk = _job_pk_col()
        response = supabase.table(config.SUPABASE_TABLE_NAME)\
                           .select(f"{pk}, title, company, resume_score")\
                           .eq("is_active", True)\
                           .eq("status", "new")\
                           .not_.is_("resume_score", None)\
                           .order("resume_score", desc=True)\
                           .limit(limit)\
                           .execute()

        if response.data:
            logging.info(f"Successfully fetched {len(response.data)} top-scored jobs to apply for.")
            return [normalize_job_row(r) for r in response.data]
        else:
            logging.info("No top-scored jobs found ready for application at this time.")
            return []

    except Exception as e:
        logging.error(f"Error fetching top-scored jobs to apply for from Supabase: {e}")
        return []

def get_top_scored_jobs_for_resume_generation(limit: int) -> list:
    """
    Jobs with match_score above threshold and no customized resume yet (canonical schema; no RPC).
    """
    if limit <= 0:
        logging.warning("Limit for jobs to apply must be positive.")
        return []

    try:
        min_cv = getattr(config, "MATCH_SCORE_MIN_FOR_CV", 8)
        pk = _job_pk_col()
        logging.info(
            f"Fetching up to {limit} jobs for resume generation (match_score >= {min_cv}, customized_resume_id is null)..."
        )
        response = (
            supabase.table(config.SUPABASE_TABLE_NAME)
            .select(f"{pk}, title, company, level, location, description, match_score, customized_resume_id")
            .is_("customized_resume_id", None)
            .not_.is_("match_score", None)
            .gte("match_score", min_cv)
            .order("match_score", desc=True)
            .limit(limit)
            .execute()
        )

        if response.data:
            logging.info(f"Successfully fetched {len(response.data)} job(s) for resume generation.")
            return [normalize_job_row(r) for r in response.data]
        logging.info("No jobs found for resume generation at this time.")
        return []

    except Exception as e:
        logging.error(f"Error fetching jobs for resume generation: {e}")
        return []

def get_jobs_to_rescore(limit: int) -> list:
    """
    Jobs with a customized resume still at initial scoring stage (direct query; no RPC).
    """
    if limit <= 0:
        logging.warning("Limit for jobs to rescore must be positive.")
        return []

    try:
        pk = _job_pk_col()
        logging.info(f"Fetching up to {limit} jobs for re-scoring...")
        response = (
            supabase.table(config.SUPABASE_TABLE_NAME)
            .select(f"{pk}, title, company, description, level, resume_score, customized_resume_id")
            .eq("is_active", True)
            .eq("status", "new")
            .eq("resume_score_stage", "initial")
            .not_.is_("customized_resume_id", None)
            .order("resume_score", desc=True)
            .limit(limit)
            .execute()
        )
        rows = response.data or []
        out = []
        for row in rows:
            cr_id = row.get("customized_resume_id")
            resume_link = None
            if cr_id:
                cr = get_customized_resume(str(cr_id))
                if cr:
                    resume_link = cr.get("resume_link")
            row["resume_link"] = resume_link
            out.append(normalize_job_row(row))

        if out:
            logging.info(f"Successfully fetched {len(out)} jobs for re-scoring.")
        else:
            logging.info("No jobs found meeting re-scoring criteria.")
        return out

    except Exception as e:
        logging.error(f"Exception in get_jobs_to_rescore: {e}", exc_info=True)
        return []

def update_job_resume_score(job_id: str, score: int, resume_score_stage: str = "initial") -> bool:
    """
    Updates the legacy 'resume_score' and 'resume_score_stage' for a specific job_id in the Supabase 'jobs' table.
    Returns True on success, False on failure.
    """
    if not job_id or score is None:
        logging.error(f"Invalid input for updating job score: job_id={job_id}, score={score}")
        return False

    if resume_score_stage not in ["initial", "custom"]:
        logging.error(f"Invalid resume_score_stage: {resume_score_stage}. Must be 'initial' or 'custom'.")
        return False

    try:
        logging.info(f"Updating resume_score for job_id {job_id} to {score} and stage to {resume_score_stage}...")
        update_payload = {
            "resume_score": score,
            "resume_score_stage": resume_score_stage
        }
        response = supabase.table(config.SUPABASE_TABLE_NAME)\
                           .update(update_payload)\
                           .eq(_job_pk_col(), job_id)\
                           .execute()

        if hasattr(response, 'data') and response.data:
             logging.info(f"Successfully updated resume_score for job_id {job_id}.")
             return True
        elif hasattr(response, 'count') and response.count is not None and response.count > 0:
             logging.info(f"Successfully updated resume_score for job_id {job_id} (count={response.count}).")
             return True
        elif not hasattr(response, 'data') and not hasattr(response, 'count'):
             logging.warning(f"Update resume_score for job_id {job_id} executed, but response structure unclear: {response}")
             return True
        else:
             logging.warning(f"Update resume_score for job_id {job_id} might have failed or job not found. Response: {response}")
             return False

    except Exception as e:
        logging.error(f"Error updating resume_score for job_id {job_id} in Supabase: {e}")
        return False


def insert_job_if_new(job: dict) -> bool:
    """Insert job only if URL not already in table. Returns True if inserted."""
    url = (job.get("url") or "").strip()
    if not url:
        logging.warning("insert_job_if_new: missing url, skipping.")
        return False

    try:
        existing = (
            supabase.table(config.SUPABASE_TABLE_NAME)
            .select(_job_pk_col())
            .eq("url", url)
            .limit(1)
            .execute()
        )
        if existing.data:
            logging.debug(f"Job URL already exists: {url[:80]}...")
            return False
    except Exception as e:
        logging.error(f"insert_job_if_new: error checking URL: {e}")
        return False

    row = {
        "url": url,
        "title": job.get("title") or "",
        "company": job.get("company") or "",
        "description": job.get("description") or "",
        "source": job.get("source") or job.get("provider") or "",
        "country": job.get("country"),
    }
    if job.get("location"):
        row["location"] = job["location"]
    if job.get("level"):
        row["level"] = job["level"]

    try:
        supabase.table(config.SUPABASE_TABLE_NAME).insert(row).execute()
        logging.info(f"Inserted new job ({url[:60]}...).")
        return True
    except Exception as e:
        logging.error(f"insert_job_if_new: insert failed: {e}")
        return False


def get_unscored_jobs(country: str, limit: int = 100) -> list:
    """Get jobs with no match_score for a given country."""
    if not country:
        return []
    try:
        pk = _job_pk_col()
        q = (
            supabase.table(config.SUPABASE_TABLE_NAME)
            .select(f"{pk}, title, company, description, level, country")
            .eq("country", country)
            .is_("match_score", None)
            .order("scraped_at", desc=False)
        )
        if limit and limit > 0:
            q = q.limit(limit)
        response = q.execute()
        rows = response.data or []
        return [normalize_job_row(r) for r in rows]
    except Exception as e:
        logging.error(f"get_unscored_jobs: {e}")
        return []


def update_job_score(job_id: str, score: int, reason: str) -> bool:
    """Update match_score and match_reason for a job."""
    if not job_id or score is None:
        logging.error(f"update_job_score: invalid job_id={job_id}, score={score}")
        return False
    try:
        payload = {"match_score": score, "match_reason": reason or ""}
        response = (
            supabase.table(config.SUPABASE_TABLE_NAME)
            .update(payload)
            .eq(_job_pk_col(), job_id)
            .execute()
        )
        if hasattr(response, "data") and response.data:
            return True
        if hasattr(response, "count") and response.count is not None and response.count > 0:
            return True
        logging.warning(f"update_job_score: no rows updated for job_id={job_id}")
        return False
    except Exception as e:
        logging.error(f"update_job_score: {e}")
        return False


def get_unnotified_matches(country: str, threshold: int) -> list:
    """Get high-scoring unnotified jobs for a country (match_score strictly above threshold)."""
    if not country:
        return []
    try:
        pk = _job_pk_col()
        response = (
            supabase.table(config.SUPABASE_TABLE_NAME)
            .select(
                f"{pk}, title, company, description, url, source, match_score, match_reason, scraped_at, notified"
            )
            .eq("country", country)
            .gt("match_score", threshold)
            .order("match_score", desc=True)
            .limit(200)
            .execute()
        )
        rows = [r for r in (response.data or []) if r.get("notified") is not True]
        return [normalize_job_row(r) or r for r in rows]
    except Exception as e:
        logging.error(f"get_unnotified_matches: {e}")
        return []


def mark_jobs_notified(job_ids: list) -> bool:
    """Set notified=true for a list of job IDs."""
    if not job_ids:
        return True
    try:
        supabase.table(config.SUPABASE_TABLE_NAME).update({"notified": True}).in_(_job_pk_col(), job_ids).execute()
        logging.info(f"mark_jobs_notified: updated {len(job_ids)} job(s).")
        return True
    except Exception as e:
        logging.error(f"mark_jobs_notified: {e}")
        return False

def get_job_by_id(job_id: str) -> dict | None:
    """
    Fetches a single job record from the Supabase 'jobs' table based on job_id.
    """
    if not job_id:
        logging.error("No job_id provided to fetch job details.")
        return None
    if not hasattr(config, 'SUPABASE_TABLE_NAME') or not config.SUPABASE_TABLE_NAME:
        logging.error("SUPABASE_TABLE_NAME is not defined in config.py")
        return None

    try:
        pk = _job_pk_col()
        logging.info(f"Fetching job details for job_id: {job_id} from table '{config.SUPABASE_TABLE_NAME}'")
        response = supabase.table(config.SUPABASE_TABLE_NAME)\
                           .select(f"{pk}, company, title, level, description, country, url, customized_resume_id")\
                           .eq(pk, job_id) \
                           .limit(1)\
                           .execute()

        if response.data:
            logging.info(f"Successfully fetched job data for job_id: {job_id}.")
            return normalize_job_row(response.data[0])
        else:
            logging.warning(f"No job found for job_id: {job_id}")
            return None

    except Exception as e:
        logging.error(f"Error fetching job data from Supabase for job_id {job_id}: {e}")
        return None

def upload_customized_resume_to_storage(file_content: bytes, destination_path: str) -> Optional[str]:
    """
    Uploads the generated resume PDF (as bytes) to Supabase Storage.

    Args:
        file_content: The resume content in bytes.
        destination_path: The desired path and filename within the bucket
                          (e.g., "personalized_resumes/resume_job_12345.pdf").
                          Ensure this path is unique per job/resume.

    Returns:
        The destination path of the uploaded file, or None if upload fails.
    """
    if not file_content:
        logging.error("Cannot upload empty file content.")
        return None
    if not config.SUPABASE_STORAGE_BUCKET:
        logging.error("Supabase storage bucket name not configured.")
        return None

    try:
        logging.info(f"Uploading resume to Supabase Storage at path: {destination_path}")

        # Use upsert=True if you want to overwrite if a file with the same name exists,
        # otherwise False (or omit) to potentially get an error if it exists.
        # Ensure your destination_path includes job_id or similar for uniqueness.
        upload_response = supabase.storage.from_(config.SUPABASE_STORAGE_BUCKET)\
            .upload(
                path=destination_path,
                file=file_content,
                file_options={"content-type": "application/pdf", "upsert": "true"} # Set upsert based on desired behavior
            )

        logging.info(f"Successfully uploaded resume to path: {destination_path}")
        return destination_path

    except Exception as e:
        # Supabase client might raise specific exceptions, catch broadly for now
        logging.error(f"Error uploading file to Supabase Storage: {e}")
        # Attempt to remove partially uploaded file if possible/needed (more complex error handling)
        # try:
        #     supabase.storage.from_(config.SUPABASE_STORAGE_BUCKET).remove([destination_path])
        # except:
        #     logging.warning(f"Could not clean up potentially failed upload at {destination_path}")
        return None

def update_job_with_resume_link(job_id: str, customized_resume_id: str,  new_status: Optional[str] = "resume_generated") -> bool:
    """
    Updates the job record in the Supabase table with the resume link and optionally a new status.

    Args:
        job_id: The unique ID of the job to update.
        customized_resume_id: The id the generated resume in Supabase customized_resumes table.
        new_status: The status to set for the job after processing (e.g., 'resume_generated').
                    Set to None to only update the link without changing status.

    Returns:
        True if the update was successful, False otherwise.
    """
    if not job_id or not customized_resume_id:
        logging.error("Job ID and Customized Resume id are required for updating the job.")
        return False

    try:
        update_data = {"customized_resume_id": customized_resume_id}
        # if new_status:
        #     update_data["job_state"] = new_status # Assuming 'status' is your column name

        logging.info(f"Updating job {job_id} with resume link, resume id and status '{new_status or 'unchanged'}'...")

        response = supabase.table(config.SUPABASE_TABLE_NAME)\
                           .update(update_data)\
                           .eq(_job_pk_col(), job_id)\
                           .execute()

        # Check if the update affected any rows (response.data might contain updated rows)
        if response.data:
            logging.info(f"Successfully updated job {job_id}.")
            return True
        else:
            # This might happen if the job_id didn't exist or matched 0 rows
            logging.warning(f"Update query executed for job {job_id}, but no rows seemed to be affected.")
            # Depending on strictness, you might return False here
            return False # Treat as failure if no row was confirmed updated

    except Exception as e:
        logging.error(f"Error updating job {job_id} in Supabase: {e}")
        return False

def update_customized_resume_link(resume_id: str, resume_link: str) -> bool:
    """Sets resume_link on a customized_resumes row (e.g. after PDF upload)."""
    if not resume_id or not resume_link:
        return False
    try:
        supabase.table(config.SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME).update(
            {"resume_link": resume_link}
        ).eq("id", resume_id).execute()
        logging.info("Updated customized resume %s with storage path.", resume_id)
        return True
    except Exception as e:
        logging.error("update_customized_resume_link: %s", e)
        return False


def save_customized_resume(resume_data: 'Resume', resume_path: Optional[str] = None) -> Optional[Any]: # Return type changed
    """
    Saves a customized resume to the Supabase 'customized_resumes' table.

    Args:
        resume_data: A Resume object (Pydantic model) containing the resume details.
        resume_path: The path of the uploaded resume in storage (optional if PDF is generated in a later step).

    Returns:
        The ID (typically string UUID or integer) of the inserted resume if successful, None otherwise.
    """

    if resume_path is None:
        logging.info("Saving customized resume without storage path (PDF may follow in a separate step).")

    if not resume_data:
        logging.error("No resume data provided to save.")
        return None

    if not hasattr(config, 'SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME') or \
       not config.SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME:
        logging.error("SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME is not defined in config.py")
        return None

    try:
        # Convert Pydantic model to dict for Supabase
        if hasattr(resume_data, 'model_dump'):
            data_to_insert = resume_data.model_dump(exclude_none=True)
        else:
            data_to_insert = resume_data.dict(exclude_none=True)

        if resume_path:
            data_to_insert['resume_link'] = resume_path

        logging.info(
            f"Saving customized resume for email: {getattr(resume_data, 'email', 'N/A')} "
            f"with path '{resume_path}' to table '{config.SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME}'"
        )

        response = supabase.table(config.SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME)\
                           .insert(data_to_insert)\
                           .execute()

        if response.data and len(response.data) > 0:
            inserted_record = response.data[0]
            if 'id' in inserted_record:
                resume_id = inserted_record['id']
                logging.info(
                    f"Successfully saved customized resume for {getattr(resume_data, 'email', 'N/A')} "
                    f"with ID: {resume_id}."
                )
                return resume_id
            else:
                logging.warning(
                    f"Customized resume for {getattr(resume_data, 'email', 'N/A')} saved, "
                    f"but 'id' key not found in the response data. Full record: {inserted_record}"
                )
                return None
        else:
            error_message = "Unknown error"
            if hasattr(response, 'error') and response.error:
                error_message = response.error
                logging.error(
                    f"Failed to save customized resume for {getattr(resume_data, 'email', 'N/A')}. "
                    f"Supabase Error: {error_message}"
                )
            elif hasattr(response, 'message') and response.message:
                error_message = response.message
                logging.error(
                    f"Failed to save customized resume for {getattr(resume_data, 'email', 'N/A')}. "
                    f"Supabase API Error: {error_message}"
                )
            else:
                logging.warning(
                    f"Customized resume for {getattr(resume_data, 'email', 'N/A')} might not have been saved "
                    f"or ID not returned. Response data is empty or missing. Response: {response}"
                )
            return None

    except Exception as e:
        logging.error(
            f"Error saving customized resume for {getattr(resume_data, 'email', 'N/A')} to Supabase: {e}",
            exc_info=True
        )
        return None

def get_customized_resume(resume_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches a customized resume record from Supabase by ID.
    """
    if not resume_id:
        return None
    
    try:
        logging.info(f"Fetching customized resume data from database for ID: {resume_id}")
        response = supabase.table(config.SUPABASE_CUSTOMIZED_RESUMES_TABLE_NAME)\
            .select("*")\
            .eq("id", resume_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        logging.error(f"Error fetching customized resume {resume_id}: {e}")
        return None


# --- Base Resume Functions ---
# These functions handle storing and retrieving the user's base resume
# securely via Supabase, instead of committing sensitive files to the repo.

def download_resume_from_storage(file_name: str = "resume.pdf") -> Optional[bytes]:
    """
    Downloads the user's resume PDF from the 'resumes' Supabase Storage bucket.

    Args:
        file_name: The name of the resume file in the storage bucket.

    Returns:
        The file content as bytes, or None if download fails.
    """
    bucket_name = config.SUPABASE_RESUME_STORAGE_BUCKET
    if not bucket_name:
        logging.error("Resume storage bucket name not configured (SUPABASE_RESUME_STORAGE_BUCKET).")
        return None

    try:
        logging.info(f"Downloading '{file_name}' from Supabase Storage bucket '{bucket_name}'...")
        file_bytes = supabase.storage.from_(bucket_name).download(file_name)

        if file_bytes:
            logging.info(f"Successfully downloaded '{file_name}' ({len(file_bytes)} bytes).")
            return file_bytes
        else:
            logging.warning(f"Downloaded empty content for '{file_name}' from bucket '{bucket_name}'.")
            return None

    except Exception as e:
        logging.error(f"Error downloading '{file_name}' from Supabase Storage: {e}")
        return None


def save_base_resume(resume_data: dict) -> bool:
    """
    Saves (upserts) the parsed base resume JSON to the 'base_resume' table.
    Updates the latest existing row when present; inserts a new row otherwise.

    Args:
        resume_data: The parsed resume data as a dictionary.

    Returns:
        True if saved successfully, False otherwise.
    """
    if not resume_data:
        logging.error("No resume data provided to save.")
        return False

    table_name = config.SUPABASE_BASE_RESUME_TABLE_NAME
    try:
        latest_response = (
            supabase.table(table_name)
            .select("id")
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )

        existing_rows = latest_response.data or []
        if existing_rows:
            existing_id = existing_rows[0].get("id")
            logging.info(f"Updating existing base resume row in '{table_name}' (id={existing_id})...")
            (
                supabase.table(table_name)
                .update({"resume_data": resume_data})
                .eq("id", existing_id)
                .execute()
            )
        else:
            logging.info(f"No existing base resume row found; inserting into '{table_name}'...")
            supabase.table(table_name).insert({
                "resume_data": resume_data
            }).execute()

        # Some PostgREST configurations return minimal payload for writes.
        # Verify success by reading the latest row after the write.
        verify_response = (
            supabase.table(table_name)
            .select("id,resume_data")
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        verify_rows = verify_response.data or []
        if verify_rows and verify_rows[0].get("resume_data"):
            logging.info(f"Successfully saved base resume to '{table_name}'.")
            return True
        else:
            logging.warning("Base resume write completed but verification found no row.")
            return False

    except Exception as e:
        logging.error(f"Error saving base resume to Supabase: {e}", exc_info=True)
        return False


def get_base_resume() -> Optional[dict]:
    """
    Fetches the base resume JSON data from the 'base_resume' table.

    Returns:
        The resume data as a dictionary, or None if not found or on error.
    """
    table_name = config.SUPABASE_BASE_RESUME_TABLE_NAME
    try:
        logging.info(f"Fetching base resume from '{table_name}'...")
        response = supabase.table(table_name)\
            .select("resume_data")\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()

        if response.data and len(response.data) > 0:
            resume_data = response.data[0].get("resume_data")
            if resume_data:
                logging.info("Successfully fetched base resume data from Supabase.")
                return resume_data
            else:
                logging.warning("Base resume row found but 'resume_data' is empty.")
                return None
        else:
            logging.warning("No base resume found in Supabase. Please run the 'Parse Resume' workflow first.")
            return None

    except Exception as e:
        logging.error(f"Error fetching base resume from Supabase: {e}", exc_info=True)
        return None

