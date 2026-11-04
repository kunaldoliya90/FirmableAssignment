# Inference: Technical Requirements Document

Package `orggraph_inference` · CLI `orggraph-infer` · Python 3.12

## 1. Problem statement

For each company we get:

- a flat list of employees: id, name and employment type, nothing else;
- several observations per employee, each from one source (HR export, company directory,
  internal directory, public profile, historical snapshot), with title, department, job
  family, location, date and status;
- each of those fields may be missing, stale, abbreviated, misspelled or in conflict with
  another source.

We have to produce, for every employee, a predicted primary manager (or an explicit
abstention), a confidence in [0, 1], and the evidence behind the decision.

A wrong reporting line costs more than a missing one. The benchmark charges two correct edges
for every wrong edge. So the design goal is high precision with honest confidence, not
maximum coverage.

## 2. Requirements

### Functional

| ID | Requirement |
|---|---|
| F1 | Read only `observed/` data. Never open anything under `ground_truth/`. |
| F2 | Normalize free-text titles, departments and locations into canonical values. |
| F3 | Combine conflicting observations into one profile per employee. |
| F4 | Predict at most one primary manager per employee, and abstain when unsure. |
| F5 | Emit a confidence and machine-readable evidence for every prediction. |
| F6 | The output graph must have no cycles, no self-reports and at most one root. |
| F7 | Employees who have left the company get no manager. |
| F8 | Write predictions in the DataGenerator `Prediction` schema, so the benchmark scores them directly. |
| F9 | Infer one company on demand (for the API) and whole splits in batch (for evaluation). |

### Non-functional

| ID | Requirement |
|---|---|
| N1 | Deterministic: the same input gives byte-identical output, across processes too. |
| N2 | A 7,000-employee company finishes within about 20 s on one core. A 15k-employee split finishes in under a minute. |
| N3 | Every tunable (weights, thresholds, caps) lives in config, not in code. |
| N4 | No second taxonomy: reuse the DataGenerator's config and `TitleTaxonomy`. |

## 3. Approach

I treat this as a ranking problem per employee, followed by a global clean-up pass over the
whole graph.

1. **Normalize, then vote.** Each observation is normalized on its own, then the
   observations vote. A vote is weighted by how reliable its source is and how recent it is.
   This turns 3–5 messy rows into one profile with a confidence on every attribute.
2. **Restrict who can be a manager.** A manager must be active and strictly more senior.
   That one constraint makes cycles almost impossible, and it shrinks the search space from
   N to a handful of plausible people.
3. **Score pairs with interpretable features.** I use a linear model with hand-set weights:
   same department, level gap, segment match, historical-manager hint, and so on. I picked
   linear over a learned model so every decision can be explained as a sum of named
   signals, and so the engine never needs ground truth to train.
4. **Make abstention a real option.** The softmax runs over the candidates **plus an abstain
   slot**. If three managers look equally good, each gets about a third of the probability,
   and the employee falls under the threshold. Ambiguity turns into abstention by itself.
5. **Fix the graph globally.** Per-employee choices are combined, then adjusted: near-ties
   are spread across managers, span caps are enforced, and any remaining cycle is broken at
   its weakest edge. Low-confidence edges are dropped at the end.

## 4. High-level design

```
                 ┌──────────────────────── InferenceEngine.infer_company ───────────────────────┐
observed/  ──►   │ ObservedDatasetReader ─► ProfileBuilder ─► CandidateGenerator ─► Scorer ─►   │ ─► Prediction[]
(jsonl)          │      (byte index)        (normalize+vote)    (rank filter)      (softmax)    │     (+ stats)
                 │                                                                 GraphBuilder │
                 └──────────────────────────────────────────────────────────────────────────────┘
                              ▲
                  Vocabulary (built once from DataGenerator config + TitleTaxonomy)
```

| Module | Responsibility |
|---|---|
| `data.py` | Observed-only I/O and per-company random access |
| `normalization/` | text → canonical title / department / location |
| `features/profiles.py` | observations → `EmployeeProfile` |
| `candidates/generator.py` | root selection and the candidate pool per employee |
| `features/relationship.py` | (employee, candidate) → `RelationshipFeatures` |
| `scoring/scorer.py` | features → probabilities with an abstain option |
| `graph/builder.py` | global optimization → `InferredGraph` |
| `pipeline/engine.py` | orchestration, prediction export, batch runs |
| `evaluation/` | the only module that reads ground truth, and only after a run finishes |
| `config.py` | `InferenceConfig`, `ScoringWeights` |

## 5. Low-level design

### 5.1 Data access: `ObservedDatasetReader`

```python
class ObservedDatasetReader:
    def __init__(self, dataset_dir: Path)            # raises ObservedDataError on a ground_truth path
    def splits(self) -> list[str]
    def company_ids(self, split: str) -> list[str]
    def load_company(self, company_id: str, split: str | None = None) -> ObservedCompanyData
    def iter_companies(self, split: str) -> Iterator[ObservedCompanyData]

@dataclass
class ObservedCompanyData:
    company: ObservedCompany
    employees: list[ObservedEmployee]
    observations: list[EmployeeObservation]
```

The exporter writes rows grouped by company. On first access to a split, the reader scans
each of its three files once and records a `_Span(start, end)` byte range per company. After
that, `load_company` is a `seek` plus reading one slice. This is what lets the API load a
single company in milliseconds without parsing a 100 MB file.

Isolation is enforced right here. The constructor rejects any path containing `ground_truth`,
and paths are only ever built under `observed/<split>/`.

### 5.2 Normalization

`Vocabulary.build(config)` runs once per engine and gathers everything the normalizers need
from the DataGenerator: the title taxonomy (533 canonical titles, about 2,900 variants), job
families, the department catalog with aliases, regions and city aliases, and the
abbreviation pairs used by the noise generator.

**`TitleNormalizer.interpret(raw) -> TitleInterpretation`**

```
TitleInterpretation(raw, canonical_title, job_family, seniority, executive_role,
                    score, method, generic, suffix)
```

The matchers are tried in order, and the first hit wins:

| Step | Example | Score |
|---|---|---|
| known generic title: seniority only, flagged `generic` | `Head of Department` | 0.35 |
| exact variant lookup | `Sr. SWE` | 1.0 |
| strip a trailing suffix (`, Engineering`, `(EMEA)`, `- Consumer`) right to left, then lookup | `Director, Engineering (EMEA)` | 0.93 |
| abbreviation expansion, then lookup | `Financial Anlst` | 0.9 |
| fuzzy: candidate keys from a token index, then `SequenceMatcher` ≥ 0.84 | `Senoir Analyst` | ratio × 0.85 |
| keyword fallback: seniority only | `Head of Something` | 0.15–0.3 |

If a key maps to several canonical titles (`CMO`), no canonical title is returned. Only the
seniority and family the candidates share are kept, at 0.6× the step's score
(`method="exact_ambiguous"` and so on). Fuzzy ties are broken by sorted key order, which
keeps the result independent of the hash seed (N1).

**`DepartmentNormalizer.interpret(raw, allowed) -> DepartmentInterpretation`** returns
`key`, `top_key` (the parent department), `segment` (from a `Consumer - Engineering` style
prefix) and `score`. The `allowed` set comes from the company's industry template, so an
ambiguous alias resolves to a department that industry actually has.

**`LocationNormalizer.interpret(raw) -> LocationInterpretation`** returns `city`, `region`
and `remote`.

### 5.3 Profiles: `ProfileBuilder.build(data) -> dict[str, EmployeeProfile]`

Each observation adds weight to several vote maps (`_Votes`):

```
weight(obs) = source_reliability[obs.source] × 0.5 ** (age_days / 365)

for obs in employee.observations:
    status votes:  former / active   (HR and internal directory count 1.0, others 0.3)
    title votes:   seniority, family, canonical, exec_role   += weight × title.score
    dept votes:    department_key += weight × dept.score ; segment += weight × 0.8
    location:      region, city += weight
    hist manager:  managers[id] += 1
```

`_vote(map)` takes the arg-max and confidence = top / total. The profile then gets:

| Field | Derived from |
|---|---|
| `seniority`, `rank` | seniority vote; the CEO gets `CEO_RANK = c_level + 1` |
| `department_key`, `department_top_key` | department vote, then catalog parent |
| `segment`, `region`, `city` | votes |
| `historical_managers` | normalized counts |
| `departed` | `former / (former + active) ≥ 0.5`, or 0.7 if seen only in stale sources |

A post-pass (`_infer_missing_functions`) fills in a missing department with the department
that family most often sits in at the same company, at confidence `0.5 × share`.

`_revive_absent_ceo` makes one exception: a CEO seen only in stale sources is kept active.
Without that, a missing CEO record would orphan the whole company.

### 5.4 Candidates: `CandidateGenerator.generate(profiles, root)`

```
active employees are bucketed by sub-department, top department and job family,
each bucket sorted by rank (bisect for "everyone above rank r")

for emp in active:
    pool  = bucket(emp.sub_dept).above(emp.rank)   within 3 management steps
          ∪ bucket(emp.top_dept).above(emp.rank)   within 3 management steps
            (or the family bucket when department is unknown)
          ∪ leaders (exec role or rank ≥ executive) with rank > emp.rank
          ∪ root, if root.rank > emp.rank
          ∪ historical managers that are active and senior
    if |pool| > 25: keep the top 25 by a cheap prior
                   (department/segment/family/region match, history ×5, level gap,
                    −3 if the candidate is not manager-level)
```

`choose_root(active)` picks the CEO, using the highest seniority confidence among several,
else the unique top-ranked person, else `None`.

The non-manager penalty in the prior matters for large departments. Without it, senior ICs
(who also outrank an IC) filled all 25 slots on ID order. The real managers got cut, and the
one that survived looked like a confident winner. On a 4,000-person clean company the true
manager was missing from the pool for 40% of employees, and IC predictions were confidently
wrong. With the penalty, the pool keeps the managers, equally plausible ones split the
probability, and the engine abstains instead. A regression test builds exactly that case.

The strict `rank > emp.rank` rule is the main structural guarantee. A cycle needs someone
who outranks themselves, which can't happen, so cycle breaking in 5.6 only ever runs as a
safety net.

### 5.5 Features and scoring

`relationship_features(emp, cand, exec_departments, present_ranks) -> RelationshipFeatures`
(19 fields). The ones that carry the most weight:

| Feature | Weight | Notes |
|---|---|---|
| `level_steps` | −1.1 per step | counts only seniority levels that actually exist in that department (`present_level_steps`), so a director over managers is 0 steps when there are no senior managers |
| `same_department` / `same_subdepartment` | +2.2 / +1.6 | |
| `department_conflict` | −2.5 | |
| `same_segment` / `segment_conflict` | +1.8 / −1.8 | BU/region copies of the same department |
| `historical_manager` | +3.5 × share | an unreliable hint, so it is weighted rather than trusted |
| `executive_owns_department` | +2.6 | CTO → engineering, etc. |
| `ceo_for_top_level` / `ceo_for_lower_level` | +1.5 / −3.0 | stops everything collapsing onto the CEO |
| `candidate_not_manager` | −3.0 | ICs managing ICs is rare |

`RelationshipScorer.score(emp, cands, ...) -> ScoredEmployee`:

```
s_i     = linear_score(features_i, weights)
p       = softmax([s_1 … s_k, abstain_score=0.6] / temperature)
quality = 0.5 + 0.3·seniority_conf + 0.2·min(1.5·dept_conf, 1)   (×0.8 if generic title)
→ candidates sorted by p, abstain_probability = p[k], profile_quality
```

### 5.6 Graph: `GraphBuilder.build(scored, root_id, departed, seniority) -> InferredGraph`

```
choice[e] = 0                                   # best candidate per employee
repeat up to 3 rounds while anything changed:
    balance_ties:  if candidates within 10% of the best exist, move to the least-loaded one
    enforce_spans: if a manager exceeds span_caps[seniority], move the reports with the
                   smallest margin over their next candidate to that next candidate
for e:
    confidence = p(chosen) × profile_quality
    reason = "confident" if confidence ≥ 0.55 else "below_threshold"
root → "root", no candidates → "no_candidates", departed → "departed"
break_cycles: while find_cycles(edges): mark the weakest edge in each cycle "cycle_broken"
```

```python
@dataclass
class Decision:      employee_id; chosen: ScoredCandidate | None; confidence: float; reason: str
@dataclass
class InferredGraph: decisions; root_id; cycles_broken; reassignments
                     edges -> {employee: manager} for "confident" decisions only
```

`find_cycles` is imported from the DataGenerator's hierarchy validator, so both sides share
one definition of what a cycle is.

### 5.7 Output: `InferenceEngine` and `run_dataset`

```python
class InferenceEngine:
    def __init__(self, config: InferenceConfig | None = None, vocabulary: Vocabulary | None = None)
    def infer_company(self, data: ObservedCompanyData) -> CompanyInference

def run_dataset(dataset_dir, output_path, splits=None, company_ids=None,
                engine=None, progress=None) -> dict      # summary counts

@dataclass
class CompanyInference: company_id; profiles; graph; predictions: list[Prediction]; stats
```

There is one `Prediction` per observed employee:

```jsonc
{"company_id": "company_00001", "employee_id": "emp_00001_000019",
 "predicted_manager_id": "emp_00001_000007",          // null = abstain
 "confidence": 0.83,
 "evidence": [
   {"type": "profile", "observed_title": "Sr. Prod Tech", "inferred_title": "...",
    "seniority": "senior_ic", "department": "...", "segment": null, "region": "apac",
    "observations": 3, "sources": ["hr_export", "..."]},
   {"type": "decision", "reason": "confident", "confidence": 0.83},
   {"type": "signals", "matched": ["same_department", "same_subdepartment", "historical_manager"]},
   {"type": "candidates", "considered": 7, "abstain_probability": 0.08,
    "top": [{"employee_id": "...", "probability": 0.71}, "..."]}]}
```

The manager is set only when the decision reason is `confident`. Departed employees get an
extra `{"type": "departed", "confidence": ...}` entry.

`run_dataset` writes to `<output>.partial` and renames it when finished, so the evaluator
can never score a half-written file.

### 5.8 Configuration: `InferenceConfig`

| Key | Default | Purpose |
|---|---|---|
| `confidence_threshold` | 0.55 | abstain below this |
| `max_candidates` | 25 | candidate pool cap |
| `abstain_score` | 0.6 | logit of the abstain slot |
| `source_reliability` | hr 1.0 … snapshot 0.25 | vote weights |
| `recency_half_life_days` | 365 | vote decay |
| `fuzzy_title_threshold` / `fuzzy_department_threshold` | 0.84 / 0.86 | fuzzy cut-offs |
| `span_caps` | manager 22 … c_level 16 | per-seniority report caps |
| `optimization_rounds` | 3 | graph clean-up passes |
| `weights` | `ScoringWeights` | 20 feature weights |

The API exposes the first three through `FIRMABLE_INFERENCE__*`.

## 6. Results and threshold choice

I tuned on validation and checked test once.

| Split | Precision | Recall | Coverage | Penalized | ECE |
|---|---|---|---|---|---|
| validation | 0.951 | 0.432 | 0.448 | 0.387 | 0.084 |
| test | 0.955 | 0.321 | 0.334 | 0.291 | 0.096 |
| challenge (enterprise noise) | 0.872 | 0.146 | 0.165 | 0.103 | 0.075 |

The penalized score is flat between 0.5 and 0.7. Going lower buys coverage at the cost of
precision: on validation, 0.40 gives 0.892 precision at 0.530 coverage, and 0.30 gives 0.803
at 0.637.

Performance is about 14,600 employees in 36 s for the test split. The largest company (7,746)
takes about 16 s.

## 7. Testing

30 tests, run against small datasets generated in fixtures (clean and noisy).

| Area | What is checked |
|---|---|
| Isolation | the package source never names ground-truth files; patching `open()` during a run catches any ground-truth access; predictions are byte-identical with and without `ground_truth/` present; no hidden fields in the output |
| Graph invariants | no cycles, no self-edges, managers active and higher-ranked, the root has no manager |
| Behaviour | seniority is recovered, departed employees are unassigned, evidence is present, the evaluator refuses unfinished files |
| Quality floor | precision > 0.9 clean and > 0.75 noisy; coverage > 0.2 |
| Determinism | same process, and two processes with different `PYTHONHASHSEED`s |
| Candidate cap | with 40 senior ICs and 3 managers above an IC, all 3 managers survive the cap of 25 |

## 8. Trade-offs and future work

- **Absence-only departures.** Someone seen only in public profiles or old snapshots is
  treated as departed (score 0.7). On the clean dataset that wrongly flags 83 of 4,000 current
  employees. It costs coverage, not precision, because those people just get no manager.
  I kept it because in noisy data it's the main way departures are detected.
- **Coverage on large flat teams.** When several managers share department, family and
  location, nothing in the data separates them, so the engine abstains. The next step would
  be using co-observation patterns (people who share an exact sub-team label across sources).
- **Hand-set weights.** Learning them offline on the train split (logistic regression on the
  same features) would be cheap. The runtime engine would still never touch ground truth.
- **Matrix (dotted-line) managers** are out of scope; only primary edges are predicted.
