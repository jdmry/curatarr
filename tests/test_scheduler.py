from datetime import UTC, datetime, timedelta

from app.db import connection, migrate
from app.sync.runner import AlreadyRunning
from app.sync.scheduler import Scheduler, load_schedule, save_schedule

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


class FakeRunner:
    def __init__(self, busy=False):
        self.busy = busy
        self.started = []

    def start(self, mode, **kwargs):
        if self.busy:
            raise AlreadyRunning()
        self.started.append((mode, kwargs))


class FakeEvents:
    def info(self, message):
        pass


def scheduler(tmp_path, runner):
    path = tmp_path / "test.db"
    migrate(path)
    return Scheduler(path, runner, FakeEvents()), path


def test_off_by_default(tmp_path):
    runner = FakeRunner()
    sched, path = scheduler(tmp_path, runner)
    assert sched.check(NOW + timedelta(days=30)) is False and runner.started == []


def test_starts_when_due_and_plans_next(tmp_path):
    runner = FakeRunner()
    sched, path = scheduler(tmp_path, runner)
    with connection(path) as conn:
        save_schedule(conn, True, 6, now=NOW)
    assert sched.check(NOW + timedelta(hours=5)) is False
    assert sched.check(NOW + timedelta(hours=6, minutes=1)) is True
    assert runner.started == [("live", {"scheduled": True})]
    with connection(path) as conn:
        assert load_schedule(conn).next_at == NOW + timedelta(hours=12, minutes=1)


def test_busy_runner_retries_later(tmp_path):
    runner = FakeRunner(busy=True)
    sched, path = scheduler(tmp_path, runner)
    with connection(path) as conn:
        save_schedule(conn, True, 1, now=NOW)
    assert sched.check(NOW + timedelta(hours=2)) is False
    runner.busy = False
    assert sched.check(NOW + timedelta(hours=2, minutes=1)) is True


def test_pause_and_bad_interval(tmp_path):
    sched, path = scheduler(tmp_path, FakeRunner())
    with connection(path) as conn:
        assert save_schedule(conn, True, 5, now=NOW).every_hours == 6
        paused = save_schedule(conn, False, 3, now=NOW)
        assert load_schedule(conn) == paused and paused.next_at is None and paused.every_hours == 3


def test_prefixes_keep_schedules_apart(tmp_path):
    runner = FakeRunner()
    path = tmp_path / "test.db"
    migrate(path)
    posters = Scheduler(path, FakeRunner(), FakeEvents())
    lists = Scheduler(path, runner, FakeEvents(), prefix="lists_schedule")
    with connection(path) as conn:
        save_schedule(conn, True, 1, now=NOW, prefix="lists_schedule")
        assert load_schedule(conn).enabled is False
    assert posters.check(NOW + timedelta(hours=2)) is False
    assert lists.check(NOW + timedelta(hours=2)) is True and runner.started == [("live", {"scheduled": True})]
