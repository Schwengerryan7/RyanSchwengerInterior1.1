FROM nvidia/cuda:12.1.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 python3-pip git wget \
    libgl1 libglib2.0-0 libgomp1 \
    colmap \
    && rm -rf /var/lib/apt/lists/*

# torch first so everything compiles against the right CUDA version
RUN pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu121

RUN pip3 install runpod pillow numpy transformers accelerate

# Pre-bake DepthAnything v2 Small weights (~100MB)
RUN python3 -c "\
from transformers import AutoImageProcessor, AutoModelForDepthEstimation; \
AutoImageProcessor.from_pretrained('depth-anything/Depth-Anything-V2-Small-hf'); \
AutoModelForDepthEstimation.from_pretrained('depth-anything/Depth-Anything-V2-Small-hf')"

# Pre-bake Grounding DINO tiny weights (~172MB)
RUN python3 -c "\
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection; \
AutoProcessor.from_pretrained('IDEA-Research/grounding-dino-tiny'); \
AutoModelForZeroShotObjectDetection.from_pretrained('IDEA-Research/grounding-dino-tiny')"

COPY handler_scan.py /handler_scan.py
CMD ["python3", "-u", "/handler_scan.py"]
