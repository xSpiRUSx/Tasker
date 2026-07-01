const ADVANCED_UI_KEY = "tasker_advanced_ui";

export function isAdvancedUiEnabled(): boolean {
  if (import.meta.env.VITE_TASKER_ADVANCED_UI === "true") {
    return true;
  }
  try {
    return window.localStorage.getItem(ADVANCED_UI_KEY) === "true";
  } catch {
    return false;
  }
}

export function setAdvancedUiEnabled(value: boolean): void {
  try {
    window.localStorage.setItem(ADVANCED_UI_KEY, value ? "true" : "false");
  } catch {
    // localStorage can be unavailable in restricted browser contexts.
  }
  window.dispatchEvent(new CustomEvent("tasker:advanced-ui-change", { detail: value }));
}
