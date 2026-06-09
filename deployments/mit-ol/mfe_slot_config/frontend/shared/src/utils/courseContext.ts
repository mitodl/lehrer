const UAI_COURSE_KEYS = [
	"course-v1:uai_",
	"course-v1:b2c+uai.",
	"course-v1:mitxt+ctl.scx_wm+1t2026",
];

const COURSE_KEY_REGEX = "(?:course-v1:[^/+]+(/|\\+)[^/+]+(/|\\+)[^/?]+)";

const safeDecodeURIComponent = (value: string): string => {
	try {
		return decodeURIComponent(value);
	} catch {
		return value;
	}
};

/**
 * Returns true when the current URL contains a UAI/MIT Learn course key.
 * These courses belong to the learn.mit.edu product; dashboard and support URLs
 * must point to learn.mit.edu rather than mitxonline.mit.edu for them.
 */
export function isLearnCourse(): boolean {
	const href = (
		(typeof window !== "undefined" ? window.location?.href : undefined) ??
		(typeof document !== "undefined" ? document.URL : "") ??
		""
	).toLowerCase();
	return UAI_COURSE_KEYS.some((key) => {
		const encodedKey = encodeURIComponent(key).toLowerCase();
		return href.includes(key) || href.includes(encodedKey);
	});
}

/**
 * Returns true when the current URL contains any MITx Online course key
 * (i.e. a course-v1: key that is NOT a UAI/Learn course).
 * Used to show/hide mitxonline-specific UI (profile, account settings links)
 * that should be hidden for both UAI courses and non-course pages.
 */
export function isMITxOnlineCourse(): boolean {
	const href = (
		(typeof window !== "undefined" ? window.location?.href : undefined) ??
		(typeof document !== "undefined" ? document.URL : "") ??
		""
	).toLowerCase();
	const decodedHref = safeDecodeURIComponent(href);
	const isCourseKeyInPath = new RegExp(COURSE_KEY_REGEX, "i").test(decodedHref);
	return isCourseKeyInPath && !isLearnCourse();
}
