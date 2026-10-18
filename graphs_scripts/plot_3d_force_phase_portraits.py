"""Longitudinal phase portraits for the two provisional finalists.

Isolated 3D-MOT components; x=y=vx=vy=0 enforced after every stochastic step.
Positions are absolute lab coordinates in the solver and signed z-z_MOT in
the figure. The force background is a mean-force central slice, not random
force realizations or a full-apparatus capture-efficiency measurement.
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.transforms import Bbox
import numpy as np

from lab_setup.config_builder import build_base_config
from atomsmltr.simulation.simulator.simbase import get_force_vec
from utils.RK4StHybridCustom import RK4StHybridCustom
from config import MOT_3D_CAPTURE_CONFIG

ROOT=Path(__file__).resolve().parents[1]
CAMPAIGN=ROOT/"data/optimization/mot_3d/mot_3d_s0_1p3_search10us_20261012_v1"
OUTPUT=ROOT/"graphs/report_optimization"
DATA=ROOT/"data/validation/mot_3d/report_phase_portraits"


class MeanForceRK4(RK4StHybridCustom):
    """Identical RK4 drift, with the recoil increment explicitly disabled."""

    def du_fluct(self,t,state,dt):
        return np.zeros_like(state)


def run_family(family,index,plot_only=False,deterministic=False):
    source=CAMPAIGN/"selection/finalists"/(family+".json")
    candidate=json.loads(source.read_text())["candidates"][index]
    profile=candidate["resolved_profile"]
    center=np.asarray(profile["center_position_m"],dtype=float)
    suffix="_deterministic" if deterministic else ""
    destination=DATA/(family+suffix)
    destination.mkdir(parents=True,exist_ok=True)
    path=destination/"phase_portrait.npz"
    metadata={"candidate":candidate,"selection_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
              "method":__doc__,"dt_s":1e-5,"t_max_s":.1,"seed":None if deterministic else 56001,
              "stochastic":not deterministic,"solver":"RK4 mean force" if deterministic else "RK4StHybridCustom",
              "initial_position_offset_m":-.08,"initial_vz_m_s":list(range(2,71,2))}
    if not plot_only:
        atom,config=build_base_config(include_zeeman=False,include_2d_mot=False,include_3dmot=True,
                                     gravity_enabled=False,zones=[],_3d_mot_config=profile)
        positions=np.linspace(-.08,.04,401)
        velocities=np.linspace(-15.,75.,451)
        zz,vv=np.meshgrid(positions,velocities)
        state=np.zeros((zz.size,6));state[:,:3]=center
        state[:,2]+=zz.ravel();state[:,5]=vv.ravel()
        print(f"{family}: computing force slice",flush=True)
        background=get_force_vec(state,config)[:,2].reshape(zz.shape)
        if not np.isfinite(background).all():raise ValueError("Invalid force grid")
        initial=np.asarray(metadata["initial_vz_m_s"],dtype=float)
        state=np.zeros((len(initial),6));state[:,:3]=center
        state[:,2]-=.08;state[:,5]=initial
        solver=(MeanForceRK4 if deterministic else RK4StHybridCustom)(config)
        solver.rng=np.random.default_rng(metadata['seed'])
        times=np.arange(10001)*metadata['dt_s']
        history=np.empty((len(times),len(initial),2),dtype=np.float32)
        history[0]=state[:,[2,5]]
        for step in range(1,len(times)):
            state+=solver._iterate(times[step-1],state,metadata['dt_s'])
            state[:,0]=center[0];state[:,1]=center[1];state[:,3:5]=0.
            if not np.isfinite(state).all():raise ValueError("Invalid stochastic state")
            history[step]=state[:,[2,5]]
            if step%2500==0:print(f"{family}: {step}/10000",flush=True)
        np.savez_compressed(path,position_grid_m=positions,velocity_grid_m_s=velocities,
                            force_z_N=background,time_s=times,initial_vz_m_s=initial,
                            trajectory_z_offset_m=history[:,:,0].T-center[2],trajectory_vz_m_s=history[:,:,1].T)
        metadata['outcomes_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        (destination/"phase_portrait.json").write_text(json.dumps(metadata,indent=2)+"\n")
    else:
        saved=json.loads((destination/"phase_portrait.json").read_text())
        if saved['candidate']!=candidate:raise ValueError("Cached candidate differs")
        if saved.get('stochastic',True)==deterministic:raise ValueError("Cached simulation mode differs")
        if hashlib.sha256(path.read_bytes()).hexdigest()!=saved['outcomes_sha256']:raise ValueError("Cache hash mismatch")
    with np.load(path,allow_pickle=False) as d:
        # Resolve the green contribution on a finer central grid, independently
        # of the much stronger total-force scale. No trajectory rerun is needed.
        green_profile=json.loads(json.dumps(profile))
        green_profile['399']['enabled']=False
        _,green_config=build_base_config(include_zeeman=False,include_2d_mot=False,include_3dmot=True,
                                        gravity_enabled=False,zones=[],_3d_mot_config=green_profile)
        green_positions=np.linspace(-.005,.005,301)
        green_velocities=np.linspace(-5.,5.,301)
        zz,vv=np.meshgrid(green_positions,green_velocities)
        green_states=np.zeros((zz.size,6));green_states[:,:3]=center
        green_states[:,2]+=zz.ravel();green_states[:,5]=vv.ravel()
        green_force=get_force_vec(green_states,green_config)[:,2].reshape(zz.shape)
        if not np.isfinite(green_force).all():raise ValueError('Invalid green force slice')
        np.savez_compressed(destination/'green_force_zoom.npz',position_offset_m=green_positions,
                            velocity_m_s=green_velocities,force_z_N=green_force)
        radius=MOT_3D_CAPTURE_CONFIG['capture_radius_m']
        speed_limit=MOT_3D_CAPTURE_CONFIG['maximum_final_speed_m_s']
        captured=(np.abs(d['trajectory_z_offset_m'][:,-1])<=radius)&(np.abs(d['trajectory_vz_m_s'][:,-1])<=speed_limit)
        classification={'criterion':'Instantaneous position and speed at end of 1D projected simulation',
                        'time_s':float(d['time_s'][-1]),'radius_m':radius,'maximum_speed_m_s':speed_limit,
                        'initial_velocity_m_s':d['initial_vz_m_s'].tolist(),'captured_at_end':captured.tolist()}
        (destination/'capture_classification.json').write_text(json.dumps(classification,indent=2)+'\n')
        fig,(ax,zoom)=plt.subplots(1,2,figsize=(15,6.8),layout="constrained",gridspec_kw={'width_ratios':[1.4,1]})
        colors={True:'#167d75',False:'#d95f02'}
        velocity_scale=plt.cm.ScalarMappable(norm=Normalize(vmin=d['initial_vz_m_s'].min(),vmax=d['initial_vz_m_s'].max()),cmap='plasma')
        for panel in (ax,zoom):
            # Draw captured paths last so the near-center loops remain visible.
            for i in np.argsort(captured):
                panel.plot(1000*d['trajectory_z_offset_m'][i],d['trajectory_vz_m_s'][i],
                           color=velocity_scale.to_rgba(d['initial_vz_m_s'][i]) if family=='angled_donut' else colors[bool(captured[i])],linewidth=1.0,alpha=1,
                           zorder=3 if captured[i] else 2)
            panel.grid(alpha=.15)
            panel.set_xlabel("Position (mm)")
            panel.set_ylabel(r"$v_z$ (m/s)")
        if family=='angled_donut':
            velocity_bar=fig.colorbar(velocity_scale,ax=ax,pad=.025,label=r'Initial longitudinal velocity $v_{z,0}$ (m/s)')
        else:
            ax.legend(handles=[Line2D([],[],color=colors[True],lw=1,label=f'Captured at end ({int(captured.sum())})'),
                           Line2D([],[],color=colors[False],lw=1,label=f'Not captured at end ({int((~captured).sum())})')],fontsize=9,loc='upper left')
        title="Blue shell" if family=="angled_donut" else "Single pass"
        ax.set(xlim=(-25 if family=='angled_donut' else -80,40),ylim=(-15,75))
        zoom.set(xlim=(-5,5),ylim=(-5,5))
        fig.suptitle(title,fontsize=17)
        method="deterministic mean-force trajectories" if deterministic else r"stochastic recoil projected onto $z$"
        fig.supxlabel(r"Central longitudinal slice: $x=y=v_x=v_y=0$ · "+method+"\n"+
                      f"End-of-run classification at 100 ms: distance ≤ {1000*radius:g} mm and speed ≤ {speed_limit:g} m/s (1D model).\n"
                      "Both panels show the same trajectories; the right panel is a central zoom.",fontsize=9)
        OUTPUT.mkdir(parents=True,exist_ok=True)
        for extension in ('pdf','png'):
            fig.savefig(OUTPUT/f"10_3d_force_phase_portrait_{family}{suffix}.{extension}",dpi=220,bbox_inches='tight')
        # Export each panel independently, preserving vector trajectories.
        fig.canvas.draw()
        fig.set_layout_engine(None)
        for panel,part in ((ax,'overview'),(zoom,'zoom')):
            included=[panel]
            if panel is ax and family=='angled_donut':
                included.append(velocity_bar.ax)
            for artist in [*fig.axes,*fig.texts]:
                artist.set_visible(artist in included)
            fig.canvas.draw()
            bounds=Bbox.union([a.get_tightbbox(fig.canvas.get_renderer()) for a in included])
            bounds=bounds.transformed(fig.dpi_scale_trans.inverted()).padded(.12)
            for extension in ('pdf','png'):
                fig.savefig(OUTPUT/f"10_3d_force_phase_portrait_{family}{suffix}_{part}.{extension}",
                            dpi=220,bbox_inches=bounds)
        plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plot-only',action='store_true')
    parser.add_argument('--deterministic',action='store_true',help='Disable photon recoil fluctuations; retain identical RK4 grid and force')
    args=parser.parse_args()
    for family,index in [('angled_donut',1),('single_pass',0)]:run_family(family,index,args.plot_only,args.deterministic)
