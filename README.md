# Jira Plugin

This Dataiku DSS plugin provides read connectors and recipes to interact with [Jira Core](https://www.atlassian.com/software/jira/core), [Jira Software](https://www.atlassian.com/software/jira) and [Jira Service Desk](https://www.atlassian.com/software/jira/service-desk) accounts.

Documentation: https://www.dataiku.com/product/plugins/jira/

Repository guide for contributors and maintainers: docs/REPOSITORY_GUIDE.md

### Confluence Cloud Search Validation

When validating search-confluence-pages behavior after cloud migration:

1. Configure cloud connection with your Atlassian subdomain.
2. Set `search_mode` to `broad` for parity checks against Confluence UI.
3. Enable `include_debug_metadata` to inspect `effective_cql` and `request_preview_url`.
4. Run the same query manually in Confluence and compare scope/filter differences.
5. Switch to `strict_page` if you want page-only default behavior.

Additional search options:

1. Use multiple spaces with `space_key` as comma- or semicolon-separated values.
2. Example multi-space input: `BNA,AIEC` or `BNA;AIEC`.
3. Set `query_semantics` to `auto` to try phrase, then AND-terms, then OR-terms.
4. Tune `min_results_threshold` to control when auto fallback stops.


### Licence

This plugin is distributed under the Apache License version 2.0
