import json
import logging
from datetime import date, datetime
from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .sems import PRODUCTION_ITEMS, STATISTICS_ITEMS, SemsPlusClient, GoodWeError

logging.basicConfig(level=logging.INFO)
settings = Settings()
client = SemsPlusClient(settings)
mcp = FastMCP("GoodWe SEMS+ Australia", host=settings.mcp_host, port=settings.mcp_port)

def _station(station_id: Optional[str]) -> str:
    return station_id or settings.goodwe_station_id


_SECTION_LABELS = {
    "system": "System",
    "ac": "AC output",
    "backup": "Backup output",
    "pv": "PV inputs",
}
_COUNTER_SECTION_LABELS = {
    "telecounting_real": "Current readings",
    "telecounting_today": "Today",
    "telecounting_week": "This week",
    "telecounting_month": "This month",
    "telecounting_year": "This year",
    "telecounting_lifetime": "Lifetime totals",
}
_TELEMETRY_LABELS = {
    "sn": "Serial number",
    "Temperature": "Inverter chamber temperature",
    "hTotal": "Total operating hours",
    "pAc": "AC active power",
    "qAc": "AC reactive power",
    "Vac": "AC voltage",
    "Iac": "AC current",
    "Fac": "Grid frequency",
    "pBackup": "Backup output power",
    "vBackupPhA": "Backup phase A voltage",
    "aBackupPhA": "Backup phase A current",
    "pDc": "Total PV DC input power",
    "ISOLimit": "Insulation resistance",
}
_COUNTER_LABELS = {
    "pAc": "Current AC power",
    "ratedPower": "Rated power",
    "proPvStatsToday": "Solar energy generated today",
    "proPvStatsWeek": "Solar energy generated this week",
    "proPvStatsMonth": "Solar energy generated this month",
    "proPvStatsYear": "Solar energy generated this year",
    "proPvStatsTotal": "Total solar energy generated",
    "proCharStatsToday": "Battery charge energy today",
    "proCharStatsWeek": "Battery charge energy this week",
    "proCharStatsMonth": "Battery charge energy this month",
    "proCharStatsYear": "Battery charge energy this year",
    "proCharStatsTotal": "Total battery charge energy",
    "proDischarStatsToday": "Battery discharge energy today",
    "proDischarStatsWeek": "Battery discharge energy this week",
    "proDischarStatsMonth": "Battery discharge energy this month",
    "proDischarStatsYear": "Battery discharge energy this year",
    "proDischarStatsTotal": "Total battery discharge energy",
}
_INFO_LABELS = {
    "gridConnStu": "Grid connection state code (meaning not specified)",
    "updateTime": "Information last updated",
    "picture": "Device image category",
    "deviceName": "Device name",
    "sn": "Serial number",
    "deviceType": "Device type",
    "status": "Device status code (meaning not specified)",
    "modelType": "Model",
    "addTime": "Added to SEMS+ at",
    "remark": "Note",
    "safetyVersion": "Safety firmware version",
    "ratedPower": "Rated power",
    "bat1MRSn": "Battery 1 serial number",
    "bat2MRSn": "Battery 2 serial number",
    "isHems": "HEMS enabled flag (0 or 1)",
}
_STATISTIC_LABELS = {
    "proSystemTotalStats": "Total system generation",
    "proConsumStats": "Energy consumption",
    "proCharStats": "Battery charge energy",
    "proDischarStats": "Battery discharge energy",
    "proGridStats": "Energy fed to the grid",
    "proPurchaseStats": "Energy purchased from the grid",
    "proSelfConsumStats": "Self-consumed PV energy",
}
_STATISTICS_SUMMARY_LABELS = {
    "production": "Production summary (definition and unit not specified)",
    "proSelfConsum": "Self-consumption (unit not specified)",
    "proSelfConsumRate": "Self-consumption rate",
    "proGrid": "Grid-fed energy (unit not specified)",
    "proGridRate": "Grid-fed rate",
    "proConsum": "Energy consumption (unit not specified)",
    "contributionRate": "Contribution rate",
    "proPurchase": "Grid-purchased energy (unit not specified)",
    "proPurchaseRate": "Grid-purchase rate",
    "proDiesel": "Diesel contribution (unit not specified)",
    "proDieselRate": "Diesel contribution rate",
    "proDieselLoad": "Diesel load (unit not specified)",
    "proPurchaseLoad": "Grid-purchase load (unit not specified)",
    "proPurchaseLoadRate": "Grid-purchase load rate",
    "proPvStoreContribution": "PV-to-storage contribution (unit not specified)",
    "proAcTotal": "Total AC output (unit not specified)",
    "hasProfit": "Profit data available",
}


class StationChartMetric(BaseModel):
    """A chart metric descriptor as accepted by the SEMS+ chart endpoint."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    metric_type: Literal["real_time", "stats"] = Field(alias="metricType")
    metric: Literal[
        "soc",
        "proSystemTotalStats",
        "proCharStats",
        "proDischarStats",
        "pBat",
        "pGrid",
        "pSystem",
    ]
    unit: Literal["%", "kW", "kWh"]


def _readings(sections: object, labels: dict[str, str], *, section_labels=None) -> list[dict]:
    """Flatten GoodWe factor groups into labeled readings while retaining raw data separately."""
    result = []
    if not isinstance(sections, list):
        return result
    section_labels = section_labels or {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        for factor in section.get("factors", []) or []:
            if not isinstance(factor, dict):
                continue
            code = str(factor.get("code", ""))
            label = labels.get(code)
            if label is None and code.startswith("MPPT-") and ":" in code:
                tracker, metric = code.split(":", 1)
                metric_labels = {
                    "Ppv": "PV power",
                    "Vpv": "PV voltage",
                    "Ipv": "PV current",
                }
                label = f"{tracker.replace('-', ' ')} {metric_labels.get(metric, metric)}"
            if label is None:
                alias = factor.get("alias")
                label = str(alias).replace("_", " ").capitalize() if alias else code
            reading = {
                "section": section_labels.get(section.get("code"), section.get("alias", section.get("code"))),
                "code": factor.get("code"),
                "label": label,
                "value": factor.get("data"),
            }
            if factor.get("unit") is not None:
                reading["unit"] = factor["unit"]
            result.append(reading)
    return result


def _mapped_records(data: object, fields: dict[str, str], *, include_currency: bool = False):
    """Give raw production metrics readable names, preserving their returned values."""
    records = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    mapped = [
        {
            **{label: record.get(code) for code, label in fields.items()},
            **({"currency": record.get("currency")} if include_currency else {}),
        }
        for record in records
        if isinstance(record, dict)
    ]
    return mapped[0] if isinstance(data, dict) else mapped

@mcp.tool()
async def test_connection() -> dict:
    """Authenticate to the Australian GoodWe SEMS+ account and verify the session."""
    return await client.login()

@mcp.tool()
async def get_live_energy_flow(station_id: Optional[str] = None) -> dict:
    """Get live system, grid, household and battery flow from SEMS+.

    The named flow_summary uses kW for power and percent for battery charge.
    Grid power is returned with GoodWe's sign unchanged; the response does not
    identify whether a positive value means import or export.
    """
    sid = _station(station_id)
    data = await client.live_flow(sid)
    return {
        "station_id": sid,
        "source": "SEMS+ stations/flow",
        "data": data,
        "flow_summary": {
            "system_power_kw": data.get("pSystem"),
            "inverter_ac_power_kw": data.get("pAc"),
            "battery_power_kw": data.get("pBat"),
            "grid_power_kw_sign_as_reported": data.get("pGrid"),
            "household_consumption_kw": data.get("pConsum"),
            "battery_state_of_charge_percent": data.get("soc"),
            "refreshed_at": data.get("refreshTime"),
        },
        "note": "Grid power direction is not specified by this SEMS+ response; the original pGrid value is preserved.",
    }

@mcp.tool()
async def discover_devices(station_id: Optional[str] = None) -> dict:
    """List device records visible to this station, grouped by GoodWe device type.

    Device status values are returned as raw GoodWe codes because their meaning
    is not provided consistently by the SEMS+ response.
    """
    sid = _station(station_id)
    return {
        "station_id": sid,
        "devices": await client.discover_common_devices(sid),
        "device_type_guide": {
            "INVERTER": "Standalone inverter",
            "ENERGY_STORAGE_INTEGRATED_CABINET": "Integrated inverter and energy-storage cabinet",
            "BATTERY": "Battery device",
            "BAT_SYS": "Battery system",
        },
    }

@mcp.tool()
async def get_device_telemetry(
    device_serial: str,
    device_type: str = "INVERTER",
    station_id: Optional[str] = None,
) -> dict:
    """Get live device telemetry, with readable labels and units for known readings.

    Raw SEMS+ data is also returned. Temperature is labeled as the inverter
    chamber temperature when the portal reports that alias; it is not ambient
    or outdoor temperature.
    """
    sid = _station(station_id)
    data = await client.telemetry(sid, device_serial, device_type)
    return {
        "station_id": sid, "device_serial": device_serial, "device_type": device_type,
        "data": data,
        "readings": _readings(data, _TELEMETRY_LABELS, section_labels=_SECTION_LABELS),
    }

@mcp.tool()
async def get_device_energy_counters(
    device_serial: str,
    device_type: str = "INVERTER",
    station_id: Optional[str] = None,
) -> dict:
    """Get device power and energy counters for today, week, month, year and lifetime.

    Readings include solar generation, battery charge and battery discharge;
    values and units are preserved as returned by SEMS+.
    """
    sid = _station(station_id)
    data = await client.telecounting(sid, device_serial, device_type)
    return {
        "station_id": sid, "device_serial": device_serial, "device_type": device_type,
        "data": data,
        "readings": _readings(data, _COUNTER_LABELS, section_labels=_COUNTER_SECTION_LABELS),
    }

@mcp.tool()
async def get_device_information(
    device_serial: str,
    device_type: str = "INVERTER",
    station_id: Optional[str] = None,
) -> dict:
    """Get device model, name, rated power and other information reported by SEMS+.

    Fields with unknown numeric status meanings are labeled as raw codes.
    """
    sid = _station(station_id)
    data = await client.information(sid, device_serial, device_type)
    return {
        "station_id": sid, "device_serial": device_serial, "device_type": device_type,
        "data": data,
        "readings": [
            {
                "code": item.get("code"),
                "label": _INFO_LABELS.get(item.get("code"), item.get("alias", item.get("code"))),
                "value": item.get("data"),
                **({"unit": item["unit"]} if item.get("unit") is not None else {}),
            }
            for item in data if isinstance(item, dict)
        ] if isinstance(data, list) else [],
    }

@mcp.tool()
async def get_historical_statistics(
    start_date: str,
    end_date: str,
    period: Literal["day", "month", "year"] = "day",
    station_id: Optional[str] = None,
    items: Optional[list[Literal[
        "proDischarStats",
        "proConsumStats",
        "proCharStats",
        "proSystemTotalStats",
        "proGridStats",
        "proPurchaseStats",
        "proSelfConsumStats",
    ]]] = None,
) -> dict:
    """Query SEMS+ station statistics for an inclusive date range.
    Dates must be YYYY-MM-DD. period is the returned dimension (day, month or
    year). Availability depends on the account, station and current undocumented
    API contract. items optionally selects a subset of known statistics metrics;
    if omitted, all known metrics are requested. Raw statistics and GoodWe
    direction codes are retained alongside readable names.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    if (end - start).days > 3660:
        raise ValueError("Date range exceeds 10 years; split into smaller requests")
    if period not in {"day", "month", "year"}:
        raise ValueError("period must be day, month or year")
    requested_items = items if items is not None else STATISTICS_ITEMS
    if not requested_items:
        raise ValueError("items must contain at least one statistics metric")
    unsupported = sorted(set(requested_items) - set(STATISTICS_ITEMS))
    if unsupported:
        raise ValueError(f"Unsupported statistics items: {', '.join(unsupported)}")
    sid = _station(station_id)
    data = await client.historical_statistics(sid, start, end, period, requested_items)
    metric_series = [
        {
            "code": item.get("item"),
            "label": _STATISTIC_LABELS.get(item.get("item"), item.get("item")),
            "unit": item.get("unit"),
            "values": item.get("statisticsList", []),
            "direction_code": item.get("direction"),
        }
        for item in (data.get("dataList") or [])
        if isinstance(item, dict)
    ] if isinstance(data, dict) else []
    summary_metrics = [
        {
            "code": code,
            "label": label,
            "value": data.get(code),
            **({"unit": "%"} if code.endswith("Rate") or code == "contributionRate" else {}),
        }
        for code, label in _STATISTICS_SUMMARY_LABELS.items()
        if isinstance(data, dict) and code in data
    ]
    return {
        "station_id": sid,
        "source": "SEMS+ stations/statistics",
        "period": period,
        "items": requested_items,
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "Australia/Brisbane",
        "data": data,
        "metric_series": metric_series,
        "summary_metrics": summary_metrics,
        "note": "Metric series are labeled from GoodWe item codes and retain GoodWe units and direction codes. Other summary fields remain raw where their meaning is unclear.",
    }

@mcp.tool()
async def get_historical_production(
    start_date: str,
    end_date: str,
    station_id: Optional[str] = None,
    items: Optional[list[Literal[
        "proConsumStats",
        "profitProStats",
        "proSystemTotalStats",
        "proGridStats",
        "proPurchaseStats",
        "profitGridStats",
    ]]] = None,
) -> dict:
    """Query daily production, energy and income metrics.

    Dates are inclusive and must be YYYY-MM-DD. This is the portal's separate
    production endpoint. The raw values are preserved, and SEMS+ income fields
    are also returned with clear labels: profitProStats is total generation
    income, while profitGridStats is income from energy fed to the grid.
    Energy summaries use the kWh convention shown in SEMS+ statistics; income
    summaries include the currency returned by the production endpoint.

    items optionally selects a subset of known production metrics. By default,
    the endpoint requests its usual energy and income metrics.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    if (end - start).days > 3660:
        raise ValueError("Date range exceeds 10 years; split into smaller requests")
    requested_items = items if items is not None else PRODUCTION_ITEMS
    if not requested_items:
        raise ValueError("items must contain at least one production metric")
    unsupported = sorted(set(requested_items) - set(PRODUCTION_ITEMS))
    if unsupported:
        raise ValueError(f"Unsupported production items: {', '.join(unsupported)}")
    sid = _station(station_id)
    data = await client.historical_production(sid, start, end, requested_items)
    return {
        "station_id": sid,
        "source": "SEMS+ stations/production",
        "period": "day",
        "items": requested_items,
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "Australia/Brisbane",
        "data": data,
        "energy_summary": _mapped_records(data, {
            "proSystemTotalStats": "total_generation_kwh",
            "proGridStats": "energy_fed_to_grid_kwh",
            "proPurchaseStats": "energy_purchased_from_grid_kwh",
            "proConsumStats": "energy_consumption_kwh",
        }),
        "income_summary": _mapped_records(data, {
            "profitProStats": "total_generation_income",
            "profitGridStats": "grid_fed_income",
        }, include_currency=True),
        "note": "The raw GoodWe response is preserved. Income labels follow SEMS+ field meanings; confirm amounts against retailer billing before treating them as settled income.",
    }


@mcp.tool()
async def get_station_chart(
    reporting_period: Literal["day", "week", "month", "year", "hour", "all"],
    dimension: Literal["minute", "hour", "week", "day", "month", "year"],
    start_time: str,
    end_time: str,
    metrics: list[StationChartMetric],
    station_ids: Optional[list[str]] = None,
) -> dict:
    """Get one or more metric series from the SEMS+ station chart endpoint.

    Times use portal-local `YYYY-MM-DD HH:mm:ss` format. When station_ids is
    omitted, the configured station is used. Each metric descriptor contains
    metricType, metric and unit. Candidate reporting periods are day, week,
    month, year, hour and all; candidate dimensions are minute, hour, week, day,
    month and year. Combinations depend on the requested range and GoodWe limits.
    A year reporting period with hourly dimension is too large and is rejected;
    use a coarser dimension or query a shorter period. Other long spans at fine
    dimensions may also be rejected. The raw response is preserved because its
    shape varies by request.
    """
    try:
        start = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("start_time and end_time must use YYYY-MM-DD HH:mm:ss") from exc
    if end < start:
        raise ValueError("end_time must be on or after start_time")
    if reporting_period.lower() == "year" and dimension.lower() == "hour":
        raise ValueError(
            "A year reporting period with hourly dimension is too large for SEMS+; "
            "use a coarser dimension or a shorter reporting period"
        )
    if not metrics:
        raise ValueError("metrics must contain at least one metric descriptor")
    sids = station_ids if station_ids is not None else [settings.goodwe_station_id]
    if not sids or any(not sid.strip() for sid in sids):
        raise ValueError("station_ids must contain at least one non-empty station ID")
    data = await client.station_chart(
        station_ids=sids,
        reporting_period=reporting_period,
        dimension=dimension,
        start_time=start_time,
        end_time=end_time,
        metrics=[metric.model_dump(by_alias=True) for metric in metrics],
    )
    return {
        "station_ids": sids,
        "source": "SEMS+ compare/station/chart",
        "reporting_period": reporting_period,
        "dimension": dimension,
        "start_time": start_time,
        "end_time": end_time,
        "metrics": [metric.model_dump(by_alias=True) for metric in metrics],
        "data": data,
        "note": "Chart interval limits depend on the reporting period and dimension. GoodWe may reject large responses; reduce the time range or use a coarser dimension when needed.",
    }


def main() -> None:
    """Run the stdio server used by Codex CLI and other local MCP clients."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    # stdio is safest for local clients. For a remote MCP connection, set
    # MCP_TRANSPORT=streamable-http and put this behind TLS + authentication.
    mcp.run(transport=settings.mcp_transport)
