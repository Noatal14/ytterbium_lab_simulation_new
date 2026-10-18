"""Canonical Zeeman field and actual deterministic full-apparatus trajectory.

No fabricated stitching of independent atoms. A cached trajectory is used only
with the exact same configuration metadata. Optical surfaces are schematic
finite beam envelopes; magnet cuboids use actual positions and rotations.
"""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
from scipy.integrate import solve_ivp
from scipy.constants import hbar, physical_constants
from config import Geometry, ZEEMAN_FIELD_CONFIG, ZEEMAN_LASER_CONFIG, ZEEMAN_BEAM_DIRECTION
from lab_setup.config_builder import build_base_config
from lab_setup.mag_field_Zeeman import ZeemanSlowerField
from atomsmltr.simulation.simulator.simbase import get_force_vec
from lab_setup.laser_setup_3d import _get_beam_directions

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"graphs/report_optimization"
DATA=ROOT/"data/validation/apparatus_report"


def cylinder(ax, start, end, radius, color, alpha=.15):
    direction=np.asarray(end)-start
    unit=direction/np.linalg.norm(direction)
    helper=np.array([1.,0.,0.]) if abs(unit[0])<.8 else np.array([0.,1.,0.])
    a=np.cross(unit,helper);a/=np.linalg.norm(a);b=np.cross(unit,a)
    t,phi=np.meshgrid(np.linspace(0,1,2),np.linspace(0,2*np.pi,25))
    surface=np.asarray(start)+t[...,None]*direction+radius*(np.cos(phi)[...,None]*a+np.sin(phi)[...,None]*b)
    ax.plot_surface(surface[:,:,2]*1000,surface[:,:,1]*1000,surface[:,:,0]*1000,
                    color=color,alpha=alpha,linewidth=0,shade=False)


def magnet(ax, magnet, color="#777777"):
    corners=np.array([[x,y,z] for x in (-.5,.5) for y in (-.5,.5) for z in (-.5,.5)])
    corners=magnet.orientation.apply(corners*np.asarray(magnet.dimension))+magnet.position
    corners=corners[:,[2,1,0]]*1000
    faces=[[0,1,3,2],[4,5,7,6],[0,1,5,4],[2,3,7,6],[0,2,6,4],[1,3,7,5]]
    ax.add_collection3d(Poly3DCollection([corners[f] for f in faces],facecolors=color,
                                       edgecolors="#444444",linewidths=.25,alpha=.75))


def main(include_field=False):
    OUTPUT.mkdir(parents=True,exist_ok=True);DATA.mkdir(parents=True,exist_ok=True)
    p=json.loads((ROOT/"data/optimization/mot_2d/corrected_zeeman_s0_1p3_20261006/winners.json").read_text())["s0_1p300000"]["parameters"]
    selection=ROOT/"data/optimization/mot_3d/mot_3d_s0_1p3_search10us_20261012_v1/selection/finalists/angled_donut.json"
    profile=json.loads(selection.read_text())["candidates"][1]["resolved_profile"]
    atom,config=build_base_config(include_zeeman=True,include_2d_mot=True,include_3dmot=True,
          gravity_enabled=True,zones=[],magnet_radius=p["magnet_radius"],
          _2d_mot_config={"s0":p["s0"],"detuning_gamma":p["detuning_gamma"],"swap_polarization":False},
          _3d_mot_config=profile)
    zeeman=ZeemanSlowerField(angle_deg=Geometry.ZEEMAN_ARM_ANGLE_DEG,start_distance=Geometry.ZEEMAN_START_DISTANCE_M,
          radii=ZEEMAN_FIELD_CONFIG["radii_m"],positions_z=ZEEMAN_FIELD_CONFIG["positions_m"],tilt_angles=ZEEMAN_FIELD_CONFIG["tilt_angles_deg"])
    direction=-np.asarray(ZEEMAN_BEAM_DIRECTION)
    origin=-direction*Geometry.ZEEMAN_START_DISTANCE_M
    axis=np.linspace(-.06,.20,1501)
    points=origin+axis[:,None]*direction
    actual=zeeman.get_value(points)@direction*1e4
    transition=atom.trans["399"]
    end=float(max(ZEEMAN_FIELD_CONFIG["positions_m"]))
    guide_axis=np.linspace(0,end,501)
    guide_speed=np.sqrt(310**2-(310**2-50**2)*guide_axis/end)
    mu=transition.lande_factor*physical_constants["Bohr magneton"][0]/hbar
    ideal=-(ZEEMAN_LASER_CONFIG["detuning_gamma"]*transition.Gamma+transition.k*guide_speed)/mu*1e4
    np.savez_compressed(DATA/"zeeman_field_profile.npz",axis_m=axis,axial_field_G=actual,
                        guide_axis_m=guide_axis,guide_field_G=ideal,guide_speed_m_s=guide_speed)
    fig,ax=plt.subplots(figsize=(10,4.5),layout="constrained")
    ax.plot(guide_axis*1000,ideal,color="#0072B2",linewidth=2,label="Constant-deceleration resonance guide (310 → 50 m/s)")
    ax.plot(axis*1000,actual,color="#d62728",linestyle="--",linewidth=2,label="Canonical 19-ring magnet field")
    ax.set(xlabel="Distance along slower axis from design origin (mm)",ylabel="Axial magnetic field (G)")
    ax.grid(alpha=.2);ax.legend(fontsize=9)
    if include_field:
        for ext in ("pdf","png"):fig.savefig(OUTPUT/f"08_zeeman_magnetic_field.{ext}",dpi=220,bbox_inches="tight")
    plt.close(fig)
    meta={"2d_parameters":p,"3d_profile":profile,"initial_speeds_tested_m_s":[280.,250.,200.,150.,100.,80.,60.,40.],"gravity":True,
          "method":"Actual full 3D deterministic mean-force trajectory; no particle stitching"}
    cache=DATA/"trajectory.npz";metadata=DATA/"trajectory.json"
    if not (cache.exists() and metadata.exists() and json.loads(metadata.read_text())==meta):
        def rhs(t,u):return np.r_[u[3:],get_force_vec(u,config)/atom.mass]
        def escaped(t,u):return .55-u[2]
        escaped.terminal=True;escaped.direction=-1
        print("Integrating full-apparatus representative atom",flush=True)
        for speed in meta["initial_speeds_tested_m_s"]:
            initial=np.r_[-direction*.45,direction*speed]
            result=solve_ivp(rhs,(0,.12),initial,method="Radau",rtol=1e-5,atol=[1e-8]*3+[1e-4]*3,
                             max_step=1e-4,events=escaped,dense_output=True)
            if not result.success:raise RuntimeError(result.message)
            time=np.linspace(0,result.t[-1],10001)
            state=result.sol(time)
            distance=np.min(np.linalg.norm(state[:3].T-np.asarray(profile['center_position_m']),axis=1))
            print("Initial speed",speed,"closest approach to 3D",distance,flush=True)
            if distance<.005:break
        else:raise RuntimeError("No tested atom passed through all stages; no full-path figure generated")
        np.savez_compressed(cache,time_s=time,state=state,initial_speed_m_s=speed)
        metadata.write_text(json.dumps(meta,indent=2)+"\n")
    with np.load(cache) as d:states=d["state"]
    print("Trajectory extent",states[:3].min(axis=1),states[:3].max(axis=1),"final",states[:,-1],flush=True)
    if np.min(np.linalg.norm(states[:3].T-np.asarray(profile['center_position_m']),axis=1))>.005:
        raise RuntimeError("Representative atom did not reach 3D MOT; field figure saved, no fictitious full-path figure produced")
    fig=plt.figure(figsize=(14,6));ax=fig.add_subplot(111,projection="3d")
    for m in zeeman.collection.sources:magnet(ax,m)
    # Include the actual four 2D-MOT magnets as well.
    from lab_setup.mag_field_2d_mot import CustomQuadrupole
    for m in CustomQuadrupole(radius=p["magnet_radius"]).collection.sources:magnet(ax,m,color="#b1a58f")
    cylinder(ax,-direction*.48,direction*.04,Geometry.ZEEMAN_LASER_WAIST_M,"#3985da",.18)
    for axis_index in (0,1):
        unit=np.eye(3)[axis_index]
        cylinder(ax,-unit*.065,unit*.065,.005,"#3985da",.18)
    center=np.asarray(profile["center_position_m"])
    for tag,u in _get_beam_directions(profile):
        u=np.asarray(u)
        for key,color in (("399","#3985da"),("556","#3ca65a")):
            cfg=profile[key]
            radius=cfg.get("outer_cutoff_radius_m",cfg["waist_m"])
            cylinder(ax,center-u*.045,center,radius,color,.18)
            endpoints=np.vstack([center-u*.045,center])[:,[2,1,0]]*1000
            ax.plot(*endpoints.T,color=color,linewidth=1.1,alpha=.85)
    ax.plot(states[2]*1000,states[1]*1000,states[0]*1000,color="#a000b0",linewidth=1.7,zorder=8)
    for position,name in ((origin+direction*.06,"Zeeman slower"),(np.zeros(3),"2D MOT"),(center-np.array([0.,0.,.025]),"3D MOT")):
        ax.text(position[2]*1000,position[1]*1000+24,position[0]*1000+12,name,fontsize=10)
    ax.set(xlabel="Lab z (mm)",ylabel="Lab y (mm)",zlabel="Lab x (mm)",xlim=(-450,470),ylim=(-240,90),zlim=(-80,80))
    ax.set_box_aspect((920,330,160),zoom=.95);ax.view_init(elev=28,azim=-76)
    ax.set_proj_type("ortho")
    ax.grid(True)
    ax.tick_params(labelsize=8,pad=0)
    for axis3d in (ax.xaxis,ax.yaxis,ax.zaxis):
        axis3d.set_pane_color((.96,.96,.96,1.))
        axis3d._axinfo["grid"].update(color=(.65,.65,.65,.65),linewidth=.6,linestyle="-")
    fig.subplots_adjust(left=.05,right=.95,bottom=.10,top=.98)
    with np.load(cache) as d:initial_speed=float(d['initial_speed_m_s'])
    fig.text(.5,.02,f"Actual mean-force trajectory · initial axial speed {initial_speed:g} m/s · optimized 2D MOT · Blue-shell finalist 2\nBeam envelopes are schematic; their displayed lengths are chosen for visibility.",ha="center",fontsize=9)
    for ext in ("pdf","png"):fig.savefig(OUTPUT/f"09_full_apparatus_3d.{ext}",dpi=220,bbox_inches="tight")
    plt.close(fig)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-field",action="store_true",help="Explicitly recreate the optional Zeeman field figure")
    main(include_field=parser.parse_args().include_field)
