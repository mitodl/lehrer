/**
 * Generic Open edX OEP-65 Site Project — development server configuration.
 *
 * Run `dagger call mfe watch-site --site-project ./deployments/generic/mfe_slot_config/frontend/default up --ports 8080:8080`
 * to start the hot-reload dev server.
 */

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
  baseUrl: "http://localhost:8080",
  lmsBaseUrl: "http://localhost:8000",
  loginUrl: "http://localhost:8000/login",
  logoutUrl: "http://localhost:8000/logout",
  environment: EnvironmentTypes.DEVELOPMENT,
  apps: [
    shellApp,
    headerApp,
    footerApp,
  ],
};

export default siteConfig;
