import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import { createMITOLFooterApp } from "@shared/footer";
import { createMITxHeaderApp } from "@shared/header";
import { createMITOLInstructorDashboardApp } from "@shared/instructor-dashboard";

import "@openedx/frontend-base/shell/style";
import "@shared/styles/mitx.scss";

// Covers both mitx and mitx-staging deployments via a single build.
// Production defaults — most fields are overridden at runtime by /api/frontend_site_config/v1/,
// which reads from the FRONTEND_SITE_CONFIG Django setting in the LMS configmap.
const siteConfig: SiteConfig = {
	siteId: "mitx",
	siteName: "MITx Residential",
	basename: "/",
	// This Site Project is served as a sub-path of the LMS host, not on a host of
	// its own, so baseUrl is the LMS origin. Fastly rewrites /apps/<app>/... to the
	// Site Project's index.html and /apps/mitx-site/... to its assets (see "Handle
	// Site Project routing" in ol-infrastructure applications/edxapp/__main__.py);
	// the routes are nested under /apps by wrapWithAppsPath, which is why basename
	// stays "/". FRONTEND_SITE_CONFIG sets no baseUrl, so this value is what the
	// auth redirects fall back to; the apps.*.mit.edu host it used to name has
	// never existed in DNS.
	baseUrl: "https://lms.mitx.mit.edu",
	lmsBaseUrl: "https://lms.mitx.mit.edu",
	loginUrl: "https://lms.mitx.mit.edu/login",
	logoutUrl: "https://lms.mitx.mit.edu/logout",
	environment: EnvironmentTypes.PRODUCTION,
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		createMITOLFooterApp(),
		createMITxHeaderApp(),
		createMITOLInstructorDashboardApp(),
		// TODO: add further module libraries as they are verified against the named release
	],
};

export default siteConfig;
