import importlib.util
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "ws_mcp_server"
    / "tool_schema.py"
)
spec = importlib.util.spec_from_file_location("tool_schema", MODULE_PATH)
tool_schema = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["tool_schema"] = tool_schema
spec.loader.exec_module(tool_schema)

build_mcp_input_schema = tool_schema.build_mcp_input_schema


def test_build_mcp_input_schema_preserves_validation_contract():
    input_schema = {
        "type": "object",
        "properties": {
            "domain": {"type": "array", "items": {"type": "string"}},
            "area": {"type": "string"},
        },
        "additionalProperties": False,
    }

    assert build_mcp_input_schema(input_schema) == input_schema


def test_build_mcp_input_schema_adds_room_metadata_for_direct_entity_tools():
    input_schema = {
        "type": "object",
        "properties": {
            "entity_ids": {"type": "string"},
            "hvac_mode": {"type": "string"},
        },
        "additionalProperties": False,
    }

    schema = build_mcp_input_schema(input_schema, gateway_context_enabled=True)

    assert schema["properties"]["entity_ids"] == {"type": "string"}
    assert schema["properties"]["hvac_mode"] == {"type": "string"}
    assert schema["properties"]["area"]["type"] == "string"
    assert schema["properties"]["room"]["type"] == "string"
    assert schema["additionalProperties"] is False
