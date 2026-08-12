# Examples

This folder contains manifests to test snipod end-to-end in a live cluster.

## What's Included

- **dummy-app.yaml** — A 3-replica nginx Deployment (the scale-in target) and a test-caller pod with a projected service account token to invoke snipod's API.

## Quick Start

```bash
# 1. Install snipod via the Helm chart
helm upgrade --install snipod charts/snipod -n pk-test --create-namespace --wait

# 2. Deploy the dummy app and test caller
kubectl apply -f examples/dummy-app.yaml -n pk-test

# 3. Wait for everything to come up
kubectl wait --for=condition=ready pod -l app=dummy-app -n pk-test --timeout=60s
kubectl wait --for=condition=ready pod snipod-test-caller -n pk-test --timeout=60s
```

## Testing Manually

Exec into the test-caller pod and call snipod:

```bash
kubectl exec -it snipod-test-caller -n pk-test -- sh

# Read the projected token
TOKEN=$(cat /var/run/secrets/snipod/token)

# Pick a dummy-app pod to kill
TARGET="dummy-app-<tab-complete-a-pod-name>"

# Call snipod
curl -X POST http://snipod.pk-test.svc.cluster.local/api/v1/scale_in \
  -H "Content-Type: application/json" \
  -H "x-token: $TOKEN" \
  -d "{\"pod_name\": \"$TARGET\"}"
```

Expected response:

```json
{
  "status": 200,
  "message": "Scaled in Deployment/dummy-app by removing pod dummy-app-7f8b9c6d4-abc12",
  "deployment_name": "dummy-app"
}
```

Verify the deployment went from 3 → 2 replicas:

```bash
kubectl get deployment dummy-app -n pk-test
```

## Automated Test Script

Run the full test end-to-end (installs helm chart + example, calls the API, verifies scale-down):

```bash
./test/run-test.sh pk-test
```

## Cleanup

```bash
helm uninstall snipod -n pk-test
kubectl delete -f examples/dummy-app.yaml -n pk-test
kubectl delete namespace pk-test
```
