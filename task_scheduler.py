"""
Task scheduler: run FunctionGemma (tool_ai) at scheduled times.
- Interval: every N minutes/hours/days → one conversation; append each run.
- Schedule: run at a specific date/time once → new conversation per run.
"""
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from config import JOBS_FILE

logger = logging.getLogger(__name__)
_scheduler = None
_conv_manager = None
_jobs_lock = threading.RLock()


def _load_jobs() -> List[dict]:
    with _jobs_lock:
        if not os.path.exists(JOBS_FILE):
            return []
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[task_scheduler] Could not load jobs; using empty list: %s", exc)
            return []
        if not isinstance(payload, list):
            logger.warning("[task_scheduler] Ignoring invalid jobs payload: expected list.")
            return []
        return [job for job in payload if isinstance(job, dict)]


def _save_jobs(jobs: List[dict]) -> None:
    with _jobs_lock:
        directory = os.path.dirname(os.path.abspath(JOBS_FILE))
        if directory:
            os.makedirs(directory, exist_ok=True)
        temp_path = f"{JOBS_FILE}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2)
        os.replace(temp_path, JOBS_FILE)


def _get_prompt_from_payload(payload: dict) -> str:
    if not payload:
        return ""
    return (payload.get("message") or payload.get("text") or "").strip()


def _is_recurring(schedule: Any) -> bool:
    if isinstance(schedule, dict):
        return schedule.get("kind") == "every"
    return False


def _run_job(job_id: str) -> None:
    """Called by scheduler when a job is due. Runs tool_ai and create/append conversation."""
    global _conv_manager
    jobs = _load_jobs()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job or not _conv_manager:
        return
    prompt = _get_prompt_from_payload(job.get("payload") or {})
    if not prompt:
        logger.warning("[task_scheduler] Job %s has no prompt, skipping.", job_id)
        return
    try:
        import tool_ai
        tool_call_raw, tool_result = tool_ai.run_task_for_backend(prompt)
    except Exception as e:
        logger.warning("[task_scheduler] tool_ai failed for job %s: %s", job_id, e)
        return
    user_msg = {"role": "user", "content": prompt}
    result_text = str(tool_result) if tool_result is not None else "No tool call produced."
    assistant_msgs = []
    if tool_call_raw:
        assistant_msgs.append({"role": "assistant", "content": tool_call_raw, "hidden": True})
    assistant_msgs.append({"role": "assistant", "content": result_text})
    conv_id = job.get("conversation_id")
    if conv_id:
        conv = _conv_manager.get_conversation(conv_id)
        if conv:
            conv["messages"].append(user_msg)
            conv["messages"].extend(assistant_msgs)
            _conv_manager.update_conversation(conv_id, conv["messages"])
            logger.info("[task_scheduler] Appended to conversation %s for job %s", conv_id, job_id)
        else:
            conv = _conv_manager.create_conversation(title=job.get("name", "Task"), messages=[user_msg] + assistant_msgs)
            job["conversation_id"] = conv["id"]
            for i, j in enumerate(jobs):
                if j.get("id") == job_id:
                    jobs[i] = job
                    break
            _save_jobs(jobs)
            logger.info("[task_scheduler] Recreated conversation for job %s", job_id)
    else:
        title = (job.get("name") or prompt[:30] or "Task").strip()
        if len(title) > 30:
            title = title[:30] + "…"
        conv = _conv_manager.create_conversation(title=title, messages=[user_msg] + assistant_msgs)
        if _is_recurring(job.get("schedule")):
            job["conversation_id"] = conv["id"]
            for i, j in enumerate(jobs):
                if j.get("id") == job_id:
                    jobs[i] = job
                    break
            _save_jobs(jobs)
        logger.info("[task_scheduler] Created conversation %s for job %s", conv['id'], job_id)


def init_scheduler(conv_manager) -> "APScheduler":
    """Initialize and return the scheduler. Call once at app startup with conversation manager."""
    global _scheduler, _conv_manager
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.date import DateTrigger
    except ImportError:
        raise ImportError("Install APScheduler: pip install apscheduler")
    _conv_manager = conv_manager
    if _scheduler is not None and getattr(_scheduler, "running", False):
        logger.info("[task_scheduler] Already started.")
        return _scheduler
    _scheduler = BackgroundScheduler()
    jobs = _load_jobs()
    for job in jobs:
        _schedule_one(job)
    _scheduler.start()
    logger.info("[task_scheduler] Started.")
    return _scheduler


def shutdown_scheduler(wait: bool = False) -> None:
    """Stop APScheduler so its worker threads do not survive backend shutdown."""
    global _scheduler
    scheduler = _scheduler
    _scheduler = None
    if scheduler is None:
        return
    try:
        scheduler.shutdown(wait=wait)
        logger.info("[task_scheduler] Stopped.")
    except Exception as exc:
        logger.warning("[task_scheduler] Stop failed: %s", exc)


def _schedule_one(job: dict) -> bool:
    """Add one job to the scheduler. Returns True if scheduled. Only interval or at (date/time)."""
    try:
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.date import DateTrigger
    except ImportError:
        return False
    job_id = job.get("id")
    if not job_id:
        return False
    schedule = job.get("schedule")
    if not schedule or not isinstance(schedule, dict):
        return False
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass
    kind = schedule.get("kind")
    if kind == "every":
        every_ms = schedule.get("everyMs", 60000)
        seconds = max(1, every_ms // 1000)
        _scheduler.add_job(_run_job, IntervalTrigger(seconds=seconds), id=job_id, args=[job_id], replace_existing=True)
        return True
    if kind == "at":
        at_ms = schedule.get("atMs")
        if at_ms is None:
            return False
        from datetime import datetime
        run_date = datetime.utcfromtimestamp(at_ms / 1000.0)
        _scheduler.add_job(_run_job, DateTrigger(run_date=run_date), id=job_id, args=[job_id], replace_existing=True)
        return True
    return False


def list_jobs() -> List[dict]:
    return _load_jobs()


def add_job(name: str, description: str, schedule: Any, payload: dict) -> dict:
    """Add a task. Returns the created job with id."""
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "name": name,
        "description": description or "",
        "schedule": schedule,
        "payload": payload or {},
        "conversation_id": None,
    }
    jobs = _load_jobs()
    jobs.append(job)
    _save_jobs(jobs)
    if _scheduler:
        _schedule_one(job)
    return job


def update_job(job_id: str, name: Optional[str] = None, description: Optional[str] = None, schedule: Any = None, payload: Optional[dict] = None) -> Optional[dict]:
    """Update an existing task. Only provided fields are updated. Returns updated job or None if not found."""
    jobs = _load_jobs()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        return None
    if name is not None:
        job["name"] = name
    if description is not None:
        job["description"] = description
    if schedule is not None:
        job["schedule"] = schedule
    if payload is not None:
        job["payload"] = payload
    _save_jobs(jobs)
    if _scheduler:
        _schedule_one(job)
    return job


def remove_job(job_id: str) -> bool:
    jobs = [j for j in _load_jobs() if j.get("id") != job_id]
    _save_jobs(jobs)
    if _scheduler:
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass
    return True
