# Infrastructure Components — Design Notes

> **Status:** Planned — not yet implemented.

## Motivation

The `lehrer.infra` package will contain Pulumi ComponentResource classes for
deploying the container images produced by `lehrer.core` to cloud
infrastructure.  The goal is the same as `lehrer.core`: generic,
parameterizable components that any Open edX operator can use, with
This module is the Dagger entry point and contains a thin root type.  The
generic build pipelines live in ``lehrer.core``, and operator-specific
configuration lives separately in each operator's own config directory.

## Intended scope

- ECS / Fargate task definitions for LMS, CMS, Workers
- RDS (MySQL) and ElastiCache (Redis) components
- S3 + CloudFront for static asset hosting
- ALB + Route 53 DNS

## Open questions

- Should infra components live in this Python package (imported by a
  separate Pulumi program) or as a standalone Pulumi component provider?
- How do Dagger-built image digests get threaded into Pulumi stack config?

## Cross-references

- `plans/02-pulumi-codejail-component.md` — first planned infra component
- Operator configuration is kept outside of this package, in operator-owned config directories
