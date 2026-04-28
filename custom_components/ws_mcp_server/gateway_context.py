"""Helpers for Xiaozhi gateway room context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ROOM_OR_AREA_KEYS = {"room", "room_id", "area", "area_id"}


class GatewayContextError(RuntimeError):
    """Raised when the gateway cannot provide a usable active context."""


@dataclass(frozen=True)
class ActiveGatewayContext:
    device_id: str
    room_id: str
    room_name: str
    ha_area_id: str
    ha_device_id: str | None = None


def normalize_gateway_url(gateway_url: str | None) -> str:
    return (gateway_url or "").strip().rstrip("/")


def is_gateway_context_enabled(gateway_url: str | None) -> bool:
    return bool(normalize_gateway_url(gateway_url))


def parse_active_context(payload: dict[str, Any]) -> ActiveGatewayContext:
    if not payload.get("active"):
        raise GatewayContextError("No active Xiaozhi room context")

    for key in ("device_id", "room_id", "room_name", "ha_area_id"):
        if not payload.get(key):
            raise GatewayContextError(f"Active Xiaozhi room context missing {key}")

    return ActiveGatewayContext(
        device_id=str(payload["device_id"]),
        room_id=str(payload["room_id"]),
        room_name=str(payload["room_name"]),
        ha_area_id=str(payload["ha_area_id"]),
        ha_device_id=str(payload["ha_device_id"]) if payload.get("ha_device_id") else None,
    )


def has_explicit_room_or_area(arguments: dict[str, Any]) -> bool:
    for key, value in arguments.items():
        if key in ROOM_OR_AREA_KEYS and value:
            return True
        if isinstance(value, dict) and has_explicit_room_or_area(value):
            return True
    return False


def build_context_payload(
    base_context: dict[str, Any],
    active_context: ActiveGatewayContext,
    tool_arguments: dict[str, Any],
    inject_preferred_area_id: bool = False,
) -> dict[str, Any]:
    context = dict(base_context)
    context["xiaozhi_device_id"] = active_context.device_id
    contextual_tool_arguments = dict(tool_arguments)

    if has_explicit_room_or_area(tool_arguments):
        return {
            "context": context,
            "device_id": None,
            "tool_arguments": contextual_tool_arguments,
        }

    context["room_id"] = active_context.room_id
    context["room_name"] = active_context.room_name
    context["ha_area_id"] = active_context.ha_area_id
    if inject_preferred_area_id:
        contextual_tool_arguments["preferred_area_id"] = active_context.ha_area_id

    return {
        "context": context,
        "device_id": active_context.ha_device_id,
        "tool_arguments": contextual_tool_arguments,
    }
