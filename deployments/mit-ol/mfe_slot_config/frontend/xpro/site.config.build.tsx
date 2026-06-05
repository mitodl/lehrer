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

// xPRO nav model differs from mitxonline: marketing site is at xpro.mit.edu (separate from LMS).
// The MARKETING_SITE_BASE_URL distinction means the header home link points to the marketing site,
// not the LMS. This is handled via runtime config overriding baseUrl per environment.
const siteConfig: SiteConfig = {
	siteId: "xpro",
	siteName: "MIT xPRO",
	baseUrl: "https://apps.xpro.mit.edu",
	lmsBaseUrl: "https://courses.xpro.mit.edu",
	loginUrl: "https://courses.xpro.mit.edu/login",
	logoutUrl: "https://courses.xpro.mit.edu/logout",
	headerLogoImageUrl:
		"https://courses.xpro.mit.edu/static/xpro/images/logo.svg",
	environment: EnvironmentTypes.PRODUCTION,
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		createMITOLFooterApp({
			homeUrl: "https://xpro.mit.edu",
			copyrightText: "© MIT xPRO. All rights reserved except where noted.",
			column1: {
				label: "Resources",
				links: [
					{ label: "About Us", url: "https://xpro.mit.edu/about-us/" },
					{ label: "Support", url: "https://xpro.zendesk.com/hc" },
					{
						label: "Accessibility",
						url: "https://accessibility.mit.edu/",
					},
				],
			},
			column2: {
				label: "Policies",
				links: [
					{
						label: "Privacy Policy",
						url: "https://xpro.mit.edu/privacy-policy/",
					},
					{
						label: "Terms of Service",
						url: "https://xpro.mit.edu/terms-of-service/",
					},
					{
						label: "Honor Code",
						url: "https://xpro.mit.edu/honor-code/",
					},
				],
			},
		}),
		instructorDashboardApp,
		// TODO: add further module libraries as they are verified against the named release
	],
};

export default siteConfig;
