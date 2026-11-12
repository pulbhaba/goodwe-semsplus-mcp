# GoodWe SEMS+ Australia MCP server

Read-only MCP tools for an AI agent to query GoodWe SEMS+ directly. No analytics
database or scheduled collector is included.

## What it exposes

- `test_connection`
- `get_live_energy_flow`
- `discover_devices`
- `get_device_telemetry`
- `get_device_energy_counters`
- `get_device_information`
- `get_historical_statistics`
- `get_historical_production`
- `get_station_chart`

The server preserves GoodWe's raw JSON values and adds readable summaries where
the SEMS+ field meanings are clear. Raw status codes, grid direction, units not
provided by SEMS+, and unknown fields are left uninterpreted.

## Readable results

- Live energy flow adds named power, household consumption and battery state
  fields. Grid power keeps GoodWe's sign, because this response does not say
  whether positive means import or export.
- Device telemetry and energy counters include a flattened `readings` list with
  clear names and the original units. The temperature reading is the inverter
  chamber temperature, not ambient or outdoor temperature.
- Device information includes readable field labels. Numeric status values stay
  raw where SEMS+ does not define their meanings.
- Historical statistics include `metric_series` with named energy series,
  GoodWe units and direction codes, plus `summary_metrics` with cautious labels
  for the portal's summary fields. Unspecified units and status meanings stay
  marked as unspecified.
- Historical production includes `energy_summary` and `income_summary` while
  retaining raw data. `profitProStats` is total generation income;
  `profitGridStats` is income from energy fed to the grid.

## Historical and chart data

The historical tool follows the observed SEMS+ web portal request to
`/sems-plant/api/stations/statistics`, including its POST body and statistics
item list. GoodWe's APIs are undocumented and responses may vary by account or
region. Raw response fields remain available alongside the labeled series and
summary metrics. Treat unspecified units and meanings as unknown; do not use
unverified fields for financial or billing claims.

`get_historical_production` queries the portal's separate
`/sems-plant/api/stations/production` endpoint with a daily dimension. You can
select a subset of its known energy and income `items`; if omitted, the usual
set is requested. The MCP preserves the raw response and adds an
`income_summary` with clear names: `profitProStats` is total generation income,
and `profitGridStats` is income from energy fed to the grid. Verify amounts
against your retailer statement before treating them as settled income.

`get_historical_statistics` also accepts an optional `items` list; by default
it requests the known statistics series. `get_station_chart` queries the
observed `compare/station/chart` route. It accepts multiple station IDs and
metric descriptors, plus a reporting period, dimension and portal-local time
range. Candidate values are listed in `openapi.yaml`; valid combinations depend
on GoodWe's limits. In particular, a year reporting period with hourly
dimension is too large and is rejected. Use a coarser dimension or a shorter
range. Chart response data is kept raw because its shape varies by request.

The live flow, device list, device telemetry, telecounting and information
endpoints are based on observed SEMS+ gateway routes. SEMS+ APIs are undocumented
and may change.

## Setup

1. Find the station ID from the SEMS+ station page URL or the station detail page.
2. Install Python 3.11+ and the server into a project-local virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
if [ ! -f .env ]; then cp .env.example .env; fi
```

Edit `.env` with your SEMS+ credentials and station ID if you have not already.
Keep this file private.

3. Register the installed command with Codex CLI:

```bash
codex mcp add goodwe-semsplus \
  --env GOODWE_ENV_FILE="$(pwd)/.env" \
  -- "$(pwd)/.venv/bin/goodwe-semsplus-mcp"
codex mcp list
```

Codex will launch the server over stdio. Restart Codex after registering it;
the GoodWe tools will then be available in Codex sessions. The environment file
path is stored in Codex configuration, while the SEMS+ credentials stay in
`.env`. See the [Codex MCP guide](https://developers.openai.com/codex/mcp/) for
other configuration options.

To remove the server later, run `codex mcp remove goodwe-semsplus`.

To run the MCP server manually for local development:

```bash
.venv/bin/python -m goodwe_mcp.server
```

The default transport is stdio. Use an MCP inspector/client to test the tools.
Never paste credentials or tokens into prompts or commit `.env`.

For a remote Streamable HTTP listener, set:

```env
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=8000
```

This sample listener does not implement OAuth or bearer-token authentication.
Do not expose it directly to the internet. Put it behind an authenticated TLS
reverse proxy or an MCP-compatible secure tunnel before connecting ChatGPT.

## ChatGPT connection

ChatGPT custom MCP connections require a reachable remote HTTPS MCP endpoint
(or supported Secure MCP Tunnel), and availability depends on ChatGPT plan and
workspace settings. Current OpenAI help states custom MCP server connections
and full MCP support are available to Business and Enterprise/Edu workspaces;
Pro supports read/fetch connections in developer mode. A standard Free account
cannot be assumed to support custom MCP connections.

For the OpenAI API Responses API, a remote MCP server can be passed as an MCP
tool using `server_url`. See:
https://developers.openai.com/api/docs/guides/tools-connectors-mcp

Do not expose a local stdio server directly to the internet. For self-hosting,
deploy behind TLS with authentication, or use Secure MCP Tunnel where supported.
The sample is intentionally local/stdio and does not include public unauthenticated
HTTP serving.

## GoodWe API notes

- Login host: `https://{region}-semsplus.goodwe.com`
- Login path: `/web/sems/sems-user/api/v1/auth/cross-login`
- Login uses the `semsPlusWeb` token header and the account/password,
  agreement, and locale fields expected by the web portal. API calls use the
  same regional host under `/web/sems`.
- Historical station statistics use `POST /sems-plant/api/stations/statistics`
  with `stationId`, `isReport`, `items`, `dimension`, `startTime`, and
  `endTime` in the JSON body.
- Historical production and profit metrics use
  `POST /sems-plant/api/stations/production` with a daily dimension and an
  inclusive start/end time range.
- Station charts use `POST https://au-gateway.semsportal.com/sems/sems-report/api/v2/compare/station/chart`.
- Station flow: `/sems-plant/api/stations/flow?stationId=...`
- Device list: `/sems-plant/api/web/device/station/getDevicesByType`
- Device telemetry: `/sems-plant/api/equipments/{sn}/telemetry`
- Device counters: `/sems-plant/api/equipments/{sn}/telecounting`
- Device information: `/sems-plant/api/equipments/{sn}/information`

The SEMS APIs are undocumented and may change. If login fails, verify the
request contract against a sanitized request from the current GoodWe app.

## Security

- Use a dedicated read-only SEMS+ account if GoodWe supports it.
- Keep credentials in environment variables or a secret manager.
- Use HTTPS and authentication for any remote MCP deployment.
- Do not expose remote-control/write endpoints.
- Restrict MCP access to your own agent.
- GoodWe's official API products may require an organization account, license
  agreement or device whitelist; a household SEMS+ login is not the same thing.
