import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

from jira_client import normalize_url

logger = logging.getLogger(__name__)


class ConfluenceClient(object):
    CONFLUENCE_SITE_URL = "https://{subdomain}.atlassian.net/wiki"

    def __init__(self, connection_details):
        logger.info("ConfluenceClient init")
        self.server_type = connection_details.get("server_type", "cloud")
        self.subdomain = connection_details.get("subdomain")
        self.api_url = normalize_url(connection_details.get("api_url", ""))
        self.username = connection_details.get("username", "")
        self.password = connection_details.get("token", "")
        self.ignore_ssl_check = connection_details.get("ignore_ssl_check", False)
        self.site_url = self.get_site_url()
        # Track whether the v2 search endpoint is available to avoid retrying
        # known-missing URLs on every invocation. The value remains ``None``
        # until we successfully call v2 (True) or receive a definitive 404/405
        # (False).
        self._search_v2_supported: Optional[bool] = None

    def get_site_url(self):
        if self.server_type == "cloud":
            return normalize_url(self.CONFLUENCE_SITE_URL.format(subdomain=self.subdomain))
        else:
            return normalize_url(self.api_url)

    def create_page(self, title, content, space_key):
        url = f"{self.site_url}rest/api/content"
        data = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {"value": content, "representation": "storage"}
            },
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        response = requests.post(
            url,
            json=data,
            auth=(self.username, self.password),
            headers=headers,
            verify=not self.ignore_ssl_check,
        )
        return response.json()

    def search_pages(self, query, limit=3, space_key=None):
        """Search Confluence pages preferring the REST API v2 endpoint.

        Falls back to the legacy v1 search endpoint when v2 is unavailable
        (e.g., older Confluence Data Center versions that return 404/405).
        The response contains normalized result entries along with metadata
        describing which endpoint succeeded and any intermediate errors.
        """

        sanitized_limit = self._sanitize_limit(limit)
        payload_v2 = self._build_v2_payload(query=query, limit=sanitized_limit, space_key=space_key)
        cql_params = self._build_v1_params(query=query, limit=sanitized_limit, space_key=space_key)

        attempts: List[Dict[str, Any]] = []
        headers_v2 = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        headers_v1 = {"Accept": "application/json"}

        for endpoint in self._search_endpoint_candidates():
            version = endpoint["version"]
            url = endpoint["url"]
            method = endpoint["method"]

            try:
                if version == "v2":
                    response = requests.post(
                        url,
                        json=payload_v2,
                        auth=(self.username, self.password),
                        headers=headers_v2,
                        verify=not self.ignore_ssl_check,
                    )
                else:
                    response = requests.get(
                        url,
                        params=cql_params,
                        auth=(self.username, self.password),
                        headers=headers_v1,
                        verify=not self.ignore_ssl_check,
                    )
            except requests.RequestException as exc:  # pragma: no cover - network failure
                attempts.append(
                    {
                        "version": version,
                        "method": method,
                        "url": url,
                        "status_code": None,
                        "error": str(exc),
                    }
                )
                continue

            attempt_record = {
                "version": version,
                "method": method,
                "url": url,
                "status_code": response.status_code,
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
                "results": normalized_results,
                "raw": payload,
                "attempts": attempts,
                "source": version,
            }

        return {
            "results": [],
            "error": {
                "message": "No supported Confluence search endpoint responded successfully.",
                "status_code": None,
                "details": attempts,
            },
            "attempts": attempts,
            "source": None,
        }

    def _sanitize_limit(self, limit: Optional[int]) -> int:
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
        normalized_space = self._normalize_space_key(space_key)
        cql_query = self._compose_v1_cql_query(query=query, space_key=normalized_space)
        return {"cql": cql_query, "limit": limit}

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

    def _normalize_entry(self, entry: Dict[str, Any], version: str) -> Dict[str, Any]:
        content = entry.get("content") if isinstance(entry, dict) else None
        if not isinstance(content, dict):
            content = {}

        page_id = str(content.get("id") or entry.get("id") or "")
        title = content.get("title") or entry.get("title") or "Untitled"

        links = {}
        if isinstance(content.get("_links"), dict):
            links.update(content["_links"])
        if isinstance(entry.get("_links"), dict):
            links.update(entry["_links"])

        link_path = (
            links.get("webui")
            or links.get("tinyui")
            or links.get("self")
            or entry.get("url")
        )
        full_url = self._build_full_url(link_path)

        excerpt = entry.get("excerpt") or content.get("excerpt") or ""
        last_modified = (
            entry.get("modified")
            or entry.get("lastModified")
            or content.get("lastModifiedDate")
            or content.get("version", {}).get("when")
        )

        space_key = None
        if isinstance(content.get("space"), dict):
            space_key = content.get("space", {}).get("key")
        if not space_key and isinstance(entry.get("space"), dict):
            space_key = entry.get("space", {}).get("key")
        if not space_key and isinstance(entry.get("spaceKey"), str):
            space_key = entry.get("spaceKey")

        return {
            "id": page_id,
            "title": title,
            "url": full_url,
            "url_path": link_path,
            "excerpt": excerpt,
            "last_modified": last_modified,
            "space_key": space_key,
            "raw": entry,
            "version": version,
        }

    def _build_full_url(self, link_path: Optional[str]) -> Optional[str]:
        if not link_path:
            return None
        if isinstance(link_path, str) and link_path.startswith("http"):
            return link_path

        if not isinstance(link_path, str):
            return None

        base_url = self.site_url.rstrip("/") + "/"
        normalized_path = link_path.lstrip("/")
        return urljoin(base_url, normalized_path)

    @staticmethod
    def _safe_json(response) -> Optional[Any]:
        try:
            return response.json()
        except ValueError:
            return response.text

    @staticmethod
    def _extract_error_message(payload: Any, fallback_text: str) -> str:
        if isinstance(payload, dict):
            message = payload.get("message")
            if message:
                return message
            if "errorMessage" in payload:
                return payload["errorMessage"]
            if "errorMessages" in payload and payload["errorMessages"]:
                return "; ".join(payload["errorMessages"])
            if "errors" in payload and isinstance(payload["errors"], dict):
                parts = [
                    f"{field}: {value}"
                    for field, value in payload["errors"].items()
                    if value
                ]
                if parts:
                    return "; ".join(parts)
        return fallback_text

    def get_page_content(self, page_id):
        url = f"{self.site_url}rest/api/content/{page_id}"
        params = {"expand": "body.storage"}
        headers = {"Accept": "application/json"}
        response = requests.get(
            url,
            params=params,
            auth=(self.username, self.password),
            headers=headers,
            verify=not self.ignore_ssl_check,
        )
        return response.json()

    def update_page(self, page_id, title, content):
        url = f"{self.site_url}rest/api/content/{page_id}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        current_page = requests.get(
            url,
            auth=(self.username, self.password),
            headers=headers,
            verify=not self.ignore_ssl_check,
        ).json()

        version_number = current_page.get("version", {}).get("number", 1) + 1

        data = {
            "id": page_id,
            "type": "page",
            "title": title,
            "version": {"number": version_number},
            "body": {
                "storage": {"value": content, "representation": "storage"},
            },
        }

        response = requests.put(
            url,
            json=data,
            auth=(self.username, self.password),
            headers=headers,
            verify=not self.ignore_ssl_check,
        )
        return response.json()
