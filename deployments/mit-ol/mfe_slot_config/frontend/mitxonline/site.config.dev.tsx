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
import { createStyleOverrideApp } from "@shared/styles/styleLoader";

import "@openedx/frontend-base/shell/style";

const siteConfig: SiteConfig = {
	siteId: "mitol",
	siteName: "MIT Learn (dev)",
	basename: "/apps/",
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
		createStyleOverrideApp("@shared/styles/mitxonline.scss"),
		createMITOLFooterApp(),
		createMITxOnlineHeaderApp(),
		instructorDashboardApp,
	],
};

export default siteConfig;
