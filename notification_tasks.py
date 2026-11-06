"""Bildirim dedektoru (beat: 5 dk) ve telefona push gonderimi (beat: 1 dk)."""

from celery_app import celery_app

import notifications
import web_push


@celery_app.task(name="notification_tasks.detect_notifications")
def detect_notifications():
    result = notifications.detect_and_notify()
    web_push.dispatch_pending()
    return result


@celery_app.task(name="notification_tasks.dispatch_push")
def dispatch_push():
    return web_push.dispatch_pending()
