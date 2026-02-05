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
from docling_core.types.doc import ImageRefMode
from pypdf import PdfReader, PdfWriter

# 1. Silence Warnings
warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

def extract_text_and_images(file_path):
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at '{file_path}'")
        return

    # --- NEW FOLDER LOGIC ---
    file_name_no_ext = os.path.splitext(os.path.basename(file_path))[0]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Create media folder: /Testing Arena/Computer Systems QP_media/
    media_dir_name = f"{file_name_no_ext}_media"
    media_dir = os.path.join(script_dir, media_dir_name)
    os.makedirs(media_dir, exist_ok=True)

    print(f"⚙️  Configuring Docling for Text + Image Extraction...")
    print(f"📂 Images will be saved to: {media_dir_name}/")

    # 2. Setup Enhanced Pipeline
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
    
    # Enable Image Extraction
    pipeline_options.generate_picture_images = True  
    pipeline_options.images_scale = 2.0              

    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=4, 
        device=AcceleratorDevice.CPU
    )

    converter = DocumentConverter(
        format_options={"pdf": PdfFormatOption(pipeline_options=pipeline_options)}
    )

    print(f"📄 Processing: {os.path.basename(file_path)}...")
    
    try:
        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        full_text = []

        start_time = time.time()

        # Use System Temp to avoid OneDrive locking issues
        with tempfile.TemporaryDirectory() as temp_dir:
            for i in range(total_pages):
                page_num = i + 1
                print(f"   ⏳ Processing Page {page_num}/{total_pages}...", end="\r")
                
                # A. Save Single Page to Temp
                writer = PdfWriter()
                writer.add_page(reader.pages[i])
                temp_pdf_path = os.path.join(temp_dir, f"temp_page_{page_num}.pdf")
                with open(temp_pdf_path, "wb") as f:
                    writer.write(f)
                
                # B. Convert
                try:
                    doc = converter.convert(temp_pdf_path)
                    
                    # --- C. SAVE IMAGES & UPDATE MAPPING ---
                    for pic_idx, picture in enumerate(doc.document.pictures):
                        image_obj = picture.get_image(doc.document)
                        if image_obj:
                            # 1. Save Image
                            img_filename = f"page_{page_num}_img_{pic_idx}.png"
                            img_path = os.path.join(media_dir, img_filename)
                            
                            with open(img_path, "wb") as f:
                                image_obj.save(f, format="PNG")
                            
                            # 2. IMPORTANT: Update the internal URI to map to the file
                            # We use a relative path so the markdown works on any computer
                            # Format: "Folder_Name/Image_Name.png"
                            relative_path = f"{media_dir_name}/{img_filename}"
                            picture.image.uri = relative_path

                    # D. Get Markdown (With Mapped Images)
                    # Now that URI is set, REFERENCED mode will use your path instead of placeholder
                    page_md = doc.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED)
                    
                    full_text.append(f"\n\n--- PAGE {page_num} ---\n\n")
                    full_text.append(page_md)

                except Exception as e:
                    full_text.append(f"\n[ERROR: Failed to extract Page {page_num}: {e}]\n")

        # 3. Save Final Markdown
        combined_text = "".join(full_text)
        output_md_path = os.path.join(script_dir, f"{file_name_no_ext}_MAPPED.md")
        
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(combined_text)
            
        duration = time.time() - start_time
        print(f"\n\n🎉 SUCCESS ({duration:.2f}s)")
        print(f"📝 Markdown saved to: {os.path.basename(output_md_path)}")
        print(f"🖼️  Images mapped in: {media_dir_name}/")

    except Exception as e:
        print(f"\n❌ Critical Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = " ".join(sys.argv[1:]).strip('"')
        extract_text_and_images(file_path)
    else:
        print("Usage: python extract_and_map.py <path_to_pdf>")