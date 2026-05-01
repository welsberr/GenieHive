from __future__ import annotations

import os
from dataclasses import dataclass
from fnmatch import fnmatchcase

from fastapi import HTTPException, Request, status

from .keys import hash_api_key


@dataclass(frozen=True)
class ClientContext:
    auth_kind: str
    key_id: str | None = None
    display_name: str | None = None
    principal_type: str | None = None
    principal_ref: str | None = None
    role: str | None = None
    allowed_models: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()


def _check_key(request: Request, allowed_keys: list[str], header_name: str) -> None:
    if not allowed_keys:
        return
    provided = request.headers.get(header_name)
    if provided in allowed_keys:
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="unauthorized",
    )


def _set_client_context(request: Request, context: ClientContext) -> None:
    request.state.client_context = context


def require_client_auth(request: Request) -> ClientContext:
    cfg = request.app.state.cfg
    provided = request.headers.get("X-Api-Key")

    if cfg.auth.client_api_keys and provided in cfg.auth.client_api_keys:
        context = ClientContext(auth_kind="static")
        _set_client_context(request, context)
        return context

    if cfg.auth.enable_named_client_keys:
        if not provided:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="unauthorized",
            )
        secret = os.environ.get(cfg.auth.key_hash_secret_env)
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{cfg.auth.key_hash_secret_env} is required for named client keys",
            )
        key_hash = hash_api_key(provided, secret=secret)
        key_row = request.app.state.registry.get_client_key_by_hash(key_hash)
        if key_row is None or not key_row["enabled"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="unauthorized",
            )
        request.app.state.registry.touch_client_key(key_row["key_id"])
        context = ClientContext(
            auth_kind="named",
            key_id=key_row["key_id"],
            display_name=key_row["display_name"],
            principal_type=key_row["principal_type"],
            principal_ref=key_row["principal_ref"],
            role=key_row["role"],
            allowed_models=tuple(key_row["allowed_models"]),
            allowed_operations=tuple(key_row["allowed_operations"]),
        )
        _set_client_context(request, context)
        return context

    if cfg.auth.client_api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthorized",
        )

    context = ClientContext(auth_kind="development")
    _set_client_context(request, context)
    return context


def require_node_auth(request: Request) -> None:
    cfg = request.app.state.cfg
    _check_key(request, cfg.auth.node_api_keys, "X-GenieHive-Node-Key")


def require_admin_auth(request: Request) -> ClientContext:
    cfg = request.app.state.cfg
    if not cfg.admin_api.enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not found",
        )
    context = require_client_auth(request)
    if context.auth_kind == "static" or context.role == "admin":
        return context
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="admin access required",
    )


def authorize_client_request(request: Request, *, operation: str, model: str | None) -> None:
    cfg = request.app.state.cfg
    context = getattr(request.state, "client_context", None)
    if context is None:
        return
    # Static and development auth preserve casual-deployment behavior. Foundation
    # scoped access is enforced for named keys only.
    if context.auth_kind != "named":
        return
    if cfg.authorization.enforce_operation_allowlists:
        _authorize_value(
            value=operation,
            allowed=context.allowed_operations,
            empty_means_no_access=cfg.authorization.empty_allowlist_means_no_access,
            denied_detail=f"operation '{operation}' is not allowed for this key",
        )
    if cfg.authorization.enforce_model_allowlists:
        if not model:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="model is required for model authorization",
            )
        _authorize_value(
            value=model,
            allowed=context.allowed_models,
            empty_means_no_access=cfg.authorization.empty_allowlist_means_no_access,
            denied_detail=f"model '{model}' is not allowed for this key",
        )


def _authorize_value(
    *,
    value: str,
    allowed: tuple[str, ...],
    empty_means_no_access: bool,
    denied_detail: str,
) -> None:
    if not allowed:
        if empty_means_no_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=denied_detail,
            )
        return
    if any(_allow_pattern_matches(pattern, value) for pattern in allowed):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=denied_detail,
    )


def _allow_pattern_matches(pattern: str, value: str) -> bool:
    if pattern.startswith("role/"):
        pattern = pattern.removeprefix("role/")
    return fnmatchcase(value, pattern)
