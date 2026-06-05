import {
	footerApp,
	headerApp,
	shellApp,
	EnvironmentTypes,
	type SiteConfig,
} from "@openedx/frontend-base";

import { instructorDashboardApp } from "@openedx/frontend-app-instructor-dashboard";
import { createMITOLFooterApp } from "@shared/footer";

import "@openedx/frontend-base/shell/style";

// Covers both mitx and mitx-staging deployments via a single build.
// Runtime config from /api/frontend_site_config/v1/ overrides URLs per environment.
const siteConfig: SiteConfig = {
	siteId: "mitx",
	siteName: "MITx Residential",
	baseUrl: "https://apps.mitx.mit.edu",
	lmsBaseUrl: "https://lms.mitx.mit.edu",
	loginUrl: "https://lms.mitx.mit.edu/login",
	logoutUrl: "https://lms.mitx.mit.edu/logout",
	headerLogoImageUrl:
		"https://lms.mitx.mit.edu/static/mitx/images/logo.svg",
	environment: EnvironmentTypes.PRODUCTION,
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		createMITOLFooterApp({
			homeUrl: "https://lms.mitx.mit.edu",
			copyrightText: "© MIT Open Learning. All rights reserved except where noted.",
			column1: {
				label: "Resources",
				links: [
					{
						label: "Support",
						url: "https://odl.zendesk.com/hc/en-us/requests/new",
					},
					{
						label: "Accessibility",
						url: "https://accessibility.mit.edu/",
					},
					{
						label: "Open Learning",
						url: "https://openlearning.mit.edu",
					},
				],
			},
			column2: {
				label: "Policies",
				links: [
					{
						label: "Terms of Service",
						url: "https://lms.mitx.mit.edu/tos",
					},
				],
			},
		}),
		instructorDashboardApp,
		// TODO: add further module libraries as they are verified against the named release
	],
};

export default siteConfig;
