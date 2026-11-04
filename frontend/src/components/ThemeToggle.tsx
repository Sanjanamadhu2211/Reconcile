"use client";

import { useEffect, useState } from "react";
import { resolveTheme, type Theme } from "@/lib/theme";

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => {
      let saved: string | null = null;
      try {
        saved = localStorage.getItem("reconcile-theme");
      } catch {
        /* Storage is optional. */
      }
      const next = resolveTheme(saved, media.matches);
      document.documentElement.dataset.theme = next;
      setTheme(next);
    };
    update();
    media.addEventListener("change", update);
    window.addEventListener("storage", update);
    return () => {
      media.removeEventListener("change", update);
      window.removeEventListener("storage", update);
    };
  }, []);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try {
      localStorage.setItem("reconcile-theme", next);
    } catch {
      /* Keep the current session usable. */
    }
  }

  return (
    <button className="theme-toggle" type="button" onClick={toggle} disabled={!theme}>
      {theme === "dark" ? "Light mode" : "Dark mode"}
    </button>
  );
}
