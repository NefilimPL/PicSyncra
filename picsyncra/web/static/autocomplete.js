(function registerAutocomplete(global) {
  "use strict";

  global.PicSyncra = global.PicSyncra || {};

  function mergeSuggestions(localValues, remoteValues) {
    const seen = new Set();
    const values = [];
    for (const value of [...(localValues || []), ...(remoteValues || [])]) {
      const text = String(value || "").trim();
      const key = text.toUpperCase();
      if (!text || seen.has(key)) continue;
      seen.add(key);
      values.push(text);
    }
    return values;
  }

  function visibleLocalCount(values, query, limit) {
    const needle = String(query || "").trim().toUpperCase();
    const seen = new Set();
    let count = 0;
    for (const value of values || []) {
      const text = String(value || "").trim();
      const key = text.toUpperCase();
      if (!text || seen.has(key) || (needle && !key.includes(needle))) continue;
      seen.add(key);
      count += 1;
      if (count >= limit) return count;
    }
    return count;
  }

  class AutocompleteController {
    constructor(options = {}) {
      this.fieldName = options.fieldName || "";
      this.localSuggestions = options.localSuggestions || (() => []);
      this.remoteSuggestions = options.remoteSuggestions || (() => Promise.resolve([]));
      this.render = options.render || (() => {});
      this.captureRequest = options.captureRequest || (() => ({ signature: this.fieldName }));
      this.getQuery = options.getQuery || (() => "");
      this.isActive = options.isActive || (() => true);
      this.mergeSuggestions = options.mergeSuggestions || mergeSuggestions;
      this.setTimer = options.setTimer || ((callback, delay) => global.setTimeout(callback, delay));
      this.clearTimer = options.clearTimer || ((timer) => global.clearTimeout(timer));
      this.delayMs = Math.max(0, Number(options.delayMs) || 0);
      this.limit = Math.max(1, Number(options.limit) || 80);
      this.latest = new global.PicSyncra.LatestRequest();
      this.timer = null;
      this.pending = Promise.resolve();
    }

    refresh() {
      const suggestedLocal = this.localSuggestions();
      const local = Array.isArray(suggestedLocal) ? suggestedLocal : [];
      this.render(this.mergeSuggestions(local, []));
      this.clearPendingTimer();

      if (visibleLocalCount(local, this.getQuery(), this.limit) >= this.limit) {
        this.latest.cancel();
        return false;
      }

      const request = this.captureRequest() || {};
      const token = this.latest.next(request.signature || this.fieldName);
      this.timer = this.setTimer(() => {
        this.timer = null;
        this.pending = Promise.resolve(this.remoteSuggestions(request, token.signal))
          .then((remoteValues) => {
            const current = this.captureRequest() || {};
            if (!token.isCurrent(current.signature || this.fieldName) || !this.isActive()) return;
            this.render(
              this.mergeSuggestions(local, Array.isArray(remoteValues) ? remoteValues : [])
            );
          })
          .catch((error) => {
            if (error && error.name === "AbortError") return;
          });
        return this.pending;
      }, this.delayMs);
      return true;
    }

    clearPendingTimer() {
      if (this.timer === null) return;
      this.clearTimer(this.timer);
      this.timer = null;
    }

    cancel() {
      this.clearPendingTimer();
      this.latest.cancel();
    }

    pendingForTest() {
      return this.pending;
    }
  }

  function setupAutocomplete(dependencies = {}) {
    const document = dependencies.document || global.document;
    const productForm = dependencies.productForm;
    if (!document || !productForm) return { closePanels: () => {} };

    const fieldNames = dependencies.fieldNames || [];
    const localSuggestions = dependencies.localSuggestions || (() => []);
    const remoteSuggestions = dependencies.remoteSuggestions || (() => Promise.resolve([]));
    const captureRequest = dependencies.captureRequest || (() => ({ signature: "" }));
    const uniqueValues = dependencies.uniqueValues || mergeSuggestions;
    const maxOptions = Math.max(1, Number(dependencies.maxOptions) || 80);
    const setTimer = dependencies.setTimer || ((callback, delay) => global.setTimeout(callback, delay));
    const clearTimer = dependencies.clearTimer || ((timer) => global.clearTimeout(timer));
    let activePanel = null;

    function closePanels(exceptPanel = null) {
      activePanel = exceptPanel;
      document.querySelectorAll(".autocomplete-panel").forEach((panel) => {
        if (panel !== exceptPanel) panel.classList.remove("active");
      });
    }

    function optionsFor(panel) {
      return [...panel.querySelectorAll('button[data-autocomplete-option="1"]')];
    }

    function setActiveOption(panel, index) {
      const options = optionsFor(panel);
      if (!options.length) {
        panel.dataset.activeIndex = "-1";
        return;
      }
      const nextIndex = ((index % options.length) + options.length) % options.length;
      options.forEach((option, optionIndex) => {
        option.classList.toggle("active", optionIndex === nextIndex);
        option.setAttribute("aria-selected", optionIndex === nextIndex ? "true" : "false");
      });
      panel.dataset.activeIndex = String(nextIndex);
      options[nextIndex].scrollIntoView({ block: "nearest" });
    }

    function appendText(button, value, query) {
      const text = String(value || "");
      const needle = String(query || "").trim();
      if (!needle) {
        button.textContent = text;
        return;
      }
      const index = text.toLowerCase().indexOf(needle.toLowerCase());
      if (index < 0) {
        button.textContent = text;
        return;
      }
      button.append(
        document.createTextNode(text.slice(0, index)),
        Object.assign(document.createElement("mark"), {
          textContent: text.slice(index, index + needle.length),
        }),
        document.createTextNode(text.slice(index + needle.length))
      );
    }

    function commitValue(input, panel, value) {
      panel.dataset.selecting = "1";
      input.value = value;
      input.dispatchEvent(new global.Event("input", { bubbles: true }));
      input.dispatchEvent(new global.Event("change", { bubbles: true }));
      closePanels();
      setTimer(() => {
        panel.dataset.selecting = "";
      }, 0);
    }

    function renderPanel(input, panel, values) {
      if (activePanel && activePanel !== panel && document.activeElement !== input) return;
      if (panel.dataset.selecting === "1") return;
      closePanels(panel);
      const previousScroll = panel.scrollTop;
      const typed = input.value.trim();
      const typedUpper = typed.toUpperCase();
      const filtered = values
        .filter((value) => !typedUpper || value.toUpperCase().includes(typedUpper))
        .slice(0, maxOptions);
      panel.textContent = "";
      panel.dataset.activeIndex = "-1";
      if (!filtered.length) {
        panel.classList.remove("active");
        return;
      }
      for (const [index, value] of filtered.entries()) {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.autocompleteOption = "1";
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", "false");
        appendText(button, value, typed);
        button.addEventListener("mouseenter", () => setActiveOption(panel, index));
        button.addEventListener("mousedown", (event) => {
          event.preventDefault();
          commitValue(input, panel, value);
        });
        panel.appendChild(button);
      }
      panel.scrollTop = previousScroll;
      panel.classList.add("active");
      activePanel = panel;
    }

    productForm.setAttribute("autocomplete", "off");
    for (const fieldName of fieldNames) {
      const input = productForm.elements[fieldName];
      if (!input) continue;
      input.removeAttribute("list");
      input.setAttribute("autocomplete", "off");
      input.setAttribute("spellcheck", "false");
      input.setAttribute("aria-autocomplete", "list");
      input.setAttribute("data-lpignore", "true");
      input.setAttribute("data-1p-ignore", "true");
      input.setAttribute("data-bwignore", "true");
      input.setAttribute("data-form-type", "other");
      input.setAttribute("readonly", "readonly");
      const host = input.closest("label");
      if (!host) continue;
      host.classList.add("autocomplete-host");
      const panel = document.createElement("div");
      panel.className = "autocomplete-panel";
      panel.setAttribute("role", "listbox");
      host.appendChild(panel);
      const controller = new AutocompleteController({
        fieldName,
        localSuggestions: () => localSuggestions(fieldName),
        remoteSuggestions: (request, signal) => remoteSuggestions(fieldName, request.payload, signal),
        render: (values) => renderPanel(input, panel, uniqueValues(values)),
        captureRequest: () => captureRequest(fieldName),
        getQuery: () => input.value,
        isActive: () => activePanel === panel,
        setTimer,
        clearTimer,
        delayMs: 180,
        limit: maxOptions,
      });
      const unlockBrowserAutofill = () => {
        input.removeAttribute("readonly");
        setTimer(() => input.setAttribute("autocomplete", "off"), 0);
      };
      const refresh = () => {
        activePanel = panel;
        closePanels(panel);
        controller.refresh();
      };
      input.addEventListener("mousedown", unlockBrowserAutofill);
      input.addEventListener("focus", unlockBrowserAutofill);
      input.addEventListener("focus", refresh);
      input.addEventListener("input", refresh);
      input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          closePanels();
          return;
        }
        if (!["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) return;
        if (!panel.classList.contains("active")) {
          if (event.key === "Enter") return;
          refresh();
        }
        const options = optionsFor(panel);
        if (!options.length) return;
        const currentIndex = Number(panel.dataset.activeIndex || "-1");
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setActiveOption(panel, currentIndex + 1);
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          setActiveOption(panel, currentIndex - 1);
        } else if (event.key === "Enter" && currentIndex >= 0 && options[currentIndex]) {
          event.preventDefault();
          commitValue(input, panel, options[currentIndex].textContent || "");
        }
      });
    }
    document.addEventListener("mousedown", (event) => {
      if (!event.target.closest(".autocomplete-host")) closePanels();
    });
    return { closePanels };
  }

  global.PicSyncra.AutocompleteController = AutocompleteController;
  global.PicSyncra.setupAutocomplete = setupAutocomplete;
})(window);
