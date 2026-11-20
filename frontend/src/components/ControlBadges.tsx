import type { ControlLevel, ExecutionMode } from "../api/types.gen";

const LEVEL_LABEL: Record<ControlLevel, string> = {
  analysed_autonomously: "Done on its own",
  recommendation: "Recommendation",
  approval_required: "Needs your approval",
};

/** The control-level badge, plus "Simulated" when the action would run against the sandbox. */
export function ControlBadges({ level, execution }: { level: ControlLevel; execution?: ExecutionMode }) {
  return (
    <div className="badges">
      <span className={`badge ${level}`}>{LEVEL_LABEL[level]}</span>
      {execution === "simulated" && <span className="badge simulated">Simulated</span>}
    </div>
  );
}
