/**
 * Receiver for the SERP MVP. The Python program POSTs the tables here (see apps_script/README.md).
 * It writes three data tabs ("Площадки", "Матрица позиций", "История (все строки)") and rebuilds
 * the first tab "Отчёт": a ready-to-read summary for a manager. Same secret as SHEETS_SECRET in .env.
 */
const SECRET = 'PUT-A-LONG-RANDOM-STRING-HERE';
const NAVY = '#1f2a44', GREY = '#6b7280', LINE = '#e5e7eb', FONT = 'Roboto';
const GREEN = '#d9f2e3', RED = '#fde2e0', YELLOW = '#fff3c4';
const NO_CONTACT = 'Не подтверждён';
const TYPE_RU = {review_rating: 'Обзор / рейтинг', blog_news: 'Блог / новости', operator: 'Оператор казино',
  encyclopedia: 'Справочник', forum_social: 'Форум / соцсети', other: 'Другое'};

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    if (data.secret !== SECRET) return out_({ok: false, error: 'wrong secret'});
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let total = 0;
    data.tabs.forEach(function (tab) { writeData_(ss, tab); total += tab.rows.length; });
    let reportError = '';
    try { buildReport_(ss, data.tabs[0]); } catch (err) {
      reportError = String(err);
      try { ss.getSheetByName('Отчёт').getRange('A3').setValue('Ошибка при построении отчёта: ' + reportError); } catch (e2) {}
    }
    return out_({ok: true, rows: total, reportError: reportError, updated: new Date().toISOString()});
  } catch (err) {
    return out_({ok: false, error: String(err)});
  }
}

function doGet() { return out_({ok: true, info: 'SERP MVP receiver is running; data is sent with POST'}); }
function out_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

// ---- data tabs: plain, but tidy
function writeData_(ss, tab) {
  const sh = ss.getSheetByName(tab.name) || ss.insertSheet(tab.name);
  if (sh.getFilter()) sh.getFilter().remove();
  sh.clear();
  const values = [tab.header].concat(tab.rows), cols = tab.header.length;
  sh.getRange(1, 1, values.length, cols).setValues(values).setFontFamily(FONT).setVerticalAlignment('top');
  sh.getRange(1, 1, 1, cols).setFontWeight('bold').setFontColor('#ffffff').setBackground(NAVY);
  sh.setFrozenRows(1);
  sh.getRange(1, 1, values.length, cols).createFilter();
  sh.autoResizeColumns(1, cols);
}

// ---- the report tab
function buildReport_(ss, src) {
  const H = {};
  src.header.forEach(function (h, i) { H[h] = i; });
  const get = function (r, k) { const v = r[H[k]]; return v === undefined || v === null ? '' : String(v); };
  const rows = src.rows.slice().sort(function (a, b) {                       // suitable first, then by best position
    const ra = get(a, 'relevant') === 'yes' ? 0 : 1, rb = get(b, 'relevant') === 'yes' ? 0 : 1;
    return ra - rb || (Number(get(a, 'best_position')) || 99) - (Number(get(b, 'best_position')) || 99);
  });
  const good = rows.filter(function (r) { return get(r, 'relevant') === 'yes'; });
  const withContact = good.filter(function (r) { const c = get(r, 'contact'); return c && c !== NO_CONTACT; });
  const toCheck = good.filter(function (r) { return get(r, 'basis') !== 'page'; });

  let sh = ss.getSheetByName('Отчёт');
  if (!sh) sh = ss.insertSheet('Отчёт', 0);
  if (sh.getFilter()) sh.getFilter().remove();
  sh.setFrozenRows(0); sh.setFrozenColumns(0);                               // merged cards cannot cross a frozen border
  sh.getRange(1, 1, sh.getMaxRows(), sh.getMaxColumns()).breakApart().clearDataValidations().clearNote();
  sh.clear(); sh.clearConditionalFormatRules();
  const NC = 9, TOP = 6;                                                      // table header is on row 6
  const widths = [210, 280, 100, 140, 330, 210, 80, 250, 110];
  widths.forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });
  sh.getRange(1, 1, TOP + rows.length, NC).setFontFamily(FONT).setFontSize(10).setVerticalAlignment('middle');
  sh.setHiddenGridlines(true);

  sh.getRange('A1').setValue('Площадки для размещения: Google.ca (mobile), топ-10').setFontSize(18).setFontWeight('bold').setFontColor(NAVY);
  sh.getRange('A2').setValue('Обновлено ' + Utilities.formatDate(new Date(), ss.getSpreadsheetTimeZone(), 'dd.MM.yyyy HH:mm') +
    '. Вкладка собирается автоматически: фильтры в шапке таблицы, свои версии делайте копией вкладки.').setFontColor(GREY);

  // four summary cards: label (row 3) + big number (row 4)
  [['A', 'B', 'Найдено сайтов', rows.length], ['C', 'D', 'Подходят для размещения', good.length],
   ['E', 'F', 'Из них есть контакт', withContact.length], ['G', 'I', 'Проверить вручную', toCheck.length]].forEach(function (c) {
    const label = sh.getRange(c[0] + '3:' + c[1] + '3').merge().setValue(c[2]).setFontColor(GREY).setFontSize(9);
    const num = sh.getRange(c[0] + '4:' + c[1] + '4').merge().setValue(c[3]).setFontSize(24).setFontWeight('bold').setFontColor(NAVY);
    sh.getRange(c[0] + '3:' + c[1] + '4').setBackground('#f3f4f8').setHorizontalAlignment('left')
      .setBorder(true, true, true, true, false, false, '#ffffff', SpreadsheetApp.BorderStyle.SOLID_THICK);
  });
  sh.getRange('A5').setValue('«Проверить вручную» = решение принято только по заголовку и описанию из Google: страница не открылась.')
    .setFontColor(GREY).setFontSize(9);
  sh.setRowHeight(4, 40);

  const heads = ['Сайт', 'О чём страница', 'Подходит?', 'Тип страницы', 'Бренды на странице', 'Контакт', 'Позиция', 'По каким запросам', 'Решение'];
  sh.getRange(TOP, 1, 1, NC).setValues([heads]).setBackground(NAVY).setFontColor('#ffffff').setFontWeight('bold');
  sh.setRowHeight(TOP, 34);
  if (!rows.length) return;

  const site = [], contact = [], plain = [], bg = [];
  rows.forEach(function (r, i) {
    const url = get(r, 'url'), dom = get(r, 'domain');
    const path = url.replace(/^https?:\/\/[^\/]+/, '').replace(/\/$/, '');
    const text = path ? dom + '\n' + path : dom;
    const b = SpreadsheetApp.newRichTextValue().setText(text).setLinkUrl(url)
      .setTextStyle(0, dom.length, SpreadsheetApp.newTextStyle().setBold(true).setForegroundColor('#1a56db').setUnderline(false).build());
    if (path) b.setTextStyle(dom.length + 1, text.length, SpreadsheetApp.newTextStyle().setForegroundColor(GREY).setFontSize(8).setUnderline(false).build());
    site.push([b.build()]);

    const c = get(r, 'contact'), ok = get(r, 'relevant') === 'yes';
    const cv = SpreadsheetApp.newRichTextValue();
    if (!c || c === NO_CONTACT) {
      const none = ok ? NO_CONTACT : '—';
      cv.setText(none).setTextStyle(0, none.length, SpreadsheetApp.newTextStyle().setForegroundColor('#9ca3af').build());
    }
    else if (c.indexOf('@') > 0 && c.indexOf('http') !== 0) cv.setText(c).setLinkUrl('mailto:' + c);
    else cv.setText('Страница контактов').setLinkUrl(c);
    contact.push([cv.build()]);

    const brands = get(r, 'brands').split(';').map(function (x) { return x.trim(); }).filter(String);
    const shown = brands.slice(0, 5).join(' · ') + (brands.length > 5 ? '  + ещё ' + (brands.length - 5) : '');
    const low = get(r, 'basis') !== 'page';
    plain.push([get(r, 'title'), ok ? '✓ Да' : '✗ Нет', TYPE_RU[get(r, 'category')] || get(r, 'category'), shown,
                Number(get(r, 'best_position')) || '', get(r, 'keywords').split('; ').join('\n'),
                low ? 'По описанию' : 'По странице']);
    const row = new Array(NC).fill(i % 2 ? '#fafafa' : '#ffffff');
    row[2] = ok ? GREEN : RED;
    row[8] = low ? YELLOW : row[8];
    bg.push(row);
  });
  const n = rows.length, F = TOP + 1;
  sh.getRange(F, 1, n, NC).setBackgrounds(bg).setWrap(true).setVerticalAlignment('middle')
    .setBorder(null, null, true, null, null, null, LINE, SpreadsheetApp.BorderStyle.SOLID);
  sh.getRange(F, 1, n, 1).setRichTextValues(site);
  sh.getRange(F, 6, n, 1).setRichTextValues(contact);
  const col = function (k) { return plain.map(function (p) { return [p[k]]; }); };
  sh.getRange(F, 2, n, 1).setValues(col(0));
  sh.getRange(F, 3, n, 1).setValues(col(1)).setFontWeight('bold').setHorizontalAlignment('center');
  sh.getRange(F, 4, n, 1).setValues(col(2));
  sh.getRange(F, 5, n, 1).setValues(col(3));
  sh.getRange(F, 7, n, 1).setValues(col(4)).setFontWeight('bold').setHorizontalAlignment('center');
  sh.getRange(F, 8, n, 1).setValues(col(5)).setFontSize(9).setFontColor(GREY);
  sh.getRange(F, 9, n, 1).setValues(col(6)).setHorizontalAlignment('center').setFontSize(9);
  sh.getRange(TOP, 1, n + 1, NC).createFilter();
  sh.setFrozenRows(TOP);
  try { sh.autoResizeRows(F, n); } catch (e) {}
  ss.setActiveSheet(sh);
}
