import json
import time

import httpx
import pytest


def request_for(broker, key="test:probe", script="probe", inputs=None):
    return {
        "key": key,
        "bundle_digest": broker.bundles[key]["bundle_digest"],
        "script": script,
        "inputs": inputs or {},
    }


def test_restricted_container_profile_and_uncertain_create_cleanup(runner_module):
    broker = runner_module.Broker(
        {
            "fixture": {
                "image": "sha256:" + "a" * 64,
                "bundle_digest": "b" * 64,
                "scripts": ["helper"],
            }
        }
    )
    calls = []

    def engine(method, path, body=None, **kwargs):
        calls.append((method, path, body, kwargs))
        if method == "POST":
            raise OSError("create response lost")
        return b""

    broker.engine = engine
    assert broker.run(request_for(broker, "fixture", "helper")) == {"error": "runner_unavailable"}
    config = calls[0][2]
    assert config["Image"] == "sha256:" + "a" * 64
    assert config["User"] == "65534:65534" and config["NetworkDisabled"]
    host = config["HostConfig"]
    assert host["ReadonlyRootfs"] and host["NetworkMode"] == "none"
    assert host["CapDrop"] == ["ALL"] and "Binds" not in host
    assert host["Memory"] == host["MemorySwap"] == 268435456
    assert host["PidsLimit"] == 32 and host["NanoCpus"] == 1000000000
    assert calls[-1][0] == "DELETE" and calls[-1][3]["missing_ok"]
    assert broker.slots.acquire(blocking=False)
    assert broker.slots.acquire(blocking=False)
    assert broker.run(request_for(broker, "fixture", "helper")) == {"error": "runner_busy"}


def test_reaper_scopes_and_removes_only_expired_jobs(runner_module):
    broker = runner_module.Broker({}, instance="test-reaper")
    calls = []

    def engine(method, path, *args, **kwargs):
        calls.append((method, path))
        return (
            json.dumps(
                [
                    {"Id": "a" * 64, "Created": int(time.time()) - 100},
                    {"Id": "b" * 64, "Created": int(time.time())},
                ]
            ).encode()
            if method == "GET"
            else b""
        )

    broker.engine = engine
    broker.reap_stale()
    assert "test-reaper" in calls[0][1]
    assert len(calls) == 2 and "a" * 64 in calls[1][1]


async def test_real_runner_auth_pins_and_generated_text_is_data(real_runner):
    async with httpx.AsyncClient(base_url=real_runner.url, trust_env=False, timeout=45) as client:
        request = request_for(
            real_runner.broker,
            "built-in:saved-notes-demo",
            "summarize_notes",
            {"text": "__import__('os').system('touch /work/generated')"},
        )
        assert (await client.post("/run", json=request)).status_code == 401
        headers = {"Authorization": "Bearer " + real_runner.token}
        response = await client.post("/run", headers=headers, json=request)
        assert response.status_code == 200
        result = response.json()
        assert result["exit_code"] == 0 and result["stderr"] == ""
        assert json.loads(result["stdout"])["preview"] == request["inputs"]["text"]
        for invalid in ({**request, "code": "print(1)"}, {**request, "command": "sh"}):
            assert (await client.post("/run", headers=headers, json=invalid)).json() == {
                "error": "invalid_request"
            }
        request["bundle_digest"] = "0" * 64
        assert (await client.post("/run", headers=headers, json=request)).json() == {
            "error": "script_not_enabled"
        }


def test_real_isolation_fresh_work_and_cleanup(real_runner):
    for _ in range(2):
        result = real_runner.broker.run(request_for(real_runner.broker))
        assert result["exit_code"] == 0, result
        probe = json.loads(result["stdout"])
        assert probe["uid"] == 65534 and probe["fresh"] and probe["readonly"]
        assert not probe["network"] and not probe["engine_socket"] and not probe["application"]
        assert int(probe["caps"], 16) == 0 and probe["no_new_privs"] == "1"
        assert set(probe["env_keys"]) <= {"PATH", "HOME", "LC_CTYPE"}
        assert probe["limits"]["memory.max"] == "268435456"
        assert probe["limits"]["memory.swap.max"] == "0"
        assert probe["limits"]["pids.max"] == "32"
        quota, period = map(int, probe["limits"]["cpu.max"].split())
        assert quota == period
    assert not json.loads(
        real_runner.broker.engine(
            "GET",
            "/containers/json?all=1&filters="
            "%7B%22label%22%3A%5B%22lq.skill-runner%3Dacceptance-563%22%5D%7D",
        )
    )


@pytest.mark.parametrize("script,error", [("stall", "script_timeout"), ("flood", "output_limit")])
def test_real_limits(real_runner, script, error):
    assert real_runner.broker.run(
        request_for(real_runner.broker, script=script, inputs={"text": "x" * 60000})
    ) == {"error": error}


def test_image_bundle_mismatch_refused(real_runner):
    broker = real_runner.broker
    original = broker.bundles["test:probe"]["bundle_digest"]
    broker.bundles["test:probe"]["bundle_digest"] = "c" * 64
    try:
        assert broker.run(request_for(broker)) == {"error": "bundle_changed"}
    finally:
        broker.bundles["test:probe"]["bundle_digest"] = original
