#!/bin/bash
# 雙擊本檔案即可一鍵啟動本地語音轉錄伺服器與重點戰情室網頁
cd "$(dirname "$0")"

# 設定 Hugging Face 高速鏡像，徹底解決跨國下載逾時問題
export HF_ENDPOINT="https://hf-mirror.com"

echo "=================================================================="
echo "🎙️ 正在啟動 講座重點戰情室 本地離線語音轉錄伺服器..."
echo "⚡ 已自動啟用 Hugging Face 高速鏡像加速 (https://hf-mirror.com)"
echo "=================================================================="

# 優先使用 Anaconda Python 或 系統 Python3
if [ -f "/opt/anaconda3/bin/python3" ]; then
    PYTHON_CMD="/opt/anaconda3/bin/python3"
elif command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
else
    echo "❌ 找不到 Python 執行檔，請確認已安裝 Python！"
    exit 1
fi

echo "使用 Python: $($PYTHON_CMD --version)"
$PYTHON_CMD offline_transcriber.py
