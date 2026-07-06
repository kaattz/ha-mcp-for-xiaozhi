"""Helpers for Xiaozhi gateway room context."""

from __future__ import annotations

from dataclasses import dataclass
import re
from difflib import SequenceMatcher
from typing import Any

from pypinyin import Style, lazy_pinyin


ROOM_OR_AREA_KEYS = {"room", "room_id", "area", "area_id"}
ENTITY_TARGET_KEYS = {"entity_id", "entity_ids"}
HOME_ASSISTANT_INTENT_TOOL_PREFIX = "Hass"
MULTIPLE_ACTIVE_CONTEXTS = "multiple_active_contexts"
DEFAULT_GATEWAY_PORT = 8125
ACTIVE_AREA_TOOL_NAMES = frozenset(
    (
        "GetLiveContext",
        "HassLightSet",
        "HassSetPosition",
        "HassStopMoving",
        "HassTurnOff",
        "HassTurnOn",
    )
)
CONF_AC_CONTROL_MODE = "ac_control_mode"
CONF_AC_TURN_ON_HVAC_MODE = "ac_turn_on_hvac_mode"
CONF_AC_CUSTOM_TOOL_NAME = "ac_custom_tool_name"
CONF_AC_CUSTOM_ENTITY_FIELD = "ac_custom_entity_field"
CONF_AC_CUSTOM_MODE_FIELD = "ac_custom_mode_field"
CONF_AC_CUSTOM_ENTITY_FORMAT = "ac_custom_entity_format"
AC_CONTROL_MODE_NATIVE = "native"
AC_CONTROL_MODE_CUSTOM = "custom"
AC_ENTITY_FORMAT_STRING_LIST = "string_list"
AC_ENTITY_FORMAT_LIST = "list"
AC_ENTITY_FORMAT_STRING = "string"
DEFAULT_AC_TURN_ON_HVAC_MODE = "cool"
DEFAULT_AC_CUSTOM_ENTITY_FIELD = "entity_ids"
DEFAULT_AC_CUSTOM_MODE_FIELD = "hvac_mode"
DEFAULT_AC_CUSTOM_ENTITY_FORMAT = AC_ENTITY_FORMAT_STRING_LIST
CLIMATE_DEVICE_AIR_CONDITIONER = "air_conditioner"
CLIMATE_DEVICE_FLOOR_HEATING = "floor_heating"
CLIMATE_DEVICE_BATHROOM_HEATER = "bathroom_heater"
CLIMATE_DEVICE_HEATING_BOILER = "heating_boiler"
CLIMATE_DEVICE_KEYWORDS = (
    (
        CLIMATE_DEVICE_HEATING_BOILER,
        ("采暖炉", "锅炉", "采暖控制", "冷凝炉"),
    ),
    (CLIMATE_DEVICE_FLOOR_HEATING, ("地暖",)),
    (CLIMATE_DEVICE_BATHROOM_HEATER, ("浴霸",)),
    (CLIMATE_DEVICE_AIR_CONDITIONER, ("空调",)),
)
ALL_TARGET_WORDS = ("所有", "全部", "全屋")
PHONETIC_MATCH_MIN_SCORE = 0.78
PHONETIC_MATCH_MIN_GAP = 0.15
POSITION_MATCH_BONUS = 0.10
POSITION_MISMATCH_PENALTY = 0.18
NEAR_INITIAL_GROUPS = (
    frozenset(("s", "sh")),
    frozenset(("z", "zh")),
    frozenset(("c", "ch")),
    frozenset(("l", "n")),
    frozenset(("f", "h")),
    frozenset(("r", "l")),
)
NEAR_FINAL_GROUPS = (
    frozenset(("an", "ang")),
    frozenset(("en", "eng")),
    frozenset(("in", "ing")),
)
POSITION_TOKEN_GROUPS = {
    "左": frozenset(("左", "佐", "坐", "做", "走")),
    "右": frozenset(("右", "又", "有", "幼")),
}
POSITION_PHRASE_REPLACEMENTS = (
    ("左手边的", "左"),
    ("左手边", "左"),
    ("左边的", "左"),
    ("左边", "左"),
    ("左侧的", "左"),
    ("左侧", "左"),
    ("左面的", "左"),
    ("左面", "左"),
    ("右手边的", "右"),
    ("右手边", "右"),
    ("右边的", "右"),
    ("右边", "右"),
    ("右侧的", "右"),
    ("右侧", "右"),
    ("右面的", "右"),
    ("右面", "右"),
)
GENERIC_AREA_TARGET_DOMAINS = {
    "空调": "climate",
    "地暖": "climate",
    "浴霸": "climate",
    "窗帘": "cover",
    "纱帘": "cover",
    "百叶帘": "cover",
}
AC_TURN_TOOL_HVAC_MODES = {
    "HassTurnOn": DEFAULT_AC_TURN_ON_HVAC_MODE,
    "HassTurnOff": "off",
}
GATEWAY_ROOM_PROMPT = (
    "Xiaozhi gateway room context is enabled. When the user does not explicitly "
    "name a room or area, still call the Home Assistant intent tool. Do not ask "
    "which room or area first. The MCP server will inject preferred_area_id for "
    "the currently active Xiaozhi room. If the tool result status is "
    "active_context_unavailable or direct_entity_target_without_room, do not "
    "claim the action or check succeeded; ask which room or area the user means. "
    "If the user names an area together with "
    "a device, pass both area and name to the Home Assistant intent tool. For "
    "example, for 'turn on the living room chandelier', call HassTurnOn with "
    "area='living room' and name='chandelier'. If the user explicitly names a "
    "room or area, preserve that explicit target. For entity_id/entity_ids "
    "tools, include area or room metadata when the user explicitly named a room "
    "or area. If the user did not name a room or area, do not assume a fixed "
    "room; the MCP server will resolve supported current-room AC requests from "
    "the active Xiaozhi room context. For air conditioner turn-on or turn-off "
    "requests, pass the target as a normal Home Assistant intent tool call with "
    "name='空调', area when known, and domain='climate'; do not pass only "
    "domain='climate'. If only domain='climate' is passed to a climate turn "
    "tool, the MCP server treats it as a current-room air conditioner request, "
    "not a whole-home climate request. Air conditioners, floor heating, bathroom "
    "heaters, and boilers/heating controls are separate device categories even "
    "when Home Assistant exposes them all as climate entities. The MCP server "
    "will call "
    "Home Assistant's native climate.set_hvac_mode service so turning on an air "
    "conditioner means cooling, not Home Assistant's previous climate mode."
)


class GatewayContextError(RuntimeError):
    """Raised when the gateway cannot provide a usable active context."""


class ActiveContextAmbiguousError(GatewayContextError):
    """Raised when more than one Xiaozhi room context is active."""


@dataclass(frozen=True)
class ActiveGatewayContext:
    device_id: str
    room_id: str
    room_name: str
    ha_area_id: str
    ha_device_id: str | None = None


def normalize_gateway_url(gateway_url: str | None) -> str:
    gateway_url = (gateway_url or "").strip().rstrip("/")
    if not gateway_url:
        return ""

    if "://" not in gateway_url:
        host, separator, path = gateway_url.partition("/")
        if ":" not in host:
            host = f"{host}:{DEFAULT_GATEWAY_PORT}"
        gateway_url = f"http://{host}{separator}{path}"

    return gateway_url


def is_gateway_context_enabled(gateway_url: str | None) -> bool:
    return bool(normalize_gateway_url(gateway_url))


def should_inject_preferred_area_id(
    tool_name: str, supports_preferred_area_id: bool
) -> bool:
    return supports_preferred_area_id or tool_name.rsplit("__", 1)[-1].startswith(
        HOME_ASSISTANT_INTENT_TOOL_PREFIX
    )


def should_fetch_gateway_context(
    tool_name: str,
    arguments: dict[str, Any],
    supports_preferred_area_id: bool,
) -> bool:
    if has_explicit_room_or_area(arguments):
        return False
    if has_direct_entity_target(arguments):
        return False
    return should_inject_preferred_area_id(tool_name, supports_preferred_area_id)


def should_inject_active_area(tool_name: str, arguments: dict[str, Any]) -> bool:
    if has_explicit_room_or_area(arguments):
        return False
    if has_direct_entity_target(arguments):
        return False
    if is_all_target_request(arguments):
        return False
    return tool_name.rsplit("__", 1)[-1] in ACTIVE_AREA_TOOL_NAMES


def inject_active_area(
    tool_name: str,
    arguments: dict[str, Any],
    active_context: ActiveGatewayContext,
) -> dict[str, Any]:
    if not should_inject_active_area(tool_name, arguments):
        return arguments
    return {**arguments, "area": active_context.room_name}


def build_gateway_room_prompt(base_prompt: str) -> str:
    return f"{base_prompt}\n\n{GATEWAY_ROOM_PROMPT}"


def parse_active_context(payload: dict[str, Any]) -> ActiveGatewayContext:
    if not payload.get("active"):
        if payload.get("status") == MULTIPLE_ACTIVE_CONTEXTS:
            raise ActiveContextAmbiguousError("multiple active Xiaozhi room contexts")
        raise GatewayContextError("No active Xiaozhi room context")

    for key in ("device_id", "room_id", "room_name", "ha_area_id"):
        if not payload.get(key):
            raise GatewayContextError(f"Active Xiaozhi room context missing {key}")

    return ActiveGatewayContext(
        device_id=str(payload["device_id"]),
        room_id=str(payload["room_id"]),
        room_name=str(payload["room_name"]),
        ha_area_id=str(payload["ha_area_id"]),
        ha_device_id=str(payload["ha_device_id"]) if payload.get("ha_device_id") else None,
    )


def has_explicit_room_or_area(arguments: dict[str, Any]) -> bool:
    for key, value in arguments.items():
        if key in ROOM_OR_AREA_KEYS and value:
            return True
        if isinstance(value, dict) and has_explicit_room_or_area(value):
            return True
    return False


def has_explicit_tool_target(arguments: dict[str, Any]) -> bool:
    return has_explicit_room_or_area(arguments) or has_direct_entity_target(arguments)


def inject_area_from_name_prefix(
    arguments: dict[str, Any],
    area_names: list[str],
) -> dict[str, Any]:
    if has_explicit_room_or_area(arguments):
        return arguments

    name = arguments.get("name")
    if not isinstance(name, str) or not name:
        return arguments

    area_name = _find_longest_area_name_prefix(name, area_names)
    if area_name is None:
        return arguments

    rewritten_arguments = dict(arguments)
    rewritten_arguments["area"] = area_name
    return rewritten_arguments


def normalize_generic_area_target(arguments: dict[str, Any]) -> dict[str, Any]:
    name = arguments.get("name")
    area = arguments.get("area")
    if not isinstance(name, str) or not isinstance(area, str):
        return arguments

    normalized_name = name.strip()
    normalized_area = area.strip()
    if not normalized_name or not normalized_area:
        return arguments

    domain = GENERIC_AREA_TARGET_DOMAINS.get(normalized_name)
    if domain is None:
        return arguments

    if not _domain_matches(arguments.get("domain"), domain):
        return arguments

    rewritten_arguments = dict(arguments)
    rewritten_arguments["name"] = f"{normalized_area}{normalized_name}"
    if not arguments.get("domain") or isinstance(arguments.get("domain"), str):
        rewritten_arguments["domain"] = [domain]
    return rewritten_arguments


def normalize_area_scoped_name_target(
    arguments: dict[str, Any],
    area_entity_names: list[str],
) -> dict[str, Any]:
    name = arguments.get("name")
    area = arguments.get("area")
    if not isinstance(name, str) or not isinstance(area, str):
        return arguments

    normalized_name = name.strip()
    normalized_area = area.strip()
    if not normalized_name or not normalized_area:
        return arguments

    normalized_candidates = {
        entity_name.strip()
        for entity_name in area_entity_names
        if isinstance(entity_name, str) and entity_name.strip()
    }
    if normalized_name in normalized_candidates:
        return arguments

    prefixed_name = f"{normalized_area}{normalized_name}"
    matches = [
        entity_name
        for entity_name in normalized_candidates
        if entity_name == prefixed_name
    ]
    matched_name = matches[0] if len(matches) == 1 else None
    if len(matches) != 1:
        matched_name = _unique_phonetic_area_match(
            normalized_name,
            normalized_area,
            normalized_candidates,
        )
        if matched_name is None:
            return arguments

    rewritten_arguments = dict(arguments)
    rewritten_arguments["name"] = matched_name
    return rewritten_arguments


def is_ac_climate_turn_request(tool_name: str, arguments: dict[str, Any]) -> bool:
    if _ac_turn_hvac_mode(tool_name) is None:
        return False
    if not _domain_matches(arguments.get("domain"), "climate"):
        return False
    name = arguments.get("name")
    if not isinstance(name, str) or not name.strip():
        return not has_direct_entity_target(arguments)
    return climate_device_type_from_name(name) == CLIMATE_DEVICE_AIR_CONDITIONER


def climate_device_type_from_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    if not normalized_value:
        return None
    for device_type, keywords in CLIMATE_DEVICE_KEYWORDS:
        if any(keyword in normalized_value for keyword in keywords):
            return device_type
    return None


def is_all_air_conditioner_request(arguments: dict[str, Any]) -> bool:
    name = arguments.get("name")
    if (
        not isinstance(name, str)
        or climate_device_type_from_name(name) != CLIMATE_DEVICE_AIR_CONDITIONER
    ):
        return False
    return any(word in name for word in ALL_TARGET_WORDS)


def is_all_target_request(arguments: dict[str, Any]) -> bool:
    name = arguments.get("name")
    return isinstance(name, str) and any(word in name for word in ALL_TARGET_WORDS)


def ac_climate_turn_hvac_mode(
    tool_name: str,
    arguments: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> str | None:
    if not is_ac_climate_turn_request(tool_name, arguments):
        return None
    hvac_mode = _ac_turn_hvac_mode(tool_name)
    if tool_name.rsplit("__", 1)[-1] != "HassTurnOn":
        return hvac_mode
    return _non_empty_config_value(
        config or {},
        CONF_AC_TURN_ON_HVAC_MODE,
        hvac_mode or DEFAULT_AC_TURN_ON_HVAC_MODE,
    )


def is_custom_ac_control_enabled(config: dict[str, Any] | None) -> bool:
    return (config or {}).get(CONF_AC_CONTROL_MODE) == AC_CONTROL_MODE_CUSTOM


def build_ac_custom_control_tool_call(
    config: dict[str, Any] | None,
    entity_id: str | list[str],
    hvac_mode: str,
    _area: str | None,
) -> tuple[str, dict[str, Any]] | None:
    config = config or {}
    if not is_custom_ac_control_enabled(config):
        return None

    tool_name = _non_empty_config_value(config, CONF_AC_CUSTOM_TOOL_NAME, "")
    entity_field = _non_empty_config_value(
        config,
        CONF_AC_CUSTOM_ENTITY_FIELD,
        DEFAULT_AC_CUSTOM_ENTITY_FIELD,
    )
    mode_field = _non_empty_config_value(
        config,
        CONF_AC_CUSTOM_MODE_FIELD,
        DEFAULT_AC_CUSTOM_MODE_FIELD,
    )
    if not tool_name or not entity_field or not mode_field:
        return None

    arguments: dict[str, Any] = {
        entity_field: _format_ac_custom_entity_value(
            entity_id,
            _non_empty_config_value(
                config,
                CONF_AC_CUSTOM_ENTITY_FORMAT,
                DEFAULT_AC_CUSTOM_ENTITY_FORMAT,
            ),
        ),
        mode_field: hvac_mode,
    }
    return tool_name, arguments


def _domain_matches(value: Any, expected_domain: str) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == expected_domain
    if isinstance(value, list):
        return expected_domain in value
    return False


def _unique_phonetic_area_match(
    name: str,
    area: str,
    candidates: set[str],
) -> str | None:
    target_variants = _name_variants_without_area(name, area)
    candidate_groups = _group_area_candidates_by_unprefixed_name(candidates, area)
    candidate_variants = {
        key: _candidate_group_variants(group, area)
        for key, group in candidate_groups.items()
    }
    if _target_is_literal_candidate_part(target_variants, candidate_variants):
        return None

    scored_matches = sorted(
        (
            (
                _adjust_phonetic_score_for_position(
                    max(
                        _phonetic_phrase_similarity(target_variant, candidate_variant)
                        for target_variant in target_variants
                        for candidate_variant in variants
                    ),
                    target_variants,
                    variants,
                ),
                key,
            )
            for key, variants in candidate_variants.items()
        ),
        reverse=True,
    )
    if not scored_matches:
        return None

    top_score, top_candidate = scored_matches[0]
    second_score = scored_matches[1][0] if len(scored_matches) > 1 else 0.0
    if (
        top_score < PHONETIC_MATCH_MIN_SCORE
        or top_score - second_score < PHONETIC_MATCH_MIN_GAP
    ):
        return None
    return _preferred_area_candidate_name(candidate_groups[top_candidate], area)


def _group_area_candidates_by_unprefixed_name(
    candidates: set[str],
    area: str,
) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for candidate in candidates:
        variants = _name_variants_without_area(candidate, area)
        if not variants:
            continue
        key = min(variants, key=len)
        groups.setdefault(key, set()).add(candidate)
    return groups


def _candidate_group_variants(candidates: set[str], area: str) -> set[str]:
    variants: set[str] = set()
    for candidate in candidates:
        variants.update(_name_variants_without_area(candidate, area))
    return variants


def _preferred_area_candidate_name(candidates: set[str], area: str) -> str:
    normalized_area = _normalize_phonetic_text(area)
    return sorted(
        candidates,
        key=lambda candidate: (
            _normalize_phonetic_text(candidate).startswith(normalized_area),
            len(candidate),
        ),
        reverse=True,
    )[0]


def _adjust_phonetic_score_for_position(
    score: float,
    target_variants: set[str],
    candidate_variants: set[str],
) -> float:
    target_position = _position_token_for_variants(target_variants)
    if target_position is None:
        return score

    candidate_position = _position_token_for_variants(candidate_variants)
    if candidate_position == target_position:
        return min(1.0, score + POSITION_MATCH_BONUS)
    if candidate_position is not None:
        return max(0.0, score - POSITION_MISMATCH_PENALTY)
    return score


def _position_token_for_variants(variants: set[str]) -> str | None:
    positions = {
        position
        for variant in variants
        if (position := _position_token(variant)) is not None
    }
    if len(positions) != 1:
        return None
    return positions.pop()


def _position_token(value: str) -> str | None:
    positions = {
        position
        for position, tokens in POSITION_TOKEN_GROUPS.items()
        if any(token in value for token in tokens)
    }
    if len(positions) != 1:
        return None
    return positions.pop()


def _target_is_literal_candidate_part(
    target_variants: set[str],
    candidate_variants: dict[str, set[str]],
) -> bool:
    for target_variant in target_variants:
        if not target_variant:
            continue
        for variants in candidate_variants.values():
            for candidate_variant in variants:
                if (
                    target_variant != candidate_variant
                    and target_variant in candidate_variant
                ):
                    return True
    return False


def _name_variants_without_area(name: str, area: str) -> set[str]:
    normalized_name = _normalize_phonetic_text(name)
    normalized_area = _normalize_phonetic_text(area)
    if normalized_area and normalized_name.startswith(normalized_area):
        stripped_name = normalized_name[len(normalized_area) :]
        if stripped_name:
            return {stripped_name}
    return {normalized_name} if normalized_name else set()


def _normalize_phonetic_text(value: str) -> str:
    normalized_value = re.sub(r"\s+", "", value.strip())
    for source, replacement in POSITION_PHRASE_REPLACEMENTS:
        normalized_value = normalized_value.replace(source, replacement)
    return normalized_value.replace("的", "")


def _phonetic_phrase_similarity(left: str, right: str) -> float:
    left_syllables = _pinyin_syllables(left)
    right_syllables = _pinyin_syllables(right)
    if not left_syllables or not right_syllables:
        return 0.0

    matcher = SequenceMatcher(a=left_syllables, b=right_syllables, autojunk=False)
    matched_score = 0.0
    for block in matcher.get_matching_blocks():
        matched_score += block.size

    matched_positions_left = set()
    matched_positions_right = set()
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            matched_positions_left.add(block.a + offset)
            matched_positions_right.add(block.b + offset)

    unmatched_left = [
        syllable
        for index, syllable in enumerate(left_syllables)
        if index not in matched_positions_left
    ]
    unmatched_right = [
        syllable
        for index, syllable in enumerate(right_syllables)
        if index not in matched_positions_right
    ]
    for left_syllable, right_syllable in zip(unmatched_left, unmatched_right):
        matched_score += _pinyin_syllable_similarity(left_syllable, right_syllable)

    return matched_score / max(len(left_syllables), len(right_syllables))


def _pinyin_syllables(value: str) -> list[tuple[str, str, str]]:
    normalized_value = _normalize_phonetic_text(value)
    syllables = lazy_pinyin(normalized_value, style=Style.NORMAL, errors="ignore")
    initials = lazy_pinyin(
        normalized_value,
        style=Style.INITIALS,
        strict=False,
        errors="ignore",
    )
    finals = lazy_pinyin(
        normalized_value,
        style=Style.FINALS,
        strict=False,
        errors="ignore",
    )
    return [
        (syllable, initial, final)
        for syllable, initial, final in zip(syllables, initials, finals)
        if syllable
    ]


def _pinyin_syllable_similarity(
    left: tuple[str, str, str],
    right: tuple[str, str, str],
) -> float:
    if left[0] == right[0]:
        return 1.0

    initial_score = _phonetic_part_similarity(
        left[1],
        right[1],
        NEAR_INITIAL_GROUPS,
    )
    final_score = _phonetic_part_similarity(left[2], right[2], NEAR_FINAL_GROUPS)
    return 0.45 * initial_score + 0.55 * final_score


def _phonetic_part_similarity(
    left: str,
    right: str,
    near_groups: tuple[frozenset[str], ...],
) -> float:
    if left == right:
        return 1.0
    if any(left in group and right in group for group in near_groups):
        return 0.85
    return SequenceMatcher(a=left, b=right, autojunk=False).ratio() * 0.65


def _find_longest_area_name_prefix(
    name: str,
    area_names: list[str],
) -> str | None:
    normalized_name = name.strip()
    sorted_area_names = sorted(
        {area_name.strip() for area_name in area_names if area_name.strip()},
        key=len,
        reverse=True,
    )
    for area_name in sorted_area_names:
        if normalized_name.startswith(area_name) and normalized_name != area_name:
            return area_name
    return None


def _ac_turn_hvac_mode(tool_name: str) -> str | None:
    return AC_TURN_TOOL_HVAC_MODES.get(tool_name.rsplit("__", 1)[-1])


def _non_empty_config_value(
    config: dict[str, Any],
    key: str,
    default: str,
) -> str:
    value = config.get(key, default)
    if not isinstance(value, str):
        return default
    normalized_value = value.strip()
    return normalized_value or default


def _format_ac_custom_entity_value(entity_id: str | list[str], entity_format: str) -> Any:
    entity_ids = [entity_id] if isinstance(entity_id, str) else entity_id
    if entity_format == AC_ENTITY_FORMAT_LIST:
        return entity_ids
    if entity_format == AC_ENTITY_FORMAT_STRING:
        return entity_ids[0] if len(entity_ids) == 1 else ",".join(entity_ids)
    return "[" + ",".join(f"'{item}'" for item in entity_ids) + "]"


def has_direct_entity_target(arguments: dict[str, Any]) -> bool:
    for key, value in arguments.items():
        if key in ENTITY_TARGET_KEYS and _has_entity_target_value(value):
            return True
        if key == "name" and isinstance(value, str) and _looks_like_entity_id(value):
            return True
        if isinstance(value, dict) and has_direct_entity_target(value):
            return True
        if isinstance(value, list) and any(
            isinstance(item, dict) and has_direct_entity_target(item) for item in value
        ):
            return True
    return False


def strip_room_metadata_for_direct_entity_target(
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if not has_direct_entity_target(arguments):
        return arguments
    return _strip_room_metadata(arguments)


def _strip_room_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_room_metadata(item)
            for key, item in value.items()
            if key not in ROOM_OR_AREA_KEYS
        }
    if isinstance(value, list):
        return [_strip_room_metadata(item) for item in value]
    return value


def rewrite_current_room_ac_entity_targets(
    tool_name: str,
    arguments: dict[str, Any],
    active_context: ActiveGatewayContext,
    current_room_ac_entity_id: str | None,
) -> dict[str, Any]:
    if has_explicit_room_or_area(arguments):
        return arguments

    if _is_ac_context_query_tool(tool_name):
        return _rewrite_current_room_ac_context_query_target(
            arguments,
            active_context,
            current_room_ac_entity_id,
        )

    if not _is_ac_script_tool(tool_name):
        return arguments

    entity_ids = arguments.get("entity_ids")
    if not _has_single_ac_entity_target(entity_ids):
        return arguments

    if current_room_ac_entity_id is None:
        return arguments

    rewritten_arguments = dict(arguments)
    rewritten_arguments["entity_ids"] = _format_entity_ids_like_input(
        entity_ids,
        current_room_ac_entity_id,
    )
    return rewritten_arguments


def _rewrite_current_room_ac_context_query_target(
    arguments: dict[str, Any],
    active_context: ActiveGatewayContext,
    current_room_ac_entity_id: str | None,
) -> dict[str, Any]:
    if not _has_single_direct_ac_entity_target(arguments):
        return arguments

    if current_room_ac_entity_id is None:
        return arguments

    rewritten_arguments = {
        key: value
        for key, value in arguments.items()
        if key not in ENTITY_TARGET_KEYS
    }
    rewritten_arguments["name"] = f"{active_context.room_name}空调"
    rewritten_arguments["area"] = active_context.room_name
    rewritten_arguments["domain"] = ["climate"]
    return rewritten_arguments


def _is_ac_script_tool(tool_name: str) -> bool:
    return tool_name.rsplit("__", 1)[-1].startswith("set_multiple_ac_")


def _is_ac_context_query_tool(tool_name: str) -> bool:
    return tool_name.rsplit("__", 1)[-1] == "GetLiveContext"


def _has_single_direct_ac_entity_target(arguments: dict[str, Any]) -> bool:
    for key in ("name", "entity_id", "entity_ids"):
        if _has_single_ac_entity_target(arguments.get(key)):
            return True
    return False


def _has_single_ac_entity_target(entity_ids: Any) -> bool:
    if isinstance(entity_ids, str):
        return len(re.findall(r"climate\.[a-z0-9_]+", entity_ids)) == 1
    if isinstance(entity_ids, list):
        return len(entity_ids) == 1 and _looks_like_climate_entity_id(entity_ids[0])
    return False


def _looks_like_climate_entity_id(value: Any) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"climate\.[a-z0-9_]+", value.strip())
    )


def _format_entity_ids_like_input(entity_ids: Any, entity_id: str) -> Any:
    if isinstance(entity_ids, list):
        return [entity_id]
    return f"['{entity_id}']"


def _has_entity_target_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_entity_target_value(item) for item in value)
    return False


def _looks_like_entity_id(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", value.strip()))


def build_context_payload(
    base_context: Any,
    active_context: ActiveGatewayContext,
    tool_arguments: dict[str, Any],
    inject_preferred_area_id: bool = False,
) -> dict[str, Any]:
    contextual_tool_arguments = dict(tool_arguments)

    if has_explicit_room_or_area(tool_arguments):
        return {
            "context": base_context,
            "device_id": None,
            "tool_arguments": contextual_tool_arguments,
        }

    if inject_preferred_area_id:
        contextual_tool_arguments["preferred_area_id"] = active_context.ha_area_id

    return {
        "context": base_context,
        "device_id": active_context.ha_device_id,
        "tool_arguments": contextual_tool_arguments,
    }
