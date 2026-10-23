import { exactKeys } from "../schema/common";

export type Mot3DFamilyJob = { id:"angled_donut"|"single_pass";array_job_id:string|null;merge_job_id:string|null };
export type Mot3DFamilyChain = { dependency:"afterok within each family";families:[Mot3DFamilyJob,Mot3DFamilyJob] };
const ARRAY_JOB=/^\d+\[\]\.zeus-master$/;const SCALAR_JOB=/^\d+\.zeus-master$/;
const object=(value:unknown,keys:string[])=>{if(!value||typeof value!=="object"||Array.isArray(value)||!exactKeys(value as Record<string,unknown>,keys))throw new Error("Invalid 3D-MOT family job chain.");return value as Record<string,unknown>};
export function parseMot3DFamilyChain(value:unknown):Mot3DFamilyChain{const row=object(value,["dependency","families"]);if(row.dependency!=="afterok within each family"||!Array.isArray(row.families)||row.families.length!==2)throw new Error("Invalid 3D-MOT family job chain.");const families=row.families.map((entry,index)=>{const family=object(entry,["id","array_job_id","merge_job_id"]);if(family.id!==["angled_donut","single_pass"][index]||(family.array_job_id!==null&&(typeof family.array_job_id!=="string"||!ARRAY_JOB.test(family.array_job_id)))||(family.merge_job_id!==null&&(typeof family.merge_job_id!=="string"||!SCALAR_JOB.test(family.merge_job_id))||(family.merge_job_id!==null&&family.array_job_id===null)))throw new Error("Invalid 3D-MOT family job chain.");return family as Mot3DFamilyJob});const numeric=families.flatMap(f=>[f.array_job_id,f.merge_job_id]).filter((job):job is string=>job!==null).map(job=>job.match(/^\d+/)![0]);if(new Set(numeric).size!==numeric.length)throw new Error("Invalid 3D-MOT family job chain.");return{dependency:"afterok within each family",families:families as [Mot3DFamilyJob,Mot3DFamilyJob]}}
export const mot3DFamilyJobCount=(chain:Mot3DFamilyChain)=>chain.families.reduce((count,family)=>count+Number(family.array_job_id!==null)+Number(family.merge_job_id!==null),0);
export const isMot3DFamilyCanonicalPrefix=(chain:Mot3DFamilyChain)=>{const present=chain.families.flatMap(f=>[f.array_job_id!==null,f.merge_job_id!==null]);const count=present.filter(Boolean).length;return present.every((value,index)=>value===(index<count))};

/** JSON member order is irrelevant; family order, keys, and exact topology remain closed. */
export function isMot3DSubmissionFamilyTopology(value: unknown): boolean {
  return Array.isArray(value) && value.length === 2 && value.every((entry, index) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return false;
    const row = entry as Record<string, unknown>;
    return exactKeys(row, ["id", "array_tasks", "merge_jobs"])
      && row.id === ["angled_donut", "single_pass"][index]
      && row.array_tasks === 3 && row.merge_jobs === 1;
  });
}
