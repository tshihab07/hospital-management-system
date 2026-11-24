/*
 * IHMS — global JavaScript.
 *
 * Responsibilities:
 *  - dark-mode toggle (persisted in a cookie)
 *  - HTMX CSRF + global loading ergonomics
 *  - Alpine.js store/component registration
 *  - small helpers (toasts, chart defaults)
 *
 * No business logic lives here; this is presentation only.
 */
(function () {
  "use strict";

  const THEME_COOKIE = "ihms_theme";

  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? match[2] : null;
  }

  function setCookie(name, value, days) {
    const expires = new Date(Date.now() + (days || 365) * 864e5).toUTCString();
    document.cookie = name + "=" + value + "; expires=" + expires + "; path=/; SameSite=Lax";
  }

  window.IHMS = {
    csrfToken: () => (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "",
    theme: {
      get: () => document.documentElement.getAttribute("data-theme") || "light",
      set: (mode) => {
        document.documentElement.setAttribute("data-theme", mode);
        setCookie(THEME_COOKIE, mode);
      },
      toggle() {
        this.set(this.get() === "dark" ? "light" : "dark");
      },
    },
    toast(message, variant) {
      window.dispatchEvent(
        new CustomEvent("ihms:toast", { detail: { message, variant: variant || "info" } })
      );
    },
  };

  // Apply persisted theme as early as possible.
  const saved = getCookie(THEME_COOKIE);
  if (saved) {
    document.documentElement.setAttribute("data-theme", saved);
  }

  document.addEventListener("DOMContentLoaded", function () {
    // HTMX: send CSRF header and surface server errors.
    if (window.htmx) {
      document.body.addEventListener("htmx:configRequest", function (event) {
        const token = window.IHMS.csrfToken();
        if (token) event.detail.headers["X-CSRFToken"] = token;
      });
      document.body.addEventListener("htmx:responseError", function (event) {
        const status = event.detail.xhr.status;
        if (status === 403) {
          window.IHMS.toast("Session expired or permission denied. Please reload.", "danger");
        }
      });
    }
  });

  document.addEventListener("alpine:init", function () {
    Alpine.store("theme", {
      mode: window.IHMS.theme.get(),
      set(mode) {
        this.mode = mode;
        window.IHMS.theme.set(mode);
      },
      toggle() {
        this.set(this.mode === "dark" ? "light" : "dark");
      },
    });

    Alpine.data("toasts", () => ({
      items: [],
      init() {
        window.addEventListener("ihms:toast", (event) => this.push(event.detail));
      },
      push(detail) {
        const id = Date.now() + Math.random();
        this.items.push({ id, message: detail.message, variant: detail.variant });
        setTimeout(() => this.remove(id), 4500);
      },
      remove(id) {
        this.items = this.items.filter((t) => t.id !== id);
      },
   }));
  });

  window.ihmsChartDefaults = {
    fontFamily: "Inter, 'Noto Sans Bengali', sans-serif",
    palette: ["#4F46E5", "#14B8A6", "#F59E0B", "#EF4444", "#8B5CF6"],
  };
})();
