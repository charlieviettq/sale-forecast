# Deployment: patterns considered and the choice made

> Assignment, Task 2: *"Deploy this method by your framework of choice. Explain some deployment patterns fit to this situation, and your choice to implement."*

**Short answer:** the forecasts are computed **offline in batch** and served by a small **FastAPI lookup service** in a Docker container. The input is only an `item_id`, and every possible answer (one month, 5,100 items × 42 shops) is known in advance, so running the model at request time would add cost and risk without adding value.

---

## 1. Situation analysis

The deployment pattern should follow from the properties of the problem, not from habit.

| Property of this problem | Consequence for deployment |
|---|---|
| The user only enters an `item_id`. No new information arrives at request time | There is nothing to compute per request |
| Fixed horizon: one month (2015-11) | Answers do not change between requests |
| Small, finite answer space: 5,100 items × 42 shops = 214,200 values | Every answer can be pre-computed in seconds and kept in memory (a few MB) |
| Features need the full sales history (lags, lagged target encodings, lifecycle) | Computing features per request would need a feature store or a heavy recomputation over ~3M transactions |
| Data is refreshed monthly | Real-time freshness has no business value |
| Internal users, low traffic | No need for autoscaling or a complex serving platform |

---

## 2. Deployment patterns that could fit

### 2.1 Batch prediction + lookup serving *(chosen)*
- **How it works:** a batch job (here, the notebook) scores every `(shop, item)` pair and writes the results to artifacts. A thin API loads them and answers requests by lookup.
- **Pros:**
  - Millisecond latency; no model and no ML libraries in the request path.
  - Cheap and simple to run.
  - Reproducible: the numbers on the page are exactly the audited artifact.
- **Cons:**
  - Can only answer what was pre-computed.
  - New data requires re-running the batch.
- **Fit:** excellent. The answer space is small and fixed for the month.

### 2.2 Online (real-time) inference
- **How it works:** the API loads the model, builds features for the requested item, and predicts on every call.
- **Pros:** can answer arbitrary or new inputs.
- **Cons here:**
  - Features depend on the full history, so each request needs either a feature store or recomputation over millions of rows.
  - Higher latency and more failure modes, yet the output would be identical to the batch result.
- **Fit:** poor for this problem. It is the right pattern only when requests carry new information.

### 2.3 Serverless lookup (AWS Lambda / Cloud Functions)
- **How it works:** the same pre-computed lookup, served by a function billed per call.
- **Pros:** near-zero cost at low traffic; no server to manage.
- **Cons:** cold starts while loading the artifact; package size and runtime limits.
- **Fit:** acceptable alternative. A small always-on container is simpler and more predictable for an internal tool.

### 2.4 Embedded in a BI tool / data warehouse
- **How it works:** write forecasts to a warehouse table and expose them in a dashboard (Metabase, Looker, …).
- **Pros:** familiar to analysts; easy filtering, aggregation and comparison with actuals.
- **Cons:** the assignment asks for a web page with an `item_id` input.
- **Fit:** good complement, not a replacement. The same batch output can feed both.

### 2.5 Static hosting of batch predictions (GitHub Pages / CDN) *(used for the public demo)*
- **How it works:** because every answer is pre-computed, each item's response is written as a static JSON file. The same web page reads those files directly; there is no server at all.
- **Pros:**
  - Free and always on: no cold starts or sleeping instances.
  - Cached by a CDN.
  - Nothing to patch or scale.
  - Redeployed automatically on every push.
- **Cons:**
  - Every forecast is public. Fine for a demo, not for confidential internal data.
  - No server-side logic: no authentication, no request logging, and no input validation beyond the browser.
- **Fit:** ideal for a public demo of a batch system. For internal production use, the FastAPI service (behind SSO) is the better choice.

### 2.6 Streaming inference *(listed to rule out)*
- **How it works:** update forecasts continuously as transactions arrive (Kafka / Flink).
- **Fit:** none. The business question is monthly; minute-level freshness adds complexity without value.

---

## 3. The choice and why

**Chosen: batch prediction + in-memory lookup, served by FastAPI, packaged with Docker.**

1. **Answers are known in advance.** The input is only `item_id` within a fixed set of 214,200 values, so pre-computing is the natural design.
2. **Forecasts are static within the month.** Running the model per request produces the same numbers at a higher cost.
3. **Simplest and lowest-risk option.** No model in the request path, a small dependency set, and few moving parts that can break.
4. **Matches the audience.** Internal users and low traffic, so one small container is enough; no autoscaling or Kubernetes needed.
5. **Easy to evolve.** If the scope grows (more items, more months), the lookup can move from memory to a key-value store (Redis / DynamoDB) or a warehouse table without changing the API contract.

**When we would switch to online inference:**
- Requests start carrying new information at query time, e.g. forecasting a product that is described in the request.
- The answer space becomes too large to pre-compute, e.g. arbitrary future months × scenarios.

---

## 4. What is implemented

```
OFFLINE (once per forecast cycle)                          ONLINE (per request)
data/raw/*.csv -> notebook: features + LightGBM -> artifacts/            browser
                                                    |- predictions.parquet     |  GET /api/forecast/{item_id}
                                                    |- item_forecast.parquet   v
                                                    '- metadata.json  -> FastAPI (in-memory lookup) -> JSON / HTML
```

| Component | Details |
|---|---|
| Batch job | `notebooks/forecast.ipynb` writes `artifacts/predictions.parquet` (214,200 shop-item forecasts), `artifacts/item_forecast.parquet` (item totals + 80% intervals) and `artifacts/metadata.json` (model version, parameters, backtest metrics) |
| API | `app/main.py` (FastAPI). Artifacts are loaded once at startup into a dictionary keyed by `item_id` |
| `GET /` | Web page: enter an `item_id`, see the total forecast, the 80% interval, a low-confidence flag for brand-new items, and the per-shop breakdown |
| `GET /api/forecast/{item_id}` | JSON response. Invalid input (`abc`, `-1`, `1.5`) → `422`; item outside the forecast scope → `404` with a clear message |
| `GET /health` | Liveness check plus model metadata (trees, training months, creation time) |
| Docker | `python:3.12-slim`; contains only the serving code and the three artifacts (no raw data, no training stack); runs as a non-root user; has a healthcheck |
| Tests | `tests/test_api.py`: health, totals match the artifact, new-item flag, 404, 422, index page |
| Public demo | `scripts/build_static.py` renders every API answer to `site/api/forecast/{item_id}.json` (generated by the same `ForecastStore`, so it is identical to the API) plus the same `index.html`. `.github/workflows/deploy-pages.yml` runs the tests, builds the site and deploys it to GitHub Pages: https://charlieviettq.github.io/sale-forecast/ |

**Why the page shows both a total and a per-shop breakdown:** the model predicts at `(shop, item)` level and the user asks by item. The item total is the sum over shops. The model uses a mean-type loss (Tweedie), so these sums are meaningful: the November total is within ~1% of the seasonal expectation. Small and brand-new items tend to be under-forecast, so brand-new items are flagged as low confidence.

**Run it:**

```bash
docker build -t forecast-api .
docker run --rm -p 8000:8000 forecast-api
# open http://localhost:8000 (API docs at http://localhost:8000/docs)
```

---

## 5. Operating it in production (proposed)

```
monthly schedule (cron / Airflow)
  |- extract last month's transactions
  |- run the training pipeline (notebook code moved to a package / run with papermill)
  |    |- backtest gate: item-WAPE must beat the "previous month" baseline and stay
  |    |  within tolerance of the current model, otherwise keep the current model and alert
  |    '- write versioned artifacts: predictions, item totals, model, metadata
  |- build & push image  forecast-api:<YYYY-MM>
  '- blue-green switch -> monitor
```

- **Release strategy:**
  - **Shadow:** score the candidate model offline and compare it with the current one on the backtest before switching.
  - **Blue-green:** switch the image tag atomically, keeping the previous image for instant rollback.
- **Why not canary / A-B testing:** a forecast can only be judged after the month ends, and splitting traffic does not change outcomes. Offline shadow comparison gives the same information sooner.
- **Monitoring:**
  - Once actuals arrive, compute the realised item-WAPE and bias and compare them with the backtest.
  - Track input data drift (volumes, new items/shops, price levels).
  - Alert on large deviations.

---

## 6. Known gaps

Acceptable for an internal take-home; to address before real use:

- **No authentication:** the service should sit behind SSO / VPN.
- **No request logging, metrics or alerting** beyond `/health`.
- **Retraining is not automated yet:** the pipeline still lives in the notebook.
- **Forecast scope is limited to the items in `test.csv`:** other item IDs return `404` because no shop assignment is defined for them.

---

## 7. FAQ

| Question | Answer |
|---|---|
| What if a user enters an item that is not in the test set? | `404` with an explanation. Without knowing which shops carry the item there is nothing well-defined to forecast. Extending the scope is a business decision (which item × shop combinations to cover) |
| How does this scale to millions of items? | Keep the batch design; move the lookup from memory to a key-value store or warehouse table. The API contract stays the same |
| When is online inference the better choice? | When requests contain new information at query time, or the answer space is too large to pre-compute |
| How do you know a new model is better before deploying it? | A backtest gate against the baseline and the current model, plus a shadow comparison. After the month ends, compare the realised WAPE and bias |
| Who can access the service? | Nobody outside the internal network should; in production it would sit behind SSO / VPN (not implemented in this take-home) |
