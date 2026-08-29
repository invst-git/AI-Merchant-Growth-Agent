# Razorpay MCP Server — setup notes (Phase 0)

The official Razorpay MCP Server (github.com/razorpay/razorpay-mcp-server)
has two deployment options. Neither has a published price — both are free
in the sense that you're only ever calling your own Razorpay Test Mode
account; the "cost" question is really "which one needs zero extra
infrastructure."

## Recommended for this project: Remote / Hosted

Razorpay runs this for you at `https://mcp.razorpay.com/mcp`. You reach it
through the `mcp-remote` bridge via `npx`, so nothing needs to be
installed or built — Node is already on this machine (checked: v22.23.2 /
npm 10.9.8). This is the option to use unless a later phase specifically
needs the extra control of self-hosting.

Auth is HTTP Basic, built from your own Key ID and Key Secret:

    echo -n "<RAZORPAY_KEY_ID>:<RAZORPAY_KEY_SECRET>" | base64

Run that yourself (locally, not pasted to Claude — see
`scripts/make_mcp_auth_header.sh` for a helper that does this from your
`.env` without printing the secret to a shared terminal transcript) and
drop the result into `claude_desktop_config.example.json` in place of
`<base64-key:secret>`, then save it as `claude_desktop_config.json`
(gitignored) or wherever your MCP client of choice reads its config from.

## Alternative: Self-hosted via Docker

`docker-mcp-config.example.json` in this folder is the equivalent config
for running the server yourself (`docker run ... razorpay/mcp`), for full
control over the tool surface / logging. This machine's Linux sandbox
doesn't have Docker installed, so this path wasn't smoke-tested here —
use it from wherever Docker *is* available (e.g. directly on the Windows
machine, if Docker Desktop is installed there) if you'd rather not depend
on Razorpay's hosted endpoint.

## Test-mode note

The server takes whatever `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` you
give it — test keys (`rzp_test_...`) work the same way live keys would.
There is nothing test-specific to configure beyond using your test
credentials.
