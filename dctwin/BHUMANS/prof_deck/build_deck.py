#!/usr/bin/env python
"""Build the DCTwin 'present to your Professor' deck from analysis.json + real screenshots."""
import json, os, shutil, textwrap
import deckkit as dk

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "shots")
ANNO = os.path.join(HERE, "annotated"); os.makedirs(ANNO, exist_ok=True)
ASSETS = os.path.join(HERE, "assets"); os.makedirs(ASSETS, exist_ok=True)
A = json.load(open(os.path.join(HERE, "analysis.json")))
NAR = A["narrative"]; TABS = A["tabs"]

# copy the architecture diagram from the manuscript figures
arch_src = os.path.join(HERE, "..", "manuscript", "figures", "fig3_arch.png")
if os.path.exists(arch_src):
    shutil.copy(arch_src, os.path.join(ASSETS, "arch.png"))

def tab(prefix):
    for t in TABS:
        if t["tab"].lower().startswith(prefix.lower()):
            return t
    raise KeyError(prefix)

def wrap(s, w=95):
    return "\n".join(textwrap.fill(line, w) for line in s.split("\n"))

def notes_for(t, extra_qa=3, lead=None):
    """Compose speaker notes from the verified analysis."""
    out = []
    if lead: out.append(lead)
    out.append("FRAME: " + t["professor_framing"])
    out.append("\nSAY (talking points):")
    for tp in t["talking_points"]:
        out.append("  • " + tp)
    out.append("\nMONEY INSIGHT: " + t["money_insight"])
    if t.get("caveats"):
        out.append("\nSTATE PROACTIVELY (caveats):")
        for c in t["caveats"]:
            out.append("  – " + c)
    if t.get("professor_questions"):
        out.append("\nLIKELY Q&A:")
        for qa in t["professor_questions"][:extra_qa]:
            out.append("  Q: " + qa["q"])
            out.append("  A: " + qa["a"])
    return wrap("\n".join(out))

C = dk  # colors
prs = dk.new_deck()

# ---------------------------------------------------------------- 1. TITLE
dk.title_slide(
    prs, NAR["deck_title"], NAR["deck_subtitle"], NAR["one_sentence_thesis"],
    footer="Hoang-Huy Nguyen  ·  Digital Twin Dual-Loop Control Framework  ·  walkthrough of the live cockpit (10.96.72.147:8001)")
dk.notes(prs.slides[-1], wrap(
    "OPENING HOOK:\n" + NAR["opening_hook"] +
    "\n\nThesis to land first: " + NAR["one_sentence_thesis"] +
    "\n\nThis deck walks the 7 tabs of the live web app in a deliberate order that mirrors the science: "
    "trust boundary -> inner planning loop -> safety evidence -> operator audit -> the learning loop -> the twin in 3D -> honest limits."))

# ---------------------------------------------------------------- 2. THE COCKPIT MAP / DUAL LOOP
dk.image_slide(
    prs, "ORIENTATION", "One controller, two loops — and a cockpit tab for each part",
    os.path.join(ASSETS, "arch.png"),
    [(None, "Read the diagram as two nested loops:"),
     (1, "INNER loop (simulation): forecast -> EnergyPlus physics -> beam search -> safety filter"),
     (2, "OUTER loop (deploy & learn): pre-validate -> expert approve -> deploy -> calibrate"),
     (None, "Tabs map onto the loops:"),
     (3, "New Plan + Review = inner loop (plan & prove)"),
     (4, "Dashboard + Live = the operator's contract & live audit"),
     (5, "History + 3D = the outer loop closing and made tangible")],
    wrap("This is the map for the whole talk. Tell the professor: the dangerous capability is broadcasting 3 setpoints "
         "to 45 actuators in a ~2 MW hall; we wrap it first in role-based governance (Login), then in a physics "
         "safety gate, then in a measured learning loop. Order of tabs today: " +
         " -> ".join(o["tab"] for o in NAR["recommended_tab_order"]) + "."),
    img_frac=0.60)

# ---------------------------------------------------------------- per-tab annotated slides
# Each entry: prefix, kicker, slide title, shot, crop, markers, legend, money-banner-as-legend, second-slide(optional)
def mk(n, x, y, color=dk.PIL_ACCENT): return {"n": n, "x": x, "y": y, "color": color}

GREEN, AMBER, RED, CY = dk.PIL_GREEN, dk.PIL_AMBER, dk.PIL_RED, dk.PIL_ACCENT

# ===== ACT 0 — LOGIN =====
dk.section_slide(prs, "ACT 0 — THE TRUST BOUNDARY",
                 "Governance before physics", "Nothing is reachable until a valid, role-separated token is verified — fail-closed.")
dk.notes(prs.slides[-1], wrap(NAR["framing_sections"][0]))

t = tab("Login")
dk.annotate(f"{SHOTS}/login.png", f"{ANNO}/login.png",
            crop=(0.33, 0.31, 0.67, 0.74),
            markers=[mk(1, 0.50, 0.50), mk(2, 0.50, 0.64, GREEN), mk(3, 0.50, 0.74, AMBER)])
dk.image_slide(prs, "TAB · LOGIN", "The door: token-gated, role-separated, fail-closed",
    f"{ANNO}/login.png",
    [(None, "How to read it:"),
     (1, "One masked token field — no user/password, credentials are pre-issued"),
     (2, "'Continue' is disabled until valid; shows 'Checking…' during a live backend probe"),
     (3, "Two roles: operator (view + run) vs expert (approve + deploy)"),
     (None, "Money insight:"),
     (None, "A bad token is never cached; even a backend outage denies entry (fail-closed).")],
    notes_for(t), img_frac=0.52)

# ===== ACT 1 — NEW PLAN (inner loop) =====
dk.section_slide(prs, "ACT 1 — THE INNER LOOP AS AN EXPERIMENT",
                 "45 actuators reduced to a 3-knob weekly search",
                 "Each candidate scored by a full-week EnergyPlus 9.5 run; coarse-to-fine beam search.")
dk.notes(prs.slides[-1], wrap(NAR["framing_sections"][1]))

t = tab("New Plan")
dk.annotate(f"{SHOTS}/newplan.png", f"{ANNO}/newplan.png",
            crop=(0.0, 0.0, 1.0, 0.80),
            markers=[mk(1, 0.13, 0.20), mk(2, 0.10, 0.40, AMBER), mk(3, 0.13, 0.47, GREEN),
                     mk(4, 0.18, 0.74), mk(5, 0.50, 0.74), mk(6, 0.85, 0.66, AMBER)])
dk.image_slide(prs, "TAB · NEW PLAN", "Launching the week — and showing its inputs",
    f"{ANNO}/newplan.png",
    [(None, "Plan parameters (left):"),
     (1, "Week, days, grid=5, beam=3, levels=3, workers — the search budget"),
     (2, "Optional day/night setpoints (time-block search)"),
     (3, "Launch → hundreds of full-week EnergyPlus runs"),
     (None, "Planning context (why this plan):"),
     (4, "IT-load past + forecast"), (5, "Weather past + forecast (+1σ hot week hedges safety)"),
     (6, "Previous-week setpoints (the as-operated baseline)")],
    notes_for(t), img_frac=0.62)

# ===== ACT 2 — REVIEW (safety + savings evidence) =====
dk.section_slide(prs, "ACT 2 — SAFETY IS A HARD CONSTRAINT, SAVINGS ARE THE CONSEQUENCE",
                 "The evidence gate", "Predicted vs baseline, robust confidence bands, and the inlet trajectory against the 26 °C line.")
dk.notes(prs.slides[-1], wrap(NAR["framing_sections"][2]))

t = tab("Review")
# Slide A: top — KPI comparison + baseline + bands + realized-vs-predicted
dk.annotate(f"{SHOTS}/review.png", f"{ANNO}/review_top.png",
            crop=(0.0, 0.0, 1.0, 0.46),
            markers=[mk(1, 0.22, 0.27), mk(2, 0.83, 0.27, AMBER), mk(3, 0.30, 0.66),
                     mk(4, 0.30, 0.86, GREEN)])
dk.image_slide(prs, "TAB · REVIEW  (1/2)", "Did it beat the baseline — and did reality agree?",
    f"{ANNO}/review_top.png",
    [(1, "KPI comparison: predicted vs baseline (energy, PUE, peak inlet, violations, reduction)"),
     (2, "Baseline = the operator's own as-operated setpoints"),
     (3, "Confidence bands p50 / p90 / max from the robust ensemble"),
     (4, "Realized vs predicted — the twin checked against the deployed week"),
     (None, "Reduction here ≈ 3.6% with 0 predicted violations.")],
    notes_for(t, lead="REVIEW is the crux — spend the most time here. This first slide is the numeric verdict."),
    img_frac=0.66)
# Slide B: bottom — KPI chart + INLET TRAJECTORY (the safety money shot)
dk.annotate(f"{SHOTS}/review.png", f"{ANNO}/review_traj.png",
            crop=(0.0, 0.52, 1.0, 1.0),
            markers=[mk(1, 0.20, 0.40), mk(2, 0.5, 0.72, RED), mk(3, 0.5, 0.80, GREEN)])
dk.image_slide(prs, "TAB · REVIEW  (2/2)", "The safety money-shot: every step stays under the cap",
    f"{ANNO}/review_traj.png",
    [(1, "KPI bar chart: plan vs baseline at a glance"),
     (2, "The red 26 °C cap line — the hard, non-negotiable limit"),
     (3, "Inlet trajectory (nominal + worst-scenario) hugs, but never crosses, the line"),
     (None, "This is what 'cheaper without crossing the line' looks like."),
     (None, "Expert approves/deploys ONLY from this evidence; blocked_unsafe is not approvable.")],
    notes_for(t, extra_qa=4,
              lead="Second Review slide: the inlet trajectory vs the 26 °C cap is the single most important picture in the talk."),
    img_frac=0.66)

# ===== ACT 3 — DASHBOARD + LIVE =====
dk.section_slide(prs, "ACT 3 — THE OPERATOR'S CONTRACT & THE LIVE AUDIT",
                 "At-a-glance verdict, then real-time proof", "Dashboard = what we're running; Live = the cap is holding right now.")
dk.notes(prs.slides[-1], wrap(NAR["framing_sections"][3]))

t = tab("Dashboard")
dk.annotate(f"{SHOTS}/dashboard.png", f"{ANNO}/dashboard.png",
            crop=(0.0, 0.0, 1.0, 0.62),
            markers=[mk(1, 0.13, 0.42), mk(2, 0.42, 0.30), mk(3, 0.45, 0.45, GREEN),
                     mk(4, 0.42, 0.58, GREEN), mk(5, 0.22, 0.86, CY)])
dk.image_slide(prs, "TAB · DASHBOARD", "The one-screen answer: safe and cheaper",
    f"{ANNO}/dashboard.png",
    [(1, "Three active setpoints (SAT 25.25, airflow 4.80, CHWST 17.88)"),
     (2, "Predicted KPIs: energy 259,894 kWh, PUE 1.19"),
     (3, "Peak inlet 25.52 °C < 26 °C cap; 0 violations"),
     (4, "Energy reduction 3.63% vs baseline"),
     (5, "Plan status = DEPLOYED (shadow mode)")],
    notes_for(t), img_frac=0.62)

t = tab("Live")
dk.annotate(f"{SHOTS}/live.png", f"{ANNO}/live.png",
            crop=(0.0, 0.0, 1.0, 1.0),
            markers=[mk(1, 0.80, 0.045, AMBER), mk(2, 0.20, 0.135, GREEN), mk(3, 0.50, 0.235),
                     mk(4, 0.86, 0.71, GREEN), mk(5, 0.13, 0.88, CY)])
dk.image_slide(prs, "TAB · LIVE", "Real-time audit: the cap is holding now (Expert Supervision)",
    f"{ANNO}/live.png",
    [(1, "SIMULATED FEED badge — honesty: this is a labelled sim feed"),
     (2, "Alert banner: all racks normal (warn ≥25 °C, critical ≥26 °C)"),
     (3, "22-rack inlet heat-map — spatial health at a glance"),
     (4, "Worst inlet 24.3 °C → 1.7 °C of headroom to the cap"),
     (5, "Setpoint compliance: commanded vs held, in tolerance")],
    notes_for(t), img_frac=0.52)

# ===== ACT 4 — HISTORY (outer loop closing) =====
dk.section_slide(prs, "ACT 4 — THE OUTER LOOP CLOSING",
                 "Six weeks of convergence, gate-released savings", "Prediction error 1.33% → 0.10%; savings 0 → 3.63%; zero violations.")
dk.notes(prs.slides[-1], wrap(NAR["framing_sections"][4]))

t = tab("History")
dk.annotate(f"{SHOTS}/history.png", f"{ANNO}/history.png",
            crop=(0.0, 0.0, 1.0, 0.66),
            markers=[mk(1, 0.50, 0.22), mk(2, 0.78, 0.20, GREEN), mk(3, 0.30, 0.68),
                     mk(4, 0.74, 0.68, GREEN), mk(5, 0.12, 0.90, AMBER)])
dk.image_slide(prs, "TAB · HISTORY", "Is the twin learning? Predicted vs realized, week over week",
    f"{ANNO}/history.png",
    [(1, "Predicted (teal) vs realized (orange) HVAC energy"),
     (2, "Lines converge as calibration learns → error 1.33% → 0.10%"),
     (3, "Plan ledger: every deployed week, energy, reduction"),
     (4, "Reduction ramps 0% → 3.2% → 3.6% (released only as proven safe)"),
     (5, "Week 1 = 0% (cold start): the gate allowed only the baseline")],
    notes_for(t), img_frac=0.62)

# ===== ACT 5 — DIGITAL TWIN 3D =====
dk.section_slide(prs, "ACT 5 — THE TWIN MADE TANGIBLE",
                 "Seeing the energy-vs-safety trade in space", "The controlled hall, rack rows colored live from telemetry.")
dk.notes(prs.slides[-1], wrap(NAR["framing_sections"][5]))

t = tab("Digital Twin")
dk.annotate(f"{SHOTS}/twin3d.png", f"{ANNO}/twin3d.png",
            crop=(0.0, 0.0, 1.0, 1.0),
            markers=[mk(1, 0.13, 0.12), mk(2, 0.88, 0.12, GREEN), mk(3, 0.52, 0.55),
                     mk(4, 0.12, 0.84, CY)])
dk.image_slide(prs, "TAB · DIGITAL TWIN (3D)", "The physics model you can walk around",
    f"{ANNO}/twin3d.png",
    [(1, "HUD: active plan setpoints (SAT / airflow / CHWST)"),
     (2, "HUD: live KPIs (energy, PUE, peak inlet, violations)"),
     (3, "Rack rows colored from live telemetry — hotspots are visible in space"),
     (4, "Color legend = inlet temperature scale toward the 26 °C cap")],
    notes_for(t), img_frac=0.60)

# ===== ACT 6 — HONEST LIMITS =====
dk.section_slide(prs, "ACT 6 — HONEST LIMITS",
                 "Structurally proven, not yet field-proven", "And the single remaining seam to a live building.")
dk.notes(prs.slides[-1], wrap(NAR["framing_sections"][6]))

dk.bullets_slide(prs, "HONESTY", "What is real, what is simulated, what remains",
    [(0, "Real and exercised today"),
     (1, "Full-physics EnergyPlus 9.5 oracle, the 3-net safety gate, the calibration/learning loop, the whole cockpit"),
     (1, "6 deployed weekly cycles, all tests green; numbers shown are read from the live run database"),
     (0, "Deliberately simulated / shadowed (and labelled)"),
     (1, "Deploy = SHADOW MODE: 45 commands recorded, never actuated"),
     (1, "Telemetry feed is SIMULATED (the SIMULATED FEED badge); 'realized' = perturbed-plant EnergyPlus stand-in"),
     (0, "The one remaining seam to the field"),
     (1, "Connect a real historian to POST /api/telemetry + implement the BACnet adapter behind the existing stub"),
     (2, "Then: recommend-only for 4–8 weeks, calibrate recirculation from real rack sensors, then actuate hall-by-hall")],
    wrap("Say this BEFORE the professor asks. The credibility of the whole talk rests on being upfront: the learning loop "
         "is structurally proven end-to-end in software and measured over 6 weeks, but 'reality' is still a perturbed-plant "
         "simulation until a field adapter + historian connect. That is a config + one-class change, not a redesign."))

# ===== ANTICIPATED QUESTIONS (questions on slide, full answers in notes) =====
def shorten(s, n=100):
    s = s.strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"
bq = NAR["big_questions"]
groups = [bq[:4], bq[4:]]
for gi, g in enumerate(groups):
    bullets = [(1, shorten(q["q"])) for q in g]
    full = "ANTICIPATED QUESTIONS — full answers (read from here; answer crisply, do not over-claim):\n\n" + \
        "\n\n".join("Q: " + q["q"] + "\nA: " + q["a"] for q in g)
    dk.bullets_slide(prs, f"ANTICIPATED QUESTIONS ({gi+1}/2)",
        "The hardest cross-cutting questions" if gi == 0 else "…and the rest of the hard ones",
        bullets, wrap(full))

# ===== CLOSING =====
dk.section_slide(prs, "CLOSING", NAR["deck_title"],
                 "Hard safety constraint · soft energy objective · a learning loop — measured over six weeks.")
dk.notes(prs.slides[-1], wrap("CLOSE:\n" + NAR["closing"] +
    "\n\nRestate the thesis in one breath: " + NAR["one_sentence_thesis"]))

# ===== APPENDIX: measured record + presenting tips =====
dk.bullets_slide(prs, "APPENDIX", "The measured record — six deployed weeks",
    [(0, "Accuracy"), (1, "Weekly-energy prediction error 1.33% → 0.10%; peak-inlet error within ~0.25 °C"),
     (0, "Savings"), (1, "0% → 3.2% → 3.63% vs the as-operated baseline, released as confidence grew"),
     (0, "Safety"), (1, "Zero violations; realized peak inlet rose 23.37 → 25.60 °C, never reached the 26 °C cap (0.40 °C margin)"),
     (0, "Well-posedness (real E+ sweep)"), (1, "Airflow moves hall energy 15.5%, CHWST 3.4%, SAT ~0.5%"),
     (0, "Calibration state (n=7)"), (1, "inlet bias 0.18 °C, σ_inlet 0.14 °C, σ_post 0.36 °C, energy bias ~0.2%")],
    wrap("Backup numbers if the professor wants the quantitative record. All read from the live system, not asserted."))

def first_sent(s):
    s = s.strip(); i = s.find(". ")
    return s[:i + 1] if i > 0 else s
dk.bullets_slide(prs, "APPENDIX", "Delivery tips (gist on slide, full text in notes)",
    [(1, first_sent(tip)) for tip in NAR["presenting_tips"]],
    wrap("DELIVERY TIPS (full):\n\n" + "\n\n".join("• " + t for t in NAR["presenting_tips"])))

out = os.path.join(HERE, "DCTwin_Webapp_Walkthrough_for_Professor.pptx")
dk.save(prs, out)
print("SLIDES:", len(prs.slides._sldIdLst))
print("PPTX:", out, os.path.getsize(out), "bytes")
print("ANNOTATED:", sorted(os.listdir(ANNO)))
