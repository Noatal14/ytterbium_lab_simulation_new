import type { ReactNode } from "react";
import { CircleCheck, CircleX, LockKeyhole } from "lucide-react";

type Props = {
  title: string;
  description: string;
  badge: string;
  readiness: "later-milestone" | "blocked";
  points: readonly ReactNode[];
  onStart?: () => void;
};

export function CampaignCard({ title, description, badge, readiness, points, onStart }: Props) {
  const blocked = readiness === "blocked";
  const actionId = `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-action-explanation`;
  return (
    <article className={`campaign-card${blocked ? " campaign-card--locked" : ""}`}>
      <div className="card-heading">
        <h3>{title}</h3>
        <span className="card-badge">{badge}</span>
      </div>
      <p>{description}</p>
      <ul>
        {points.map((point, index) => (
          <li key={index}>
            {!blocked ? <CircleCheck aria-hidden="true" /> : index ? <LockKeyhole aria-hidden="true" /> : <CircleX aria-hidden="true" />}
            <span>{point}</span>
          </li>
        ))}
      </ul>
      <div className="card-actions">
        <button type="button" className="primary-button" disabled={blocked || !onStart} aria-describedby={actionId} onClick={onStart}>
          {blocked ? `Start ${title}` : `Start ${title}`}
        </button>
        <p className="action-explanation" id={actionId}>
          {blocked ? "Complete and select a canonical 2D-MOT campaign first." : "Review every setting before creating local campaign files."}
        </p>
      </div>
    </article>
  );
}
