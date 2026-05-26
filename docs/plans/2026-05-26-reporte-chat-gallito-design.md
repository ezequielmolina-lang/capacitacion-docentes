# Pregúntale al gallito — chat sobre el reporte de tu escuela

**Diseño · 2026-05-26**

## Propósito

Una página en `eligiendomicamino.org/reporte/` donde directores, docentes de matemática y tutores pueden conversar con una IA (Claude Opus 4.7) sobre el reporte quincenal de su escuela / sección. La IA conoce el contenido completo del PDF de esa persona y responde con la voz del gallito de Eligiendo Mi Camino.

## Contexto

El programa entrega 436 PDFs por ciclo (Director × 85 escuelas + Matemática × secciones + Tutoría × secciones). Los reportes son densos (5 páginas, tablas, comparaciones con UGEL y programa, perfiles RIASEC, plan de acción). Muchos usuarios — sobre todo directores con poco tiempo — no terminan de leerlos. El chat baja la barrera: pregunto en lenguaje natural, el gallito me explica y me sugiere acciones.

## URL & despliegue

- **Página**: `eligiendomicamino.org/reporte/` — nueva carpeta `reporte/` en el repo [capacitacion-docentes](../../reporte/), un solo `index.html`.
- **Proxy API**: Vercel Serverless Function en un proyecto Vercel separado (e.g. `emc-reporte-api`), URL como `emc-reporte-api.vercel.app/api/chat`. Guarda la `ANTHROPIC_API_KEY` como env var en el dashboard de Vercel, recibe `POST /api/chat` y reenvía a Claude. Streaming SSE de vuelta al navegador.
- **Datos del reporte**: script Python único que extrae texto de los 436 PDFs → `reportes-data/{director|matematica|tutoria}/{codigo}_{seccion}.json`. Aprox. 1 MB total, vive en el repo.

## Flujo del usuario (4 pantallas)

### Pantalla 1 — Bienvenida
- Gallito centrado, ~200px, sobre fondo crema.
- Saludo: "Hola, soy el gallito de Eligiendo Mi Camino." + subtítulo: "Te ayudo a entender tu reporte y a decidir qué hacer."
- Botón único: **Empezar**.

### Pantalla 2 — ¿Quién eres?
- Tres tarjetas grandes, ícono + nombre del rol:
  - **Director(a)**
  - **Docente de Matemática**
  - **Tutor(a) de aula**
- Click en una avanza.

### Pantalla 3 — ¿Tu escuela?
- UGEL: dropdown (7 UGELs: 01 SJ Miraflores, 02 Rímac, 03 Breña, 04 Comas, 05 SJ Lurigancho, 06 Ate, 07 San Borja).
- Escuela: dropdown filtrado por UGEL (10–15 escuelas por UGEL).
- Si rol = matemática o tutoría: campo extra **Sección** (A/B/C/D/E/U según lo que exista para esa escuela en `index.json`).
- Botón **Continuar**.

### Pantalla 3.5 — Verificación suave (privacidad)
- "Para abrir tu reporte, escribe tu primer nombre tal como aparece en la página 1 — ahí donde dice 'Hola, _____'."
- Input + botón **Abrir reporte**. Compara case-insensitive contra el nombre extraído del JSON del reporte. Si no coincide: "No reconozco ese nombre. Revisa la primera página del PDF, o pide ayuda a tu acompañante."
- (Esto bloquea snooping casual sin friccionar al usuario legítimo que tiene el PDF en mano.)

### Pantalla 4 — Chat
- Top bar: gallito pequeño + chip con `Director · 7082 Juan de Espinosa Medrano · UGEL 01`.
- Tres tarjetas de pregunta sugerida (según el rol):
  - Director: "¿Qué destaca de mi escuela?" / "¿Qué debo priorizar esta semana?" / "Compárame con mi UGEL".
  - Matemática: "¿Cómo va mi sección?" / "¿Qué estudiantes necesitan atención?" / "Ideas para mi próxima clase".
  - Tutoría: "Explícame los perfiles RIASEC de mi sección" / "¿Qué hacer en la próxima sesión?" / "¿Quiénes necesitan que les pregunte más?".
- Mensajes en burbujas (usuario a la derecha en naranja `--primary`, gallito a la izquierda en crema con borde).
- Input de mensaje abajo, fijo. Enter envía, shift+enter nueva línea.
- Footer con tres acciones: **Ver PDF original** · **WhatsApp a mi acompañante** (link directo `wa.me/<número del acompañante>`) · **Cambiar reporte** (vuelve a pantalla 2).

## Arquitectura técnica

### Frontend (`reporte/index.html`)
- Un archivo HTML autónomo (sin Node.js), igual que el resto del sitio: React + Tailwind por CDN, ó vanilla JS si prefiero simpleza. Decisión: **vanilla JS** — la página es pequeña, no necesita el peso de React.
- Estado en memoria: `{role, ugel, codigo, seccion, name_typed, report_text, messages}`.
- En montaje: fetch `reportes-data/index.json` para llenar dropdowns.
- Al confirmar pantalla 3.5: fetch `reportes-data/{role}/{codigo}_{seccion}.json` para tener `report_text` y `greeting_name`.
- Cada turno: `POST {worker_url}/chat` con `{messages, role, report_text, school_label}`, recibe streaming, va pintando.

### Backend — Vercel Serverless Function
Proyecto Vercel separado del repo de GitHub Pages (`capacitacion-docentes` se queda en GH Pages). Estructura mínima:
```
emc-reporte-api/
├── api/
│   └── chat.js
├── package.json
└── vercel.json
```

`api/chat.js`:
```javascript
export const config = { runtime: "edge" };  // streaming-friendly

const ALLOWED_ORIGIN = "https://eligiendomicamino.org";

export default async function handler(req) {
  const cors = {
    "access-control-allow-origin": ALLOWED_ORIGIN,
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-allow-headers": "content-type",
  };
  if (req.method === "OPTIONS") return new Response(null, { headers: cors });
  if (req.method !== "POST") return new Response("Not found", { status: 404, headers: cors });

  const { messages, role, report_text, school_label } = await req.json();
  const system = buildSystemPrompt(role, school_label, report_text);

  const claudeRes = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": process.env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: "claude-opus-4-7",
      max_tokens: 1024,
      stream: true,
      system: [
        { type: "text", text: system, cache_control: { type: "ephemeral" } },
      ],
      messages,
    }),
  });

  return new Response(claudeRes.body, {
    headers: { ...cors, "content-type": "text/event-stream" },
  });
}
```

- `ANTHROPIC_API_KEY` se setea como Environment Variable en el dashboard de Vercel (Production + Preview).
- CORS limitado a `eligiendomicamino.org`.
- Prompt caching activado en el system prompt (el texto del reporte cambia por usuario, pero dentro de una conversación se reutiliza — ahorra ~80% de input tokens del 2do mensaje en adelante).
- No persistimos mensajes (privacidad por defecto).
- Rate limit suave por IP — Vercel Edge no trae uno built-in, así que usamos Upstash Redis (free tier) o un contador en memoria con KV. Para v1: contador en memoria por instancia, suficiente para el volumen esperado.
- Despliegue: `vercel --prod` desde el folder `emc-reporte-api/`. Vercel asigna una URL `*.vercel.app` automáticamente; opcionalmente apuntar un subdominio.

### Data layer — script de extracción
Un script Python único (`scripts/extract_reports.py`) que:
1. Itera por los PDFs del zip `PARA_IMPRIMIR_30mar-15may2026.zip`.
2. Para cada PDF: extrae texto con `pdfplumber` o `pypdf`, normaliza espacios.
3. Parsea el filename para obtener `{role, ugel, codigo, seccion}`.
4. Extrae el nombre del saludo ("Hola, X") con regex.
5. Escribe `reportes-data/{role}/{codigo}_{seccion}.json` con:
   ```json
   {
     "codigo_modular": "870949",
     "school_name": "7082 JUAN DE ESPINOSA MEDRANO",
     "ugel": "UGEL_01_SJ_MIRAFLORES",
     "seccion": null,
     "role": "director",
     "greeting_name": "Veronica",
     "report_text": "Hola, Veronica.\nEste es el primer reporte..."
   }
   ```
6. Construye `reportes-data/index.json` con la lista de todas las escuelas, agrupadas por UGEL, con los reportes disponibles para cada una.

El script corre una vez por ciclo (cada quincena). En el futuro puede convertirse en un step del pipeline que genera los PDFs.

## Voz del gallito (system prompt)

```
Eres el gallito de Eligiendo Mi Camino, un programa del Banco Mundial con uDocz
que acompaña a estudiantes de 5to de secundaria en Lima a explorar su futuro.

Estás conversando con {role_label} de la escuela {school_label}.

Tu trabajo es ayudar a {role_label} a entender su reporte y a decidir qué hacer.
Tu tono es de coach cálido peruano: respetuoso, claro, breve, accionable.
- Usa "tú" con docentes y tutores, "usted" con directores.
- Nunca inventes números — todo lo que digas sobre la escuela debe venir del
  reporte que sigue. Si te preguntan algo que no está en el reporte, di
  "esto no aparece en tu reporte" y sugiere conversar con su acompañante.
- Sé concreto: si te piden ideas para la próxima clase / sesión, da 2-3 sugerencias
  específicas basadas en los datos del reporte (qué tema, qué estudiantes, qué pregunta).
- Sobre temas generales del programa (cómo funciona Ponte a Prueba, qué es RIASEC,
  qué pasos tiene el viaje vocacional), puedes responder. Sobre temas no relacionados
  al programa, redirige amablemente.
- No menciones que eres una IA. Eres "el gallito".

REPORTE DE {role_label} · {school_label}
======================================
{report_text}
```

Reemplazos:
- `{role_label}`: "la directora" / "el director" / "el docente de matemática" / "la tutora" — usar el género que coincida con el `greeting_name` cuando sea inequívoco; si no, usar "la directora / el director" en plural neutro o evitar.
- `{school_label}`: "7082 Juan de Espinosa Medrano (UGEL 01)" o similar.

## Branding visual

Paleta heredada de `index.html`:
- `--primary: #f39300` (naranja Eligiendo Mi Camino).
- `--primary-dark: #f75a00`.
- `--bg-cream: #fffbf0`.
- `--text-dark: #242c32`.
- `--math-color: #C62828` para acentos de matemática.
- `--ov-color: #2E7D32` para acentos de tutoría.

Tipografía:
- Headlines y "Hola, [nombre]" en serif elegante (la del PDF, idealmente "Cormorant Garamond" desde Google Fonts — o el match más cercano).
- Cuerpo y UI en `Montserrat`, igual que el resto del sitio.
- Cursiva selectiva en frases clave, como en el PDF ("tu sección", "puede hacer", "explora").

Elementos:
- [gallito-pip.png](../../img/gallito-pip.png) presente en cada pantalla. Grande en bienvenida (~200px), mediano en chat header (~48px).
- Fondo crema en todas las pantallas. Sombras suaves (`0 2px 12px rgba(0,0,0,0.08)`).
- Burbujas de chat: usuario en naranja con texto crema, gallito en crema con borde sutil y nombre "Gallito" arriba.
- Animación de "el gallito está escribiendo..." con tres puntitos.

## Privacidad

- **PII en los reportes**: los reportes de tutoría incluyen nombres completos de estudiantes y sus rutas elegidas; los reportes de director incluyen números de WhatsApp de docentes; todos los reportes saludan a la persona destinataria por su nombre.
- **Gate suave**: el usuario debe escribir su primer nombre exactamente como aparece en la página 1. Bloquea snooping casual sin requerir login.
- **No persistencia**: el Worker no guarda mensajes ni reportes. Cada sesión es efímera.
- **CORS**: el Worker sólo acepta requests desde `eligiendomicamino.org`.
- **Rate limit**: 30 mensajes / 10 min por IP, para limitar el costo si alguien intenta abusar.
- **No logging de contenido**: el Worker no loguea el texto de los mensajes ni del reporte, sólo metadatos (timestamp, IP, role, código modular) para debugging.

## Costo estimado

Por usuario, conversación típica de 8 mensajes:
- Input cacheado (system + report ~3k tokens): ~$0.003 (1er mensaje) + ~$0.0003 × 7 (cache hit) ≈ **$0.005**.
- Output (~300 tokens/respuesta × 8): 2400 tokens × $0.075/1k ≈ **$0.18**.
- **Total: ~$0.19 por conversación.**

Si 100 escuelas hacen 1 conversación por ciclo: ~$19. Si la mitad de 85 directores + 200 docentes cada uno: ~$50 por ciclo. Despreciable.

Vercel: gratis (Hobby tier = 100GB bandwidth, 100k function invocations/mes).

## Roadmap futuro (no v1)

- **Voz**: integrar Speech-to-Text para que directores con poco tiempo puedan hablarle al gallito.
- **WhatsApp**: misma IA pero accesible vía WhatsApp Business API — los directores ya están en WhatsApp con su acompañante.
- **Comparaciones cruzadas**: "compárame con otra escuela parecida en mi UGEL" — requiere agregar acceso a múltiples reportes (con anonimización).
- **Histórico**: cuando lleguemos al 2do/3er reporte del ciclo, mostrar evolución entre quincenas.
- **Recordatorios proactivos**: el gallito te avisa cuando llega un nuevo reporte ("ya está tu reporte de la quincena 16-31 may, ¿quieres revisarlo conmigo?").

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| API key filtrada | Vercel env var (server-side), CORS estricto, rate limit. |
| Alucinación de cifras | System prompt explícito + el reporte completo en contexto. Test manual con ~5 reportes diversos antes del lanzamiento. |
| Directores leen datos de otra escuela | Gate de primer nombre + URL solo compartida por WhatsApp del acompañante. |
| Abuso (costos) | Rate limit por IP + presupuesto mensual con alerta en Anthropic console. |
| Reporte no extraído correctamente | Script de extracción genera un report de validación; revisión manual de muestra de 10 PDFs por cada tipo. |
| Tono inadecuado al rol | System prompt diferenciado por rol + revisión manual de ejemplos con un director real y un tutor real antes del lanzamiento amplio. |

## Plan de implementación (alto nivel)

1. Script de extracción Python — 436 PDFs → 436 JSON + index.json.
2. Vercel Edge Function — proxy con streaming, prompt caching, CORS, rate limit suave.
3. Frontend `reporte/index.html` — 4 pantallas, vanilla JS, mismo CSS que el resto.
4. Test manual con 3 reportes (1 director, 1 mate, 1 tutor) y 5 preguntas cada uno.
5. Deploy: push a `master` (página) + `vercel --prod` desde `emc-reporte-api/` (función).
6. Compartir URL personalizada por WhatsApp a un grupo piloto (5 escuelas).
7. Iteración basada en feedback.

El plan detallado paso-a-paso lo escribiré en una segunda pasada con la skill `writing-plans`.
