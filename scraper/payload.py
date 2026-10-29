"""
Maps a scraped/enriched job record to the shape expected by
POST /api/Job/create-external-jobrequest.

Only fields that are either required or currently have a real calculated
value are included. Fields that are neither required nor calculated yet
(hardcoded placeholders with no data source) have been removed to keep this
preview readable. See PAYLOAD_MAPPING_TODO.md for the removed-fields list
and what's needed before they can be added back.

Company: sent as `companyId`, a real Company GUID from companies.json (see
that file's `companyId` field). Requires the corresponding change on the
basecampjobs-core side (ExternalJobViewModel.CompanyId / CreateFromExternalJobAsync)
to actually be used, see PAYLOAD_MAPPING_TODO.md. Only present when
companies.json has a companyId for that company; omitted otherwise so the
backend behaves exactly as it does today for companies we haven't matched yet.
"""
from typing import Dict, List
import markdown as _markdown
from scraper.job_type import job_type_from_label, resolve_job_type
from scraper.location import location_line, parse_locations

# Basecamp's public enum JobType, minus Other (6): web has no entry for it and
# renders "N/A", so scraper/job_type.py never resolves to it.
JOB_TYPE_MAP = {
    "full-time": 1,
    "part-time": 2,
    "freelance": 3,
    "seasonal-part-time": 4,
    "internship": 5,
    "seasonal-full-time": 7,
}

# Basecamp's public enum RemoteStatus
REMOTE_STATUS_MAP = {
    "remote-anywhere": 1,
    "on-the-road": 2,
    "remote-in-region": 3,
    "onsite": 4,
    "hybrid": 5,
}

# Fallback only, used when Basecamp's own focus extractor (matched_focuses,
# scraper/basecamp_client.py:extract_focuses) returns nothing for a job. Focuses can't
# be empty server-side (JobService.cs:360 crashes with 500 on empty). "Data" is a
# real focus, confirmed against the live Focuses table.
PLACEHOLDER_FOCUS = "Data"

# Basecamp's public enum SalaryCompensation, keyed on the period scraper/salary.py
# detects from the posting's own text (e.g. "per hour" -> "hour"). No entry covers
# "ContractLength" (5), nothing in the scraped text maps to that today.
SALARY_COMPENSATION_MAP = {
    "year": 1,
    "hour": 2,
    "week": 3,
    "month": 4,
    "day": 6,
}


def _salary_compensation(job: Dict) -> Dict:
    salary_compensation_id = SALARY_COMPENSATION_MAP.get(job.get("salary_period"))
    # Don't report min/max at all when we can't also determine the period. A number
    # with no unit label is worse than no number (confirmed: shows "undefined" in the UI).
    if salary_compensation_id is None:
        return {"min": 0, "max": 0, "salaryCompensation": None}
    return {
        "min": job.get("salary_min") or 0,
        "max": job.get("salary_max") or 0,
        "salaryCompensationId": salary_compensation_id,
        "salaryCompensation": job.get("salary_range"),
    }


def _locations(job: Dict) -> List[Dict]:
    # ATS sources (Greenhouse/Lever/SmartRecruiters) have no location_struct or
    # "Location:" line, so they get [] here for now.
    description = job.get("description") or job.get("raw_description") or ""
    return [{
        "city": l["city"],
        "stateOrProvince": l["state"],
        "longStateOrProvince": l["state_name"],
        "country": l["country"],
        "longCountry": l["country_name"],
        # 0/0 when the city isn't in the table; the job still matches by state/country.
        "lat": l["lat"],
        "lng": l["lng"],
    } for l in parse_locations(location_line(description), job.get("location_struct"))]


def _description_html(text: str) -> str:
    """Render markdown/plain text into real HTML. Existing HTML (e.g. Greenhouse's
    content field) passes through mostly unchanged, python-markdown leaves
    recognized block-level HTML alone rather than re-escaping it."""
    if not text:
        return ""
    return _markdown.markdown(text)


def build_payload(job: Dict) -> Dict:
    title = job.get("title") or job.get("raw_title") or ""
    description = job.get("description") or job.get("raw_description") or ""
    location = job.get("location") or job.get("raw_location")
    # matched_skills comes from Basecamp's own extract-skills-from-job-description endpoint
    # (scraper/basecamp_client.py), guaranteed to exist in their Skills table, unlike our
    # AI-guessed skill names which mostly won't survive their exact-match lookup. Falls back
    # to the AI's own guesses only if skill-matching was never run for this job.
    skills = job["matched_skills"] if "matched_skills" in job else (job.get("skills") or [])
    # matched_focuses comes from Basecamp's own extract-field-focus-from-job-description
    # endpoint, guaranteed to exist in their Focuses table. Falls back to PLACEHOLDER_FOCUS
    # when matching wasn't run or came back empty, since focuses can't be empty server-side
    # (JobService.cs:360 crashes with 500 on empty).
    focuses = job.get("matched_focuses") or [PLACEHOLDER_FOCUS]
    remote_status = job.get("remote_status")

    # jobTypeId is non-nullable server-side; resolve_job_type always returns a real type
    # (text first, then JSON-LD employmentType, else part-time). A labeled "Job Type:"
    # line beats the AI's reading of the text.
    text_type = job_type_from_label((job.get("page_fields") or {}).get("job type")) or job.get("employment_type")
    job_type_id = JOB_TYPE_MAP[resolve_job_type(job.get("raw_employment_type"), text_type)]
    # remoteStatusId is non-nullable server-side too, but unlike jobTypeId has no "other"/
    # "unknown" value to fall back to (RemoteStatus.cs only defines 1-5). Sending null
    # crashes the whole request (confirmed: DetailsViewModel.RemoteStatusId can't deserialize
    # null into the enum), so omit the key entirely when we can't resolve one, same fix as
    # salaryCompensationId below.
    remote_status_id = REMOTE_STATUS_MAP.get(remote_status)

    payload = {
        "title": title,

        "jobTypeId": job_type_id,

        "isRemoteConsidered": job.get("is_remote_considered") or False,
        "isHousingIncluded": job.get("is_housing_included") or False,
        "isHousingSubsidized": job.get("is_housing_subsidized") or False,
        "isRelocationStipend": job.get("is_relocation_stipend") or False,
        "isCommuterBenefits": job.get("is_commuter_benefits") or False,

        "introduction": job.get("introduction"),
        "description": _description_html(description),

        "additionalLocationInformation": location,
        "locations": _locations(job),

        # salaryCompensationId is non-nullable server-side and has no "unknown" value.
        # Sending min/max without it shows as "undefined" in the UI (confirmed live), so
        # only report a salary at all when scraper/salary.py could also determine the
        # period (hour/year/etc). Omitting the id key entirely (rather than sending
        # null) avoids the same null-to-non-nullable-enum crash we hit with jobTypeId.
        "salaryCompensation": _salary_compensation(job),

        "qualifications": {
            "isManagementRequired": job.get("is_management_required"),
            # Plain name strings (ExternalJobQualificationsViewModel). Server does exact-match
            # lookup against its own Focus/Skill tables server-side; non-matching names are
            # silently dropped, not created. See PAYLOAD_MAPPING_TODO.md.
            "focuses": list(focuses),
            "skills": list(skills),
        },

        "howToApply": {
            "urlOrEmail": job.get("url"),
        },
    }

    if remote_status_id is not None:
        payload["remoteStatusId"] = remote_status_id

    company_id = job.get("company_id")
    if company_id:
        payload["companyId"] = company_id

    return payload
