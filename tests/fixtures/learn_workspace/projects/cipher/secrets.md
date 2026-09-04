# Secrets Handling

This document explains how the team handles credentials. It contains no credentials.

- Never commit a credential. Use the platform keychain.
- Rotate deploy tokens quarterly.
- Secrets are injected at runtime, never baked into an image.
