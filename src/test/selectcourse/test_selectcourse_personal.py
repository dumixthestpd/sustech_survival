"""Offline contract tests for the TIS personal-selection search."""
from __future__ import annotations

from unittest.mock import MagicMock

from sustech_survival.selectcourse import SelectCourseClient


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    return response


def test_personal_search_matches_active_round_query_shape():
    """Personal search must request selectable rows, not the cart-only view."""
    client = SelectCourseClient(xn="2026-2027", xq="1")
    client._auth.ensure = MagicMock(return_value=(True, "stub"))
    client._auth.post = MagicMock(side_effect=[
        _response({
            "p_dqxn": "2026-2027",
            "p_dqxq": "1",
            "p_dqxnxq": "2026-20271",
            "cxsfmt": "0",
        }),
        _response({
            "jg": "1",
            "kxrwList": {"total": 1, "list": [{
                "kcdm": "HUM032", "kcmc": "Writing",
                "rwh": "2026-2027-1-HUM032-002",
                "zrl": "35", "yxzrs": "26",
            }]},
        }),
    ])

    result = client.search_personal(keyword="HUM032", round_code="bxxk")

    assert result["ok"] is True
    assert result["courses"][0].enrolled == 26
    query_call = client._auth.post.call_args_list[-1]
    assert query_call.args[0] == "/Xsxk/queryKxrw"
    payload = query_call.kwargs["data"]
    assert payload["p_sfsyxkgwc"] == "0"
    assert payload["p_chaxunxkfsdm"] == "bxxk"
    assert payload["p_xkfsdm"] == "bxxk"
    assert payload["p_xn"] == "2026-2027"
    assert payload["p_xq"] == "1"
    assert payload["p_xnxq"] == "2026-20271"
    assert payload["p_gjz"] == "HUM032"
    assert payload["p_kc_gjz"] == "HUM032"
