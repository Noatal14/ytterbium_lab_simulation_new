"""Animate a real identity-preserving stochastic oven -> Blue-shell chain.

Only new report caches/figures are written. Scientific campaigns are read-only.
The source uses the standard computational angular cutoff, not all oven flux.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
import numpy as np

from simulations import zeeman as zeeman_stage
from simulations import mot_2d as mot2d_stage
from simulations import mot_3d as mot3d_stage
from utils.simulation_helpers import (
    generate_timepoints, mot_extract_survivors, run_multiple_atoms_simulation,
)
from lab_setup.config_builder import build_base_config
from lab_setup.zones import get_entire_apparatus_zone
from graphs_scripts.plot_apparatus_and_zeeman import (
    Geometry, ZEEMAN_BEAM_DIRECTION, ZEEMAN_FIELD_CONFIG,
    ZeemanSlowerField, cylinder, magnet, _get_beam_directions,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/validation/apparatus_animation'
OUTPUT = ROOT / 'graphs/report_optimization'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(result, end_state=None, end_time=None):
    """Retain finite samples, the exact handoff, and at most 6000 points."""
    finite = np.isfinite(result.y).all(axis=0)
    t, y = np.asarray(result.t)[finite], np.asarray(result.y)[:, finite].T
    if not len(t):
        raise ValueError('Empty trajectory')
    if end_time is not None:
        take = t < end_time
        t, y = np.r_[t[take], end_time], np.vstack([y[take], end_state])
    indices = np.unique(np.r_[np.arange(0, len(t), max(1, int(np.ceil(len(t)/6000)))), len(t)-1])
    return t[indices], y[indices]


def crossing_time(result, state):
    """Recover the time of the production Zeeman interpolated handoff."""
    values = result.y[:3].T @ np.asarray(ZEEMAN_BEAM_DIRECTION)
    cutoff = zeeman_stage.ZEEMAN_SIM_CONFIG['cutoff_distance_m']
    candidates = np.flatnonzero((values[:-1] > cutoff) & (values[1:] <= cutoff))
    if not len(candidates):
        raise ValueError('Missing Zeeman crossing')
    i = candidates[-1]
    alpha = (values[i]-cutoff)/(values[i]-values[i+1])
    reconstructed = result.y[:, i]+alpha*(result.y[:, i+1]-result.y[:, i])
    np.testing.assert_allclose(reconstructed, state, rtol=1e-10, atol=1e-12)
    return float(result.t[i]+alpha*(result.t[i+1]-result.t[i]))


def write_stage(path, rows, survivors, survivor_ids, offsets, signature):
    arrays = {'survivors': np.asarray(survivors).reshape(-1, 6),
              'survivor_ids': np.asarray(survivor_ids, dtype=int),
              'offsets': np.asarray(offsets, dtype=float),
              'ids': np.asarray([row[0] for row in rows], dtype=int)}
    for atom_id, t, y in rows:
        arrays[f't_{atom_id}'], arrays[f'y_{atom_id}'] = t, y
    np.savez_compressed(path, **arrays)
    path.with_suffix('.json').write_text(json.dumps({'signature': signature, 'sha256': digest(path)}, indent=2)+'\n')


def load_stage(path, signature):
    meta = json.loads(path.with_suffix('.json').read_text())
    if meta['signature'] != signature or meta['sha256'] != digest(path):
        raise ValueError(f'Incompatible report cache: {path}')
    with np.load(path, allow_pickle=False) as d:
        rows = [(int(i), d[f't_{i}'], d[f'y_{i}']) for i in d['ids']]
        return rows, d['survivors'], d['survivor_ids'], d['offsets']


def simulate(n, workers):
    DATA.mkdir(parents=True, exist_ok=True)
    # Frozen settings already used for the report; do not alter live selections.
    report = ROOT/'data/validation/apparatus_report/trajectory.json'
    frozen = json.loads(report.read_text())
    p, profile = frozen['2d_parameters'], frozen['3d_profile']
    laser2d = {k: p[k] for k in ('s0', 'detuning_gamma')}
    laser2d['swap_polarization'] = False
    signature = {'n': n, 'seed': 713, 'report_settings_sha256': digest(report),
                 'zeeman_dt': zeeman_stage.ZEEMAN_SIM_CONFIG['dt_s'],
                 'mot2d_dt': mot2d_stage.MOT_2D_SIM_CONFIG['dt_s'],
                 'mot3d_dt': 1e-5, 'mot3d_tmax': .1,
                 'source_angular_cutoff_deg': zeeman_stage.COLLIMATION_ANGLE_DEG,
                 'method': 'production stochastic stage engines; continuous particle identities',
                 'script_sha256': digest(Path(__file__))}
    all_rows = []
    start = time.monotonic()
    path = DATA/f'chain_{n}_zeeman.npz'
    if not path.exists():
        results, survivors, ids = zeeman_stage.zeeman_simulation(
            N_particles=n, seed=713, npools=workers,
            magnet_radius=p['magnet_radius'], _2d_mot_config=laser2d)
        rows, offsets = [], []
        handoffs = {int(i): state for i, state in zip(ids, survivors)}
        for i, result in enumerate(results):
            if i in handoffs:
                end = crossing_time(result, handoffs[i])
                offsets.append(end)
                t, y = compact(result, handoffs[i], end)
            else:
                t, y = compact(result)
            rows.append((i, t, y))
        write_stage(path, rows, survivors, ids, offsets, signature)
        del results
    rows, survivors, ids, offsets = load_stage(path, signature)
    all_rows.extend(rows)
    print(f'Zeeman: {len(ids)}/{n}; elapsed {time.monotonic()-start:.1f}s', flush=True)
    path2 = DATA/f'chain_{n}_mot2d.npz'
    if not path2.exists():
        results, _, _ = mot2d_stage.mot_simulation(
            survivors, seed=714, npools=workers, magnet_radius=p['magnet_radius'], _2d_mot_config=laser2d)
        states2, _, local_ids = mot_extract_survivors(results)
        next_ids, next_offsets, rows = [], [], []
        for j, (i, offset, result) in enumerate(zip(ids, offsets, results)):
            if j in local_ids:
                k = local_ids.index(j)
                crossing = np.flatnonzero((result.y[2] >= Geometry.CAPTURE_MIN_Z_M) & (result.y[5] > 0))[0]
                end = float(result.t[crossing])
                t, y = compact(result, states2[k], end)
                next_ids.append(i); next_offsets.append(offset+end)
            else:
                t, y = compact(result)
            # Continuity must hold for the SAME particle across the handoff.
            np.testing.assert_allclose(y[0], survivors[j], rtol=1e-12, atol=1e-12)
            rows.append((int(i), t+offset, y))
        write_stage(path2, rows, states2, next_ids, next_offsets, signature)
        del results
    rows, states2, ids2, offsets2 = load_stage(path2, signature)
    all_rows.extend(rows)
    print(f'2D survivors: {len(ids2)}/{len(ids)}; elapsed {time.monotonic()-start:.1f}s', flush=True)
    path3 = DATA/f'chain_{n}_mot3d.npz'
    if not path3.exists():
        results = []
        if len(ids2):
            _, config = build_base_config(include_zeeman=True, include_2d_mot=True, include_3dmot=True,
                gravity_enabled=True, zones=get_entire_apparatus_zone(), magnet_radius=p['magnet_radius'],
                _2d_mot_config=laser2d, _3d_mot_config=profile)
            times, _ = generate_timepoints(.1, 1e-5)
            results, _ = run_multiple_atoms_simulation(config=config, u0=list(states2.copy()),
                time_points=times, sim_function=mot3d_stage._configured_3d_solver(), npools=workers, seed_idx=715)
        usable, usable_ids = [], []
        rows = []
        for j, (i, offset, result) in enumerate(zip(ids2, offsets2, results)):
            t, y = compact(result)
            np.testing.assert_allclose(y[0], states2[j], rtol=1e-12, atol=1e-12)
            if (t[-1] >= .1-1e-5 and np.linalg.norm(y[-1,:3]-profile['center_position_m']) <= .005
                    and np.linalg.norm(y[-1,3:]) <= 1.):
                usable.append(y[-1]); usable_ids.append(i)
            rows.append((int(i), t+offset, y))
        write_stage(path3, rows, usable, usable_ids, [], signature)
    rows, usable, usable_ids, _ = load_stage(path3, signature)
    all_rows.extend(rows)
    # Join only consecutive segments of the same atom, checking every seam.
    joined = []
    for i in range(n):
        segments = [(t,y) for atom_id,t,y in all_rows if atom_id==i]
        ts, ys = segments[0]
        for t,y in segments[1:]:
            np.testing.assert_allclose(ts[-1], t[0], rtol=0, atol=1e-10)
            np.testing.assert_allclose(ys[-1], y[0], rtol=1e-10, atol=1e-10)
            ts, ys = np.r_[ts,t[1:]], np.vstack([ys,y[1:]])
        joined.append((ts,ys))
    summary = {**signature, 'zeeman_survivors':len(ids), 'mot2d_survivors':len(ids2),
               'usable_at_3d_end':len(usable_ids), 'usable_ids':usable_ids.tolist(),
               'elapsed_seconds_this_invocation':time.monotonic()-start,
               'interpretation':'Illustrative angular-truncated source sample, not oven capture efficiency',
               'settings':frozen, 'stage_cache_sha256':{p.name:digest(p) for p in (path,path2,path3)}}
    (DATA/f'chain_{n}_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return joined, summary


def render(joined, summary, frames=180, end_ms=25.):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    p, profile = summary['settings']['2d_parameters'], summary['settings']['3d_profile']
    direction = -np.asarray(ZEEMAN_BEAM_DIRECTION)
    center = np.asarray(profile['center_position_m'])
    fig = plt.figure(figsize=(12,6.8), facecolor='white')
    # A tall axes box lets the physically long apparatus fill the GIF width;
    # its projected scene remains inside the canvas despite unused axes space.
    ax = fig.add_axes([0.,-.20,1.,1.4],projection='3d',computed_zorder=False)
    field = ZeemanSlowerField(angle_deg=Geometry.ZEEMAN_ARM_ANGLE_DEG, start_distance=Geometry.ZEEMAN_START_DISTANCE_M,
        radii=ZEEMAN_FIELD_CONFIG['radii_m'], positions_z=ZEEMAN_FIELD_CONFIG['positions_m'], tilt_angles=ZEEMAN_FIELD_CONFIG['tilt_angles_deg'])
    for source in field.collection.sources:
        magnet(ax,source)
    from lab_setup.mag_field_2d_mot import CustomQuadrupole
    for source in CustomQuadrupole(radius=p['magnet_radius']).collection.sources:
        magnet(ax,source,color='#b1a58f')
    cylinder(ax,-direction*.48,direction*.04,Geometry.ZEEMAN_LASER_WAIST_M,'#3985da',.12)
    for axis in (0,1):
        u=np.eye(3)[axis];cylinder(ax,-u*.065,u*.065,.005,'#3985da',.12)
    for _,u in _get_beam_directions(profile):
        u=np.asarray(u)
        for key,color in (('399','#3985da'),('556','#3ca65a')):
            cfg=profile[key]; cylinder(ax,center-u*.045,center,cfg['outer_cutoff_radius_m'],color,.18)
    for pos,label in ((-direction*.45,'Oven'),(-direction*.26,'Zeeman slower'),(np.zeros(3),'2D MOT'),(center,'3D MOT')):
        ax.text(pos[2]*1000,pos[1]*1000+20,pos[0]*1000+15,label,fontsize=10,color='#19363e')
    ax.set(xlabel='Lab z (mm)',ylabel='Lab y (mm)',zlabel='Lab x (mm)',
           xlim=(-450,470),ylim=(-240,90),zlim=(-80,80))
    ax.set_box_aspect((920,330,160),zoom=.95);ax.view_init(elev=28,azim=-76);ax.set_proj_type('ortho')
    ax.tick_params(labelsize=8,pad=0)
    for axis in (ax.xaxis,ax.yaxis,ax.zaxis):
        axis.set_pane_color((.97,.98,.98,1));axis._axinfo['grid'].update(color=(.65,.65,.65,.5),linewidth=.5)
    # Emission is staggered only for readability; no trajectory is rescaled.
    delays=np.random.default_rng(716).uniform(0,.006,len(joined))
    colors=plt.cm.plasma(np.linspace(.12,.9,len(joined)))
    trails=[ax.plot([],[],[],lw=1.2,alpha=.75,color=c,zorder=15)[0] for c in colors]
    dots=ax.scatter([],[],[],s=40,depthshade=False,edgecolors='white',linewidths=.4,zorder=20)
    closeup=fig.add_axes([.72,.67,.22,.22])
    closeup.set(xlim=(-8,8),ylim=(-8,8),xlabel='z offset (mm)',ylabel='y (mm)')
    closeup.set_aspect('equal');closeup.tick_params(labelsize=7)
    closeup.set_title('3D MOT · close-up',fontsize=10,color='#19363e')
    closeup.add_patch(plt.Circle((0,0),5,color='#3985da',alpha=.12))
    closeup.add_patch(plt.Circle((0,0),profile['556']['outer_cutoff_radius_m']*1000,color='#3ca65a',alpha=.3))
    closeup.grid(alpha=.15)
    zoom_dots=closeup.scatter([],[],s=28,edgecolors='white',linewidths=.4,zorder=5)
    clock=fig.text(.035,.94,'',fontsize=13,color='#19363e')
    fig.text(.5,.045,
             f"{len(joined)} stochastic atoms · {summary['zeeman_survivors']} passed Zeeman · "
             f"{summary['mot2d_survivors']} passed 2D MOT · {summary['usable_at_3d_end']} usable at 3D end\n"
             'Angular-truncated source sample; not an efficiency measurement. Schematic beam lengths.',
             ha='center',fontsize=9,color='#4b5c62')
    fig.suptitle('Ytterbium laser cooling · Oven to Blue shell',fontsize=17,color='#19363e',y=.99)
    times=np.linspace(0,end_ms/1000,frames)
    def update(k):
        now=times[k]; positions=[]; point_colors=[]; zoom_positions=[]; zoom_colors=[]
        for i,((t,y),delay,line) in enumerate(zip(joined,delays,trails)):
            local=now-delay
            if local<0 or local>t[-1]+.002:
                line.set_data_3d([],[],[]);continue
            sample=min(local,t[-1]); last=np.searchsorted(t,sample,side='right')
            first=max(0,np.searchsorted(t,sample-.0015)-1)
            xyz=y[first:last,:3]*1000
            line.set_data_3d(xyz[:,2],xyz[:,1],xyz[:,0])
            point=np.array([np.interp(sample,t,y[:,j]) for j in range(3)])*1000
            positions.append(point[[2,1,0]]);point_colors.append(colors[i])
            offset=point-center*1000
            if np.linalg.norm(offset)<.012*1000:
                zoom_positions.append(offset[[2,1]]);zoom_colors.append(colors[i])
        positions=np.asarray(positions).reshape(-1,3)
        dots._offsets3d=(positions[:,0],positions[:,1],positions[:,2]);dots.set_facecolor(point_colors)
        zoom_dots.set_offsets(np.asarray(zoom_positions).reshape(-1,2));zoom_dots.set_facecolor(zoom_colors)
        clock.set_text(f't = {now*1000:5.1f} ms')
        return [dots,zoom_dots,clock,*trails]
    animation=FuncAnimation(fig,update,frames=len(times),interval=65,blit=False)
    target=OUTPUT/f'11_oven_to_blue_shell_{len(joined)}_atoms.gif'
    animation.save(target,writer=PillowWriter(fps=15),dpi=100)
    update(int(frames*.5));fig.savefig(target.with_suffix('.png'),dpi=150)
    plt.close(fig)
    print(f'Saved {target}',flush=True)


def read_cached_chain(n):
    """Re-render verified, frozen trajectories without recomputing physics."""
    summary=json.loads((DATA/f'chain_{n}_summary.json').read_text())
    all_rows=[]
    for name,expected in summary['stage_cache_sha256'].items():
        path=DATA/name
        if digest(path)!=expected:raise ValueError(f'Changed trajectory data: {path}')
        signature=json.loads(path.with_suffix('.json').read_text())['signature']
        rows,_,_,_=load_stage(path,signature)
        all_rows.extend(rows)
    joined=[]
    for i in range(n):
        segments=[(t,y) for atom_id,t,y in all_rows if atom_id==i]
        ts,ys=segments[0]
        for t,y in segments[1:]:
            np.testing.assert_allclose(ts[-1],t[0],rtol=0,atol=1e-10)
            np.testing.assert_allclose(ys[-1],y[0],rtol=1e-10,atol=1e-10)
            ts,ys=np.r_[ts,t[1:]],np.vstack([ys,y[1:]])
        joined.append((ts,ys))
    return joined,summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--atoms',type=int,default=100)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--frames',type=int,default=180)
    parser.add_argument('--end-ms',type=float,default=25.,help='Last displayed laboratory time in milliseconds')
    parser.add_argument('--render-only',action='store_true',help='Use hash-verified existing trajectories; do not simulate')
    args=parser.parse_args()
    if not 1<=args.atoms<=300:parser.error('Use 1–300 atoms for this local illustration')
    if args.end_ms<=0:parser.error('--end-ms must be positive')
    joined,summary=read_cached_chain(args.atoms) if args.render_only else simulate(args.atoms,args.workers)
    print(json.dumps({k:summary[k] for k in ('zeeman_survivors','mot2d_survivors','usable_at_3d_end')}),flush=True)
    render(joined,summary,args.frames,args.end_ms)
