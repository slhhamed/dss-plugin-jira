import requests
import logging

logger = logging.getLogger(__name__)


class WebSearchClient(object):
    """Client to perform web searches using the DuckDuckGo Instant Answer API."""

    SEARCH_URL = "https://api.duckduckgo.com/"

    def __init__(self):
        logger.info("WebSearchClient init")

    def search(self, query, limit=3):
        """Search the web and return a list of results with URL and title."""
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }
        response = requests.get(self.SEARCH_URL, params=params)
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("Results", []):
            url = item.get("FirstURL")
            title = item.get("Text")
            if url and title:
                results.append({"url": url, "title": title})
            if len(results) >= limit:
                break
        if len(results) < limit:
            for topic in data.get("RelatedTopics", []):
                if len(results) >= limit:
                    break
                url = topic.get("FirstURL")
                title = topic.get("Text")
                if url and title:
                    results.append({"url": url, "title": title})
                for sub in topic.get("Topics", []):
                    if len(results) >= limit:
                        break
                    url = sub.get("FirstURL")
                    title = sub.get("Text")
                    if url and title:
                        results.append({"url": url, "title": title})
        return results[:limit]
