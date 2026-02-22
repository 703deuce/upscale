# RunPod serverless: video upscaler (Real-ESRGAN ncnn-vulkan + ffmpeg)
# GPU: Vulkan-capable (e.g. T4, L4). Use /workspace for binary and models.
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV WORKDIR_PATH=/workspace

# Ubuntu 22.04: use default python3 (3.10); python3.11 not in default repos
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    curl \
    wget \
    unzip \
    libvulkan1 \
    && rm -rf /var/lib/apt/lists/*

# Real-ESRGAN ncnn-vulkan: Linux build from Real-ESRGAN releases
# https://github.com/xinntao/Real-ESRGAN/releases (includes ncnn-vulkan build + models)
RUN mkdir -p ${WORKDIR_PATH} && cd ${WORKDIR_PATH} \
    && wget -q "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip" -O realesrgan.zip \
    && unzip -o realesrgan.zip \
    && (mv realesrgan-ncnn-vulkan-20220424-ubuntu/* . 2>/dev/null || true) \
    && (mv realesrgan-ncnn-vulkan-20220424-ubuntu/ubuntu/* . 2>/dev/null || true) \
    && rm -rf realesrgan.zip realesrgan-ncnn-vulkan-20220424-ubuntu \
    && chmod +x realesrgan-ncnn-vulkan \
    && ln -sf ${WORKDIR_PATH}/realesrgan-ncnn-vulkan /usr/local/bin/realesrgan-ncnn-vulkan || true

WORKDIR /app
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt
COPY handler.py .

ENV REAL_ESRGAN_BIN=${WORKDIR_PATH}/realesrgan-ncnn-vulkan
ENV REAL_ESRGAN_MODEL=realesr-animevideov3

CMD ["python3", "-u", "/app/handler.py"]
