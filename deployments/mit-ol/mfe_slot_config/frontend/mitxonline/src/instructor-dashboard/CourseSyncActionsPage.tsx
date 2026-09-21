import { useParams } from 'react-router-dom';
import { getAuthenticatedHttpClient, getSiteConfig } from '@openedx/frontend-base';
import { useEffect, useState } from 'react';
import {
  Button, Alert, Spinner, DataTable, Form, ModalDialog, ActionRow,
} from '@openedx/paragon';

const getApiBaseUrl = () => getSiteConfig().lmsBaseUrl;

const ACTION_RESET_ATTEMPTS = 'reset_attempts';
const ACTION_RESCORE = 'rescore';

const ACTION_LABELS: Record<string, string> = {
  [ACTION_RESET_ATTEMPTS]: 'Reset attempts',
  [ACTION_RESCORE]: 'Rescore',
};

interface ActionResult {
  course_id: string;
  action: string;
  status: string;
  task_id?: string;
  error?: string;
  mapped_problem_id?: string;
  only_if_higher?: boolean;
}

// The API reports an outcome per course, so a single submission can come back
// partly successful. Surface the worst outcome so a failure buried under
// successful rows isn't missed.
const summarize = (results: ActionResult[]) => {
  const counts = {
    submitted: results.filter((row) => row.status === 'submitted').length,
    alreadyRunning: results.filter((row) => row.status === 'already_running').length,
    failed: results.filter((row) => row.status === 'failed').length,
  };
  const parts = [`${counts.submitted} submitted`];
  if (counts.alreadyRunning) parts.push(`${counts.alreadyRunning} already running`);
  if (counts.failed) parts.push(`${counts.failed} failed`);

  let variant: 'success' | 'warning' | 'danger' = 'success';
  if (counts.failed) {
    variant = 'danger';
  } else if (counts.alreadyRunning) {
    variant = 'warning';
  }
  return { variant, message: parts.join(', ') };
};

const CourseSyncActionsPage = () => {
  const { courseId } = useParams<{ courseId: string }>();
  const [action, setAction] = useState(ACTION_RESET_ATTEMPTS);
  const [problemId, setProblemId] = useState('');
  const [onlyIfHigher, setOnlyIfHigher] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<ActionResult[] | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  // React Router reuses this component when only :courseId changes (no
  // remount), so state from the previous course would otherwise carry over
  // and a stale problem ID could be submitted against the new course.
  useEffect(() => {
    setAction(ACTION_RESET_ATTEMPTS);
    setProblemId('');
    setOnlyIfHigher(true);
    setLoading(false);
    setError(null);
    setResults(null);
    setShowConfirm(false);
  }, [courseId]);

  const baseUrl = `${getApiBaseUrl()}/courses/${courseId}/course_sync_actions/api`;

  const handleSubmit = async () => {
    const submittedCourseId = courseId;
    setShowConfirm(false);
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const client = getAuthenticatedHttpClient();
      // Send form-encoded so Django's request.POST is populated — the view reads
      // action / problem_id / only_if_higher from form data, which is NOT filled
      // from a JSON body. The course is taken from the URL, not sent here.
      const body = new URLSearchParams({
        action,
        problem_id: problemId.trim(),
        only_if_higher: String(onlyIfHigher),
      });
      const response = await client.post(`${baseUrl}/sync_problem_actions`, body);
      // Navigated to a different course while this request was in flight —
      // don't apply a stale response to the new course's page.
      if (submittedCourseId !== courseId) return;
      setResults(response.data?.results ?? []);
    } catch (err: any) {
      if (submittedCourseId !== courseId) return;
      setError(err.response?.data?.error || err.message || 'An error occurred');
    } finally {
      if (submittedCourseId === courseId) setLoading(false);
    }
  };

  const resultRows = (results ?? []).map((row) => ({
    course: row.course_id,
    status: row.status,
    detail: row.error || row.task_id || '',
  }));

  const summary = results && results.length > 0 ? summarize(results) : null;

  return (
    <div className="course-sync-actions-page p-4">
      <h3>Course Sync Actions</h3>
      <p>
        Reset attempts or rescore a problem for all learners in this course
        <strong> and in every course synced from it</strong>. Enter the problem&apos;s
        usage key as it appears in this course — it is mapped into each synced course
        automatically.
      </p>

      <Form.Group className="mb-3" style={{ maxWidth: '20rem' }}>
        <Form.Label className="mb-1">Action</Form.Label>
        <Form.Control
          as="select"
          value={action}
          onChange={(e) => setAction(e.target.value)}
        >
          <option value={ACTION_RESET_ATTEMPTS}>{ACTION_LABELS[ACTION_RESET_ATTEMPTS]}</option>
          <option value={ACTION_RESCORE}>{ACTION_LABELS[ACTION_RESCORE]}</option>
        </Form.Control>
      </Form.Group>

      <Form.Group className="mb-3" style={{ maxWidth: '40rem' }}>
        <Form.Label className="mb-1">Problem ID</Form.Label>
        <Form.Control
          type="text"
          value={problemId}
          onChange={(e) => setProblemId(e.target.value)}
          placeholder="block-v1:ORG+COURSE+RUN+type@problem+block@abc123"
        />
      </Form.Group>

      {action === ACTION_RESCORE && (
        <Form.Group className="mb-3">
          <Form.Checkbox
            checked={onlyIfHigher}
            onChange={(e) => setOnlyIfHigher(e.target.checked)}
          >
            <strong>Only update a learner&apos;s score if the new score is higher</strong>
          </Form.Checkbox>
        </Form.Group>
      )}

      <Button
        variant="primary"
        onClick={() => setShowConfirm(true)}
        disabled={loading || !problemId.trim()}
      >
        {ACTION_LABELS[action]}
      </Button>

      {loading && (
        <div className="text-center my-3">
          <Spinner animation="border" screenReaderText="Submitting..." />
        </div>
      )}

      {error && <Alert variant="danger" className="my-3">{error}</Alert>}

      {summary && (
        <Alert variant={summary.variant} className="my-3">{summary.message}</Alert>
      )}

      {results && results.length > 0 && (
        <DataTable
          itemCount={resultRows.length}
          data={resultRows}
          columns={[
            { Header: 'Course', accessor: 'course' },
            { Header: 'Status', accessor: 'status' },
            { Header: 'Task / error', accessor: 'detail' },
          ]}
        >
          <DataTable.Table />
        </DataTable>
      )}

      <ModalDialog
        title={`${ACTION_LABELS[action]} for all learners?`}
        isOpen={showConfirm}
        onClose={() => setShowConfirm(false)}
        hasCloseButton
        isBlocking
        isOverflowVisible={false}
      >
        <ModalDialog.Header>
          <ModalDialog.Title>{ACTION_LABELS[action]} for all learners?</ModalDialog.Title>
        </ModalDialog.Header>
        <ModalDialog.Body>
          <p>
            This applies to <strong>every learner</strong> in this course and in all
            courses synced from it.
          </p>
          {action === ACTION_RESET_ATTEMPTS && (
            <p>
              Resetting attempts discards each learner&apos;s existing attempts on this
              problem and cannot be undone.
            </p>
          )}
          <p className="mb-0">Continue?</p>
        </ModalDialog.Body>
        <ModalDialog.Footer>
          <ActionRow>
            <ModalDialog.CloseButton variant="tertiary">Cancel</ModalDialog.CloseButton>
            <Button variant="danger" onClick={handleSubmit}>
              {ACTION_LABELS[action]}
            </Button>
          </ActionRow>
        </ModalDialog.Footer>
      </ModalDialog>
    </div>
  );
};

export default CourseSyncActionsPage;
