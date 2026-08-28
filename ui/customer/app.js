/* Sam — customer surface.
 *
 * Renders the seven `state` values the bridge returns (see
 * bridge/app/schemas.py). Vanilla JS, no build step, matching the rest of the
 * project.
 *
 * ── The one rule this file exists to enforce ──────────────────────────────
 * `unknown` and `kb_unreachable` render DIFFERENTLY and must never be merged.
 *   unknown         the manual was read and has no answer  → offer escalation
 *   kb_unreachable  the manual could not be read at all    → banner + retry
 * Collapsing them tells a customer their question is undocumented when in
 * fact our Atlassian credentials broke, and sends them chasing a
 * documentation gap that does not exist.
 *
 * ── Trust boundary ───────────────────────────────────────────────────────
 * This file must NOT hold BRIDGE_API_KEY. The bearer token authenticates the
 * RGS+ *application*, not the end user, so `user.role` is only meaningful
 * when RGS+'s own backend makes the call. Point `apiUrl` at an RGS+ endpoint
 * that attaches identity server-side and proxies to the bridge. Calling the
 * bridge straight from the browser would let a user set their own role.
 */
(function () {
  "use strict";

  var cfg = Object.assign({
    apiUrl: "/api/sam/chat",   // RGS+ backend proxy → bridge POST /v1/chat
    context: {},               // { screen, version }
    user: {},                  // { name, email, organisation, role, licence }
    logoUrl: "../assets/rgsplus-logo.svg"
  }, window.SAM_CONFIG || {});

  var sessionId = null;
  var busy = false;

  var thread = document.getElementById("thread");
  var form = document.getElementById("composer");
  var input = document.getElementById("input");
  var send = document.getElementById("send");
  var counter = document.getElementById("count");
  var MAX = 8000;                     // matches ChatRequest.message max_length

  /* ---------- helpers ---------- */

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;   // textContent, never innerHTML
    return n;
  }

  function add(node) {
    thread.appendChild(node);
    thread.scrollTop = thread.scrollHeight;
    return node;
  }

  /* Minimal, safe markdown.
   *
   * The agent replies in markdown — **bold**, `code`, - lists, [text](url).
   * Rendering that with textContent shows the asterisks and backticks raw,
   * which is what shipped first and looked broken. Rendering it with innerHTML
   * would let a customer's pasted text inject markup, and evals/helpdesk-nl.txt
   * has two prompt-injection cases precisely because people paste hostile text
   * in here.
   *
   * So: parse a small, fixed subset and BUILD NODES. No innerHTML anywhere,
   * so nothing in a reply can become live markup. Anything unrecognised falls
   * through as plain text rather than being dropped. */
  function inlineMd(host, text) {
    // Order matters. `code` is tested FIRST because the agent writes things
    // like `**m.rgsplus.nl**` — backticks wrapping bold. Matching bold first
    // consumed the inner **…** and left the backticks stranded as literal
    // characters on screen, which is exactly how this looked when first shipped.
    // Emphasis markers inside a code span are stripped rather than rendered.
    //   `code` · [label](url) · **bold** · *italic*
    var re = /(`([^`]+)`)|(\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))|(\*\*([^*]+)\*\*)|(\*([^*\n]+)\*)/;
    var m;
    while ((m = re.exec(text))) {
      if (m.index) host.appendChild(document.createTextNode(text.slice(0, m.index)));
      if (m[2] != null) {
        host.appendChild(el("code", "md-code", m[2].replace(/\*\*?/g, "")));
      } else if (m[4] != null) {
        var a = el("a", "md-link", m[4]);
        a.href = m[5];
        a.target = "_blank";
        a.rel = "noopener noreferrer";   // never expose window.opener
        host.appendChild(a);
      } else if (m[7] != null) {
        host.appendChild(el("strong", null, m[7]));
      } else {
        host.appendChild(el("em", null, m[9]));
      }
      text = text.slice(m.index + m[0].length);
    }
    if (text) host.appendChild(document.createTextNode(text));
  }

  function renderMarkdown(host, raw) {
    var lines = String(raw == null ? "" : raw).split("\n");
    var list = null;
    lines.forEach(function (line) {
      var trimmed = line.trim();

      // Horizontal rules are document furniture; a chat bubble does not need them.
      if (/^(---+|\*\*\*+|___+)$/.test(trimmed)) { list = null; return; }

      // Headings: the agent occasionally emits "## Antwoord". Keep the words,
      // drop the heading — this is a reply, not a document.
      var h = trimmed.match(/^#{1,6}\s+(.*)$/);
      if (h) {
        list = null;
        var p = el("p", "md-p");
        inlineMd(p, h[1]);
        host.appendChild(p);
        return;
      }

      var li = trimmed.match(/^[-*+]\s+(.*)$/) || trimmed.match(/^(\d+)\.\s+(.*)$/);
      if (li) {
        if (!list) { list = el("ul", "md-list"); host.appendChild(list); }
        var item = el("li");
        inlineMd(item, li.length === 3 ? li[2] : li[1]);
        list.appendChild(item);
        return;
      }

      list = null;
      if (!trimmed) return;
      var para = el("p", "md-p");
      inlineMd(para, trimmed);
      host.appendChild(para);
    });
  }

  function bubble(text, kind) {
    var wrap = el("div", "msg msg--" + kind);
    var b = el("div", "msg__bubble");
    if (kind === "user") {
      b.textContent = text;              // never interpret what a customer typed
    } else {
      renderMarkdown(b, text);
    }
    wrap.appendChild(b);
    add(wrap);
    return b;
  }

  /* ---------- rendering ---------- */

  function renderCitations(host, citations) {
    if (!citations || !citations.length) return;
    var box = el("div", "cites");
    box.appendChild(el("span", "cites__label", "Bron:"));
    citations.forEach(function (c) {
      if (!c || !c.title || !c.url) return;   // a citation you can't open isn't one
      var a = el("a", "cite", c.title);
      a.href = c.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      if (c.excerpt) a.title = c.excerpt;
      box.appendChild(a);
    });
    if (box.children.length > 1) host.appendChild(box);
  }

  function renderBanner(kind, title, body, actionLabel, onAction) {
    var b = el("div", "banner banner--" + kind);
    b.setAttribute("role", kind === "warn" ? "alert" : "status");
    b.appendChild(el("p", "banner__title", title));
    b.appendChild(el("p", null, body));
    if (actionLabel) {
      var btn = el("button", "banner__action", actionLabel);
      btn.type = "button";
      btn.addEventListener("click", onAction);
      b.appendChild(btn);
    }
    add(b);
  }

  /* The escalation card.
   *
   * Ticket creation is a DRY RUN — the agent prepares a draft and a human
   * files it. So this is a thing the user CONFIRMS. The user presses the
   * button; the agent never decides to. That distinction is the whole reason
   * this does not violate "agent mag niets aanmaken", and the UI is where it
   * becomes visible rather than argued about.
   *
   * No ticket key and no turnaround time are shown, because none exists. */
  function renderDraft(draft) {
    var card = el("div", "draft");
    card.appendChild(el("div", "draft__head", "Dit stuur ik door naar de helpdesk"));

    var body = el("div", "draft__body");
    body.appendChild(el("label", "draft__label", "Onderwerp"));
    var summary = el("input", "draft__summary");
    summary.type = "text";
    summary.value = draft.summary || "";
    summary.id = "draft-summary";
    body.appendChild(summary);

    if (draft.description) {
      var det = el("details", "draft__more");
      det.appendChild(el("summary", null, "Wat ik meestuur"));
      det.appendChild(el("pre", null, draft.description));
      body.appendChild(det);
    }
    card.appendChild(body);

    var foot = el("div", "draft__foot");
    var cancel = el("button", "btn btn--ghost", "Annuleren");
    var confirm = el("button", "btn btn--primary", "Versturen");
    cancel.type = confirm.type = "button";
    foot.appendChild(cancel);
    foot.appendChild(confirm);
    card.appendChild(foot);
    add(card);

    cancel.addEventListener("click", function () { card.remove(); });
    confirm.addEventListener("click", function () {
      card.remove();
      // Deliberately no ticket number and no SLA: the draft still has to be
      // filed by a person. If nobody empties .jira-dryrun/, this sentence is
      // a lie — see docs/CLIENT-CONTEXT.md §11.
      renderBanner("info", "Doorgestuurd",
        "Een collega van de helpdesk pakt dit op en neemt contact met je op.");
    });
  }

  function renderAnswer(data) {
    var state = data.state || "answer";
    var text = data.reply || "";

    if (state === "kb_unreachable") {
      renderBanner("warn", "Ik kan de handleiding nu niet bereiken",
        text || "Er is een storing in de verbinding met onze kennisbank. Dit ligt niet aan " +
                "je vraag. Probeer het zo nog eens, of neem contact op met de helpdesk.",
        "Opnieuw proberen", function () { resend(); });
      return;
    }

    if (state === "safety") {
      renderBanner("warn", "Let op — gevoelige gegevens",
        text || "Je bericht lijkt inloggegevens of persoonsgegevens te bevatten. " +
                "Wijzig je wachtwoord voor de zekerheid. Ik neem deze gegevens niet " +
                "over in een ticket.");
      return;
    }

    var b = bubble(text, state === "clarify" ? "clarify" : "bot");
    renderCitations(b, data.citations);

    // state=answer with no citations means the model answered without
    // grounding itself in a page. Say so rather than let it pass as sourced.
    // Only flag genuinely unsourced answers. Practice answers cite the helpdesk
    // in prose and have no URL to link; greetings need no source at all. Warning
    // on those trains people to ignore the warning.
    var saysSource = /volgens de helpdesk|bron:|handleiding|kennisbank|faq/i.test(text);
    var substantial = text.length > 180;
    if (state === "answer" && !(data.citations || []).length && !saysSource && substantial) {
      var note = el("div", "gap");
      note.appendChild(el("span", "gap__label", "Let op: "));
      note.appendChild(document.createTextNode(
        "dit antwoord is niet herleid tot een pagina in de handleiding."));
      b.appendChild(note);
    }

    if (state === "partial") {
      var gap = el("div", "gap");
      gap.appendChild(el("span", "gap__label", "Niet gevonden in de handleiding. "));
      gap.appendChild(document.createTextNode("Dit deel zet ik door naar een collega."));
      b.appendChild(gap);
    }

    if (data.draft) renderDraft(data.draft);
  }

  /* ---------- transport ---------- */

  var lastMessage = null;

  function resend() { if (lastMessage) ask(lastMessage, true); }

  function setBusy(on) {
    busy = on;
    send.disabled = on;
    input.disabled = on;
    if (!on) input.focus();
  }

  function thinking() {
    var w = el("div", "msg msg--bot");
    var b = el("div", "msg__bubble");
    var t = el("div", "thinking");
    t.appendChild(el("span", "sr-only", "Sam is aan het zoeken"));
    t.appendChild(el("i")); t.appendChild(el("i")); t.appendChild(el("i"));
    b.appendChild(t); w.appendChild(b);
    return add(w);
  }

  function ask(text, isRetry) {
    if (busy) return;
    lastMessage = text;
    if (!isRetry) bubble(text, "user");
    setBusy(true);
    var pending = thinking();

    var payload = { message: text };
    if (sessionId) payload.session_id = sessionId;
    if (cfg.user && Object.keys(cfg.user).length) payload.user = cfg.user;
    if (cfg.context && Object.keys(cfg.context).length) payload.context = cfg.context;

    fetch(cfg.apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",         // RGS+ session cookie; no API key here
      body: JSON.stringify(payload)
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        pending.remove();
        if (data.session_id) sessionId = data.session_id;
        renderAnswer(data);
      })
      .catch(function () {
        pending.remove();
        // Our own failure, and we say so. Never dressed up as "ik weet het niet".
        renderBanner("warn", "Ik kan de helpdesk-assistent niet bereiken",
          "Er ging iets mis bij het versturen van je vraag. Dit ligt niet aan je vraag zelf.",
          "Opnieuw proberen", function () { resend(); });
      })
      .finally(function () { setBusy(false); });
  }

  /* ---------- composer ---------- */

  function autoGrow() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 176) + "px";
    var n = input.value.length;
    counter.textContent = n > 7000 ? (n + " / " + MAX) : "";
  }

  input.addEventListener("input", autoGrow);

  // Enter inserts a newline; Ctrl/Cmd+Enter sends. People paste whole emails
  // in here — submitting on a bare Enter would cut them off mid-sentence.
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || busy) return;
    if (text.length > MAX) text = text.slice(0, MAX);
    input.value = "";
    autoGrow();
    ask(text, false);
  });

  /* ---------- boot ---------- */

  (function init() {
    var logo = document.getElementById("logo");
    if (logo && cfg.logoUrl) logo.src = cfg.logoUrl;

    // Use the screen the widget was opened from. It primes a specific question
    // instead of "ik krijg mijn import niet voor elkaar".
    if (cfg.context && cfg.context.screen) {
      document.getElementById("where").textContent = cfg.context.screen;
      document.getElementById("intro-where").hidden = false;
    }
    input.focus();
  })();

  window.SamChat = { ask: ask, reset: function () { sessionId = null; } };
})();
