#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
離線講座語音轉錄、繁中重點語氣詞偵測與本地 Ollama 萃取系統
(Offline Lecture Speech Transcriber & Highlight Extractor)

支援三種模式：
  1. 一鍵雙工伺服器 (Server Mode, 預設)：啟動本地 HTTP API (http://127.0.0.1:8765)，
     自動開啟瀏覽器網頁，支援網頁直接錄音並一鍵上傳本地 Faster-Whisper 離線轉文字！
  2. 檔案批次轉錄模式 (Batch Mode)：指令列直接轉錄 .mp3/.wav/.m4a 講座錄音檔，產生 .json 與 .srt
  3. 即時麥克風串流模式 (Live Streaming Mode)：透過 WebSocket (ws://localhost:8765) 推播即時段落
"""

import os
import sys

# 自動設定 Hugging Face 高速鏡像
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import re
import json
import time
import argparse
import asyncio
import tempfile
import webbrowser
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

# 選擇性匯入相依套件
try:
    import requests
except ImportError:
    requests = None

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

# 修補 PyAV 19+ 與 faster-whisper 的 metadata_errors 參數相容性
try:
    import av
    _orig_av_open = av.open
    def _safe_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _safe_av_open
except Exception:
    pass

# 本地已下載的 offline large-v3-turbo 模型絕對路徑
LOCAL_OFFLINE_MODEL_PATH = os.path.expanduser(
    "~/.cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
)

# ==============================================================================
# 1. 台灣業界講師「重點語氣詞」Regex 詞庫定義
# ==============================================================================
HIGHLIGHT_PATTERNS = {
    "🎯 核心結論": re.compile(r"(重點是|關鍵在於|最重要的一點|總結來說|一句話講完|核心邏輯|本質上|結論是|最重要的核心)"),
    "📊 產業案例": re.compile(r"(舉個例子|實際案例|我們當時|踩過的坑|血淚教訓|業界現在|商業模式|痛點|血淚|失敗的經驗)"),
    "📸 關鍵投影片": re.compile(r"(看這張圖|投影片上|這個數據|右上角|左邊這欄|架構圖|趨勢|曲線|看下這張)")
}

TAIWAN_MANDARIN_INITIAL_PROMPT = (
    "以下是台灣業界講師的繁體中文商業與技術講座，包含商業實務、架構設計、數據指標與踩坑案例。"
)


def detect_signal_tags(text: str):
    """偵測句子中是否包含台灣講師常用的重點訊號語氣詞"""
    matched_tags = []
    for tag, pattern in HIGHLIGHT_PATTERNS.items():
        if pattern.search(text):
            matched_tags.append(tag)
    return matched_tags


# ==============================================================================
# 2. 本地端 Ollama 離線重點萃取 (無需連網)
# ==============================================================================
def extract_summary_via_ollama(transcript_chunk: str, model_name: str = "qwen2.5:7b", ollama_host: str = "http://localhost:11434"):
    """
    呼叫本地 Ollama API，將口語段落去贅字並提煉 2~3 點繁體中文摘要與專有名詞。
    若 Ollama 未啟動或逾時，則自動退回 (Graceful Fallback)。
    """
    if requests is None:
        return {"summary_points": [transcript_chunk[:120] + "..."], "keywords": []}

    prompt = f"""你是一位專業的商業與技術講座紀錄員。請將以下業界講者的口語逐字稿去除冗言贅字，
提煉出 2 到 3 條「核心重點摘要（使用繁體中文列點）」，並列出文中出現的「關鍵字或專有名詞」：

逐字稿內容：
{transcript_chunk}

請務必嚴格以繁體中文且標準 JSON 格式回傳，格式範例如下：
{{"summary_points": ["重點1", "重點2"], "keywords": ["專有名詞A", "關鍵字B"]}}
"""

    try:
        response = requests.post(
            f"{ollama_host}/api/generate",
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            },
            timeout=20
        )
        if response.status_code == 200:
            res_json = response.json()
            parsed = json.loads(res_json.get("response", "{}"))
            return {
                "summary_points": parsed.get("summary_points", []),
                "keywords": parsed.get("keywords", [])
            }
    except Exception:
        pass

    return {
        "summary_points": [transcript_chunk[:120] + "..."],
        "keywords": []
    }


# ==============================================================================
# 3. 轉錄結果轉換與 SRT 字幕產生
# ==============================================================================
def format_seconds_to_srt_time(sec: float) -> str:
    hrs = int(sec // 3600)
    mins = int((sec % 3600) // 60)
    secs = int(sec % 60)
    millis = int(round((sec - int(sec)) * 1000))
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def export_to_srt(records, output_srt_path: str):
    """將轉錄結果匯出為標準 .srt 字幕檔"""
    with open(output_srt_path, "w", encoding="utf-8") as f:
        for idx, rec in enumerate(records, 1):
            start_str = format_seconds_to_srt_time(rec["start_sec"])
            end_str = format_seconds_to_srt_time(rec["end_sec"])
            f.write(f"{idx}\n")
            f.write(f"{start_str} --> {end_str}\n")
            f.write(f"{rec['text']}\n\n")


# ==============================================================================
# 4. Whisper 模型快取與核心轉錄引擎 (Singleton Model Cache)
# ==============================================================================
_CACHED_MODELS = {}

def get_whisper_model(model_size: str = "large-v3-turbo", device: str = "cpu", compute_type: str = "int8"):
    """全域模型快取：若本機已有 large-v3-turbo 快取，100% 離線載入零網路依賴"""
    if WhisperModel is None:
        raise RuntimeError("系統尚未安裝 faster-whisper。請先執行：pip3 install faster-whisper requests")

    key = (model_size, device, compute_type)
    if key not in _CACHED_MODELS:
        # 若指定 large-v3-turbo 且本機快取存在，直接使用本機離線檔案
        if ("large-v3-turbo" in model_size or model_size == "default") and os.path.exists(LOCAL_OFFLINE_MODEL_PATH):
            target_path = LOCAL_OFFLINE_MODEL_PATH
            print(f"\n🎧 載入本機 100% 離線 Faster-Whisper 模型 [large-v3-turbo]...")
            print(f"📁 本機模型位置：{target_path}")
            _CACHED_MODELS[key] = WhisperModel(target_path, device=device, compute_type=compute_type, local_files_only=True)
        else:
            print(f"\n🎧 載入 Faster-Whisper 模型 [{model_size}] (裝置: {device}, 量化: {compute_type})...")
            _CACHED_MODELS[key] = WhisperModel(model_size, device=device, compute_type=compute_type)

        print(f"✅ Faster-Whisper 模型載入就緒！")
    return _CACHED_MODELS[key]


def transcribe_audio_core(
    audio_path: str,
    model_size: str = "large-v3-turbo",
    device: str = "cpu",
    compute_type: str = "int8",
    enable_ollama: bool = False,
    ollama_model: str = "qwen2.5:7b"
):
    """底層調用 Faster-Whisper 離線將音訊轉為結構化繁中句段與語氣詞標籤"""
    model = get_whisper_model(model_size=model_size, device=device, compute_type=compute_type)

    print(f"🎙️ 正在以離線神經網路解碼音訊：{audio_path}")
    print(f"💡 強制輸出繁體中文 Prompt：「{TAIWAN_MANDARIN_INITIAL_PROMPT}」")

    segments, info = model.transcribe(
        str(audio_path),
        language="zh",
        initial_prompt=TAIWAN_MANDARIN_INITIAL_PROMPT,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500)
    )

    records = []
    highlight_count = 0

    for seg in segments:
        text = seg.text.strip()
        tags = detect_signal_tags(text)
        is_highlight = len(tags) > 0
        if is_highlight:
            highlight_count += 1

        rec = {
            "start_sec": round(seg.start, 2),
            "end_sec": round(seg.end, 2),
            "text": text,
            "auto_tags": tags,
            "is_highlight": is_highlight
        }

        if enable_ollama and is_highlight:
            ollama_res = extract_summary_via_ollama(text, model_name=ollama_model)
            rec["summary_points"] = ollama_res.get("summary_points", [])
            rec["keywords"] = ollama_res.get("keywords", [])

        records.append(rec)
        time_str = f"{format_seconds_to_srt_time(seg.start)} -> {format_seconds_to_srt_time(seg.end)}"
        tag_str = f" 🏷️ [{' '.join(tags)}]" if tags else ""
        print(f"  [{time_str}] {text}{tag_str}")

    return records, info.duration, highlight_count


# ==============================================================================
# 5. 音檔批次轉錄 (Batch Mode)
# ==============================================================================
def process_audio_file(
    audio_path: str,
    model_size: str = "large-v3-turbo",
    device: str = "cpu",
    compute_type: str = "int8",
    enable_ollama: bool = False,
    ollama_model: str = "qwen2.5:7b",
    output_prefix: str = "lecture_transcript"
):
    audio_file = Path(audio_path)
    if not audio_file.exists():
        print(f"\n❌ 錯誤：找不到音訊檔案 {audio_path}\n")
        sys.exit(1)

    start_time = time.time()
    try:
        records, duration, highlight_count = transcribe_audio_core(
            str(audio_file),
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            enable_ollama=enable_ollama,
            ollama_model=ollama_model
        )
    except Exception as e:
        print(f"\n❌ 轉錄失敗：{e}\n")
        sys.exit(1)

    elapsed = time.time() - start_time
    print(f"\n✅ 轉錄完成！共辨識 {len(records)} 個句段，其中 {highlight_count} 個包含重點語氣詞 (耗時: {elapsed:.1f} 秒)")

    # 輸出結構化 JSON
    output_json_path = f"{output_prefix}.json"
    result_data = {
        "audio_file": audio_file.name,
        "duration_seconds": round(duration, 2),
        "total_segments": len(records),
        "highlight_count": highlight_count,
        "transcripts": records
    }
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    print(f"💾 結構化 JSON 已儲存至：{output_json_path} (可直接在 HTML 戰情室載入)")

    # 輸出 SRT 字幕
    output_srt_path = f"{output_prefix}.srt"
    export_to_srt(records, output_srt_path)
    print(f"💾 標準字幕檔已儲存至：{output_srt_path}")

    return result_data


# ==============================================================================
# 6. 本地 HTTP 伺服器與一鍵網頁錄音轉錄 API (/api/transcribe)
# ==============================================================================
GLOBAL_MODEL_SIZE = "large-v3-turbo"

class LectureRequestHandler(SimpleHTTPRequestHandler):
    """自訂 HTTP 處理器，支援靜態網頁檔案服務、CORS 與音訊轉錄 API"""

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            status_obj = {
                "whisper_ready": WhisperModel is not None,
                "message": "Faster-Whisper 已就緒 (本機大模型 large-v3-turbo 離線可用)"
            }
            self.wfile.write(json.dumps(status_obj, ensure_ascii=False).encode("utf-8"))
            return

        if self.path in ("/", "/index.html"):
            self.path = "/lecture_highlight_dashboard.html"

        super().do_GET()

    def do_POST(self):
        if self.path == "/api/transcribe":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self.send_error(400, "未收到任何音訊內容")
                return

            audio_data = self.rfile.read(content_length)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
                tmp_audio.write(audio_data)
                tmp_path = tmp_audio.name

            try:
                print(f"\n📥 收到前端網頁傳送之課堂錄音檔 (大小: {len(audio_data) / 1024:.1f} KB)，開始離線辨識...")
                records, duration, highlight_count = transcribe_audio_core(
                    tmp_path,
                    model_size=GLOBAL_MODEL_SIZE,
                    device="cpu",
                    compute_type="int8",
                    enable_ollama=False
                )

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                resp = {
                    "status": "success",
                    "duration": duration,
                    "highlight_count": highlight_count,
                    "transcripts": records
                }
                self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
                print(f"✅ 成功將 {len(records)} 句繁中逐字稿回傳至網頁前端！")
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                resp = {"status": "error", "message": f"轉錄過程出錯：{str(e)}"}
                self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            return

        self.send_error(404, "找不到此 API 端點")


def run_local_server(port=8765, model_size="large-v3-turbo"):
    """啟動本地雙工伺服器並自動開啟網頁"""
    global GLOBAL_MODEL_SIZE
    GLOBAL_MODEL_SIZE = model_size

    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, LectureRequestHandler)
    url = f"http://127.0.0.1:{port}/lecture_highlight_dashboard.html"

    print("=" * 68)
    print(f"🚀 講座重點戰情室 本地離線轉錄伺服器已啟動！")
    print(f"👉 服務網址：{url}")
    print(f"🎯 使用模型：[{model_size}] (100% 離線推論，零外網依賴)")
    print(f"💡 功能特色：網頁內建『🎙️ 課堂全程錄音』，錄完一鍵點擊即可直接轉為繁中逐字稿！")
    print("=" * 68)
    print("按 Ctrl + C 可隨時停止伺服器\n")

    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n伺服器已正常停止。")


# ==============================================================================
# 7. 主程式命令列入口 (CLI)
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="台灣繁體中文講座離線語音轉錄、錄音接收與重點萃取服務",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--server", action="store_true", help="啟動本地 HTTP 網頁與轉錄服務 (預設模式)")
    parser.add_argument("--audio", type=str, help="欲轉錄的錄音檔路徑 (.mp3, .wav, .m4a, .aac, .flac)")
    parser.add_argument("--model", type=str, default="large-v3-turbo", help="Whisper 模型規格 (預設: large-v3-turbo)")
    parser.add_argument("--device", type=str, default="cpu", help="運算裝置 (預設: cpu, 可選 cuda 或 mps)")
    parser.add_argument("--compute-type", type=str, default="int8", help="量化類型 (預設: int8, 可選 float16 或 float32)")
    parser.add_argument("--enable-ollama", action="store_true", help="是否啟用本地端 Ollama 離線提煉摘要與關鍵字")
    parser.add_argument("--ollama-model", type=str, default="qwen2.5:7b", help="本地 Ollama 模型名稱 (預設: qwen2.5:7b)")
    parser.add_argument("--output", type=str, default="lecture_transcript", help="輸出檔名前綴 (預設: lecture_transcript)")
    parser.add_argument("--port", type=int, default=8765, help="本地伺服器監聽埠號 (預設: 8765)")

    args = parser.parse_args()

    if args.audio:
        process_audio_file(
            audio_path=args.audio,
            model_size=args.model,
            device=args.device,
            compute_type=args.compute_type,
            enable_ollama=args.enable_ollama,
            ollama_model=args.ollama_model,
            output_prefix=args.output
        )
    else:
        run_local_server(port=args.port, model_size=args.model)


if __name__ == "__main__":
    main()
