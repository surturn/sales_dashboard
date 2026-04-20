const API_BASE = "/api";
const TOKEN_KEY = "bizard_leads_access_token";
const REFRESH_TOKEN_KEY = "bizard_leads_refresh_token";
let refreshRequest = null;

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setTokens(accessToken, refreshToken) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  sessionStorage.removeItem("bizard_social_trend_selection_ids");
}

function getRefreshToken() {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

async function refreshAccessToken() {
  if (refreshRequest) {
    return refreshRequest;
  }

  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    throw new Error("Missing Refresh Token");
  }

  refreshRequest = (async () => {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
      credentials: "include",
    });

    if (!response.ok) {
      const rawBody = await response.text();
      let payload = null;
      try {
        payload = rawBody ? JSON.parse(rawBody) : null;
      } catch {
        payload = null;
      }
      const message = payload ? readErrorPayload(payload, response.status) : friendlyHttpErrorMessage(response.status);
      throw new Error(message);
    }

    const payload = await response.json();
    setTokens(payload.access_token, payload.refresh_token);
    return payload;
  })();

  try {
    return await refreshRequest;
  } finally {
    refreshRequest = null;
  }
}

function redirectToLogin() {
  const onAuthPage = /\/(login|signup)\.html$/i.test(window.location.pathname);
  if (!onAuthPage) {
    window.location.href = "/login.html?reason=session-expired";
  }
}

function readErrorPayload(payload, responseStatus) {
  if (!payload) {
    return `Request Failed With ${responseStatus}`;
  }
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (payload.detail && typeof payload.detail.message === "string") {
    return payload.detail.message;
  }
  if (Array.isArray(payload.detail) && payload.detail.length > 0) {
    return payload.detail.map((item) => item.msg || item.type || "Validation Error").join(", ");
  }
  return payload.message || `Request Failed With ${responseStatus}`;
}

function friendlyHttpErrorMessage(responseStatus) {
  if (responseStatus >= 500) {
    return "Service Temporarily Unavailable. Please Try Again Shortly.";
  }
  if (responseStatus === 401) {
    return "Your Session Has Expired. Please Sign In Again.";
  }
  if (responseStatus === 403) {
    return "You Do Not Have Access To This Action.";
  }
  if (responseStatus === 404) {
    return "The Requested Resource Was Not Found.";
  }
  return `Request Failed With ${responseStatus}`;
}

async function apiFetch(path, options = {}) {
  const retryOnUnauthorized = options.retryOnUnauthorized !== false;
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  if (options.showLoader !== false && typeof showAppLoader === "function") {
    showAppLoader(options.loaderTitle || "Loading Workspace", options.loaderSubtitle || "Syncing Live Platform Data");
  }

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      credentials: "include",
    });

    if (!response.ok) {
      let payload = null;
      const rawBody = await response.text();
      try {
        payload = rawBody ? JSON.parse(rawBody) : null;
      } catch {
        payload = null;
      }
      const looksLikeHtml = /^\s*</.test(rawBody || "") || /<html/i.test(rawBody || "");
      if (looksLikeHtml && rawBody) {
        console.error("Upstream Html Error Response", {
          path,
          status: response.status,
          body: rawBody,
        });
      }
      const message = titleCase(
        payload ? readErrorPayload(payload, response.status) : friendlyHttpErrorMessage(response.status)
      );

      if (response.status === 401 && retryOnUnauthorized && !String(path).startsWith("/auth/")) {
        try {
          await refreshAccessToken();
          return apiFetch(path, { ...options, retryOnUnauthorized: false });
        } catch (refreshError) {
          clearTokens();
          console.warn("Authentication Refresh Failed", {
            path,
            error: refreshError.message || refreshError,
          });
          redirectToLogin();
        }
      }

      const error = new Error(message);
      error.status = response.status;
      error.payload = payload;
      error.rawBody = rawBody;
      throw error;
    }

    if (response.status === 204) {
      return null;
    }

    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      return response.text();
    }
    return response.json();
  } finally {
    if (options.showLoader !== false && typeof hideAppLoader === "function") {
      hideAppLoader();
    }
  }
}

function requireAuth() {
  if (!getToken()) {
    redirectToLogin();
  }
}

window.getToken = getToken;
window.getRefreshToken = getRefreshToken;
window.setTokens = setTokens;
window.clearTokens = clearTokens;
window.apiFetch = apiFetch;
window.requireAuth = requireAuth;
