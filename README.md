# Snipod

A slim FastAPI service that lets an application choose **which specific pod** to remove from a Deployment — instead of leaving that decision to Kubernetes.

## The Problem

When Kubernetes scales down a Deployment (via HPA, manual scale, or any controller), it picks pods to kill using a generic algorithm: pending pods first, then unready, then lower pod-deletion-cost, then higher restart count, then more recently started. This is fine for stateless workloads, but breaks down when:

- **Pods hold in-flight state** — a pod is processing a long-running request, executing a batch job, or holding an active user session. Killing it means lost work or a disrupted user.
- **The application knows best** — the app itself knows which replica is idle, which has finished its work queue, or which is the least valuable to keep running. Kubernetes doesn't have this context.
- **HPA scale-down is random from the app's perspective** — when HPA decides to go from 5 → 4 replicas, it doesn't ask the app which pod should go. It just picks one. If it picks the wrong one, you get interrupted sessions, failed requests, or lost computation.

## The Solution

Snipod flips the decision around: **the application tells Kubernetes which pod to kill**.

Instead of waiting for Kubernetes to arbitrarily select a victim, a pod that knows it's idle (or has finished its work) calls snipod's API with its own name. Snipod then:

1. Marks that pod with `controller.kubernetes.io/pod-deletion-cost: "-1"` (lowest priority for the controller)
2. Decreases the Deployment's replica count by 1
3. Kubernetes sees the marked pod as the cheapest to remove and terminates it

The result: the application controls its own scale-down lifecycle. No sessions are interrupted, no work is lost, and the pod that volunteered to die is the one that actually gets killed.

## Why Not KEDA / Custom Metrics?

The traditional approach to application-aware scaling is: expose a custom metric (e.g. `active_sessions`), push it to Prometheus or CloudWatch, configure a KEDA ScaledObject or HPA with that metric, wait for the autoscaler to react, and hope it picks the right pod. This works for scale-up, but for scale-down it still has the same fundamental problem — the autoscaler decides *that* a pod should die, but not *which* one.

With snipod, the app skips the entire metric pipeline:

```
Traditional (KEDA/HPA + custom metric):
  App → expose metric → Prometheus → KEDA → HPA → scale decision → random pod killed

Snipod (direct):
  App → "I'm idle, kill me" → POST /api/v1/scale_in → that specific pod killed
```

No metric scrapers, no ScaledObject CRDs, no polling intervals, no aggregation delays. The pod that's ready to die says so immediately and gets removed in one API call. This is particularly useful when:

- The metric-to-action latency is too slow (custom metrics have scrape intervals, aggregation windows, cooldown periods)
- You need pod-level precision that no metric-based autoscaler can provide
- You don't want to maintain a KEDA/Prometheus/metrics-adapter stack just for scale-down targeting
- The application already knows it's done — why wait for a metrics pipeline to figure that out?

Snipod doesn't replace HPA or KEDA for scale-up decisions. It complements them by giving the application direct, immediate control over scale-down targeting.

## Use Cases

- **Session-holding services** — a pod finishes serving its last user session and volunteers itself for removal
- **Worker pools** — a worker completes its current task, sees the queue is empty, and opts out
- **Coordinator/leader patterns** — the application knows which replica is a follower with no active bindings and picks it for removal
- **Graceful HPA integration** — instead of letting HPA kill randomly, your app watches for scale-down signals and proactively nominates the right pod

## How It Works

```
                    ┌─────────────────┐
                    │  Pod (idle)     │
                    │  "I'm done,    │
                    │   remove me"    │
                    └────────┬────────┘
                             │ POST /api/v1/scale_in
                             │ x-token: <sa-token>
                             │ {"pod_name": "my-app-abc12"}
                             ▼
                    ┌─────────────────┐
                    │    Snipod       │
                    │                 │
                    │ 1. Verify token │
                    │ 2. Find owner   │
                    │    (Pod→RS→Dep) │
                    │ 3. Annotate pod │
                    │    cost = -1    │
                    │ 4. Replicas - 1 │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Kubernetes     │
                    │  kills the pod  │
                    │  with lowest    │
                    │  deletion-cost  │
                    └─────────────────┘
```

## Features

- **Pod-targeted scale-in** — pass a pod name, snipod resolves the owning Deployment automatically via ownerReferences (Pod → ReplicaSet → Deployment)
- **Kubernetes TokenReview auth** — requests must carry a valid service account token from the same namespace (audience: `snipod-sa`)
- **Health endpoint** — `/health` for liveness/readiness probes
- **Slim container** — `python:3.11-slim` based, minimal dependencies
- **Conflict-safe** — retries with exponential backoff on scale conflicts

## API

### `GET /health`

Returns `{"status": "ok"}`.

### `POST /api/v1/scale_in`

Scale in by removing a specific pod.

**Headers:**
- `x-token` — Kubernetes service account token (projected with audience `snipod-sa`)

**Body:**
```json
{
  "pod_name": "my-app-7f8b9c6d4-abc12"
}
```

**Success (200):**
```json
{
  "status": 200,
  "message": "Scaled in Deployment/my-app by removing pod my-app-7f8b9c6d4-abc12",
  "deployment_name": "my-app"
}
```

**Error responses:**

| Code | Scenario |
|------|----------|
| 401 | Missing or invalid `x-token` |
| 403 | Token is from a different namespace |
| 404 | Pod not found, or pod is not owned by a Deployment |
| 422 | Deployment already at 1 replica (can't go lower) |
| 500 | Kubernetes API failure |

## Running Locally

```bash
poetry install
poetry run uvicorn app.main:app --port 8080 --reload
```

Requires a working kubeconfig pointing at a cluster.

## Docker

```bash
docker build -t snipod:latest .
docker run -p 8080:8080 snipod:latest
```

## Kubernetes Deployment

The calling pod needs a projected service account token with audience `snipod-sa`:

```yaml
volumes:
  - name: snipod-token
    projected:
      sources:
        - serviceAccountToken:
            audience: snipod-sa
            expirationSeconds: 3600
            path: token
```

The pod reads the token file and passes it as the `x-token` header when calling snipod.

## RBAC

Snipod's own service account needs:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: snipod
rules:
  # Authenticate incoming tokens
  - apiGroups: ["authentication.k8s.io"]
    resources: ["tokenreviews"]
    verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: snipod
rules:
  # Read pods and patch annotations
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "patch"]
  # Resolve ReplicaSet -> Deployment chain
  - apiGroups: ["apps"]
    resources: ["replicasets"]
    verbs: ["get"]
  # Scale deployments
  - apiGroups: ["apps"]
    resources: ["deployments/scale"]
    verbs: ["get", "update"]
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SNIPOD_LISTEN_PORT` | `8080` | Port to listen on |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `KUBERNETES_NAMESPACE` | auto | Overrides namespace detection |

## Project Structure

```
snipod/
├── app/
│   ├── api/
│   │   ├── health.py          # GET /health
│   │   └── scale.py           # POST /api/v1/scale_in
│   ├── core/
│   │   ├── config.py          # Kubernetes config + namespace discovery
│   │   ├── middleware.py      # Global exception handler
│   │   └── security.py        # TokenReview auth + namespace assertion
│   ├── services/
│   │   └── scale_in.py        # Find owner, annotate, scale down
│   └── main.py                # FastAPI entrypoint
├── Dockerfile
├── Makefile
├── pyproject.toml
└── README.md
```
