# Pre-entrega 2: Pipeline de procesamiento validado

## Qué construir

Debes desarrollar un **Pipeline de Extracción de Entidades Técnicas**. El sistema debe recibir un párrafo de texto sin procesar (por ejemplo, una descripción de arquitectura de software o un log de error) y devolver un objeto validado.

### Los componentes requeridos:

1. **Esquema Pydantic**: Un modelo que defina campos como `tecnologias` (lista de strings), `nivel_de_criticidad` (enum: baja, media, alta), y `resumen_tecnico` (string).
2. **Prompt Template**: Un template modular que acepte el texto de entrada y las instrucciones de formato.
3. **Cadena LCEL**: Una composición que una el Prompt + LLM + Output Parser.
4. **Lógica de Resiliencia**: Configuración de al menos un reintento automático si el LLM devuelve un JSON mal formado o incompleto.


## Pasos sugeridos

1. **Define tu Contrato**: Crea la clase Pydantic. Piensa en qué restricciones quieres poner (ej. que la lista de tecnologías no esté vacía).
2. **Prepara el Parser**: Utiliza `PydanticOutputParser` o el método `.with_structured_output()` de LangChain (preferido para OpenAI/Anthropic).
3. **Ensambla la Cadena**:

   ```python
   chain = prompt | model.with_structured_output(TuEsquema)
   ```

4. **Añade Resiliencia**: Envuelve la llamada con una estrategia de reintento (`.with_retry()`).
5. **Prueba de Estrés**: Pasa un texto ambiguo y verifica si el validador lanza excepciones o si el modelo se recupera.


 
## Errores comunes a evitar

- **Ignorar el `finish_reason`**: A veces el LLM corta la respuesta por falta de tokens. Tu pipeline debe detectar si el objeto está incompleto antes de intentar transformarlo.
- **Hardcoding de Prompts**: Evita las F-strings de Python dentro de la cadena. Usa `ChatPromptTemplate` para mantener la modularidad y permitir que LangChain gestione las variables de entrada.

----

# Qué entregás y en qué formato

- **Tipo:** Código — un repositorio de GitHub.
- **Artefacto concreto:** repo con `schemas.py` (modelo Pydantic) y `chain.py` (cadena LCEL con `.with_structured_output()` y reintento `.with_retry()`). Las instrucciones van en el `README.md`.
- **Script de pruebas:** Repositorio de GitHub con el código del pipeline, incluyendo el modelo Pydantic, el prompt template y la cadena LCEL con lógica de reintentos. Debe incluir un mini-script de prueba asíncrono.

## Descripción


 
1. Crea un archivo `schemas.py` donde definas la estructura de salida deseada usando Pydantic.
2. En `chain.py`, configura un cliente de ChatOpenAI o ChatAnthropic (reutilizando la lógica del Módulo 1).
3. Crea un `ChatPromptTemplate` que instruya al modelo para extraer información técnica de un texto.
4. Construye la cadena usando LCEL: `prompt | model.with_structured_output(Schema)`.
5. Implementa una función asíncrona `process_text(text: str)` que ejecute la cadena usando `.ainvoke()`.
6. Asegúrate de incluir logs adecuados para observar el proceso de validación y posibles reintentos.


### Ejemplo de la salida esperada

Dado un texto de entrada (ej. un log de error o descripción de arquitectura), tu pipeline debe devolver un objeto validado como este:

```json
{  
  "tecnologias": ["FastAPI", "Redis", "PostgreSQL"],  
  "nivel_de_criticidad": "alta",  
  "resumen_tecnico": "API con caché en Redis y persistencia en PostgreSQL; cuello de botella en conexiones concurrentes."  
}
```

### Checklist de entrega

- Repositorio de GitHub con `schemas.py` (modelo Pydantic) y `chain.py` (cadena LCEL).
- Cadena compuesta con LCEL: `prompt | model.with_structured_output(Schema)`.
- Lógica de reintento (`.with_retry()`) ante JSON mal formado o incompleto.
- Función asíncrona `process_text()` con `.ainvoke()` y logs de validación.
- Mini-script de prueba que ejecute un ejemplo.
  
----

## Entorno

Estoy utilizando `uv` es una herramienta todo-en-uno para gestionar el ciclo de vida de proyectos Python: intérprete, entorno virtual, dependencias, ejecución y distribución.

### Crear un proyecto
`uv init mi-proyecto`
`cd mi-proyecto`

### Agregar dependencias
`uv add requests pydantic`

### Crear o sincronizar el entorno
`uv sync`

### Ejecutar el proyecto usando el entorno administrado por uv
`uv run python main.py`

### Ejecutar los tests
`uv run pytest`


### Convenciones

- Usar Python 3.12.
- Preferir funciones async cuando haya operaciones de I/O.
- Agregar tests para toda nueva funcionalidad.
- No modificar archivos de configuración de producción sin confirmación.

----

# Decisiones de implementación

Esta sección resuelve las ambigüedades del enunciado. Ante una contradicción con
el texto de arriba, **manda esta sección**.

## Estructura del repositorio

Layout plano en la raíz, espejando `entrega_1`:

```
schemas.py        modelos Pydantic (salida, entrada y configuración)
providers.py      capa anticorrupción: crea el chat model y declara qué
                  excepciones del SDK son transitorias, por proveedor
chain.py          carga de config, prompt, cadena LCEL y process_text()
main.py           mini-script asíncrono de prueba (pega contra la API real)
tests/test_chain.py   tests offline con LLM falso (sin API key, sin costo)
```

`providers.py` cumple en la era LangChain el rol que en `entrega_1` cumplía la
carpeta `clients/`: es el **único** módulo que sabe que existen OpenAI y Anthropic.

## Proveedor y configuración

- Se reutiliza el patrón de configuración de `entrega_1`
  (`https://github.com/diegofziegler/entrega_1.git`): el enum `Provider`, el modelo
  `ModelConfig` con `SecretStr`, y los helpers de lectura de entorno.
- **No** se reutiliza la carpeta `clients/`: en el Módulo 1 se usaban los SDK crudos
  de OpenAI y Anthropic; acá esa capa la reemplaza `ChatOpenAI` / `ChatAnthropic`
  de LangChain.
- El proveedor se elige con `LLM_PROVIDER` (`openai` | `anthropic`), ya presente en
  `.env.example` junto a `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `LLM_TEMPERATURE`,
  `LLM_MAX_TOKENS` y `LLM_MAX_RETRIES`. Se carga con `python-dotenv`.
- `ModelConfig` suma `max_retries: int = Field(default=2, ge=1)`. El `ge=1` hace
  cumplir el "al menos un reintento" de la consigna, y el default permite que un
  `.env` que no traiga la variable siga funcionando sin cambios.
- `LLM_TEMPERATURE=0.7` se mantiene a propósito: con temperatura 0 un reintento
  reproduce exactamente el mismo error y la resiliencia no sirve de nada.

## Contrato de salida (`schemas.py`)

- `tecnologias: list[str]` con `min_length=1`. Si el texto no menciona ninguna
  tecnología, es un **fallo esperado**: se agotan los reintentos y `process_text`
  devuelve `None` tras loguear el motivo.
- `nivel_de_criticidad: Criticidad` con exactamente tres valores: `baja`, `media`,
  `alta`. Es la criticidad **del problema descrito**, no la de cada tecnología
  suelta (ej.: si afecta a más de un componente, sube).
- Cuando el texto no describe ningún error o problema (típicamente una descripción
  de arquitectura sana), el modelo debe responder `baja` y **decir explícitamente en
  `resumen_tecnico` que no se detectó ningún error o problema**. El pipeline además
  emite un log `WARNING` cuando la criticidad es `baja`, recordando verificar si el
  texto describía un incidente real.
- `resumen_tecnico: str` siempre en español.

## Parser y detección de truncamiento

- Se usa `.with_structured_output(Extraccion, include_raw=True)`. Reemplaza al
  `PydanticOutputParser`, así que el `ChatPromptTemplate` **no** lleva variable
  `{format_instructions}`: el esquema viaja como JSON Schema vía tool-calling.
- `include_raw=True` hace que los errores de parseo **dejen de lanzar excepción** y
  vuelvan en la clave `parsing_error` del dict `{"raw", "parsed", "parsing_error"}`.
  Por eso la cadena lleva un paso final `RunnableLambda(_verificar_respuesta)` que:
  1. detecta truncamiento leyendo el `raw`: `finish_reason == "length"` en OpenAI o
     `stop_reason == "max_tokens"` en Anthropic;
  2. detecta `parsing_error` no nulo o `parsed is None`;
  3. en cualquiera de esos casos **relanza** como `RespuestaLLMInvalida` para que el
     reintento se dispare; si no, devuelve el objeto Pydantic ya validado.

## Reintentos

- `.with_retry()` se aplica a la **cadena completa**, con `wait_exponential_jitter=True`
  y `exponential_jitter_params={"initial": 1.0, "max": 20.0}` (los 429 necesitan esperas
  más largas que el default).
- La cantidad sale de la config: **`stop_after_attempt=config.max_retries + 1`**.
  `stop_after_attempt` cuenta *intentos totales*, no reintentos, así que el `+1` es
  obligatorio; sin él, `LLM_MAX_RETRIES=1` daría cero reintentos reales. Con el
  default `LLM_MAX_RETRIES=2` quedan 3 llamadas como máximo.
- **Ojo:** `with_retry()` no acepta un predicado. Su firma real en langchain-core
  1.6.2 es `(*, retry_if_exception_type, wait_exponential_jitter,
  exponential_jitter_params, stop_after_attempt)`. El `retry_on_exception=callable`
  que aparece en el ejemplo del Módulo 2 no existe y lanza `TypeError`; el filtrado
  se hace **por tipo de excepción**.

### Qué se reintenta

1. `RespuestaLLMInvalida` y su subclase `RespuestaTruncada` (JSON malformado,
   `parsing_error`, respuesta cortada por tokens).
2. Los errores **transitorios del proveedor activo**: rate limit, corte de conexión,
   timeout y 5xx.

Un `ValidationError` originado en la entrada humana **no** se reintenta: el input se
valida *antes* de invocar la cadena, se loguea de forma accionable y se devuelve
`None`.

### Cómo se desacopla la detección por proveedor

Los SDK de OpenAI y Anthropic tienen jerarquías **estructuralmente idénticas pero sin
base común** (`OpenAIError` y `AnthropicError` cuelgan directo de `Exception`), así que
no hay ningún `isinstance` transversal que sirva. La solución es un **registro por
proveedor con imports diferidos** en `providers.py`, de modo que el acoplamiento viva
en un solo archivo y no haga falta tener instalado el SDK que no se usa:

```python
def _transitorias_openai() -> tuple[type[BaseException], ...]:
    from openai import (APIConnectionError, APITimeoutError,
                        InternalServerError, RateLimitError)
    return (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)

def _transitorias_anthropic() -> tuple[type[BaseException], ...]:
    from anthropic import (APIConnectionError, APITimeoutError,
                           InternalServerError, RateLimitError)
    return (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)

_REGISTRO: dict[Provider, ProveedorLLM] = {
    Provider.OPENAI:    ProveedorLLM(crear=_crear_openai,    transitorias=_transitorias_openai),
    Provider.ANTHROPIC: ProveedorLLM(crear=_crear_anthropic, transitorias=_transitorias_anthropic),
}
```

`chain.py` nunca importa `openai` ni `anthropic`; sólo pide la tupla al registro:

```python
transitorias = providers.excepciones_transitorias(config.provider)
cadena = base.with_retry(
    retry_if_exception_type=(RespuestaLLMInvalida, *transitorias),
    stop_after_attempt=3,
    wait_exponential_jitter=True,
)
```

Sumar un tercer proveedor es agregar una entrada al diccionario. Si el proveedor no
está en el registro se levanta un error explícito, igual que hacía
`AsyncLLMManager._crear_cliente()` en `entrega_1`.

### Desactivar el reintento interno del SDK

`ChatAnthropic` trae `max_retries=2` y `ChatOpenAI` lo deja en `None`, delegando en el
default del SDK de OpenAI, que también es 2. Esos reintentos ocurren **por debajo** de
LangChain: son invisibles a nuestros logs y se multiplican con los nuestros (hasta 9
llamadas por invocación). Por eso los modelos se construyen con **`max_retries=0`**, y
nuestra capa `.with_retry()` queda como única responsable y única fuente de verdad
para el logging.

Ese `0` va **fijo en el código, no en `.env`**: no es un parámetro de tuning sino una
invariante del diseño. El único contador ajustable es `LLM_MAX_RETRIES`.

Contrapartida asumida: el SDK respeta el header `Retry-After` de los 429 y
`wait_exponential_jitter` no lo lee. Se compensa con el backoff más largo declarado
arriba.

## `process_text()` y logging

- Firma: `async def process_text(text: str) -> Extraccion | None`, ejecutando la
  cadena con `.ainvoke()`.
- Devuelve `None` ante cualquier fallo y **siempre loguea la excepción**.
- Módulo `logging` de la stdlib, un logger por módulo (`logging.getLogger(__name__)`),
  nivel **DEBUG** y formato estándar con timestamp:

  ```python
  logging.basicConfig(
      level=logging.DEBUG,
      format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
      datefmt="%Y-%m-%d %H:%M:%S",
  )
  ```

- **La raíz queda en `WARNING` y sólo los módulos propios bajan a DEBUG.** En DEBUG las
  librerías HTTP vuelcan cada petición con la cabecera `Authorization: Bearer ...`.
  Enumerar loggers de terceros para silenciarlos **no funciona**: se probó y los SDK de
  OpenAI y Anthropic no usan `httpx`/`httpcore` sino **`httpx2`/`httpcore2`**, así que
  la lista no atrapaba nada y las cabeceras se filtraban igual. El criterio invertido
  es seguro por defecto y no depende de acertar nombres:

  ```python
  logging.basicConfig(level=logging.WARNING, format=FORMATO_LOG, datefmt=FORMATO_FECHA)
  for nombre in ("chain", "providers", "schemas", "__main__"):
      logging.getLogger(nombre).setLevel(logging.DEBUG)
  ```

- Nunca se loguea la API key ni el texto de entrada completo (se trunca a ~200 chars).
- Todos los mensajes de log van en español. Si el texto de una excepción de librería
  viene en inglés, se propaga tal cual sin traducir.

## Pruebas

### El punto de inyección

Los chat models falsos de langchain-core (`FakeListChatModel`, `GenericFakeChatModel`,
etc.) **no** implementan `with_structured_output`: lanzan
`NotImplementedError: with_structured_output is not implemented for this model`. No
sirven para este pipeline.

La costura correcta es un nivel más arriba: `chain.py` expone

```python
def construir_cadena(estructurado: Runnable, max_retries: int, transitorias: tuple) -> Runnable:
    return (prompt | estructurado | RunnableLambda(_verificar_respuesta)).with_retry(...)
```

En producción se le pasa `modelo.with_structured_output(Extraccion, include_raw=True)`;
en los tests, un `RunnableLambda` que devuelve el dict
`{"raw", "parsed", "parsing_error"}` que se necesite, o que lanza la excepción del caso.
Así el prompt, el `_verificar_respuesta` y el `.with_retry()` bajo prueba son **los
reales**; lo único que se sustituye es la llamada de red. La composición literal
`prompt | model.with_structured_output(Schema)` que pide el checklist se conserva.

### Cobertura

`tests/test_chain.py` corre **offline**, sin API key ni costo:

- recuperación tras un `parsing_error` (JSON malformado);
- detección de truncamiento por `finish_reason == "length"` / `stop_reason == "max_tokens"`;
- `ValidationError` de entrada humana: loguea y devuelve `None` **sin** reintentar;
- agotamiento de reintentos → `None`;
- con `LLM_MAX_RETRIES=1` y fallo permanente, **exactamente 2 llamadas**, blindando el
  `+1` de `stop_after_attempt`;
- errores transitorios sin importar los SDK: el test le pide el tipo al registro
  (`providers.excepciones_transitorias(...)[0]`), lo lanza una vez y verifica que la
  segunda invocación tenga éxito;
- el registro de `providers.py` cubre todos los valores de `Provider`.

### Contra la API real

- `main.py` es el mini-script asíncrono de la entrega: un log de error, una arquitectura
  sana y un texto ambiguo. Requiere las claves en `.env`; las provee quien lo ejecute.
- Además hay un test de integración marcado `@pytest.mark.integration` que hace una
  llamada real y **se saltea solo** (`pytest.skip`) si no hay API key en el entorno. Así
  `uv run pytest` funciona con o sin claves, y con claves valida el camino completo.

## Dependencias

El intérprete está fijado a **3.12** en `.python-version` (con `requires-python =
">=3.12"`, `uv` había resuelto 3.14, que contradice la convención). Ese archivo se
commitea.

Ya instaladas en `pyproject.toml` con `uv add`:

- runtime: `langchain-core`, `langchain-openai`, `langchain-anthropic`, `pydantic`,
  `python-dotenv`. Los SDK `openai` y `anthropic` entran como dependencias transitivas,
  que es lo que permite el import diferido de `providers.py`.
- dev: `pytest`, `pytest-asyncio` (con `asyncio_mode = "auto"` y `testpaths = ["tests"]`
  en `[tool.pytest.ini_options]`).

## Entregable

Repositorio ya inicializado y apuntando a `github.com/diegofziegler/entrega_2.git`.

`README.md` acotado a dos cosas: **instrucciones de setup** (requisitos, copiar
`.env.example` a `.env` y completar las claves, `uv sync`) y **cómo ejecutar el
ejemplo** (`uv run python main.py`, y `uv run pytest` para los tests). Sin secciones de
arquitectura ni de diseño: eso vive en este archivo.


 
