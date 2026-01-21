import sys
import os
import time
import tempfile
import warnings
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, 
    AcceleratorOptions, 
    AcceleratorDevice,
    TableFormerMode
)
from pypdf import PdfReader, PdfWriter

# 1. Silence the Pydantic/System Warnings
warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3" 

def extract_robust(file_path):
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at '{file_path}'")
        return

    # 2. Setup Docling (CPU Mode)
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=4, 
        device=AcceleratorDevice.CPU
    )

    converter = DocumentConverter(
        format_options={"pdf": PdfFormatOption(pipeline_options=pipeline_options)}
    )

    print(f"📄 Inspecting: {os.path.basename(file_path)}...")
    
    try:
        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        print(f"📊 Found {total_pages} pages. Processing safely in System Temp...")
        
        full_text = []
        start_time = time.time()

        # 3. Use System Temp Directory (Bypasses OneDrive Locking)
        with tempfile.TemporaryDirectory() as temp_dir:
            
            for i in range(total_pages):
                page_num = i + 1
                # Update progress on the same line
                print(f"   ⏳ Extracting Page {page_num}/{total_pages}...", end="\r")
                
                # A. Write Single Page to Temp
                writer = PdfWriter()
                writer.add_page(reader.pages[i])
                temp_pdf_path = os.path.join(temp_dir, f"temp_page_{page_num}.pdf")
                
                with open(temp_pdf_path, "wb") as f:
                    writer.write(f)
                
                # B. Extract
                try:
                    doc = converter.convert(temp_pdf_path)
                    page_md = doc.document.export_to_markdown()
                    
                    full_text.append(f"\n\n--- PAGE {page_num} ---\n\n")
                    full_text.append(page_md)
                except Exception as e:
                    full_text.append(f"\n[ERROR: Failed to extract Page {page_num}]\n")
        
        # 4. Save Final Output
        print(f"   ✅ Finished processing {total_pages} pages. Saving...          ")
        
        combined_text = "".join(full_text)
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        output_filename = f"{base_name}_FULL.md"
        
        # Save in the script's directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, output_filename)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(combined_text)
            
        duration = time.time() - start_time
        print(f"\n🎉 SUCCESS ({duration:.2f}s)")
        print(f"📂 Output File: {output_filename}")

    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Handle paths with spaces
        file_path = " ".join(sys.argv[1:]).strip('"')
        extract_robust(file_path)
    else:
        print("Usage: python force_extract_v2.py <path_to_pdf>")