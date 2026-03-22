FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y \
    wget xz-utils libxrender1 libxxf86vm1 \
    libxfixes3 libxi6 libxkbcommon0 libsm6 \
    python3 python3-pip curl && \
    rm -rf /var/lib/apt/lists/*

# Install Blender
RUN wget -q https://download.blender.org/release/Blender3.6/blender-3.6.5-linux-x64.tar.xz && \
    tar -xf blender-3.6.5-linux-x64.tar.xz && \
    mv blender-3.6.5-linux-x64 /opt/blender && \
    ln -s /opt/blender/blender /usr/local/bin/blender && \
    rm blender-3.6.5-linux-x64.tar.xz

# Install RunPod
RUN pip3 install runpod

COPY handler.py /handler.py

CMD ["python3", "-u", "/handler.py"]
