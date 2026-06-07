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
build_gateway_room_prompt = gateway_context.build_gateway_room_prompt
has_explicit_room_or_area = gateway_context.has_explicit_room_or_area
has_direct_entity_target = gateway_context.has_direct_entity_target
has_explicit_tool_target = gateway_context.has_explicit_tool_target
is_gateway_context_enabled = gateway_context.is_gateway_context_enabled
normalize_gateway_url = gateway_context.normalize_gateway_url
parse_active_context = gateway_context.parse_active_context
should_inject_preferred_area_id = gateway_context.should_inject_preferred_area_id
should_fetch_gateway_context = gateway_context.should_fetch_gateway_context
rewrite_current_room_ac_entity_targets = (
    gateway_context.rewrite_current_room_ac_entity_targets
)
strip_room_metadata_for_direct_entity_target = (
    gateway_context.strip_room_metadata_for_direct_entity_target
)


def test_parse_active_context_requires_active_response():
    with pytest.raises(GatewayContextError, match="No active Xiaozhi room context"):
        parse_active_context({"active": False})


def test_parse_active_context_reports_multiple_active_contexts():
    with pytest.raises(GatewayContextError, match="multiple active"):
        parse_active_context({"active": False, "status": "multiple_active_contexts"})


def test_parse_active_context_requires_room_id():
    with pytest.raises(GatewayContextError, match="missing room_id"):
        parse_active_context({"active": True, "device_id": "device"})


def test_build_context_payload_injects_default_room_context():
    base_context = object()
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
        base_context=base_context,
        active_context=active_context,
        tool_arguments={},
    )

    assert payload == {
        "context": base_context,
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
    base_context = object()
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
        base_context=base_context,
        active_context=active_context,
        tool_arguments=arguments,
    )

    assert payload == {
        "context": base_context,
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


def test_build_context_payload_injects_room_when_model_guesses_entity_id_without_room():
    active_context = parse_active_context(
        {
            "active": True,
            "device_id": "xiaozhi-device",
            "room_id": "guest_bedroom",
            "room_name": "次卧",
            "ha_area_id": "ci_wo",
        }
    )

    payload = build_context_payload(
        base_context={},
        active_context=active_context,
        tool_arguments={
            "entity_ids": "['climate.vrf_master_bedroom']",
            "hvac_mode": "off",
        },
        inject_preferred_area_id=True,
    )

    assert payload["tool_arguments"] == {
        "entity_ids": "['climate.vrf_master_bedroom']",
        "hvac_mode": "off",
        "preferred_area_id": "ci_wo",
    }


def test_should_inject_preferred_area_id_for_home_assistant_intent_tools():
    assert should_inject_preferred_area_id("HassTurnOn", False)
    assert should_inject_preferred_area_id("assist__HassTurnOff", False)
    assert not should_inject_preferred_area_id("calendar_get_events", False)


def test_should_fetch_gateway_context_for_current_room_intent_tool():
    assert should_fetch_gateway_context(
        "HassTurnOff",
        {"name": "纱帘", "domain": ["cover"]},
        supports_preferred_area_id=False,
    )


def test_should_not_fetch_gateway_context_for_fixed_room_tool():
    assert not should_fetch_gateway_context(
        "livingroom_off_light",
        {},
        supports_preferred_area_id=False,
    )


def test_should_not_fetch_gateway_context_for_direct_entity_target():
    assert not should_fetch_gateway_context(
        "set_multiple_ac_hvac_mode",
        {"entity_ids": "['climate.vrf_master_bedroom']"},
        supports_preferred_area_id=False,
    )


def test_strip_room_metadata_for_direct_entity_target_keeps_tool_arguments():
    assert strip_room_metadata_for_direct_entity_target(
        {
            "entity_ids": "['climate.vrf_master_bedroom']",
            "hvac_mode": "cool",
            "area": "主卧",
        }
    ) == {
        "entity_ids": "['climate.vrf_master_bedroom']",
        "hvac_mode": "cool",
    }


def test_rewrite_current_room_ac_script_entity_target_from_active_context():
    active_context = parse_active_context(
        {
            "active": True,
            "device_id": "xiaozhi-device",
            "room_id": "guest_bedroom",
            "room_name": "次卧",
            "ha_area_id": "ci_wo",
        }
    )

    assert rewrite_current_room_ac_entity_targets(
        "set_multiple_ac_hvac_mode",
        {
            "entity_ids": "['climate.vrf_master_bedroom']",
            "hvac_mode": "cool",
        },
        active_context,
    ) == {
        "entity_ids": "['climate.vrf_guest_bedroom']",
        "hvac_mode": "cool",
    }


def test_rewrite_current_room_ac_script_keeps_explicit_room_target():
    active_context = parse_active_context(
        {
            "active": True,
            "device_id": "xiaozhi-device",
            "room_id": "guest_bedroom",
            "room_name": "次卧",
            "ha_area_id": "ci_wo",
        }
    )

    arguments = {
        "entity_ids": "['climate.vrf_master_bedroom']",
        "hvac_mode": "cool",
        "area": "主卧",
    }

    assert (
        rewrite_current_room_ac_entity_targets(
            "set_multiple_ac_hvac_mode",
            arguments,
            active_context,
        )
        == arguments
    )


def test_rewrite_current_room_ac_script_keeps_all_room_targets():
    active_context = parse_active_context(
        {
            "active": True,
            "device_id": "xiaozhi-device",
            "room_id": "guest_bedroom",
            "room_name": "次卧",
            "ha_area_id": "ci_wo",
        }
    )

    arguments = {
        "entity_ids": (
            "['climate.vrf_livingroom','climate.vrf_master_bedroom',"
            "'climate.vrf_guest_bedroom']"
        ),
        "hvac_mode": "off",
    }

    assert (
        rewrite_current_room_ac_entity_targets(
            "set_multiple_ac_hvac_mode",
            arguments,
            active_context,
        )
        == arguments
    )


def test_build_gateway_room_prompt_tells_model_not_to_ask_for_room_first():
    prompt = build_gateway_room_prompt("base prompt")

    assert "base prompt" in prompt
    assert "Do not ask which room or area first" in prompt
    assert "active_context_unavailable" in prompt
    assert "ask which room or area" in prompt
    assert "If the user names an area together with a device" in prompt
    assert "pass both area and name" in prompt
    assert "entity_id/entity_ids" in prompt
    assert "active Xiaozhi room context" in prompt
    assert "preferred_area_id" in prompt


def test_has_explicit_room_or_area_checks_nested_arguments():
    assert has_explicit_room_or_area({"target": {"area_id": "bedroom"}})


@pytest.mark.parametrize(
    "arguments",
    [
        {"entity_id": "climate.vrf_master_bedroom"},
        {"entity_ids": "['climate.vrf_master_bedroom']"},
        {"target": {"entity_id": "climate.vrf_master_bedroom"}},
        {"name": "climate.vrf_master_bedroom"},
    ],
)
def test_has_direct_entity_target_accepts_entity_ids(arguments):
    assert has_direct_entity_target(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {"entity_id": "climate.vrf_master_bedroom"},
        {"entity_ids": ["climate.vrf_master_bedroom"]},
        {"target": {"entity_id": "climate.vrf_master_bedroom"}},
        {"name": "climate.vrf_master_bedroom"},
    ],
)
def test_has_explicit_tool_target_accepts_direct_entity_targets(arguments):
    assert has_explicit_tool_target(arguments)


@pytest.mark.parametrize("gateway_url", [None, "", "   "])
def test_gateway_context_is_disabled_when_gateway_url_is_empty(gateway_url):
    assert not is_gateway_context_enabled(gateway_url)


def test_gateway_context_is_enabled_when_gateway_url_is_set():
    assert is_gateway_context_enabled("http://127.0.0.1:8125")


def test_normalize_gateway_url_accepts_bare_gateway_host():
    assert normalize_gateway_url("192.168.166.68") == "http://192.168.166.68:8125"
