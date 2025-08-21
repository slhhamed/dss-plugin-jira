from dataiku.llm.agent_tools import BaseAgentTool
import logging
from utils import get_connection_details
from confluence_client import ConfluenceClient


class ConfluenceCreatePageTool(BaseAgentTool):
    def set_config(self, config, plugin_config):
        logging.getLogger("jiraapiclient.discovery").setLevel("INFO")
        logging.info("ConfluenceCreatePageTool init")
        self.config = config
        connection_details = get_connection_details(config)
        self.client = ConfluenceClient(connection_details)

    def get_descriptor(self, tool):
        return {
            "description": "This tool creates a Confluence page in space 'Testagent'. The input must contain the page title and content.",
            "inputSchema": {
                "$id": "https://dataiku.com/agents/tools/search/input",
                "title": "Create Confluence page tool",
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The page title",
                    },
                    "content": {
                        "type": "string",
                        "description": "The page content in Confluence storage format",
                    },
                },
                "required": ["title", "content"],
            },
        }

    def create_confluence_page(self, title: str, content: str):
        try:
            new_page = self.client.create_page(title, content)
            return new_page
        except Exception as exception:
            return f"Error creating page: {str(exception)}"

    def invoke(self, input, trace):
        args = input.get("input", {})
        title = args.get("title")
        content = args.get("content")
        confluence_instance_url = self.client.site_url

        trace.span["name"] = "CONFLUENCE_CREATE_PAGE_TOOL_CALL"
        for key, value in args.items():
            trace.inputs[key] = value
        trace.attributes["config"] = {
            "confluence_instance_url": confluence_instance_url,
            "space_key": "Testagent",
        }

        created_page = self.create_confluence_page(title, content)

        if isinstance(created_page, dict) and created_page.get("id"):
            output_text = (
                f"Page created: {created_page.get('id')} available at {confluence_instance_url}pages/{created_page.get('id')}"
            )
        elif isinstance(created_page, dict) and created_page.get("message"):
            output_text = f"There was a problem while creating the page: {created_page.get('message')}"
        else:
            output_text = str(created_page)

        trace.outputs["output"] = output_text

        return {"output": output_text}
