"""Capa anticorrupcion entre el pipeline y los SDK de cada proveedor.

Este es el unico modulo que sabe que existen OpenAI y Anthropic. Cumple el rol que
en el Modulo 1 tenia la carpeta `clients/`.

Los SDK de OpenAI y Anthropic tienen jerarquias de excepciones estructuralmente
identicas pero sin base comun (`OpenAIError` y `AnthropicError` cuelgan directo de
`Exception`), asi que no hay ningun `isinstance` transversal que sirva para detectar
un error transitorio. Por eso cada proveedor declara su propia tupla, con imports
diferidos: nadie necesita tener instalado el SDK que no usa.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from schemas import ModelConfig, Provider

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

# Los reintentos internos del SDK ocurren por debajo de LangChain: son invisibles a
# nuestros logs y se multiplicarian con los de `.with_retry()`. Se desactivan para que
# nuestra capa sea la unica responsable. Es una invariante del disenio, no un ajuste.
_REINTENTOS_INTERNOS_SDK = 0


@dataclass(frozen=True)
class ProveedorLLM:
    """Todo lo que el pipeline necesita saber de un proveedor."""

    crear: Callable[[ModelConfig], "BaseChatModel"]
    transitorias: Callable[[], tuple[type[BaseException], ...]]


def _crear_openai(config: ModelConfig) -> "BaseChatModel":
    """Construye el chat model de OpenAI, importando el SDK recien al usarse."""
    from langchain_openai import ChatOpenAI

    if config.openai_api_key is None:
        raise ValueError(
            "Falta OPENAI_API_KEY en el entorno y LLM_PROVIDER esta en 'openai'."
        )

    return ChatOpenAI(
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        api_key=config.openai_api_key,
        max_retries=_REINTENTOS_INTERNOS_SDK,
    )


def _transitorias_openai() -> tuple[type[BaseException], ...]:
    """Errores de OpenAI que valen un reintento: 429, 5xx, timeouts y cortes de red."""
    from openai import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )

    return (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


def _crear_anthropic(config: ModelConfig) -> "BaseChatModel":
    """Construye el chat model de Anthropic, importando el SDK recien al usarse."""
    from langchain_anthropic import ChatAnthropic

    if config.anthropic_api_key is None:
        raise ValueError(
            "Falta ANTHROPIC_API_KEY en el entorno y LLM_PROVIDER esta en 'anthropic'."
        )

    return ChatAnthropic(
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        api_key=config.anthropic_api_key,
        max_retries=_REINTENTOS_INTERNOS_SDK,
    )


def _transitorias_anthropic() -> tuple[type[BaseException], ...]:
    """Errores de Anthropic que valen un reintento. Misma forma que los de OpenAI,
    pero sin base comun: por eso cada proveedor declara su propia tupla."""
    from anthropic import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )

    return (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


_REGISTRO: dict[Provider, ProveedorLLM] = {
    Provider.OPENAI: ProveedorLLM(
        crear=_crear_openai,
        transitorias=_transitorias_openai,
    ),
    Provider.ANTHROPIC: ProveedorLLM(
        crear=_crear_anthropic,
        transitorias=_transitorias_anthropic,
    ),
}


def _buscar(provider: Provider) -> ProveedorLLM:
    """Devuelve la entrada del registro, o falla listando los proveedores validos."""
    proveedor = _REGISTRO.get(provider)
    if proveedor is None:
        soportados = ", ".join(sorted(p.value for p in _REGISTRO))
        raise ValueError(
            f"Proveedor no soportado: '{provider}'. Soportados: {soportados}."
        )
    return proveedor


def crear_modelo(config: ModelConfig) -> "BaseChatModel":
    """Instancia el chat model de LangChain del proveedor activo."""
    modelo = _buscar(config.provider).crear(config)
    logger.debug(
        "Chat model creado | proveedor=%s modelo=%s temperature=%s max_tokens=%s",
        config.provider.value,
        config.model,
        config.temperature,
        config.max_tokens,
    )
    return modelo


def excepciones_transitorias(provider: Provider) -> tuple[type[BaseException], ...]:
    """Excepciones del proveedor que ameritan reintento: 429, 5xx, timeouts y cortes."""
    transitorias = _buscar(provider).transitorias()
    logger.debug(
        "Excepciones transitorias de %s: %s",
        provider.value,
        ", ".join(excepcion.__name__ for excepcion in transitorias),
    )
    return transitorias
