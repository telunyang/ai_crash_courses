import json, time, uuid, requests
from pathlib import Path

BASE = "https://你的-ngrok-url.ngrok-free.app"
HEADERS = {"ngrok-skip-browser-warning": "1"}

PROMPT = "a cute cat, cinematic light, high quality"
WIDTH = 1024
HEIGHT = 1024
BATCH_SIZE = 1
SEED = 123
STEPS = 8
CFG = 1

workflow = json.load(open("image_z_image_turbo.json", encoding="utf-8"))

workflow["57:27"]["inputs"]["text"] = PROMPT
workflow["57:13"]["inputs"]["width"] = WIDTH
workflow["57:13"]["inputs"]["height"] = HEIGHT
workflow["57:13"]["inputs"]["batch_size"] = BATCH_SIZE
workflow["57:3"]["inputs"]["seed"] = SEED
workflow["57:3"]["inputs"]["steps"] = STEPS
workflow["57:3"]["inputs"]["cfg"] = CFG

prompt_id = requests.post(
    f"{BASE}/prompt",
    json={"prompt": workflow, "client_id": str(uuid.uuid4())},
    headers=HEADERS,
).json()["prompt_id"]

while True:
    history = requests.get(f"{BASE}/history/{prompt_id}", headers=HEADERS).json()
    if prompt_id in history:
        break
    time.sleep(2)

Path("outputs").mkdir(exist_ok=True)

for output in history[prompt_id]["outputs"].values():
    for img in output.get("images", []):
        data = requests.get(f"{BASE}/view", params=img, headers=HEADERS).content
        path = Path("outputs") / img["filename"]
        path.write_bytes(data)
        print("saved:", path)