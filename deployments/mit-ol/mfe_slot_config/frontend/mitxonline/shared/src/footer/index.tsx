import { Slot, useSiteConfig, WidgetOperationTypes } from "@openedx/frontend-base";
import type { App, SlotOperation } from "@openedx/frontend-base";
import { Hyperlink, Image } from "@openedx/paragon";

/**
 * Shape of the MIT OL footer config expected in
 * SiteConfig.commonAppConfig.mitolFooter, populated by FRONTEND_SITE_CONFIG
 * in the LMS Django settings and served by /api/frontend_site_config/v1/.
 */
export interface MITOLFooterConfig {
	privacyPolicyUrl?: string;
	termsOfServiceUrl?: string;
	honorCodeUrl?: string;
	aboutUrl?: string;
	supportUrl?: string;
	accessibilityUrl?: string;
	copyrightText?: string;
	footerLogoUrl?: string;
	footerLogoDestination?: string;
}

function useMITOLFooterConfig(): MITOLFooterConfig {
	const { commonAppConfig } = useSiteConfig();
	return ((commonAppConfig as Record<string, unknown>)?.mitolFooter ??
		{}) as MITOLFooterConfig;
}

function CopyrightNotice() {
	const { copyrightText } = useMITOLFooterConfig();
	return (
		<div className="d-flex flex-column justify-content-center">
			{copyrightText && (
				<div className="text-center x-small">{copyrightText}</div>
			)}
			<div className="text-center x-small">
				edX and Open edX are registered trademarks of edX LLC.
			</div>
		</div>
	);
}

/**
 * Footer logo (left side). Reads footerLogoUrl from the runtime config;
 * falls back to the shell's default (headerLogoImageUrl) if not set.
 */
function FooterLogo() {
	const { footerLogoUrl, footerLogoDestination } = useMITOLFooterConfig();
	const { headerLogoImageUrl } = useSiteConfig();
	const src = footerLogoUrl || headerLogoImageUrl;
	if (!src) return null;
	const img = <Image src={src} style={{ maxHeight: '2rem', height: '33px' }} />;
	if (footerLogoDestination) {
		return <Hyperlink destination={footerLogoDestination} className="p-0">{img}</Hyperlink>;
	}
	return img;
}

/** Recreation of the shell's PoweredBy widget (it is not exported from the root). */
function PoweredBy() {
	return (
		<Hyperlink destination="https://openedx.org">
			<Image
				width="120px"
				alt="Powered by Open edX"
				src="https://logos.openedx.org/open-edx-logo-tag.png"
			/>
		</Hyperlink>
	);
}

/**
 * Custom desktop footer layout replacing the shell's DesktopFooterLayout so we
 * can match the legacy learning MFE: logo left, a tight stack of the centered
 * link row + copyright/trademark in the middle, and the "Powered by Open edX"
 * logo at the TOP right. The shell layout used `justify-content-between` (a
 * paragon-layer `!important` utility we cannot override from our site layer),
 * which forced a large gap between the links and copyright and pushed the
 * "Powered by" logo to the bottom.
 */
function MITOLDesktopFooterLayout() {
	return (
		<footer className="d-flex flex-column align-items-stretch">
			<div className="py-3 px-3 d-flex flex-column flex-md-row gap-4 gap-md-5 justify-content-md-between align-items-center align-items-md-start">
				<div className="flex-basis-0 d-flex align-items-center">
					<Slot id="org.openedx.frontend.slot.footer.desktopLeftLinks.v1" />
				</div>
				<div className="flex-grow-1 flex-basis-0 d-flex justify-content-center">
					<div className="d-flex flex-column align-items-center gap-2">
						<Slot id="org.openedx.frontend.slot.footer.desktopCenterLinks.v1" />
						<Slot id="org.openedx.frontend.slot.footer.desktopLegalNotices.v1" />
					</div>
				</div>
				<div className="flex-basis-0 d-flex justify-content-center justify-content-md-end align-items-start">
					<PoweredBy />
				</div>
			</div>
		</footer>
	);
}

/**
 * Single horizontal row of footer links matching the legacy learning MFE
 * (About Us · Terms of Service · Accessibility · Help), centered, with no
 * column labels. Each link is omitted if its URL is missing from the runtime
 * config.
 */
function MITOLFooterLinks() {
	const { aboutUrl, termsOfServiceUrl, accessibilityUrl, supportUrl } =
		useMITOLFooterConfig();
	const links = [
		{ url: aboutUrl, label: "About Us" },
		{ url: termsOfServiceUrl, label: "Terms of Service" },
		{ url: accessibilityUrl, label: "Accessibility" },
		{ url: supportUrl, label: "Help" },
	].filter((link) => Boolean(link.url));
	if (links.length === 0) return null;
	return (
		<ul className="d-flex flex-column flex-md-row flex-wrap list-unstyled gap-3 gap-md-4 menu-links align-items-center justify-content-center mb-0">
			{links.map((link) => (
				<li key={link.label} className="mx-2">
					<Hyperlink destination={link.url as string}>{link.label}</Hyperlink>
				</li>
			))}
		</ul>
	);
}

/**
 * Returns an App that injects MIT OL footer content into footerApp's slots.
 * All link URLs are read at render time from SiteConfig.commonAppConfig.mitolFooter,
 * populated via FRONTEND_SITE_CONFIG in the LMS Django settings. A widget renders
 * nothing if its URL is absent from the runtime config.
 */
export function createMITOLFooterApp(): App {
	const slots: SlotOperation[] = [
		// Replace the shell's desktop footer layout with our own so we control the
		// link/copyright spacing and place "Powered by Open edX" at the top right.
		{
			slotId: "org.openedx.frontend.slot.footer.desktop.v1",
			relatedId: "org.openedx.frontend.widget.footer.desktopLayout.v1",
			id: "mitol.footer.desktopLayout",
			op: WidgetOperationTypes.REPLACE,
			component: MITOLDesktopFooterLayout,
		},
		// Remove the shell's default copyright line (e.g. "© 2026 MIT Learn (dev).")
		// so only the MIT OL copyright + trademark notice remain, matching the
		// legacy learning MFE footer.
		{
			slotId: "org.openedx.frontend.slot.footer.desktopLegalNotices.v1",
			relatedId: "org.openedx.frontend.widget.footer.desktopCopyrightNotice.v1",
			op: WidgetOperationTypes.REMOVE,
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopLegalNotices.v1",
			id: "mitol.footer.copyright",
			op: WidgetOperationTypes.APPEND,
			component: CopyrightNotice,
		},
		// Replace the shell's default logo (which uses headerLogoImageUrl) with
		// our FooterLogo component that reads footerLogoUrl from the config.
		{
			slotId: "org.openedx.frontend.slot.footer.desktopLeftLinks.v1",
			relatedId: "org.openedx.frontend.widget.footer.desktopLeftLinksLogo.v1",
			id: "mitol.footer.logo",
			op: WidgetOperationTypes.REPLACE,
			component: FooterLogo,
		},
		// Single centered horizontal row of links (no column labels) matching
		// the legacy learning MFE footer. Append directly to the center-links
		// container (CenterLinks layout) instead of a desktopCenterLinkN.v1 slot
		// so the links are NOT wrapped in frontend-base's LabeledLinkColumn
		// (which forces `small` font + a flex column). Remove the 4 default
		// column slots so only our row renders.
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLinks.v1",
			relatedId: "org.openedx.frontend.widget.footer.desktopCenterLink1.v1",
			op: WidgetOperationTypes.REMOVE,
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLinks.v1",
			relatedId: "org.openedx.frontend.widget.footer.desktopCenterLink2.v1",
			op: WidgetOperationTypes.REMOVE,
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLinks.v1",
			relatedId: "org.openedx.frontend.widget.footer.desktopCenterLink3.v1",
			op: WidgetOperationTypes.REMOVE,
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLinks.v1",
			relatedId: "org.openedx.frontend.widget.footer.desktopCenterLink4.v1",
			op: WidgetOperationTypes.REMOVE,
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLinks.v1",
			id: "mitol.footer.links",
			op: WidgetOperationTypes.APPEND,
			component: MITOLFooterLinks,
		},
	];

	return { appId: "mitol.footer", slots };
}
