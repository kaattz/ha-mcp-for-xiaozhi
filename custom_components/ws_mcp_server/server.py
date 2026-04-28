"""The Model Context Protocol Server implementation.

The Model Context Protocol python sdk defines a Server API that provides the
MCP message handling logic and error handling. The server implementation provided
here is independent of the lower level transport protocol.

See https://modelcontextprotocol.io/docs/concepts/architecture#implementation-example
"""

from collections.abc import Callable, Sequence
import asyncio
import json
import logging
from typing import Any

import aiohttp
from mcp import types
from mcp.server import Server
import voluptuous as vol
from voluptuous_openapi import convert

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm

from .const import DEFAULT_GATEWAY_URL, STATELESS_LLM_API
from .gateway_context import (
    GatewayContextError,
    build_context_payload,
    is_gateway_context_enabled,
    normalize_gateway_url,
    parse_active_context,
    should_inject_preferred_area_id,
)

_LOGGER = logging.getLogger(__name__)


def _format_tool(
    tool: llm.Tool, custom_serializer: Callable[[Any], Any] | None
) -> types.Tool:
    """Format tool specification."""
    input_schema = convert(tool.parameters, custom_serializer=custom_serializer)
    return types.Tool(
        name=tool.name,
        description=tool.description or "",
        inputSchema={
            "type": "object",
            "properties": input_schema["properties"],
        },
    )


async def create_server(
    hass: HomeAssistant,
    llm_api_id: str | list[str],
    llm_context: llm.LLMContext,
    gateway_url: str | None = DEFAULT_GATEWAY_URL,
) -> Server:
    """Create a new Model Context Protocol Server.

    A Model Context Protocol Server object is associated with a single session.
    The MCP SDK handles the details of the protocol.
    """
    #_LOGGER.error("mcp create server, llm_api_id:%s , llm_context:%s)",llm_api_id ,llm_context)
    #_LOGGER.error("mcp create server, STATELESS_LLM_API:%s )",STATELESS_LLM_API)
    #_LOGGER.error("mcp create server, llm.LLM_API_ASSIST:%s )",llm.LLM_API_ASSIST)
    if llm_api_id == STATELESS_LLM_API:
        llm_api_id = llm.LLM_API_ASSIST

    server = Server("home-assistant")
    #server = Server[Any]("home-assistant")

    async def get_api_instance() -> llm.APIInstance:
        """Get the LLM API selected."""
        # Backwards compatibility with old MCP Server config
        return await llm.async_get_api(hass, llm_api_id, llm_context)

    async def get_contextual_api_instance(
        tool_name: str, tool_arguments: dict
    ) -> tuple[llm.APIInstance, dict]:
        """Get the LLM API selected with active Xiaozhi room context."""
        active_context = await _fetch_active_context(gateway_url)
        context_payload = build_context_payload(
            base_context=llm_context.context,
            active_context=active_context,
            tool_arguments=tool_arguments,
        )
        contextual_llm_context = llm.LLMContext(
            platform=llm_context.platform,
            context=context_payload["context"],
            language=llm_context.language,
            assistant=llm_context.assistant,
            device_id=context_payload["device_id"],
        )
        llm_api = await llm.async_get_api(hass, llm_api_id, contextual_llm_context)
        context_payload = build_context_payload(
            base_context=llm_context.context,
            active_context=active_context,
            tool_arguments=tool_arguments,
            inject_preferred_area_id=should_inject_preferred_area_id(
                tool_name,
                _tool_supports_preferred_area_id(llm_api, tool_name),
            ),
        )
        if context_payload["tool_arguments"] != tool_arguments:
            _LOGGER.info(
                "Injected Xiaozhi room context: tool=%s room=%s area_id=%s",
                tool_name,
                active_context.room_name,
                active_context.ha_area_id,
            )
        return llm_api, context_payload["tool_arguments"]

    @server.list_prompts()  # type: ignore[no-untyped-call, misc]
    async def handle_list_prompts() -> list[types.Prompt]:
        llm_api = await get_api_instance()
        return [
            types.Prompt(
                name=llm_api.api.name,
                description=f"Default prompt for Home Assistant {llm_api.api.name} API",
            )
        ]

    @server.get_prompt()  # type: ignore[no-untyped-call, misc]
    async def handle_get_prompt(
        name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        llm_api = await get_api_instance()
        if name != llm_api.api.name:
            raise ValueError(f"Unknown prompt: {name}")

        return types.GetPromptResult(
            description=f"Default prompt for Home Assistant {llm_api.api.name} API",
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(
                        type="text",
                        text=llm_api.api_prompt,
                    ),
                )
            ],
        )

    @server.list_tools()  # type: ignore[no-untyped-call, misc]
    async def list_tools() -> list[types.Tool]:
        """List available time tools."""
        llm_api = await get_api_instance()
        _LOGGER.error("mcp list tools:%s )",llm_api.tools)
        return [_format_tool(tool, llm_api.custom_serializer) for tool in llm_api.tools]

    @server.call_tool()  # type: ignore[no-untyped-call, misc]
    async def call_tool(name: str, arguments: dict) -> Sequence[types.TextContent]:
        """Handle calling tools."""
        if is_gateway_context_enabled(gateway_url):
            try:
                llm_api, arguments = await get_contextual_api_instance(name, arguments)
            except GatewayContextError as e:
                raise HomeAssistantError(f"Xiaozhi gateway active context unavailable: {e}") from e
        else:
            llm_api = await get_api_instance()
        tool_input = llm.ToolInput(tool_name=name, tool_args=arguments)
        _LOGGER.error("Tool call: %s(%s)", tool_input.tool_name, tool_input.tool_args)

        try:
            tool_response = await llm_api.async_call_tool(tool_input)
        except (HomeAssistantError, vol.Invalid) as e:
            raise HomeAssistantError(f"Error calling tool: {e}") from e
        return [
            types.TextContent(
                type="text",
                text=json.dumps(tool_response),
            )
        ]

    return server


async def _fetch_active_context(gateway_url: str | None):
    gateway_url = normalize_gateway_url(gateway_url)
    if not gateway_url:
        raise GatewayContextError("gateway URL is empty")
    url = gateway_url + "/active-context"
    timeout = aiohttp.ClientTimeout(total=3)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise GatewayContextError(f"gateway returned HTTP {response.status}")
                return parse_active_context(await response.json())
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise GatewayContextError(str(e)) from e


def _tool_supports_preferred_area_id(llm_api: llm.APIInstance, tool_name: str) -> bool:
    for tool in llm_api.tools:
        if tool.name == tool_name:
            return _has_preferred_area_slot(tool)
    return False


def _has_preferred_area_slot(tool: llm.Tool) -> bool:
    extra_slots = getattr(tool, "extra_slots", None)
    if extra_slots and "preferred_area_id" in extra_slots:
        return True

    wrapped_tool = getattr(tool, "tool", None)
    if wrapped_tool is not None:
        return _has_preferred_area_slot(wrapped_tool)

    return False

