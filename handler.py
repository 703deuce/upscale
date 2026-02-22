"""
RunPod serverless handler for video upscaling with Real-ESRGAN.
Accepts video_url (or file path), runs ffmpeg → Real-ESRGAN (CUDA) → ffmpeg,
returns the upscaled video directly as base64 (no S3).
Uses PyTorch/CUDA Real-ESRGAN (no Vulkan required).
"""
import os
import subprocess
import uuid
import base64

import cv2
from runpod import serverless
from realesrgan import RealESRGANer
from realesrgan.archs.srvgg_arch import SRVGGNetCompact

DEFAULT_MODEL = os.environ.get("REAL_ESRGAN_MODEL", "realesr-animevideov3")
WEIGHTS_DIR = "/workspace/weights"

# 720p -> 1080p = 1.5x, 720p -> 2K (1440p) = 2x
TARGET_RESOLUTION_SCALE = {
    "1080p": 1.5,
    "2k": 2.0,
    "1440p": 2.0,
}
DEFAULT_SCALE = 1.5  # 1080p from 720p
DEFAULT_CRF = 20
DEFAULT_PRESET = "medium"


def run(cmd: list[str], cwd: str | None = None) -> None:
    subprocess.check_call(cmd, cwd=cwd)


def get_video_fps(path: str) -> float:
    """Get frame rate of video (for reassembly). Default 30 if probe fails."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        # e.g. "30/1" or "30000/1001"
        num, den = out.strip().split("/")
        return float(num) / float(den) if den != "0" else 30.0
    except Exception:
        return 30.0


def get_video_size(path: str) -> tuple[int, int] | None:
    """Return (width, height) or None if probe fails."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                path,
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        w, h = out.strip().split(",")
        return int(w), int(h)
    except Exception:
        return None


def resolve_scale(scale: float | None, target_resolution: str | None) -> float:
    """
    Final scale factor: explicit scale wins; else target_resolution preset (1080p=1.5, 2k=2); else default 1.5.
    """
    if scale is not None and scale > 0:
        return float(scale)
    if target_resolution:
        key = (target_resolution or "").strip().lower().replace(" ", "")
        if key in TARGET_RESOLUTION_SCALE:
            return TARGET_RESOLUTION_SCALE[key]
        if key == "2k" or key == "1440p":
            return 2.0
        if key == "1080p":
            return 1.5
    return DEFAULT_SCALE


def upscale_frames_cuda(work_dir: str, scale: float, model_name: str) -> None:
    """Upscale all frames using Real-ESRGAN CUDA (no Vulkan)."""
    model = SRVGGNetCompact(
        num_in_ch=3,
        num_out_ch=3,
        num_feat=64,
        num_conv=16,
        upscale=4,
        act_type="prelu",
    )
    model_path = f"{WEIGHTS_DIR}/{model_name}.pth"
    upsampler = RealESRGANer(
        scale=4,
        model_path=model_path,
        model=model,
        tile=512,
        tile_pad=10,
        pre_pad=0,
        half=True,
    )

    frame_files = sorted(
        f
        for f in os.listdir(work_dir)
        if f.startswith("frame_") and f.endswith(".png")
    )
    for fname in frame_files:
        in_path = os.path.join(work_dir, fname)
        out_name = fname.replace("frame_", "frames_upscaled_")
        out_path = os.path.join(work_dir, out_name)
        img = cv2.imread(in_path, cv2.IMREAD_UNCHANGED)
        output, _ = upsampler.enhance(img, outscale=scale)
        cv2.imwrite(out_path, output)


def upscale_video(
    input_path: str,
    scale: float = DEFAULT_SCALE,
    model: str = DEFAULT_MODEL,
    fps: float | None = None,
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
) -> str:
    job_id = str(uuid.uuid4())
    work_dir = f"/tmp/{job_id}"
    os.makedirs(work_dir, exist_ok=True)

    src = os.path.join(work_dir, "src.mp4")
    frame_pattern = os.path.join(work_dir, "frame_%08d.png")
    upscaled_frame_pattern = os.path.join(work_dir, "frames_upscaled_%08d.png")
    upscaled_video = os.path.join(work_dir, "upscaled_noaudio.mp4")
    final_video = os.path.join(work_dir, "upscaled_with_audio.mp4")

    if os.path.abspath(input_path) != os.path.abspath(src):
        os.rename(input_path, src)

    out_fps = fps if fps is not None and fps > 0 else get_video_fps(src)

    # 1) Extract frames
    run([
        "ffmpeg", "-y", "-i", src,
        "-q:v", "1",
        frame_pattern,
    ])

    # 2) Run Real-ESRGAN on frames (CUDA, no Vulkan)
    upscale_frames_cuda(work_dir, scale=scale, model_name=model)

    # 3) Reassemble upscaled frames (CRF + preset for quality)
    run([
        "ffmpeg", "-y",
        "-framerate", str(out_fps),
        "-i", upscaled_frame_pattern,
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-pix_fmt", "yuv420p",
        upscaled_video,
    ])

    # 4) Copy audio from original
    run([
        "ffmpeg", "-y",
        "-i", upscaled_video,
        "-i", src,
        "-c:v", "copy",
        "-c:a", "copy",
        "-shortest",
        final_video,
    ])

    return final_video


def handler(event: dict) -> dict:
    """
    RunPod job payload – all parameters exposed for 720p → 1080p / 2K:
    {
      "input": {
        "video_url": "https://...",      // or "file_path" if file on worker
        "target_resolution": "1080p",    // "1080p" | "2k" | "1440p" (sets scale: 1.5 or 2)
        "scale": 1.5,                    // optional; overrides target_resolution if set
        "model": "realesr-animevideov3", // Real-ESRGAN model name
        "output_fps": 30,                 // optional; default = source fps
        "crf": 20,                       // x264 quality (18–23 typical, lower = better)
        "preset": "medium"                // x264 preset: ultrafast–veryslow
      }
    }
    """
    job_input = event.get("input") or event
    video_url = job_input.get("video_url")
    file_path = job_input.get("file_path")
    target_resolution = job_input.get("target_resolution")
    scale_raw = job_input.get("scale")
    scale = float(scale_raw) if scale_raw is not None else None
    model = str(job_input.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    output_fps = job_input.get("output_fps")
    output_fps = float(output_fps) if output_fps is not None else None
    crf = int(job_input.get("crf", DEFAULT_CRF))
    preset = str(job_input.get("preset") or DEFAULT_PRESET).strip() or DEFAULT_PRESET

    if not video_url and not file_path:
        return {
            "error": "Provide either 'video_url' or 'file_path' in input.",
            "output_base64": None,
            "output_url": None,
        }

    tmp_path = f"/tmp/input_{uuid.uuid4().hex}.mp4"

    try:
        if video_url:
            run(["curl", "-L", "-s", "-S", video_url, "-o", tmp_path])
            if not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
                return {
                    "error": "Download failed or empty file.",
                    "output_base64": None,
                    "output_url": None,
                }
        else:
            if not os.path.isfile(file_path):
                return {
                    "error": f"File not found: {file_path}",
                    "output_base64": None,
                    "output_url": None,
                }
            tmp_path = file_path

        scale = resolve_scale(scale, target_resolution)
        out_path = upscale_video(
            tmp_path,
            scale=scale,
            model=model,
            fps=output_fps,
            crf=crf,
            preset=preset,
        )

        # Return directly: read file and base64 encode (no S3)
        with open(out_path, "rb") as f:
            data = f.read()
        output_base64 = base64.b64encode(data).decode("utf-8")

        return {
            "output_url": None,
            "output_base64": output_base64,
            "content_type": "video/mp4",
            "filename": "upscaled.mp4",
            "params": {
                "scale": scale,
                "model": model,
                "target_resolution": target_resolution,
                "crf": crf,
                "preset": preset,
                "output_fps": output_fps if output_fps is not None else "source",
            },
        }
    except subprocess.CalledProcessError as e:
        return {
            "error": f"Upscale failed: {e}",
            "output_base64": None,
            "output_url": None,
        }
    finally:
        if video_url and os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


serverless.start({"handler": handler})
