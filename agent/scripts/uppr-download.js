/*
 * UPPR: make agent file downloads work inside the embedded iframe.
 *
 * The agent is embedded on a partner site (e.g. aiCruiter) via an iframe
 * on {slug}.uppr.online. Access is gated by UPPR Cloud's Caddy
 * forward_auth, authenticated by a host-only + Partitioned (CHIPS) embed
 * cookie. That cookie is keyed to the partner's top-level partition, so:
 *
 *   - subresource requests (fetch/XHR/WebSocket) the UI makes inside the
 *     iframe DO carry it — which is why the agent works at all; but
 *   - a *navigation* to a file URL (clicking a download link that loads a
 *     document, or opens a new tab) leaves that partition, so the cookie
 *     isn't sent, forward_auth can't authenticate the request, and the
 *     user is bounced to a login they can't complete inside the frame —
 *     landing on the partner's home page instead of the file.
 *
 * Fix: intercept download-style clicks and stream the file with a
 * same-origin fetch() (a subresource request, so the embed cookie IS
 * sent) into a Blob, then save it locally. Nothing navigates, so the
 * iframe stays put and the download just works — in every browser,
 * including under strict third-party-cookie blocking.
 *
 * Safe by construction:
 *   - only runs when embedded (a standalone, top-level agent is untouched,
 *     since its first-party cookie already rides normal navigations);
 *   - only same-origin, download-looking links;
 *   - if the server response is a normal HTML page (not an attachment),
 *     it lets the browser navigate as usual;
 *   - any failure falls back to the original navigation, so it can never
 *     make downloads worse than before.
 */
(function () {
  "use strict";

  // Idempotent: never install the handler twice, even if the script tag
  // ends up included more than once.
  if (window.__upprDownloadFixInstalled) return;
  window.__upprDownloadFixInstalled = true;

  // Only intervene inside an embedding iframe. Reference identity check;
  // safe to evaluate even when the top window is cross-origin.
  try {
    if (window.top === window.self) return;
  } catch (e) {
    // Cross-origin access threw — we ARE embedded; continue.
  }

  var FILE_EXT = /\.[a-z0-9]{1,8}$/i;
  var FILE_PATH = /\/(?:download|downloads|file|files|attachment|attachments|artifact|artifacts|media|export|exports|blob|blobs|raw)(?:\/|$)/i;

  // Markdown/punctuation debris that gets glued onto filenames when the
  // agent writes e.g. **CV.docx** and the webui linkifies the bold text:
  // the link's ?path= then ends in "**" and points at a file that doesn't
  // exist. Used to build a cleaned retry candidate after a 404.
  var TRAIL_DEBRIS = /[*`'"‘’“”)\]>,;:!?]+$/;

  // Return a URL with trailing debris stripped from the ?path= param and
  // the last path segment, or null when nothing changed.
  function cleanedVariant(url) {
    try {
      var u = new URL(url.href);
      var changed = false;
      var p = u.searchParams.get("path");
      if (p) {
        var np = p.replace(TRAIL_DEBRIS, "");
        if (np && np !== p) {
          u.searchParams.set("path", np);
          changed = true;
        }
      }
      var segs = u.pathname.split("/");
      var last = segs[segs.length - 1] || "";
      var nl = last.replace(TRAIL_DEBRIS, "");
      if (nl && nl !== last) {
        segs[segs.length - 1] = nl;
        u.pathname = segs.join("/");
        changed = true;
      }
      return changed ? u : null;
    } catch (e) {
      return null;
    }
  }

  function looksDownloadable(a, url) {
    if (a.hasAttribute("download")) return true;
    if (a.target === "_blank" || a.target === "_top" || a.target === "_parent") return true;
    var last = url.pathname.split("/").pop() || "";
    if (FILE_EXT.test(last)) return true;
    if (FILE_PATH.test(url.pathname)) return true;
    return false;
  }

  function filenameFrom(disposition, fallback) {
    if (disposition) {
      var star = /filename\*=(?:UTF-8'')?["']?([^"';]+)["']?/i.exec(disposition);
      if (star) {
        try { return decodeURIComponent(star[1]); } catch (e) { /* fall through */ }
      }
      var plain = /filename=["']?([^"';]+)["']?/i.exec(disposition);
      if (plain) return plain[1];
    }
    return fallback || "download";
  }

  function saveBlob(blob, name) {
    var objUrl = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = objUrl;
    link.download = name || "";
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(objUrl); }, 10000);
  }

  document.addEventListener(
    "click",
    function (ev) {
      // Respect other handlers and modified clicks (open-in-new-tab etc.).
      if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) {
        return;
      }

      var a = ev.target;
      while (a && a.nodeType === 1 && a.tagName !== "A") a = a.parentElement;
      if (!a || a.tagName !== "A") return;

      var raw = a.getAttribute("href");
      if (!raw || raw.charAt(0) === "#") return; // skip empty / in-page anchors

      var url;
      try {
        // a.href is the browser-resolved absolute URL (honours any <base>
        // tag and relative hrefs like "api/media?…"), so it matches exactly
        // what a normal click would have navigated to.
        url = new URL(a.href);
      } catch (e) {
        return;
      }
      if (url.protocol !== "http:" && url.protocol !== "https:") return;
      if (url.origin !== window.location.origin) return; // never touch external links
      if (!looksDownloadable(a, url)) return;

      var suggested = a.getAttribute("download") || url.pathname.split("/").pop() || "download";
      suggested = suggested.replace(TRAIL_DEBRIS, "") || suggested;

      ev.preventDefault();
      ev.stopPropagation();

      // Candidates in order: the link as-is, then (after a 404) the same
      // link with markdown debris stripped off the filename.
      var candidates = [url];
      var cleaned = cleanedVariant(url);
      if (cleaned) candidates.push(cleaned);

      var lastStatus = 0;

      function attempt(i) {
        if (i >= candidates.length) {
          if (lastStatus === 404) {
            // Genuinely missing file. Navigating would only paint the
            // backend's raw JSON 404 over the chat — tell the user instead.
            try { alert("Bestand niet gevonden: " + suggested); } catch (e) {}
            return;
          }
          // Auth/network-ish failure: fall back to a real navigation. The
          // cloud-side re-auth bounce can complete on a navigation (it
          // can't on a fetch), so this path can still save the download.
          window.location.href = (cleaned || url).href;
          return;
        }
        fetch(candidates[i].href, { credentials: "include" })
          .then(function (res) {
            if (!res.ok) {
              lastStatus = res.status;
              attempt(i + 1);
              return null;
            }
            var cd = res.headers.get("content-disposition") || "";
            var ct = res.headers.get("content-type") || "";
            // If the server didn't mean this as a file (plain HTML page,
            // no attachment), let the browser navigate normally instead.
            if (!/attachment/i.test(cd) && /text\/html/i.test(ct)) {
              window.location.href = candidates[i].href;
              return null;
            }
            var name = filenameFrom(cd, suggested);
            return res.blob().then(function (blob) { saveBlob(blob, name); });
          })
          .catch(function (err) {
            try { console.error("[uppr] blob download attempt failed:", err); } catch (e) {}
            lastStatus = 0; // network error, not an HTTP status
            attempt(i + 1);
          });
      }
      attempt(0);
    },
    true, // capture — run before the app's own click handlers
  );
})();
