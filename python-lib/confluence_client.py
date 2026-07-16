import logging
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import requests


logger = logging.getLogger(__name__)


class ConfluenceClient:
    """Lightweight Confluence REST API helper focused on search."""

    def __init__(self, connection_details: Dict[str, Any]):
        logger.info("ConfluenceClient init")

        self.server_type = connection_details.get("server_type", "cloud")
        subdomain = connection_details.get("subdomain")
        api_url = connection_details.get("api_url") or ""

        base_url = self._derive_base_url(self.server_type, subdomain, api_url)

        self.base_url = base_url.rstrip("/")
        self.site_url = f"{self.base_url}/" if self.base_url else ""
        self.verify = not connection_details.get("ignore_ssl_check", False)

        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self.session.verify = self.verify

        username = connection_details.get("username")
        password = connection_details.get("password")
        token = connection_details.get("token")

        # Prefer Basic if username+password provided; otherwise Bearer if only token provided
        if username and (password or token):
            self.session.auth = (username, password or token)
        elif token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

    @staticmethod
    def _derive_base_url(server_type: str, subdomain: Optional[str], api_url: str) -> str:
        api_url = str(api_url or "").strip()
        if api_url:
            parsed = urlparse(api_url)
            if parsed.scheme and parsed.netloc:
                # For Atlassian cloud links, canonicalize to host/wiki root.
                if parsed.netloc.endswith("atlassian.net"):
                    return f"{parsed.scheme}://{parsed.netloc}/wiki"
                if server_type == "cloud" and "/wiki" in (parsed.path or ""):
                    return urlunparse((parsed.scheme, parsed.netloc, "/wiki", "", "", ""))
                return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
            return api_url.rstrip("/")

        if server_type == "cloud" and subdomain:
            return f"https://{subdomain}.atlassian.net/wiki"

        return ""

    def _origin_url(self) -> str:
        parsed = urlparse(self.base_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return ""

    def build_absolute_url(self, link_path: Any) -> Optional[str]:
        if not isinstance(link_path, str) or not link_path:
            return None
        if link_path.startswith("http://") or link_path.startswith("https://"):
            return link_path

        origin = self._origin_url()
        if not origin:
            return None

        # Atlassian cloud often returns /spaces/... or /wiki/... paths.
        if self.base_url.endswith("atlassian.net/wiki") or self.base_url.endswith("atlassian.net/wiki/"):
            if link_path.startswith("/wiki/"):
                return f"{origin}{link_path}"
            if link_path.startswith("/"):
                return f"{origin}/wiki{link_path}"
            return f"{origin}/wiki/{link_path.lstrip('/')}"

        if link_path.startswith("/"):
            return f"{origin}{link_path}"
        return urljoin(self.site_url, link_path)

    # ---------------------------- internal helpers ----------------------------

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        return self.session.request(method, url, **kwargs)

    @staticmethod
    def _escape_cql_value(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        # escape backslash and double quotes
        text = text.replace("\\", "\\\\").replace('"', '\\"')
        return text

    @staticmethod
    def _normalize_query(query: Any) -> str:
        if query is None:
            return ""
        return query.strip() if isinstance(query, str) else str(query).strip()

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
    def _coerce_positive_int(value: Any, default: int = 3) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _normalize_labels(labels: Any) -> List[str]:
        if labels is None:
            return []
        if isinstance(labels, str):
            raw_items: Iterable[str] = labels.replace(";", ",").split(",")
        elif isinstance(labels, Iterable):
            raw_items = labels  # type: ignore[assignment]
        else:
            raw_items = [str(labels)]

        normalized: List[str] = []
        for item in raw_items:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized

    @staticmethod
    def _normalize_user_reference(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalize_order_by(value: Any) -> str:
        if value is None:
            return "lastmodified DESC"

        text = str(value).strip()
        if not text:
            return "lastmodified DESC"

        normalized = text.lower().replace("-", "_")
        shorthand_map = {
            "last_modified": "lastmodified DESC",
            "last_modified_desc": "lastmodified DESC",
            "last_modified_asc": "lastmodified ASC",
            "lastmodified": "lastmodified DESC",
            "lastmodified_desc": "lastmodified DESC",
            "lastmodified_asc": "lastmodified ASC",
            "created": "created DESC",
            "created_desc": "created DESC",
            "created_asc": "created ASC",
            "title": "title ASC",
            "title_asc": "title ASC",
            "title_desc": "title DESC",
        }

        if normalized in shorthand_map:
            return shorthand_map[normalized]

        tokens = text.split()
        if tokens:
            field = tokens[0].lower()
            direction = tokens[1].upper() if len(tokens) > 1 else "DESC"
            if field in {"lastmodified", "created", "title"} and direction in {"ASC", "DESC"}:
                return f"{field} {direction}"

        return "lastmodified DESC"

    @staticmethod
    def _normalize_last_modified(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip().lower().replace("-", "_")
        if not text:
            return None

        mapping = {
            "today": "lastmodified >= startOfDay()",
            "yesterday": "lastmodified >= startOfDay(-1d)",
            "last_week": "lastmodified >= startOfDay(-7d)",
            "last_4_weeks": "lastmodified >= startOfDay(-28d)",
            "last_four_weeks": "lastmodified >= startOfDay(-28d)",
            "last_month": "lastmodified >= startOfDay(-31d)",
            "last_3_months": "lastmodified >= startOfDay(-12w)",
            "last_three_months": "lastmodified >= startOfDay(-12w)",
            "last_year": "lastmodified >= startOfDay(-52w)",
            "past_day": "lastmodified >= startOfDay(-1d)",
            "past_week": "lastmodified >= startOfDay(-7d)",
            "past_month": "lastmodified >= startOfDay(-31d)",
        }

        return mapping.get(text)

    # ------------------------------- public API --------------------------------

    def search_pages(
        self,
        query: str,
        limit: int = 3,
        space_key: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        attempts: List[str] = []

        limit_value = self._coerce_positive_int(limit, default=3)

        qtext = self._normalize_query(query)
        if qtext.endswith("?"):
            qtext = qtext[:-1].strip()

        filters = dict(filters or {})

        search_mode_raw = filters.get("search_mode")
        search_mode = None
        if search_mode_raw is not None:
            normalized_mode = str(search_mode_raw).strip().lower().replace("-", "_")
            if normalized_mode in {"strict_page", "strict"}:
                search_mode = "strict_page"
            elif normalized_mode in {"broad", "all"}:
                search_mode = "broad"

        content_type = filters.get("type")
        if content_type is None:
            cql_parts = [] if search_mode == "broad" else ["type = \"page\""]
        else:
            content_type_text = str(content_type).strip()
            if not content_type_text:
                cql_parts = [] if search_mode == "broad" else ["type = \"page\""]
            elif content_type_text.lower() == "page":
                cql_parts = ["type = \"page\""]
            else:
                cql_parts = [f'type = "{self._escape_cql_value(content_type_text)}"']

        if space_key := self._normalize_space_key(space_key):
            cql_parts.append(f'space = "{self._escape_cql_value(space_key)}"')

        labels = self._normalize_labels(filters.get("labels"))
        for label in labels:
            cql_parts.append(f'label = "{self._escape_cql_value(label)}"')

        creator = self._normalize_user_reference(filters.get("creator"))
        if creator:
            cql_parts.append(f'creator = "{self._escape_cql_value(creator)}"')

        contributor = self._normalize_user_reference(filters.get("contributor"))
        if contributor:
            cql_parts.append(f'contributor = "{self._escape_cql_value(contributor)}"')

        last_modified_clause = self._normalize_last_modified(filters.get("last_modified"))
        if last_modified_clause:
            cql_parts.append(last_modified_clause)

        if qtext:
            cql_parts.append(f'text ~ "{self._escape_cql_value(qtext)}"')

        order_by_clause = self._normalize_order_by(filters.get("order_by"))

        if not cql_parts:
            cql_parts = ["type = \"page\""]

        cql = " AND ".join(cql_parts)
        if order_by_clause:
            cql = f"{cql} ORDER BY {order_by_clause}"
        attempts.append(f"CQL={cql}")

        url = f"{self.base_url}/rest/api/search"
        params = {"cql": cql, "limit": limit_value}
        attempts.append(f"GET {url}?{urlencode(params)}")

        try:
            resp = self._request("GET", url, params=params)
        except requests.RequestException as exc:
            message = f"Request failed: {exc}"
            return {
                "results": [],
                "error": {"message": message},
                "source": "confluence",
                "attempts": attempts,
                "message": message,
            }

        if not resp.ok:
            message = self._build_error_message(resp)
            return {
                "results": [],
                "error": {"message": message},
                "source": "confluence",
                "attempts": attempts,
                "message": message,
            }

        try:
            payload = resp.json() if resp.content else {}
        except ValueError:
            message = "Unable to decode Confluence response as JSON."
            return {
                "results": [],
                "error": {"message": message},
                "source": "confluence",
                "attempts": attempts,
                "message": message,
            }

        raw_items = payload.get("results") or []
        results = [self._normalise_result_entry(entry) for entry in raw_items]
        return {"results": results[:limit_value], "source": "confluence", "attempts": attempts}

    def get_page_content(self, page_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/rest/api/content/{page_id}"
        params = {"expand": "body.storage"}
        resp = self._request("GET", url, params=params)
        if not resp.ok:
            return {"error": {"message": self._build_error_message(resp)}}
        try:
            return resp.json() if resp.content else {}
        except ValueError:
            return {"error": {"message": "Unable to decode Confluence response as JSON."}}

    # --------------------------- normalisation helpers --------------------------

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

        absolute_url = self.build_absolute_url(link_path)

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

    # ---------------- legacy helpers retained for other plugin features --------

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
