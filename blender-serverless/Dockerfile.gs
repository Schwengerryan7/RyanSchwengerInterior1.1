FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV QT_QPA_PLATFORM=offscreen
ENV DISPLAY=
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV MESA_GL_VERSION_OVERRIDE=3.3

# System deps including Mesa software OpenGL — fixes COLMAP headless crash
RUN apt-get update && apt-get install -y \
    python3.10 python3-pip git wget curl \
    ffmpeg colmap \
    libgl1-mesa-glx libgl1-mesa-dri \
    mesa-utils libgles2-mesa \
    libglib2.0-0 libsm6 libxext6 libxrender-dev \
    build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --upgrade pip

# PyTorch CUDA 11.8
RUN pip3 install torch==2.0.1+cu118 torchvision==0.15.2+cu118 \
    --index-url https://download.pytorch.org/whl/cu118

# Nerfstudio
RUN pip3 install nerfstudio

# RunPod
RUN pip3 install runpod numpy Pillow requests

COPY handler_gs.py /handler.py

CMD ["python3", "-u", "/handler.py"]# v13 mesa software opengl
