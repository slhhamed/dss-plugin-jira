from dataiku.llm.agent_tools import BaseAgentTool
import logging
from utils import get_connection_details
from confluence_client import ConfluenceClient


class ConfluenceSearchPagesTool(BaseAgentTool):
    def set_config(self, config, plugin_config):
        logging.getLogger("jiraapiclient.discovery").setLevel("INFO")
        logging.info("ConfluenceSearchPagesTool init")
        self.config = config
        connection_details = get_connection_details(config)
        self.client = ConfluenceClient(connection_details)

    def get_descriptor(self, tool):
        return {
            "description": "This tool searches Confluence pages using the provided keywords and returns the first three results.",
            "inputSchema": {
                "$id": "https://dataiku.com/agents/tools/search/input",
                "title": "Search Confluence pages tool",
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for in Confluence pages",
                    }
                },
                "required": ["query"],
            },
        }

    def search_pages(self, query: str):
        try:
            return self.client.search_pages(query, limit=3)
        except Exception as exception:
            return f"Error searching pages: {str(exception)}"

    def invoke(self, input, trace):
        args = input.get("input", {})
        query = args.get("query")
        confluence_instance_url = self.client.site_url

        trace.span["name"] = "CONFLUENCE_SEARCH_PAGES_TOOL_CALL"
        for key, value in args.items():
            trace.inputs[key] = value
        trace.attributes["config"] = {
            "confluence_instance_url": confluence_instance_url,
        }

        search_result = self.search_pages(query)

        if isinstance(search_result, dict) and search_result.get("results"):
            items = []
            for item in search_result.get("results", [])[:3]:
                content = item.get("content", {})
                title = content.get("title", "Untitled")
                page_id = content.get("id")
                if page_id:
                    link = f"{confluence_instance_url}pages/{page_id}"
                    items.append(f"{title}: {link}")
            output_text = "\n".join(items) if items else "No pages found."
        elif isinstance(search_result, dict) and search_result.get("message"):
            output_text = f"There was a problem while searching pages: {search_result.get('message')}"
        else:
            output_text = str(search_result)

        trace.outputs["output"] = output_text

        return {"output": output_text}
