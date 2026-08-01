# Synthetic demo deployment

The demo container exposes only the allowlisted replay UI and API. It requires
no database, identity provider, OpenAI credential, or outbound integration.

Build and verify it:

```bash
docker build --target demo -t opspilot-demo:0.8.0 .
docker run --rm -p 8081:8080 --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  opspilot-demo:0.8.0
curl --fail http://127.0.0.1:8081/api/scenarios
```

For Cloud Run, push this exact `demo` target to Artifact Registry and deploy it
with unauthenticated ingress only after confirming the image digest. Set a low
maximum instance count and concurrency appropriate for a portfolio site. Do not
attach secrets, a VPC connector, database access, or service-account roles; the
demo does not use them.

The production API image is the Dockerfile's default `api` target. Do not make
that authenticated workflow API public as a substitute for the demo.
