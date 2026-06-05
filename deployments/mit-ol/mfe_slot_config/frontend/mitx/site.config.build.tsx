import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import { instructorDashboardApp } from "@openedx/frontend-app-instructor-dashboard";

import "@openedx/frontend-base/shell/style";

// MITx production build. mitx-staging uses this same artifact — the
// runtimeConfigJsonUrl endpoint supplies staging-appropriate URLs at startup.
const siteConfig: SiteConfig = {
	siteId: "mitx",
	siteName: "MITx",
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
		instructorDashboardApp,
		// TODO: add further module libraries as they are verified against the named release
	],
};

export default siteConfig;
