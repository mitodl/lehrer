import React, { useContext, useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { getConfig } from '@edx/frontend-platform';

import Sidebar from './src/courseware/course/sidebar/Sidebar';
import SidebarContext from './src/courseware/course/sidebar/SidebarContext';
import AIDrawerManagerSidebar from './AIDrawerManagerSidebar';
import FeedbackDrawerSlot from './FeedbackDrawerSlot';

const AI_DRAWER_MESSAGE_TYPES = [
    'smoot-design::ai-drawer-open',
    'smoot-design::tutor-drawer-open',
];

const FEEDBACK_OPEN_MESSAGE = 'ol-feedback::drawer-open';
const AI_DRAWER_CLOSE_MESSAGE = 'smoot-design::ai-drawer-close';

// Keeps `--ai-drawer-height` in sync with the visible viewport on scroll/resize;
// shared by AskTIM and feedback slot. `active` = visible AND not full-screen.
const useStickyDrawerHeight = (wrapperRef, active) => {
    useEffect(() => {
        const wrapper = wrapperRef.current;
        if (!wrapper) {
            return undefined;
        }
        if (!active) {
            wrapper.style.removeProperty('--ai-drawer-height');
            return undefined;
        }

        const INSET_PX = 16;
        const mq = window.matchMedia('(min-width: 1025px)');

        let rafId = null;
        let resizeObserver = null;

        const update = () => {
            rafId = null;
            if (!mq.matches) {
                wrapper.style.removeProperty('--ai-drawer-height');
                return;
            }
            const parent = wrapper.parentElement;
            if (!parent) return;
            const parentRect = parent.getBoundingClientRect();
            const stickyTop = Math.max(parentRect.top, INSET_PX);
            const effectiveBottom = Math.min(window.innerHeight - INSET_PX, parentRect.bottom);
            const available = effectiveBottom - stickyTop;

            wrapper.style.setProperty(
                '--ai-drawer-height',
                `${Math.max(0, available)}px`,
            );
        };

        const schedule = () => {
            if (rafId == null) {
                rafId = window.requestAnimationFrame(update);
            }
        };

        const detach = () => {
            window.removeEventListener('scroll', schedule);
            window.removeEventListener('resize', schedule);
            if (resizeObserver) {
                resizeObserver.disconnect();
                resizeObserver = null;
            }
            if (rafId != null) {
                window.cancelAnimationFrame(rafId);
                rafId = null;
            }
            wrapper.style.removeProperty('--ai-drawer-height');
        };

        const attach = () => {
            if (mq.matches) {
                window.addEventListener('scroll', schedule, { passive: true });
                window.addEventListener('resize', schedule);
                if (!resizeObserver && wrapper.parentElement && typeof ResizeObserver !== 'undefined') {
                    resizeObserver = new ResizeObserver(schedule);
                    resizeObserver.observe(wrapper.parentElement);
                }
                schedule();
            } else {
                detach();
            }
        };

        mq.addEventListener('change', attach);
        attach();

        return () => {
            mq.removeEventListener('change', attach);
            detach();
        };
    }, [wrapperRef, active]);
};

const SidebarAIDrawerCoordinator = () => {
    const contextValue = useContext(SidebarContext);
    const currentSidebar = contextValue?.currentSidebar ?? null;
    const toggleSidebar = contextValue?.toggleSidebar ?? (() => { });
    const shouldDisplayFullScreen = contextValue?.shouldDisplayFullScreen ?? false;
    const unitId = contextValue?.unitId ?? null;

    const [showAIDrawer, setShowAIDrawer] = useState(false);
    const [showFeedback, setShowFeedback] = useState(false);
    const prevUnitIdRef = useRef(unitId);
    const showAIDrawerRef = useRef(false);
    const wrapperRef = useRef(null);
    const feedbackWrapperRef = useRef(null);

    const messageOrigin = useMemo(() => {
        const lmsBaseUrl = getConfig().LMS_BASE_URL;
        if (lmsBaseUrl) {
            try {
                return new URL(lmsBaseUrl).origin;
            } catch (error) {
                // ignore; falls through to window.location.origin
            }
        }
        return window.location.origin;
    }, []);

    const handleAIDrawerMessage = useCallback((event) => {
        if (event.origin !== messageOrigin) {
            return;
        }

        const messageType = event.data?.type;

        if (messageType && AI_DRAWER_MESSAGE_TYPES.includes(messageType)) {
            setShowAIDrawer(true);
            // Opening AskTIM hides feedback (they share this column).
            setShowFeedback(false);
            if (currentSidebar !== null) {
                toggleSidebar(null);
            }
        } else if (messageType === FEEDBACK_OPEN_MESSAGE) {
            setShowFeedback(true);
            // Opening feedback hides AskTIM and the discussions sidebar.
            setShowAIDrawer(false);
            if (currentSidebar !== null) {
                toggleSidebar(null);
            }
        }
    }, [messageOrigin, currentSidebar, toggleSidebar]);

    useEffect(() => {
        window.addEventListener('message', handleAIDrawerMessage);
        return () => {
            window.removeEventListener('message', handleAIDrawerMessage);
        };
    }, [handleAIDrawerMessage]);

    useEffect(() => {
        if (currentSidebar !== null) {
            // Opening the discussions sidebar hides both drawers (React state only).
            setShowAIDrawer(false);
            setShowFeedback(false);
        }
    }, [currentSidebar]);

    useEffect(() => {
        showAIDrawerRef.current = showAIDrawer;
    }, [showAIDrawer]);

    useEffect(() => {
        if (prevUnitIdRef.current && prevUnitIdRef.current !== unitId && unitId !== null) {
            // AskTIM's bundle still listens for this close message from the LMS iframe;
            // only send it when the drawer is actually open.
            if (showAIDrawerRef.current) {
                window.postMessage(
                    {
                        type: AI_DRAWER_CLOSE_MESSAGE,
                    },
                    messageOrigin
                );
            }
            setShowAIDrawer(false);
            // Auto-close feedback on unit change too (mirrors AskTIM); handled by state.
            setShowFeedback(false);
        }
        prevUnitIdRef.current = unitId;
    }, [unitId, messageOrigin]);

    useStickyDrawerHeight(wrapperRef, showAIDrawer && !shouldDisplayFullScreen);
    useStickyDrawerHeight(feedbackWrapperRef, showFeedback && !shouldDisplayFullScreen);

    return (
        <>
            {currentSidebar !== null && <Sidebar />}
            <div
                ref={wrapperRef}
                className={`ai-drawer-wrapper ml-0 ml-xl-4 align-top ${shouldDisplayFullScreen ? 'ai-drawer-wrapper-fullscreen' : ''
                } ${showAIDrawer ? '' : 'd-none'}`}
                aria-hidden={!showAIDrawer}
            >
                <AIDrawerManagerSidebar />
            </div>
            <div
                ref={feedbackWrapperRef}
                className={`ai-drawer-wrapper ml-0 ml-xl-4 align-top ${shouldDisplayFullScreen ? 'ai-drawer-wrapper-fullscreen' : ''
                } ${showFeedback ? '' : 'd-none'}`}
                aria-hidden={!showFeedback}
            >
                <FeedbackDrawerSlot />
            </div>
        </>
    );
};

export default SidebarAIDrawerCoordinator;
