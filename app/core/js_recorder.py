RECORDER_JS = r"""
(() => {
  if (window.__JAQA_INSTALLED__) return;
  window.__JAQA_INSTALLED__ = true;
  window.__JAQA_EXPECT_MODE__ = !!window.__JAQA_EXPECT_MODE__;

  const cssEscape = (value) => {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_\-]/g, (ch) => "\\" + ch);
  };

  const uniqueSelector = (el) => {
    if (!el || el.nodeType !== 1) return "";
    if (el.id) {
      const byId = "#" + cssEscape(el.id);
      try {
        if (document.querySelectorAll(byId).length === 1) return byId;
      } catch (err) { /* ignore */ }
    }

    const attrNames = ["data-testid", "data-test-id", "data-qa", "data-cy"];
    for (const name of attrNames) {
      const val = el.getAttribute(name);
      if (!val) continue;
      const sel = "[" + name + "=\"" + val.replace(/"/g, '\\"') + "\"]";
      try {
        if (document.querySelectorAll(sel).length === 1) return sel;
      } catch (err) { /* ignore */ }
    }

    if (el.name) {
      const sel = el.tagName.toLowerCase() + "[name=\"" + String(el.name).replace(/"/g, '\\"') + "\"]";
      try {
        if (document.querySelectorAll(sel).length === 1) return sel;
      } catch (err) { /* ignore */ }
    }

    const aria = el.getAttribute("aria-label");
    if (aria) {
      const sel = el.tagName.toLowerCase() + "[aria-label=\"" + aria.replace(/"/g, '\\"') + "\"]";
      try {
        if (document.querySelectorAll(sel).length === 1) return sel;
      } catch (err) { /* ignore */ }
    }

    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node.tagName && node.tagName.toLowerCase() !== "html") {
      let part = node.tagName.toLowerCase();
      if (node.id) {
        parts.unshift("#" + cssEscape(node.id));
        break;
      }
      const parent = node.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        if (same.length > 1) {
          part += ":nth-of-type(" + (same.indexOf(node) + 1) + ")";
        }
      }
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(" > ");
  };

  const describe = (el) => {
    const tag = (el.tagName || "").toLowerCase();
    const text = String(el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80);
    return {
      tag,
      type: el.type || "",
      name: el.name || "",
      id: el.id || "",
      text,
      value: el.value != null ? String(el.value).slice(0, 200) : "",
      placeholder: el.placeholder || "",
      href: el.href || "",
    };
  };

  const isOurs = (el) => !!(el && el.closest && el.closest("#jaqa-overlay"));

  const interesting = (el) =>
    el.closest("a,button,input,select,textarea,label,summary,[role='button'],[role='tab'],[role='menuitem'],[onclick]") || el;

  const sendAction = (data) => {
    if (typeof window.__jaqa_action === "function") {
      window.__jaqa_action(data);
    }
  };

  const sendExpect = (data) => {
    if (typeof window.__jaqa_expect === "function") {
      window.__jaqa_expect(data);
    }
  };

  const payload = (el, extra) => Object.assign({ selector: uniqueSelector(el) }, describe(el), extra);

  document.addEventListener("click", (event) => {
    const raw = event.target;
    if (!(raw instanceof Element) || isOurs(raw)) return;
    const el = interesting(raw);
    if (window.__JAQA_EXPECT_MODE__) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      sendExpect(payload(el, { mode: "expect" }));
      return;
    }
    const tag = (el.tagName || "").toLowerCase();
    const typ = (el.type || "").toLowerCase();
    if (tag === "select" || typ === "checkbox" || typ === "radio" || typ === "file" || typ === "text" || typ === "password" || typ === "email" || typ === "number" || typ === "search" || typ === "tel" || tag === "textarea") {
      return;
    }
    sendAction(payload(el, { action: "click" }));
  }, true);

  document.addEventListener("change", (event) => {
    const el = event.target;
    if (!(el instanceof Element) || isOurs(el) || window.__JAQA_EXPECT_MODE__) return;
    const tag = (el.tagName || "").toLowerCase();
    const typ = (el.type || "").toLowerCase();
    if (typ === "checkbox" || typ === "radio") {
      sendAction(payload(el, { action: "check", checked: !!el.checked }));
    } else if (tag === "select") {
      sendAction(payload(el, { action: "select", value: el.value || "" }));
    } else {
      sendAction(payload(el, { action: "fill", value: el.value || "" }));
    }
  }, true);

  document.addEventListener("keydown", (event) => {
    if (window.__JAQA_EXPECT_MODE__) return;
    const el = event.target;
    if (!(el instanceof Element) || isOurs(el)) return;
    if (event.key === "Enter" && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) {
      sendAction(payload(el, { action: "press", key: "Enter", value: el.value || "" }));
    }
  }, true);

  const ensureBanner = () => {
    let bar = document.getElementById("jaqa-overlay");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "jaqa-overlay";
      bar.style.cssText = [
        "position:fixed",
        "top:0",
        "left:0",
        "right:0",
        "z-index:2147483647",
        "padding:8px 16px",
        "font:600 13px/1.4 Segoe UI,sans-serif",
        "color:#fff",
        "text-align:center",
        "pointer-events:none",
        "box-shadow:0 2px 8px rgba(0,0,0,.25)",
      ].join(";");
      (document.body || document.documentElement).appendChild(bar);
    }
    if (window.__JAQA_EXPECT_MODE__) {
      bar.style.background = "#c2410c";
      bar.textContent = "JAQA • MODE EXPECTED — klik elemen, lalu isi nilai yang diharapkan";
    } else {
      bar.style.background = "#b91c1c";
      bar.textContent = "JAQA • MEREKAM — lakukan langkah uji di halaman ini";
    }
  };

  window.__jaqa_set_expect_mode = (on) => {
    window.__JAQA_EXPECT_MODE__ = !!on;
    ensureBanner();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureBanner);
  } else {
    ensureBanner();
  }
})();
"""
