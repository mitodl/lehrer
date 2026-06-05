import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import { instructorDashboardApp } from "@openedx/frontend-app-instructor-dashboard";

import "@openedx/frontend-base/shell/style";

const siteConfig: SiteConfig = {
	siteId: "mitol",
	siteName: "MIT OpenLearning",
	baseUrl: "https://apps.mitxonline.mit.edu",
	lmsBaseUrl: "https://courses.mitxonline.mit.edu",
	loginUrl: "https://courses.mitxonline.mit.edu/login",
	logoutUrl: "https://courses.mitxonline.mit.edu/logout",
	environment: EnvironmentTypes.PRODUCTION,
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		instructorDashboardApp,
		// TODO: add further module libraries as they are migrated to frontend-base
	],
};

export default siteConfig;
