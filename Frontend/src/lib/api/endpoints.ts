// One typed function per backend endpoint
import { request } from "./client";
import type {
  CompanyDetail,
  CompanyEvaluation,
  CompanyInferenceResult,
  CompanySummary,
  DatasetDetail,
  DatasetSummary,
  EmployeeDetail,
  EmployeeSummary,
  EvaluationReport,
  EvaluationSummary,
  GenerateDatasetRequest,
  Health,
  InferenceRun,
  Job,
  NoiseProfileInfo,
  OrgChart,
  Page,
  SearchHit,
  UnresolvedEmployee,
} from "./types";

const ds = (datasetId: string) => `/datasets/${encodeURIComponent(datasetId)}`;
const co = (datasetId: string, companyId: string) => `${ds(datasetId)}/companies/${encodeURIComponent(companyId)}`;

export interface CompanyQuery {
  page?: number;
  page_size?: number;
  split?: string;
  industry?: string;
  size_segment?: string;
  q?: string;
  sort?: "company_name" | "employee_count" | "industry" | "company_id";
  descending?: boolean;
}

export interface EmployeeQuery {
  page?: number;
  page_size?: number;
  q?: string;
  department?: string;
  seniority?: string;
  resolved?: boolean;
  include_departed?: boolean;
}

export const api = {
  health: () => request<Health>("GET", "/health"),

  datasets: () => request<DatasetSummary[]>("GET", "/datasets"),
  dataset: (datasetId: string) => request<DatasetDetail>("GET", ds(datasetId)),
  facets: (datasetId: string) => request<Record<string, Record<string, number>>>("GET", `${ds(datasetId)}/facets`),
  noiseProfiles: () => request<NoiseProfileInfo[]>("GET", "/config/noise-profiles"),
  generateDataset: (body: GenerateDatasetRequest) => request<Job>("POST", "/datasets", { body }),
  validateDataset: (datasetId: string) => request<Job>("POST", `${ds(datasetId)}/validate`),

  companies: (datasetId: string, query: CompanyQuery = {}) =>
    request<Page<CompanySummary>>("GET", `${ds(datasetId)}/companies`, { query: { ...query } }),
  company: (datasetId: string, companyId: string) => request<CompanyDetail>("GET", co(datasetId, companyId)),

  employees: (datasetId: string, companyId: string, query: EmployeeQuery = {}) =>
    request<Page<EmployeeSummary>>("GET", `${co(datasetId, companyId)}/employees`, { query: { ...query } }),
  employee: (datasetId: string, companyId: string, employeeId: string) =>
    request<EmployeeDetail>("GET", `${co(datasetId, companyId)}/employees/${encodeURIComponent(employeeId)}`),
  search: (datasetId: string, q: string, page = 1, companyId?: string) =>
    request<Page<SearchHit>>("GET", `${ds(datasetId)}/employees/search`, {
      query: { q, page, page_size: 25, company_id: companyId },
    }),

  inferCompany: (datasetId: string, companyId: string, refresh = false) =>
    request<CompanyInferenceResult>("POST", `${co(datasetId, companyId)}/inference`, { query: { refresh } }),
  orgChart: (datasetId: string, companyId: string, rootId?: string, depth = 2, maxChildren = 40) =>
    request<OrgChart>("GET", `${co(datasetId, companyId)}/org-chart`, {
      query: { root_id: rootId, depth, max_children: maxChildren },
    }),
  unresolved: (datasetId: string, companyId: string, page = 1, reason?: string) =>
    request<Page<UnresolvedEmployee>>("GET", `${co(datasetId, companyId)}/org-chart/unresolved`, {
      query: { page, page_size: 25, reason },
    }),
  runInference: (datasetId: string, splits: string[]) =>
    request<Job>("POST", `${ds(datasetId)}/inference`, { body: { splits } }),
  inferenceRuns: (datasetId: string) => request<InferenceRun[]>("GET", `${ds(datasetId)}/inference`),

  runEvaluation: (datasetId: string, splits: string[], rerunInference = false) =>
    request<Job>("POST", `${ds(datasetId)}/evaluations`, { body: { splits, rerun_inference: rerunInference } }),
  evaluations: (datasetId: string) => request<EvaluationSummary[]>("GET", `${ds(datasetId)}/evaluations`),
  evaluation: (datasetId: string, evaluationId: string) =>
    request<EvaluationReport>("GET", `${ds(datasetId)}/evaluations/${encodeURIComponent(evaluationId)}`),
  companyEvaluation: (datasetId: string, companyId: string) =>
    request<CompanyEvaluation>("GET", `${co(datasetId, companyId)}/evaluation`),

  jobs: () => request<Job[]>("GET", "/jobs"),
  job: (jobId: string) => request<Job>("GET", `/jobs/${encodeURIComponent(jobId)}`),
};
