import { composerDraftAtom, stickyDirtyAtom, stickyEnabledAtom, store } from "@/store";
import { notifications } from "@mantine/notifications";

let checkForClipboardAccess = () => {
  const isOfficeOnline =
    typeof Office !== "undefined" &&
    Office.context?.platform === Office.PlatformType?.OfficeOnline;
  const hasClipboard =
    !isOfficeOnline &&
    typeof navigator !== "undefined" &&
    typeof navigator.clipboard !== "undefined" &&
    typeof navigator.clipboard.write === "function" &&
    typeof ClipboardItem !== "undefined";
  return hasClipboard
}

export let actions = {

  setComposerDraft(text: string) {
    store.set(composerDraftAtom, text);
  },

  toggleSticky(): void {
    store.set(stickyEnabledAtom, (prev) => !prev);
    store.set(stickyDirtyAtom, true);
  },

  showNotification(
    title: string = "",
    message: React.ReactNode = "",
    autoClose: number | false = 5000
  ) {
    notifications.show({
      title,
      message,
      autoClose,
      color: "var(--mantine-color-sage-6)",
      style: { border: "var(--mantine-color-sage-6)" },
    });
  },

  showErrorNotification(
    title: string = "",
    message: React.ReactNode = "",
    autoClose: number | false = 5000
  ) {
    notifications.show({
      title,
      message,
      autoClose,
      color: "red",
      style: { border: "var(--mantine-color-red-6)" },
    });
  },

  openExternalLink(url: string) {
    try {
      if (typeof Office !== "undefined" && Office?.context?.ui?.openBrowserWindow) {
        Office.context.ui.openBrowserWindow(url);
        return;
      }
    } catch (error) {
      console.warn("Failed to open external URL via Office API", error);
    }
    if (typeof window !== "undefined") {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  },

  async copyToClipboard (text: string) {
    const hasClipboard = checkForClipboardAccess()
    

    if (!hasClipboard) {
      this.showErrorNotification("Error", "Clipboard is Unavailable");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      this.showErrorNotification("Error", "Unable to Copy to Clipboard");
    }
    return;
  },

  async copyHtmlToClipboard (text: string) {
    const plainText =
      typeof document !== "undefined"
        ? (() => {
            const container = document.createElement("div");
            container.innerHTML = text;
            return container.textContent ?? container.innerText ?? text;
          })()
        : text;
    try {
      const htmlBlob = new Blob([text], { type: "text/html" });
      const textBlob = new Blob([plainText], { type: "text/plain" });
      const item = new ClipboardItem({ "text/html": htmlBlob, "text/plain": textBlob });
      await navigator.clipboard.write([item]);
    } catch {
      this.showErrorNotification("Error", "Unable to Copy to Clipboard");
    }

  }

};



 