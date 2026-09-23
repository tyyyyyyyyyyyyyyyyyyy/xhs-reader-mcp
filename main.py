import re
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(
    title="XHS Reader MCP",
    description="Backend for resolving and reading Xiaohongshu shared URLs.",
    version="0.4.0",
)


ALLOWED_HOSTS = {
    "xhslink.com",
    "www.xhslink.com",
    "xiaohongshu.com",
    "www.xiaohongshu.com",
}


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


class ResolveRequest(BaseModel):
    url: str


def extract_url_from_text(text: str) -> str:
    match = re.search(r"https?://[^\s<>\"']+", text)

    if not match:
        raise HTTPException(
            status_code=400,
            detail="No HTTP/HTTPS URL was found in the input.",
        )

    return match.group(0).rstrip(
        "。，！？；：,!?;:)]}）】"
    )


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

    if "explore" in path_parts:
        index = path_parts.index("explore")

        if index + 1 < len(path_parts):
            note_id = path_parts[index + 1]

    elif "discovery" in path_parts and "item" in path_parts:
        index = path_parts.index("item")

        if index + 1 < len(path_parts):
            note_id = path_parts[index + 1]

    xsec_token = query.get(
        "xsec_token",
        [None],
    )[0]

    xsec_source = query.get(
        "xsec_source",
        [None],
    )[0]

    if not note_id:
        redirect_path = query.get(
            "redirectPath",
            [None],
        )[0]

        if redirect_path:
            decoded = unquote(redirect_path)

            if decoded.startswith("http"):
                nested = extract_note_info(decoded)

                if nested["note_id"]:
                    return nested

    return {
        "note_id": note_id,
        "xsec_token": xsec_token,
        "xsec_source": xsec_source,
    }


async def resolve_redirects(url: str) -> str:
    current_url = url

    async with httpx.AsyncClient(
        timeout=15.0,
        headers={"User-Agent": USER_AGENT},
    ) as client:

        for _ in range(6):
            validate_xhs_url(current_url)

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
                location = response.headers.get(
                    "location"
                )

                if not location:
                    break

                next_url = urljoin(
                    current_url,
                    location,
                )

                validate_xhs_url(next_url)

                next_info = extract_note_info(
                    next_url
                )

                if next_info["note_id"]:
                    return next_url

                current_url = next_url
                continue

            break

    return current_url


async def normalize_input(text: str):
    cleaned_url = extract_url_from_text(text)

    validate_xhs_url(cleaned_url)

    info = extract_note_info(cleaned_url)

    if info["note_id"]:
        return cleaned_url, cleaned_url, info

    final_url = await resolve_redirects(
        cleaned_url
    )

    final_info = extract_note_info(
        final_url
    )

    return cleaned_url, final_url, final_info


def get_meta(
    soup: BeautifulSoup,
    *,
    property_name=None,
    name=None,
):
    if property_name:
        tag = soup.find(
            "meta",
            attrs={"property": property_name},
        )

    else:
        tag = soup.find(
            "meta",
            attrs={"name": name},
        )

    if tag:
        return tag.get("content")

    return None


async def fetch_public_post_page(url: str):
    validate_xhs_url(url)

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": (
                "zh-CN,zh;q=0.9,en;q=0.8"
            ),
        },
    ) as client:

        current_url = url

        for _ in range(5):
            validate_xhs_url(current_url)

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
                location = response.headers.get(
                    "location"
                )

                if not location:
                    break

                current_url = urljoin(
                    current_url,
                    location,
                )

                validate_xhs_url(current_url)
                continue

            return response, current_url

    raise HTTPException(
        status_code=502,
        detail="Too many redirects.",
    )


@app.get("/")
def root():
    return {
        "name": "xhs-reader-mcp",
        "version": "0.4.0",
        "message": "XHS Reader backend is running.",
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post("/resolve")
async def resolve_xhs_url(
    request: ResolveRequest
):
    try:
        cleaned_url, final_url, info = (
            await normalize_input(request.url)
        )

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to access Xiaohongshu: "
                f"{exc}"
            ),
        )

    return {
        "input": request.url,
        "cleaned_url": cleaned_url,
        "resolved_url": final_url,
        **info,
    }


@app.post("/read")
async def read_xhs_post(
    request: ResolveRequest
):
    try:
        cleaned_url, final_url, info = (
            await normalize_input(request.url)
        )

        response, fetched_url = (
            await fetch_public_post_page(
                final_url
            )
        )

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to access Xiaohongshu: "
                f"{exc}"
            ),
        )

    content_type = response.headers.get(
        "content-type",
        "",
    )

    html = response.text

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    title = (
        get_meta(
            soup,
            property_name="og:title",
        )
        or get_meta(
            soup,
            name="title",
        )
        or (
            soup.title.string.strip()
            if soup.title and soup.title.string
            else None
        )
    )

    description = (
        get_meta(
            soup,
            property_name="og:description",
        )
        or get_meta(
            soup,
            name="description",
        )
    )

    image = get_meta(
        soup,
        property_name="og:image",
    )

    final_path = urlparse(
        fetched_url
    ).path.lower()

    needs_login = (
        "/login" in final_path
        or "登录" in title
        if title
        else "/login" in final_path
    )

    return {
        "note_id": info["note_id"],
        "xsec_source": info["xsec_source"],
        "requested_url": final_url,
        "fetched_url": fetched_url,
        "status_code": response.status_code,
        "content_type": content_type,
        "needs_login": needs_login,
        "title": title,
        "description": description,
        "image": image,
        "html_size": len(html),
    }
