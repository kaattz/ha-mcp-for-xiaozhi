"""MCP tool schema helpers."""

from __future__ import annotations

from typing import Any


def build_mcp_input_schema(input_schema: dict[str, Any]) -> dict[str, Any]:
    """Build the MCP input schema without dropping validation constraints."""
    schema = dict(input_schema)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema
