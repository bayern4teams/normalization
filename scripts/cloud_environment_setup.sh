# Paste as the round2-env cloud environment's SETUP SCRIPT (docs/plans/round2/LAUNCH.md step 2).
# Self-contained on purpose: the setup script's working directory is NOT the repo. Rules learned the
# hard way (phase-kit LESSONS.md 3 and 4): (1) never pipe output through `tee`: an orphaned child
# (graft's postinstall downloader) kept the pipe open and setup hung for hours; redirect to a FILE.
# (2) every command is bounded with `timeout -k`. (3) graft is optional, so it is installed detached
# and can never block or fail setup. (4) the session must start even if an install fails. Only what
# must exist before Claude starts is installed here; the supervisor runs the project bootstrap inside
# the tick. The versions are scripts/refresh_graphs.py::PINS (a unit test keeps them equal).
{
date
export DO_NOT_TRACK=1
timeout -k 5 300 python3.11 -m venv /opt/graphtools || echo "FAILED: venv"
timeout -k 5 600 /opt/graphtools/bin/pip install -q --default-timeout=30 graphifyy==0.9.96 codebase-memory-mcp==0.12.1 || echo "FAILED: pip"
for t in graphify codebase-memory-mcp; do ln -sf /opt/graphtools/bin/$t /usr/local/bin/$t; done
DO_NOT_TRACK=1 setsid nohup timeout -k 5 300 npm install -g @nanonets/graft@0.26.0 > /tmp/graft_install.log 2>&1 < /dev/null &
for t in graphify codebase-memory-mcp; do command -v $t || echo "MISSING: $t"; done
date
} >> /tmp/cloud_setup.log 2>&1 < /dev/null
