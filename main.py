"""Mini-script de prueba: ejecuta el pipeline sobre tres textos de ejemplo."""

import asyncio
import logging
import sys

from chain import configurar_logging, process_text

logger = logging.getLogger(__name__)

CASOS: list[tuple[str, str]] = [
    (
        "Log de error",
        "2026-09-10 03:14:22 ERROR api.workers: la API en FastAPI empezo a devolver "
        "504 en el 40 por ciento de las requests. El pool de PostgreSQL se agoto en "
        "20 conexiones y Redis esta respondiendo con latencias de 800ms. Los "
        "consumidores de RabbitMQ quedaron encolados sin procesar.",
    ),
    (
        "Arquitectura sana",
        "El servicio de catalogo corre en FastAPI detras de Nginx, cachea las "
        "respuestas en Redis con un TTL de cinco minutos y persiste en PostgreSQL. "
        "Los despliegues se hacen con Docker sobre Kubernetes y las metricas se "
        "envian a Prometheus. El sistema viene operando sin incidentes.",
    ),
    (
        "Texto ambiguo",
        "Ayer estuvo raro el tema del deploy, algunas cosas iban lentas y otras no. "
        "Capaz sea el cache o la base, no llegamos a mirar los graficos todavia.",
    ),
]


async def main() -> None:
    """Procesa cada texto de ejemplo e imprime el objeto validado que devuelve."""
    # La consola de Windows usa cp1252 y rompe los acentos de la salida en espaniol.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    configurar_logging()

    for titulo, texto in CASOS:
        print(f"\n{'=' * 70}\n{titulo}\n{'=' * 70}")
        resultado = await process_text(texto)

        if resultado is None:
            print("\n-> Sin resultado. El motivo quedo en los logs de arriba.")
            continue

        print(f"\n{resultado.model_dump_json(indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
