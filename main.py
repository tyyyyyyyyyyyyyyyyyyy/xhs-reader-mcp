import re
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(
    title="XHS Reader MCP",
    description="Backend for resolving Xiaohongshu shared URLs.",
    version="0.3.0",
)


ALLOWED_HOSTS = {
    "xhslink.com",
    "www.xhslink.com",
    "xiaohongshu.com",
    "www.xiaohongshu.com",
}


class ResolveRequest(BaseModel):
    url: str


def extract_url_from_text(text: str) -> str:
    """
    Accept either:
    1. A bare Xiaohongshu URL
    2. A whole Xiaohongshu share message containing a URL
    """

    match = re.search(r"https?://[^\s<>\"']+", text)

    if not match:
        raise HTTPException(
            status_code=400,
            detail="No HTTP/HTTPS URL was found in the input.",
        )

    url = match.group(0)

    # Remove punctuation that may be attached to the end of copied text
    url = url.rstrip("。，！？；：,!?;:)]}）】")

    return url


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


def extract_note_info(url: str):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    path_parts = [
        part for part in parsed.path.split("/")
        if part
    ]

    note_id = None

    # Example:
    # /explore/xxxxxxxx
    if "explore" in path_parts:
        index = path_parts.index("explore")

        if index + 1 < len(path_parts):
            note_id = path_parts[index + 1]

    # Example:
    # /discovery/item/xxxxxxxx
    elif "discovery" in path_parts and "item" in path_parts:
        index = path_parts.index("item")

        if index + 1 < len(path_parts):
            note_id = path_parts[index + 1]

    xsec_token = query.get("xsec_token", [None])[0]
    xsec_source = query.get("xsec_source", [None])[0]

    # Xiaohongshu sometimes redirects to:
    # /login?redirectPath=<original post URL>
    #
    # Recover the original post URL from redirectPath.
    if not note_id:
        redirect_path = query.get("redirectPath", [None])[0]

        if redirect_path:
            decoded = unquote(redirect_path)

            if decoded.startswith("http"):
                nested_info = extract_note_info(decoded)

                if nested_info["note_id"]:
                    return nested_info

    return {
        "note_id": note_id,
        "xsec_token": xsec_token,
        "xsec_source": xsec_source,
    }


async def resolve_redirects(url: str) -> str:
    current_url = url

    async with httpx.AsyncClient(
        timeout=15.0,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            )
        },
    ) as client:

        for _ in range(6):

            validate_xhs_url(current_url)

            # Important:
            # If this URL already identifies a post,
            # do NOT continue requesting it and get redirected to login.
            info = extract_note_info(current_url)

            if info["note_id"]:
                return current_url

            response = await client.get(
                current_url,
                follow_redirects=False,
            )

            if response.status_code in {
                301,
                302,
                303,
                307,
                308,
            }:
                location = response.headers.get("location")

                if not location:
                    break

                next_url = urljoin(
                    current_url,
                    location,
                )

                validate_xhs_url(next_url)

                # Stop as soon as a real post URL appears.
                next_info = extract_note_info(next_url)

                if next_info["note_id"]:
                    return next_url

                current_url = next_url
                continue

            break

    return current_url


@app.get("/")
def root():
    return {
        "name": "xhs-reader-mcp",
        "version": "0.3.0",
        "message": "XHS Reader backend is running.",
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post("/resolve")
async def resolve_xhs_url(request: ResolveRequest):

    # Allow an entire Xiaohongshu share message,
    # not just a bare URL.
    cleaned_url = extract_url_from_text(
        request.url
    )

    validate_xhs_url(cleaned_url)

    # First try parsing the original URL.
    # Direct Xiaohongshu post URLs may already contain everything we need.
    original_info = extract_note_info(
        cleaned_url
    )

    if original_info["note_id"]:
        return {
            "input": request.url,
            "cleaned_url": cleaned_url,
            "resolved_url": cleaned_url,
            **original_info,
        }

    # Short links such as xhslink.com need redirect resolution.
    try:
        final_url = await resolve_redirects(
            cleaned_url
        )

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to access Xiaohongshu: {exc}",
        )

    final_info = extract_note_info(
        final_url
    )

    return {
        "input": request.url,
        "cleaned_url": cleaned_url,
        "resolved_url": final_url,
        **final_info,
    }
