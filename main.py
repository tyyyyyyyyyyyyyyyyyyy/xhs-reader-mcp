from fastapi import FastAPI

app = FastAPI(
    title="XHS Reader MCP",
    description="Minimal backend for the XHS Reader project.",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "name": "xhs-reader-mcp",
        "version": "0.1.0",
        "message": "XHS Reader backend is running.",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
