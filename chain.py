"""Cadena LCEL de extraccion de entidades tecnicas, con validacion y reintentos."""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import SecretStr, ValidationError

import providers
from schemas import Criticidad, Extraccion, ModelConfig, Provider, TextoEntrada

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Excepciones propias
# --------------------------------------------------------------------------- #


class RespuestaLLMInvalida(Exception):
    """El LLM respondio algo que no cumple el contrato. Amerita reintento."""


class RespuestaTruncada(RespuestaLLMInvalida):
    """El LLM corto la respuesta por limite de tokens. Amerita reintento."""


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

FORMATO_LOG = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"

_MODULOS_PROPIOS = ("chain", "providers", "schemas", "__main__")

MAX_CHARS_LOG = 200


def configurar_logging(nivel: int = logging.DEBUG) -> None:
    """Pone en DEBUG solo nuestros modulos; todo lo demas queda en WARNING.

    Enumerar los loggers de terceros para silenciarlos es fragil: los SDK de OpenAI
    y Anthropic usan `httpx2`/`httpcore2`, no `httpx`/`httpcore`, y en DEBUG vuelcan
    cada peticion HTTP con la cabecera Authorization que lleva la API key. Por eso
    se invierte el criterio: la raiz queda en WARNING y solo se baja el nivel de los
    modulos propios. Asi una libreria nueva no puede filtrar nada por descuido.
    """
    logging.basicConfig(
        level=logging.WARNING, format=FORMATO_LOG, datefmt=FORMATO_FECHA
    )
    for nombre in _MODULOS_PROPIOS:
        logging.getLogger(nombre).setLevel(nivel)


def _recortar(texto: str, limite: int = MAX_CHARS_LOG) -> str:
    """Acorta un texto para que los logs no vuelquen entradas enteras."""
    limpio = " ".join(texto.split())
    if len(limpio) <= limite:
        return limpio
    return f"{limpio[:limite]}[...]"


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #

# Sin f-strings ni concatenacion de variables: las entradas las gestiona LangChain.
INSTRUCCIONES_SISTEMA = (
    "Sos un analista tecnico. Extraes informacion estructurada de textos sin "
    "procesar, como logs de error o descripciones de arquitectura de software.\n"
    "\n"
    "Reglas:\n"
    "1. En 'tecnologias' van unicamente nombres propios de productos nombrados de "
    "forma explicita en el texto, por ejemplo FastAPI, Redis, PostgreSQL o "
    "Kubernetes. No inventar ni inferir. No incluir categorias genericas como "
    "'cache', 'base de datos', 'API', 'el deploy' o 'el servidor'.\n"
    "2. 'nivel_de_criticidad' describe el problema en su conjunto, no cada "
    "tecnologia por separado. Sube a 'media' o 'alta' cuando el problema afecta a "
    "mas de un componente o compromete la disponibilidad del sistema.\n"
    "3. Si el texto no describe ningun error ni problema, por ejemplo una "
    "descripcion de arquitectura sana, usar 'baja' y aclarar de forma explicita en "
    "'resumen_tecnico' que no se detecto ningun error o problema.\n"
    "4. 'resumen_tecnico' va siempre en espaniol, en una o dos oraciones.\n"
    "5. Responder unicamente con la estructura pedida, completa."
)

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", INSTRUCCIONES_SISTEMA),
        ("human", "Analiza el siguiente texto:\n\n{texto}"),
    ]
)


# --------------------------------------------------------------------------- #
# Verificacion de la respuesta cruda
# --------------------------------------------------------------------------- #

# OpenAI lo informa en finish_reason, Anthropic en stop_reason.
_MOTIVOS_TRUNCAMIENTO = {"length", "max_tokens"}


def _motivo_de_corte(bruto: Any) -> str | None:
    """Devuelve por que se corto la respuesta, o None si termino completa.

    OpenAI informa el corte por tokens en `finish_reason='length'` y Anthropic en
    `stop_reason='max_tokens'`; se miran las dos claves para no depender del
    proveedor activo.
    """
    metadata = getattr(bruto, "response_metadata", None) or {}
    for clave in ("finish_reason", "stop_reason"):
        motivo = metadata.get(clave)
        if motivo in _MOTIVOS_TRUNCAMIENTO:
            return f"{clave}={motivo}"
    return None


def _verificar_respuesta(payload: dict[str, Any]) -> Extraccion:
    """Convierte el dict de `include_raw=True` en un objeto validado.

    `include_raw=True` es necesario para poder mirar el motivo de corte del modelo,
    pero tiene un efecto lateral: los errores de parseo dejan de lanzar excepcion y
    vuelven en la clave 'parsing_error'. Sin este paso, `.with_retry()` nunca se
    disparia. Aca se detecta el problema y se relanza para que el reintento ocurra.
    """
    motivo = _motivo_de_corte(payload.get("raw"))
    if motivo is not None:
        logger.warning(
            "Respuesta truncada por limite de tokens (%s); se reintentara.", motivo
        )
        raise RespuestaTruncada(f"El modelo corto la respuesta ({motivo}).")

    error_de_parseo = payload.get("parsing_error")
    if error_de_parseo is not None:
        logger.warning(
            "El modelo devolvio una estructura invalida (%s); se reintentara.",
            error_de_parseo,
        )
        raise RespuestaLLMInvalida(f"Salida no parseable: {error_de_parseo}")

    parseado = payload.get("parsed")
    if parseado is None:
        logger.warning("El modelo no devolvio ninguna estructura; se reintentara.")
        raise RespuestaLLMInvalida("El modelo no devolvio ninguna estructura.")

    logger.debug("Respuesta validada contra el esquema Extraccion.")
    return parseado


def _registrar_intento(valor: Any) -> Any:
    """Deja rastro de cada intento, incluidos los que provoca `.with_retry()`."""
    logger.debug("Invocando al modelo.")
    return valor


# --------------------------------------------------------------------------- #
# Construccion de la cadena
# --------------------------------------------------------------------------- #


# Los 429 necesitan esperas mas largas que el default de tenacity. Es un modulo
# aparte para que los tests puedan acortarlo y no dormir de verdad.
JITTER_REINTENTOS = {"initial": 1.0, "max": 20.0}


def construir_cadena(
    estructurado: Runnable,
    max_retries: int,
    transitorias: tuple[type[BaseException], ...] = (),
) -> Runnable:
    """Compone la cadena LCEL y le agrega la politica de reintentos.

    `estructurado` es el punto de inyeccion: en produccion recibe
    `modelo.with_structured_output(Extraccion, include_raw=True)`; en los tests, un
    Runnable falso. Asi el prompt, la verificacion y el reintento bajo prueba son
    los reales y solo se sustituye la llamada de red.
    """
    cadena = (
        PROMPT
        | RunnableLambda(_registrar_intento)
        | estructurado
        | RunnableLambda(_verificar_respuesta)
    )

    # stop_after_attempt cuenta intentos totales, no reintentos: sin el +1,
    # max_retries=1 daria cero reintentos reales.
    return cadena.with_retry(
        retry_if_exception_type=(RespuestaLLMInvalida, *transitorias),
        stop_after_attempt=max_retries + 1,
        wait_exponential_jitter=True,
        exponential_jitter_params=JITTER_REINTENTOS,
    )


def crear_cadena(config: ModelConfig) -> Runnable:
    """Arma la cadena de produccion para el proveedor configurado."""
    modelo = providers.crear_modelo(config)
    estructurado = modelo.with_structured_output(Extraccion, include_raw=True)
    transitorias = providers.excepciones_transitorias(config.provider)

    logger.info(
        "Cadena lista | proveedor=%s modelo=%s reintentos=%d",
        config.provider.value,
        config.model,
        config.max_retries,
    )
    return construir_cadena(estructurado, config.max_retries, transitorias)


# --------------------------------------------------------------------------- #
# Configuracion desde el entorno
# --------------------------------------------------------------------------- #


def _secreto(nombre: str) -> SecretStr | None:
    """Lee una credencial del entorno y la envuelve en SecretStr.

    `SecretStr` evita que la clave aparezca al imprimir o loguear la configuracion.
    """
    valor = os.getenv(nombre)
    return SecretStr(valor) if valor else None


def _modelo_para(provider: Provider) -> str:
    """Devuelve el modelo configurado para el proveedor, o su default."""
    if provider is Provider.OPENAI:
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if provider is Provider.ANTHROPIC:
        return os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    raise ValueError(f"Proveedor no soportado: {provider}")


def cargar_config() -> ModelConfig:
    """Lee la configuracion del entorno, cargando antes el archivo .env."""
    load_dotenv()

    crudo = os.getenv("LLM_PROVIDER", Provider.OPENAI.value).strip().lower()
    try:
        provider = Provider(crudo)
    except ValueError as error:
        soportados = ", ".join(p.value for p in Provider)
        raise ValueError(
            f"LLM_PROVIDER='{crudo}' no es valido. Opciones: {soportados}."
        ) from error

    return ModelConfig(
        provider=provider,
        model=_modelo_para(provider),
        openai_api_key=_secreto("OPENAI_API_KEY"),
        anthropic_api_key=_secreto("ANTHROPIC_API_KEY"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
    )


_cadena_por_defecto: Runnable | None = None


def obtener_cadena() -> Runnable:
    """Devuelve la cadena de produccion, construyendola una sola vez."""
    global _cadena_por_defecto
    if _cadena_por_defecto is None:
        _cadena_por_defecto = crear_cadena(cargar_config())
    return _cadena_por_defecto


# --------------------------------------------------------------------------- #
# Punto de entrada del pipeline
# --------------------------------------------------------------------------- #


async def process_text(text: str, *, cadena: Runnable | None = None) -> Extraccion | None:
    """Extrae entidades tecnicas de un texto y devuelve el objeto validado.

    Devuelve None ante cualquier fallo, siempre dejando el motivo en el log. El
    parametro `cadena` existe para inyectar una cadena de prueba.
    """
    try:
        entrada = TextoEntrada(texto=text)
    except ValidationError as error:
        # Error de la persona, no del LLM: no se reintenta ni se gasta una llamada.
        logger.error(
            "Entrada invalida, no se llama al LLM: %s",
            "; ".join(detalle["msg"] for detalle in error.errors()),
        )
        return None

    try:
        activa = cadena if cadena is not None else obtener_cadena()
    except (ValueError, ValidationError) as error:
        logger.error("No se pudo construir la cadena: %s", error)
        return None

    logger.info(
        "Procesando texto de %d caracteres: %s",
        len(entrada.texto),
        _recortar(entrada.texto),
    )

    try:
        resultado: Extraccion = await activa.ainvoke({"texto": entrada.texto})
    except RespuestaLLMInvalida as error:
        logger.error("Se agotaron los reintentos sin respuesta valida: %s", error)
        return None
    except ValidationError as error:
        logger.error("El LLM devolvio un objeto que no cumple el contrato: %s", error)
        return None
    except Exception as error:  # noqa: BLE001 - se registra y se degrada a None
        logger.exception("Fallo inesperado al procesar el texto: %s", error)
        return None

    if resultado.nivel_de_criticidad is Criticidad.BAJA:
        logger.warning(
            "Criticidad 'baja': el texto puede no describir ningun incidente real. "
            "Resumen: %s",
            resultado.resumen_tecnico,
        )

    logger.info(
        "Extraccion valida | tecnologias=%s criticidad=%s",
        resultado.tecnologias,
        resultado.nivel_de_criticidad.value,
    )
    return resultado
