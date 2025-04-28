# PipeCrab Dashboard

[![Experimental Project](https://img.shields.io/badge/Status-Experimental-blueviolet)]() [![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-brightgreen?logo=fastapi)](https://fastapi.tiangolo.com/)

**PipeCrab Dashboard** is a lightweight experimental dashboard for managing and monitoring Python scripts.

It lets you:

- Add tasks and launch them manually or on a cron schedule.
- Monitor uptime and count script launches.
- View detailed logs with real-time updates and error highlighting.
- Connect Telegram bots to your scripts for extra control and notifications.

Two sample scripts are included:

- Posting NASA's Astronomy Picture of the Day (APOD) to Telegram.
- Posting NASA's Image of the Day (from RSS feed) to Telegram.

---

## Screenshots

![](assets/dashboard.png)

---

## Key Features

- Simple script management with start/stop toggles.
- Cron scheduling support per task.
- Uptime tracking and launch counters for each task.
- Log viewer with real-time updates and error highlighting.
- Telegram bot support (optional per script).
- Clean UI with Bootstrap 5, including dark/light theme toggle.

---

## Tech Stack

- **Backend:** FastAPI + Uvicorn
- **Frontend:** HTML + Bootstrap 5 + Vanilla JavaScript + Axios

---

## Requirements

- Python 3.10 or higher
- Installed project dependencies (`pip install -r requirements.txt`)

Run via `start.bat` (Windows) or manually:

```bash
python -m uvicorn app.main:app --reload
```

Once running, access the dashboard at [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)

## Purpose

- The dashboard was created as a learning tool to explore backend/frontend integration, subprocess management, real-time updates, and dashboard design.

---

Crafted with care. Moving forward to new challenges.
