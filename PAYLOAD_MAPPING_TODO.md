# Mapping to the Basecamp Job API, open items

`scraper/payload.py` (`build_payload()`) reshapes an enriched job into an
API payload. `scraper/basecamp_client.py` (login + `create-external-job` +
the shared `publish_payloads()` helper) is used by both:
- `run_local.py --step push`, opt-in only, never runs as part of
  `--step all`, for local testing.
- `function_app.py`'s nightly run, publishes outdoor-industry jobs to
  Basecamp automatically after enrichment, no manual step.

Unresolved fields below are placeholders (`null` / `[]` / `false`).

## Real endpoint details (found in `basecampjobs-core`)
- Real endpoint: **`POST /api/Job/create-external-job`**. Requires a Bearer
  token from a user with the `Scrapping` role, via `POST /api/Auth/login`
  with `{ "userName": "...", "password": "..." }`.
- **`GET /api/Job/options/get`** (anonymous) is a one-stop lookup: full
  `Skills`, `Focuses`, `Visions`, `JobFields`, `Leaderships` lists, and
  every enum (`JobTypes`, `RemoteStatuses`, `SalaryCompensations`,
  `YearsOfExperience`, `Benefits`, `OutdoorIndustries`).
- `Focuses`/`Skills`/`Visions`/`AdditionalSkills` on most endpoints expect
  `{id, name}` pairs (`NameIdDto`). The external job endpoint is the
  exception: `ExternalJobQualificationsViewModel` takes plain string
  arrays, matched server-side by exact name.
- `ExternalJobViewModel`/`DetailsViewModel` also has `jobTypeDuration`,
  `isHQPosition`, `isExclusiveToPlatform`, `locationNonNegotiable`, and
  `howToApply.isDeadlinePublic` as real fields, currently unused here (see
  "Removed from the payload" below).

## Skills
- **`POST /api/Job/extract-skills-from-job-description`** (anonymous):
  send `{ "jobDescription": "..." }`, get back Basecamp's own matched
  `{id, name}` skills. Server-side mechanism
  (`JobDescriptionSkillExtractor.cs`): normalizes text and skill names,
  then does word-boundary exact-phrase matching, longest names first,
  deleting matched text as it goes. Plain regex, not AI/embeddings. We
  feed it the fullest raw description text available to maximize matches.
- Used as-is: free, deterministic, IDs guaranteed valid. Replaces sending
  our own AI-extracted skill strings entirely.
- **Later improvement**: exact-phrase-only means it misses paraphrased
  skills (our AI says "Product Roadmapping", their list has "Product
  Management", no match today). Could add local fuzzy matching
  (e.g. `rapidfuzz`, Levenshtein distance) as a second pass over
  AI-extracted skills the exact-match endpoint missed. Only catches
  textually close variants, not true synonyms.

## Locations
Not matched against a lookup table like skills/focuses. `LocationDto` is
just `{Country, LongCountry, StateOrProvince, LongStateOrProvince, City,
Lat, Lng}`, built fresh per job. Currently populated for Firecrawl-sourced
jobs from JSON-LD (`scraper/firecrawl.py`); ATS sources still get `[]`.
`Lat`/`Lng` are hardcoded `0` (no geocoding source yet).

## Enums
Fixed values from `basecampjobs-core`'s `BasecampJobs.Common/Enums/`, no
lookup call needed:
- `SalaryCompensation`: Yearly=1, Hour=2, Week=3, Month=4,
  ContractLength=5, Day=6 (wired into `payload.py`)
- `YearsOfExperience`: EntryLevel=1, From1Years=2, From3Years=3,
  From5Years=4, From10Years=5, From20Years=6 (not wired in yet)
- `Benefit` (19 values, e.g. Medical=1, Vacation=2, ParentalLeave=3, up to
  RemoteWork=19; full list in `BasecampJobs.Common/Enums/Benefit.cs`, not
  wired in yet)

Still need: `YearsOfExperience`/`Benefit` maps in `payload.py`, and
`enrichment.py` extracting the signal to pick a value.

## API integration
`scraper/basecamp_client.py` (`login()`, `create_job()`, `publish_payloads()`)
+ `run_local.py --step push` / `function_app.py`'s nightly run call the
real API, tracking already-pushed URLs (`debug/pushed_urls.json` locally,
Table Storage in production) so re-runs are safe.

**Confirmed bug on `develop`, not ours to fix**: unconditional `.First()`
on `Focuses` in `JobService.cs:360`
(`job.Qualifications.JobFieldId = await _focusRepository.GetJobFieldId(model.Focuses.First().Id);`),
no null/empty check. An empty `focuses` array crashes with `500`
("Sequence contains no elements"). We work around it client-side:
`payload.py`'s `PLACEHOLDER_FOCUS` ("Data", a real focus name) is sent
only when real focus matching comes back empty. `"Other"` is not a valid
substitute, it doesn't exist in the real Focuses table.

**Also confirmed**: focus/skill/vision matching does exact string
matching server-side; a name with no matching row is silently dropped,
not created.

## Removed from the payload, revisit once resolved
Dropped from `build_payload()`'s output entirely (not left null) because
they're neither required nor have a calculated value. Add back once each
gets a real data source:
- `jobTypeDuration`
- `isHQPosition`
- `isExclusiveToPlatform`
- `locationNonNegotiable`
- `remoteLocations`
- `qualifications.yearsOfExperienceId`
- `qualifications.superpowersSuggestions`
- `qualifications.benefits`
- `qualifications.visions`
- `qualifications.additionalSkills`
- `howToApply.contact` (`name`, `email`, `title`, `linkedIn`)
- `howToApply.applicationDeadline`
- `howToApply.notes`

## No data source yet
- `howToApply.contact` (name/email/title/linkedIn): not present in scraped
  postings. Likely needs to live in `companies.json` as per-company config.
- `howToApply.applicationDeadline`: not scraped from ATS APIs. REI's
  Firecrawl pages embed a real `validThrough` date via schema.org
  JSON-LD (`raw_valid_through`), but it isn't wired into `payload.py` yet.
  Still need to decide whether `validThrough` means "application deadline"
  or just "listing expiry".
- `qualifications.visions` (e.g. "Diversity"): same shape as skills/focuses
  now, but nothing extracts candidate values from postings yet.
- `qualifications.additionalSkills`: unclear how this differs from
  `qualifications.skills`. Need an example.
- `isHQPosition`: hardcoded `false`, no data source.
