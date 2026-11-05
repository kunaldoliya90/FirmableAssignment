# FirmableAssignment: OrgGraph

Given a flat, messy list of a company's employees, work out who reports to whom. Every
answer comes with a confidence score and the evidence behind it. When the data isn't good
enough, the system says so instead of guessing.

```
Backend/    Python, one uv workspace
  DataGenerator/   synthetic companies with hidden ground truth      -> DataGenerator/TRD.md
  Inference/       infers reporting lines from observed data only    -> Inference/TRD.md
  Application/     FastAPI service the UI talks to                   -> Application/TRD.md
  Infra/           settings, logging, Docker                         -> Infra/TRD.md
Frontend/   Next.js UI with the interactive org chart                -> Frontend/TRD.md
```

## Running it

You need Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node 20+.

```bash
cd Backend
uv sync
uv run orggraph-dataset generate --companies 500 --target-employees 50000 --seed 42   # once, ~1.5 min
uv run uvicorn firmable.main:app --reload --port 8000                                 # http://localhost:8000/docs

cd ../Frontend
npm install
npm run dev                                                                            # http://localhost:3000
```

Or use Docker: `cd Backend && docker compose -f Infra/Local/docker-compose.yaml up`.

## Where it stands

On the held-out test split, the engine gets **96% of the edges it predicts right, and
predicts an edge for 39% of employees** (up from 33% with hand-set weights). It abstains on
the rest on purpose: a wrong reporting line costs more than a missing one, and in this data
many employees have several managers that no observed field can tell apart, which caps
high-precision recall at roughly 45–55%. The scoring weights are learned offline on the
train split (`orggraph-infer train`); the Inference TRD has the numbers and the analysis.

## Tests

```bash
cd Backend && make test        # or, without make: run `uv run pytest -q` inside DataGenerator,
                               # Inference and Application, then once in Backend/
cd Frontend && npm test
```

## Deploying

The backend runs on Render as a Docker web service, the frontend on Vercel.

**Backend (Render).** Create a Blueprint from this repo with the Blueprint path
`Backend/Infra/Production/render.yaml`, or create a Docker web service by hand with context
`Backend`, Dockerfile `Backend/Infra/Production/DockerfileProd` and health check
`/api/v1/health`. Then set:

| Variable | Value |
|---|---|
| `FIRMABLE_ENV` | `production` |
| `FIRMABLE_CORS_ORIGINS` | `["https://<your-app>.vercel.app"]` |
| `FIRMABLE_CORS_ORIGIN_REGEX` | optional, for preview URLs: `^https://<your-app>-[a-z0-9-]+\.vercel\.app$` |

What survives a deploy:

- **Code, learned weights and title aliases** are committed files and ship inside the image.
- **The dataset** is committed and baked into the image, so it is there on every deploy.
- **Predictions and evaluations** for validation, test and challenge are computed while the
  image builds and copied into `/data/artifacts` at startup, so every deploy starts complete.
- **Runtime results** (inference or evaluation runs started from the UI) are lost on a
  redeploy or restart on the free plan. To keep them, switch the blueprint to `starter` and
  uncomment its disk; the seed then never overwrites them.
- **Background jobs** are in memory, so a job running during a deploy is lost; rerun it.

**Frontend (Vercel).** Import the repo, set the root directory to `Frontend` and add
`NEXT_PUBLIC_API_BASE_URL=https://<your-service>.onrender.com/api/v1` for Production and
Preview. The variable is inlined at build time, so redeploy after changing it.

After the first deploy, check the Render logs for `seeded artifacts into /data/artifacts`
and open the Evaluation page; it should list three evaluations.
