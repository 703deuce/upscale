# RunPod Serverless Video Upscaler

Upscale short videos (e.g. ≤15s) using **Real-ESRGAN ncnn-vulkan** and **ffmpeg**. Designed for RunPod serverless: receive a video URL, run frame extraction → upscale → reassembly with audio, and **return the upscaled video directly** as base64 (no S3).

## Flow

1. **Request** — JSON with `video_url` (or `file_path` if the file is already on the worker).
2. **Download** — Input saved to `/tmp`.
3. **Process** — `ffmpeg` (extract frames) → Real-ESRGAN (upscale frames) → `ffmpeg` (reassemble + copy audio).
4. **Response** — Upscaled video returned as **base64** in the JSON (no upload to S3).

## Request payload

All parameters are exposed so you can target **720p → 1080p** (or 2K) and tune quality.

**Example: 720p → 1080p (default)**

```json
{
  "input": {
    "video_url": "https://your-bucket/sora-720p.mp4",
    "target_resolution": "1080p"
  }
}
```

**Example: 720p → 2K with custom encoding**

```json
{
  "input": {
    "video_url": "https://your-bucket/sora-720p.mp4",
    "target_resolution": "2k",
    "model": "realesr-animevideov3",
    "crf": 18,
    "preset": "slow"
  }
}
```

| Field                | Required | Description |
|----------------------|----------|-------------|
| `video_url`           | Yes*     | Public URL of the source video (e.g. 720p MP4). |
| `file_path`           | Yes*     | Alternative: path to file already on the worker. |
| `target_resolution`   | No       | **`"1080p"`** (1.5×) or **`"2k"`** / **`"1440p"`** (2×). Default behavior = 1080p. |
| `scale`               | No       | Raw scale factor (e.g. `1.5`, `2`). Overrides `target_resolution` if set. |
| `model`               | No       | Real-ESRGAN model (default `realesr-animevideov3`). |
| `output_fps`          | No       | Output frame rate; default = source video fps. |
| `crf`                 | No       | x264 quality, 18–23 typical (default `20`; lower = better quality, larger file). |
| `preset`              | No       | x264 preset: `ultrafast` … `veryslow` (default `medium`). |

*Provide either `video_url` or `file_path`.*

## Response (success)

```json
{
  "output_url": null,
  "output_base64": "<base64-encoded upscaled MP4>",
  "content_type": "video/mp4",
  "filename": "upscaled.mp4"
}
```

Decode on the client:

```js
const b64 = response.output_base64;
const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
const blob = new Blob([bytes], { type: "video/mp4" });
const url = URL.createObjectURL(blob);
```

## Response (error)

```json
{
  "error": "Download failed or empty file.",
  "output_base64": null,
  "output_url": null
}
```

## Deploy on RunPod

1. **Build and push the image**

   ```bash
   docker build -t your-registry/runpod-video-upscaler:latest .
   docker push your-registry/runpod-video-upscaler:latest
   ```

2. **Create a Serverless Endpoint**

   - **Image:** `your-registry/runpod-video-upscaler:latest`
   - **GPU:** e.g. T4 or L4 (4–8 GB VRAM is enough for Real-ESRGAN ncnn-vulkan).
   - **Container disk:** 20 GB+ (for `/tmp` frames and output).
   - **Timeout:** Set to something reasonable for your max video length (e.g. 300–600 s for short clips).
   - **Handler:** The container runs `python -u /app/handler.py`; RunPod uses the `handler` function automatically.

3. **Call the endpoint**

   ```bash
   curl -X POST https://api.runpod.ai/v2/<endpoint-id>/runsync \
     -H "Authorization: Bearer <api-key>" \
     -H "Content-Type: application/json" \
     -d '{"input": {"video_url": "https://example.com/video.mp4", "target_resolution": "1080p"}}'
   ```

## Environment variables (optional)

| Variable             | Default                          | Description                    |
|----------------------|----------------------------------|--------------------------------|
| `REAL_ESRGAN_BIN`    | `/workspace/realesrgan-ncnn-vulkan` | Path to the Real-ESRGAN binary. |
| `REAL_ESRGAN_MODEL`  | `realesr-animevideov3`           | Model name for upscaling.      |

## Local test (no RunPod)

```bash
pip install runpod
python handler.py --test_input '{"input": {"video_url": "https://example.com/short-clip.mp4"}}'
```

Note: Local run needs `ffmpeg`, `curl`, and Real-ESRGAN ncnn-vulkan on your machine; for real testing, use the Docker image.

## Notes

- **Working dir:** All temp files use `/tmp`; each job uses a unique subdir and is cleaned up.
- **Length:** Aim for short videos (e.g. ≤15 s) so runs stay within timeout and response size limits.
- **Response size:** Returning base64 increases size by ~33%. For very long videos, consider switching to S3/object storage and returning a URL instead.
