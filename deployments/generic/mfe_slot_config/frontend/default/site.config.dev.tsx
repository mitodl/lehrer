/**
 * Generic Open edX OEP-65 Site Project — development server configuration.
 *
 * Hostnames come from ../shared/src/dev-hosts.json; the port webpack-dev-server
 * binds comes from ../dev-ports.yaml. `lehrer dev start --mfe-hot-reload` reads
 * both and refuses to load when they disagree. To run the server by hand:
 *
 *   dagger call mfe watch-site \
 *     --site-project ./deployments/generic/mfe_slot_config/frontend/default \
 *     --shared-src   ./deployments/generic/mfe_slot_config/frontend/shared \
 *     up --ports 8100:8080
 */

import devHosts from "@shared/dev-hosts.json";

import {
  footerApp,
  headerApp,
  shellApp,
  EnvironmentTypes,
  type SiteConfig,
} from "@openedx/frontend-base";

const siteConfig: SiteConfig = {
  siteId: "openedx",
  siteName: "Open edX",
  baseUrl: devHosts.sites.default,
  lmsBaseUrl: devHosts.lmsBaseUrl,
  loginUrl: `${devHosts.lmsBaseUrl}/login`,
  logoutUrl: `${devHosts.lmsBaseUrl}/logout`,
  environment: EnvironmentTypes.DEVELOPMENT,
  apps: [
    shellApp,
    headerApp,
    footerApp,
  ],
};

export default siteConfig;
