// The original photo or PDF behind a document, when the API stores one.
import { useEffect, useState } from "react";
import { rawContentUrl } from "../api/client";
import type { OrdoDocument } from "../api/types.gen";
import { Modal } from "./Modal";

export type Original = { kind: "image" | "pdf"; url: string };

/** The API answers a file it does not store with an SVG placeholder; that is not the original, so it is skipped. */
const kindOf = (type: string): Original["kind"] | null =>
  type.startsWith("image/") && !type.startsWith("image/svg") ? "image" : type === "application/pdf" ? "pdf" : null;

/** Tries the document's raw items in order and keeps the first photo or PDF. Null while loading or when none exists. */
export function useOriginal(d: OrdoDocument): Original | null {
  const [original, setOriginal] = useState<Original | null>(null);
  const ids = d.raw_item_ids.join(",");
  useEffect(() => {
    let alive = true;
    let objectUrl: string | null = null;
    setOriginal(null);
    void (async () => {
      for (const id of ids.split(",").filter(Boolean)) {
        const url = rawContentUrl(id);
        if (!url) return;
        try {
          const res = await fetch(url);
          const kind = res.ok ? kindOf(res.headers.get("content-type") ?? "") : null;
          if (!kind) continue;
          objectUrl = URL.createObjectURL(await res.blob());
          if (alive) setOriginal({ kind, url: objectUrl });
          return;
        } catch {
          /* try the next file */
        }
      }
    })();
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [ids]);
  return original;
}

/** The original, large, over the page. */
export function OriginalModal({ original, title, onClose }: { original: Original; title: string; onClose: () => void }) {
  return (
    <Modal title={title} onClose={onClose} wide>
      {original.kind === "image"
        ? <img className="original-large" src={original.url} alt={title} />
        : <iframe className="original-pdf" src={original.url} title={title} />}
      <a className="small" href={original.url} target="_blank" rel="noreferrer">Open in a new tab</a>
    </Modal>
  );
}
