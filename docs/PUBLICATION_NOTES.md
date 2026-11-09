# Public source snapshot boundaries

This portfolio preserves the selected source directory layout with a completely NEW Git history. It is not a mirror of the team-private repository.

Excluded: secrets, deployment credentials, user recordings/transcripts, customer data, evaluation response dumps, AI Hub datasets, nonredistributable model checkpoints, and internal administration/evidence files.

A source snapshot does not guarantee model-dependent end-to-end execution; external services, credentials and model artifacts are separate dependencies.

Individual contribution statements are distinct from the team source as a whole. Third-party models, visuals, fonts and content have independent redistribution requirements.

- The generated web/runtime-config.js contains an empty API URL; deployers supply their own HTTPS endpoint.
- The original intro-page evaluator test was excluded because it requires a private/generated artifacts/intro site tree, not the kiosk runtime.
