"""
Test script for RunPod serverless video upscaler endpoint.
Upload your test.mp4 somewhere to get a public URL, or set VIDEO_URL below.
Output is saved next to this script as upscaled_output.mp4.

Requires: pip install -r requirements-test.txt  (or pip install requests)
"""
import os
import sys
import time
import base64
import requests

# --- Configure these ---
# Use ?wait=300000 so RunPod holds the connection up to 5 min (default is 90s and often returns IN_PROGRESS early)
RUNPOD_ENDPOINT = "https://api.runpod.ai/v2/uzhuiwcgootp0m/runsync?wait=300000"
RUNPOD_API_KEY = "rpa_5B3UJFTJCQW65L0IZPHBOUC41742AESP9B378LSQrf9q5a"
# Base URL for status polling (same endpoint id, no /runsync)
RUNPOD_STATUS_BASE = "https://api.runpod.ai/v2/uzhuiwcgootp0m"

# Public URL of the video to upscale (e.g. upload test.mp4 to a bucket or file host)
VIDEO_URL = os.environ.get("VIDEO_URL", "")
# Where to save the upscaled video (default: same folder as this script)
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "")
if not OUTPUT_PATH:
    OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upscaled_output.mp4")


# Use this to quickly verify the endpoint (short public sample video)
SAMPLE_VIDEO_URL = "https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4"


def upload_for_url(local_path: str) -> str:
    """Upload a local file to transfer.sh and return the public URL (RunPod can then download it)."""
    path = os.path.abspath(local_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")
    name = os.path.basename(path)
    print(f"Uploading {path} to transfer.sh ...")
    with open(path, "rb") as f:
        r = requests.put(
            f"https://transfer.sh/{name}",
            data=f,
            headers={"Content-Type": "application/octet-stream"},
            timeout=300,
        )
    r.raise_for_status()
    url = r.text.strip()
    print(f"Uploaded. Public URL: {url}")
    return url


def poll_until_done(job_id: str, status_base: str, headers: dict, poll_interval: int = 5, timeout: int = 600):
    """Poll GET status/{job_id} until COMPLETED, FAILED, or timeout. Returns final response dict."""
    url = f"{status_base.rstrip('/')}/status/{job_id}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        status = data.get("status", "")
        if status == "COMPLETED":
            return data
        if status in ("FAILED", "TIMED_OUT", "CANCELLED"):
            return data
        time.sleep(poll_interval)
    raise TimeoutError(f"Job {job_id} still not complete after {timeout}s")


def run_test(video_url_or_path: str, target_resolution: str = "1080p", timeout: int = 600) -> None:
    video_url_or_path = video_url_or_path.strip()
    if not video_url_or_path:
        print("ERROR: Pass a local file (e.g. test.mp4) or a public video URL.")
        print("Example: python test_endpoint.py test.mp4")
        print("         python test_endpoint.py https://your-bucket.s3.amazonaws.com/video.mp4")
        sys.exit(1)

    # If it's a local file path, upload to transfer.sh so RunPod can download it
    video_url = video_url_or_path
    if "://" not in video_url_or_path:
        local_path = os.path.abspath(video_url_or_path)
        if not os.path.isfile(local_path):
            print(f"ERROR: File not found: {local_path}")
            sys.exit(1)
        try:
            video_url = upload_for_url(local_path)
        except requests.exceptions.RequestException as e:
            print(f"ERROR: Upload failed: {e}")
            sys.exit(1)

    # Reject placeholder URLs
    if "your-url" in video_url or "example.com" in video_url:
        print("ERROR: That URL is a placeholder. Use a local path (e.g. test.mp4) or a real URL.")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": {
            "video_url": video_url,
            "target_resolution": target_resolution,
        },
    }

    print(f"Calling endpoint: {RUNPOD_ENDPOINT}")
    print(f"Video URL: {video_url[:60]}...")
    print(f"Target: {target_resolution}. Waiting up to {timeout}s...")
    print()

    try:
        r = requests.post(RUNPOD_ENDPOINT, json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.Timeout:
        print("ERROR: Request timed out. Try increasing timeout or use a shorter video.")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Request failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            try:
                print(e.response.json())
            except Exception:
                print(e.response.text[:500])
        sys.exit(1)

    status = data.get("status", "")
    # If runsync returned early (IN_PROGRESS/IN_QUEUE), poll status until done
    if status in ("IN_PROGRESS", "IN_QUEUE") and data.get("id"):
        job_id = data["id"]
        print(f"Job still running (status={status}). Polling /status/{job_id} until complete...")
        try:
            data = poll_until_done(job_id, RUNPOD_STATUS_BASE, headers, poll_interval=5, timeout=timeout)
            status = data.get("status", "")
        except TimeoutError as e:
            print(f"ERROR: {e}")
            sys.exit(1)

    output = data.get("output") or {}

    if status != "COMPLETED" or not output:
        print(f"Job status: {status}")
        if data.get("error"):
            print(f"Error: {data['error']}")
        elif output.get("error"):
            print(f"Error: {output['error']}")
        else:
            print("Response:", data)
        # Curl exit 6 = couldn't resolve host → URL was invalid or unreachable
        if "exit status 6" in str(data.get("error", "")):
            print("\nTip: The worker ran; the video URL was unreachable (wrong host or not public).")
        sys.exit(1)

    if output.get("error"):
        print(f"ERROR: {output['error']}")
        sys.exit(1)

    b64 = output.get("output_base64")
    if not b64:
        print("ERROR: No output_base64 in response.")
        print("Output keys:", list(output.keys()))
        sys.exit(1)

    os.makedirs(os.path.dirname(OUTPUT_PATH) or ".", exist_ok=True)
    with open(OUTPUT_PATH, "wb") as f:
        f.write(base64.b64decode(b64))

    print(f"Saved upscaled video to: {os.path.abspath(OUTPUT_PATH)}")
    if output.get("params"):
        print("Params used:", output["params"])


if __name__ == "__main__":
    # Default to test.mp4 in the same folder as this script if no arg
    default_input = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test.mp4")
    if len(sys.argv) > 1 and sys.argv[1].strip() in ("--sample", "-s"):
        video_input = SAMPLE_VIDEO_URL
        target = sys.argv[2].strip() if len(sys.argv) > 2 else "1080p"
    else:
        video_input = sys.argv[1].strip() if len(sys.argv) > 1 else (VIDEO_URL or default_input)
        target = sys.argv[2].strip() if len(sys.argv) > 2 else "1080p"
    run_test(video_input, target_resolution=target)
