import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import { createMITOLFooterApp } from "@shared/footer";
import { createMITxOnlineHeaderApp } from "@shared/header";

import { createMITxOnlineInstructorDashboardApp } from "./src/instructor-dashboard";

import "@openedx/frontend-base/shell/style";
import "@shared/styles/mitxonline.scss";

// Production defaults — most fields are overridden at runtime by /api/frontend_site_config/v1/,
// which reads from the FRONTEND_SITE_CONFIG Django setting in the LMS configmap.
const siteConfig: SiteConfig = {
	siteId: "mitol",
	siteName: "MIT Learn",
	basename: "/",
	// This Site Project is served as a sub-path of the LMS host, not on a host of
	// its own, so baseUrl is the LMS origin. Fastly rewrites /apps/<app>/... to the
	// Site Project's index.html and /apps/mitxonline-site/... to its assets (see "Handle
	// Site Project routing" in ol-infrastructure applications/edxapp/__main__.py);
	// the routes are nested under /apps by wrapWithAppsPath, which is why basename
	// stays "/". FRONTEND_SITE_CONFIG sets no baseUrl, so this value is what the
	// auth redirects fall back to; the apps.*.mit.edu host it used to name has
	// never existed in DNS.
	baseUrl: "https://courses.learn.mit.edu",
	lmsBaseUrl: "https://courses.learn.mit.edu",
	loginUrl: "https://courses.learn.mit.edu/login",
	logoutUrl: "https://courses.learn.mit.edu/logout",
	environment: EnvironmentTypes.PRODUCTION,
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	// Override the proctoring info panel link to the MITx Online ZD article.
	// Note: the type says string[] but the runtime treats this as Record<string,string> — type bug in alpha.
	externalLinkUrlOverrides: {
		"https://support.edx.org/hc/en-us/sections/115004169247-Taking-Timed-and-Proctored-Exams":
			"https://mitxonline.zendesk.com/hc/en-us/articles/4418223178651-What-is-the-Proctortrack-Onboarding-Exam",
	} as unknown as string[],
	apps: [
		shellApp,
		headerApp,
		footerApp,
		createMITOLFooterApp(),
		createMITxOnlineHeaderApp(),
		createMITxOnlineInstructorDashboardApp(),
		// TODO: add further module libraries as they are migrated to frontend-base
	],
};

export default siteConfig;
