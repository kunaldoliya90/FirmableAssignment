# Backend commands, run from Backend/
DATASET_DIR ?= DataGenerator/datasets/FirmableAssignmentDataset
SPLIT ?= test
ARTIFACTS ?= DataGenerator/datasets/_artifacts/FirmableAssignmentDataset
COMPOSE = docker compose -f Infra/Local/docker-compose.yaml

.PHONY: setup install generate generate-large validate benchmark-smoke infer evaluate pipeline \
        test test-datagen test-inference test-api test-integration test-fullscale \
        lint format typecheck check api api-prod compose-up compose-down compose-logs logs \
        docker-build-prod clean

setup: install
	cp -n .env.example .env || true

install:
	uv sync

generate:
	cd DataGenerator && uv run orggraph-dataset generate --companies 500 --min-employees-per-company 100 \
		--target-employees 50000 --seed 42 --noise-profile medium_noise --overwrite

generate-large:
	cd DataGenerator && uv run orggraph-dataset generate --companies 500 --target-employees 200000 --seed 42 \
		--noise-profile enterprise_complexity --output-dir datasets/FirmableAssignmentDataset-200k --overwrite

validate:
	uv run orggraph-dataset validate --dataset-dir $(DATASET_DIR)

benchmark-smoke:
	uv run python DataGenerator/scripts/make_sanity_predictions.py --dataset-dir $(DATASET_DIR) \
		--split $(SPLIT) --strategy noisy_oracle --output $(ARTIFACTS)/sanity_predictions.jsonl
	uv run orggraph-dataset benchmark --dataset-dir $(DATASET_DIR) --split $(SPLIT) \
		--predictions $(ARTIFACTS)/sanity_predictions.jsonl

infer:
	uv run orggraph-infer run --dataset-dir $(DATASET_DIR) --split $(SPLIT) \
		--output $(ARTIFACTS)/predictions/$(SPLIT).jsonl

evaluate:
	uv run orggraph-infer evaluate --dataset-dir $(DATASET_DIR) --split $(SPLIT) \
		--predictions $(ARTIFACTS)/predictions/$(SPLIT).jsonl --output $(ARTIFACTS)/report_$(SPLIT).json

pipeline:
	uv run python scripts/run_pipeline.py --dataset-dir $(DATASET_DIR) --split $(SPLIT)

test: test-datagen test-inference test-api test-integration

test-datagen:
	cd DataGenerator && uv run pytest -q

test-inference:
	cd Inference && uv run pytest -q

test-api:
	cd Application && uv run pytest -q

test-integration:
	uv run pytest -q

test-fullscale:
	cd DataGenerator && uv run pytest -q -m fullscale

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy DataGenerator/src Inference/src Application/src Infra

check: lint typecheck test

api:
	uv run uvicorn firmable.main:app --host 0.0.0.0 --port 8000 --reload \
		--reload-dir Application/src --reload-dir Inference/src --reload-dir Infra

api-prod:
	FIRMABLE_ENV=production FIRMABLE_DATASETS_DIR=DataGenerator/datasets FIRMABLE_ARTIFACTS_DIR=$(ARTIFACTS) \
		FIRMABLE_GENERATOR_CONFIG_DIR=DataGenerator/config uv run uvicorn firmable.main:app --host 0.0.0.0 --port 8000

compose-up:
	$(COMPOSE) up -d

compose-down:
	$(COMPOSE) down

compose-logs logs:
	$(COMPOSE) logs -f --tail=200

docker-build-prod:
	docker build -f Infra/Production/DockerfileProd -t firmable-backend:latest .

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache DataGenerator/.mypy_cache DataGenerator/.ruff_cache \
		DataGenerator/.pytest_cache Inference/.pytest_cache Application/.pytest_cache DataGenerator/datasets/_artifacts
	find . -name __pycache__ -type d -prune -not -path "./.venv/*" -exec rm -rf {} +
