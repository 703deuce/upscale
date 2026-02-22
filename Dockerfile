# RunPod serverless: video upscaler (Real-ESRGAN Python/CUDA + ffmpeg)
# GPU: CUDA (e.g. RTX A4000, T4, L4). No Vulkan required.
FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel

ENV DEBIAN_FRONTEND=noninteractive

# ffmpeg for frame extraction/reassembly, curl for downloading input
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# NumPy must be 1.x for PyTorch 2.1 (numpy 2.x breaks torch.from_numpy)
RUN pip install "numpy<2" pillow pyyaml opencv-python-headless
RUN pip install realesrgan basicsr facexlib gfpgan
RUN pip install runpod requests

# Download model weights (anime video v3)
RUN mkdir -p /workspace/weights && \
    wget -q https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth \
    -O /workspace/weights/realesr-animevideov3.pth

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY handler.py .

CMD ["python3", "-u", "/app/handler.py"]
