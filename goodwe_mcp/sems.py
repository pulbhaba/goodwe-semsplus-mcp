import base64
import hashlib
import json
import logging
import time
import uuid
from datetime import date
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger(__name__)

class GoodWeError(RuntimeError):
    pass

_WEB_CLIENT = "semsPlusWeb"
_WEB_VERSION = ""
_LANGUAGE = "en"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) "
    "Gecko/20100101 Firefox/159.0"
)
STATISTICS_ITEMS = [
    "proDischarStats",
    "proConsumStats",
    "proCharStats",
    "proSystemTotalStats",
    "proGridStats",
    "proPurchaseStats",
    "proSelfConsumStats",
]
PRODUCTION_ITEMS = [
    "proConsumStats",
    "profitProStats",
    "proSystemTotalStats",
    "proGridStats",
    "proPurchaseStats",
    "profitGridStats",
]
_CHART_API_BASE = "https://au-gateway.semsportal.com"

def _signature(timestamp: str, uid: str, token: str) -> str:
    material = f"{timestamp}@{uid}@{token}".encode("utf-8")
    sha_hex = hashlib.sha256(material).hexdigest()
    return base64.b64encode(f"{sha_hex}@{timestamp}".encode("utf-8")).decode("ascii")

class SemsPlusClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = httpx.AsyncClient(
            timeout=settings.request_timeout,
            follow_redirects=True,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json, text/plain, */*",
            },
        )
        self.token: dict[str, Any] | None = None
        self.api_base: str | None = None
        self.uuid: str | None = None

    async def close(self):
        await self.http.aclose()

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise GoodWeError("Not authenticated")
        ts = str(self.token.get("timestamp", ""))
        uid = str(self.token.get("uid", ""))
        token = str(self.token.get("token", ""))
        return {
            "Token": json.dumps(self.token, separators=(",", ":")),
            "X-Signature": _signature(ts, uid, token),
            "X-Uid": uid,
            "X-Token": token,
            "X-Timestamp": ts,
            "neutral": "0",
            "currentLang": _LANGUAGE,
            "uuid": str(self.token.get("uuid", "")),
            "os": "Windows 10.0 desktop",
            "brand": "Firefox 159.0 en-US Australia/Brisbane",
            "Content-Type": "application/json",
            "Origin": self.settings.portal_origin,
            "Referer": self.settings.portal_origin + "/",
        }

    async def login(self, force: bool = False) -> dict[str, Any]:
        if self.token and not force:
            return {"authenticated": True, "region": self.settings.goodwe_region}
        url = self.settings.portal_origin + "/web/sems/sems-user/api/v1/auth/cross-login"
        self.uuid = str(uuid.uuid4())
        login_timestamp = str(int(time.time() * 1000))
        headers = {
            "Token": json.dumps(
                {
                    "uid": "",
                    "timestamp": 0,
                    "token": "",
                    "client": _WEB_CLIENT,
                    "version": _WEB_VERSION,
                    "language": _LANGUAGE,
                },
                separators=(",", ":"),
            ),
            "X-Signature": _signature(login_timestamp, "", ""),
            "neutral": "0",
            "currentLang": _LANGUAGE,
            "uuid": self.uuid,
            "os": "Windows 10.0 desktop",
            "brand": "Firefox 159.0 en-US Australia/Brisbane",
            "Content-Type": "application/json",
            "Origin": self.settings.portal_origin,
            "Referer": self.settings.portal_origin + "/",
        }
        body = {
            "account": self.settings.goodwe_username,
            "pwd": self.settings.goodwe_password,
            "agreement": 1,
            "isLocal": False,
            "isChinese": False,
        }
        response = await self.http.post(url, json=body, headers=headers)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if (
            payload.get("hasError") is True
            or str(payload.get("code")) not in {"0", "00000"}
            or not isinstance(data, dict)
        ):
            # Do not print credentials or request headers. The response's trace
            # ID/code is useful for debugging and safe to surface.
            raise GoodWeError(
                f"SEMS login rejected: code={payload.get('code')} "
                f"description={payload.get('description') or payload.get('msg')} "
                f"traceId={payload.get('traceId')}"
            )
        self.token = {
            **data,
            "client": _WEB_CLIENT,
            "version": _WEB_VERSION,
            "language": _LANGUAGE,
            "uuid": self.uuid,
        }
        self.api_base = self.settings.api_base.rstrip("/")
        if not self.api_base.startswith("https://"):
            raise GoodWeError("GoodWe returned a non-HTTPS API gateway; refusing request")
        return {"authenticated": True, "region": self.token.get("region", self.settings.goodwe_region)}

    async def request(
        self, method: str, path: str, *, params=None, json_body=None, base_url: str | None = None
    ):
        if not self.token:
            await self.login()
        request_base = (base_url or self.api_base).rstrip("/")
        url = request_base + "/" + path.lstrip("/")
        response = await self.http.request(
            method.upper(), url, params=params, json=json_body, headers=self._headers()
        )
        if response.status_code in (401, 403):
            await self.login(force=True)
            response = await self.http.request(
                method.upper(), url, params=params, json=json_body, headers=self._headers()
            )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoodWeError(f"SEMS+ returned non-JSON response for {path}") from exc
        code = str(payload.get("code", "00000"))
        if code not in ("00000", "0", "200", "None"):
            raise GoodWeError(
                f"SEMS+ API error on {path}: code={code}, "
                f"description={payload.get('description') or payload.get('errorMsg')}"
            )
        return payload.get("data", payload)

    async def live_flow(self, station_id: str):
        return await self.request(
            "GET", "/sems-plant/api/stations/flow", params={"stationId": station_id}
        )

    async def device_list(self, station_id: str, device_type: str):
        return await self.request(
            "GET", "/sems-plant/api/web/device/station/getDevicesByType",
            params={"stationId": station_id, "deviceType": device_type},
        )

    async def telemetry(self, station_id: str, serial: str, device_type: str):
        return await self.request(
            "GET", f"/sems-plant/api/equipments/{serial}/telemetry",
            params={"deviceType": device_type, "pwId": station_id},
        )

    async def telecounting(self, station_id: str, serial: str, device_type: str):
        return await self.request(
            "GET", f"/sems-plant/api/equipments/{serial}/telecounting",
            params={"deviceType": device_type, "pwId": station_id},
        )

    async def information(self, station_id: str, serial: str, device_type: str):
        return await self.request(
            "GET", f"/sems-plant/api/equipments/{serial}/information",
            params={"deviceType": device_type, "pwId": station_id},
        )

    async def historical_statistics(
        self,
        station_id: str,
        start_date: date,
        end_date: date,
        period: str = "day",
        items: list[str] | None = None,
    ):
        body = {
            "stationId": station_id,
            "isReport": False,
            "items": items if items is not None else STATISTICS_ITEMS,
            "dimension": period,
            "startTime": f"{start_date.isoformat()} 00:00:00",
            "endTime": f"{end_date.isoformat()} 23:59:59",
        }
        return await self.request(
            "POST",
            "/sems-plant/api/stations/statistics",
            json_body=body,
        )

    async def historical_production(
        self,
        station_id: str,
        start_date: date,
        end_date: date,
        items: list[str] | None = None,
    ):
        body = {
            "stationId": station_id,
            "items": items if items is not None else PRODUCTION_ITEMS,
            "dimension": "day",
            "isReport": False,
            "startTime": f"{start_date.isoformat()} 00:00:00",
            "endTime": f"{end_date.isoformat()} 23:59:59",
        }
        return await self.request(
            "POST",
            "/sems-plant/api/stations/production",
            json_body=body,
        )

    async def station_chart(
        self,
        station_ids: list[str],
        reporting_period: str,
        dimension: str,
        start_time: str,
        end_time: str,
        metrics: list[dict[str, str]],
    ):
        body = {
            "stationIds": station_ids,
            "reportingPeriod": reporting_period,
            "dimension": dimension,
            "startTime": start_time,
            "endTime": end_time,
            "metrics": metrics,
        }
        return await self.request(
            "POST",
            "/sems/sems-report/api/v2/compare/station/chart",
            json_body=body,
            base_url=_CHART_API_BASE,
        )

    async def discover_common_devices(self, station_id: str):
        results = {}
        for kind in ("INVERTER", "ENERGY_STORAGE_INTEGRATED_CABINET", "BATTERY", "BAT_SYS"):
            try:
                results[kind] = await self.device_list(station_id, kind)
            except Exception as exc:
                results[kind] = {"unavailable": str(exc)}
        return results
