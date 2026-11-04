# Application: Technical Requirements Document

Package `firmable` · FastAPI · entry point `firmable.main:app`

## 1. Problem statement

The two Python packages (DataGenerator and Inference) are libraries and CLIs. The frontend
needs an HTTP API over them that can:

- list datasets and companies, with filters;
- run inference for one company on demand and return the org chart in pieces small enough
  to render;
- explain any single employee's prediction;
- run the slow work (dataset generation, whole-split inference, evaluation) without
  blocking requests;
- report evaluation metrics without ever exposing ground truth.

## 2. Requirements

### Functional

| ID | Requirement |
|---|---|
| F1 | Dataset discovery from disk, with manifest summary, facets and noise profiles. |
| F2 | Company list with search, filters, sorting and pagination; company detail from observed data only. |
| F3 | Per-company inference, on demand and cached. |
| F4 | Org chart from any root to a given depth, with a cap on children per node; a list of unresolved employees with reasons. |
| F5 | Employee list and filters; employee detail (profile, raw observations, predicted manager, candidates, evidence, chain of command, reports); cross-company name search. |
| F6 | Background jobs: generate a dataset, validate a dataset, infer splits, evaluate splits; job status polling. |
| F7 | Evaluation reports stored and listed; per-company evaluation as aggregate metrics. |
| F8 | No endpoint returns ground-truth reporting lines or generator-only fields. |

### Non-functional

| ID | Requirement |
|---|---|
| N1 | Cached company endpoints respond in under 100 ms. |
| N2 | A request never runs longer than one company's inference; anything bigger is a job. |
| N3 | One error shape for every failure; a request ID on every response. |
| N4 | Fully configured through `Infra` settings; testable with injected settings (no globals). |

## 3. Approach

The service is a **modular monolith**: one process, with strict layering inside it.

```
HTTP  ─►  api/v1 routers  ─►  services  ─►  orggraph_dataset / orggraph_inference
             │                    │
          schemas/             core/ (errors, jobs, middleware)
```

- **Routers are thin.** They parse and validate input, call one service method and return a
  schema. No logic lives in them.
- **Services own the logic.** They are the only layer that imports the two packages. Each
  service gets its dependencies through its constructor.
- **Inference results are cached as a `CompanyView`.** The expensive step (engine run plus
  derived graph maps) happens once per company. Every read endpoint for that company then
  becomes a dictionary lookup.
- **Slow work goes to a job manager.** POST returns `202` and a job, and the client polls.
- **Ground truth is reachable from exactly one service** (`EvaluationService`), and it only
  returns numbers.

I picked a monolith over separate services because everything shares one in-memory cache
and one dataset directory. Splitting it would add network hops and cache coherence problems
without any real benefit at this scale.

## 4. High-level design

```
create_app(settings)
 ├─ configure_logging(settings)
 ├─ ServiceContainer.build(settings) ─► app.state.services
 │     JobManager(workers)
 │     DatasetService(settings, jobs)
 │     InferenceService(settings, datasets, jobs)       LRU[(dataset, company)] → CompanyView
 │     CompanyService(datasets, inference)
 │     EmployeeService(datasets, inference)              search index per dataset
 │     OrgChartService(inference)
 │     EvaluationService(datasets, inference, jobs)      the only reader of ground_truth/
 ├─ CORS, RequestLoggingMiddleware
 ├─ install_error_handlers
 └─ routers: health, datasets, companies, employees, inference, evaluation, jobs  (prefix /api/v1)
```

```
src/firmable/
  main.py            create_app, app, run
  api/deps.py        services(request) -> ServiceContainer
  api/v1/*.py        one router per resource
  services/*.py      one service per domain
  schemas/*.py       Pydantic request/response models
  core/errors.py     AppError hierarchy + handlers
  core/jobs.py       Job, JobContext, JobManager
  core/middleware.py RequestLoggingMiddleware
```

## 5. Low-level design

### 5.1 Composition: `ServiceContainer`

```python
@dataclass
class ServiceContainer:
    settings: CommonSettings
    jobs: JobManager
    datasets: DatasetService
    inference: InferenceService
    companies: CompanyService
    employees: EmployeeService
    orgchart: OrgChartService
    evaluation: EvaluationService

    @classmethod
    def build(cls, settings: CommonSettings) -> ServiceContainer
```

Routes get the container with `Depends(services)`, which reads `request.app.state.services`.
Tests call `create_app(LocalSettings(datasets_dir=tmp, ...))`, so nothing needs patching.

When a dataset is regenerated, `DatasetService.on_invalidate(listener)` notifies the
company, employee and inference services, and each drops its caches for that dataset.

### 5.2 `DatasetService`

```python
def list(self) -> list[DatasetSummary]                 # every dir under datasets_dir with a manifest
def detail(self, dataset_id) -> DatasetDetail
def reader(self, dataset_id) -> ObservedDatasetReader  # cached per dataset
def dataset_dir / artifacts_dir / predictions_path(dataset_id, split) -> Path
def check_split(self, dataset_id, split) -> None       # 404 for unknown splits
def noise_profiles(self) -> list[NoiseProfileInfo]
def generate(self, request: GenerateDatasetRequest) -> Job   # 403 if disabled, 409 if exists, 422 if too big
def validate(self, dataset_id) -> Job
```

Dataset IDs must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` and have a manifest, otherwise
the service returns 404. That also rules out path traversal. Generation calls
`run_generation` from the DataGenerator inside a job, and the job reports progress per batch.

### 5.3 `InferenceService` and `CompanyView`

```python
@dataclass
class CompanyView:
    dataset_id: str
    split: str
    company: ObservedCompany
    inference: CompanyInference              # engine output: profiles, graph, predictions, stats
    names: dict[str, str]
    employment_types: dict[str, str]
    observations: dict[str, list[EmployeeObservation]]
    children: dict[str, list[str]]           # derived in __post_init__
    subtree_size: dict[str, int]             # derived in __post_init__
    edges: dict[str, str]                    # confident edges only

class InferenceService:
    def company(self, dataset_id, company_id, refresh=False) -> CompanyView
    def cached(self, dataset_id, company_id) -> CompanyView | None
    def run_splits(self, dataset_id, splits) -> Job
    def runs(self, dataset_id) -> list[dict]
```

`company()` flow:

```
key = (dataset_id, company_id)
with lock: hit → move_to_end(key), return
data = reader.load_company(company_id)         # byte-offset seek
result = engine.infer_company(data)
view = CompanyView(...)                         # builds children / subtree sizes / edges once
with lock: cache[key] = view; evict oldest beyond company_cache_size (64)
```

`__post_init__` computes the manager → children map, sorted by rank, then subtree size,
then name. It also computes subtree sizes with an iterative post-order walk, which avoids
recursion limits on deep trees. Before I precomputed these, every org-chart and employee
call rebuilt them and took 2–3 s on a large company; now cached calls take 20–60 ms.

Split inference (`run_splits`) runs `run_dataset` per split inside a job and writes
`_artifacts/<dataset>/predictions/<split>.jsonl`. `JobManager.active(kind, key)` returns the
running job if the same split set is already in progress, instead of starting a duplicate.

### 5.4 `OrgChartService`

```python
def roots(self, view) -> list[str]        # inferred root, then unmanaged people who have reports (largest first)
def chart(self, dataset_id, company_id, root_id=None, depth=2, max_children=50) -> OrgChart
def unresolved(self, dataset_id, company_id, page, page_size, reason=None) -> Page[UnresolvedEmployee]
```

`chart` does a breadth-first walk from the roots (or `root_id`) down to `depth`, taking at
most `max_children` per node from `view.children`. Each `OrgNode` carries `direct_reports`,
`subtree_size`, `children_loaded` and confidence, so the UI knows whether a node can expand
and how many reports it's hiding. Edges are confident edges only. `unresolved` lists
abstentions with the reason (`below_threshold`, `departed`, `no_candidates`,
`cycle_broken`) and the best tentative candidate from the evidence.

### 5.5 `EmployeeService`

```python
def list(self, dataset_id, company_id, page, page_size, q=None, department=None,
         seniority=None, resolved=None, include_departed=True) -> Page[EmployeeSummary]
def detail(self, dataset_id, company_id, employee_id) -> EmployeeDetail
def search(self, dataset_id, q, page, page_size, company_id=None) -> Page[SearchHit]
```

`detail` assembles everything from the `CompanyView`: the profile, the raw observations, the
predicted manager with its confidence, the top candidates with probabilities and matched
signals, the chain of command (walking `edges` upward) and direct reports.

`search` uses a per-dataset index of `_IndexEntry(employee_id, company_id, company_name,
full_name, split, haystack)`, built once from observed employee files without running
inference. A query is a substring match on `haystack` (lower-cased name and ID). Prefix
matches on the name rank first.

### 5.6 `CompanyService`

The company list is read once per dataset from `observed/*/companies.jsonl` and kept in
memory (500 rows). Filters, sorting and pagination are done in Python, and `facets` counts
splits, industries and sizes for the filter dropdowns. `detail` adds observation counts and,
if the company is already cached, its inference stats. It never triggers inference itself.

### 5.7 `EvaluationService`

```python
def run(self, dataset_id, splits, rerun_inference) -> Job
def list(self, dataset_id) -> list[EvaluationSummary]
def get(self, dataset_id, evaluation_id) -> EvaluationReport
def company(self, dataset_id, company_id) -> CompanyEvaluation
```

The `run` job infers any split that has no stored predictions (or all of them if
`rerun_inference`), concatenates the prediction files, calls `evaluate_predictions`, and
writes `_artifacts/<dataset>/evaluations/<id>.json`. `company()` reads only that company's
rows from `reporting_edges` and `departed_employees`, scores the cached predictions with the
DataGenerator's `EdgeCounts` and `Calibration`, and returns metrics only, with no per-employee
truth.

### 5.8 Jobs: `core/jobs.py`

```python
@dataclass
class Job:  id; kind; params; status: queued|running|succeeded|failed; progress: float;
            message; result: dict | None; error: str | None; created_at; started_at; finished_at

class JobManager:
    def __init__(self, workers: int)                         # ThreadPoolExecutor
    def submit(self, kind, params, fn: Callable[[JobContext], dict]) -> Job
    def get(self, job_id) -> Job                             # NotFoundError if unknown
    def list(self) -> list[Job]                              # newest first
    def active(self, kind, key) -> Job | None                # de-duplication
```

`fn` receives a `JobContext` and calls `ctx.progress(fraction, message)`. Exceptions are
caught, logged, and stored as `status="failed", error=...`. State is guarded by one lock.
Threads are enough here because the heavy parts (JSON parsing, NumPy, I/O) are short, and
the API stays responsive with 2 workers.

### 5.9 Errors and middleware

```python
class AppError(Exception):            status_code = 400; code = "bad_request"
class NotFoundError(AppError):        404 "not_found"
class ConflictError(AppError):        409 "conflict"
class ForbiddenError(AppError):       403 "forbidden"
class UnprocessableError(AppError):   422 "unprocessable"
```

`install_error_handlers` maps them to `{"error": {"code", "message", "details"}}`. Unhandled
exceptions become a 500 with the same shape, and the traceback is logged but not returned.
`RequestLoggingMiddleware` reuses an incoming `X-Request-ID` or creates one, echoes it on
the response, and logs method, path, status and duration.

## 6. API contract

All routes are under `/api/v1`. Paginated responses are `{items, total, page, page_size}`.

| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/health/ready` | readiness: `ready` or `degraded`, plus per-check results (generator config, datasets dir, dataset list) |
| GET / POST | `/datasets` | list / start a generation job |
| GET | `/datasets/{d}`, `/datasets/{d}/facets` | manifest detail, filter values |
| POST | `/datasets/{d}/validate` | job |
| GET | `/config/noise-profiles` | |
| GET | `/datasets/{d}/companies` | `page, page_size, split, industry, size_segment, q, min/max_employees, sort, descending` |
| GET | `/datasets/{d}/companies/{c}` | observed detail |
| POST | `/datasets/{d}/companies/{c}/inference` | `refresh` |
| GET | `.../companies/{c}/org-chart` | `root_id, depth, max_children` |
| GET | `.../companies/{c}/org-chart/unresolved` | `reason`, pagination |
| GET | `.../companies/{c}/employees`, `.../employees/{e}` | |
| GET | `/datasets/{d}/employees/search` | `q` (≥ 2 chars), `company_id` |
| GET / POST | `/datasets/{d}/inference` | stored runs / start a split job |
| GET / POST | `/datasets/{d}/evaluations`, GET `.../evaluations/{id}` | |
| GET | `.../companies/{c}/evaluation` | aggregates only |
| GET | `/jobs`, `/jobs/{id}` | |

The OpenAPI docs are at `/docs` (disabled in production).

## 7. Testing

15 tests in `src/firmable/tests`, run against a real 8-company dataset generated once per
session. Nothing is mocked.

| Test | Covers |
|---|---|
| health, openapi | routing, versioned prefix |
| datasets | discovery, detail, facets |
| companies | pagination, filters, sorting, observed-only detail (no hidden fields) |
| inference and org chart | on-demand inference, depth and child caps, subtree expansion, unresolved list |
| employees | list filters, detail contents, search |
| evaluation | per-company metrics contain no manager IDs |
| jobs | generate, validate, split inference, evaluation end to end |
| errors | 404 / 409 / 403 / 422 shapes |
| settings | environment selection, nested env vars, production guards |

`Backend/tests` adds a cross-package check: for the same company, the API returns exactly
what `run_dataset` writes directly.

## 8. Trade-offs and limitations

- **In-process state.** The cache and job state live in memory, so the service runs as one
  worker per container. Scaling out means moving jobs to a queue and the cache to something
  shared; the service interfaces wouldn't change.
- **Cold start.** The first request for a large company waits for inference (about 16 s for
  the largest). Warming the biggest companies at startup would hide it.
- **No auth.** It's expected to sit behind a gateway or reverse proxy.
