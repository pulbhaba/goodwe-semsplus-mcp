---
name: semsplus-tool-change
description: Use when adding, changing, or debugging this project's GoodWe SEMS+ MCP tools, upstream requests, field mappings, units, historical metrics, or chart data.
---

# Change GoodWe SEMS+ tools

Use this workflow to keep MCP contracts aligned with observed SEMS+ behavior
and to preserve uncertainty in GoodWe's undocumented API.

## Workflow

1. **Read the current contract.** Read the relevant sections of `README.md`,
   `openapi.yaml`, `goodwe_mcp/server.py`, `goodwe_mcp/sems.py`, and
   `goodwe_mcp/config.py`. Trace the selected MCP tool through its client method
   to the upstream route. Finish when the inputs, response shape, and request
   contract relevant to the change are clear.

2. **Establish evidence.** Treat GoodWe's SEMS+ web APIs as undocumented. Base
   changes to request fields, response labels, units, signs, and status codes on
   observed portal behavior or sanitized request/response examples. Keep
   unknown meanings explicitly unknown; never infer grid direction, billing
   value, or status semantics from a field name alone. Finish when each new or
   changed interpretation has evidence, or is represented as raw/unspecified.

3. **Change the request path.** For a new upstream operation, add an async
   method to `SemsPlusClient` in `goodwe_mcp/sems.py` and route it through the
   existing authenticated request helper. Add or update the MCP tool and input
   validation in `goodwe_mcp/server.py`. Keep the server read-only. Finish when
   the tool reaches the intended route with validated inputs and preserves the
   upstream response.

4. **Preserve response data.** Keep the raw SEMS+ response available whenever
   adding readable labels or summaries. Preserve returned values, units, and
   signs. Mark unclear units or definitions as unspecified, and keep raw status
   codes where meanings are not established. Finish when the added summary
   introduces no unsupported interpretation.

5. **Update references.** Update `README.md` for user-visible tool behavior and
   `openapi.yaml` for observed endpoint shapes or candidate values. Keep
   `openapi.yaml` identified as an observed reference, not an official GoodWe
   specification. Finish when the docs describe the implementation and its
   evidence limits.

6. **Validate and review.** Check the repository for available tests or
   validation commands, and use the project-local `.venv` for Python tooling.
   Run checks appropriate to the task and report exactly what ran. Review the
   final diff for leaked credentials, changed raw values, unsupported labels,
   and stale docs. Finish when the review finds no mismatch between the tool,
   its upstream request, and the documented contract.

## Credential handling

Use sanitized examples for request analysis. Keep `.env`, passwords, tokens,
signatures, and authenticated headers out of source, logs, examples, and
commits. Never add an upstream write or remote-control operation as part of a
read-only data tool.
