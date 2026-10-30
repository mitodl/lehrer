import React, { useContext, useEffect, useState } from "react";
import { Button, Dropdown, Collapsible, Hyperlink, Image } from "@openedx/paragon";
import { ExpandLess, ExpandMore } from '@openedx/paragon/icons';
import { getConfig } from '@edx/frontend-platform';
import { PluginSlot } from '@openedx/frontend-plugin-framework';
import { getLoginRedirectUrl } from '@edx/frontend-platform/auth';
import { AppContext } from '@edx/frontend-platform/react';
import { useLocation } from 'react-router-dom';
import { getAuthenticatedHttpClient } from '@edx/frontend-platform/auth';
import { FormattedMessage } from '@edx/frontend-platform/i18n';

function RevealLinks({ label, children }) {

  return (
    <Collapsible.Advanced>
      <div className="d-flex align-items-center">
        <div className="border-top mr-2 flex-grow-1" />
        <Collapsible.Trigger>
          <Button
            data-testid="helpToggleButton"
            variant="outline-primary"
            size="sm"
          >
            <span className="pr-1">{label}</span>
            <Collapsible.Visible whenClosed><ExpandMore /></Collapsible.Visible>
            <Collapsible.Visible whenOpen><ExpandLess /></Collapsible.Visible>
          </Button>
        </Collapsible.Trigger>
        <div className="border-top ml-2 flex-grow-1" />
      </div>
      <Collapsible.Body>
        <div className="d-flex justify-content-center gap-3 align-items-center my-3">
          {children}
        </div>
      </Collapsible.Body>
    </Collapsible.Advanced>
  );
}

function PoweredBy() {
    return (
      <Hyperlink destination="https://openedx.org">
        <Image
          width="120px"
          alt={"Open edX"}
          src="https://logos.openedx.org/open-edx-logo-tag.png"
        />
      </Hyperlink>
    );
  }

export function CopyrightNotice({copyrightText, copyrightMessageId, trademarkMessageId, currentYear}){
    return (
        <div className="d-flex flex-column justify-content-center mb-3">
        <div className="text-center x-small">
          {copyrightMessageId ? (
            <FormattedMessage
              id={copyrightMessageId}
              defaultMessage={copyrightText || copyrightMessageId}
              values={{ year: currentYear }}
            />
          ) : (
            copyrightText
          )}
        </div>
        <div className="text-center x-small">
          <FormattedMessage
            id={trademarkMessageId || 'footer.trademark.notice'}
            defaultMessage="edX and Open edX are registered trademarks of edX LLC."
          />
        </div>
        </div>
    );
}

export function MenuLinks({ menuItems }) {
  return (
    <ul className="d-flex flex-column flex-md-row flex-wrap list-unstyled gap-3 gap-md-4 menu-links align-items-center justify-content-center">
      {
        menuItems.map((item, index) => (
          <li key={index} className="mx-2">
            <Hyperlink destination={item.url}>
              {item.messageId ? (
                <FormattedMessage id={item.messageId} defaultMessage={item.title || item.messageId} />
              ) : (
                item.title
              )}
            </Hyperlink>
          </li>
        ))
      }
    </ul>
  );
}


export function Logo({
    imageUrl = 'https://edx-cdn.org/v3/default/logo.svg',
    destinationUrl,
    logoStyle = { maxHeight: '2rem', height: '33px' }
}) {
const image = (
    <Image src={imageUrl} style={logoStyle} />
);

if (destinationUrl === undefined) {
    return image;
}

return (
    <Hyperlink destination={destinationUrl} className="p-0">
    {image}
    </Hyperlink>
);
}

// This is just a dummy config for the default values used when the slot is not overridden.
const config = {
    imageUrl: "dummy image url",
    destinationUrl: "dumy destination url",
    languages: [ // Languages are hidden in our configuration as the functionality is not implemented right now
      { code: "en", name: "English" },
      { code: "es", name: "Español" },
    ],
    centerLinks: [  // Will be used if the slot is not overridden
      {
        label: "First Column",
        links: [
          { label: "About Us", url: "dummy url" },
          { label: "Terms of Service", url: "dummy url" },
          { label: "Privacy Policy", url: "dummy url" },
        ],
      },
      {
        label: "Second Column",
        links: [
            { label: "Honor Code", url: "dummy url" },
            { label: "Accessibility", url: "https://accessibility.mit.edu/" },
        ],
      },
    ],
  };

const ForceLoginRedirect = () => {
  const config = getConfig();
  const { authenticatedUser } = useContext(AppContext);
  const location = useLocation(); // React Router's current page URL
  useEffect(() => {
    const allowedRedirects = ["mitxonline", "xpro"];
    if (
      config.APP_ID === "learning" &&
      allowedRedirects.some((name) => process.env.DEPLOYMENT_NAME?.includes(name)) &&
      authenticatedUser === null
    ) {
      const destination = getLoginRedirectUrl(
        `${process.env.LEARNING_BASE_URL}${location.pathname}${location.search}`
      );
      window.location.replace(destination);
    }
  }, [config, authenticatedUser, location]);

  return null;
};

const AutoSelectLanguage = () => {
  const config = getConfig();
  const location = useLocation();
  const { authenticatedUser } = useContext(AppContext);

  const lmsBaseURL = config.LMS_BASE_URL;
  const studioBaseURL = config.STUDIO_BASE_URL;
  const username = authenticatedUser?.username;
  const DEVELOPMENT_ENVIRONMENT = "development";
  const AUTHORING_APP_ID = "authoring";
  const ENGLISH_LANG_CODE = "en";
  const LANGUAGE_PREFERENCE_COOKIE_NAME =
    config.LANGUAGE_PREFERENCE_COOKIE_NAME ||
    process.env.LANGUAGE_PREFERENCE_COOKIE_NAME ||
    `${process.env.ENVIRONMENT}-openedx-language-preference`;
  const courseKeyRegex = /course-v1:[^/]+/;
  const reloadCookieName = "authoringLangCookieReloaded";

  // Helper to escape regex metacharacters in cookie name
  const escapeRegExp = (string) => string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const getCookie = (name) => {
    const safeName = escapeRegExp(name);
    const match = document.cookie.match(new RegExp(`(^| )${safeName}=([^;]+)`));
    return match ? decodeURIComponent(match[2]) : null;
  };
  const setCookie = (name, value, days = 1, domainAttr = null) => {
    const expires = new Date(Date.now() + days * 864e5).toUTCString();
    document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/${domainAttr};`;
  };
  const removeCookie = (name, domainAttr = null) => {
    document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/${domainAttr};`;
  };

  /**
   * Returns cookie domain attribute string:
   *   "; Domain=example.com"
   * or "" if unable to determine domain.
   *
   * Rules:
   * - If URL contains `lmsBaseURL`, use hostname from `lmsBaseURL` as-is
   * - Otherwise, remove ONLY the first subdomain from the URL hostname
   */
  const getReloadCookieDomainAttr = (url) => {
    try {
      // Case 1: Prefer domain from lmsBaseURL when contained
      if (lmsBaseURL && url.includes(lmsBaseURL)) {
        const lmsHostname = new URL(lmsBaseURL).hostname;
        return lmsHostname ? `; Domain=${lmsHostname}` : "";
      }

      // Case 2: Fallback → remove first subdomain
      const hostname = new URL(url).hostname;
      const parts = hostname.split(".");

      // If hostname has <= 2 labels, nothing to strip
      if (parts.length <= 2) {
        return `; Domain=${hostname}`;
      }

      // Remove ONLY the first subdomain
      const withoutFirstSubdomain = parts.slice(1).join(".");

      return `; Domain=${withoutFirstSubdomain}`;
    } catch (error) {
      if (process.env.NODE_ENV === DEVELOPMENT_ENVIRONMENT) {
        console.error("Failed to parse URL:", error);
      }
      return "";
    }
  };

  async function setLanguage(baseURL, language) {
    try {
      const response = await getAuthenticatedHttpClient().patch(
        `${baseURL}/api/user/v1/preferences/${username}`,
        { "pref-lang": language },
        { headers: { "Content-Type": "application/merge-patch+json" } }
      );
      return response.status === 204;
    } catch (error) {
      if (process.env.NODE_ENV === DEVELOPMENT_ENVIRONMENT) {
        console.error("Language update failed:", error);
      }
      return false;
    }
  }

  // This API is provided by the ol-openedx-auto-select-language plugin https://github.com/mitodl/open-edx-plugins/tree/main/src/ol_openedx_auto_select_language
  async function fetchCourseLanguage(courseKey) {
    const url = `${lmsBaseURL}/auto-select-language/api/course-language/${courseKey}`;
    try {
      const { data } = await getAuthenticatedHttpClient().get(url);
      return data?.language;
    } catch (error) {
      if (process.env.NODE_ENV === DEVELOPMENT_ENVIRONMENT) {
        console.warn("Course language fetch failed:", error);
      }
      return null;
    }
  }

  useEffect(() => {
    if (!username) return;

    const cookieLang = getCookie(LANGUAGE_PREFERENCE_COOKIE_NAME);
    // Studio (Authoring App) logic
    if (process.env.APP_ID === AUTHORING_APP_ID) {
      // Only reset if reload cookie does not exist and language is not English
      if (cookieLang === ENGLISH_LANG_CODE || getCookie(reloadCookieName)) return;

      (async () => {
        try {
          const updated = await setLanguage(studioBaseURL, ENGLISH_LANG_CODE);
          if (updated) {
            const cookieDomainAttr = getReloadCookieDomainAttr(studioBaseURL);
            setCookie(reloadCookieName, "true", 1, cookieDomainAttr);
            window.location.reload();
          }
        } catch (error) {
          if (process.env.NODE_ENV === DEVELOPMENT_ENVIRONMENT) {
            console.error("Failed to set authoring language:", error);
          }
        }
      })();
      return;
    }

    const match = location.pathname.match(courseKeyRegex);
    if (!match) return;

    const courseKey = match[0];
    (async () => {
      const courseLang = await fetchCourseLanguage(courseKey);
      if (
        courseLang &&
        cookieLang &&
        courseLang !== cookieLang
      ) {
        const updated = await setLanguage(lmsBaseURL, courseLang);
        if (updated) {
          const cookieDomainAttr = getReloadCookieDomainAttr(lmsBaseURL);
          removeCookie(reloadCookieName, cookieDomainAttr); // Remove after setting in learning MFE
          window.location.reload();
        }
      }
    })();

  }, [location.pathname, username]);

  return null;
};

const AppziScript = () => {
  const appziUrl = process.env.APPZI_URL;

  useEffect(() => {
    if (!appziUrl) {
      return;
    }
    const script = document.createElement('script');
    script.src = appziUrl;
    script.async = true;
    document.head.appendChild(script);
  }, []);

  return null;
};

const CONTACT_US_RECHECK_MS = 60000;
// Matches both the learning MFE's /course/course-v1:ORG+NUM+RUN and Studio's
// /container/block-v1:ORG+NUM+RUN+type@...; the first three segments are the
// course triple in either form. Anchored to a path boundary so ccx-block-v1:,
// which contains block-v1:, does not resolve to its parent course.
const COURSE_TRIPLE_REGEX = /(?:^|\/)(?:course-v1|block-v1):([^/+]+\+[^/+]+\+[^/+?#]+)/;

// The pathname arrives percent-encoded; the MFE only redirects to the decoded
// URL after a first render, so decode here to resolve the key on render one.
const decodePathname = (pathname) => {
  try {
    return decodeURIComponent(pathname);
  } catch {
    // A stray % is not valid encoding.
    return pathname;
  }
};

// Module scope, not component state: route changes remount the footer, and
// unmounting the launcher loses the open chat and files a second ticket.

// Fetched once per page, apart from the launcher, so a re-enable need not refetch.
let bundleLoad = null;
let launcher = null;
// A bundle may return no handle, so track mounted-ness separately.
let launcherMounted = false;
// Desired state: a flag flip mid-load must be visible to the load's callback.
let launcherWanted = false;
// Written by the component so the async mount reads current values.
let launcherOptions = null;

const loadContactUsBundle = () => {
  if (bundleLoad) {
    return bundleLoad;
  }
  // Only the learning MFE ships this bundle. Absolute URL because authoring is a
  // different origin, and a classic script needs no CORS.
  const bundlePath = process.env.CONTACT_US_BUNDLE_PATH
    || `${getConfig().LMS_BASE_URL}/learn/static/smoot-design/contactUsLauncher.umd.js`;
  bundleLoad = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = bundlePath;
    script.async = true;
    script.onerror = () => {
      reject(new Error(`failed to load bundle from ${bundlePath}`));
    };
    script.onload = () => {
      if (!window.contactUsLauncher?.init) {
        // A 404 rewritten to index.html can fire `load`, not `error`.
        reject(new Error(`bundle at ${bundlePath} has no init()`));
        return;
      }
      resolve(window.contactUsLauncher);
    };
    document.head.appendChild(script);
  });
  // Keep the rejection, unlike feedbackBundle.js: that retries on a click, this
  // would refetch on every remount for a failure that will not fix itself.
  bundleLoad.catch((error) => {
    // Pass the error, not its message: the bundle can throw a non-Error.
    console.error('ContactUsLauncherScript:', error);
  });
  return bundleLoad;
};

const mountContactUsLauncher = () => {
  launcherWanted = true;
  if (launcherMounted) {
    return;
  }
  loadContactUsBundle()
    .then((bundle) => {
      // The flag can go off, or another caller can win, while the bundle loads.
      if (!launcherWanted || launcherMounted) {
        return;
      }
      try {
        const {
          apiUrl, userEmail, userName, userUsername,
        } = launcherOptions;
        // learn-ai has no session on this cross-origin POST, so these are the
        // ticket's only requester fields.
        const requestBody = {
          ...(userEmail ? { user_email: userEmail } : {}),
          ...(userName ? { user_name: userName } : {}),
          ...(userUsername ? { user_username: userUsername } : {}),
        };
        launcher = bundle.init({
          settings: {
            chat: { apiUrl, requestBody },
          },
        });
        launcherMounted = true;
      } catch (error) {
        // Otherwise the promise swallows it and nothing says why.
        console.error('ContactUsLauncherScript:', error);
      }
    })
    .catch(() => {
      // The bundle itself failed; loadContactUsBundle already reported it.
    });
};

const unmountContactUsLauncher = () => {
  launcherWanted = false;
  if (!launcherMounted) {
    return;
  }
  try {
    launcher?.unmount();
  } catch (error) { /* unmount handles its own errors */ }
  launcher = null;
  launcherMounted = false;
};

// Drop a mount still waiting on the bundle: it was wanted for the course we are
// leaving. A card already up stays, so the learner does not lose it.
const cancelPendingMount = () => {
  if (!launcherMounted) {
    launcherWanted = false;
  }
};

// Cached per course so a remount reuses the answer. null means not yet answered.
let gateCourseKey = null;
let gateEnabled = null;
let gateLastCheck = 0;
let gateSeq = 0;

const applyContactUsGate = (enabled) => {
  gateEnabled = enabled;
  if (enabled) {
    mountContactUsLauncher();
  } else {
    unmountContactUsLauncher();
  }
};

// No answer yet (null) means fail closed. With an answer, only an explicit false
// removes the launcher, so a blip cannot kill a live chat. Read when the answer
// lands: a re-check can supersede a first check that never answered.
const checkContactUsGate = (courseKey) => {
  gateSeq += 1;
  const mySeq = gateSeq;
  gateLastCheck = Date.now();
  fetch(
    `${getConfig().LMS_BASE_URL}/ol-openedx-chat/api/contact-us-enabled/${courseKey}`,
    { credentials: 'omit' },
  )
    .then((response) => (response.ok ? response.json() : null))
    .then((data) => {
      // A superseded course's answer must not overwrite the current course's.
      if (mySeq !== gateSeq) {
        return;
      }
      if (data?.enabled === true) {
        applyContactUsGate(true);
      } else if (gateEnabled === null || data?.enabled === false) {
        applyContactUsGate(false);
      }
    })
    .catch(() => {
      if (mySeq === gateSeq && gateEnabled === null) {
        applyContactUsGate(false);
      }
    });
};

const ContactUsLauncherScript = () => {
  const { authenticatedUser } = useContext(AppContext);
  const location = useLocation();
  const apiUrl = process.env.CONTACT_US_SUPPORT_API_URL;
  const userEmail = authenticatedUser?.email;
  const userName = authenticatedUser?.name;
  const userUsername = authenticatedUser?.username;

  const match = decodePathname(location.pathname).match(COURSE_TRIPLE_REGEX);
  const courseKey = match ? `course-v1:${match[1]}` : '';

  useEffect(() => {
    if (!apiUrl) {
      return undefined;
    }
    launcherOptions = {
      apiUrl, userEmail, userName, userUsername,
    };

    // An empty key means no information, not "off": do not ask, and do not
    // disturb a card already up.
    if (courseKey && courseKey !== gateCourseKey) {
      // A new course needs its own answer. The launcher stays up until it
      // lands, to avoid a flicker.
      cancelPendingMount();
      gateCourseKey = courseKey;
      gateEnabled = null;
      checkContactUsGate(courseKey);
    } else if (courseKey && gateEnabled !== null) {
      // Same course: reuse the answer. A check in flight applies itself.
      applyContactUsGate(gateEnabled);
    }

    // Re-check the course this render is on, not the one the module remembers:
    // they differ across a keyless route.
    const onVisible = () => {
      if (courseKey && courseKey === gateCourseKey
          && document.visibilityState === 'visible'
          && Date.now() - gateLastCheck > CONTACT_US_RECHECK_MS) {
        checkContactUsGate(courseKey);
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [apiUrl, courseKey, userEmail, userName, userUsername]);

  return null;
};

const Footer = () => {

  const {
    imageUrl,
    destinationUrl,
    languages = [],
    centerLinks = [],
  } = config;

  return (
    <footer className="d-flex flex-column align-items-stretch">
      <ForceLoginRedirect />
      <AppziScript />
      <ContactUsLauncherScript />
      {
          (process.env.ENABLE_AUTO_LANGUAGE_SELECTION === "true") ? <AutoSelectLanguage /> : null
      }
        <PluginSlot id="frontend.shell.footer.desktop.top.ui">
            <RevealLinks label={"Reveal Button"} />
        </PluginSlot>
        <div className="py-3 px-3 d-flex gap-5 justify-content-between align-items-stretch">
            <div className="flex-basis-0 d-flex align-items-start">
                <div className="d-flex gap-3 align-items-center">
                    <PluginSlot id="frontend.shell.footer.desktop.leftLinks.ui">
                        <div className="d-flex flex-column">
                            <Logo imageUrl={imageUrl} destinationUrl={destinationUrl} />
                        </div>
                    </PluginSlot>
                </div>
            </div>

            <div className="flex-grow-1 flex-basis-0 d-flex justify-content-center">
                <div className="d-flex flex-column justify-content-between gap-5">
                <PluginSlot id="frontend.shell.footer.desktop.centerLinks.ui">
                    <div className="d-flex flex-wrap column-gap-6 row-gap-4" style={{ columnGap: "1.5rem" }}>
                        {centerLinks.map((column, index) => (
                        <div className="d-flex flex-grow-1 flex-column gap-2 small">
                            {column.links.map((link, linkIndex) => (
                                <Hyperlink destination={link.url} key={linkIndex}>
                                    {link.label}
                                </Hyperlink>

                            ))}
                        </div>
                    ))}
                    </div>
                    </PluginSlot>
                    <PluginSlot id="frontend.shell.footer.desktop.legalNotices.ui">
                        <div className="d-flex flex-column justify-content-center mb-3">
                            {/* This footer trademark notice is a legal requirement and cannot be removed or modified. */}
                            <div className="text-center x-small">{"edX and Open edX are registered trademarks of edX LLC."}</div>
                        </div>
                    </PluginSlot>
                </div>
            </div>
            <div className="flex-basis-0 d-flex justify-content-end">
                <div className="d-flex flex-column justify-content-between">
                    <PluginSlot id="frontend.shell.footer.desktop.rightLinks.ui">
                        <div className="d-flex flex-column gap-3 align-items-end flex-grow-1 justify-content-between">
                            <Dropdown>
                                <Dropdown.Toggle variant="outline-primary" size="sm">
                                {languages[0].name}
                                </Dropdown.Toggle>
                                <Dropdown.Menu className="overflow-auto" style={{ maxHeight: '320px' }}>
                                {languages.map((language) => (
                                    <Dropdown.Item key={language.code}>
                                        {language.name}
                                    </Dropdown.Item>
                                ))}
                                </Dropdown.Menu>
                            </Dropdown>

                        </div>
                    </PluginSlot>
                    <PoweredBy />
                </div>
            </div>
        </div>
    </footer>
  );
};

export default Footer;
