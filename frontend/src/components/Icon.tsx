const PATHS = {
  home: "M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z",
  inbox: "M4 13.5 6.2 6h11.6L20 13.5V18a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1zM4 13.5h4.5a3.5 3.5 0 0 0 7 0H20",
  file: "M7 3.5h7l4 4V19.5a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1zM14 3.5v4h4M9 12.5h6M9 16h6",
  swap: "M4 8.5h15M15.5 5l3.5 3.5L15.5 12M20 15.5H5M8.5 12 5 15.5 8.5 19",
  book: "M5 4.5h12a2 2 0 0 1 2 2V20H7a2 2 0 0 1-2-2zM5 18a2 2 0 0 1 2-2h12M9 8.5h6",
  plug: "M9 3.5v4M15 3.5v4M6.5 7.5h11v3a5.5 5.5 0 0 1-11 0zM12 16v4.5",
  pulse: "M3.5 12.5h4l2.5-7 4 13 2.5-6h4",
  chat: "M5 5h14a1 1 0 0 1 1 1v9.5a1 1 0 0 1-1 1h-7L7.5 20v-3.5H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z",
  search: "M10.5 17a6.5 6.5 0 1 1 0-13 6.5 6.5 0 0 1 0 13zM15.5 15.5 20 20",
  chevron: "m7 10 5 5 5-5",
  drop: "M12 3.5s6 6.3 6 10.5a6 6 0 0 1-12 0c0-4.2 6-10.5 6-10.5z",
  shield: "M12 3.5 19 6v5.5c0 4.3-2.9 7.5-7 9-4.1-1.5-7-4.7-7-9V6z",
  percent: "M18.5 5.5 5.5 18.5M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM16 17.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z",
  user: "M12 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM5.5 19.5a6.5 6.5 0 0 1 13 0",
} as const;

export type IconName = keyof typeof PATHS;

/** Line icons drawn on a 24px grid; decorative, so hidden from screen readers. */
export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  );
}
