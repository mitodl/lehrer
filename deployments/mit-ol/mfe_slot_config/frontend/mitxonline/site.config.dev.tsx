import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import { createMITOLFooterApp } from "@shared/footer";
import { createMITxOnlineHeaderApp } from "@shared/header";

import { createMitxOnlineInstructorDashboardApp } from "./src/instructor-dashboard";

import "@openedx/frontend-base/shell/style";
import "@shared/styles/mitxonline.scss";

const siteConfig: SiteConfig = {
	siteId: "mitol",
	siteName: "MIT Learn (dev)",
	basename: "/",
	baseUrl: "http://apps.local.openedx.io:8090",
	lmsBaseUrl: "http://local.openedx.io:8000",
	loginUrl: "http://local.openedx.io:8000/login",
	logoutUrl: "http://local.openedx.io:8000/logout",
	environment: EnvironmentTypes.DEVELOPMENT,
	// commonAppConfig (mitolHeader / mitolFooter) is loaded at runtime from the LMS
	// frontend_site_config API rather than hardcoded here. The dev server proxies
	// /api/frontend_site_config/v1 to lmsBaseUrl; the response is deep-merged over
	// this static config. Requires ENABLE_MFE_CONFIG_API + FRONTEND_SITE_CONFIG set
	// on the LMS.
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		createMITOLFooterApp(),
		createMITxOnlineHeaderApp(),
		createMitxOnlineInstructorDashboardApp(),
	],
};

export default siteConfig;
