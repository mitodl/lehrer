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
	// The origin this Site Project is served from, which is the LMS host: Fastly
	// serves it under /apps there ('Handle Site Project routing' in
	// ol-infrastructure applications/edxapp/__main__.py) rather than giving it a
	// host of its own, and wrapWithAppsPath nests the routes to match, which is why
	// basename stays "/". A default like the origins below it, replaced per
	// environment by FRONTEND_SITE_CONFIG. It previously named apps.*.mit.edu, a
	// placeholder from the original OEP-65 scaffold (5d68e40) that has never
	// resolved.
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
