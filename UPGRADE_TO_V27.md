# Product Hunter Pro v27 — Enterprise Foundation

This release prioritizes commercial reliability over feature count.

## New System Center

- Live SearXNG JSON endpoint health check
- OpenAI configuration check without exposing the API key
- Writable knowledge-database check
- Latency, status, details, and recommended action for each service
- Exportable diagnostics package
- Incident center with traceback inspection
- Operational activity log
- Commercial-readiness tracker

## Safe crash recovery

Unexpected application errors are now captured by a top-level error boundary. Users see a friendly incident ID instead of a raw traceback and can open System Center or retry the workspace.

## Structured observability

The app records structured JSONL events and incidents in a private runtime folder. Diagnostic exports redact secrets and include only configuration presence/status.

## Deployment

Replace the existing repository files with the contents of this folder, commit, and reboot Streamlit. Existing secrets remain unchanged.
