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
3. **Score pairs with interpretable features.** I use a linear model over named features:
   same department, level gap, segment match, historical-manager hint, and so on. Linear
   keeps every decision explainable as a sum of named signals. The weights are learned
   offline on the train split (5.9) and committed as a JSON file; the runtime engine reads
   that file and never touches ground truth.
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
| reviewed alias (`normalization/title_aliases.json`, built offline by an LLM, see 5.10) | `Snr Dta Platfrm Engnr` | 0.9 |
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
(19 scored fields, plus `employee_is_ic` and `candidate_seniority`). Besides one weight per
field, the scorer has two small learned tables: a bonus per exact level gap
(`level_step_exact`: 0, 1, 2, 3+) and, for IC employees, a bonus per manager seniority
(`ic_reports_to`). The weights that matter most, learned vs the original hand-set values:

| Feature | Learned | Hand-set | Notes |
|---|---|---|---|
| `historical_manager` | +4.2 × share | +3.5 | the strongest single signal when present (10–12% of employees) |
| `same_department` / `same_subdepartment` | +2.1 / +2.3 | +2.2 / +1.6 | |
| `manages_family` / `same_family` | +1.6 / +0.8 | +0.6 / +0.9 | a team almost always shares its manager's job family |
| `executive_wrong_function` | −2.6 | −1.5 | |
| `candidate_not_manager` | −1.9 | −3.0 | |
| `ic_reports_to.manager` vs `.senior_manager` | +1.8 / −1.1 | — | ICs report to first-line managers, not to the level above |
| `level_steps` | −0.2 per step | −1.1 | mostly replaced by the IC table and `level_step_exact` |

`level_steps` counts only seniority levels that actually exist in that department
(`present_level_steps`), so a director over managers is 0 steps when there are no senior
managers.

`RelationshipScorer.score(emp, cands, ...) -> ScoredEmployee`:

```
s_i     = linear_score(features_i, weights)
p       = softmax([s_1 … s_k, abstain_score] / temperature)     # abstain_score = −1.0, tuned
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

`confidence_threshold`, `abstain_score` and `weights` default to the values in
`learned_weights.json` when that file exists, and to the original hand-set values otherwise.

| Key | Default | Purpose |
|---|---|---|
| `confidence_threshold` | 0.63 (learned; 0.55 hand-set) | abstain below this |
| `max_candidates` | 25 | candidate pool cap |
| `abstain_score` | −1.0 (learned; 0.6 hand-set) | logit of the abstain slot |
| `source_reliability` | hr 1.0 … snapshot 0.25 | vote weights |
| `recency_half_life_days` | 365 | vote decay |
| `fuzzy_title_threshold` / `fuzzy_department_threshold` | 0.84 / 0.86 | fuzzy cut-offs |
| `span_caps` | manager 22 … c_level 16 | per-seniority report caps |
| `optimization_rounds` | 3 | graph clean-up passes |
| `weights` | `ScoringWeights` | 20 feature weights plus the two learned tables |

The API exposes the first two through `FIRMABLE_INFERENCE__*`; leaving the threshold unset
keeps the learned one.

### 5.9 Learning the weights: `orggraph-infer train`

`evaluation/training.py` is the only code that reads ground truth for anything other than
scoring, which is why it lives in `evaluation/`. It never runs inside the engine.

```
1. for the first 150 train companies: score_company() → per employee, the candidates'
   feature_terms() and the index of the true manager (skipped if absent or alone)
2. fit a conditional logit (softmax over each employee's candidates) with Adam, L2 1e-3
3. for abstain_score in −4 … +1: run the engine on validation, sweep thresholds 0.30–0.95,
   keep the pair with the best penalized score (correct − 2·wrong) / true edges
4. score the report split (test) once with the result, then write learned_weights.json
```

`feature_terms()` and `linear_score()` share one definition of the terms, and a test checks
that `linear_score` equals the weighted sum of `feature_terms` on real candidates, so the
trainer and the engine can't drift apart. The whole run takes about 8 minutes.

### 5.10 LLM title aliases (offline)

`Inference/scripts/llm_title_aliases.py` sends the observed titles the matchers handle worst
(fuzzy, keyword, unknown, ambiguous: about 8,600 unique strings, 108 calls) to an LLM
(`OPENAI_MODEL`, default `gpt-5.5`; `OPENAI_ENDPOINT` selects OpenAI or an Azure AI Foundry
resource, whose OpenAI v1 API lives under `/openai/v1` with an `api-key` header). It asks for a canonical title from the taxonomy or null,
using strict JSON-schema output, and drops any answer that isn't a real canonical title.
Every answer is cached in `scripts/llm_cache/`, so re-runs are free and reproducible. The
result is `normalization/title_aliases.json`, which is reviewed and committed like code.
Production never calls the LLM, and determinism (N1) holds because the engine only reads a
file.

I measured the ceiling before building it: giving the engine the *true* seniority and job
family of every employee only moves validation from 0.387 to 0.408 penalized. Title
normalization is not the bottleneck (5.4 and section 8 explain what is), so the alias pass is
a cheap, bounded improvement, not a big lever. It matters more on real data, whose titles
are messier than the generator's.

The committed run used `gpt-5.5` on Azure AI Foundry: 8,561 titles in 108 calls, 7,688
mapped and the rest left null (bare titles such as "Account" or "Lead"). Where the model
answered, its canonical title was right in every case I spot-checked. On the 14,000
observations whose title it mapped, seniority accuracy against ground truth goes from 65.4% to
69.9% (about 770 fixed, 147 made worse). The remaining errors are generator noise no reader
can undo, such as a dropped "Senior" or a stale title. Penalized score rises by 0.001–0.002
on every split and precision doesn't drop.

## 6. Results and threshold choice

Weights learned on train, abstain logit and threshold tuned on validation, test scored once,
with the LLM title aliases (5.10) in place.

| Split | Precision | Recall | Coverage | Penalized | ECE |
|---|---|---|---|---|---|
| validation | 0.959 | 0.503 | 0.518 | 0.460 | 0.033 |
| test | 0.961 | 0.382 | 0.394 | 0.352 | 0.046 |
| challenge (enterprise noise) | 0.884 | 0.174 | 0.195 | 0.129 | 0.058 |

Without the aliases the penalized scores are 0.458, 0.351 and 0.128.

With the original hand-set weights (threshold 0.55):

| Split | Precision | Recall | Coverage | Penalized | ECE |
|---|---|---|---|---|---|
| validation | 0.951 | 0.432 | 0.448 | 0.387 | 0.084 |
| test | 0.955 | 0.321 | 0.334 | 0.291 | 0.096 |
| challenge (enterprise noise) | 0.872 | 0.146 | 0.165 | 0.103 | 0.075 |

Lowering the threshold buys coverage at the cost of precision, and the penalized score drops
below about 0.6.

**How far this data lets us go.** The candidate pool contains the true manager for about 98%
of employees, so almost every miss is a choice between look-alikes. In the ground truth, the
true manager is the only manager with its department, job family and seniority for 51% of
validation employees and 38% of test employees; on test, 35% of employees have six or more
such look-alikes. Adding employees with a correct historical hint, the recall reachable at
high precision is roughly 56% (validation) and 44% (test). The learned model reaches 50% and
38%.

Performance is about 14,600 employees in 36 s for the test split. The largest company (7,746)
takes about 16 s.

## 7. Testing

36 tests, run against small datasets generated in fixtures (clean and noisy).

| Area | What is checked |
|---|---|
| Isolation | the package source never names ground-truth files; patching `open()` during a run catches any ground-truth access; predictions are byte-identical with and without `ground_truth/` present; no hidden fields in the output |
| Graph invariants | no cycles, no self-edges, managers active and higher-ranked, the root has no manager |
| Behaviour | seniority is recovered, departed employees are unassigned, evidence is present, the evaluator refuses unfinished files |
| Quality floor | precision > 0.9 clean and > 0.75 noisy; coverage > 0.2 |
| Determinism | same process, and two processes with different `PYTHONHASHSEED`s |
| Candidate cap | with 40 senior ICs and 3 managers above an IC, all 3 managers survive the cap of 25 |
| Learning | `linear_score` equals the weighted `feature_terms`; the logit fit recovers an informative feature; the threshold sweep maximizes the penalized score |
| Aliases | an alias resolves a title the matchers miss (keeping its suffix); aliases to unknown titles are ignored; the script batches, honours the cache, and drops invalid LLM answers (mocked API) |

## 8. Trade-offs and future work

- **Absence-only departures.** Someone seen only in public profiles or old snapshots is
  treated as departed (score 0.7). On the clean dataset that wrongly flags 83 of 4,000 current
  employees. It costs coverage, not precision, because those people just get no manager.
  I kept it because in noisy data it's the main way departures are detected.
- **Coverage on large flat teams.** When several managers share department, family and
  location, nothing in the data separates them, so the engine abstains (section 6 measures
  how often). I tried propagating historical hints between same-family peers as a feature;
  it added nothing on validation, so it isn't in the model. A useful next step for the UI is
  a skip-level answer: when the near-tied managers share a parent, attach the employee to
  that parent's team rather than leaving them unplaced.
- **What an LLM can and can't do here.** It can read messy titles (5.10). It can't pick
  between look-alike managers, because the data holds no signal to separate them, and
  asking it per employee would cost tens of millions of tokens per run and break
  determinism.
- **Matrix (dotted-line) managers** are out of scope; only primary edges are predicted.
