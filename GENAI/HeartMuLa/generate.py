# 執行語法
'''
先安裝 requests 套件

pip install requests

================================================

在 Linux

python generate.py \
  --url "https://你的-ngrok-url.ngrok-free.app" \
  --song_name "my_song" \
  --lyrics_file "./my_lyrics.txt" \
  --tags_file "./my_tags.txt"

================================================
  
在 Windows

python generate.py --url "https://你的-ngrok-url.ngrok-free.app" --song_name "my_song" --lyrics_file "./my_lyrics.txt" --tags_file "./my_tags.txt"
'''

import time, requests, argparse

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--song_name", default="my_song")
parser.add_argument("--lyrics_file", default="./my_lyrics.txt")
parser.add_argument("--tags_file", default="./my_tags.txt")
args = parser.parse_args()

BASE = args.url.rstrip("/")

files = {
    "lyrics_file": open(args.lyrics_file, "rb"),
    "tags_file": open(args.tags_file, "rb"),
}

data = {
    "filename": f"{args.song_name}.mp3",
    "max_audio_length_ms": "60000",
    "cfg_scale": "1.5",
    "topk": "50",
    "temperature": "1.0",
}

r = requests.post(f"{BASE}/generate", files=files, data=data)
r.raise_for_status()

job_id = r.json()["job_id"]
print("job_id:", job_id)

while True:
    s = requests.get(f"{BASE}/status/{job_id}").json()
    print(s["status"])

    if s["status"] == "done":
        break

    if s["status"] == "error":
        raise RuntimeError(s.get("error"))

    time.sleep(10)

r = requests.get(f"{BASE}/download/{job_id}")
r.raise_for_status()

out = f"{args.song_name}.mp3"
open(out, "wb").write(r.content)

print("saved:", out)