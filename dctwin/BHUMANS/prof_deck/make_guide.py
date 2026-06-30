#!/usr/bin/env python
"""Generate the written companion guide (deliverable 1) from the verified analysis.json."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
A = json.load(open(os.path.join(HERE, "analysis.json")))
TABS = A["tabs"]; N = A["narrative"]

ORDER = [o["tab"] for o in N["recommended_tab_order"]]
def find(prefix):
    for t in TABS:
        if t["tab"].lower().startswith(prefix.lower()):
            return t
    return None
def short(name):
    return name.split(" (")[0].split(" —")[0].split(" (")[0].strip()

L = []
w = L.append
w(f"# {N['deck_title']}\n")
w(f"### {N['deck_subtitle']}\n")
w(f"**How to read, interpret, and present each tab of the DCTwin web app to your Professor.**\n")
w(f"_Companion to the slide deck `DCTwin_Webapp_Walkthrough_for_Professor.pptx`. "
  f"Live app: http://10.96.72.147:8001/_\n")
w("\n---\n")
w("## The one-sentence thesis\n")
w(f"> {N['one_sentence_thesis']}\n")
w("## How to open\n")
w(f"{N['opening_hook']}\n")
w("## The presentation arc\n")
for s in N["framing_sections"]:
    w(f"- {s}")
w("\n**Recommended tab order:** " + " → ".join(short(o['tab']) for o in N["recommended_tab_order"]) + "\n")
for o in N["recommended_tab_order"]:
    w(f"- **{short(o['tab'])}** — {o['why_here']}  _(segue: {o['transition_in']})_")
w("\n---\n")

# per tab in recommended order
def tab_section(t, n):
    w(f"## Tab {n} · {short(t['tab'])}\n")
    w(f"**What it's for.** {t['one_line_purpose']}\n")
    w(f"**How to introduce it.** {t['professor_framing']}\n")
    w("### How to read it\n")
    w("| Element | What it shows | How to interpret |")
    w("|---|---|---|")
    for e in t["elements"]:
        def cl(s): return s.replace("|", "\\|").replace("\n", " ")
        w(f"| {cl(e['label'])} | {cl(e['what_it_shows'])} | {cl(e['how_to_read'])} |")
    w("\n### Key numbers on this tab\n")
    for k in t["key_numbers"]:
        w(f"- {k}")
    w("\n### What to say (talking points)\n")
    for tp in t["talking_points"]:
        w(f"- {tp}")
    w(f"\n**Money insight.** {t['money_insight']}\n")
    if t.get("caveats"):
        w("### State proactively (honest caveats)\n")
        for c in t["caveats"]:
            w(f"- {c}")
    w("\n### Likely questions & strong answers\n")
    for qa in t["professor_questions"]:
        w(f"- **Q: {qa['q']}**")
        w(f"  - **A:** {qa['a']}")
    w("\n### Intuitive visual aids (used in the deck)\n")
    for v in t["visual_aid_suggestions"]:
        w(f"- {v}")
    w("\n---\n")

for i, name in enumerate(ORDER, 1):
    t = find(short(name)) or find(name.split()[0])
    if t:
        tab_section(t, i)

w("## Cross-cutting questions the Professor is most likely to ask\n")
for qa in N["big_questions"]:
    w(f"- **Q: {qa['q']}**")
    w(f"  - **A:** {qa['a']}")
w("\n## How to close\n")
w(f"{N['closing']}\n")
w("## Delivery tips\n")
for tip in N["presenting_tips"]:
    w(f"- {tip}")
w("\n## Appendix — the measured record (read straight from the live system)\n")
w("| Metric | Value |")
w("|---|---|")
for k, v in [
    ("Deployed weekly cycles", "6 (2024-11-08 → 2024-12-13)"),
    ("Weekly-energy prediction error", "1.33% (wk1) → 0.10% (wk6)"),
    ("Energy saving vs as-operated baseline", "0% → 3.2% → 3.63% (gate-released)"),
    ("Safety violations", "0 — worst realized inlet 25.60 °C vs the 26 °C cap (0.40 °C margin)"),
    ("Peak-inlet prediction error", "within ~0.25 °C every week"),
    ("Calibration state (n=7)", "inlet bias 0.18 °C, σ_inlet 0.14 °C, σ_post 0.36 °C, energy bias ~0.2%"),
    ("Well-posedness (real EnergyPlus sweep)", "airflow moves hall energy 15.5%, CHWST 3.4%, SAT ~0.5%"),
    ("Control space", "3 global setpoints → 45 actuators (22 SAT + 22 airflow + 1 CHWST)"),
    ("Honesty", "deploy = shadow mode (recorded, not actuated); telemetry feed simulated & labelled"),
]:
    w(f"| {k} | {v} |")
w("")

out = os.path.join(HERE, "DCTwin_Webapp_Tab_Guide.md")
open(out, "w").write("\n".join(L))
print("wrote", out, os.path.getsize(out), "bytes")
print("tabs covered:", sum(1 for name in ORDER if (find(short(name)) or find(name.split()[0]))))
