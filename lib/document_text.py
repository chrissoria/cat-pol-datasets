from __future__ import annotations

import io
import os
import random
import subprocess
import tempfile
import time

import requests


def extract_pdf_text(url: str, session: requests.Session) -> str:
    """Download a PDF, DOCX, or DOC and extract text."""
    if not url:
        return ""

    url_lower = url.lower()
    if not (url_lower.endswith(".pdf") or url_lower.endswith(".docx") or url_lower.endswith(".doc")):
        return ""

    try:
        resp = session.get(url, timeout=60, verify=False)
        resp.raise_for_status()
    except Exception:
        return ""

    if url_lower.endswith(".pdf"):
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                pages = [page.extract_text() for page in pdf.pages if page.extract_text()]
                return "\n\n".join(pages)
        except Exception:
            return ""

    if url_lower.endswith(".docx"):
        try:
            from docx import Document

            doc = Document(io.BytesIO(resp.content))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return ""

    if url_lower.endswith(".doc"):
        try:
            with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name
            try:
                result = subprocess.run(
                    ["textutil", "-convert", "txt", "-stdout", tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    os.unlink(tmp_path)
                    return result.stdout.strip()
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            os.unlink(tmp_path)
        except Exception:
            pass
        return ""

    return ""


def jittered_sleep(base: float) -> None:
    """Sleep for a randomized interval around the given base duration."""
    time.sleep(base * random.uniform(0.5, 1.5))
