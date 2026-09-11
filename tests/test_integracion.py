"""Test de integracion: hace una llamada real al proveedor configurado.

Se saltea solo si no hay API key en el entorno, de modo que `uv run pytest` funcione
igual con o sin credenciales.
"""

from __future__ import annotations

import os

import pytest

from chain import cargar_config, crear_cadena, process_text
from schemas import Criticidad, Extraccion, Provider

pytestmark = pytest.mark.integration

_CLAVE_POR_PROVEEDOR = {
    Provider.OPENAI: "OPENAI_API_KEY",
    Provider.ANTHROPIC: "ANTHROPIC_API_KEY",
    Provider.GEMINI: "GEMINI_API_KEY",
}

TEXTO = (
    "2026-09-10 03:14:22 ERROR api.workers: la API en FastAPI devuelve 504 en el 40 "
    "por ciento de las requests. El pool de PostgreSQL se agoto y Redis responde con "
    "latencias de 800ms."
)


@pytest.fixture
def cadena_real():
    """Arma la cadena de produccion, o saltea el test si faltan credenciales."""
    try:
        config = cargar_config()
    except ValueError as error:
        pytest.skip(f"Configuracion incompleta: {error}")

    variable = _CLAVE_POR_PROVEEDOR[config.provider]
    if not os.getenv(variable):
        pytest.skip(f"Falta {variable}; se omite la prueba contra la API real.")

    return crear_cadena(config)


async def test_extraccion_contra_api_real(cadena_real) -> None:
    """Valida el camino completo: prompt, salida estructurada y contrato Pydantic."""
    resultado = await process_text(TEXTO, cadena=cadena_real)

    assert isinstance(resultado, Extraccion)
    assert resultado.tecnologias
    assert isinstance(resultado.nivel_de_criticidad, Criticidad)
    assert resultado.resumen_tecnico.strip()

    nombradas = {tecnologia.casefold() for tecnologia in resultado.tecnologias}
    assert {"fastapi", "postgresql", "redis"} & nombradas, (
        f"esperaba alguna tecnologia del texto, se obtuvo {resultado.tecnologias}"
    )
