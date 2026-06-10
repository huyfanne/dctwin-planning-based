# Graph Report - src  (2026-06-09)

## Corpus Check
- 127 files · ~50,504 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1093 nodes · 2287 edges · 53 communities (49 shown, 4 thin omitted)
- Extraction: 63% EXTRACTED · 37% INFERRED · 0% AMBIGUOUS · INFERRED: 854 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `35079027`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 47|Community 47]]

## God Nodes (most connected - your core abstractions)
1. `Setpoints` - 98 edges
2. `ObjectiveWeights` - 59 edges
3. `PlanStore` - 54 edges
4. `WeeklyKPI` - 49 edges
5. `MockEvaluator` - 48 edges
6. `Path` - 43 edges
7. `MockSurface` - 42 edges
8. `ParallelEnvOracle` - 35 edges
9. `BeamConfig` - 32 edges
10. `BeamPlanner` - 32 edges

## Surprising Connections (you probably didn't know these)
- `test_deploy_status_blocked_on_realized_breach()` --calls--> `deploy_status_for()`  [INFERRED]
  tests/test_jobs.py → webapp/jobs.py
- `test_setpoints_as_tuple_order()` --calls--> `Setpoints`  [INFERRED]
  tests/test_types.py → planner/types.py
- `test_search_space_clip_clamps_all_dims()` --calls--> `Setpoints`  [INFERRED]
  tests/test_types.py → planner/types.py
- `test_weekly_kpi_defaults()` --calls--> `WeeklyKPI`  [INFERRED]
  tests/test_types.py → planner/types.py
- `_good_kpi()` --calls--> `WeeklyKPI`  [INFERRED]
  tests/test_oracle.py → planner/types.py

## Communities (53 total, 4 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (72): BeamConfig, BeamPlanner, MockEvaluator, MockSurface, Analytic test surface: convex energy bowl + monotone inlet model., Deterministic Evaluator for TDD of the planner (no EnergyPlus)., ObjectiveWeights, Soft-penalty weights and hard-constraint tolerances.      Energy (kWh) is the do (+64 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (53): type, mapper_from_env(), Derive a BroadcastPolicy from a (possibly gym-wrapped) dctwin env., discover_monitor(), _is_hall_acu_fan(), _is_plant_power(), MonitorSpec, Shared chiller/CHW-plant electrical power: chiller compressors, CHW pumps,     t (+45 more)

### Community 2 - "Community 2"
Cohesion: 0.05
Nodes (53): Write a pre-validation per-step trajectory to CSV (the diagram's trajectory_*.cs, write_trajectory_csv(), render_report(), validation_metrics(), build_his_col_for_room(), main(), Data Hall 1F 2A' -> tokens '1f 2a' for fuzzy column matching., Map each room to its 'IT loads' column in his_data by fuzzy name match. (+45 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (45): backtest_room(), main(), mape(), picp(), Backtest the seasonal forecaster vs persistence on held-out real telemetry. Repo, Prediction-interval coverage probability: fraction of actuals within [lo, hi]., Fit on all-but-last holdout_days, forecast the holdout, compare seasonal vs, rmse() (+37 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (43): client(), _deploy_client(), _ex(), _make_epw(), _op(), test_cancel_endpoint_running_404_409(), test_create_accepts_week_inside_weather_coverage(), test_create_plan_accepts_valid() (+35 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (38): Calibration, fit_calibration(), from_dict(), identity(), load_calibration(), Output-residual calibration: learn per-KPI bias + uncertainty from the deploy lo, Re-fit the Calibration from the paired history and persist it., recompute_calibration() (+30 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (30): Enum, ActionEntry, BroadcastPolicy, ControlKind, gds_action_spec(), normalize(), One env actuator: which global control feeds it, and its physical bounds., Physical value -> [-1, 1] linear normalization (matches dctwin LINEAR). (+22 more)

### Community 7 - "Community 7"
Cohesion: 0.08
Nodes (31): apply_perturbation(), build_plant_prototxt(), Perturbation, PlantConfig, Perturbed-plant model: the deploy-only 'real' DC = nominal IDF with scaled physi, Scale the configured numeric fields and save a perturbed IDF copy.      Non-nume, Write a perturbed IDF + a DT prototxt copy that points at it. Mirrors     week_c, _cvar() (+23 more)

### Community 8 - "Community 8"
Cohesion: 0.06
Nodes (34): dependencies, react, react-dom, @react-three/drei, @react-three/fiber, recharts, three, devDependencies (+26 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (31): epw_data_period(), epw_first_date(), _md_in_range(), Lightweight EPW coverage check — read the DATA PERIODS line to know which (month, Return ((start_month, start_day), (end_month, end_day)) from the EPW's     'DATA, Human + machine view of the EPW's covered window (month/day, year-agnostic)., First concrete date in the EPW data block (8 header lines, then CSV rows     'ye, Is (month, day) within [start, end], allowing a year wrap (start > end)? (+23 more)

### Community 10 - "Community 10"
Cohesion: 0.14
Nodes (24): Analytic schedule KPI: per-block bowl KPI, energy hour-weighted (equal blocks),, build_recommendation(), energy_reduction_pct(), Index of the safest candidate: fewest inlet violations, then least energy., safest_fallback(), write_recommendation(), Aggregated outcome of one full-week evaluation of a candidate., WeeklyKPI (+16 more)

### Community 11 - "Community 11"
Cohesion: 0.19
Nodes (25): aggregate_kpi(), _hvac_watts(), OracleSettings, One timestep's monitored readings (physical units)., Per-step series for the pre-validation trajectory CSV. Applies the same     warm, Controllable HVAC power for energy: the scoped hall+plant sum when measured,, step_trajectory(), StepSample (+17 more)

### Community 12 - "Community 12"
Cohesion: 0.12
Nodes (19): onAuthed, approvePlan(), Building, clearToken(), createPlan(), getToken(), HallInfra, PlanParams (+11 more)

### Community 13 - "Community 13"
Cohesion: 0.13
Nodes (17): BuildingHall, TopoCRAH, TopoLink, Topology, TopoPlant, Vec3, buildPath(), CRAH() (+9 more)

### Community 14 - "Community 14"
Cohesion: 0.13
Nodes (18): test_plan_sse_stream_keepalive_then_terminal(), test_create_list_and_get(), test_delete_plan_removes_row_and_dir(), test_get_recommendation_tolerates_partial_file(), test_get_trajectory_missing_is_empty(), test_get_trajectory_parses_two_csvs(), test_progress_roundtrip(), test_progress_sanitizes_non_finite() (+10 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (18): A daily time window [start_hour, end_hour) in local hours. end <= start wraps mi, A per-time-block setpoint schedule. `setpoints[i]` applies during `blocks[i]`., Index of the block covering `hour` (first match wins; falls back to 0)., _neighbors(), Warm-start day/night schedule refinement (sub-project B). Stage 2 of the time-bl, Warm-start: seed at (constant,...) per block, then coordinate-descent refine ove, refine_schedule(), ScheduleResult (+10 more)

### Community 16 - "Community 16"
Cohesion: 0.11
Nodes (20): Dashboard(), KPI_LABELS, Props, SETPOINT_LABELS, statusClass(), btn, mockDetail, mockPlan (+12 more)

### Community 17 - "Community 17"
Cohesion: 0.12
Nodes (19): KPI_META, Props, Review(), SETPOINT_LABELS, statusClass(), APPROVED_DETAIL, DEPLOYED_DETAIL, FAILED_DETAIL (+11 more)

### Community 18 - "Community 18"
Cohesion: 0.12
Nodes (19): Docker-gated regression: the demonstrated 666-violation deployment cannot ship., test_breaching_plan_cannot_ship(), Docker-gated smoke: a time-block plan emits a day/night schedule and the per-ste, test_time_block_plan_emits_schedule(), test_residual_source_prefers_raw_predicted(), test_robust_rerank_weights_carry_the_margin(), deploy_status_for(), _kill_eplus_containers() (+11 more)

### Community 19 - "Community 19"
Cohesion: 0.15
Nodes (13): Evaluator, 1-day deploy against the perturbed plant; realized KPIs are captured., test_perturbed_plant_deploy_records_realized(), _batch_deadline(), _infeasible(), ParallelEnvOracle, Inline single-candidate run that ALSO returns the per-step StepSample list., Score time-block WeeklySchedules with full-week EnergyPlus runs (per-step action (+5 more)

### Community 20 - "Community 20"
Cohesion: 0.11
Nodes (14): test_single_candidate_short_window(), test_two_candidates_parallel_processes(), test_tiny_weekly_plan_then_baseline_acceptance(), EnergyPlus oracle runs a 1-day window using the real provided EPW (Nov 2024)., test_oracle_runs_on_real_weather_within_year(), 2-scenario robust re-rank of 2 finalists on a 1-day window (real EnergyPlus)., test_robust_rerank_over_two_scenarios(), make_oracle_robust_rerank() (+6 more)

### Community 21 - "Community 21"
Cohesion: 0.16
Nodes (13): _make(), test_deploy_status_blocked_on_realized_breach(), test_job_failure_sets_failed(), test_job_runs_and_sets_status(), test_jobrunner_dispatches_deploy(), test_reconcile_orphans_fails_non_terminal_plans(), test_request_cancel_skips_a_queued_plan(), test_request_cancel_stops_a_running_plan() (+5 more)

### Community 22 - "Community 22"
Cohesion: 0.15
Nodes (16): TopoRackRow, Airflow(), clamp(), lerp(), particleSpeed(), Props, RGB, tempColorRGB() (+8 more)

### Community 23 - "Community 23"
Cohesion: 0.11
Nodes (18): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection, moduleResolution (+10 more)

### Community 24 - "Community 24"
Cohesion: 0.11
Nodes (17): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, moduleResolution, noEmit (+9 more)

### Community 25 - "Community 25"
Cohesion: 0.27
Nodes (15): is_feasible(), Lower is better. Infeasible candidates score +inf and never enter the beam., score(), _kpi(), test_feasible_when_no_violations(), test_infeasible_when_inlet_violation_exceeds_tol(), test_inlet_forecast_margin_default_is_noop(), test_inlet_forecast_margin_tightens_gate() (+7 more)

### Community 26 - "Community 26"
Cohesion: 0.26
Nodes (12): OracleConfig, _FakeForecast, _good_kpi(), _stub_week_config(), test_evaluate_bounds_a_hung_worker_by_the_deadline(), test_materializes_forecast(), test_process_pool_preserves_order(), test_process_pool_timeout_marks_infeasible() (+4 more)

### Community 27 - "Community 27"
Cohesion: 0.20
Nodes (9): deploy(), _NullForecast, Forecast token for deploy: workloads already materialized; carry week_start., Sim-only deployment: require approval, run the plant week, record realized KPIs., _setpoints_from_rec(), _FakeOracle, _rec(), test_deploy_refuses_when_not_approved() (+1 more)

### Community 28 - "Community 28"
Cohesion: 0.20
Nodes (4): _atomic_write_json(), Write JSON so a concurrent reader never sees a partial file: write a sibling, Read JSON tolerantly: a missing, empty, or caught-mid-write file -> default., _read_json()

### Community 29 - "Community 29"
Cohesion: 0.19
Nodes (8): _coarse_grid(), _no_signal(), PlanResult, _top_b(), Evaluator, Protocol implemented by the dctwin oracle (Plan 2) and the MockEvaluator., `on_result`, if given, is called once per candidate as it finishes         (for, Protocol

### Community 30 - "Community 30"
Cohesion: 0.18
Nodes (6): Props, MockEventSource, cancelPlan(), getWeather(), planStreamUrl(), Progress

### Community 31 - "Community 31"
Cohesion: 0.27
Nodes (11): as_operated_setpoints(), BaselineColumns, _match(), _pooled_median(), Regex patterns selecting the as-operated control columns in the history CSV., Derive the plant's current ("as-operated") setpoints from telemetry medians., _df(), test_as_operated_setpoints_clips_to_search_space() (+3 more)

### Community 32 - "Community 32"
Cohesion: 0.18
Nodes (8): Exception, test_record_failure_falls_back_to_class_name(), test_record_failure_stores_reason_and_status(), PlanCancelled, Raised cooperatively (from progress_cb) when an operator cancels a running plan., Persist a failure reason via the progress channel, then mark the plan failed,, Run a deploy job now. Sets 'deploying'; the deploy_runner must set         'depl, record_failure()

### Community 33 - "Community 33"
Cohesion: 0.22
Nodes (8): Bounds, Inclusive physical bounds for one control dimension., test_bounds_clip_inside_and_outside(), test_bounds_rejects_inverted(), test_default_search_space_matches_gds_bounds(), test_search_space_clip_clamps_all_dims(), test_setpoints_as_tuple_order(), test_weekly_kpi_defaults()

### Community 34 - "Community 34"
Cohesion: 0.20
Nodes (7): Props, SortDir, SortKey, onReview, PLANS, deletePlan(), PlanSummary

### Community 35 - "Community 35"
Cohesion: 0.31
Nodes (7): test_allowed_transitions(), test_deploy_blocked_allows_retry_or_reject(), test_forbidden_transitions(), test_unsafe_statuses_are_not_approvable(), can_transition(), PlanStatus, Plan status values + the allowed transition graph (the outer-loop state machine)

### Community 36 - "Community 36"
Cohesion: 0.22
Nodes (8): API, Backend (FastAPI), code:bash (cd /mnt/lv/home/hoanghuy/newcode/dctwin/src), code:bash (cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend), code:bash (# backend (no Docker needed; integration tests are deselecte), Digital Twin Dual-Loop — Web App, Frontend (React + Vite), Tests

### Community 37 - "Community 37"
Cohesion: 0.29
Nodes (3): Props, SceneBoundary, State

### Community 38 - "Community 38"
Cohesion: 0.29
Nodes (6): code:bash (# 1. (once) fit the statistical forecaster from historical d), code:bash (python -m pytest                       # fast unit tests (no), Digital Twin Dual-Loop Control Framework (dtwin-dualloop), Tests, The four template modes, Weekly operator workflow

### Community 39 - "Community 39"
Cohesion: 0.33
Nodes (5): code:js (export default defineConfig([), code:js (// eslint.config.js), Expanding the ESLint configuration, React Compiler, React + TypeScript + Vite

### Community 40 - "Community 40"
Cohesion: 0.60
Nodes (4): BaseModel, PlanCreated, PlanParams, SetpointEdit

### Community 41 - "Community 41"
Cohesion: 0.50
Nodes (3): Docker-gated: a real plan emits both trajectory CSVs and GET /trajectory serves, # NOTE: week_start "2013-11-11" assumes models/forecaster.pkl has weather_file=N, test_prevalidation_emits_both_trajectories()

## Knowledge Gaps
- **133 isolated node(s):** `tsBuildInfoFile`, `target`, `lib`, `module`, `types` (+128 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Path` connect `Community 2` to `Community 0`, `Community 1`, `Community 3`, `Community 4`, `Community 5`, `Community 7`, `Community 9`, `Community 10`, `Community 14`, `Community 18`, `Community 19`, `Community 20`, `Community 22`, `Community 27`?**
  _High betweenness centrality (0.370) - this node is a cross-community bridge._
- **Why does `Setpoints` connect `Community 20` to `Community 0`, `Community 1`, `Community 2`, `Community 33`, `Community 6`, `Community 7`, `Community 10`, `Community 43`, `Community 15`, `Community 18`, `Community 19`, `Community 26`, `Community 27`, `Community 29`, `Community 31`?**
  _High betweenness centrality (0.260) - this node is a cross-community bridge._
- **Why does `run_plan_job()` connect `Community 18` to `Community 32`, `Community 0`, `Community 2`, `Community 3`, `Community 5`, `Community 41`, `Community 19`, `Community 20`, `Community 26`, `Community 31`?**
  _High betweenness centrality (0.108) - this node is a cross-community bridge._
- **Are the 94 inferred relationships involving `Setpoints` (e.g. with `AITrajectoryReplay` and `WeeklyPlanTemplate`) actually correct?**
  _`Setpoints` has 94 INFERRED edges - model-reasoned connections that need verification._
- **Are the 57 inferred relationships involving `ObjectiveWeights` (e.g. with `WeeklyPlanTemplate` and `_FakeForecaster`) actually correct?**
  _`ObjectiveWeights` has 57 INFERRED edges - model-reasoned connections that need verification._
- **Are the 35 inferred relationships involving `PlanStore` (e.g. with `_make()` and `test_jobrunner_dispatches_deploy()`) actually correct?**
  _`PlanStore` has 35 INFERRED edges - model-reasoned connections that need verification._
- **Are the 47 inferred relationships involving `WeeklyKPI` (e.g. with `_Forecast` and `_FakeOracle`) actually correct?**
  _`WeeklyKPI` has 47 INFERRED edges - model-reasoned connections that need verification._