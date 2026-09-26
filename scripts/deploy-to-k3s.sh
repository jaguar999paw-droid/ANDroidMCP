#!/bin/bash
# deploy-to-k3s.sh - Deploy ANDroidMCP to K3s cluster

set -e

echo "🚀 Deploying ANDroidMCP to K3s..."
echo "=================================="

KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
DOCKER_REGISTRY="${DOCKER_REGISTRY:-localhost:5000}"

# Check kubectl
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl not found. Install it first."
    exit 1
fi

# Step 1: Create namespaces
echo "📦 Creating namespaces..."
kubectl apply -f k8s/namespaces/androidmcp.yaml

# Step 2: Apply network policies
echo "🔒 Applying network policies..."
kubectl apply -f k8s/network-policies/network-policies.yaml

# Step 3: Build Docker images
echo "🐳 Building Docker images..."
docker build -f servers/userspace/Dockerfile -t ${DOCKER_REGISTRY}/androidmcp/userspace-server:latest .

# Step 4: Deploy userspace server
echo "🚢 Deploying userspace-server..."
kubectl apply -f k8s/deployments/userspace-server.yaml

# Step 5: Wait for deployment
echo "⏳ Waiting for deployment to be ready..."
kubectl wait --for=condition=available --timeout=300s deployment/android-userspace-server -n androidmcp

echo "✅ Deployment complete!"
echo ""
echo "📝 Next steps:"
echo "  1. Verify pod status: kubectl get pods -n androidmcp"
echo "  2. Check logs: kubectl logs -f deployment/android-userspace-server -n androidmcp"
echo "  3. Port-forward: kubectl port-forward svc/android-userspace 8100:8100 -n androidmcp"
