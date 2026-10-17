"""Aylik rapor Celery gorevleri."""

from celery_app import celery_app

import monthly_reports


@celery_app.task(name="report_tasks.generate_previous_month_report")
def generate_previous_month_report():
    return monthly_reports.generate_report(monthly_reports.previous_period(), notify=True)


@celery_app.task(name="report_tasks.refresh_draft_reports")
def refresh_draft_reports():
    return monthly_reports.refresh_drafts(months=3)
