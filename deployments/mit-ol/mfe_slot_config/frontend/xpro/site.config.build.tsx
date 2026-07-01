import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import { instructorDashboardApp } from "@openedx/frontend-app-instructor-dashboard";
import { createMITOLFooterApp } from "@shared/footer";
import { createXProHeaderApp } from "@shared/header";
import { wrapWithAppsPath } from "@shared/utils/apps";

import "@openedx/frontend-base/shell/style";
import "@shared/styles/mitx.scss";

// xPRO nav model differs from mitxonline: the marketing site (xpro.mit.edu) is separate from
// the LMS (courses.xpro.mit.edu). Production defaults — all fields are overridden at runtime
// by /api/frontend_site_config/v1/, which reads from FRONTEND_SITE_CONFIG in the LMS configmap.
const siteConfig: SiteConfig = {
	siteId: "xpro",
	siteName: "MIT xPRO",
	basename: "/",
	baseUrl: "https://apps.xpro.mit.edu",
	lmsBaseUrl: "https://courses.xpro.mit.edu",
	loginUrl: "https://courses.xpro.mit.edu/login",
	logoutUrl: "https://courses.xpro.mit.edu/logout",
	environment: EnvironmentTypes.PRODUCTION,
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		createMITOLFooterApp(),
		createXProHeaderApp(),
		wrapWithAppsPath(instructorDashboardApp),
		// TODO: add further module libraries as they are verified against the named release
	],
};

export default siteConfig;
