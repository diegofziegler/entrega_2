"""Contratos de datos del pipeline: entrada, salida y configuracion."""

from enum import Enum

from pydantic import BaseModel, Field, SecretStr, field_validator


class Provider(str, Enum):
    """Proveedores de LLM soportados."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class Criticidad(str, Enum):
    """Nivel de criticidad del problema descrito en el texto."""

    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"


class Extraccion(BaseModel):
    """Entidades tecnicas extraidas de un texto sin procesar.

    Es el contrato de salida del pipeline: si el LLM no lo satisface, la cadena
    reintenta.
    """

    tecnologias: list[str] = Field(
        min_length=1,
        description=(
            "Tecnologias, frameworks, motores o servicios nombrados en el texto. "
            "Nombres propios tal como se escriben, por ejemplo FastAPI, Redis, "
            "PostgreSQL. No incluir conceptos genericos como 'base de datos'."
        ),
    )
    nivel_de_criticidad: Criticidad = Field(
        description=(
            "Criticidad del problema descrito en su conjunto, no de cada tecnologia "
            "por separado: sube si el problema afecta a mas de un componente o si "
            "compromete la disponibilidad. Si el texto no describe ningun error ni "
            "problema, usar 'baja'."
        ),
    )
    resumen_tecnico: str = Field(
        min_length=1,
        description=(
            "Resumen tecnico en espaniol, de una o dos oraciones. Si el texto no "
            "describe ningun error ni problema, decirlo explicitamente."
        ),
    )

    @field_validator("tecnologias")
    @classmethod
    def _normalizar_tecnologias(cls, valores: list[str]) -> list[str]:
        """Limpia espacios y elimina duplicados sin distinguir mayusculas.

        Conserva el orden de aparicion y la grafia de la primera ocurrencia.
        """
        vistas: set[str] = set()
        limpias: list[str] = []

        for valor in valores:
            nombre = valor.strip()
            if not nombre:
                continue
            clave = nombre.casefold()
            if clave in vistas:
                continue
            vistas.add(clave)
            limpias.append(nombre)

        if not limpias:
            raise ValueError(
                "El modelo no identifico ninguna tecnologia en el texto; "
                "'tecnologias' no puede quedar vacia."
            )

        return limpias

    @field_validator("resumen_tecnico")
    @classmethod
    def _resumen_no_vacio(cls, valor: str) -> str:
        """Rechaza un resumen que sea solo espacios en blanco."""
        resumen = valor.strip()
        if not resumen:
            raise ValueError("'resumen_tecnico' no puede ser solo espacios.")
        return resumen


class TextoEntrada(BaseModel):
    """Valida el texto que aporta la persona, antes de gastar una llamada al LLM."""

    texto: str = Field(
        min_length=20,
        description="Parrafo a analizar: log de error o descripcion de arquitectura.",
    )

    @field_validator("texto")
    @classmethod
    def _sin_relleno(cls, valor: str) -> str:
        """Exige 20 caracteres utiles.

        `min_length` cuenta los espacios, asi que una cadena de puros blancos lo
        satisface; el recorte previo evita gastar una llamada al LLM por nada.
        """
        texto = valor.strip()
        if len(texto) < 20:
            raise ValueError(
                "El texto debe tener al menos 20 caracteres utiles; "
                f"se recibieron {len(texto)} tras quitar espacios."
            )
        return texto


class ModelConfig(BaseModel):
    """Configuracion del cliente LLM, tomada del entorno."""

    provider: Provider
    model: str = Field(min_length=1)
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, gt=0)
    # ge=1 hace cumplir el "al menos un reintento" que exige la consigna.
    max_retries: int = Field(default=2, ge=1)
