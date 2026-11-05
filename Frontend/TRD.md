# Frontend: Technical Requirements Document

Next.js 15 (App Router) · React 19 · TypeScript (strict) · Tailwind 4 · React Flow (`@xyflow/react`) · Vitest

## 1. Problem statement

The inference engine produces thousands of predicted reporting lines, each with a
confidence and a list of evidence. The UI has to make that explorable:

- browse 500 companies and find the interesting ones;
- see a company's inferred org chart, including companies with about 7,700 people;
- understand **why** someone was given a manager, or why they weren't;
- run inference and evaluation, and see how good the engine is.

## 2. Requirements

### Functional

| ID | Requirement |
|---|---|
| F1 | Dashboard: dataset stats, distributions, latest evaluation, dataset generation, recent jobs. |
| F2 | Company explorer: search, filter by split, industry and size, sort, paginate. |
| F3 | Company workspace with four tabs: org chart, unresolved employees, employee table, evaluation. |
| F4 | Interactive org chart that loads progressively and can be expanded node by node. |
| F5 | Employee page: profile, predicted manager and confidence, candidates, evidence signals, chain of command, reports, raw observations. |
| F6 | Cross-company employee search. |
| F7 | Inference page (one company, or whole splits as a job) and evaluation page (run, history, metrics, reliability diagram, breakdowns). |
| F8 | All data comes from the FastAPI backend; nothing is hard-coded or mocked. |

### Non-functional

| ID | Requirement |
|---|---|
| N1 | The org chart stays responsive for the largest company. |
| N2 | Backend errors and an unreachable backend are shown as clear messages, not blank screens. |
| N3 | Typed end to end: response types mirror the backend schemas, with strict TypeScript. |
| N4 | Logic that can be tested without a browser (layout, chart state, client) lives in plain functions with unit tests. |

## 3. Approach

- **Pages are thin.** Routes in `src/app` only compose feature components. Each feature owns
  its components and state.
- **One typed API layer.** Every backend call goes through `lib/api/endpoints.ts`, one
  function per endpoint, built on a small `request()` wrapper that maps every failure to an
  `ApiError`. Components never call `fetch` directly.
- **Never load a whole org chart.** The chart starts at depth 2 with a child cap and fetches
  more only when the user expands a node. The visible tree is laid out by a small custom
  tidy-tree algorithm, and React Flow renders only what's in the viewport.
- **Keep the logic out of React.** Chart state merging and layout are pure functions, so
  they're deterministic and easy to unit-test.
- **Jobs are polled.** Long operations return a job ID, and a hook polls it until it
  finishes.

## 4. High-level design

```
src/
  app/                          routes
    page.tsx                    /                 dashboard
    companies/page.tsx          /companies
    companies/[companyId]/page.tsx                company workspace
    companies/[companyId]/employees/[employeeId]/page.tsx
    search/ inference/ evaluation/
  features/
    shell/        AppShell (nav, dataset selector, DatasetProvider)
    datasets/     DatasetContext, GenerateDatasetForm
    companies/    CompanyExplorer, CompanyWorkspace
    orgchart/     OrgChartView, graphState.ts, treeLayout.ts, UnresolvedTable
    employees/    EmployeeTable, EmployeeDetailView
    evaluation/   EvaluationDashboard, MetricsGrid, ReliabilityChart, CompanyEvaluationCard
    inference/    SplitSelector
    jobs/         JobsPanel
    charts/       BarList
  components/ui.tsx             Card, PageHeader, StatTile, Badge, ConfidenceBadge, Button,
                                Spinner, ErrorState, EmptyState, ProgressBar, Pagination, Field
  lib/
    api/types.ts                response types (mirror of backend schemas)
    api/client.ts               request(), buildUrl(), ApiError
    api/endpoints.ts            api.* functions
    hooks.ts                    useAsync, useJob
    format.ts                   number, percent, date, label formatting
```

Data flow for any screen:

```
component ─► useAsync(() => api.x(...), deps) ─► request() ─► fetch ─► FastAPI
                 │                                   │
          {data, error, loading, reload}      ApiError(status, code, message, details)
```

## 5. Low-level design

### 5.1 API client: `lib/api/client.ts`

```ts
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string,
              readonly details: Record<string, unknown> = {})
}

export function buildUrl(path: string, query?: Record<string, QueryValue>, base = API_BASE_URL): string
export async function request<T>(method: "GET" | "POST", path: string,
  options?: { query?; body?; signal?: AbortSignal; fetchImpl?: typeof fetch }): Promise<T>
```

- `buildUrl` drops `null`, `undefined` and empty query values.
- A network failure becomes `ApiError(0, "network_error", "Cannot reach the API at …")`.
- A non-2xx response is parsed into `ApiError` from either the backend's
  `{"error": {code, message, details}}` shape or FastAPI's validation `detail` list.
- `fetchImpl` is injectable, which is how the client is tested without a server.

`endpoints.ts` exports `api`, one function per route, for example:

```ts
api.companies(datasetId, { page, page_size, split, industry, size_segment, q, sort, descending })
api.orgChart(datasetId, companyId, rootId?, depth = 2, maxChildren = 40)
api.employee(datasetId, companyId, employeeId)
api.runEvaluation(datasetId, { splits, rerun_inference })
api.job(jobId)
```

`types.ts` mirrors the backend Pydantic models (`Page<T>`, `CompanySummary`, `OrgChart`,
`OrgNode`, `EmployeeDetail`, `BenchmarkReport`, `Job`, ...).

### 5.2 Hooks: `lib/hooks.ts`

```ts
export function useAsync<T>(load: (() => Promise<T>) | null, deps: unknown[]):
  { data?: T; error?: Error; loading: boolean; reload: () => void }

export function useJob(jobId: string | null, onDone?: (job: Job) => void): Job | undefined
```

`useAsync` tags each call with an increasing ID and ignores responses from superseded calls,
so typing fast in a search box can't show stale results. Passing `null` disables loading.

`useJob` polls `GET /jobs/{id}` every second until the status is `succeeded` or `failed`,
then calls `onDone`. A failed poll (for example a backend restart) is ignored, and polling
continues. The timer is cleared on unmount.

### 5.3 Dataset selection: `DatasetContext`

`DatasetProvider` (mounted in `AppShell`) loads `/datasets`, picks the stored choice from
`localStorage` or the first dataset, and exposes `useDataset() -> { datasets, datasetId,
setDatasetId, refresh, loading, error }`. Storage access is wrapped in try/catch so the app still works
when storage is blocked.

### 5.4 Org chart

**State: `graphState.ts`**

```ts
export interface ChartState {
  nodes: Map<string, OrgNode>;          // every node loaded so far
  children: Map<string, string[]>;      // manager → loaded children, in API order
  confidence: Map<string, number>;      // child → edge confidence
  expanded: Set<string>;
}
export function emptyState(): ChartState
export function mergeChart(state: ChartState, chart: OrgChart): ChartState
export function toggle(state: ChartState, id: string): ChartState
export function needsFetch(state: ChartState, id: string): boolean
export function visibleNodes(state: ChartState): VisibleNode[]   // {node, parentId, hiddenChildren}
```

`mergeChart` is immutable: it copies the maps and adds the response's nodes and edges. A
subtree response reports depth relative to its own root, so the merge works out the offset
from the anchor node that's already known and shifts the new nodes under it. Nodes whose
children came back are marked expanded.

`needsFetch` is true when a node has more `direct_reports` than loaded children.
`visibleNodes` walks from the roots through expanded nodes only and reports how many
children each expanded node still hides.

**Layout: `treeLayout.ts`**

```ts
export function layoutTree(nodes: LayoutInput[], options = DEFAULT_LAYOUT): Map<string, Position>
// LayoutInput { id, parentId }   Position { x, y }
// DEFAULT_LAYOUT { nodeWidth: 230, nodeHeight: 84, horizontalGap: 24, verticalGap: 70 }
```

```
roots = nodes whose parent is missing or not visible
place(id, depth):
    if leaf: x = nextLeaf × step; nextLeaf += 1
    else:    place each child; x = midpoint(first child x, last child x)
    y = depth × (nodeHeight + verticalGap)
for each root: place(root, 0); nextLeaf += 0.5        # gap between separate trees
```

It runs in O(n). A `visiting` set guards against cycles. I wrote it myself instead of using
dagre or elk, because the tree is strict (one parent per node) and this stays about 60
lines with no dependency.

**View: `OrgChartView.tsx`**

```
mount:     api.orgChart(dataset, company)                 → mergeChart
expand:    needsFetch ? api.orgChart(..., id, depth=1, 40) → mergeChart
                      : toggle(id)
"+N":      api.orgChart(..., id, depth=1, 500)            → mergeChart   (load all reports)
render:    visibleNodes → layoutTree → React Flow nodes/edges
           (custom EmployeeNode card, onlyRenderVisibleElements, fitView)
```

Event handlers read the latest state from a `stateRef`, so the fetch decision never runs
inside a `setState` updater. A per-node `loading` set shows spinners on the nodes that are
fetching. Only confident edges exist in the response; abstentions are on the Unresolved tab.

### 5.5 Employee detail: `EmployeeDetailView`

One call, `api.employee(...)`, returns everything. The page shows:

| Section | Source field |
|---|---|
| inferred profile with per-attribute confidence | `inferred_title`, `seniority`, `job_family`, `department`, `segment`, `region`, `city`, `*_confidence`, `sources` |
| predicted manager, confidence badge, decision reason | `manager`, `confidence`, `decision_reason` |
| top candidates with probability bars and matched signals | `candidates`, `evidence` |
| chain of command (up to the root) and direct reports | `chain_of_command`, `reports` |
| every raw observation (source, date, title, department, location, status) | `observations` |

### 5.6 Error and loading states

Every async block renders one of `Spinner`, `ErrorState(error, onRetry=reload)`,
`EmptyState` or the data. `ErrorState` shows `ApiError.message`; for `network_error` that
message names the API URL, so a wrong `NEXT_PUBLIC_API_BASE_URL` is obvious right away.

## 6. Build and configuration

| Item | Value |
|---|---|
| API URL | `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000/api/v1`) |
| Build | `next build` with `output: "standalone"`, ready for a slim Node image |
| Hosting | Vercel, root directory `Frontend`; set `NEXT_PUBLIC_API_BASE_URL` for Production and Preview (it is inlined at build time). The backend must allow the Vercel origins through `FIRMABLE_CORS_ORIGINS` / `FIRMABLE_CORS_ORIGIN_REGEX` |
| Scripts | `dev`, `build`, `start`, `test`, `typecheck` |
| Path alias | `@/` → `src/` |

```bash
npm install
npm run dev        # http://localhost:3000
npm test
npm run typecheck
npm run build
```

## 7. Testing

16 Vitest tests (jsdom, Testing Library):

| File | Covers |
|---|---|
| `treeLayout.test.ts` | parents centred over children, levels stacked, no sibling overlap, multiple roots, unknown parents |
| `graphState.test.ts` | merge, expansion, depth offset for subtree responses, hidden-child counts, `needsFetch` |
| `apiClient.test.ts` | URL building, JSON success, backend error mapping, FastAPI validation errors, unreachable backend, POST bodies |
| `components.test.tsx` | pagination, confidence badge, bar list ordering, metrics grid, formatting |

## 8. Limitations and next steps

- No ESLint config yet; strict `tsc` is the current static check.
- No browser end-to-end tests; Playwright against a small generated dataset would be next.
- The first visit to the largest company waits about 16 s for backend inference with only a
  spinner. Streaming job progress for single-company inference would improve that.
