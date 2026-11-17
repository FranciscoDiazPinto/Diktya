import { useCallback, useEffect, useRef, useState } from "react";

// A non-modal disclosure on small screens, a permanent sidebar on desktop.
export function useMobileNavigation() {
  const [small, setSmall] = useState(
    () => window.matchMedia?.("(max-width: 700px)").matches ?? false,
  );
  const [open, setOpen] = useState(false);
  const sidebar = useRef(null),
    trigger = useRef(null),
    closeButton = useRef(null);
  const close = useCallback((restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) trigger.current?.focus();
  }, []);
  useEffect(() => {
    const media = window.matchMedia?.("(max-width: 700px)");
    if (!media) return;
    const change = () => {
      if (media.matches && sidebar.current?.contains(document.activeElement))
        trigger.current?.focus();
      setSmall(media.matches);
      setOpen(false);
    };
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    if (
      !small &&
      (document.activeElement === closeButton.current ||
        document.activeElement === trigger.current)
    ) {
      sidebar.current?.querySelector('[aria-current="page"]')?.focus();
    }
  }, [small]);
  useEffect(() => {
    if (!small || !open) return;
    closeButton.current?.focus();
    const escape = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    const outside = (event) => {
      if (
        !sidebar.current?.contains(event.target) &&
        !trigger.current?.contains(event.target)
      )
        close(false);
    };
    document.addEventListener("keydown", escape);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    return () => {
      document.removeEventListener("keydown", escape);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
    };
  }, [small, open, close]);
  return {
    small,
    open,
    sidebar,
    trigger,
    closeButton,
    close,
    toggle: () => setOpen((value) => !value),
  };
}
