import type { EnrollmentActionsSlotProps } from '@openedx/frontend-app-instructor-dashboard';
import { defineMessages, useIntl } from '@openedx/frontend-base';
import { Button, OverlayTrigger, Tooltip } from '@openedx/paragon';

const messages = defineMessages({
  // Reuse the upstream instructor-dashboard message IDs for the button labels so their existing
  // translations carry over (rather than reverting every non-English locale to English).
  addBetaTesters: {
    id: 'instruct.enrollments.addBetaTesters',
    defaultMessage: 'Add Beta Testers',
    description: 'Button label for adding beta testers',
  },
  enrollLearners: {
    id: 'instruct.enrollments.enrollLearners',
    defaultMessage: 'Enroll Learners',
    description: 'Button label and modal title for enrolling learners',
  },
  addBetaTestersDisabledTooltip: {
    id: 'mitxonline.instructorDashboard.enrollmentActions.addBetaTestersDisabledTooltip',
    defaultMessage: 'You do not have permission to add beta testers to this course.',
    description: 'Tooltip shown when the add beta testers button is disabled due to insufficient permissions',
  },
  enrollLearnersDisabledTooltip: {
    id: 'mitxonline.instructorDashboard.enrollmentActions.enrollLearnersDisabledTooltip',
    defaultMessage: 'You do not have permission to enroll learners in this course.',
    description: 'Tooltip shown when the enroll learners button is disabled due to insufficient permissions',
  },
});

/**
 * MITx Online widget for the instructor dashboard enrollment actions slot.
 *
 * Replaces the MFE's default (ungated) widget to reproduce the legacy MITx Online dashboard
 * gating:
 *   - Enroll Learners requires `permissions.admin` (platform staff / is_staff).
 *   - Add Beta Testers requires `permissions.instructor` (the course Admin role).
 *
 * A button the user cannot use stays visible but disabled, with an explanatory tooltip. The
 * modals stay owned by the dashboard's Enrollments page — this widget only renders the buttons
 * and calls the handlers the slot passes in.
 */
const EnrollmentActions = ({ permissions, onEnrollLearners, onAddBetaTesters }: EnrollmentActionsSlotProps) => {
  const intl = useIntl();

  const gatedButton = (
    canAccess: boolean,
    label: string,
    onClick: () => void,
    tooltipId: string,
    tooltip: string,
    variant?: string,
  ) => {
    const button = (
      <Button
        variant={variant}
        onClick={onClick}
        disabled={!canAccess}
        style={canAccess ? undefined : { pointerEvents: 'none' }}
      >
        + {label}
      </Button>
    );

    if (canAccess) {
      return button;
    }

    return (
      <OverlayTrigger placement="top" overlay={<Tooltip id={tooltipId}>{tooltip}</Tooltip>}>
        <span className="d-inline-block" tabIndex={0}>{button}</span>
      </OverlayTrigger>
    );
  };

  return (
    <>
      {gatedButton(
        Boolean(permissions?.instructor),
        intl.formatMessage(messages.addBetaTesters),
        onAddBetaTesters,
        'mitxonline-add-beta-testers-disabled',
        intl.formatMessage(messages.addBetaTestersDisabledTooltip),
        'outline-primary',
      )}
      {gatedButton(
        Boolean(permissions?.admin),
        intl.formatMessage(messages.enrollLearners),
        onEnrollLearners,
        'mitxonline-enroll-learners-disabled',
        intl.formatMessage(messages.enrollLearnersDisabledTooltip),
      )}
    </>
  );
};

export default EnrollmentActions;
