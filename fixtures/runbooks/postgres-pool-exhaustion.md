# PostgreSQL connection pool exhaustion

Use this runbook when API latency and timeouts increase while available database
connections fall to zero. Check active, idle, and waiting sessions; pool wait
time; query duration; transaction age; application replica count; and database
connection limits.

Common causes include leaked connections, slow queries, transactions held open,
or multiplying a per-instance pool across a new scale-out event. Increasing the
pool can make database contention worse.

Stop the leak or slow-query source, bound acquisition timeouts, and size the
aggregate pool against database capacity. Terminating sessions is a controlled
action and requires incident approval.
