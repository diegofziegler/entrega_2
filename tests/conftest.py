"""Utilidades compartidas por los tests offline."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda

import chain
from schemas import Criticidad, Extraccion


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Acorta el backoff para que la suite no duerma de verdad entre reintentos."""
    monkeypatch.setattr(chain, "JITTER_REINTENTOS", {"initial": 0.01, "max": 0.02})


class Contador:
    """Cuenta cuantas veces se invoco al modelo falso."""

    def __init__(self) -> None:
        self.llamadas = 0


def extraccion_valida() -> Extraccion:
    """Objeto de salida valido, usado como respuesta exitosa del modelo falso."""
    return Extraccion(
        tecnologias=["FastAPI", "Redis", "PostgreSQL"],
        nivel_de_criticidad=Criticidad.ALTA,
        resumen_tecnico="API con cache en Redis; cuello de botella en conexiones.",
    )


def respuesta_ok(parsed: Extraccion | None = None) -> dict[str, Any]:
    """Payload equivalente al de `with_structured_output(..., include_raw=True)`."""
    return {
        "raw": AIMessage(content=""),
        "parsed": parsed if parsed is not None else extraccion_valida(),
        "parsing_error": None,
    }


def respuesta_malformada() -> dict[str, Any]:
    """Payload con `parsing_error`, como cuando el modelo devuelve un JSON roto."""
    return {
        "raw": AIMessage(content='{"tecnologias": ["Redis"'),
        "parsed": None,
        "parsing_error": ValueError("JSON incompleto"),
    }


def respuesta_truncada(clave: str = "finish_reason") -> dict[str, Any]:
    """Simula un corte por limite de tokens.

    OpenAI lo informa como finish_reason='length'; Anthropic como
    stop_reason='max_tokens'.
    """
    motivo = "length" if clave == "finish_reason" else "max_tokens"
    return {
        "raw": AIMessage(content="", response_metadata={clave: motivo}),
        "parsed": None,
        "parsing_error": None,
    }


def modelo_falso(acciones: list[Any]) -> tuple[Runnable, Contador]:
    """Runnable que ocupa el lugar del modelo con salida estructurada.

    Cada elemento de `acciones` es el payload a devolver o una excepcion a lanzar.
    Agotada la lista, se repite el ultimo elemento.
    """
    contador = Contador()
    secuencia = list(acciones)

    def _invocar(_entrada: Any) -> Any:
        """Consume la siguiente accion y la devuelve, o la lanza si es excepcion."""
        contador.llamadas += 1
        accion = secuencia[min(contador.llamadas - 1, len(secuencia) - 1)]
        if isinstance(accion, BaseException):
            raise accion
        return accion

    return RunnableLambda(_invocar), contador
