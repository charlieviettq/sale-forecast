# Monthly Sales Forecast (2015-11) — Modeling & Deployment

Forecast the number of units sold in November 2015 for every `(shop_id, item_id)` pair in `test.csv`, and serve the forecasts to internal users through a web page where they type an `item_id`.

**Live demo:** https://charlieviettq.github.io/sale-forecast/ (static build of the same page and API payloads, see [docs/deployment.md](docs/deployment.md#4-what-is-implemented))

[![Test and deploy static demo](https://github.com/charlieviettq/sale-forecast/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/charlieviettq/sale-forecast/actions/workflows/deploy-pages.yml)

| Deliverable | Location |
|---|---|
| Task 1 — analysis, modeling, evaluation (single notebook) | [`notebooks/forecast.ipynb`](notebooks/forecast.ipynb) |
| Forecast artifacts produced by the notebook | [`artifacts/`](artifacts) |
| Task 2 — web service (FastAPI + HTML) | [`app/`](app), [`Dockerfile`](Dockerfile) |
| Task 2 — deployment patterns & choice | [`docs/deployment.md`](docs/deployment.md) |
| Tests | [`tests/test_api.py`](tests/test_api.py) |

## Results (expanding-window backtest, validation months 31–33)

| Model | item WAPE (primary) | Pair RMSE | Pair RMSE (clip 0–20) | Bias |
|---|---|---|---|---|
| Previous month (best naive) | 0.600 | 3.21 | 1.05 | −11.9% |
| Previous month × seasonal ratio | 0.614 | 3.27 | 1.07 | −6.8% |
| **LightGBM Tweedie (final)** | **0.510** | **3.11** | **0.84** | −9.6% |

- The model beats the best baseline in **every fold**: item-WAPE is 9%, 13% and 18% better on months 31, 32 and 33.
- November-2015 total on the test grid: ~67k units. This is within 1% of "October actuals × historical Nov/Oct ratio".

## Key points of the approach

1. **Test is a full Cartesian grid** (42 shops × 5,100 items, ~87% zeros). Training is done on a monthly grid built the same way (`active shops × items sold that month`). An experiment in the notebook (§5.5) shows that training only on rows with transactions gives a large over-forecast.
2. **The documentation differs from the data.** The date format is `dd.mm.yyyy`, the name columns are missing, and there is an extra index column. All of these are verified explicitly (§1.2-1.3).
3. **Duplicate shops** (0→57, 1→58, 11→10) are detected from their activity timelines and category mix, because shop names are not available (§3.2).
4. **Metric defined from evidence.** The assignment gives no metric. In one validation month, 5 event-type pairs produce ~80% of the squared error, so pair-level RMSE is a noisy selection metric. Users look at item totals, so **item-level WAPE** is the primary metric, with pair RMSE (raw and clipped at 20) and **bias** as secondary and guardrail metrics (§5.1).
5. **Loss chosen by backtest.** Tweedie on the raw target beats L2 and L2-clipped-at-20. Clipping makes every high-volume item under-forecast (§5.4).
6. **Cold start without names.** Adjacent `item_id`s behave like the same product family (IDs follow name order), so they are used together with category launch statistics for brand-new items (§3.7).
7. **Leakage-proof by test.** The features for month 33 are rebuilt from data ≤ 32 only and asserted to be identical (§4.2).
8. **Uncertainty.** Split-conformal 80% intervals for item totals, with coverage checked out-of-time (§6.5).

Section numbers (§) refer to `notebooks/forecast.ipynb`.

## Task 2 — Deployment

**Pattern: batch prediction + lookup serving.**
- The forecasts for all 214,200 test pairs are computed offline by the notebook and saved to `artifacts/`.
- A small FastAPI service loads them at startup and answers requests by lookup, packaged as a Docker image.
- Why: the user only enters an `item_id`, the horizon is one fixed month, and every answer is known in advance. Running the model per request would add latency, cost and failure modes without changing the result.

Implemented:
- `GET /`: web page with the total, the 80% interval, a low-confidence flag for new items, and a per-shop breakdown.
- `GET /api/forecast/{item_id}`: JSON API.
- `GET /health`: liveness check plus model metadata.
- Public demo: `scripts/build_static.py` writes every API answer to a static JSON file. GitHub Actions runs the tests, builds the site and deploys it to GitHub Pages on every push.

**Full explanation:** see [docs/deployment.md](docs/deployment.md). It covers the situation analysis, the deployment patterns considered, why batch was chosen, the production lifecycle, known gaps and an FAQ.

## How to run

Place the raw CSVs in `data/raw/` (they are not committed).

Reproduce the analysis and regenerate the artifacts (~30 min on a laptop):

```bash
pip install -r requirements.txt
jupyter nbconvert --to notebook --execute --inplace notebooks/forecast.ipynb
```

Run the web app with Docker:

```bash
docker build -t forecast-api .
docker run --rm -p 8000:8000 forecast-api
# open http://localhost:8000
```

Run locally without Docker, and run the tests:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest -q
```

## Limitations & next steps

Production gaps (no auth, no monitoring, retraining not automated): see [docs/deployment.md](docs/deployment.md#6-known-gaps).

Modeling:

- No item/shop names, promotions or release calendars. The largest remaining errors are launches and event products whose spikes are not visible in the history.
- Forecast scope = items in `test.csv`. Other item IDs return 404 by design (no shop assignment is known for them).
- Next: move the notebook pipeline into a versioned training package run by an orchestrator, add drift monitoring, and use hierarchical reconciliation if item-level and shop-level totals are both consumed.
