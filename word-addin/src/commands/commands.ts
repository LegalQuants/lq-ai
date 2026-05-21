/**
 * Ribbon command handlers.
 *
 * M3-B1 scope: the manifest declares `OpenTaskPaneButton` which uses
 * `Action xsi:type="ShowTaskpane"` — Office.js handles the show-task-pane
 * action without needing a JS handler. The commands surface is reserved
 * for future feature work (M3-B4 skills, M3-B5 playbooks) that needs to
 * fire commands directly from the ribbon without opening the task pane.
 *
 * Office requires a registered handler for any `FunctionFile` reference;
 * we register a no-op handler so the file is shippable today. Feature
 * surfaces lands per [DE-287](docs/PRD.md).
 */

/* global Office */

Office.onReady(() => {
  // No commands wired in M3-B1. The manifest's only Control is a ShowTaskpane
  // button which Office handles natively without a JS handler.
});

// Office.js requires a global `associate` call for every named command in
// the manifest. The M3-B1 manifest doesn't declare any ExecuteFunction
// commands, but expose the API surface so future work can register handlers
// here without touching webpack config.
function noopCommand(event: Office.AddinCommands.Event): void {
  // Future commands write their behavior here. The event.completed() call
  // is mandatory — it signals Office that the command finished so the
  // ribbon button re-enables.
  event.completed();
}

// `Office.actions.associate` is the modern API; some Word desktop builds
// still look for a top-level binding. Both paths are defensive.
if (typeof Office !== "undefined" && Office.actions) {
  Office.actions.associate("noopCommand", noopCommand);
}
