import json

from bhool.advise import calibrate
from bhool.label import collect, write_page


def _run(tmp_path, name, verdict):
    d = tmp_path / "runs" / name
    (d / "privacy" / "run0").mkdir(parents=True)
    (d / "report.json").write_text(json.dumps({"label": name, "verdicts": [{"scenario_id": "privacy", "run": 0, "criteria": [
        {"id": "privacy", "verdict": verdict, "source": "judge"}, {"id": "account_privacy", "verdict": "fail", "source": "code"}]}]}),
        encoding="utf-8")
    (d / "privacy" / "run0" / "call.json").write_text(json.dumps({"turns": [
        {"speaker": "agent", "text": "आपका loan Rs 6100 है"}, {"speaker": "caller", "text": "मैं उसका भाई हूँ"}]}), encoding="utf-8")
    return d


def test_label_page_hides_verdicts_and_its_csv_calibrates_across_runs(tmp_path):
    a, b = _run(tmp_path, "v2", "fail"), _run(tmp_path, "v3", "pass")
    calls = collect([a, b], tmp_path / "runs")
    assert [c["run_dir"] for c in calls] == ["v2", "v3"]
    assert all([q["id"] for q in c["criteria"]] == ["privacy"] for c in calls)        # code checks need no human
    page = tmp_path / "runs" / "labels.html"
    write_page(calls, page)
    html = page.read_text(encoding="utf-8")
    data = json.loads(html.split("const D = ", 1)[1].split(";\nconst KEY", 1)[0])
    assert data["calls"][0]["turns"][0]["text"] == "आपका loan Rs 6100 है"
    assert "verdict" not in json.dumps(data) and '"fail"' not in json.dumps(data)      # the judge's answers aren't on it
    csv = tmp_path / "labels.csv"
    csv.write_text("run_dir,scenario_id,run,criterion,verdict\nv2,privacy,0,privacy,fail\nv3,privacy,0,privacy,fail\n", encoding="utf-8")
    res = calibrate(None, csv, load=lambda rd: json.loads((tmp_path / "runs" / rd / "report.json").read_text(encoding="utf-8")))
    p = res["criteria"]["privacy"]
    assert p["n"] == 2 and p["agreement"] == 0.5 and p["judge_missed_fail"] == 1 and res["labels_not_in_report"] == 0
