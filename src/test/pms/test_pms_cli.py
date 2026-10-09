"""PMS CLI uses actual dataclass fields and keeps auth output out of JSON."""

import json

from click.testing import CliRunner

from sustech_survival.cli import cli
from sustech_survival.pms import PMSError, PrintJob, Station
from sustech_survival.sso.authlib.pms import PMSAuth


def test_check_failure_has_nonzero_exit(monkeypatch):
    monkeypatch.setattr(PMSAuth(), "ensure", lambda: (False, "PMS unavailable"))
    result = CliRunner().invoke(cli, ["pms", "check"])
    assert result.exit_code == 1 and "PMS unavailable" in result.output


def test_json_jobs_serializes_dataclass_with_separate_auth_diagnostics(monkeypatch):
    class Client:
        def list_print_jobs(self):
            return [PrintJob.from_api({"dwJobId": 1, "szJobName": "PMS_TEST.pdf"})]

    def factory():
        print("authentication diagnostic")
        return Client()

    monkeypatch.setattr("sustech_survival.pms.pms", factory)
    result = CliRunner().invoke(cli, ["pms", "jobs", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["dw_job_id"] == 1
    assert "authentication diagnostic" in result.stderr


def test_station_name_and_json_fields_exist(monkeypatch):
    class Client:
        def list_stations(self, **kwargs):
            return [Station.from_api({"szName": "Test printer", "dwDevSN": 1001})]

    monkeypatch.setattr("sustech_survival.pms.pms", lambda: Client())
    result = CliRunner().invoke(cli, ["pms", "stations"])
    assert result.exit_code == 0 and "Test printer" in result.stdout
    result = CliRunner().invoke(cli, ["pms", "stations", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["sz_name"] == "Test printer"


def test_auth_failure_is_a_cli_error_not_empty_jobs(monkeypatch):
    def failed():
        raise PMSError("PMS unavailable")

    monkeypatch.setattr("sustech_survival.pms.pms", failed)
    result = CliRunner().invoke(cli, ["pms", "jobs", "--json"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "PMS unavailable" in result.stderr
