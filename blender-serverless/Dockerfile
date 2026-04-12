
  FROM ubuntu:22.04

  ENV DEBIAN_FRONTEND=noninteractive

  RUN apt-get update && apt-get install -y \
      python3 python3-pip wget xz-utils \
      blender \
      libgl1 libglib2.0-0 libgomp1 \
      && rm -rf /var/lib/apt/lists/*

  RUN pip3 install runpod numpy open3d anthropic                                                                                      
   
  COPY handler.py /handler.py                                                                                                         
                  
  CMD ["python3", "-u", "/handler.py"]     