"""``palimnesis setup`` and ``palimnesis check`` (D101).

``setup`` writes an agent's configuration into a temporary directory and must keep every
key it does not own, back up what it changes, change nothing on a second run, and refuse
files that are not plain JSON. ``check`` runs against tests/fake_upstream.py on real
loopback sockets and against the proxy itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palimnesis import adapters
from palimnesis.api import create_app
from palimnesis.cli import main
from palimnesis.config import Settings

from .fake_upstream import FakeUpstream
from .servers import serve

ROOT = Path(__file__).resolve().parents[1]
ALIAS = "qwen3.8-flash-next-iq3_xxs"  # the recorded server's model_alias


@pytest.fixture(autouse=True)
def _no_real_agent_dirs(tmp_path, monkeypatch):
    # Never read or write the host's own agent configuration.
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "default-opencode"))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "default-pi"))


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _backups(d: Path) -> list[Path]:
    return sorted(p for p in d.rglob("*") if ".bak-" in p.name)


# ---------------------------------------------------------------- packaged adapters

def test_the_packaged_adapters_are_the_integrations_files():
    pairs = [("opencode/opencode.json", "opencode/opencode.json"),
             ("opencode/plugins/palimnesis.ts", "opencode/plugins/palimnesis.ts"),
             ("pi/models.json", "pi/models.json"), ("pi/settings.json", "pi/settings.json"),
             ("pi/extensions/palimnesis-session.ts", "pi/extensions/palimnesis-session.ts")]
    for packaged, repo in pairs:
        assert adapters.read_bytes(packaged) == (ROOT / "integrations" / repo).read_bytes(), packaged


# ---------------------------------------------------------------- setup opencode

def test_setup_opencode_into_an_empty_directory(tmp_path, capsys):
    assert main(["setup", "opencode", "--model", "m1", "--config-dir", str(tmp_path)]) == 0

    cfg = _json(tmp_path / "opencode.json")
    provider = cfg["providers"]["palimnesis"]
    assert list(provider["models"]) == ["m1"]
    assert provider["models"]["m1"]["limit"]["context"] == 1_000_000
    assert provider["settings"]["baseURL"] == "http://127.0.0.1:9000/v1"
    assert cfg["model"] == "palimnesis/m1"
    assert cfg["compaction"] == {"auto": False}
    assert (tmp_path / "plugins" / "palimnesis.ts").read_bytes() == adapters.read_bytes("opencode/plugins/palimnesis.ts")
    assert _backups(tmp_path) == []
    assert "opencode.json" in capsys.readouterr().out


def test_setup_opencode_keeps_the_users_keys_and_backs_up_what_it_changes(tmp_path):
    original = {"theme": "dark", "model": "other/x",
                "providers": {"other": {"name": "Other", "settings": {"baseURL": "http://x/v1"}}},
                "compaction": {"auto": True, "keep": 3}}
    (tmp_path / "opencode.json").write_text(json.dumps(original), encoding="utf-8")

    assert main(["setup", "opencode", "--model", "m1", "--config-dir", str(tmp_path)]) == 0

    cfg = _json(tmp_path / "opencode.json")
    assert cfg["theme"] == "dark"
    assert cfg["providers"]["other"] == original["providers"]["other"]
    assert "palimnesis" in cfg["providers"]
    assert cfg["compaction"] == {"auto": False, "keep": 3}
    assert cfg["model"] == "palimnesis/m1"
    [backup] = _backups(tmp_path)
    assert json.loads(backup.read_text(encoding="utf-8")) == original


def test_setup_twice_changes_nothing_the_second_time(tmp_path, capsys):
    args = ["setup", "opencode", "--model", "m1", "--config-dir", str(tmp_path)]
    assert main(args) == 0
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    capsys.readouterr()

    assert main(args) == 0

    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert "nothing to change" in capsys.readouterr().out


def test_setup_dry_run_writes_nothing(tmp_path, capsys):
    assert main(["setup", "opencode", "--model", "m1", "--config-dir", str(tmp_path), "--dry-run"]) == 0
    assert list(tmp_path.iterdir()) == []
    assert "would write" in capsys.readouterr().out


def test_setup_refuses_a_config_that_is_not_plain_json(tmp_path, capsys):
    jsonc = '{\n  // my settings\n  "theme": "dark"\n}\n'
    (tmp_path / "opencode.json").write_text(jsonc, encoding="utf-8")

    assert main(["setup", "opencode", "--model", "m1", "--config-dir", str(tmp_path)]) == 2

    assert (tmp_path / "opencode.json").read_text(encoding="utf-8") == jsonc
    assert "not plain JSON" in capsys.readouterr().err


def test_setup_uses_the_agents_own_directory_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "oc"))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "pi"))
    assert main(["setup", "opencode", "--model", "m1"]) == 0
    assert main(["setup", "pi", "--model", "m1"]) == 0
    assert (tmp_path / "oc" / "opencode.json").exists()
    assert (tmp_path / "pi" / "models.json").exists()


def test_setup_needs_a_model(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["setup", "opencode", "--config-dir", str(tmp_path)])
    assert exc.value.code == 2


# ---------------------------------------------------------------- setup pi

def test_setup_pi_merges_models_and_settings_and_installs_the_extension(tmp_path):
    (tmp_path / "models.json").write_text(json.dumps(
        {"providers": {"local": {"baseUrl": "http://x", "models": []}}}), encoding="utf-8")
    (tmp_path / "settings.json").write_text(json.dumps(
        {"theme": "light", "compaction": {"enabled": True, "reserveTokens": 1000}}), encoding="utf-8")

    assert main(["setup", "pi", "--model", "m1", "--agent-dir", str(tmp_path), "--port", "9100"]) == 0

    models = _json(tmp_path / "models.json")
    assert models["providers"]["local"] == {"baseUrl": "http://x", "models": []}
    assert models["providers"]["palimnesis"]["baseUrl"] == "http://127.0.0.1:9100/v1"
    assert models["providers"]["palimnesis-messages"]["baseUrl"] == "http://127.0.0.1:9100"
    for name in ("palimnesis", "palimnesis-messages"):
        [model] = models["providers"][name]["models"]
        assert model["id"] == "m1" and model["contextWindow"] == 1_000_000
    settings = _json(tmp_path / "settings.json")
    assert settings["theme"] == "light"
    assert settings["compaction"] == {"enabled": False, "reserveTokens": 1000}
    assert (settings["defaultProvider"], settings["defaultModel"]) == ("palimnesis", "m1")
    assert (tmp_path / "extensions" / "palimnesis-session.ts").read_bytes() == \
        adapters.read_bytes("pi/extensions/palimnesis-session.ts")
    assert len(_backups(tmp_path)) == 2


# ---------------------------------------------------------------- check

@pytest.fixture
def stack(tmp_path):
    fake = FakeUpstream()
    with serve(fake.app()) as upstream:
        s = Settings(upstream_base_url=upstream, db_path=tmp_path / "archive.db")
        with serve(create_app(s), palimnesis=True) as proxy:
            yield fake, upstream, int(proxy.rsplit(":", 1)[1])


def test_check_passes_on_a_working_setup(stack, tmp_path, capsys):
    fake, upstream, port = stack
    oc, pi = tmp_path / "oc", tmp_path / "pi"
    assert main(["setup", "opencode", "--model", ALIAS, "--config-dir", str(oc), "--port", str(port)]) == 0
    assert main(["setup", "pi", "--model", ALIAS, "--agent-dir", str(pi), "--port", str(port)]) == 0
    capsys.readouterr()

    code = main(["check", "--upstream", upstream, "--port", str(port),
                 "--opencode-dir", str(oc), "--pi-dir", str(pi)])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "FAIL" not in out
    assert "Strata 0.1.48" in out and ALIAS in out


def test_check_names_each_problem_with_its_fix(stack, tmp_path, capsys):
    fake, upstream, port = stack
    oc = tmp_path / "oc"
    oc.mkdir()
    (oc / "opencode.json").write_text(json.dumps({"compaction": {"auto": True}}), encoding="utf-8")

    code = main(["check", "--upstream", upstream, "--port", str(port + 1), "--opencode-dir", str(oc)])

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out and "palimnesis setup opencode" in out  # missing provider and plugin
    assert "compaction" in out
    assert "proxy" in out.lower()  # nothing answers on port + 1


def test_check_warns_when_the_model_name_differs_from_the_server(stack, tmp_path, capsys):
    fake, upstream, port = stack
    pi = tmp_path / "pi"
    assert main(["setup", "pi", "--model", "not-the-alias", "--agent-dir", str(pi), "--port", str(port)]) == 0
    capsys.readouterr()

    code = main(["check", "--upstream", upstream, "--port", str(port), "--pi-dir", str(pi)])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "WARN" in out and "not-the-alias" in out and ALIAS in out


def test_check_fails_when_the_upstream_does_not_answer(capsys):
    code = main(["check", "--upstream", "http://127.0.0.1:9", "--port", "9"])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out and "upstream" in out.lower()


def test_setup_refuses_a_key_of_an_unexpected_type(tmp_path, capsys):
    original = '{"permissions": "allow-all"}'
    (tmp_path / "opencode.json").write_text(original, encoding="utf-8")
    assert main(["setup", "opencode", "--model", "m1", "--config-dir", str(tmp_path)]) == 2
    assert (tmp_path / "opencode.json").read_text(encoding="utf-8") == original
    assert "permissions" in capsys.readouterr().err


def test_setup_refuses_when_opencode_reads_a_jsonc_config(tmp_path, capsys):
    (tmp_path / "opencode.jsonc").write_text('{"theme": "dark"}', encoding="utf-8")
    assert main(["setup", "opencode", "--model", "m1", "--config-dir", str(tmp_path)]) == 2
    assert not (tmp_path / "opencode.json").exists()
    assert "opencode.jsonc" in capsys.readouterr().err


def test_backups_from_runs_in_the_same_second_never_overwrite_each_other(tmp_path):
    (tmp_path / "settings.json").write_text('{"theme": "light"}', encoding="utf-8")
    for model in ("m1", "m2", "m3"):
        assert main(["setup", "pi", "--model", model, "--agent-dir", str(tmp_path)]) == 0
    backups = [p for p in _backups(tmp_path) if p.name.startswith("settings.json")]
    assert len(backups) == 3
    assert {"theme": "light"} in [json.loads(p.read_text(encoding="utf-8")) for p in backups]


def test_check_reports_a_null_context_limit_instead_of_crashing(stack, tmp_path, capsys):
    fake, upstream, port = stack
    pi = tmp_path / "pi"
    assert main(["setup", "pi", "--model", ALIAS, "--agent-dir", str(pi), "--port", str(port)]) == 0
    models = _json(pi / "models.json")
    models["providers"]["palimnesis"]["models"][0]["contextWindow"] = None
    (pi / "models.json").write_text(json.dumps(models), encoding="utf-8")
    capsys.readouterr()

    assert main(["check", "--upstream", upstream, "--port", str(port), "--pi-dir", str(pi)]) == 1
    assert "contextWindow" in capsys.readouterr().out


def test_check_says_a_server_that_answers_is_not_strata_rather_than_absent(tmp_path, capsys):
    # LM Studio answers every unknown route with 200 and an error object (R51).
    fake = FakeUpstream()
    fake.props_body = b'{"error": "Unexpected endpoint or method. (GET /props)"}'
    with serve(fake.app()) as upstream:
        code = main(["check", "--upstream", upstream, "--port", "9"])
    out = capsys.readouterr().out
    assert code == 1
    assert "no answer" not in out
    assert "not Strata" in out and "archives and forwards" in out
