# Reporte Chat con Gallito — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `eligiendomicamino.org/reporte/` — a chat page where directors/teachers/tutors can ask Claude Opus 4.7 about their EMC quincenal report, with gallito branding and a soft-check privacy gate.

**Architecture:** Static HTML on GitHub Pages (existing `capacitacion-docentes` repo), Vercel Edge Function as proxy for the Anthropic API call (hides the key), pre-extracted JSON per school+role+section so the AI has full report context with prompt caching.

**Tech Stack:** Python 3.12 + `pypdf` for extraction · Vercel Edge Function (JS) for the proxy · Vanilla JS + CSS on the frontend (matches the rest of the site) · Anthropic API `claude-opus-4-7` with prompt caching + streaming.

**Source design doc:** [2026-05-26-reporte-chat-gallito-design.md](2026-05-26-reporte-chat-gallito-design.md)

---

## Sequencing & checkpoints

The 5 tasks below are roughly independent and can be done in this order:

1. **Task 1 — Extraction script** (~25 min, no external accounts needed)
2. **Task 2 — Vercel proxy** (~30 min, needs user's Vercel account + Anthropic API key)
3. **Task 3 — Frontend, screens 1–3** (rol + escuela picker)
4. **Task 4 — Frontend, screens 3.5 + 4** (soft check + chat)
5. **Task 5 — QA + deploy**

Between tasks I'll show output and ask for go-ahead. Tasks 1 and 3 can run in parallel if you want speed.

> **USER ACTIONS needed during this plan:**
> - Provide an Anthropic API key (or confirm I can use one of your existing keys).
> - Sign in to Vercel (free, ~2 min) and run `vercel link` for the new project.
> - Approve a `git push` to the master branch (this is what triggers Pages deploy).

---

## Task 1 — PDF extraction script

**Files:**
- Create: `scripts/extract_reports.py`
- Create: `reportes-data/index.json`
- Create: `reportes-data/director/*.json`, `reportes-data/matematica/*.json`, `reportes-data/tutoria/*.json` (one per report).

**Step 1: Set up the script skeleton**

Create [scripts/extract_reports.py](../../scripts/extract_reports.py) that:
- Takes a path to the zip file as arg 1.
- Unzips into a temp dir.
- Walks all `.pdf` files.

**Step 2: Parse filename → metadata**

Add a function `parse_filename(path) → {role, ugel, codigo, seccion, school_name}`. Three filename formats:
- Director: `Director_30mar-15may2026/UGEL_01_SJ_MIRAFLORES/Reporte_Director_12_7082_JUAN_DE_ESPINOSA_MEDRANO.pdf` → `{role:"director", codigo:"7082", school_name:"JUAN DE ESPINOSA MEDRANO", seccion:null}`
- Matemática: `Matematica_30mar-15may2026/UGEL_01_SJ_MIRAFLORES/7231_SecA.pdf` → `{role:"matematica", codigo:"7231", seccion:"A", school_name:null}` (school name resolved later from director report).
- Tutoría: `Tutoria_30mar-15may2026/UGEL_01_SJ_MIRAFLORES/Reporte_Tutoria_v2_ie7_7061LOSHEROESDESANJUAN_SecA.pdf` → `{role:"tutoria", codigo:"7061", school_name:"LOSHEROESDESANJUAN", seccion:"A"}`.

**Step 3: Test the parser with 3 fixture filenames**

```python
def test_parse_filename():
    assert parse_filename("Director_30mar-15may2026/UGEL_01_SJ_MIRAFLORES/Reporte_Director_12_7082_JUAN_DE_ESPINOSA_MEDRANO.pdf") == {
        "role": "director", "ugel": "UGEL_01_SJ_MIRAFLORES",
        "codigo": "7082", "school_name": "JUAN DE ESPINOSA MEDRANO", "seccion": None
    }
    # ... same for matematica and tutoria
```

Run with `python scripts/extract_reports.py --self-test` — expect 3 assertions to pass.

**Step 4: Extract text from one PDF**

Use `pypdf.PdfReader(path).pages[i].extract_text()` joined by `\n\n`. Normalize whitespace (collapse `\s+` to single space within lines, keep newlines). Verify on the Juan de Espinosa Medrano sample we already extracted — text should contain "Veronica Mestas Masias" and "98% de sus estudiantes".

**Step 5: Extract greeting_name**

Regex on the first ~500 chars: `r"Hola,\s+([A-ZÁÉÍÓÚÑa-záéíóúñ]+)\."` → first capture group is the greeting_name. Strip and store.

**Step 6: Loop over all PDFs, write JSON per report**

Output structure for `reportes-data/director/7082.json`:
```json
{
  "codigo_modular": "7082",
  "school_name": "7082 JUAN DE ESPINOSA MEDRANO",
  "ugel": "UGEL_01_SJ_MIRAFLORES",
  "ugel_label": "UGEL 01 · San Juan de Miraflores",
  "seccion": null,
  "role": "director",
  "role_label": "Director(a)",
  "greeting_name": "Veronica",
  "report_text": "Hola, Veronica.\nEste es el primer reporte..."
}
```

Filename pattern:
- Director: `reportes-data/director/{codigo}.json`
- Matemática: `reportes-data/matematica/{codigo}_{seccion}.json`
- Tutoría: `reportes-data/tutoria/{codigo}_{seccion}.json`

**Step 7: Build `reportes-data/index.json`**

```json
{
  "generated_at": "2026-05-26T15:00:00",
  "period_label": "30 marzo — 15 mayo 2026",
  "ugels": [
    {
      "id": "UGEL_01_SJ_MIRAFLORES",
      "label": "UGEL 01 · San Juan de Miraflores",
      "schools": [
        {
          "codigo": "7082",
          "name": "7082 JUAN DE ESPINOSA MEDRANO",
          "roles_available": {
            "director": true,
            "matematica": ["A", "B"],
            "tutoria": ["A", "B"]
          }
        }
      ]
    }
  ]
}
```

**Step 8: Run the script and validate output**

```bash
python scripts/extract_reports.py "C:/Users/cosmo/Downloads/PARA_IMPRIMIR_30mar-15may2026.zip"
```

Validate:
- ~436 JSON files generated.
- `index.json` has 7 UGELs, ~85 schools.
- Spot-check 3 random JSONs: greeting_name correct, school_name correct, report_text length ~3-5 KB.
- Print a summary table: PDFs found / PDFs extracted / PDFs failed.

**Step 9: Show output to user, get sign-off before committing**

Show the user:
- The generated `reportes-data/index.json` (first 1 KB).
- 1 sample director JSON, 1 sample matemática, 1 sample tutoría.
- Any failed extractions and why.

User approves → commit. User flags issues → fix and re-run.

---

## Task 2 — Vercel proxy

**Files:**
- Create: `C:\Users\cosmo\Downloads\emc-reporte-api\api\chat.js`
- Create: `C:\Users\cosmo\Downloads\emc-reporte-api\package.json`
- Create: `C:\Users\cosmo\Downloads\emc-reporte-api\vercel.json`
- Create: `C:\Users\cosmo\Downloads\emc-reporte-api\.gitignore`

(The proxy lives in a **separate folder/repo** because the main site is on GitHub Pages, which can't run functions.)

**Step 1: USER — gather credentials**

- Anthropic API key: confirm you have one available (any of your existing keys works).
- Vercel account: if you don't have one, sign up free at vercel.com (sign in with GitHub).

Tell Claude when these are ready.

**Step 2: Scaffold the Vercel project**

Create `emc-reporte-api/` with these files (from the design doc — code is in [2026-05-26-reporte-chat-gallito-design.md](2026-05-26-reporte-chat-gallito-design.md) under "Backend — Vercel Serverless Function").

`package.json`:
```json
{
  "name": "emc-reporte-api",
  "version": "1.0.0",
  "private": true
}
```

`vercel.json`:
```json
{ "functions": { "api/chat.js": { "runtime": "edge" } } }
```

`.gitignore`: `node_modules/`, `.vercel/`, `.env`.

`api/chat.js`: per the design doc (CORS-locked, streaming, prompt caching, calls `claude-opus-4-7`).

**Step 3: Add the system prompt builder**

In `api/chat.js`, add:
```javascript
function buildSystemPrompt(role, school_label, report_text) {
  const roleLabel = {
    director: "el director/la directora",
    matematica: "el/la docente de matemática",
    tutoria: "el/la tutor(a) de aula",
  }[role];
  return `Eres el gallito de Eligiendo Mi Camino, un programa del Banco Mundial...
[full prompt from design doc]
REPORTE DE ${roleLabel} · ${school_label}
======================================
${report_text}`;
}
```

Full text in the design doc.

**Step 4: Test locally with `vercel dev`**

```bash
cd C:/Users/cosmo/Downloads/emc-reporte-api
npx vercel dev
```

In another terminal, curl test:
```bash
curl -X POST http://localhost:3000/api/chat \
  -H "Content-Type: application/json" \
  -H "Origin: https://eligiendomicamino.org" \
  -d '{"messages":[{"role":"user","content":"Hola"}],"role":"director","report_text":"prueba","school_label":"Test"}'
```

Expected: SSE stream from Claude. If 401 → API key not loaded; check `.env.local`.

**Step 5: Deploy to Vercel**

```bash
npx vercel --prod
```

Note the deploy URL (e.g. `emc-reporte-api-xyz.vercel.app`).

In the Vercel dashboard:
- Settings → Environment Variables → add `ANTHROPIC_API_KEY` (Production scope).
- Re-deploy: `npx vercel --prod`.

**Step 6: Smoke-test the deployed endpoint**

Same curl as step 4 but against `https://emc-reporte-api-xyz.vercel.app/api/chat`. Expected: streaming response from Claude. Save the URL — it goes into the frontend in Task 3.

**Step 7: Commit (user approval first)**

```bash
cd C:/Users/cosmo/Downloads/emc-reporte-api
git init && git add . && git status   # show before committing
# user approves
git commit -m "feat: vercel edge proxy for emc reporte chat"
```

---

## Task 3 — Frontend, screens 1–3

**Files:**
- Create: `capacitacion-docentes/reporte/index.html` (the whole page).
- Reuse: `capacitacion-docentes/img/gallito-pip.png`.

**Step 1: Scaffold the HTML**

Single self-contained file. `<head>` with same fonts as `capacitacion-docentes/index.html` (Montserrat from Google Fonts). Add Cormorant Garamond for the literary serif headlines (matches the PDF aesthetic).

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Pregúntale al gallito — Eligiendo Mi Camino</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,600&family=Montserrat:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --primary: #f39300;
      --primary-dark: #f75a00;
      --bg-cream: #fffbf0;
      --text-dark: #242c32;
      --math-color: #C62828;
      --ov-color: #2E7D32;
      /* ...rest from design doc */
    }
    /* base + view-switching CSS */
  </style>
</head>
<body>
  <div id="view-welcome" class="view active">...</div>
  <div id="view-role" class="view">...</div>
  <div id="view-school" class="view">...</div>
  <div id="view-namegate" class="view">...</div>
  <div id="view-chat" class="view">...</div>
  <script>...</script>
</body>
</html>
```

**Step 2: Pantalla 1 — bienvenida**

Centered card: gallito (~200px) + serif heading "Hola, soy el gallito" + Montserrat subtitle "Te ayudo a entender tu reporte y a decidir qué hacer." + big orange "Empezar" button.

**Step 3: Pantalla 2 — ¿Quién eres?**

Three cards in a row (stack on mobile):
- Director(a) — icon: clipboard.
- Docente de Matemática — icon: calculator (or red accent).
- Tutor(a) de aula — icon: compass (or green accent).

Click → stores `state.role` and shows view-school.

**Step 4: Pantalla 3 — ¿Tu escuela?**

On mount of view-school: `fetch('../reportes-data/index.json')` → fill UGEL dropdown.
On UGEL select: filter `index.json` to that UGEL's schools → fill school dropdown.
If role ≠ director: show section dropdown filtered to sections where `roles_available[role]` contains the section.
"Continuar" button: validates all selections, advances to view-namegate.

**Step 5: Test screens 1–3 in browser**

Open the page locally (e.g. `python -m http.server 8000` from `capacitacion-docentes/`). Navigate `/reporte/`. Manual test:
- Click Empezar → screen 2.
- Click each role → screen 3 (URL state unchanged).
- Select UGEL 01 → schools dropdown shows ~12 schools.
- Select 7082 → if role=mate, section dropdown shows A,B; if role=director, no section dropdown.
- Click Continuar → advances.
- Back button works at each step.

**Step 6: Show user, get sign-off before committing.**

Use `preview_*` tools or share a screenshot. User approves visual → commit.

---

## Task 4 — Frontend, screens 3.5 + 4 (the meat)

**Files:**
- Modify: `capacitacion-docentes/reporte/index.html` (append views + script).

**Step 1: Pantalla 3.5 — soft check**

After Continuar in view-school: fetch the chosen report JSON:
```javascript
const path = role === 'director'
  ? `../reportes-data/director/${codigo}.json`
  : `../reportes-data/${role}/${codigo}_${seccion}.json`;
const report = await fetch(path).then(r => r.json());
state.report = report;
```

Show view-namegate: title "Para abrir tu reporte" + input "Tu primer nombre (como aparece en la primera página del PDF)" + button "Abrir reporte".

On submit:
```javascript
const typed = input.value.trim().toLowerCase();
const expected = report.greeting_name.trim().toLowerCase();
if (typed === expected) showView('chat');
else showError("No reconozco ese nombre. Revisa la primera página del PDF.");
```

**Step 2: Pantalla 4 — chat UI**

Top bar:
- Gallito (~48px) on the left.
- Chip: `{role_label} · {school_name}` (e.g., "Director · 7082 Juan de Espinosa Medrano").
- Right: "Cambiar reporte" button.

Body:
- 3 suggested-question cards in a row at the top (role-specific from design doc).
- Below: message list. User messages right-aligned, orange bubble, cream text. Gallito messages left-aligned, cream bubble, dark text, with small "Gallito" label above.
- Bottom: textarea + "Enviar" button (or Enter).

**Step 3: Wire chat to Vercel proxy**

`sendMessage(text)`:
1. Push `{role:'user', content:text}` to `state.messages`; render the bubble.
2. Show "el gallito está escribiendo..." indicator.
3. `POST {VERCEL_URL}/api/chat` with `{messages: state.messages, role, report_text, school_label}`.
4. Read SSE stream chunks (Anthropic format: `event: content_block_delta\ndata: {...}\n\n`), append text to a growing assistant bubble.
5. When `event: message_stop` received: finalize the bubble, push to `state.messages`.

Const at the top of the script:
```javascript
const API_URL = "https://emc-reporte-api-xyz.vercel.app/api/chat"; // from Task 2
```

**Step 4: Footer actions**

Three small buttons below the input:
- **Ver PDF original** — opens the PDF in a new tab. We need the URL. Decision: host PDFs in the same repo (`reportes-pdf/` folder, gitignored if too large, or kept). Alternative: link to a Google Drive folder. Decide with user.
- **WhatsApp a mi acompañante** — `wa.me/<number>` where the number comes from `report.report_text` (extracted with a regex on `+51 \d{3} \d{3} \d{3}` near the acompañante role label). If not extractable, hide the button.
- **Cambiar reporte** — `state = {}; showView('role')`.

**Step 5: Test screens 3.5 + 4 with one real report**

Manual test:
- Pick UGEL 01 → Juan de Espinosa Medrano → director.
- Type "veronica" → gate passes.
- Type "juan" → gate shows error.
- Pass gate, ask "¿qué destaca de mi escuela?" → see streaming response from gallito mentioning the school's stats.
- Ask "¿cuánto subió mi matemática esta semana?" → see grounded answer with real numbers from the report.
- Ask "¿cuántos años tiene el presidente del Perú?" → see polite redirect.

**Step 6: Show, get sign-off, commit.**

---

## Task 5 — QA + deploy

**Step 1: Manual QA matrix**

Test 3 reports end-to-end (in `state.report` and chat):
- Director (Juan de Espinosa Medrano · UGEL 01) — 5 questions.
- Matemática (sección A de una escuela) — 5 questions.
- Tutoría (sección A de una escuela diferente) — 5 questions, including ones about the RIASEC perfiles and Paso 4 vs Paso 8 routes.

Note any hallucinations, tone slips, or UX bugs. Fix.

**Step 2: Mobile test**

Open on phone (or Chrome DevTools mobile emulator, 375×667). Verify:
- All 5 screens are usable.
- Chat input is reachable above keyboard.
- Gallito + chip don't overflow on the chat header.

**Step 3: Cross-browser smoke**

Chrome + Safari + Firefox: load `/reporte/`, do one chat. Stream works in all three.

**Step 4: Deploy frontend**

```bash
# from capacitacion-docentes/
git status   # show before push
# user approves
git push origin master
```

Wait ~30-60s. Verify https://eligiendomicamino.org/reporte/ loads and works end-to-end.

**Step 5: Deploy backend** (already done in Task 2, just re-verify)

Hit the production endpoint once more from the deployed frontend.

**Step 6: Pilot rollout**

USER ACTION: send a WhatsApp message with the URL to 3-5 trusted directors. Collect feedback over 48h. Iterate.

---

## Open questions to resolve during execution

1. **PDF hosting for "Ver PDF original" link** — keep PDFs in the repo (~520 MB, too big for GitHub Pages free tier), or use a Google Drive folder, or generate per-report signed URLs from somewhere else? **Default: omit "Ver PDF" in v1, add it in v1.1.**
2. **Vercel subdomain** — use the `*.vercel.app` URL, or set up `api.eligiendomicamino.org` to CNAME-point to Vercel? **Default: `*.vercel.app` for v1, custom subdomain later if it matters.**
3. **Rate limit** — Vercel Edge doesn't have built-in rate limiting. **Default: skip for v1 (audience is tiny and trusted), add Upstash Redis-based limit if abuse appears.**

---

## Definition of done

- `eligiendomicamino.org/reporte/` loads on mobile + desktop.
- I can complete the 4-screen flow as a director and ask 5 questions, getting grounded streaming answers in the gallito voice.
- API key is not visible in the page source.
- Source design doc and this plan are committed to `capacitacion-docentes/docs/plans/`.
