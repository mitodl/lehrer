import { useParams } from 'react-router-dom';
import { getAuthenticatedHttpClient, getSiteConfig } from '@openedx/frontend-base';
import { useState, useCallback } from 'react';
import {
  Button, Alert, Spinner, DataTable, Form, ModalDialog, ActionRow,
} from '@openedx/paragon';

const getApiBaseUrl = () => getSiteConfig().lmsBaseUrl;

const CanvasIntegrationPage = () => {
  const { courseId } = useParams<{ courseId: string }>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<{ type: string; data: any } | null>(null);
  const [assignments, setAssignments] = useState<any[]>([]);
  const [selectedAssignment, setSelectedAssignment] = useState('');
  const [showOverloadConfirm, setShowOverloadConfirm] = useState(false);

  const baseUrl = `${getApiBaseUrl()}/courses/${courseId}/canvas/api`;

  const makeRequest = useCallback(async (endpoint: string, method = 'GET', data: any = null) => {
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const client = getAuthenticatedHttpClient();
      let response;
      if (method === 'GET') {
        response = await client.get(`${baseUrl}/${endpoint}`);
      } else {
        // Send form-encoded so Django's request.POST is populated. The canvas
        // integration view reads flags like unenroll_current via request.POST
        // (form data), which is NOT filled from a JSON body — sending JSON here
        // would silently drop unenroll_current and make "Overload" behave like
        // "Merge". URLSearchParams sets Content-Type: x-www-form-urlencoded.
        const body = data ? new URLSearchParams(data) : undefined;
        response = await client.post(`${baseUrl}/${endpoint}`, body);
      }
      return response.data;
    } catch (err: any) {
      const message = err.response?.data?.error || err.message || 'An error occurred';
      setError(message);
      return null;
    } finally {
      setLoading(false);
    }
  }, [baseUrl]);

  const handleListEnrollments = async () => {
    const data = await makeRequest('list_canvas_enrollments');
    if (data) {
      setResults({ type: 'enrollments', data });
    }
  };

  const handleMergeEnrollments = async () => {
    const data = await makeRequest('add_canvas_enrollments', 'POST', { unenroll_current: false });
    if (data) {
      setResults({ type: 'message', data });
    }
  };

  const handleOverloadEnrollments = async () => {
    setShowOverloadConfirm(false);
    const data = await makeRequest('add_canvas_enrollments', 'POST', { unenroll_current: true });
    if (data) {
      setResults({ type: 'message', data });
    }
  };

  const handlePushGrades = async () => {
    const data = await makeRequest('push_edx_grades', 'POST');
    if (data) {
      setResults({ type: 'message', data });
    }
  };

  const handleLoadAssignments = async () => {
    const data = await makeRequest('list_canvas_assignments');
    if (data) {
      setAssignments(Array.isArray(data) ? data : data.assignments || []);
      setResults({ type: 'assignments', data });
    }
  };

  const handleListGrades = async () => {
    if (!selectedAssignment) {
      setError('Please select an assignment first.');
      return;
    }
    const data = await makeRequest('list_canvas_grades?assignment_id=' + encodeURIComponent(selectedAssignment));
    if (data) {
      setResults({ type: 'grades', data });
    }
  };

  const renderTable = (data: any) => {
    if (!data || (Array.isArray(data) && data.length === 0)) {
      return <p>No results found.</p>;
    }
    const items = Array.isArray(data) ? data : [data];
    if (items.length === 0) return <p>No results found.</p>;
    const columns = Object.keys(items[0]).map(col => ({
      Header: col,
      accessor: col,
    }));
    return (
      <DataTable
        itemCount={items.length}
        data={items}
        columns={columns}
      >
        <DataTable.Table />
      </DataTable>
    );
  };

  const renderResults = () => {
    if (!results) return null;
    const { type, data } = results;
    if (type === 'message') {
      const message = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
      return <Alert variant="success"><pre style={{ margin: 0 }}>{message}</pre></Alert>;
    }
    return renderTable(Array.isArray(data) ? data : data.results || data.enrollments || [data]);
  };

  return (
    <div className="canvas-integration-page p-4">
      <section className="mb-4">
        <h3>Canvas Enrollments</h3>
        <div className="d-flex gap-2 flex-wrap mb-3">
          <Button variant="outline-primary" onClick={handleListEnrollments} disabled={loading}>
            List Enrollments on Canvas
          </Button>
          <Button variant="outline-primary" onClick={handleMergeEnrollments} disabled={loading}>
            Merge Enrollment List Using Canvas
          </Button>
          <Button variant="outline-primary" onClick={() => setShowOverloadConfirm(true)} disabled={loading}>
            Overload Enrollment List Using Canvas
          </Button>
        </div>
      </section>

      <hr />

      <section className="mb-4">
        <h3>Export Grades to Canvas</h3>
        <div className="d-flex gap-2 flex-wrap mb-3">
          <Button variant="outline-primary" onClick={handlePushGrades} disabled={loading}>
            Push All MITx Grades to Canvas
          </Button>
          <Button variant="outline-primary" onClick={handleLoadAssignments} disabled={loading}>
            Load Canvas Assignments
          </Button>
        </div>

        {assignments.length > 0 && (
          <div className="d-flex align-items-center gap-2 mb-3">
            <Form.Group className="mb-0">
              <Form.Label className="mr-2">Assignment:</Form.Label>
              <Form.Control
                as="select"
                value={selectedAssignment}
                onChange={(e) => setSelectedAssignment(e.target.value)}
                style={{ width: 'auto', display: 'inline-block' }}
              >
                <option value="">-- Select --</option>
                {assignments.map((a) => (
                  <option key={a.id} value={a.id}>{a.name || a.id}</option>
                ))}
              </Form.Control>
            </Form.Group>
            <Button variant="outline-primary" onClick={handleListGrades} disabled={loading}>
              List Canvas Assignment Grades
            </Button>
          </div>
        )}
      </section>

      <hr />

      {loading && (
        <div className="text-center my-3">
          <Spinner animation="border" screenReaderText="Loading..." />
        </div>
      )}

      {error && (
        <Alert variant="danger" className="my-3">{error}</Alert>
      )}

      {renderResults()}

      <ModalDialog
        title="Overload enrollment list?"
        isOpen={showOverloadConfirm}
        onClose={() => setShowOverloadConfirm(false)}
        hasCloseButton
        isBlocking
        isOverflowVisible={false}
      >
        <ModalDialog.Header>
          <ModalDialog.Title>Overload enrollment list?</ModalDialog.Title>
        </ModalDialog.Header>
        <ModalDialog.Body>
          <p>
            This replaces the course enrollment with the Canvas roster and{' '}
            <strong>unenrolls any current non-staff students who are not in Canvas</strong>.
            This cannot be undone. Continue?
          </p>
        </ModalDialog.Body>
        <ModalDialog.Footer>
          <ActionRow>
            <ModalDialog.CloseButton variant="tertiary">Cancel</ModalDialog.CloseButton>
            <Button variant="danger" onClick={handleOverloadEnrollments}>
              Overload enrollments
            </Button>
          </ActionRow>
        </ModalDialog.Footer>
      </ModalDialog>
    </div>
  );
};

export default CanvasIntegrationPage;
