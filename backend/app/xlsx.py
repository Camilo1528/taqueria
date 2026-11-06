"""Generador mínimo de archivos Excel (.xlsx) sin dependencias externas.

Un .xlsx es un ZIP con XML adentro; aquí solo se arma lo necesario: varias hojas,
encabezados en negrita, números con separador de miles y anchos de columna.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape

# Estilos: 0 = normal, 1 = encabezado en negrita con fondo, 2 = número con miles, 3 = título grande
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0"/></numFmts>
<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="14"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE5E7EB"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>
</styleSheet>"""

_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, value, style: int) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        value = "Sí" if value else "No"
    if isinstance(value, (int, float)):
        st = style if style else 2
        return f'<c r="{ref}" s="{st}"><v>{value}</v></c>'
    text = escape(_BAD_XML.sub("", str(value)))
    return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{text}</t></is></c>'


class Sheet:
    def __init__(self, name: str):
        self.name = re.sub(r"[\[\]:*?/\\]", "", name)[:31]
        self.rows: list[tuple[list, int]] = []

    def title(self, text: str):
        self.rows.append(([text], 3))

    def header(self, *cols):
        self.rows.append((list(cols), 1))

    def row(self, *vals):
        self.rows.append((list(vals), 0))

    def blank(self):
        self.rows.append(([], 0))

    def _xml(self) -> str:
        widths: dict[int, int] = {}
        body = []
        for r, (vals, style) in enumerate(self.rows, start=1):
            cells = []
            for c, v in enumerate(vals):
                cells.append(_cell(f"{_col(c)}{r}", v, style))
                if style != 3 and v is not None:
                    shown = f"{v:,.0f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
                    widths[c] = max(widths.get(c, 8), min(len(shown) + 2, 60))
            body.append(f'<row r="{r}">{"".join(cells)}</row>')
        cols = "".join(f'<col min="{c + 1}" max="{c + 1}" width="{w}" customWidth="1"/>' for c, w in sorted(widths.items()))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                + (f"<cols>{cols}</cols>" if cols else "")
                + f'<sheetData>{"".join(body)}</sheetData></worksheet>')


class Workbook:
    def __init__(self):
        self.sheets: list[Sheet] = []

    def add(self, name: str) -> Sheet:
        s = Sheet(name)
        self.sheets.append(s)
        return s

    def to_bytes(self) -> bytes:
        n = len(self.sheets)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                       '<Default Extension="xml" ContentType="application/xml"/>'
                       '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                       '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                       + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                                 for i in range(1, n + 1))
                       + "</Types>")
            z.writestr("_rels/.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                       "</Relationships>")
            z.writestr("xl/workbook.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                       + "".join(f'<sheet name="{escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>' for i, s in enumerate(self.sheets, 1))
                       + "</sheets></workbook>")
            z.writestr("xl/_rels/workbook.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                                 for i in range(1, n + 1))
                       + f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                       "</Relationships>")
            z.writestr("xl/styles.xml", _STYLES)
            for i, s in enumerate(self.sheets, 1):
                z.writestr(f"xl/worksheets/sheet{i}.xml", s._xml())
        return buf.getvalue()
