from urllib.parse import urljoin, urlparse, parse_qs

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(
    title="XHS Reader MCP",
    description="Backend for resolving Xiaohongshu shared URLs.",
    version="0.2.0",
)


ALLOWED_HOSTS = {
    "xhslink.com",
    "www.xhslink.com",
    "xiaohongshu.com",
    "www.xiaohongshu.com",
}


class ResolveRequest(BaseModel):
    url: str


def validate_xhs_url(url: str):
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=400,
            detail="Only HTTP/HTTPS URLs are supported.",
        )

    host = (parsed.hostname or "").lower()

    if host not in ALLOWED_HOSTS:
        raise HTTPException(
            status_code=400,
            detail="Only Xiaohongshu URLs are allowed.",
        )


async def resolve_redirects(url: str) -> str:
    current_url = url

    async with httpx.AsyncClient(
        timeout=15.0,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/130 Safari/537.36"
            )
        },
    ) as client:

        for _ in range(6):
            validate_xhs_url(current_url)

            response = await client.get(
                current_url,
                follow_redirects=False,
            )

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")

                if not location:
                    break

                next_url = urljoin(current_url, location)
                validate_xhs_url(next_url)

                current_url = next_url
                continue

            break

    return current_url


def extract_note_info(url: str):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    path_parts = [
        part for part in parsed.path.split("/")
        if part
    ]

    note_id = None

    if "explore" in path_parts:
        index = path_parts.index("explore")

        if index + 1 < len(path_parts):
            note_id = path_parts[index + 1]

    elif "discovery" in path_parts:
        if "item" in path_parts:
            index = path_parts.index("item")

            if index + 1 < len(path_parts):
                note_id = path_parts[index + 1]

    xsec_token = query.get("xsec_token", [None])[0]
    xsec_source = query.get("xsec_source", [None])[0]

    return {
        "note_id": note_id,
        "xsec_token": xsec_token,
        "xsec_source": xsec_source,
    }


@app.get("/")
def root():
    return {
        "name": "xhs-reader-mcp",
        "version": "0.2.0",
        "message": "XHS Reader backend is running.",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/resolve")
async def resolve_xhs_url(request: ResolveRequest):
    validate_xhs_url(request.url)

    try:
        final_url = await resolve_redirects(request.url)

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to access Xiaohongshu: {exc}",
        )

    info = extract_note_info(final_url)

    return {
        "input_url": request.url,
        "resolved_url": final_url,
        **info,
    }
