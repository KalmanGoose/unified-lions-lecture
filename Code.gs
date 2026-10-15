/**
 * ==============================================================================
 * 講座課離線拍照筆記與逐字稿重點 - Google Apps Script (GAS) 後端服務
 * ==============================================================================
 * 
 * 功能說明：
 * 1. doPost(e)：接收前端 lecture_highlight_dashboard.html 送出的 JSON 筆記包。
 *    - 將 Base64 現場投影片照片轉存至指定的 Google 雲端硬碟 (Google Drive) 資料夾。
 *    - 自動將照片設為公開檢視，取得直連圖片網址。
 *    - 將「時間戳記、分類標籤、講者原話、個人筆記、=IMAGE() 照片公式」依序寫入 Google 試算表。
 * 2. doGet(e)：提供 API 供儀表板讀取試算表中的歷史筆記資料。
 * 
 * 部署設定指南：
 * 1. 在 Google 試算表選單點選「擴充功能」->「Apps Script」。
 * 2. 清空既有程式碼，將本檔案內容全部複製貼上。
 * 3. 點選右上角「部署」->「新部署作業」。
 * 4. 種類選擇「網頁應用程式 (Web App)」：
 *    - 說明：講座筆記同步 Webhook
 *    - 執行身分：我 (您的 Google 帳號)
 *    - 誰可以存取：所有人 (Anyone)  <--- 非常重要！若選僅限自己會導致前端跨網域無權限
 * 5. 點擊「部署」，授權 Google 試算表與雲端硬碟存取權限。
 * 6. 複製產生的「網頁應用程式網址 (Web App URL)」，貼回 HTML 網頁的雲端同步設定中。
 */

const SHEET_NAME = 'Notes';
const FOLDER_NAME = '講座課拍照筆記_圖庫';

// 初始化工作表欄位標題
const HEADERS = [
  '筆記 ID',
  '講座名稱',
  '時間戳記',
  '分類標籤',
  '講者原話 (前後90秒)',
  '個人筆記與反思',
  '投影片照片預覽',
  '照片雲端網址',
  '同步時間'
];

/**
 * 接收前端 POST 請求，將圖文筆記同步寫入 Google Sheets 與 Drive
 */
function doPost(e) {
  try {
    const rawContents = e.postData ? e.postData.contents : '';
    if (!rawContents) {
      return jsonResponse({ status: 'error', message: '未收到任何 POST 內容' });
    }

    const payload = JSON.parse(rawContents);
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let sheet = ss.getSheetByName(SHEET_NAME);

    // 若工作表不存在，自動新建並格式化標題
    if (!sheet) {
      sheet = ss.insertSheet(SHEET_NAME);
      sheet.appendRow(HEADERS);
      formatHeaderRow(sheet);
    } else if (sheet.getLastRow() === 0) {
      sheet.appendRow(HEADERS);
      formatHeaderRow(sheet);
    }

    const folder = getOrCreateFolder(FOLDER_NAME);
    const notes = payload.notes || [];
    const lectureTitle = payload.lectureTitle || '未命名講座';
    const nowStr = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');

    let processedCount = 0;

    notes.forEach(item => {
      let imageUrl = '';
      let imageFormula = '';

      // 若筆記包含 Base64 投影片照片，轉存為 Google Drive 圖片檔
      if (item.photoBase64 && item.photoBase64.startsWith('data:image')) {
        try {
          const splitData = item.photoBase64.split(',');
          const contentTypeMatch = splitData[0].match(/:(.*?);/);
          const contentType = contentTypeMatch ? contentTypeMatch[1] : 'image/jpeg';
          const byteCharacters = Utilities.base64Decode(splitData[1]);
          const filename = `slide_${item.id || Date.now()}_${item.timestamp ? item.timestamp.replace(/:/g, '-') : 'time'}.jpg`;
          const blob = Utilities.newBlob(byteCharacters, contentType, filename);

          const file = folder.createFile(blob);
          file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
          
          // Google Drive 圖片直連預覽網址
          imageUrl = `https://drive.google.com/uc?export=view&id=${file.getId()}`;
          imageFormula = `=IMAGE("${imageUrl}", 1)`;
        } catch (imgErr) {
          imageUrl = `圖片處理失敗: ${imgErr.toString()}`;
          imageFormula = '無預覽';
        }
      }

      sheet.appendRow([
        item.id || ('id_' + Date.now()),
        item.lectureTitle || lectureTitle,
        item.timestamp || '00:00:00',
        item.tag || '一般筆記',
        item.transcript || '',
        item.userNote || '',
        imageFormula,
        imageUrl,
        nowStr
      ]);

      processedCount++;
    });

    // 自動調整部分欄寬與設定列高以美化試算表
    if (processedCount > 0) {
      const lastRow = sheet.getLastRow();
      sheet.setRowHeights(lastRow - processedCount + 1, processedCount, 90);
    }

    return jsonResponse({
      status: 'success',
      count: processedCount,
      message: `成功將 ${processedCount} 筆講座筆記同步至 Google 試算表！`
    });

  } catch (err) {
    return jsonResponse({
      status: 'error',
      message: err.toString()
    });
  }
}

/**
 * 接收 GET 請求，供 HTML 儀表板查詢試算表既有筆記
 */
function doGet(e) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = ss.getSheetByName(SHEET_NAME);
    if (!sheet || sheet.getLastRow() <= 1) {
      return jsonResponse({ status: 'success', data: [] });
    }

    const rows = sheet.getDataRange().getValues();
    const headers = rows.shift(); // 移除第一列標題

    const data = rows.map(row => ({
      id: row[0],
      lectureTitle: row[1],
      timestamp: row[2],
      tag: row[3],
      transcript: row[4],
      userNote: row[5],
      imageUrl: row[7],
      syncTime: row[8]
    }));

    return jsonResponse({ status: 'success', count: data.length, data: data });
  } catch (err) {
    return jsonResponse({ status: 'error', message: err.toString() });
  }
}

/**
 * 取得或新建指定名稱之 Google Drive 資料夾
 */
function getOrCreateFolder(folderName) {
  const folders = DriveApp.getFoldersByName(folderName);
  return folders.hasNext() ? folders.next() : DriveApp.createFolder(folderName);
}

/**
 * 標題列視覺美化輔助函式
 */
function formatHeaderRow(sheet) {
  const headerRange = sheet.getRange(1, 1, 1, HEADERS.length);
  headerRange.setBackground('#1e293b');
  headerRange.setFontColor('#38bdf8');
  headerRange.setFontWeight('bold');
  headerRange.setFontSize(11);
  headerRange.setHorizontalAlignment('center');
  sheet.setFrozenRows(1);
  sheet.setColumnWidth(1, 140); // ID
  sheet.setColumnWidth(2, 200); // 講座名稱
  sheet.setColumnWidth(3, 90);  // 時間戳記
  sheet.setColumnWidth(4, 120); // 分類標籤
  sheet.setColumnWidth(5, 320); // 講者原話
  sheet.setColumnWidth(6, 260); // 個人筆記
  sheet.setColumnWidth(7, 130); // 縮圖公式
  sheet.setColumnWidth(8, 200); // 網址
  sheet.setColumnWidth(9, 160); // 同步時間
}

/**
 * 跨來源封裝標準 JSON 回應
 */
function jsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
