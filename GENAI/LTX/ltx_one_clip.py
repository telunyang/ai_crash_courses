import io
import json
import time
import uuid
import requests
import subprocess
from pathlib import Path
from PIL import Image

BASE = "https://your-ngrok-url.ngrok-free.app"
HEADERS = {"ngrok-skip-browser-warning": "1"}

MODE = "i2v"  # "t2v" or "i2v"
INPUT_IMAGE = "./my_photo.jpg"  # used only when MODE = "i2v"

PROMPT = '''
你希望影片呈現的內容。
A prompt that describes the content you want in the video.
'''.strip()


# 寬/高至少為 256，並且是 32 的倍數。
WIDTH = 480
HEIGHT = 832
SECONDS = 11
FPS = 24

# 兩階段推論設定
SEED_PASS_1 = 43
SEED_PASS_2 = 42
CFG_PASS_1 = 1.0
CFG_PASS_2 = 1.0

WORKFLOW_PATH = "ltx2_3_t2v_i2v.json"

# 寬/高至少為 256，並且是 32 的倍數
def safe_size(value):
    return max(256, round(value / 32) * 32)

# 上傳圖片，支援 PIL.Image 或檔案路徑
def upload_image(path_or_image, filename):
    if isinstance(path_or_image, Image.Image):
        buffer = io.BytesIO()
        path_or_image.save(buffer, format="PNG")
        buffer.seek(0)
        files = {"image": (filename, buffer, "image/png")}
    else:
        path = Path(path_or_image)
        files = {"image": (path.name, path.open("rb"), "application/octet-stream")}

    # 上傳圖片到伺服器，並回傳伺服器上儲存的檔案名稱
    response = requests.post(
        f"{BASE}/upload/image",
        files=files,
        data={"overwrite": "true"},
        headers=HEADERS,
        timeout=None
    )
    response.raise_for_status()

    result = response.json()
    return result.get("name", filename)

# 將工作流程送到伺服器，並回傳 prompt_id
def queue_prompt(workflow):
    response = requests.post(
        f"{BASE}/prompt",
        json={"prompt": workflow, "client_id": str(uuid.uuid4())},
        headers=HEADERS,
        timeout=None
    )
    response.raise_for_status()
    return response.json()["prompt_id"]

# 等待伺服器完成工作流程，並回傳歷史紀錄
def wait_for_history(prompt_id, sleep_seconds=10):
    while True:
        try:
            r = requests.get(
                f"{BASE}/history/{prompt_id}",
                headers=HEADERS,
                timeout=(10, 60),
            )
            r.raise_for_status()

            history = r.json()
            if prompt_id in history:
                return history[prompt_id]

            print("still running...")

        except requests.exceptions.RequestException as e:
            print("history request failed, retrying:", type(e).__name__)

        time.sleep(sleep_seconds)

# 下載伺服器上的輸出檔案，並儲存到本地端
def download_outputs(history, output_dir="outputs"):
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    saved = []

    for output in history["outputs"].values():
        for key in ("videos", "gifs", "images"):
            for item in output.get(key, []):
                filename = item.get("filename", f"output_{len(saved)}")
                path = output_dir / filename

                while True:
                    try:
                        r = requests.get(
                            f"{BASE}/view",
                            params=item,
                            headers=HEADERS,
                            timeout=(10, 300),
                        )
                        r.raise_for_status()
                        path.write_bytes(r.content)
                        saved.append(path)
                        print("saved:", path)
                        break

                    except requests.exceptions.RequestException as e:
                        print("download failed, retrying:", type(e).__name__)
                        time.sleep(10)

    return saved

# 寬/高至少為 256，並且是 32 的倍數
width = safe_size(WIDTH)
height = safe_size(HEIGHT)

# 讀取工作流程 JSON 檔案
workflow = json.load(open(WORKFLOW_PATH, encoding="utf-8"))

# Common settings
workflow["292"]["inputs"]["value"] = width
workflow["293"]["inputs"]["value"] = height
workflow["285"]["inputs"]["value"] = FPS
workflow["121"]["inputs"]["text"] = PROMPT
workflow["291"]["inputs"]["value"] = SECONDS

# Pass 1
workflow["137"]["inputs"]["sampler_name"] = "lcm"
workflow["360"]["inputs"]["sigmas"] = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
workflow["129"]["inputs"]["cfg"] = CFG_PASS_1
workflow["115"]["inputs"]["noise_seed"] = SEED_PASS_1

# Pass 2
workflow["138"]["inputs"]["sampler_name"] = "euler_cfg_pp"
workflow["359"]["inputs"]["sigmas"] = "0.85, 0.7250, 0.4219, 0.0"
workflow["103"]["inputs"]["cfg"] = CFG_PASS_2
workflow["114"]["inputs"]["noise_seed"] = SEED_PASS_2

if MODE.lower() == "t2v": # 文字轉影片
    workflow["290"]["inputs"]["value"] = True

    # Some LTX workflows still contain an image-loader node.
    # Uploading a black dummy image prevents missing-input errors.
    dummy = Image.new("RGB", (width, height), color="black")
    workflow["167"]["inputs"]["image"] = upload_image(dummy, "ltx_dummy.png")

elif MODE.lower() == "i2v": # 圖片轉影片
    workflow["290"]["inputs"]["value"] = False
    workflow["167"]["inputs"]["image"] = upload_image(INPUT_IMAGE, Path(INPUT_IMAGE).name)

else: # 拋出錯誤
    raise ValueError('MODE must be "t2v" or "i2v".')

# 送出工作流程，取得 prompt_id
prompt_id = queue_prompt(workflow)
print("prompt_id:", prompt_id)

# 等待伺服器完成工作流程，並下載輸出檔案
history = wait_for_history(prompt_id)
saved_files = download_outputs(history)
