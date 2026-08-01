# Engineering evidence policy

This repository is intended to demonstrate decisions and verified engineering
work, not contribution volume.

## Accepted evidence

- passing unit, integration, and security tests;
- versioned evaluation datasets and reproducible metrics;
- load-test inputs, environment details, and percentile results;
- architecture decision records with alternatives and consequences;
- runnable demos whose limitations are stated;
- CI results tied to the commit being discussed.

## Rejected evidence

- fabricated users, revenue, customer deployments, incidents, or scale;
- unsupported accuracy and latency claims;
- backdated commits or generated micro-commits intended to simulate duration;
- private employer artifacts presented as public project work;
- screenshots without a reproducible command or documented environment.

Fast implementation is not itself suspicious. The proof is whether the author
can explain the trade-offs, reproduce the results, diagnose failures, and extend
the system under interview conditions.

## Milestone 3 acceptance evidence

The single-investigator milestone is accepted only when automated tests prove:

- a model-selected sequence can collect runbook, log, deployment, and metric
  evidence and return a typed report;
- every cited ID belongs to the successful-call evidence ledger;
- invented citations fail closed;
- service and environment scope cannot expand beyond the incident request;
- repeated calls and bounded-resource exhaustion cannot loop indefinitely;
- model-provider credentials are unnecessary for the unit and API test suites.

These tests prove contracts and failure behavior. They do not prove live-model
diagnostic accuracy, production security, or customer impact.
