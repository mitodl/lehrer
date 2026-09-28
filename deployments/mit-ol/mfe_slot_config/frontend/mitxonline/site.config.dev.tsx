import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import devHosts from "@shared/dev-hosts.json";
import { createMITOLFooterApp } from "@shared/footer";
import { createMITxOnlineHeaderApp } from "@shared/header";

import { adminConsoleApp } from "@openedx/frontend-app-admin-console";
import { gradebookApp } from "@openedx/frontend-app-gradebook";

import { createMITxOnlineInstructorDashboardApp } from "./src/instructor-dashboard";

import "@openedx/frontend-base/shell/style";
import "@shared/styles/mitxonline.scss";

const siteConfig: SiteConfig = {
	siteId: "mitol",
	siteName: "MIT Learn (dev)",
	basename: "/",
	baseUrl: devHosts.sites.mitxonline,
	lmsBaseUrl: devHosts.lmsBaseUrl,
	loginUrl: `${devHosts.lmsBaseUrl}/login`,
	logoutUrl: `${devHosts.lmsBaseUrl}/logout`,
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
		createMITxOnlineInstructorDashboardApp(),
		// Not nested under /apps like the instructor dashboard: both register
		// absolute route paths (/admin-console/authz/*, /gradebook/:courseId) and
		// admin-console builds its links from that absolute base. Fastly serves this
		// Site Project at those paths, which are also the URLs the LMS already links
		// to (ADMIN_CONSOLE_MICROFRONTEND_URL, WRITABLE_GRADEBOOK_URL).
		adminConsoleApp,
		gradebookApp,
	],
};

export default siteConfig;
