#!/usr/bin/env python3
"""One-click launcher for the manager (started by "Обновить данные.bat").
Asks one simple question when data for today already exists, runs the program, opens the report."""
import os
import sqlite3
import sys
import webbrowser

import run

DB = os.path.join(run.ROOT, "data", "serp.db")
REPORT = os.path.join(run.ROOT, "out", "report.html")


def stored_today():
    """How many unique URLs are already stored for today (0 if none / no database)."""
    if not os.path.exists(DB):
        return 0
    db = sqlite3.connect(DB)
    try:
        return db.execute("SELECT COUNT(DISTINCT url) FROM serp_results WHERE date=?", (run.today_utc(),)).fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        db.close()


def choose(have, ask=input):
    """Returns the arguments for run.main(), or None to quit."""
    if have:
        print(f"\nСегодня данные уже собраны ({have} адресов сайтов).\n")
        print("  1 - Только обновить отчёт и Google Таблицу (бесплатно, 1 минута)")
        print("  2 - Собрать всё заново (тратит ~10 кредитов SerpApi и ~$0.07 на ИИ, 5-15 минут)")
        print("  3 - Добрать только ключевые слова, по которым данных ещё нет")
        print("  0 - Выйти\n")
        choice = ""
        while choice not in ("0", "1", "2", "3"):
            choice = ask("Введите цифру и нажмите Enter: ").strip()
        return {"0": None, "1": ["--export-only"], "2": [], "3": ["--missing"]}[choice]
    print("\nСегодня данных ещё нет. Будет собран свежий топ-10 Google по всем ключам:")
    print("тратится ~10 кредитов SerpApi и ~$0.07 на ИИ, 5-15 минут.\n")
    answer = ask("Запустить? Введите д (да) или н (нет) и нажмите Enter: ").strip().lower()
    return [] if answer in ("д", "да", "y", "yes") else None


def main():
    args = choose(stored_today())
    if args is None:
        print("Отменено, ничего не запускалось.")
        return 0
    print("\nРаботаю. Окно не закрывайте, ход работы пишется ниже...\n")
    code = run.main(args)
    if os.path.exists(REPORT):
        webbrowser.open("file:///" + REPORT.replace("\\", "/"))
    print("\nГотово. Отчёт открыт в браузере (out\\report.html)." if code == 0
          else "\nЗавершено с ошибками, см. строки ERROR выше. Отчёт открыт с тем, что удалось собрать.")
    return code


if __name__ == "__main__":
    sys.exit(main())
