import { useContext, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import SidebarContext from './src/courseware/course/sidebar/SidebarContext';
import {
  loadBundle, getMessageOrigin, SUBMIT_URL, CSRF_COOKIE_NAME, CSRF_HEADER_NAME, CSRF_PRIME_URL,
  LOGIN_URL,
} from './feedbackBundle';
import useFeedbackEnrichment from './useFeedbackEnrichment';

const FeedbackDrawerSlot = ({ onClose }) => {
  const { courseId = null, unitId = null } = useContext(SidebarContext) ?? {};
  const getEnrichment = useFeedbackEnrichment(courseId, unitId);
  const containerRef = useRef(null);
  const instanceRef = useRef(null);
  // The bundle is initialised once, so keep the latest onClose in a ref and pass
  // a stable wrapper below; the manager calls it when the drawer closes so the
  // coordinator can hide this (otherwise empty) column.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!containerRef.current) {
      return undefined;
    }
    let isMounted = true;
    loadBundle()
      .then((module) => {
        if (!isMounted || !containerRef.current) {
          return;
        }
        instanceRef.current = module.init(
          {
            messageOrigin: getMessageOrigin(),
            submitUrl: SUBMIT_URL,
            csrfCookieName: CSRF_COOKIE_NAME,
            csrfHeaderName: CSRF_HEADER_NAME,
            csrfPrimeUrl: CSRF_PRIME_URL,
            loginUrl: LOGIN_URL,
            getEnrichment,
            variant: 'slot',
            onClose: () => onCloseRef.current?.(),
          },
          { container: containerRef.current },
        );
      })
      .catch((error) => {
        // Non-fatal for the page, but warn so a missing/broken bundle is debuggable.
        // eslint-disable-next-line no-console
        console.warn('FeedbackDrawerSlot: failed to load/init feedback bundle', error);
      });

    return () => {
      isMounted = false;
      if (instanceRef.current?.unmount) {
        try {
          instanceRef.current.unmount();
        } catch (error) { /* unmount handles its own errors */ }
      }
      instanceRef.current = null;
    };
  }, [getEnrichment]);

  return <div ref={containerRef} className="feedback-drawer-slot-wrapper" />;
};

FeedbackDrawerSlot.propTypes = {
  onClose: PropTypes.func,
};

export default FeedbackDrawerSlot;
