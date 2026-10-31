# Google Sheets (optional, ~5 min, one time)

After each run the tables are pushed to a Google Sheet: a ready-to-read tab "Отчёт" (summary cards, colours, filters) and three data tabs "Площадки", "Матрица позиций", "История (все строки)". No service accounts: a small script inside the sheet receives the data.

1. Create an empty Google Sheet -> Extensions -> Apps Script -> paste `Code.gs`, set `SECRET` to a long random password -> save.
2. Deploy -> New deployment -> type "Web app" -> execute as: me, access: anyone -> copy the URL. After changing the code later: Deploy -> Manage deployments -> pencil -> New version.
3. In `.env`: `SHEETS_WEBHOOK_URL=<URL>` and `SHEETS_SECRET=<same password>`.
4. Push without re-analysis: `python run.py --export-only`. A failed push only warns; files in `out/` are always written. If the report tab cannot be built, the error text is written into cell A3 of the "Отчёт" tab.
