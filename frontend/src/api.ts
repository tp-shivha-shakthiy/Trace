import type {
  DeveloperListItem,
  DeveloperProfile,
  SyncCreated,
  SyncJob,
} from "./types";

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, init);
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

export async function enqueueSync(username: string): Promise<SyncCreated> {
  return request<SyncCreated>("/api/v1/sync", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ username }),
  });
}

export async function getSyncJob(jobId: string): Promise<SyncJob> {
  return request<SyncJob>(`/api/v1/sync/${jobId}`);
}

/** Enqueue a sync and poll until the background job finishes. */
export async function syncAndWait(
  username: string,
  onStatus?: (status: string) => void,
): Promise<SyncJob> {
  const created = await enqueueSync(username);
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = await getSyncJob(created.job_id);
    onStatus?.(job.status);
    if (job.status === "succeeded" || job.status === "failed") return job;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new ApiError(408, "Sync timed out waiting for the job to finish");
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "–";
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}