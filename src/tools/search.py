"""Web search via DuckDuckGo (free, no API key). Uses ddgs package."""
import asyncio
import os
import httpx
from ddgs import DDGS


def _search_sync(query: str, max_results: int) -> list[dict]:
    """Run search in thread."""
    results = list(DDGS().text(query, max_results=max_results))
    return [
        {
            "title": r.get("title", ""),
            "href": r.get("href", ""),
            "body": r.get("body", ""),
        }
        for r in results
    ]


async def search_web(query: str, max_results: int = 8) -> str:
    """Search the web and return formatted results."""
    try:
        results = await asyncio.to_thread(_search_sync, query, max_results)
    except Exception as e:
        return f"Error: {e}"

    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        href = r.get("href", "")
        body = (r.get("body") or "")[:200]
        lines.append(f"{i}. {title}\n   {href}\n   {body}")
    return "\n\n".join(lines)


async def search_huggingface(query: str, resource_type: str = "models", max_results: int = 5) -> str:
    """Search Hugging Face for models, datasets, or spaces."""
    if resource_type not in ("models", "datasets", "spaces"):
        return f"Error: Unsupported resource_type '{resource_type}'. Supported: models, datasets, spaces."

    url = f"https://huggingface.co/api/{resource_type}"
    params = {"search": query, "limit": max_results}
    headers = {"User-Agent": "eve-assistant/1.0"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return f"Error querying Hugging Face API: {e}"

    if not data:
        return f"No Hugging Face {resource_type} found matching '{query}'."

    lines = []
    for i, item in enumerate(data, 1):
        item_id = item.get("id", "")
        if not item_id:
            continue
        url_link = f"https://huggingface.co/{item_id}" if resource_type != "spaces" else f"https://huggingface.co/spaces/{item_id}"
        likes = item.get("likes", 0)
        downloads = item.get("downloads", 0)

        info = f"{i}. {item_id}\n   URL: {url_link}\n   Likes: {likes}"
        if "downloads" in item:
            info += f" | Downloads: {downloads}"

        if "pipeline_tag" in item and item["pipeline_tag"]:
            info += f" | Task: {item['pipeline_tag']}"
        elif "author" in item and item["author"]:
            info += f" | Author: {item['author']}"

        lines.append(info)

    return "\n\n".join(lines)


async def search_github(query: str, max_results: int = 5) -> str:
    """Search GitHub repositories."""
    url = "https://api.github.com/search/repositories"
    params = {"q": query, "per_page": max_results}
    headers = {"User-Agent": "eve-assistant/1.0"}

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return f"Error querying GitHub API: {e}"

    items = data.get("items", [])
    if not items:
        return f"No GitHub repositories found matching '{query}'."

    lines = []
    for i, repo in enumerate(items, 1):
        full_name = repo.get("full_name", "")
        html_url = repo.get("html_url", "")
        desc = repo.get("description", "No description provided.")
        stars = repo.get("stargazers_count", 0)
        forks = repo.get("forks_count", 0)
        lang = repo.get("language", "Unknown")

        lines.append(
            f"{i}. {full_name}\n"
            f"   URL: {html_url}\n"
            f"   Stars: {stars} | Forks: {forks} | Language: {lang}\n"
            f"   Description: {desc}"
        )

    return "\n\n".join(lines)

