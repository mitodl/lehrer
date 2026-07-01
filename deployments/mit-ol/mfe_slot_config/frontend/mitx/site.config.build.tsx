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
// Production defaults — all fields are overridden at runtime by /api/frontend_site_config/v1/,
// which reads from the FRONTEND_SITE_CONFIG Django setting in the LMS configmap.
const siteConfig: SiteConfig = {
	siteId: "mitx",
	siteName: "MITx Residential",
	basename: "/",
	baseUrl: "https://apps.mitx.mit.edu",
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
