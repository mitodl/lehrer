/**
 * Generic Open edX OEP-65 Site Project — production build configuration.
 *
 * This is a minimal Site Project for vanilla Open edX. It includes only the
 * upstream Shell, header, and footer apps — no operator-specific module
 * libraries or customizations.
 *
 * To add module libraries or customize the shell, fork this file into your
 * own operator deployment config.
 */

import {
  footerApp,
  headerApp,
  shellApp,
  EnvironmentTypes,
  type SiteConfig,
} from "@openedx/frontend-base";

// Production defaults; most fields are overridden at runtime by
// /api/frontend_site_config/v1/ if FRONTEND_SITE_CONFIG is configured in the LMS.
// baseUrl is not one of them, so the compiled value is what auth redirects fall
// back to. This deployment gives the MFE a host of its own (vanilla Open edX's
// topology), which in local dev is the Traefik ingress lehrer-core.star creates:
// <site>.localhost on the 8090 the k3d loadbalancer binds. An operator serving
// MFEs as a sub-path of the LMS instead (what ol-infrastructure does; see
// deployments/mit-ol) sets this to the LMS origin.
const siteConfig: SiteConfig = {
  siteId: "openedx",
  siteName: "Open edX",
  baseUrl: "http://default.localhost:8090",
  lmsBaseUrl: "http://localhost:8000",
  loginUrl: "http://localhost:8000/login",
  logoutUrl: "http://localhost:8000/logout",
  environment: EnvironmentTypes.PRODUCTION,
  runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
  apps: [
    shellApp,
    headerApp,
    footerApp,
  ],
};

export default siteConfig;
