"""
Converts every uploaded material (image, PDF, or plain text) into plain
text BEFORE it touches any AI model. This is the single entry point:
extract_text_from_upload(raw_bytes, filename).

Pipeline per file type:
- .txt / .md          -> decoded directly, no OCR needed
- .png / .jpg / .jpeg  -> pytesseract OCR via Pillow
- .pdf                 -> pypdf embedded-text extraction first (fast, free,
                          works for "born-digital" PDFs); if that yields
                          suspiciously little text (a scanned/image PDF),
                          falls back to rendering each page with PyMuPDF
                          and running Tesseract OCR on the rendered image.

Requires the `tesseract-ocr` system package (see packages.txt for
Streamlit Community Cloud, or `apt install tesseract-ocr` locally /
`brew install tesseract` on Mac).
"""

from __future__ import annotations
import io
from PIL import Image
import pytesseract
from pytesseract import Output
import fitz  # PyMuPDF
from pypdf import PdfReader

from config import OCR_FALLBACK_CHARS_PER_PAGE_THRESHOLD, OCR_RENDER_DPI


class OCRError(Exception):
    pass


def _open_image(image_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes))
    # Convert to RGB — some scanners produce CMYK/P mode images that
    # pytesseract handles poorly.
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    return img


def extract_text_from_image_bytes(image_bytes: bytes) -> str:
    try:
        img = _open_image(image_bytes)
        return pytesseract.image_to_string(img)
    except Exception as e:
        raise OCRError(f"Image OCR failed: {e}") from e


def extract_text_with_confidence(image_bytes: bytes) -> tuple[str, float]:
    """Returns (text, avg_word_confidence 0-100). The confidence score is
    Tesseract's own per-word estimate and is a solid proxy for whether it
    could actually read the content: low confidence usually means
    handwriting, a skewed/blurry scan, or unusual fonts — exactly the
    cases worth escalating to Gemini Vision instead of trusting locally."""
    try:
        img = _open_image(image_bytes)
        data = pytesseract.image_to_data(img, output_type=Output.DICT)
        confidences = [
            float(c) for c in data.get("conf", [])
            if str(c).strip() not in ("", "-1") and float(c) >= 0
        ]
        text = pytesseract.image_to_string(img)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return text, avg_conf
    except Exception as e:
        raise OCRError(f"Image OCR failed: {e}") from e


def _extract_pdf_embedded_text(pdf_bytes: bytes) -> tuple[str, int]:
    """Returns (text, page_count) using pypdf's fast embedded-text reader."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_count = len(reader.pages)
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return text, page_count


def render_pdf_pages_as_png(pdf_bytes: bytes) -> list[bytes]:
    """Renders every page of a PDF to a PNG image (via PyMuPDF) and
    returns the list of PNG byte strings, one per page. Used both by the
    plain OCR fallback below and by the handwriting-aware routing in
    ai_clients.py, so a scanned PDF only gets rendered once per caller."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=OCR_RENDER_DPI)
            pages.append(pix.tobytes("png"))
    finally:
        doc.close()
    return pages


def get_pdf_embedded_text_quality(pdf_bytes: bytes) -> tuple[str, int, float]:
    """Returns (embedded_text, page_count, avg_chars_per_page). A low
    avg_chars_per_page means the PDF has little/no real text layer —
    i.e. it's scanned/image-only and needs OCR rather than direct
    extraction."""
    try:
        embedded_text, page_count = _extract_pdf_embedded_text(pdf_bytes)
    except Exception:
        embedded_text, page_count = "", 1
    avg_chars_per_page = len(embedded_text.strip()) / max(page_count, 1)
    return embedded_text, page_count, avg_chars_per_page


def _ocr_pdf_pages(pdf_bytes: bytes) -> str:
    """Renders each PDF page to an image with PyMuPDF and OCRs it with
    Tesseract (no Gemini escalation — plain local OCR). Used for
    materials (syllabus/notes/PYQ), where content is virtually always
    printed/typed, so Tesseract alone is reliable and free. For
    handwritten answer submissions, ai_clients.transcribe_pdf_submission
    uses render_pdf_pages_as_png() directly with confidence-based
    Gemini Vision escalation instead of this function."""
    pages = render_pdf_pages_as_png(pdf_bytes)
    chunks = []
    for page_index, png_bytes in enumerate(pages):
        page_text = extract_text_from_image_bytes(png_bytes)
        chunks.append(f"[Page {page_index + 1}]\n{page_text}")
    return "\n\n".join(chunks)


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    embedded_text, _, avg_chars_per_page = get_pdf_embedded_text_quality(pdf_bytes)

    if avg_chars_per_page >= OCR_FALLBACK_CHARS_PER_PAGE_THRESHOLD:
        # This PDF has a real text layer — cheap and fast, use it directly.
        return embedded_text

    # Looks like a scanned/image-only PDF (e.g. photographed lecture
    # slides) — fall back to rendering + OCR, which is slower but works.
    return _ocr_pdf_pages(pdf_bytes)


def extract_text_from_upload(raw_bytes: bytes, filename: str) -> str:
    """Single entry point used by the app. Dispatches by file extension."""
    name = filename.lower()

    if name.endswith((".txt", ".md")):
        return raw_bytes.decode("utf-8", errors="ignore")

    if name.endswith(".pdf"):
        return extract_text_from_pdf_bytes(raw_bytes)

    if name.endswith((".png", ".jpg", ".jpeg")):
        return extract_text_from_image_bytes(raw_bytes)

    raise OCRError(f"Unsupported file type for '{filename}'. Use PDF, PNG, JPG, or TXT.")
