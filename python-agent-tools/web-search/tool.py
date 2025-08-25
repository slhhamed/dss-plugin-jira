from dataiku.llm.agent_tools import BaseAgentTool
import json
import logging
from web_search_client import WebSearchClient


class WebSearchTool(BaseAgentTool):
    def set_config(self, config, plugin_config):
        logging.getLogger("jiraapiclient.discovery").setLevel("INFO")
        logging.info("WebSearchTool init")
        self.client = WebSearchClient()

    def get_descriptor(self, tool):
        return {
            "description": "This tool searches the web using the provided keywords and returns up to three results with their URLs and titles.",
            "inputSchema": {
                "$id": "https://dataiku.com/agents/tools/web-search/input",
                "title": "Web search tool",
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for on the web",
                    }
                },
                "required": ["query"],
            },
        }

    def invoke(self, input, trace):
        args = input.get("input", {})
        query = args.get("query")

        trace.span["name"] = "WEB_SEARCH_TOOL_CALL"
        for key, value in args.items():
            trace.inputs[key] = value

        try:
            results = self.client.search(query, limit=3)
            trace.outputs["results"] = results
            output_data = results
        except Exception as exception:
            error = f"Error performing web search: {str(exception)}"
            trace.outputs["error"] = error
            output_data = {"error": error}

        return {"output": json.dumps(output_data), "results": output_data}
