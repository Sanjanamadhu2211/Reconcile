import { useEffect } from "react";

const APP_NAME = "Reconcile";

export function documentTitleFor(title?: string) {
  return title ? `${title} · ${APP_NAME}` : APP_NAME;
}

export function useDocumentTitle(title?: string) {
  useEffect(() => {
    document.title = documentTitleFor(title);
  }, [title]);
}
