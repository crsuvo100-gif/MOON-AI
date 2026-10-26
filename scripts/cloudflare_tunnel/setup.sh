#!/usr/bin/env bash
#
# MOON Cloudflare Tunnel Setup
#
# Sets up a Cloudflare Tunnel to expose MOON's local instance to the internet.
# This provides a secure, always-on endpoint without port forwarding or
# exposing your local IP address.
#
# Prerequisites:
#   - Cloudflare account (free tier is fine)
#   - Cloudflare API token with "Tunnel" and "R2" permissions
#   - MOON running locally on port 8777
#
# Usage:
#   chmod +x scripts/cloudflare_tunnel/setup.sh
#   ./scripts/cloudflare_tunnel/setup.sh
#

set -euo pipefail

echo "=== MOON Cloudflare Tunnel Setup ==="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Step 1: Check prerequisites
info "Step 1: Checking prerequisites..."

# Check for cloudflared
if ! command -v cloudflared &>/dev/null; then
    info "Installing cloudflared..."
    if command -v apt &>/dev/null; then
        sudo apt install cloudflared -y
    elif command -v curl &>/dev/null; then
        sudo curl -fsSL https://pkg.cloudflare.com/cloudflare-main.pem -o /usr/share/pki/ca-trust-source/anchors/cloudflare.pem
        sudo update-ca-certificates
        sudo apt install cloudflared -y
    else
        error "Please install cloudflared manually from: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/install-linux/"
        exit 1
    fi
fi

# Check for wrangler
if ! command -v wrangler &>/dev/null; then
    info "Installing wrangler (Cloudflare CLI)..."
    npm install -g wrangler
fi

# Check for npm/node
if ! command -v node &>/dev/null || ! command -v npm &>/dev/null; then
    error "Node.js and npm are required. Please install them first."
    exit 1
fi

info "Prerequisites satisfied."
echo ""

# Step 2: Prompt for Cloudflare account ID
info "Step 2: Cloudflare Account Configuration"
echo "Please provide your Cloudflare account details."
read -rp "Cloudflare Account ID: " CLOUDFLARE_ACCOUNT_ID
read -rp "R2 Bucket name (leave empty for 'moon-online'): " R2_BUCKET
R2_BUCKET=${R2_BUCKET:-moon-online}

# Step 3: Create token (if not provided)
info "Step 3: Cloudflare API Token"
read -rp "Cloudflare API Token (leave empty to create a new one): " API_TOKEN
if [ -z "$API_TOKEN" ]; then
    info "Creating API token in cloudflare.com... (requires manual step)"
    warning "Please create an API token at https://dash.cloudflare.com/profile/api-tokens"
    warning "Grant these permissions:"
    warning "  - Cloudflare R2: Edit (or Read)"
    warning "  - Cloudflare Workers: Edit"
    warning "  - Cloudflare Tunnel: Edit"
    warning ""
    warning "Then re-run with your token: ./scripts/cloudflare_tunnel/setup.sh"
    exit 1
fi

# Step 4: Setupwrangler
info "Step 4: Configuring Wrangler..."

mkdir -p scripts/cloudflare_worker/src

# Check if wrangler.toml exists
if [ ! -f "scripts/cloudflare_worker/wrangler.toml" ]; then
    error "wrangler.toml not found"
    exit 1
fi

# Set secrets
echo "$API_TOKEN" | wrangler secret put CLOUDFLARE_ACCESS_KEY
echo "$API_TOKEN" | wrangler secret put CLOUDFLARE_SECRET_KEY

# Use environment variables or prompt for account ID
if [ -z "$CLOUDFLARE_ACCOUNT_ID" ]; then
    echo ""
    warning "Unable to read CLOUDFLARE_ACCOUNT_ID from environment."
    read -rp "Please enter your Cloudflare Account ID: " CLOUDFLARE_ACCOUNT_ID
    info "Writing wrangler.toml with your Account ID..."
    sed -i "s/CLOUDFLARE_ACCOUNT_ID/$CLOUDFLARE_ACCOUNT_ID/g" scripts/cloudflare_worker/wrangler.toml
else
    info "Using existing CLOUDFLARE_ACCOUNT_ID"
fi

info "Wrangler configured."
echo ""

# Step 5: Deploy the Worker
info "Step 5: Deploying Cloudflare Worker..."
info "This may take a minute..."
wrangler deploy scripts/cloudflare_worker/

if [ $? -eq 0 ]; then
    info "Worker deployed successfully!"
else
    error "Worker deployment failed"
    exit 1
fi

info "Worker URL: https://moon-online.your-subdomain.workers.dev"
echo ""

# Step 6: Setup Cloudflare Tunnel
info "Step 6: Setting up Cloudflare Tunnel..."

# Create the tunnel
cloudflared tunnel create moon-online

# Get the tunnel ID
TUNNEL_ID=$(cloudflared tunnel list | grep moon-online | awk '{print $1}')
if [ -z "$TUNNEL_ID" ]; then
    error "Failed to create tunnel"
    exit 1
fi

info "Tunnel ID: $TUNNEL_ID"
echo ""

# Create the tunnel configuration
cat > moon-online.yaml << EOF
# MOON Tunnel Configuration
tunnel: $TUNNEL_ID
credential-file: /home/meow/.cloudflared/$(cat /home/meow/.cloudflared/*.json | python3 -c "import sys, json; print([k for k in json.load(sys.stdin) if k.startswith('cert.')][0])" 2>/dev/null || echo "moontunnel.json")
hostname: moon.twin.ai
service: http://localhost:8777
originRequest:
  disableProxyProtocol: true
EOF

# Verify the tunnel credentials
TOKEN_PATH=$(ls /home/meow/.cloudflared/*.json 2>/dev/null | head -1)
if [ -z "$TOKEN_PATH" ]; then
    info "Cloudflare tunnel credentials not auto-detected, please configure manually."
else
    info "Tunnel credentials found."
fi

# Step 7: Run the tunnel
info "Step 7: Running Cloudflare Tunnel"
info "The tunnel will run in the background and keep MOON always online."
info ""
info "To start the tunnel now (background mode):"
echo "  cloudflared tunnel run moon-online"
info ""
info "To run the tunnel on system startup, add this to your .bashrc or use systemd:"
echo "  nohup cloudflared tunnel run moon-online &"
echo ""

# Step 8: Setup MOON data sync
info "Step 8: Setting up MOON data sync (optional)"
info "MOON data can be backed up to R2 using the following commands:"
echo "  # Install the sync script"
echo "  cd /home/meow/Projects/MOON"
echo "  pip install boto3"
echo ""
echo "  # Test the sync (requires R2 credentials)"
echo "  python scripts/moon_online/moon_sync.py --account-id $CLOUDFLARE_ACCOUNT_ID --bucket $R2_BUCKET --access-key <KEY> --secret-key <SECRET> --dry-run"
echo ""

# Cleanup
info "Setup complete!"
echo ""
echo "=== Summary ==="
echo "  Worker deployed: https://moon-online.your-subdomain.workers.dev"
echo "  Tunnel ID: $TUNNEL_ID"
echo "  Next steps:"
echo "    1. Start the tunnel: cloudflared tunnel run moon-online"
echo "    2. Configure MOON to use the worker URL"
echo "    3. Set up MOON sync via scripts/moon_online/moon_sync.py"
echo ""
echo "Enjoy your always-online MOON!"
