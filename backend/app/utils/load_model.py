import tensorflow as tf
import os

# load the selected TensorFlow model
def load_model():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(BASE_DIR, 'models', 'v10.h5')
    return tf.keras.models.load_model(model_path)