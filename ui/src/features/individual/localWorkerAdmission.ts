/** Advisory form limit; the backend independently enforces its actual host budget. */
export function localWorkerMaximum(
  particleCount: number,
  maximum = 256,
  availableCpus = typeof navigator === "undefined"
    ? 1
    : navigator.hardwareConcurrency,
): number {
  const cpus =
    Number.isInteger(availableCpus) && availableCpus > 0 ? availableCpus : 1;
  const particles =
    Number.isInteger(particleCount) && particleCount > 0
      ? particleCount
      : maximum;
  return Math.min(maximum, cpus, particles);
}
