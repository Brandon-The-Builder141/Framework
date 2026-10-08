from __future__ import annotations

import pytest
import httpx
from src.tools import search


@pytest.mark.asyncio
async def test_search_huggingface_models(monkeypatch) -> None:
    # Mock Response data
    mock_data = [
        {
            "id": "gpt2",
            "likes": 5000,
            "downloads": 120000,
            "pipeline_tag": "text-generation",
        },
        {
            "id": "bert-base-uncased",
            "likes": 4000,
            "downloads": 95000,
            "pipeline_tag": "fill-mask",
        }
    ]

    class MockResponse:
        def __init__(self, json_data, status_code=200):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("API Error", request=None, response=None)

    async def mock_get(self, url, params=None, headers=None, timeout=None):
        assert "models" in url
        assert params["search"] == "gpt"
        return MockResponse(mock_data)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    res = await search.search_huggingface("gpt", resource_type="models")
    assert "gpt2" in res
    assert "Likes: 5000" in res
    assert "Downloads: 120000" in res
    assert "Task: text-generation" in res
    assert "bert-base-uncased" in res


@pytest.mark.asyncio
async def test_search_github(monkeypatch) -> None:
    # Mock Response data
    mock_data = {
        "items": [
            {
                "full_name": "google/jax",
                "html_url": "https://github.com/google/jax",
                "description": "Autograd and XLA",
                "stargazers_count": 28000,
                "forks_count": 2500,
                "language": "Python",
            }
        ]
    }

    class MockResponse:
        def __init__(self, json_data, status_code=200):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("API Error", request=None, response=None)

    async def mock_get(self, url, params=None, headers=None, timeout=None):
        assert "repositories" in url
        assert params["q"] == "jax"
        return MockResponse(mock_data)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    res = await search.search_github("jax")
    assert "google/jax" in res
    assert "Stars: 28000" in res
    assert "Forks: 2500" in res
    assert "Language: Python" in res
    assert "Description: Autograd and XLA" in res
