# app/utils/db.py
import os
import pyodbc
from dotenv import load_dotenv
import json
from pathlib import Path


load_dotenv(dotenv_path=Path(".env"), override=True)

def get_sql_connection(use_env_override=False):
    server = os.getenv("SQL_SERVER")
    database = os.getenv("SQL_DATABASE")
    username = os.getenv("SQL_USER")
    password = os.getenv("SQL_PASSWORD")
    driver = os.getenv("SQL_DRIVER")
    trusted = os.getenv("SQL_TRUSTED", "false").lower() == "true"
    use_sql = os.getenv("USE_SQL", "false").lower() == "true"

    # ⚠️ Only abort if not in override mode and USE_SQL is false
    if not use_env_override and not use_sql:
        return None

    if trusted:
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Trusted_Connection=yes;"
        )
    else:
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
        )

    try:
        # print("[SQL] Trying connection string:", conn_str)
        return pyodbc.connect(conn_str)
    except Exception as e:
        raise ConnectionError(f"get_sql_connection() failed: {e}")


def save_sql_scripts(scripts, original_id=None):
    conn = get_sql_connection()
    if conn is None:
        raise Exception("SQL connection failed")

    cursor = conn.cursor()
    inserted_ids = []

    

    if original_id:
        scripts = [s for s in scripts if s.get("id") == original_id]

    for script in scripts:
        apps_json = json.dumps(script.get("apps", []))
        id_value = script.get("id") or original_id
        script_json_str = json.dumps({k: v for k, v in script.items() if k != "script_json"})

        cron_expr = script.get("schedule_expression", "* * * * *")
        cron_readable = script.get("cron_expr_parse", "")
        tags = script.get("tags", "")

        if id_value is None:
            print("[SQL] INSERT INTO Tasks (...)")
            cursor.execute("""
            INSERT INTO Tasks (Name, Path, Description, Tags, IsEnabled, UseScheduler, CronExpr, CronExprParse, Apps, EmailRecipients, BotName, PassBotParam, PassPushParam, PushText, ScriptJson)
            OUTPUT INSERTED.Id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            script["name"],
            script["path"],
            script.get("description", ""),
            tags,
            0,
            "scheduler" in script.get("apps", []),
            cron_expr,
            cron_readable,
            apps_json,
            script.get("email_recipients", ""),
            script.get("bot_name", "DefaultBot"),
            script.get("pass_bot_param", True),
            script.get("pass_push_param", False),
            script.get("push_text", ""),

            script_json_str
        ))

            inserted_id = cursor.fetchone()[0]
            script["id"] = inserted_id
            inserted_ids.append(inserted_id)
        else:
            print(f"[SQL] UPDATE Tasks SET ... WHERE Id = {id_value}")
            is_enabled = int(script.get("enabled", False))
            cursor.execute("""
                UPDATE Tasks
                SET Name = ?, Path = ?, Description = ?, Tags = ?, IsEnabled = ?, UseScheduler = ?, CronExpr = ?, CronExprParse = ?, Apps = ?, EmailRecipients = ?, BotName = ?, PassBotParam = ?, PassPushParam = ?, PushText = ?, ScriptJson = ?
                WHERE Id = ?
            """, (
                script["name"],
                script["path"],
                script.get("description", ""),
                script.get("tags", ""),
                int(is_enabled),
                "scheduler" in script.get("apps", []),
                cron_expr,
                cron_readable,
                apps_json,
                script.get("email_recipients", ""),
                script.get("bot_name", "DefaultBot"),
                script.get("pass_bot_param", True),
                script.get("pass_push_param", False),
                script.get("push_text", ""),

                script_json_str,
                id_value
            ))
            inserted_ids.append(id_value)

    conn.commit()
    conn.close()

    # Optional: one-way sync SQL - scripts.json
    if os.getenv("USE_SQL", "false").lower() == "true":
        try:
            scripts_for_json = load_sql_scripts() 
            with open("scripts.json", "w", encoding="utf-8") as f:
                json.dump(scripts_for_json, f, indent=2, ensure_ascii=True) 
            print("[SYNC] SQL scripts.json updated.")
        except Exception as e:
            print("[SYNC] Non-critical: Failed to write scripts.json. This does NOT affect SQL:", str(e))


    return inserted_ids if len(inserted_ids) > 1 else inserted_ids[0]





def load_sql_scripts(use_env_override=False):
    conn = get_sql_connection(use_env_override=use_env_override)

    if not conn:
        print("[DB] [FAIL] No connection for loading scripts")
        return []

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Id, ScriptJson FROM Tasks")
        rows = cursor.fetchall()
        scripts = []
        for row in rows:
            script = json.loads(row.ScriptJson)
            script["id"] = row.Id
            scripts.append(script)
        return scripts
    except Exception as e:
        print("[DB] [FAIL] Failed to load scripts:", e)
        return []
    finally:
        cursor.close()
        conn.close()

