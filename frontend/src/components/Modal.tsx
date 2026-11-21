import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { CloseButton } from "./ui";

export function Modal({ title, head, onClose, footer, children, wide }: {
  title: string; head?: ReactNode; onClose: () => void; footer?: ReactNode; children: ReactNode; wide?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    box.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      before?.focus?.();
    };
  }, [onClose]);
  return createPortal(
    <div className="modal-layer" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={box} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} className={`modal${wide ? " wide" : ""}`}>
        <div className="modal-head">
          <div className="stack grow" style={{ gap: 6 }}>
            {head}
            <h2>{title}</h2>
          </div>
          <CloseButton onClick={onClose} />
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function ModalSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="modal-section">
      <span className="label t3">{title}</span>
      {children}
    </section>
  );
}
