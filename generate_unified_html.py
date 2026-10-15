#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 100% 靜態預渲染的《統一獅董事長涂忠正 企業家講座》完整戰情室 HTML
所有 47 張卡片與 28 張投影片直接寫入 HTML DOM，即使 JS 被停用也能立刻看到完整內容！
"""

import json
import html
import re

# 1. 讀取資料
with open('講座備份_1792050185273.json', 'r', encoding='utf-8') as f:
    backup_data = json.load(f)

with open('統一獅講座逐字稿.json', 'r', encoding='utf-8') as f:
    tr_data = json.load(f)

notes = backup_data.get('notes', [])
transcripts = tr_data.get('transcripts', [])

# 按照時間由小到大排序
notes = sorted(notes, key=lambda x: x.get('timeSec', 0))

def format_time(total_sec):
    hrs = int(total_sec // 3600)
    mins = int((total_sec % 3600) // 60)
    secs = int(total_sec % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"

HIGHLIGHT_REGEX = re.compile(r"(重點是|關鍵在於|最重要的一點|總結來說|一句話講完|核心邏輯|本質上|結論是|舉個例子|實際案例|我們當時|踩過的坑|血淚教訓|業界現在|商業模式|痛點|血淚|看這張圖|投影片上|這個數據|右上角|左邊這欄|架構圖|趨勢|曲線)")

def highlight_markers(text):
    if not text:
        return ""
    escaped = html.escape(text)
    return HIGHLIGHT_REGEX.sub(r'<mark class="highlight-tag">\1</mark>', escaped)

# 2. 為每張筆記對齊逐字稿
highlight_count = 0
for n in notes:
    t_sec = n.get('timeSec', 0)
    window_start = max(0, t_sec - 45)
    window_end = t_sec + 45
    matched = [s for s in transcripts if s['end_sec'] >= window_start and s['start_sec'] <= window_end]
    if matched:
        n['transcriptSnippet'] = " ".join([f"[{format_time(s['start_sec'])}] {s['text']}" for s in matched])
        highlight_count += 1
    elif not n.get('transcriptSnippet'):
        n['transcriptSnippet'] = f"【課堂時間 {n.get('timestamp')}】探討核心：{n.get('userNote')}"

# 3. 預渲染 47 張卡片 HTML
cards_html_list = []
for item in notes:
    tag = item.get('tag', '一般筆記')
    tag_class = 'tag-general-badge'
    if '結論' in tag:
        tag_class = 'tag-conclusion-badge'
    elif '案例' in tag or '踩坑' in tag:
        tag_class = 'tag-case-badge'
    elif '投影片' in tag or '圖表' in tag:
        tag_class = 'tag-chart-badge'
    elif '金句' in tag:
        tag_class = 'tag-quote-badge'

    photo_b64 = item.get('photoBase64', '')
    if photo_b64:
        photo_html = f'<img src="{photo_b64}" class="slide-thumb" alt="投影片" onclick="openLightbox(\'{photo_b64}\')">'
    else:
        photo_html = '''<div class="slide-thumb-empty">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
          <span style="margin-top: 4px;">純文字重點 (無拍照)</span>
        </div>'''

    user_note = html.escape(item.get('userNote', ''))
    transcript_snippet = item.get('transcriptSnippet', '')
    hl_transcript = highlight_markers(transcript_snippet)

    card = f'''
    <div class="card-item" id="card-{item['id']}">
      <div class="col-media">
        {photo_html}
        <div class="meta-badge-row">
          <span class="time-badge">{item.get('timestamp', '00:00:00')}</span>
          <span style="color: var(--text-muted); font-size: 11px;">相對時間 {item.get('timeSec', 0)}s</span>
        </div>
      </div>

      <div class="col-summary">
        <div>
          <span class="note-tag {tag_class}">{tag}</span>
        </div>
        <div class="user-note-text">
          {user_note}
        </div>
        <div class="card-footer-actions">
          <label style="font-size: 11px; color: var(--text-muted); cursor: pointer; display: flex; align-items: center; gap: 4px;">
            <input type="checkbox" class="export-checkbox" value="{item['id']}" checked>
            納入匯出清單
          </label>
          <button class="btn btn-sm" onclick="deleteNote('{item['id']}')" style="color: #ef4444; background: transparent; padding: 2px 6px;">
            刪除
          </button>
        </div>
      </div>

      <div class="col-transcript">
        <div class="transcript-header">
          <span>前後 90 秒講者原話語境 [T-45s ~ T+45s]</span>
          <button class="btn btn-sm" onclick="copyText('{html.escape(transcript_snippet)}')" style="padding: 2px 6px; font-size: 10px;">
            複製原話
          </button>
        </div>
        <div class="transcript-body">
          {hl_transcript}
        </div>
      </div>
    </div>
    '''
    cards_html_list.append(card)

pre_rendered_cards = "\n".join(cards_html_list)

# 4. 讀取 template
with open('lecture_highlight_dashboard.html', 'r', encoding='utf-8') as f:
    template = f.read()

# 5. 替換靜態元素
template = template.replace(
    'value="台灣 AI 商業化落地與產品架構實戰踩坑記"',
    'value="統一棒球隊 (統一獅) 企業經營策略與組織管理"'
)
template = template.replace(
    'value="業界資深產品總監 林志宏"',
    'value="統一棒球隊董事長 涂忠正博士 (與談人: 卓信佑教授 / 主持人: 唐資文主任)"'
)
template = template.replace(
    '<div class="rec-timer" id="recording-timer">00:00:00</div>',
    '<div class="rec-timer" id="recording-timer">00:57:23</div>'
)
template = template.replace(
    '<span class="pill-val" id="stat-total-notes">0</span>',
    f'<span class="pill-val" id="stat-total-notes">{len(notes)}</span>'
)
template = template.replace(
    '<span class="pill-val" id="stat-total-photos">0</span>',
    f'<span class="pill-val" id="stat-total-photos">{len([n for n in notes if n.get("photoBase64")])}</span>'
)
template = template.replace(
    '<span class="pill-val" id="stat-total-highlights">0</span>',
    f'<span class="pill-val" id="stat-total-highlights">{highlight_count}</span>'
)

# 音訊播放器預先顯示
template = template.replace(
    '<div id="recorded-audio-playback-box">',
    '<div id="recorded-audio-playback-box" style="display: flex;">'
)
template = template.replace(
    '<audio id="recorded-audio-element" controls></audio>',
    '<audio id="recorded-audio-element" src="統一獅董事長_1792049357429.wav" controls style="width: 100%;"></audio>'
)
template = template.replace(
    '<span id="audio-filesize-text">0 KB</span>',
    '<span id="audio-filesize-text">22.3 MB (時長 13:59)</span>'
)
template = template.replace(
    '<button class="btn btn-sm" id="rec-download-btn" onclick="downloadRecordedAudio()" style="display: none;">',
    '<button class="btn btn-sm" id="rec-download-btn" onclick="downloadRecordedAudio()" style="display: inline-flex;">'
)

# 直接把預渲染好的 47 張卡片填入 #notes-container！
empty_state_html = '''<div class="notes-list" id="notes-container">
          <div class="empty-state">
            目前尚無筆記記錄。請在右上角點擊「🔴 開始課堂全程錄音」，並在左側拍下投影片或點選「打點記錄」！<br>
            亦可點擊上方「載入範例資料體驗」快速查看完整版面。
          </div>
        </div>'''

template = template.replace(empty_state_html, f'''<div class="notes-list" id="notes-container">
{pre_rendered_cards}
</div>''')

# 6. 注入全局預設變數與事件監聽
notes_json_str = json.dumps(notes, ensure_ascii=False)
transcripts_json_str = json.dumps(transcripts, ensure_ascii=False)

js_bootstrap = f"""
    // 預設載入統一獅講座全部 47 筆筆記與 137 段逐字稿
    const PRELOADED_NOTES = {notes_json_str};
    const PRELOADED_TRANSCRIPTS = {transcripts_json_str};

    allNotes = PRELOADED_NOTES;
    loadedTranscripts = PRELOADED_TRANSCRIPTS;
    recordingTimerSeconds = 3443;

    window.addEventListener('DOMContentLoaded', async () => {{
      try {{
        await initIndexedDB();
        for (let n of allNotes) await dbSaveNote(n);
        await dbSaveTranscriptsBatch(loadedTranscripts);
      }} catch (err) {{
        console.warn('IndexedDB 離線快取初始化略過 (Safari file:// 限制):', err);
      }}

      updateNetworkStatus();
      updateTranscriptUi();
      renderTimelineChart();
    }});
"""

template = re.sub(
    r'window\.addEventListener\(\'DOMContentLoaded\', async \(\) => \{.*?\}\);',
    js_bootstrap,
    template,
    flags=re.DOTALL
)

with open('統一獅講座_完整圖文戰情室.html', 'w', encoding='utf-8') as f:
    f.write(template)

print("✅ 成功生成 100% 靜態預渲染 Master HTML：統一獅講座_完整圖文戰情室.html！")
