# lehrer-core.star — reusable Tilt logic for lehrer-based Open edX deployments.
#
# Usage: load this file and call setup(cfg) with a configuration dict.
#
#   load("./lehrer-core.star", "setup")
#   setup({
#     "deploy_config":   "/abs/path/to/deployments/generic",
#     "registry":        "localhost:5100",         # host-side push URL
#     "registry_k8s":    "k3d-lehrer-registry:5000", # cluster-side pull URL
#     "redis_host":      "redis-master.openedx.svc.cluster.local",
#     "opensearch_host": "opensearch-cluster-master.openedx.svc.cluster.local",
#     "namespace":       "openedx",
#     "manage_infra":    True,   # install MySQL/MongoDB/Redis/OpenSearch via Helm
#     "mysql_managed":   True,   # install MySQL (independent of manage_infra)
#     "mongo_managed":   True,   # install MongoDB (independent of manage_infra)
#     "ingress":         "traefik",   # or "apisix"
#     "mfe_hot_reload":  False,
#     "release_name":    "master",
#     "deploy_name":     "generic",
#     "settings_ns":     "production",
#     "notes_repo":      "https://github.com/openedx/edx-notes-api",
#     "helm_override_dir": "",   # path to dir with override Helm values, or ""
#     "local_dev_dir":   "/abs/path/to/lehrer/local-dev",
#     "apply_platform_configmaps": True,  # False when caller applies its own
#   })

load("ext://helm_resource", "helm_resource", "helm_repo")

def setup(cfg):
    """Deploy the full Open edX local dev stack from the given configuration."""

    # ------------------------------------------------------------------ #
    # Config helpers
    # ------------------------------------------------------------------ #

    deploy_config = cfg["deploy_config"]
    registry = cfg["registry"]
    registry_k8s = cfg["registry_k8s"]
    namespace = cfg["namespace"]
    manage_infra = cfg["manage_infra"]
    mysql_managed = cfg["mysql_managed"]
    mongo_managed = cfg["mongo_managed"]
    ingress = cfg["ingress"]
    mfe_hot_reload = cfg["mfe_hot_reload"]
    release_name = cfg["release_name"]
    deploy_name = cfg["deploy_name"]
    settings_ns = cfg["settings_ns"]
    notes_repo = cfg["notes_repo"]
    helm_override_dir = cfg["helm_override_dir"]
    local_dev = cfg["local_dev_dir"]
    apply_configmaps = cfg["apply_platform_configmaps"]

    # Absolute path to the deployment config directory.
    # Relative paths are treated as relative to local_dev (where tilt up is run from).
    if deploy_config.startswith("/"):
        dep_cfg = deploy_config.rstrip("/")
    else:
        dep_cfg = (local_dev + "/" + deploy_config).rstrip("/")

    # Set the default registry to the cluster-side address so $EXPECTED_REF uses it.
    # Build commands then rewrite $EXPECTED_REF to the host-side address for docker push
    # (since registry_k8s only resolves from inside the cluster, not from the host).
    # This explicit call also resets any previously-persisted default_registry state.
    default_registry(registry_k8s)

    def img(name):
        return registry_k8s + "/" + name + ":dev"

    # Rewrite $EXPECTED_REF to a host-accessible push reference.
    # Tilt may persist old default_registry state, causing $EXPECTED_REF to have a mangled
    # repo name (e.g. "lehrer-registry_5000_openedx-codejail" with underscores instead of
    # "lehrer-registry:5000/openedx-codejail"). Strip the mangled infix first, then replace
    # the cluster-side host (registry_k8s) with the host-accessible address (registry).
    # Both transformations are safe no-ops when the other case is active.
    push_rewrite = (
        "PUSH_REF=$(echo \"$EXPECTED_REF\" " +
        "| sed 's|lehrer-registry_5000_||g' " +
        "| sed 's|" + registry_k8s + "|" + registry + "|g') && "
    )

    def helm_values(filename):
        if helm_override_dir:
            override = helm_override_dir + "/" + filename
            if os.path.exists(override):
                return override
        return local_dev + "/helm/" + filename

    # ------------------------------------------------------------------ #
    # Infrastructure (Helm)
    # ------------------------------------------------------------------ #

    helm_repo(
        "opensearch-helm",
        "https://opensearch-project.github.io/helm-charts",
        labels=["infra"],
    )

    if manage_infra or mysql_managed:
        # Install the MariaDB operator in its own namespace, then apply the
        # MariaDB CR (+ Database/Grant CRs) in the application namespace.
        helm_repo("mariadb", "https://helm.mariadb.com/mariadb-operator", labels=["infra"])
        helm_resource(
            "mariadb-operator",
            "mariadb/mariadb-operator",
            namespace="mariadb-operator",
            flags=["--values", helm_values("mariadb-operator-values.yaml"), "--create-namespace"],
            labels=["infra"],
        )
        k8s_yaml(local_dev + "/manifests/infra/mariadb.yaml")
        # Group all MariaDB CRs so Tilt waits for the operator CRDs before
        # applying them (Database/Grant kinds don't exist until the chart installs).
        k8s_resource(
            new_name="mysql",
            objects=[
                "mariadb-root-secret:Secret:openedx",
                "mysql:MariaDB:openedx",
                "notes:Database:openedx",
                "edxapp-csmh:Database:openedx",
                "edxapp-grant-edxapp:Grant:openedx",
                "edxapp-grant-notes:Grant:openedx",
                "edxapp-grant-csmh:Grant:openedx",
            ],
            resource_deps=["mariadb-operator"],
            labels=["infra"],
        )

    if manage_infra or mongo_managed:
        # Install the MongoDB Community Operator, then apply the MongoDBCommunity CR.
        helm_repo("mongodb", "https://mongodb.github.io/helm-charts", labels=["infra"])
        helm_resource(
            "mongodb-operator",
            "mongodb/community-operator",
            namespace="mongodb-operator",
            flags=["--values", helm_values("mongodb-operator-values.yaml"), "--create-namespace"],
            labels=["infra"],
        )
        k8s_yaml(local_dev + "/manifests/infra/mongodb.yaml")
        # Group MongoDB CRs so Tilt waits for the operator CRDs before applying.
        # Name is "mongodb-cr" (not "mongodb") to avoid collision with the
        # helm_repo("mongodb", ...) local_resource that Tilt registers.
        k8s_resource(
            new_name="mongodb-cr",
            objects=[
                "mongodb-edxapp-secret:Secret:openedx",
                "mongodb:MongoDBCommunity:openedx",
            ],
            resource_deps=["mongodb-operator"],
            labels=["infra"],
        )

    if manage_infra:
        # Valkey (Redis-compatible fork) — standalone, release name "redis" keeps
        # the service name "redis-master" as expected by the platform configmap.
        helm_repo("valkey", "https://valkey.io/valkey-helm/", labels=["infra"])
        helm_resource(
            "redis",
            "valkey/valkey",
            namespace=namespace,
            flags=["--values", helm_values("valkey-values.yaml"), "--create-namespace"],
            labels=["infra"],
        )
        helm_resource(
            "opensearch",
            "opensearch-helm/opensearch",
            namespace=namespace,
            flags=[
                "--values",
                helm_values("opensearch-values.yaml"),
                "--create-namespace",
            ],
            labels=["infra"],
        )

    # Platform depends on the database CRs being submitted (not just the operators),
    # so Tilt won't start platform pods before the MariaDB/MongoDB CRDs exist.
    infra_deps = []
    if manage_infra or mysql_managed:
        infra_deps.append("mysql")
    if manage_infra or mongo_managed:
        infra_deps.append("mongodb-cr")
    if manage_infra:
        infra_deps.append("redis")
        infra_deps.append("opensearch")

    # ------------------------------------------------------------------ #
    # Namespace
    # ------------------------------------------------------------------ #

    k8s_yaml(local_dev + "/manifests/namespace.yaml")

    # ------------------------------------------------------------------ #
    # edx-platform image build
    # ------------------------------------------------------------------ #

    platform_image = img("openedx-platform")

    custom_build(
        ref=platform_image,
        command=(
            "set -e && " +
            push_rewrite +
            "tmp=$(mktemp /tmp/lehrer-platform-XXXXXX.tar) && " +
            "dagger --progress=plain call platform build-platform" +
            " --deployment-name " + deploy_name +
            " --release-name " + release_name +
            " --settings-namespace " + settings_ns +
            " --pip-package-lists " + dep_cfg + "/pip_package_lists" +
            " --pip-package-overrides " + dep_cfg + "/pip_package_overrides" +
            " --custom-settings " + dep_cfg + "/settings" +
            " export --path $tmp && " +
            "loaded=$(docker load -i $tmp | awk '{print $NF}') && " +
            "docker tag $loaded $PUSH_REF && " +
            "docker push $PUSH_REF && " +
            "rm -f $tmp"
        ),
        deps=[
            dep_cfg + "/pip_package_lists",
            dep_cfg + "/pip_package_overrides",
            dep_cfg + "/settings",
        ],
        skips_local_docker=True,
    )

    # ------------------------------------------------------------------ #
    # codejail image build
    # ------------------------------------------------------------------ #

    codejail_image = img("openedx-codejail")

    custom_build(
        ref=codejail_image,
        command=(
            "set -e && " +
            push_rewrite +
            "tmp=$(mktemp /tmp/lehrer-codejail-XXXXXX.tar) && " +
            "dagger --progress=plain call codejail build" +
            " --release-name " + release_name +
            " --codejail-config " + dep_cfg + "/codejail_config" +
            " export --path $tmp && " +
            "loaded=$(docker load -i $tmp | awk '{print $NF}') && " +
            "docker tag $loaded $PUSH_REF && " +
            "docker push $PUSH_REF && " +
            "rm -f $tmp"
        ),
        deps=[dep_cfg + "/codejail_config"],
        skips_local_docker=True,
    )

    # ------------------------------------------------------------------ #
    # edx-notes-api image build
    # ------------------------------------------------------------------ #

    notes_image = img("openedx-notes")

    custom_build(
        ref=notes_image,
        command=(
            "set -e && " +
            push_rewrite +
            "tmp=$(mktemp /tmp/lehrer-notes-XXXXXX.tar) && " +
            "dagger --progress=plain call notes build" +
            " --release-name " + release_name +
            " --notes-repo " + notes_repo +
            " --notes-config " + dep_cfg + "/notes_config" +
            " export --path $tmp && " +
            "loaded=$(docker load -i $tmp | awk '{print $NF}') && " +
            "docker tag $loaded $PUSH_REF && " +
            "docker push $PUSH_REF && " +
            "rm -f $tmp"
        ),
        deps=[dep_cfg + "/notes_config"],
        skips_local_docker=True,
    )

    # ------------------------------------------------------------------ #
    # MFE compiled builds (one nginx image per site project)
    # ------------------------------------------------------------------ #

    frontend_dir = dep_cfg + "/mfe_slot_config/frontend"
    shared_src = frontend_dir + "/shared"
    has_shared = os.path.exists(shared_src)
    shared_src_flag = (" --shared-src " + shared_src) if has_shared else ""
    mfe_deps_base = [shared_src] if has_shared else []

    site_projects = [
        p.split("/")[-1]
        for p in str(local(
            "find " + frontend_dir + " -maxdepth 1 -mindepth 1 -type d" +
            " -not -name shared -not -name src",
            quiet=True,
        )).strip().splitlines()
        if p
    ]

    mfe_images = {}

    for site_name in site_projects:
        site_dir = frontend_dir + "/" + site_name
        mfe_ref = img("openedx-mfe-" + site_name)
        mfe_images[site_name] = mfe_ref
        tmp_dir = "/tmp/lehrer-mfe-dist/" + site_name

        custom_build(
            ref=mfe_ref,
            command=(
                "set -e && " +
                # Push ourselves to the host-side registry (same pattern as the
                # platform/codejail/notes builds). Without this, Tilt pushes
                # $EXPECTED_REF itself and mangles the repo name under
                # default_registry, so the pod's pull ref never resolves.
                push_rewrite +
                "mkdir -p " + tmp_dir + " && " +
                "dagger --progress=plain call mfe build-site" +
                " --site-project " + site_dir +
                shared_src_flag +
                " export --path " + tmp_dir + "/dist && " +
                "cp " + local_dev + "/nginx-mfe.conf " + tmp_dir + "/nginx-mfe.conf && " +
                "docker build -t $PUSH_REF" +
                " -f " + local_dev + "/Dockerfile.mfe" +
                " " + tmp_dir + " && " +
                "docker push $PUSH_REF"
            ),
            deps=[site_dir] + mfe_deps_base,
            skips_local_docker=True,
        )

    if mfe_hot_reload:
        for site_name in site_projects:
            site_dir = frontend_dir + "/" + site_name
            local_resource(
                name="mfe-dev-" + site_name,
                serve_cmd=(
                    "dagger --progress=plain call mfe watch-site" +
                    " --site-project " + site_dir +
                    shared_src_flag +
                    # Host 8090 (matches k3d-config MFE ingress) -> container 8080.
                    " up --ports 8090:8080"
                ),
                deps=[site_dir] + mfe_deps_base,
                labels=["mfe"],
            )

    # ------------------------------------------------------------------ #
    # K8s manifests — platform
    # ------------------------------------------------------------------ #

    if apply_configmaps:
        k8s_yaml(local_dev + "/manifests/platform/configmap-lms.yaml")
        k8s_yaml(local_dev + "/manifests/platform/configmap-cms.yaml")

    k8s_yaml(local_dev + "/manifests/platform/service-lms.yaml")
    k8s_yaml(local_dev + "/manifests/platform/service-cms.yaml")
    k8s_yaml(local_dev + "/manifests/platform/deployment-lms.yaml")
    k8s_yaml(local_dev + "/manifests/platform/deployment-cms.yaml")
    k8s_yaml(local_dev + "/manifests/platform/deployment-worker.yaml")
    k8s_yaml(local_dev + "/manifests/platform/deployment-cms-worker.yaml")

    k8s_resource(
        "lms",
        resource_deps=infra_deps,
        port_forwards=["8000:8000"],
        labels=["platform"],
    )
    k8s_resource(
        "cms",
        resource_deps=infra_deps,
        port_forwards=["8010:8010"],
        labels=["platform"],
    )
    k8s_resource(
        "lms-worker",
        resource_deps=infra_deps,
        labels=["platform"],
    )
    k8s_resource(
        "cms-worker",
        resource_deps=infra_deps,
        labels=["platform"],
    )

    # ------------------------------------------------------------------ #
    # K8s manifests — codejail
    # ------------------------------------------------------------------ #

    k8s_yaml(local_dev + "/manifests/codejail/deployment.yaml")
    k8s_yaml(local_dev + "/manifests/codejail/service.yaml")

    k8s_resource(
        "codejail",
        port_forwards=["8002:8000"],
        labels=["codejail"],
    )

    # ------------------------------------------------------------------ #
    # K8s manifests — notes
    # ------------------------------------------------------------------ #

    k8s_yaml(local_dev + "/manifests/notes/deployment.yaml")
    k8s_yaml(local_dev + "/manifests/notes/service.yaml")

    k8s_resource(
        "notes",
        resource_deps=infra_deps,
        port_forwards=["8001:8000"],
        labels=["notes"],
    )

    # ------------------------------------------------------------------ #
    # K8s manifests — MFE nginx deployments (generated inline)
    # ------------------------------------------------------------------ #

    for site_name in site_projects:
        k8s_yaml(blob(
            "apiVersion: apps/v1\n" +
            "kind: Deployment\n" +
            "metadata:\n" +
            "  name: mfe-" + site_name + "\n" +
            "  namespace: " + namespace + "\n" +
            "spec:\n" +
            "  replicas: 1\n" +
            "  selector:\n" +
            "    matchLabels:\n" +
            "      app: mfe-" + site_name + "\n" +
            "  template:\n" +
            "    metadata:\n" +
            "      labels:\n" +
            "        app: mfe-" + site_name + "\n" +
            "    spec:\n" +
            "      containers:\n" +
            "      - name: mfe\n" +
            "        image: " + mfe_images[site_name] + "\n" +
            "        ports:\n" +
            "        - containerPort: 80\n" +
            "        readinessProbe:\n" +
            "          httpGet:\n" +
            "            path: /\n" +
            "            port: 80\n" +
            "          initialDelaySeconds: 5\n" +
            "          periodSeconds: 10\n" +
            "        resources:\n" +
            "          requests:\n" +
            "            memory: 64Mi\n" +
            "            cpu: 50m\n" +
            "          limits:\n" +
            "            memory: 128Mi\n" +
            "            cpu: 200m\n" +
            "---\n" +
            "apiVersion: v1\n" +
            "kind: Service\n" +
            "metadata:\n" +
            "  name: mfe-" + site_name + "\n" +
            "  namespace: " + namespace + "\n" +
            "spec:\n" +
            "  selector:\n" +
            "    app: mfe-" + site_name + "\n" +
            "  ports:\n" +
            "  - name: http\n" +
            "    port: 80\n" +
            "    targetPort: 80\n" +
            "  type: ClusterIP\n"
        ))

        k8s_resource(
            "mfe-" + site_name,
            labels=["mfe"],
        )

    # ------------------------------------------------------------------ #
    # Ingress (Traefik standalone only; APISIX handled by caller)
    # ------------------------------------------------------------------ #

    if ingress == "traefik":
        ingress_yaml = (
            "apiVersion: networking.k8s.io/v1\n" +
            "kind: Ingress\n" +
            "metadata:\n" +
            "  name: openedx\n" +
            "  namespace: " + namespace + "\n" +
            "  annotations:\n" +
            "    kubernetes.io/ingress.class: traefik\n" +
            "spec:\n" +
            "  rules:\n" +
            "  - host: lms.localhost\n" +
            "    http:\n" +
            "      paths:\n" +
            "      - path: /\n" +
            "        pathType: Prefix\n" +
            "        backend:\n" +
            "          service:\n" +
            "            name: lms\n" +
            "            port:\n" +
            "              number: 8000\n" +
            "  - host: studio.localhost\n" +
            "    http:\n" +
            "      paths:\n" +
            "      - path: /\n" +
            "        pathType: Prefix\n" +
            "        backend:\n" +
            "          service:\n" +
            "            name: cms\n" +
            "            port:\n" +
            "              number: 8010\n" +
            "  - host: notes.localhost\n" +
            "    http:\n" +
            "      paths:\n" +
            "      - path: /\n" +
            "        pathType: Prefix\n" +
            "        backend:\n" +
            "          service:\n" +
            "            name: notes\n" +
            "            port:\n" +
            "              number: 8000\n"
        )
        for site_name in site_projects:
            ingress_yaml += (
                "  - host: " + site_name + ".localhost\n" +
                "    http:\n" +
                "      paths:\n" +
                "      - path: /\n" +
                "        pathType: Prefix\n" +
                "        backend:\n" +
                "          service:\n" +
                "            name: mfe-" + site_name + "\n" +
                "            port:\n" +
                "              number: 80\n"
            )
        k8s_yaml(blob(ingress_yaml))
