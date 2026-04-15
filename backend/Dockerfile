# Use an official NVIDIA CUDA runtime image as the base.
# This image comes with CUDA toolkit and cuDNN pre-installed.
# We will install Python, pip, and PostgreSQL client libraries on top of this.
FROM nvidia/cuda:11.2.2-cudnn8-runtime-ubuntu20.04

# Set the working directory in the container
WORKDIR /app

# Install Python, pip, and PostgreSQL client libraries using apt-get
# We need Python and pip to install the dependencies from requirements.txt
# libpq-dev is required to build psycopg2 from source
RUN apt-get update && \
    apt-get install -y python3 python3-pip libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy the requirements.txt file from the build context (backend directory)
# Since the Dockerfile is in 'backend' and requirements.txt is also in 'backend',
# this path is relative to the build context root ('.')
COPY requirements.txt .

# Install pip dependencies
# This installs the packages listed in your requirements.txt file.
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy your application code from the 'app' directory in the build context
# Since the 'app' directory is in 'backend' and the Dockerfile is in 'backend',
# this path is relative to the build context root ('.')
COPY app /app

# Expose the port for FastAPI app
EXPOSE 8000

# Command to run the FastAPI application
# This now correctly points to the 'main' module inside the '/app' directory
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
