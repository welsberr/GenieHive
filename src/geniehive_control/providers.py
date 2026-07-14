from __future__ import annotations

import os
from collections.abc import Mapping

from .config import ProviderConfig
from .models import HostRegistration, RegisteredService
from .registry import Registry


SUPPORTED_PROVIDER_KINDS = {"openai_compatible"}


class ProviderConfigurationError(RuntimeError):
    pass


class ConfiguredProviders:
    """Registers configured external providers and resolves their request headers."""

    def __init__(
        self,
        providers: list[ProviderConfig],
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        enabled_ids = [provider.provider_id for provider in providers if provider.enabled]
        if len(enabled_ids) != len(set(enabled_ids)):
            raise ProviderConfigurationError("enabled provider_id values must be unique")
        self._providers = {provider.provider_id: provider for provider in providers if provider.enabled}
        self._environ = environ if environ is not None else os.environ
        for provider in self._providers.values():
            if provider.provider_kind not in SUPPORTED_PROVIDER_KINDS:
                raise ProviderConfigurationError(
                    f"provider '{provider.provider_id}' uses unsupported kind "
                    f"'{provider.provider_kind}'"
                )
            if not provider.models:
                raise ProviderConfigurationError(
                    f"provider '{provider.provider_id}' must declare at least one model"
                )

    def register_services(self, registry: Registry) -> None:
        active_host_ids = {
            f"external-provider:{provider_id}" for provider_id in self._providers
        }
        registry.remove_external_provider_hosts(active_host_ids)
        for provider in self._providers.values():
            host_id = f"external-provider:{provider.provider_id}"
            registry.register_host(
                HostRegistration(
                    host_id=host_id,
                    display_name=provider.provider_id,
                    address=provider.base_url,
                    labels={
                        "service_origin": "external_provider",
                        "provider_kind": provider.provider_kind,
                    },
                    services=[
                        RegisteredService(
                            service_id=f"provider/{provider.provider_id}/{provider.operation}",
                            host_id=host_id,
                            kind=provider.operation,
                            protocol=provider.provider_kind,
                            endpoint=provider.base_url,
                            runtime={
                                "engine": provider.provider_kind,
                                "launcher": "configured_provider",
                                "provider_id": provider.provider_id,
                            },
                            assets=[
                                {"asset_id": model_id, "loaded": True}
                                for model_id in provider.models
                            ],
                            state={"health": "healthy", "accept_requests": True},
                        )
                    ],
                )
            )

    def headers_for_service(self, service: dict) -> dict[str, str]:
        provider_id = (service.get("runtime") or {}).get("provider_id")
        if not provider_id:
            return {}
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderConfigurationError(
                f"service references unknown configured provider '{provider_id}'"
            )

        headers = dict(provider.default_headers)
        if provider.api_key_env:
            api_key = self._environ.get(provider.api_key_env)
            if not api_key:
                raise ProviderConfigurationError(
                    f"provider '{provider_id}' requires environment variable "
                    f"{provider.api_key_env}"
                )
            if not any(name.lower() == "authorization" for name in headers):
                headers["Authorization"] = f"Bearer {api_key}"
        return headers
