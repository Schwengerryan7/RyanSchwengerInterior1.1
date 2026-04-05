                                                                                                                                    
  FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04
                                                                                                                                      
  ENV DEBIAN_FRONTEND=noninteractive
                                                                                                                                      
  RUN apt-get update && apt-get install -y \
      python3 python3-pip wget xz-utils \
      libgl1 libglib2.0-0 libgomp1 libxi6 libxrender1 libxxf86vm1 libxkbcommon0 \                                                                   
      && rm -rf /var/lib/apt/lists/*                                                                                                  
                                                                                                                                      
  RUN wget https://download.blender.org/release/Blender3.6/blender-3.6.8-linux-x64.tar.xz -O /tmp/blender.tar.xz && \                 
      tar -xf /tmp/blender.tar.xz -C /opt/ && \
      mv /opt/blender-3.6.8-linux-x64 /opt/blender && \                                                                               
      ln -s /opt/blender/blender /usr/local/bin/blender && \
      rm /tmp/blender.tar.xz                                                                                                          
                  
  RUN pip3 install runpod==1.7.3 numpy open3d                                                                                         
                  
  COPY handler.py /handler.py                                                                                                         
   
  CMD ["python3", "-u", "/handler.py"]