# Google Sheets (optional, ~5 min, one time)

After each run the same tables can be pushed to a Google Sheet (tabs "Площадки", "Матрица позиций", "История (все строки)"). No service accounts: a small script inside the sheet receives the data.

1. Create an empty Google Sheet -> Extensions -> Apps Script -> paste `Code.gs`, set `SECRET` to a long random password -> save.
2. Deploy -> New deployment -> type "Web app" -> execute as: me, access: anyone -> copy the URL.
3. In `.env`: `SHEETS_WEBHOOK_URL=<URL>` and `SHEETS_SECRET=<same password>`.
4. Push without re-analysis: `python run.py --export-only`. A failed push only warns; files in `out/` are always written.
