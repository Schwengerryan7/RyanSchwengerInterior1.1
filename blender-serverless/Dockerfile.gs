FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV QT_QPA_PLATFORM=offscreen
ENV DISPLAY=
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV MESA_GL_VERSION_OVERRIDE=3.3

RUN apt-get update && apt-get install -y \
    python3.10 python3-pip git wget curl \
    ffmpeg colmap \
    libgl1-mesa-glx libgl1-mesa-dri mesa-utils \
    libglib2.0-0 libsm6 libxext6 \
    build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --upgrade pip

# Install PyTorch first separately
RUN pip3 install torch==2.0.1+cu118 torchvision==0.15.2+cu118 \
    --index-url https://download.pytorch.org/whl/cu118

# Install nerfstudio dependencies manually to avoid conflicts
RUN pip3 install ninja numpy Pillow tqdm rich tyro

# Install nerfstudio without deps to avoid version conflicts
RUN pip3 install nerfstudio --no-deps

# Install remaining nerfstudio deps
RUN pip3 install runpod requests opencv-python-headless

COPY handler_gs.py /handler.py

CMD ["python3", "-u", "/handler.py"]
