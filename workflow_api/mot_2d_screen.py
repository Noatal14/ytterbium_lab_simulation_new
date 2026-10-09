"""Strict, shared validation for canonical 2D-MOT Screening outputs."""
from __future__ import annotations

import hashlib, json, math, os, sqlite3, stat
from pathlib import Path
from typing import Any
from utils.mot_2d_study import summarize_replicates

SCREEN_TRIALS = 17
MAX_DB_BYTES = 128 * 1024 * 1024

class ScreenValidationError(ValueError): pass

def _finite(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ScreenValidationError("Screening output contains a non-finite number.")
    return float(value)

def _safe(root:Path,path:Path)->None:
    current=root
    for part in path.relative_to(root).parts:
        current/=part
        if current.is_symlink(): raise ScreenValidationError("Unsafe Screening artifact path.")

def _json(path: Path, limit: int = 8 * 1024 * 1024, *, root:Path|None=None) -> Any:
    if root is not None:_safe(root,path)
    row=path.lstat()
    if not stat.S_ISREG(row.st_mode) or path.is_symlink() or not 0<row.st_size<=limit: raise ScreenValidationError("Unsafe Screening artifact.")
    return json.loads(path.read_text("utf-8"))

def _all_finite(value: Any) -> None:
    if isinstance(value,dict):
        for child in value.values(): _all_finite(child)
    elif isinstance(value,list):
        for child in value: _all_finite(child)
    elif isinstance(value,float) and not math.isfinite(value): raise ScreenValidationError("Screening output contains a non-finite number.")

def _design(manifest:dict[str,Any],s0:float,worker:int)->dict[str,Any]:
    fixed=manifest["fixed_design"]
    return {"fixed_s0":s0,"dt_s":fixed["working_dt_s"],"solver":"RK4StHybridCustom","ensemble_dir":manifest["ensemble_source"]["directory"],"zeeman_seeds":manifest["seed_roles"]["discovery"],"mot_seeds":manifest["mot_seeds"]["discovery"],"particles_per_ensemble":fixed["particle_counts"]["screen"],"sampler_seed":137+worker,"bounds":{"s0":[s0,s0],"detuning_gamma":list(fixed["detuning_bounds_gamma"]),"magnet_radius_m":list(fixed["magnet_radius_bounds_m"])},"git_commit":manifest["provenance"]["git_commit"],"campaign_design_id":manifest["provenance"]["physical_model_sha256"]}

def _db(path:Path,expected:dict[str,Any],trials:list[dict[str,Any]],study_name:str,root:Path)->None:
    _safe(root,path)
    row=path.lstat()
    if not stat.S_ISREG(row.st_mode) or path.is_symlink() or not 0<row.st_size<=MAX_DB_BYTES: raise ScreenValidationError("Invalid Screening database.")
    connection=None
    try:
        connection=sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro&immutable=1",uri=True,timeout=1)
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",): raise ScreenValidationError("Invalid Screening database.")
        studies=connection.execute("SELECT study_id,study_name FROM studies").fetchall()
        rows=connection.execute("SELECT trial_id,number,state FROM trials ORDER BY number").fetchall()
        attrs=dict(connection.execute("SELECT key,value_json FROM study_user_attributes"))
        values=connection.execute("SELECT t.number,v.value,v.value_type FROM trials t JOIN trial_values v ON v.trial_id=t.trial_id WHERE v.objective=0 ORDER BY t.number").fetchall()
        params=connection.execute("SELECT t.number,p.param_name,p.param_value,p.distribution_json FROM trials t JOIN trial_params p ON p.trial_id=t.trial_id ORDER BY t.number,p.param_name").fetchall()
    except (sqlite3.Error,OSError,KeyError,json.JSONDecodeError) as error: raise ScreenValidationError("Invalid Screening database.") from error
    finally:
        if connection is not None: connection.close()
    design_id=hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
    if len(studies)!=1 or studies[0][1]!=study_name: raise ScreenValidationError("Screening database study identity is incompatible.")
    if len(rows)!=SCREEN_TRIALS or [(number,state) for _,number,state in rows]!=[(n,"COMPLETE") for n in range(SCREEN_TRIALS)]: raise ScreenValidationError("Screening database trial set is incomplete.")
    if set(attrs)!={"scientific_design","design_id"} or json.loads(attrs.get("scientific_design","null"))!=expected or json.loads(attrs.get("design_id","null"))!=design_id: raise ScreenValidationError("Screening database design is incompatible.")
    if len(values)!=SCREEN_TRIALS or any(number!=index or value_type!="FINITE" or _finite(value)!=trials[index]["mean_conditional_efficiency"] for index,(number,value,value_type) in enumerate(values)): raise ScreenValidationError("Screening database values disagree with JSON results.")
    expected_params=[]
    distributions={"detuning_gamma":{"name":"FloatDistribution","attributes":{"log":False,"step":None,"low":expected["bounds"]["detuning_gamma"][0],"high":expected["bounds"]["detuning_gamma"][1]}},"magnet_radius":{"name":"FloatDistribution","attributes":{"log":False,"step":None,"low":expected["bounds"]["magnet_radius_m"][0],"high":expected["bounds"]["magnet_radius_m"][1]}}}
    for number,item in enumerate(trials):expected_params.extend([(number,"detuning_gamma",item["detuning_gamma"],distributions["detuning_gamma"]),(number,"magnet_radius",item["magnet_radius"],distributions["magnet_radius"])])
    if len(params)!=len(expected_params) or any(number!=a or name!=b or _finite(value)!=c or json.loads(distribution)!=d for (number,name,value,distribution),(a,b,c,d) in zip(params,expected_params)):raise ScreenValidationError("Screening database parameters disagree with JSON results.")

def validate_screen_outputs(root:Path,manifest:dict[str,Any])->list[dict[str,Any]]:
    """Return every validated trial as a compact canonical ranking row."""
    if manifest.get("kind")!="mot_2d_s0_campaign" or manifest.get("stage")!="screen": raise ScreenValidationError("Campaign is not awaiting Screening validation.")
    values=manifest.get("s0_values")
    if not isinstance(values,list) or not values or len({float(value) for value in values})!=len(values) or any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0 for value in values):raise ScreenValidationError("Invalid frozen s0 values.")
    tasks=_json(root/"screen/tasks.json",root=root)
    expected_tasks=[{"s0":float(s0),"worker":worker} for s0 in values for worker in range(3)] if isinstance(values,list) else []
    if tasks!=expected_tasks: raise ScreenValidationError("Screening task registry is not canonical.")
    output=[]; seen_sources=set()
    for task in tasks:
        s0=float(task["s0"]);worker=int(task["worker"]);directory=root/"screen"/(f"s0_{s0:.6f}".replace(".","p"))/f"worker{worker}"
        _safe(root,directory);_safe(root,directory/"trials")
        if not directory.is_dir() or not (directory/"trials").is_dir() or {path.name for path in directory.iterdir()}!={"trials","summary.json","joint_screening.db"}:raise ScreenValidationError("Screening worker directory is not canonical.")
        files=sorted((directory/"trials").iterdir())
        if [path.name for path in files]!=[f"trial_{n:04d}.json" for n in range(SCREEN_TRIALS)]: raise ScreenValidationError("Screening trial set is incomplete or contains extras.")
        expected=_design(manifest,s0,worker);design_id=hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest(); compact=[]
        for number,path in enumerate(files):
            row=_json(path,root=root);_all_finite(row)
            if not isinstance(row,dict) or row.get("kind")!="mot_2d_joint_optimization_trial" or row.get("trial_number")!=number or _finite(row.get("batch_elapsed_seconds"))<0: raise ScreenValidationError("Invalid Screening trial identity.")
            parameters=row.get("parameters");design=row.get("design");replicates=row.get("replicates");statistics=row.get("statistics")
            if not isinstance(row,dict) or set(row)!={"kind","trial_number","parameters","design","batch_elapsed_seconds","replicates","statistics"} or not isinstance(parameters,dict) or set(parameters)!={"s0","detuning_gamma","magnet_radius"} or _finite(parameters["s0"])!=s0: raise ScreenValidationError("Invalid Screening parameters.")
            detuning=_finite(parameters["detuning_gamma"]);radius=_finite(parameters["magnet_radius"]);bounds=expected["bounds"]
            if not bounds["detuning_gamma"][0]<=detuning<=bounds["detuning_gamma"][1] or not bounds["magnet_radius_m"][0]<=radius<=bounds["magnet_radius_m"][1]: raise ScreenValidationError("Screening parameters are outside frozen bounds.")
            expected_trial_design={"dt_s":expected["dt_s"],"n_ensembles":len(expected["zeeman_seeds"]),"particles_per_ensemble":expected["particles_per_ensemble"],"mot_seed_start":24000,"stochastic_solver":expected["solver"],"design_id":design_id,"git_commit":expected["git_commit"],"ensemble_dir":expected["ensemble_dir"],"zeeman_seeds":expected["zeeman_seeds"],"mot_seeds":expected["mot_seeds"]}
            if design!=expected_trial_design or not isinstance(replicates,list) or len(replicates)!=len(expected["zeeman_seeds"]): raise ScreenValidationError("Screening trial provenance is incompatible.")
            efficiencies=[]
            for index,replicate in enumerate(replicates):
                exact={"ensemble_file","zeeman_seed","mot_seed","n_available","selection_method","subset_seed","n_input","captured","conditional_efficiency","estimated_total_efficiency","batch_elapsed_seconds"}
                frozen=manifest["input_ensembles"]["discovery"][index]
                if not isinstance(replicate,dict) or set(replicate)!=exact or replicate.get("ensemble_file")!=Path(frozen["path"]).name or replicate.get("zeeman_seed")!=expected["zeeman_seeds"][index] or replicate.get("mot_seed")!=expected["mot_seeds"][index] or replicate.get("n_available")!=frozen["survivor_count"] or replicate.get("selection_method")!="deterministic_random_without_replacement" or replicate.get("subset_seed")!=100000+expected["zeeman_seeds"][index] or replicate.get("n_input")!=expected["particles_per_ensemble"] or _finite(replicate.get("batch_elapsed_seconds"))!=_finite(row["batch_elapsed_seconds"]): raise ScreenValidationError("Screening replicate provenance is incompatible.")
                captured=replicate.get("captured"); n=expected["particles_per_ensemble"]
                if not isinstance(captured,int) or isinstance(captured,bool) or not 0<=captured<=n or _finite(replicate.get("conditional_efficiency"))!=captured/n: raise ScreenValidationError("Screening replicate efficiency is inconsistent.")
                survival=frozen["survivor_count"]/frozen["generation"]["n_initial_atoms"]
                if not math.isclose(_finite(replicate.get("estimated_total_efficiency")),(captured/n)*survival,rel_tol=1e-15,abs_tol=0.0):raise ScreenValidationError("Screening total efficiency is inconsistent.")
                efficiencies.append(captured/n)
            mean=sum(efficiencies)/len(efficiencies)
            if not isinstance(statistics,dict) or set(statistics)!={"n_replicates","mean_conditional_efficiency","conditional_95_ci","conditional_95_ci_half_width","mean_estimated_total_efficiency","estimated_total_95_ci","estimated_total_95_ci_half_width"} or statistics!=summarize_replicates(replicates) or _finite(statistics.get("mean_conditional_efficiency"))!=mean: raise ScreenValidationError("Screening statistics are inconsistent.")
            source=path.relative_to(root).as_posix()
            if source in seen_sources: raise ScreenValidationError("Duplicate Screening source.")
            seen_sources.add(source);item={"s0":s0,"detuning_gamma":detuning,"magnet_radius":radius,"mean_conditional_efficiency":mean,"source":source};compact.append(item);output.append(item)
        summary=_json(directory/"summary.json",root=root);_all_finite(summary)
        ranked=summary.get("ranked_trials") if isinstance(summary,dict) else None
        expected_summary_design={"dt_s":expected["dt_s"],"n_ensembles":len(expected["zeeman_seeds"]),"particles_per_ensemble":expected["particles_per_ensemble"],"mot_seed_start":24000,"stochastic_solver":expected["solver"],"ensemble_dir":expected["ensemble_dir"],"zeeman_seeds":expected["zeeman_seeds"],"sampler_seed":expected["sampler_seed"],"bounds":expected["bounds"]}
        study_name=f"{manifest['name']}_screen_{f's0_{s0:.6f}'.replace('.', 'p')}_w{worker}"
        if set(summary)!={"kind","study_name","objectives","fixed_s0","n_registered_trials","n_finished_trials","ranked_trials","pareto_front","design"} or summary.get("kind")!="mot_2d_joint_optimization_summary" or summary.get("study_name")!=study_name or summary.get("objectives")!=["maximize_mean_conditional_efficiency"] or summary.get("design")!=expected_summary_design or summary.get("fixed_s0")!=s0 or summary.get("n_registered_trials")!=SCREEN_TRIALS or summary.get("n_finished_trials")!=SCREEN_TRIALS or not isinstance(ranked,list) or len(ranked)!=SCREEN_TRIALS or summary.get("pareto_front")!=[]: raise ScreenValidationError("Invalid Screening summary.")
        by_number={number:item for number,item in enumerate(compact)}
        if [row.get("trial_number") for row in ranked]!=sorted(range(SCREEN_TRIALS),key=lambda number:(-by_number[number]["mean_conditional_efficiency"],number)):raise ScreenValidationError("Screening ranking is not canonical.")
        for ranked_row in ranked:
            number=ranked_row.get("trial_number") if isinstance(ranked_row,dict) else None
            if not isinstance(ranked_row,dict) or set(ranked_row)!={"trial_number","mean_conditional_efficiency","parameters"} or not isinstance(number,int) or number not in by_number or ranked_row.get("parameters")!={"s0":s0,"detuning_gamma":by_number[number]["detuning_gamma"],"magnet_radius":by_number[number]["magnet_radius"]} or _finite(ranked_row.get("mean_conditional_efficiency"))!=by_number[number]["mean_conditional_efficiency"]: raise ScreenValidationError("Screening summary disagrees with trial JSON.")
        _db(directory/"joint_screening.db",expected,compact,study_name,root)
    return output
