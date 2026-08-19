# Mapping to the Basecamp Job API — open items

`scraper/payload.py` (`build_payload()`) reshapes an enriched job into an
API payload. `scraper/basecamp_client.py` + `run_local.py --step push` now
actually call the real endpoint (login + `create-external-job`) — opt-in
only, never runs as part of `--step all`. Unresolved fields below are
placeholders (`null` / `[]` / `false`).

## Real endpoint details (found in `basecampjobs-core`, 2026-08-18)
Checked the actual backend repo (`C:\Users\arace\Documents\Git\basecampjobs\basecampjobs-core`)
against `https://basecamp-develop.azurewebsites.net/api`. Corrections to
what we'd assumed:
- The real endpoint is
  **`POST https://basecamp-develop.azurewebsites.net/api/Job/create-external-job`**,
  not `create-external-jobrequest`. Requires a Bearer token from a user
  with the `Scrapping` role. Get a token via `POST /api/Auth/login` with
  `{ "userName": "...", "password": "..." }`.
- **`GET /api/Job/options/get`** (`[AllowAnonymous]`, no token needed) —
  one-stop lookup endpoint. Returns the full `Skills` list, `Focuses`,
  `Visions`, `JobFields`, `Leaderships`, and every enum (`JobTypes`,
  `RemoteStatuses`, `SalaryCompensations`, `YearsOfExperience`, `Benefits`,
  `OutdoorIndustries`) in one response.
- `Focuses`, `Skills`, `Visions`, `AdditionalSkills` all expect
  `{id, name}` pairs (`NameIdDto`), not just free-text names — confirms
  the taxonomy-mismatch concern below is real: sending a name with no
  matching `id` is not valid.
- The real request model (`ExternalJobViewModel` / `DetailsViewModel`)
  does include `jobTypeDuration`, `isHQPosition`, `isExclusiveToPlatform`,
  `locationNonNegotiable` as real fields (we removed these from our local
  preview as noise since we don't calculate them — still fine to leave
  removed, just noting they're real fields on the actual endpoint, not
  invented). Also found one field we didn't know about at all:
  `howToApply.isDeadlinePublic` (bool).

## Skills — plan decided, use as-is for now
- **`POST /api/Job/extract-skills-from-job-description`** (`[AllowAnonymous]`,
  no token needed) — send `{ "jobDescription": "..." }`, get back Basecamp's
  own matched `{id, name}` skills. Mechanism (from
  `JobDescriptionSkillExtractor.cs`): loads all skills from their `Skills`
  table (cached 6h), normalizes text and skill names (lowercase, strip
  non-alphanumeric), then does **word-boundary exact-phrase matching**,
  longest skill names first, deleting matched text as it goes so phrases
  aren't double-counted. It's plain regex, not AI/embeddings — a skill only
  matches if its literal name appears in the text. Feed it the fullest raw
  description text we have (not the 800-char-truncated or AI-summarized
  versions) to maximize matches.
- **Decision**: use this endpoint as-is for now — it's free, deterministic,
  IDs are guaranteed valid, and it's presumably the same mechanism
  Basecamp's own platform uses internally. This replaces the need to send
  our own AI-extracted skill strings at all.
- **Later improvement**: since it's exact-phrase-only, it will miss
  paraphrased/synonym skills our AI extracted but that aren't worded
  exactly like Basecamp's skill names (e.g. our AI says "Product
  Roadmapping", their list has "Product Management" — no match today).
  Plan to add **local fuzzy string matching** as a second pass over
  whatever the AI-extracted skill list contains but the exact-match
  endpoint missed: compare each unmatched AI skill string against
  Basecamp's full skill list (from `options/get`) using a similarity
  algorithm like **Levenshtein distance** (edit distance — how many
  character insertions/deletions/substitutions turn one string into the
  other) via a local library (e.g. `rapidfuzz`), no extra API calls or AI
  cost. Only counts as a match above some similarity threshold (TBD).
  Note this only catches *textually* close variants (typos, word-order,
  near-misses) — it won't catch true synonyms with no string overlap
  (that would need AI, which we're deliberately avoiding for this — see
  chat for the cost/hallucination tradeoffs of that approach).

## Locations — corrected, not a matching problem
Earlier assumption was wrong — locations are **not** matched against a
Basecamp lookup table like skills are. `LocationDto` is just
`{Country, LongCountry, StateOrProvince, LongStateOrProvince, City, Lat,
Lng}`, built fresh per job with no ID/lookup involved. The real gap: we
don't currently produce `Lat`/`Lng` at all, so our scraped location
strings (e.g. "Phoenix, Arizona") need geocoding before they can populate
this shape. `locations` in `payload.py` is still `[]`.

## Enums — resolved from source, no longer blocked
Found the actual C# enum definitions in `basecampjobs-core`
(`BasecampJobs.Common/Enums/`) — these don't need a Basecamp lookup call,
the values are fixed and already known:
- `SalaryCompensation`: Yearly=1, Hour=2, Week=3, Month=4,
  ContractLength=5, Day=6
- `YearsOfExperience`: EntryLevel=1, From1Years=2, From3Years=3,
  From5Years=4, From10Years=5, From20Years=6
- `Benefit` (19 values, e.g. Medical=1, Vacation=2, ParentalLeave=3 ... up
  to RemoteWork=19 — full list in `BasecampJobs.Common/Enums/Benefit.cs`)

Still need: wire these into `payload.py` as maps (same pattern as
`JOB_TYPE_MAP`/`REMOTE_STATUS_MAP`), and have `enrichment.py` extract the
signal needed to pick a value (years-of-experience mentions, benefits
mentioned in the posting).

## API integration — built and tested live; wrong payload shape fixed, one real blocker remains
`scraper/basecamp_client.py` (`login()`, `create_job()`) + `run_local.py
--step push` call the real API: logs in once, POSTs each job from
`jobs_output.json` to `create-external-job`, tracks already-pushed URLs in
`debug/pushed_urls.json` so re-running is safe. Login confirmed working
live (2026-08-18) with real credentials.

**Fixed on our side**: `salaryCompensation.min`/`max` now default to `0`
instead of `null` — confirmed live that `0` passes validation (`min`/`max`
are non-nullable `decimal` server-side).

**CORRECTION (2026-08-19)**: the "positional deserialization bug" theory
below was wrong. Root cause: `scraper/payload.py` was sending
`qualifications.focuses`/`skills` as `[{"name": "..."}]` objects, matching
the old `UpdateQualificationsViewModel` (`IList<NameIdDto>`). The real
model for this endpoint is `ExternalJobQualificationsViewModel`
(`BasecampJobs.Common/ViewModels/Job/Post/ExternalJobQualificationsViewModel.cs`),
which expects **plain string arrays** — `["Outdoor Retail"]`, not
`[{"name": "Outdoor Retail"}]`. That's why the parser choked on `{`. This
file only exists on the `develop` branch (added 2026-07-22, commit
`a890a7f9` "scrapping updates") — the investigation that produced the
"positional" theory was done against a local checkout still on `main`,
which never had this file, so the mismatch wasn't visible from the code.
Fixed in `payload.py`: `focuses`/`skills` now send plain strings.

**Still a real, confirmed bug on `develop`**: unconditional `.First()` on
`Focuses` — `JobService.cs:360` —
`job.Qualifications.JobFieldId = await _focusRepository.GetJobFieldId(model.Focuses.First().Id);`
— no null/empty check. If `focuses` ends up empty, this crashes with `500`
/ `"Sequence contains no elements"`.

**Also confirmed**: `FocusRepository.MapCollection()` (and presumably the
equivalent for skills/visions/benefits/outdoor industries) does **exact
string matching** against their own DB tables (`Where(f =>
incoming.Contains(f.Name))`) — a name that doesn't exactly match an
existing row is silently dropped, not created. So our AI-generated `field`
taxonomy won't reliably match Basecamp's real focus names, and could
regularly end up empty — which would then hit the `.First()` crash above.
Need real name-matching against `GET /api/Job/options/get`'s `Focuses`
list before this is trustworthy (same problem already tracked for skills
elsewhere in this doc).

**Known blocker, also found while building this**: `CreateFromExternalJobAsync`
(`JobService.cs`) never sets `job.CompanyId` — it's nullable and stays
`null` for every job created this way, since `ExternalJobViewModel` has no
company field for it to come from and the method doesn't derive it from
the logged-in user's company. Endpoint won't reject the request on its
own for this (field is optional) — separate issue from the blocker above.

## Removed from the payload — revisit once resolved
These fields were dropped from `build_payload()`'s output entirely (not
just left null) because they're neither required nor have a calculated
value — they were pure noise. Once any of them gets a real data source or
lookup table, add it back:
- `jobTypeDuration`
- `isHQPosition`
- `isExclusiveToPlatform`
- `locationNonNegotiable`
- `remoteLocations`
- `salaryCompensation.salaryCompensationId`
- `qualifications.yearsOfExperienceId`
- `qualifications.superpowersSuggestions`
- `qualifications.benefits`
- `qualifications.visions`
- `qualifications.additionalSkills`
- `howToApply.contact` (`name`, `email`, `title`, `linkedIn`)
- `howToApply.applicationDeadline`
- `howToApply.notes`

## No data source yet — need a decision on where the value comes from
- `howToApply.contact` (name/email/title/linkedIn) — not present in scraped
  postings. Likely needs to live in `companies.json` as per-company config
  rather than being AI-derived.
- `howToApply.applicationDeadline` — not scraped from ATS APIs. **Partial
  source exists for Firecrawl companies**: REI's job pages embed a
  schema.org `JobPosting` JSON-LD block with a real `validThrough` date
  (confirmed live). `scraper/firecrawl.py` extracts it into
  `raw_valid_through`, but it isn't wired into `payload.py` yet — still
  need to decide whether `validThrough` really means "application
  deadline" or just "listing expiry" before treating it as one.
- `qualifications.visions` (e.g. "Diversity") — same `{id, name}` shape as
  skills/focuses now confirmed, but still no data source — nothing extracts
  candidate vision values from postings yet.
- `qualifications.additionalSkills` — unclear how this differs from
  `qualifications.skills`. Same taxonomy, different bucket? Need an example.
- `isHQPosition` — hardcoded `false`, no data source.

## Taxonomy mismatch
- `qualifications.focuses` — currently populated from our `field` value
  (e.g. "Ski/Snow", "Outdoor Retail"). Now confirmed via `basecampjobs-core`
  that `Focuses` needs real `{id, name}` pairs from Basecamp's own focus
  list (same `GET /api/Job/options/get` response as skills) — our `field`
  taxonomy is a guess and won't have valid IDs. Same fix path as skills:
  match against the real list, exact first, fuzzy later.
- `niche` (our field) has no home in the target payload at all — dropped.
