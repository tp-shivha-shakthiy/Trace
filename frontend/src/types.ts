// Types mirroring the TRACE API response schemas (app/schemas.py).

export type Confidence = "high" | "medium" | "low";

export interface DomainSignal {
  domain: string;
  score: number;
  confidence: Confidence;
  evidence: string[];
  repository_count: number;
}

export interface DomainAggregate {
  repository_count: number;
  repository_names: string[];
}

export interface EventMonth {
  month: string;
  events: number;
}

export interface DeveloperSummary {
  total_repositories: number;
  total_events: number;
  languages: Record<string, number>;
  domains: Record<string, DomainAggregate>;
  domain_signals: DomainSignal[];
  events_by_domain: Record<string, number>;
  activity: Record<string, number>;
  events_per_month: EventMonth[];
  last_activity_at: string | null;
}

export interface RepositorySummary {
  full_name: string;
  name: string;
  html_url: string | null;
  description: string | null;
  language: string | null;
  languages: string[];
  topics: string[];
  domains: string[];
  stargazers_count: number;
  forks_count: number;
  pushed_at: string | null;
  event_count: number;
}

export interface RecentActivity {
  event_type: string;
  resource_id: string | null;
  repository: string | null;
  occurred_at: string;
}

export interface DeveloperProfile {
  username: string;
  name: string | null;
  avatar_url: string | null;
  html_url: string | null;
  bio: string | null;
  location: string | null;
  company: string | null;
  public_repos: number;
  followers: number;
  following: number;
  summary: DeveloperSummary;
  repositories: RepositorySummary[];
  recent_activity: RecentActivity[];
}

export interface DeveloperListItem {
  username: string;
  name: string | null;
  avatar_url: string | null;
  html_url: string | null;
  public_repos: number;
  total_events: number;
  last_synced_at: string | null;
}

export interface SyncCreated {
  job_id: string;
  developer_username: string;
  status: string;
}

export interface SyncJob {
  id: string;
  developer_username: string;
  developer_id: number | null;
  status: string;
  error_message: string | null;
  events_fetched: number;
  events_persisted: number;
  events_duplicates: number;
  repositories_synced: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}