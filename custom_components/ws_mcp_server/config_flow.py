import voluptuous as vol
from typing import Any
import logging
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.helpers import llm, selector
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import CONF_GATEWAY_URL, DEFAULT_GATEWAY_URL, DOMAIN

CONF_CLIENT_ENDPOINT = "client_endpoint"
CONF_MODE = "control_mode"
MORE_INFO_URL = "https://www.home-assistant.io/integrations/mcp_server/#configuration"
DEFAULT_NAME = "WebSocket MCP Server"
_LOGGER = logging.getLogger(__name__)



class WsMCPServerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MCP Server."""
    VERSION = 1
    SUPPORT_MULTIPLE_ENTRIES = True  # 添加这行来支持多实例

    def _get_llm_apis(self) -> dict[str, str]:
        return {api.id: api.name for api in llm.async_get_apis(self.hass)}

    def _entry_unique_id(self, user_input: dict[str, Any]) -> str:
        llm_api_ids = ",".join(user_input[CONF_LLM_HASS_API])
        return f"{llm_api_ids}_{user_input[CONF_CLIENT_ENDPOINT]}"

    def _entry_title(self, user_input: dict[str, Any], llm_apis: dict[str, str]) -> str:
        return ", ".join(llm_apis[api_id] for api_id in user_input[CONF_LLM_HASS_API])

    def _data_schema(
        self,
        llm_apis: dict[str, str],
        suggested_values: dict[str, Any] | None = None,
    ) -> vol.Schema:
        schema = vol.Schema(
            {
                vol.Required(CONF_CLIENT_ENDPOINT): selector.TextSelector(),
                vol.Optional(
                    CONF_GATEWAY_URL,
                    default=DEFAULT_GATEWAY_URL,
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_LLM_HASS_API,
                    default=[llm.LLM_API_ASSIST],
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                label=name,
                                value=llm_api_id,
                            )
                            for llm_api_id, name in llm_apis.items()
                        ],
                        multiple=True,
                    )
                ),
            }
        )
        if suggested_values is None:
            return schema
        return self.add_suggested_values_to_schema(schema, suggested_values)

    def _has_duplicate_unique_id(self, unique_id: str, current_entry_id: str) -> bool:
        return any(
            entry.entry_id != current_entry_id and entry.unique_id == unique_id
            for entry in self._async_current_entries(include_ignore=False)
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        _LOGGER.debug("mcp  LLM APIs available: %s",  llm.async_get_apis(self.hass))

        llm_apis = self._get_llm_apis()
        #llm_apis = {api.id: api.name for api in await llm.async_get_apis(self.hass)}
        if user_input is not None:
            # 验证配置是否重复
            await self.async_set_unique_id(self._entry_unique_id(user_input))
            self._abort_if_unique_id_configured()

            if not user_input[CONF_LLM_HASS_API]:
                errors[CONF_LLM_HASS_API] = "llm_api_required"
            else:
                return self.async_create_entry(
                    title=self._entry_title(user_input, llm_apis),
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._data_schema(llm_apis),
            description_placeholders={"more_info_url": MORE_INFO_URL},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle editing an existing config entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        llm_apis = self._get_llm_apis()

        if user_input is not None:
            if not user_input[CONF_LLM_HASS_API]:
                errors[CONF_LLM_HASS_API] = "llm_api_required"
            else:
                unique_id = self._entry_unique_id(user_input)
                if self._has_duplicate_unique_id(unique_id, entry.entry_id):
                    errors["base"] = "already_configured"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=unique_id,
                        title=self._entry_title(user_input, llm_apis),
                        data=user_input,
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._data_schema(llm_apis, user_input or dict(entry.data)),
            description_placeholders={"more_info_url": MORE_INFO_URL},
            errors=errors,
        )




