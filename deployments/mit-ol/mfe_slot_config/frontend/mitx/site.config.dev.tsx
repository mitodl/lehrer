import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type App,
	type SiteConfig,
} from "@openedx/frontend-base";

import { instructorDashboardApp } from "@openedx/frontend-app-instructor-dashboard";
import { createMITOLFooterApp } from "@shared/footer";
import { createMITxHeaderApp } from "@shared/header";
import { createStyleOverrideApp } from "@shared/styles/styleLoader";

import "@openedx/frontend-base/shell/style";

const wrapWithAppsPath = (app: App): App =>
	app.routes
		? { ...app, routes: [{ path: "apps", children: app.routes }] }
		: app;

const siteConfig: SiteConfig = {
	siteId: "mitx",
	siteName: "MITx Residential (dev)",
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
		createStyleOverrideApp("@shared/styles/mitx.scss"),
		createMITOLFooterApp(),
		createMITxHeaderApp(),
		wrapWithAppsPath(instructorDashboardApp),
	],
};

export default siteConfig;
