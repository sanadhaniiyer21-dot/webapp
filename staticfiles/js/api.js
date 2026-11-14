/**
 * Maison Tisane API Client
 * Provides helpers with automatic CSRF token handling and persistent session tracking.
 */

(function () {
  "use strict";

  // Persistent session ID in localStorage
  const SESSION_KEY = "maison_session_id";
  function getSessionId() {
    let sid = localStorage.getItem(SESSION_KEY);
    if (!sid) {
      sid = "sess_" + Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
      localStorage.setItem(SESSION_KEY, sid);
    }
    return sid;
  }

  // Retrieve cookie value by name
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      const cookies = document.cookie.split(";");
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  // Get or refresh CSRF token
  async function getCsrfToken() {
    let token = getCookie("csrftoken");
    if (!token) {
      try {
        const res = await fetch("/api/csrf/");
        if (res.ok) {
          const data = await res.json();
          token = data.csrfToken || getCookie("csrftoken");
        }
      } catch (e) {
        console.warn("Failed to fetch CSRF token:", e);
      }
    }
    return token || "";
  }

  // Common JSON fetch wrapper
  async function request(url, options = {}) {
    const opts = { ...options };
    opts.headers = {
      Accept: "application/json",
      ...(opts.headers || {}),
    };

    if (opts.method && opts.method.toUpperCase() !== "GET") {
      const csrf = await getCsrfToken();
      if (csrf) {
        opts.headers["X-CSRFToken"] = csrf;
      }
      if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(opts.body);
      }
    }

    const response = await fetch(url, opts);
    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      const error = new Error((data && data.error) || response.statusText || "Request failed");
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  // API Functions
  const MaisonAPI = {
    getSessionId,

    async sendChat(message, page = window.location.pathname) {
      return request("/api/chat/", {
        method: "POST",
        body: {
          message: String(message || ""),
          session_id: getSessionId(),
          page: String(page || "/"),
        },
      });
    },

    async sendFeedback(messageId, value, page = window.location.pathname) {
      return request("/api/feedback/", {
        method: "POST",
        body: {
          message_id: String(messageId || ""),
          session_id: getSessionId(),
          value: value === "up" ? "up" : "down",
          page: String(page || "/"),
        },
      });
    },

    async createTicket(name, email, subject, message) {
      return request("/api/tickets/", {
        method: "POST",
        body: {
          name: String(name || ""),
          email: String(email || ""),
          subject: String(subject || ""),
          message: String(message || ""),
          session_id: getSessionId(),
        },
      });
    },

    async subscribe(email, firstName = "") {
      return request("/api/subscribe/", {
        method: "POST",
        body: {
          email: String(email || ""),
          first_name: String(firstName || ""),
        },
      });
    },

    async getTeas(filters = {}) {
      const params = new URLSearchParams();
      if (filters.category) params.set("category", filters.category);
      if (filters.caffeine) params.set("caffeine", filters.caffeine);
      if (filters.weather) params.set("weather", filters.weather);
      if (filters.mood) params.set("mood", filters.mood);
      if (filters.q) params.set("q", filters.q);
      const qs = params.toString();
      return request("/api/teas/" + (qs ? `?${qs}` : ""));
    },

    async getWeatherTea(lat, lon) {
      return request(`/api/weather-tea/?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
    },
  };

  // Expose globally
  window.MaisonAPI = MaisonAPI;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = MaisonAPI;
  }
})();
