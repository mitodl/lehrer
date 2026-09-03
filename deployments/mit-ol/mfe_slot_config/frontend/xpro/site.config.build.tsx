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
// the LMS (courses.xpro.mit.edu). Production defaults; most fields are overridden at runtime
// by /api/frontend_site_config/v1/, which reads from FRONTEND_SITE_CONFIG in the LMS configmap.
const siteConfig: SiteConfig = {
	siteId: "xpro",
	siteName: "MIT xPRO",
	basename: "/",
	// The origin this Site Project is served from, which is the LMS host: Fastly
	// serves it under /apps there ('Handle Site Project routing' in
	// ol-infrastructure applications/edxapp/__main__.py) rather than giving it a
	// host of its own, and wrapWithAppsPath nests the routes to match, which is why
	// basename stays "/". A default like the origins below it, replaced per
	// environment by FRONTEND_SITE_CONFIG. It previously named apps.*.mit.edu, a
	// placeholder from the original OEP-65 scaffold (5d68e40) that has never
	// resolved.
	baseUrl: "https://courses.xpro.mit.edu",
	lmsBaseUrl: "https://courses.xpro.mit.edu",
	loginUrl: "https://courses.xpro.mit.edu/login",
	logoutUrl: "https://courses.xpro.mit.edu/logout",
	environment: EnvironmentTypes.PRODUCTION,
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		// xPRO footer matches the legacy xPRO footer: About Us · Privacy Policy ·
		// Honor Code · Terms of Service · Accessibility (no Help). URLs still come
		// from the runtime mitolFooter config.
		createMITOLFooterApp({
			linkOrder: ["about", "privacy", "honor", "tos", "accessibility"],
		}),
		createXProHeaderApp(),
		wrapWithAppsPath(instructorDashboardApp),
		// TODO: add further module libraries as they are verified against the named release
	],
};

export default siteConfig;
