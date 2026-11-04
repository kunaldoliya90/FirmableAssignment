// Types mirroring the backend response schemas
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type Split = "train" | "validation" | "test" | "challenge";

export interface DatasetSummary {
  dataset_id: string;
  company_count: number;
  employee_count: number;
  observation_count: number;
  departed_employee_count: number;
  generation_timestamp: string;
  random_seed: number;
  noise_profile: string;
  challenge_noise_profile: string;
  split_distribution: Record<string, { companies: number; employees: number; observations: number }>;
  inferred_splits: string[];
}

export interface DatasetDetail extends DatasetSummary {
  dataset_version: string;
  schema_version: string;
  industry_distribution: Record<string, number>;
  company_size_distribution: Record<string, number>;
  archetype_distribution: Record<string, number>;
  noise_profile_distribution: Record<string, number>;
}

export interface NoiseProfileInfo {
  name: string;
  description: string;
  parameters: Record<string, number>;
}

export interface GenerateDatasetRequest {
  dataset_id: string;
  companies: number;
  min_employees_per_company: number;
  target_employees: number;
  seed: number;
  noise_profile: string;
  challenge_noise_profile: string;
  overwrite: boolean;
}

export interface CompanySummary {
  company_id: string;
  company_name: string;
  industry: string;
  employee_count: number;
  company_size_segment: string;
  headquarters: string;
  operating_regions: string[];
  split: Split;
  inferred: boolean;
}

export interface CompanyInferenceStats {
  employees: number;
  predicted_edges: number;
  abstentions: number;
  departed_detected: number;
  root_id: string | null;
  decision_reasons: Record<string, number>;
  elapsed_seconds: number;
}

export interface CompanyDetail extends CompanySummary {
  observed_employee_count: number;
  observation_count: number;
  observations_by_source: Record<string, number>;
  inference: CompanyInferenceStats | null;
}

export interface CompanyInferenceResult extends CompanyInferenceStats {
  company_id: string;
  confidence_threshold: number;
}

export interface EmployeeRef {
  employee_id: string;
  full_name: string;
  title: string | null;
  seniority: string | null;
}

export interface EmployeeSummary extends EmployeeRef {
  company_id: string;
  employment_type: string;
  inferred_title: string | null;
  job_family: string | null;
  department: string | null;
  region: string | null;
  departed: boolean;
  predicted_manager_id: string | null;
  confidence: number;
  direct_reports: number;
}

export interface Observation {
  observation_id: string;
  source: string | null;
  observed_title: string | null;
  observed_department: string | null;
  observed_job_family: string | null;
  observed_location: string | null;
  observed_at: string | null;
  employment_status: string;
  historical_manager_id: string | null;
  missing_fields: string[];
}

export interface Candidate {
  employee_id: string;
  full_name: string | null;
  title: string | null;
  probability: number;
}

export type Evidence = { type: string } & Record<string, unknown>;

export interface EmployeeDetail extends EmployeeSummary {
  segment: string | null;
  city: string | null;
  seniority_confidence: number;
  department_confidence: number;
  departed_confidence: number;
  sources: string[];
  decision_reason: string;
  manager: EmployeeRef | null;
  reports: EmployeeRef[];
  chain_of_command: EmployeeRef[];
  candidates: Candidate[];
  evidence: Evidence[];
  observations: Observation[];
}

export interface SearchHit {
  employee_id: string;
  company_id: string;
  company_name: string;
  full_name: string;
  split: Split;
}

export interface OrgNode {
  employee_id: string;
  full_name: string;
  title: string | null;
  seniority: string | null;
  department: string | null;
  manager_id: string | null;
  confidence: number;
  direct_reports: number;
  subtree_size: number;
  depth: number;
  children_loaded: boolean;
}

export interface OrgEdge {
  source: string;
  target: string;
  confidence: number;
}

export interface OrgChart {
  company_id: string;
  root_id: string | null;
  focus_id: string | null;
  nodes: OrgNode[];
  edges: OrgEdge[];
  resolved: number;
  unresolved: number;
  total_employees: number;
}

export interface UnresolvedEmployee {
  employee_id: string;
  full_name: string;
  title: string | null;
  seniority: string | null;
  department: string | null;
  reason: string;
  best_candidate_id: string | null;
  best_candidate_name: string | null;
  best_probability: number;
}

export interface InferenceRun {
  split: string;
  predictions_file: string;
  summary: Record<string, unknown>;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  progress: number;
  message: string;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EdgeMetrics {
  edge_precision: number | null;
  edge_recall: number | null;
  edge_f1: number | null;
  coverage: number | null;
  abstention_rate: number | null;
  wrong_edge_rate: number | null;
  penalized_score: number | null;
  counts: Record<string, number>;
}

export interface ReliabilityBin {
  bin: [number, number];
  count: number;
  mean_confidence?: number;
  accuracy?: number;
  gap?: number;
}

export interface BenchmarkReport {
  splits: string[];
  wrong_edge_penalty: number;
  prediction_rows: number;
  overall: EdgeMetrics;
  calibration: {
    answered_predictions: number;
    expected_calibration_error: number | null;
    max_calibration_error: number | null;
    brier_score: number | null;
    reliability: ReliabilityBin[];
  };
  risk_coverage: { threshold: number; answered: number; precision: number | null; coverage: number | null }[];
  breakdowns: Record<string, Record<string, EdgeMetrics>>;
}

export interface EvaluationSummary {
  evaluation_id: string;
  dataset_id: string;
  splits: string[];
  created_at: string;
  edge_precision: number | null;
  edge_recall: number | null;
  edge_f1: number | null;
  coverage: number | null;
  penalized_score: number | null;
}

export interface EvaluationReport extends EvaluationSummary {
  report: BenchmarkReport;
}

export interface CompanyEvaluation {
  company_id: string;
  metrics: EdgeMetrics & { calibration: Record<string, number | null> };
}

export interface Health {
  status: string;
  version: string;
  environment: string;
}
