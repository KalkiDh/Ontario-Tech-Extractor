#!/usr/bin/env python3
"""
LLM & Vector-DB Optimized PDF → Markdown → Chunks Pipeline
"""

import os
import sys
import re
import json
from pathlib import Path
from typing import Optional, List, Dict
import logging

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ==========================================================
# 1. CLEAN & NORMALIZE MARKDOWN
# ==========================================================

def clean_answer_placeholders(md: str) -> str:
    return re.sub(
        r"(?:\n\s*\.{5,}\s*){1,}",
        "\n\n<!-- ANSWER_SPACE -->\n\n",
        md
    )


def normalize_whitespace(md: str) -> str:
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


# ==========================================================
# 2. STRUCTURE DETECTION
# ==========================================================

QUESTION_RE = re.compile(r"^(\d+)\s*\((.*?)\)", re.MULTILINE)
SUBPART_RE = re.compile(r"\((i+|iv|v|vi+)\)", re.IGNORECASE)
MARK_RE = re.compile(r"\b(\d+)\s*mark", re.IGNORECASE)


def detect_question_context(line: str, state: dict):
    q = re.search(r"^(\d+)\b", line)
    if q:
        state["question"] = q.group(1)

    sp = SUBPART_RE.search(line)
    if sp:
        state["subpart"] = sp.group(1)

    m = MARK_RE.search(line)
    if m:
        state["marks"] = int(m.group(1))


# ==========================================================
# 3. SEMANTIC CHUNKING
# ==========================================================

def chunk_markdown(md: str, source: str) -> List[Dict]:
    chunks = []
    buffer = []
    state = {
        "question": None,
        "subpart": None,
        "marks": None
    }

    def flush():
        if not buffer:
            return
        text = " ".join(buffer).strip()
        if len(text) < 30:
            buffer.clear()
            return

        chunk_id = f"{source}_Q{state.get('question')}_{state.get('subpart')}_{len(chunks)}"

        chunks.append({
            "id": chunk_id,
            "text": text,
            "metadata": {
                "question": state.get("question"),
                "subpart": state.get("subpart"),
                "marks": state.get("marks"),
                "source": source
            }
        })
        buffer.clear()

    for line in md.splitlines():
        if line.startswith("|"):  # table row → atomic chunk
            flush()
            chunks.append({
                "id": f"{source}_table_{len(chunks)}",
                "text": line,
                "metadata": {
                    "type": "table_row",
                    "source": source
                }
            })
            continue

        if line.startswith("##") or re.match(r"^\d+\s*\(", line):
            flush()
            detect_question_context(line, state)

        if "<!-- ANSWER_SPACE -->" in line:
            flush()
            continue

        if line.strip():
            buffer.append(line)

    flush()
    return chunks


# ==========================================================
# 4. PDF → MARKDOWN (Docling)
# ==========================================================

def parse_pdf_to_chunks(
    pdf_path: str,
    output_dir: str = "output",
    images_dir: str = "images"
) -> Optional[str]:

    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling_core.types.doc import PictureItem

    pdf_name = Path(pdf_path).stem
    output_path = Path(output_dir)
    images_path = Path(images_dir)

    output_path.mkdir(exist_ok=True)
    images_path.mkdir(exist_ok=True)

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.do_table_structure = True
    pipeline_options.generate_page_images = False

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend
            )
        }
    )

    logger.info("Converting PDF with Docling...")
    result = converter.convert(pdf_path)

    md = result.document.export_to_markdown()
    md = clean_answer_placeholders(md)
    md = normalize_whitespace(md)

    # extract images
    for idx, item in enumerate(result.document.iterate_items()):
        if isinstance(item, PictureItem) and item.image:
            item.image.save(images_path / f"{pdf_name}_{idx}.png")

    # semantic chunks
    chunks = chunk_markdown(md, pdf_name)

    out_file = output_path / f"{pdf_name}_chunks.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    logger.info(f"✓ Generated {len(chunks)} vector-ready chunks")
    return str(out_file)


# ==========================================================
# CLI
# ==========================================================

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--images-dir", default="images")
    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        logger.error("PDF not found")
        sys.exit(1)

    parse_pdf_to_chunks(args.pdf, args.output_dir, args.images_dir)


if __name__ == "__main__":
    main()
