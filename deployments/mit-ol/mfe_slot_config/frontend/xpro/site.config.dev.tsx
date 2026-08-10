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

const siteConfig: SiteConfig = {
	siteId: "xpro",
	siteName: "MIT xPRO (dev)",
	basename: "/",
	baseUrl: "http://apps.local.openedx.io:8090",
	lmsBaseUrl: "http://local.openedx.io:8000",
	loginUrl: "http://local.openedx.io:8000/login",
	logoutUrl: "http://local.openedx.io:8000/logout",
	environment: EnvironmentTypes.DEVELOPMENT,
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
	],
};

export default siteConfig;
