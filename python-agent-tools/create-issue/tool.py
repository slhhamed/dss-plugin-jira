from dataiku.llm.agent_tools import BaseAgentTool
import logging
from jira_client import JiraClient, JiraIssueCreationError
from utils import get_connection_details


class JiraCreateIssueTool(BaseAgentTool):
    def set_config(self, config, plugin_config):
        # This logger outputs the key in DEBUG mode ...
        logging.getLogger("jiraapiclient.discovery").setLevel("INFO")
        logging.info("JiraCreateIssueTool init")
        self.config = config
        connection_details = get_connection_details(config)
        self.client = JiraClient(connection_details)
        self.client.start_session("issue")
        self.jira_project_key = config.get("jira_project_key")

    def get_descriptor(self, tool):
        return {
            "description": "This tool is a wrapper around atlassian-python-api's Jira issue_create API, useful when you need to create a Jira issue. The input to this tool is a dictionary containing the new issue summary and description, e.g. '{'summary':'new issue summary', 'description':'new issue description'}'",
            "inputSchema": {
                "$id": "https://dataiku.com/agents/tools/search/input",
                "title": "Create Jira issue tool",
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "The issue summary"
                    },
                    "description": {
                        "type": "string",
                        "description": "The issue description"
                    }
                },
                "required": ["summary", "description"]
            }
        }

    def create_jira_issue(self, summary: str, description: str, issue_type: str = "Task"):
        try:
            new_issue = self.client.create_issue(self.jira_project_key, summary, description, issue_type)
            return {"success": True, "issue": new_issue}

        except JiraIssueCreationError as exception:
            error_messages = exception.error_messages or []
            errors = exception.errors or {}

            detailed_messages = []
            if errors:
                detailed_messages.extend(
                    f"{field}: {message}" for field, message in errors.items() if message
                )
            if not detailed_messages and error_messages:
                detailed_messages.extend(error_messages)
            if not detailed_messages:
                detailed_messages.append(str(exception))

            human_message = "; ".join(detailed_messages)

            return {
                "success": False,
                "error": {
                    "message": human_message,
                    "status_code": exception.status_code,
                    "errorMessages": error_messages,
                    "errors": errors,
                }
            }

        except Exception as exception:
            return {
                "success": False,
                "error": {
                    "message": f"Error creating issue: {str(exception)}"
                }
            }

    def invoke(self, input, trace):
        args = input.get("input", {})

        summary = args.get("summary")
        description = args.get("description")
        jira_instance_url = self.client.get_site_url()

        # Log inputs and config to trace
        trace.span["name"] = "JIRA_CREATE_ISSUE_TOOL_CALL"
        for key, value in args.items():
            trace.inputs[key] = value
        trace.attributes["config"] = {
            "jira_instance_url": jira_instance_url,
            "jira_project_key": self.jira_project_key
        }

        creation_result = self.create_jira_issue(summary, description)

        if creation_result.get("success"):
            issue = creation_result.get("issue", {})
            output_text = (
                f"Issue created: {issue.get('key')} available at {jira_instance_url}browse/{issue.get('key')}"
            )
            trace.outputs["issue"] = issue
        else:
            error_info = creation_result.get("error", {})
            error_message = error_info.get("message", "Unknown error while creating the issue")
            output_text = (
                "There was a problem while creating the issue ticket: {}".format(error_message)
            )
            trace.outputs["error"] = error_info

        # Log outputs to trace
        trace.outputs["output"] = output_text

        return {
            "output": output_text
        }
