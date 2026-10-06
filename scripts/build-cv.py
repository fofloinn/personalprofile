"""Build the public CV PDF from the reviewed portfolio content (no private details)."""
import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docker" / "portfolio-content.php"
OUTPUT = ROOT / "theme" / "assets" / "Fearghal-O-Floinn-CV.pdf"
NAME = "Fearghal Ó Floinn"
TITLE = "Senior Site Reliability Engineer"
LINKEDIN = "https://www.linkedin.com/in/fearghal-o-floinn-7b237939"
GITHUB = "https://github.com/fofloinn"

INK = HexColor("#1f2933")
ACCENT = HexColor("#1d4e89")


class Extract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.current = None
        self.markup = ""
        self.list = None

    def handle_starttag(self, tag, attrs):
        if tag in ("h2", "h3", "h4", "p", "li"):
            self.current = tag
            self.markup = ""
        elif tag == "ul":
            self.list = []
        elif tag == "strong" and self.current:
            self.markup += "<b>"
        elif tag == "br" and self.current:
            self.markup += "<br/>"
        elif tag == "a" and self.current:
            self.markup += "<u>"

    def handle_endtag(self, tag):
        if tag == "strong" and self.current:
            self.markup += "</b>"
        elif tag == "a" and self.current:
            self.markup += "</u>"
        elif tag in ("h2", "h3", "h4", "p") and self.current == tag:
            self.blocks.append((tag, self.markup))
            self.current = None
        elif tag == "li" and self.current == "li":
            self.list.append(self.markup)
            self.current = None
        elif tag == "ul":
            self.blocks.append(("ul", self.list))
            self.list = None

    def handle_data(self, data):
        if self.current:
            self.markup += html.escape(data, quote=False)

    def handle_entityref(self, name):
        if self.current:
            self.markup += html.escape(html.unescape(f"&{name};"), quote=False)


def main():
    php = SOURCE.read_text(encoding="utf-8")
    body = re.search(r"<<<'HTML'\n(.*?)\nHTML;", php, re.S).group(1)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    parser = Extract()
    parser.feed(body)

    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK)
    styles = {
        "name": ParagraphStyle("name", parent=base, fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=ACCENT),
        "title": ParagraphStyle("title", parent=base, fontSize=12, leading=16),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=ACCENT, spaceBefore=10, spaceAfter=2),
        "h4": ParagraphStyle("h4", parent=base, fontName="Helvetica-Oblique", fontSize=10, leading=13, textColor=ACCENT, spaceBefore=6),
        "h3": ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=6),
        "p": ParagraphStyle("p", parent=base, spaceAfter=3),
        "li": ParagraphStyle("li", parent=base),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"{NAME} - Curriculum Vitae", author=NAME,
    )
    story = [Paragraph(NAME, styles["name"]), Paragraph(TITLE, styles["title"]),
             Paragraph(f'<u>{LINKEDIN}</u> &nbsp;|&nbsp; <u>{GITHUB}</u>', styles["p"]), HRFlowable(width="100%", color=ACCENT, thickness=1), Spacer(1, 4)]

    skip_intro = True
    for kind, value in parser.blocks:
        if skip_intro and kind == "p":
            continue  # tagline duplicates the site hero
        if kind == "h2":
            skip_intro = False
            if value in ("Connect",):
                break
            story.append(Paragraph(value, styles["h2"]))
        elif kind in ("h3", "h4", "p"):
            story.append(Paragraph(value, styles[kind]))
        elif kind == "ul":
            items = [ListItem(Paragraph(item, styles["li"]), leftIndent=12) for item in value]
            story.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=12, bulletFontSize=8))
    doc.build(story)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    sys.exit(main())
