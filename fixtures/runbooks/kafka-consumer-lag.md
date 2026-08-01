# Kafka consumer lag and group rebalancing

Use this runbook when consumer lag rises, partitions stop making progress, or
workers repeatedly leave and rejoin a consumer group after a deployment.

Confirm the affected topic, consumer group, partition count, current offsets,
and deployment version. Compare incoming record rate with processing throughput.
Repeated rebalancing commonly follows slow processing, an aggressive session
timeout, unstable workers, or more consumers than useful partitions.

Check downstream database latency before increasing consumers. Pause a rollout
when the new version correlates with lag growth. Never reset offsets without an
approved recovery point and a documented duplicate-processing assessment.
