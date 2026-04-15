# 🧠 Model Creator Guide

Welcome to the **SIQE Model Creator** guide. This module allows you to train your own custom Super-Resolution models using the **Residual Dense Block (RDB)** architecture.

---

## 📊 Training Specifications

To achieve the current level of performance, the baseline models were trained with the following specifications:

- **Dataset:** Trained on the **ResNet dataset**, providing a diverse range of high-quality image features.
- **Hardware:** Training was performed on an **NVIDIA GeForce RTX 2060 Mobile GPU**.
- **Epochs:** 100 (with Early Stopping).
- **Batch Size:** 32.
- **Upscale Factor:** 3x.

---

## 🛠️ Prerequisites

Before you begin, ensure you have the following installed (preferably in a virtual environment):

- **Python 3.10+**
- **TensorFlow / Keras**
- **NumPy**
- **Pillow (PIL)**
- **Jupyter Notebook / Lab**

You can install the necessary dependencies using:

```bash
pip install tensorflow keras numpy pillow jupyter
```

---

## 🚀 How to Train Your Model

The entire training pipeline is contained within the `Model Creator.ipynb` notebook. Follow these steps:

### 1. Prepare your Data

Place your training images in a directory named `Data/` within the `Model Creator` folder.

### 2. Pre-processing

The notebook includes functions to:

- **Filter Images:** Automatically removes non-RGB images and low-resolution samples (width < 600 or height < 300).
- **Color Space Conversion:** Converts images to **YUV** and extracts the **Y (Luminance)** channel. This reduces training complexity as the human eye is more sensitive to luminance than chrominance.

### 3. Configure Hyperparameters

In the **Main** section of the notebook, you can adjust:

- `upscale_factor`: Default is set to `3`.
- `epochs_number`: Default is `100`.
- `batch_size`: Default is `32`.

### 4. Run the Notebook

Execute the cells in order. The notebook will:

- Load and scale the dataset.
- Build the RDB-based CNN architecture.
- Train the model using the **MSE (Mean Squared Error)** loss function and **Adam** optimizer.
- Save the final model as `Super_Resolved_Model.keras`.

---

## 🏗️ Architecture Overview

SIQE utilizes a custom CNN architecture centered around **Residual Dense Blocks (RDBs)**.

- **Global Residual Learning:** Helps in passing high-frequency information.
- **Local Dense Connections:** Allows the model to extract more complex features without a massive increase in parameters.
- **Depth-to-Space:** A sub-pixel convolution layer used for efficient upscaling.

---

## 💾 Using the Trained Model

Once the training is complete, the `.keras` file can be moved to the `backend/` directory for deployment via the SIQE API.

> [!TIP]
> Training on a 2060 Mobile GPU typically takes several hours depending on the dataset size. Ensure your hardware has adequate cooling!
