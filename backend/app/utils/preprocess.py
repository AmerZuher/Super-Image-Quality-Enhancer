from PIL import Image
import tensorflow as tf

def preprocess_image(image):
    ycbcr = image.convert("YCbCr")
    luminance, cb, cr = ycbcr.split()

    luminance = tf.keras.preprocessing.image.img_to_array(luminance)
    luminance = luminance.astype("float32") / 255.0
    input_luminance = luminance.reshape(1, luminance.shape[0], luminance.shape[1], 1)

    return input_luminance, cb, cr