import { afterEach, describe, expect, it, vi } from 'vitest';
import { createIndividualZeemanApi } from '../api/clients/individualZeeman';
import { createIndividualMot2DApi } from '../api/clients/individualMot2D';
import { createIndividualMot3DApi } from '../api/clients/individualMot3D';
const clients = [['zeeman',createIndividualZeemanApi],['mot_2d',createIndividualMot2DApi],['mot_3d',createIndividualMot3DApi]] as const;
function summary(family: string, scheduled?: unknown) {
  return {id:'individual-run-'+'a'.repeat(24),record_kind:'individual_simulation_run',run_kind:family,
    display_name:({zeeman:'zeeman-queued',mot_2d:'mot2d-queued',mot_3d:'mot3d-queued'}[family]||'invalid'),stage_semantics:'single-run-lifecycle',source:'local',
    queried_at:'2026-10-20T19:00:00+00:00',trust:'verified-package',scientific_role:'individual-only',
    record_state:'configured',integrity:'active',lifecycle:'configured',next_action:scheduled===true?'wait':'none',
    created_at:'2026-10-20T19:00:00+00:00',updated_at:'2026-10-20T19:00:00+00:00',
    execution:{mode:'local',zeus_job_id:null,...(scheduled===undefined?{}:{locally_scheduled:scheduled})},
    retention:{particle_states_requested:false,status:'pending'},results:{availability:'not_ready',completed_at:null},warnings:[]};
}
function respond(row: unknown) {vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({api_version:1,data:{runs:[row],invalid_count:0,total:1,truncated:false}}),{status:200,headers:{'Content-Type':'application/json'}})));}
afterEach(()=>vi.unstubAllGlobals());
for(const [family,create] of clients) describe(family+' process-owned queue observation',()=>{
  it('defaults absent legacy observation to false',async()=>{
    respond(summary(family));const [row]=await create(async()=>'csrf').runs();
    expect(row.execution.locally_scheduled).toBe(false);expect(row.record_state).toBe('configured');
  });
  it('accepts observed configured rows without inventing canonical queued state',async()=>{
    respond(summary(family,true));const [row]=await create(async()=>'csrf').runs();
    expect(row.execution.locally_scheduled).toBe(true);expect(row.record_state).toBe('configured');
  });
  it.each([null,0,1,'true'])('rejects nonboolean observation %s',async(value)=>{
    respond(summary(family,value));await expect(create(async()=>'csrf').runs()).rejects.toThrow();
  });
  it('rejects scheduling claimed for Zeus',async()=>{
    const row=summary(family,true);row.execution.mode='zeus';respond(row);await expect(create(async()=>'csrf').runs()).rejects.toThrow();
  });
  it('rejects scheduling claimed for terminal records',async()=>{
    const row=summary(family,true);Object.assign(row,{record_state:'cancelled',lifecycle:'cancelled',integrity:'terminal_without_results'});respond(row);
    await expect(create(async()=>'csrf').runs()).rejects.toThrow();
  });
  it('rejects an observed queue paired with a none action',async()=>{
    const row=summary(family,true);row.next_action='none';respond(row);await expect(create(async()=>'csrf').runs()).rejects.toThrow();
  });
});
