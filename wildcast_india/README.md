# WILDCAST INDIA

Wildlife and environmental intelligence for India's protected areas: a module of the National Weather Big Data Analytics Platform.

**Version 3** adds **Water Intelligence & Species Impact Analysis**, which covers:

* watering holes and other water bodies
* availability categories and field-verification priorities
* water-dependent species
* reserve-specific insights

**Version 2** added the Wildlife Intelligence module: documented species, occurrence maps, official population estimates and conservation status.

WILDCAST INDIA combines four environmental indicators into a weekly **Habitat Stress Score (HSS, 0–100)** for ten pilot protected areas:

* heat stress
* rainfall deficit / drought
* vegetation health (NDVI)
* satellite-detected fire activity

Habitat indicators describe **conditions**, not animals. Wildlife records show **documented occurrences**, not abundance. Population figures come only from cited official surveys.

## Quick start (Windows, Mac or Linux; Python 3.10 or newer)

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The app opens at http://localhost:8501.

To load real wildlife records, go to **Wildlife Intelligence** and click **Fetch records from GBIF + iNaturalist**. This needs an internet connection and takes 1–3 minutes.

**Upgrading from version 1 or 2:** copy your old `data/wildcast.db` into the new folder. The new tables, the demonstration water data and the water assessments are added automatically, and your existing data, wildlife records, uploads and alert acknowledgements are kept.

**Windows error "An Application Control policy has blocked this file":** this is Windows Smart App Control blocking pandas, not an app bug. Turn it off under Windows Security → App & browser control → Smart App Control. On a managed laptop, ask IT. Python 3.12 is recommended.

On first launch the app creates `data/wildcast.db` (SQLite) and seeds a **deterministic demonstration dataset**. This takes about 10 seconds. No API keys or paid services are needed.

You need an internet connection in the browser for the map tiles and the Leaflet library.

Run the tests with:

```bash
pytest -q
```

## Deploying online

See **DEPLOY.md** for how to run the app on Streamlit Community Cloud (free) and publish it through a Netlify front page (`netlify_site/`).

## Pages

| Page | Contents |
|---|---|
| **Wildlife Intelligence → 💧 Water Intelligence** (v3) | KPIs, an interactive water-body map (colour = availability, ring style = evidence; click a point to open its profile), filters for reserve, availability, evidence and assessment week, a monitoring-priority table with a score breakdown, reserve water conditions (rain over 30/60/90 days vs normal, temperature anomaly, NDVI, seasonal water pattern) and a **watering-hole profile**. The profile shows location, type, provenance, evidence, priority history, water level and satellite water spread, NDVI within 500 m, recent rain and temperature, and the last observation date. |
| **Wildlife Intelligence → 🐘 Species Impact** (v3) | For each reserve: its documented water-dependent species, why each matters, which indicators to watch with current values, records over 5 years and data gaps. Also four panels of weather-driven insights: **observed conditions / potential implications / research recommendations / data limitations**. |
| **Reserve Explorer → 💧 Water & wildlife report** (v3) | Rain over 30/60/90 days and deficit, temperature, vegetation, water-availability indicators, number of mapped water bodies, water-dependent species, habitat implications and recommended field investigations. It updates with the selected reserve. |
| **Wildlife Intelligence** (v2) | **Overview:** five KPIs, species diversity by reserve and group, most-documented species, recent observations, records by year. **Species Explorer:** search and filters, species profile card with taxonomy, IUCN category, reserves, record counts, timeline and population estimates. **Occurrence Map:** clustered map filtered by species, state, reserve, date, group and source; popups show record details; sensitive species appear only as ~11 km cells; CSV export. **Population Monitoring:** official estimates with method, institution, CI and citation; repeated-survey comparisons. **Conservation Status:** IUCN breakdown, threatened species by reserve, CR/EN profiles with assessment years. |
| **Habitat Monitoring** (reorganised) | **Indicator monitor:** weekly HSS or indicator heatmap across reserves, plus the latest-week detail. **Fire detections** and the **Alert centre**, unchanged from version 1. |
| **National Overview** | Five KPIs, interactive India stress map (footprints, popups, 7-day fires layer, satellite basemap toggle), ranking table with CSV export, category distribution, latest alerts. Filters: state, stress category. |
| **Reserve Explorer** | **Habitat conditions** and **Wildlife profile** tabs. The wildlife tab shows documented species, mammals, birds, reptiles and amphibians, threatened species, notable species cards, observation history and the reserve's population estimates. Habitat tab: reserve dropdown, reserve information, HSS gauge with completeness/provisional flag, four indicator cards, temperature & rainfall, HSS trend, NDVI vs seasonal baseline, fire summary, reserve map, automated research summary. |
| *(Habitat Monitoring → Fire / Alerts)* | 24 h / 7 d / 30 d detections, fire map (points or density), daily timeline, per-reserve table, record table with CSV export. Filters: date, state, reserve, spatial scope. Alert centre with severity filter, multi-select acknowledgement (persisted with user and time), CSV export. |
| **Research & Administration** | *Research → Biodiversity comparison:* diversity, threatened species, records over time and population estimates side by side with HSS. *Research → Integrated exploration:* a monthly reserve panel of wildlife records, species count and effort-normalised records against temperature, rainfall, NDVI, fires and HSS, with a correlation matrix, scatter plot and causation/effort caveats. *Admin → Wildlife data:* GBIF, iNaturalist, eBird and IUCN fetch buttons, plus uploads for Darwin Core occurrence CSVs and population-estimate CSVs. *Research → Habitat comparison:* two-reserve comparison, annual climate history, seasonal comparison (DJF/MAM/JJAS/ON), correlation matrix, four CSV downloads. *Admin:* data-source status and last successful update, records by provenance, connector refresh buttons, CSV/GeoJSON uploads with validation preview, scoring weights/thresholds/alert rules, demo reset, methodology. |

## Habitat Stress Score

The scoring logic lives in `processing/stress_scoring.py`. The full methodology is shown in the app under **Admin → Scoring methodology**.

| Indicator | Default max | Basis |
|---|---:|---|
| Heat | 25 | 7-day mean Tmax anomaly vs day-of-year baseline (60%), plus days above the baseline 90th percentile (40%) |
| Drought | 25 | 90-day rainfall deficit % = (Normal − Actual) / Normal × 100, where Normal is the same window averaged over baseline years. Damped when Normal < 50 mm. |
| Vegetation | 25 | Latest NDVI (≤ 32 days old) vs seasonal baseline (±16 days) |
| Fire | 25 | Detections inside the reserve footprint over 7 days (log-scaled) |

Categories: 0–39 Low · 40–59 Moderate · 60–79 High · 80–100 Severe.

* **Baseline:** observations more than one year older than the scored week. At least two years are required.
* **Missing data is never scored as zero.** When an indicator is missing, the total is rescaled over the indicators that are available, and the score is marked **provisional** with its completeness shown. Fire is only scored for date windows where fire data was actually retrieved.
* The HSS is a transparent screening index. It is **not an officially validated ecological index**.

## Data sources and provenance

Every record is labelled **LIVE**, **HISTORICAL**, **UPLOADED** or **SIMULATED**.

| Source | Connector | Key needed? |
|---|---|---|
| NASA POWER daily T2M_MAX, T2M, PRECTOTCORR | `ingestion/nasa_power.py` | No |
| NASA FIRMS area API (VIIRS/MODIS) | `ingestion/nasa_firms.py` | Free MAP_KEY: copy `.env.example` to `.env` and set `FIRMS_MAP_KEY` |
| MODIS MOD13Q1 NDVI via ORNL DAAC (optional) | `ingestion/ndvi.py` | No |
| CSV upload pathway for weather, NDVI and FIRMS fire CSVs | Admin page | — |

How the connectors handle data:

* Connectors retry, then log failures to `data_sources`. They never fabricate responses, and existing data is kept when a fetch fails.
* Successful live data replaces simulated rows for the same reserve and date window, so the two are never mixed.
* The demo dataset is generated **once** with a fixed seed. Its climate values are coarse, plausible regional parameters, not observations, and it contains built-in recent scenarios (for example, a drought at Gir and an NDVI gap at Sundarbans) so that every feature can be demonstrated.

## Water Intelligence

**Evidence hierarchy.** Each water body is assessed weekly (the last 26 weeks are stored) using the best evidence available:

1. **Direct** water-level measurements, no more than 21 days old
2. **Satellite** water spread or NDWI, no more than 32 days old
3. A **weather-based proxy** (90- and 30-day rainfall vs normal, reduced for heat), labelled unverified
4. Otherwise, **Insufficient data**

Proxies are computed, never stored as observations.

**Categories.** The latest value is compared with the median of earlier same-season values:

| Latest value vs seasonal median | Category |
|---|---|
| ≥ 90% | High availability |
| 60–90% | Moderate availability |
| 35–60% | Low availability |
| < 35% | **Potential water stress** |

No water body is ever reported as dry.

**Monitoring priority (0–100).** This ranks the need for **field verification**, not confirmed scarcity. Components:

| Component | Points |
|---|---:|
| Water evidence | 35 |
| Rainfall deficit | 20 |
| Heat | 10 |
| NDVI decline within 500 m | 10 |
| Fires within 5 km | 5 |
| Data uncertainty | 20 |

Bands: Priority 1 (≥60), Priority 2 (40–60), Priority 3 (20–40), Routine.

**Demonstration water data.** There are 50 illustrative water points, five per reserve, with types that fit each ecosystem: beels in Kaziranga, tidal creeks and freshwater ponds in the Sundarbans, managed water points in Gir, and so on.

* They are placed at arbitrary points inside the approximate footprints and named "Demo water point …". They are labelled **SIMULATED / ILLUSTRATIVE** everywhere, because they are not real sites.
* Their staff-gauge and satellite series come from a daily water balance driven by each reserve's stored rainfall and temperature, generated once with a fixed seed.
* Some points deliberately have no observations or a gauge that stopped reporting, so the proxy and staleness rules can be seen working.

**Real data pathway.** On **Admin → Upload data**:

* **Water bodies CSV**: name, type, coordinates, reserve; mark surveyed points `location_basis=VERIFIED`.
* **Water observations CSV**: `water_level_m` (DIRECT), `water_spread_pct`, `ndwi` or `ndvi_buffer` (SATELLITE), or `presence`.

Assessments are recomputed after every import. Uploaded records stay labelled UPLOADED, separate from the simulated ones.

**Species impact.** Water relevance comes from transparent rules in `processing/water.py`, by species, family or group:

* elephants and rhinos: high
* deer and bovids: moderate (water + forage)
* large cats and dhole: indirect (prey concentration)
* waterbirds, crocodilians, otters, fish and amphibians: high

Only species documented for the reserve are assessed, either through occurrence records or official estimates, so before a GBIF/iNaturalist fetch the list is short and its data gaps are flagged.

## Wildlife data

| Source | Connector | Key | What it provides |
|---|---|---|---|
| GBIF occurrence API | `ingestion/gbif.py` | none | Animal records inside each reserve footprint (2000 onward, up to 1,500 per reserve by default), taxonomy, IUCN category, common names |
| iNaturalist API | `ingestion/inaturalist.py` | none | Research-grade observations; obscured locations are respected |
| eBird API 2.0 | `ingestion/ebird.py` | `EBIRD_API_KEY` (free) | Bird observations from the last 30 days. Older eBird records reach the app through GBIF. |
| IUCN Red List API v4 | `ingestion/iucn.py` | `IUCN_API_TOKEN` (free) | Latest category and assessment year |
| Official population estimates | `data/population_estimates.csv` | — | 19 cited estimates: NTCA/WII tiger estimation 2022 (and Sundarbans 2018), Gujarat Forest Department lion estimations for 2015/2020/2025, Kaziranga rhino censuses for 2006–2022 |

To set up keys, copy `.env.example` to `.env`, paste in the keys, and restart the app.

Every occurrence record keeps:

* source and dataset
* observation date
* scientific name
* coordinates and their uncertainty
* record identifier and link
* verification status
* retrieval time
* provenance (LIVE / HISTORICAL / UPLOADED)

**Rules applied to wildlife data:**

* **No occurrence records ship with the app** and none are simulated. Wildlife locations are never generated.
* **Duplicates:** each record has a unique key. iNaturalist records that GBIF also holds are keyed `inat:<id>`, so they are stored only once. Re-fetching adds nothing new.
* **Sensitive species:** IUCN CR/EN species and a list of poaching-sensitive taxa (tiger, lion, rhino, elephant, pangolins, gharial, star tortoise and others) are stored and shown with coordinates snapped to a 0.1° (~11 km) grid. Source-obscured records are flagged.
* **Population estimates** are kept entirely separate from occurrence counts. Comparisons are offered only between repeated surveys of the same scope.
* **Before publishing, verify the Ranthambore, Periyar and Similipal tiger figures.** They come from secondary sources that cite the 2022 report; the other figures do too. Check all of them against the original reports at ntca.gov.in.

## Boundaries

No official boundary polygons are bundled, because verified polygons were not available offline and boundaries are not invented.

* Each reserve uses its published coordinates and an **approximate circular footprint** with an area equal to its published area. It is drawn dashed and labelled "approximate".
* To use verified boundaries, upload a GeoJSON FeatureCollection on the Admin page (for example, from Protected Planet / WDPA, subject to its licence). Each feature needs a `pa_id` (BAN, NAG, COR, RAN, SIM, KAZ, KAN, GIR, PER, SUN) or a `name` property.
* After an upload, fire detections are reassigned to reserves automatically.
* Reserve coordinates and areas in `data/sample_reserves.csv` are approximate published values. Verify them before operational use.

## Project layout

```
app.py                      entry point and navigation
config/settings.py          paths, theme, default scoring config
database/schema.py, db.py   SQLite schema (7 original + 4 wildlife + 3 water tables) and the shared data-access layer
ingestion/                  nasa_power, nasa_firms, ndvi, gbif, inaturalist, ebird, iucn, http helper, demo_data, water_demo
processing/                 stress_scoring, alerts, geospatial, cleaning, pipeline, wildlife, water (assessment, priority,
                            species traits, insights), water_io (uploads)
components/                 sidebar/theme, cards, charts, maps, filters, cached data access
dashboard/                  overview, reserve_explorer, habitat_monitoring, fire_alerts, wildlife, water, research_admin
tests/                      test_scoring.py, test_wildlife.py, test_water.py, test_app.py, mock_apis.py (test-only fixtures)
```

Changes from the suggested structure: `ingestion/demo_data.py`, `ingestion/http.py`, `processing/pipeline.py`, `components/data.py` and `components/filters.py` were added so that this logic is shared rather than duplicated. A `.streamlit/config.toml` file sets the theme.

## Known limitations

* **Water data is illustrative.** Every watering hole and water measurement shipped with the app is illustrative. The water categories therefore demonstrate the method; they say nothing about real conditions until surveyed points and measurements are uploaded.

* **Wildlife connectors weren't tested live.** GBIF, iNaturalist, eBird and IUCN were unreachable from the build environment. The connectors were tested against sample responses in each API's documented format and against simulated network failures. The first live fetch on your machine is the first real-world run, so check the Admin status table afterwards.
* **Diversity counts are partial.** They are based on the records retrieved (capped per reserve), so they understate true species richness.

* The NASA endpoints could not be reached from the build environment. The connectors were tested only for their failure handling (a clear error message, with existing data kept), not against live responses.
* Fire coverage for uploads is tracked as a single overall date span. Uploading two batches far apart in time marks the gap between them as covered.
* NDVI from ORNL is a point sample (about 4×4 km around the reserve centre), not a whole-reserve mean.
