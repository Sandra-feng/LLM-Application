from celery import Celery

from base_configs.redis_config import *

celery_app = Celery(
    "tiance_tasks",
    broker=f"redis://:{PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/6",  # 任务队列
    backend=f"redis://:{PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/7",  # 任务执行结果
    include=[  # 关键：用字符串告诉 Celery 去哪些包里找任务
        "service_celery_manage.tasks",
        "service_celery_manage.evaluation_tasks",
    ],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    result_expires=3600,  # 任务结果过期时间，单位为秒
    task_track_started=True,
)
from celery.result import AsyncResult


async def wait_one(task_id, timeout=None):
    result = AsyncResult(task_id, app=celery_app)
    try:
        value = result.get(timeout=timeout)
        return "Success"
    except Exception as e:
        return "Failure"
