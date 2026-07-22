# MIT Open Learning — Lehrer Deployment Configuration

This directory contains MIT Open Learning's deployment-specific configuration
for building Open edX services with lehrer.

## Contents

| Directory / File | Purpose |
|---|---|
| `settings/` | Django settings for edx-platform (LMS + CMS) |
| `build_manifest.yaml` | Declarative edx-platform build cells (repo/branch, python/node, theme, translations, pip packages) — see `plans/06-build-manifest.md` |
| `mfe_slot_config/legacy/` | Slot configuration JSX files for legacy MFE builds |
| `mfe_slot_config/frontend/` | Future OEP-65 Site Project (see README inside) |
| `codejail_config/` | sudoers file for the codejail sandbox |
| `notes_config/` | `env_config.py` settings for edx-notes-api |
| `build.md` | Copy-pasteable `dagger call` commands for every service |

## Deployments supported

| Name | Description |
|---|---|
| `mitx` | MIT residential (MITx) |
| `mitxonline` | MITx Online |
| `mitx-staging` | MITx staging environment |
| `xpro` | MIT xPRO |

## Usage

See `build.md` for canonical invocations for each service.

## Relationship to lehrer core

All build logic lives in `src/lehrer/core/`.  This directory contains only
configuration and data files — no Python build code.  If you are an Open edX
operator building your own deployment, this directory is the reference
implementation of what a "deployment configuration" looks like.

See `docs/creating-a-deployment.md` for a guide to creating your own.
