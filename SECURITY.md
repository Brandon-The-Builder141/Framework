# Credentials and private data

Never commit passwords, API tokens, database credentials, private keys, `.env` files, conversation histories, or runtime databases. Use local environment variables and the supplied configuration examples. Keep secret values outside Git.

GitHub Actions scans all branch history for secrets on pushes and pull requests using a checksum-verified Gitleaks release. Findings are redacted in logs. A passing scan does not replace reviewing changes for private information.

If a credential is ever committed, revoke or rotate it at its provider immediately. Deleting a file or rewriting Git history does not invalidate an exposed credential. Do not restore older uncleaned local history into this repository.
