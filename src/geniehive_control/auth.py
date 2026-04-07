from __future__ import annotations

from fastapi import HTTPException, Request, status


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


def require_client_auth(request: Request) -> None:
    cfg = request.app.state.cfg
    _check_key(request, cfg.auth.client_api_keys, "X-Api-Key")


def require_node_auth(request: Request) -> None:
    cfg = request.app.state.cfg
    _check_key(request, cfg.auth.node_api_keys, "X-GenieHive-Node-Key")
