# Jira Dataiku Plugin - Repository Guide

## 1. Project Overview

This repository contains a Dataiku DSS plugin that integrates with Atlassian services.

Confirmed capabilities in this codebase:
- Import data from Jira through a Dataiku connector.
- Enrich datasets from Jira endpoints through a custom Python recipe.
- Expose agent tools for:
  - Creating Jira issues.
  - Searching Confluence pages.
  - Creating Confluence pages.
  - Updating Confluence pages.

Primary plugin metadata:
- Plugin ID: jira
- Version: 1.1.1
- Label: Jira
- Author: Dataiku
- License: Apache Software License

Source references:
- _/plugin.json
- _/README.md
- _/CHANGELOG.md

## 2. Architecture and Structure

Top-level structure in this workspace:

- _/
  - Plugin packaging metadata and release files for Dataiku plugin distribution.
  - Contains plugin.json, Makefile, README.md, CHANGELOG.md.
- code-env/python/
  - Python runtime compatibility definition.
- parameter-sets/basic-auth/
  - Shared authentication configuration UI for cloud and on-prem Jira/Confluence access.
- python-connectors/jira/
  - Connector descriptor and implementation for Jira data import.
- custom-recipes/jira-services/
  - Recipe descriptor and implementation for dataset-driven Jira retrieval.
- python-agent-tools/
  - Agent tool descriptors and Python implementations.
- python-lib/
  - Shared clients and helper modules used by connector, recipe, and tools.
- tests/python/unit/
  - Unit tests for Jira issue creation and Confluence search behavior.

## 3. Core Components and Responsibilities

### 3.1 Shared library modules (python-lib)

- jira_api.py
  - Central endpoint descriptor registry for Jira Core, Jira Software, Jira Service Desk, and Opsgenie-related endpoints.
  - Stores URL templates, query parameter templates, response extraction keys, pagination settings, and status-code-specific messages.

- jira_client.py
  - Core Jira HTTP client used by connector/recipe/tools.
  - Handles:
    - Site URL selection for cloud vs on-prem.
    - Endpoint descriptor resolution and merge with defaults.
    - GET/POST request execution.
    - Pagination orchestration.
    - Response filtering and output shaping.
    - Jira issue creation with detailed error extraction.

- confluence_client.py
  - Confluence HTTP client used by Confluence agent tools.
  - Handles:
    - Base URL resolution for cloud vs on-prem.
    - Session authentication setup.
    - CQL query construction for search.
    - Search result normalization.
    - Page content fetch.
    - Page create/update operations.

- pagination.py
  - Reusable pagination state machine supporting both offset-based and next-link pagination styles.

- utils.py
  - Small utility helpers:
    - de_float_column for recipe dataframe normalization.
    - extract_data_with_json_path for nested key traversal.
    - get_connection_details for config extraction based on access type.

- web_search_client.py
  - Standalone DuckDuckGo search client present in repository.
  - Not wired to connector/recipe/tool manifests in this workspace snapshot.

### 3.2 Connector layer

- python-connectors/jira/connector.json
  - Declares a readable connector with many endpoint options and parameter UI behavior.

- python-connectors/jira/connector.py
  - Dataiku Connector subclass.
  - Initializes JiraClient from parameter-set credentials.
  - Streams rows by:
    - Calling an endpoint.
    - Yielding formatted results.
    - Following pagination until completion or record limit.

### 3.3 Recipe layer

- custom-recipes/jira-services/recipe.json
  - Declares one input dataset role and one output dataset role.
  - Expects an input column containing IDs or keys depending on selected endpoint.

- custom-recipes/jira-services/recipe.py
  - Reads input dataset as pandas dataframe.
  - Normalizes ID columns.
  - Calls JiraClient endpoint per input row.
  - Flattens and appends results.
  - Writes output dataset when data exists.

### 3.4 Agent tools layer

- create-issue
  - Wraps Jira issue creation and returns user-oriented success or error output.

- search-confluence-pages
  - Builds filters (space, type, labels, users, freshness, ordering, limit).
  - Executes Confluence search.
  - Fetches page content for returned pages.
  - Produces JSON output plus trace metadata.

- create-confluence-page
  - Creates a page in configured space key.

- update-confluence-page
  - Updates existing page by ID and increments version through Confluence API flow.

## 4. Data and Control Flow

### 4.1 Jira connector flow

1. Dataiku initializes JiraConnector with config.
2. JiraConnector builds JiraClient with resolved connection details.
3. JiraConnector calls client.start_session(endpoint_name).
4. JiraConnector calls client.get_endpoint(...).
5. JiraClient resolves endpoint descriptor from jira_api.py.
6. JiraClient executes HTTP request and parses response.
7. JiraClient filters data list/object based on configured return key.
8. JiraConnector yields formatted rows.
9. If pagination indicates next page, JiraConnector repeats using client.get_next_page().

### 4.2 Jira custom recipe flow

1. Recipe loads input dataset and config.
2. Recipe reads ID column and optional queue ID column.
3. For each input row, recipe calls JiraClient endpoint.
4. Recipe collects and formats records, preserving row context (jira_id and optional queue_id).
5. Recipe writes consolidated output dataframe to output dataset.

### 4.3 Jira issue creation tool flow

1. Tool receives summary and description.
2. Tool calls JiraClient.create_issue(project_key, summary, description, issue_type).
3. On success, tool returns created issue key and browse URL.
4. On failure, tool returns extracted Jira error details (errorMessages and field-level errors when present).

### 4.4 Confluence search tool flow

1. Tool merges defaults from configuration and runtime input.
2. Tool normalizes filters and builds a constrained request.
3. ConfluenceClient builds CQL and sends /rest/api/search request.
4. Tool enriches search results by retrieving page body content per page ID.
5. Tool returns structured results and trace details.

## 5. Notable Design Choices and Patterns

- Descriptor-driven endpoint behavior for Jira.
  - Most Jira endpoint differences are data-driven in jira_api.py rather than hardcoded branching in many places.

- Shared pagination abstraction.
  - One Pagination class supports multiple API pagination styles.

- Trace-first tool implementation style.
  - Agent tools set trace span names, inputs, outputs, and config attributes.

- Cloud and on-prem support in one parameter set.
  - Authentication and URL fields are controlled by visibility conditions in parameter-set definition.

- Defensive normalization in Confluence search.
  - Filter and ordering values are sanitized before query construction.

## 6. Dependencies and Runtime Requirements

### 6.1 Declared environment compatibility

From code-env/python/desc.json:
- Accepted interpreters: Python 3.6 to 3.12
- installCorePackages: true
- installJupyterSupport: false

### 6.2 Imported packages observed in code

Direct imports in repository Python files include:
- requests
- pandas
- numpy
- dataiku
- Standard library modules (json, logging, os, typing, urllib.parse, copy, etc.)

### 6.3 Important gap

The file code-env/python/spec/requirements.txt is present but empty in this workspace snapshot.
This means explicit pip dependency pinning is not provided here.

## 7. Setup and Installation (Inferred)

This repository is a Dataiku plugin source tree.
The packaging automation is under _/Makefile and expects _/plugin.json.

### 7.1 Build plugin archive

Run from the _ directory:

```bash
make plugin
```

Expected behavior:
- Validates plugin.json format.
- Creates dist/dss-plugin-<id>-<version>.zip.
- Adds release_info.json with git remote URL and commit ID.
- Removes tests from the archive.

### 7.2 Development archive build

Run from the _ directory:

```bash
make dev
```

Expected behavior:
- Builds plugin zip excluding tests and local env/cache folders.

### 7.3 Unit tests

Run from the _ directory:

```bash
make unit-tests
```

What Makefile attempts:
- Creates a local virtual environment at _/env.
- Installs test dependencies from tests/python/unit/requirements.txt.
- Installs runtime dependencies from code-env/python/spec/requirements.txt.
- Runs pytest on tests/python/unit.

Important workspace mismatch:
- tests/python/unit/requirements.txt is referenced by Makefile but is missing in this workspace snapshot.

### 7.4 Integration tests

Run from the _ directory:

```bash
make integration-tests
```

Important workspace mismatch:
- tests/python/integration/requirements.txt is referenced by Makefile but tests/python/integration is not present in this workspace snapshot.

## 8. How to Use in Dataiku DSS

High-level usage inferred from descriptors and code:

1. Install packaged plugin zip into Dataiku DSS.
2. Create a Jira connection using parameter set basic-auth:
   - Choose cloud or on-prem.
   - Fill required URL/subdomain and credentials.
3. Use one of the plugin surfaces:
   - Connector: pull Jira datasets from selected endpoint.
   - Recipe: enrich an input ID dataset with Jira API results.
   - Agent tools: configure in an agent to create/search/update Jira/Confluence artifacts.

## 9. Configuration Reference

### 9.1 Parameter set: basic-auth

Fields include:
- server_type: cloud or on_premise
- cloud mode:
  - subdomain
  - username
  - token
- on-prem mode:
  - api_url
  - username
  - token (password field)
  - ignore_ssl_check

### 9.2 Connector key parameters

- endpoint_name
- item_value (contextual meaning depends on endpoint)
- queue_id (for service desk queue issue endpoint)
- expand (for endpoints supporting expansion)
- token_access preset (basic-auth)

### 9.3 Recipe key parameters

- endpoint_name
- id_column_name
- queue_id_column_name (for service desk queue issue endpoint)
- expand
- token_access preset (basic-auth)

### 9.4 Agent tool parameters

- create-jira-issue:
  - jira_project_key
- search-confluence-pages:
  - space_key
  - search_mode (strict_page or broad)
  - type
  - enforce_page_type
  - labels
  - creator
  - contributor
  - last_modified
  - order_by
  - limit
  - include_debug_metadata
- create-confluence-page:
  - spaceKey
- update-confluence-page:
  - No extra mandatory config field beyond connection in tool.json

### 9.5 Confluence cloud and parity troubleshooting

For cloud migration and manual-vs-agent result comparison, the search-confluence-pages tool now supports:

- search_mode:
  - strict_page: keeps page-only default filtering behavior.
  - broad: does not force type=page unless type is explicitly provided.
- include_debug_metadata:
  - Adds effective_cql, request_preview_url, attempts, effective_filters, and search_mode in tool output.

Recommended troubleshooting workflow:

1. Enable include_debug_metadata.
2. Run the same query from the tool and manually in Confluence.
3. Compare effective_cql and request_preview_url from tool output with expected filters/sort/scope.
4. If needed, switch search_mode from strict_page to broad and compare again.

## 10. Test Coverage Snapshot

Unit tests currently present:
- tests/python/unit/test_create_issue_tool.py
  - Covers Jira issue creation error propagation.
- tests/python/unit/test_confluence_search_tool.py
  - Covers CQL construction, filter handling, request errors, and tool invoke behavior.

Not covered in current unit tests found here:
- Connector row streaming behavior.
- Recipe end-to-end behavior.
- Confluence create/update tool flows.
- Pagination class behavior in isolation.

## 11. Contributor Notes

For future maintainers:

1. Keep endpoint behavior centralized in python-lib/jira_api.py when adding Jira endpoints.
2. Keep JiraClient and ConfluenceClient focused on transport/normalization; place UI parameter behavior in descriptor JSON files.
3. Add or restore explicit dependency manifests:
   - code-env/python/spec/requirements.txt
   - tests/python/unit/requirements.txt
4. Align Makefile targets with actual repository layout to avoid broken local test commands.
5. Expand tests for connector and recipe paths, not only agent tools.

## 12. Known Unknowns and Incomplete Areas

The following are intentionally not assumed because evidence is missing in the workspace snapshot:

- Exact pip dependencies and versions (requirements file is empty).
- Working integration test suite content (referenced by Makefile but not present).
- Dataiku instance-specific deployment steps beyond standard plugin install workflow.
- Whether web_search_client.py is currently wired into any active plugin component.

This guide intentionally avoids filling these gaps with assumptions.
