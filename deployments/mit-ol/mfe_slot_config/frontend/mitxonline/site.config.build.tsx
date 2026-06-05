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
		createStyleOverrideApp("@shared/styles/mitxonline.scss"),
		createMITOLFooterApp(),
		createMITxOnlineHeaderApp(),
		instructorDashboardApp,
		// TODO: add further module libraries as they are migrated to frontend-base
	],
};

export default siteConfig;
