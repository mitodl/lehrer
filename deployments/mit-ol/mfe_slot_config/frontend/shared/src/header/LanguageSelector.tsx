import { useEffect, useState, type FC } from "react";
import {
	getAuthenticatedHttpClient,
	getLocale,
	getSiteConfig,
	updateSiteLanguage,
	useAuthenticatedUser,
} from "@openedx/frontend-base";
import { Dropdown } from "@openedx/paragon";

interface LearnerLanguageConfig {
	enabled: boolean;
	languages: { code: string; name: string }[];
}

const learnerLanguageRequests: Record<string, Promise<LearnerLanguageConfig>> = {};

/**
 * Served by the ol-openedx-auto-select-language plugin. `enabled` mirrors its
 * learner-language flag for the course in the page URL (or its global value
 * outside a course), so the dropdown only shows when the learner's own choice
 * wins.
 */
function fetchLearnerLanguageConfig(): Promise<LearnerLanguageConfig> {
	const courseId = window.location.pathname.match(/course-v1:[^/]+/)?.[0] ?? "";
	if (!learnerLanguageRequests[courseId]) {
		const query = courseId ? `?course_id=${encodeURIComponent(courseId)}` : "";
		const url = `${getSiteConfig().lmsBaseUrl}/auto-select-language/api/languages/${query}`;
		learnerLanguageRequests[courseId] = getAuthenticatedHttpClient()
			.get(url)
			.then(({ data }) => data as LearnerLanguageConfig)
			.catch(() => ({ enabled: false, languages: [] }));
	}
	return learnerLanguageRequests[courseId];
}

export const LanguageSelector: FC = () => {
	const authenticatedUser = useAuthenticatedUser();
	const [config, setConfig] = useState<LearnerLanguageConfig | null>(null);

	useEffect(() => {
		fetchLearnerLanguageConfig().then(setConfig);
	}, []);

	if (!authenticatedUser || !config?.enabled || !config.languages.length) {
		return null;
	}
	const current =
		config.languages.find((language) => language.code === getLocale()) ??
		config.languages[0];

	const onSelect = async (code: string | null) => {
		if (!code || code === current.code) return;
		// Course content is rendered by the LMS, so reload to fetch it in the new language.
		await updateSiteLanguage(code).catch(() => undefined);
		window.location.reload();
	};

	return (
		<Dropdown onSelect={onSelect} className="mr-3">
			<Dropdown.Toggle variant="outline-primary" size="sm" id="ol-language-selector">
				{current.name}
			</Dropdown.Toggle>
			<Dropdown.Menu className="overflow-auto" style={{ maxHeight: "320px" }}>
				{config.languages.map((language) => (
					<Dropdown.Item
						key={language.code}
						eventKey={language.code}
						active={language.code === current.code}
					>
						{language.name}
					</Dropdown.Item>
				))}
			</Dropdown.Menu>
		</Dropdown>
	);
};
