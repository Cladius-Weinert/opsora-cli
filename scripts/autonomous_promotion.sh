#!/bin/bash
"""
Opsora Autonomous Promotion Script
Runs daily to generate content, broadcast to all platforms, and track analytics.

Usage:
    bash scripts/autonomous_promotion.sh              # Run full pipeline
    bash scripts/autonomous_promotion.sh --dry-run    # Preview only
    bash scripts/autonomous_promotion.sh --status     # Show status
"""

set -e

OPSORA_DIR="/root/opsora-cli"
LOG_DIR="$OPSORA_DIR/marketing_hub/logs"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
DATE=$(date '+%Y-%m-%d')

mkdir -p "$LOG_DIR"

log() {
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_DIR/promotion.log"
}

# =========================================================================
# Status Check
# =========================================================================

check_status() {
    echo ""
    echo "📡 Opsora Promotion System Status"
    echo "=================================="
    echo ""

    # Check MCP servers
    echo "🔌 MCP Servers:"
    echo "  Telegram: $(python3 -c "import os; print('✅' if os.path.exists('/root/.telegram-mcp/opsora.session') else '⚠️ No session')" 2>/dev/null || echo '❌ Error')"
    echo "  Google: $(python3 -c "import os; print('✅' if os.path.exists('/root/.google_auth/tokens') else '⚠️ No tokens')" 2>/dev/null || echo '❌ Error')"
    echo "  GitHub: $(which gh &>/dev/null && echo '✅ CLI ready' || echo '❌ No CLI')"
    echo ""

    # Check API keys
    echo "🔑 API Keys:"
    echo "  NVIDIA: $(test -n \"$NVIDIA_API_KEY\" && echo '✅ Set' || echo '❌ Not set')"
    echo "  DashScope: $(test -n \"$DASHSCOPE_API_KEY\" && echo '✅ Set' || echo '❌ Not set')"
    echo "  Twitter: $(test -n \"$TWITTER_API_KEY\" && echo '✅ Set' || echo '⚠️ Not set')"
    echo ""

    # Check marketing hub
    echo "📦 Marketing Hub:"
    for f in autonomous_engine.py broadcaster.py content_strategy.py analytics.py; do
        if [ -f "$OPSORA_DIR/marketing_hub/$f" ]; then
            echo "  ✅ $f"
        else
            echo "  ❌ $f (missing)"
        fi
    done
    echo ""

    # Check docs
    echo "📚 Documentation:"
    for f in README.md ARCHITECTURE.md DEPLOYMENT.md PROVIDERS.md MCP_SERVERS.md EXTENSIONS.md CONTRIBUTING.md REFACTORING_PLAN.md; do
        if [ -f "$OPSORA_DIR/$f" ]; then
            SIZE=$(wc -c < "$OPSORA_DIR/$f")
            echo "  ✅ $f ($SIZE bytes)"
        else
            echo "  ❌ $f (missing)"
        fi
    done
    echo ""

    # Check tests
    echo "🧪 Tests:"
    TEST_COUNT=$(find "$OPSORA_DIR/tests" -name 'test_*.py' 2>/dev/null | wc -l)
    echo "  Test files: $TEST_COUNT"
    echo ""

    # Check deployments
    echo "🚀 Deployments:"
    echo "  Landing Page: https://opsora-landing-zeta.vercel.app"
    echo "  API Docs: https://cladius-weinert.github.io/opsora-api-docs/"
    echo "  API Gateway: http://localhost:8080"
    echo ""

    # Check git
    echo "📂 Git Status:"
    cd "$OPSORA_DIR"
    git status --short 2>/dev/null | head -20 || echo "  Not a git repo"
    echo ""
}

# =========================================================================
# Content Generation
# =========================================================================

generate_content() {
    log "📝 Generating content..."
    python3 -m marketing_hub.content_strategy generate --type "$1" --lang both 2>&1 | tee -a "$LOG_DIR/content_$DATE.log"
    log "✅ Content generated"
}

# =========================================================================
# Broadcasting
# =========================================================================

broadcast() {
    log "📢 Broadcasting to all platforms..."
    python3 -m marketing_hub.broadcaster post --text "$1" --platform all 2>&1 | tee -a "$LOG_DIR/broadcast_$DATE.log"
    log "✅ Broadcast complete"
}

# =========================================================================
# Analytics
# =========================================================================

record_analytics() {
    log "📊 Recording analytics..."
    python3 -m marketing_hub.analytics report --days 7 2>&1 | tee -a "$LOG_DIR/analytics_$DATE.log"
    log "✅ Analytics recorded"
}

# =========================================================================
# Main Pipeline
# =========================================================================

run_pipeline() {
    DRY_RUN=${1:-false}

    log "🚀 Opsora Autonomous Promotion Pipeline"
    log "========================================"
    log "Date: $DATE"
    log ""

    # Determine content type based on day of week
    DAY=$(date '+%u')  # 1=Monday, 7=Sunday
    case $DAY in
        1) CONTENT_TYPE="intro" ;;
        2) CONTENT_TYPE="tips" ;;
        3) CONTENT_TYPE="feature" ;;
        4) CONTENT_TYPE="engagement" ;;
        5) CONTENT_TYPE="testimonial" ;;
        6) CONTENT_TYPE="tips" ;;
        7) CONTENT_TYPE="digest" ;;
    esac

    log "📋 Today: $(date '+%A') - Content: $CONTENT_TYPE"

    if [ "$DRY_RUN" = true ]; then
        log "🏁 DRY RUN - No actions executed"
        python3 -m marketing_hub.content_strategy generate --type "$CONTENT_TYPE" --lang both
        exit 0
    fi

    # Step 1: Generate content
    log "Step 1/4: Generating content..."
    python3 -m marketing_hub.content_strategy generate --type "$CONTENT_TYPE" --lang both 2>&1 | tee "$LOG_DIR/content_$DATE.txt"

    # Read generated content
    CONTENT=$(cat "$LOG_DIR/content_$DATE.txt" 2>/dev/null || echo "Opsora AI update for $DATE")

    # Step 2: Broadcast
    log "Step 2/4: Broadcasting..."
    python3 -m marketing_hub.broadcaster post --text "$CONTENT" --platform all 2>&1 | tee "$LOG_DIR/broadcast_$DATE.txt"

    # Step 3: Record analytics
    log "Step 3/4: Recording analytics..."
    python3 -m marketing_hub.analytics track --platform all --metric campaigns_completed --value 1 2>&1
    python3 -m marketing_hub.analytics report --days 1 2>&1 | tee "$LOG_DIR/analytics_$DATE.txt"

    # Step 4: Generate report
    log "Step 4/4: Generating report..."
    python3 -m marketing_hub.analytics report --days 7 --format json 2>&1 | tee "$LOG_DIR/report_$DATE.json"

    log ""
    log "✅ Pipeline complete!"
    log "📁 Logs: $LOG_DIR/"
}

# =========================================================================
# Entry Point
# =========================================================================

case "${1:-pipeline}" in
    status)
        check_status
        ;;
    pipeline)
        run_pipeline false
        ;;
    --dry-run)
        run_pipeline true
        ;;
    --status)
        check_status
        ;;
    *)
        echo "Usage: $0 [pipeline|status|--dry-run]"
        echo ""
        echo "Commands:"
        echo "  pipeline     Run full promotion pipeline (default)"
        echo "  status       Show system status"
        echo "  --dry-run    Preview content without broadcasting"
        exit 1
        ;;
esac