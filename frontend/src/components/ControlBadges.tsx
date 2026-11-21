import type { ControlLevel, ExecutionMode } from "../api/types.gen";
import { StatusLabel } from "./ui";

/** The control level in plain words. That every action is simulated is said once, in the sidebar. */
export function ControlBadges({ level }: { level: ControlLevel; execution?: ExecutionMode }) {
  return (
    <span className="hstack">
      <StatusLabel level={level} />
    </span>
  );
}
