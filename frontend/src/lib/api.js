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

    if (response.status === 401) {
      throw new ApiError("Not signed in", 401);
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(body.detail || "Request failed", response.status);
    }
    return response.status === 204 ? null : response.json();
  } finally {
    clearTimeout(timer);
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export const api = {
  get: (p) => request(p),
  post: (p, body) => request(p, { method: "POST", body: JSON.stringify(body) }),
  put: (p, body) => request(p, { method: "PUT", body: JSON.stringify(body) }),
  patch: (p, body) => request(p, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (p) => request(p, { method: "DELETE" }),
};
