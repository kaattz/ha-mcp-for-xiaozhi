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

from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry, device_registry, entity_registry, llm

from .const import DEFAULT_GATEWAY_URL, STATELESS_LLM_API
from .gateway_context import (
    ActiveContextAmbiguousError,
    GatewayContextError,
    GATEWAY_ROOM_PROMPT,
    ac_climate_turn_hvac_mode,
    build_ac_custom_control_tool_call,
    build_context_payload,
    build_gateway_room_prompt,
    climate_device_type_from_name,
    CLIMATE_DEVICE_AIR_CONDITIONER,
    has_direct_entity_target,
    has_explicit_room_or_area,
    inject_area_from_name_prefix,
    is_ac_climate_turn_request,
    is_all_air_conditioner_request,
    is_custom_ac_control_enabled,
    is_gateway_context_enabled,
    normalize_area_scoped_name_target,
    normalize_generic_area_target,
    normalize_gateway_url,
    parse_active_context,
    rewrite_current_room_ac_entity_targets,
    should_fetch_gateway_context,
    should_inject_preferred_area_id,
    strip_room_metadata_for_direct_entity_target,
)
from .tool_schema import build_mcp_input_schema

_LOGGER = logging.getLogger(__name__)


def _format_tool(
    tool: llm.Tool,
    custom_serializer: Callable[[Any], Any] | None,
    gateway_context_enabled: bool = False,
) -> types.Tool:
    """Format tool specification."""
    input_schema = convert(tool.parameters, custom_serializer=custom_serializer)
    description = tool.description or ""
    if gateway_context_enabled and should_inject_preferred_area_id(tool.name, False):
        description = f"{description}\n\n{GATEWAY_ROOM_PROMPT}".strip()
    return types.Tool(
        name=tool.name,
        description=description,
        inputSchema=build_mcp_input_schema(
            input_schema,
            gateway_context_enabled=gateway_context_enabled,
        ),
    )


async def create_server(
    hass: HomeAssistant,
    llm_api_id: str | list[str],
    llm_context: llm.LLMContext,
    gateway_url: str | None = DEFAULT_GATEWAY_URL,
    ac_control_config: dict[str, Any] | None = None,
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

        api_prompt = llm_api.api_prompt
        if is_gateway_context_enabled(gateway_url):
            api_prompt = build_gateway_room_prompt(api_prompt)

        return types.GetPromptResult(
            description=f"Default prompt for Home Assistant {llm_api.api.name} API",
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(
                        type="text",
                        text=api_prompt,
                    ),
                )
            ],
        )

    @server.list_tools()  # type: ignore[no-untyped-call, misc]
    async def list_tools() -> list[types.Tool]:
        """List available time tools."""
        llm_api = await get_api_instance()
        _LOGGER.debug("MCP list tools count=%d", len(llm_api.tools))
        tools = [
            _format_tool(
                tool,
                llm_api.custom_serializer,
                is_gateway_context_enabled(gateway_url),
            )
            for tool in llm_api.tools
        ]
        return tools

    @server.call_tool()  # type: ignore[no-untyped-call, misc]
    async def call_tool(name: str, arguments: dict) -> Sequence[types.TextContent]:
        """Handle calling tools."""
        if is_gateway_context_enabled(gateway_url):
            if should_inject_preferred_area_id(name, False):
                arguments = inject_area_from_name_prefix(arguments, _area_names(hass))
            arguments = normalize_generic_area_target(arguments)
            arguments = normalize_area_scoped_name_target(
                arguments,
                _area_entity_names(
                    hass,
                    arguments.get("area"),
                    _domain_names(arguments),
                ),
            )
            if is_ac_climate_turn_request(name, arguments):
                domains = _domain_names(arguments) or ["climate"]
                if is_all_air_conditioner_request(arguments) and has_explicit_room_or_area(
                    arguments
                ):
                    entity_id = _area_air_conditioner_entity_ids(
                        hass,
                        arguments.get("area"),
                    )
                elif is_all_air_conditioner_request(arguments):
                    entity_id = _all_air_conditioner_entity_ids(hass)
                elif has_explicit_room_or_area(arguments):
                    entity_id = _single_named_area_entity_id(
                        hass,
                        arguments.get("area"),
                        arguments.get("name"),
                        domains,
                    ) or _single_area_air_conditioner_entity_id(
                        hass,
                        arguments.get("area"),
                    )
                else:
                    try:
                        active_context = await _fetch_active_context(gateway_url)
                    except ActiveContextAmbiguousError:
                        return _json_response(
                            {
                                "status": "active_context_ambiguous",
                                "reason": "multiple_active_contexts",
                            }
                        )
                    except GatewayContextError as e:
                        return _json_response(
                            {
                                "status": "active_context_unavailable",
                                "reason": str(e),
                                "action": "ask_user_for_room",
                            }
                        )
                    entity_id = _single_area_air_conditioner_entity_id(
                        hass,
                        active_context.ha_area_id,
                    ) or _single_area_air_conditioner_entity_id(
                        hass,
                        active_context.room_name,
                    )
                    arguments = {**arguments, "area": active_context.room_name}
                hvac_mode = ac_climate_turn_hvac_mode(
                    name,
                    arguments,
                    ac_control_config,
                )
                if not entity_id or hvac_mode is None:
                    return _json_response(
                        {
                            "status": "ac_target_unresolved",
                            "reason": (
                                "Unable to resolve exactly one air conditioner "
                                "entity from Home Assistant area and entity state."
                            ),
                            "action": "check_ha_area_and_entity_name",
                        }
                    )
                if is_custom_ac_control_enabled(ac_control_config):
                    custom_call = build_ac_custom_control_tool_call(
                        ac_control_config,
                        entity_id,
                        hvac_mode,
                        arguments.get("area")
                        if isinstance(arguments.get("area"), str)
                        else None,
                    )
                    if custom_call is None:
                        return _json_response(
                            {
                                "status": "ac_custom_tool_invalid",
                                "reason": (
                                    "Custom AC control is enabled but tool name "
                                    "or argument fields are incomplete."
                                ),
                                "action": "check_ac_custom_tool_config",
                            }
                        )
                    custom_tool_name, custom_arguments = custom_call
                    llm_api = await get_api_instance()
                    if not _has_tool(llm_api, custom_tool_name):
                        return _json_response(
                            {
                                "status": "ac_custom_tool_not_found",
                                "reason": (
                                    "Configured custom AC control tool is not "
                                    "exposed by the selected Home Assistant API."
                                ),
                                "tool": custom_tool_name,
                                "action": "check_ac_custom_tool_config",
                            }
                        )
                    custom_arguments = strip_room_metadata_for_direct_entity_target(
                        custom_arguments
                    )
                    try:
                        tool_response = await llm_api.async_call_tool(
                            llm.ToolInput(
                                tool_name=custom_tool_name,
                                tool_args=custom_arguments,
                            )
                        )
                    except (HomeAssistantError, vol.Invalid) as e:
                        return _json_response(
                            {
                                "success": False,
                                "error": (
                                    f"Error calling custom AC control tool "
                                    f"{custom_tool_name}: {e}"
                                ),
                            }
                        )
                    return _json_response(tool_response)
                try:
                    await _async_set_climate_hvac_mode(hass, entity_id, hvac_mode)
                except (HomeAssistantError, vol.Invalid) as e:
                    return _json_response(
                        {
                            "success": False,
                            "error": f"Error calling climate.set_hvac_mode: {e}",
                        }
                    )
                return _json_response(
                    {
                        "speech": {},
                        "response_type": "action_done",
                        "data": {
                            "success": [
                                {
                                    "name": arguments.get("name"),
                                    "type": "entity",
                                    "id": entity_id,
                                }
                            ],
                            "failed": [],
                        },
                    }
                )

            if has_direct_entity_target(arguments):
                if not has_explicit_room_or_area(arguments):
                    try:
                        active_context = await _fetch_active_context(gateway_url)
                    except ActiveContextAmbiguousError:
                        return [
                            types.TextContent(
                                type="text",
                                text=json.dumps(
                                    {
                                        "status": "active_context_ambiguous",
                                        "reason": "multiple_active_contexts",
                                    }
                                ),
                            )
                        ]
                    except GatewayContextError as e:
                        return [
                            types.TextContent(
                                type="text",
                                text=json.dumps(
                                    {
                                        "status": "active_context_unavailable",
                                        "reason": str(e),
                                        "action": "ask_user_for_room",
                                    }
                                ),
                            )
                        ]

                    rewritten_arguments = rewrite_current_room_ac_entity_targets(
                        name,
                        arguments,
                        active_context,
                        _single_area_air_conditioner_entity_id(
                            hass,
                            active_context.ha_area_id,
                        )
                        or _single_area_air_conditioner_entity_id(
                            hass,
                            active_context.room_name,
                        ),
                    )
                    if rewritten_arguments is arguments:
                        return [
                            types.TextContent(
                                type="text",
                                text=json.dumps(
                                    {
                                        "status": "direct_entity_target_without_room",
                                        "reason": (
                                            "Direct entity_id/entity_ids targets require "
                                            "an explicit room or area when Xiaozhi gateway "
                                            "room context is enabled."
                                        ),
                                        "action": (
                                            "retry_with_area_or_room_if_the_user_named_one"
                                        ),
                                    }
                                ),
                            )
                        ]

                    arguments = rewritten_arguments
                    _LOGGER.info(
                        "Rewrote AC entity target from Xiaozhi room context: "
                        "tool=%s room=%s area_id=%s",
                        name,
                        active_context.room_name,
                        active_context.ha_area_id,
                    )
                llm_api = await get_api_instance()
                arguments = strip_room_metadata_for_direct_entity_target(arguments)
            elif has_explicit_room_or_area(arguments):
                llm_api = await get_api_instance()
            else:
                llm_api = None
                needs_gateway_context = should_fetch_gateway_context(
                    name,
                    arguments,
                    supports_preferred_area_id=False,
                )
                if not needs_gateway_context:
                    llm_api = await get_api_instance()
                    needs_gateway_context = should_fetch_gateway_context(
                        name,
                        arguments,
                        supports_preferred_area_id=_tool_supports_preferred_area_id(
                            llm_api, name
                        ),
                    )
                if needs_gateway_context:
                    try:
                        llm_api, arguments = await get_contextual_api_instance(
                            name, arguments
                        )
                    except ActiveContextAmbiguousError:
                        return [
                            types.TextContent(
                                type="text",
                                text=json.dumps(
                                    {
                                        "status": "active_context_ambiguous",
                                        "reason": "multiple_active_contexts",
                                    }
                                ),
                            )
                        ]
                    except GatewayContextError as e:
                        return [
                            types.TextContent(
                                type="text",
                                text=json.dumps(
                                    {
                                        "status": "active_context_unavailable",
                                        "reason": str(e),
                                        "action": "ask_user_for_room",
                                    }
                                ),
                            )
                        ]
                if llm_api is None:
                    llm_api = await get_api_instance()
        else:
            llm_api = await get_api_instance()
        tool_input = llm.ToolInput(tool_name=name, tool_args=arguments)
        _LOGGER.debug("MCP tool call: %s", tool_input.tool_name)

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


def _json_response(payload: dict[str, Any]) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload))]


async def _async_set_climate_hvac_mode(
    hass: HomeAssistant,
    entity_id: str | list[str],
    hvac_mode: str,
) -> None:
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_hvac_mode",
        {
            ATTR_ENTITY_ID: entity_id,
            "hvac_mode": hvac_mode,
        },
        blocking=True,
    )


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
    if not _has_tool(llm_api, tool_name):
        return False
    for tool in llm_api.tools:
        if tool.name == tool_name:
            return _has_preferred_area_slot(tool)
    return False


def _has_tool(llm_api: llm.APIInstance, tool_name: str) -> bool:
    for tool in llm_api.tools:
        if tool.name == tool_name:
            return True
    return False


def _area_names(hass: HomeAssistant) -> list[str]:
    registry = area_registry.async_get(hass)
    return [area.name for area in registry.async_list_areas()]


def _area_entity_names(
    hass: HomeAssistant,
    area_name: Any,
    domains: list[str],
) -> list[str]:
    registry = entity_registry.async_get(hass)
    area_entity_names = []
    for state in _area_entity_states(hass, area_name, domains):
        area_entity_names.append(state.name)
        entity_entry = registry.async_get(state.entity_id)
        aliases = getattr(entity_entry, "aliases", None) if entity_entry else None
        if aliases:
            area_entity_names.extend(
                alias for alias in aliases if isinstance(alias, str) and alias
            )
    return area_entity_names


def _single_named_area_entity_id(
    hass: HomeAssistant,
    area_name: Any,
    entity_name: Any,
    domains: list[str],
) -> str | None:
    if not isinstance(entity_name, str) or not entity_name.strip():
        return None

    normalized_entity_name = entity_name.strip()
    matches = [
        state.entity_id
        for state in _area_entity_states(hass, area_name, domains)
        if state.name == normalized_entity_name
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _single_area_air_conditioner_entity_id(
    hass: HomeAssistant,
    area_name: Any,
) -> str | None:
    area = _area_by_name_or_id(hass, area_name)
    if area is None:
        return None

    states = _area_entity_states(hass, area.id, ["climate"])
    exact_name = f"{area.name}空调"
    exact_matches = [state.entity_id for state in states if state.name == exact_name]
    if len(exact_matches) == 1:
        return exact_matches[0]

    ac_matches = _area_air_conditioner_entity_ids(hass, area.id)
    if len(ac_matches) != 1:
        return None
    return ac_matches[0]


def _area_air_conditioner_entity_ids(
    hass: HomeAssistant,
    area_name: Any,
) -> list[str]:
    return [
        state.entity_id
        for state in _area_entity_states(hass, area_name, ["climate"])
        if climate_device_type_from_name(state.name) == CLIMATE_DEVICE_AIR_CONDITIONER
    ]


def _all_air_conditioner_entity_ids(hass: HomeAssistant) -> list[str]:
    return [
        state.entity_id
        for state in hass.states.async_all("climate")
        if climate_device_type_from_name(state.name) == CLIMATE_DEVICE_AIR_CONDITIONER
    ]


def _area_entity_states(
    hass: HomeAssistant,
    area_name: Any,
    domains: list[str],
):
    if not isinstance(area_name, str) or not area_name.strip():
        return []

    area_id = _area_id_by_name(hass, area_name)
    if area_id is None:
        return []

    states = (
        hass.states.async_all(domains[0])
        if len(domains) == 1
        else hass.states.async_all()
    )
    domain_set = set(domains)
    area_states = []
    for state in states:
        entity_domain = state.entity_id.split(".", 1)[0]
        if domain_set and entity_domain not in domain_set:
            continue
        if _entity_area_id(hass, state.entity_id) == area_id:
            area_states.append(state)
    return area_states


def _area_id_by_name(hass: HomeAssistant, area_name: str) -> str | None:
    area = _area_by_name_or_id(hass, area_name)
    if area is None:
        return None
    return area.id


def _area_by_name_or_id(hass: HomeAssistant, area_name: Any):
    if not isinstance(area_name, str):
        return None
    normalized_area_name = area_name.strip()
    registry = area_registry.async_get(hass)
    for area in registry.async_list_areas():
        if area.name == normalized_area_name or area.id == normalized_area_name:
            return area
    return None


def _entity_area_id(hass: HomeAssistant, entity_id: str) -> str | None:
    entity_entry = entity_registry.async_get(hass).async_get(entity_id)
    if entity_entry is None:
        return None
    if entity_entry.area_id:
        return entity_entry.area_id
    if entity_entry.device_id:
        device_entry = device_registry.async_get(hass).async_get(entity_entry.device_id)
        if device_entry is not None:
            return device_entry.area_id
    return None


def _domain_names(arguments: dict) -> list[str]:
    domain = arguments.get("domain")
    if isinstance(domain, str) and domain:
        return [domain]
    if isinstance(domain, list):
        return [item for item in domain if isinstance(item, str) and item]
    return []


def _has_preferred_area_slot(tool: llm.Tool) -> bool:
    extra_slots = getattr(tool, "extra_slots", None)
    if extra_slots and "preferred_area_id" in extra_slots:
        return True

    wrapped_tool = getattr(tool, "tool", None)
    if wrapped_tool is not None:
        return _has_preferred_area_slot(wrapped_tool)

    return False

