"""Constants for the Model Context Protocol Server integration."""

DOMAIN = "ws_mcp_server"
TITLE = "WebSocket Model Context Protocol Server"
CONF_GATEWAY_URL = "gateway_url"
DEFAULT_GATEWAY_URL = "http://127.0.0.1:8125"
# The Stateless API is no longer registered explicitly, but this name may still exist in the
# users config entry.
STATELESS_LLM_API = "stateless_assist"

