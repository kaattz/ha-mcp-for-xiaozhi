from pathlib import Path


COMPONENT_PATH = Path(__file__).parents[1] / "custom_components" / "ws_mcp_server"


def test_server_does_not_register_pending_confirmation_tools():
    server_source = (COMPONENT_PATH / "server.py").read_text(encoding="utf-8")

    assert "pending_confirmation" not in server_source
    assert "GetPendingConfirmation" not in server_source
    assert "ResolvePendingConfirmation" not in server_source


def test_pending_confirmation_helper_is_removed():
    assert not (COMPONENT_PATH / "pending_confirmation.py").exists()
