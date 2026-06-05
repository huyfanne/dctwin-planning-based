import json

from prevalidation import set_status


def test_set_status_approves(tmp_path):
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps({"status": "pending_approval"}))
    set_status(str(p), "approved")
    assert json.loads(p.read_text())["status"] == "approved"


def test_set_status_reject(tmp_path):
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps({"status": "pending_approval"}))
    set_status(str(p), "rejected")
    assert json.loads(p.read_text())["status"] == "rejected"
