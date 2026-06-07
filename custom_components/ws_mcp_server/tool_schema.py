"""MCP tool schema helpers."""

from __future__ import annotations

from typing import Any


def build_mcp_input_schema(
    input_schema: dict[str, Any],
    gateway_context_enabled: bool = False,
) -> dict[str, Any]:
    """Build the MCP input schema without dropping validation constraints."""
    schema = dict(input_schema)
    schema.setdefault("type", "object")
    properties = dict(schema.setdefault("properties", {}))
    if gateway_context_enabled and _has_direct_entity_target_property(properties):
        properties.setdefault(
            "area",
            {
                "type": "string",
                "description": (
                    "Room or area explicitly named by the user. The MCP server "
                    "uses it as validation metadata and does not pass it to the "
                    "Home Assistant entity tool."
                ),
            },
        )
        properties.setdefault(
            "room",
            {
                "type": "string",
                "description": (
                    "Room explicitly named by the user. Use this only when the "
                    "user named a room while calling an entity_id/entity_ids tool."
                ),
            },
        )
    schema["properties"] = properties
    return schema


def _has_direct_entity_target_property(properties: dict[str, Any]) -> bool:
    return "entity_id" in properties or "entity_ids" in properties
