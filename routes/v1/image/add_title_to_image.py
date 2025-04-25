import os
import re
import json
import tempfile
import logging
import requests
import subprocess
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from io import BytesIO
from pythainlp import word_tokenize

from services.gcp_toolkit import upload_to_gcs_with_path, generate_signed_url

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create blueprint
add_title_to_image_bp = Blueprint('add_title_to_image', __name__)

@add_title_to_image_bp.route('/add_title_to_image', methods=['POST'])
def add_title_to_image():
    """
    Add a title with padding to an image.
    
    Request body:
    {
        "image_url": "URL of the image",
        "title": "Title text",
        "font_size": 64,
        "font_color": "white",
        "border_color": "#000000",
        "border_width": 2,
        "padding_bottom": 180,
        "padding_color": "#fa901e",
        "font_name": "Sarabun-Regular.ttf"  # Optional: specify a Thai font
    }
    
    Returns:
        JSON with URL of the processed image and metadata
    """
    try:
        # Get request data
        data = request.get_json()
        
        # Check required parameters
        if 'image_url' not in data:
            return jsonify({"error": "Missing required parameter: image_url"}), 400
        if 'title' not in data:
            return jsonify({"error": "Missing required parameter: title"}), 400
            
        # Get parameters with defaults
        image_url = data['image_url']
        title = data['title']
        font_size = data.get('font_size', 64)
        font_color = data.get('font_color', 'white')
        border_color = data.get('border_color', '#000000')
        border_width = data.get('border_width', 2)
        padding_bottom = data.get('padding_bottom', 180)
        padding_color = data.get('padding_color', '#fa901e')
        font_name = data.get('font_name')  # Optional font name
        
        # Generate a unique job ID
        import uuid
        job_id = str(uuid.uuid4())
        
        # Clean title text by removing colons and semicolons
        title = clean_title_text(title)
        
        # Split title into lines for better display
        from routes.v1.video.add_title_to_video import smart_split_thai_text
        title_lines = smart_split_thai_text(title, max_chars_per_line=30)
        
        # Process the image
        result = process_add_title_to_image(
            image_url=image_url,
            title_lines=title_lines,
            font_size=font_size,
            font_color=font_color,
            border_color=border_color,
            border_width=border_width,
            padding_bottom=padding_bottom,
            padding_color=padding_color,
            job_id=job_id,
            font_name=font_name  # Pass the font name to the processing function
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error in add_title_to_image: {str(e)}")
        return jsonify({"error": str(e)}), 500

def clean_title_text(text):
    """
    Clean title text by removing colons and semicolons.
    
    Args:
        text: The title text to clean
        
    Returns:
        Cleaned text without colons or semicolons
    """
    # Remove colons and semicolons
    cleaned_text = text.replace(':', '').replace(';', '')
    
    # If the text contains Thai characters, we need to handle it differently
    if re.search(r'[\u0E00-\u0E7F]', text):
        # For Thai text with colons or semicolons, we want to split at those points
        # but not include the punctuation
        if ':' in text:
            parts = text.split(':', 1)
            if len(parts) == 2:
                title_part = parts[0].strip()
                subtitle_part = parts[1].strip()
                # Join with a space instead of the colon
                cleaned_text = f"{title_part} {subtitle_part}"
        
        # Same for semicolons
        if ';' in cleaned_text:
            parts = cleaned_text.split(';', 1)
            if len(parts) == 2:
                title_part = parts[0].strip()
                subtitle_part = parts[1].strip()
                # Join with a space instead of the semicolon
                cleaned_text = f"{title_part} {subtitle_part}"
    
    return cleaned_text

def download_image(url, local_path=None):
    """
    Download an image from a URL.
    
    Args:
        url: URL of the image
        local_path: Optional local path to save the image
        
    Returns:
        PIL Image object
    """
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    img = Image.open(BytesIO(response.content))
    
    if local_path:
        img.save(local_path)
        
    return img

def find_thai_font(font_size=64, font_name=None):
    """
    Find a suitable sans-serif font for Thai text.
    
    Args:
        font_size: Font size
        font_name: Optional specific font name to use
        
    Returns:
        PIL ImageFont object
    """
    # Check for fonts in the project's fonts directory first
    project_fonts = [
        # Prioritize Sarabun (modern Thai sans-serif)
        os.path.join('fonts', 'Sarabun-Regular.ttf'),
        os.path.join('fonts', 'Sarabun-Bold.ttf'),
        os.path.join('fonts', 'Sarabun-Medium.ttf'),
        # Then Noto Sans Thai (excellent Thai support)
        os.path.join('fonts', 'NotoSansThai-Regular.ttf'),
        os.path.join('fonts', 'NotoSansThai-Bold.ttf'),
        os.path.join('fonts', 'NotoSansThai-Medium.ttf')
    ]
    
    # If a specific font name is provided, try to use it first
    if font_name:
        specific_font = os.path.join('fonts', font_name)
        if os.path.exists(specific_font):
            try:
                return ImageFont.truetype(specific_font, font_size)
            except Exception as e:
                logger.warning(f"Could not load specified font {specific_font}: {str(e)}")
    
    # Try project fonts first
    for path in project_fonts:
        if os.path.exists(path):
            try:
                logger.info(f"Loading Thai font: {path}")
                return ImageFont.truetype(path, font_size)
            except Exception as e:
                logger.warning(f"Could not load font {path}: {str(e)}")
    
    # Try common Thai sans-serif font paths (prioritizing sans-serif fonts)
    possible_paths = [
        # Sans-serif Thai fonts
        "/usr/share/fonts/truetype/thai-tlwg/Garuda.ttf",
        "/usr/share/fonts/truetype/thai-tlwg/Garuda-Bold.ttf",
        "/usr/share/fonts/custom/Garuda.ttf",
        "/usr/share/fonts/custom/Garuda-Bold.ttf",
        "/usr/share/fonts/truetype/thai-tlwg/THSarabunNew.ttf",
        "/usr/share/fonts/truetype/thai-tlwg/THSarabunNew-Bold.ttf",
        "/usr/share/fonts/custom/THSarabunNew.ttf",
        "/usr/share/fonts/custom/THSarabunNew-Bold.ttf",
        # Fallback to other Thai fonts
        "/usr/share/fonts/truetype/thai-tlwg/Sarabun.ttf",
        "/usr/share/fonts/truetype/thai-tlwg/Sarabun-Bold.ttf",
        "/usr/share/fonts/custom/Sarabun.ttf",
        "/usr/share/fonts/custom/Sarabun-Bold.ttf",
        # Windows paths
        "C:/Windows/Fonts/Garuda.ttf",
        "C:/Windows/Fonts/Garuda-Bold.ttf",
        "C:/Windows/Fonts/THSarabunNew.ttf",
        "C:/Windows/Fonts/THSarabunNew-Bold.ttf",
        "C:/Windows/Fonts/Sarabun.ttf",
        "C:/Windows/Fonts/Sarabun-Bold.ttf",
        # Mac paths
        "/System/Library/Fonts/Garuda.ttf",
        "/System/Library/Fonts/THSarabunNew.ttf",
        "/System/Library/Fonts/Sarabun.ttf"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, font_size)
            except Exception as e:
                logger.warning(f"Could not load font {path}: {str(e)}")
    
    # Fallback to default font
    return ImageFont.load_default()

def process_add_title_to_image(image_url, title_lines, font_size, font_color, 
                              border_color, border_width, padding_bottom, padding_color, job_id, font_name=None):
    """
    Process the image to add a title with padding.
    
    Args:
        image_url: URL of the image
        title_lines: List of title lines
        font_size: Font size
        font_color: Font color
        border_color: Border color
        border_width: Border width
        padding_bottom: Bottom padding in pixels
        padding_color: Padding color
        job_id: Job ID
        font_name: Optional font name
        
    Returns:
        Dictionary with result information
    """
    try:
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        
        # Download the image
        input_image_path = os.path.join(temp_dir, f"input_{job_id}.jpg")
        img = download_image(image_url, input_image_path)
        
        # Get image dimensions
        original_width, original_height = img.size
        
        # Ensure padding is sufficient for text
        # Calculate minimum required padding based on text content
        font = find_thai_font(font_size, font_name)
        
        # Calculate total text height with spacing
        total_lines = len(title_lines)
        line_spacing = int(font_size * 0.3)  # Adjust line spacing to 30% of font size
        
        # Calculate the total height of all text lines including spacing
        total_text_height = (total_lines * font_size) + ((total_lines - 1) * line_spacing)
        
        # Add extra padding above and below text (50% of font size)
        extra_padding = int(font_size * 0.5)
        
        # Calculate minimum required padding
        min_required_padding = total_text_height + (extra_padding * 2)
        
        # If requested padding is less than required, increase it
        if padding_bottom < min_required_padding:
            padding_bottom = min_required_padding
            logger.info(f"Increased padding to {padding_bottom}px to fit text properly")
        
        # Calculate the ratio to resize the original image to make room for the title
        # while maintaining the original dimensions
        new_image_height = original_height - padding_bottom
        if new_image_height <= 0:
            # If padding would take up entire image, reduce padding to half the image height
            padding_bottom = original_height // 2
            new_image_height = original_height - padding_bottom
            logger.warning(f"Padding was too large, reduced to {padding_bottom}px")
        
        # Resize the original image to make room for the title
        # Keep the original width (no side padding)
        resized_img = img.resize((original_width, new_image_height), Image.LANCZOS)
        
        # Create a new image with the original dimensions
        new_img = Image.new('RGB', (original_width, original_height), color=padding_color)
        
        # Paste the resized original image at the top
        new_img.paste(resized_img, (0, 0))
        
        # Create a drawing context
        draw = ImageDraw.Draw(new_img)
        
        # Calculate starting Y position to center text vertically in the padding area with extra space
        padding_start_y = new_image_height
        y_start = padding_start_y + extra_padding
        
        # Calculate maximum text width to ensure it fits within the image
        max_text_width = 0
        for line in title_lines:
            text_width = draw.textlength(line, font=font)
            max_text_width = max(max_text_width, text_width)
        
        # If text is too wide, reduce font size
        if max_text_width > (original_width * 0.9):  # Allow 90% of image width
            scale_factor = (original_width * 0.9) / max_text_width
            new_font_size = int(font_size * scale_factor)
            logger.info(f"Reduced font size from {font_size} to {new_font_size} to fit text width")
            font = find_thai_font(new_font_size, font_name)
            # Recalculate line spacing with new font size
            line_spacing = int(new_font_size * 0.3)
        
        # Draw each line of text
        for i, line in enumerate(title_lines):
            # Calculate exact Y position for this line with improved spacing
            y_pos = y_start + (i * (font_size + line_spacing))
            
            # Calculate text width to center horizontally
            text_width = draw.textlength(line, font=font)
            x_pos = (original_width - text_width) / 2
            
            # Draw text border if specified
            if border_width > 0:
                for offset_x in range(-border_width, border_width + 1):
                    for offset_y in range(-border_width, border_width + 1):
                        if offset_x != 0 or offset_y != 0:
                            draw.text((x_pos + offset_x, y_pos + offset_y), line, 
                                     font=font, fill=border_color)
            
            # Draw the main text
            draw.text((x_pos, y_pos), line, font=font, fill=font_color)
        
        # Save the output image
        output_image_path = os.path.join(temp_dir, f"output_title_{job_id}.jpg")
        new_img.save(output_image_path, quality=95)
        
        # Upload to GCS
        bucket_name = os.environ.get('GCP_BUCKET_NAME', 'nca-toolkit-thai-text-bucket')
        output_blob_name = f"{job_id}_titled_image.jpg"
        
        # Use the correct GCP toolkit functions
        upload_to_gcs_with_path(output_image_path, bucket_name, output_blob_name)
        
        # Create public URL instead of signed URL
        public_url = f"https://storage.googleapis.com/{bucket_name}/{output_blob_name}"
        
        # Prepare result
        result = {
            "url": public_url,
            "dimensions": {
                "original": {
                    "width": original_width,
                    "height": original_height
                },
                "output": {
                    "width": original_width,
                    "height": original_height  # Now matches original height
                }
            }
        }
        
        # Clean up temporary files
        try:
            os.remove(input_image_path)
            os.remove(output_image_path)
            os.rmdir(temp_dir)
        except Exception as e:
            logger.warning(f"Error cleaning up temporary files: {str(e)}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in process_add_title_to_image: {str(e)}")
        raise e
