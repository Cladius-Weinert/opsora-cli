#!/bin/bash
# Opsora Marketing Hub - OpenShift Deployment Script
# Usage: ./deploy.sh [apply|delete|build|logs|status]

set -euo pipefail

NAMESPACE="opsora-dev"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUSTOMIZE_DIR="${SCRIPT_DIR}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

check_oc() {
    if ! command -v oc &> /dev/null; then
        log_error "OpenShift CLI (oc) not found. Please install it first."
        exit 1
    fi
    if ! oc whoami &> /dev/null; then
        log_error "Not logged into OpenShift. Run 'oc login' first."
        exit 1
    fi
}

check_kustomize() {
    if ! command -v kustomize &> /dev/null; then
        log_warning "kustomize not found, using 'oc apply -k' instead"
        KUSTOMIZE_CMD="oc apply -k"
    else
        KUSTOMIZE_CMD="kustomize build"
    fi
}

deploy() {
    log_info "Deploying Opsora Marketing Hub to OpenShift..."
    check_oc
    check_kustomize

    log_info "Applying manifests..."
    ${KUSTOMIZE_CMD} "${KUSTOMIZE_DIR}"

    log_info "Waiting for deployment to be ready..."
    oc rollout status deployment/opsora-marketing-hub -n "${NAMESPACE}" --timeout=300s

    log_success "Deployment complete!"
    log_info "Route: $(oc get route opsora-marketing-hub -n "${NAMESPACE}" -o jsonpath='{.spec.host}')"
}

delete_deployment() {
    log_warning "Deleting Opsora Marketing Hub from OpenShift..."
    check_oc
    oc delete -k "${KUSTOMIZE_DIR}" --ignore-not-found=true
    log_success "Deletion complete!"
}

build_image() {
    log_info "Starting OpenShift build..."
    check_oc

    oc start-build opsora-marketing-hub -n "${NAMESPACE}" --follow --wait

    log_success "Build complete!"
}

show_logs() {
    check_oc
    local pod=$(oc get pods -n "${NAMESPACE}" -l app=opsora-marketing-hub -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [[ -z "${pod}" ]]; then
        log_error "No pods found for opsora-marketing-hub"
        exit 1
    fi
    log_info "Showing logs for pod: ${pod}"
    oc logs -f "${pod}" -n "${NAMESPACE}" --all-containers=true
}

show_status() {
    check_oc
    log_info "Deployment Status:"
    oc get deployment opsora-marketing-hub -n "${NAMESPACE}" -o wide

    echo ""
    log_info "Pods:"
    oc get pods -n "${NAMESPACE}" -l app=opsora-marketing-hub -o wide

    echo ""
    log_info "Service:"
    oc get svc opsora-marketing-hub -n "${NAMESPACE}" -o wide

    echo ""
    log_info "Route:"
    oc get route opsora-marketing-hub -n "${NAMESPACE}" -o wide

    echo ""
    log_info "Builds:"
    oc get builds -n "${NAMESPACE}" -l app=opsora-marketing-hub -o wide
}

scale() {
    local replicas="${1:-2}"
    check_oc
    log_info "Scaling to ${replicas} replicas..."
    oc scale deployment opsora-marketing-hub -n "${NAMESPACE}" --replicas="${replicas}"
    oc rollout status deployment/opsora-marketing-hub -n "${NAMESPACE}" --timeout=300s
    log_success "Scaled to ${replicas} replicas!"
}

rollback() {
    check_oc
    log_info "Rolling back deployment..."
    oc rollout undo deployment/opsora-marketing-hub -n "${NAMESPACE}"
    oc rollout status deployment/opsora-marketing-hub -n "${NAMESPACE}" --timeout=300s
    log_success "Rollback complete!"
}

case "${1:-apply}" in
    apply|deploy)
        deploy
        ;;
    delete)
        delete_deployment
        ;;
    build)
        build_image
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    scale)
        scale "${2:-2}"
        ;;
    rollback)
        rollback
        ;;
    *)
        echo "Usage: $0 {apply|delete|build|logs|status|scale|rollback}"
        echo "  apply    - Deploy to OpenShift (default)"
        echo "  delete   - Delete all resources"
        echo "  build    - Trigger a new build"
        echo "  logs     - Follow pod logs"
        echo "  status   - Show deployment status"
        echo "  scale N  - Scale to N replicas"
        echo "  rollback - Rollback to previous revision"
        exit 1
        ;;
esac