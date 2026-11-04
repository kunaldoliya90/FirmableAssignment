# Business logic
from __future__ import annotations

from dataclasses import dataclass

from firmable.core.jobs import JobManager
from firmable.services.companies import CompanyService
from firmable.services.datasets import DatasetService
from firmable.services.employees import EmployeeService
from firmable.services.evaluation import EvaluationService
from firmable.services.inference import InferenceService
from firmable.services.orgchart import OrgChartService
from Infra.Common.BaseSettings import CommonSettings


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
    def build(cls, settings: CommonSettings) -> ServiceContainer:
        jobs = JobManager(settings.job_workers)
        datasets = DatasetService(settings, jobs)
        inference = InferenceService(settings, datasets, jobs)
        companies = CompanyService(datasets, inference)
        employees = EmployeeService(datasets, inference)
        for listener in (inference.invalidate, companies.invalidate, employees.invalidate):
            datasets.on_invalidate(listener)
        return cls(
            settings=settings,
            jobs=jobs,
            datasets=datasets,
            inference=inference,
            companies=companies,
            employees=employees,
            orgchart=OrgChartService(inference),
            evaluation=EvaluationService(datasets, inference, jobs),
        )
