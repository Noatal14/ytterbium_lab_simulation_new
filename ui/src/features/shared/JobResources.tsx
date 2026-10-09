export function JobResources({ job }: { job: { cores_per_task: number; memory_per_task_bytes: number; walltime_seconds: number } }) {
  return <>{job.cores_per_task} cores · {Math.round(job.memory_per_task_bytes / 1024 ** 3)} GB · {job.walltime_seconds / 3600} h</>;
}
