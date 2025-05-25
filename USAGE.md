# PipeCrab Dashboard – Extended Functionality Overview

## Add / Edit Task

- **Task Name** — Display name of the task.
- **Python Script File** — Select a Python file to associate with the task.  
  The file will be copied to `/scripts`; use that copy for further edits and execution.
- **Description** — Optional field. Shown as a tooltip (ⓘ icon) next to the task name.
- **Tags** — Space-separated keywords. Used for filtering in the dashboard.
- **App Icons** — Clickable icons representing task modes and integrations.

### App Mode Options

- **Cron Scheduler** — Runs the script on a schedule based on a cron expression.
- **1-Time Run** — Runs the script once, then automatically disables the task upon completion.
- **Long-running** — For scripts intended to run continuously.  
  *(Filter and classification only — execution logic not implemented yet.)*
- **Docker Container** — For monitoring Docker containers.  
  *(Filter and classification only — execution logic not implemented yet.)*

### Integration Options

- **✓ Email** — Passes the `--email` parameter with a comma-separated list of recipients.  
  Example:  
  ```bash
  python -u script.py --email user@example.com,admin@example.org
  ```

- **✓ Telegram Bot**
  - Select a bot name (configured via `config_telegram.py`) — 🔵 blue icon when selected.
  - Optionally pass a push message with `--push` — 🟠 orange icon when enabled.  
    Example:  
    ```bash
    python -u script.py --bot my_bot --push "Task completed"
    ```

---

## Filter Bar

- Displays all available App icons and all tags used across tasks.
- Clicking icons or tags filters the dashboard view.
- Multiple simultaneous filters are supported.

---

## Dashboard Settings

- **✓ Use SQL Server for task storage** — Configure connection parameters (host, database, user, password, driver).  
  Tasks are stored in the `[dbo].[Tasks]` table.  
  Settings are automatically synchronized *one-way* from SQL → `scripts.json` during:
  - dashboard startup
  - task addition
  - task editing

- **[Import JSON → DB]** — Manually sync all current tasks from `scripts.json` into the SQL `Tasks` table.

---

## Settings Files

- `.env` — Global configuration (SQL, SMTP, etc.)
- `scripts.json` — Local task definitions (used when SQL mode is disabled)
- `config_telegram.py` — Stores Telegram bot tokens and chat IDs

---

## Included Example Scripts

- `nasa_apod_image.py` — Posts NASA Astronomy Picture of the Day (APOD) to Telegram.
- `nasa_day_image.py` — Posts NASA's Image of the Day (from RSS feed) to Telegram.
- `template_notify.py` — A flexible notification script supporting `--bot`, `--email`, and `--push` arguments.

---

