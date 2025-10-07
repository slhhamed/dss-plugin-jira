import logging
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
        # Newlines in CQL fragments can break parsing, normalise them to spaces
        text = text.replace("\r", " ").replace("\n", " ")
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

        if not response.ok:
            message = self._build_error_message(response)
            return {
                "results": [],
                "error": {"message": message},
                "source": "confluence",
                "attempts": attempts,
                "message": message,
            }

        try:
            payload = response.json() if response.content else {}
        except ValueError:
            message = "Unable to decode Confluence response as JSON."
            return {
                "results": [],
                "error": {"message": message},
                "source": "confluence",
                "attempts": attempts,
                "message": message,
            }

        results: List[Dict[str, Any]] = []
        raw_entries = payload.get("results") or []
        for index, entry in enumerate(raw_entries):
            if isinstance(entry, dict):
                results.append(self._normalise_result_entry(entry))
            else:
                attempts.append(f"Skipped non-dict search entry at index {index}")

        return {
            "results": results,
            "source": "confluence",
            "attempts": attempts,
        }

    def get_page_content(self, page_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/rest/api/content/{page_id}"
        params = {"expand": "body.storage"}

        try:
            response = self._request("GET", url, params=params)
        except requests.RequestException as exc:  # pragma: no cover - network failure
            return {"error": {"message": f"Request failed: {exc}"}}

        if not response.ok:
            return {"error": {"message": self._build_error_message(response)}}

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
