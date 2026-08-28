/*
 * rgsplus-chat.js — drop-in helpdesk chat launcher for the RGS+ application.
 *
 *   <script src="/widget/rgsplus-chat.js"
 *           data-agent-url="https://agent.rgsplus.nl"
 *           data-title="RGS+ Helpdesk"
 *           defer></script>
 *
 * Renders a launcher button bottom-right and, on click, a panel containing an
 * iframe of the agent UI. No dependencies, no globals beyond window.RGSPlusChat,
 * no styles leaked into the host page (everything lives in a shadow root, so
 * RGS+'s own CSS and this widget cannot affect each other).
 *
 * The agent container must allow being framed by the RGS+ origin — set
 * EMBED_FRAME_ANCESTORS in the deployment's .env. Without it the browser
 * blocks the iframe and the panel stays blank.
 *
 * data- attributes, all optional except data-agent-url:
 *   data-agent-url   required. Origin serving the agent UI.
 *   data-title       panel header text.        default "Helpdesk"
 *   data-accent      launcher/header colour.   default #2f80ed
 *   data-position    left | right.             default right
 *   data-open        "true" opens on load.     default false
 *   data-z-index     stacking context.         default 2147483000
 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script) return;

  var config = {
    agentUrl: (script.dataset.agentUrl || "").replace(/\/+$/, ""),
    title: script.dataset.title || "Helpdesk",
    accent: script.dataset.accent || "#2f80ed",
    position: script.dataset.position === "left" ? "left" : "right",
    openOnLoad: script.dataset.open === "true",
    zIndex: script.dataset.zIndex || "2147483000",
  };

  if (!config.agentUrl) {
    console.error("[rgsplus-chat] data-agent-url is required; widget not started.");
    return;
  }

  var STYLES = [
    ":host { all: initial; }",
    ".root { position: fixed; bottom: 20px; " + config.position + ": 20px;",
    "  z-index: " + config.zIndex + ";",
    "  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; }",

    ".launcher { width: 56px; height: 56px; border-radius: 50%; border: 0;",
    "  background: " + config.accent + "; color: #fff; cursor: pointer;",
    "  display: flex; align-items: center; justify-content: center;",
    "  box-shadow: 0 4px 16px rgba(0,0,0,.24); transition: transform .15s ease; }",
    ".launcher:hover { transform: scale(1.06); }",
    ".launcher:focus-visible { outline: 3px solid #fff; outline-offset: 2px; }",
    ".launcher svg { width: 26px; height: 26px; fill: currentColor; }",

    ".panel { position: absolute; bottom: 72px; " + config.position + ": 0;",
    "  width: 400px; height: 620px; max-width: calc(100vw - 40px);",
    "  max-height: calc(100vh - 120px);",
    "  background: #fff; border-radius: 12px; overflow: hidden;",
    "  box-shadow: 0 12px 48px rgba(0,0,0,.28);",
    "  display: none; flex-direction: column; }",
    ".panel[data-open='true'] { display: flex; }",

    ".header { display: flex; align-items: center; justify-content: space-between;",
    "  padding: 12px 16px; background: " + config.accent + "; color: #fff;",
    "  font-size: 15px; font-weight: 600; flex: 0 0 auto; }",
    ".close { background: none; border: 0; color: #fff; cursor: pointer;",
    "  font-size: 22px; line-height: 1; padding: 0 4px; }",
    ".close:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }",

    ".frame { flex: 1 1 auto; width: 100%; border: 0; }",

    // Full-screen on phones: a 400px panel on a 360px viewport is unusable.
    "@media (max-width: 480px) {",
    "  .panel { position: fixed; inset: 0; width: 100vw; height: 100dvh;",
    "    max-width: none; max-height: none; border-radius: 0; }",
    "}",
  ].join("\n");

  var host = document.createElement("div");
  host.setAttribute("data-rgsplus-chat", "");
  var shadow = host.attachShadow({ mode: "open" });

  var style = document.createElement("style");
  style.textContent = STYLES;

  var root = document.createElement("div");
  root.className = "root";
  root.innerHTML = [
    '<div class="panel" part="panel" data-open="false" role="dialog" aria-modal="false" aria-label="' +
      escapeAttr(config.title) + '">',
    '  <div class="header"><span>' + escapeHtml(config.title) + "</span>",
    '    <button class="close" type="button" aria-label="Sluiten">&times;</button>',
    "  </div>",
    "</div>",
    '<button class="launcher" type="button" aria-expanded="false" aria-label="' +
      escapeAttr(config.title) + ' openen">',
    '  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 2H4a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2z"/></svg>',
    "</button>",
  ].join("\n");

  shadow.append(style, root);

  var panel = root.querySelector(".panel");
  var launcher = root.querySelector(".launcher");
  var closeButton = root.querySelector(".close");
  var frame = null;

  function open() {
    // Lazy: the iframe is only created on first open, so the widget costs the
    // host page nothing until someone actually asks for help.
    if (!frame) {
      frame = document.createElement("iframe");
      frame.className = "frame";
      frame.src = config.agentUrl;
      frame.title = config.title;
      frame.setAttribute("allow", "clipboard-write");
      panel.appendChild(frame);
    }
    panel.dataset.open = "true";
    launcher.setAttribute("aria-expanded", "true");
    closeButton.focus();
  }

  function close() {
    panel.dataset.open = "false";
    launcher.setAttribute("aria-expanded", "false");
    launcher.focus();
  }

  function toggle() {
    panel.dataset.open === "true" ? close() : open();
  }

  launcher.addEventListener("click", toggle);
  closeButton.addEventListener("click", close);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && panel.dataset.open === "true") close();
  });

  function mount() {
    document.body.appendChild(host);
    if (config.openOnLoad) open();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  // Small API so the RGS+ app can open the widget from its own "Hulp nodig?"
  // buttons instead of relying on the launcher.
  window.RGSPlusChat = { open: open, close: close, toggle: toggle };

  function escapeHtml(value) {
    return String(value).replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/"/g, "&quot;");
  }
})();
