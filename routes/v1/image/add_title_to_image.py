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

from services.gcp_toolkit import upload_file_to_gcs, get_signed_url

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
        "padding_color": "#fa901e"
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
        
        # Generate a unique job ID
        import uuid
        job_id = str(uuid.uuid4())
        
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
            job_id=job_id
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error in add_title_to_image: {str(e)}")
        return jsonify({"error": str(e)}), 500

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

def find_thai_font(font_size=64):
    """
    Find a suitable font for Thai text.
    
    Args:
        font_size: Font size
        
    Returns:
        PIL ImageFont object
    """
    # Try common Thai font paths
    possible_paths = [
        "/usr/share/fonts/truetype/thai-tlwg/Sarabun-Bold.ttf",
        "/usr/share/fonts/custom/Sarabun-Bold.ttf",
        "/usr/share/fonts/truetype/tlwg/Sarabun-Bold.ttf",
        "C:/Windows/Fonts/Sarabun-Bold.ttf",
        "/System/Library/Fonts/Sarabun-Bold.ttf"
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
                              border_color, border_width, padding_bottom, padding_color, job_id):
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
        
        # Create a new image with padding at the bottom
        new_height = original_height + padding_bottom
        new_img = Image.new('RGB', (original_width, new_height), color=padding_color)
        
        # Paste the original image at the top
        new_img.paste(img, (0, 0))
        
        # Find a suitable font
        font = find_thai_font(font_size)
        
        # Create a drawing context
        draw = ImageDraw.Draw(new_img)
        
        # Calculate line height and positions for perfect vertical centering
        total_lines = len(title_lines)
        line_spacing = 15  # Pixels between lines
        
        # Calculate the total height of all text lines including spacing
        total_text_height = (total_lines * font_size) + ((total_lines - 1) * line_spacing)
        
        # Calculate starting Y position to center text vertically in the padding area
        padding_start_y = original_height
        y_start = padding_start_y + (padding_bottom - total_text_height) / 2
        
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
        bucket_name = os.environ.get('GCS_BUCKET_NAME', 'nca-toolkit-thai-text-bucket')
        output_blob_name = f"{job_id}_titled_image.jpg"
        
        upload_file_to_gcs(bucket_name, output_blob_name, output_image_path)
        
        # Get signed URL
        signed_url = get_signed_url(bucket_name, output_blob_name)
        
        # Prepare result
        result = {
            "url": signed_url,
            "dimensions": {
                "original": {
                    "width": original_width,
                    "height": original_height
                },
                "output": {
                    "width": original_width,
                    "height": new_height
                }
            }
        }
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing image title: {str(e)}")
        raise
