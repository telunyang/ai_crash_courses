import os
import json

from flask import Flask, request, Response, render_template
from ollama import Client


app = Flask(__name__)

# Ollama 設定
OLLAMA_HOST = "http://localhost:11434"
MODEL_NAME = "qwen3.5:0.8b"
HISTORY_FILE = "chat_history.json"

client = Client(
    host=OLLAMA_HOST,
    timeout=600
)


# 讀取歷史對話
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []

    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# 儲存歷史對話
def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# 將我們自己的歷史格式轉成 Ollama 需要的格式
def build_ollama_messages(history):
    messages = []

    for msg in history:
        role = msg["role"]
        text = msg["text"]

        # 前端沿用 model，但 Ollama 需要 assistant
        if role == "model":
            role = "assistant"

        messages.append({
            "role": role,
            "content": text
        })

    return messages


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/history")
def get_history():
    return load_history()


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    data = request.get_json()
    user_message = data["message"]

    # 1. 讀取舊歷史
    history = load_history()

    # 2. 把歷史轉成 Ollama messages
    messages = build_ollama_messages(history)

    # 3. 加入這次使用者的新問題
    messages.append({
        "role": "user",
        "content": user_message
    })

    def generate():
        full_reply = ""

        # 4. 串流呼叫 Ollama
        stream = client.chat(
            model=MODEL_NAME,
            messages=messages,
            keep_alive="1h",
            stream=True
        )

        for part in stream:
            text = part["message"]["content"]

            if text:
                full_reply += text
                yield text

        # 5. 串流結束後，儲存本輪對話
        history.append({
            "role": "user",
            "text": user_message
        })

        history.append({
            "role": "model",
            "text": full_reply
        })

        save_history(history)

    return Response(generate(), mimetype="text/plain")


@app.route("/api/clear", methods=["POST"])
def clear_history():
    save_history([])
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(debug=True)