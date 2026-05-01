"""Helpers for Xiaozhi gateway room context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ROOM_OR_AREA_KEYS = {"room", "room_id", "area", "area_id"}
HOME_ASSISTANT_INTENT_TOOL_PREFIX = "Hass"
MULTIPLE_ACTIVE_CONTEXTS = "multiple_active_contexts"
GATEWAY_ROOM_PROMPT = (
    "Xiaozhi gateway room context is enabled. When the user does not explicitly "
    "name a room or area, still call the Home Assistant intent tool. Do not ask "
    "which room or area first. The MCP server will inject preferred_area_id for "
    "the currently active Xiaozhi room. If the user names an area together with "
    "a device, pass both area and name to the Home Assistant intent tool. For "
    "example, for 'turn on the living room chandelier', call HassTurnOn with "
    "area='living room' and name='chandelier'. If the user explicitly names a "
    "room or area, preserve that explicit target."
)


class GatewayContextError(RuntimeError):
    """Raised when the gateway cannot provide a usable active context."""


class ActiveContextAmbiguousError(GatewayContextError):
    """Raised when more than one Xiaozhi room context is active."""


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


def should_inject_preferred_area_id(
    tool_name: str, supports_preferred_area_id: bool
) -> bool:
    return supports_preferred_area_id or tool_name.rsplit("__", 1)[-1].startswith(
        HOME_ASSISTANT_INTENT_TOOL_PREFIX
    )


def build_gateway_room_prompt(base_prompt: str) -> str:
    return f"{base_prompt}\n\n{GATEWAY_ROOM_PROMPT}"


def parse_active_context(payload: dict[str, Any]) -> ActiveGatewayContext:
    if not payload.get("active"):
        if payload.get("status") == MULTIPLE_ACTIVE_CONTEXTS:
            raise ActiveContextAmbiguousError("multiple active Xiaozhi room contexts")
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
    base_context: Any,
    active_context: ActiveGatewayContext,
    tool_arguments: dict[str, Any],
    inject_preferred_area_id: bool = False,
) -> dict[str, Any]:
    contextual_tool_arguments = dict(tool_arguments)

    if has_explicit_room_or_area(tool_arguments):
        return {
            "context": base_context,
            "device_id": None,
            "tool_arguments": contextual_tool_arguments,
        }

    if inject_preferred_area_id:
        contextual_tool_arguments["preferred_area_id"] = active_context.ha_area_id

    return {
        "context": base_context,
        "device_id": active_context.ha_device_id,
        "tool_arguments": contextual_tool_arguments,
    }
