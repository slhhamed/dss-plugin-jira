import sys
import types
from pathlib import Path

import pytest


# Ensure plugin modules can be imported during tests
ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.append(str(ROOT_DIR / "python-lib"))
sys.path.append(str(ROOT_DIR / "python-agent-tools" / "create-issue"))


# Provide a minimal stub for the Dataiku BaseAgentTool dependency
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
    sys.modules["requests"] = requests_module

if "numpy" not in sys.modules:
    numpy_module = types.ModuleType("numpy")
    numpy_module.float64 = float
    numpy_module.nan = float("nan")
    sys.modules["numpy"] = numpy_module

import jira_client
from jira_client import JiraClient, JiraIssueCreationError
from tool import JiraCreateIssueTool


class DummyTrace:
    def __init__(self):
        self.span = {}
        self.inputs = {}
        self.outputs = {}
        self.attributes = {}


class DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = "Response text"

    def json(self):
        return self._payload


def test_create_issue_raises_error_with_error_messages(monkeypatch):
    client = JiraClient({
        "subdomain": "example",
        "username": "user",
        "token": "token",
        "server_type": "cloud"
    })

    def fake_post(self, url, data=None, json=None, params=None):
        return DummyResponse(400, {"errorMessages": ["Summary is required."]})

    monkeypatch.setattr(JiraClient, "post", fake_post, raising=False)

    with pytest.raises(JiraIssueCreationError) as excinfo:
        client.create_issue("TEST", "", "A description", "Task")

    assert excinfo.value.error_messages == ["Summary is required."]
    assert excinfo.value.errors == {}


def test_tool_invoke_surfaces_error_messages():
    class DummyClient:
        def __init__(self):
            self._site_url = "https://example.atlassian.net/"

        def create_issue(self, project_key, summary, description, issue_type):
            raise JiraIssueCreationError(400, error_messages=["Summary is required."])

        def get_site_url(self):
            return self._site_url

    tool_instance = JiraCreateIssueTool()
    tool_instance.client = DummyClient()
    tool_instance.jira_project_key = "TEST"

    trace = DummyTrace()

    result = tool_instance.invoke({"input": {"summary": "", "description": "Missing summary"}}, trace)

    assert "Summary is required." in result["output"]
    assert trace.outputs["error"]["message"] == "Summary is required."
