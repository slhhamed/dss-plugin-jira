import logging
from collections import OrderedDict
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin

import requests


logger = logging.getLogger(__name__)


class ConfluenceClient:
    """Lightweight Confluence REST API helper focused on search."""

    def __init__(self, connection_details: Dict[str, Any]):
        logger.info("ConfluenceClient init")

        self.server_type = connection_details.get("server_type", "cloud")
        subdomain = connection_details.get("subdomain")
        api_url = (connection_details.get("api_url") or "").rstrip("/")

        if self.server_type == "cloud" and subdomain:
            base_url = f"https://{subdomain}.atlassian.net/wiki"
        else:
            base_url = api_url

        self.base_url = base_url.rstrip("/")
        self.site_url = f"{self.base_url}/" if self.base_url else ""
        self.verify = not connection_details.get("ignore_ssl_check", False)

        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self.session.verify = self.verify

        username = connection_details.get("username")
        password = connection_details.get("password")
        token = connection_details.get("token")

        if username and (password or token):
            self.session.auth = (username, password or token)
        elif token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

    # ------------------------------------------------------------------
    # REST helpers
    # ------------------------------------------------------------------
    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        return self.session.request(method, url, **kwargs)

    @staticmethod
    def _escape_cql_value(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        replacements = {
            "\\": "\\\\",
            '"': '\\"',
        }
        for original, escaped in replacements.items():
            text = text.replace(original, escaped)
        return text

    @staticmethod
    def _coerce_positive_int(value: Any, default: int = 3) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _normalise_space_key(self, space_key: Optional[str]) -> Optional[str]:
        if space_key is None:
            return None
        if isinstance(space_key, str):
            stripped = space_key.strip()
            return stripped or None
        return str(space_key).strip() or None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def search_pages(self, query: str, limit: int = 3, space_key: Optional[str] = None) -> Dict[str, Any]:
        attempts: List[str] = []

        limit_value = self._coerce_positive_int(limit, default=3)

        query_text = (query or "").strip()
        if query_text.endswith("?"):
            query_text = query_text[:-1].strip()

        cql_parts = ["type=page"]

        normalised_space = self._normalise_space_key(space_key)
        if normalised_space:
            escaped_space = self._escape_cql_value(normalised_space)
            cql_parts.append(f'space = "{escaped_space}"')

        if query_text:
            escaped_query = self._escape_cql_value(query_text)
            cql_parts.append(f'text ~ "{escaped_query}"')

        cql = " AND ".join(cql_parts) + " ORDER BY lastmodified DESC"
        attempts.append(f"CQL={cql}")

        url = f"{self.base_url}/rest/api/search"
        params = {"cql": cql, "limit": limit_value}
        attempts.append(f"GET {url}?{urlencode(params)}")

        try:
            response = self._request("GET", url, params=params)
        except requests.RequestException as exc:  # pragma: no cover - network failure
            message = f"Request failed: {exc}"
            return {
                "results": [],
                "error": {"message": message},
                "source": "confluence",
                "attempts": attempts,
                "message": message,
            }

            if version == "v2" and response.status_code in {404, 405}:
                attempt_record["error"] = "search endpoint unavailable"
                self._search_v2_supported = False
                attempts.append(attempt_record)
                continue

            if version == "v2" and response.status_code < 400:
                self._search_v2_supported = True

            if response.status_code >= 400:
                error_payload = self._safe_json(response)
                attempt_record["error"] = self._extract_error_message(error_payload, response.text)
                attempts.append(attempt_record)
                return {
                    "results": [],
                    "error": {
                        "message": attempt_record["error"],
                        "status_code": response.status_code,
                        "details": error_payload,
                    },
                    "attempts": attempts,
                    "source": version,
                    "message": attempt_record["error"],
                }

            try:
                payload = response.json()
            except ValueError:
                attempt_record["error"] = "invalid JSON response"
                attempts.append(attempt_record)
                return {
                    "results": [],
                    "error": {
                        "message": "Unexpected response from Confluence search endpoint.",
                        "status_code": response.status_code,
                        "details": response.text,
                    },
                    "attempts": attempts,
                    "source": version,
                }

            attempts.append(attempt_record)
            normalized_results = self._normalize_results(payload, version)
            return {
                "results": [],
                "error": {"message": message},
                "source": "confluence",
                "attempts": attempts,
                "message": message,
            }

        results = [self._normalise_result_entry(entry) for entry in payload.get("results", []) or []]

        return {
            "results": results,
            "source": "confluence",
            "attempts": attempts,
            "source": None,
            "message": "No supported Confluence search endpoint responded successfully.",
        }

    def get_page_content(self, page_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/rest/api/content/{page_id}"
        params = {"expand": "body.storage"}

        try:
            parsed = int(limit)
        except (TypeError, ValueError):
            return 3
        return parsed if parsed > 0 else 3

    @staticmethod
    def _normalize_query(query: Any) -> str:
        if query is None:
            return ""
        if isinstance(query, str):
            return query.strip()
        return str(query)

    @staticmethod
    def _normalize_space_key(space_key: Optional[str]) -> Optional[str]:
        if space_key is None:
            return None
        if isinstance(space_key, str):
            stripped = space_key.strip()
            return stripped or None
        text = str(space_key).strip()
        return text or None

    @staticmethod
    def _escape_cql_value(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        text = text.replace("\\", "\\\\")
        text = text.replace('"', '\\"')
        return text

    def _build_v2_payload(self, query: str, limit: int, space_key: Optional[str]) -> Dict[str, Any]:
        normalized_query = self._normalize_query(query)
        escaped_query = self._escape_cql_value(normalized_query)
        query_string = f'text ~ "{escaped_query}"'
        payload: Dict[str, Any] = {
            "queryString": query_string,
            "entityType": ["page"],
            "limit": limit,
            "sort": "modified_date DESC",
        }
        normalized_space = self._normalize_space_key(space_key)
        if normalized_space:
            payload["spaceKeys"] = [normalized_space]
        return payload

    def _build_v1_params(self, query: str, limit: int, space_key: Optional[str]) -> Dict[str, Any]:
        cql_parts = []
        if space_key:
            cql_parts.append(f'space="{space_key}"')
        cql_parts.append(f'text~"{query}"')
        cql_query = " AND ".join(cql_parts)
        return f"{cql_query} ORDER BY lastmodified DESC"

    def _compose_v1_cql_query(self, query: str, space_key: Optional[str]) -> str:
        """Build the Confluence Query Language string for v1 searches.

        Space scoping is embedded directly in the CQL so that on-premises
        instances honour the restriction instead of relying on a separate
        ``space`` query parameter, which the endpoint ignores.
        """

        cql_parts = []
        normalized_space = self._normalize_space_key(space_key)
        if normalized_space:
            escaped_space = self._escape_cql_value(normalized_space)
            cql_parts.append(f'space="{escaped_space}"')
        normalized_query = self._normalize_query(query)
        escaped_query = self._escape_cql_value(normalized_query)
        cql_parts.append(f'text~"{escaped_query}"')
        cql_query = " AND ".join(cql_parts)
        return f"{cql_query} ORDER BY lastmodified DESC"

    def _compose_v1_cql_query(self, query: str, space_key: Optional[str]) -> str:
        """Build the Confluence Query Language string for v1 searches.

        Space scoping is embedded directly in the CQL so that on-premises
        instances honour the restriction instead of relying on a separate
        ``space`` query parameter, which the endpoint ignores.
        """

        cql_parts = []
        normalized_space = self._normalize_space_key(space_key)
        if normalized_space:
            escaped_space = self._escape_cql_value(normalized_space)
            cql_parts.append(f'space="{escaped_space}"')
        normalized_query = self._normalize_query(query)
        escaped_query = self._escape_cql_value(normalized_query)
        cql_parts.append(f'text~"{escaped_query}"')
        cql_query = " AND ".join(cql_parts)
        return f"{cql_query} ORDER BY lastmodified DESC"

    def _search_endpoint_candidates(self) -> List[Dict[str, str]]:
        base_url = self.site_url
        candidates: List[Dict[str, str]] = []

        prefer_v2 = self.server_type == "cloud" and self._search_v2_supported is not False

        if prefer_v2:
            # Primary v2 endpoint relative to the configured site URL.
            v2_primary = urljoin(base_url, "api/v2/search")
            candidates.append({"version": "v2", "method": "POST", "url": v2_primary})

            # Some instances expose v2 under /wiki/api/v2/ even when the base URL
            # does not include /wiki/.
            v2_alt = urljoin(base_url, "wiki/api/v2/search")
            if v2_alt != v2_primary:
                candidates.append({"version": "v2", "method": "POST", "url": v2_alt})

        # Legacy v1 endpoint fallback.
        v1_url = urljoin(base_url, "rest/api/content/search")
        candidates.append({"version": "v1", "method": "GET", "url": v1_url})

        return candidates

    def _normalize_results(self, payload: Dict[str, Any], version: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for entry in payload.get("results", []) or []:
            normalized = self._normalize_entry(entry, version)
            results.append(normalized)
        return results

        try:
            return response.json() if response.content else {}
        except ValueError:
            return {"error": {"message": "Unable to decode Confluence response as JSON."}}

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------
    def _normalise_result_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        content = entry.get("content") if isinstance(entry.get("content"), dict) else {}

        page_id = str(entry.get("id") or content.get("id") or "")
        title = content.get("title") or entry.get("title") or "Untitled"

        links: Dict[str, Any] = {}
        if isinstance(entry.get("_links"), dict):
            links.update(entry["_links"])
        if isinstance(content.get("_links"), dict):
            links.update(content["_links"])

        link_path = (
            links.get("webui")
            or links.get("tinyui")
            or links.get("self")
            or entry.get("url")
        )

        absolute_url = None
        if isinstance(link_path, str) and link_path.startswith("http"):
            absolute_url = link_path
        elif isinstance(link_path, str) and self.site_url:
            absolute_url = urljoin(self.site_url, link_path.lstrip("/"))

        excerpt = entry.get("excerpt") or entry.get("excerptText") or content.get("excerpt")
        last_modified = (
            entry.get("lastModified")
            or entry.get("last_modified")
            or entry.get("modified")
            or content.get("lastModified")
            or content.get("lastModifiedDate")
            or (content.get("version", {}) if isinstance(content.get("version"), dict) else {}).get("when")
        )

        space_key = None
        if isinstance(entry.get("space"), dict):
            space_key = entry["space"].get("key")
        if not space_key and isinstance(content.get("space"), dict):
            space_key = content["space"].get("key")
        if not space_key and isinstance(entry.get("spaceKey"), str):
            space_key = entry.get("spaceKey")

        return {
            "id": page_id,
            "title": title,
            "url": absolute_url,
            "url_path": link_path if isinstance(link_path, str) else None,
            "excerpt": excerpt,
            "last_modified": last_modified,
            "space_key": space_key,
        }

    def _build_error_message(self, response: requests.Response) -> str:
        status = response.status_code

        detail: Optional[str] = None
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            detail = (
                payload.get("message")
                or payload.get("errorMessage")
                or ("; ".join(payload.get("errorMessages", [])) if payload.get("errorMessages") else None)
            )

        body_excerpt = response.text.strip()[:300] if response.text else ""
        detail = detail or body_excerpt or "Unexpected error from Confluence."
        return f"HTTP {status}: {detail}"

    # ------------------------------------------------------------------
    # Legacy helpers kept for other tools in the plugin
    # ------------------------------------------------------------------
    def create_page(self, title: str, content: str, space_key: str):
        url = f"{self.site_url}rest/api/content"
        data = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": content, "representation": "storage"}},
        }
        headers = {"Content-Type": "application/json"}
        response = self._request("POST", url, json=data, headers=headers)
        return response.json()

    def update_page(self, page_id: str, title: str, content: str):
        url = f"{self.site_url}rest/api/content/{page_id}"
        headers = {"Content-Type": "application/json"}
        current_page = self._request("GET", url, headers=headers).json()

        new_version = current_page.get("version", {}).get("number", 0) + 1

        data = {
            "id": page_id,
            "type": "page",
            "title": title,
            "body": {"storage": {"value": content, "representation": "storage"}},
            "version": {"number": new_version},
        }

        response = self._request("PUT", url, json=data, headers=headers)
        return response.json()
