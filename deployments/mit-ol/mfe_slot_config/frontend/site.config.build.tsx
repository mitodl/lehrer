import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import "@openedx/frontend-base/shell/style";

// TODO: import migrated module library app configs as they are published
// import { learningApp } from '@openedx/frontend-app-learning';
// import { accountApp } from '@openedx/frontend-app-account';

// Note: frontend-base removes process.env / dotenv.
// All config lives here and/or is delivered at runtime via runtimeConfigJsonUrl.
const siteConfig: SiteConfig = {
	siteId: "mitol",
	siteName: "MIT OpenLearning",
	baseUrl: "https://apps.mitxonline.mit.edu",
	lmsBaseUrl: "https://courses.mitxonline.mit.edu",
	loginUrl: "https://courses.mitxonline.mit.edu/login",
	logoutUrl: "https://courses.mitxonline.mit.edu/logout",
	environment: EnvironmentTypes.PRODUCTION,
	// Runtime config is fetched at startup and can override these values.
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		// TODO: add module library configs here once MFEs are migrated
		// learningApp,
		// accountApp,
	],
};

export default siteConfig;
