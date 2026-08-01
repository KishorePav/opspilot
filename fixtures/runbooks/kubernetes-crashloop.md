# Kubernetes CrashLoopBackOff and exit code 137

Use this runbook when pods restart repeatedly, show CrashLoopBackOff, or exit
with code 137. Inspect the terminated container reason, restart count, recent
events, memory limit, node pressure, and the last successful deployment.

Exit code 137 commonly indicates an out-of-memory termination or forced kill.
Compare working-set memory with the configured request and limit. Check whether
a new release changed concurrency, cache size, payload size, or heap settings.

Do not solve the incident by removing memory limits. Roll back a correlated
release or make a bounded limit change through the normal approval process.
