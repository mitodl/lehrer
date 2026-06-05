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

const siteConfig: SiteConfig = {
	siteId: "mitol",
	siteName: "MIT Learn",
	baseUrl: "https://apps.mitxonline.mit.edu",
	lmsBaseUrl: "https://courses.learn.mit.edu",
	loginUrl: "https://courses.learn.mit.edu/login",
	logoutUrl: "https://courses.learn.mit.edu/logout",
	headerLogoImageUrl:
		"https://courses.learn.mit.edu/static/mitxonline/images/logo.svg",
	environment: EnvironmentTypes.PRODUCTION,
	runtimeConfigJsonUrl: "/api/frontend_site_config/v1/",
	apps: [
		shellApp,
		headerApp,
		footerApp,
		createMITOLFooterApp({
			homeUrl: "https://mitxonline.mit.edu",
			copyrightText: "© MIT Open Learning. All rights reserved except where noted.",
			column1: {
				label: "Resources",
				links: [
					{ label: "About Us", url: "https://mitxonline.mit.edu/about-us/" },
					{ label: "Contact", url: "https://support.learn.mit.edu/" },
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
						url: "https://mitxonline.mit.edu/privacy-policy/",
					},
					{
						label: "Terms of Service",
						url: "https://mitxonline.mit.edu/terms-of-service/",
					},
					{
						label: "Honor Code",
						url: "https://mitxonline.mit.edu/honor-code/",
					},
				],
			},
		}),
		instructorDashboardApp,
		// TODO: add further module libraries as they are migrated to frontend-base
	],
};

export default siteConfig;
