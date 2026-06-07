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
