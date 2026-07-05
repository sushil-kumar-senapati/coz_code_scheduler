# People's Priorities AI — Copilot Context (Scheduler Service)

> This file is automatically read by GitHub Copilot to understand the project context.
> **DO NOT DELETE** — It ensures every team member gets full context in Copilot Chat.

---

## PROJECT OVERVIEW

**People's Priorities AI** is a multilingual AI platform for constituency development planning under India's MPLADS scheme (₹5 Crore/year per MP). It converts unstructured citizen complaints (text/audio/image in 13 Indian languages) into transparent, data-driven MP funding recommendations.

### Core Problem
No systematic way for MPs to collect citizen demands → funds misallocated, unheard voices, no accountability. This platform is the missing decision-support layer.

---

## ARCHITECTURE (6 Layers)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PEOPLE'S PRIORITIES AI                            │
├─────────────┬───────────────────────────────────────┬───────────────┤
│  FRONTEND   │          BACKEND SERVICES              │   DATABASE   │
│  (React)    │                                        │   (MySQL)    │
│             │  ┌──────────────┐  ┌────────────────┐  │              │
│  Layer 1 ──►│  │ backend-api  │  │  scheduler     │  │  19 tables   │
│  Layer 6 ──►│  │ (FastAPI)    │  │  (Layers 2-5)  │  │  7 triggers  │
│             │  │ Port: 8000   │  │  23:30 nightly  │  │  6 views     │
│  Port: 5173 │  └──────────────┘  └────────────────┘  │  Port: 3306  │
└─────────────┴───────────────────────────────────────┴───────────────┘
```

### Three Repos
1. **`coz_code_backend`** — FastAPI backend for Layer 1 (citizen intake) + Layer 6 (MP dashboard). Always running on port 8000.
2. **`coz_code_scheduler`** (THIS REPO) — Python scheduler for Layers 2-5. Runs nightly at 23:30 or manually triggered.
3. **`coz_code_frontend`** — React + Vite UI on port 5173. Citizen submission + dashboards.

---

## THIS REPO: SCHEDULER SERVICE (`coz_code_scheduler`)

### Tech Stack
- **Language:** Python
- **Scheduler:** `schedule` library (cron-like)
- **ML:** scikit-learn (TF-IDF + cosine similarity)
- **ASR:** `speech_recognition` (Google free API)
- **OCR:** `pytesseract` (Tesseract — requires install at `C:\Program Files\Tesseract-OCR\tesseract.exe`)
- **Translation:** `deep-translator` (Google Translate free)
- **Database:** MySQL 8.0.13+ (mysql.connector)

### Project Structure
```
coz_code_scheduler/
├── run_scheduler.py          # Entry: schedule + CLI (--now, --seed)
├── seed_layer4_data.py       # Pre-load government data into data_sources
├── requirements.txt
├── reset_pipeline.py         # Reset pipeline state for testing
├── test_submissions.py       # Test script
└── pipeline/
    ├── __init__.py
    ├── config.py             # DB config (same MySQL as backend)
    ├── db.py                 # MySQL connection helpers
    ├── layer2_processing.py  # ASR + OCR + Translate + Spam filter
    ├── layer3_clustering.py  # TF-IDF clustering + MPLADS categorization
    ├── layer4_enrichment.py  # Infrastructure gap + demographics + history
    └── layer5_scoring.py     # 7-factor weighted scoring + ranking
```

### How to Run
```bash
python run_scheduler.py --seed   # Seed Layer 4 data first
python run_scheduler.py --now    # Run pipeline once immediately
python run_scheduler.py          # Start nightly scheduler (23:30)
```

Also triggerable via backend API: `POST /scheduler/run`

---

## PIPELINE STAGES

### LAYER 2: Data Processing & Filtering (`layer2_processing.py`)

**Input:** `raw_submissions` WHERE `status='submitted'`
**Output:** `processed_submissions`

Process per submission:
1. **Audio → Text:** Google Speech Recognition (supports 13 Indian languages)
   - Converts audio → WAV → sends to Google API
   - Language codes: hi-IN, or-IN, bn-IN, ta-IN, te-IN, mr-IN, gu-IN, kn-IN, ml-IN, pa-IN, as-IN, ur-IN
2. **Image → Text:** Tesseract OCR (pytesseract)
   - Fallback to PIL image metadata if Tesseract fails
   - Requires Tesseract installed (Windows: `C:\Program Files\Tesseract-OCR\tesseract.exe`)
3. **Translate to English:** Google Translate (deep-translator)
   - Auto-detects source language
4. **Spam Filter:**
   - Too short (< 10 chars)
   - Rate limit (> 5 submissions/day per user)
   - Exact duplicate text detection
5. **Store** in `processed_submissions` with `translated_text_en`, `is_spam`, `processing_method`
6. **Update** `raw_submissions.status` → 'processed'

### LAYER 3: Clustering & Categorization (`layer3_clustering.py`)

**Input:** `processed_submissions` WHERE `is_spam=FALSE AND status='processed'`
**Output:** `demand_clusters` + `cluster_submissions`

Process:
1. **Duplicate Detection:** Same user can't have same issue twice (rejected + notification sent)
2. **Similarity Matching:** TF-IDF + Cosine Similarity
   - Compare new submission against all existing cluster representative texts
   - Threshold: 0.40 (lower for hackathon text diversity)
   - Only match within same constituency
3. **Clustering:** Similar enough → add to existing cluster. Otherwise → create new cluster.
4. **MPLADS Categorization:** Keyword-based matching into 14 categories:
   - `ROADS_PATHWAYS_BRIDGES, EDUCATION, HEALTH, DRINKING_WATER, SANITATION, ELECTRICITY, IRRIGATION, SPORTS, COMMUNITY_INFRASTRUCTURE, WOMEN_CHILD_WELFARE, DISABILITY_WELFARE, SC_ST_WELFARE, RAILWAYS, DISASTER_RELIEF`
5. **Eligibility:** If no MPLADS category matches → `is_mplads_eligible = FALSE`, cluster rejected, users notified
6. **Update counts:** `unique_users`, `submission_count`, `pin_codes_covered`

### LAYER 4: Data Fusion & Enrichment (`layer4_enrichment.py`)

**Input:** `demand_clusters` WHERE `status='categorized'`
**Output:** `demand_clusters.data_overlay` (enriched JSON)

For each cluster:
1. **Infrastructure Gap Analysis:**
   - Fetch govt norms from `infrastructure_norms` table for the cluster's category
   - Fetch actual data from `data_sources` for the cluster's district
   - Compare actual vs norms → gap score (0.0 = perfect, 1.0 = critical)
   - Example: Water coverage 59.6% vs norm 100% → gap = 0.40
2. **Demographics** (Census 2011 + SECC):
   - SC/ST%, BPL%, literacy rate, female literacy rate
   - Fallback to national averages if district data missing
3. **MPLADS Spending History:**
   - Past sector spending from `mplads_fund_history`
   - Used for historical bias correction in Layer 5
4. **Update** `demand_clusters.status` → 'enriched'

**Data Sources (pre-loaded via `seed_layer4_data.py`):**

| Source Type | Portal | Data |
|-------------|--------|------|
| `census_village` | censusindia.gov.in | Population, SC/ST%, literacy |
| `secc_village` | secc.gov.in | BPL%, deprivation indicators |
| `udise_school` | udiseplus.gov.in | Schools, teachers, infrastructure |
| `health_facility` | hmis.nhp.gov.in | PHC/CHC, doctors, beds |
| `jjm_water` | ejalshakti.gov.in | Tap water coverage % |
| `pmgsy_road` | pmgsygeosadak.dord.gov.in | Road connectivity |
| `saubhagya_electric` | saubhagya.gov.in | Electrification % |
| `sbm_sanitation` | sbm.gov.in | Toilet coverage, ODF status |

**Infrastructure Norms (from official sources):**
- EDUCATION: 1 school per 300 pop / 1km (RTE Act 2009), 30:1 student-teacher ratio
- HEALTH: 1 PHC per 30K plain / 20K tribal (IPHS 2022), 1 doctor per 1K (WHO)
- WATER: 100% tap water (JJM target)
- ROADS: 100% all-weather road (PMGSY target), ≥500 pop habitations connected
- SANITATION: 100% ODF (Swachh Bharat), ELECTRICITY: 100% (Saubhagya)

### LAYER 5: Prioritization & Scoring (`layer5_scoring.py`)

**Input:** `demand_clusters` WHERE enriched
**Output:** `cluster_scores` + ranked clusters

#### 7-Factor Weighted Formula

| # | Factor | Symbol | Weight | Calculation |
|---|--------|--------|--------|-------------|
| 1 | Demand Volume | D | 0.18 | `ln(1+users)/ln(1+N_max)` — log-scaled anti-gaming |
| 2 | Category Severity | S | 0.20 | Static lookup: Water=1.00, Health=0.95, Sanitation=0.90, Education=0.85, Roads=0.75 |
| 3 | Vulnerability | V | 0.15 | `0.35×SC/ST% + 0.30×BPL% + 0.20×(1-literacy) + 0.15×(1-female_lit)` |
| 4 | Infrastructure Gap | I | 0.20 | Actual data vs govt norms — **THE ANTI-GAMING ANCHOR** |
| 5 | Feasibility | F | 0.10 | `0.5×budget_available + 0.3×cost_efficiency + 0.2×mplads_eligible` |
| 6 | Recency & Trend | R | 0.07 | `0.6×recency + 0.4×trend` (accelerating=1, declining=0.3) |
| 7 | Historical Bias | H | 0.10 | `1 - (sector_spend%/max_spend%)` — boosts underfunded sectors |

```
BASE_SCORE = 0.18×D + 0.20×S + 0.15×V + 0.20×I + 0.10×F + 0.07×R + 0.10×H
FINAL_SCORE = BASE_SCORE × spam_decay × concentration_penalty
PRIORITY_SCORE = FINAL_SCORE × 10  (0.0 to 10.0)
```

**Anti-Gaming Modifiers:**
- `spam_decay`: If `unique_users/total_submissions < 0.3` → ×0.70 penalty
- `concentration_penalty`: If >25% demand from one PIN → ×0.80 penalty
- Log-scaled demand: 500 organized submissions score 1.0 vs 50 genuine score 0.63 (not 0.10)

**Score Explanation Template:**
```
"Ranked #{rank} of {total} (Score: {score}/10).
DEMAND: {users} citizens from {areas} areas.
EVIDENCE: {data_source} confirms: {gap_description}. Gap: {gap_score}/1.0.
EQUITY: {sc_st%}% SC/ST, {bpl%}% BPL.
HISTORY: {category} received {past%}% of MPLADS funds last year.
FEASIBILITY: Est. cost ₹{cost}. Budget remaining: ₹{remaining}."
```

---

## DATABASE SCHEMA (MySQL 8.0.13+ — 19 Tables)

**Schema diagram:** https://dbdiagram.io/d/69305fd5d6676488ba74c3e8

### Tables This Service Reads/Writes

| Table | Layer | Read/Write | Purpose |
|-------|-------|------------|---------|
| `raw_submissions` | 1 | Read + Update status | Get new submissions |
| `submission_media` | 1 | Read | Get audio/image file paths |
| `processed_submissions` | 2 | Write | Store processed English text |
| `processing_queue` | 2 | Write | Track pipeline stages |
| `demand_clusters` | 3 | Read + Write | Create/update clusters |
| `cluster_submissions` | 3 | Write | Map submissions to clusters |
| `mplads_categories` | 3 | Read | Category definitions |
| `data_sources` | 4 | Read | Government data for enrichment |
| `infrastructure_norms` | 4 | Read | Standards for gap calculation |
| `category_severity` | 5 | Read | Severity lookup |
| `scoring_weights` | 5 | Read | Weight configuration |
| `cluster_scores` | 5 | Write | Full score breakdown |
| `mplads_fund_history` | 5 | Read | Historical spending |
| `budget_tracker` | 5 | Read | Budget remaining |
| `notifications` | 3 | Write | Notify users of rejections |
| `submission_status_log` | 2-5 | Write | Audit trail |
| `pin_code_directory` | 1 | Read | Location lookup |
| `users` | All | Read | User info for duplicate checks |

### Key Schema Rules
- `raw_submissions` is SACRED — never modified (only status updated)
- `submission_status_log` is APPEND-ONLY
- `demand_clusters.rank` uses backticks (`` `rank` ``) — MySQL 8+ reserved word
- UUIDs: `CHAR(36) DEFAULT (UUID())`

---

## DATA FLOW

```
raw_submissions (status='submitted')
    │
    ▼ LAYER 2
processed_submissions (translated_text_en + is_spam)
    │
    ▼ LAYER 3
demand_clusters + cluster_submissions (categorized)
    │
    ▼ LAYER 4
demand_clusters.data_overlay (enriched with govt data)
    │
    ▼ LAYER 5
cluster_scores (7-factor score) → demand_clusters.priority_score + rank
```

### Incremental Processing
- Only processes submissions WHERE `status='submitted'` (new since last run)
- If new submission matches existing cluster → update cluster count + re-score
- Same user submitting same issue → detected and rejected with notification

---

## KEY DESIGN DECISIONS

1. **Nightly at 23:30** — all new submissions processed in batch
2. **Edit window:** Citizens can modify until 23:30 same day, locked after
3. **Never delete originals** — raw data preserved, processing creates new records
4. **TF-IDF similarity threshold: 0.40** — lower for hackathon text diversity
5. **Keyword-based categorization** — no LLM needed for hackathon speed
6. **Log-scaled demand** — `ln(1+users)/ln(1+N_max)` prevents brigading
7. **Infrastructure gap anchor** — real govt data overrides fake demand volume
8. **Historical bias correction** — auto-rebalances toward underfunded sectors
9. **Constituency-scoped** — clusters only compared within same constituency
10. **Fallback defaults** — national averages used when district data missing
