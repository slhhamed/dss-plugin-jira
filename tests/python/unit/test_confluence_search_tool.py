import json
import sys
import types
from pathlib import Path
import importlib.util


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
    def __init__(self, status_code=200, payload=None, text="", ok=None, content=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.ok = True if ok is None else ok
        if content is not None:
            self.content = content
        else:
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


def test_confluence_client_search_pages_builds_expected_cql(monkeypatch):
    captured = {}

    def fake_request(self, method, url, params=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = params
        payload = {
            "results": [
                {
                    "id": "123",
                    "content": {
                        "id": "123",
                        "title": "Dataiku Page",
                        "_links": {"webui": "/display/AIEC/Dataiku"},
                        "space": {"key": "AIEC"},
                    },
                    "excerpt": "Snippet",
                    "lastModified": "2024-01-01T00:00:00Z",
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
        == 'type = "page" AND space = "AIEC" AND text ~ "what is Dataiku" ORDER BY lastmodified DESC'
    )
    assert result["attempts"][0] == (
        'CQL=type = "page" AND space = "AIEC" AND text ~ "what is Dataiku" ORDER BY lastmodified DESC'
    )
    assert result["attempts"][1].startswith("GET")
    assert result["results"][0]["url"].endswith("/display/AIEC/Dataiku")
    assert result["results"][0]["space_key"] == "AIEC"


def test_confluence_client_search_pages_applies_filters(monkeypatch):
    captured = {}

    def fake_request(self, method, url, params=None, **kwargs):
        captured["params"] = params
        return DummyResponse(payload={"results": []})

    monkeypatch.setattr(requests.Session, "request", fake_request)

    client = ConfluenceClient({"api_url": "https://confluence.example.com/"})

    client.search_pages(
        "analytics",
        limit=10,
        filters={
            "type": "blogpost",
            "labels": ["release", "internal"],
            "creator": "jsmith",
            "contributor": "adoe",
            "last_modified": "last_week",
            "order_by": "created_asc",
        },
    )

    cql = captured["params"]["cql"]
    assert 'type = "blogpost"' in cql
    assert 'label = "release"' in cql
    assert 'label = "internal"' in cql
    assert 'creator = "jsmith"' in cql
    assert 'contributor = "adoe"' in cql
    assert 'lastmodified >= startOfDay(-7d)' in cql
    assert cql.endswith("ORDER BY created ASC")


def test_confluence_client_search_pages_handles_error(monkeypatch):
    def fake_request(self, method, url, params=None, **kwargs):
        payload = {"message": "cql query parameter is required"}
        return DummyResponse(status_code=400, payload=payload, text=json.dumps(payload), ok=False)

    monkeypatch.setattr(requests.Session, "request", fake_request)

    client = ConfluenceClient({"api_url": "https://confluence.example.com/"})

    result = client.search_pages("Dataiku")

    assert result["results"] == []
    assert "HTTP 400" in result["error"]["message"]
    assert result["message"].startswith("HTTP 400")


def test_confluence_client_search_pages_handles_request_exception(monkeypatch):
    def fake_request(self, method, url, params=None, **kwargs):  # pragma: no cover - stub
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests.Session, "request", fake_request)

    client = ConfluenceClient({"api_url": "https://confluence.example.com/"})

    result = client.search_pages("Dataiku")

    assert result["results"] == []
    assert result["error"]["message"] == "Request failed: boom"
    assert result["message"] == "Request failed: boom"


def test_confluence_client_get_page_content_requests_body_storage(monkeypatch):
    captured = {}

    def fake_request(self, method, url, params=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = params
        payload = {"body": {"storage": {"value": "<p>Body</p>"}}}
        return DummyResponse(payload=payload)

    monkeypatch.setattr(requests.Session, "request", fake_request)

    client = ConfluenceClient({"api_url": "https://confluence.example.com/"})

    payload = client.get_page_content("123")

    assert captured["method"] == "GET"
    assert captured["url"].endswith("/rest/api/content/123")
    assert captured["params"] == {"expand": "body.storage"}
    assert payload["body"]["storage"]["value"] == "<p>Body</p>"


def test_confluence_client_get_page_content_handles_decode_error(monkeypatch):
    def fake_request(self, method, url, params=None, **kwargs):
        return DummyResponse(payload=None, ok=True, content=b"not-json")

    monkeypatch.setattr(requests.Session, "request", fake_request)

    client = ConfluenceClient({"api_url": "https://confluence.example.com/"})

    payload = client.get_page_content("123")

    assert payload["error"]["message"] == "Unable to decode Confluence response as JSON."


def test_tool_invoke_uses_defaults_and_fetches_page_content():
    tool = _load_tool()

    recorded = {}

    class DummyClient:
        site_url = "https://confluence.example.com/"

        def search_pages(self, query, limit=None, space_key=None, filters=None):
            recorded["query"] = query
            recorded["limit"] = limit
            recorded["space_key"] = space_key
            recorded["filters"] = filters
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

    assert recorded == {
        "query": "Dataiku",
        "limit": 5,
        "space_key": "AIEC",
        "filters": {"type": "page"},
    }
    assert len(response["results"]) == 1
    assert response["results"][0]["page_content"] == "<p>Content</p>"
    assert trace.outputs["results"][0]["url"].endswith("/display/AIEC/Dataiku")
    assert trace.attributes["config"]["filters"] == {"type": "page"}


def test_tool_invoke_surfaces_error_message():
    tool = _load_tool()

    class DummyClient:
        site_url = "https://confluence.example.com/"

        def search_pages(self, query, limit=None, space_key=None, filters=None):
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

    assert response["results"] == []
    assert response["output"] == "HTTP 400: cql query parameter is required"
    assert trace.attributes["search"]["attempts"] == ["failure"]


def test_tool_invoke_sanitizes_inputs():
    tool_instance = ConfluenceSearchPagesTool()
    tool_instance.config = {}

    captured = {}

    class DummyClient:
        site_url = "https://confluence.example.com/"

        def search_pages(self, query, limit=3, space_key=None, filters=None):
            captured["query"] = query
            captured["limit"] = limit
            captured["space_key"] = space_key
            captured["filters"] = filters
            return {"results": [], "source": "confluence", "attempts": []}

    tool_instance.client = DummyClient()

    trace = DummyTrace()

    result = tool_instance.invoke(
        {
            "input": {
                "query": "  trimmed  ",
                "space_key": "   ",
                "limit": "invalid",
                "type": "  BLOGPOST  ",
                "labels": " tag-one , tag-two ",
                "creator": "  user1  ",
                "contributor": "   ",
                "last_modified": "Last_Week",
                "order_by": "created asc",
            }
        },
        trace,
    )

    assert captured == {
        "query": "trimmed",
        "limit": 3,
        "space_key": None,
        "filters": {
            "type": "blogpost",
            "labels": ["tag-one", "tag-two"],
            "creator": "user1",
            "last_modified": "last_week",
            "order_by": "created_asc",
        },
    }
    assert trace.inputs["query"] == "trimmed"
    assert trace.inputs["limit"] == 3
    assert trace.inputs["space_key"] is None
    assert trace.attributes["config"]["filters"]["type"] == "blogpost"
    assert trace.outputs["results"] == []
    assert result["results"] == []
    assert result["output"] == "No Confluence pages matched your query."


def test_confluence_client_cloud_url_is_canonicalized_to_wiki_root():
    client = ConfluenceClient(
        {
            "server_type": "cloud",
            "api_url": "https://kpn.atlassian.net/wiki/spaces/AIEC/pages/109159581/GenAI+Gateway+Models",
            "username": "user@example.com",
            "token": "token",
        }
    )

    assert client.base_url == "https://kpn.atlassian.net/wiki"
    assert client.build_absolute_url("/spaces/AIEC/pages/109159581/GenAI+Gateway+Models") == (
        "https://kpn.atlassian.net/wiki/spaces/AIEC/pages/109159581/GenAI+Gateway+Models"
    )


def test_tool_invoke_can_disable_default_page_filter():
    tool_instance = ConfluenceSearchPagesTool()
    tool_instance.config = {"enforce_page_type": False}

    captured = {}

    class DummyClient:
        site_url = "https://kpn.atlassian.net/wiki/"

        def search_pages(self, query, limit=3, space_key=None, filters=None):
            captured["query"] = query
            captured["limit"] = limit
            captured["space_key"] = space_key
            captured["filters"] = filters
            return {"results": [], "source": "confluence", "attempts": []}

    tool_instance.client = DummyClient()

    trace = DummyTrace()
    result = tool_instance.invoke({"input": {"query": "model governance"}}, trace)

    assert captured["filters"] == {}
    assert trace.attributes["config"]["enforce_page_type"] is False
    assert result["results"] == []
    assert result["output"] == "No Confluence pages matched your query."
