# Contributing

Changes should be small enough to review as one idea and large enough to carry
meaning. A normal feature branch may contain several commits when each captures
a useful checkpoint; do not split changes to make the activity graph appear
busier.

Every pull request should include:

- the problem and acceptance criteria;
- the architecture decision or trade-off;
- tests, evaluations, or benchmark commands;
- known limitations and deferred work;
- screenshots or traces only when they add verifiable evidence.

Use `make check` before requesting review. Never add private operational data or
credentials to fixtures.

`make eval-live` is intentionally excluded from `make check`. Do not run it for
a pull request, add a provider key to CI, or publish a live-quality claim unless
the protected manual workflow produced a commit-linked artifact. The synthetic
demo must remain a separate allowlisted application with no arbitrary prompt or
remediation route.
