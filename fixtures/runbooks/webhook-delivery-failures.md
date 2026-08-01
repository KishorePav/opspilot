# Webhook delivery failures and HTTP 500 responses

Use this runbook when webhook deliveries return HTTP 500, retry repeatedly, or
accumulate in a delivery queue. Confirm the destination, event type, response
code, latency, retry count, and whether failures began after a sender or receiver
deployment.

Validate signatures before processing, make handlers idempotent, and return a
success response only after durable acceptance. Use exponential backoff with
jitter and a dead-letter path for exhausted deliveries.

Do not replay the full backlog until the receiver is healthy and duplicate side
effects have been assessed. A bulk replay is an approval-gated action.
