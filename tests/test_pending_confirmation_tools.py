import importlib.util
import sys
from pathlib import Path

import pytest


COMPONENT_PATH = Path(__file__).parents[1] / "custom_components" / "ws_mcp_server"


def load_module(name: str):
    module_path = COMPONENT_PATH / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gateway_context = load_module("gateway_context")
pending_confirmation = load_module("pending_confirmation")

ActiveGatewayContext = gateway_context.ActiveGatewayContext
PENDING_CONFIRMATION_EVENT = pending_confirmation.PENDING_CONFIRMATION_EVENT
handle_pending_confirmation_tool = pending_confirmation.handle_pending_confirmation_tool
is_pending_confirmation_tool = pending_confirmation.is_pending_confirmation_tool
pending_confirmation_tool_specs = pending_confirmation.pending_confirmation_tool_specs


class FakeBus:
    def __init__(self) -> None:
        self.events = []

    def async_fire(self, event_type, event_data):
        self.events.append((event_type, event_data))


class FakeHass:
    def __init__(self) -> None:
        self.bus = FakeBus()


@pytest.mark.asyncio
async def test_pending_tool_specs_define_get_and_resolve_tools():
    specs = pending_confirmation_tool_specs()

    assert [spec["name"] for spec in specs] == [
        "GetPendingConfirmation",
        "ResolvePendingConfirmation",
    ]
    assert is_pending_confirmation_tool("GetPendingConfirmation")
    assert is_pending_confirmation_tool("ResolvePendingConfirmation")
    assert not is_pending_confirmation_tool("HassTurnOn")
    assert specs[1]["inputSchema"]["properties"]["decision"]["enum"] == ["yes", "no"]


@pytest.mark.asyncio
async def test_get_pending_confirmation_queries_gateway_active_pending():
    calls = []

    async def request_json(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {
            "active": True,
            "confirmation_id": "confirm-1",
            "prompt": "是否打开空调？",
            "room_id": "living_room",
        }

    result = await handle_pending_confirmation_tool(
        "GetPendingConfirmation",
        {},
        gateway_url="http://gateway:8125",
        active_context=ActiveGatewayContext(
            device_id="device-1",
            room_id="living_room",
            room_name="客厅",
            ha_area_id="living_room",
        ),
        hass=FakeHass(),
        request_json=request_json,
    )

    assert result["active"] is True
    assert result["confirmation_id"] == "confirm-1"
    assert calls == [
        (
            "GET",
            "http://gateway:8125/pending-confirmations/active",
            {"params": {"device_id": "device-1", "room_id": "living_room"}},
        )
    ]


@pytest.mark.asyncio
async def test_resolve_pending_confirmation_returns_no_pending_without_event():
    async def request_json(method, url, **kwargs):
        return {"active": False, "status": "no_pending_confirmation"}

    hass = FakeHass()
    result = await handle_pending_confirmation_tool(
        "ResolvePendingConfirmation",
        {"decision": "yes"},
        gateway_url="http://gateway:8125",
        active_context=ActiveGatewayContext(
            device_id="device-1",
            room_id="living_room",
            room_name="客厅",
            ha_area_id="living_room",
        ),
        hass=hass,
        request_json=request_json,
    )

    assert result == {"active": False, "status": "no_pending_confirmation"}
    assert hass.bus.events == []


@pytest.mark.asyncio
async def test_pending_confirmation_tool_returns_gateway_unavailable_on_request_failure():
    async def request_json(method, url, **kwargs):
        raise pending_confirmation.aiohttp.ClientError("gateway down")

    hass = FakeHass()
    result = await handle_pending_confirmation_tool(
        "GetPendingConfirmation",
        {},
        gateway_url="http://gateway:8125",
        active_context=ActiveGatewayContext(
            device_id="device-1",
            room_id="living_room",
            room_name="客厅",
            ha_area_id="living_room",
        ),
        hass=hass,
        request_json=request_json,
    )

    assert result == {"status": "gateway_unavailable"}
    assert hass.bus.events == []


@pytest.mark.asyncio
async def test_resolve_pending_confirmation_fires_ha_event_on_success():
    calls = []

    async def request_json(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return {
                "active": True,
                "confirmation_id": "confirm-1",
                "device_id": "device-1",
                "room_id": "living_room",
            }
        return {
            "confirmation_id": "confirm-1",
            "status": "confirmed",
            "decision": "yes",
            "device_id": "device-1",
            "room_id": "living_room",
            "metadata": {"automation": "hot_room"},
        }

    hass = FakeHass()
    result = await handle_pending_confirmation_tool(
        "ResolvePendingConfirmation",
        {"decision": "yes"},
        gateway_url="http://gateway:8125",
        active_context=ActiveGatewayContext(
            device_id="device-1",
            room_id="living_room",
            room_name="客厅",
            ha_area_id="living_room",
        ),
        hass=hass,
        request_json=request_json,
    )

    assert result["status"] == "confirmed"
    assert calls[1] == (
        "POST",
        "http://gateway:8125/pending-confirmations/confirm-1/resolve",
        {
            "json": {
                "decision": "yes",
                "device_id": "device-1",
                "room_id": "living_room",
                "source": "xiaozhi_mcp",
            }
        },
    )
    assert hass.bus.events == [
        (
            PENDING_CONFIRMATION_EVENT,
            {
                "confirmation_id": "confirm-1",
                "status": "confirmed",
                "decision": "yes",
                "device_id": "device-1",
                "room_id": "living_room",
                "metadata": {"automation": "hot_room"},
            },
        )
    ]


def test_server_registers_and_intercepts_pending_tools():
    server_source = (COMPONENT_PATH / "server.py").read_text(encoding="utf-8")

    assert "pending_confirmation_tool_specs" in server_source
    assert "is_pending_confirmation_tool(name)" in server_source
    assert "handle_pending_confirmation_tool" in server_source
    assert "active_context_unavailable" in server_source
    assert "_LOGGER.debug(\"MCP list tools count=%d\"" in server_source
    assert "_LOGGER.debug(\"MCP tool call: %s\"" in server_source
    assert "tool_input.tool_args)" not in server_source
