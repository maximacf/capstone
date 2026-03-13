// ─────────────────────────────────────────────────────────────────────────────
// Mailgine Evaluation Form — Google Apps Script
//
// HOW TO SET UP (takes ~3 minutes):
//
// 1. Go to https://sheets.google.com → create a new blank spreadsheet
//    Name it "Mailgine Evaluation Results"
//
// 2. In that spreadsheet: Extensions → Apps Script
//
// 3. Delete all existing code and paste EVERYTHING below into the editor
//
// 4. Click Save (💾), then click Deploy → New deployment
//    - Type: Web app
//    - Execute as: Me
//    - Who has access: Anyone
//    → Click Deploy → Copy the Web App URL
//
// 5. Open evaluation_form.html in a text editor
//    Find:  const SHEET_ENDPOINT = 'YOUR_APPS_SCRIPT_URL_HERE'
//    Replace with your copied URL (keep the quotes)
//
// 6. Done! Each form submission creates a new row in your spreadsheet.
//    Share the spreadsheet with your advisor via the normal Google Sheets share button.
// ─────────────────────────────────────────────────────────────────────────────

const SHEET_NAME = 'Responses'

const COLUMNS = [
  'Timestamp',
  'A1 – Emails per day',
  'A2 – Time on email',
  'A3 – Professional context',
  'B1 – Interface clarity',
  'B2 – Understandable without explanation',
  'B3 – Inbox layout organised',
  'B4 – Confident after brief intro',
  'B5 – Suitable for non-technical users',
  'C1 – Categories intuitive',
  'C2 – Classification appeared correct',
  'C3 – Auto-categorisation saves time',
  'D1 – Summaries accurate',
  'D2 – Extracted fields save time',
  'D3 – Draft replies appropriate',
  'D4 – Per-category actions valuable',
  'E1 – Reduces email time',
  'E2 – Improves finding information',
  'E3 – Helps respond faster',
  'E4 – Useful in team environment',
  'E5 – Would use for own email',
  'F1 – Most useful feature',
  'F2 – What to improve',
  'F3 – Additional comments',
]

function doPost(e) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet()
    let sheet = ss.getSheetByName(SHEET_NAME)

    // Create sheet + header row on first run
    if (!sheet) {
      sheet = ss.insertSheet(SHEET_NAME)
      sheet.appendRow(COLUMNS)
      sheet.setFrozenRows(1)
      // Bold the header
      sheet.getRange(1, 1, 1, COLUMNS.length).setFontWeight('bold')
    }

    const data = JSON.parse(e.postData.contents)

    const row = [
      data.submitted_at || new Date().toISOString(),
      data.a1 || '',
      data.a2 || '',
      data.a3 || '',
      data.b1 || '',
      data.b2 || '',
      data.b3 || '',
      data.b4 || '',
      data.b5 || '',
      data.c1 || '',
      data.c2 || '',
      data.c3 || '',
      data.d1 || '',
      data.d2 || '',
      data.d3 || '',
      data.d4 || '',
      data.e1 || '',
      data.e2 || '',
      data.e3 || '',
      data.e4 || '',
      data.e5 || '',
      data.f1 || '',
      data.f2 || '',
      data.f3 || '',
    ]

    sheet.appendRow(row)

    return ContentService
      .createTextOutput(JSON.stringify({ status: 'ok' }))
      .setMimeType(ContentService.MimeType.JSON)

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: 'error', message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON)
  }
}

// Optional: test by running this function manually in the Apps Script editor
function testRow() {
  const fakeEvent = {
    postData: {
      contents: JSON.stringify({
        submitted_at: new Date().toISOString(),
        a1: 'More than 100', a2: '1–2 hours', a3: 'Finance / Banking / Trading',
        b1: '4', b2: '3', b3: '5', b4: '4', b5: '3',
        c1: '5', c2: '4', c3: '5',
        d1: '4', d2: '5', d3: '3', d4: '5',
        e1: '5', e2: '4', e3: '4', e4: '5', e5: '4',
        f1: 'Auto-classification', f2: 'Mobile app', f3: 'Great demo',
      })
    }
  }
  doPost(fakeEvent)
  Logger.log('Test row added. Check your spreadsheet.')
}
