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
inject_area_from_name_prefix = gateway_context.inject_area_from_name_prefix
normalize_generic_area_target = gateway_context.normalize_generic_area_target
normalize_area_scoped_name_target = gateway_context.normalize_area_scoped_name_target
has_explicit_room_or_area = gateway_context.has_explicit_room_or_area
has_direct_entity_target = gateway_context.has_direct_entity_target
has_explicit_tool_target = gateway_context.has_explicit_tool_target
is_gateway_context_enabled = gateway_context.is_gateway_context_enabled
normalize_gateway_url = gateway_context.normalize_gateway_url
parse_active_context = gateway_context.parse_active_context
ac_climate_turn_hvac_mode = gateway_context.ac_climate_turn_hvac_mode
build_ac_custom_control_tool_call = gateway_context.build_ac_custom_control_tool_call
climate_device_type_from_name = gateway_context.climate_device_type_from_name
is_ac_climate_turn_request = gateway_context.is_ac_climate_turn_request
is_all_air_conditioner_request = gateway_context.is_all_air_conditioner_request
is_custom_ac_control_enabled = gateway_context.is_custom_ac_control_enabled
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


def test_inject_area_from_name_prefix_uses_matching_area_name():
    assert inject_area_from_name_prefix(
        {"name": "餐厅吊灯", "domain": ["light"]},
        ["客厅", "餐厅", "主卧", "次卧"],
    ) == {"name": "餐厅吊灯", "domain": ["light"], "area": "餐厅"}


def test_inject_area_from_name_prefix_uses_longest_area_name():
    assert inject_area_from_name_prefix(
        {"name": "主卧卫生间灯", "domain": ["light"]},
        ["主卧", "主卧卫生间"],
    ) == {"name": "主卧卫生间灯", "domain": ["light"], "area": "主卧卫生间"}


def test_inject_area_from_name_prefix_keeps_explicit_area():
    arguments = {"name": "餐厅吊灯", "domain": ["light"], "area": "客厅"}

    assert inject_area_from_name_prefix(arguments, ["餐厅"]) == arguments


def test_inject_area_from_name_prefix_ignores_generic_name():
    arguments = {"name": "吊灯", "domain": ["light"]}

    assert inject_area_from_name_prefix(arguments, ["餐厅"]) == arguments


def test_normalize_generic_area_target_expands_area_scoped_ac_name():
    assert normalize_generic_area_target({"name": "空调", "area": "客厅"}) == {
        "name": "客厅空调",
        "area": "客厅",
        "domain": ["climate"],
    }


def test_normalize_generic_area_target_keeps_full_target_name():
    arguments = {"name": "客厅空调", "area": "客厅", "domain": ["climate"]}

    assert normalize_generic_area_target(arguments) == arguments


def test_normalize_generic_area_target_normalizes_matching_domain_string():
    assert normalize_generic_area_target(
        {"name": "空调", "area": "客厅", "domain": "climate"}
    ) == {
        "name": "客厅空调",
        "area": "客厅",
        "domain": ["climate"],
    }


def test_normalize_generic_area_target_keeps_conflicting_domain():
    arguments = {"name": "空调", "area": "客厅", "domain": ["light"]}

    assert normalize_generic_area_target(arguments) == arguments


def test_normalize_area_scoped_name_target_expands_unique_prefixed_entity_name():
    assert normalize_area_scoped_name_target(
        {"name": "吊灯", "area": "餐厅", "domain": ["light"]},
        ["餐厅吊灯", "餐厅壁灯"],
    ) == {"name": "餐厅吊灯", "area": "餐厅", "domain": ["light"]}


def test_normalize_area_scoped_name_target_keeps_full_entity_name():
    arguments = {"name": "餐厅吊灯", "area": "餐厅", "domain": ["light"]}

    assert (
        normalize_area_scoped_name_target(
            arguments,
            ["餐厅吊灯", "餐厅壁灯"],
        )
        == arguments
    )


def test_normalize_area_scoped_name_target_keeps_unmatched_short_name():
    arguments = {"name": "岛台灯组", "area": "餐厅", "domain": ["light"]}

    assert (
        normalize_area_scoped_name_target(
            arguments,
            ["餐厅吊灯", "餐厅壁灯"],
        )
        == arguments
    )


def test_normalize_area_scoped_name_target_uses_unique_phonetic_cover_candidate():
    assert normalize_area_scoped_name_target(
        {"name": "三联", "area": "主卧", "domain": ["cover"]},
        ["主卧窗帘", "主卧纱帘"],
    ) == {"name": "主卧纱帘", "area": "主卧", "domain": ["cover"]}


def test_normalize_area_scoped_name_target_keeps_ambiguous_phonetic_candidate():
    arguments = {"name": "三联", "area": "主卧", "domain": ["cover"]}

    assert (
        normalize_area_scoped_name_target(
            arguments,
            ["主卧纱帘", "主卧三联帘"],
        )
        == arguments
    )


def test_detects_ac_climate_turn_request():
    assert is_ac_climate_turn_request(
        "HassTurnOn",
        {"name": "空调", "domain": ["climate"]},
    )


@pytest.mark.parametrize(
    ("entity_name", "device_type"),
    [
        ("客厅空调", "air_conditioner"),
        ("次卧地暖", "floor_heating"),
        ("主卫浴霸", "bathroom_heater"),
        ("林内冷凝炉 采暖控制", "heating_boiler"),
        ("燃气锅炉", "heating_boiler"),
        ("采暖炉", "heating_boiler"),
    ],
)
def test_classifies_climate_entity_names_by_device_semantics(
    entity_name,
    device_type,
):
    assert climate_device_type_from_name(entity_name) == device_type


def test_all_air_conditioner_request_requires_explicit_all_word():
    assert is_all_air_conditioner_request({"name": "所有空调", "domain": ["climate"]})
    assert is_all_air_conditioner_request({"name": "全屋空调", "domain": ["climate"]})
    assert not is_all_air_conditioner_request({"name": "空调", "domain": ["climate"]})
    assert not is_all_air_conditioner_request({"domain": ["climate"]})


def test_floor_heating_and_boiler_are_not_ac_turn_requests():
    for name in ("所有地暖", "主卫浴霸", "林内冷凝炉 采暖控制"):
        assert not is_ac_climate_turn_request(
            "HassTurnOff",
            {"name": name, "domain": ["climate"]},
        )


def test_detects_domain_only_climate_turn_request_as_current_room_ac():
    assert is_ac_climate_turn_request(
        "HassTurnOff",
        {"domain": ["climate"]},
    )
    assert (
        ac_climate_turn_hvac_mode(
            "HassTurnOff",
            {"domain": ["climate"]},
        )
        == "off"
    )


def test_does_not_detect_domain_only_light_turn_request_as_ac():
    assert not is_ac_climate_turn_request(
        "HassTurnOff",
        {"domain": ["light"]},
    )


def test_ac_climate_turn_on_uses_cool_mode():
    assert (
        ac_climate_turn_hvac_mode(
            "HassTurnOn",
            {"name": "主卧空调", "area": "主卧", "domain": ["climate"]},
        )
        == "cool"
    )


def test_ac_climate_turn_off_uses_off_mode():
    assert (
        ac_climate_turn_hvac_mode(
            "HassTurnOff",
            {"name": "主卧空调", "area": "主卧", "domain": ["climate"]},
        )
        == "off"
    )


def test_ac_climate_turn_mode_ignores_floor_heating_target():
    arguments = {"name": "主卧地暖", "area": "主卧", "domain": ["climate"]}

    assert ac_climate_turn_hvac_mode(
        "HassTurnOn",
        arguments,
    ) is None


def test_custom_ac_control_is_disabled_by_default():
    assert not is_custom_ac_control_enabled({})
    assert build_ac_custom_control_tool_call(
        {},
        "climate.any_master_bedroom_ac",
        "cool",
        "主卧",
    ) is None


def test_build_ac_custom_control_tool_call_uses_configured_script_fields():
    assert build_ac_custom_control_tool_call(
        {
            "ac_control_mode": "custom",
            "ac_custom_tool_name": "my_ac_hvac_mode",
            "ac_custom_entity_field": "target_entities",
            "ac_custom_mode_field": "mode",
            "ac_custom_entity_format": "string_list",
        },
        "climate.any_master_bedroom_ac",
        "cool",
        "主卧",
    ) == (
        "my_ac_hvac_mode",
        {
            "target_entities": "['climate.any_master_bedroom_ac']",
            "mode": "cool",
        },
    )


def test_build_ac_custom_control_tool_call_supports_list_entity_format():
    assert build_ac_custom_control_tool_call(
        {
            "ac_control_mode": "custom",
            "ac_custom_tool_name": "my_ac_hvac_mode",
            "ac_custom_entity_format": "list",
        },
        "climate.any_master_bedroom_ac",
        "off",
        None,
    ) == (
        "my_ac_hvac_mode",
        {
            "entity_ids": ["climate.any_master_bedroom_ac"],
            "hvac_mode": "off",
        },
    )


def test_build_ac_custom_control_tool_call_supports_multiple_entities():
    assert build_ac_custom_control_tool_call(
        {
            "ac_control_mode": "custom",
            "ac_custom_tool_name": "my_ac_hvac_mode",
        },
        ["climate.livingroom_ac", "climate.master_bedroom_ac"],
        "off",
        None,
    ) == (
        "my_ac_hvac_mode",
        {
            "entity_ids": "['climate.livingroom_ac','climate.master_bedroom_ac']",
            "hvac_mode": "off",
        },
    )


def test_build_ac_custom_control_tool_call_rejects_missing_tool_name():
    assert build_ac_custom_control_tool_call(
        {"ac_control_mode": "custom"},
        "climate.any_master_bedroom_ac",
        "cool",
        "主卧",
    ) is None


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
        "climate.any_guest_bedroom_ac",
    ) == {
        "entity_ids": "['climate.any_guest_bedroom_ac']",
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
            "climate.any_guest_bedroom_ac",
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
            "climate.any_guest_bedroom_ac",
        )
        == arguments
    )


def test_rewrite_current_room_ac_context_query_entity_target_from_active_context():
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
        "GetLiveContext",
        {"name": "climate.vrf_livingroom"},
        active_context,
        "climate.any_guest_bedroom_ac",
    ) == {
        "name": "次卧空调",
        "area": "次卧",
        "domain": ["climate"],
    }


def test_rewrite_current_room_ac_context_query_keeps_explicit_room_target():
    active_context = parse_active_context(
        {
            "active": True,
            "device_id": "xiaozhi-device",
            "room_id": "guest_bedroom",
            "room_name": "次卧",
            "ha_area_id": "ci_wo",
        }
    )
    arguments = {"name": "climate.vrf_livingroom", "area": "客厅"}

    assert (
        rewrite_current_room_ac_entity_targets(
            "GetLiveContext",
            arguments,
            active_context,
            "climate.any_guest_bedroom_ac",
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
