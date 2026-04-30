"""Pending confirmation MCP helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

try:
    from .gateway_context import ActiveGatewayContext, normalize_gateway_url
except ImportError:  # pragma: no cover - used by standalone tests
    from gateway_context import ActiveGatewayContext, normalize_gateway_url


PENDING_CONFIRMATION_EVENT = "xiaozhi_gateway_pending_confirmation_resolved"
GET_PENDING_CONFIRMATION_TOOL = "GetPendingConfirmation"
RESOLVE_PENDING_CONFIRMATION_TOOL = "ResolvePendingConfirmation"

RequestJson = Callable[..., Awaitable[dict[str, Any]]]


def pending_confirmation_tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": GET_PENDING_CONFIRMATION_TOOL,
            "description": "Get the active Home Assistant pending confirmation for the current Xiaozhi room.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": RESOLVE_PENDING_CONFIRMATION_TOOL,
            "description": "Resolve the active Home Assistant pending confirmation with yes or no.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "string",
                        "enum": ["yes", "no"],
                        "description": "yes means confirmed, no means rejected.",
                    }
                },
                "required": ["decision"],
            },
        },
    ]


def is_pending_confirmation_tool(name: str) -> bool:
    return name in {
        GET_PENDING_CONFIRMATION_TOOL,
        RESOLVE_PENDING_CONFIRMATION_TOOL,
    }


async def handle_pending_confirmation_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    gateway_url: str | None,
    active_context: ActiveGatewayContext,
    hass: Any,
    request_json: RequestJson | None = None,
) -> dict[str, Any]:
    request = request_json or request_gateway_json
    try:
        if name == GET_PENDING_CONFIRMATION_TOOL:
            return await get_pending_confirmation(
                gateway_url,
                active_context,
                request_json=request,
            )
        if name == RESOLVE_PENDING_CONFIRMATION_TOOL:
            return await resolve_pending_confirmation(
                gateway_url,
                active_context,
                arguments.get("decision"),
                hass,
                request_json=request,
            )
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return {"status": "gateway_unavailable"}
    return {"status": "unknown_tool", "tool": name}


async def get_pending_confirmation(
    gateway_url: str | None,
    active_context: ActiveGatewayContext,
    *,
    request_json: RequestJson,
) -> dict[str, Any]:
    gateway_url = normalize_gateway_url(gateway_url)
    return await request_json(
        "GET",
        gateway_url + "/pending-confirmations/active",
        params={
            "device_id": active_context.device_id,
            "room_id": active_context.room_id,
        },
    )


async def resolve_pending_confirmation(
    gateway_url: str | None,
    active_context: ActiveGatewayContext,
    decision: Any,
    hass: Any,
    *,
    request_json: RequestJson,
) -> dict[str, Any]:
    if decision not in {"yes", "no"}:
        return {"status": "invalid_decision"}

    active = await get_pending_confirmation(
        gateway_url,
        active_context,
        request_json=request_json,
    )
    if not active.get("active"):
        return active

    confirmation_id = active.get("confirmation_id")
    if not confirmation_id:
        return {"status": "no_pending_confirmation"}

    resolved = await request_json(
        "POST",
        normalize_gateway_url(gateway_url)
        + f"/pending-confirmations/{confirmation_id}/resolve",
        json={
            "decision": decision,
            "device_id": active_context.device_id,
            "room_id": active_context.room_id,
            "source": "xiaozhi_mcp",
        },
    )
    if resolved.get("status") in {"confirmed", "rejected"}:
        hass.bus.async_fire(
            PENDING_CONFIRMATION_EVENT,
            {
                "confirmation_id": resolved.get("confirmation_id"),
                "status": resolved.get("status"),
                "decision": resolved.get("decision"),
                "device_id": resolved.get("device_id"),
                "room_id": resolved.get("room_id"),
                "metadata": resolved.get("metadata") or {},
            },
        )
    return resolved


async def request_gateway_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=3)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if method == "GET":
            response_context = session.get(url, params=kwargs.get("params"))
        elif method == "POST":
            response_context = session.post(url, json=kwargs.get("json"))
        else:
            return {"status": "unsupported_method"}

        try:
            async with response_context as response:
                try:
                    payload = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    return {"status": "gateway_unavailable"}
                if response.status >= 400:
                    return {"status": payload.get("detail", f"http_{response.status}")}
                return payload
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return {"status": "gateway_unavailable"}
