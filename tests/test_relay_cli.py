import app.cli as cli
from app.services import outbox_service


class StopLoop(Exception):
    pass


def test_relay_once_surfaces_broker_failures(app, monkeypatch):
    def broker_down():
        raise ConnectionError("broker is down")

    monkeypatch.setattr(outbox_service, "publish_pending", broker_down)
    result = app.test_cli_runner().invoke(args=["outbox-relay", "--once"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ConnectionError)


def test_relay_loop_survives_failures_and_idles_when_empty(app, monkeypatch):
    calls, sleeps = [], []

    def publish():
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("broker is down")  # the first pass fails...
        return 0  # ...then there is simply nothing to do

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise StopLoop  # the only way out of an intentionally endless loop

    class FakeTime:
        sleep = staticmethod(fake_sleep)

    monkeypatch.setattr(outbox_service, "publish_pending", publish)
    monkeypatch.setattr(cli, "time", FakeTime)

    result = app.test_cli_runner().invoke(args=["outbox-relay", "--interval", "0.5"])

    assert isinstance(result.exception, StopLoop)
    assert len(calls) == 2  # it kept going after the failure
    assert sleeps == [0.5, 0.5]  # and paused between passes


def test_relay_backs_off_exponentially_and_resets_after_a_success(app, monkeypatch):
    outcomes = iter([ConnectionError("down")] * 3 + [0, ConnectionError("down")])
    sleeps = []

    def publish():
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 5:
            raise StopLoop

    class FakeTime:
        sleep = staticmethod(fake_sleep)

    monkeypatch.setattr(outbox_service, "publish_pending", publish)
    monkeypatch.setattr(cli, "time", FakeTime)

    result = app.test_cli_runner().invoke(
        args=["outbox-relay", "--interval", "0.5", "--max-backoff", "1.5"]
    )

    assert isinstance(result.exception, StopLoop)
    assert sleeps == [0.5, 1.0, 1.5, 0.5, 0.5]  # grows, is capped, resets after the success
