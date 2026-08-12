#!/bin/bash
# ============================================================
# Snipod Integration Test
# ============================================================
# Installs snipod helm chart and dummy-app into the current
# kubectl context, then verifies scale-in works.
#
# Usage:
#   ./test/run-test.sh [NAMESPACE]
#
# Default namespace: pk-test
# ============================================================

set -euo pipefail

NAMESPACE="${1:-pk-test}"
RELEASE_NAME="snipod"
CHART_PATH="charts/snipod"
EXAMPLES_PATH="examples/dummy-app.yaml"
CALLER_POD="snipod-test-caller"
SNIPOD_SVC="http://snipod.${NAMESPACE}.svc.cluster.local/api/v1/scale_in"
TOKEN_PATH="/var/run/secrets/snipod/token"

echo "=== Snipod Integration Test ==="
echo "Namespace: $NAMESPACE"
echo ""

# 1. Create namespace if needed
echo "[1/7] Ensuring namespace '$NAMESPACE' exists..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
echo ""

# 2. Install snipod via helm
echo "[2/7] Installing snipod helm chart..."
helm upgrade --install "$RELEASE_NAME" "$CHART_PATH" \
  --namespace "$NAMESPACE" \
  --set env.LOG_LEVEL=DEBUG \
  --wait --timeout 120s
echo "  ✓ Helm release '$RELEASE_NAME' installed"
echo ""

# 3. Deploy dummy app and test caller
echo "[3/7] Deploying dummy-app and test-caller..."
kubectl apply -f "$EXAMPLES_PATH" -n "$NAMESPACE"
echo ""

# 4. Wait for readiness
echo "[4/7] Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app=snipod -n "$NAMESPACE" --timeout=60s
kubectl wait --for=condition=ready pod -l app=dummy-app -n "$NAMESPACE" --timeout=60s
kubectl wait --for=condition=ready pod "$CALLER_POD" -n "$NAMESPACE" --timeout=60s
echo "  ✓ All pods ready"
echo ""

# 5. Health check
echo "[5/7] Testing health endpoint..."
kubectl exec "$CALLER_POD" -n "$NAMESPACE" -- \
  curl -sf "http://snipod.${NAMESPACE}.svc.cluster.local/health" | grep -q '"ok"'
echo "  ✓ Health check passed"
echo ""

# 6. Scale in
echo "[6/7] Calling snipod to scale in a dummy-app pod..."
TARGET_POD=$(kubectl get pods -n "$NAMESPACE" -l app=dummy-app -o jsonpath='{.items[0].metadata.name}')
echo "  Target: $TARGET_POD"

RESPONSE=$(kubectl exec "$CALLER_POD" -n "$NAMESPACE" -- \
  curl -sf -X POST "$SNIPOD_SVC" \
    -H "Content-Type: application/json" \
    -H "x-token: $(kubectl exec "$CALLER_POD" -n "$NAMESPACE" -- cat $TOKEN_PATH)" \
    -d "{\"pod_name\": \"$TARGET_POD\"}")
echo "  Response: $RESPONSE"
echo ""

# 7. Verify
echo "[7/7] Verifying deployment scaled down..."
sleep 5
REPLICAS=$(kubectl get deployment dummy-app -n "$NAMESPACE" -o jsonpath='{.spec.replicas}')
if [ "$REPLICAS" -eq 2 ]; then
  echo "  ✓ dummy-app scaled from 3 → 2 replicas"
else
  echo "  ✗ Expected 2 replicas, got $REPLICAS"
  exit 1
fi

echo ""
echo "=== All tests passed ==="
echo ""
echo "Cleanup:"
echo "  helm uninstall $RELEASE_NAME -n $NAMESPACE"
echo "  kubectl delete -f $EXAMPLES_PATH -n $NAMESPACE"
echo "  kubectl delete namespace $NAMESPACE"
