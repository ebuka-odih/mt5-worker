from scripts.render_mt5_ea import render_ea_source


def test_render_ea_source_replaces_input_defaults() -> None:
    template = """
input string ApiBase = "http://127.0.0.1:8780";
input string WorkerToken = "CHANGE_ME_LONG_RANDOM_TOKEN";
input string WorkerId = "macos-mt5-local-01";
input bool DryRun = true;
input long MagicNumber = 552501;
input int PollSeconds = 1;
input int HeartbeatSeconds = 10;
input int RequestTimeoutMs = 5000;
""".strip()
    env = {
        "VPS_API_BASE": "http://95.217.130.102:8780",
        "WORKER_TOKEN": "secret-token",
        "WORKER_ID": "worker-01",
        "DRY_RUN": "false",
        "MT5_MAGIC": "123456",
        "POLL_SECONDS": "2",
        "HEARTBEAT_SECONDS": "11",
        "REQUEST_TIMEOUT_MS": "7000",
    }

    rendered = render_ea_source(template, env)

    assert 'input string ApiBase = "http://95.217.130.102:8780";' in rendered
    assert 'input string WorkerToken = "secret-token";' in rendered
    assert 'input string WorkerId = "worker-01";' in rendered
    assert "input bool DryRun = false;" in rendered
    assert "input long MagicNumber = 123456;" in rendered
    assert "input int PollSeconds = 2;" in rendered
    assert "input int HeartbeatSeconds = 11;" in rendered
    assert "input int RequestTimeoutMs = 7000;" in rendered
