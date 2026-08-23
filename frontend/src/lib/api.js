// Thin fetch wrapper. Two things that are otherwise forgotten everywhere:
// credentials for the session cookie, and a timeout.

const TIMEOUT_MS = 10_000;

async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(`/api${path}`, {
      ...options,
      credentials: "include",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });

    if (!response.ok) {
      // The body is read for 401 too: the sign-in form needs the actual
      // reason, while everything else just cares that it was a 401.
      const body = await response.json().catch(() => ({}));
      const fallback = response.status === 401 ? "Not signed in" : "Request failed";
      throw new ApiError(body.detail || fallback, response.status, response);
    }
    return response.status === 204 ? null : response.json();
  } finally {
    clearTimeout(timer);
  }
}

export class ApiError extends Error {
  constructor(message, status, response) {
    super(message);
    this.status = status;
    // Rate limiting answers with Retry-After; the form turns it into a wait.
    this.retryAfter = Number(response?.headers?.get("retry-after")) || null;
  }
}

export const api = {
  get: (p) => request(p),
  post: (p, body) => request(p, { method: "POST", body: JSON.stringify(body) }),
  put: (p, body) => request(p, { method: "PUT", body: JSON.stringify(body) }),
  patch: (p, body) => request(p, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (p) => request(p, { method: "DELETE" }),
};
