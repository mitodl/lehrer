import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import "@openedx/frontend-base/shell/style";

// Dev config — mirrors site.config.build.tsx with local URLs and DEVELOPMENT environment.
// Run with: openedx dev   (or: dagger call mfe watch-site --site-project .)
const siteConfig: SiteConfig = {
	siteId: "mitol",
	siteName: "MIT OpenLearning (dev)",
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
		// TODO: add module library configs here once MFEs are migrated
	],
};

export default siteConfig;
