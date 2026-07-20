import type { EnrollmentActionsSlotProps } from '@openedx/frontend-app-instructor-dashboard';
import { Button, OverlayTrigger, Tooltip } from '@openedx/paragon';

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
        'Add Beta Testers',
        onAddBetaTesters,
        'mitxonline-add-beta-testers-disabled',
        'You do not have permission to add beta testers to this course.',
        'outline-primary',
      )}
      {gatedButton(
        Boolean(permissions?.admin),
        'Enroll Learners',
        onEnrollLearners,
        'mitxonline-enroll-learners-disabled',
        'You do not have permission to enroll learners in this course.',
      )}
    </>
  );
};

export default EnrollmentActions;
