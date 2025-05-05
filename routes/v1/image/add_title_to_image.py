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

# Comment out GCP imports but keep them for future use
# from services.gcp_toolkit import upload_to_gcs_with_path, generate_signed_url
# Import only the storage utility
from storage_utils import upload_file, get_file_url

# Set up logging with more detailed format
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
        "font_name": "Sarabun-Regular.ttf",  # Optional: specify a Thai font
        "text_align": "center",              # Optional: text alignment (left, center, right)
        "max_lines": 3,                      # Optional: maximum number of lines to display
        "highlight_words": ["word1", "word2"],  # Optional: words to highlight
        "highlight_color": "#ffff00",        # Optional: color for highlighted words
        "auto_highlight": true,              # Optional: automatically highlight important words
        "highlight_count": 2,                # Optional: number of words to auto-highlight
        "padding_multiplier": 0.5            # Optional: padding multiplier for breathing area (0.5 = 50% of font size)
    }
    
    Returns:
        JSON with URL of the processed image and metadata
    """
    try:
        logger.info("[DEBUG] Starting add_title_to_image endpoint processing")
        
        # Get request data
        data = request.get_json()
        logger.info(f"[DEBUG] Received request data: {json.dumps(data, ensure_ascii=False)}")
        
        # Check required parameters
        if 'image_url' not in data:
            logger.warning("[DEBUG] Missing required parameter: image_url")
            return jsonify({"error": "Missing required parameter: image_url"}), 400
        if 'title' not in data:
            logger.warning("[DEBUG] Missing required parameter: title")
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
        text_align = data.get('text_align', 'center')  # Default to center alignment
        max_lines = data.get('max_lines', 3)  # Default to 3 lines maximum
        highlight_words = data.get('highlight_words', [])  # Words to highlight
        highlight_color = data.get('highlight_color', '#ffff00')  # Highlight color
        auto_highlight = data.get('auto_highlight', False)  # Auto-highlight important words
        highlight_count = data.get('highlight_count', 2)  # Number of words to auto-highlight
        padding_multiplier = data.get('padding_multiplier', 0.5)  # Default to 50% of font size
        
        logger.info(f"[DEBUG] Processing parameters - Font: {font_name}, Align: {text_align}, Max Lines: {max_lines}")
        logger.info(f"[DEBUG] Title text: {title}")
        logger.info(f"[DEBUG] Padding multiplier: {padding_multiplier}")
        
        # Generate a unique job ID
        import uuid
        job_id = str(uuid.uuid4())
        logger.info(f"[DEBUG] Generated job ID: {job_id}")
        
        # Clean title text by removing colons and semicolons
        title = clean_title_text(title)
        logger.info(f"[DEBUG] Cleaned title: {title}")
        
        # Split title into lines for better display
        title_lines = adaptive_split_thai_text(title, max_lines)
        logger.info(f"[DEBUG] Split title into {len(title_lines)} lines: {title_lines}")
        
        # Auto-highlight important words if requested
        if auto_highlight:
            logger.info(f"[DEBUG] Auto-highlighting enabled, looking for {highlight_count} important words")
            auto_highlight_words = find_important_words(title, highlight_count)
            logger.info(f"[DEBUG] Auto-highlighted words: {auto_highlight_words}")
            # Combine with manually specified highlight words
            highlight_words = list(set(highlight_words + auto_highlight_words))
            logger.info(f"[DEBUG] Final highlight words: {highlight_words}")
        
        # Process the image
        logger.info("[DEBUG] Starting image processing")
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
            font_name=font_name,
            text_align=text_align,
            highlight_words=highlight_words,
            highlight_color=highlight_color,
            padding_multiplier=padding_multiplier
        )
        
        logger.info(f"[DEBUG] Image processing completed, result URL: {result.get('url', 'No URL')}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"[DEBUG] Error in add_title_to_image: {str(e)}", exc_info=True)
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

def find_important_words(text, count):
    """
    Find the most important words in the text, focusing on quality over quantity.
    Ensures we highlight words that are closely related or appear near each other.
    
    Args:
        text: The text to analyze
        count: The maximum number of important words to find
        
    Returns:
        List of important words (limited to prevent overwhelming)
    """
    logger.info(f"[DEBUG] Finding important words in text: '{text}', max count: {count}")
    
    # Tokenize the text into words
    words = word_tokenize(text, engine='newmm')
    logger.info(f"[DEBUG] Tokenized into {len(words)} words: {words}")
    
    # Remove common stop words (expanded list)
    stop_words = [
        'และ', 'หรือ', 'ของ', 'ใน', 'ที่', 'เป็น', 'ไม่', 'มี', 'ได้', 'จะ', 
        'กับ', 'จาก', 'โดย', 'ถึง', 'แต่', 'ก็', 'เพื่อ', 'ต่อ', 'กว่า', 'เมื่อ',
        'ให้', 'แล้ว', 'ด้วย', 'อยู่', 'อย่าง', 'ไป', 'มา', 'ยัง', 'คือ', 'นี้',
        'นั้น', 'ๆ', 'นะ', 'ครับ', 'ค่ะ', 'น่า', 'ช่วย', 'เลย', 'พอ', 'ทำ'
    ]
    filtered_words = [word for word in words if word not in stop_words and len(word) > 1]
    logger.info(f"[DEBUG] After stop word removal: {len(filtered_words)} words: {filtered_words}")
    
    # Create a list of word positions to track where each word appears in the text
    word_positions = {}
    for i, word in enumerate(words):
        if word in filtered_words:
            if word not in word_positions:
                word_positions[word] = []
            word_positions[word].append(i)
    
    # Count word frequencies
    word_freq = {}
    for word in filtered_words:
        if word in word_freq:
            word_freq[word] += 1
        else:
            word_freq[word] = 1
    logger.info(f"[DEBUG] Word frequencies: {word_freq}")
    
    # Score words based on frequency and length
    word_scores = {}
    for word, freq in word_freq.items():
        # Prioritize words that are:
        # 1. Used multiple times (frequency)
        # 2. Longer (typically more meaningful in Thai)
        # 3. Not too short (at least 2 characters)
        if len(word) >= 2:
            word_scores[word] = freq * (0.5 + (min(len(word), 10) / 10))
    
    # Sort words by score
    sorted_words = sorted(word_scores.items(), key=lambda x: x[1], reverse=True)
    logger.info(f"[DEBUG] Words sorted by score: {sorted_words}")
    
    # Limit the number of highlighted words to prevent overwhelming
    max_highlights = min(count, 2)  # Never highlight more than 2 words by default
    
    # If we have a very short text, highlight even fewer words
    if len(filtered_words) < 10:
        max_highlights = min(max_highlights, 1)  # For short text, highlight at most 1 word
    logger.info(f"[DEBUG] Max highlights set to: {max_highlights}")
    
    # Get the top-scoring words as candidates
    candidate_words = [word for word, score in sorted_words[:max_highlights * 2]]  # Get more candidates than needed
    logger.info(f"[DEBUG] Candidate words: {candidate_words}")
    
    # If we have more than one word to highlight, ensure they are closely related
    final_words = []
    if len(candidate_words) > 0:
        # Start with the highest scoring word
        final_words.append(candidate_words[0])
        logger.info(f"[DEBUG] Selected first word: {candidate_words[0]}")
        
        # If we need more words and have candidates
        if max_highlights > 1 and len(candidate_words) > 1:
            # Find words that are close to the first selected word
            first_word = candidate_words[0]
            first_positions = word_positions.get(first_word, [])
            logger.info(f"[DEBUG] First word '{first_word}' positions: {first_positions}")
            
            # Calculate proximity scores for remaining candidates
            proximity_scores = {}
            for word in candidate_words[1:]:
                if word in word_positions:
                    # Find the minimum distance between this word and the first word
                    min_distance = float('inf')
                    for pos1 in first_positions:
                        for pos2 in word_positions[word]:
                            distance = abs(pos1 - pos2)
                            min_distance = min(min_distance, distance)
                    
                    # Score is inverse of distance (closer = higher score)
                    # but also consider the original importance score
                    original_score = word_scores[word]
                    if min_distance <= 5:  # Words are close (within 5 tokens)
                        proximity_scores[word] = original_score * (1 + (5 - min_distance) * 0.2)
                    else:
                        proximity_scores[word] = original_score * 0.5  # Penalize distant words
                    logger.info(f"[DEBUG] Word '{word}' min distance: {min_distance}, proximity score: {proximity_scores[word]}")
            
            # Sort by proximity score
            proximity_sorted = sorted(proximity_scores.items(), key=lambda x: x[1], reverse=True)
            logger.info(f"[DEBUG] Words sorted by proximity: {proximity_sorted}")
            
            # Add the closest high-scoring word
            if proximity_sorted:
                final_words.append(proximity_sorted[0][0])
                logger.info(f"[DEBUG] Added second word based on proximity: {proximity_sorted[0][0]}")
    
    logger.info(f"[DEBUG] Final selected words to highlight: {final_words}")
    return final_words

def adaptive_split_thai_text(text, max_lines):
    """
    Adaptively split Thai text to fit within a specified number of lines.
    Adjusts the characters per line based on the maximum number of lines allowed.
    
    Args:
        text: The text to split
        max_lines: Maximum number of lines to use
        
    Returns:
        List of lines that fit within the max_lines constraint
    """
    from routes.v1.video.add_title_to_video import smart_split_thai_text
    
    # If text is empty or max_lines is 0, return empty list
    if not text or max_lines <= 0:
        return []
    
    # Start with a reasonable character limit
    chars_per_line = 30
    
    # Get initial split
    lines = smart_split_thai_text(text, max_chars_per_line=chars_per_line)
    
    # If it already fits, we're done
    if len(lines) <= max_lines:
        logger.info(f"[DEBUG] Text fits in {len(lines)} lines with {chars_per_line} chars per line")
        return lines
    
    # Binary search to find the optimal characters per line
    min_chars = 10  # Minimum reasonable characters per line
    max_chars = 100  # Maximum reasonable characters per line
    
    while min_chars <= max_chars:
        mid_chars = (min_chars + max_chars) // 2
        lines = smart_split_thai_text(text, max_chars_per_line=mid_chars)
        
        if len(lines) <= max_lines:
            # This works, but try to find a smaller chars_per_line that still works
            max_chars = mid_chars - 1
            chars_per_line = mid_chars  # Save this working value
        else:
            # Too many lines, need more chars per line
            min_chars = mid_chars + 1
    
    # Use the last working value
    lines = smart_split_thai_text(text, max_chars_per_line=chars_per_line)
    
    # If we still have too many lines (shouldn't happen due to binary search), force truncate
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    
    logger.info(f"[DEBUG] Adaptive split: {len(lines)} lines with {chars_per_line} chars per line")
    return lines

def process_add_title_to_image(image_url, title_lines, font_size, font_color, 
                              border_color, border_width, padding_bottom, padding_color, job_id, font_name=None,
                              text_align='center', highlight_words=[], highlight_color='#ffff00', padding_multiplier=0.5):
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
        text_align: Text alignment (left, center, right)
        highlight_words: Words to highlight
        highlight_color: Color for highlighted words
        padding_multiplier: Multiplier for padding space (breathing area) above and below text (default: 0.5)
        
    Returns:
        Dictionary with result information
    """
    try:
        logger.info(f"[DEBUG] Starting image processing with job_id: {job_id}")
        logger.info(f"[DEBUG] Image URL: {image_url}")
        logger.info(f"[DEBUG] Title lines: {title_lines}")
        logger.info(f"[DEBUG] Font settings: size={font_size}, color={font_color}, name={font_name}")
        logger.info(f"[DEBUG] Text alignment: {text_align}")
        logger.info(f"[DEBUG] Highlight settings: words={highlight_words}, color={highlight_color}")
        logger.info(f"[DEBUG] Padding multiplier: {padding_multiplier}")
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        logger.info(f"[DEBUG] Created temp directory: {temp_dir}")
        
        # Download the image
        input_image_path = os.path.join(temp_dir, f"input_{job_id}.jpg")
        img = download_image(image_url, input_image_path)
        logger.info(f"[DEBUG] Downloaded image to: {input_image_path}")
        
        # Get image dimensions
        original_width, original_height = img.size
        logger.info(f"[DEBUG] Original image dimensions: {original_width}x{original_height}")
        
        # Ensure padding is sufficient for text
        # Calculate minimum required padding based on text content
        font = find_thai_font(font_size, font_name)
        logger.info(f"[DEBUG] Selected font: {font}")
        
        # Calculate total text height with spacing
        total_lines = len(title_lines)
        line_spacing = int(font_size * 0.3)  # Adjust line spacing to 30% of font size
        
        # Calculate the total height of all text lines including spacing
        total_text_height = (total_lines * font_size) + ((total_lines - 1) * line_spacing)
        
        # Add extra padding above and below text (using the padding_multiplier parameter)
        extra_padding = int(font_size * padding_multiplier)
        
        # Calculate minimum required padding
        min_required_padding = total_text_height + (extra_padding * 2)
        logger.info(f"[DEBUG] Calculated min required padding: {min_required_padding}px (with padding multiplier: {padding_multiplier})")
        
        # If requested padding is less than required, increase it
        if padding_bottom < min_required_padding:
            padding_bottom = min_required_padding
            logger.info(f"[DEBUG] Increased padding to {padding_bottom}px to fit text properly")
        
        # Calculate the ratio to resize the original image to make room for the title
        # while maintaining the original dimensions
        new_image_height = original_height - padding_bottom
        if new_image_height <= 0:
            # If padding would take up entire image, reduce padding to half the image height
            padding_bottom = original_height // 2
            new_image_height = original_height - padding_bottom
            logger.warning(f"[DEBUG] Padding was too large, reduced to {padding_bottom}px")
        
        # Resize the original image to make room for the title
        # Keep the original width (no side padding)
        resized_img = img.resize((original_width, new_image_height), Image.LANCZOS)
        logger.info(f"[DEBUG] Resized image to: {original_width}x{new_image_height}")
        
        # Create a new image with the original dimensions
        new_img = Image.new('RGB', (original_width, original_height), color=padding_color)
        logger.info(f"[DEBUG] Created new image with dimensions: {original_width}x{original_height}")
        
        # Paste the resized original image at the top
        new_img.paste(resized_img, (0, 0))
        
        # Create a drawing context
        draw = ImageDraw.Draw(new_img)
        
        # Calculate starting Y position to center text vertically in the padding area with extra space
        padding_start_y = new_image_height
        y_start = padding_start_y + extra_padding
        logger.info(f"[DEBUG] Text starting Y position: {y_start}")
        
        # Calculate maximum text width to ensure it fits within the image
        max_text_width = 0
        for line in title_lines:
            text_width = draw.textlength(line, font=font)
            max_text_width = max(max_text_width, text_width)
        logger.info(f"[DEBUG] Maximum text width: {max_text_width}px")
        
        # If text is too wide, reduce font size
        if max_text_width > (original_width * 0.9):  # Allow 90% of image width
            scale_factor = (original_width * 0.9) / max_text_width
            new_font_size = int(font_size * scale_factor)
            logger.info(f"[DEBUG] Reduced font size from {font_size} to {new_font_size} to fit text width")
            font = find_thai_font(new_font_size, font_name)
            # Recalculate line spacing with new font size
            line_spacing = int(new_font_size * 0.3)
        
        # Set margins for text alignment
        left_margin = 30  # Left margin for left-aligned text
        right_margin = 30  # Right margin for right-aligned text
        
        # Draw each line of text
        for i, line in enumerate(title_lines):
            # Calculate exact Y position for this line with improved spacing
            y_pos = y_start + (i * (font_size + line_spacing))
            
            # Calculate text position based on alignment
            text_width = draw.textlength(line, font=font)
            if text_align == 'center':
                x_pos = (original_width - text_width) / 2
            elif text_align == 'left':
                x_pos = left_margin
            elif text_align == 'right':
                x_pos = original_width - text_width - right_margin
            else:
                logger.warning(f"[DEBUG] Unknown text alignment: {text_align}. Defaulting to center.")
                x_pos = (original_width - text_width) / 2
            
            logger.info(f"[DEBUG] Drawing line {i+1}: '{line}' at position ({x_pos}, {y_pos})")
            
            # Draw text border if specified
            if border_width > 0:
                for offset_x in range(-border_width, border_width + 1):
                    for offset_y in range(-border_width, border_width + 1):
                        if offset_x != 0 or offset_y != 0:
                            draw.text((x_pos + offset_x, y_pos + offset_y), line, 
                                     font=font, fill=border_color)
            
            # If there are words to highlight, we need to draw each word separately
            if highlight_words and any(word.lower() in line.lower() for word in highlight_words):
                logger.info(f"[DEBUG] Line {i+1} contains words to highlight")
                # Split the line into words while preserving Thai word boundaries
                import re
                # This regex pattern will match Thai words and other words with spaces
                words = re.findall(r'[\u0E00-\u0E7F]+|[^\s]+', line)
                logger.info(f"[DEBUG] Split line into words: {words}")
                
                current_x = x_pos
                for word in words:
                    # Check if this word should be highlighted
                    word_to_draw = word
                    word_color = font_color
                    
                    # Check if this word matches any highlight word (case insensitive)
                    for highlight_word in highlight_words:
                        if highlight_word.lower() in word.lower():
                            word_color = highlight_color
                            logger.info(f"[DEBUG] Highlighting word: '{word}' with color: {highlight_color}")
                            break
                    
                    # Draw the word with appropriate color
                    word_width = draw.textlength(word_to_draw + ' ', font=font)
                    
                    # Draw word border if specified
                    if border_width > 0 and word_color != font_color:
                        for offset_x in range(-border_width, border_width + 1):
                            for offset_y in range(-border_width, border_width + 1):
                                if offset_x != 0 or offset_y != 0:
                                    draw.text((current_x + offset_x, y_pos + offset_y), word_to_draw, 
                                             font=font, fill=border_color)
                    
                    # Draw the word
                    draw.text((current_x, y_pos), word_to_draw, font=font, fill=word_color)
                    
                    # Add space after the word
                    current_x += word_width
            else:
                # Draw the main text normally if no highlighting needed
                draw.text((x_pos, y_pos), line, font=font, fill=font_color)
        
        # Save the output image
        output_image_path = os.path.join(temp_dir, f"output_title_{job_id}.jpg")
        new_img.save(output_image_path, quality=95)
        logger.info(f"[DEBUG] Saved output image to: {output_image_path}")
        
        # Upload using the storage utility (MinIO with GCS fallback)
        output_blob_name = f"{job_id}_titled_image.jpg"
        logger.info(f"[DEBUG] Uploading image using storage utility, blob: {output_blob_name}")
        
        # Upload the file and get the public URL
        success, public_url, storage_used = upload_file(
            output_image_path,
            object_name=output_blob_name,
            content_type="image/jpeg",
            folder="titled-images",
            make_public=True
        )
        
        if not success:
            raise Exception("Failed to upload image to storage")
            
        logger.info(f"[DEBUG] Uploaded to {storage_used} storage with URL: {public_url}")
        
        # Prepare result
        result = {
            "url": public_url,
            "storage_provider": storage_used,
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
            logger.info(f"[DEBUG] Cleaned up temporary files and directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"[DEBUG] Error cleaning up temporary files: {str(e)}")
        
        logger.info(f"[DEBUG] Image processing completed successfully")
        return result
        
    except Exception as e:
        logger.error(f"[DEBUG] Error in process_add_title_to_image: {str(e)}", exc_info=True)
        raise e
