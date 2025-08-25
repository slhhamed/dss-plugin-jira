from dataiku.llm.agent_tools import BaseAgentTool
import logging
from utils import get_connection_details
from confluence_client import ConfluenceClient


class ConfluenceUpdatePageTool(BaseAgentTool):
    def set_config(self, config, plugin_config):
        logging.getLogger("jiraapiclient.discovery").setLevel("INFO")
        logging.info("ConfluenceUpdatePageTool init")
        self.config = config
        connection_details = get_connection_details(config)
        self.client = ConfluenceClient(connection_details)

    def get_descriptor(self, tool):
        return {
            "description": "This tool updates a Confluence page identified by its ID using the provided title and content.",
            "inputSchema": {
                "$id": "https://dataiku.com/agents/tools/update/input",
                "title": "Update Confluence page tool",
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "The ID of the page to update",
                    },
                    "title": {
                        "type": "string",
                        "description": "The new page title",
                    },
                    "content": {
                        "type": "string",
                        "description": "The page content in Confluence storage format",
                    },
                },
                "required": ["page_id", "title", "content"],
            },
        }

    def update_confluence_page(self, page_id: str, title: str, content: str):
        try:
            return self.client.update_page(page_id, title, content)
        except Exception as exception:
            return f"Error updating page: {str(exception)}"

    def invoke(self, input, trace):
        args = input.get("input", {})
        page_id = args.get("page_id")
        title = args.get("title")
        content = args.get("content")
        confluence_instance_url = self.client.site_url

        trace.span["name"] = "CONFLUENCE_UPDATE_PAGE_TOOL_CALL"
        for key, value in args.items():
            trace.inputs[key] = value
        trace.attributes["config"] = {
            "confluence_instance_url": confluence_instance_url,
        }

        updated_page = self.update_confluence_page(page_id, title, content)

        if isinstance(updated_page, dict) and updated_page.get("id"):
            output_text = (
                f"Page updated: {updated_page.get('id')} available at {confluence_instance_url}pages/{updated_page.get('id')}"
            )
        elif isinstance(updated_page, dict) and updated_page.get("message"):
            output_text = f"There was a problem while updating the page: {updated_page.get('message')}"
        else:
            output_text = str(updated_page)

        trace.outputs["output"] = output_text

        return {"output": output_text}
