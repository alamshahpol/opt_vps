#!/bin/sh
set -eu
umask 077
: "${WHATSAPP_AUTH_POLICY:?Private consumer policy required}"
: "${WHATSAPP_ACCOUNT_ALIAS:?Account alias required}"
case "${1:-}" in
 service) shift; : "${WHATSAPP_MCP_SOCKET:?Private Unix socket required}"
   exec /app/whatsapp-mcp-server/.venv/bin/python /app/whatsapp-mcp-server/service_supervisor.py "$@" ;;
 bridge) shift; exec /usr/local/bin/whatsapp-bridge "$@" ;;
 broker) shift; test "$#" -eq 0; : "${WHATSAPP_MCP_SOCKET:?Private Unix socket required}"
   exec /app/whatsapp-mcp-server/.venv/bin/python /app/whatsapp-mcp-server/consumer_broker.py ;;
 mcp) shift
   test "$#" -eq 0
   : "${WHATSAPP_CONSUMER_ID:?Consumer ID required}"
   : "${WHATSAPP_CONSUMER_TOKEN_FILE:?Scoped consumer token required}"
   export WHATSAPP_MCP_TRANSPORT=stdio
   exec /app/whatsapp-mcp-server/.venv/bin/python /app/whatsapp-mcp-server/main.py ;;
 *) echo 'Expected service, bridge, broker or mcp entrypoint' >&2; exit 64 ;;
esac
