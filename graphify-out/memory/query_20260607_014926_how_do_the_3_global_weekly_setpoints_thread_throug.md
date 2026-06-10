---
type: "query"
date: "2026-06-07T01:49:26.336374+00:00"
question: "How do the 3 global weekly Setpoints thread through the pipeline (beam search -> broadcast -> oracle -> WeeklyKPI -> objective -> recommendation -> robust -> deploy)?"
contributor: "graphify"
source_nodes: ["Setpoints", "WeeklyKPI", "BeamPlanner", "ParallelEnvOracle", "run_weekly_plan", "robust_select", "build_recommendation", "ObjectiveWeights"]
---

# Q: How do the 3 global weekly Setpoints thread through the pipeline (beam search -> broadcast -> oracle -> WeeklyKPI -> objective -> recommendation -> robust -> deploy)?

## Answer

Setpoints (planner/types.py:8) is the data spine, not a flow step: SearchSpace bounds it; run_weekly_plan (pipeline.py:23) shares_data_with it and calls BeamPlanner (beam_search.py:49) which proposes candidate Setpoints and applies Calibration in scoring; ParallelEnvOracle implements Evaluator and .evaluate() calls EvalTask (oracle_worker.py:17) which shares_data_with Setpoints; evaluate_one() runs EnergyPlus with them (3 globals fan to ~45 actuators via BroadcastPolicy->ActionEntry); aggregate_kpi() (kpi.py:33) turns readings into WeeklyKPI (types.py:49); score() calls is_feasible() weighted by ObjectiveWeights to rank; build_recommendation() (recommendation.py:25) emits the winning Setpoints+WeeklyKPI; run_plan_job calls make_oracle_robust_rerank (robust.py:94) and robust_select re-ranks beam finalists across scenarios into RobustResult; run_deploy_job (jobs.py:157) re-runs approved Setpoints on the perturbed plant (build_plant_prototxt) -> realized WeeklyKPI -> calibration. Setpoints (proposed) + WeeklyKPI (measured) are the two value objects every community touches.

## Source Nodes

- Setpoints
- WeeklyKPI
- BeamPlanner
- ParallelEnvOracle
- run_weekly_plan
- robust_select
- build_recommendation
- ObjectiveWeights