# Lehrer - OpenEdx Platform Build Pipeline

A Dagger module for building and deploying Open edX platform images and related services. This module provides composable and reusable functions based on the MIT ODL Earthly build process.

## Overview

This module replaces the Earthly-based build pipeline with Dagger, providing:

- **Composable functions** - Build steps can be used independently or chained together
- **Flexibility** - Support for multiple deployments with different configurations
- **Multiple services** - Build platform, codejail, and edx-notes containers
- **Reproducibility** - Consistent builds across environments
- **Efficiency** - Leverages Dagger's caching and parallelization

## Architecture

The build pipeline follows these stages:

1. **apt-base** - Base Python container with system dependencies and uv
2. **locales** - Download OpenEdx i18n locale files
3. **get-code** - Get edx-platform source (local or Git)
4. **install-deps** - Install Python and Node.js dependencies using uv
5. **themes** - Get theme files (local or Git)
6. **tutor-utils** - Get utility scripts from Tutor
7. **collected** - Assemble artifacts and configure container
8. **fetch-translations** - Pull and compile translations
9. **build-static-assets** - Build and collect static assets
10. **docker-image** - Finalize for deployment
11. **publish-platform** - Publish to container registry

### Key Optimizations

- **uv for Python dependencies** - Uses Astral's uv instead of pip for significantly faster dependency resolution and installation
- **Bytecode compilation** - Pre-compiles Python bytecode during dependency installation for faster startup
- **Docker caching** - Leverages Dagger's caching for efficient rebuilds

## Functions

### Core Build Functions

#### `apt-base`
Creates base Python container with system dependencies and uv binary.

```bash
dagger call apt-base --python-version 3.11
```

#### `get-code`
Gets edx-platform source code from local directory or Git.

```bash
# From Git
dagger call apt-base get-code \
  --edx-platform-git-repo "https://github.com/openedx/edx-platform" \
  --edx-platform-git-branch "open-release/sumac.master"

# From local directory
dagger call apt-base get-code \
  --source ../edx-platform
```

#### `install-deps`
Installs Python and Node.js dependencies using uv for faster installation.

```bash
dagger call apt-base get-code \
  --edx-platform-git-repo "..." \
  --edx-platform-git-branch "..." \
  install-deps \
  --deployment-name mitxonline \
  --release-name sumac \
  --pip-package-lists ./pip_package_lists \
  --pip-package-overrides ./pip_package_overrides
```

### Convenience Functions

#### `build-platform`
Chains all build steps together for a complete build.

```bash
dagger call build-platform \
  --deployment-name mitxonline \
  --release-name sumac \
  --pip-package-lists ./pip_package_lists \
  --pip-package-overrides ./pip_package_overrides \
  --custom-settings ./settings \
  --edx-platform-git-branch "open-release/sumac.master" \
  --theme-git-repo "https://github.com/mitodl/mitxonline-theme" \
  --theme-git-branch "main"
```

#### `publish-platform`
Publishes the built image to a container registry.

```bash
dagger call build-platform \
  [...build args...] \
  publish-platform \
  --registry ghcr.io \
  --repository mitodl/openedx-mitxonline \
  --tag sumac-latest \
  --username $GITHUB_USER \
  --password env:GITHUB_TOKEN
```

## Required Inputs

### Directory Structures

#### `pip_package_lists/`
Contains pip requirements files organized by release and deployment:

```
pip_package_lists/
├── sumac/
│   ├── mitx.txt
│   └── mitxonline.txt
└── redwood/
    ├── mitx.txt
    └── mitxonline.txt
```

#### `pip_package_overrides/`
Contains pip override requirements (e.g., for lxml/xmlsec fixes):

```
pip_package_overrides/
├── sumac/
│   ├── mitx.txt
│   └── mitxonline.txt
└── redwood/
    ├── mitx.txt
    └── mitxonline.txt
```

#### `custom_settings/`
Contains custom Django settings and configuration files:

```
custom_settings/
├── lms.env.yml
├── cms.env.yml
├── lms/
│   ├── assets.py
│   └── i18n.py
├── cms/
│   ├── assets.py
│   └── i18n.py
├── lms_settings.py
├── cms_settings.py
├── models.py
├── utils.py
├── set_waffle_flags.py
├── process_scheduled_emails.py
└── saml_pull.py
```

## Examples

### Build for Multiple Deployments

```bash
# Build mitxonline
dagger call build-platform \
  --deployment-name mitxonline \
  --release-name sumac \
  [...common args...]

# Build mitx
dagger call build-platform \
  --deployment-name mitx \
  --release-name sumac \
  [...common args...]
```

### Use Local Source for Development

```bash
dagger call build-platform \
  --deployment-name mitxonline \
  --release-name sumac \
  --source ../edx-platform \
  --theme-source ../mitxonline-theme \
  [...other args...]
```

### Build Without Locales (for mitxonline)

```bash
dagger call build-platform \
  --deployment-name mitxonline \
  --release-name sumac \
  --include-locales false \
  [...other args...]
```

### Python Version Selection

By default:
- **master branch**: Uses Python 3.12
- **Other releases (sumac, redwood, etc.)**: Use Python 3.11

Override with `--python-version`:
```bash
dagger call build-platform \
  --deployment-name mitxonline \
  --release-name master \
  --python-version 3.11 \
  [...other args...]
```

### Building Codejail Service

The codejail service provides sandboxed Python execution for running student code:

```bash
# Build codejail for master (Python 3.12)
dagger call build-codejail --release-name master

# Build codejail for sumac release (Python 3.11)
dagger call build-codejail --release-name sumac

# Override Python version
dagger call build-codejail --release-name master --python-version 3.11
```

Codejail automatically installs the appropriate edx-platform sandbox requirements based on the release.

### Building edx-notes Service

The edx-notes-api service provides student annotation functionality:

```bash
# Build notes for master branch
dagger call build-notes --release-name master

# Build notes for specific release
dagger call build-notes --release-name open-release/sumac.master

# Use different Python version (default is 3.11)
dagger call build-notes --release-name master --python-version 3.9
```

**Note**: edx-notes-api master branch requires Python 3.9+. Older releases may work with Python 3.8.

### Publishing Service Images

Both codejail and notes images can be published using standard container commands:

```bash
# Build and publish codejail
dagger call build-codejail --release-name sumac \
  publish \
  --address ghcr.io/mitodl/openedx-codejail:sumac

# Build and publish notes
dagger call build-notes --release-name master \
  publish \
  --address ghcr.io/mitodl/openedx-notes:latest
```

## Differences from Earthfile

### Key Changes

1. **Explicit arguments** - All parameters must be passed explicitly (no file copying from context)
2. **Directory mounting** - Use `--source`, `--theme-source` for local directories
3. **No LOCALLY** - All operations run in containers
4. **Function composition** - Chain functions for flexibility

### Migration Notes

- Replace `COPY` commands with directory/file mounting
- Replace `ARG --required` with required function parameters
- Use `build-platform` for complete builds or compose individual functions
- Package lists and overrides must be passed as directories

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Build OpenEdx Image
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build and publish
        uses: dagger/dagger-for-github@v5
        with:
          version: "latest"
          verb: call
          args: |
            build-platform
            --deployment-name mitxonline
            --release-name sumac
            --pip-package-lists ./pip_package_lists
            --pip-package-overrides ./pip_package_overrides
            --custom-settings ./settings
            --edx-platform-git-branch open-release/sumac.master
            --theme-git-repo https://github.com/mitodl/mitxonline-theme
            --theme-git-branch main
            publish-platform
            --registry ghcr.io
            --repository mitodl/openedx-mitxonline
            --tag ${{ github.sha }}
            --username ${{ github.actor }}
            --password env:GITHUB_TOKEN
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Development

### Running Locally

```bash
# Install dependencies
uv sync

# List available functions
dagger functions

# Get help on a function
dagger call build-platform --help

# Test a build step
dagger call apt-base stdout
```

### Adding New Functions

1. Add function to `src/lehrer/main.py`
2. Follow naming convention (snake_case becomes kebab-case in CLI)
3. Add docstrings with Args and Returns sections
4. Update this README with examples

## License

BSD-3-Clause