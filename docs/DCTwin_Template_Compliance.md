# DCTwin — dcwiz Template Compliance Report

**Bottom line.** DCTwin adopts *both* dcwiz standard policy templates: `RecommendTemplate` (subclassed by `WeeklyPlanTemplate` in `src/plan_weekly.py`) and `TrajectoryPolicyTemplate` (subclassed by `AITrajectoryReplay` in `src/ai_trajectory_test.py` and by `BaselineTrajectory` in `src/baseline_policy_test.py`). It mirrors the `sample_template/` layout for `configs/`, `data/`, and `models/` — the device-mapping JSON schemas (`device_key_map.json`, `device_his_map.json`, `room2ite_map.json`) and the `dt.prototxt`/`test.prototxt`/`train.prototxt` protobuf shapes are honored either identically or near-identically. The base-class contracts (`__init__` → `__call__` → `initialize` → `run`) are respected: the subclasses override `initialize()` and (for the planner) `run()` exactly where the templates designate those as the extension points. DCTwin **intentionally omits the RL-training artifacts** — `ai_policy_train.py`, the single-file `hooks.py`, the trained `policy/policy.pth`, and the `recommend.prototxt`/`train_test.prototxt` configs — because it is a *search/planning optimizer* (beam search over 3 setpoints scored by an EnergyPlus oracle), not a trained dcbrain RL policy. That functionality is not missing so much as relocated: reward/objective logic lives in `planner/objective.py` + `planner/kpi.py`, state discovery in `planner/monitor.py` + `planner/oracle_worker.py`, recommendation logging in `planner/recommendation.py`, zone→actuator mapping in `planner/broadcast.py`, and "model prep" in `fit_forecaster.py` (producing `forecaster.pkl` rather than `policy.pth`). One real defect surfaced: `AITrajectoryReplay` invokes `run(policy="ai")` without setting `self.test_collector`, which the template's `run_ai()` requires — a runtime incompatibility flagged below.

---

## Compliance at a glance

| Template artifact | DCTwin counterpart | Verdict |
| --- | --- | --- |
| `RecommendTemplate` / `ai_policy_test.py` | `src/plan_weekly.py` → `WeeklyPlanTemplate(RecommendTemplate)` | **adapted** |
| `TrajectoryPolicyTemplate` / `ai_trajectory_test.py` | `src/ai_trajectory_test.py` → `AITrajectoryReplay(TrajectoryPolicyTemplate)` | **adapted** (partial — `test_collector` not set) |
| `baseline_policy_test.py` | `src/baseline_policy_test.py` → `BaselineTrajectory(TrajectoryPolicyTemplate)` | **followed** |
| `ai_policy_train.py` | none (closest analogue: `src/fit_forecaster.py`) | **missing** (by design) |
| `hooks.py` (single file) | distributed: `objective.py`, `kpi.py`, `monitor.py`, `oracle_worker.py`, `recommendation.py`, `broadcast.py`, `configs/dt/room2ite_map.json` | **adapted** |
| `configs/` (dt + policy) | `src/configs/` | **adapted** (omits `recommend.prototxt`, `train_test.prototxt`) |
| `data/` formats | `src/data/` | **adapted** (EPW + schedule JSON kept; adds calibration/realized-history) |
| `models/` | `src/models/` | **extended** (same `building.json` schema; IDF moved to `idf/`; adds `forecaster.pkl`) |
| `policy/` (`policy.pth`) | none — `BeamPlanner` (`planner/beam_search.py`) is the "policy" | **missing** (by design) |

Legend: **followed** = template contract honored as-is; **adapted** = honored with deliberate, justified divergences; **partial** = contract partly honored with a gap; **missing** = artifact absent (here: by architectural design); **extended** = template honored plus domain-specific additions.

---

## Side-by-side directory map

`sample_template/` (dcwiz canonical) vs `src/` (DCTwin). `✓` = match, `+` = DCTwin extension, `✗` = absent in DCTwin.

| `sample_template/` | `src/` (DCTwin) | |
| --- | --- | --- |
| `ai_policy_test.py` | `plan_weekly.py` (`WeeklyPlanTemplate`) | ✓ adapted role |
| `ai_trajectory_test.py` | `ai_trajectory_test.py` (`AITrajectoryReplay`) | ✓ |
| `baseline_policy_test.py` | `baseline_policy_test.py` (`BaselineTrajectory`) | ✓ |
| `ai_policy_train.py` | — | ✗ (no RL training) |
| `hooks.py` | — (logic split into `planner/*`) | ✗ file / ✓ logic |
| `main_example.py` | — | ✗ |
| `configs/dt/dt.prototxt` | `configs/dt/dt.prototxt` | ✓ |
| `configs/dt/device_key_map.json` | `configs/dt/device_key_map.json` | ✓ |
| `configs/dt/device_his_map.json` | `configs/dt/device_his_map.json` | ✓ |
| `configs/dt/room2ite_map.json` | `configs/dt/room2ite_map.json` | ✓ |
| `configs/policy/test.prototxt` | `configs/policy/test.prototxt` | ✓ |
| `configs/policy/train.prototxt` | `configs/policy/train.prototxt` | ✓ |
| `configs/policy/recommend.prototxt` | — | ✗ |
| `configs/policy/train_test.prototxt` | — | ✗ |
| `data/weather/*.epw` | `data/weather/SGP_Singapore.486980_IWEC.epw` | ✓ EPW format |
| `data/schedule/acus/` | `data/schedule/acus/fan_on_off/` | ✓ (subfolder) |
| `data/schedule/branches/` | `data/schedule/branches/` | ✓ |
| `data/schedule/workloads/` | `data/schedule/workloads/` | ✓ |
| — | `data/schedule/pumps/` | + (CHW plant) |
| `data/data_sample.json` | `data/his_data_processed.csv` | ✓ adapted role |
| — | `data/calibration.json`, `calibration_history.json`, `realized_history.csv` | + (dual-loop) |
| `models/building.json` | `models/building.json` | ✓ |
| `models/building.idf` | `models/idf/building.idf` | ✓ (subfolder) |
| — | `models/forecaster.pkl` | + (statistical forecaster) |
| `policy/policy.pth` | — (`planner/beam_search.py::BeamPlanner`) | ✗ (algorithmic policy) |

---

## RecommendTemplate (AI policy)

**Verdict: adapted.** `WeeklyPlanTemplate` correctly subclasses `RecommendTemplate` and imports it from `dcwiz_policy_template`. It overrides `initialize()` and `run()` with batch-planner logic; the remaining base methods are inherited but partially bypassed for a deterministic planner.

The load-bearing subclass lines:

```python
# src/plan_weekly.py:11
from dcwiz_policy_template import RecommendTemplate
# src/plan_weekly.py:22
class WeeklyPlanTemplate(RecommendTemplate):
```

**Proof**

| Claim | Template ref | DCTwin ref | Evidence |
| --- | --- | --- | --- |
| Subclasses `RecommendTemplate`, imports from `dcwiz_policy_template` | `recommend_template.py:10` | `plan_weekly.py:11,22` | `class RecommendTemplate:` → `from dcwiz_policy_template import RecommendTemplate` and `class WeeklyPlanTemplate(RecommendTemplate)` |
| `initialize()` overridden with concrete impl | `recommend_template.py:11` | `plan_weekly.py:30` | Base raises `NotImplementedError`; DCTwin fully implements forecaster, oracle, beam-planner setup |
| `run()` overridden for batch search | `recommend_template.py:25-50` | `plan_weekly.py:67-86` | Base calls `self.policy.policy(data)`; DCTwin calls `run_weekly_plan()` with oracle evaluator + forecaster |
| `log_recommendations()` not overridden | `recommend_template.py:60-72` | ABSENT | Base defines the abstract method; DCTwin never overrides it (never reached — `run()` is fully replaced) |
| `configure_run_period()` not used | `recommend_template.py:74-113` | ABSENT | DCTwin docstring: it does NOT pass `recommendation_timestamp` to `__call__` |
| `_default_data()` bypassed | `recommend_template.py:121-128` | `plan_weekly.py:62-65` | `initialize()` comment: "satisfy base-class attribute presence (we override run, so these are unused)" |
| `__init__()` not overridden | `recommend_template.py:52-58` | `plan_weekly.py:22-86` | Only `initialize()` and `run()` defined; `__init__` inherited from base |

**Deviations.** DCTwin adapts `RecommendTemplate` for a deterministic batch planner (beam search), not a reactive RL policy. `run()` is completely replaced to call `run_weekly_plan()` instead of `self.policy.policy(data)`; `log_recommendations()` is not implemented; `recommendation_timestamp` is excluded because the oracle controls the run period via `week_start`; `initialize()` requires a `week_start` kwarg for batch semantics. `__call__`, `configure_run_period`, `_default_data`, and `__init__` are inherited but partially bypassed.

---

## TrajectoryPolicyTemplate (AI trajectory)

**Verdict: adapted (partial).** `AITrajectoryReplay` correctly subclasses `TrajectoryPolicyTemplate` and overrides `initialize()` to set `self.env` and `self.act` as the contract requires. However, it invokes `run(policy="ai")` without setting `self.test_collector`, which the template's `run_ai()` checks for and rejects — a runtime gap.

```python
# src/ai_trajectory_test.py:14
class AITrajectoryReplay(TrajectoryPolicyTemplate):
# src/ai_trajectory_test.py:36
AITrajectoryReplay()(policy="ai", dt_engine_config=args.dt, recommendation=args.recommendation)
```

**Proof**

| Claim | Template ref | DCTwin ref | Evidence |
| --- | --- | --- | --- |
| Subclasses `TrajectoryPolicyTemplate` | `trajectory_policy_template.py:15`; `ai_trajectory_test.py:131` (canonical) | `ai_trajectory_test.py:14` | Canonical `TestAITrajectoryPolicy(TrajectoryPolicyTemplate)`; DCTwin `AITrajectoryReplay(TrajectoryPolicyTemplate)` |
| Overrides `initialize()` | `trajectory_policy_template.py:614-627` (raises `NotImplementedError`) | `ai_trajectory_test.py:17-28` | DCTwin reads `dt_engine_config` from kwargs, builds env + mapped action |
| Sets `self.env` | `trajectory_policy_template.py:19`; `run_ai:247` | `ai_trajectory_test.py:20` | `self.env = dctwin.make_env(env_proto_config=dt_engine_config, reward_fn=lambda x: 0)` |
| Sets `self.act` (fixed replay) | `trajectory_policy_template.py:20`; `run_baseline:155` | `ai_trajectory_test.py:28` | `self.act = mapper_from_env(self.env).expand(setpoints)` |
| Invokes `run()` via `__call__` with `policy="ai"` | `trajectory_policy_template.py:110-117`; `run_ai:207-338` | `ai_trajectory_test.py:36` | `AITrajectoryReplay()(policy="ai", ...)` dispatches to `run_ai()` |
| Uses `__call__` entry point (not `run()` directly) | `trajectory_policy_template.py:629-676` | `ai_trajectory_test.py:36` | Instance called as a callable; base `__call__` delegates to `initialize` + `run` |
| Does NOT override `run()`/`run_ai()` | `trajectory_policy_template.py:207-338` | no override | Template's `run_ai()` (custom_step wrapper, per-step temp collection) executes unchanged |
| Replay (fixed setpoints) vs live AI policy | `ai_trajectory_test.py:131-143` (canonical) | `ai_trajectory_test.py:14-28` | Canonical: `dcbrain.init(...)` + `test_collector.collect()`; DCTwin: load recommendation JSON → fixed `self.act` |
| Does NOT set `self.test_collector` | `trajectory_policy_template.py:127-205` (`run_baseline` steps env directly) | `ai_trajectory_test.py:17-28` | DCTwin sets `self.env`, `self.act` but no `self.test_collector` |
| Year-split inherited but unused | `trajectory_policy_template.py:350-469`, `629-676` | `ai_trajectory_test.py:36` | `recommendation_timestamp` not passed → `configure_run_period`/`_run_with_year_split_ai` bypassed |
| Fixed action maps to baseline pathway semantics | `trajectory_policy_template.py:119-205`, `49-117` | `ai_trajectory_test.py:36` | `run_ai()` line 227 checks `if self.test_collector is None: raise ValueError("Test collector is not set")` — errors unless set, or `policy="baseline"` |

**Deviations.**
1. **Missing `test_collector` (runtime incompatibility).** `AITrajectoryReplay` invokes `run(policy="ai")` but does not set `self.test_collector`; the template's `run_ai()` (lines 227–229) raises `ValueError("Test collector is not set")`. As written, this crashes when called with `policy="ai"`. The class should either set `self.test_collector` in `initialize()` or call with `policy="baseline"` (fixed-action replay matches baseline semantics — constant action per step, no AI inference).
2. **Replay vs live AI policy.** The canonical `TestAITrajectoryPolicy` uses `dcbrain.init()` to set up a live policy + `test_collector`, then `test_collector.collect()` generates actions dynamically. DCTwin loads a pre-computed recommendation JSON and expands it to a fixed action array — a valid "replay" adaptation, but it diverges from the template's assumption of a trained policy object.
3. **No `recommendation_timestamp`/year-split usage.** Line 36 does not pass `recommendation_timestamp`, so year-wrap splitting is never triggered. Acceptable for a single-week recommendation, but differs from the canonical example's arbitrary-date-range support.
4. **Lean overrides.** `AITrajectoryReplay` is ~14 lines with a single overridden method vs the canonical's heavier boilerplate — a deliberate simplification for a replay-only scope, not a contract violation.

---

## Baseline trajectory test

**Verdict: followed.** `BaselineTrajectory` fully honors the `TrajectoryPolicyTemplate` contract for baseline trajectory testing: it subclasses correctly, implements `initialize()` to set the env and a conservative `self.act`, calls the base `run_baseline()` via `policy="baseline"`, and uses the same `__call__` entry point.

```python
# src/baseline_policy_test.py:12
class BaselineTrajectory(TrajectoryPolicyTemplate):
# src/baseline_policy_test.py:27
BaselineTrajectory()(policy="baseline", dt_engine_config=args.dt)
```

**Proof**

| Claim | Template ref | DCTwin ref | Evidence |
| --- | --- | --- | --- |
| Subclasses `TrajectoryPolicyTemplate` | `baseline_policy_test.py:32` | `baseline_policy_test.py:12` | `class TestBaselineProjectTemplate(TrajectoryPolicyTemplate)` → `class BaselineTrajectory(TrajectoryPolicyTemplate)` |
| Overrides `initialize()` with env setup | `baseline_policy_test.py:33-60` | `baseline_policy_test.py:15-20` | Both retrieve `dt_engine_config` from kwargs, call `dctwin.make_env()`, set `self.env` + `self.act` |
| Uses base `run_baseline` via `policy="baseline"` | `baseline_policy_test.py:95-99` | `baseline_policy_test.py:27` | Both invoke `__call__(policy="baseline", ...)`, routing to `run_baseline()` (`trajectory_policy_template.py:111-112`) |
| Baseline semantics: coolest SAT/CHW, max airflow | `baseline_policy_test.py:43-46` | `baseline_policy_test.py:13,19` | Template: `[-1]*16` (min SAT), `[0.9..1.0]` (max airflow), chiller `[-1]`. DCTwin: `sat_c=s.sat.lb`, `flow_kg_s=s.flow.ub`, `chwst_c=s.chwst.lb` from `DEFAULT_SEARCH_SPACE` (sat=[20,26], flow=[4.8,13.8], chwst=[13,19]) |
| Conservative action via `Setpoints → mapper_from_env().expand()` | `baseline_policy_test.py:42-60` | `baseline_policy_test.py:18-20` | Template hand-builds per-zone arrays; DCTwin builds `Setpoints(...)` then `mapper_from_env(self.env).expand(baseline)` (broadcast to all zones, `broadcast.py:46-56`) |
| Signature: `initialize` receives `**kwargs` with `dt_engine_config` | `baseline_policy_test.py:33-36` | `baseline_policy_test.py:15-16` | Both `kwargs.get("dt_engine_config", ...)` with the same default fallback |
| `run_baseline()` not overridden; base method runs | `trajectory_policy_template.py:110-126` | `baseline_policy_test.py:12-20` | Base `run_baseline()` (lines 119-205) steps `self.act` to done, collects temps, writes CSV — matches contract exactly |
| Entry point: instantiate + call with `policy="baseline"` | `baseline_policy_test.py:92-100` | `baseline_policy_test.py:23-28` | Identical `__call__` invocation pattern |

**Deviations.** Only a benign encoding difference: the template hard-codes conservative setpoints as normalized per-zone action arrays; DCTwin parametrizes via `Setpoints` + dynamic `BroadcastPolicy.expand()`. The physical semantics (coolest SAT/CHW, maximum airflow → safe, energy-heavy) are identical. No functionality gaps or contract violations.

---

## AI policy train

**Verdict: missing (by design).** DCTwin has no `ai_policy_train.py` and no `src/policy/` directory because it is not an RL policy learner. It performs one-shot heuristic search (`BeamPlanner`) scored by an EnergyPlus oracle, rather than training a dcbrain SAC policy via reward-driven episodes.

**Proof**

| Claim | Template ref | DCTwin ref | Evidence |
| --- | --- | --- | --- |
| Template trains a dcbrain RL policy → `policy/policy.pth` | `ai_policy_train.py:10-16` | ABSENT | Template: `policy, train_collector, test_collector, trainer = dcbrain.init(...); trainer.run()` → `policy/policy.pth` (2.9 MB). DCTwin has no `ai_policy_train.py`; `src/policy/` does not exist |
| Template uses `train.prototxt` (SAC, 20 epochs, batch 256) | `configs/policy/train.prototxt:7-32` | `src/configs/policy/train.prototxt:7-32` | Template: SAC, `max_epoch:20`, `batch_size:256`. DCTwin: SAC config present but `batch_size:512`, `step_per_epoch:5376` — config exists yet is NOT used (no `dcbrain.init` call anywhere) |
| Template calls `hooks.get_reward_fn()` / `save_best_fn()` | `ai_policy_train.py:3,8,13` | ABSENT from `src/` | Template: `from hooks import get_reward_fn, save_best_fn` and `make_env(..., reward_fn=get_reward_fn())`. No `hooks.py` in `src/` (`test/hooks.py` is for co-sim, not RL); no reward_fn or training loop in `src/` |
| DCTwin is a search/planning optimizer | n/a | `plan_weekly.py:22-26`; `planner/beam_search.py:1-50` | `WeeklyPlanTemplate` docstring: "One-shot weekly planner: heuristic search over 3 setpoints, EnergyPlus-scored. Overrides run() because the base RecommendTemplate.run() expects a reactive dcbrain policy." `BeamPlanner` = grid + beam refine with oracle, not gradient RL |
| `fit_forecaster.py` is the analogous "model prep" | `ai_policy_train.py:7-16` (RL prep → `policy.pth`) | `src/fit_forecaster.py:42-68` | DCTwin fits a forecaster config (persistence forecast + room→IT-load mapping) to a pickle: `main()` → `models/forecaster.pkl` (config/data prep, no learning loop) |

**Deviations.** Fundamental architectural difference. The template trains a `policy.pth` neural network via `dcbrain.init()` + `trainer.run()`. DCTwin pre-fits a forecaster config and uses deterministic search at runtime — no policy gradient, no episode collection, no trainer loop. Not a violation; a deliberate pivot from learned control to search-based planning.

---

## Hooks

**Verdict: adapted.** There is no single `hooks.py` in `src/`. The hook responsibilities are distributed across the `planner/` package and `configs/dt/room2ite_map.json`. The `RecommendTemplate` contract (`initialize` + `run` + `log_recommendations`) is honored; the per-step RL hooks are superseded by the oracle-based evaluation model.

**Proof**

| Claim (template hook) | Template ref | DCTwin ref | Evidence |
| --- | --- | --- | --- |
| `zone_acu_dict` (zone→device map) | `hooks.py:19-133` | `configs/dt/room2ite_map.json:1-50` | Template Python dict; DCTwin JSON config maps "Data Hall 1F 2A" → ITE resources — same role for thermal KPI scoping |
| `get_reward_fn()` (power/temp/RH penalties) | `hooks.py:149-241` | `planner/objective.py:47-67`, `planner/kpi.py:50-118` | Template: PUE/HVAC/inlet/chiller reward terms. DCTwin: `objective.score()` = `energy_term + λ_temp·inlet_excess + λ_rh·rh_excursion + λ_zone·zone_band`; `kpi.aggregate_kpi` computes `weighted_energy_cost`, `inlet_violation_steps`, `rh_violation_steps`, `zone_temp_band_steps` |
| `get_current_state(env, data_file, obs_keys)` | `hooks.py:339-355` | `planner/oracle_worker.py:32-46`, `planner/monitor.py:35-71` | Template reads JSON, returns `[1,n_obs]` array. DCTwin: `read_step_sample()` calls `env.inspect_current_observation()` over `MonitorSpec`-discovered names → `StepSample`; `discover_monitor()` auto-detects obs names |
| `log_recommendations(env, data, data_file)` | `hooks.py:358-392` | `planner/recommendation.py:25-160` | Template writes per-action JSON. DCTwin: `build_recommendation()` → setpoints + predicted KPIs + forecast metadata + robust diagnostics; `write_recommendation()` serializes |
| `get_reward_fn_single_hall(target_hall)` | `hooks.py:248-329` | `planner/oracle.py:33-34`, `planner/oracle_worker.py:17-29` | Template filters `zone_acu_dict[target_hall]`. DCTwin: `OracleConfig.monitored_hall="1f 2a"`, `EvalTask.monitored_hall` scopes thermal KPI to the controlled hall |
| `save_best_fn(policy)` | `hooks.py:244-246` | ABSENT | Template `torch.save(policy.state_dict(), policy.pth)`. DCTwin is a search optimizer — no policy artifact; output is `recommendation.json` |
| `zone_names` list | `hooks.py:135-139` | implicit in `room2ite_map.json` keys | Template `['DH_1','DH_2','DH_4']`; DCTwin: zone identifiers are the JSON keys (no explicit list) |
| `zone_acu_model_map` | `hooks.py:142-146` | `planner/plant.py` + `broadcast.py` | DCTwin: `BroadcastPolicy` maps 3 globals → N actuators via `ActionEntry` kinds; `plant.py` models chiller/CHW energy |
| device-name regex normalization | `hooks.py:16` | `planner/env_actions.py` / `broadcast.py` | DCTwin works with actuator names in DT-prototxt declaration order; consistent naming via prototxt rather than regex |
| No `ai_policy_train.py` | `ai_policy_train.py` (exists) | ABSENT | DCTwin is search-based; no RL training loop, no `policy.pth` |
| No `hooks.py` in `src/` | `sample_template/hooks.py` | ABSENT from `src/` | `find src -name hooks.py` → none (`test/hooks.py`, `tutorials/co-sim/hooks.py` are EnergyPlus-adapter, not policy templates) |

**Deviations.** The hook functionality is reorganized, not omitted: reward → `objective.py` + `kpi.py`; state observation → `oracle_worker.py` + `monitor.py`; recommendation logging → `recommendation.py`; zone config → `room2ite_map.json`. Reward semantics differ in kind: the template's `reward_fn` returns a per-step scalar for RL gradient; DCTwin's `objective.score()` is a weekly rollup (energy + soft penalties) used to rank beam-search candidates. `save_best_fn`/`policy.pth` are N/A because there is no learned policy.

---

## Configs

**Verdict: adapted.** DCTwin keeps the `configs/dt/` file set and JSON schemas identical, and keeps `test.prototxt`/`train.prototxt`/`dt.prototxt` protobuf shapes identical. It deliberately omits the two RL-only policy configs.

**Proof**

| Claim | Template ref | DCTwin ref | Evidence |
| --- | --- | --- | --- |
| `dt/` file set matches (4 files) | `configs/dt/` | `configs/dt/` | Both: `dt.prototxt`, `device_his_map.json`, `device_key_map.json`, `room2ite_map.json` |
| `device_key_map.json` top-level schema | `device_key_map.json` (13 keys) | `device_key_map.json` (13 keys) | Identical set of 13 top-level keys (acus, chilled water loops, chilled water pumps, chillers, condenser water loops, condenser water pumps, cooling towers, dehumidifiers, heat_exchangers, ites, secondary chilled water pumps, thermal storage tanks, zones). Same schema, fewer device instances: template 2814 lines vs DCTwin 918 |
| `device_key_map.json` zones schema (3 sub-keys) | `device_key_map.json:18-113` | `device_key_map.json:18-54` | Both: `{air temperature, air relative humidity, ite power}` |
| `device_key_map.json` ites schema (5 sub-keys) | `device_key_map.json:115-158` | `device_key_map.json:55-62` | Both: `{inlet dry-bulb temperature, inlet relative humidity, cpu power, fan power, ups power}` |
| `device_his_map.json` top-level matches | `device_his_map.json:1-30` | `device_his_map.json:1-27` | Identical structure (chilled/condenser water loops, zones, ites, …) |
| `room2ite_map.json` schema matches | `room2ite_map.json:1-30` | `room2ite_map.json:1-30` | Both: `{room → {ite → {wattsPerUnit, numberOfUnits, totalWatts}}}` |
| `test.prototxt` structure | `configs/policy/test.prototxt:1-27` | `configs/policy/test.prototxt:1-27` | Both: `logging_config`, `policy_config`, `test_collector_config` at the same lines |
| `train.prototxt` structure | `configs/policy/train.prototxt:1-30` | `configs/policy/train.prototxt:1-30` | Both: `logging_config`, `policy_config`, `off_policy_trainer_config` |
| `dt.prototxt` `eplus_env_config` shape | `configs/dt/dt.prototxt:1-10` | `configs/dt/dt.prototxt:1-10` | Both: `eplus_env_config { weather_file, model_file, simulation_time_config, … }` |
| Omits `recommend.prototxt` | `configs/policy/recommend.prototxt` (present) | ABSENT | DCTwin does not run inference on pre-trained RL policies |
| Omits `train_test.prototxt` | `configs/policy/train_test.prototxt` (present) | ABSENT | DCTwin does not use combined RL train+test |

**Deviations.** `recommend.prototxt` (inference on a trained RL policy) and `train_test.prototxt` (combined RL train+test) are intentionally absent — DCTwin is a search/planning optimizer, not an RL system. All shared JSON schemas and the `test`/`train`/`dt` protobuf shapes are honored precisely.

---

## Data formats

**Verdict: adapted.** DCTwin follows the schedule-folder convention (`acus/`, `branches/`, `workloads/` with JSON arrays) and the EPW weather standard, replaces the static `data_sample.json` with continuous per-15-minute telemetry, and extends `data/` with calibration + realized-history files for dual-loop learning.

**Proof**

| Claim | Template ref | DCTwin ref | Evidence |
| --- | --- | --- | --- |
| `schedule/` subfolders follow template (+ `pumps/`) | `schedule/{acus,branches,workloads}/` | `schedule/{acus,branches,pumps,workloads}/` | Template: 3 dirs; DCTwin: 4 dirs. Template `acus/`: 48 files (`cra_*_crac_x_*.json`); DCTwin `acus/`: `fan_on_off/` with 22 files (`data hall * acu-*.json`) |
| `weather/` uses EPW on both sides | `weather/de_berlin.epw` (`LOCATION,BERLIN,-,DEU,IWEC…`) | `weather/SGP_Singapore.486980_IWEC.epw` (`LOCATION,SINGAPORE,-,SGP,IWEC…`) | Identical ASHRAE EPW header format |
| Workload files: JSON arrays of floats | `workloads/cra_1_07_crac_x_402.json:1-20` | `workloads/data hall 1f 2a ite-1.json:1-20` | Both are JSON arrays of per-interval floats |
| Branch files: JSON arrays | `branches/` (`chilled water supply branch N.json`) | `branches/` (same naming, 5 files) | Same naming convention |
| ACU files: JSON arrays | `acus/cra_1_07_crac_x_401.json:1-3` (`[1.0,1.0,…]`) | `acus/fan_on_off/data hall 1f 2a acu-1.json:1-30` (`[1,1,1,…]`) | Both JSON on/off-schedule arrays |
| `data_sample.json` → `his_data_processed.csv` | `data/data_sample.json:2-4` (single timestamped config dict) | `data/his_data_processed.csv` (`_time,ACLF,PUE,WCLF,…_Power`) | Shift from static policy sample to continuous per-15-min telemetry (100+ PDU power columns) |
| DCTwin EXTENDS `data/` with calibration/realized history | `data/` (none) | `data/calibration.json`, `calibration_history.json`, `realized_history.csv` | Adds bias/sigma dicts, paired predicted/realized weeks, weekly KPI records (`total_hvac_energy_kwh`, `pue_mean`, `inlet_temp_max_c`) |
| Calibration history stores paired (predicted, realized) | n/a (not in template) | `data/calibration_history.json` (`planner/history.py:46-60`) | `advance_calibration()` appends `{week_start, predicted, realized}` → dual-loop learning |
| Realized history CSV separate from forecaster CSV | n/a | `his_data_processed.csv` vs `realized_history.csv` (`planner/history.py:6-7,16-29`) | Comment: realized-KPI history must NOT be the forecaster's per-step IT-load CSV (different schema: 15-min, 384 columns) |

**Deviations.** Domain-specific, not schema violations: (1) ACU schedules live under `fan_on_off/` with building-topology naming (`data hall * acu-*.json`) instead of generic `cra_*_crac_x_*.json`; (2) static `data_sample.json` → per-15-min `his_data_processed.csv` for forecasting; (3) `calibration.json`/`calibration_history.json`/`realized_history.csv` added for the P1-policy + P2-calibrator dual loop (absent from the RL baseline); (4) `pumps/` is a CHW-plant extension. The schedule-subfolder convention, EPW format, and JSON-array formats are all honored.

---

## Models

**Verdict: extended.** `models/building.json` is schema-compliant (identical top-level keys); the IDF is moved into a `models/idf/` subfolder; a statistical `forecaster.pkl` is added in place of trained neural weights.

**Proof**

| Claim | Template ref | DCTwin ref | Evidence |
| --- | --- | --- | --- |
| `building.json` structure matches | `models/building.json:1-5` | `models/building.json:1-5` | Identical top-level keys `[constructions, geometry, inputs, meta, models]`; `meta` has `name`/`description`, `models` has curve models |
| `building.idf` moved to `models/idf/` | `models/building.idf` | `models/idf/building.idf` | Template: `building.idf` in root (1207 KB). DCTwin: `idf/` subfolder, `idf/building.idf` (842 KB) — logical grouping |
| Adds `forecaster.pkl` (statistical, not neural) | n/a (template has no forecaster) | `models/forecaster.pkl` | `plan_weekly.py:40` loads it via pickle; `fit_forecaster.py:45-68` saves config (`method="persistence"`, his_csv, room2ite_path, weather_file). Template `policy.pth` (2.9 MB PyTorch) vs DCTwin `forecaster.pkl` (655 B config dict) |
| `WeeklyPlanTemplate` honors `RecommendTemplate.__call__` | `recommend_template.py:130-142` | `plan_weekly.py:22,30,67` | Base `__call__` runs `initialize()`, `run()`, `cleanup()`; DCTwin imports `RecommendTemplate` (l.11), defines `initialize` (l.30) + `run` (l.67), `run()` overridden to call `run_weekly_plan()` (l.73-81) |
| Trajectory subclasses honor `TrajectoryPolicyTemplate` | `trajectory_policy_template.py:15,629` | `ai_trajectory_test.py:14,17`; `baseline_policy_test.py:12,15` | Both subclass `TrajectoryPolicyTemplate` and define `initialize()`; both use the `__call__(policy=...)` protocol |
| `src/policy/` ABSENT (no `policy.pth`) | `policy/policy.pth` | ABSENT | DCTwin's "policy" is `BeamPlanner` (`beam_search.py`); `plan_weekly.py:61` assigns `self.planner = BeamPlanner(...)` to `self.policy` (l.63) as a base-class stub; `run()` overrides the policy call entirely |
| `run()` override skips `log_recommendations` | `recommend_template.py:25-50,60-72` | `plan_weekly.py:67-86` | Base `run()` calls `self.log_recommendations()` (would raise `NotImplementedError`); DCTwin `run()` fully overrides, calls `run_weekly_plan()` + `write_recommendation()` directly, never reaches `log_recommendations()` |
| No `hooks.py` / `ai_policy_train.py` | `hooks.py:1-242`; `ai_policy_train.py:1-24` | ABSENT | No RL reward infra, no `dcbrain.init` + `trainer.run()`; replaced by `fit_forecaster.py` + `planner/beam_search.py` |
| `configs/policy/` missing `recommend`/`train_test` prototxt | `configs/policy/{recommend,test,train,train_test}.prototxt` | `configs/policy/{test,train}.prototxt` only | DCTwin has 2 of 4 policy prototxts |

**Deviations.** Intentional, by architecture: (1) IDF reorganized to `models/idf/`; (2) `forecaster.pkl` (655 B statistical config) replaces `policy.pth` (2.9 MB neural weights); (3) no `policy/` directory — the policy is the in-code `BeamPlanner`; (4) no `hooks.py`/`ai_policy_train.py` — replaced by `fit_forecaster.py` + `planner/`; (5) `configs/policy/` omits the RL-only prototxts; (6) `WeeklyPlanTemplate.run()` override is the intended extension point, so `log_recommendations()` is never called. All `RecommendTemplate`/`TrajectoryPolicyTemplate` base-class contracts for `__call__`, `initialize`, `run` are honored.

---

## Policy

**Verdict: missing (by design).** There is no `src/policy/` and no `policy.pth`. DCTwin's optimization "policy" is the algorithmic `BeamPlanner` (`planner/beam_search.py`), an in-code heuristic search over the setpoint grid — not a trained weights artifact.

**Proof**

| Claim | Template ref | DCTwin ref | Evidence |
| --- | --- | --- | --- |
| Template `policy/` holds trained `policy.pth` | `policy/policy.pth` | ABSENT | Template: 2.9 MB trained RL policy from dcbrain. DCTwin: no `policy/` dir |
| DCTwin's "policy" is `BeamPlanner` (algorithmic) | n/a | `plan_weekly.py:61,63`; `planner/beam_search.py` | `self.planner = BeamPlanner(...)` assigned to `self.policy` as a base-class stub; deterministic enumeration + beam refine, never invoked through the base `run()` contract |
| Beam search configured in Python, not prototxt | `configs/policy/*.prototxt` | `plan_weekly.py:56-60` (`BeamConfig` dataclass) | DCTwin configures search via a `BeamConfig` dataclass, not protobuf |

**Deviations.** No learned weights exist to persist. The `policy/policy.pth` artifact and its surrounding RL machinery are deliberately replaced by deterministic optimization. The base-class attribute `self.policy` is still satisfied (it points at the `BeamPlanner` stub), so the template's structural contract holds even though the storage artifact is absent.

---

## Where DCTwin diverges (and why)

The single architectural fact explains every "missing" verdict: **DCTwin is a search/planning optimizer, not a trained RL agent.** The dcwiz sample template assumes a dcbrain SAC policy — a neural network trained on the dctwin environment via reward-driven episodes, persisted as `policy/policy.pth`, fed per-step rewards and states through `hooks.py`, and trained by `ai_policy_train.py` (`dcbrain.init()` + `trainer.run()`). DCTwin instead searches three global setpoints (SAT, airflow, CHWST) with a beam search whose every candidate is scored by a full-week EnergyPlus oracle run.

That swap removes the entire RL training pipeline and relocates its responsibilities:

| Template (RL) artifact | DCTwin replacement | Where it lives |
| --- | --- | --- |
| `policy/policy.pth` (trained weights) | `BeamPlanner` (in-code algorithm) | `planner/beam_search.py` |
| `ai_policy_train.py` (`trainer.run()`) | one-shot model/config prep | `fit_forecaster.py` → `models/forecaster.pkl` |
| `hooks.get_reward_fn()` (per-step scalar) | weekly objective rollup | `planner/objective.py` + `planner/kpi.py` |
| `hooks.get_current_state()` | observation discovery + sampling | `planner/monitor.py` + `planner/oracle_worker.py` |
| `hooks.log_recommendations()` | recommendation builder/serializer | `planner/recommendation.py` |
| `hooks.zone_acu_dict` / `zone_acu_model_map` | global→actuator broadcast + plant model | `planner/broadcast.py` + `planner/plant.py` + `configs/dt/room2ite_map.json` |
| `recommend.prototxt` / `train_test.prototxt` | Python `BeamConfig` dataclass | `plan_weekly.py:56-60` |

So the reward function, state extraction, recommendation logging, and zone mapping all still exist — just as Python modules in `planner/` and JSON config, rather than as the template's single `hooks.py`. The forecaster (`fit_forecaster.py` → `forecaster.pkl`, a small statistical config) is DCTwin's "model preparation" step in the slot the template fills with neural-policy training.

---

## Conclusion

**Yes — with caveats.** DCTwin did follow the dcwiz standard policy templates where they apply to its architecture:

- **`RecommendTemplate`: followed via adaptation.** `WeeklyPlanTemplate(RecommendTemplate)` imports from `dcwiz_policy_template`, overrides `initialize()` and `run()` at the designated extension points, and respects the `__init__`/`__call__` contract.
- **`TrajectoryPolicyTemplate`: followed for baseline, partially for AI replay.** `BaselineTrajectory` honors the contract end-to-end (subclass, `initialize()`, base `run_baseline()` via `policy="baseline"`). `AITrajectoryReplay` honors the structure and `initialize()` override but has a real gap — it calls `run(policy="ai")` without setting `self.test_collector`, which the template's `run_ai()` rejects at runtime. **Fix:** set `self.test_collector` in `initialize()`, or call with `policy="baseline"` (the fixed-action replay is baseline-shaped anyway).
- **`configs/`, `data/`, `models/`: honored.** JSON device-map schemas, EPW weather format, schedule-folder convention, and `dt`/`test`/`train` prototxt shapes all match; DCTwin adds domain-specific extensions (calibration/realized-history, `pumps/`, `forecaster.pkl`) without breaking the shared schemas.
- **RL-training artifacts (`ai_policy_train.py`, single-file `hooks.py`, `policy/policy.pth`, `recommend.prototxt`, `train_test.prototxt`): intentionally absent.** These are RL-pipeline-specific; DCTwin is a deterministic planner and replaces them with `fit_forecaster.py`, the `planner/` package, and `BeamPlanner`.

Net: the template *contracts* (base-class subclassing, the `initialize`/`run`/`__call__` lifecycle, the config/data/model layouts) are honored. The only outright contract gap to remediate is the `AITrajectoryReplay` `test_collector` omission; everything else is a justified architectural adaptation from "trained RL policy" to "search-based planner."
