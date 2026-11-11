/**
 * RecipeLens 錯誤回報接收端（Google Apps Script 網頁應用程式）
 *
 * 安裝步驟見 readme.md「錯誤回報接收端」。摘要：
 * 1. 建立 Google 試算表 → 擴充功能 → Apps Script，貼上本檔內容。
 * 2. 專案設定 → 指令碼屬性，新增：
 *      REPORT_KEY    與 report_endpoint.json 的 key 相同的隨機字串（必填）
 *      NOTIFY_EMAIL  收到回報時通知的信箱（選填；留空只寫入試算表）
 * 3. 部署 → 新增部署作業 → 網頁應用程式；執行身分「我」，存取權「所有人」。
 * 4. 把部署網址（結尾 /exec）與 REPORT_KEY 寫入 RecipeLens 的 report_endpoint.json。
 */

const SHEET_NAME = '錯誤回報';
const MAX_REPORT_CHARS = 5000;
const RATE_LIMIT = 30;           // 每 10 分鐘最多收幾筆，防止被灌爆
const RATE_WINDOW_SECONDS = 600;
const HEADERS = ['收到時間', '回報編號', '版本', '作業系統', 'AI 平台', '階段', '錯誤摘要', '處理狀態'];

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(10000);
    const props = PropertiesService.getScriptProperties();
    const expected = props.getProperty('REPORT_KEY');
    if (!expected) return reply({ ok: false, error: 'receiver_not_configured' });

    let data;
    try {
      data = JSON.parse((e && e.postData && e.postData.contents) || '');
    } catch (err) {
      return reply({ ok: false, error: 'invalid_json' });
    }
    if (!data || data.key !== expected) return reply({ ok: false, error: 'unauthorized' });

    const cache = CacheService.getScriptCache();
    const count = Number(cache.get('report_count') || 0);
    if (count >= RATE_LIMIT) return reply({ ok: false, error: 'rate_limited' });
    cache.put('report_count', String(count + 1), RATE_WINDOW_SECONDS);

    const report = String(data.report || '').slice(0, MAX_REPORT_CHARS);
    const provider = field(report, 'AI 平台');
    const stage = field(report, '階段');
    const id = String(data.report_id || '').slice(0, 32);

    sheet().appendRow([
      new Date(), id, clip(data.version, 32), clip(data.os, 64),
      provider, stage, report, '未處理',
    ]);

    const to = props.getProperty('NOTIFY_EMAIL');
    if (to) {
      MailApp.sendEmail({
        to: to,
        subject: `RecipeLens 錯誤回報：${stage || '未知階段'}（${id}）`,
        body: `${report}\n\n版本：${data.version || ''}\n作業系統：${data.os || ''}\n` +
              `試算表：${SpreadsheetApp.getActiveSpreadsheet().getUrl()}`,
      });
    }
    return reply({ ok: true, id: id });
  } catch (err) {
    return reply({ ok: false, error: 'server_error' });
  } finally {
    try { lock.releaseLock(); } catch (err) {}
  }
}

/** 瀏覽器直接開啟網址時顯示，方便確認部署成功。 */
function doGet() {
  return reply({ ok: true, service: 'RecipeLens report receiver' });
}

function sheet() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  let target = book.getSheetByName(SHEET_NAME);
  if (!target) {
    target = book.insertSheet(SHEET_NAME);
    target.appendRow(HEADERS);
    target.setFrozenRows(1);
  }
  return target;
}

function field(report, name) {
  const match = report.match(new RegExp('^' + name + '：(.*)$', 'm'));
  return match ? match[1].trim().slice(0, 64) : '';
}

function clip(value, size) {
  return String(value || '').slice(0, size);
}

function reply(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

/** 在 Apps Script 編輯器手動執行一次，授權試算表與寄信權限並寫入一筆測試資料。 */
function testReceiver() {
  const key = PropertiesService.getScriptProperties().getProperty('REPORT_KEY');
  const result = doPost({ postData: { contents: JSON.stringify({
    key: key, report_id: 'test', version: 'test', os: 'Apps Script',
    report: 'RecipeLens 錯誤報告\nAI 平台：Codex\n階段：測試\n錯誤摘要：\n這是一筆測試資料',
  }) } });
  Logger.log(result.getContent());
}
