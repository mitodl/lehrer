import {
  footerApp,
  headerApp,
  shellApp,
  EnvironmentTypes,
  type SiteConfig,
} from "@openedx/frontend-base";

import "@openedx/frontend-base/shell/style";

// xPRO uses xpro.mit.edu as the marketing/navigation base URL.
// User menu links (Profile, Settings, Dashboard) resolve against marketingSiteBaseUrl
// rather than lmsBaseUrl — this is the structural difference from mitxonline/mitx.
// See: deployments/mit-ol/mfe_slot_config/legacy/xpro/common-mfe-config.env.jsx
const siteConfig: SiteConfig = {
  siteId: "xpro",
  siteName: "MIT xPRO",
  baseUrl: "https://apps.xpro.mit.edu",
  lmsBaseUrl: "https://lms.xpro.mit.edu",
  loginUrl: "https://lms.xpro.mit.edu/login",
  logoutUrl: "https://lms.xpro.mit.edu/logout",
  environment: EnvironmentTypes.PRODUCTION,
  runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
  apps: [
    shellApp,
    headerApp,
    footerApp,
    // TODO: add module libraries as they are verified against the named release
  ],
};

export default siteConfig;
