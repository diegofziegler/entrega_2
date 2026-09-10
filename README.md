# Pipeline de Extracción de Entidades Técnicas

Recibe un párrafo de texto sin procesar (un log de error o una descripción de
arquitectura) y devuelve un objeto validado con las tecnologías mencionadas, el nivel
de criticidad del problema y un resumen técnico.

## Requisitos

- Python 3.12 (queda fijado en `.python-version`; `uv` lo descarga solo si falta).
- [`uv`](https://docs.astral.sh/uv/).
- Una API key de OpenAI **o** de Anthropic.

## Setup

```bash
git clone https://github.com/diegofziegler/entrega_2.git
cd entrega_2
uv sync
```

Copiá el archivo de ejemplo y completá tus credenciales:

```bash
cp .env.example .env      # en PowerShell: Copy-Item .env.example .env
```

Editá `.env`:

| Variable | Descripción | Default |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` o `anthropic` | `openai` |
| `OPENAI_API_KEY` | Requerida si el proveedor es `openai` | — |
| `ANTHROPIC_API_KEY` | Requerida si el proveedor es `anthropic` | — |
| `OPENAI_MODEL` | Modelo de OpenAI | `gpt-4o-mini` |
| `ANTHROPIC_MODEL` | Modelo de Anthropic | `claude-haiku-4-5-20251001` |
| `LLM_TEMPERATURE` | Temperatura | `0.7` |
| `LLM_MAX_TOKENS` | Máximo de tokens de la respuesta | `1024` |
| `LLM_MAX_RETRIES` | Reintentos de la cadena (mínimo 1) | `2` |

`.env` está en `.gitignore`: no se commitea.

## Ejecutar el ejemplo

```bash
uv run python main.py
```

Procesa tres textos —un log de error, una arquitectura sana y un texto ambiguo— y
muestra el objeto validado de cada uno junto con los logs del proceso.

Salida esperada para el primer caso:

```json
{
  "tecnologias": ["FastAPI", "PostgreSQL", "Redis", "RabbitMQ"],
  "nivel_de_criticidad": "alta",
  "resumen_tecnico": "La API en FastAPI presenta una degradación crítica con 40% de requests retornando 504, causada por agotamiento del pool de conexiones de PostgreSQL y latencias extremas en Redis."
}
```

## Tests

```bash
uv run pytest
```

Los tests unitarios corren **offline**, sin API key ni costo. Hay además un test de
integración que hace una llamada real y se saltea solo si no encuentra credenciales.
Para correr únicamente uno u otro:

```bash
uv run pytest -m "not integration"   # solo offline
uv run pytest -m integration         # solo la llamada real
```

## Uso desde código

```python
import asyncio
from chain import configurar_logging, process_text

configurar_logging()
resultado = asyncio.run(process_text("La API en FastAPI devuelve 504..."))
# -> Extraccion | None  (None ante cualquier fallo; el motivo queda en el log)
```
