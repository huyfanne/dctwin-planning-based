# Graph Report - src  (2026-06-08)

## Corpus Check
- 7 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1147 nodes · 2388 edges · 68 communities (59 shown, 9 thin omitted)
- Extraction: 68% EXTRACTED · 32% INFERRED · 0% AMBIGUOUS · INFERRED: 776 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Beam Search Planner|Beam Search Planner]]
- [[_COMMUNITY_KPI & Oracle Worker|KPI & Oracle Worker]]
- [[_COMMUNITY_Action Broadcast|Action Broadcast]]
- [[_COMMUNITY_Deploy & Trajectory Replay|Deploy & Trajectory Replay]]
- [[_COMMUNITY_Frontend Dependencies|Frontend Dependencies]]
- [[_COMMUNITY_New Plan & Review Pages|New Plan & Review Pages]]
- [[_COMMUNITY_Backend API & Job Runner|Backend API & Job Runner]]
- [[_COMMUNITY_Load Forecaster|Load Forecaster]]
- [[_COMMUNITY_3D Twin Scene Components|3D Twin Scene Components]]
- [[_COMMUNITY_Frontend App & Dashboard|Frontend App & Dashboard]]
- [[_COMMUNITY_Topology Builder + Tests|Topology Builder + Tests]]
- [[_COMMUNITY_Robust Scenario Selection|Robust Scenario Selection]]
- [[_COMMUNITY_Weather  Week Config (EPW)|Weather / Week Config (EPW)]]
- [[_COMMUNITY_Recommendation & Validation|Recommendation & Validation]]
- [[_COMMUNITY_Plan Store + Tests|Plan Store + Tests]]
- [[_COMMUNITY_Output-Residual Calibration|Output-Residual Calibration]]
- [[_COMMUNITY_TS Config (app)|TS Config (app)]]
- [[_COMMUNITY_Airflow Viz Helpers|Airflow Viz Helpers]]
- [[_COMMUNITY_TS Config (node)|TS Config (node)]]
- [[_COMMUNITY_App Shell & History Page|App Shell & History Page]]
- [[_COMMUNITY_ForecasterKPIOracle Test Specs|Forecaster/KPI/Oracle Test Specs]]
- [[_COMMUNITY_History Advance (loop closure)|History Advance (loop closure)]]
- [[_COMMUNITY_Auth + Tests|Auth + Tests]]
- [[_COMMUNITY_Job Runner Tests|Job Runner Tests]]
- [[_COMMUNITY_EnergyPlus Oracle & Deploy Tests|EnergyPlus Oracle & Deploy Tests]]
- [[_COMMUNITY_SetpointsSearchSpace + Integration|Setpoints/SearchSpace + Integration]]
- [[_COMMUNITY_Forecaster Backtest|Forecaster Backtest]]
- [[_COMMUNITY_Perturbed Plant Model|Perturbed Plant Model]]
- [[_COMMUNITY_API Auth Tests|API Auth Tests]]
- [[_COMMUNITY_Prevalidation & WeeklyKPI|Prevalidation & WeeklyKPI]]
- [[_COMMUNITY_Oracle Unit Tests|Oracle Unit Tests]]
- [[_COMMUNITY_PipelineRobust Test Specs|Pipeline/Robust Test Specs]]
- [[_COMMUNITY_Planner API (weatherplantrobust)|Planner API (weather/plant/robust)]]
- [[_COMMUNITY_Planner API (core)|Planner API (core)]]
- [[_COMMUNITY_Objective & Scoring|Objective & Scoring]]
- [[_COMMUNITY_BoundsTypes Tests|Bounds/Types Tests]]
- [[_COMMUNITY_Forecaster Fit|Forecaster Fit]]
- [[_COMMUNITY_Planner API (forecaster)|Planner API (forecaster)]]
- [[_COMMUNITY_Oracle Public API|Oracle Public API]]
- [[_COMMUNITY_HistoryObjective Test Specs|History/Objective Test Specs]]
- [[_COMMUNITY_Broadcast Public API|Broadcast Public API]]
- [[_COMMUNITY_3D Error Boundary|3D Error Boundary]]
- [[_COMMUNITY_Job Runners (plandeploy)|Job Runners (plan/deploy)]]
- [[_COMMUNITY_Plan Status State Machine|Plan Status State Machine]]
- [[_COMMUNITY_Recalibrator Seam (P2c)|Recalibrator Seam (P2c)]]
- [[_COMMUNITY_API Schemas|API Schemas]]
- [[_COMMUNITY_Search Space Constants|Search Space Constants]]
- [[_COMMUNITY_Evaluator Protocol|Evaluator Protocol]]
- [[_COMMUNITY_Fit-Forecaster Test Specs|Fit-Forecaster Test Specs]]
- [[_COMMUNITY_Plant Test Specs|Plant Test Specs]]
- [[_COMMUNITY_Recommendation Test Specs|Recommendation Test Specs]]
- [[_COMMUNITY_Topology Test Specs|Topology Test Specs]]
- [[_COMMUNITY_TopologyCalibration API|Topology/Calibration API]]
- [[_COMMUNITY_files|files]]
- [[_COMMUNITY_test_epw|test_epw]]
- [[_COMMUNITY_test_monitor|test_monitor]]
- [[_COMMUNITY_test_prevalidation_gate.py|test_prevalidation_gate.py]]
- [[_COMMUNITY_test_plan_weekly|test_plan_weekly]]
- [[_COMMUNITY_list_plans|list_plans]]
- [[_COMMUNITY___init__.py|__init__.py]]
- [[_COMMUNITY_test_smoke.py|test_smoke.py]]
- [[_COMMUNITY_test_real_weather|test_real_weather]]
- [[_COMMUNITY___init__.py|__init__.py]]

## God Nodes (most connected - your core abstractions)
1. `Setpoints` - 69 edges
2. `ObjectiveWeights` - 53 edges
3. `PlanStore` - 48 edges
4. `WeeklyKPI` - 44 edges
5. `ParallelEnvOracle` - 41 edges
6. `Path` - 37 edges
7. `_FakeForecast` - 36 edges
8. `BeamPlanner` - 36 edges
9. `MockSurface` - 36 edges
10. `BeamConfig` - 34 edges

## Surprising Connections (you probably didn't know these)
- `Recommendation type` --semantically_similar_to--> `recommendation.json`  [INFERRED] [semantically similar]
  src/frontend/src/api.ts → src/README.md
- `test_setpoints_as_tuple_order()` --calls--> `Setpoints`  [INFERRED]
  tests/test_types.py → planner/types.py
- `test_search_space_clip_clamps_all_dims()` --calls--> `Setpoints`  [INFERRED]
  tests/test_types.py → planner/types.py
- `test_weekly_kpi_defaults()` --calls--> `WeeklyKPI`  [INFERRED]
  tests/test_types.py → planner/types.py
- `test_run_prevalidation_emits_worst_trajectory()` --calls--> `build_recommendation`  [INFERRED]
  tests/test_prevalidation_gate.py → planner/recommendation.py

## Communities (68 total, 9 thin omitted)

### Community 0 - "Beam Search Planner"
Cohesion: 0.06
Nodes (40): Exception, JobRunner, as_operated_setpoints(), BaselineColumns, _match(), _pooled_median(), Regex patterns selecting the as-operated control columns in the history CSV., Derive the plant's current ("as-operated") setpoints from telemetry medians. (+32 more)

### Community 1 - "KPI & Oracle Worker"
Cohesion: 0.08
Nodes (37): ActionEntry, BroadcastPolicy, ControlKind, gds_action_spec, normalize, Enum, action_spec_from_actions, bounds_for (+29 more)

### Community 2 - "Action Broadcast"
Cohesion: 0.07
Nodes (39): fit_calibration, recompute_calibration, advance_calibration, advance_history, refit_from_history, from_dict(), identity(), load_calibration() (+31 more)

### Community 3 - "Deploy & Trajectory Replay"
Cohesion: 0.12
Nodes (35): edit_setpoints, get_calibration, get_progress, get_topology, Props, BASELINE_KPIS, KPI_META, Props (+27 more)

### Community 4 - "Frontend Dependencies"
Cohesion: 0.07
Nodes (34): build_forecaster, Forecast, loading_from_it_loads, persistence_window, seasonal_climatology, SeasonalForecaster, StatisticalForecaster, Day-of-week x time-of-day climatology forecaster with p10/p50/p90 bands. (+26 more)

### Community 5 - "New Plan & Review Pages"
Cohesion: 0.12
Nodes (33): PlanRequest, run_weekly_plan, apply_forecast_margin(), Set inlet_forecast_margin = k * sigma_inlet so the search treats the inlet cap, Fail-fast BEFORE any EnergyPlus run (spec §11). Raises ValueError on a     misco, Forecast -> best-first search -> recommendation dict. The DRY planning core., validate_plan_request(), RobustResult (+25 more)

### Community 6 - "Backend API & Job Runner"
Cohesion: 0.08
Nodes (33): test_plan_weekly, Perturbed-plant model: the deploy-only 'real' DC = nominal IDF with scaled physi, Scale the configured numeric fields and save a perturbed IDF copy.      Non-nume, _cvar(), _quantile(), Scenario/ensemble-robust setpoint selection (P2b): evaluate the beam finalists a, N deterministic PlantConfig draws: scale EVERY perturbation factor by     evenly, Ensemble half-width: a prior at cold-start, widened by the calibrated inlet (+25 more)

### Community 7 - "Load Forecaster"
Cohesion: 0.09
Nodes (33): epw_data_period, week_within_epw, test_real_weather, epw_first_date(), _md_in_range(), Lightweight EPW coverage check — read the DATA PERIODS line to know which (month, Return ((start_month, start_day), (end_month, end_day)) from the EPW's     'DATA, Is (month, day) within [start, end], allowing a year wrap (start > end)? (+25 more)

### Community 8 - "3D Twin Scene Components"
Cohesion: 0.06
Nodes (34): dependencies, react, react-dom, @react-three/drei, @react-three/fiber, recharts, three, devDependencies (+26 more)

### Community 9 - "Frontend App & Dashboard"
Cohesion: 0.13
Nodes (31): Evaluator, test_single_candidate_short_window(), test_two_candidates_parallel_processes(), test_tiny_weekly_plan_then_baseline_acceptance(), EnergyPlus oracle runs a 1-day window using the real provided EPW (Nov 2024)., test_oracle_runs_on_real_weather_within_year(), 2-scenario robust re-rank of 2 finalists on a 1-day window (real EnergyPlus)., test_robust_rerank_over_two_scenarios() (+23 more)

### Community 10 - "Topology Builder + Tests"
Cohesion: 0.09
Nodes (27): DigitalTwin3D, HudStat, Topology type, DigitalTwin3D(), HudStatProps, num(), PLAN_DETAIL, TOPO (+19 more)

### Community 11 - "Robust Scenario Selection"
Cohesion: 0.18
Nodes (28): BeamConfig, BeamPlanner, Calibration, ObjectiveWeights, Soft-penalty weights and hard-constraint tolerances.      Energy (kWh) is the do, test_on_eval_ticks_once_per_candidate(), test_on_level_called_once_per_level(), test_plan_works_without_callback() (+20 more)

### Community 12 - "Weather / Week Config (EPW)"
Cohesion: 0.11
Nodes (27): BaseModel, JobRunner._loop, JobRunner.run_deploy_sync, JobRunner.submit, approve, create_plan, deploy_plan, get_plan (+19 more)

### Community 13 - "Recommendation & Validation"
Cohesion: 0.15
Nodes (22): Building, TopoCRAH, TopoLink, TopoPlant, TopoRackRow, Vec3, buildPath(), Props (+14 more)

### Community 14 - "Plan Store + Tests"
Cohesion: 0.12
Nodes (18): PlanStore, test_plan_sse_stream_keepalive_then_terminal(), test_create_list_and_get(), test_delete_plan_removes_row_and_dir(), test_get_recommendation_tolerates_partial_file(), test_get_trajectory_missing_is_empty(), test_get_trajectory_parses_two_csvs(), test_progress_roundtrip() (+10 more)

### Community 15 - "Output-Residual Calibration"
Cohesion: 0.11
Nodes (26): test_building_has_all_stacked_halls(), test_building_per_hall_infrastructure(), test_parse_zone_bboxes_world_coords(), test_topology_has_22_crahs_and_racks_and_plant(), build_building_topology, build_hall_topology, _acu_counts_from_text(), _bboxes_from_text() (+18 more)

### Community 16 - "TS Config (app)"
Cohesion: 0.13
Nodes (23): Aggregated outcome of one full-week evaluation of a candidate., _kpi_from_predicted(), Independently replay the RECOMMENDED setpoints (not the stored predicted_kpis), Compare the recommended plan (predicted KPIs) against a baseline run., Production wrapper: build the real ParallelEnvOracle and run an independent repl, Production wrapper: nominal replay + the deterministic max-perturbation scenario, run_prevalidation(), run_prevalidation_with_oracle() (+15 more)

### Community 17 - "Airflow Viz Helpers"
Cohesion: 0.18
Nodes (20): _ex(), _make_epw(), _op(), test_create_accepts_week_inside_weather_coverage(), test_create_plan_accepts_valid(), test_create_plan_rejects_bad_grid(), test_create_rejects_week_outside_weather_coverage(), test_expert_can_approve() (+12 more)

### Community 18 - "TS Config (node)"
Cohesion: 0.12
Nodes (21): AITrajectoryReplay, BaselineTrajectory, _NullForecast, _setpoints_from_rec, deploy, build_his_col_for_room, forecaster.pkl config dict, fit_forecaster main (+13 more)

### Community 19 - "App Shell & History Page"
Cohesion: 0.18
Nodes (20): build_recommendation, energy_reduction_pct, write_recommendation, test_recommendation, build_recommendation schema 1.0; robust block bumps to 1.1, energy_reduction_pct vs baseline, _kpi(), _rk() (+12 more)

### Community 20 - "Forecaster/KPI/Oracle Test Specs"
Cohesion: 0.15
Nodes (18): test_deploy_loop, 1-day deploy against the perturbed plant; realized KPIs are captured., test_perturbed_plant_deploy_records_realized(), Docker-gated regression: the demonstrated 666-violation deployment cannot ship., test_breaching_plan_cannot_ship(), Docker-gated smoke: a time-block plan emits a day/night schedule and the per-ste, test_time_block_plan_emits_schedule(), pickle_load (+10 more)

### Community 21 - "History Advance (loop closure)"
Cohesion: 0.11
Nodes (18): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection, moduleResolution (+10 more)

### Community 22 - "Auth + Tests"
Cohesion: 0.15
Nodes (14): deploy(), _NullForecast, Forecast token for deploy: workloads already materialized; carry week_start., Sim-only deployment: require approval, run the plant week, record realized KPIs., _setpoints_from_rec(), test_deploy_gate, _FakeOracle, _rec() (+6 more)

### Community 23 - "Job Runner Tests"
Cohesion: 0.23
Nodes (18): is_feasible, score, Lower is better. Infeasible candidates score +inf and never enter the beam., test_objective, is_feasible tolerances; rh_hard toggle; infeasible flag/non-finite -> INFEASIBLE, _kpi(), score dominated by energy + additive soft penalties (temp/rh/zone), test_feasible_when_no_violations() (+10 more)

### Community 24 - "EnergyPlus Oracle & Deploy Tests"
Cohesion: 0.14
Nodes (9): TokenAuth, test_empty_tokens_disables_auth(), test_empty_tokens_with_insecure_disables_auth(), test_invalid_token_401(), test_require_role_allows_equal_or_higher(), test_require_role_rejects_insufficient(), test_role_resolution(), Bearer-token auth with two roles (operator < expert). (+1 more)

### Community 25 - "Setpoints/SearchSpace + Integration"
Cohesion: 0.11
Nodes (17): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, moduleResolution, noEmit (+9 more)

### Community 26 - "Forecaster Backtest"
Cohesion: 0.17
Nodes (9): onAuthed, clearToken(), getToken(), setToken(), verifyToken(), App(), NAV, Page (+1 more)

### Community 27 - "Perturbed Plant Model"
Cohesion: 0.20
Nodes (12): MockSurface, Analytic test surface: convex energy bowl + monotone inlet model., Deterministic Evaluator for TDD of the planner (no EnergyPlus)., Analytic schedule KPI: per-block bowl KPI, energy hour-weighted (equal blocks),, test_mock_evaluator, MockSurface energy minimized at optimum; deterministic batched eval, test_deterministic_and_batched(), test_energy_minimized_at_optimum() (+4 more)

### Community 28 - "API Auth Tests"
Cohesion: 0.18
Nodes (13): MonitorSpec, read_step_sample, run_episode, Step a (already-built) env to completion with a fixed action; aggregate KPI., Like run_episode but also returns the per-step StepSample list., Step the env to completion, switching the action by local time-of-day from `sche, run_episode_with_samples(), _FakeEnv (+5 more)

### Community 29 - "Prevalidation & WeeklyKPI"
Cohesion: 0.14
Nodes (14): Docker-gated: a real plan emits both trajectory CSVs and GET /trajectory serves, # NOTE: week_start "2013-11-11" assumes models/forecaster.pkl has weather_file=N, test_prevalidation_emits_both_trajectories(), StepSample, _hvac_watts(), One timestep's monitored readings (physical units)., Controllable HVAC power for energy: the scoped hall+plant sum when measured,, Per-step series for the pre-validation trajectory CSV. Applies the same     warm (+6 more)

### Community 30 - "Oracle Unit Tests"
Cohesion: 0.18
Nodes (13): discover_monitor, _is_hall_acu_fan(), _is_plant_power(), Scan a dctwin env's observations and classify the ones we read each step.      P, Shared chiller/CHW-plant electrical power: chiller compressors, CHW pumps,     t, test_monitor, discover_monitor classifies observations; requires power obs, _FakeEnv (+5 more)

### Community 31 - "Pipeline/Robust Test Specs"
Cohesion: 0.13
Nodes (15): API client, Recommendation type, App (frontend root), frontend package, Vite /api proxy, Dashboard(), KPI_LABELS, Props (+7 more)

### Community 32 - "Planner API (weather/plant/robust)"
Cohesion: 0.15
Nodes (11): PlanResult, History, _coarse_grid(), _no_signal(), _top_b(), Protocol implemented by the dctwin oracle (Plan 2) and the MockEvaluator., `on_result`, if given, is called once per candidate as it finishes         (for, Protocol (+3 more)

### Community 33 - "Planner API (core)"
Cohesion: 0.23
Nodes (14): evaluate_one, _configure_backend(), evaluate_one_schedule(), evaluate_one_with_samples(), _infeasible(), Best-effort: unblock a stuck BCVTB recv() (shutdown the connection) and stop+rem, Like evaluate_one but returns (WeeklyKPI, list[StepSample]). For the inline, Process-pool target for a time-block schedule. Same env setup as evaluate_one bu (+6 more)

### Community 34 - "Objective & Scoring"
Cohesion: 0.40
Nodes (15): aggregate_kpi, OracleSettings, _sample(), test_empty_samples_is_infeasible(), test_empty_samples_sentinels(), test_energy_is_hvac_power_times_hours(), test_feasible_true_on_successful_aggregation(), test_inlet_excess_uses_soft_margin() (+7 more)

### Community 35 - "Bounds/Types Tests"
Cohesion: 0.17
Nodes (14): build_his_col_for_room(), main(), Data Hall 1F 2A' -> tokens '1f 2a' for fuzzy column matching., Map each room to its 'IT loads' column in his_data by fuzzy name match., Fit the forecaster config and write the pkl.      To regenerate the production p, _room_token(), save_forecaster_config(), test_fit_forecaster (+6 more)

### Community 36 - "Forecaster Fit"
Cohesion: 0.19
Nodes (9): A daily time window [start_hour, end_hour) in local hours. end <= start wraps mi, A per-time-block setpoint schedule. `setpoints[i]` applies during `blocks[i]`., Index of the block covering `hour` (first match wins; falls back to 0)., TimeBlock, WeeklySchedule, test_run_episode_schedule_switches_action_by_hour(), test_default_blocks_partition_the_day(), test_schedule_length_invariant() (+1 more)

### Community 37 - "Planner API (forecaster)"
Cohesion: 0.21
Nodes (8): EvalTask, _batch_deadline(), _infeasible(), Inline single-candidate run that ALSO returns the per-step StepSample list., Score time-block WeeklySchedules with full-week EnergyPlus runs (per-step action, Wall-clock backstop for a whole batch. Each parallel wave is bounded by the, Picklable description of one candidate evaluation (process-pool payload)., test_batch_deadline_scales_with_waves_not_task_count()

### Community 38 - "Oracle Public API"
Cohesion: 0.19
Nodes (10): Inclusive physical bounds for one control dimension., test_bounds_clip_inside_and_outside(), test_bounds_rejects_inverted(), test_default_search_space_matches_gds_bounds(), test_search_space_clip_clamps_all_dims(), test_setpoints_as_tuple_order(), test_weekly_kpi_defaults(), Bounds (+2 more)

### Community 39 - "History/Objective Test Specs"
Cohesion: 0.27
Nodes (10): backtest_room, main, mape(), picp(), Backtest the seasonal forecaster vs persistence on held-out real telemetry. Repo, Prediction-interval coverage probability: fraction of actuals within [lo, hi]., Fit on all-but-last holdout_days, forecast the holdout, compare seasonal vs, rmse() (+2 more)

### Community 40 - "Broadcast Public API"
Cohesion: 0.24
Nodes (9): _neighbors(), Warm-start day/night schedule refinement (sub-project B). Stage 2 of the time-bl, Warm-start: seed at (constant,...) per block, then coordinate-descent refine ove, refine_schedule(), ScheduleResult, _Monotone, Schedule evaluator where warmer SAT / lower flow is CHEAPER but raises inlet. Th, test_refine_schedule_finds_a_cheaper_night_relaxed_split() (+1 more)

### Community 41 - "3D Error Boundary"
Cohesion: 0.18
Nodes (11): TokenAuth.check, TokenAuth.from_env, TokenAuth.require, create_app, client(), _deploy_client(), test_cancel_endpoint_running_404_409(), test_delete_endpoint_terminal_404_409() (+3 more)

### Community 42 - "Job Runners (plan/deploy)"
Cohesion: 0.25
Nodes (4): _atomic_write_json(), Write JSON so a concurrent reader never sees a partial file: write a sibling, Read JSON tolerantly: a missing, empty, or caught-mid-write file -> default., _read_json()

### Community 43 - "Plan Status State Machine"
Cohesion: 0.22
Nodes (6): Props, SortDir, SortKey, onReview, PLANS, deletePlan()

### Community 44 - "Recalibrator Seam (P2c)"
Cohesion: 0.22
Nodes (8): test_oracle_worker, read_step_sample collects named obs values into StepSample, run_episode steps env and aggregates KPI over steps, test_configure_backend_sets_host_and_bounds_socket_timeout(), test_run_with_timeout_fires_watchdog_on_hang(), test_run_with_timeout_returns_value_on_fast_run(), test_teardown_container_is_best_effort(), test_teardown_container_shuts_down_conn_to_unblock_recv()

### Community 45 - "API Schemas"
Cohesion: 0.22
Nodes (5): AITrajectoryReplay, Replay the recommended weekly setpoints (held constant) over the full week., BaselineTrajectory, Conservative baseline: coolest SAT/CHW, maximum airflow (safe, energy-heavy)., TrajectoryPolicyTemplate

### Community 46 - "Search Space Constants"
Cohesion: 0.28
Nodes (8): test_is_terminal_table(), test_progress_frame_shape(), is_terminal(), plan_sse_stream(), progress_frame(), A plan is terminal once it leaves the queued/running/deploying states., One SSE frame: the latest progress + the plan's current status., Yield SSE chunks for a plan's progress until it turns terminal, the client     d

### Community 47 - "Evaluator Protocol"
Cohesion: 0.29
Nodes (6): P2c seam: future EnergyPlus parameter recalibration — tune the twin's physical p, Return EnergyPlus model-parameter updates once enough realized weeks +     drift, recalibrate, test_recalibrator, recalibrate is a documented no-op seam (returns None), test_recalibrate_is_a_documented_noop_seam()

### Community 48 - "Fit-Forecaster Test Specs"
Cohesion: 0.33
Nodes (3): RecommendTemplate, One-shot weekly planner: heuristic search over 3 setpoints, EnergyPlus-scored., WeeklyPlanTemplate

### Community 50 - "Recommendation Test Specs"
Cohesion: 0.40
Nodes (3): test_prevalidation_gate, set_status approves/rejects recommendation.json, test_run_prevalidation_emits_worst_trajectory()

### Community 51 - "Topology Test Specs"
Cohesion: 0.40
Nodes (5): test_kpi, empty samples -> infeasible sentinel KPI (inf energy, huge violations), aggregate_kpi: HVAC energy = power*hours; pue ignores zero-IT steps, inlet/rh/zone violation + excess/excursion counting with soft margins, warmup_steps excluded from KPI unless too few samples

### Community 52 - "Topology/Calibration API"
Cohesion: 0.50
Nodes (4): test_plant, apply_perturbation scales fan efficiency / coil flow on building.idf, build_plant_prototxt points engine config at perturbed absolute IDF, DEFAULT_PLANT perturbs Fan_VariableVolume + Coil_Cooling_Water

### Community 53 - "files"
Cohesion: 0.50
Nodes (4): test_topology, build_hall_topology: 22 controlled ACUs, racks, plant, deterministic layout, parse_zone_bboxes yields non-degenerate world-coord boxes for 7 halls, GDS building has 7 stacked halls, 1 controlled (1F 2A), 28 air loops total

### Community 55 - "test_monitor"
Cohesion: 0.67
Nodes (3): test_epw, epw_data_period parses DATA PERIODS start/end month-day, week_within_epw handles year-wrap window membership

## Knowledge Gaps
- **178 isolated node(s):** `tsBuildInfoFile`, `target`, `lib`, `module`, `types` (+173 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Path` connect `Forecaster/KPI/Oracle Test Specs` to `Action Broadcast`, `Bounds/Types Tests`, `Frontend Dependencies`, `Planner API (forecaster)`, `Backend API & Job Runner`, `Load Forecaster`, `History/Objective Test Specs`, `Frontend App & Dashboard`, `API Schemas`, `Recommendation & Validation`, `Plan Store + Tests`, `Fit-Forecaster Test Specs`, `TS Config (app)`, `Output-Residual Calibration`, `App Shell & History Page`, `Auth + Tests`?**
  _High betweenness centrality (0.201) - this node is a cross-community bridge._
- **Why does `Setpoints` connect `Frontend App & Dashboard` to `Planner API (weather/plant/robust)`, `KPI & Oracle Worker`, `Planner API (core)`, `Frontend Dependencies`, `New Plan & Review Pages`, `Oracle Public API`, `Backend API & Job Runner`, `Planner API (forecaster)`, `Robust Scenario Selection`, `API Schemas`, `Fit-Forecaster Test Specs`, `TS Config (app)`, `App Shell & History Page`, `Forecaster/KPI/Oracle Test Specs`, `Auth + Tests`, `Perturbed Plant Model`?**
  _High betweenness centrality (0.131) - this node is a cross-community bridge._
- **Why does `PlanStore` connect `Plan Store + Tests` to `Beam Search Planner`, `Deploy & Trajectory Replay`, `3D Error Boundary`, `Job Runners (plan/deploy)`, `Search Space Constants`, `Airflow Viz Helpers`, `App Shell & History Page`, `Forecaster/KPI/Oracle Test Specs`, `Prevalidation & WeeklyKPI`?**
  _High betweenness centrality (0.106) - this node is a cross-community bridge._
- **Are the 60 inferred relationships involving `Setpoints` (e.g. with `AITrajectoryReplay` and `.initialize()`) actually correct?**
  _`Setpoints` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 49 inferred relationships involving `ObjectiveWeights` (e.g. with `WeeklyPlanTemplate` and `.initialize()`) actually correct?**
  _`ObjectiveWeights` has 49 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `PlanStore` (e.g. with `_make()` and `test_jobrunner_dispatches_deploy()`) actually correct?**
  _`PlanStore` has 29 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `WeeklyKPI` (e.g. with `_kpi_from_predicted()` and `_kpi()`) actually correct?**
  _`WeeklyKPI` has 33 INFERRED edges - model-reasoned connections that need verification._