# Graph Report - src  (2026-06-11)

## Corpus Check
- 144 files · ~70,775 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1484 nodes · 3057 edges · 82 communities (75 shown, 7 thin omitted)
- Extraction: 64% EXTRACTED · 36% INFERRED · 0% AMBIGUOUS · INFERRED: 1112 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b044514a`
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
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]

## God Nodes (most connected - your core abstractions)
1. `Setpoints` - 118 edges
2. `ObjectiveWeights` - 72 edges
3. `PlanStore` - 63 edges
4. `Path` - 57 edges
5. `WeeklyKPI` - 56 edges
6. `MockEvaluator` - 56 edges
7. `MockSurface` - 47 edges
8. `OracleSettings` - 41 edges
9. `OracleConfig` - 39 edges
10. `ParallelEnvOracle` - 39 edges

## Surprising Connections (you probably didn't know these)
- `test_advance_history_appends_realized_week()` --calls--> `advance_history()`  [INFERRED]
  tests/test_history.py → planner/history.py
- `test_advance_history_is_idempotent_per_week()` --calls--> `advance_history()`  [INFERRED]
  tests/test_history.py → planner/history.py
- `test_residual_source_prefers_raw_predicted()` --calls--> `residual_predicted_for()`  [INFERRED]
  tests/test_jobs.py → webapp/jobs.py
- `test_write_plant_calibration_is_guarded_never_raises()` --calls--> `write_plant_calibration()`  [INFERRED]
  tests/test_jobs.py → webapp/jobs.py
- `test_teardown_container_is_best_effort()` --calls--> `_teardown_container()`  [INFERRED]
  tests/test_oracle_worker.py → planner/oracle_worker.py

## Communities (82 total, 7 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.18
Nodes (20): _ex(), _make_epw(), _op(), test_cancel_endpoint_running_404_409(), test_create_accepts_week_inside_weather_coverage(), test_create_plan_accepts_valid(), test_create_plan_rejects_bad_grid(), test_create_rejects_week_outside_weather_coverage() (+12 more)

### Community 1 - "Community 1"
Cohesion: 0.15
Nodes (17): MonitorSpec, Like run_episode but also returns the per-step StepSample list., Step a (already-built) env to completion with a fixed action; aggregate KPI., read_step_sample(), run_episode(), run_episode_with_samples(), _FakeEnv, _FakeUnwrapped (+9 more)

### Community 2 - "Community 2"
Cohesion: 0.11
Nodes (26): test_building_has_all_stacked_halls(), test_building_per_hall_infrastructure(), test_parse_zone_bboxes_world_coords(), test_topology_has_22_crahs_and_racks_and_plant(), _acu_counts_from_text(), _bboxes_from_text(), build_building_topology(), build_hall_topology() (+18 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (43): backtest_room(), main(), mape(), picp(), Backtest the seasonal forecaster vs persistence on held-out real telemetry. Repo, Prediction-interval coverage probability: fraction of actuals within [lo, hi]., Fit on all-but-last holdout_days, forecast the holdout, compare seasonal vs, rmse() (+35 more)

### Community 4 - "Community 4"
Cohesion: 0.10
Nodes (19): client(), _deploy_client(), Async mode: the endpoint must mark the plan 'deploying' at ACCEPT time, not at, test_delete_endpoint_terminal_404_409(), test_deploy_requires_expert_and_approval(), test_deploy_reserves_status_at_accept_so_repeat_clicks_409(), test_root_hint_when_frontend_not_built(), test_root_serves_built_frontend() (+11 more)

### Community 5 - "Community 5"
Cohesion: 0.05
Nodes (53): Calibration, fit_calibration(), from_dict(), identity(), load_calibration(), Output-residual calibration: learn per-KPI bias + uncertainty from the deploy lo, Re-fit the Calibration from the paired history and persist it., Re-fit the Calibration from the paired history and persist it. (+45 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (32): Enum, ActionEntry, BroadcastPolicy, ControlKind, gds_action_spec(), normalize(), One env actuator: which global control feeds it, and its physical bounds., Physical value -> [-1, 1] linear normalization (matches dctwin LINEAR). (+24 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (45): make_oracle_robust_rerank(), make_scenarios(), _quantile(), Scenario/ensemble-robust setpoint selection (P2b): evaluate the beam finalists a, finalists: list of (Setpoints, WeeklyKPI, score). scenario_kpis[i]: the list, Build a robust_rerank_fn(finalists, forecast) -> RobustResult that evaluates, finalists: list of (Setpoints, WeeklyKPI, score). scenario_kpis[i]: the list, Build a robust_rerank_fn(finalists, forecast) -> RobustResult that evaluates (+37 more)

### Community 8 - "Community 8"
Cohesion: 0.06
Nodes (34): dependencies, react, react-dom, @react-three/drei, @react-three/fiber, recharts, three, devDependencies (+26 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (31): epw_data_period(), epw_first_date(), _md_in_range(), Lightweight EPW coverage check — read the DATA PERIODS line to know which (month, Return ((start_month, start_day), (end_month, end_day)) from the EPW's     'DATA, Human + machine view of the EPW's covered window (month/day, year-agnostic)., First concrete date in the EPW data block (8 header lines, then CSV rows     'ye, Is (month, day) within [start, end], allowing a year wrap (start > end)? (+23 more)

### Community 10 - "Community 10"
Cohesion: 0.10
Nodes (32): Per-hour outdoor dry-bulb temperature for [start_date, start_date+days) from the, weather_timeseries(), forecast_hall_load_kw(), past_hall_load_kw(), Pure helpers that assemble the New-Plan planning-context time series: past + for, [{"t","kw"}] of the hall IT load (kW) over [start_date, start_date+days).      T, [{"t","kw"}] aggregate hall IT-load forecast (kW) = Σ_ite fraction[ite][i]·cap_k, Weather forecast + uncertainty from the historical EPW (Stage 6, item #7).  With (+24 more)

### Community 11 - "Community 11"
Cohesion: 0.09
Nodes (51): aggregate_kpi(), _hvac_watts(), OracleSettings, One timestep's monitored readings (physical units)., Per-step series for the pre-validation trajectory CSV. Applies the same     warm, Per-step series for the pre-validation trajectory CSV. Applies the same     warm, Controllable HVAC power for energy: the scoped hall+plant sum when measured,, step_trajectory() (+43 more)

### Community 12 - "Community 12"
Cohesion: 0.22
Nodes (7): clearToken(), getToken(), DigitalTwin3D, NAV, Page, labels, mockGetToken

### Community 13 - "Community 13"
Cohesion: 0.12
Nodes (18): BuildingHall, TopoCRAH, TopoLink, Topology, TopoPlant, TopoRackRow, Vec3, buildPath() (+10 more)

### Community 14 - "Community 14"
Cohesion: 0.13
Nodes (18): test_plan_sse_stream_keepalive_then_terminal(), test_create_list_and_get(), test_delete_plan_removes_row_and_dir(), test_get_recommendation_tolerates_partial_file(), test_get_trajectory_missing_is_empty(), test_get_trajectory_parses_two_csvs(), test_progress_roundtrip(), test_progress_sanitizes_non_finite() (+10 more)

### Community 15 - "Community 15"
Cohesion: 0.22
Nodes (11): A per-time-block setpoint schedule. `setpoints[i]` applies during `blocks[i]`., _neighbors(), Warm-start day/night schedule refinement (sub-project B). Stage 2 of the time-bl, Warm-start: seed at (constant,...) per block, then coordinate-descent refine ove, refine_schedule(), ScheduleResult, WeeklySchedule, _Monotone (+3 more)

### Community 16 - "Community 16"
Cohesion: 0.16
Nodes (12): Dashboard(), KPI_LABELS, Props, SETPOINT_LABELS, statusClass(), btn, mockDetail, mockPlan (+4 more)

### Community 17 - "Community 17"
Cohesion: 0.12
Nodes (17): KPI_META, Props, Review(), SETPOINT_LABELS, statusClass(), APPROVED_DETAIL, DEPLOYED_DETAIL, FAILED_DETAIL (+9 more)

### Community 18 - "Community 18"
Cohesion: 0.33
Nodes (6): test_deploy_status_blocked_on_realized_breach(), deploy_status_for(), 0-tolerance hard cap (spec §4.3): any realized inlet violation on the real     d, 0-tolerance hard cap (spec §4.3): any realized inlet violation on the real     d, 0-tolerance hard cap (spec §4.3): any realized inlet violation on the real     d, 0-tolerance hard cap (spec §4.3): any realized inlet violation on the real     d

### Community 19 - "Community 19"
Cohesion: 0.16
Nodes (13): _batch_deadline(), _collect_with_stall_guard(), _infeasible(), Inline single-candidate run that ALSO returns the per-step StepSample list., Score time-block WeeklySchedules with full-week EnergyPlus runs (per-step action, Inline single-candidate run that ALSO returns the per-step StepSample list., Score time-block WeeklySchedules with full-week EnergyPlus runs (per-step action, Wall-clock backstop for a whole batch. Each parallel wave is bounded by the (+5 more)

### Community 20 - "Community 20"
Cohesion: 0.11
Nodes (19): 1-day deploy against the perturbed plant; realized KPIs are captured., test_perturbed_plant_deploy_records_realized(), 2-scenario robust re-rank of 2 finalists on a 1-day window (real EnergyPlus)., test_robust_rerank_over_two_scenarios(), build_plant_prototxt(), Write a perturbed IDF + a DT prototxt copy that points at it. Mirrors     week_c, Write a perturbed IDF + a DT prototxt copy that points at it. Mirrors     week_c, Write a pre-validation per-step trajectory to CSV (the diagram's trajectory_*.cs (+11 more)

### Community 21 - "Community 21"
Cohesion: 0.11
Nodes (11): A stale duplicate deploy (repeat clicks while the worker was busy) must neither, If a duplicate already clobbered the row, the next stale duplicate restores the, test_duplicate_deploy_heals_a_clobbered_row(), test_duplicate_deploy_is_skipped_and_does_not_clobber(), JobRunner, Single-worker background runner for plan + deploy jobs (one at a time)., Single-worker background runner for plan + deploy jobs (one at a time)., A restart loses the in-memory job queue, so any plan still marked non-terminal (+3 more)

### Community 22 - "Community 22"
Cohesion: 0.16
Nodes (16): Airflow(), clamp(), lerp(), particleSpeed(), Props, RGB, tempColor(), tempColorRGB() (+8 more)

### Community 23 - "Community 23"
Cohesion: 0.11
Nodes (18): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection, moduleResolution (+10 more)

### Community 24 - "Community 24"
Cohesion: 0.11
Nodes (17): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, moduleResolution, noEmit (+9 more)

### Community 25 - "Community 25"
Cohesion: 0.13
Nodes (26): build_recommendation(), energy_reduction_pct(), Index of the safest candidate: fewest inlet violations, then least energy., safest_fallback(), write_recommendation(), render_report(), validation_metrics(), _kpi() (+18 more)

### Community 26 - "Community 26"
Cohesion: 0.19
Nodes (19): Evaluator, test_single_candidate_short_window(), test_two_candidates_parallel_processes(), OracleConfig, ParallelEnvOracle, Score candidate weekly setpoints with real full-week EnergyPlus runs., Score candidate weekly setpoints with real full-week EnergyPlus runs., _FakeForecast (+11 more)

### Community 27 - "Community 27"
Cohesion: 0.10
Nodes (23): BacnetBmsAdapter, expand_commands(), Expand the 3 global setpoints to the 45 per-actuator BMS commands.      Values a, Shadow-mode BMS seam: records what WOULD be commanded, never actuates.      No p, Write out_dir/bms_commands.json (45 commands, actuated:false).          `week_st, Field-BMS seam (NOT implemented — no physical BMS on this rig).      Implementin, ShadowBmsAdapter, deploy() (+15 more)

### Community 28 - "Community 28"
Cohesion: 0.20
Nodes (4): _atomic_write_json(), Write JSON so a concurrent reader never sees a partial file: write a sibling, Read JSON tolerantly: a missing, empty, or caught-mid-write file -> default., _read_json()

### Community 29 - "Community 29"
Cohesion: 0.12
Nodes (36): MockSurface, Analytic test surface: convex energy bowl + monotone inlet model., PlanRequest, Fail-fast BEFORE any EnergyPlus run (spec §11). Raises ValueError on a     misco, Fail-fast BEFORE any EnergyPlus run (spec §11). Raises ValueError on a     misco, Forecast -> best-first search -> recommendation dict. The DRY planning core., Forecast -> best-first search -> recommendation dict. The DRY planning core., Forecast -> best-first search -> recommendation dict. The DRY planning core. (+28 more)

### Community 30 - "Community 30"
Cohesion: 0.08
Nodes (30): onAuthed, PREV_SETPOINT_LABELS, Props, EMPTY_CTX, approvePlan(), Building, createPlan(), getLiveSeries() (+22 more)

### Community 31 - "Community 31"
Cohesion: 0.21
Nodes (14): as_operated_setpoints(), BaselineColumns, _match(), _pooled_median(), Regex patterns selecting the as-operated control columns in the history CSV., Derive the plant's current ("as-operated") setpoints from telemetry medians., _df(), test_as_operated_setpoints_clips_to_search_space() (+6 more)

### Community 32 - "Community 32"
Cohesion: 0.29
Nodes (7): test_record_failure_falls_back_to_class_name(), test_record_failure_stores_reason_and_status(), Persist a failure reason via the progress channel, then mark the plan failed,, Persist a failure reason via the progress channel, then mark the plan failed,, Persist a failure reason via the progress channel, then mark the plan failed,, Persist a failure reason via the progress channel, then mark the plan failed,, record_failure()

### Community 33 - "Community 33"
Cohesion: 0.22
Nodes (8): Bounds, Inclusive physical bounds for one control dimension., test_bounds_clip_inside_and_outside(), test_bounds_rejects_inverted(), test_default_search_space_matches_gds_bounds(), test_search_space_clip_clamps_all_dims(), test_setpoints_as_tuple_order(), test_weekly_kpi_defaults()

### Community 34 - "Community 34"
Cohesion: 0.21
Nodes (8): Props, SortDir, SortKey, onReview, PLANS, cancelPlan(), deletePlan(), listPlans()

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
Cohesion: 0.05
Nodes (35): BaseModel, _FakePlanStore, store(), test_alerts_ignore_non_inlet_points_and_sort_by_point(), test_alerts_nominal_warn_critical_thresholds(), test_commanded_setpoints_latest_deployed_plan(), test_commanded_setpoints_none_when_nothing_deployed(), test_compliance_breach_beyond_half_degree() (+27 more)

### Community 41 - "Community 41"
Cohesion: 0.08
Nodes (29): Exception, Docker-gated regression: the demonstrated 666-violation deployment cannot ship., test_breaching_plan_cannot_ship(), advance_history(), Append (or replace) the realized-week summary row keyed by week_start.      ``hi, pickle_load(), PlanCancelled, Production runner: run the real framework and persist the recommendation.      I (+21 more)

### Community 43 - "Community 43"
Cohesion: 0.27
Nodes (12): _configure_backend(), evaluate_one(), evaluate_one_schedule(), evaluate_one_with_samples(), _infeasible(), Best-effort: unblock a stuck BCVTB recv() (shutdown the connection) and stop+rem, Top-level process-pool target: build env, run one full week, aggregate.      Any, Like evaluate_one but returns (WeeklyKPI, list[StepSample]). For the inline (+4 more)

### Community 53 - "Community 53"
Cohesion: 0.07
Nodes (40): estimate_recirc_fraction(), flow_shortfall_recirc(), inlet_with_recirc(), load_recirc_config(), data/recirc.json merged over DEFAULT_RECIRC_CONFIG. An absent file or explicit, Fit the recirc fraction from telemetry tuples (inlet_c, supply_c, return_c[, rac, Containment physics: recirculation rises linearly with the CRAH airflow shortfal, Post-oracle inlet correction for recirculation above the oracle's built-in r0: (+32 more)

### Community 54 - "Community 54"
Cohesion: 0.19
Nodes (11): discover_monitor(), _is_hall_acu_fan(), _is_plant_power(), Shared chiller/CHW-plant electrical power: chiller compressors, CHW pumps,     t, Scan a dctwin env's observations and classify the ones we read each step.      P, _FakeEnv, _Obs, test_discover_classifies_hvac_power_names() (+3 more)

### Community 55 - "Community 55"
Cohesion: 0.10
Nodes (18): DigitalTwin3D(), HudStatProps, LIVE_ZONE_COLOR, LiveZone, num(), rowWorstInlets(), f, PLAN_DETAIL (+10 more)

### Community 56 - "Community 56"
Cohesion: 0.15
Nodes (10): Step the env to completion, switching the action by local time-of-day from `sche, run_episode_schedule(), A daily time window [start_hour, end_hour) in local hours. end <= start wraps mi, Index of the block covering `hour` (first match wins; falls back to 0)., TimeBlock, test_run_episode_schedule_switches_action_by_hour(), test_default_blocks_partition_the_day(), test_schedule_length_invariant() (+2 more)

### Community 57 - "Community 57"
Cohesion: 0.20
Nodes (11): test_is_terminal_table(), test_progress_frame_shape(), is_terminal(), plan_sse_stream(), progress_frame(), A plan is terminal once it leaves the queued/running/deploying states., A plan is terminal once it leaves the queued/running/deploying states., One SSE frame: the latest progress + the plan's current status. (+3 more)

### Community 58 - "Community 58"
Cohesion: 0.22
Nodes (5): AITrajectoryReplay, Replay the recommended weekly setpoints (held constant) over the full week., BaselineTrajectory, Conservative baseline: coolest SAT/CHW, maximum airflow (safe, energy-heavy)., TrajectoryPolicyTemplate

### Community 59 - "Community 59"
Cohesion: 0.19
Nodes (27): BeamConfig, BeamPlanner, MockEvaluator, Deterministic Evaluator for TDD of the planner (no EnergyPlus)., test_on_eval_ticks_once_per_candidate(), test_on_level_called_once_per_level(), test_plan_works_without_callback(), A control-invariant model (identical KPIs for every candidate) is flagged. (+19 more)

### Community 60 - "Community 60"
Cohesion: 0.53
Nodes (5): _client(), Integration-ish test of GET /api/planning-context against the real forecaster/EP, test_planning_context_bad_date_is_empty_not_500(), test_planning_context_requires_auth(), test_planning_context_shape_and_data()

### Community 61 - "Community 61"
Cohesion: 0.50
Nodes (3): type, test_configure_backend_sets_host_and_bounds_socket_timeout(), test_teardown_container_shuts_down_conn_to_unblock_recv()

### Community 62 - "Community 62"
Cohesion: 0.23
Nodes (10): AXES, fmt(), fmtClock(), inletZone(), Live(), rackChip(), RACKS, Zone (+2 more)

### Community 63 - "Community 63"
Cohesion: 0.18
Nodes (25): is_feasible(), ObjectiveWeights, Soft-penalty weights and hard-constraint tolerances.      Energy (kWh) is the do, Lower is better. Infeasible candidates score +inf and never enter the beam., score(), apply_forecast_margin(), Set inlet_forecast_margin = k * sigma_inlet so the search treats the inlet cap, Set inlet_forecast_margin = k * sigma_inlet so the search treats the inlet cap (+17 more)

### Community 64 - "Community 64"
Cohesion: 0.33
Nodes (5): test_deterministic_and_batched(), test_energy_minimized_at_optimum(), test_inlet_rises_with_sat_and_chwst_falls_with_flow(), test_mock_evaluate_schedules_constant_matches_single_kpi(), test_violation_flagged_above_cap()

### Community 65 - "Community 65"
Cohesion: 0.25
Nodes (12): _deploy_plan(), _op(), test_live_alerts_warn_then_critical(), test_live_compliance_breach(), test_live_compliance_null_without_deployed_plan(), test_live_compliance_ok_against_deployed_plan(), test_live_series_respects_minutes_window(), test_live_series_shape_and_worst_inlet() (+4 more)

### Community 66 - "Community 66"
Cohesion: 0.22
Nodes (7): Worst (max) rack inlet per snapshot ts — server-side, so the UI never         sh, Append-only point telemetry in SQLite (same dir convention as PlanStore).     Ev, Insert one snapshot (all points share one ts) and return that ts., {point: {"ts", "value"}} for the newest sample of every point. SQLite's, {point: [{"ts","value"}…]} over the trailing window, ascending,         stride-d, _stride(), TelemetryStore

### Community 67 - "Community 67"
Cohesion: 0.23
Nodes (10): build_his_col_for_room(), main(), Data Hall 1F 2A' -> tokens '1f 2a' for fuzzy column matching., Map each room to its 'IT loads' column in his_data by fuzzy name match., Fit the forecaster config and write the pkl.      To regenerate the production p, _room_token(), save_forecaster_config(), test_build_his_col_for_room_matches_columns() (+2 more)

### Community 68 - "Community 68"
Cohesion: 0.18
Nodes (15): apply_perturbation(), load_plant_config(), Perturbation, PlantConfig, Perturbed-plant model: the deploy-only 'real' DC = nominal IDF with scaled physi, Scale the configured numeric fields and save a perturbed IDF copy.      Non-nume, The data-driven believed plant state (Stage 6 #9): DEFAULT_PLANT with the     de, Scale the configured numeric fields and save a perturbed IDF copy.      Non-nume (+7 more)

### Community 69 - "Community 69"
Cohesion: 0.13
Nodes (20): _hist_week(), _make(), test_bms_adapter_for_mode_defaults_to_shadow(), test_bms_adapter_for_mode_sim_keeps_todays_behavior(), test_job_failure_sets_failed(), test_job_runs_and_sets_status(), test_jobrunner_dispatches_deploy(), test_reconcile_orphans_fails_non_terminal_plans() (+12 more)

### Community 72 - "Community 72"
Cohesion: 0.14
Nodes (11): _coarse_grid(), _no_signal(), PlanResult, _top_b(), Evaluator, Protocol implemented by the dctwin oracle (Plan 2) and the MockEvaluator., Protocol implemented by the dctwin oracle (Plan 2) and the MockEvaluator., `on_result`, if given, is called once per candidate as it finishes         (for (+3 more)

### Community 75 - "Community 75"
Cohesion: 0.47
Nodes (4): _FakeForecaster, Prove the calibration learning loop converges over N weeks with NO EnergyPlus., _sp(), test_multi_week_loop_converges()

### Community 78 - "Community 78"
Cohesion: 0.50
Nodes (3): Docker-gated: a real plan emits both trajectory CSVs and GET /trajectory serves, # NOTE: week_start "2013-11-11" assumes models/forecaster.pkl has weather_file=N, test_prevalidation_emits_both_trajectories()

### Community 79 - "Community 79"
Cohesion: 0.17
Nodes (8): test_tiny_weekly_plan_then_baseline_acceptance(), EnergyPlus oracle runs a 1-day window using the real provided EPW (Nov 2024)., test_oracle_runs_on_real_weather_within_year(), build_forecaster(), Construct the forecaster for `method`: 'seasonal' -> SeasonalForecaster,     any, RecommendTemplate, One-shot weekly planner: heuristic search over 3 setpoints, EnergyPlus-scored., WeeklyPlanTemplate

### Community 80 - "Community 80"
Cohesion: 0.50
Nodes (4): _cvar(), Mean of the worst (1-alpha) upper tail (higher energy = worse)., Mean of the worst (1-alpha) upper tail (higher energy = worse)., Mean of the worst (1-alpha) upper tail (higher energy = worse).

### Community 82 - "Community 82"
Cohesion: 0.40
Nodes (5): _kill_eplus_containers(), Kill running EnergyPlus containers so a hung batch unblocks. One plan runs at a, Kill running EnergyPlus containers so a hung batch unblocks. One plan runs at a, Kill running EnergyPlus containers so a hung batch unblocks. One plan runs at a, Kill running EnergyPlus containers so a hung batch unblocks. One plan runs at a

### Community 83 - "Community 83"
Cohesion: 0.50
Nodes (4): If the runner reached 'deployed' before raising, the failure handler must not, If the runner reached 'deployed' before raising, the failure handler must not, If the runner reached 'deployed' before raising, the failure handler must not, test_deploy_failure_does_not_downgrade_terminal_status()

### Community 84 - "Community 84"
Cohesion: 0.12
Nodes (11): Analytic schedule KPI: per-block bowl KPI, energy hour-weighted (equal blocks),, RobustResult, Aggregated outcome of one full-week evaluation of a candidate., WeeklyKPI, _good_kpi(), _pool_good(), _pool_slow(), _pool_wedge_one() (+3 more)

## Knowledge Gaps
- **153 isolated node(s):** `tsBuildInfoFile`, `target`, `lib`, `module`, `types` (+148 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Path` connect `Community 20` to `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 9`, `Community 10`, `Community 11`, `Community 14`, `Community 19`, `Community 22`, `Community 25`, `Community 27`, `Community 29`, `Community 41`, `Community 53`, `Community 58`, `Community 66`, `Community 67`, `Community 68`, `Community 79`?**
  _High betweenness centrality (0.420) - this node is a cross-community bridge._
- **Why does `Setpoints` connect `Community 7` to `Community 1`, `Community 6`, `Community 11`, `Community 15`, `Community 20`, `Community 21`, `Community 25`, `Community 26`, `Community 27`, `Community 29`, `Community 31`, `Community 33`, `Community 41`, `Community 43`, `Community 53`, `Community 56`, `Community 58`, `Community 59`, `Community 64`, `Community 72`, `Community 75`, `Community 79`, `Community 84`?**
  _High betweenness centrality (0.215) - this node is a cross-community bridge._
- **Why does `create_app()` connect `Community 4` to `Community 0`, `Community 66`, `Community 5`, `Community 14`, `Community 20`, `Community 21`, `Community 57`, `Community 60`?**
  _High betweenness centrality (0.104) - this node is a cross-community bridge._
- **Are the 114 inferred relationships involving `Setpoints` (e.g. with `AITrajectoryReplay` and `WeeklyPlanTemplate`) actually correct?**
  _`Setpoints` has 114 INFERRED edges - model-reasoned connections that need verification._
- **Are the 70 inferred relationships involving `ObjectiveWeights` (e.g. with `WeeklyPlanTemplate` and `_FakeForecaster`) actually correct?**
  _`ObjectiveWeights` has 70 INFERRED edges - model-reasoned connections that need verification._
- **Are the 44 inferred relationships involving `PlanStore` (e.g. with `JobRunner` and `PlanCancelled`) actually correct?**
  _`PlanStore` has 44 INFERRED edges - model-reasoned connections that need verification._
- **Are the 56 inferred relationships involving `Path` (e.g. with `.initialize()` and `save_forecaster_config()`) actually correct?**
  _`Path` has 56 INFERRED edges - model-reasoned connections that need verification._