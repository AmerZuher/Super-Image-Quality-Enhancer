from fastapi import HTTPException
from PIL import Image, ImageEnhance
import os
import cv2
import numpy as np
from utils.database import get_db_connection
from psycopg2.extras import RealDictCursor

from utils.preprocess import preprocess_image
from utils.load_model import load_model
from utils.postprocess import post_process


async def enhance_image_func(image_id: int):
    # Get the original image path from database
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute(
        "SELECT original_path FROM images WHERE id = %s",
        (image_id,)
    )
    
    result = cursor.fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="Image not found")
    
    original_path = result["original_path"]
    model = load_model() 

    
    # Create enhanced version
    try:

        # Load image using OpenCV
        img =  Image.open(original_path)

        
        # Preprocess the image
        # Convert to YCbCr and split into channels
        # luminance, cb, cr = preprocess_image(image_rgb) # Fixed variable name
        luminance, cb, cr = preprocess_image(img) # Fixed variable name

        # Use the pre-loaded model to enhance image resolution
        extracted_luminance = model.predict(luminance)[0] # Use the 'model' argument

        # Convert the luminance back to RGB and addint filters
        enhanced_img = await post_process(extracted_luminance, cb, cr, original_path)
        # Save enhanced image
        filename = os.path.basename(original_path)
        enhanced_filename = filename.replace("original_", "enhanced_")
        enhanced_path = os.path.join("images", enhanced_filename)
        enhanced_img.save(enhanced_path)
        
        # Update database with enhanced image path
        cursor.execute(
            "UPDATE images SET enhanced_path = %s WHERE id = %s RETURNING id, original_path, enhanced_path",
            (enhanced_path, image_id)
        )
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        return {
            "id": result["id"],
            "original_path": result["original_path"],
            "original_url": f"/images/{os.path.basename(result['original_path'])}",
            "enhanced_path": result["enhanced_path"],
            "enhanced_url": f"/images/{enhanced_filename}"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error enhancing image: {str(e)}")
