# Infra: Technical Requirements Document

Package `Infra` (root project of the `Backend/` uv workspace)

## 1. Problem statement

The backend has to run in three situations: on a laptop during development, in tests, and
in a container in production. They need different settings (log format, CORS, paths, what's
allowed), but the application code shouldn't know which one it's in. We also need a way to
build and run everything that behaves the same on Windows, macOS and Linux.

## 2. Requirements

### Functional

| ID | Requirement |
|---|---|
| F1 | One typed settings model, configurable through environment variables and an optional `.env`. |
| F2 | Separate local and production defaults, selected by one variable (`FIRMABLE_ENV`). |
| F3 | Production must refuse unsafe configuration at startup (wildcard CORS). |
| F4 | Logging: readable text locally, one JSON object per line in production, with request fields. |
| F5 | A local Docker setup that runs the API and the UI together. |
| F6 | A production image for the backend. |
| F7 | One command per common task (setup, generate, test, run, build). |

### Non-functional

| ID | Requirement |
|---|---|
| N1 | Reproducible installs: one lock file for every backend package. |
| N2 | The production image runs as non-root, has no build tools and no datasets inside, and is configured only through env. |
| N3 | Docker Compose works on Windows (Docker Desktop / WSL 2) without path tweaks. |
| N4 | Tests can build settings directly, without environment variables or global state. |

## 3. Approach

- **One uv workspace.** `Backend/pyproject.toml` is the workspace root. Its members are
  `DataGenerator`, `Inference` and `Application`, plus the root project itself, which ships
  the `Infra` package. They share one `.venv` and one `uv.lock`. The packages import each
  other and always change together, so a single lock means a laptop, CI and the Docker image
  resolve exactly the same versions.
- **Settings as an inheritance chain.** `CommonSettings` holds every field with safe
  defaults. `LocalSettings` and `ProductionSettings` override only what differs. A cached
  factory picks the class. The app receives a settings object and never reads env itself.
- **Fail at boot, not at runtime.** Pydantic validators reject bad values (log level,
  wildcard CORS in production) when settings are built.
- **Containers hold code, volumes hold data.** Datasets are large and reproducible, so they
  are mounted, never copied into images.

## 4. Design

```
Backend/
  pyproject.toml            workspace root; builds the Infra package
  uv.lock
  Makefile
  .env.example
  Infra/
    __init__.py             get_settings()
    Common/BaseSettings.py  InferenceSettings, CommonSettings
    Common/Logging.py       JsonFormatter, configure_logging
    Local/LocalSettings.py
    Local/docker-compose.yaml
    Production/ProductionSettings.py
    Production/DockerfileProd
```

### 4.1 Settings

```python
class InferenceSettings(BaseModel):
    confidence_threshold: float = 0.55      # 0..1
    max_candidates: int = 25
    company_cache_size: int = 64

class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIRMABLE_", env_nested_delimiter="__",
                                      env_file=".env", extra="ignore")
    app_name: str;  environment: Literal["local", "production", "test"]
    api_prefix: str = "/api/v1"             # normalized to a single leading slash
    docs_enabled: bool;  log_level: str;  log_json: bool
    datasets_dir: Path;  generator_config_dir: Path;  artifacts_dir: Path;  default_dataset: str
    cors_origins: list[str];  frontend_url: str
    inference: InferenceSettings
    allow_dataset_generation: bool;  max_generation_companies: int = 500;  job_workers: int = 2

class LocalSettings(CommonSettings):       # docs on, generation on, localhost CORS, reload
class ProductionSettings(CommonSettings):  # JSON logs, docs off, generation off,
                                           # /data paths, empty CORS, rejects "*"
```

Nested values use a double underscore: `FIRMABLE_INFERENCE__CONFIDENCE_THRESHOLD=0.4`.
Lists are JSON: `FIRMABLE_CORS_ORIGINS='["https://app.example.com"]'`.

| Setting | Local | Production |
|---|---|---|
| `log_json` | false | true |
| `docs_enabled` | true | false |
| `allow_dataset_generation` | true | false |
| `datasets_dir` | `Backend/DataGenerator/datasets` | `/data/datasets` |
| `artifacts_dir` | `Backend/DataGenerator/datasets/_artifacts` | `/data/artifacts` |
| `cors_origins` | `localhost:3000` | empty; must be set, `*` rejected |

Selection:

```python
@lru_cache(maxsize=1)
def get_settings() -> CommonSettings:
    env = os.environ.get("FIRMABLE_ENV", "local").lower()
    cls = {"local": LocalSettings, "test": LocalSettings, "production": ProductionSettings}[env]
    return cls(environment="test") if env == "test" else cls()
```

An unknown `FIRMABLE_ENV` raises a `ValueError` that lists the valid values. In the app,
`get_settings()` is only the fallback in `create_app(settings=None)`, used by the
module-level `app` and `run()`. Tests construct settings directly and pass them in.

Generation is off in production on purpose: a 500-company run takes minutes of CPU and
doesn't belong inside a web process. Datasets are generated offline and mounted.

### 4.2 Logging

```python
def configure_logging(settings: CommonSettings) -> None
class JsonFormatter(logging.Formatter)
```

`configure_logging` replaces the root handlers with one stderr handler, either plain
(`HH:MM:SS LEVEL logger: message`) or JSON. The JSON line contains `ts`, `level`, `logger`
and `message`, plus `request_id`, `method`, `path`, `status` and `duration_ms` when the
request middleware attaches them, and `exc` for tracebacks. The DataGenerator's own logger
is reset to propagate to the root, so generation jobs log in the same format.

### 4.3 Local Docker: `Local/docker-compose.yaml`

| Service | Image | What it does |
|---|---|---|
| `backend` | `uv:python3.12-bookworm-slim` | `uv sync --frozen`, then `uvicorn --reload` on :8000; health check on `/api/v1/health` |
| `frontend` | `node:22-bookworm-slim` | `npm ci`, then `next dev` on :3000; starts after the backend is healthy |

Windows-specific decisions:

- `Backend/` is bind-mounted, but the Linux virtualenv lives in a named volume
  (`UV_PROJECT_ENVIRONMENT=/opt/venv`), so it never clashes with a Windows `.venv`. The same
  goes for `node_modules` and `.next`.
- `WATCHFILES_FORCE_POLLING` and `WATCHPACK_POLLING` are set, because file-change events
  don't cross Windows bind mounts reliably.
- Paths are relative to the compose file (`../..`, `../../../Frontend`).
- Datasets stay on the host and nothing is generated at startup.

### 4.4 Production image: `Production/DockerfileProd`

```
stage builder  (ghcr.io/astral-sh/uv:python3.12-bookworm-slim)
  COPY pyproject.toml uv.lock + each member's pyproject.toml
  uv sync --frozen --no-dev --no-install-workspace     # dependency layer, cached
  COPY Infra, */src, DataGenerator/config
  uv sync --frozen --no-dev --no-editable              # workspace packages as wheels

stage runtime  (python:3.12-slim-bookworm)
  user app (uid 10001), /data/datasets and /data/artifacts owned by app
  COPY /app/.venv and the generator config
  ENV FIRMABLE_ENV=production, FIRMABLE_*_DIR=/data/..., PATH=/app/.venv/bin
  HEALTHCHECK GET /api/v1/health
  CMD uvicorn firmable.main:app --host 0.0.0.0 --port 8000 --proxy-headers
```

`.dockerignore` keeps datasets, caches, tests and markdown out of the build context. No
secrets are embedded; the app currently needs none.

### 4.5 Makefile

| Target | Command |
|---|---|
| `setup` / `install` | `uv sync` (+ copy `.env.example`) |
| `generate`, `generate-large`, `validate`, `benchmark-smoke` | DataGenerator CLI |
| `infer`, `evaluate`, `pipeline` | `orggraph-infer`, `scripts/run_pipeline.py` |
| `test`, `test-fullscale`, `lint`, `format`, `typecheck` | pytest, ruff, mypy |
| `api`, `api-prod` | uvicorn with local or production settings |
| `compose-up`, `compose-down`, `compose-logs` | Docker Compose |
| `docker-build-prod` | production image |

Every recipe is a plain `uv run ...` or `docker ...` line, so the commands can be copied
directly on Windows without `make`.

## 5. Testing

- `Application/src/firmable/tests/test_settings.py`: environment selection, nested env
  overrides, the production wildcard-CORS rejection, generation disabled in production.
- `Backend/tests/test_structure.py`: the repository layout, every path the Makefile refers
  to exists, and the docs are exactly one TRD per section.
- `docker compose config` validates the compose file.

## 6. Limitations and next steps

- The compose file is validated, but I haven't built the images on this machine, because
  Docker wasn't running.
- Running one API process per container is required, because the job state and the
  inference cache are in memory.
- TLS and authentication are expected from a gateway or reverse proxy in front of the API.
- The frontend production build (`next build`, standalone output) isn't part of this image;
  it would get its own Node image with `NEXT_PUBLIC_API_BASE_URL` set at build time.
