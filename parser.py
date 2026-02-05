#!/usr/bin/env python3
"""
PDF Parser using Docling - Updated Version
Converts PDF question papers and marking schemes to Markdown format
Extracts images to a separate folder
Optimized for systems with 16GB RAM and no GPU
"""

import os
import sys
from pathlib import Path
from typing import Optional
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_pdf_to_markdown(
    pdf_path: str,
    output_dir: str = "output",
    images_dir: str = "images"
) -> Optional[str]:
    """
    Parse a PDF file to Markdown format using Docling
    
    Args:
        pdf_path: Path to the input PDF file
        output_dir: Directory to save the markdown output
        images_dir: Directory to save extracted images
        
    Returns:
        Path to the generated markdown file, or None if failed
    """
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        from docling_core.types.doc import PictureItem, TableItem
        
        logger.info(f"Processing PDF: {pdf_path}")
        
        # Create output directories
        output_path = Path(output_dir)
        images_path = Path(images_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        images_path.mkdir(parents=True, exist_ok=True)
        
        # Configure pipeline for low-resource systems
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False  # Disable OCR to save memory
        pipeline_options.do_table_structure = True
        pipeline_options.images_scale = 1.0  # Don't upscale images
        pipeline_options.generate_page_images = False  # Save memory
        
        # Initialize converter with optimized settings
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                    backend=PyPdfiumDocumentBackend
                )
            }
        )
        
        # Convert the PDF
        logger.info("Converting PDF to document format...")
        result = converter.convert(pdf_path)
        
        # Get the base filename without extension
        pdf_filename = Path(pdf_path).stem
        
        # Export to Markdown
        markdown_filename = f"{pdf_filename}.md"
        markdown_path = output_path / markdown_filename
        
        logger.info(f"Exporting to Markdown: {markdown_path}")
        
        # Export markdown
        markdown_content = result.document.export_to_markdown()
        
        # Extract images
        image_counter = 0
        try:
            # Iterate through document items to find images
            for idx, item in enumerate(result.document.body.iterate_items()):
                if isinstance(item, PictureItem):
                    try:
                        if hasattr(item, 'image') and item.image:
                            image_filename = f"{pdf_filename}_image_{image_counter+1}.png"
                            image_path = images_path / image_filename
                            
                            # Save the image
                            item.image.save(str(image_path))
                            logger.info(f"Saved image: {image_path}")
                            image_counter += 1
                            
                    except Exception as e:
                        logger.warning(f"Failed to save image {idx}: {e}")
                        
        except Exception as e:
            logger.warning(f"Could not extract images: {e}")
        
        # Write markdown file
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        
        logger.info(f"✓ Successfully created: {markdown_path}")
        logger.info(f"✓ Extracted {image_counter} images to: {images_path}")
        
        return str(markdown_path)
        
    except ImportError as e:
        logger.error(f"Missing required dependency: {e}")
        logger.error("Please install dependencies: pip install -r requirements.txt")
        return None
    except Exception as e:
        logger.error(f"Error processing PDF: {e}", exc_info=True)
        return None


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Convert PDF question papers/marking schemes to Markdown"
    )
    parser.add_argument(
        "pdf_file",
        help="Path to the PDF file to convert"
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for markdown output (default: output)"
    )
    parser.add_argument(
        "--images-dir",
        default="images",
        help="Directory for extracted images (default: images)"
    )
    
    args = parser.parse_args()
    
    # Check if PDF file exists
    if not os.path.exists(args.pdf_file):
        logger.error(f"PDF file not found: {args.pdf_file}")
        sys.exit(1)
    
    # Parse the PDF
    result = parse_pdf_to_markdown(
        args.pdf_file,
        args.output_dir,
        args.images_dir
    )
    
    if result:
        logger.info(f"\n{'='*60}")
        logger.info(f"Conversion completed successfully!")
        logger.info(f"Markdown file: {result}")
        logger.info(f"Images folder: {args.images_dir}")
        logger.info(f"{'='*60}")
        sys.exit(0)
    else:
        logger.error("Conversion failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()