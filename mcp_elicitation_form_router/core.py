"""Core MCP elicitation/create schema builder, validator, default merger, and timeout FSM."""
import copy
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


_ALLOWED_TYPES = {"string", "number", "integer", "boolean"}
_ALLOWED_FORMATS = {"email", "uri", "date", "date-time"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URI_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


class ElicitationError(ValueError):
    """Raised when an elicitation schema, payload, or state transition is invalid."""


class ElicitationFormBuilder:
    """Fluent builder producing MCP-compliant flat object requestedSchema definitions."""

    def __init__(self):
        self._properties: Dict[str, Dict[str, Any]] = {}
        self._required: List[str] = []

    def _register(self, name: str, spec: Dict[str, Any], required: bool) -> "ElicitationFormBuilder":
        if not name or not re.match(r"^[a-zA-Z_][a-zA-Z0-9_-]*$", name):
            raise ElicitationError(f"Invalid field name: {name!r}")
        if name in self._properties:
            raise ElicitationError(f"Duplicate field: {name}")
        self._properties[name] = spec
        if required:
            self._required.append(name)
        return self

    def add_string(
        self,
        name: str,
        title: str,
        description: Optional[str] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        pattern: Optional[str] = None,
        fmt: Optional[str] = None,
        enum: Optional[List[str]] = None,
        enum_names: Optional[List[str]] = None,
        default: Optional[str] = None,
        required: bool = False,
    ) -> "ElicitationFormBuilder":
        spec: Dict[str, Any] = {"type": "string", "title": title}
        if description:
            spec["description"] = description
        if min_length is not None:
            spec["minLength"] = min_length
        if max_length is not None:
            spec["maxLength"] = max_length
        if pattern is not None:
            re.compile(pattern)
            spec["pattern"] = pattern
        if fmt is not None:
            if fmt not in _ALLOWED_FORMATS:
                raise ElicitationError(f"Unsupported string format: {fmt}")
            spec["format"] = fmt
        if enum is not None:
            if not enum:
                raise ElicitationError("enum must be non-empty")
            spec["enum"] = list(enum)
            if enum_names is not None:
                if len(enum_names) != len(enum):
                    raise ElicitationError("enumNames length must match enum length")
                spec["enumNames"] = list(enum_names)
        if default is not None:
            spec["default"] = default
        return self._register(name, spec, required)

    def add_integer(
        self,
        name: str,
        title: str,
        minimum: Optional[int] = None,
        maximum: Optional[int] = None,
        default: Optional[int] = None,
        required: bool = False,
    ) -> "ElicitationFormBuilder":
        spec: Dict[str, Any] = {"type": "integer", "title": title}
        if minimum is not None:
            spec["minimum"] = minimum
        if maximum is not None:
            spec["maximum"] = maximum
        if default is not None:
            spec["default"] = default
        return self._register(name, spec, required)

    def add_number(
        self,
        name: str,
        title: str,
        minimum: Optional[float] = None,
        maximum: Optional[float] = None,
        default: Optional[float] = None,
        required: bool = False,
    ) -> "ElicitationFormBuilder":
        spec: Dict[str, Any] = {"type": "number", "title": title}
        if minimum is not None:
            spec["minimum"] = minimum
        if maximum is not None:
            spec["maximum"] = maximum
        if default is not None:
            spec["default"] = default
        return self._register(name, spec, required)

    def add_boolean(
        self,
        name: str,
        title: str,
        default: Optional[bool] = None,
        required: bool = False,
    ) -> "ElicitationFormBuilder":
        spec: Dict[str, Any] = {"type": "boolean", "title": title}
        if default is not None:
            spec["default"] = default
        return self._register(name, spec, required)

    def build(self) -> Dict[str, Any]:
        if not self._properties:
            raise ElicitationError("Elicitation schema must define at least one property")
        schema: Dict[str, Any] = {
            "type": "object",
            "properties": copy.deepcopy(self._properties),
        }
        if self._required:
            schema["required"] = list(self._required)
        return schema


def _validate_format(fmt: str, value: str, field: str) -> None:
    if fmt == "email" and not _EMAIL_RE.match(value):
        raise ElicitationError(f"Field '{field}' is not a valid email")
    elif fmt == "uri" and not _URI_RE.match(value):
        raise ElicitationError(f"Field '{field}' is not a valid URI")
    elif fmt == "date":
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ElicitationError(f"Field '{field}' must be YYYY-MM-DD") from exc
    elif fmt == "date-time":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ElicitationError(f"Field '{field}' must be ISO-8601 date-time") from exc


def merge_defaults(schema: Dict[str, Any], content: Dict[str, Any]) -> Dict[str, Any]:
    """Merges schema field defaults into a copy of content without mutating the input."""
    merged = copy.deepcopy(content)
    properties = schema.get("properties", {})
    for field_name, spec in properties.items():
        if field_name not in merged and "default" in spec:
            merged[field_name] = copy.deepcopy(spec["default"])
    return merged


def validate_elicitation_content(schema: Dict[str, Any], content: Dict[str, Any]) -> Dict[str, Any]:
    """Validates submitted elicitation content against a flat MCP JSON Schema and merges defaults."""
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise ElicitationError("requestedSchema must be an object schema with properties")
    if not isinstance(content, dict):
        raise ElicitationError("Elicitation content must be a JSON object")

    properties = schema["properties"]
    unknown = sorted(set(content.keys()) - set(properties.keys()))
    if unknown:
        raise ElicitationError(f"Unknown elicitation fields: {', '.join(unknown)}")

    merged = merge_defaults(schema, content)
    for req in schema.get("required", []):
        if req not in merged or merged[req] is None:
            raise ElicitationError(f"Missing required field: {req}")

    for field_name, val in merged.items():
        spec = properties[field_name]
        ptype = spec.get("type")
        if ptype not in _ALLOWED_TYPES:
            raise ElicitationError(f"Unsupported property type {ptype!r} on '{field_name}'")
        if ptype == "string":
            if not isinstance(val, str):
                raise ElicitationError(f"Field '{field_name}' must be a string")
            if "minLength" in spec and len(val) < spec["minLength"]:
                raise ElicitationError(f"Field '{field_name}' shorter than minLength {spec['minLength']}")
            if "maxLength" in spec and len(val) > spec["maxLength"]:
                raise ElicitationError(f"Field '{field_name}' exceeds maxLength {spec['maxLength']}")
            if "pattern" in spec and not re.search(spec["pattern"], val):
                raise ElicitationError(f"Field '{field_name}' does not match pattern")
            if "format" in spec:
                _validate_format(spec["format"], val, field_name)
            if "enum" in spec and val not in spec["enum"]:
                raise ElicitationError(f"Field '{field_name}' value {val!r} not in enum")
        elif ptype == "integer":
            if isinstance(val, bool) or not isinstance(val, int):
                raise ElicitationError(f"Field '{field_name}' must be an integer")
            if "minimum" in spec and val < spec["minimum"]:
                raise ElicitationError(f"Field '{field_name}' below minimum {spec['minimum']}")
            if "maximum" in spec and val > spec["maximum"]:
                raise ElicitationError(f"Field '{field_name}' above maximum {spec['maximum']}")
        elif ptype == "number":
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ElicitationError(f"Field '{field_name}' must be a number")
            if "minimum" in spec and val < spec["minimum"]:
                raise ElicitationError(f"Field '{field_name}' below minimum {spec['minimum']}")
            if "maximum" in spec and val > spec["maximum"]:
                raise ElicitationError(f"Field '{field_name}' above maximum {spec['maximum']}")
        elif ptype == "boolean":
            if not isinstance(val, bool):
                raise ElicitationError(f"Field '{field_name}' must be a boolean")
    return merged


@dataclass
class ElicitationRequest:
    request_id: str
    message: str
    requested_schema: Dict[str, Any]
    created_at: float
    expires_at: float
    state: str = "pending"


@dataclass
class ElicitationResult:
    request_id: str
    action: str
    state: str
    merged_content: Optional[Dict[str, Any]]
    completed_at: float


class ElicitationRouter:
    """Tracks pending MCP elicitation requests with validation and TTL timeout transitions."""

    def __init__(self, default_ttl_seconds: float = 120.0):
        self.default_ttl_seconds = default_ttl_seconds
        self._requests: Dict[str, ElicitationRequest] = {}

    def create_request(
        self,
        request_id: str,
        message: str,
        requested_schema: Dict[str, Any],
        ttl_seconds: Optional[float] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        if request_id in self._requests:
            raise ElicitationError(f"Request {request_id} already exists")
        if requested_schema.get("type") != "object" or not requested_schema.get("properties"):
            raise ElicitationError("Invalid requestedSchema")
        current = time.time() if now is None else now
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        req = ElicitationRequest(
            request_id=request_id,
            message=message,
            requested_schema=copy.deepcopy(requested_schema),
            created_at=current,
            expires_at=current + ttl,
        )
        self._requests[request_id] = req
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "elicitation/create",
            "params": {"message": message, "requestedSchema": req.requested_schema},
        }

    def expire_stale(self, now: Optional[float] = None) -> List[str]:
        current = time.time() if now is None else now
        expired: List[str] = []
        for req_id, req in self._requests.items():
            if req.state == "pending" and current > req.expires_at:
                req.state = "timed_out"
                expired.append(req_id)
        return expired

    def submit_response(
        self,
        request_id: str,
        action: str,
        content: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> ElicitationResult:
        req = self._requests.get(request_id)
        if req is None:
            raise ElicitationError(f"Unknown request_id: {request_id}")
        current = time.time() if now is None else now
        if req.state == "pending" and current > req.expires_at:
            req.state = "timed_out"
        if req.state != "pending":
            raise ElicitationError(f"Request {request_id} is in terminal state '{req.state}'")
        if action not in ("accept", "decline", "cancel"):
            raise ElicitationError(f"Invalid elicitation action: {action!r}")

        if action == "accept":
            merged = validate_elicitation_content(req.requested_schema, content or {})
            req.state = "accepted"
            return ElicitationResult(request_id, action, req.state, merged, current)
        req.state = "declined" if action == "decline" else "cancelled"
        return ElicitationResult(request_id, action, req.state, None, current)

    def get_state(self, request_id: str) -> str:
        if request_id not in self._requests:
            raise ElicitationError(f"Unknown request_id: {request_id}")
        return self._requests[request_id].state
