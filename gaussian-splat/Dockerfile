FROM nvidia/cuda:12.1.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 python3-pip git wget \
    libgl1 libglib2.0-0 libgomp1 \
    colmap \
    && rm -rf /var/lib/apt/lists/*

# torch first so gsplat CUDA extension compiles against the right version
RUN pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu121

RUN pip3 install runpod pillow numpy plyfile

COPY handler_scan.py /handler_scan.py
CMD ["python3", "-u", "/handler_scan.py"]
