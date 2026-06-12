import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import { instructorDashboardApp } from "@openedx/frontend-app-instructor-dashboard";
import { createMITOLFooterApp } from "@shared/footer";
import { createMITxOnlineHeaderApp } from "@shared/header";
import { createInstructorDashboardCustomApp } from "@shared/instructor-dashboard";

import "@openedx/frontend-base/shell/style";
import "@shared/styles/mitxonline.scss";

const siteConfig: SiteConfig = {
	siteId: "mitol",
	siteName: "MIT Learn (dev)",
	baseUrl: "http://apps.local.openedx.io:8080",
	lmsBaseUrl: "http://local.openedx.io:8000",
	loginUrl: "http://local.openedx.io:8000/login",
	logoutUrl: "http://local.openedx.io:8000/logout",
	environment: EnvironmentTypes.DEVELOPMENT,
	headerLogoImageUrl: "https://edx-cdn.org/v3/default/logo.svg",
	commonAppConfig: {
		mitolHeader: {
			mitLearnBaseUrl: "https://learn.mit.edu",
			marketingSiteBaseUrl: "http://local.openedx.io:8000",
		},
		mitolFooter: {
			copyrightText: "© 2026 Massachusetts Institute of Technology",
			aboutUrl: "https://learn.mit.edu/about",
			termsOfServiceUrl: "http://local.openedx.io:8000/tos",
			privacyPolicyUrl: "http://local.openedx.io:8000/privacy",
			accessibilityUrl: "https://accessibility.mit.edu/",
			supportUrl: "https://mitxonline.zendesk.com/hc/en-us",
			honorCodeUrl: "http://local.openedx.io:8000/honor",
		},
	},
	apps: [
		shellApp,
		headerApp,
		footerApp,
		createMITOLFooterApp(),
		createMITxOnlineHeaderApp(),
		{
			...instructorDashboardApp,
			config: {
				...instructorDashboardApp.config,
				SUPPORT_URL: "https://support.learn.mit.edu/",
			},
		},
		createInstructorDashboardCustomApp(),
	],
};

export default siteConfig;
