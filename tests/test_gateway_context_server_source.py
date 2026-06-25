from pathlib import Path


COMPONENT_PATH = Path(__file__).parents[1] / "custom_components" / "ws_mcp_server"


def test_server_does_not_treat_entity_ids_as_gateway_bypass():
    server_source = (COMPONENT_PATH / "server.py").read_text(encoding="utf-8")

    assert "if has_explicit_room_or_area(arguments):" in server_source
    assert "has_explicit_tool_target(arguments)" not in server_source
    assert "direct_entity_target_without_room" in server_source


def test_server_returns_structured_status_when_active_context_is_missing():
    server_source = (COMPONENT_PATH / "server.py").read_text(encoding="utf-8")

    assert "active_context_unavailable" in server_source
    assert "ask_user_for_room" in server_source
    assert "Xiaozhi gateway active context unavailable" not in server_source


def test_server_injects_explicit_area_from_ha_area_registry():
    server_source = (COMPONENT_PATH / "server.py").read_text(encoding="utf-8")

    assert "area_registry" in server_source
    assert "inject_area_from_name_prefix" in server_source
    assert "_area_names(hass)" in server_source


def test_server_uses_native_climate_service_for_ac_turn_requests():
    server_source = (COMPONENT_PATH / "server.py").read_text(encoding="utf-8")

    assert "hass.services.async_call" in server_source
    assert '"set_hvac_mode"' in server_source
    assert "set_multiple_ac_hvac_mode" not in server_source


def test_websocket_transport_passes_config_entry_data_to_server():
    transport_source = (COMPONENT_PATH / "websocket_transport.py").read_text(
        encoding="utf-8"
    )

    assert "create_server(hass, llm_api_id, context, gateway_url, entry.data)" in (
        transport_source
    )


def test_server_includes_entity_aliases_in_area_name_candidates():
    server_source = (COMPONENT_PATH / "server.py").read_text(encoding="utf-8")

    assert "aliases" in server_source
    assert "area_entity_names" in server_source
