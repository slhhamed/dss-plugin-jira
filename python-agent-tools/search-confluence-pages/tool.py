from dataiku.llm.agent_tools import BaseAgentTool
import json
import logging
from urllib.parse import urljoin
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
            "description": "This tool searches Confluence pages using the provided keywords and returns up to three results with their URLs, titles, and page content.",
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
        confluence_instance_url = self.client.site_url or ""
        base_url = (
            f"{confluence_instance_url.rstrip('/')}/"
            if confluence_instance_url
            else ""
        )

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

                link_path = None
                content_links = content.get("_links") if isinstance(content, dict) else None
                if isinstance(content_links, dict):
                    link_path = (
                        content_links.get("webui")
                        or content_links.get("tinyui")
                        or content_links.get("self")
                    )

                if not link_path:
                    item_links = item.get("_links") if isinstance(item, dict) else None
                    if isinstance(item_links, dict):
                        link_path = item_links.get("webui") or item_links.get("self")

                if not link_path and isinstance(content, dict):
                    link_path = content.get("url")

                if not link_path and isinstance(item, dict):
                    link_path = item.get("url")

                if link_path:
                    if base_url:
                        normalized_path = (
                            link_path.lstrip("/")
                            if isinstance(link_path, str) and link_path.startswith("/")
                            else link_path
                        )
                        link = urljoin(base_url, normalized_path)
                    else:
                        link = link_path
                elif page_id and base_url:
                    link = urljoin(base_url, f"pages/{page_id}")
                elif page_id:
                    link = f"pages/{page_id}"
                else:
                    link = base_url.rstrip("/") or None

                if page_id:
                    page_data = self.client.get_page_content(page_id)
                    page_content = (
                        page_data.get("body", {})
                        .get("storage", {})
                        .get("value", "")
                        if isinstance(page_data, dict)
                        else ""
                    )
                else:
                    page_content = ""

                if link:
                    items.append(
                        {
                            "url": link,
                            "title": title,
                            "page_content": page_content,
                        }
                    )
            output_data = items if items else []
        elif isinstance(search_result, dict) and search_result.get("message"):
            output_data = {
                "error": f"There was a problem while searching pages: {search_result.get('message')}"
            }
        else:
            output_data = {"error": str(search_result)}

        trace.outputs["results"] = output_data

        return {"output": json.dumps(output_data), "results": output_data}