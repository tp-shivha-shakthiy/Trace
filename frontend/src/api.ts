import type {
  DeveloperListItem,
  DeveloperProfile,
  MeIdentity,
  SyncCreated,
  SyncJob,
} from "./types";

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, { ...init, credentials: "include" });
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // non-JSON error body; keep the status fallback
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function listDevelopers(): Promise<DeveloperListItem[]> {
  return request<DeveloperListItem[]>("/api/v1/developers");
}

export async function getProfile(username: string): Promise<DeveloperProfile> {
  return request<DeveloperProfile>(`/api/v1/developers/${username}`);
}

export async function deleteFetchedProfile(username: string): Promise<void> {
  await request<void>(
    `/api/v1/developers/${encodeURIComponent(username)}/fetched`,
    { method: "DELETE" },
  );
}

export async function getMe(): Promise<MeIdentity> {
  return request<MeIdentity>("/api/v1/me");
}

export async function logout(): Promise<void> {
  await request<{ status: string }>("/auth/logout", { method: "POST" });
}

export async function getMyProfile(): Promise<DeveloperProfile> {
  return request<DeveloperProfile>("/api/v1/me/profile");
}

export async function enqueueSync(username: string): Promise<SyncCreated> {
  return request<SyncCreated>("/api/v1/sync", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ username }),
  });
}

export async function getSyncJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<SyncJob> {
  return request<SyncJob>(`/api/v1/sync/${encodeURIComponent(jobId)}`, {
    signal,
  });
}

/** Resolve after ``ms``, or reject with the signal's reason once aborted. */
function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(signal?.reason);
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Poll a background sync job until it finishes.
 *
 * Aborting ``signal`` stops polling (including an in-flight request) and
 * rejects with the abort reason, so callers can tear polling down on unmount.
 */
export async function waitForJob(
  jobId: string,
  onStatus?: (status: string) => void,
  signal?: AbortSignal,
): Promise<SyncJob> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    signal?.throwIfAborted();
    const job = await getSyncJob(jobId, signal);
    signal?.throwIfAborted();
    onStatus?.(job.status);
    if (job.status === "succeeded" || job.status === "failed") return job;
    await delay(1000, signal);
  }
  throw new ApiError(408, "Sync timed out waiting for the job to finish");
}

/** Enqueue a sync and poll until the background job finishes. */
export async function syncAndWait(
  username: string,
  onStatus?: (status: string) => void,
): Promise<SyncJob> {
  const created = await enqueueSync(username);
  return waitForJob(created.job_id, onStatus);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "–";
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}