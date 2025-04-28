import sys
import os
import shutil
import json
import subprocess
import re
import threading
from datetime import datetime
from fastapi import APIRouter, HTTPException, Body, UploadFile, File
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError
from app.config_telegram import TELEGRAM_BOTS, DEFAULT_BOT_NAME

def get_timestamp():
    return f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

router = APIRouter()
scheduler = BackgroundScheduler()
scheduler.start()

SCRIPTS_JSON_PATH = "scripts.json"
running_processes = {}
stopped_uptime_seconds = {}

class ScriptUpdateRequest(BaseModel):
    old_name: str
    new_name: str
    path: str
    description: str
    apps: list[str] = []
    pass_bot_param: bool = True
    bot_name: str = DEFAULT_BOT_NAME
    schedule_expression: str = "* * * * *"

def load_scripts():
    if not os.path.exists(SCRIPTS_JSON_PATH):
        return []
    with open(SCRIPTS_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_scripts(scripts):
    with open(SCRIPTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(scripts, f, indent=2)

def launch_cron_script(script_name: str, command: list[str]):
    log_file_path = f"logs/{script_name}.log"
    with open(log_file_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"{get_timestamp()} Cron job triggered.\n")
    subprocess.Popen(command, stdout=open(log_file_path, "a"), stderr=subprocess.STDOUT, text=True)

@router.get("/")
async def list_scripts():
    scripts = load_scripts()
    for script in scripts:
        name = script["name"]
        log_file_path = f"logs/{name}.log"

        if name in running_processes:
            script["status"] = "running"
            uptime = datetime.utcnow() - running_processes[name]["start_time"]
            script["uptime_seconds"] = int(uptime.total_seconds())
        elif name in stopped_uptime_seconds:
            script["status"] = "stopped"
            script["uptime_seconds"] = stopped_uptime_seconds[name]
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
    apps: list[str] = Body(default=[]),
    pass_bot_param: bool = Body(default=True),
    bot_name: str = Body(default=DEFAULT_BOT_NAME),
    schedule_expression: str = Body(default="* * * * *")
):
    scripts = load_scripts()
    if any(script["name"] == name for script in scripts):
        raise HTTPException(status_code=400, detail="Script with this name already exists.")

    new_script = {
        "name": name,
        "path": path,
        "description": description,
        "status": "stopped",
        "apps": apps,
        "pass_bot_param": pass_bot_param,
        "bot_name": bot_name,
        "schedule_expression": schedule_expression
    }

    scripts.append(new_script)
    save_scripts(scripts)

    os.makedirs("logs", exist_ok=True)
    log_file_path = f"logs/{name}.log"
    if not os.path.exists(log_file_path):
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(f"{get_timestamp()} Log file initialized.\n")

    return {"message": f"Script '{name}' added successfully."}

def log_subprocess_output(pipe, log_file_path):
    with open(log_file_path, "a", encoding="utf-8") as log_file:
        for line in iter(pipe.readline, ''):
            if not line:
                break
            log_file.write(line)
            log_file.flush()

@router.post("/start/{script_name}")
async def start_script(script_name: str):
    scripts = load_scripts()
    matching = next((s for s in scripts if s["name"] == script_name), None)
    if not matching:
        raise HTTPException(status_code=404, detail="Script not found")

    if script_name in running_processes:
        raise HTTPException(status_code=400, detail="Script already running")

    full_path = os.path.abspath(matching["path"])
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Script file does not exist or is invalid")

    os.makedirs("logs", exist_ok=True)
    log_file_path = f"logs/{script_name}.log"
    command = ["python", full_path]

    if "telegram" in matching.get("apps", []):
        if matching.get("pass_bot_param", True):
            bot_name = matching.get("bot_name", DEFAULT_BOT_NAME)
            command.extend(["--bot", bot_name])

    cron_expr = matching.get("schedule_expression", "").strip()
    if cron_expr:
        trigger = CronTrigger.from_crontab(cron_expr)
        scheduler.add_job(launch_cron_script, trigger, args=[script_name, command], id=f"{script_name}_cron", replace_existing=True)

        running_processes[script_name] = {
            "process": None,
            "start_time": datetime.utcnow(),
            "is_cron_job": True
        }

        with open(log_file_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"{get_timestamp()} Task started.\n")
            log_file.write(f"{get_timestamp()} Cron schedule registered: {cron_expr}\n")

        return {"message": f"Scheduled '{script_name}' via cron"}

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    running_processes[script_name] = {
        "process": process,
        "start_time": datetime.utcnow(),
        "is_cron_job": False
    }

    with open(log_file_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"{get_timestamp()} Task started.\n")
        log_file.write(f"{get_timestamp()} Launch command: {' '.join(command)}\n")

    threading.Thread(target=log_subprocess_output, args=(process.stdout, log_file_path), daemon=True).start()

    return {"message": f"Started script '{script_name}'"}

@router.post("/stop/{script_name}")
async def stop_script(script_name: str):
    if script_name not in running_processes:
        raise HTTPException(status_code=400, detail="Script not running")

    info = running_processes.pop(script_name)
    log_file_path = f"logs/{script_name}.log"

    if info["is_cron_job"]:
        try:
            scheduler.remove_job(f"{script_name}_cron")
        except JobLookupError:
            pass
    else:
        process = info["process"]
        if process and process.poll() is None:
            process.terminate()

    with open(log_file_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"{get_timestamp()} Task stopped.\n")

    uptime = datetime.utcnow() - info["start_time"]
    stopped_uptime_seconds[script_name] = int(uptime.total_seconds())


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

@router.delete("/delete/{script_name}")
async def delete_script(script_name: str):
    scripts = load_scripts()
    scripts = [s for s in scripts if s["name"] != script_name]
    save_scripts(scripts)
    return {"message": f"Script '{script_name}' deleted."}

@router.post("/update")
async def update_script(update_request: ScriptUpdateRequest):
    scripts = load_scripts()
    script = next((s for s in scripts if s["name"] == update_request.old_name), None)
    if not script:
        raise HTTPException(status_code=404, detail="Original script not found.")

    if update_request.old_name != update_request.new_name:
        if any(s["name"] == update_request.new_name for s in scripts):
            raise HTTPException(status_code=400, detail="New name already exists.")

    script.update({
        "name": update_request.new_name,
        "path": update_request.path,
        "description": update_request.description,
        "apps": update_request.apps,
        "pass_bot_param": update_request.pass_bot_param,
        "bot_name": update_request.bot_name,
        "schedule_expression": update_request.schedule_expression
    })

    save_scripts(scripts)
    return {"message": "Script updated."}

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