import { Hyperlink } from "@openedx/paragon";
import { LayoutOperationTypes, WidgetOperationTypes } from "@openedx/frontend-base";
import type { App, SlotOperation } from "@openedx/frontend-base";

export interface MITOLFooterLinks {
	/** Copyright line, e.g. "© 2025 Massachusetts Institute of Technology" */
	copyrightText: string;
	column1?: { label: string; links: Array<{ label: string; url: string }> };
	column2?: { label: string; links: Array<{ label: string; url: string }> };
	// homeUrl is unused at runtime (headerLogoImageUrl in SiteConfig drives the logo href)
	homeUrl: string;
}

function linkWidgets(
	slotId: string,
	prefix: string,
	links: Array<{ label: string; url: string }>,
): SlotOperation[] {
	return links.map((link) => ({
		slotId,
		id: `${prefix}.${link.label.toLowerCase().replace(/\s+/g, "-")}`,
		op: WidgetOperationTypes.APPEND,
		element: <Hyperlink destination={link.url}>{link.label}</Hyperlink>,
	}));
}

/**
 * Returns an App whose slot operations inject MIT OL footer content into
 * the slots provided by @openedx/frontend-base's footerApp.
 *
 * Add to site.config.build.tsx apps[] after footerApp:
 *   apps: [shellApp, headerApp, footerApp, createMITOLFooterApp({...}), ...]
 *
 * The headerLogoImageUrl field on SiteConfig drives the logo displayed by the
 * default footerApp left-links slot — set it in SiteConfig, not here.
 */
export function createMITOLFooterApp(links: MITOLFooterLinks): App {
	const slots: SlotOperation[] = [];

	slots.push({
		slotId: "org.openedx.frontend.slot.footer.desktopLegalNotices.v1",
		id: "mitol.footer.copyright",
		op: WidgetOperationTypes.APPEND,
		element: (
			<div className="text-center x-small mt-1">{links.copyrightText}</div>
		),
	});

	if (links.column1) {
		slots.push({
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLink1.v1",
			op: LayoutOperationTypes.OPTIONS,
			options: { label: links.column1.label },
		});
		slots.push(
			...linkWidgets(
				"org.openedx.frontend.slot.footer.desktopCenterLink1.v1",
				"mitol.footer.col1",
				links.column1.links,
			),
		);
	}

	if (links.column2) {
		slots.push({
			slotId: "org.openedx.frontend.slot.footer.desktopCenterLink2.v1",
			op: LayoutOperationTypes.OPTIONS,
			options: { label: links.column2.label },
		});
		slots.push(
			...linkWidgets(
				"org.openedx.frontend.slot.footer.desktopCenterLink2.v1",
				"mitol.footer.col2",
				links.column2.links,
			),
		);
	}

	return {
		appId: "mitol.footer",
		slots,
	};
}
