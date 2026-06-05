import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import { instructorDashboardApp } from "@openedx/frontend-app-instructor-dashboard";
import { createMITOLFooterApp } from "@shared/footer";

import "@openedx/frontend-base/shell/style";

// Production defaults — all fields are overridden at runtime by /api/frontend_site_config/v1/,
// which reads from the FRONTEND_SITE_CONFIG Django setting in the LMS configmap.
const siteConfig: SiteConfig = {
	siteId: "mitol",
	siteName: "MIT Learn",
	baseUrl: "https://apps.mitxonline.mit.edu",
	lmsBaseUrl: "https://courses.learn.mit.edu",
	loginUrl: "https://courses.learn.mit.edu/login",
	logoutUrl: "https://courses.learn.mit.edu/logout",
	environment: EnvironmentTypes.PRODUCTION,
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		createMITOLFooterApp(),
		instructorDashboardApp,
		// TODO: add further module libraries as they are migrated to frontend-base
	],
};

export default siteConfig;
