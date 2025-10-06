import json
import logging
from urllib.parse import urljoin

from dataiku.llm.agent_tools import BaseAgentTool

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
            "description": (
                "This tool searches Confluence pages using the provided keywords "
                "and returns up to the requested number of results with their URLs, "
                "titles, and page content."
            ),
            "inputSchema": {
                "$id": "https://dataiku.com/agents/tools/search/input",
                "title": "Search Confluence pages tool",
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for in Confluence pages",
                    },
                    "space_key": {
                        "type": "string",
                        "description": "Optional Confluence space key to restrict the search. Leave empty to search all spaces.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 3).",
                        "minimum": 1,
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        }

    @staticmethod
    def _sanitize_limit(value, default: int = 3) -> int:
        try:
            limit_value = int(value)
        except (TypeError, ValueError):
            return default
        return limit_value if limit_value > 0 else default

    def _normalize_space_key(self, space_key):
        if isinstance(space_key, str):
            stripped = space_key.strip()
            return stripped or None
        if space_key is None:
            return None
        text_value = str(space_key).strip()
        return text_value or None

    def search_pages(self, query: str, space_key: str = None, limit: int = 3):
        try:
            return self.client.search_pages(query, limit=limit, space_key=space_key)
        except Exception as exception:
            return {
                "results": [],
                "error": {
                    "message": f"Error searching pages: {str(exception)}",
                },
            }

    def invoke(self, input, trace):
        args = dict(input.get("input", {}))
        query_value = args.get("query", "")
        if isinstance(query_value, str):
            query = query_value.strip()
        elif query_value is None:
            query = ""
        else:
            query = str(query_value)
        space_key = self._normalize_space_key(args.get("space_key"))
        limit_value = self._sanitize_limit(args.get("limit", 3))

        confluence_instance_url = self.client.site_url or ""
        base_url = (
            f"{confluence_instance_url.rstrip('/')}/"
            if confluence_instance_url
            else ""
        )

        trace.span["name"] = "CONFLUENCE_SEARCH_PAGES_TOOL_CALL"
        trace_inputs = {
            "query": query,
            "limit": limit_value,
            "space_key": space_key,
        }
        trace.inputs.update(trace_inputs)
        trace.attributes["config"] = {
            "confluence_instance_url": confluence_instance_url,
            "limit": limit_value,
        }

        search_result = self.search_pages(query, space_key, limit_value)

        raw_results = []
        if isinstance(search_result, dict):
            raw_results = search_result.get("results") or []
            trace.attributes["search"] = {
                "source": search_result.get("source"),
                "attempts": search_result.get("attempts"),
                "space_key": space_key,
            }


        if isinstance(search_result, dict) and raw_results:
            items = []
            for item in raw_results[:limit_value]:
                title = item.get("title") or "Untitled"
                page_id = item.get("id") or None
                link = item.get("url")

                if not link:
                    link_path = item.get("url_path")
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

                page_content = ""
                if page_id:
                    try:
                        page_data = self.client.get_page_content(page_id)
                        page_content = (
                            page_data.get("body", {})
                            .get("storage", {})
                            .get("value", "")
                            if isinstance(page_data, dict)
                            else ""
                        )
                    except Exception as exception:  # pragma: no cover - network failure
                        page_content = f"Unable to load page content: {exception}"

                item_output = {
                    "url": link,
                    "title": title,
                    "page_content": page_content,
                }

                excerpt = item.get("excerpt")
                if excerpt:
                    item_output["excerpt"] = excerpt

                if item.get("last_modified"):
                    item_output["last_modified"] = item.get("last_modified")

                if item.get("space_key"):
                    item_output["space_key"] = item.get("space_key")

                if page_id:
                    item_output["page_id"] = page_id

                if link:
                    items.append(item_output)
            output_data = items if items else []
            output_text = json.dumps(output_data)
            trace.outputs["results"] = output_data
            return {"output": output_text, "results": output_data}

        if isinstance(search_result, dict):
            message = search_result.get("message")
            attempts = search_result.get("attempts", [])
            trace.attributes.setdefault("search", {})["attempts"] = attempts
            output_message = message or "No Confluence pages matched your query."
            trace.outputs["message"] = output_message
            trace.outputs["results"] = []
            return {"output": output_message, "results": []}
        else:
            message = None
            if isinstance(search_result, dict):
                message = search_result.get("error", {}).get("message")
            output_data = {
                "error": message or str(search_result)
            }

        trace.outputs["results"] = output_data

        return {"output": json.dumps(output_data), "results": output_data}
