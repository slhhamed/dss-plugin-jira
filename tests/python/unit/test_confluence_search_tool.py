import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.append(str(ROOT_DIR / "python-lib"))


# ---------------------------------------------------------------------------
# Lightweight stubs so the tool module can be imported in isolation
# ---------------------------------------------------------------------------
if "dataiku" not in sys.modules:
    dataiku_module = types.ModuleType("dataiku")
    llm_module = types.ModuleType("dataiku.llm")
    agent_tools_module = types.ModuleType("dataiku.llm.agent_tools")

    class _BaseAgentTool:  # pragma: no cover - minimal shim
        pass

    agent_tools_module.BaseAgentTool = _BaseAgentTool
    llm_module.agent_tools = agent_tools_module
    dataiku_module.llm = llm_module

    sys.modules["dataiku"] = dataiku_module
    sys.modules["dataiku.llm"] = llm_module
    sys.modules["dataiku.llm.agent_tools"] = agent_tools_module


if "requests" not in sys.modules:
    requests_module = types.ModuleType("requests")

    class _RequestException(Exception):
        pass

    class _Response:  # pragma: no cover - minimal placeholder
        def __init__(self, status_code=200, payload=None, text="", ok=True):
            self.status_code = status_code
            self._payload = payload
            self.text = text
            self.ok = ok
            self.content = b"{}" if payload is not None else b""

        def json(self):
            if self._payload is None:
                raise ValueError("No JSON payload available")
            return self._payload

    class _Session:
        def __init__(self):
            self.headers = {}
            self.verify = True

        def request(self, *args, **kwargs):  # pragma: no cover - guard
            raise NotImplementedError("requests stub is not configured")

    requests_module.Session = _Session
    requests_module.RequestException = _RequestException
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
    def __init__(self, status_code=200, payload=None, text="", ok=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.ok = True if ok is None else ok
        self.content = b"{}" if payload is not None else b""

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON payload available")
        return self._payload


class DummyTrace:
    def __init__(self):
        self.span = {}
        self.inputs = {}
        self.outputs = {}
        self.attributes = {}


def _load_tool():
    tool = ConfluenceSearchPagesTool()
    config = {
        "access_type": "token_access",
        "token_access": {
            "server_type": "on_premise",
            "api_url": "https://confluence.example.com/",
            "ignore_ssl_check": False,
            "username": "user",
            "token": "token",
        },
        "space_key": "AIEC",
        "limit": "5",
    }
    tool.set_config(config, {})
    return tool


def test_confluence_client_builds_expected_cql(monkeypatch):
    captured = {}

    def fake_request(self, method, url, params=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = params
        payload = {
            "results": [
                {
                    "id": "123",
                    "title": "Dataiku Page",
                    "_links": {"webui": "/display/AIEC/Dataiku"},
                    "excerpt": "Snippet",
                    "lastModified": "2024-01-01T00:00:00Z",
                    "space": {"key": "AIEC"},
                }
            ]
        }
        return DummyResponse(payload=payload)

    monkeypatch.setattr(requests.Session, "request", fake_request)

    client = ConfluenceClient(
        {
            "server_type": "on_premise",
            "api_url": "https://confluence.example.com/",
            "ignore_ssl_check": False,
            "username": "user",
            "token": "pass",
        }
    )

    result = client.search_pages("what is Dataiku?", limit=3, space_key="AIEC")

    assert captured["method"] == "GET"
    assert captured["url"].endswith("/rest/api/search")
    assert captured["params"]["limit"] == 3
    assert (
        captured["params"]["cql"]
        == 'type=page AND space = "AIEC" AND text ~ "what is Dataiku" ORDER BY lastmodified DESC'
    )
    assert result["attempts"][0] == (
        'CQL=type=page AND space = "AIEC" AND text ~ "what is Dataiku" ORDER BY lastmodified DESC'
    )
    assert result["results"][0]["url"].endswith("/display/AIEC/Dataiku")
    assert result["results"][0]["space_key"] == "AIEC"

    monkeypatch.setattr(requests.Session, "request", fake_request)

def test_confluence_client_returns_error_message(monkeypatch):
    def fake_request(self, method, url, params=None, **kwargs):
        payload = {"message": "cql query parameter is required"}
        return DummyResponse(status_code=400, payload=payload, text=json.dumps(payload), ok=False)

    monkeypatch.setattr(requests.Session, "request", fake_request)

def test_confluence_client_uses_v1_on_on_prem(monkeypatch):
    client = ConfluenceClient(
        {
            "server_type": "on_premise",
            "api_url": "https://confluence.example.com/",
        }
    )

    captured = {}

    def fake_post(*args, **kwargs):  # pragma: no cover - defensive guard
        raise AssertionError("v2 search should not be attempted for on-prem instances")

    captured = {}

    def fake_get(url, params=None, auth=None, headers=None, verify=None):
        captured["url"] = url
        captured["params"] = params
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


def test_get_page_content_requests_body_storage(monkeypatch):
    captured = {}

    assert result["source"] == "v1"
    assert len(result["attempts"]) == 3
    assert result["attempts"][-1]["version"] == "v1"
    assert captured["params"]["limit"] == 1
    assert captured["params"]["cql"].startswith('space="SPACE" AND text~"legacy"')
    assert result["results"][0]["space_key"] == "SPACE"
    assert result["results"][0]["url"].endswith("/display/SPACE/Legacy+Page")

    monkeypatch.setattr(requests.Session, "request", fake_request)

def test_compose_v1_cql_query_scopes_space():
    client = ConfluenceClient(
        {
            "server_type": "on_premise",
            "api_url": "https://confluence.example.com/",
            "username": "user",
            "token": "token",
        }
    )

    cql = client._compose_v1_cql_query(query="Dataiku", space_key="AIEC")

    assert cql.startswith('space="AIEC" AND text~"Dataiku"')
    assert cql.endswith("ORDER BY lastmodified DESC")


def test_confluence_client_reports_error(monkeypatch):
    client = ConfluenceClient(
        {
            "server_type": "on_premise",
            "api_url": "https://confluence.example.com/",
        }
    )

    payload = client.get_page_content("123")

    assert captured["method"] == "GET"
    assert captured["url"].endswith("/rest/api/content/123")
    assert captured["params"] == {"expand": "body.storage"}
    assert payload["body"]["storage"]["value"] == "<p>Body</p>"


    assert result["source"] == "v2"
    assert result["error"]["message"] == "internal error"
    assert result["error"]["status_code"] == 500
    assert result["message"] == "internal error"

    recorded = {}

    class DummyClient:
        site_url = "https://confluence.example.com/"

        def search_pages(self, query, limit=None, space_key=None):
            recorded["query"] = query
            recorded["limit"] = limit
            recorded["space_key"] = space_key
            return {
                "results": [
                    {
                        "id": "123",
                        "title": "Dataiku",
                        "url_path": "/display/AIEC/Dataiku",
                        "space_key": "AIEC",
                    }
                ],
                "attempts": ["ok"],
                "source": "confluence",
            }

        def get_page_content(self, page_id):
            return {"body": {"storage": {"value": "<p>Content</p>"}}}

    tool.client = DummyClient()

    trace = DummyTrace()
    response = tool.invoke({"input": {"query": "Dataiku"}}, trace)

    assert recorded == {"query": "Dataiku", "limit": 5, "space_key": "AIEC"}
    assert len(response["results"]) == 1
    assert response["results"][0]["page_content"] == "<p>Content</p>"
    assert trace.outputs["results"][0]["url"].endswith("/display/AIEC/Dataiku")


def test_tool_surfaces_error_message(monkeypatch):
    tool = _load_tool()

    class DummyClient:
        site_url = "https://confluence.example.com/"

        def search_pages(self, query, limit=None, space_key=None):
            return {
                "results": [],
                "error": {"message": "HTTP 400: cql query parameter is required"},
                "message": "HTTP 400: cql query parameter is required",
                "attempts": ["failure"],
                "source": "confluence",
            }

    tool.client = DummyClient()

    trace = DummyTrace()
    response = tool.invoke({"input": {"query": "Dataiku"}}, trace)

    result = tool_instance.invoke(
        {"input": {"query": "tool", "space_key": "SPACE", "limit": 1}},
        trace,
    )

    assert trace.attributes["config"]["limit"] == 1
    assert trace.inputs["query"] == "tool"
    assert trace.inputs["limit"] == 1
    assert trace.inputs["space_key"] == "SPACE"
    assert trace.attributes["search"]["source"] == "v2"
    assert trace.attributes["search"]["space_key"] == "SPACE"
    assert len(result["results"]) == 1
    item = result["results"][0]
    assert item["page_id"] == "789"
    assert "Tool excerpt" in item["excerpt"]
    assert item["page_content"] == "<p>Content for 789</p>"
    assert trace.outputs["results"] == result["results"]



def test_compose_v1_cql_query_escapes_special_characters():
    client = ConfluenceClient(
        {
            "server_type": "on_premise",
            "api_url": "https://confluence.example.com/",
            "username": "user",
            "token": "token",
        }
    )

    raw_query = 'Data "iku" \\ story'
    raw_space = ' A"IEC '
    cql = client._compose_v1_cql_query(
        query=raw_query,
        space_key=raw_space,
    )

    expected_space = raw_space.strip().replace("\\", "\\\\").replace('"', '\\"')
    expected_query = raw_query.strip().replace("\\", "\\\\").replace('"', '\\"')

    assert f'space="{expected_space}"' in cql
    assert f'text~"{expected_query}"' in cql
    assert cql.endswith('ORDER BY lastmodified DESC')


def test_build_v2_payload_normalizes_inputs():
    client = ConfluenceClient(
        {
            "server_type": "cloud",
            "subdomain": "example",
            "username": "user",
            "token": "token",
        }
    )

    raw_query = '  Demo  "story"  '
    payload = client._build_v2_payload(
        query=raw_query,
        limit=5,
        space_key=' SPACE ',
    )

    expected_query = raw_query.strip().replace("\\", "\\\\").replace('"', '\\"')

    assert payload["queryString"] == f'text ~ "{expected_query}"'
    assert payload["limit"] == 5
    assert payload["spaceKeys"] == ["SPACE"]



def test_tool_invoke_sanitizes_inputs():
    tool_instance = ConfluenceSearchPagesTool()

    captured = {}

    class DummyClient:
        site_url = "https://confluence.example.com/"

        def search_pages(self, query, limit=3, space_key=None):
            captured["query"] = query
            captured["limit"] = limit
            captured["space_key"] = space_key
            return {"results": [], "source": "v1", "attempts": []}

    tool_instance.client = DummyClient()

    trace = DummyTrace()

    result = tool_instance.invoke(
        {"input": {"query": "  trimmed  ", "space_key": "   ", "limit": "invalid"}},
        trace,
    )

    assert captured == {"query": "trimmed", "limit": 3, "space_key": None}
    assert trace.inputs["query"] == "trimmed"
    assert trace.inputs["limit"] == 3
    assert trace.inputs["space_key"] is None
    assert trace.attributes["config"]["limit"] == 3
    assert trace.attributes["search"]["source"] == "v1"
    assert trace.attributes["search"]["space_key"] is None
    assert result["results"] == []
    assert result["output"] == "No Confluence pages matched your query."
