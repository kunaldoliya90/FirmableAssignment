# HTTP API behaviour: routing, schemas, pagination, filtering, errors and jobs
from __future__ import annotations

from fastapi.testclient import TestClient

from firmable.tests.conftest import DATASET, wait_for_job

API = "/api/v1"


def test_health(client: TestClient) -> None:
    assert client.get(f"{API}/health").json()["status"] == "ok"
    ready = client.get(f"{API}/health/ready").json()
    assert ready["status"] == "ready"
    assert DATASET in ready["checks"]["datasets"]


def test_openapi_documents_versioned_routes(client: TestClient) -> None:
    spec = client.get(f"{API}/openapi.json").json()
    paths = spec["paths"]
    for path in (
        "/api/v1/datasets",
        "/api/v1/datasets/{dataset_id}/companies",
        "/api/v1/datasets/{dataset_id}/companies/{company_id}/org-chart",
        "/api/v1/datasets/{dataset_id}/evaluations",
        "/api/v1/jobs/{job_id}",
    ):
        assert path in paths


def test_datasets(client: TestClient) -> None:
    datasets = client.get(f"{API}/datasets").json()
    assert [d["dataset_id"] for d in datasets] == [DATASET]
    detail = client.get(f"{API}/datasets/{DATASET}").json()
    assert detail["company_count"] == 8 and detail["employee_count"] >= 1600
    assert set(detail["split_distribution"]) == {"train", "validation", "test", "challenge"}
    profiles = client.get(f"{API}/config/noise-profiles").json()
    assert {p["name"] for p in profiles} >= {"clean", "medium_noise"}


def test_company_pagination_filtering_and_sorting(client: TestClient) -> None:
    page = client.get(f"{API}/datasets/{DATASET}/companies", params={"page_size": 3}).json()
    assert page["total"] == 8 and len(page["items"]) == 3 and page["page"] == 1
    second = client.get(f"{API}/datasets/{DATASET}/companies", params={"page_size": 3, "page": 3}).json()
    assert len(second["items"]) == 2
    by_size = client.get(
        f"{API}/datasets/{DATASET}/companies", params={"sort": "employee_count", "descending": True}
    ).json()["items"]
    counts = [c["employee_count"] for c in by_size]
    assert counts == sorted(counts, reverse=True)
    split = client.get(f"{API}/datasets/{DATASET}/companies", params={"split": "train"}).json()
    assert split["total"] > 0 and all(c["split"] == "train" for c in split["items"])
    first = by_size[0]
    found = client.get(f"{API}/datasets/{DATASET}/companies", params={"q": first["company_name"][:6]}).json()
    assert any(c["company_id"] == first["company_id"] for c in found["items"])
    facets = client.get(f"{API}/datasets/{DATASET}/facets").json()
    assert sum(facets["split"].values()) == 8


def test_company_detail_is_observed_only(client: TestClient, company_id: str) -> None:
    detail = client.get(f"{API}/datasets/{DATASET}/companies/{company_id}").json()
    assert detail["company_id"] == company_id
    assert detail["observation_count"] > detail["observed_employee_count"]
    for hidden in ("org_archetype", "generation_seed", "noise_profile"):
        assert hidden not in detail


def test_inference_and_org_chart(client: TestClient, company_id: str) -> None:
    result = client.post(f"{API}/datasets/{DATASET}/companies/{company_id}/inference").json()
    assert result["employees"] > 100 and result["predicted_edges"] > 0
    assert result["predicted_edges"] + result["abstentions"] == result["employees"]

    chart = client.get(
        f"{API}/datasets/{DATASET}/companies/{company_id}/org-chart", params={"depth": 1}
    ).json()
    node_ids = {n["employee_id"] for n in chart["nodes"]}
    assert chart["root_id"] in node_ids
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in chart["edges"])
    assert max(n["depth"] for n in chart["nodes"]) <= 1
    expandable = next(n for n in chart["nodes"] if n["depth"] == 1 and n["direct_reports"] > 0)
    sub = client.get(
        f"{API}/datasets/{DATASET}/companies/{company_id}/org-chart",
        params={"root_id": expandable["employee_id"], "depth": 1},
    ).json()
    assert len(sub["edges"]) == expandable["direct_reports"]
    capped = client.get(
        f"{API}/datasets/{DATASET}/companies/{company_id}/org-chart", params={"depth": 3, "max_children": 1}
    ).json()
    assert all(sum(e["source"] == n["employee_id"] for e in capped["edges"]) <= 1 for n in capped["nodes"])

    unresolved = client.get(
        f"{API}/datasets/{DATASET}/companies/{company_id}/org-chart/unresolved", params={"page_size": 5}
    ).json()
    assert unresolved["total"] == chart["unresolved"]
    assert all(u["reason"] != "confident" for u in unresolved["items"])


def test_employees(client: TestClient, company_id: str) -> None:
    page = client.get(
        f"{API}/datasets/{DATASET}/companies/{company_id}/employees", params={"page_size": 20}
    ).json()
    assert page["total"] > 100 and len(page["items"]) == 20
    resolved = client.get(
        f"{API}/datasets/{DATASET}/companies/{company_id}/employees",
        params={"resolved": True, "page_size": 500},
    ).json()
    assert resolved["items"] and all(e["predicted_manager_id"] for e in resolved["items"])
    employee = resolved["items"][0]
    detail = client.get(
        f"{API}/datasets/{DATASET}/companies/{company_id}/employees/{employee['employee_id']}"
    ).json()
    assert detail["manager"]["employee_id"] == employee["predicted_manager_id"]
    assert detail["chain_of_command"][0]["employee_id"] == employee["predicted_manager_id"]
    assert detail["observations"] and detail["evidence"]
    assert all("manager_employee_id" not in o for o in detail["observations"])

    name = employee["full_name"].split()[0]
    hits = client.get(f"{API}/datasets/{DATASET}/employees/search", params={"q": name}).json()
    assert any(h["employee_id"] == employee["employee_id"] for h in hits["items"]) or hits["total"] > 25


def test_company_evaluation_returns_aggregates_only(client: TestClient, company_id: str) -> None:
    body = client.get(f"{API}/datasets/{DATASET}/companies/{company_id}/evaluation").json()
    metrics = body["metrics"]
    assert 0.0 <= metrics["edge_precision"] <= 1.0
    assert "manager_employee_id" not in str(body)


def test_split_inference_and_evaluation_jobs(client: TestClient) -> None:
    job = client.post(f"{API}/datasets/{DATASET}/inference", json={"splits": ["validation"]})
    assert job.status_code == 202
    finished = wait_for_job(client, job.json()["id"])
    assert finished["status"] == "succeeded", finished["error"]
    runs = client.get(f"{API}/datasets/{DATASET}/inference").json()
    assert [r["split"] for r in runs] == ["validation"]

    job = client.post(f"{API}/datasets/{DATASET}/evaluations", json={"splits": ["validation", "test"]})
    finished = wait_for_job(client, job.json()["id"])
    assert finished["status"] == "succeeded", finished["error"]
    evaluation_id = finished["result"]["evaluation_id"]
    listed = client.get(f"{API}/datasets/{DATASET}/evaluations").json()
    assert listed[0]["evaluation_id"] == evaluation_id
    report = client.get(f"{API}/datasets/{DATASET}/evaluations/{evaluation_id}").json()
    assert report["splits"] == ["validation", "test"]
    assert set(report["report"]["breakdowns"]) >= {"industry", "org_archetype", "noise_profile"}
    assert report["edge_precision"] is not None


def test_dataset_generation_and_validation_jobs(client: TestClient) -> None:
    body = {"dataset_id": "generated_small", "companies": 3, "target_employees": 300, "seed": 9}
    job = client.post(f"{API}/datasets", json=body)
    assert job.status_code == 202
    finished = wait_for_job(client, job.json()["id"])
    assert finished["status"] == "succeeded", finished["error"]
    assert finished["result"]["validation_passed"] is True
    assert "generated_small" in [d["dataset_id"] for d in client.get(f"{API}/datasets").json()]
    again = client.post(f"{API}/datasets", json=body)
    assert again.status_code == 409

    job = client.post(f"{API}/datasets/generated_small/validate")
    finished = wait_for_job(client, job.json()["id"])
    assert finished["result"]["ok"] is True and finished["result"]["leakage_checks"] > 0


def test_errors(client: TestClient, company_id: str) -> None:
    missing = client.get(f"{API}/datasets/nope")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert client.get(f"{API}/datasets/{DATASET}/companies/company_99999").status_code == 404
    assert client.get(f"{API}/datasets/{DATASET}/companies/{company_id}/employees/emp_x").status_code == 404
    assert client.get(f"{API}/datasets/..%2F..%2Fetc").status_code == 404
    assert client.get(f"{API}/jobs/unknown").status_code == 404
    assert client.get(f"{API}/datasets/{DATASET}/companies", params={"page": 0}).status_code == 422
    too_many = client.post(f"{API}/datasets", json={"dataset_id": "x", "companies": 99})
    assert too_many.status_code == 422
    bad_target = client.post(
        f"{API}/datasets", json={"dataset_id": "y", "companies": 5, "target_employees": 10}
    )
    assert bad_target.status_code == 422 and "conflicts" in bad_target.json()["error"]["message"]
    bad_split = client.post(f"{API}/datasets/{DATASET}/inference", json={"splits": ["nope"]})
    assert bad_split.status_code == 404
    assert client.get(f"{API}/health").headers.get("x-request-id")
