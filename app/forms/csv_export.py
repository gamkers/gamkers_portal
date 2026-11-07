"""CSV export helpers that neutralise spreadsheet formula injection (CWE-1236)."""

import csv
import io
import re

# Must stay a tuple: `"" in "=+-@"` is True for a str, which would flag empty cells.
FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
IS_SAFE_NUMERIC = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def sanitize_csv_value(value):
    """Return ``value`` as text that spreadsheet apps will not evaluate as a formula.

    ``None`` becomes ``""``. Lists (checkbox answers) are joined with ``", "`` and
    the joined text is sanitised once, because only a cell's leading character
    decides whether it is a formula.

    Pure signed integer or decimal numbers (e.g. -5, +42, -3.14, +0.5) are exempt
    from single-quote escaping because they cannot trigger formula or DDE execution.
    If the value starts with control chars (TAB or CR) or contains formula expressions
    (e.g. -2+3), it is prefixed with ``'``.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = ", ".join("" if item is None else str(item) for item in value)
    text = str(value)
    if not text:
        return ""
    if text[0] in ("\t", "\r"):
        return "'" + text
    stripped = text.strip()
    if stripped and IS_SAFE_NUMERIC.match(stripped):
        return text
    if text[0] in FORMULA_TRIGGERS or text.lstrip()[:1] in FORMULA_TRIGGERS:
        return "'" + text
    return text


def iter_csv_rows(rows):
    """Yield a UTF-8 BOM, then one CSV-encoded line per row with every cell sanitised."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    yield "\ufeff"
    for row in rows:
        writer.writerow([sanitize_csv_value(cell) for cell in row])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


def export_filename(form_id, title):
    """Return an ASCII-only attachment filename such as ``responses_7_CTF_2026.csv``."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", title or "").strip("_")[:30]
    return f"responses_{form_id}_{slug or 'form'}.csv"
