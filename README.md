# xhs-reader-mcp

A minimal FastAPI backend that will later become a read-only Xiaohongshu URL reader and MCP server.

## Current milestone

Version 0.1 only proves that the deployment pipeline works:

GitHub → Render → public HTTPS API

## Endpoints

- `GET /` — service information
- `GET /health` — health check

## Local run

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open:

- http://127.0.0.1:8000/
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/docs

## Render

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```
