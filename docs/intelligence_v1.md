# TRACE Intelligence V1 — Technical Documentation

## 1. Supported Domains

TRACE Intelligence V1 recognizes 11 technical domains derived from persisted repository evidence:

| Domain | Key | Primary Signals & Technologies |
| :--- | :--- | :--- |
| **Backend** | `backend` | Python, Java, Go, Rust, C#, PHP, Ruby, SQL; topics & keywords: `api`, `server`, `rest`, `graphql`, `microservice`, `fastapi`, `django`, `flask`, `postgresql` |
| **Frontend** | `frontend` | TypeScript, JavaScript, HTML, CSS, Vue, Svelte; topics & keywords: `react`, `tailwind`, `ui`, `ux`, `dashboard`, `webapp`, `design-system` |
| **DevOps** | `devops` | Go, Shell, Dockerfile, Makefile; topics & keywords: `docker`, `kubernetes`, `k8s`, `terraform`, `ci`, `cd`, `aws`, `gcp`, `azure`, `helm`, `deployment`, `cloud` |
| **Data** | `data` | Python, SQL, R, Julia, Scala; topics & keywords: `etl`, `pipeline`, `analytics`, `pandas`, `spark`, `database`, `warehouse`, `streaming` |
| **ML** | `ml` | Python, R, Julia, Jupyter Notebook; topics & keywords: `machine-learning`, `deep-learning`, `pytorch`, `tensorflow`, `keras`, `llm`, `nlp`, `computer-vision` |
| **Mobile** | `mobile` | Swift, Kotlin, Objective-C, C#; topics & keywords: `android`, `ios`, `flutter`, `react-native` |
| **Security** | `security` | Topics & keywords: `cryptography`, `crypto`, `auth`, `oauth`, `encryption`, `vulnerability`, `pentest` |
| **Systems** | `systems` | C, C++, Rust; topics & keywords: `compiler`, `kernel`, `embedded`, `network`, `operating-system` |
| **Gaming** | `gaming` | C++, C#, Lua; topics & keywords: `unity`, `unreal`, `godot`, `gameplay` |
| **Web** | `web` | PHP, Ruby; topics & keywords: `website`, `ssg`, `blog`, `portfolio` |
| **Testing** | `testing` | Topics & keywords: `qa`, `quality`, `pytest`, `cypress`, `unit-test` |

---

## 2. Evidence Types

Every domain inference is explainable and traceable back to concrete, persisted GitHub metadata stored in PostgreSQL.

* `language`: Matched programming language from repository language breakdown (`Repository.languages` byte counts or `Repository.language`).
* `topic`: Explicit repository topics tagged by the developer on GitHub (`Repository.topics`).
* `keyword`: Curated domain terminology matched in repository name or description (`Repository.name`, `Repository.description`).

---

## 3. Scoring Approach & Deduplication

Inference replaces binary classification with deterministic, reproducible, and bounded scoring.

### Signal Weights
* **Language Weight**: `share * 1.0` (proportional to language byte share in the repository; max 1.0).
* **Topic Weight**: `0.50` per matched topic tag.
* **Repository Name Keyword**: `0.25` per matched keyword in repository name.
* **Description Keyword**: `0.20` per matched keyword in repository description.

### Deduplication (Double-Counting Prevention)
* **Cross-Source Deduplication**: If a term (e.g. `fastapi`) matches as a topic, it is not re-counted as a name keyword or description keyword within that repository.
* **Within-Field Deduplication**: Multiple occurrences of the same keyword within a description or name match only once.
* **Repository Keyword Cap**: The total combined keyword weight (topics + name + description) is capped at `0.80` per repository per domain.
* **Repository Total Intensity Cap**: Total repository intensity is capped at `1.50`.
* **Activity Amplification**: If and only if a repository already has non-zero domain evidence, event volume amplifies intensity by `0.20 * min(1.0, event_count / 50)`. Activity alone never creates a domain.

---

## 4. Aggregation Approach

TRACE aggregates repository-level evidence into developer-level intelligence:
1. For each domain, identify all contributing repositories where evidence intensity > 0.
2. Sum the raw intensities of all contributing repositories: `raw_intensity = sum(repo_intensity)`.
3. Normalize the raw intensity into a bounded developer evidence score:
   $$\text{score} = \min\left(1.0, \text{round}\left(\frac{\text{raw\_intensity}}{3.0}, 2\right)\right)$$
   The scaling factor $3.0$ represents sustained evidence across 2-3 repositories.
4. Each domain retains its supporting repositories and their concrete signals for total traceability.

---

## 5. Strength Levels

Developer evidence scores map deterministically to three human-readable strength levels:

* **`strong`**: `score >= 0.70` with evidence corroborated across `repository_count >= 2` (or `score >= 0.85` for overwhelming evidence).
* **`moderate`**: `score >= 0.40`.
* **`emerging`**: `score < 0.40` (and satisfies the minimum-evidence rule).

> [!NOTE]
> TRACE strictly avoids speculative employment claims such as "expert", "senior", "professional", or "master". Strength reflects the depth and breath of observable GitHub evidence, not career seniority.

---

## 6. Minimum-Evidence Rule

To prevent weak, ambiguous signals from generating false classifications, TRACE enforces the **Minimum-Evidence Rule**:

A domain is included in developer intelligence **if and only if**:
1. Confirmed language evidence in that domain exists, **OR**
2. Explicit GitHub topic tag evidence in that domain exists, **OR**
3. Multiple distinct keywords ($\ge 2$) match across repositories AND aggregate intensity $\ge 0.40$.

**Consequence**: A single keyword match in a repository name (e.g., a repository named `my-data` with no data languages, no topics, and no other data keywords, yielding intensity 0.25) is discarded and will not create a `Data` domain.

---

## 7. Privacy & Ownership Isolation

TRACE Intelligence is derived strictly from persisted data, adhering to authorization boundaries:

* **Self Profile (`GET /api/v1/me/profile`)**: Assembled using the authenticated developer's own repositories and activity (including private repositories).
* **Fetched Profile (`GET /api/v1/developers/{username}`)**: Assembled exclusively using repositories and events with `owner_id == viewer.id`.
* **Isolation Guarantee**: If User A fetches User B, User C (who has not fetched B) cannot access B's profile. User C never receives intelligence derived from A's private snapshot of B.
* **Snapshot Deletion**: When User A deletes their fetched copy of User B, all associated repositories and events owned by A are purged, and A's intelligence for B is immediately deleted.
* **Demo Profiles**: Explicit demo profiles only derive intelligence from public demo data.
