"""Guarded registry for every documented Planner OS public tool."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from planner_platform.function_manifest import build_manifest, check_manifest
from planner_platform.policies import CloudStatus, ToolPolicy, policy_for


class ToolRegistryError(ValueError):
    code = "TOOL_REGISTRY_ERROR"


class ToolNotRegisteredError(ToolRegistryError):
    code = "TOOL_NOT_REGISTERED"


class ToolDisabledInCloudError(ToolRegistryError):
    code = "TOOL_DISABLED_IN_CLOUD"


class ToolInputError(ToolRegistryError):
    code = "TOOL_INPUT_INVALID"


@dataclass(frozen=True)
class ToolInvocationRequest:
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ToolInvocationResponse:
    payload: dict[str, Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    handler: Callable[..., dict[str, Any]]
    request_model: type[ToolInvocationRequest]
    response_model: type[ToolInvocationResponse]
    parameters: tuple[dict[str, Any], ...]
    policy: ToolPolicy
    description: str


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in self._specs:
                raise ToolRegistryError(f"Duplicate tool registration: {spec.name}")
            self._specs[spec.name] = spec

    def list(self) -> list[ToolSpec]:
        return [self._specs[name] for name in sorted(self._specs)]

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as error:
            raise ToolNotRegisteredError(f"Tool is not registered: {name}") from error

    def invoke(
        self,
        name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        cloud_mode: bool = False,
    ) -> dict[str, Any]:
        spec = self.get(name)
        if cloud_mode and spec.policy.cloud_status == CloudStatus.DISABLED:
            raise ToolDisabledInCloudError(spec.policy.cloud_reason)
        if cloud_mode and spec.policy.cloud_status == CloudStatus.ADAPTATION_REQUIRED:
            raise ToolDisabledInCloudError(spec.policy.cloud_reason)
        values = self._validated_values(spec, dict(payload or {}))
        result = spec.handler(*values)
        if not isinstance(result, dict):
            raise ToolRegistryError(f"Tool {name} returned a non-dictionary response")
        return result

    @staticmethod
    def _validated_values(spec: ToolSpec, payload: dict[str, Any]) -> list[Any]:
        allowed = {str(item["name"]) for item in spec.parameters}
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise ToolInputError(f"Unexpected fields for {spec.name}: {unexpected}")
        values: list[Any] = []
        missing: list[str] = []
        for parameter in spec.parameters:
            name = str(parameter["name"])
            if name in payload:
                values.append(payload[name])
            elif parameter["required"]:
                missing.append(name)
            else:
                default = parameter.get("default")
                values.append(ast.literal_eval(default) if default is not None else None)
        if missing:
            raise ToolInputError(f"Missing required fields for {spec.name}: {missing}")
        return values


def _handler_for(tools: Any, name: str) -> Callable[..., dict[str, Any]]:
    if name == "calendar_delete_series":
        return lambda external_id: tools.calendar_delete_event(external_id, "series")
    if name == "calendar_delete_future_series":
        return lambda external_id: tools.calendar_delete_event(external_id, "future")
    try:
        return getattr(tools, name)
    except AttributeError as error:
        raise ToolRegistryError(f"No local handler for registered tool: {name}") from error


def build_tool_registry(tools: Any) -> ToolRegistry:
    """Bind all canonical manifest records to one request-scoped tool adapter."""

    check_manifest()
    specs = []
    for tool in build_manifest()["tools"]:
        specs.append(
            ToolSpec(
                name=str(tool["name"]),
                handler=_handler_for(tools, str(tool["name"])),
                request_model=ToolInvocationRequest,
                response_model=ToolInvocationResponse,
                parameters=tuple(tool["parameters"]),
                policy=policy_for(tool),
                description=str(tool["description"]),
            )
        )
    return ToolRegistry(specs)

