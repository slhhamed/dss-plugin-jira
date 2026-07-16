import json
import logging
from urllib.parse import urljoin

from dataiku.llm.agent_tools import BaseAgentTool

from utils import get_connection_details
from confluence_client import ConfluenceClient


class ConfluenceSearchPagesTool(BaseAgentTool):
    def set_config(self, config, plugin_config):
        logging.getLogger("confluence_client").setLevel("INFO")
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
                    "type": {
                        "type": "string",
                        "description": "Optional Confluence content type filter (e.g. page, blogpost, attachment). Leave empty to search pages only.",
                    },
                    "search_mode": {
                        "type": "string",
                        "enum": ["strict_page", "broad"],
                        "description": "strict_page keeps page-only default behavior; broad does not force type=page unless type is explicitly provided.",
                    },
                    "enforce_page_type": {
                        "type": "boolean",
                        "description": "Legacy override for page-only default behavior. true maps to strict_page, false maps to broad.",
                    },
                    "labels": {
                        "type": "string",
                        "description": "Comma-separated Confluence labels to filter results (e.g. docs,how-to).",
                    },
                    "creator": {
                        "type": "string",
                        "description": "Filter by creator username or account identifier.",
                    },
                    "contributor": {
                        "type": "string",
                        "description": "Filter by contributor username or account identifier.",
                    },
                    "last_modified": {
                        "type": "string",
                        "enum": [
                            "today",
                            "yesterday",
                            "last_week",
                            "last_4_weeks",
                            "last_3_months",
                            "last_year",
                        ],
                        "description": "Limit results to pages updated within the selected timeframe.",
                    },
                    "order_by": {
                        "type": "string",
                        "enum": [
                            "lastmodified_desc",
                            "lastmodified_asc",
                            "created_desc",
                            "created_asc",
                            "title_asc",
                            "title_desc",
                        ],
                        "description": "Sort order for results (default: lastmodified_desc).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 3).",
                        "minimum": 1,
                        "default": 3,
                    },
                    "include_debug_metadata": {
                        "type": "boolean",
                        "description": "When true, include effective CQL and request attempts in tool output for troubleshooting.",
                        "default": False,
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

    @staticmethod
    def _coerce_bool(value, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return default

    def _normalize_space_key(self, space_key):
        if isinstance(space_key, str):
            stripped = space_key.strip()
            return stripped or None
        if space_key is None:
            return None
        text_value = str(space_key).strip()
        return text_value or None

    @staticmethod
    def _normalize_text(value):
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalize_labels(labels):
        if labels is None:
            return []
        if isinstance(labels, str):
            raw_items = labels.replace(";", ",").split(",")
        elif isinstance(labels, (list, tuple, set)):
            raw_items = labels
        else:
            raw_items = [labels]

        normalized = []
        for item in raw_items:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized

    @staticmethod
    def _normalize_last_modified(value):
        if value is None:
            return None
        text = str(value).strip().lower().replace("-", "_")
        if not text:
            return None
        allowed = {
            "today",
            "yesterday",
            "last_week",
            "last_4_weeks",
            "last_3_months",
            "last_year",
        }
        return text if text in allowed else None

    @staticmethod
    def _normalize_order_by(value):
        if value is None:
            return "lastmodified_desc"
        text = str(value).strip().lower().replace(" ", "_")
        if not text:
            return "lastmodified_desc"
        mapping = {
            "lastmodified": "lastmodified_desc",
            "lastmodified_desc": "lastmodified_desc",
            "lastmodified_asc": "lastmodified_asc",
            "created": "created_desc",
            "created_desc": "created_desc",
            "created_asc": "created_asc",
            "title": "title_asc",
            "title_asc": "title_asc",
            "title_desc": "title_desc",
        }
        return mapping.get(text, "lastmodified_desc")

    @staticmethod
    def _normalize_search_mode(value):
        if value is None:
            return None
        text = str(value).strip().lower().replace("-", "_")
        if text in {"strict_page", "strict"}:
            return "strict_page"
        if text in {"broad", "all"}:
            return "broad"
        return None

    def search_pages(self, query: str, space_key: str = None, limit: int = 3):
        try:
            filters = getattr(self, "_current_filters", {})
            return self.client.search_pages(
                query, limit=limit, space_key=space_key, filters=filters
            )
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
        default_space = None
        if hasattr(self, "config") and isinstance(getattr(self, "config"), dict):
            default_space = self.config.get("space_key")
        space_key = self._normalize_space_key(
            args.get("space_key") or default_space
        )
        default_limit = 3
        if hasattr(self, "config") and isinstance(getattr(self, "config"), dict):
            default_limit = self.config.get("limit", 3)
        limit_value = self._sanitize_limit(
            args.get("limit", default_limit), default=default_limit
        )
        include_debug_metadata = False
        if isinstance(getattr(self, "config", None), dict):
            include_debug_metadata = self._coerce_bool(
                self.config.get("include_debug_metadata", False), default=False
            )
        if "include_debug_metadata" in args:
            include_debug_metadata = self._coerce_bool(
                args.get("include_debug_metadata"), default=include_debug_metadata
            )

        enforce_page_type = True
        search_mode = None
        filters = {}
        if isinstance(getattr(self, "config", None), dict):
            search_mode = self._normalize_search_mode(self.config.get("search_mode"))
            enforce_page_type = self._coerce_bool(
                self.config.get("enforce_page_type", True), default=True
            )

            if search_mode == "strict_page":
                enforce_page_type = True
            elif search_mode == "broad":
                enforce_page_type = False

            if enforce_page_type:
                filters["type"] = "page"

            default_type = self._normalize_text(
                self.config.get("type") or self.config.get("content_type")
            )
            if default_type:
                filters["type"] = default_type.lower()

            default_labels = self._normalize_labels(self.config.get("labels"))
            if default_labels:
                filters["labels"] = default_labels

            default_creator = self._normalize_text(self.config.get("creator"))
            if default_creator:
                filters["creator"] = default_creator

            default_contributor = self._normalize_text(self.config.get("contributor"))
            if default_contributor:
                filters["contributor"] = default_contributor

            default_last_modified = self._normalize_last_modified(
                self.config.get("last_modified")
            )
            if default_last_modified:
                filters["last_modified"] = default_last_modified

            if "order_by" in self.config:
                default_order = self._normalize_order_by(self.config.get("order_by"))
                if default_order:
                    filters["order_by"] = default_order

        runtime_search_mode = self._normalize_search_mode(args.get("search_mode"))
        if runtime_search_mode is not None:
            search_mode = runtime_search_mode
            if search_mode == "strict_page":
                enforce_page_type = True
            elif search_mode == "broad":
                enforce_page_type = False

            if enforce_page_type and "type" not in filters:
                filters["type"] = "page"
            if not enforce_page_type and "type" not in args and filters.get("type") == "page":
                filters.pop("type", None)

        if "enforce_page_type" in args:
            enforce_page_type = self._coerce_bool(args.get("enforce_page_type"), default=enforce_page_type)
            search_mode = "strict_page" if enforce_page_type else "broad"
            if enforce_page_type and "type" not in filters:
                filters["type"] = "page"
            if not enforce_page_type and "type" not in args and filters.get("type") == "page":
                filters.pop("type", None)

        if "type" in args:
            type_value = self._normalize_text(args.get("type"))
            if type_value:
                filters["type"] = type_value.lower()
            elif enforce_page_type:
                filters["type"] = "page"
            else:
                filters.pop("type", None)

        if "labels" in args:
            labels_value = self._normalize_labels(args.get("labels"))
            if labels_value:
                filters["labels"] = labels_value
            elif "labels" in filters:
                filters.pop("labels")

        if "creator" in args:
            creator_value = self._normalize_text(args.get("creator"))
            if creator_value:
                filters["creator"] = creator_value
            elif "creator" in filters:
                filters.pop("creator")

        if "contributor" in args:
            contributor_value = self._normalize_text(args.get("contributor"))
            if contributor_value:
                filters["contributor"] = contributor_value
            elif "contributor" in filters:
                filters.pop("contributor")

        if "last_modified" in args:
            last_modified_value = self._normalize_last_modified(args.get("last_modified"))
            if last_modified_value:
                filters["last_modified"] = last_modified_value
            elif "last_modified" in filters:
                filters.pop("last_modified")

        if "order_by" in args:
            order_value = self._normalize_order_by(args.get("order_by"))
            if order_value:
                filters["order_by"] = order_value

        if search_mode is None:
            search_mode = "strict_page" if enforce_page_type else "broad"
        filters["search_mode"] = search_mode

        self._current_filters = filters

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
            "space_key": space_key,
            "filters": filters,
            "enforce_page_type": enforce_page_type,
            "search_mode": search_mode,
            "include_debug_metadata": include_debug_metadata,
        }

        search_result = self.search_pages(query, space_key, limit_value)

        raw_results = []
        if isinstance(search_result, dict):
            raw_results = search_result.get("results") or []
            attempts = search_result.get("attempts", [])
            effective_cql = None
            request_preview_url = None
            if attempts and isinstance(attempts[0], str) and attempts[0].startswith("CQL="):
                effective_cql = attempts[0][4:]
            if len(attempts) > 1 and isinstance(attempts[1], str) and attempts[1].startswith("GET "):
                request_preview_url = attempts[1][4:]
            trace.attributes["search"] = {
                "source": search_result.get("source"),
                "attempts": attempts,
                "space_key": space_key,
                "filters": filters,
                "effective_cql": effective_cql,
                "request_preview_url": request_preview_url,
            }
            trace.outputs["search_attempts"] = attempts
            trace.outputs["effective_cql"] = effective_cql
            trace.outputs["request_preview_url"] = request_preview_url


        if isinstance(search_result, dict) and raw_results:
            items = []
            for item in raw_results[:limit_value]:
                title = item.get("title") or "Untitled"
                page_id = item.get("id") or None
                link = item.get("url")

                if not link:
                    link_path = item.get("url_path")
                    if link_path:
                        if hasattr(self.client, "build_absolute_url"):
                            link = self.client.build_absolute_url(link_path)
                        elif base_url:
                            link = urljoin(base_url, link_path)
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

                items.append(item_output)
            output_data = items if items else []
            output_text = json.dumps(output_data)
            trace.outputs["results"] = output_data
            response = {"output": output_text, "results": output_data}
            if include_debug_metadata:
                response["debug"] = {
                    "attempts": search_result.get("attempts", []),
                    "effective_cql": trace.outputs.get("effective_cql"),
                    "request_preview_url": trace.outputs.get("request_preview_url"),
                    "effective_filters": filters,
                    "search_mode": search_mode,
                }
            return response

        if isinstance(search_result, dict):
            message = search_result.get("message")
            attempts = search_result.get("attempts", [])
            trace.attributes.setdefault("search", {})["attempts"] = attempts
            error_info = search_result.get("error") if isinstance(search_result.get("error"), dict) else {}
            if not message and error_info:
                message = error_info.get("message")
            output_message = message or "No Confluence pages matched your query."
            trace.outputs["message"] = output_message
            trace.outputs["results"] = []
            response = {"output": output_message, "results": []}
            if include_debug_metadata:
                response["debug"] = {
                    "attempts": attempts,
                    "effective_cql": trace.outputs.get("effective_cql"),
                    "request_preview_url": trace.outputs.get("request_preview_url"),
                    "effective_filters": filters,
                    "search_mode": search_mode,
                }
            return response
        else:
            message = None
            if isinstance(search_result, dict):
                message = search_result.get("error", {}).get("message")
            output_data = {
                "error": message or str(search_result)
            }

        trace.outputs["results"] = output_data
        response = {"output": json.dumps(output_data), "results": output_data}
        if include_debug_metadata:
            response["debug"] = {
                "attempts": [],
                "effective_cql": trace.outputs.get("effective_cql"),
                "request_preview_url": trace.outputs.get("request_preview_url"),
                "effective_filters": filters,
                "search_mode": search_mode,
            }
        return response
