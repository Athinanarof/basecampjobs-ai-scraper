"""
Maps a scraped/enriched job record to the shape expected by
POST /api/Job/create-external-jobrequest.

Only fields that are either required or currently have a real calculated
value are included. Fields that are neither required nor calculated yet
(hardcoded placeholders with no data source) have been removed to keep this
preview readable — see PAYLOAD_MAPPING_TODO.md for the removed-fields list
and what's needed before they can be added back.

Company is intentionally not part of this payload — the target schema has
no company field. It's known from whichever companies.json entry produced
the job in the first place, not something that needs to travel through here.
"""
from typing import Dict

# Basecamp's public enum JobType
JOB_TYPE_MAP = {
    "full-time": 1,
    "part-time": 2,
    "freelance": 3,
    "seasonal-part-time": 4,
    "internship": 5,
    "other": 6,
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


def build_payload(job: Dict) -> Dict:
    title = job.get("title") or job.get("raw_title") or ""
    description = job.get("description") or job.get("raw_description") or ""
    location = job.get("location") or job.get("raw_location")
    skills = job.get("skills") or []
    field = job.get("field")
    employment_type = job.get("employment_type")
    remote_status = job.get("remote_status")

    job_type_id = JOB_TYPE_MAP.get(employment_type)
    remote_status_id = REMOTE_STATUS_MAP.get(remote_status)

    return {
        "title": title,

        "jobTypeId": job_type_id,
        # Only carry the raw text when we couldn't map it (or it's genuinely "other") — otherwise jobTypeId already says it.
        "jobTypeOther": employment_type if (job_type_id is None or job_type_id == JOB_TYPE_MAP["other"]) else None,

        "remoteStatusId": remote_status_id,
        "isRemoteConsidered": job.get("is_remote_considered") or False,
        "isHousingIncluded": job.get("is_housing_included") or False,
        "isHousingSubsidized": job.get("is_housing_subsidized") or False,
        "isRelocationStipend": job.get("is_relocation_stipend") or False,
        "isCommuterBenefits": job.get("is_commuter_benefits") or False,

        "introduction": job.get("introduction"),
        "description": f"<p>{description}</p>" if description else "",

        "additionalLocationInformation": location,
        "locations": [],

        "salaryCompensation": {
            "min": job.get("salary_min"),
            "max": job.get("salary_max"),
            "salaryCompensation": job.get("salary_range"),
        },

        "qualifications": {
            "isManagementRequired": job.get("is_management_required"),
            "focuses": [{"name": field}] if field else [],
            "skills": [{"name": s} for s in skills],
        },

        "howToApply": {
            "urlOrEmail": job.get("url"),
        },
    }
