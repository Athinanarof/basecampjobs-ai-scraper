# basecampjobs-ai-scraper

Automated job scraper for the Basecamp outdoor industry job board. Runs daily on Azure Functions, pulls job listings from outdoor industry companies via ATS APIs and Firecrawl, enriches them with Azure OpenAI, and stores results in Azure Table Storage.

---

## How It Works

```
Daily timer (6am UTC)
    ├── ATS APIs (Greenhouse / Lever / SmartRecruiters) → free structured JSON
    └── Firecrawl → scrapes any JS-rendered career page (REI, Workday, iCIMS, etc.)
         ↓
    Deduplication (skip already-seen job URLs)
         ↓
    Azure OpenAI GPT-5o-mini → enriches each job with field, niche, skills, etc.
         ↓
    Azure Table Storage → saves results
```

---

## Prerequisites

Before you start, make sure you have the following installed and ready.

**Software**
- [Python 3.11](https://www.python.org/downloads/) — check "Add Python to PATH" during install
- [VS Code](https://code.visualstudio.com/) with the [Azurite extension](https://marketplace.visualstudio.com/items?itemName=Azurite.azurite) installed

**Accounts & API Keys — you will need all three**

| Service | What it's for | Get it at |
|---|---|---|
| [Firecrawl](https://firecrawl.dev) | Scrapes career pages that require JavaScript | firecrawl.dev → Sign up → API Keys |
| [Azure AI Foundry](https://ai.azure.com) | Enriches raw job text into structured fields | Azure Portal → Create Azure OpenAI resource → then deploy model in Azure AI Foundry |
| [Azure Storage](https://portal.azure.com) | Stores jobs and dedup cache (local: Azurite handles this) | Same Azure resource group |

---

## Installation

**1. Clone the repo**
```bash
git clone https://github.com/Athinanarof/basecampjobs-ai-scraper.git
cd basecampjobs-ai-scraper
```

**2. Create a virtual environment**
```bash
python -m venv .venv
```

**3. Activate it**

On Windows:
```powershell
.venv\Scripts\activate
```

On Mac/Linux:
```bash
source .venv/bin/activate
```

**4. Install dependencies**
```bash
pip install -r requirements.txt
```

---

## Configuration

**1. Copy the example settings file**
```bash
cp local.settings.json.example local.settings.json
```

**2. Open `local.settings.json` and fill in your keys**

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AZURE_STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;...",
    "FIRECRAWL_API_KEY": "fc-xxxxxxxxxxxxxxxx",
    "AZURE_OPENAI_API_KEY": "your-azure-openai-key",
    "AZURE_OPENAI_ENDPOINT": "https://your-resource.openai.azure.com/",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-mini"
  }
}
```

> `local.settings.json` is in `.gitignore` — your keys will never be committed.

**Where to find each key:**

- `FIRECRAWL_API_KEY` → [firecrawl.dev](https://firecrawl.dev) → Dashboard → API Keys
- `AZURE_OPENAI_API_KEY` → [Azure AI Foundry](https://ai.azure.com) → Deployments → `gpt-5-mini-deploy` → copy **API Key**
- `AZURE_OPENAI_ENDPOINT` → [Azure AI Foundry](https://ai.azure.com) → Deployments → `gpt-5-mini-deploy` → copy **Project endpoint**
- `AZURE_STORAGE_CONNECTION_STRING` → leave as-is for local development (Azurite handles it)

---

## Running Locally

**Start Azurite first** (local Azure Storage emulator)

In VS Code: press `F1` → type `Azurite: Start` → press Enter.  
You should see "Azurite Blob/Queue/Table service is starting" in the status bar.

---

### Test each step individually

**Step 1 — ATS APIs** (free, no API keys needed)
```powershell
python run_local.py --step ats
```
Fetches jobs from Greenhouse, Lever, and SmartRecruiters for all companies in `companies.json`. Use this to verify company slugs are correct.

---

**Step 2 — Firecrawl** (needs `FIRECRAWL_API_KEY`)
```powershell
python run_local.py --step firecrawl
```
Scrapes career pages for companies marked `"ats": "firecrawl"` in `companies.json` (e.g. REI, Backcountry). Uses Firecrawl credits.

---

**Step 3 — Enrichment** (needs `AZURE_OPENAI_API_KEY`)
```powershell
python run_local.py --step enrich
```
Runs Azure OpenAI enrichment on sample job data. Confirms AI keys are working and the output format is correct. Uses a small number of tokens.

> Only the first 800 characters of each job's raw description are sent to the AI (`scraper/enrichment.py`), to keep token usage down. If a posting's relevant details sit further down the page than that, they won't reach the model.

---

**Full pipeline**
```powershell
python run_local.py
```
Runs all steps end-to-end: ATS fetch → Firecrawl scrape → dedup → enrich → save to Azurite.

---

## Adding Companies

Open `companies.json`. Each entry follows this format:

**For companies using Greenhouse, Lever, or SmartRecruiters:**
```json
{"name": "Patagonia", "ats": "greenhouse", "slug": "patagonia"}
```
The `slug` is the company identifier visible in their career page URL:
```
https://boards.greenhouse.io/patagonia  →  slug: "patagonia"
https://jobs.lever.co/blackdiamond      →  slug: "blackdiamond"
```

**For any other career page (Workday, iCIMS, custom sites):**
```json
{"name": "REI", "ats": "firecrawl", "url": "https://rei.jobs/jobs"}
```
Use the URL of the main jobs listing page, not a specific job posting.

After adding a company, run `--step ats` or `--step firecrawl` to verify it works before committing.

---

## Project Structure

```
basecampjobs-ai-scraper/
├── function_app.py          # Azure Functions Timer Trigger — entry point
├── companies.json           # List of outdoor industry companies to scrape
├── run_local.py             # Local test runner
├── requirements.txt         # Python dependencies
├── host.json                # Azure Functions runtime config
├── local.settings.json      # Your API keys (not committed)
├── local.settings.json.example
├── scraper/
│   ├── ats.py               # Greenhouse / Lever / SmartRecruiters API adapters
│   ├── firecrawl.py         # Firecrawl scraper for JS-rendered career pages
│   ├── fetcher.py           # Plain HTTP fetcher (static pages fallback)
│   └── enrichment.py        # Azure OpenAI GPT-4o-mini batch enrichment
├── storage/
│   ├── cache.py             # Azure Table Storage URL deduplication
│   └── writer.py            # Azure Table Storage job writer
└── .github/
    └── workflows/
        └── deploy.yml       # GitHub Actions → deploys to Azure on push to main
```

---

## Deploying to Azure

**1. Create Azure resources**
- Azure Function App (Python 3.11, Consumption plan)
- Azure Storage Account
- Azure OpenAI resource with `gpt-4o-mini` deployed

**2. Set environment variables in Azure Portal**

Go to your Function App → Settings → Environment variables → add:
- `FIRECRAWL_API_KEY`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_STORAGE_CONNECTION_STRING`

**3. Connect GitHub Actions**

In Azure Portal → your Function App → Deployment Center → GitHub → authorize and select this repo.  
Or add the publish profile as a secret `AZURE_FUNCTIONAPP_PUBLISH_PROFILE` in your GitHub repo settings.

Push to `main` — GitHub Actions deploys automatically.

---

## Monthly Cost Estimate

| Component | Cost |
|---|---|
| Azure Functions | ~$0 (free tier) |
| Azure Table Storage | ~$0 at this scale |
| Azure OpenAI GPT-5-mini | ~$0.25 per month |
| Firecrawl | Free (1,000 credits/month) → $16/month if over |
| **Total** | **~$0.25–$17/month** |

**Firecrawl credit breakdown — 1 credit = 1 page scraped (no multipliers).**

Each Firecrawl company uses:
- 1 credit to map the career page and discover job URLs
- 1 credit per individual job page scraped

| Company | Est. active jobs | Credits/month |
|---|---|---|
| REI | ~200 | ~201 |
| Backcountry | ~50 | ~51 |
| **Total (current list)** | | **~252 credits** |

The free tier (1,000 credits/month) comfortably covers the current company list with room for ~3 more REI-sized companies. All companies on Greenhouse, Lever, and SmartRecruiters use their free public APIs and cost **zero Firecrawl credits** regardless of job volume.
