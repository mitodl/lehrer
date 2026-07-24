import { getConfig } from '@edx/frontend-platform';

export const BUNDLE_PATH = process.env.FEEDBACK_DRAWER_BUNDLE_PATH
  || '/learn/static/smoot-design/feedbackDrawerManager.es.js';

// mit-learn content_feedback endpoint
export const SUBMIT_URL = process.env.FEEDBACK_SUBMIT_URL || undefined;

// Same auth mechanism AskTIM (smoot AiChat) uses: the bundle submits with
// credentials (session cookie) and reads the CSRF token from CSRF_COOKIE_NAME,
// echoing it into CSRF_HEADER_NAME. The cookie name must match the backend's
// CSRF_COOKIE_NAME — mit-learn uses a deployment-specific prefixed name (not the
// bare `csrftoken`), so it's env-configurable via FEEDBACK_CSRF_COOKIE_NAME.
export const CSRF_COOKIE_NAME = process.env.FEEDBACK_CSRF_COOKIE_NAME || 'csrftoken';
export const CSRF_HEADER_NAME = 'X-CSRFToken';

// mit-learn @ensure_csrf_cookie endpoint (e.g. `<mit-learn>/api/v0/users/me/`) the
// drawer primes to obtain the CSRF cookie before submitting.
export const CSRF_PRIME_URL = process.env.FEEDBACK_CSRF_PRIME_URL;

let loadPromise = null;
export const loadBundle = () => {
  if (loadPromise) {
    return loadPromise;
  }
  loadPromise = import(/* webpackIgnore: true */ BUNDLE_PATH)
    .then((module) => {
      if (!module?.init) {
        throw new Error('feedbackDrawerManager bundle has no init()');
      }
      return module;
    })
    .catch((error) => {
      loadPromise = null;
      throw error;
    });
  return loadPromise;
};

export const getMessageOrigin = () => {
  const lmsBaseUrl = getConfig().LMS_BASE_URL;
  try {
    return new URL(lmsBaseUrl).origin;
  } catch (error) {
    return window.location.origin;
  }
};
