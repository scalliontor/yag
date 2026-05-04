from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.services.executor import list_specs, run_automation


scheduler = BackgroundScheduler()


def start_scheduler() -> None:
    if not get_settings().scheduler_enabled:
        return
    if not scheduler.running:
        scheduler.start()
    reload_jobs()


def reload_jobs() -> None:
    if not scheduler.running:
        return
    for job in scheduler.get_jobs():
        if job.id.startswith("automation:"):
            job.remove()
    for spec in list_specs():
        if spec.get("status") != "active":
            continue
        schedule = spec.get("schedule")
        if spec["type"] == "cv_extract_to_sheet" and spec["google"].get("drive_folder_id"):
            scheduler.add_job(
                run_automation,
                IntervalTrigger(minutes=60),
                args=[spec["id"]],
                id=f"automation:{spec['id']}",
                replace_existing=True,
                max_instances=1,
            )
        elif schedule and spec["type"] == "hr_overdue_checker":
            scheduler.add_job(
                run_automation,
                CronTrigger(
                    hour=schedule.get("hour", 9),
                    minute=schedule.get("minute", 0),
                    timezone=schedule.get("timezone", "Asia/Ho_Chi_Minh"),
                ),
                args=[spec["id"]],
                id=f"automation:{spec['id']}",
                replace_existing=True,
                max_instances=1,
            )
