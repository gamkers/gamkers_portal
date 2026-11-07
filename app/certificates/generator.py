from datetime import datetime, timezone
from pathlib import Path
import secrets

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.certificates.logo_shape import LOGO_POLYGONS


PAGE_WIDTH = 842
PAGE_HEIGHT = 536
# GAMKERS theme: dark background, brand green accents, light text.
BACKGROUND = HexColor("#070907")
GLOW = HexColor("#0E2E18")
GREEN = HexColor("#22C55E")
GREEN_SOFT = HexColor("#4ADE80")
TEXT = HexColor("#FFFFFF")
MUTED = HexColor("#9AA79D")
LINE = HexColor("#1E3A27")

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONTS = {"regular": "Helvetica", "semibold": "Helvetica-Bold", "bold": "Helvetica-Bold"}


def _register_fonts():
    """Use the bundled Inter TTFs (subset-embedded); fall back to Helvetica."""
    if FONTS["regular"] == "Inter-Regular":
        return
    try:
        for key, name in (
            ("regular", "Inter-Regular"),
            ("semibold", "Inter-SemiBold"),
            ("bold", "Inter-ExtraBold"),
        ):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / f"{name}.ttf")))
            FONTS[key] = name
    except Exception:
        FONTS.update(regular="Helvetica", semibold="Helvetica-Bold", bold="Helvetica-Bold")


def render_description(description, name, college_name, certificate_number, date):
    replacements = {
        "{name}": name,
        "{college_name}": college_name,
        "{certificate_number}": certificate_number,
        "{date}": date,
    }
    for variable, value in replacements.items():
        description = description.replace(variable, value)
    return description


def generate_certificate_number(certificate_id):
    year = datetime.now(timezone.utc).year
    return f"CERT-{year}-{certificate_id:06d}"


def generate_public_token():
    return secrets.token_urlsafe(32)


def fit_font_size(text, font_name, max_size, max_width, min_size=14):
    size = max_size
    while size > min_size and stringWidth(text, font_name, size) > max_width:
        size -= 1
    return size


def wrap_text(text, font_name, font_size, max_width):
    lines = []
    for paragraph in text.splitlines() or [""]:
        current_line = ""
        for word in paragraph.split():
            if stringWidth(word, font_name, font_size) > max_width:
                if current_line:
                    lines.append(current_line)
                    current_line = ""
                chunk = ""
                for character in word:
                    if chunk and stringWidth(
                        chunk + character, font_name, font_size
                    ) > max_width:
                        lines.append(chunk)
                        chunk = character
                    else:
                        chunk += character
                current_line = chunk
                continue
            test_line = f"{current_line} {word}".strip()
            if stringWidth(test_line, font_name, font_size) <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
    return lines


def draw_logo(pdf, x, y, size, color, alpha=1.0):
    """Draw the GAMKERS logo as vector paths (keeps the PDF free of raster images)."""
    pdf.saveState()
    pdf.setFillColor(color)
    pdf.setFillAlpha(alpha)
    for polygon in LOGO_POLYGONS:
        path = pdf.beginPath()
        first_x, first_y = polygon[0]
        path.moveTo(x + first_x * size, y + first_y * size)
        for point_x, point_y in polygon[1:]:
            path.lineTo(x + point_x * size, y + point_y * size)
        path.close()
        pdf.drawPath(path, fill=1, stroke=0)
    pdf.restoreState()


def draw_spaced(pdf, text, x, y, font, size, spacing, align="left"):
    """Draw letter-spaced text; x is the left edge, centre or right edge per align."""
    width = stringWidth(text, font, size) + spacing * max(len(text) - 1, 0)
    if align == "center":
        x -= width / 2
    elif align == "right":
        x -= width
    # save/restore so the character spacing does not leak into later text
    pdf.saveState()
    text_object = pdf.beginText()
    text_object.setTextOrigin(x, y)
    text_object.setFont(font, size)
    text_object.setCharSpace(spacing)
    text_object.textOut(text)
    pdf.drawText(text_object)
    pdf.restoreState()
    return width


def _corner_brackets(pdf, inset, length):
    left, right = inset, PAGE_WIDTH - inset
    bottom, top = inset, PAGE_HEIGHT - inset
    pdf.setStrokeColor(GREEN)
    pdf.setLineWidth(1.6)
    for corner_x, corner_y, dx, dy in (
        (left, top, 1, -1),
        (right, top, -1, -1),
        (left, bottom, 1, 1),
        (right, bottom, -1, 1),
    ):
        pdf.line(corner_x, corner_y, corner_x + dx * length, corner_y)
        pdf.line(corner_x, corner_y, corner_x, corner_y + dy * length)


def generate_pdf(
    title,
    description,
    name,
    college_name,
    certificate_number,
    output_path,
    issue_date=None,
    verify_url=None,
):
    _register_fonts()
    regular, semibold, bold = FONTS["regular"], FONTS["semibold"], FONTS["bold"]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output_path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    pdf.setTitle(f"{title} — {name}")
    pdf.setAuthor("GAMKERS")
    pdf.setSubject(f"Certificate {certificate_number}")
    center_x = PAGE_WIDTH / 2
    content_width = PAGE_WIDTH - 240
    issue_date = issue_date or datetime.now(timezone.utc).strftime("%d %B %Y")

    # Background: dark page, soft green glow from the top, faint logo watermark.
    pdf.setFillColor(BACKGROUND)
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
    pdf.saveState()
    clip = pdf.beginPath()
    clip.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT)
    pdf.clipPath(clip, stroke=0, fill=0)
    pdf.radialGradient(center_x, PAGE_HEIGHT + 60, 560, (GLOW, BACKGROUND), extend=True)
    pdf.restoreState()
    draw_logo(pdf, PAGE_WIDTH - 330, 60, 360, GREEN, alpha=0.05)

    # Frame: thin outer rule plus green corner brackets.
    pdf.setStrokeColor(LINE)
    pdf.setLineWidth(0.8)
    pdf.rect(16, 16, PAGE_WIDTH - 32, PAGE_HEIGHT - 32, fill=0, stroke=1)
    _corner_brackets(pdf, 24, 34)

    # Header: logo + wordmark (left), certificate number (right).
    draw_logo(pdf, 58, 444, 44, GREEN)
    pdf.setFillColor(TEXT)
    draw_spaced(pdf, "GAMKERS", 114, 471, bold, 18, 2.4)
    pdf.setFillColor(GREEN)
    draw_spaced(pdf, "CYBERSECURITY & TECHNOLOGY COMMUNITY", 115, 455, semibold, 6.5, 1.3)
    pdf.setFillColor(MUTED)
    draw_spaced(pdf, "CERTIFICATE NO.", PAGE_WIDTH - 58, 471, semibold, 6.5, 1.3, align="right")
    pdf.setFillColor(TEXT)
    draw_spaced(pdf, certificate_number, PAGE_WIDTH - 58, 455, semibold, 10, 0.6, align="right")

    # Eyebrow with rules either side.
    pdf.setFillColor(GREEN)
    eyebrow_width = draw_spaced(pdf, "CERTIFICATE", center_x, 394, semibold, 9, 3.2, align="center")
    pdf.setStrokeColor(GREEN)
    pdf.setLineWidth(1)
    pdf.line(center_x - eyebrow_width / 2 - 44, 397, center_x - eyebrow_width / 2 - 14, 397)
    pdf.line(center_x + eyebrow_width / 2 + 14, 397, center_x + eyebrow_width / 2 + 44, 397)

    title_size = fit_font_size(title, bold, 26, content_width, min_size=12)
    pdf.setFillColor(TEXT)
    pdf.setFont(bold, title_size)
    pdf.drawCentredString(center_x, 360, title)

    pdf.setFillColor(MUTED)
    draw_spaced(pdf, "THIS CERTIFICATE IS PROUDLY PRESENTED TO", center_x, 324, semibold, 8, 1.8, align="center")

    name_size = fit_font_size(name, bold, 40, content_width, min_size=16)
    pdf.setFillColor(TEXT)
    pdf.setFont(bold, name_size)
    pdf.drawCentredString(center_x, 280, name)
    name_width = min(stringWidth(name, bold, name_size) + 50, content_width)
    pdf.setStrokeColor(GREEN)
    pdf.setLineWidth(2)
    pdf.line(center_x - name_width / 2, 266, center_x + name_width / 2, 266)

    college_size = fit_font_size(college_name, semibold, 11, content_width, min_size=8)
    pdf.setFillColor(GREEN_SOFT)
    pdf.setFont(semibold, college_size)
    pdf.drawCentredString(center_x, 244, college_name)

    rendered_description = render_description(
        description, name, college_name, certificate_number, issue_date
    )
    description_size = 10
    lines = wrap_text(rendered_description, regular, description_size, content_width)
    pdf.setFillColor(MUTED)
    pdf.setFont(regular, description_size)
    description_y = 216
    for line in lines[:3]:
        pdf.drawCentredString(center_x, description_y, line)
        description_y -= 15

    # Footer: date issued | issued by GAMKERS | verification.
    pdf.setStrokeColor(LINE)
    pdf.setLineWidth(0.8)
    pdf.line(58, 112, PAGE_WIDTH - 58, 112)

    pdf.setFillColor(MUTED)
    draw_spaced(pdf, "DATE ISSUED", 62, 86, semibold, 6.5, 1.3)
    pdf.setFillColor(TEXT)
    pdf.setFont(semibold, 10.5)
    pdf.drawString(62, 69, issue_date)

    pdf.setFillColor(MUTED)
    draw_spaced(pdf, "ISSUED BY", center_x, 86, semibold, 6.5, 1.3, align="center")
    draw_logo(pdf, center_x - 50, 64, 16, GREEN)
    pdf.setFillColor(TEXT)
    draw_spaced(pdf, "GAMKERS", center_x - 28, 68, bold, 12, 1.6)
    pdf.setFillColor(MUTED)
    pdf.setFont(regular, 7)
    pdf.drawCentredString(center_x, 52, "Learn. Build. Share. Grow.")

    pdf.setFillColor(MUTED)
    draw_spaced(pdf, "VERIFY THIS CERTIFICATE", PAGE_WIDTH - 62, 86, semibold, 6.5, 1.3, align="right")
    verify_text = (verify_url or "").split("://", 1)[-1] or certificate_number
    verify_size = fit_font_size(verify_text, semibold, 8.5, 230, min_size=6)
    pdf.setFillColor(GREEN_SOFT)
    pdf.setFont(semibold, verify_size)
    pdf.drawRightString(PAGE_WIDTH - 62, 69, verify_text)
    if verify_url:
        pdf.linkURL(verify_url, (PAGE_WIDTH - 62 - 230, 62, PAGE_WIDTH - 62, 80), relative=0)
    pdf.save()
