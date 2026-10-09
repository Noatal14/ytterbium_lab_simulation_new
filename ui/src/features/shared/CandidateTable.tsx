type Candidate = { source: string; s0: number; rank: number; detuning_gamma: number; magnet_radius_m: number; mean_conditional_efficiency: number };

export function CandidateTable({ candidates, caption, estimateLabel }: { candidates: Candidate[]; caption: string; estimateLabel: string }) {
  return <div className="smoke-points" role="region" aria-label={caption} tabIndex={0}><table><caption>{caption}</caption><thead><tr><th scope="col">Fixed s₀</th><th scope="col">Rank</th><th scope="col">Detuning</th><th scope="col">Magnet radius</th><th scope="col">{estimateLabel}</th></tr></thead><tbody>{candidates.map((candidate) => <tr key={candidate.source}><td>{candidate.s0}</td><td>{candidate.rank}</td><td>{candidate.detuning_gamma.toFixed(3)} Γ</td><td>{(candidate.magnet_radius_m * 1000).toFixed(3)} mm</td><td>{new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 2 }).format(candidate.mean_conditional_efficiency)}</td></tr>)}</tbody></table></div>;
}
