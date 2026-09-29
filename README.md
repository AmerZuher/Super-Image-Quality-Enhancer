<p align="center">
  <img src="SIQE_poster.png" alt="Super Image Quality Enhancer (SIQE) poster" width="100%" />
</p>

<div align="center">
  <h1>Super Image Quality Enhancer (SIQE)</h1>
  <h3>Unleashing AI for Superior Image Quality</h3>

  <p>
    <img src="https://img.shields.io/badge/TensorFlow-FF6F00?logo=tensorflow&logoColor=white" alt="TensorFlow" />
    <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
    <img src="https://img.shields.io/badge/Next.js-000000?logo=nextdotjs&logoColor=white" alt="Next.js" />
    <img src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white" alt="Docker" />
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License" />
  </p>

  <p>
    <a href="#-project-demonstration">Demo</a> ·
    <a href="#-overview">Overview</a> ·
    <a href="#-key-features">Features</a> ·
    <a href="#-technology-stack">Tech Stack</a> ·
    <a href="#-repository-structure">Structure</a> ·
    <a href="#-quick-start">Quick Start</a> ·
    <a href="#-gallery">Gallery</a> ·
    <a href="#-authors">Authors</a> ·
    <a href="#-license">License</a>
  </p>
</div>

---

## 📽️ Project Demonstration

<div align="center">
  <video src="https://github.com/user-attachments/assets/def9dedf-4777-484c-a1ba-ac450eaa3a40" width="100%" controls autoplay muted loop>
  </video>
</div>

---

## 🌟 Overview

**Super Image Quality Enhancer (SIQE)** is an advanced deep learning platform designed to breathe new life into low-resolution images. By leveraging **Residual Dense Blocks (RDBs)** and focusing on the **luminance (Y) component** of the YUV color space, SIQE achieves state-of-the-art upscaling while maintaining high computational efficiency.

Developed as a full-stack solution, SIQE provides a seamless journey from training custom models to deploying them in a modern, interactive web environment.

> [!NOTE]
> For a deep dive into the underlying research, read our paper: [Resolution Revolution: Unleashing AI for Superior Image Quality](resources/Resolution%20Revolution%20Unleashing%20AI%20for%20Superior%20Image%20Quality.pdf).

---

## 🎨 Key Features

### 💎 Intelligent Upscaling

Transform pixelated, low-quality images into crisp, high-definition visuals using our specialized AI models.

<div align="center">
  <img src="Gallery/EnhancedSample1.png" alt="Enhanced Sample" width="80%" />
</div>

### ⚖️ Real-time Comparison

Our interactive UI allows you to compare original and enhanced images side-by-side using an intuitive slider/toggle system.

<div align="center">
  <img src="Gallery/MainUi.png" alt="Main UI" width="80%" />
</div>

### 🛠️ [Model Creator](ModelCreator/README.md)

Don't just use our models—create your own! Adjust hyperparameters, specify datasets, and train custom RDB architectures tailored to your specific needs. See our [detailed guide](ModelCreator/README.md) for more info.

### ⚡ GPU Accelerated

Optimized for performance with Docker containers that support GPU passthrough, ensuring rapid inference and training.

---

## 🛠️ Technology Stack


| Component        | Technology                                              |
| :--------------- | :------------------------------------------------------ |
| **Deep Learning**| TensorFlow, Keras, Residual Dense Blocks (RDB)          |
| **Backend**      | FastAPI (Python), OpenCV, NumPy, Pillow                 |
| **Frontend**     | Next.js, React, TypeScript                              |
| **Infrastructure** | Docker, Docker Compose, PostgreSQL                   |

### Architecture Detail

The model utilizes **Residual Dense Blocks**, which allow for deeper networks without the vanishing gradient problem. By focusing on the **Y (Luminance) channel**, we capture the majority of structural details while significantly reducing the training power required compared to RGB-based models.

---

## 🗂️ Repository Structure

```text
Super-Image-Quality-Enhancer/
├── backend/          # FastAPI service, model loading and enhancement pipeline
├── frontend/         # Next.js web application
├── ModelCreator/     # Notebook and guide for training custom RDB models
├── Gallery/          # Logo, poster and screenshots
├── resources/        # Research paper, architecture diagram, demo video, test images
├── docker-compose.yml
├── SIQE_poster.png
├── LICENSE
└── README.md
```

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- NVIDIA Drivers (for GPU support)

### Installation

1.  Clone the repository:

    ```bash
    git clone https://github.com/AmerZuher/Super-Image-Quality-Enhancer.git
    cd Super-Image-Quality-Enhancer
    ```

2.  Start the services:

    ```bash
    docker compose up --build
    ```

3.  Access the application:

    - **Frontend**: `http://localhost:3000`
    -  **Backend API**: `http://localhost:8000/docs`

---

## 📸 Gallery

<div align="center">
  <img src="Gallery/Sample2.png" alt="Sample 2" width="45%" />
  <img src="Gallery/Sample3.png" alt="Sample 3" width="45%" />
  <br />
  <img src="Gallery/Sample4.png" alt="Sample 4" width="90%" />
</div>

---

## 👥 Authors

- **Amer Zuher ALriahy** - [GitHub](https://github.com/AmerZuher)
- **Hisham Maher Sunjaq** - [GitHub](https://github.com/HishamSunjeq)

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">
  <p>Thank you for your interest in SIQE! 🚀</p>
  <p>If you find this project useful, please consider giving it a ⭐!</p>
</div>
