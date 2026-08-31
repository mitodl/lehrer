# Infrastructure Components — Design Notes

> **Status:** Planned — not yet implemented.

## Motivation

The `lehrer.infra` package will contain Pulumi ComponentResource classes for
deploying the container images produced by `lehrer.core` to cloud
infrastructure.  The goal is the same as `lehrer.core`: generic,
parameterizable components that any Open edX operator can use, with
operator-specific configuration supplied from outside the package.

That split already holds for the build side.  `src/lehrer/main.py` is the
Dagger entry point and carries only a thin root type; the generic build
pipelines live in `lehrer.core`, and operator-specific configuration lives in
each operator's own config directory, outside this package.  The
`lehrer-core-boundary` pre-commit hook keeps it that way by rejecting
operator-specific strings under `lehrer.core` and `lehrer.infra`, this file
included.  Each package's `__init__.py` is excluded from the hook, so the
policy holds there by convention rather than by enforcement.

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

- Deployment topology lives in the operator's own infrastructure repository,
  not here: lehrer owns build definitions, the infrastructure repo owns
  deployment topology.
- Operator configuration is kept outside of this package, in operator-owned
  config directories.
