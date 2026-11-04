# DataGenerator: Technical Requirements Document

Package `orggraph_dataset` · CLI `orggraph-dataset` · Python 3.12, Pydantic v2, NumPy, Faker

## 1. Problem statement

To build and measure an org-chart inference engine we need companies where the true
reporting lines are known. Real HR data with ground truth isn't available, so we generate it.

The hard part isn't producing records; it's producing records that are **wrong in realistic
ways**: stale titles, abbreviations, missing departments, sources that disagree, people who
left but still show up. At the same time, nothing that gives away the answer may leak into
the data the engine is allowed to see.

## 2. Requirements

### Functional

| ID | Requirement |
|---|---|
| F1 | At least 500 companies, at least 100 employees each, and at least 50,000 employees in total; scalable to 500k. |
| F2 | Each company has one valid primary hierarchy: exactly one root, no cycles, every manager in the same company. |
| F3 | Varied org shapes: 7 archetypes, 19 industries and 5 size segments (100 to 20,000 employees). |
| F4 | 1–5 observations per employee from 5 sources, each with its own coverage, freshness and noise. |
| F5 | Configurable noise profiles, from `clean` to `enterprise_complexity`. |
| F6 | Ground truth is written to a separate tree, and observed files contain only inference-safe fields. |
| F7 | Validation that proves F2 and F6, both before writing and after reloading from disk. |
| F8 | Company-level train/validation/test/challenge splits. |
| F9 | A benchmark that scores a prediction file against ground truth. |

### Non-functional

| ID | Requirement |
|---|---|
| N1 | The same seed and config produce byte-identical JSONL. |
| N2 | Memory stays bounded by one company, regardless of dataset size. |
| N3 | Every probability, distribution and vocabulary is config-driven (YAML), with typed validation. |
| N4 | Any failure stops the run with an actionable message; nothing is repaired silently. |

## 3. Approach

**Build the organization first, then put people into it.** If you start from people and
assign managers by title, the titles end up encoding the answer and the inference problem
becomes trivial. So the pipeline goes top-down:

```
plan → departments → reporting tree → positions + canonical titles → people → observations → noise
```

Ground truth is read straight off the tree. Observations are produced afterwards as noisy
*views* of each person, and only their `to_observed()` projections are exported. That makes
separation a property of the construction, with validation as an independent check on top.

For determinism, every company gets its own seed derived from `(seed, company_index)`, and
every stage draws from its own child stream. Because of that, output doesn't depend on batch
size or generation order, and changing the noise profile doesn't change the org structure.

## 4. High-level design

```
config/*.yaml ─► config.py (OrgGraphConfig, cross-checked) ─► taxonomy/ (titles, families, departments, industries)
                                                                   │
run_generation ─► plan_dataset ─► for each CompanyPlan:            ▼
                                   CompanyBuilder.build ──► CompanyRecords
                                   validate_records ──► GenerationValidationError on any issue
                                   DatasetExporter.write (streaming JSONL)
               ─► manifest, split manifest, config snapshot, summary
               ─► validate_dataset_dir (reload from disk, run every check again)
```

| Package | Responsibility |
|---|---|
| `config.py` | Pydantic models for every YAML file, `--set` overrides, cross-file reference checks |
| `constants.py` | level order, splits, sources, file layout, forbidden and allowed observed fields |
| `schemas/` | record models and their `to_observed()` projections |
| `taxonomy/` | `TitleTaxonomy`, `DepartmentCatalog`, `JobFamilyRegistry`, `IndustryCatalog` |
| `generators/` | one module per pipeline stage |
| `pipeline/` | planning, per-company builder, splitting, exporter, manifest, streaming loader |
| `validation/` | company, employee, hierarchy, observation and leakage validators |
| `evaluation/` | prediction schema, edge metrics, calibration, risk-coverage, benchmark |
| `utils/` | `Rng`, IDs, JSONL I/O, logging |

## 5. Low-level design

### 5.1 Data model

**Dataset layout**

```
<dataset>/
  observed/<split>/      companies.jsonl  employees.jsonl  observations.jsonl
  ground_truth/<split>/  companies  departments  positions  canonical_roles  reporting_edges
                         secondary_edges  observation_labels  departed_employees   (.jsonl)
  metadata/              dataset_manifest.json  split_manifest.json  generation_config.json
                         generation_summary.json  validation_report.json
```

Rows are grouped by company, in the same company order in every file. That ordering is what
lets the loader and the inference reader stream or seek one company at a time.

**Records** (`schemas/`)

| Model | Key fields | Observed projection |
|---|---|---|
| `Company` | id, name, industry, size segment, HQ, regions, archetype, seed, noise profile, split | `ObservedCompany` (drops archetype, seed, profile, split) |
| `Department` | id, name, type, parent, catalog key | none |
| `Position` | id, department, canonical title, family, seniority, level, parent position | none |
| `Employee` | id, names, canonical title, department, family, seniority, location, employment type, position | `ObservedEmployee` (id, names, employment type) |
| `ReportingEdge` | employee, manager (null for root), relationship type, depth | none |
| `EmployeeObservation` | observed title, department, family, location, source, date, status, historical manager, `missing_fields` | is itself observed |
| `ObservationLabel` | canonical values, true source, `noise_applied[]`, stale/departed flags | none |
| `DepartedEmployee` | last title, department, departed date | `ObservedEmployee` |

`CompanyRecords` bundles all of these for one company. It's the unit that moves between the
builder, the validator and the exporter.

**IDs** (`utils/ids.py`): `company_00001`, `emp_00001_000042`, `obs_…`, `pos_…`, `dept_…`.
Employee and observation numbers come from random permutations, so ID order doesn't reveal
hierarchy order. The `pos_` and `dept_` prefixes exist only in ground truth, which lets the
leakage check scan for them.

### 5.2 Determinism: `Rng`

```python
def derive_seed(*parts: int | str) -> int          # sha256 over the parts
class Rng:
    def child(self, *parts) -> Rng                 # independent stream per stage
    def bernoulli(p) / randint / choice / weighted_key / shuffle / permutation / dirichlet ...
```

`CompanyBuilder.build` uses `rng.child("metadata" | "departments" | "hierarchy" | "people" |
"departed" | "observations" | "export_order")`. Adding draws in one stage can't shift another
stage's random numbers. Timestamps are anchored to `reference_date` in config, not the clock.

### 5.3 Planning: `plan_dataset(config, settings) -> DatasetPlan`

1. `resolve_planned_total`: `planned = max(target, companies × min × 2.0)`. With a total of
   exactly `companies × min`, every company would have to be the minimum size, so the
   multiplier leaves room for size variety.
2. `fit_segment_mix`: scale the configured segment mix (180/140/100/60/20 for 500 companies)
   until it can reach `planned`, moving companies one segment at a time.
3. `assign_sizes`: within a segment, `size = min × (max/min) ** (u ** skew)` with skew 2, so
   sizes are heavy-tailed, then `fit_counts_to_total` adjusts them to hit `planned` exactly.
4. `assign_industries`: exact proportions by weight; large segments prefer industries that
   skew large.
5. `select_archetype`: weight = industry preference × archetype size weight, filtered by
   archetype min/max size.
6. `assign_splits`: challenge companies are chosen first, weighted toward complex archetypes
   and large sizes; the rest are split 60/15/15/10; holdout industries go to test.

### 5.4 Per-company build: `CompanyBuilder.build(plan) -> CompanyRecords`

**Departments**: `DepartmentGenerator.generate(...) -> OrgBlueprint`

- Each department in the industry template is included with its probability. Headcount is
  split by weight with lognormal jitter (σ 0.3), and departments below the minimum size are
  dropped.
- Sub-departments are created when the parent reaches `min_parent_headcount` and at least two
  of them qualify; 8% of the parent's headcount stays directly under the head.
- Segmented archetypes pool the tagged departments into 2–5 segments (BU, region, product
  line), each with its own copy of those departments.
- Output: `OrgBlueprint(executive_office: DeptUnit, corporate: list[DeptUnit], segments: list[SegmentUnit], departments: list[Department])`.

**Hierarchy**: `HierarchyGenerator.generate(...) -> OrgTree`

```python
@dataclass
class OrgNode:  index; parent: int | None; seniority; family; exec_role; department;
                department_key; role; depth; segment_names; region_key
@dataclass
class OrgTree:  nodes: list[OrgNode]; secondary: list[tuple[int, int]]
```

The recursion lives in `_TreeBuilder`:

```
build:            CEO → corporate groups (C-level head if the company or group is big enough)
                       → segments (segment head) → department units
build_unit(u, cap):
    level = head_level(u.headcount, cap)   # highest archetype level whose min headcount ≤ size,
                                           # strictly below the parent's level
    head  = add(parent, level, ...)
    for sub in u.subunits: build_unit(sub, below(level))
    build_people(head, u.direct_headcount, level)
build_people(head, n, level):
    if n fits one IC team (ic_team_size 4–10):  build_team(head, n)     # leaf ICs
    else:
        directors+: with p=leader_direct_ic_probability (0.3 default), add 1–2 staff/principal ICs
        k = clamp(ceil(n / mean_team), 2, span_of_control[level])
        raise k if first-line teams would exceed manager_max_team_size (2× for 5% of managers)
        for size in split_with_minimum(n, k, min=2, dirichlet α=2.5):
            child = add(head, head_level(size, below(level)), "manager")
            build_people(child, size - 1, child.level)
```

Each node gets its parent at creation time, so cycles and multiple primary managers can't
happen. Validation still checks for both. For matrix archetypes, `build_secondary` adds
dotted lines to a manager in a product or delivery department, never the primary manager,
never the person themselves and never one of their reports.

**Positions and titles**: `generate_positions(...) -> (list[Position], list[CanonicalTitle])`.
`TitleTaxonomy.title_for(family, level)` fills ladder patterns (`"Senior {ic_role}"`,
`"Director of {function}"`) from family tokens, with per-family overrides. Executive and
segment heads use `executive_title(role)`.

**People**: `EmployeeGenerator.generate(...) -> WorkforceResult`. Names come from Faker with
a locale picked by office region and reseeded per company. Locations are the HQ (55%) or
another office, with 6% remote. Ground-truth `ReportingEdge`s are derived from the node
parents. The departed employees (`Binomial(n, departed_rate)`) share the shuffled ID space.

**Observations and noise**: `ObservationGenerator.generate(...)`. For each person, each
source covers them independently with its own coverage, and the fallback source makes sure
everyone has at least one observation. History (a promotion or a transfer) is decided once
per person, so stale sources agree with each other. Then, per observation, in fixed order:

```
staleness → source conflict → title noise + ambiguity → department noise → location noise
→ job family alias → missing fields → timestamp → status → historical manager
```

Each step is a small method on `ObservationGenerator` (`_apply_staleness`,
`_apply_source_conflict`, ...) working on a mutable `_Observation`. The order is fixed
because it determines the random draws (N1).

`NoiseEngine` implements the operations themselves: 12 title operations (variant,
abbreviation, typo, truncation, suffixes, generic, legacy, ...; 1–3 chained per title),
5 department operations and 3 location operations. Probabilities come from the profile ×
source multiplier.

| Profile | Title corruption | Missing dept | Stale | Conflict | Ambiguity | Departed |
|---|---|---|---|---|---|---|
| clean | 0 | 0 | 0 | 0 | 0 | 0 |
| low_noise | 0.15 | 0.04 | 0.05 | 0.03 | 0.03 | 0.01 |
| medium_noise | 0.35 | 0.12 | 0.12 | 0.08 | 0.08 | 0.03 |
| high_noise | 0.60 | 0.25 | 0.22 | 0.15 | 0.18 | 0.06 |
| enterprise_complexity | 0.55 | 0.22 | 0.28 | 0.20 | 0.30 | 0.07 |

`historical_manager_id` is the one deliberate hint left in observed data. It's a *previous*
manager, current only part of the time, so inference has to weigh it rather than trust it.

### 5.5 Export: `DatasetExporter`

```python
class DatasetExporter:
    def __init__(self, output_dir: Path)
    def write(self, records: CompanyRecords) -> None    # observed = to_observed() only
    def flush(self) -> None                             # once per batch
    def close(self) -> dict[str, int]                   # record counts per file
```

The exporter keeps one `JsonlWriter` per (tree, split, file). JSON is serialized with sorted
keys and compact separators so the output is byte-stable. `prepare_output_dir` refuses to
overwrite a dataset without `--overwrite`.

### 5.6 Validation

```python
def validate_records(records, ctx, registry, report=None) -> ValidationReport     # in memory
def validate_dataset_dir(dataset_dir, config, min_companies=None, ...) -> ValidationReport
```

`ValidationReport` collects `(code, message, company_id, record_id)` issues and check counts.
`GlobalIdRegistry` holds dataset-wide ID sets for uniqueness checks.

| Validator | Checks |
|---|---|
| company | count, unique IDs, valid industry, size within segment bounds |
| employee | unique IDs (including departed), one holder per position, title and seniority match the position, observed list = current + departed |
| hierarchy | one root, one primary edge per person, manager exists, no self-reports, no cycles, depth matches the recomputed depth, edges agree with the position tree, position and department trees valid, secondary ≠ primary |
| observation | unique IDs, valid references, `missing_fields` exactly equals the null fields, timestamp range, everyone observed, labels 1:1 |
| leakage | per-file whitelist of allowed keys, recursive forbidden-key scan, value scan for `pos_` / `dept_` |

After export, `DatasetReader.iter_company_chunks` streams every file in lockstep one company
at a time, re-parses the rows with the Pydantic schemas, runs the same validators, and also
checks the manifest checksums and counts.

### 5.7 Benchmark

```python
def run_benchmark(dataset_dir, predictions_path, splits=None, wrong_edge_penalty=2.0,
                  calibration_bins=10, confidence_thresholds=None) -> dict
```

| Metric | Definition |
|---|---|
| precision | correct / predicted |
| recall | correct / true edges |
| coverage | employees with a prediction / current employees |
| penalized score | (correct − 2 × wrong) / true edges |
| calibration | 10 reliability bins, ECE, MCE, Brier |
| risk-coverage | precision and coverage at confidence ≥ 0.5 / 0.7 / 0.9 |

A null manager counts as an abstention. A manager predicted for the CEO or for a departed
employee counts as wrong. There are breakdowns by industry, size, archetype, noise profile,
split and seniority.

### 5.8 Configuration

| File | Holds |
|---|---|
| `dataset_defaults.yaml` | scale, seed, reference date, splits, workforce mix, benchmark penalty |
| `company_sizes.yaml` | 5 segments, default mix, size skew |
| `industries.yaml` | 19 industries: weights, archetypes, regions, `department: [p_include, weight]` |
| `departments.yaml` | 42 departments: families, owning executive, segment tags, sub-departments |
| `job_families.yaml` + `title_taxonomy.yaml` | 47 families → 533 canonical titles and about 2,900 variants |
| `org_archetypes.yaml` | levels, min headcount per level, spans, team sizes, segment layers |
| `noise_profiles.yaml`, `sources.yaml`, `locations.yaml` | noise, sources, geography |

`load_config` validates each file and then runs `_cross_reference_errors`, a set of small
checkers, one per file (`_check_departments`, `_check_archetypes`, ...). A dangling key fails
at load time. Overrides use the form `--set dataset.splits.holdout_industries=[media]`.

## 6. Interfaces

```bash
orggraph-dataset generate  --companies 500 --target-employees 50000 --seed 42 --noise-profile medium_noise
orggraph-dataset validate  --dataset-dir datasets/FirmableAssignmentDataset
orggraph-dataset benchmark --dataset-dir datasets/FirmableAssignmentDataset --split test --predictions p.jsonl
orggraph-dataset config    --section noise
```

Exit codes: `0` OK, `1` validation failed, `2` config or input error. Python entry points:
`run_generation(config, settings)`, `validate_dataset_dir(...)` and `run_benchmark(...)`, all
used by the FastAPI service.

## 7. Performance

| Dataset | Employees | Observations | Generate + export | Validate |
|---|---|---|---|---|
| 500 companies, medium_noise | 100,000 | 295,899 | 82 s | 48 s |
| 500 companies, enterprise_complexity | 200,000 | 603,189 | 238 s | passed |

Memory holds one company plus the global ID sets, about 100 MB at 500k employees.

## 8. Testing

96 tests (plus 1 opt-in full-scale run):

- unit tests per stage: planning, config, titles, structure, employees, noise, benchmark
  against hand-built answers;
- validators accept generated data and reject tampered data, one case per issue code;
- byte-identical output for the same seed, including with a different batch size;
- end to end: generate → validate → reload → validate, through both the API and the CLI.

## 9. Trade-offs and limitations

- Org shapes come from hand-set heuristics, not fitted to real org data.
- Noise is drawn per observation. Correlated staleness across a whole source is only
  approximated by per-source multipliers.
- At the minimum scale, enterprise companies are a small share of the dataset; use a larger
  `--target-employees` for a heavier mix.
