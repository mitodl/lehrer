# lehrer-core.star — reusable Tilt logic for lehrer-based Open edX deployments.
#
# Usage: load this file and call setup(cfg) with a configuration dict.
#
# Every key below is read by setup(); there are no optional ones, and a key
# that stops having a consumer should be deleted here and in the callers
# rather than left as decoration that looks configurable but is not.
#
#   load("./lehrer-core.star", "setup")
#   setup({
#     "deploy_config":   "/abs/path/to/deployments/generic",
#     "registry":        "localhost:5100",         # host-side push URL
#     "registry_k8s":    "k3d-lehrer-registry:5000", # cluster-side pull URL
#     # Host for the notes ConfigMap. The platform's own OpenSearch/Redis/URL
#     # settings come from the platform configmaps, which a caller running on
#     # different infrastructure supplies itself (apply_platform_configmaps).
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
#     # Paths to any ConfigMaps the caller layers over lms-config/cms-config
#     # (the *-config-overrides read last in envFrom). Folded into the pod
#     # fingerprint so editing one rolls the platform pods; [] when none.
#     "config_override_paths": [],
#     # Create the openedx-secrets Secret from local-dev/secret-defaults.yaml.
#     # True for a caller whose cluster does not already have it (anyone not
#     # running `lehrer dev setup`, which creates it from the same file).
#     "manage_secrets":  False,
#   })

load("ext://helm_resource", "helm_resource", "helm_repo")

def _dev_hosts(frontend_dir):
    """Return the deployment's local-dev hostname declarations.

    ``shared/src/dev-hosts.json`` is the one place a deployment's local-dev
    hostnames are set: every ``site.config.dev.tsx`` imports it as
    ``@shared/dev-hosts.json``, so what the tooling reads here is what the
    bundle was built with.
    """
    hosts_path = frontend_dir + "/shared/src/dev-hosts.json"
    if not os.path.exists(hosts_path):
        fail(
            "--mfe-hot-reload needs " + hosts_path + ", declaring lmsBaseUrl " +
            "and a baseUrl per Site Project."
        )
    return decode_json(str(read_file(hosts_path)))


def _base_url_port(dev_hosts, site_name, frontend_dir):
    """Return the port in a Site Project's dev ``baseUrl``, or "" if it has none.

    An MFE that owns a host carries its port here; one served as a sub-path of
    the LMS (the topology ol-infrastructure deploys) carries the LMS origin and
    no port of its own. Only the first case is worth cross-checking against the
    declared dev port.
    """
    sites = dev_hosts.get("sites", {})
    if site_name not in sites:
        fail(
            "MFE site '" + site_name + "' has no baseUrl in " + frontend_dir +
            "/shared/src/dev-hosts.json."
        )

    authority = sites[site_name].split("://")[-1].split("/")[0]
    parts = authority.split(":")
    if len(parts) == 2 and parts[1].isdigit():
        return parts[1]
    return ""


def _dev_server_ports(frontend_dir, site_projects):
    """Return {site: host port} for the hot-reload dev servers.

    Declared in ``dev-ports.yaml`` next to the Site Projects rather than
    derived from each site's baseUrl, since the two answer different questions
    — see the comments in that file.
    """
    ports_path = frontend_dir + "/dev-ports.yaml"
    if not os.path.exists(ports_path):
        fail(
            "--mfe-hot-reload needs " + ports_path + ", declaring a host port " +
            "for each of: " + ", ".join(site_projects) + "."
        )
    declared = decode_yaml(read_file(ports_path))

    ports = {}
    for site_name in site_projects:
        if site_name not in declared:
            fail(
                "MFE site '" + site_name + "' has no dev-server port in " +
                ports_path + "."
            )
        ports[site_name] = str(declared[site_name])
    return ports

def secret_manifest(local_dev, namespace):
    """Build the openedx-secrets Secret from the shared secret-defaults.yaml.

    The same file `lehrer dev setup` reads, so a caller composing this stack
    into a cluster it already owns gets a Secret identical to the one lehrer's
    own cluster gets, instead of hand-maintaining a second copy that drifts.

    Values come from the environment when set, falling back to the committed
    local-dev default. stringData keeps them literal — no base64 in Starlark.
    """
    path = local_dev + "/secret-defaults.yaml"
    parsed = decode_yaml(read_file(path))

    data = {}
    for entry in parsed["secrets"]:
        key = entry["key"]
        data[key] = str(os.environ.get(key, entry["default"]))
    # A mirrored key copies the resolved source value, so an override reaches
    # both it and its source.
    for entry in parsed.get("mirrors") or []:
        data[entry["key"]] = data[entry["from"]]

    return encode_yaml({
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "openedx-secrets", "namespace": namespace},
        "type": "Opaque",
        "stringData": data,
    })


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
    opensearch_host = cfg["opensearch_host"]
    notes_repo = cfg["notes_repo"]
    helm_override_dir = cfg["helm_override_dir"]
    local_dev = cfg["local_dev_dir"]
    apply_configmaps = cfg["apply_platform_configmaps"]
    manage_secrets = cfg["manage_secrets"]
    config_override_paths = cfg["config_override_paths"]

    # Lehrer core source — injected directly into the container by inject_aqueduct_settings
    # (dag.current_module().source().file("src/lehrer/settings/base.py")).
    # Must be in deps so Tilt triggers a rebuild when base.py changes.
    lehrer_core_src = local_dev + "/../src/lehrer/settings"

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

    # The MariaDB CR reads MYSQL_ROOT_PASSWORD from this Secret and the MongoDB
    # CR reads MONGO_PASSWORD, so it has to land before either operator CR is
    # applied — hence its own resource, named in their resource_deps below.
    secret_deps = []
    if manage_secrets:
        k8s_yaml(secret_manifest(local_dev, namespace))
        k8s_resource(
            new_name="openedx-secrets",
            objects=["openedx-secrets:Secret:" + namespace],
            labels=["infra"],
        )
        secret_deps = ["openedx-secrets"]

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
                "mysql:MariaDB:openedx",
                "mysql-database:Database:openedx",
                "notes:Database:openedx",
                "edxapp-csmh:Database:openedx",
                "edxapp-grant-edxapp:Grant:openedx",
                "edxapp-grant-notes:Grant:openedx",
                "edxapp-grant-csmh:Grant:openedx",
            ],
            resource_deps=["mariadb-operator"] + secret_deps,
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
                "mongodb:MongoDBCommunity:openedx",
            ],
            resource_deps=["mongodb-operator"] + secret_deps,
            labels=["infra"],
        )

    if manage_infra:
        # Valkey (Redis-compatible fork), standalone. The chart names its
        # Service "<release>-valkey", so release "redis" yields "redis-valkey"
        # — the host CELERY_BROKER_HOSTNAME points at in the platform
        # configmaps.
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
            " --build-manifest " + dep_cfg + "/build_manifest.yaml" +
            " --custom-settings " + dep_cfg + "/settings" +
            " export --path $tmp && " +
            "loaded=$(docker load -i $tmp | awk '{print $NF}') && " +
            "docker tag $loaded $PUSH_REF && " +
            "docker push $PUSH_REF && " +
            "rm -f $tmp"
        ),
        deps=[
            dep_cfg + "/build_manifest.yaml",
            dep_cfg + "/settings",
            lehrer_core_src,
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

    # Hot-reload serves the MFEs from host dev servers instead of from the
    # cluster, so the compiled image, Deployment and ingress route are all
    # skipped for the duration — building them would cost a dagger run per site
    # to produce something nothing routes to.
    compiled_sites = [] if mfe_hot_reload else site_projects

    mfe_images = {}

    for site_name in compiled_sites:
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
        # Each dev server binds the host port declared for its site in
        # dev-ports.yaml, cross-checked against the baseUrl the bundle is built
        # with (shared/src/dev-hosts.json): a server listening anywhere other
        # than where the app points serves a site that points at nothing.
        #
        # The port must also stay clear of the ones k3d's loadbalancer binds
        # (see k3d-config.yaml). It holds those for as long as the cluster is
        # up, so a dev server can never have one.
        reserved = {}
        for match in str(read_file(local_dev + "/k3d-config.yaml")).split("- port: ")[1:]:
            reserved[match.split(":")[0].strip()] = True

        ports_path = frontend_dir + "/dev-ports.yaml"
        dev_ports = _dev_server_ports(frontend_dir, site_projects)
        dev_hosts = _dev_hosts(frontend_dir)

        claimed = {}
        for site_name in site_projects:
            site_dir = frontend_dir + "/" + site_name
            port = dev_ports[site_name]

            if port in reserved:
                fail(
                    "MFE site '" + site_name + "' asks for dev-server port " +
                    port + ", which k3d's loadbalancer binds for the cluster " +
                    "ingress. Pick a free port in " + ports_path + "."
                )
            if port in claimed:
                fail(
                    "MFE sites '" + claimed[port] + "' and '" + site_name +
                    "' both ask for dev-server port " + port + ". Give each " +
                    "one its own port in " + ports_path + "."
                )
            claimed[port] = site_name

            # Only meaningful when the site owns a host. A sub-path baseUrl
            # carries the LMS origin, so there is nothing to reconcile.
            base_port = _base_url_port(dev_hosts, site_name, frontend_dir)
            if base_port and base_port != port:
                fail(
                    "MFE site '" + site_name + "' serves on port " + port +
                    " per " + ports_path + ", but its baseUrl in " +
                    "shared/src/dev-hosts.json points at port " + base_port +
                    ". The app would load from an address nothing is " +
                    "listening on."
                )

            # A baseUrl host that does not resolve is checked by
            # `lehrer dev check --deployment-config ...`, not here: a Tiltfile
            # print() only lands in the Tilt log, mixed in with build output.
            local_resource(
                name="mfe-dev-" + site_name,
                serve_cmd=(
                    "dagger --progress=plain call mfe watch-site" +
                    " --site-project " + site_dir +
                    shared_src_flag +
                    " up --ports " + port + ":8080"
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

    k8s_yaml(local_dev + "/manifests/platform/job-migrate.yaml")

    # The edxapp-provision Job's payload — a Django script and a waffle flag
    # list — is kept as real files rather than inlined into a ConfigMap
    # manifest, so provision.py stays lintable and readable. kubectl renders
    # them into the ConfigMap; --dry-run=client never contacts the cluster.
    provision_dir = local_dev + "/provision"
    watch_file(provision_dir)
    k8s_yaml(local(
        "kubectl create configmap edxapp-provision --namespace " + namespace +
        " --from-file=" + provision_dir + "/provision.py" +
        " --from-file=" + provision_dir + "/waffle-flags.yaml" +
        " --dry-run=client -o yaml",
        quiet=True,
    ))
    k8s_yaml(local_dev + "/manifests/platform/job-provision.yaml")

    # The demo course repo branches per Open edX release, so the Job is told
    # which release this stack was built from and resolves the branch itself.
    k8s_yaml(blob(str(read_file(
        local_dev + "/manifests/platform/job-demo-course.yaml"
    )).replace("__RELEASE_NAME__", release_name)))
    k8s_yaml(local_dev + "/manifests/platform/service-lms.yaml")
    k8s_yaml(local_dev + "/manifests/platform/service-cms.yaml")

    # Stamp a config hash into every platform pod template, same reason as the
    # notes deployment above: envFrom does not trigger a rollout, so without
    # this a config edit updates the ConfigMap and leaves every running pod on
    # the old values — silently, since nothing reports it.
    #
    # Covers the caller's override ConfigMaps as well as ours. A composing
    # caller applies those itself, so hashing only our files would miss exactly
    # the edits that caller makes most often.
    platform_config_files = []
    if apply_configmaps:
        platform_config_files.append(
            local_dev + "/manifests/platform/configmap-lms.yaml")
        platform_config_files.append(
            local_dev + "/manifests/platform/configmap-cms.yaml")
    platform_config_files.extend(config_override_paths)

    if platform_config_files:
        # read_file registers a Tilt watch on each path, so an edit re-runs the
        # Tiltfile and recomputes this; `cat` alone would hash the file without
        # ever being told it changed.
        platform_config_checksum = str(hash("\n".join(
            [str(read_file(path)) for path in platform_config_files]
        )))
    else:
        platform_config_checksum = "none"

    for name in [
        "deployment-lms.yaml",
        "deployment-cms.yaml",
        "deployment-worker.yaml",
        "deployment-cms-worker.yaml",
    ]:
        k8s_yaml(blob(str(read_file(
            local_dev + "/manifests/platform/" + name
        )).replace("__PLATFORM_CONFIG_CHECKSUM__", platform_config_checksum)))

    # Run DB migrations once the database is up, before the services start.
    k8s_resource(
        "edxapp-migrate",
        resource_deps=infra_deps,
        labels=["platform"],
    )

    # Superuser, notes OAuth client and waffle flags. Needs the schema, so it
    # follows the migration Job; the LMS/CMS do not need it to boot, but the
    # stack is not usable until it has run, so it gates them too.
    k8s_resource(
        "edxapp-provision",
        objects=["edxapp-provision:ConfigMap:openedx"],
        resource_deps=["edxapp-migrate"],
        labels=["platform"],
    )

    # Demo course import — opt-in. It clones the course repo over the network,
    # so it is left for the developer to trigger from the Tilt UI rather than
    # added to the critical path of every `tilt up`.
    k8s_resource(
        "edxapp-demo-course",
        resource_deps=["edxapp-provision"],
        trigger_mode=TRIGGER_MODE_MANUAL,
        auto_init=False,
        labels=["platform"],
    )

    # The platform services depend on a migrated and provisioned schema, so
    # they wait for both Jobs to complete (in addition to the infra services).
    platform_deps = infra_deps + ["edxapp-migrate", "edxapp-provision"]
    # LMS and CMS are exposed on host ports 8000/8010 via the k3d load
    # balancer → Traefik ingress.  Port-forwards are omitted here to avoid
    # conflicting with that binding ("address already in use").
    k8s_resource(
        "lms",
        resource_deps=platform_deps,
        labels=["platform"],
    )
    k8s_resource(
        "cms",
        resource_deps=platform_deps,
        labels=["platform"],
    )
    k8s_resource(
        "lms-worker",
        resource_deps=platform_deps,
        labels=["platform"],
    )
    k8s_resource(
        "cms-worker",
        resource_deps=platform_deps,
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

    notes_configmap = local_dev + "/manifests/notes/configmap.yaml"
    k8s_yaml(blob(str(read_file(notes_configmap)).replace(
        "__OPENSEARCH_HOST__", opensearch_host
    )))
    k8s_yaml(local_dev + "/manifests/notes/job-migrate.yaml")

    # Stamp the ConfigMap's hash into the notes pod template. Without it a
    # config edit re-runs notes-migrate against the new values while the
    # running pod keeps the old ones — envFrom does not trigger a rollout.
    # Hashed over the file *and* the substituted host, so changing either
    # rolls the pod; hashing the file alone would miss an opensearch_host
    # change.
    notes_config_checksum = str(local(
        "{ cat " + notes_configmap + "; printf '%s' '" + opensearch_host +
        "'; } | sha256sum | cut -c1-16",
        quiet=True,
    )).strip()
    k8s_yaml(blob(str(read_file(
        local_dev + "/manifests/notes/deployment.yaml"
    )).replace("__NOTES_CONFIG_CHECKSUM__", notes_config_checksum)))

    k8s_yaml(local_dev + "/manifests/notes/service.yaml")

    # The notes database and grant come from the MariaDB CR, but the schema and
    # the search index do not — the service 500s on every annotator request
    # until this Job has run.
    k8s_resource(
        "notes-migrate",
        objects=["notes-config:ConfigMap:openedx"],
        resource_deps=infra_deps,
        labels=["notes"],
    )

    k8s_resource(
        "notes",
        resource_deps=infra_deps + ["notes-migrate"],
        port_forwards=["8001:8000"],
        labels=["notes"],
    )

    # ------------------------------------------------------------------ #
    # K8s manifests — MFE nginx deployments (generated inline)
    # ------------------------------------------------------------------ #

    for site_name in compiled_sites:
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
        for site_name in compiled_sites:
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
