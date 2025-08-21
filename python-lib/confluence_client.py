import requests
import logging
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

    def search_pages(self, query, limit=3):
        url = f"{self.site_url}rest/api/search"
        params = {"cql": f'text~"{query}"', "limit": limit}
        headers = {"Accept": "application/json"}
        response = requests.get(
            url,
            params=params,
            auth=(self.username, self.password),
            headers=headers,
            verify=not self.ignore_ssl_check,
        )
        return response.json()

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