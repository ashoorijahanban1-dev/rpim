"""M0 acceptance criterion: the rpim.ping Celery task is registered and returns 'pong'."""

from rpim_workers.celery_app import celery_app, ping


def test_m0_ping_task_is_registered():
    assert "rpim.ping" in celery_app.tasks


def test_m0_ping_task_returns_pong():
    celery_app.conf.update(task_always_eager=True)
    result = ping.apply()
    assert result.get() == "pong"
