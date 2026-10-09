import type { RefinementChainStatus } from "../../api/clients/refinement";

const words = (value: string) => value.replaceAll("_", " ").replaceAll("-", " ");
export function RefinementReceipt({ status }: { status: RefinementChainStatus }) {
  return <ol className="chain-rounds" aria-label="Refinement submission rounds">{status.chain.rounds.map((round) => <li key={round.round}><strong>Round {round.round}</strong><span>{words(round.state)}</span>{round.job_id && <code>{round.job_id}</code>}{round.depends_on_job_id && <small>afterok {round.depends_on_job_id}</small>}</li>)}</ol>;
}
