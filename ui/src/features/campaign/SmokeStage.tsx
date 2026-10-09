import type { SmokePoint } from "../../api/clients/smoke";

export function SmokePointsTable({ points }: { points: SmokePoint[] }) {
  return <div className="smoke-points" role="region" aria-label="Validated smoke points" tabIndex={0}><table><caption>Validated smoke points</caption><thead><tr><th scope="col">Fixed s₀</th><th scope="col">Captured</th><th scope="col">Efficiency</th></tr></thead><tbody>{points.map((point) => <tr key={point.s0}><td>{point.s0}</td><td>{point.captured} of {point.input}</td><td>{new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 1 }).format(point.efficiency)}</td></tr>)}</tbody></table></div>;
}
