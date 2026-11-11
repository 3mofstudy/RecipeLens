"""將本機食譜 Markdown 及其圖片轉為可上傳的 PDF、DOCX。"""
import hashlib
from io import BytesIO
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote
from xml.sax.saxutils import escape

from markdown_it import MarkdownIt
from filelock import FileLock

from .local_storage import read_json, write_json


def validate_filename(name):
    name = name.strip()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    if (not name or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith(".")
            or name.split(".", 1)[0].upper() in reserved):
        raise ValueError("檔名不可空白，亦不可包含 Windows 禁用字元或保留名稱。")
    return name

def recipe_blocks(markdown):
    markdown = Path(markdown).resolve()
    tokens = MarkdownIt("commonmark").parse(markdown.read_text(encoding="utf-8"))
    blocks = []
    heading = 0
    list_item = False
    for token in tokens:
        if token.type == "heading_open":
            heading = int(token.tag[1:])
        elif token.type == "heading_close":
            heading = 0
        elif token.type == "list_item_open":
            list_item = True
        elif token.type == "list_item_close":
            list_item = False
        elif token.type in {"code_block", "fence"}:
            for line in token.content.splitlines():
                blocks.append(("text", line, 0))
        elif token.type == "inline":
            text = ""
            for child in token.children or []:
                if child.type == "image":
                    if text.strip():
                        blocks.append(("text", text, heading))
                        text = ""
                    image = (markdown.parent / unquote(child.attrGet("src"))).resolve()
                    if not image.is_relative_to(markdown.parent) or not image.is_file():
                        raise ValueError(f"找不到食譜內的本機圖片：{child.attrGet('src')}")
                    blocks.append(("image", image, 0))
                elif child.type in {"text", "code_inline"}:
                    text += child.content
                elif child.type in {"softbreak", "hardbreak"}:
                    text += "\n"
            if text.strip():
                prefix = "• " if list_item else ""
                blocks.append(("text", prefix + text, heading))
    return blocks


def create_docx(blocks, target):
    from docx import Document
    from docx.image.exceptions import UnrecognizedImageError
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
    from PIL import Image

    document = Document()
    for section in document.sections:
        section.top_margin = section.bottom_margin = Cm(2)
        section.left_margin = section.right_margin = Cm(2.2)
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
        style = document.styles[name]
        style.font.name = "Microsoft JhengHei"
        style.font.color.rgb = RGBColor(0, 0, 0)
        fonts = style.element.get_or_add_rPr().find(qn("w:rFonts"))
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            style.element.get_or_add_rPr().append(fonts)
        fonts.set(qn("w:eastAsia"), "Microsoft JhengHei")
    document.styles["Normal"].font.size = Pt(11)
    document.styles["Normal"].paragraph_format.space_after = Pt(6)
    for index, (kind, value, level) in enumerate(blocks):
        if kind == "image":
            with Image.open(value) as image:
                width, height = image.size
            scale = min(15 / width, 17 / height)
            try:
                document.add_picture(str(value), width=Cm(width * scale), height=Cm(height * scale))
            except UnrecognizedImageError:
                # FFmpeg JPEG 可能沒有 JFIF/Exif 標記；轉為記憶體 PNG 供 Word 嵌入。
                with Image.open(value) as image:
                    compatible = BytesIO()
                    image.convert("RGB").save(compatible, format="PNG")
                compatible.seek(0)
                document.add_picture(compatible, width=Cm(width * scale), height=Cm(height * scale))
        elif level:
            document.add_paragraph(value, style="Title" if level == 1 else f"Heading {min(level - 1, 3)}")
        else:
            paragraph = document.add_paragraph(value)
            if index + 1 < len(blocks) and blocks[index + 1][0] == "image":
                paragraph.paragraph_format.keep_with_next = True
    document.save(target)


def create_pdf(blocks, target):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

    # 嵌入中文字型，讓匯出檔能在其他裝置閱讀。
    import os
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msjh.ttc"
    if not font.is_file():
        raise ValueError("PDF 需要微軟正黑體，請確認 Windows 的 msjh.ttc 字型已安裝。")
    pdfmetrics.registerFont(TTFont("RecipeLensChinese", str(font), subfontIndex=0))
    body = ParagraphStyle("RecipeBody", fontName="RecipeLensChinese", fontSize=11,
                          leading=17, wordWrap="CJK", alignment=TA_LEFT, spaceAfter=7)
    heading = ParagraphStyle("RecipeHeading", parent=body, fontSize=15, leading=22,
                             textColor=colors.black, spaceBefore=10, keepWithNext=True)
    title = ParagraphStyle("RecipeTitle", parent=heading, fontSize=21, leading=28)
    caption = ParagraphStyle("RecipeCaption", parent=body, keepWithNext=True)
    story = []
    for index, (kind, value, level) in enumerate(blocks):
        if kind == "image":
            image = Image(str(value))
            scale = min(15 / (image.imageWidth / cm), 17 / (image.imageHeight / cm))
            image.drawWidth = image.imageWidth * scale
            image.drawHeight = image.imageHeight * scale
            story.extend([image, Spacer(1, 0.3 * cm)])
        else:
            style = title if level == 1 else heading if level else body
            if not level and index + 1 < len(blocks) and blocks[index + 1][0] == "image":
                style = caption
            story.append(Paragraph(escape(value).replace("\n", "<br/>"), style))
    document = SimpleDocTemplate(str(target), pagesize=A4, leftMargin=2.2 * cm,
                                 rightMargin=2.2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    document.build(story)


def export_documents(markdown, formats=("pdf",), *, output_dir=None):
    """轉檔結果留在 Markdown 旁邊，重試時重用未變動的檔案。"""
    markdown = Path(markdown).resolve()
    output = Path(output_dir).resolve() if output_dir is not None else markdown.parent / f"{markdown.stem}_cloud"
    output.mkdir(exist_ok=True)
    with FileLock(str(output / "exports.lock"), timeout=10):
        return _export_documents(markdown, formats, output)


def _export_documents(markdown, formats, output):
    formats = tuple(formats)
    if not formats or any(value not in {"md", "pdf", "docx"} for value in formats):
        raise ValueError("請至少選擇 MD、PDF、DOCX 其中一種格式。")
    blocks = recipe_blocks(markdown) if any(value != "md" for value in formats) else []
    fingerprint = hashlib.sha256(markdown.read_bytes())
    fingerprint.update(b"RecipeLens-document-layout-v2")
    for kind, value, _ in blocks:
        if kind == "image":
            fingerprint.update(value.read_bytes())
    source_hash = fingerprint.hexdigest()
    manifest_file = output / "exports.json"
    manifest = read_json(manifest_file)
    result = []
    for format_name in dict.fromkeys(formats):
        target = output / f"{markdown.stem}.{format_name}"
        if target == markdown:
            result.append(markdown)
            continue
        cached = manifest.get(format_name, {})
        if (cached.get("source") == source_hash and target.is_file()
                and cached.get("sha256") == hashlib.sha256(target.read_bytes()).hexdigest()):
            result.append(target)
            continue
        with tempfile.TemporaryDirectory(dir=output) as folder:
            staged = Path(folder) / target.name
            if format_name == "md":
                staged.write_bytes(markdown.read_bytes())
            else:
                builder = create_pdf if format_name == "pdf" else create_docx
                builder(blocks, staged)
            staged.replace(target)
        manifest[format_name] = {
            "source": source_hash, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        write_json(manifest_file, manifest)
        result.append(target)
    return result
