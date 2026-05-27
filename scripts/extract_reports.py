"""
Extract text from EMC quincenal PDFs (Director / Matematica / Tutoria) into JSON
files keyed by school + role + section, plus an index.json grouping schools by
UGEL. Run once per cycle.

Uses `pdftotext` (from poppler / Git-for-Windows) for clean UTF-8 extraction —
the PDFs use custom font subsets without a ToUnicode cmap, so pure Python
libraries (pypdf / pdfplumber / pymupdf) corrupt the Spanish accents.

Usage:
    python scripts/extract_reports.py <path-to-zip-or-dir> [--out reportes-data]

Output:
    reportes-data/
      index.json
      director/{codigo}.json
      matematica/{codigo}_{seccion}.json
      tutoria/{codigo}_{seccion}.json
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

PDFTOTEXT = shutil.which("pdftotext") or r"C:\Program Files\Git\mingw64\bin\pdftotext.exe"

# ---------- PDF download secret -------------------------------------------------

PDF_SECRET_FILE = Path(r"C:\Users\cosmo\Downloads\emc-reporte-api\.pdf-secret")
PDF_DOWNLOADS_DIR = Path(r"C:\Users\cosmo\Downloads\emc-reporte-api\public\r")


def load_or_create_pdf_secret() -> str:
    """Read .pdf-secret if present; otherwise generate one and save it.

    On first run, prints the secret + setup instructions so the user can
    paste it into the Vercel dashboard.
    """
    env_secret = os.environ.get("PDF_URL_SECRET")
    if env_secret:
        return env_secret.strip()
    if PDF_SECRET_FILE.exists():
        return PDF_SECRET_FILE.read_text(encoding="utf-8").strip()
    new_secret = secrets.token_hex(32)
    PDF_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    PDF_SECRET_FILE.write_text(new_secret, encoding="utf-8")
    print()
    print("=" * 70)
    print("PRIMERA VEZ: generé un secreto para los URLs de descarga de PDF.")
    print(f"  Guardado en: {PDF_SECRET_FILE}")
    print()
    print("Para que los PDFs se descarguen desde el sitio, copia este valor")
    print("en Vercel (Settings > Environment Variables > nueva variable):")
    print()
    print(f"  Nombre:  PDF_URL_SECRET")
    print(f"  Valor:   {new_secret}")
    print()
    print("Marca Production + Preview + Development. Luego corre")
    print("'npx vercel --prod' una vez para que el servidor use el secreto.")
    print("=" * 70)
    print()
    return new_secret


def pdf_url_filename(secret: str, role: str, codigo: str, seccion: Optional[str]) -> str:
    """Stable 32-hex-char filename derived from (role, codigo, seccion) + secret."""
    payload = f"{role}|{codigo}|{seccion or ''}"
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:32]


# ---------- filename parsing ----------------------------------------------------

UGEL_LABELS = {
    "UGEL_01_SJ_MIRAFLORES": "UGEL 01 · San Juan de Miraflores",
    "UGEL_02_RIMAC": "UGEL 02 · Rímac",
    "UGEL_03_BRENA": "UGEL 03 · Breña",
    "UGEL_04_COMAS": "UGEL 04 · Comas",
    "UGEL_05_SJ_LURIGANCHO": "UGEL 05 · San Juan de Lurigancho",
    "UGEL_06_ATE": "UGEL 06 · Ate",
    "UGEL_07_SAN_BORJA": "UGEL 07 · San Borja",
}

ROLE_LABELS = {
    "director": "Director(a)",
    "matematica": "Docente de Matemática",
    "tutoria": "Tutor(a) de aula",
}


@dataclass
class ParsedFile:
    role: str
    ugel: Optional[str]
    seccion: Optional[str]
    file_codigo: Optional[str]  # local school code from the filename, when present
    file_name_hint: Optional[str]  # name fragment from the filename, when present
    rank: Optional[str]  # the school's program-wide rank number (consistent across roles)
    src_path: str


def _strip_section_suffix(stem: str) -> tuple[str, Optional[str]]:
    m = re.search(r"_Sec([A-Z])$", stem)
    if m:
        return stem[: m.start()], m.group(1)
    return stem, None


def parse_filename(path: str) -> Optional[ParsedFile]:
    """Determine role + ugel + seccion + local-code/name-hint from a path.

    The PDF body's 'CÓDIGO MODULAR' is the *national* identifier; reports
    actually cross-reference each other via the *local school code* (the
    underscore-prefixed digits in the director filename, e.g. '7082'). We use
    that for matching when present, and fall back to a normalized name when
    not.
    """
    p = Path(path)
    parts = p.parts
    if not parts or not p.name.lower().endswith(".pdf"):
        return None
    ugel = next((part for part in parts if part.startswith("UGEL_")), None)
    stem = p.stem

    if any(part.startswith("Director_") for part in parts):
        # Reporte_Director_<rank>[_<localcode>]_<NAME...>
        m = re.match(r"^Reporte_Director_(\d+)_(.+)$", stem)
        if not m:
            return None
        rank = m.group(1)
        rest = m.group(2)
        head, *tail = rest.split("_", 1)
        if head.isdigit():
            file_codigo = head
            file_name_hint = tail[0] if tail else None
        else:
            file_codigo = None
            file_name_hint = rest
        return ParsedFile("director", ugel, None, file_codigo, file_name_hint, rank, path)

    if any(part.startswith("Tutoria_") for part in parts):
        base, seccion = _strip_section_suffix(stem)
        # Tutoria filenames: Reporte_Tutoria_v<ver>_ie<rank>_<localcode>?<NAME>
        m = re.match(r"^Reporte_Tutoria_v\d+_ie(\d+)_(.*)$", base)
        if m:
            rank = m.group(1)
            rest = m.group(2)
            # rest may be "<digits><NAME>" or just "<NAME>"
            mm = re.match(r"^(\d{3,})(.*)$", rest)
            if mm:
                file_codigo = mm.group(1)
                file_name_hint = mm.group(2) or None
            else:
                file_codigo = None
                file_name_hint = rest or None
        else:
            rank = None
            file_codigo = None
            file_name_hint = base
        return ParsedFile("tutoria", ugel, seccion, file_codigo, file_name_hint, rank, path)

    if any(part.startswith("Matematica_") for part in parts):
        # strip version/CORREGIDO suffix first so Sec marker is at end
        pre = re.sub(r"_v\d+(?:_CORREGIDO)?$", "", stem)
        base, seccion = _strip_section_suffix(pre)
        rank = None
        # 'Reporte_<rank>_' prefix
        m = re.match(r"^Reporte_(\d+)_(.+)$", base)
        if m:
            rank = m.group(1)
            base = m.group(2)
        # strip 'Inactivo_' prefix
        base = re.sub(r"^Inactivo_", "", base)
        # leading 'rank_' (1-2 digit rank, underscore-separated)
        m = re.match(r"^(\d{1,2})_(.+)$", base)
        if m and not rank:
            rank = m.group(1)
            base = m.group(2)
        elif m:
            base = m.group(2)
        # remaining base:
        if base.isdigit():
            file_codigo = base
            file_name_hint = None
        else:
            mm = re.match(r"^(\d{3,})(.+)$", base)
            if mm:
                file_codigo = mm.group(1)
                file_name_hint = mm.group(2)
            else:
                file_codigo = None
                file_name_hint = base
        return ParsedFile("matematica", ugel, seccion, file_codigo, file_name_hint, rank, path)

    return None


# ---------- PDF text extraction -------------------------------------------------

def extract_text(pdf_path: Path) -> str:
    """Run `pdftotext -enc UTF-8 -layout` and return cleaned text."""
    out = subprocess.run(
        [PDFTOTEXT, "-enc", "UTF-8", "-layout", str(pdf_path), "-"],
        capture_output=True,
        text=False,
        check=True,
    )
    raw = out.stdout.decode("utf-8", errors="replace")
    # Some EMC reports render section headings as letter-spaced text, e.g.
    # "C Ó M O   F U N C I O N A". Collapse single-letter sequences back.
    raw = _collapse_letter_spacing(raw)
    # Collapse runs of spaces but keep line structure.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
    # Drop pure-empty leading/trailing lines, but keep paragraph breaks inside.
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _collapse_letter_spacing(text: str) -> str:
    """Convert 'C Ó M O   F U N C I O N A' → 'CÓMO FUNCIONA'.

    Heuristic: when a line has 4+ consecutive single-letter tokens
    separated by single spaces, treat them as letter-spaced headings.
    """
    def fixer(m: re.Match) -> str:
        run = m.group(0)
        # Tokenize on whitespace, collapse single-char tokens (incl. punctuation
        # like ·).  Multi-space gaps become normal word breaks.
        # Approach: replace runs of "<char> " with "<char>" when each char is
        # 1 grapheme.  Multiple spaces (2+) become a regular space.
        # Split into segments separated by 2+ spaces (word boundaries).
        words = re.split(r" {2,}", run)
        out = []
        for w in words:
            # If every token in w is exactly 1 char, collapse.
            toks = w.split(" ")
            if all(len(t) == 1 for t in toks):
                out.append("".join(toks))
            else:
                out.append(w)
        return " ".join(out)

    # Match runs of letter-spaced text (4+ single chars separated by single spaces).
    pattern = re.compile(r"(?:[A-Za-zÁÉÍÓÚÑáéíóúñ¿¡] ){3,}[A-Za-zÁÉÍÓÚÑáéíóúñ¿¡!?\.](?:  +[A-Za-zÁÉÍÓÚÑáéíóúñ¿¡] (?:[A-Za-zÁÉÍÓÚÑáéíóúñ¿¡] )*[A-Za-zÁÉÍÓÚÑáéíóúñ¿¡!?\.])*")
    return pattern.sub(fixer, text)


def extract_greeting_name(text: str) -> Optional[str]:
    head = text[:800]
    m = re.search(r"Hola,\s+([A-Za-zÁÉÍÓÚÑáéíóúñ]+)\.", head)
    return m.group(1).strip() if m else None


def extract_codigo_modular(text: str) -> Optional[str]:
    """Find the código modular from page 1.

    Director reports say 'CÓDIGO MODULAR <digits>'.
    Math/Tutoría reports show '<digits> · Sección X' (or '<digits> <NAME> · Sección X')
    in the page header.
    """
    m = re.search(r"C[ÓO]DIGO\s+MODULAR\s+(\d{3,8})", text)
    if m:
        return m.group(1)
    # Header banner: '<digits>[ NAME] · Sección X' (math/tutoría)
    head = text[:2000]
    m = re.search(r"(\d{3,8})(?:\s+[^\n·]+?)?\s*·\s*Secci[óo]n\s+[A-Z]", head)
    if m:
        return m.group(1)
    return None


def extract_school_name_from_director(text: str) -> Optional[str]:
    """Director report has the school name as a banner line above CÓDIGO MODULAR.
    It's an ALL-CAPS line, may start with digits.
    """
    head = text[:3000]
    # Find the line right before "CÓDIGO MODULAR"
    m = re.search(r"\n([^\n]+)\n[^\n]*C[ÓO]DIGO\s+MODULAR", head)
    if m:
        line = m.group(1).strip()
        # exclude obvious non-name lines
        if line and line not in {"BIENVENIDA"} and not line.startswith("Hola"):
            # accept ALL CAPS or digits-then-CAPS
            if re.match(r"^[\dA-ZÁÉÍÓÚÑ\s\.\-]+$", line) and len(line) > 4:
                return line
    return None


def extract_school_name_from_tutoria(text: str) -> Optional[str]:
    """Tutoría reports have '<codigo> <NAME> · Sección X' near the top."""
    head = text[:3000]
    m = re.search(
        r"((?:\d{3,5}\s+)?[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]+?)\s*·\s*Sección\s+[A-Z]",
        head,
    )
    if m:
        return m.group(1).strip()
    return None


def extract_banner_name(text: str) -> Optional[str]:
    """Extract school name from a math or tutoría banner like
    'REPUBLICA DE BOLIVIA · Sección A' or '1124 JOSE MARTI · Sección A'.
    Returns the name part (with optional leading digits stripped).
    """
    head = text[:2000]
    m = re.search(
        r"((?:\d{3,8}\s+)?[A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9\s\.\-]+?)\s*·\s*Secci[óo]n\s+[A-Z]",
        head,
    )
    if not m:
        return None
    name = m.group(1).strip()
    return name


def normalize_name(s: str) -> str:
    """Normalize a school name for fuzzy matching.

    Strips leading school codes (3+ digits followed by space) and inactive
    markers, removes diacritics, collapses non-alphanumerics.  Preserves
    short leading digits like '20 de abril' so the name stays intact.
    """
    if not s:
        return ""
    s = s.upper()
    s = re.sub(r"^INACTIVO[_\s]+", "", s)
    # strip leading codigo when it's 3+ digits followed by space/underscore + non-digit
    s = re.sub(r"^\d{3,}[\s_]+(?=\D)", "", s)
    s = (s.replace("Á", "A").replace("É", "E").replace("Í", "I")
           .replace("Ó", "O").replace("Ú", "U").replace("Ñ", "N"))
    s = re.sub(r"[^A-Z0-9]+", "", s)
    return s


def _first(pattern: str, text: str, group: int = 1, flags: int = 0) -> Optional[str]:
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else None


def _int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_director_summary(text: str) -> dict:
    """Extract structured KPI data from a director report's text."""
    s: dict = {}
    s["students_total"] = _int(_first(r"ESTUDIANTES\s+(\d+)\s+de\s+5", text))
    sec_str = _first(r"SECCIONES\s+\d+\s*\(([^)]+)\)", text)
    if sec_str:
        # "A y B" / "A, B y C" / "U"
        parts = re.split(r"\s*,\s*|\s*y\s*", sec_str)
        s["sections"] = [p.strip() for p in parts if p.strip()]
    else:
        s["sections"] = []

    # Matemática
    mate: dict = {}
    mate["active_pct_school"] = _int(_first(r"(\d+)%\s+de\s+sus\s+estudiantes\s+participaron\s+en\s+matem[áa]tica", text))
    m = re.search(r"\((\d+)\s+de\s+(\d+)\s+respondieron", text)
    if m:
        mate["active_count"] = int(m.group(1))
        mate["students_provisioned"] = int(m.group(2))
    mate["questions_total"] = _int(_first(r"respondieron\s+(\d+)\s+preguntas", text))
    # comparison row: "Preguntas respondidas por estudiante (promedio) 119.5 86.0 85.3"
    m = re.search(
        r"Preguntas respondidas por estudiante[^\n]*?([\d.]+)\s+([\d.]+)\s+([\d.]+)",
        text,
    )
    if m:
        mate["q_per_student_school"] = float(m.group(1))
        mate["q_per_student_ugel"] = float(m.group(2))
        mate["q_per_student_programa"] = float(m.group(3))
    m = re.search(r"%\s+de\s+precisi[óo]n[^\n]*?(\d+)%\s+(\d+)%\s+(\d+)%", text)
    if m:
        mate["precision_school"] = int(m.group(1))
        mate["precision_ugel"] = int(m.group(2))
        mate["precision_programa"] = int(m.group(3))
    # programa comparison for % active (in § 02 comparison table)
    m = re.search(
        r"%\s+que\s+respondi[óo]\s+al\s+menos\s+una\s+pregunta\s+(\d+)%\s+(\d+)%\s+(\d+)%",
        text,
    )
    if m:
        mate["active_pct_ugel"] = int(m.group(2))
        mate["active_pct_programa"] = int(m.group(3))
    s["matematica"] = mate

    # Tutoría
    tut: dict = {}
    m = re.search(r"([\d.]+)\s*/\s*8\s+pasos\s+completados\s+en\s+promedio", text)
    if m:
        tut["pasos_promedio"] = float(m.group(1))
    tut["completed_8_count"] = _int(_first(r"(\d+)\s+ya\s+completaron\s+los\s+8", text))
    # tutoria comparison rows
    m = re.search(
        r"Pasos completados \(sobre 8[^\n]*?([\d.]+)\s+([\d.]+)\s+([\d.]+)",
        text,
    )
    if m:
        tut["pasos_promedio_school"] = float(m.group(1))
        tut["pasos_promedio_ugel"] = float(m.group(2))
        tut["pasos_promedio_programa"] = float(m.group(3))
    m = re.search(
        r"%\s+de\s+estudiantes\s+que\s+terminaron\s+los\s+8\s+pasos\s+(\d+)%\s+(\d+)%\s+(\d+)%",
        text,
    )
    if m:
        tut["completed_8_pct_school"] = int(m.group(1))
        tut["completed_8_pct_ugel"] = int(m.group(2))
        tut["completed_8_pct_programa"] = int(m.group(3))
    m = re.search(
        r"%\s+que\s+entraron\s+al\s+menos\s+una\s+vez\s+(\d+)%\s+(\d+)%\s+(\d+)%",
        text,
    )
    if m:
        tut["entered_pct_school"] = int(m.group(1))
        tut["entered_pct_ugel"] = int(m.group(2))
        tut["entered_pct_programa"] = int(m.group(3))
    # RIASEC top profiles: in "Perfiles RIASEC dominantes" we see one-letter
    # labels (I S A R E C) followed by names. Extract up to 3.
    riasec_section = re.search(
        r"Perfiles RIASEC dominantes(.{0,800})", text, re.DOTALL,
    )
    if riasec_section:
        rs = riasec_section.group(1)
        # find letter labels like "I S A" or "I R S" - look for single-letter
        # tokens on their own line, then full names
        riasec_full = {
            "I": "Investigador", "S": "Social", "A": "Artístico",
            "R": "Realista", "E": "Emprendedor", "C": "Convencional",
        }
        found = []
        for letter, name in riasec_full.items():
            if re.search(rf"\b{name}\b", rs):
                # also try to extract student count after the name
                m2 = re.search(rf"{name}\s+(?:[^\d\n]*?)?(\d+)\s*\n?\s*estudiantes", rs)
                count = int(m2.group(1)) if m2 else None
                found.append({"letter": letter, "name": name, "count": count})
        # sort by count desc when available
        found.sort(key=lambda x: -(x["count"] or 0))
        tut["riasec_top"] = found[:3]
    s["tutoria"] = tut

    # Weekly actions in § 04
    actions = []
    weekly_section = re.search(
        r"§\s*04[^\n]*\n.*",
        text,
        re.DOTALL,
    )
    if weekly_section:
        ws = weekly_section.group(0)
        for m in re.finditer(r"^\s*(0[1-9])\s+([^\n]+)$", ws, re.MULTILINE):
            title = m.group(2).strip()
            if title and "Cuándo lo voy a hacer" not in title:
                actions.append(title)
    s["weekly_actions"] = actions[:3]

    return s


def parse_matematica_summary(text: str) -> dict:
    """Extract structured KPI data from a matemática section report's text.

    Math reports lead with "ESTA QUINCENA, EN N MINUTOS" + two numbered
    actions. We extract those titles verbatim because the wording varies
    ("Refuerza el tema..." / "Enseña a distinguir..." / etc.) and the
    teacher needs to see the actual recommendation.
    """
    s: dict = {}
    # "ESTA QUINCENA, EN N MINUTOS" — time budget
    m = re.search(r"ESTA QUINCENA,?\s+EN\s+(\d+)\s+MINUTOS", text)
    if m:
        s["time_budget_minutes"] = int(m.group(1))

    # Action 1 + Action 2 — the two numbered priorities in the priority block.
    # Each starts with "1 " or "2 " on a line, then a first sentence.
    actions_section = re.search(
        r"ESTA QUINCENA[^\n]*\n(?:[^\n]*\n){0,3}((?:\s*\d\s+[^\n]+(?:\n[^\n0-9§][^\n]*)*\n*){1,3})",
        text,
    )
    actions = []
    if actions_section:
        block = actions_section.group(1)
        # find lines starting with "1 " or "2 ":
        for m in re.finditer(r"(?:^|\n)\s*([12])\s+([^\n]+(?:\n[^\n0-9§][^\n]*)*)", block):
            raw = re.sub(r"\s+", " ", m.group(2)).strip()
            # take just the first sentence
            first = re.split(r"(?<=[\.\!\?])\s+", raw, maxsplit=1)[0]
            actions.append(first.rstrip("."))
    s["priority_actions"] = actions[:2]

    # First action also drives weak_topic for compatibility
    if actions:
        # try the "Refuerza el tema con menor precisión: X" pattern; else the first action
        m = re.search(
            r"Refuerza\s+el\s+tema\s+con\s+menor\s+precisi[óo]n[:\s]+([^\n\.]+?)\.",
            text,
            re.IGNORECASE,
        )
        s["weak_topic"] = m.group(1).strip() if m else actions[0]

    # Students for follow-up from "Habla con X y con Y"
    m = re.search(r"Habla\s+con\s+([^\.\n]+?)\.\s", text, re.IGNORECASE | re.DOTALL)
    if m:
        names_clause = re.sub(r"\s+", " ", m.group(1)).strip()
        names = re.split(r"\s+y\s+(?:con\s+)?", names_clause)
        s["students_for_followup"] = [n.strip() for n in names if n.strip()]

    # § 01 opening sentence — handle line wraps (use DOTALL on the wrapped section).
    m = re.search(
        r"activos\s+pasaron\s+en\s+promedio\s+(\d+)\s+minutos\s+por\s+semana"
        r".*?UGEL[^\(]*?\((\d+)\s+minutos\)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        s["active_minutes_section"] = int(m.group(1))
        s["active_minutes_ugel"] = int(m.group(2))

    return s


def parse_tutoria_summary(text: str) -> dict:
    """Extract structured KPI data from a tutoría section report's text."""
    s: dict = {}
    # "De un vistazo": "4.1 de 8 pasos", "100% entró al módulo", "5 terminaron los 8", "3 de 7 sesiones de aula"
    m = re.search(r"([\d.]+)\s+de\s+8\s+pasos\s*\(prom", text)
    if m:
        s["pasos_promedio"] = float(m.group(1))
    m = re.search(r"(\d+)%\s+entr[óo]\s+al\s+m[óo]dulo", text)
    if m:
        s["entered_pct"] = int(m.group(1))
    m = re.search(r"(\d+)\s+terminaron\s+los\s+8", text)
    if m:
        s["completed_8_count"] = int(m.group(1))
    m = re.search(r"(\d+)\s+de\s+(\d+)\s+sesiones\s+de\s+aula", text)
    if m:
        s["sesiones_aula"] = int(m.group(1))
        s["sesiones_aula_esperadas"] = int(m.group(2))
    # comparison table values
    m = re.search(
        r"Pasos completados \(prom\.?\s*/?8\)\s+([\d.]+)\s+([\d.]+)",
        text,
    )
    if m:
        s["pasos_promedio_section"] = float(m.group(1))
        s["pasos_promedio_programa"] = float(m.group(2))
    m = re.search(r"Terminaron los 8 pasos\s+(\d+)\s*\((\d+)%\)\s+(\d+)%", text)
    if m:
        s["completed_8_count"] = int(m.group(1))
        s["completed_8_pct"] = int(m.group(2))
        s["completed_8_pct_programa"] = int(m.group(3))
    m = re.search(r"Entraron al m[óo]dulo vocacional\s+\d+\s*\((\d+)%\)\s+(\d+)%", text)
    if m:
        s["entered_pct"] = int(m.group(1))
        s["entered_pct_programa"] = int(m.group(2))
    # RIASEC top profiles
    riasec_section = re.search(
        r"Perfiles RIASEC\s+de\s+tu\s+secci[óo]n(.{0,800})", text, re.DOTALL,
    )
    if riasec_section:
        rs = riasec_section.group(1)
        riasec_full = {
            "I": "Investigador", "S": "Social", "A": "Artístico",
            "R": "Realista", "E": "Emprendedor", "C": "Convencional",
        }
        found = []
        for letter, name in riasec_full.items():
            if re.search(rf"\b{name}\b", rs):
                m2 = re.search(rf"{name}\s+(\d+)\s+estud", rs)
                count = int(m2.group(1)) if m2 else None
                found.append({"letter": letter, "name": name, "count": count})
        found.sort(key=lambda x: -(x["count"] or 0))
        s["riasec_top"] = found[:3]
    # Paso 4 top route
    m = re.search(
        r"Universidad\s+(\d+)\s+\((\d+)%\)",
        text,
    )
    if m:
        s["ruta_p4_universidad_pct"] = int(m.group(2))
    return s


def extract_acompanante_whatsapp(text: str, role: str) -> Optional[str]:
    """Return the most relevant +51 phone for this role.
    - For director: prefer the math acompañante or any acompañante (printed near
      'SUS ACOMPAÑANTES'). We return the first phone after 'ACOMPAÑANTES'.
    - For matematica/tutoria: extract the single 'acompañante' phone — these
      reports print it at the bottom near 'Escribe por WhatsApp a tu
      acompañante'.
    """
    phone_re = re.compile(r"\+51\s*\d{3}\s*\d{3}\s*\d{3}")
    if role == "director":
        # First phone after the "ACOMPAÑANTES" header.
        m = re.search(r"ACOMPA[ÑN]ANTES.*?(\+51\s*\d{3}\s*\d{3}\s*\d{3})", text, re.DOTALL)
        return m.group(1).strip() if m else None
    # mate/tutoría: first +51 phone in the body
    m = phone_re.search(text)
    return m.group(0).strip() if m else None


# ---------- main pipeline -------------------------------------------------------

@dataclass
class SchoolInfo:
    codigo: str
    name: Optional[str] = None
    ugel: Optional[str] = None
    director_available: bool = False
    matematica_secciones: list[str] = field(default_factory=list)
    tutoria_secciones: list[str] = field(default_factory=list)


def collect_pdfs(input_path: Path) -> tuple[Path, list[tuple[str, Path]]]:
    if input_path.is_dir():
        return input_path, [(f.relative_to(input_path).as_posix(), f) for f in input_path.rglob("*.pdf")]
    tempdir = Path(tempfile.mkdtemp(prefix="emc_reports_"))
    with zipfile.ZipFile(input_path, "r") as z:
        z.extractall(tempdir)
    return tempdir, [(f.relative_to(tempdir).as_posix(), f) for f in tempdir.rglob("*.pdf")]


def process(input_path: Path, out_dir: Path, period_label: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("director", "matematica", "tutoria"):
        (out_dir / sub).mkdir(exist_ok=True)
        # clean prior runs so we don't leave stale files behind
        for old in (out_dir / sub).glob("*.json"):
            old.unlink()

    # PDF downloads: load/create the secret, wipe the old folder so we don't
    # ship stale PDFs for schools that left the program this cycle.
    pdf_secret = load_or_create_pdf_secret()
    PDF_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    for old in PDF_DOWNLOADS_DIR.glob("*.pdf"):
        old.unlink()

    root, files = collect_pdfs(input_path)
    print(f"Found {len(files)} PDFs.")

    parsed: list[tuple[ParsedFile, Path]] = []
    skipped: list[tuple[str, str]] = []
    for rel, abs_p in files:
        if "_FALTA_" in rel or "no_enviar" in rel:
            skipped.append((rel, "marked do-not-send"))
            continue
        pf = parse_filename(rel)
        if pf is None:
            skipped.append((rel, "unparseable filename"))
            continue
        parsed.append((pf, abs_p))

    print(f"Parsed {len(parsed)} files; skipped {len(skipped)}.")

    schools: dict[str, SchoolInfo] = {}
    name_to_key: dict[str, str] = {}  # normalized name → school_key
    rank_to_key: dict[str, str] = {}  # rank → school_key
    failed: list[tuple[str, str]] = []
    extracted_count = 0

    def school_key_for_director(pf: ParsedFile) -> str:
        if pf.file_codigo:
            return pf.file_codigo
        # for same-name schools across UGELs, rank disambiguates
        slug = normalize_name(pf.file_name_hint or "")
        if slug and slug in name_to_key:
            # collision: same-name school already registered. Use rank-suffixed key.
            return f"{slug}-{pf.rank or 'X'}"
        return slug or (pf.rank and f"rank-{pf.rank}") or "unknown"

    def school_key_for_section(pf: ParsedFile, banner_name: Optional[str]) -> Optional[str]:
        # Try (in order):
        # 1. file_codigo if it matches an existing school
        # 2. rank → key (most reliable cross-role match)
        # 3. banner name → key
        # 4. file_name_hint name → key
        # 5. file_codigo as a fresh key
        # 6. name slug
        if pf.file_codigo and pf.file_codigo in schools:
            return pf.file_codigo
        if pf.rank and pf.rank in rank_to_key:
            return rank_to_key[pf.rank]
        for n in (banner_name, pf.file_name_hint):
            if n:
                k = normalize_name(n)
                if k and k in name_to_key:
                    return name_to_key[k]
        if pf.file_codigo:
            return pf.file_codigo
        for n in (banner_name, pf.file_name_hint):
            if n:
                k = normalize_name(n)
                if k:
                    return k
        return None

    # Pass 1: directors are authoritative for school identity.
    for pf, abs_p in parsed:
        if pf.role != "director":
            continue
        try:
            text = extract_text(abs_p)
        except Exception as e:
            failed.append((pf.src_path, f"pdftotext failed: {e}"))
            continue

        school_name = extract_school_name_from_director(text)
        # if the body school-name extraction failed, build one from the filename hint
        if not school_name and pf.file_name_hint:
            school_name = pf.file_name_hint.replace("_", " ").strip().upper()
        if not school_name:
            school_name = pf.file_codigo or "ESCUELA"
        # prefix with local code if it isn't already in the name
        if pf.file_codigo and not school_name.startswith(pf.file_codigo):
            school_name = f"{pf.file_codigo} {school_name}"

        key = school_key_for_director(pf)
        greeting = extract_greeting_name(text)
        whatsapp = extract_acompanante_whatsapp(text, "director")
        national_codigo = extract_codigo_modular(text)

        info = schools.setdefault(key, SchoolInfo(codigo=key))
        info.name = school_name
        info.ugel = pf.ugel
        info.director_available = True

        # register name lookups for matching math/tutoría reports
        for n in (school_name, pf.file_name_hint):
            if n:
                ns = normalize_name(n)
                if ns:
                    name_to_key.setdefault(ns, key)
        # register rank for cross-role matching (most reliable disambiguator)
        if pf.rank:
            rank_to_key[pf.rank] = key

        doc = {
            "codigo_modular": pf.file_codigo or key,
            "codigo_modular_nacional": national_codigo,
            "school_name": school_name,
            "ugel": pf.ugel,
            "ugel_label": UGEL_LABELS.get(pf.ugel, pf.ugel),
            "seccion": None,
            "role": "director",
            "role_label": ROLE_LABELS["director"],
            "greeting_name": greeting,
            "acompanante_whatsapp": whatsapp,
            "summary": parse_director_summary(text),
            "report_text": text,
        }
        (out_dir / "director" / f"{key}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Copy the original PDF under an unguessable HMAC-named filename so
        # the gated /api/verify can hand out a stable download URL.
        try:
            pdf_name = pdf_url_filename(pdf_secret, "director", key, None)
            shutil.copyfile(abs_p, PDF_DOWNLOADS_DIR / f"{pdf_name}.pdf")
        except Exception as e:
            failed.append((pf.src_path, f"pdf copy failed: {e}"))
        extracted_count += 1

    # Pass 2: matemática + tutoría — match to school by local codigo / name.
    for pf, abs_p in parsed:
        if pf.role == "director":
            continue
        try:
            text = extract_text(abs_p)
        except Exception as e:
            failed.append((pf.src_path, f"pdftotext failed: {e}"))
            continue

        banner_name = extract_banner_name(text)
        key = school_key_for_section(pf, banner_name)
        if not key:
            failed.append((pf.src_path, f"could not resolve school key (banner='{banner_name}')"))
            continue

        info = schools.setdefault(key, SchoolInfo(codigo=key, ugel=pf.ugel))
        if not info.ugel:
            info.ugel = pf.ugel
        if not info.name:
            info.name = banner_name or pf.file_name_hint or key

        if pf.role == "matematica" and pf.seccion and pf.seccion not in info.matematica_secciones:
            info.matematica_secciones.append(pf.seccion)
        if pf.role == "tutoria" and pf.seccion and pf.seccion not in info.tutoria_secciones:
            info.tutoria_secciones.append(pf.seccion)

        greeting = extract_greeting_name(text)
        whatsapp = extract_acompanante_whatsapp(text, pf.role)

        summary = (
            parse_matematica_summary(text) if pf.role == "matematica"
            else parse_tutoria_summary(text)
        )
        doc = {
            "codigo_modular": key,
            "school_name": info.name,
            "ugel": pf.ugel,
            "ugel_label": UGEL_LABELS.get(pf.ugel, pf.ugel),
            "seccion": pf.seccion,
            "role": pf.role,
            "role_label": ROLE_LABELS[pf.role],
            "greeting_name": greeting,
            "acompanante_whatsapp": whatsapp,
            "summary": summary,
            "report_text": text,
        }
        (out_dir / pf.role / f"{key}_{pf.seccion}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            pdf_name = pdf_url_filename(pdf_secret, pf.role, key, pf.seccion)
            shutil.copyfile(abs_p, PDF_DOWNLOADS_DIR / f"{pdf_name}.pdf")
        except Exception as e:
            failed.append((pf.src_path, f"pdf copy failed: {e}"))
        extracted_count += 1

    # Build index.json
    ugels_map: dict[str, list[dict]] = {}
    for info in sorted(schools.values(), key=lambda s: (s.ugel or "", s.codigo)):
        if not info.ugel:
            continue
        ugels_map.setdefault(info.ugel, []).append({
            "codigo": info.codigo,
            "name": info.name or info.codigo,
            "roles_available": {
                "director": info.director_available,
                "matematica": sorted(info.matematica_secciones),
                "tutoria": sorted(info.tutoria_secciones),
            },
        })

    index = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "period_label": period_label,
        "ugels": [
            {"id": ugel_id, "label": UGEL_LABELS.get(ugel_id, ugel_id), "schools": ugels_map[ugel_id]}
            for ugel_id in sorted(ugels_map.keys())
        ],
    }
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "pdfs_found": len(files),
        "pdfs_parsed": len(parsed),
        "pdfs_extracted": extracted_count,
        "pdfs_skipped": len(skipped),
        "pdfs_failed": len(failed),
        "schools_total": len(schools),
        "ugels_total": len(ugels_map),
        "skipped_examples": skipped[:5],
        "failed_examples": failed[:10],
    }


# ---------- self-test ----------------------------------------------------------

def _self_test() -> int:
    """Assert filename parser handles all the variants we've seen in the wild."""
    cases = [
        # (path, expected role, ugel, seccion, file_codigo, rank, file_name_hint contains?)
        ("Director_30mar-15may2026/UGEL_01_SJ_MIRAFLORES/Reporte_Director_12_7082_JUAN_DE_ESPINOSA_MEDRANO.pdf",
         "director", "UGEL_01_SJ_MIRAFLORES", None, "7082", "12", "JUAN_DE_ESPINOSA_MEDRANO"),
        ("Director_30mar-15may2026/UGEL_01_SJ_MIRAFLORES/Reporte_Director_2_MANUEL_CALVO_Y_PEREZ.pdf",
         "director", "UGEL_01_SJ_MIRAFLORES", None, None, "2", "MANUEL_CALVO_Y_PEREZ"),
        ("Director_30mar-15may2026/UGEL_03_BRENA/Reporte_Director_39_JUAN_PABLO_VIZCARDO_Y_GUZMAN.pdf",
         "director", "UGEL_03_BRENA", None, None, "39", "JUAN_PABLO_VIZCARDO_Y_GUZMAN"),
        ("Tutoria_30mar-15may2026/UGEL_03_BRENA/Reporte_Tutoria_v2_ie48_1021REPUBLICAFEDERALDEALEMANIA_SecA.pdf",
         "tutoria", "UGEL_03_BRENA", "A", "1021", "48", "REPUBLICAFEDERALDEALEMANIA"),
        ("Tutoria_30mar-15may2026/UGEL_03_BRENA/Reporte_Tutoria_v2_ie39_JUANPABLOVIZCARDOYGUZMAN_SecA.pdf",
         "tutoria", "UGEL_03_BRENA", "A", None, "39", "JUANPABLOVIZCARDOYGUZMAN"),
        ("Matematica_30mar-15may2026/UGEL_01_SJ_MIRAFLORES/7231_SecA.pdf",
         "matematica", "UGEL_01_SJ_MIRAFLORES", "A", "7231", None, None),
        ("Matematica_30mar-15may2026/UGEL_03_BRENA/JoseMarti_SecA.pdf",
         "matematica", "UGEL_03_BRENA", "A", None, None, "JoseMarti"),
        ("Matematica_30mar-15may2026/UGEL_03_BRENA/39_JuanPabloVizcardoYGuzman_SecA.pdf",
         "matematica", "UGEL_03_BRENA", "A", None, "39", "JuanPabloVizcardoYGuzman"),
        ("Matematica_30mar-15may2026/UGEL_02_RIMAC/Reporte_30_20DeAbril_SecA_v2_CORREGIDO.pdf",
         "matematica", "UGEL_02_RIMAC", "A", None, "30", "20DeAbril"),
    ]
    failures = 0
    for path, role, ugel, seccion, fc, rank, hint in cases:
        got = parse_filename(path)
        if got is None:
            print(f"FAIL (no parse): {path}")
            failures += 1
            continue
        problems = []
        if got.role != role: problems.append(f"role={got.role!r}!={role!r}")
        if got.ugel != ugel: problems.append(f"ugel={got.ugel!r}!={ugel!r}")
        if got.seccion != seccion: problems.append(f"seccion={got.seccion!r}!={seccion!r}")
        if got.file_codigo != fc: problems.append(f"file_codigo={got.file_codigo!r}!={fc!r}")
        if got.rank != rank: problems.append(f"rank={got.rank!r}!={rank!r}")
        if hint and (not got.file_name_hint or hint not in got.file_name_hint):
            problems.append(f"hint missing {hint!r} in {got.file_name_hint!r}")
        if problems:
            print(f"FAIL: {path}\n  " + "; ".join(problems))
            failures += 1
    if failures:
        print(f"{failures} test(s) failed.")
        return 1
    print(f"All {len(cases)} filename parser tests passed.")
    return 0


# ---------- cli ----------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Extract EMC quincenal PDFs into JSON.")
    parser.add_argument("input", nargs="?", help="Path to zip or folder containing the PDFs")
    parser.add_argument(
        "--out",
        default=r"C:\Users\cosmo\Downloads\emc-reporte-api\data",
        help="Output directory (default: the Vercel project's data folder)",
    )
    parser.add_argument(
        "--period",
        default=None,
        help="Human-readable period label (auto-detected from zip filename if omitted)",
    )
    parser.add_argument("--self-test", action="store_true", help="Run filename-parser self-test only")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.input:
        parser.error("input path is required (unless --self-test)")
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 2

    period = args.period or detect_period_from_filename(input_path.name)
    print(f"Period label: {period}")
    print(f"Output directory: {args.out}")
    summary = process(input_path, Path(args.out), period)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        f"\nOK — extracted {summary['pdfs_extracted']} reports for "
        f"{summary['schools_total']} schools."
    )
    return 0


SPANISH_MONTHS = {
    "ene": "enero", "feb": "febrero", "mar": "marzo", "abr": "abril",
    "may": "mayo", "jun": "junio", "jul": "julio", "ago": "agosto",
    "sep": "septiembre", "set": "septiembre", "oct": "octubre",
    "nov": "noviembre", "dic": "diciembre",
}


def detect_period_from_filename(name: str) -> str:
    """Best-effort: 'PARA_IMPRIMIR_30mar-15may2026.zip' → '30 marzo — 15 mayo 2026'."""
    m = re.search(
        r"(\d{1,2})([a-z]{3})\s*-\s*(\d{1,2})([a-z]{3})(\d{4})",
        name.lower(),
    )
    if not m:
        return f"Período extraído de {name}"
    d1, mo1, d2, mo2, year = m.groups()
    return f"{int(d1)} {SPANISH_MONTHS.get(mo1, mo1)} — {int(d2)} {SPANISH_MONTHS.get(mo2, mo2)} {year}"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
