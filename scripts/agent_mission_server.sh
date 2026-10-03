#!/bin/bash
# scripts/agent_mission_server.sh — launchd wrapper for com.spa.mission_server (ADR-552).
#
# WHAT. The Mission Control web UI, served by TWO loopback-only listeners (security review
# finding #1, post-ADR-552): a LOCAL listener (this PORT, no Cloudflare Access config at all —
# it cannot serve the public host even if a request's Host header claims to be it) and a PUBLIC
# listener (its own port, MC_PUBLIC_PORT, default 8792) that starts ONLY when a public host is
# configured, and on which EVERY route requires a valid Cloudflare Access JWT with NO loopback
# exemption. Only the LOCAL listener is "ONLY 127.0.0.1, fixed route map, GET/HEAD" by itself; the
# PUBLIC listener adds the Access gate on top of the same guarantees.
#
# OWNER E-MAILS NEVER GO IN THIS GIT-TRACKED PLIST. Public-mode config (MC_PUBLIC_HOST,
# MC_ACCESS_AUD, MC_ACCESS_TEAM, MC_OWNER_EMAILS) must NOT be set as plist env vars — anything in
# the plist is in git, and MC_OWNER_EMAILS would publish the owner's e-mail address. Instead,
# mission_server.py reads an --access-config <path> JSON file OUTSIDE the repo (default
# ~/studio-os-serve/mission_access.json: {public_host, public_port, aud, team, owner_emails[]}),
# and refuses to start if that file exists but is not mode 0600 and owned by the current user.
#
# ENV VARS ARE ALSO EXPLICITLY STRIPPED BELOW (security review finding #6, second round), not
# just "not set here": mission_server.py reads MC_* env ONLY when called with --allow-env-config
# (this wrapper never passes it, and never should), and even then only when the access-config
# file is ABSENT — the file and env are never mixed. The `env -u ...` on the exec line is a second,
# independent layer: even if some future launchd plist edit, inherited shell profile, or other
# process accidentally exported one of these into this process's environment, it reaches neither
# argparse nor os.environ inside the module — belt-and-suspenders against exactly the failure mode
# this whole paragraph is about (a stray MC_OWNER_EMAILS leaking the owner's e-mail).
#
# TARGET DECLARED (MODULE below) so the static probe can check the wrapper WITHOUT starting it —
# for a long-lived process that is the only permitted check (.claude/rules/deployment.md).
#
# WHY NOT agent_template.sh. The same reason as agent_director_server.sh: the template is built
# for a finishing step (it calls code_sync and exits); this is a KeepAlive service, and fresh code
# reaches it by restarting the service, not through the wrapper.
#
# PATH AND PORT ARE FIXED. launchd does not inherit a shell; an empty variable would change what
# is served. The serve root is OUTSIDE the repository: generated owner data never lands in the
# public repo by any mistake. PORT here is the LOCAL listener; the public listener's port (if
# ever enabled) comes from the access-config file, not from this wrapper.
#
# Log: /tmp/spa_mission_server.log
MODULE="spa_core.studio_os.mission_server"
SERVE_ROOT="/Users/yuriikulieshov/studio-os-serve/mission"
PORT="8790"

cd /Users/yuriikulieshov/Documents/SPA_Claude || exit 78
exec /usr/bin/env -u MC_PUBLIC_HOST -u MC_ACCESS_AUD -u MC_ACCESS_TEAM -u MC_OWNER_EMAILS \
    -u MC_PUBLIC_PORT \
    /Users/yuriikulieshov/miniconda3/bin/python3 -m "$MODULE" \
    --root "$SERVE_ROOT" --port "$PORT" \
    >> /tmp/spa_mission_server.log 2>&1
