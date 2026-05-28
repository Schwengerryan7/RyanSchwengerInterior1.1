#!/bin/bash
# Kill any existing proxy
pkill -f "node proxy.js" 2>/dev/null
sleep 1

# Start proxy with both API keys
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
RUNPOD_API_KEY="${RUNPOD_API_KEY}" \
node proxy.js
