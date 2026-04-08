FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies for Blender headless + Open3D
RUN apt-get update && apt-get install -y \
    python3 python3-pip wget xz-utils \
    libgl1 libglib2.0-0 libgomp1 \
    libxi6 libxrender1 libxkbcommon0 \
    libsm6 libice6 libx11-6 libxext6 \
    libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*

# Install Blender 4.2 LTS (headless, stable)
RUN wget -q https://download.blender.org/release/Blender4.2/blender-4.2.0-linux-x64.tar.xz \
    && tar -xf blender-4.2.0-linux-x64.tar.xz \
    && mv blender-4.2.0-linux-x64 /opt/blender \
    && rm blender-4.2.0-linux-x64.tar.xz

ENV PATH="/opt/blender:$PATH"
ENV BLENDER_PATH="/opt/blender/blender"

# Python dependencies
RUN pip3 install --no-cache-dir \
    runpod \
    open3d \
    numpy

WORKDIR /app
COPY handler.py .

CMD ["python3", "handler.py"]
