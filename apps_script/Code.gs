/**
 * Receiver for the SERP MVP: the Python program POSTs the report tables here and this script
 * writes them into THIS Google Sheet. Raw tabs: "Площадки", "Матрица позиций", "История (все строки)".
 * After every upload the nice tab "Отчёт" is rebuilt from them (do not edit it by hand: copy it to
 * your own tab if you want a personal version).
 *
 * Setup: see README, section "Google Таблица". Put the same secret in .env as SHEETS_SECRET.
 */
const SECRET = 'PUT-A-LONG-RANDOM-STRING-HERE';

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    if (data.secret !== SECRET) return out_({ok: false, error: 'wrong secret'});
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let rowsTotal = 0;
    data.tabs.forEach(function (tab) {
      let sheet = ss.getSheetByName(tab.name) || ss.insertSheet(tab.name);
      sheet.clear();
      const values = [tab.header].concat(tab.rows);
      sheet.getRange(1, 1, values.length, tab.header.length).setValues(values);
      sheet.getRange(1, 1, values.length, tab.header.length).setFontWeight('bold').setBackground('#e8eaed');
      sheet.getRange(2, 1, Math.max(values.length - 1, 1), tab.header.length).setFontWeight('normal').setBackground(null);
      sheet.setFrozenRows(1);
      if (sheet.getFilter()) sheet.getFilter().remove();
      sheet.getRange(1, 1, values.length, tab.header.length).createFilter();
      sheet.autoResizeColumns(1, tab.header.length);
      rowsTotal += tab.rows.length;
    });
    let reportError = '';
    try { buildReport_(ss, data.tabs[0]); } catch (err) { reportError = String(err); }
    return out_({ok: true, rows: rowsTotal, updated: new Date().toISOString(), reportError: reportError});
  } catch (err) {
    return out_({ok: false, error: String(err)});
  }
}

function doGet() { return out_({ok: true, info: 'SERP MVP receiver is running; data is sent with POST'}); }

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// ----------------------------------------------------------------------------- nice report tab
const NO_CONTACT = 'Не подтверждён';
const CATEGORY_RU = {review_rating: 'Обзор / рейтинг', blog_news: 'Блог / новости', operator: 'Оператор казино',
  encyclopedia: 'Энциклопедия', forum_social: 'Форум / соцсети', other: 'Другое'};
const CONF_RU = {high: 'Высокая', medium: 'Средняя', low: 'Низкая'};
const NAVY = '#1f2a44', GREY = '#80868b', BAND = '#f6f8fb';

function buildReport_(ss, src) {
  const H = {};
  src.header.forEach(function (h, i) { H[h] = i; });
  const rows = src.rows;
  const g = function (r, k) { var v = r[H[k]]; return v === undefined || v === null ? '' : String(v); };

  let sh = ss.getSheetByName('Отчёт');
  if (sh) {
    if (sh.getFilter()) sh.getFilter().remove();
    sh.clear(); sh.clearConditionalFormatRules();
  } else {
    sh = ss.insertSheet('Отчёт', 0);
  }
  const heads = ['Сайт', 'Заголовок', 'Релевантен', 'Тип страницы', 'Бренды на странице', 'Брендов', 'Контакт',
                 'Уверенность', 'Лучшая поз.', 'Ключи и позиции'];
  const widths = [200, 280, 95, 130, 400, 70, 190, 100, 90, 270];
  const NC = heads.length, HEAD_ROW = 5, FIRST = 6;

  // numbers for the summary line
  const relevant = rows.filter(function (r) { return g(r, 'relevant') === 'yes'; });
  const withContact = relevant.filter(function (r) { var c = g(r, 'contact'); return c && c !== NO_CONTACT; });
  const withBrands = relevant.filter(function (r) { return g(r, 'brands'); });

  sh.getRange('A1').setValue('Площадки для размещения: Google.ca (mobile), топ-10')
    .setFontSize(16).setFontWeight('bold').setFontColor(NAVY);
  sh.getRange('A2').setValue('Обновлено: ' + Utilities.formatDate(new Date(), ss.getSpreadsheetTimeZone(), 'dd.MM.yyyy HH:mm') +
    '. Эта вкладка собирается автоматически при каждой выгрузке: фильтруйте стрелочками в шапке, а свои версии делайте копией вкладки.')
    .setFontColor(GREY).setFontStyle('italic');
  sh.getRange('A3').setValue('Всего URL: ' + rows.length + '   ·   Релевантных: ' + relevant.length +
    '   ·   С контактом: ' + withContact.length + '   ·   С брендами: ' + withBrands.length)
    .setFontWeight('bold').setFontColor(NAVY);

  sh.getRange(HEAD_ROW, 1, 1, NC).setValues([heads]).setFontWeight('bold').setFontColor('#ffffff')
    .setBackground(NAVY).setVerticalAlignment('middle');

  if (rows.length) {
    const site = [], contact = [], plain = [], bg = [];
    rows.forEach(function (r, i) {
      const url = g(r, 'url');
      let path = '';
      try { path = url.replace(/^https?:\/\/[^\/]+/, '').replace(/\/$/, ''); } catch (e) {}
      const dom = g(r, 'domain');
      const text = path ? dom + '\n' + path : dom;
      const rtv = SpreadsheetApp.newRichTextValue().setText(text).setLinkUrl(url);
      if (path) {
        rtv.setTextStyle(dom.length + 1, text.length, SpreadsheetApp.newTextStyle().setForegroundColor(GREY).setFontSize(8).setUnderline(false).build());
      }
      rtv.setTextStyle(0, dom.length, SpreadsheetApp.newTextStyle().setBold(true).setForegroundColor('#1a56db').setUnderline(false).build());
      site.push([rtv.build()]);

      const c = g(r, 'contact');
      let cv;
      if (!c || c === NO_CONTACT) {
        cv = SpreadsheetApp.newRichTextValue().setText(c === NO_CONTACT ? NO_CONTACT : '').setTextStyle(0, NO_CONTACT.length,
          SpreadsheetApp.newTextStyle().setForegroundColor('#9aa0a6').build()).build();
        if (!c) cv = SpreadsheetApp.newRichTextValue().setText('').build();
      } else if (c.indexOf('@') > 0 && c.indexOf('http') !== 0) {
        cv = SpreadsheetApp.newRichTextValue().setText(c).setLinkUrl('mailto:' + c).build();
      } else {
        cv = SpreadsheetApp.newRichTextValue().setText('Страница контактов').setLinkUrl(c).build();
      }
      contact.push([cv]);

      const brandList = g(r, 'brands').split(';').map(function (b) { return b.trim(); }).filter(String);
      const shown = brandList.slice(0, 6).join(' · ') + (brandList.length > 6 ? '  … ещё ' + (brandList.length - 6) : '');
      const isRel = g(r, 'relevant') === 'yes';
      const pos = Number(g(r, 'best_position'));
      plain.push([g(r, 'title'), isRel ? 'Да' : 'Нет', CATEGORY_RU[g(r, 'category')] || g(r, 'category'), shown,
                  brandList.length || '', CONF_RU[g(r, 'confidence')] || g(r, 'confidence'), isNaN(pos) ? '' : pos,
                  g(r, 'keywords')]);
      const base = i % 2 ? BAND : '#ffffff';
      const row = new Array(NC).fill(base);
      row[2] = isRel ? '#e6f4ea' : '#fce8e6';
      const conf = g(r, 'confidence');
      row[7] = conf === 'high' ? '#e6f4ea' : conf === 'medium' ? '#fef7e0' : '#fce8e6';
      bg.push(row);
    });
    const n = rows.length;
    sh.getRange(FIRST, 1, n, NC).setBackgrounds(bg).setVerticalAlignment('top').setWrap(true).setFontSize(10);
    sh.getRange(FIRST, 1, n, 1).setRichTextValues(site);
    sh.getRange(FIRST, 7, n, 1).setRichTextValues(contact);
    // plain columns: B title, C relevant, D type, E brands, F count, H confidence, I position, J keywords
    const col = function (k) { return plain.map(function (p) { return [p[k]]; }); };
    sh.getRange(FIRST, 2, n, 1).setValues(col(0));
    sh.getRange(FIRST, 3, n, 1).setValues(col(1)).setHorizontalAlignment('center').setFontWeight('bold');
    sh.getRange(FIRST, 4, n, 1).setValues(col(2));
    sh.getRange(FIRST, 5, n, 1).setValues(col(3));
    sh.getRange(FIRST, 6, n, 1).setValues(col(4)).setHorizontalAlignment('center');
    sh.getRange(FIRST, 8, n, 1).setValues(col(5)).setHorizontalAlignment('center');
    sh.getRange(FIRST, 9, n, 1).setValues(col(6)).setHorizontalAlignment('center').setFontWeight('bold');
    sh.getRange(FIRST, 10, n, 1).setValues(col(7));
    sh.getRange(HEAD_ROW, 1, n + 1, NC).createFilter();
  }
  widths.forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });
  sh.setRowHeight(HEAD_ROW, 30);
  sh.setFrozenRows(HEAD_ROW);
  sh.setFrozenColumns(1);
  sh.setHiddenGridlines(true);
  try { sh.autoResizeRows(FIRST, Math.max(rows.length, 1)); } catch (e) {}
  ss.setActiveSheet(sh);
}
