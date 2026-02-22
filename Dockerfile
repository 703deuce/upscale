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

# Install into the same Python that runs at runtime (RunPod gotcha: pip vs python3.10 -m pip)
# NumPy must be 1.x for PyTorch 2.1 (numpy 2.x breaks torch.from_numpy)
RUN python3.10 -m pip install --upgrade pip && \
    python3.10 -m pip install \
        "numpy<2" \
        pillow \
        pyyaml \
        opencv-python-headless \
        realesrgan \
        basicsr \
        facexlib \
        gfpgan \
        runpod \
        requests

# Download model weights at build time so workers don't download on every job
RUN mkdir -p /workspace/weights && \
    wget -q https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth \
    -O /workspace/weights/realesr-animevideov3.pth

COPY handler.py /handler.py

CMD ["python3.10", "-u", "/handler.py"]
