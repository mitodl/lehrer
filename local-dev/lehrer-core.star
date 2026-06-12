# lehrer-core.star — reusable Tilt logic for lehrer-based Open edX deployments.
#
# This file is NOT a standalone Tiltfile. It must be include()'d from a root Tiltfile
# that has already called config.parse() and set the following globals:
#
#   LEHRER_DEPLOY_CONFIG   — path to deployment config dir (e.g. deployments/generic)
#   LEHRER_REGISTRY        — host-side registry URL for pushing (e.g. localhost:5100)
#   LEHRER_REGISTRY_K8S    — cluster-side registry URL for pulling (e.g. k3d-lehrer-registry:5000)
#   LEHRER_REDIS_HOST      — Redis/Valkey service hostname (cluster-internal)
#   LEHRER_OPENSEARCH_HOST — OpenSearch service hostname (cluster-internal)
#   LEHRER_NAMESPACE       — Kubernetes namespace (e.g. openedx)
#   LEHRER_MANAGE_INFRA    — bool: install MySQL/MongoDB/Redis/OpenSearch via Helm
#   LEHRER_MYSQL_MANAGED   — bool: install MySQL via Helm (independent of MANAGE_INFRA)
#   LEHRER_MONGO_MANAGED   — bool: install MongoDB via Helm (independent of MANAGE_INFRA)
#   LEHRER_INGRESS         — "traefik" or "apisix"
#   LEHRER_MFE_HOT_RELOAD  — bool: also start watch_site dev servers
#   LEHRER_RELEASE_NAME    — Open edX release name (e.g. "master", "redwood")
#   LEHRER_DEPLOY_NAME     — deployment name matching pip_package_lists filename
#   LEHRER_SETTINGS_NS     — settings namespace (e.g. "production")
#   LEHRER_NOTES_REPO      — notes git repo URL (e.g. https://github.com/openedx/edx-notes-api)
#   LEHRER_HELM_OVERRIDE_DIR — path to dir with override Helm values (set to "" if none)
#   LEHRER_LOCAL_DEV_DIR   — absolute path to lehrer/local-dev/ (set to config.main_dir in standalone)
#   LEHRER_APPLY_PLATFORM_CONFIGMAPS — bool: apply manifests/platform/configmap-*.yaml (set False in
#                             integration mode where the caller applies its own configmaps)
#
# Informational globals (set by root Tiltfiles for documentation; not read here):
#   LEHRER_LMS_BASE_URL    — public LMS URL for browser access
#   LEHRER_CMS_BASE_URL    — public CMS URL for browser access
#   LEHRER_NOTES_PUBLIC_URL — public Notes API URL for browser access

load('ext://helm_resource', 'helm_resource', 'helm_repo')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lehrer_root():
    # LEHRER_LOCAL_DEV_DIR is always set to lehrer/local-dev/; walk up one level.
    return LEHRER_LOCAL_DEV_DIR + "/.."

def _deploy_cfg():
    cfg = LEHRER_DEPLOY_CONFIG
    # If relative, resolve against the lehrer repo root.
    if not cfg.startswith("/"):
        cfg = _lehrer_root() + "/" + cfg
    return cfg

def _local_dev_dir():
    # When included from ol-infrastructure, config.main_dir is the ol-infra root.
    # LEHRER_LOCAL_DEV_DIR must always be set to the absolute path of lehrer/local-dev/.
    return LEHRER_LOCAL_DEV_DIR

def _img(name):
    return LEHRER_REGISTRY_K8S + "/" + name + ":dev"

def _push_addr(name):
    return LEHRER_REGISTRY + "/" + name + ":dev"

def _notes_repo():
    # LEHRER_NOTES_REPO is optional; callers that don't set it get the upstream default.
    # Starlark can't check for undefined globals, so the root Tiltfile must always set this.
    return LEHRER_NOTES_REPO

# ---------------------------------------------------------------------------
# Infrastructure (Helm)
# ---------------------------------------------------------------------------

helm_repo('bitnami', 'https://charts.bitnami.com/bitnami', labels=["infra"])
helm_repo('opensearch-helm', 'https://opensearch-project.github.io/helm-charts', labels=["infra"])

# _helm_values resolves a Helm values filename: uses LEHRER_HELM_OVERRIDE_DIR if
# the override file exists there, otherwise falls back to lehrer/local-dev/helm/.
# All root Tiltfiles must set LEHRER_HELM_OVERRIDE_DIR (to "" if not overriding).
def _helm_values(filename):
    if LEHRER_HELM_OVERRIDE_DIR:
        override = LEHRER_HELM_OVERRIDE_DIR + "/" + filename
        if os.path.exists(override):
            return override
    return _local_dev_dir() + "/helm/" + filename

helm_dir = _local_dev_dir() + "/helm"

if LEHRER_MANAGE_INFRA or LEHRER_MYSQL_MANAGED:
    helm_resource(
        'mysql',
        'bitnami/mysql',
        namespace=LEHRER_NAMESPACE,
        flags=[
            '--values', _helm_values('mysql-values.yaml'),
            '--create-namespace',
        ],
        labels=["infra"],
    )

if LEHRER_MANAGE_INFRA or LEHRER_MONGO_MANAGED:
    helm_resource(
        'mongodb',
        'bitnami/mongodb',
        namespace=LEHRER_NAMESPACE,
        flags=[
            '--values', _helm_values('mongodb-values.yaml'),
            '--create-namespace',
        ],
        labels=["infra"],
    )

if LEHRER_MANAGE_INFRA:
    helm_resource(
        'redis',
        'bitnami/redis',
        namespace=LEHRER_NAMESPACE,
        flags=[
            '--values', _helm_values('redis-values.yaml'),
            '--create-namespace',
        ],
        labels=["infra"],
    )
    helm_resource(
        'opensearch',
        'opensearch-helm/opensearch',
        namespace=LEHRER_NAMESPACE,
        flags=[
            '--values', _helm_values('opensearch-values.yaml'),
            '--create-namespace',
        ],
        labels=["infra"],
    )

# ---------------------------------------------------------------------------
# Determine infra dependencies for application resources
# ---------------------------------------------------------------------------

_infra_deps = []
if LEHRER_MANAGE_INFRA or LEHRER_MYSQL_MANAGED:
    _infra_deps.append("mysql")
if LEHRER_MANAGE_INFRA or LEHRER_MONGO_MANAGED:
    _infra_deps.append("mongodb")
if LEHRER_MANAGE_INFRA:
    _infra_deps.append("redis")
    _infra_deps.append("opensearch")

# ---------------------------------------------------------------------------
# Namespace + base manifests
# ---------------------------------------------------------------------------

k8s_yaml(_local_dev_dir() + "/manifests/namespace.yaml")

# ---------------------------------------------------------------------------
# edx-platform image build
# ---------------------------------------------------------------------------

_platform_image = _img("openedx-platform")
_cfg = _deploy_cfg()

custom_build(
    ref=_platform_image,
    command=(
        "dagger call platform build-platform"
        " --deployment-name " + LEHRER_DEPLOY_NAME +
        " --release-name " + LEHRER_RELEASE_NAME +
        " --settings-namespace " + LEHRER_SETTINGS_NS +
        " --pip-package-lists " + _cfg + "/pip_package_lists" +
        " --pip-package-overrides " + _cfg + "/pip_package_overrides" +
        " --custom-settings " + _cfg + "/settings" +
        " publish-platform"
        " --registry " + LEHRER_REGISTRY +
        " --repository openedx-platform"
        " --tag dev"
    ),
    deps=[
        _cfg + "/pip_package_lists",
        _cfg + "/pip_package_overrides",
        _cfg + "/settings",
    ],
    skips_local_docker=True,
    labels=["platform"],
)

# ---------------------------------------------------------------------------
# codejail image build
# ---------------------------------------------------------------------------

_codejail_image = _img("openedx-codejail")

custom_build(
    ref=_codejail_image,
    command=(
        "dagger call codejail build"
        " --release-name " + LEHRER_RELEASE_NAME +
        " --codejail-config " + _cfg + "/codejail_config"
        " publish"
        " --address " + _push_addr("openedx-codejail")
    ),
    deps=[_cfg + "/codejail_config"],
    skips_local_docker=True,
    labels=["codejail"],
)

# ---------------------------------------------------------------------------
# edx-notes-api image build
# ---------------------------------------------------------------------------

_notes_image = _img("openedx-notes")

custom_build(
    ref=_notes_image,
    command=(
        "dagger call notes build"
        " --release-name " + LEHRER_RELEASE_NAME +
        " --notes-repo " + _notes_repo() +
        " --notes-config " + _cfg + "/notes_config"
        " publish"
        " --address " + _push_addr("openedx-notes")
    ),
    deps=[_cfg + "/notes_config"],
    skips_local_docker=True,
    labels=["notes"],
)

# ---------------------------------------------------------------------------
# MFE compiled builds (one nginx image per site project)
# ---------------------------------------------------------------------------

_frontend_dir = _cfg + "/mfe_slot_config/frontend"
_shared_src = _frontend_dir + "/shared"
_local_dev = _local_dev_dir()

# Enumerate site projects: subdirectories of frontend/ that aren't shared/ or src/.
# Extract basenames from full paths for BSD/macOS compatibility (no -printf).
_site_projects = [
    p.split("/")[-1]
    for p in str(local(
        "find " + _frontend_dir + " -maxdepth 1 -mindepth 1 -type d"
        " -not -name shared -not -name src",
        quiet=True,
    )).strip().splitlines()
    if p
]

_mfe_images = {}

for _site_name in _site_projects:
    _site_dir = _frontend_dir + "/" + _site_name
    _mfe_ref = _img("openedx-mfe-" + _site_name)
    _mfe_images[_site_name] = _mfe_ref

    # Two-step build:
    # 1. Dagger exports the compiled dist/ to a temp directory.
    # 2. docker build packages it into an nginx image using Dockerfile.mfe.
    #    The build context directory contains dist/ (from dagger) + nginx-mfe.conf (copied in).
    _tmp_dir = "/tmp/lehrer-mfe-dist/" + _site_name

    custom_build(
        ref=_mfe_ref,
        command=(
            "set -e && "
            "mkdir -p " + _tmp_dir + " && "
            "dagger call mfe build-site"
            " --site-project " + _site_dir +
            " --shared-src " + _shared_src +
            " export --path " + _tmp_dir + "/dist && "
            "cp " + _local_dev + "/nginx-mfe.conf " + _tmp_dir + "/nginx-mfe.conf && "
            "docker build -t $EXPECTED_REF"
            " -f " + _local_dev + "/Dockerfile.mfe"
            " " + _tmp_dir
        ),
        deps=[_site_dir, _shared_src],
        labels=["mfe"],
    )

# ---------------------------------------------------------------------------
# MFE hot-reload dev servers (optional)
# ---------------------------------------------------------------------------

if LEHRER_MFE_HOT_RELOAD:
    for _site_name in _site_projects:
        _site_dir = _frontend_dir + "/" + _site_name
        local_resource(
            name="mfe-dev-" + _site_name,
            serve_cmd=(
                "dagger call mfe watch-site"
                " --site-project " + _site_dir +
                " --shared-src " + _shared_src +
                " up --ports 8080:8080"
            ),
            deps=[_site_dir, _shared_src],
            labels=["mfe"],
        )

# ---------------------------------------------------------------------------
# K8s manifests — platform
# ---------------------------------------------------------------------------

if LEHRER_APPLY_PLATFORM_CONFIGMAPS:
    k8s_yaml(_local_dev + "/manifests/platform/configmap-lms.yaml")
    k8s_yaml(_local_dev + "/manifests/platform/configmap-cms.yaml")

k8s_yaml(_local_dev + "/manifests/platform/service-lms.yaml")
k8s_yaml(_local_dev + "/manifests/platform/service-cms.yaml")
k8s_yaml(_local_dev + "/manifests/platform/deployment-lms.yaml")
k8s_yaml(_local_dev + "/manifests/platform/deployment-cms.yaml")
k8s_yaml(_local_dev + "/manifests/platform/deployment-worker.yaml")

k8s_resource(
    "lms",
    image_deps=[_platform_image],
    resource_deps=_infra_deps,
    port_forwards=["8000:8000"],
    labels=["platform"],
)
k8s_resource(
    "cms",
    image_deps=[_platform_image],
    resource_deps=_infra_deps,
    port_forwards=["8010:8010"],
    labels=["platform"],
)
k8s_resource(
    "lms-worker",
    image_deps=[_platform_image],
    resource_deps=_infra_deps,
    labels=["platform"],
)

# ---------------------------------------------------------------------------
# K8s manifests — codejail
# ---------------------------------------------------------------------------

k8s_yaml(_local_dev + "/manifests/codejail/deployment.yaml")
k8s_yaml(_local_dev + "/manifests/codejail/service.yaml")

k8s_resource(
    "codejail",
    image_deps=[_codejail_image],
    port_forwards=["8002:8000"],
    labels=["codejail"],
)

# ---------------------------------------------------------------------------
# K8s manifests — notes
# ---------------------------------------------------------------------------

k8s_yaml(_local_dev + "/manifests/notes/deployment.yaml")
k8s_yaml(_local_dev + "/manifests/notes/service.yaml")

k8s_resource(
    "notes",
    image_deps=[_notes_image],
    resource_deps=_infra_deps,
    port_forwards=["8001:8000"],
    labels=["notes"],
)

# ---------------------------------------------------------------------------
# K8s manifests — MFE nginx deployments (generated)
# ---------------------------------------------------------------------------

for _site_name in _site_projects:
    _mfe_deploy = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mfe-{name}
  namespace: {ns}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mfe-{name}
  template:
    metadata:
      labels:
        app: mfe-{name}
    spec:
      containers:
        - name: mfe
          image: {img}
          ports:
            - containerPort: 80
          readinessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              memory: "64Mi"
              cpu: "50m"
            limits:
              memory: "128Mi"
              cpu: "200m"
---
apiVersion: v1
kind: Service
metadata:
  name: mfe-{name}
  namespace: {ns}
spec:
  selector:
    app: mfe-{name}
  ports:
    - name: http
      port: 80
      targetPort: 80
  type: ClusterIP
""".format(name=_site_name, ns=LEHRER_NAMESPACE, img=_mfe_images[_site_name])

    k8s_yaml(blob(_mfe_deploy))

    k8s_resource(
        "mfe-" + _site_name,
        image_deps=[_mfe_images[_site_name]],
        labels=["mfe"],
    )

# ---------------------------------------------------------------------------
# Ingress (standalone Traefik only — APISIX is handled by the integration Tiltfile)
# ---------------------------------------------------------------------------

if LEHRER_INGRESS == "traefik":
    _ingress = """
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: openedx
  namespace: {ns}
  annotations:
    kubernetes.io/ingress.class: traefik
spec:
  rules:
    - host: lms.localhost
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: lms
                port:
                  number: 8000
    - host: studio.localhost
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: cms
                port:
                  number: 8010
    - host: notes.localhost
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: notes
                port:
                  number: 8000
""".format(ns=LEHRER_NAMESPACE)
    for _site_name in _site_projects:
        _ingress += """    - host: {name}.localhost
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: mfe-{name}
                port:
                  number: 80
""".format(name=_site_name)
    k8s_yaml(blob(_ingress))
