#scripts.py
import os
import shutil
import json
import subprocess
import re
import threading
from dotenv import load_dotenv
load_dotenv(override=True)
from datetime import datetime
from fastapi import APIRouter, HTTPException, Body, UploadFile, File
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError
from app.config_telegram import TELEGRAM_BOTS, DEFAULT_BOT_NAME
from pathlib import Path
from dotenv import dotenv_values
import asyncio
from app.utils.db import save_sql_scripts
from app.utils.db import load_sql_scripts
from cron_descriptor import get_description

TASKS_TABLE_DDL = """
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'Tasks')
                    CREATE TABLE Tasks (
                        Id INT IDENTITY PRIMARY KEY,
                        Name NVARCHAR(255) NOT NULL,
                        Path NVARCHAR(255) NOT NULL,
                        Description NVARCHAR(255),
                        Tags NVARCHAR(100),
                        IsEnabled BIT NOT NULL,
                        UseScheduler BIT NOT NULL DEFAULT 0,
                        CronExpr NVARCHAR(50),
                        CronExprParse NVARCHAR(255),
                        Apps NVARCHAR(255),
                        EmailRecipients NVARCHAR(1000),
                        BotName NVARCHAR(100),
                        PassBotParam BIT NOT NULL DEFAULT 0,
                        PassPushParam BIT NOT NULL DEFAULT 0,
                        PushText NVARCHAR(255),
                        LastUpTime INT NULL,
                        LastLaunchCount INT NULL,
                        ScriptJson NVARCHAR(MAX) CHECK (ISJSON(ScriptJson) > 0),
                        LastUpdated DATETIME DEFAULT GETDATE()
                    )
"""



def get_timestamp():
    return f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

router = APIRouter()
scheduler = BackgroundScheduler()
scheduler.start()

SCRIPTS_JSON_PATH = "scripts.json"
running_processes = {}
stopped_uptime_seconds = {}

class ScriptUpdateRequest(BaseModel):
    id: int | None = None
    old_name: str
    new_name: str
    path: str
    description: str
    tags: str = ""
    apps: list[str] = []
    email_recipients: str = ""
    pass_bot_param: bool = True
    bot_name: str = DEFAULT_BOT_NAME
    schedule_expression: str = "* * * * *"


LOG_LINE_LIMIT = int(os.getenv("LOG_LINE_LIMIT", "1000"))

def append_to_limited_log(log_file_path, new_line, max_lines=LOG_LINE_LIMIT):
    try:
        if os.path.exists(log_file_path):
            with open(log_file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            lines = lines[-(max_lines - 1):]  # keep last (N-1) lines
        else:
            lines = []
        lines.append(new_line + "\n")
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        print(f"[LOGGING] Failed to write to {log_file_path}: {e}")


async def load_scripts():
    use_db = os.getenv("USE_SQL", "false").lower() == "true"

    if use_db:
        return await asyncio.to_thread(load_sql_scripts)

    if not os.path.exists(SCRIPTS_JSON_PATH):
        return []

    try:
        with open(SCRIPTS_JSON_PATH, "r", encoding="utf-8") as f:
            scripts = json.load(f)
            if not isinstance(scripts, list):
                print("[LOAD] scripts.json is not a list")
                return []
            if len(scripts) <= 1:
                print(f"[LOAD WARNING] scripts.json contains {len(scripts)} task(s). Watch for data loss.")
            return scripts
    except Exception as e:
        print(f"[LOAD ERROR] Failed to load scripts.json: {e}")
        return []



async def save_scripts(scripts, original_id=None):
    use_db = os.getenv("USE_SQL", "false").lower() == "true"
    if use_db:
        try:
            return await asyncio.to_thread(save_sql_scripts, scripts, original_id)
        except Exception as e:
            print("[DB SAVE ERROR]", str(e).encode("ascii", errors="replace").decode())
        return

    if not isinstance(scripts, list) or not scripts:
        print("[WARNING] Skipping save_scripts: scripts is empty or not a list")
        return

    # If updating one script in JSON mode
    if original_id is not None:
        if os.path.exists(SCRIPTS_JSON_PATH):
            with open(SCRIPTS_JSON_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        else:
            existing = []

        updated = []
        found = False
        for s in existing:
            if s.get("id") == original_id:
                updated.append(scripts[0])  # replace
                found = True
            else:
                updated.append(s)

        if not found:
            updated.extend(scripts)

        with open(SCRIPTS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2)
        return

    # Default: full overwrite
    with open(SCRIPTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(scripts, f, indent=2)





def launch_cron_script(script_name: str, command: list[str]):
    log_file_path = f"logs/{script_name}.log"
    append_to_limited_log(log_file_path, f"{get_timestamp()} Cron job triggered.")

    try:
        process = subprocess.Popen(command, stdout=open(log_file_path, "a"), stderr=subprocess.STDOUT, text=True)
        append_to_limited_log(log_file_path, f"{get_timestamp()} [MANAGER] Cron-launched PID: {process.pid}")

        # save process to running_processes
        for script in running_processes:
            if running_processes[script]["is_cron_job"] and script_name.lower() in script_name.lower():
                running_processes[script]["process"] = process
                break
    except Exception as e:
        append_to_limited_log(log_file_path, f"{get_timestamp()} [ERROR] Failed to launch script: {e}")



@router.get("/")
async def list_scripts():
    use_sql = os.getenv("USE_SQL", "false").lower() == "true"

    if use_sql:
        from app.utils.db import get_sql_connection
        conn = get_sql_connection()
        if conn is None:
            raise HTTPException(status_code=500, detail="SQL connection failed")

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT Id, Name, Path, Description, Tags, IsEnabled, UseScheduler, CronExpr, CronExprParse, Apps,EmailRecipients, BotName, PassBotParam, PassPushParam, PushText FROM Tasks")
            rows = cursor.fetchall()

            scripts = []
            for row in rows:
                name = row.Name
                log_path = f"logs/{name}.log"
                run_count = 0
                uptime = 0
                has_errors = False
                apps = json.loads(row.Apps or "[]")

                if row.Id in running_processes:
                    status = "running"
                    uptime = int((datetime.utcnow() - running_processes[row.Id]["start_time"]).total_seconds())
                elif row.Id in stopped_uptime_seconds:
                    status = "stopped"
                    uptime = stopped_uptime_seconds[row.Id]
                else:
                    status = "stopped"

                if os.path.exists(log_path):
                    try:
                        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                            log_text = f.read()
                            last_start = log_text.rfind("Task started.")
                            if "scheduler" in apps and last_start != -1:
                                run_count = log_text[last_start:].count("Cron job triggered.")
                            elif "scheduler" in apps:
                                run_count = log_text.count("Cron job triggered.")
                            else:
                                run_count = log_text.count("Script executed.")

                            recent_session = log_text[last_start:] if last_start != -1 else ""
                            if re.search(r"(error|exception|failed|critical|fatal|warning|[a-zA-Z]*Error|[a-zA-Z]*Exception)", recent_session, re.IGNORECASE):
                                has_errors = True
                    except Exception:
                        pass

                scripts.append({
                    "id": row.Id,
                    "name": name,
                    "enabled": row.IsEnabled == 1,
                    "path": row.Path,
                    "description": row.Description,
                    "tags": row.Tags or "",
                    "apps": apps,
                    "email_recipients": row.EmailRecipients or "",
                    "status": status,
                    "uptime_seconds": uptime,
                    "run_count": run_count,
                    "has_errors": has_errors,
                    "schedule_expression": row.CronExpr,
                    "cron_expr_parse": row.CronExprParse,
                    "bot_name": row.BotName,
                    "pass_bot_param": row.PassBotParam,
                    "pass_push_param": getattr(row, "PassPushParam", False),
                    "push_text": getattr(row, "PushText", ""),
                })


            return scripts

        except Exception as e:
            print("[SQL] list_scripts error:", e)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            conn.close()

    # === fallback to JSON ===
    scripts = await load_scripts()
    for script in scripts:
        name = script["name"]
        log_file_path = f"logs/{name}.log"

        if script.get("id") in running_processes:
            script["status"] = "running"
            uptime = datetime.utcnow() - running_processes[script["id"]]["start_time"]
            script["uptime_seconds"] = int(uptime.total_seconds())
        elif script.get("id") in stopped_uptime_seconds:
            script["status"] = "stopped"
            script["uptime_seconds"] = stopped_uptime_seconds[script["id"]]
        else:
            script["status"] = "stopped"
            script["uptime_seconds"] = 0

        script["run_count"] = 0
        if os.path.exists(log_file_path):
            try:
                with open(log_file_path, "r", encoding="utf-8", errors="ignore") as f:
                    log_text = f.read()
                    if "scheduler" in script.get("apps", []):
                        last_start = log_text.rfind("Task started.")
                        if last_start != -1:
                            session_text = log_text[last_start:]
                            script["run_count"] = session_text.count("Cron job triggered.")
                        else:
                            script["run_count"] = log_text.count("Cron job triggered.")
                    else:
                        script["run_count"] = log_text.count("Script executed.")
            except Exception:
                pass

        script["has_errors"] = False
        if os.path.exists(log_file_path):
            try:
                with open(log_file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    sessions = content.split("[")
                    recent_session = next(("[" + sessions[i] + "".join(sessions[i+1:]) for i in range(len(sessions) - 1, -1, -1) if "Task started." in sessions[i]), "")
                    if re.search(r"(error|exception|failed|critical|fatal|warning|[a-zA-Z]*Error|[a-zA-Z]*Exception)", recent_session, re.IGNORECASE):
                        script["has_errors"] = True
            except Exception:
                pass

    return scripts


@router.post("/")
async def add_script(
    name: str = Body(...),
    path: str = Body(...),
    description: str = Body(...),
    tags: str = Body(default=""),
    apps: list[str] = Body(default=[]),
    email_recipients: str = Body(default=""),
    pass_bot_param: bool = Body(default=True),
    bot_name: str = Body(default=DEFAULT_BOT_NAME),
    pass_push_param: bool = Body(default=False),
    push_text: str = Body(default=""),
    schedule_expression: str = Body(default="* * * * *")
):
    scripts = await load_scripts()
    if any(script["name"] == name for script in scripts):
        raise HTTPException(status_code=400, detail="Script with this name already exists.")

    # Create initial object
    new_script = {
        "name": name,
        "path": path,
        "description": description,
        "tags": tags,
        "status": "stopped",
        "apps": apps,
        "email_recipients": email_recipients,
        "pass_bot_param": pass_bot_param,
        "bot_name": bot_name,
        "pass_push_param": pass_push_param,
        "push_text": push_text,
        "schedule_expression": schedule_expression,
        "enabled": False,
        "id": None
    }

    try:
        new_script["cron_expr_parse"] = get_description(schedule_expression)
    except Exception:
        new_script["cron_expr_parse"] = ""

    # Determine destination
    scripts_folder = os.path.abspath("scripts")
    source_path = os.path.abspath(path)
    destination_path = os.path.join(scripts_folder, os.path.basename(path))
    copied_to_scripts = False

    # If outside /scripts, copy it in
    if (
        not os.path.commonpath([source_path, scripts_folder]) == scripts_folder
        and source_path != destination_path
    ):
        os.makedirs(scripts_folder, exist_ok=True)
        try:
            shutil.copy2(source_path, destination_path)
            new_script["path"] = destination_path
            copied_to_scripts = True
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to copy script: {e}")

    # Save script and assign ID
    from app.utils.db import save_sql_scripts
    new_id = await asyncio.to_thread(save_sql_scripts, [new_script])
    new_script["id"] = new_id
    new_script["script_json"] = json.dumps({k: v for k, v in new_script.items() if k != "script_json"})

    await save_scripts([new_script], original_id=new_id)

    # Create log file if not exists
    os.makedirs("logs", exist_ok=True)
    log_file_path = f"logs/{name}.log"
    if not os.path.exists(log_file_path):
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(f"{get_timestamp()} Log file initialized.\n")

    return {"message": f"Script '{name}' added successfully.", "copied_to_scripts": copied_to_scripts}




def log_subprocess_output(pipe, log_file_path):
    for line in iter(pipe.readline, ''):
        if not line:
            break
        append_to_limited_log(log_file_path, line.rstrip())

@router.post("/start/{script_name}")
async def start_script(script_name: str):
    scripts = await load_scripts()
    matching = next((s for s in scripts if s["name"].strip().lower() == script_name.strip().lower()), None)
    if not matching:
        raise HTTPException(status_code=404, detail=f"Script '{script_name}' not found")
    if matching["id"] in running_processes:
        raise HTTPException(status_code=400, detail="Script already running")

    full_path = os.path.abspath(matching["path"])
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Script file does not exist or is invalid")

    os.makedirs("logs", exist_ok=True)
    log_file_path = f"logs/{script_name}.log"
    # command = ["python", "-u", full_path]
    command = [r"C:\Program Files\Python312\python.exe", "-u", full_path]

    if "telegram" in matching.get("apps", []):
        if matching.get("pass_bot_param", True):
            bot_name = matching.get("bot_name", DEFAULT_BOT_NAME)
            command.extend(["--bot", bot_name])

    if matching.get("pass_push_param", False):
        push_text = matching.get("push_text", "").strip()
        if push_text:
            command.extend(["--push", f'"{push_text}"'])

    if "email" in matching.get("apps", []):
        raw = matching.get("email_recipients", "").strip()
        if raw:
            parts = re.split(r"[,\s;]+", raw)
            cleaned = [p.strip() for p in parts if p.strip()]
            command.extend(["--email", ",".join(cleaned)])

    cron_expr = matching.get("schedule_expression", "").strip()
    if cron_expr and "scheduler" in matching.get("apps", []):
        trigger = CronTrigger.from_crontab(cron_expr)
        scheduler.add_job(launch_cron_script, trigger, args=[script_name, command], id=f"{matching['id']}_cron", replace_existing=True)

        running_processes[matching["id"]] = {
            "process": None,
            "start_time": datetime.utcnow(),
            "is_cron_job": True
        }

        append_to_limited_log(log_file_path, f"{get_timestamp()} Task started.")
        append_to_limited_log(log_file_path, f"{get_timestamp()} Launch command: {' '.join(command)}")
        append_to_limited_log(log_file_path, f"{get_timestamp()} [MANAGER] Scheduled script (no PID yet)")

        matching["enabled"] = True
        matching["status"] = "running"
        matching["script_json"] = json.dumps({k: v for k, v in matching.items() if k != "script_json"})
        if isinstance(matching, dict):
            await save_scripts([matching], original_id=matching["id"])

        return {"message": f"Scheduled '{script_name}' via cron"}

    # Standard script launch
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    running_processes[matching["id"]] = {
        "process": process,
        "start_time": datetime.utcnow(),
        "is_cron_job": False
    }

    append_to_limited_log(log_file_path, f"{get_timestamp()} Task started.")
    append_to_limited_log(log_file_path, f"{get_timestamp()} Launch command: {' '.join(command)}")
    append_to_limited_log(log_file_path, f"{get_timestamp()} [MANAGER] Starting process PID: {process.pid}")

    log_thread = threading.Thread(target=log_subprocess_output, args=(process.stdout, log_file_path))
    log_thread.start()

    matching["enabled"] = False if "1timerun" in matching.get("apps", []) else True
    matching["status"] = "running"
    matching["script_json"] = json.dumps({k: v for k, v in matching.items() if k != "script_json"})
    if isinstance(matching, dict):
        await save_scripts([matching], original_id=matching["id"])

    if "1timerun" in matching.get("apps", []):
        def auto_stop():
            try:
                process.wait()
                log_thread.join()
                append_to_limited_log(log_file_path, f"{get_timestamp()} [MANAGER] 1timerun completed, triggering stop.")
                import requests
                port = os.getenv("PORT", "8000")
                requests.post(f"http://127.0.0.1:{port}/scripts/stop/{script_name}")
            except Exception as e:
                append_to_limited_log(log_file_path, f"{get_timestamp()} [ERROR] Auto-stop failed: {e}")

        threading.Thread(target=auto_stop, daemon=True).start()

    return {"message": f"Started script '{script_name}'"}




    

@router.post("/stop/{script_name}")
async def stop_script(script_name: str):
    scripts = await load_scripts()
    matching = next((s for s in scripts if s["name"].strip().lower() == script_name.strip().lower()), None)
    if not matching or matching["id"] not in running_processes:
        raise HTTPException(status_code=400, detail="Script not running")

    info = running_processes.pop(matching["id"])
    log_file_path = f"logs/{script_name}.log"

    if info["is_cron_job"]:
        try:
            scheduler.remove_job(f"{matching['id']}_cron")
        except JobLookupError:
            pass
    else:
        process = info["process"]
        if process and process.poll() is None:
            append_to_limited_log(log_file_path, f"{get_timestamp()} [MANAGER] Sending SIGTERM to PID {process.pid}")
            process.terminate()
            try:
                process.wait(timeout=5)
                append_to_limited_log(log_file_path, f"{get_timestamp()} [MANAGER] Process {process.pid} terminated cleanly.")
            except subprocess.TimeoutExpired:
                append_to_limited_log(log_file_path, f"{get_timestamp()} [MANAGER] WARNING: Process {process.pid} did not terminate in time. Forcing kill.")
                process.kill()

    append_to_limited_log(log_file_path, f"{get_timestamp()} Task stopped.")

    uptime = datetime.utcnow() - info["start_time"]
    stopped_uptime_seconds[matching["id"]] = int(uptime.total_seconds())

    matching["enabled"] = False
    matching["status"] = "stopped"
    matching["script_json"] = json.dumps({k: v for k, v in matching.items() if k != "script_json"})

    if isinstance(matching, dict):
        await save_scripts([matching], original_id=matching["id"])

    use_db = os.getenv("USE_SQL", "false").lower() == "true"
    if use_db:
        from app.utils.db import get_sql_connection
        conn = get_sql_connection()
        if conn:
            try:
                cursor = conn.cursor()
                run_count = matching.get("run_count", 0)
                cursor.execute("""
                    UPDATE Tasks
                    SET IsEnabled = 0,
                        LastUpTime = ?,
                        LastLaunchCount = ?
                    WHERE Id = ?
                """, (
                    int(uptime.total_seconds()),
                    run_count,
                    matching["id"]
                ))
                conn.commit()
            except Exception as e:
                print("[DB] Failed to update script state:", e)
            finally:
                conn.close()

    return {"message": f"Stopped script '{script_name}'"}





@router.get("/logs/{log_type}", response_class=PlainTextResponse)
async def view_logs(log_type: str):
    log_path = f"logs/{log_type}.log"
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file not found")
    with open(log_path, "r", encoding="utf-8") as f:
        return f.read()

@router.post("/clear_log/{script_name}")
async def clear_log(script_name: str):
    path = f"logs/{script_name}.log"
    if os.path.exists(path):
        open(path, "w").close()
    else:
        raise HTTPException(status_code=404, detail="Log file not found")
    return {"message": "Log cleared."}

@router.delete("/delete/{script_id}")
async def delete_script(script_id: int):
    use_db = os.getenv("USE_SQL", "false").lower() == "true"
    script_name = None

    if use_db:
        from app.utils.db import get_sql_connection
        conn = get_sql_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT Name FROM Tasks WHERE Id = ?", script_id)
                row = cursor.fetchone()
                if row:
                    script_name = row.Name
                cursor.execute("DELETE FROM Tasks WHERE Id = ?", script_id)
                conn.commit()
                print(f"[DB] Deleted task with ID: {script_id}")
            except Exception as e:
                print("[DB] Delete error:", e)
                raise HTTPException(status_code=500, detail="Failed to delete script.")
            finally:
                conn.close()
    else:
        scripts = await load_scripts()
        for s in scripts:
            if s.get("id") == script_id:
                script_name = s.get("name")
        scripts = [s for s in scripts if s.get("id") != script_id]
        await save_scripts(scripts)

    # Delete associated log file
    if script_name:
        log_path = f"logs/{script_name}.log"
        try:
            if os.path.exists(log_path):
                os.remove(log_path)
                print(f"[LOG] Deleted log file: {log_path}")
        except Exception as e:
            print(f"[LOG] Failed to delete log file for '{script_name}': {e}")

    return {"message": f"Script with ID {script_id} deleted."}




@router.post("/update")
async def update_script(
    id: int = Body(...),
    old_name: str = Body(...),
    new_name: str = Body(...),
    path: str = Body(...),
    description: str = Body(...),
    tags: str = Body(default=""),
    apps: list[str] = Body(default=[]),
    email_recipients: str = Body(default=""),
    pass_bot_param: bool = Body(default=True),
    bot_name: str = Body(default=DEFAULT_BOT_NAME),
    pass_push_param: bool = Body(default=False),
    push_text: str = Body(default=""),
    schedule_expression: str = Body(default="* * * * *"),
    enabled: bool = Body(default=False)
):
    scripts = await load_scripts()
    script = next((s for s in scripts if s.get("id") == id), None)
    if not script:
        raise HTTPException(status_code=404, detail="Original script not found.")

    if old_name != new_name:
        if any(s["name"] == new_name for s in scripts):
            raise HTTPException(status_code=400, detail="New name already exists.")

    script.update({
        "name": new_name,
        "path": path,
        "description": description,
        "tags": tags,
        "apps": apps,
        "email_recipients": email_recipients,
        "pass_bot_param": pass_bot_param,
        "bot_name": bot_name,
        "pass_push_param": pass_push_param,
        "push_text": push_text,
        "schedule_expression": schedule_expression,
        "enabled": enabled
    })

    try:
        cron_expr = script.get("schedule_expression", "* * * * *")
        script["cron_expr_parse"] = get_description(cron_expr)
    except Exception:
        script["cron_expr_parse"] = ""

    script["script_json"] = json.dumps({k: v for k, v in script.items() if k != "script_json"})
    if isinstance(script, dict):
        await save_scripts([script], original_id=script["id"])

    scripts_folder = os.path.abspath("scripts")
    source_path = os.path.abspath(path)
    destination_path = os.path.join(scripts_folder, os.path.basename(path))

    copied_to_scripts = False
    if (
        not os.path.commonpath([source_path, scripts_folder]) == scripts_folder
        and source_path != destination_path
    ):
        os.makedirs(scripts_folder, exist_ok=True)
        try:
            shutil.copy2(source_path, destination_path)
            script["path"] = destination_path
            script["script_json"] = json.dumps({k: v for k, v in script.items() if k != "script_json"})
            await save_scripts([script], original_id=script["id"])
            copied_to_scripts = True
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to copy script: {e}")

    return {"message": "Script updated.", "copied_to_scripts": copied_to_scripts}


@router.get("/bots")
async def get_telegram_bots():
    return {"bots": list(TELEGRAM_BOTS.keys()), "default_bot": DEFAULT_BOT_NAME}

@router.post("/upload-script")
async def upload_script(file: UploadFile = File(...)):
    os.makedirs("scripts", exist_ok=True)
    filename = os.path.basename(file.filename)
    dest_path = os.path.join("scripts", filename)

    try:
        with open(dest_path, "wb") as f:
            f.write(await file.read())
        return {"message": "Script uploaded", "path": f"scripts/{filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save script: {str(e)}")

@router.post("/copy")
async def copy_script(payload: dict = Body(...)):
    src = payload.get("source_path")
    dst = payload.get("target_name")

    if not src or not dst or not os.path.isfile(src):
        raise HTTPException(status_code=400, detail="Invalid source file.")

    os.makedirs("scripts", exist_ok=True)
    destination = os.path.join("scripts", dst)

    try:
        shutil.copyfile(src, destination)
        return {"message": f"Copied to {destination}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Copy failed: {str(e)}")
    
@router.post("/save-db-config")
async def save_db_config(config: dict):
    env_path = Path(".env")
    env_lines = []

    if env_path.exists():
        with env_path.open("r", encoding="utf-8") as f:
            env_lines = f.readlines()

    updated_keys = {
        "USE_SQL": str(config.get("use_sql", False)),
        "SQL_SERVER": config.get("sql_server", ""),
        "SQL_DATABASE": config.get("sql_database", ""),
        "SQL_USER": config.get("sql_user", ""),
        "SQL_PASSWORD": config.get("sql_password", ""),
        "SQL_DRIVER": config.get("sql_driver", ""),
        "SQL_TRUSTED": str(config.get("sql_trusted", False))
    }

    # Keep existing lines that are not being overwritten
    new_lines = []
    existing_keys = set()

    for line in env_lines:
        key = line.split("=", 1)[0].strip()
        if key in updated_keys:
            new_lines.append(f"{key}={updated_keys[key]}\n")
            existing_keys.add(key)
        else:
            new_lines.append(line)

    for key, val in updated_keys.items():
        if key not in existing_keys:
            new_lines.append(f"{key}={val}\n")

    with env_path.open("w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # Refresh env vars after writing
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path, override=True)

    # After save - create table, if USE_SQL = true
    if updated_keys["USE_SQL"].lower() == "true":
        from app.utils.db import get_sql_connection
        conn = get_sql_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(TASKS_TABLE_DDL)
                conn.commit()
                print("[DB] Tasks table created (if not exists)")
            except Exception as e:
                print("[DB] Failed to create Tasks table:", e)
            finally:
                conn.close()

    return {"status": "ok"}


@router.post("/debug-sql")
async def debug_sql_connection(config: dict = Body(...)):
    from app.utils.db import get_sql_connection
    import pyodbc

    cleaned_config = {k: v for k, v in config.items() if k != "use_sql"}
    # print("[DEBUG] SQL config received:", cleaned_config)

    os.environ["SQL_SERVER"] = config.get("sql_server", "")
    os.environ["SQL_DATABASE"] = config.get("sql_database", "")
    os.environ["SQL_USER"] = config.get("sql_user", "")
    os.environ["SQL_PASSWORD"] = config.get("sql_password", "")
    os.environ["SQL_DRIVER"] = config.get("sql_driver", "")
    os.environ["SQL_TRUSTED"] = str(config.get("sql_trusted", False))

    try:
        conn = get_sql_connection(use_env_override=True)
        if not conn:
            raise ConnectionError("get_sql_connection() returned None — possibly invalid driver or connection string.")

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_NAME = 'Tasks'
            """)
            exists = cursor.fetchone()[0] > 0
            message = "Connected successfully." if exists else "Connected. Table 'Tasks' not found and will be created on save."
            return {"status": "connected", "message": message}
        except Exception as e:
            return {"status": "error", "message": f"Connected, but failed to query table: {str(e)}"}
        finally:
            conn.close()

    except pyodbc.Error as e:
        err_msg = f"{e.__class__.__name__}: {'; '.join(str(x) for x in e.args)}"
        return {"status": "error", "message": f"Connection failed: {err_msg}"}

    except Exception as e:
        return {"status": "error", "message": f"Unhandled connection error: {str(e)}"}




async def autostart_enabled_scripts():
    scripts = await load_scripts()
    for script in scripts:
        if script.get("enabled", False):


            try:
                await start_script(script["name"])
                print(f"[AUTO-START] Started: {script['name']}")
            except Exception as e:
                print(f"[AUTO-START FAIL] {script['name']}: {str(e)}")


@router.post("/import-from-json")
async def import_from_json_to_sql():
    if not os.getenv("USE_SQL", "false").lower() == "true":
        raise HTTPException(status_code=400, detail="SQL is not enabled.")

    if not os.path.exists(SCRIPTS_JSON_PATH):
        raise HTTPException(status_code=404, detail="scripts.json not found")

    try:
        with open(SCRIPTS_JSON_PATH, "r", encoding="utf-8") as f:
            scripts = json.load(f)
        from app.utils.db import save_sql_scripts
        await asyncio.to_thread(save_sql_scripts, scripts)
        return {"message": f"Imported {len(scripts)} scripts into SQL."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.get("/preview-json")
async def preview_json_script_count():
    if not os.path.exists(SCRIPTS_JSON_PATH):
        raise HTTPException(status_code=404, detail="scripts.json not found")
    try:
        with open(SCRIPTS_JSON_PATH, "r", encoding="utf-8") as f:
            scripts = json.load(f)
        return {"count": len(scripts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read JSON: {str(e)}")
    
@router.get("/db-config")
async def get_db_config():
    config = {
        "use_sql": os.getenv("USE_SQL", "false").lower() == "true",
        "sql_server": os.getenv("SQL_SERVER", ""),
        "sql_database": os.getenv("SQL_DATABASE", ""),
        "sql_user": os.getenv("SQL_USER", ""),
        "sql_password": os.getenv("SQL_PASSWORD", ""),
        "sql_driver": os.getenv("SQL_DRIVER", ""),
        "sql_trusted": os.getenv("SQL_TRUSTED", "false").lower() == "true",
    }
    # print("[DEBUG] SQL config received:", config)
    return JSONResponse(content=config)

@router.on_event("startup")
async def sync_sql_to_json_on_start():
    from app.utils.db import load_sql_scripts
    from dotenv import load_dotenv

    load_dotenv(override=True)  # Ensure .env is loaded before use

    if os.getenv("USE_SQL", "false").lower() == "true":
        try:
            scripts = await asyncio.to_thread(lambda: load_sql_scripts(use_env_override=True))
            if scripts:
                with open("scripts.json", "w", encoding="utf-8") as f:
                    json.dump(scripts, f, indent=2, ensure_ascii=True)
                print("[SYNC] SQL scripts.json on startup")
            else:
                print("[SYNC] No scripts found in SQL.")
        except Exception as e:
            print("[SYNC ERROR] Could not dump SQL to JSON:", e)






