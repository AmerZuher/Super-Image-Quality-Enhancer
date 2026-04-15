from fastapi import HTTPException # Keep imports from original snippet
from PIL import Image, ImageEnhance # Keep imports from original snippet
import os # Keep imports from original snippet
import cv2 # Keep imports from original snippet
import numpy as np # Keep imports from original snippet
from psycopg2.extras import RealDictCursor # Keep imports from original snippet
from typing import Tuple # Add type hinting for clarity

# Keep the existing return_to_rgb function as it seems correct
def return_to_rgb(new_luminance: np.ndarray, cb: Image.Image, cr: Image.Image) -> Image.Image:
    """
    Converts YCbCr components (with new luminance) back to an RGB PIL Image.

    Args:
        new_luminance: A NumPy array representing the new luminance channel (Y).
        cb: A PIL Image representing the Cb channel.
        cr: A PIL Image representing the Cr channel.

    Returns:
        A PIL Image in RGB format.
    """
    # Ensure luminance is in the 0-255 range and correct shape
    new_luminance *= 255.0
    new_luminance = new_luminance.clip(0, 255)
    new_luminance = new_luminance.reshape((new_luminance.shape[0], new_luminance.shape[1]))

    new_luminance_image = Image.fromarray(np.uint8(new_luminance), 'L') # Specify 'L' mode for single channel

    # Resize Cb and Cr to match the new luminance size
    cb_resized = cb.resize(new_luminance_image.size, Image.BICUBIC)
    cr_resized = cr.resize(new_luminance_image.size, Image.BICUBIC)

    # Merge the channels in YCbCr format
    super_res_image_ycbcr = Image.merge("YCbCr",(new_luminance_image, cb_resized, cr_resized))

    # Convert YCbCr to RGB
    return super_res_image_ycbcr.convert("RGB")

# Keep the existing gray_world_white_balance function if it's needed elsewhere
def gray_world_white_balance(img_bgr: np.ndarray) -> np.ndarray:
    """
    Applies Gray World white balancing to a BGR OpenCV image.

    Args:
        img_bgr: Input image as a NumPy array in BGR format.

    Returns:
        Image as a NumPy array in RGB format after white balancing.
    """
    image_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    result = image_rgb.copy().astype(np.float32)
    avg_b = np.mean(result[:, :, 0])
    avg_g = np.mean(result[:, :, 1])
    avg_r = np.mean(result[:, :, 2])
    avg_gray = (avg_b + avg_g + avg_r) / 3

    result[:, :, 0] *= avg_gray / avg_b
    result[:, :, 1] *= avg_gray / avg_g
    result[:, :, 2] *= avg_gray / avg_r
    result = np.clip(result, 0, 255).astype(np.uint8)
    return result # This returns RGB, not BGR

# --- NEW / MODIFIED FILTER FUNCTION ---
def apply_filters(img_pil: Image.Image) -> Image.Image:
    """
    Applies Apple-style subtle enhancements and a vignette effect to a PIL Image.

    This function operates directly on the provided PIL Image object.

    Args:
        img_pil: The input image as a PIL Image object (expected to be in RGB mode).

    Returns:
        The processed image as a PIL Image object.
    """
    # Ensure image is in RGB mode for consistent processing
    if img_pil.mode != 'RGB':
        img_pil = img_pil.convert('RGB')

    # Apply Apple-style subtle boosts using PIL ImageEnhance
    img_enhanced = ImageEnhance.Color(img_pil).enhance(1.2)
    img_enhanced = ImageEnhance.Contrast(img_enhanced).enhance(1.15)
    img_enhanced = ImageEnhance.Sharpness(img_enhanced).enhance(1.1)
    img_enhanced = ImageEnhance.Brightness(img_enhanced).enhance(1.05)

    # --- Apply Vignette effect ---
    # Convert PIL image to NumPy array for OpenCV/NumPy operations
    image_np = np.array(img_enhanced)

    rows, cols = image_np.shape[:2]

    # Create 2D Gaussian kernel for vignette effect
    # Kernels are slightly wider/taller than the image to ensure the center is brightest
    kernel_x = cv2.getGaussianKernel(cols, cols / 2)
    kernel_y = cv2.getGaussianKernel(rows, rows / 2)
    kernel = kernel_y @ kernel_x.T # Outer product to get a 2D kernel

    # Normalize the kernel to the range [0, 1]
    mask = kernel / kernel.max()

    # Apply the mask to each color channel
    vignette_np = np.copy(image_np).astype(np.float32) # Use float for multiplication
    for i in range(3): # Apply to R, G, B channels
        vignette_np[:, :, i] *= mask

    # Clip values to 0-255 and convert back to uint8
    vignette_np = np.clip(vignette_np, 0, 255).astype(np.uint8)

    # Convert the result back to a PIL Image
    return Image.fromarray(vignette_np)

# --- MODIFIED POST-PROCESS FUNCTION ---
async def post_process(new_luminance: np.ndarray, cb: Image.Image, cr: Image.Image, original_path: str) -> Image.Image:
    """
    Performs post-processing steps including YCbCr to RGB conversion and applying filters.

    Args:
        new_luminance: NumPy array with the new luminance channel.
        cb: PIL Image with the Cb channel.
        cr: PIL Image with the Cr channel.
        original_path: Path to the original image (included for signature consistency,
                       but not used within this function's core logic after YCbCr merge).

    Returns:
        The final processed PIL Image object.
    """
    # 1. Convert YCbCr components (with the new luminance) back to an RGB image
    # This function returns a PIL Image
    image_rgb = return_to_rgb(new_luminance, cb, cr)

    # 2. Apply filters to the resulting RGB PIL image
    # We use the new apply_filters function that works on a PIL Image object
    final_image = apply_filters(image_rgb)

    # 3. Return the final processed image
    return final_image
