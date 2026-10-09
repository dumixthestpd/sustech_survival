"""Upload once, then reconcile a receipt with the live queue; never replay POST."""

import json

import pytest
import requests

from sustech_survival.pms import PMSClient, PMSError, PrintJob
from sustech_survival.pms.pms import PMS_QUEUE_URL


def reply(payload=None, status=200, location=None, html=False):
    r = requests.Response()
    r.url = "https://pms.sustech.edu.cn/api/client/CloudPrint/Upload"
    r.status_code = status
    r._content = b"<html>result page</html>" if html else json.dumps(payload).encode()
    if location:
        r.headers["Location"] = location
    return r


def job(job_id=2, name="PMS_TEST.pdf", flag="vdup"):
    return {
        "dwJobId": job_id,
        "szJobName": name,
        "dwCopies": 1,
        "szAttribe": f"{flag},",
        "szPaperDetail": '[{"dwPaperID":9,"dwBWPages":2,"dwColorPages":0,"dwPaperNum":1}]',
    }


class Session:
    def __init__(self, before, after, upload):
        self.queues = iter([before, after])
        self.upload = upload
        self.posts = []
        self.gets = []

    def get(self, url, **kwargs):
        self.gets.append(url)
        assert url.endswith("/PrintJob/Get")
        value = next(self.queues)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, requests.Response):
            return value
        return reply({"code": 0, "result": value})

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        assert kwargs["allow_redirects"] is False
        assert kwargs["data"]["BackURL"] == PMS_QUEUE_URL
        assert not kwargs["files"]["szPath"][1].closed
        if isinstance(self.upload, Exception):
            raise self.upload
        return self.upload


@pytest.fixture
def file(tmp_path):
    p = tmp_path / "PMS_TEST.pdf"
    p.write_bytes(b"offline upload fixture")
    return p


@pytest.mark.parametrize(
    "response",
    [
        reply(status=302, location=PMS_QUEUE_URL + "?code=0&fee=1"),
        reply(status=302, location="https://pms.sustech.edu.cnresult.html/?code=0"),
        reply(status=200, html=True),
        reply({"code": 0}),
        reply({"code": 123, "message": "reported failure"}),
        reply(status=502, html=True),
        requests.Timeout("response lost after POST"),
    ],
)
def test_new_queue_job_confirms_upload_despite_bad_response(file, response):
    session = Session([job(1, "old.pdf")], [job(1, "old.pdf"), job()], response)
    result = PMSClient(session).upload_print(file, duplex="long")
    assert result.ok and result.uploaded is True
    assert result.status == "confirmed" and result.job_id == 2
    assert result.observed_job_ids == [2]
    assert len(session.posts) == 1
    assert len(session.gets) == 2
    assert session.posts[0][1]["data"]["dwDuplex"] == "2"


@pytest.mark.parametrize(
    "response",
    [
        reply({"code": 0}),
        reply(status=200, html=True),
        reply(status=302, location="https://example.org/printDoc.html?code=0"),
        reply(status=302, location=PMS_QUEUE_URL + "?code=0&code=1"),
        requests.ConnectionError("lost response"),
    ],
)
def test_no_receipt_means_unknown_not_definite_failure_or_success(file, response):
    session = Session([job(1)], [job(1)], response)
    result = PMSClient(session).upload_print(file)
    assert not result.ok and result.uploaded is None
    assert result.job_id is None and result.status == "unknown"
    assert "before retrying" in result.message
    assert "outcome unknown" in result.to_markdown()
    assert len(session.posts) == 1


@pytest.mark.parametrize("response", [reply(status=413), reply({"code": 12})])
def test_rejected_response_and_no_new_job_is_failure(file, response):
    session = Session([], [], response)
    result = PMSClient(session).upload_print(file)
    assert not result.ok and result.uploaded is False
    assert result.status == "rejected"
    assert len(session.posts) == 1


@pytest.mark.parametrize("after", [None, requests.Timeout("queue timeout")])
def test_failed_verification_keeps_outcome_unknown(file, after):
    session = Session([], after, reply({"code": 0}))
    result = PMSClient(session).upload_print(file)
    assert result.uploaded is None
    assert result.verification_error
    assert len(session.posts) == 1


@pytest.mark.parametrize(
    "after",
    [
        reply([]),
        reply({"code": 0, "result": None}),
        [job(0)],
        [{**job(), "szPaperDetail": '["invalid detail"]'}],
    ],
)
def test_malformed_queue_cannot_turn_a_sent_upload_into_a_definite_failure(file, after):
    session = Session([], after, reply({"code": 0}))
    result = PMSClient(session).upload_print(file)
    assert result.uploaded is None and not result.ok
    assert result.verification_error
    assert len(session.posts) == 1


def test_multiple_new_matches_are_not_silently_collapsed(file):
    session = Session([], [job(2), job(3)], reply({"code": 0}))
    result = PMSClient(session).upload_print(file)
    assert result.status == "unknown" and result.uploaded is None
    assert result.observed_job_ids == [2, 3]
    assert result.job_id is None
    assert len(session.posts) == 1


def test_unavailable_before_snapshot_sends_no_upload(file):
    session = Session(None, [], reply({"code": 0}))
    with pytest.raises(PMSError, match="queue"):
        PMSClient(session).upload_print(file)
    assert session.posts == []


def test_dry_run_has_no_io_and_uses_queue_short_edge_value(file):
    session = Session([], [], None)
    result = PMSClient(session).upload_print(file, duplex="short", dry_run=True)
    assert result.duplex == 3
    assert result.status == "dry_run" and result.uploaded is False
    assert not session.gets and not session.posts


@pytest.mark.parametrize(
    "duplex,code,flag,edge,label,other_label",
    [
        (2, 2, "vdup", "long", "双面长边", "双面短边"),
        ("2", 2, "vdup", "long", "双面长边", "双面短边"),
        ("long", 2, "vdup", "long", "双面长边", "双面短边"),
        ("双面长边", 2, "vdup", "long", "双面长边", "双面短边"),
        (3, 3, "hdup", "short", "双面短边", "双面长边"),
        ("3", 3, "hdup", "short", "双面短边", "双面长边"),
        ("short", 3, "hdup", "short", "双面短边", "双面长边"),
        ("双面短边", 3, "hdup", "short", "双面短边", "双面长边"),
    ],
)
def test_duplex_preview_wire_value_and_queue_label_agree(
    file, duplex, code, flag, edge, label, other_label
):
    raw_job = job(flag=flag)
    session = Session([], [raw_job], reply({"code": 0}))
    client = PMSClient(session)
    preview = client.upload_print(file, duplex=duplex, dry_run=True)
    assert preview.duplex == code
    assert f"{label}; dwDuplex={code}" in preview.to_markdown()
    assert other_label not in preview.to_markdown()
    assert not session.gets and not session.posts

    receipt = client.upload_print(file, duplex=duplex)
    assert receipt.ok and receipt.job_id == raw_job["dwJobId"]
    assert len(session.posts) == 1
    assert session.posts[0][1]["data"]["dwDuplex"] == str(code)
    assert f"{label}; dwDuplex={code}" in receipt.to_markdown()
    queued = PrintJob.from_api(raw_job)
    assert queued.duplex_flag == flag and queued.is_duplex is True
    assert queued.duplex_edge == edge and queued.duplex_label == label
    assert label in queued.to_markdown()
    assert other_label not in queued.to_markdown()
