FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 python3-pip wget xz-utils \
    blender \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install runpod

# Install numpy inside Blender's bundled Python
RUN blender --background --python-expr "import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'numpy'])"

COPY handler.py /handler.py

CMD ["python3", "-u", "/handler.py"]
