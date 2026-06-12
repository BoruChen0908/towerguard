# TowerGuard — Backend Modules

> **Non-certified ATC support system. Not for operational use.**

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in OPENSKY_CLIENT_ID, OPENSKY_CLIENT_SECRET, REDIS_URL
```

## Start Redis

```bash
docker compose up -d redis
```

## Run the data runner

```bash
python -m modules.runner
```

The runner fetches OpenSky state vectors every 60 seconds and publishes three
Redis pub/sub events: `towerguard:traffic_density`, `towerguard:conflict_geometry`,
`towerguard:workload_index`.

## Run tests

```bash
ruff format . && ruff check .
pytest -v --cov=. --cov-report=term-missing
```
