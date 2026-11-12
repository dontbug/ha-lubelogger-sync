"""Minimal async client for the LubeLogger REST API."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT


class LubeLoggerError(Exception):
    """Generic LubeLogger API error."""


class LubeLoggerAuthError(LubeLoggerError):
    """The API key was rejected."""


class LubeLoggerConnectionError(LubeLoggerError):
    """The LubeLogger server could not be reached."""


class LubeLoggerApi:
    """Client for the LubeLogger REST API, authenticated with an API key."""

    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str) -> None:
        """Initialize the client."""
        self._session = session
        self.url = url.rstrip("/")
        self._headers = {
            "x-api-key": api_key,
            # Ask for ISO dates and plain numbers regardless of server locale.
            "culture-invariant": "true",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with self._session.request(
                method,
                f"{self.url}{path}",
                headers=self._headers,
                params=params,
                json=json,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status in (401, 403):
                    raise LubeLoggerAuthError(
                        f"LubeLogger rejected the API key (HTTP {resp.status})"
                    )
                if resp.status >= 400:
                    body = (await resp.text())[:200]
                    raise LubeLoggerError(
                        f"LubeLogger returned HTTP {resp.status} for {path}: {body}"
                    )
                try:
                    return await resp.json(content_type=None)
                except ValueError as err:
                    raise LubeLoggerError(
                        f"Unexpected non-JSON response from {path}"
                    ) from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise LubeLoggerConnectionError(
                f"Cannot connect to LubeLogger at {self.url}: {err}"
            ) from err

    async def vehicle_info(self) -> list[dict[str, Any]]:
        """Return details (incl. last odometer) for every accessible vehicle."""
        data = await self._request("GET", "/api/vehicle/info")
        if not isinstance(data, list):
            raise LubeLoggerError("Unexpected response from /api/vehicle/info")
        return data

    async def reminders(self) -> list[dict[str, Any]]:
        """Return reminders (with calculated urgency) for all vehicles."""
        data = await self._request("GET", "/api/vehicle/reminders/all")
        if not isinstance(data, list):
            raise LubeLoggerError("Unexpected response from /api/vehicle/reminders/all")
        return data

    async def latest_odometer(self, vehicle_id: int) -> int:
        """Return the latest odometer reading known to LubeLogger."""
        data = await self._request(
            "GET",
            "/api/vehicle/odometerrecords/latest",
            params={"vehicleId": vehicle_id},
        )
        try:
            return int(float(data))
        except (TypeError, ValueError) as err:
            raise LubeLoggerError(
                f"Unexpected latest odometer value: {data!r}"
            ) from err

    async def add_odometer(
        self,
        vehicle_id: int,
        *,
        date: str,
        odometer: int,
        initial_odometer: int,
        notes: str = "",
    ) -> Any:
        """Add an odometer record. `date` is an ISO date (YYYY-MM-DD)."""
        data = await self._request(
            "POST",
            "/api/vehicle/odometerrecords/add",
            params={"vehicleId": vehicle_id},
            json={
                "date": date,
                "initialOdometer": initial_odometer,
                "odometer": odometer,
                "notes": notes,
            },
        )
        if isinstance(data, dict) and data.get("success") is False:
            raise LubeLoggerError(
                f"LubeLogger refused the odometer record: {data.get('message')}"
            )
        return data
