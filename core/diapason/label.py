"""`diapason label`: a page for labelling calls by hand, to measure the judge against a human.

The judge's verdicts are left out of the page on purpose, so the labeller isn't anchored by them. Each call shows its
transcript and the judge's criteria (the code checks don't need a human: they are exact); the labeller marks each
pass / fail / n.a., the page keeps the work in the browser, and "Download CSV" writes the file `diapason calibrate` reads.
"""

from __future__ import annotations

import json
from pathlib import Path

from .judge.packs import PACKS
from .judge.rubric import DEFAULT_CRITERIA

QUESTIONS = {c.id: c.question for pack in PACKS.values() for c in pack} | {c.id: c.question for c in DEFAULT_CRITERIA}


def collect(run_dirs: list[Path], base: Path) -> list[dict]:
    calls = []
    for d in run_dirs:
        report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        rel = d.resolve().relative_to(base.resolve()).as_posix()
        for v in report["verdicts"]:
            call_json = d / v["scenario_id"] / f"run{v['run']}" / "call.json"
            if not call_json.exists():
                continue
            call = json.loads(call_json.read_text(encoding="utf-8"))
            crit = [c["id"] for c in v["criteria"] if c.get("source") != "code"]
            if not crit:
                continue
            calls.append({"run_dir": rel, "label": report.get("label") or rel, "scenario_id": v["scenario_id"], "run": v["run"],
                          "turns": [{"who": t["speaker"], "text": t["text"]} for t in call["turns"]],
                          "criteria": [{"id": c, "q": QUESTIONS.get(c, c)} for c in crit]})
    return calls


def write_page(calls: list[dict], path: Path, crm_note: str = "") -> None:
    data = json.dumps({"calls": calls, "note": crm_note}, ensure_ascii=False).replace("</", "<\\/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PAGE.replace("__DATA__", data), encoding="utf-8")


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Label Calls</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#f7f6f2;--card:#fff;--text:#1d1d1b;--muted:#6b6a65;--line:#e4e2db;--agent:#eef3ff;--caller:#f3f1ea;--pass:#1f7a4d;--fail:#b3261e;--na:#6b6a65}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--card:#1f1f1d;--text:#ecebe6;--muted:#a3a29b;--line:#34332f;--agent:#1d2433;--caller:#262521;--pass:#5cc08b;--fail:#f08a80;--na:#a3a29b}}
:root[data-theme="dark"]{--bg:#151514;--card:#1f1f1d;--text:#ecebe6;--muted:#a3a29b;--line:#34332f;--agent:#1d2433;--caller:#262521;--pass:#5cc08b;--fail:#f08a80;--na:#a3a29b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 Inter,system-ui,sans-serif}
main{max-width:900px;margin:0 auto;padding:24px 16px 80px}h1{font-size:26px;margin:0 0 6px}.muted{color:var(--muted)}
.bar{position:sticky;top:0;background:var(--bg);padding:12px 0;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;flex-wrap:wrap;z-index:2}
button{font:inherit;padding:8px 16px;border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--text);cursor:pointer}
.call{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:18px 0}
.call h2{font-size:16px;margin:0 0 10px}.t{padding:6px 10px;border-radius:10px;margin:4px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.t.agent{background:var(--agent)}.t.caller{background:var(--caller)}.t b{font-weight:600;margin-right:6px}
.q{display:grid;grid-template-columns:1fr auto;gap:8px 12px;align-items:center;padding:8px 0;border-top:1px solid var(--line)}
.q small{display:block;color:var(--muted)}.opts{display:flex;gap:4px}
.opts label{padding:4px 10px;border:1px solid var(--line);border-radius:999px;cursor:pointer;font-size:13px}
.opts input{display:none}.opts input:checked+span{font-weight:600}
.opts label:has(input[value=pass]:checked){border-color:var(--pass);color:var(--pass)}
.opts label:has(input[value=fail]:checked){border-color:var(--fail);color:var(--fail)}
.opts label:has(input[value=na]:checked){border-color:var(--na)}
@media (max-width:560px){.q{grid-template-columns:1fr}}
</style></head><body><main>
<h1>Label calls</h1>
<p class="muted">Read each call and mark every criterion as you would judge it. The judge's verdicts are hidden so they don't
anchor you. Fail only if the agent's own words break the rule; n.a. if the criterion didn't come up. Your answers stay in this
browser until you download them. <span id="note"></span></p>
<div class="bar"><b id="prog"></b><button id="dl">Download CSV</button><button id="clear">Clear my labels</button></div>
<div id="calls"></div>
</main><script>
const D = __DATA__;
const KEY = "diapason-labels-v1";
let L = {};
try { L = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { L = {}; }
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(L)); } catch (e) {} };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const id = (c, k) => [c.run_dir, c.scenario_id, c.run, k].join("|");
document.getElementById("note").textContent = D.note || "";
document.getElementById("calls").innerHTML = D.calls.map((c, i) => `<section class="call"><h2>Call ${i + 1} of ${D.calls.length}
  <span class="muted">· ${esc(c.scenario_id)}</span></h2>
  ${c.turns.map((t) => `<div class="t ${t.who === "agent" ? "agent" : "caller"}"><b>${t.who === "agent" ? "Agent" : "Caller"}</b>${esc(t.text)}</div>`).join("")}
  ${c.criteria.map((q) => `<div class="q"><div>${esc(q.id)}<small>${esc(q.q)}</small></div><div class="opts">
    ${["pass", "fail", "na"].map((v) => `<label><input type="radio" name="${esc(id(c, q.id))}" value="${v}" ${L[id(c, q.id)] === v ? "checked" : ""}><span>${v === "na" ? "n.a." : v}</span></label>`).join("")}
  </div></div>`).join("")}</section>`).join("");
const total = D.calls.reduce((n, c) => n + c.criteria.length, 0);
const prog = () => { document.getElementById("prog").textContent = `${Object.keys(L).length} of ${total} labelled`; };
document.addEventListener("change", (e) => { if (e.target.type !== "radio") return; L[e.target.name] = e.target.value; save(); prog(); });
document.getElementById("dl").onclick = () => {
  const rows = [["run_dir", "scenario_id", "run", "criterion", "verdict"]].concat(Object.entries(L).map(([k, v]) => [...k.split("|"), v]));
  const blob = new Blob([rows.map((r) => r.join(",")).join("\n") + "\n"], {type: "text/csv"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "labels.csv"; a.click();
};
document.getElementById("clear").onclick = () => { if (confirm("Clear all your labels in this browser?")) { L = {}; save(); location.reload(); } };
prog();
</script></body></html>"""
