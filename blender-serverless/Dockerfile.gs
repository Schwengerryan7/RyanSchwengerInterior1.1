FROM dromni/nerfstudio:latest

ENV QT_QPA_PLATFORM=offscreen

RUN pip install runpod

COPY handler_gs.py /handler.py

CMD ["python3", "-u", "/handler.py"]
