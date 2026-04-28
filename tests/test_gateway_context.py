import pytest
import importlib.util
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "ws_mcp_server"
    / "gateway_context.py"
)
spec = importlib.util.spec_from_file_location("gateway_context", MODULE_PATH)
gateway_context = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["gateway_context"] = gateway_context
spec.loader.exec_module(gateway_context)

GatewayContextError = gateway_context.GatewayContextError
build_context_payload = gateway_context.build_context_payload
has_explicit_room_or_area = gateway_context.has_explicit_room_or_area
is_gateway_context_enabled = gateway_context.is_gateway_context_enabled
parse_active_context = gateway_context.parse_active_context
should_inject_preferred_area_id = gateway_context.should_inject_preferred_area_id


def test_parse_active_context_requires_active_response():
    with pytest.raises(GatewayContextError, match="No active Xiaozhi room context"):
        parse_active_context({"active": False})


def test_parse_active_context_requires_room_id():
    with pytest.raises(GatewayContextError, match="missing room_id"):
        parse_active_context({"active": True, "device_id": "device"})


def test_build_context_payload_injects_default_room_context():
    active_context = parse_active_context(
        {
            "active": True,
            "device_id": "xiaozhi-device",
            "room_id": "living_room",
            "room_name": "客厅",
            "ha_area_id": "living_room",
            "ha_device_id": "ha-device",
        }
    )

    payload = build_context_payload(
        base_context={"existing": "value"},
        active_context=active_context,
        tool_arguments={},
    )

    assert payload == {
        "context": {
            "existing": "value",
            "xiaozhi_device_id": "xiaozhi-device",
            "room_id": "living_room",
            "room_name": "客厅",
            "ha_area_id": "living_room",
        },
        "device_id": "ha-device",
        "tool_arguments": {},
    }


def test_build_context_payload_injects_preferred_area_id_for_supported_intent_tool():
    active_context = parse_active_context(
        {
            "active": True,
            "device_id": "xiaozhi-device",
            "room_id": "living_room",
            "room_name": "客厅",
            "ha_area_id": "ke_ting",
        }
    )

    payload = build_context_payload(
        base_context={},
        active_context=active_context,
        tool_arguments={"name": "窗帘", "domain": "cover"},
        inject_preferred_area_id=True,
    )

    assert payload["tool_arguments"] == {
        "name": "窗帘",
        "domain": "cover",
        "preferred_area_id": "ke_ting",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {"room": "卧室"},
        {"room_id": "bedroom"},
        {"area": "卧室"},
        {"area_id": "bedroom"},
    ],
)
def test_build_context_payload_does_not_inject_room_when_tool_has_explicit_room(arguments):
    active_context = parse_active_context(
        {
            "active": True,
            "device_id": "xiaozhi-device",
            "room_id": "living_room",
            "room_name": "客厅",
            "ha_area_id": "living_room",
            "ha_device_id": "ha-device",
        }
    )

    payload = build_context_payload(
        base_context={},
        active_context=active_context,
        tool_arguments=arguments,
    )

    assert payload == {
        "context": {"xiaozhi_device_id": "xiaozhi-device"},
        "device_id": None,
        "tool_arguments": arguments,
    }


def test_build_context_payload_does_not_inject_preferred_area_when_tool_has_explicit_room():
    active_context = parse_active_context(
        {
            "active": True,
            "device_id": "xiaozhi-device",
            "room_id": "living_room",
            "room_name": "客厅",
            "ha_area_id": "ke_ting",
        }
    )

    arguments = {"name": "窗帘", "domain": "cover", "area": "主卧"}
    payload = build_context_payload(
        base_context={},
        active_context=active_context,
        tool_arguments=arguments,
        inject_preferred_area_id=True,
    )

    assert payload["tool_arguments"] == arguments


def test_should_inject_preferred_area_id_for_home_assistant_intent_tools():
    assert should_inject_preferred_area_id("HassTurnOn", False)
    assert should_inject_preferred_area_id("assist__HassTurnOff", False)
    assert not should_inject_preferred_area_id("calendar_get_events", False)


def test_has_explicit_room_or_area_checks_nested_arguments():
    assert has_explicit_room_or_area({"target": {"area_id": "bedroom"}})


@pytest.mark.parametrize("gateway_url", [None, "", "   "])
def test_gateway_context_is_disabled_when_gateway_url_is_empty(gateway_url):
    assert not is_gateway_context_enabled(gateway_url)


def test_gateway_context_is_enabled_when_gateway_url_is_set():
    assert is_gateway_context_enabled("http://127.0.0.1:8125")
