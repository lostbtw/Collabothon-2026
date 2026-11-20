import type { ControlLevel, ExecutionMode } from "../api/types.gen";
import { StatusLabel } from "./ui";

/** The control level in plain words, plus SIMULATED when the action would run against the sandbox bank. */
export function ControlBadges({ level, execution }: { level: ControlLevel; execution?: ExecutionMode }) {
  return (
    <span className="hstack">
      <StatusLabel level={level} />
      {execution === "simulated" && <span className="simulated">SIMULATED</span>}
    </span>
  );
}
