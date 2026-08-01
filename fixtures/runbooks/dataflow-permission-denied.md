# Dataflow service account permission denied

Use this runbook when a Dataflow launch or worker reports permission denied,
cannot act as a service account, or cannot access Pub/Sub and Cloud Storage.

Identify both the identity starting the job and the worker service account. The
launcher needs permission to act as the worker identity, while the worker needs
only the resource permissions required by the pipeline. Confirm that project,
subscription, topic, staging bucket, region, network, and service-account email
all belong to the intended environment.

Do not copy broad development roles into QA or production. Correct the IAM
binding at the narrowest scope and verify with a dry-run or non-production job.
