FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# — System dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-dev \
    git wget curl \
    ffmpeg \
    colmap \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 libxext6 libxrender-dev \
    build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

# — Python deps
RUN pip3 install --upgrade pip

# — PyTorch with CUDA 11.8
RUN pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# — Nerfstudio + gsplat
RUN pip3 install nerfstudio

# — RunPod handler deps
RUN pip3 install runpod requests numpy Pillow

# — Copy handler
COPY handler.py /handler.py

CMD ["python3", "-u", "/handler.py"]# gs container
