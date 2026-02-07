import sys
import os
import re
import json
import logging
from pathlib import Path
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.datamodel.base_models import InputFormat

# ----------------------------
# Logging Setup
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Extractor")

# ----------------------------
# Regex Patterns
# ----------------------------
# Matches: "1.", "Question 1", "1 (a)", "2(b)(i)"
QUESTION_PATTERN = re.compile(r"^(?:Question\s+)?(\d+)(?:\s*[\.\(]?\s*([a-z]|[iv]+)[\)\.]?)?", re.IGNORECASE)
# Matches marks: "[4]", "[4 marks]", "(4)"
MARKS_PATTERN = re.compile(r"[\[\(](\d+)\s*marks?[\]\)]", re.IGNORECASE)

class SmartChunker:
    """
    A state-machine based chunker that keeps Tables and Code Blocks intact.
    """
    def __init__(self, text, source_name):
        self.lines = text.splitlines()
        self.source = source_name
        self.chunks = []
        
        # Buffers
        self.current_chunk_lines = []
        # "Sticky" metadata that persists until a new question is found
        self.current_metadata = {"question": None, "subpart": None, "marks": None}
        
        # State Flags
        self.in_code_block = False
        self.in_table = False

    def flush(self, chunk_type="text"):
        """Compiles the current buffer into a chunk."""
        if not self.current_chunk_lines:
            return

        text = "\n".join(self.current_chunk_lines).strip()
        
        # Skip empty or noise chunks (e.g. just a pipe | or page numbers)
        if len(text) < 5 or text == "|":
            self.current_chunk_lines = []
            return

        # Unique ID for RAG
        chunk_id = f"{self.source}_{chunk_type}_{len(self.chunks):03d}"
        
        chunk_obj = {
            "id": chunk_id,
            "text": text,
            "metadata": {
                "source": self.source,
                "type": chunk_type,
                # Copy current metadata state
                "question": self.current_metadata["question"],
                "subpart": self.current_metadata["subpart"],
                "marks": self.current_metadata["marks"]
            }
        }
        self.chunks.append(chunk_obj)
        self.current_chunk_lines = []

    def update_metadata(self, line):
        """Updates question/marks context based on the current line."""
        stripped = line.strip()
        
        # --- STRATEGY 1: Standard Heading Detection (e.g. "1. Question") ---
        match = QUESTION_PATTERN.match(stripped)
        
        # --- STRATEGY 2: Table Row Detection (e.g. "| 1 | (a) | ...") ---
        # If the line starts with pipe |, the regex above fails. We must peek inside the cell.
        if not match and stripped.startswith("|"):
            # Split by pipe and get the first non-empty content
            parts = [p.strip() for p in stripped.split("|") if p.strip()]
            if parts:
                # Check if the first cell is a number (Question ID)
                first_cell_match = QUESTION_PATTERN.match(parts[0])
                if first_cell_match:
                    match = first_cell_match
                    # If we found a question number, check second cell for subpart (e.g. "(a)")
                    if len(parts) > 1:
                        sub_match = re.match(r"^\(?([a-z]|[iv]+)\)?", parts[1], re.IGNORECASE)
                        if sub_match:
                            self.current_metadata["subpart"] = sub_match.group(1)

        # --- APPLY UPDATES ---
        if match:
            # If we found a NEW question, save the OLD chunk first
            if not self.in_table and not self.in_code_block:
                self.flush("text")
                
            q_num = match.group(1)
            sub_part = match.group(2)
            
            # Update State
            self.current_metadata["question"] = q_num
            if sub_part:
                self.current_metadata["subpart"] = sub_part
            
            # Reset marks/subpart if it's a new main question number (e.g. going from 1b to 2)
            if not sub_part:
                self.current_metadata["marks"] = None
                self.current_metadata["subpart"] = None 

        # --- STRATEGY 3: Marks Detection ---
        mark_match = MARKS_PATTERN.search(line)
        if mark_match:
            self.current_metadata["marks"] = mark_match.group(1)

    def process(self):
        for line in self.lines:
            stripped = line.strip()

            # --- CASE 1: CODE BLOCKS (```) ---
            if stripped.startswith("```"):
                if self.in_code_block:
                    # Closing fence -> Save Code Block
                    self.current_chunk_lines.append(line)
                    self.flush("code")
                    self.in_code_block = False
                else:
                    # Opening fence -> Save previous text first
                    self.flush("text") 
                    self.in_code_block = True
                    self.current_chunk_lines.append(line)
                continue
            
            if self.in_code_block:
                self.current_chunk_lines.append(line)
                continue

            # --- CASE 2: TABLES ---
            # Line is part of a table if it has pipes AND isn't just a single char
            is_table_row = stripped.startswith("|") and (stripped.endswith("|") or len(stripped.split("|")) > 2)
            
            if is_table_row:
                if not self.in_table:
                    # Start of new table -> Save previous text
                    self.flush("text")
                    self.in_table = True
                
                # Check for metadata INSIDE the table row
                self.update_metadata(line)
                self.current_chunk_lines.append(line)
                continue
            else:
                if self.in_table:
                    # End of table -> Save Table
                    self.flush("table")
                    self.in_table = False

            # --- CASE 3: STANDARD TEXT ---
            self.update_metadata(line)
            self.current_chunk_lines.append(line)

        # Final flush for any remaining text
        if self.in_table: self.flush("table")
        elif self.in_code_block: self.flush("code")
        else: self.flush("text")
        
        return self.chunks

def run_extraction_pipeline(pdf_path):
    # 1. Clean Path (Fixes Mac drag-and-drop artifacts)
    pdf_path = pdf_path.strip().strip("'").strip('"')
    
    if not os.path.exists(pdf_path):
        logger.error(f"File not found: {pdf_path}")
        return

    file_name = Path(pdf_path).stem
    output_dir = Path("output_jsonl")
    output_dir.mkdir(exist_ok=True)

    # 2. Configure Docling (FAST MODE - No OCR download)
    logger.info("Initializing Docling Pipeline...")
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False               # DISABLED to prevent download errors
    pipeline_options.do_table_structure = True    # Keep table detection
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
    pipeline_options.generate_page_images = False    
    pipeline_options.generate_picture_images = False 

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    # 3. Process
    logger.info(f"Processing: {file_name}")
    try:
        doc = converter.convert(pdf_path)
        markdown_text = doc.document.export_to_markdown()
        
        # 4. Chunk with Smart Logic
        chunker = SmartChunker(markdown_text, file_name)
        chunks = chunker.process()

        # 5. Save
        output_file = output_dir / f"{file_name}.jsonl"
        with open(output_file, "w", encoding="utf-8") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

        logger.info(f"SUCCESS: Saved {len(chunks)} chunks to {output_file}")

    except Exception as e:
        logger.error(f"Extraction Failed: {str(e)}")

if __name__ == "__main__":
    # Auto-detect or use command line arg
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        # Check current folder for PDFs
        pdfs = [f for f in os.listdir(".") if f.lower().endswith(".pdf")]
        if pdfs:
            target = pdfs[0]
            logger.info(f"Auto-detected PDF: {target}")
        else:
            target = input("Enter path to PDF: ").strip('"')
            
    run_extraction_pipeline(target)