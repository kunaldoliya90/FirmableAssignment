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

On the held-out test split, the engine gets **95% of the edges it predicts right, and
predicts an edge for 33% of employees**. It abstains on the rest on purpose: a wrong
reporting line costs more than a missing one. The trade-off is one setting, and the
Inference TRD has the numbers for other thresholds.

## Tests

```bash
cd Backend && make test        # or, without make: run `uv run pytest -q` inside DataGenerator,
                               # Inference and Application, then once in Backend/
cd Frontend && npm test
```
