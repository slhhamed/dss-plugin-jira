import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.append(str(ROOT_DIR / "python-lib"))


if "dataiku" not in sys.modules:
    dataiku_module = types.ModuleType("dataiku")
    llm_module = types.ModuleType("dataiku.llm")
    agent_tools_module = types.ModuleType("dataiku.llm.agent_tools")

    class _BaseAgentTool:  # pragma: no cover - trivial stub
        def __init__(self, *args, **kwargs):
            pass

    agent_tools_module.BaseAgentTool = _BaseAgentTool
    llm_module.agent_tools = agent_tools_module
    dataiku_module.llm = llm_module

    sys.modules["dataiku"] = dataiku_module
    sys.modules["dataiku.llm"] = llm_module
    sys.modules["dataiku.llm.agent_tools"] = agent_tools_module


if "requests" not in sys.modules:
    requests_module = types.ModuleType("requests")

    def _request_stub(*args, **kwargs):  # pragma: no cover - safety stub
        raise NotImplementedError("The requests module is not available in the test environment.")

    requests_module.get = _request_stub
    requests_module.post = _request_stub

    class _RequestException(Exception):
        pass

    requests_module.RequestException = _RequestException

    class _Response:  # pragma: no cover - minimal placeholder
        pass

    requests_module.Response = _Response
    sys.modules["requests"] = requests_module


import requests

if "numpy" not in sys.modules:
    numpy_module = types.ModuleType("numpy")
    numpy_module.float64 = float
    numpy_module.nan = float("nan")
    sys.modules["numpy"] = numpy_module


search_tool_path = ROOT_DIR / "python-agent-tools" / "search-confluence-pages" / "tool.py"
spec = importlib.util.spec_from_file_location("search_confluence_tool", search_tool_path)
search_tool_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search_tool_module)
ConfluenceSearchPagesTool = search_tool_module.ConfluenceSearchPagesTool

from confluence_client import ConfluenceClient


class DummyResponse:
    def __init__(self, status_code, payload, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or ""

    def json(self):
        return self._payload


class DummyTrace:
    def __init__(self):
        self.span = {}
        self.inputs = {}
        self.outputs = {}
        self.attributes = {}


def test_confluence_client_prefers_v2(monkeypatch):
    client = ConfluenceClient(
        {
            "server_type": "cloud",
            "subdomain": "example",
            "username": "user",
            "token": "token",
        }
    )

    captured = {}

    def fake_post(url, json=None, auth=None, headers=None, verify=None):
        captured["url"] = url
        captured["json"] = json
        return DummyResponse(
            200,
            {
                "results": [
                    {
                        "content": {
                            "id": "123",
                            "title": "Demo Page",
                            "_links": {"webui": "/wiki/spaces/SPACE/pages/123/Demo+Page"},
                        },
                        "excerpt": "Demo excerpt",
                    }
                ]
            },
        )

    def fake_get(*args, **kwargs):  # pragma: no cover - defensive fallback
        raise AssertionError("v1 search should not be used when v2 succeeds")

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)

    result = client.search_pages("demo", limit=2, space_key="SPACE")

    assert result["source"] == "v2"
    assert captured["json"]["spaceKeys"] == ["SPACE"]
    assert captured["json"]["limit"] == 2
    assert result["results"][0]["title"] == "Demo Page"
    assert result["results"][0]["url"].endswith("/wiki/spaces/SPACE/pages/123/Demo+Page")


def test_confluence_client_falls_back_to_v1(monkeypatch):
    client = ConfluenceClient(
        {
            "server_type": "on_premise",
            "api_url": "https://confluence.example.com/",
            "username": "user",
            "token": "token",
        }
    )

    def fake_post(url, json=None, auth=None, headers=None, verify=None):
        return DummyResponse(404, {"message": "not found"}, text="not found")

    def fake_get(url, params=None, auth=None, headers=None, verify=None):
        return DummyResponse(
            200,
            {
                "results": [
                    {
                        "content": {
                            "id": "456",
                            "title": "Legacy Page",
                            "_links": {"webui": "/display/SPACE/Legacy+Page"},
                            "space": {"key": "SPACE"},
                        },
                        "excerpt": "Legacy excerpt",
                    }
                ]
            },
        )

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)

    result = client.search_pages("legacy", limit=1, space_key="SPACE")

    assert result["source"] == "v1"
    assert len(result["attempts"]) == 3
    assert result["attempts"][-1]["version"] == "v1"
    assert result["results"][0]["space_key"] == "SPACE"
    assert result["results"][0]["url"].endswith("/display/SPACE/Legacy+Page")


def test_confluence_client_reports_error(monkeypatch):
    client = ConfluenceClient(
        {
            "server_type": "cloud",
            "subdomain": "example",
            "username": "user",
            "token": "token",
        }
    )

    def fake_post(url, json=None, auth=None, headers=None, verify=None):
        return DummyResponse(500, {"message": "internal error"}, text="internal error")

    def fake_get(*args, **kwargs):  # pragma: no cover - defensive fallback
        raise AssertionError("v1 search should not execute on fatal v2 errors")

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)

    result = client.search_pages("demo", limit=3)

    assert result["source"] == "v2"
    assert result["error"]["message"] == "internal error"
    assert result["error"]["status_code"] == 500


def test_tool_invoke_formats_results_and_trace(monkeypatch):
    tool_instance = ConfluenceSearchPagesTool()

    class DummyClient:
        site_url = "https://confluence.example.com/"

        def search_pages(self, query, limit=3, space_key=None):
            return {
                "results": [
                    {
                        "id": "789",
                        "title": "Tool Page",
                        "url": "https://confluence.example.com/display/SPACE/Tool+Page",
                        "excerpt": "Tool excerpt",
                        "last_modified": "2024-01-01T00:00:00.000Z",
                        "space_key": space_key,
                    },
                    {
                        "id": "000",
                        "title": "Should be trimmed",
                        "url": "https://confluence.example.com/display/SPACE/Trimmed",
                    },
                ],
                "source": "v2",
                "attempts": [
                    {"version": "v2", "status_code": 200},
                ],
            }

        def get_page_content(self, page_id):
            return {
                "body": {
                    "storage": {
                        "value": f"<p>Content for {page_id}</p>",
                    }
                }
            }

    tool_instance.client = DummyClient()

    trace = DummyTrace()

    result = tool_instance.invoke(
        {"input": {"query": "tool", "space_key": "SPACE", "limit": 1}},
        trace,
    )

    assert trace.attributes["config"]["limit"] == 1
    assert trace.attributes["search"]["source"] == "v2"
    assert trace.attributes["search"]["space_key"] == "SPACE"
    assert len(result["results"]) == 1
    item = result["results"][0]
    assert item["page_id"] == "789"
    assert "Tool excerpt" in item["excerpt"]
    assert item["page_content"] == "<p>Content for 789</p>"
    assert trace.outputs["results"] == result["results"]