import io
import json
import time
import uuid
import shutil
import subprocess
from pathlib import Path

import requests
from PIL import Image


# ============================================================
# 基本設定
# ============================================================

BASE = "https://your-ngrok-url.ngrok-free.app"
HEADERS = {"ngrok-skip-browser-warning": "1"}

INPUT_IMAGE = "./my_photo.jpg"
WORKFLOW_PATH = "ltx2_3_t2v_i2v.json"

# 寬/高至少為 256，並且是 32 的倍數。
WIDTH = 480
HEIGHT = 832
FPS = 24

# 兩階段推論設定
SEED_PASS_1 = 43
SEED_PASS_2 = 42
CFG_PASS_1 = 1.0
CFG_PASS_2 = 1.0

OUTPUT_ROOT = Path("outputs")
FINAL_VIDEO_PATH = OUTPUT_ROOT / "final_video.mp4"


# ============================================================
# 三段 Clip Prompt
# ============================================================
CLIPS = [
    {
        "name": "01_",
        "seconds": 5,
        "prompt": """""".strip(),
    },
    {
        "name": "02_",
        "seconds": 5,
        "prompt": """""".strip(),
    },
    {
        "name": "03_",
        "seconds": 5,
        "prompt": """""".strip(),
    },
]


# ============================================================
# Utility functions
# ============================================================


def check_ffmpeg():
    """確認系統中有 ffmpeg。"""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "找不到 ffmpeg。請先安裝 ffmpeg，否則無法擷取最後一幀與合併影片。"
        )


def safe_size(value):
    """寬/高至少為 256，並且修正成 32 的倍數。"""
    return max(256, round(value / 32) * 32)


def upload_image(path_or_image, filename):
    """
    上傳圖片到 ComfyUI server。

    支援：
    - PIL.Image
    - 本地圖片路徑

    回傳：
    - server 端儲存的檔名
    """
    if isinstance(path_or_image, Image.Image):
        buffer = io.BytesIO()
        path_or_image.save(buffer, format="PNG")
        buffer.seek(0)
        files = {"image": (filename, buffer, "image/png")}

        response = requests.post(
            f"{BASE}/upload/image",
            files=files,
            data={"overwrite": "true"},
            headers=HEADERS,
            timeout=None,
        )
        response.raise_for_status()

    else:
        path = Path(path_or_image)
        if not path.exists():
            raise FileNotFoundError(f"找不到圖片：{path}")

        with path.open("rb") as f:
            files = {"image": (path.name, f, "application/octet-stream")}
            response = requests.post(
                f"{BASE}/upload/image",
                files=files,
                data={"overwrite": "true"},
                headers=HEADERS,
                timeout=None,
            )
            response.raise_for_status()

    result = response.json()
    return result.get("name", filename)


def queue_prompt(workflow):
    """將 workflow 送到 ComfyUI server，回傳 prompt_id。"""
    response = requests.post(
        f"{BASE}/prompt",
        json={"prompt": workflow, "client_id": str(uuid.uuid4())},
        headers=HEADERS,
        timeout=None,
    )
    response.raise_for_status()
    return response.json()["prompt_id"]


def wait_for_history(prompt_id, sleep_seconds=10):
    """等待 ComfyUI 完成 workflow，完成後回傳 history。"""
    while True:
        try:
            response = requests.get(
                f"{BASE}/history/{prompt_id}",
                headers=HEADERS,
                timeout=(10, 60),
            )
            response.raise_for_status()

            history = response.json()
            if prompt_id in history:
                return history[prompt_id]

            print("still running...")

        except requests.exceptions.RequestException as e:
            print("history request failed, retrying:", type(e).__name__)

        time.sleep(sleep_seconds)


def download_outputs(history, output_dir):
    """下載 ComfyUI server 上的輸出檔案。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved = []

    for output in history.get("outputs", {}).values():
        for key in ("videos", "gifs", "images"):
            for item in output.get(key, []):
                filename = item.get("filename", f"output_{len(saved)}")
                path = output_dir / filename

                while True:
                    try:
                        response = requests.get(
                            f"{BASE}/view",
                            params=item,
                            headers=HEADERS,
                            timeout=(10, 300),
                        )
                        response.raise_for_status()
                        path.write_bytes(response.content)
                        saved.append(path)
                        print("saved:", path)
                        break

                    except requests.exceptions.RequestException as e:
                        print("download failed, retrying:", type(e).__name__)
                        time.sleep(10)

    if not saved:
        raise RuntimeError("沒有下載到任何輸出檔案，請檢查 workflow 的輸出節點。")

    return saved


def pick_video(saved_files):
    """從輸出檔案中挑出影片檔。"""
    video_exts = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
    videos = [Path(p) for p in saved_files if Path(p).suffix.lower() in video_exts]

    if not videos:
        raise RuntimeError(f"找不到影片輸出，輸出檔案如下：{saved_files}")

    return videos[0]


def extract_last_frame(video_path, output_image_path):
    """
    從上一段影片擷取最後一幀，作為下一段 I2V 的起始圖片。
    """
    video_path = Path(video_path)
    output_image_path = Path(output_image_path)
    output_image_path.parent.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        raise FileNotFoundError(f"找不到影片：{video_path}")

    cmd = [
        "ffmpeg.exe",
        "-y",
        "-sseof",
        "-0.1",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(output_image_path),
    ]

    subprocess.run(cmd, check=True)

    if not output_image_path.exists():
        raise RuntimeError(f"最後一幀擷取失敗：{output_image_path}")

    return output_image_path


def concat_videos(video_paths, output_path):
    """
    將多段影片合併成一支影片。

    這裡使用 re-encode，而不是 -c copy，因為不同 clip 的封裝或編碼參數
    有時可能不完全一致，re-encode 比較穩定。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    list_path = output_path.parent / "concat_list.txt"

    with list_path.open("w", encoding="utf-8") as f:
        for video_path in video_paths:
            absolute_path = Path(video_path).resolve()
            f.write(f"file '{absolute_path.as_posix()}'\n")

    cmd = [
        "ffmpeg.exe",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]

    subprocess.run(cmd, check=True)

    if not output_path.exists():
        raise RuntimeError(f"影片合併失敗：{output_path}")

    return output_path


# ============================================================
# Workflow runner
# ============================================================


def build_workflow(clip, input_image, clip_index):
    """讀取 workflow JSON，並寫入當前 clip 的設定。"""
    workflow_path = Path(WORKFLOW_PATH)
    if not workflow_path.exists():
        raise FileNotFoundError(f"找不到 workflow JSON：{workflow_path}")

    width = safe_size(WIDTH)
    height = safe_size(HEIGHT)

    workflow = json.load(workflow_path.open(encoding="utf-8"))

    # ------------------------------------------------------------
    # Common settings
    # ------------------------------------------------------------
    workflow["292"]["inputs"]["value"] = width
    workflow["293"]["inputs"]["value"] = height
    workflow["285"]["inputs"]["value"] = FPS
    workflow["121"]["inputs"]["text"] = clip["prompt"]
    workflow["291"]["inputs"]["value"] = clip["seconds"]

    # ------------------------------------------------------------
    # Pass 1
    # ------------------------------------------------------------
    workflow["137"]["inputs"]["sampler_name"] = "lcm"
    workflow["360"]["inputs"]["sigmas"] = (
        "1.0, 0.99375, 0.9875, 0.98125, 0.975, "
        "0.909375, 0.725, 0.421875, 0.0"
    )
    workflow["129"]["inputs"]["cfg"] = CFG_PASS_1
    workflow["115"]["inputs"]["noise_seed"] = SEED_PASS_1 + clip_index

    # ------------------------------------------------------------
    # Pass 2
    # ------------------------------------------------------------
    workflow["138"]["inputs"]["sampler_name"] = "euler_cfg_pp"
    workflow["359"]["inputs"]["sigmas"] = "0.85, 0.7250, 0.4219, 0.0"
    workflow["103"]["inputs"]["cfg"] = CFG_PASS_2
    workflow["114"]["inputs"]["noise_seed"] = SEED_PASS_2 + clip_index

    # ------------------------------------------------------------
    # Image-to-Video mode
    # ------------------------------------------------------------
    workflow["290"]["inputs"]["value"] = False
    workflow["167"]["inputs"]["image"] = upload_image(
        input_image,
        Path(input_image).name,
    )

    return workflow


def run_one_clip(clip, input_image, clip_index):
    """執行單一 clip，並回傳輸出的影片路徑。"""
    print("\n" + "=" * 70)
    print(f"Running clip {clip_index}: {clip['name']}")
    print(f"Input image: {input_image}")
    print(f"Seconds: {clip['seconds']}")
    print("=" * 70)

    workflow = build_workflow(clip, input_image, clip_index)

    prompt_id = queue_prompt(workflow)
    print("prompt_id:", prompt_id)

    history = wait_for_history(prompt_id)

    output_dir = OUTPUT_ROOT / clip["name"]
    saved_files = download_outputs(history, output_dir=output_dir)

    video_path = pick_video(saved_files)
    print("clip video:", video_path)

    return video_path


# ============================================================
# Main
# ============================================================


def main():
    check_ffmpeg()

    input_image = Path(INPUT_IMAGE)
    if not input_image.exists():
        raise FileNotFoundError(f"找不到起始圖片：{input_image}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    current_image = input_image
    clip_videos = []

    for i, clip in enumerate(CLIPS, start=1):
        video_path = run_one_clip(clip, current_image, i)
        clip_videos.append(video_path)

        # 不是最後一段的話，擷取最後一幀給下一段當起始圖片。
        if i < len(CLIPS):
            next_image = OUTPUT_ROOT / f"{clip['name']}_last_frame.png"
            current_image = extract_last_frame(video_path, next_image)
            print("next input image:", current_image)

    final_video = concat_videos(clip_videos, FINAL_VIDEO_PATH)

    print("\n" + "=" * 70)
    print("All clips finished.")
    print("Final video saved:", final_video)
    print("=" * 70)


if __name__ == "__main__":
    main()
