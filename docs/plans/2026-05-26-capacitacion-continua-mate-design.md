# Capacitación Continua — Matemáticas (Tutor de IA)

**Estado:** Diseño aprobado · 2026-05-26
**Reemplaza:** `certificacion/perfeccionamiento_mate.html` (preview placeholder)
**URL final:** `https://eligiendomicamino.org/certificacion/perfeccionamiento_mate.html`
**Horas:** ~8 h pedagógicas asincrónicas (componente Productos y autoestudio, 30% nota)

## Contexto

El cert site marca el curso de perfeccionamiento docente como "En preparación final" desde el módulo 5 (Productos a entregar). El `perfeccionamiento_mate.html` actual sirve como vista previa con 6 módulos placeholder (5 momentos, dashboard, intervención, integración curricular, casos, quiz). Este documento describe el contenido que reemplaza el preview por el curso real.

El objetivo de este curso es que el docente de Matemáticas pase de:
- *"Recibo un reporte cada 2 semanas pero no termino de entenderlo"*
- *"No sé cuándo intervenir vs cuándo dejar que la IA haga"*

a:
- *"Leo el reporte en 5 minutos y sé qué clase corta dar el lunes"*
- *"Conozco los 5 errores conceptuales típicos y cuándo aparecen en el dashboard"*

## Arquitectura

**Single-page application HTML** con sidebar de navegación, mismo template que `perfeccionamiento_mate.html` actual (Montserrat, paleta naranja `#F39300`, callouts de colores). Cada módulo es un object en el array `modules` con `{id, title, eyebrow, duration, content, quiz}`.

`localStorage` guarda progreso por docente (módulos completados, respuestas a quizzes).

**Sin backend propio** — feedback y reflexión final via Google Form embebido (mismo patrón que Anexo 2), respuestas caen a Sheet centralizado.

## Estructura de 8 módulos

1. **Bienvenida + Video del programa** (~15 min) — embed iframe Drive (file ID `1vi49W906B84E-hFt9FwJmBpPtstK0WeX`) + por qué este curso
2. **Repaso: los 5 momentos** (~45 min) — recap del placeholder actual
3. **Qué funcionó y qué no — campo abierto** (~30 min) — observaciones EMC + Form de feedback
4. **Tu reporte quincenal — página por página** (~2 h) — walk-through de las 8 pp del reporte de aula
5. **El reporte del director** (~1 h) — walk-through de las 5 pp del reporte del director
6. **Errores conceptuales típicos + intervención** (~1.5 h) — 5 errores frecuentes con guion de clase corta
7. **Casos reales anonimizados** (~1 h) — 6 mini-casos con diagnóstico y acción
8. **Quiz final + reflexión + certificado** (~30 min) — 10 preguntas + reflexión via Form + cert descargable

## Reporte ficticio (módulos 4 y 5)

**Requisito crítico:** debe ser **visualmente idéntico** al reporte real (mismo tipo, layout, colores, tipografía Caslon/Inter del PDF). No basta con texto descriptivo.

Implementación: HTML estilizado con CSS que replica el PDF, incrustado dentro del módulo. Datos sintéticos diseñados para enseñar cada punto pedagógico (no reproducción 1:1 de un reporte real). Nombres ficticios consistentes a través del curso (IE Ficticia 9999, Sección A, docente "Demo").

## Plantilla por bloque (módulos 4 y 5)

Cada página del reporte se cubre con un bloque pedagógico:

```
📄 PÁGINA X · [TÍTULO]
[Captura HTML del reporte demo]
🔎 ¿Qué muestra?       — explicación literal
🧭 ¿Cómo se lee?       — interpretación pedagógica
🎯 ¿Qué hago con esto? — acciones concretas
⚠️ Lo que NO significa — malinterpretaciones a evitar
└─ mini-check: "¿qué harías si...?"
```

## Stack técnico

- Mismo template HTML que `perfeccionamiento_mate.html` actual
- `localStorage` para progreso del docente
- Google Form propio (nuevo via Apps Script) para feedback módulo 3 y reflexión final módulo 8
- Iframe Google Drive para video (file ID arriba)
- Tono: tuteo neutro peruano (sin voseo argentino)
- 0 dependencias JS externas más allá de Font Awesome y Montserrat (Google Fonts) que ya están

## Fasing (entrega incremental)

| Fase | Contenido | Commit objetivo |
|---|---|---|
| **A** | Shell + módulos 1-3 (welcome+video, 5 momentos, feedback+Form) | Live antes de Fase B |
| **B** | Módulo 4 (reporte de aula docente, 8 sub-bloques) + reporte demo | Live antes de Fase C |
| **C** | Módulo 5 (reporte director) + Módulo 6 (5 errores + guiones) | Live antes de Fase D |
| **D** | Módulo 7 (casos) + Módulo 8 (quiz final + certificado) | Live antes de Fase E |
| **E** | Extras (glosario, calendario, auto-eval, botón llamada) | Curso completo |

Cada fase queda live en `eligiendomicamino.org` antes de empezar la siguiente para feedback temprano.

## Decisiones tomadas (preguntas y respuestas)

| Pregunta | Decisión |
|---|---|
| Relación con perfeccionamiento_mate.html existente | Reemplaza el preview por el curso real |
| Storage del feedback | Google Form propio (patrón Anexo 2) |
| Hosting del video | Google Drive (link compartido por usuario) |
| Anonimización del reporte | Reporte ficticio con datos sintéticos plausibles |
| Identidad visual del reporte demo | Idéntico al formato real del PDF |

## Verificación

Curso aprobado para producción cuando:

1. Las 5 fases están deployadas en `eligiendomicamino.org/certificacion/perfeccionamiento_mate.html`
2. El Form de feedback recibe respuestas en su Sheet vinculado (test end-to-end)
3. El video carga desde Drive iframe en el módulo 1
4. localStorage persiste progreso entre sesiones
5. El quiz final emite certificado HTML descargable al aprobar (≥6/10)
6. Cero formas de voseo argentino en el contenido nuevo
7. Tabla del módulo 5 (productos) sigue linkeando a `perfeccionamiento_mate.html` con el texto "Ver el curso →" (actualizar de "Ver vista previa del curso")
