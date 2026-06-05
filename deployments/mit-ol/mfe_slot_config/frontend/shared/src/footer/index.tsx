import {
	useSiteConfig,
	WidgetOperationTypes,
	LayoutOperationTypes,
} from "@openedx/frontend-base";
import type { App, SlotOperation } from "@openedx/frontend-base";
import { Hyperlink } from "@openedx/paragon";

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
}

function useMITOLFooterConfig(): MITOLFooterConfig {
	const { commonAppConfig } = useSiteConfig();
	return ((commonAppConfig as Record<string, unknown>)
		?.mitolFooter ?? {}) as MITOLFooterConfig;
}

function CopyrightNotice() {
	const { copyrightText } = useMITOLFooterConfig();
	if (!copyrightText) return null;
	return <div className="text-center x-small mt-1">{copyrightText}</div>;
}

function AboutLink() {
	const { aboutUrl } = useMITOLFooterConfig();
	if (!aboutUrl) return null;
	return <Hyperlink destination={aboutUrl}>About Us</Hyperlink>;
}

function SupportLink() {
	const { supportUrl } = useMITOLFooterConfig();
	if (!supportUrl) return null;
	return <Hyperlink destination={supportUrl}>Contact</Hyperlink>;
}

function AccessibilityLink() {
	const { accessibilityUrl } = useMITOLFooterConfig();
	if (!accessibilityUrl) return null;
	return <Hyperlink destination={accessibilityUrl}>Accessibility</Hyperlink>;
}

function PrivacyPolicyLink() {
	const { privacyPolicyUrl } = useMITOLFooterConfig();
	if (!privacyPolicyUrl) return null;
	return <Hyperlink destination={privacyPolicyUrl}>Privacy Policy</Hyperlink>;
}

function TermsOfServiceLink() {
	const { termsOfServiceUrl } = useMITOLFooterConfig();
	if (!termsOfServiceUrl) return null;
	return (
		<Hyperlink destination={termsOfServiceUrl}>Terms of Service</Hyperlink>
	);
}

function HonorCodeLink() {
	const { honorCodeUrl } = useMITOLFooterConfig();
	if (!honorCodeUrl) return null;
	return <Hyperlink destination={honorCodeUrl}>Honor Code</Hyperlink>;
}

/**
 * Returns an App that injects MIT OL footer content into footerApp's slots.
 * All link URLs are read at render time from SiteConfig.commonAppConfig.mitolFooter,
 * populated via FRONTEND_SITE_CONFIG in the LMS Django settings. A widget renders
 * nothing if its URL is absent from the runtime config.
 */
export function createMITOLFooterApp(): App {
	const slots: SlotOperation[] = [
		{
			slotId: "org.openedx.frontend.slot.footer.desktopLegalNotices.v1",
			id: "mitol.footer.copyright",
			op: WidgetOperationTypes.APPEND,
			component: CopyrightNotice,
		},
		// Column 1: Resources
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLink1.v1",
			op: LayoutOperationTypes.OPTIONS,
			options: { label: "Resources" },
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLink1.v1",
			id: "mitol.footer.col1.about",
			op: WidgetOperationTypes.APPEND,
			component: AboutLink,
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLink1.v1",
			id: "mitol.footer.col1.contact",
			op: WidgetOperationTypes.APPEND,
			component: SupportLink,
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLink1.v1",
			id: "mitol.footer.col1.accessibility",
			op: WidgetOperationTypes.APPEND,
			component: AccessibilityLink,
		},
		// Column 2: Policies
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLink2.v1",
			op: LayoutOperationTypes.OPTIONS,
			options: { label: "Policies" },
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLink2.v1",
			id: "mitol.footer.col2.privacy",
			op: WidgetOperationTypes.APPEND,
			component: PrivacyPolicyLink,
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLink2.v1",
			id: "mitol.footer.col2.tos",
			op: WidgetOperationTypes.APPEND,
			component: TermsOfServiceLink,
		},
		{
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLink2.v1",
			id: "mitol.footer.col2.honor-code",
			op: WidgetOperationTypes.APPEND,
			component: HonorCodeLink,
		},
	];

	return { appId: "mitol.footer", slots };
}
