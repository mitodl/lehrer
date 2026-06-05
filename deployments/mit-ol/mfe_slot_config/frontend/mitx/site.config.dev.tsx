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

const siteConfig: SiteConfig = {
	siteId: "mitx",
	siteName: "MITx Residential (dev)",
	baseUrl: "http://apps.local.openedx.io:8080",
	lmsBaseUrl: "http://local.openedx.io:8000",
	loginUrl: "http://local.openedx.io:8000/login",
	logoutUrl: "http://local.openedx.io:8000/logout",
	environment: EnvironmentTypes.DEVELOPMENT,
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		createMITOLFooterApp({
			homeUrl: "http://local.openedx.io:8000",
			copyrightText: "© MIT Open Learning. All rights reserved except where noted.",
			column1: {
				label: "Resources",
				links: [
					{ label: "Support", url: "http://local.openedx.io:8000/support/" },
					{ label: "Accessibility", url: "https://accessibility.mit.edu/" },
					{ label: "Open Learning", url: "https://openlearning.mit.edu" },
				],
			},
			column2: {
				label: "Policies",
				links: [
					{ label: "Terms of Service", url: "http://local.openedx.io:8000/tos" },
				],
			},
		}),
		instructorDashboardApp,
	],
};

export default siteConfig;
