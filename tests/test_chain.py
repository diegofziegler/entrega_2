"""Tests offline del pipeline: no requieren API key ni conexion."""

from __future__ import annotations

import logging

# Los SDK de OpenAI y Anthropic usan httpx2, no httpx: el request tiene que ser
# del mismo tipo que el que construiria el propio cliente.
import pytest
from pydantic import ValidationError

import providers
from chain import construir_cadena, process_text
from conftest import (
    extraccion_valida,
    modelo_falso,
    respuesta_malformada,
    respuesta_ok,
    respuesta_truncada,
)
from schemas import Criticidad, Extraccion, Provider

TEXTO = (
    "La API en FastAPI devuelve 504 y el pool de PostgreSQL se agoto; "
    "Redis responde con 800ms de latencia."
)


# --------------------------------------------------------------------------- #
# Reintentos ante respuestas invalidas del LLM
# --------------------------------------------------------------------------- #


async def test_se_recupera_tras_una_estructura_invalida() -> None:
    """Un `parsing_error` en el primer intento no debe hundir la invocacion."""
    modelo, contador = modelo_falso([respuesta_malformada(), respuesta_ok()])
    cadena = construir_cadena(modelo, max_retries=2)

    resultado = await cadena.ainvoke({"texto": TEXTO})

    assert isinstance(resultado, Extraccion)
    assert resultado.tecnologias == ["FastAPI", "Redis", "PostgreSQL"]
    assert contador.llamadas == 2


@pytest.mark.parametrize("clave", ["finish_reason", "stop_reason"])
async def test_detecta_truncamiento_y_reintenta(clave: str) -> None:
    """Una respuesta cortada por tokens se detecta con cualquiera de las dos claves.

    `include_raw=True` no marca el truncamiento como error, asi que sin la revision
    del metadata la respuesta incompleta pasaria como valida.
    """
    modelo, contador = modelo_falso([respuesta_truncada(clave), respuesta_ok()])
    cadena = construir_cadena(modelo, max_retries=2)

    resultado = await cadena.ainvoke({"texto": TEXTO})

    assert isinstance(resultado, Extraccion)
    assert contador.llamadas == 2


async def test_parsed_vacio_dispara_reintento() -> None:
    """Un payload sin objeto ni error tampoco puede darse por bueno."""
    vacio = {"raw": None, "parsed": None, "parsing_error": None}
    modelo, contador = modelo_falso([vacio, respuesta_ok()])
    cadena = construir_cadena(modelo, max_retries=2)

    assert isinstance(await cadena.ainvoke({"texto": TEXTO}), Extraccion)
    assert contador.llamadas == 2


async def test_agotar_reintentos_devuelve_none() -> None:
    """Si el modelo nunca acierta, `process_text` degrada a None en vez de explotar."""
    modelo, contador = modelo_falso([respuesta_malformada()])
    cadena = construir_cadena(modelo, max_retries=2)

    assert await process_text(TEXTO, cadena=cadena) is None
    assert contador.llamadas == 3


async def test_cantidad_exacta_de_llamadas() -> None:
    """Blinda el +1 de stop_after_attempt: 1 reintento son 2 llamadas, no 1."""
    modelo, contador = modelo_falso([respuesta_malformada()])
    cadena = construir_cadena(modelo, max_retries=1)

    assert await process_text(TEXTO, cadena=cadena) is None
    assert contador.llamadas == 2


# --------------------------------------------------------------------------- #
# Errores transitorios del proveedor
# --------------------------------------------------------------------------- #


def _error_de_conexion(provider: Provider) -> BaseException:
    """Construye un error transitorio preguntandole el tipo al registro.

    El test toma la clase de la tupla que declara `providers.py`, sin acoplarse a
    un SDK. Los SDK no comparten el mismo constructor de excepciones, por lo que
    se instancia la primera clase que acepte un mensaje simple.
    """
    transitorias = providers.excepciones_transitorias(provider)
    for clase in transitorias:
        try:
            return clase("corte de red simulado")
        except TypeError:
            try:
                # google-genai usa (codigo_http, cuerpo_de_respuesta).
                return clase(503, {"error": {"message": "corte de red simulado"}})
            except TypeError:
                continue
    pytest.fail(f"No se pudo instanciar ningun error transitorio de {provider.value}")


@pytest.mark.parametrize("provider", list(Provider))
async def test_error_transitorio_se_reintenta(provider: Provider) -> None:
    """Un corte de red del SDK entra en la politica de reintento de cada proveedor."""
    transitorias = providers.excepciones_transitorias(provider)
    modelo, contador = modelo_falso([_error_de_conexion(provider), respuesta_ok()])
    cadena = construir_cadena(modelo, max_retries=2, transitorias=transitorias)

    resultado = await cadena.ainvoke({"texto": TEXTO})

    assert isinstance(resultado, Extraccion)
    assert contador.llamadas == 2


async def test_error_transitorio_no_declarado_no_se_reintenta() -> None:
    """Sin la tupla del proveedor, el error de red aborta en el primer intento."""
    modelo, contador = modelo_falso(
        [_error_de_conexion(Provider.OPENAI), respuesta_ok()]
    )
    cadena = construir_cadena(modelo, max_retries=2, transitorias=())

    assert await process_text(TEXTO, cadena=cadena) is None
    assert contador.llamadas == 1


def test_el_registro_cubre_todos_los_providers() -> None:
    """Sumar un Provider sin darle de alta en el registro debe romper la suite."""
    for provider in Provider:
        transitorias = providers.excepciones_transitorias(provider)
        assert transitorias, f"{provider.value} no declara excepciones transitorias"
        assert all(issubclass(e, BaseException) for e in transitorias)


def test_provider_desconocido_falla_con_mensaje_claro() -> None:
    """Un proveedor fuera del registro falla explicito, no con un KeyError pelado."""
    with pytest.raises(ValueError, match="Proveedor no soportado"):
        providers.excepciones_transitorias("desconocido")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Validacion de la entrada humana
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("entrada", ["", "   ", "muy corto"])
async def test_entrada_invalida_no_llama_al_llm(
    entrada: str, caplog: pytest.LogCaptureFixture
) -> None:
    """El error es de la persona: se avisa y no se gasta una llamada al proveedor."""
    modelo, contador = modelo_falso([respuesta_ok()])
    cadena = construir_cadena(modelo, max_retries=2)

    with caplog.at_level(logging.ERROR):
        assert await process_text(entrada, cadena=cadena) is None

    assert contador.llamadas == 0, "no debe gastarse una llamada al LLM"
    assert "Entrada invalida" in caplog.text


# --------------------------------------------------------------------------- #
# Contrato de salida
# --------------------------------------------------------------------------- #


def test_tecnologias_se_normalizan_y_deduplican() -> None:
    """Se limpian espacios y repetidos, conservando orden y grafia original."""
    extraccion = Extraccion(
        tecnologias=["  Redis ", "redis", "", "PostgreSQL"],
        nivel_de_criticidad=Criticidad.MEDIA,
        resumen_tecnico="Cache y persistencia.",
    )

    assert extraccion.tecnologias == ["Redis", "PostgreSQL"]


@pytest.mark.parametrize("tecnologias", [[], ["   ", ""]])
def test_tecnologias_vacias_son_invalidas(tecnologias: list[str]) -> None:
    """Una lista vacia, o que queda vacia al limpiarla, rompe el contrato."""
    with pytest.raises(ValidationError):
        Extraccion(
            tecnologias=tecnologias,
            nivel_de_criticidad=Criticidad.BAJA,
            resumen_tecnico="Nada que reportar.",
        )


def test_criticidad_fuera_del_enum_es_invalida() -> None:
    """El enum se limita a baja/media/alta: nada de niveles inventados."""
    with pytest.raises(ValidationError):
        Extraccion(
            tecnologias=["Redis"],
            nivel_de_criticidad="critica",  # type: ignore[arg-type]
            resumen_tecnico="Fallo.",
        )


async def test_criticidad_baja_emite_advertencia(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Criticidad 'baja' avisa que el texto puede no describir ningun incidente.

    Con el enum acotado a tres valores el pipeline no puede distinguir "sin
    problema" de "problema leve", asi que la advertencia va al log.
    """
    sana = extraccion_valida().model_copy(
        update={
            "nivel_de_criticidad": Criticidad.BAJA,
            "resumen_tecnico": "No se detecto ningun error ni problema.",
        }
    )
    modelo, _ = modelo_falso([respuesta_ok(sana)])
    cadena = construir_cadena(modelo, max_retries=2)

    with caplog.at_level(logging.WARNING):
        resultado = await process_text(TEXTO, cadena=cadena)

    assert resultado is not None
    assert resultado.nivel_de_criticidad is Criticidad.BAJA
    assert "puede no describir ningun incidente real" in caplog.text
