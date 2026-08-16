from html import escape
from pathlib import Path
from docx import Document
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, LongTable, TableStyle, KeepTogether

SRC = Path(r"D:\gold-bot\Gold_Trading_Strategy_Video_Guide.docx")
OUT_DIR = Path(r"D:\gold-bot\output\pdf")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT = OUT_DIR / "Gold_Trading_Strategy_Video_Guide.pdf"

font_dir = Path(r"C:\Windows\Fonts")
pdfmetrics.registerFont(TTFont("Arial", str(font_dir / "arial.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Bold", str(font_dir / "arialbd.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Italic", str(font_dir / "ariali.ttf")))

BLUE = colors.HexColor("#2E74B5")
DARK = colors.HexColor("#1F4D78")
LIGHT = colors.HexColor("#E8EEF5")
PALE = colors.HexColor("#F4F6F9")

styles = getSampleStyleSheet()
body = ParagraphStyle("Body", fontName="Arial", fontSize=9.4, leading=12.3, spaceAfter=5, textColor=colors.black)
h1 = ParagraphStyle("H1", fontName="Arial-Bold", fontSize=16, leading=19, textColor=BLUE, spaceBefore=10, spaceAfter=8, keepWithNext=True)
h2 = ParagraphStyle("H2", fontName="Arial-Bold", fontSize=12.2, leading=15, textColor=BLUE, spaceBefore=8, spaceAfter=5, keepWithNext=True)
h3 = ParagraphStyle("H3", fontName="Arial-Bold", fontSize=10.8, leading=13, textColor=DARK, spaceBefore=6, spaceAfter=4, keepWithNext=True)
bullet = ParagraphStyle("Bullet", parent=body, leftIndent=16, firstLineIndent=-9, bulletIndent=4, spaceAfter=3)
small = ParagraphStyle("Small", parent=body, fontSize=8.2, leading=10.2)
cell = ParagraphStyle("Cell", parent=body, fontSize=7.7, leading=9.4, spaceAfter=0)
cell_bold = ParagraphStyle("CellBold", parent=cell, fontName="Arial-Bold", textColor=DARK)
title = ParagraphStyle("Title", fontName="Arial-Bold", fontSize=25, leading=29, alignment=TA_CENTER, textColor=DARK, spaceBefore=35, spaceAfter=8)
subtitle = ParagraphStyle("Subtitle", fontName="Arial", fontSize=14, leading=18, alignment=TA_CENTER, textColor=BLUE, spaceAfter=10)

def safe(text):
    return escape(text or "").replace("\n", "<br/>")

def iter_blocks(parent):
    root = parent.element.body
    for child in root.iterchildren():
        if isinstance(child, CT_P):
            yield DocxParagraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield DocxTable(child, parent)

def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D8E2ED")); canvas.setLineWidth(.5)
    canvas.line(doc.leftMargin, letter[1]-0.62*inch, letter[0]-doc.rightMargin, letter[1]-0.62*inch)
    canvas.setFont("Arial", 7.5); canvas.setFillColor(DARK)
    canvas.drawString(doc.leftMargin, letter[1]-0.52*inch, "GOLD TRADING STRATEGY  |  VIDEO REFERENCE GUIDE")
    canvas.setFillColor(colors.HexColor("#666666")); canvas.drawRightString(letter[0]-doc.rightMargin, 0.48*inch, f"Page {doc.page}")
    canvas.restoreState()

docx = Document(SRC)
story=[]
first_paragraphs=0
list_number=0
for block in iter_blocks(docx):
    if isinstance(block, DocxParagraph):
        text = block.text.strip()
        if not text:
            continue
        style_name = block.style.name if block.style else "Normal"
        if first_paragraphs == 0:
            story.append(Paragraph(safe(text), title)); first_paragraphs += 1; continue
        if first_paragraphs == 1:
            story.append(Paragraph(safe(text), subtitle)); first_paragraphs += 1; continue
        first_paragraphs += 1
        if style_name == "Heading 1": st=h1
        elif style_name == "Heading 2": st=h2
        elif style_name == "Heading 3": st=h3
        elif style_name.startswith("List Bullet"):
            list_number=0
            story.append(Paragraph(safe(text.replace('☐','[ ]')), bullet, bulletText="•")); continue
        elif style_name.startswith("List Number"):
            list_number += 1
            story.append(Paragraph(safe(f"{list_number}. {text}"), bullet)); continue
        else: st=body
        if not style_name.startswith("List Number"):
            list_number=0
        if text == "Quick Strategy Card" or text == "Chapter Guide":
            story.append(PageBreak())
        story.append(Paragraph(safe(text.replace('☐','[ ]')), st))
    else:
        data=[]
        ncols=max(len(r.cells) for r in block.rows)
        for ri,row in enumerate(block.rows):
            vals=[]
            for ci,c in enumerate(row.cells):
                txt=c.text.strip()
                vals.append(Paragraph(safe(txt) if txt else "&nbsp;", cell_bold if ri==0 or (ncols==2 and ci==0) else cell))
            data.append(vals)
        if ncols==1:
            widths=[6.5*inch]
        elif ncols==2:
            widths=[1.78*inch,4.72*inch]
        elif ncols==6:
            widths=[.72*inch,.82*inch,1.08*inch,1.08*inch,1.0*inch,1.8*inch]
        else:
            widths=[6.5*inch/ncols]*ncols
        table=LongTable(data,colWidths=widths,repeatRows=1 if ncols>1 else 0,hAlign='CENTER')
        cmds=[('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#BAC7D5'))]
        if ncols>1: cmds += [('BACKGROUND',(0,0),(-1,0),LIGHT)]
        else: cmds += [('BACKGROUND',(0,0),(-1,-1),PALE),('BOX',(0,0),(-1,-1),.7,colors.HexColor('#B8C9DA'))]
        table.setStyle(TableStyle(cmds)); story += [Spacer(1,3),table,Spacer(1,7)]

pdf=SimpleDocTemplate(str(OUT),pagesize=letter,leftMargin=inch,rightMargin=inch,topMargin=.78*inch,bottomMargin=.72*inch,title="Gold Trading Strategy - Video Guide",author="Prepared for the user")
pdf.build(story,onFirstPage=header_footer,onLaterPages=header_footer)
print(OUT)
