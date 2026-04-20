import pytest

from backend.app.core.retry import with_retry, circuit_breaker


@pytest.mark.asyncio
async def test_with_retry_succeeds_after_retry():
    calls = {"n": 0}

    @with_retry(max_attempts=3, base_delay=0.0, service="svc_test1")
    async def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("transient")
        return "ok"

    res = await flaky()
    assert res == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_circuit_breaker_opens_and_blocks():
    svc = "svc_test2"
    # reset state
    circuit_breaker._failures.pop(svc, None)
    circuit_breaker._opened_at.pop(svc, None)
    circuit_breaker.threshold = 2

    @with_retry(max_attempts=1, base_delay=0.0, service=svc)
    async def always_fail():
        raise RuntimeError("boom")

    # two failing invocations should open the circuit
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await always_fail()

    assert circuit_breaker.is_open(svc)

    # subsequent call should fail fast due to open circuit
    with pytest.raises(RuntimeError) as exc:
        await always_fail()
    assert "Circuit open" in str(exc.value)
