import { useParams } from 'react-router-dom';
import { getAuthenticatedHttpClient, getSiteConfig } from '@openedx/frontend-base';
import { useState, useEffect } from 'react';
import {
  Alert, Spinner, Hyperlink,
} from '@openedx/paragon';

const getApiBaseUrl = () => getSiteConfig().lmsBaseUrl;

interface ProblemRun {
  id: string;
  problem_usage_key: string;
  problem_display_name: string;
  created: string;
}

interface GroupedRuns {
  [date: string]: ProblemRun[];
}

const RapidResponseReportsPage = () => {
  const { courseId } = useParams<{ courseId: string }>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [groupedRuns, setGroupedRuns] = useState<GroupedRuns>({});

  const baseUrl = `${getApiBaseUrl()}/courses/${courseId}/instructor/api`;

  useEffect(() => {
    const fetchRuns = async () => {
      try {
        const client = getAuthenticatedHttpClient();
        const response = await client.get(`${baseUrl}/rapid_response_runs`);
        const runs: ProblemRun[] = Array.isArray(response.data) ? response.data : response.data?.problem_runs || [];

        // Group by date
        const grouped: GroupedRuns = {};
        runs.forEach((run) => {
          const date = new Date(run.created).toLocaleDateString('en-US', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            timeZone: 'UTC',
          });
          if (!grouped[date]) {
            grouped[date] = [];
          }
          grouped[date].push(run);
        });
        setGroupedRuns(grouped);
      } catch (err: any) {
        const message = err.response?.data?.error || err.message || 'Failed to load rapid response data';
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    fetchRuns();
  }, [baseUrl]);

  const getDownloadUrl = (runId: string) =>
    `${baseUrl}/rapid_response_report/${runId}`;

  const formatTime = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZone: 'UTC',
    });
  };

  if (loading) {
    return (
      <div className="text-center p-4">
        <Spinner animation="border" screenReaderText="Loading..." />
      </div>
    );
  }

  if (error) {
    return <Alert variant="danger" className="m-4">{error}</Alert>;
  }

  const dates = Object.keys(groupedRuns);

  if (dates.length === 0) {
    return (
      <div className="p-4">
        <h3>Rapid Responses</h3>
        <p>No rapid response runs found for this course.</p>
      </div>
    );
  }

  return (
    <div className="rapid-response-reports-page p-4">
      <h3>Rapid Responses</h3>
      <ul>
        {dates.map((date) => (
          <li key={date}>
            <strong>{date}</strong>
            <ul>
              {groupedRuns[date].map((run) => (
                <li key={run.id}>
                  {run.problem_display_name || run.problem_usage_key} - {formatTime(run.created)}:
                  {' '}
                  <Hyperlink destination={getDownloadUrl(run.id)} target="_blank">
                    Download
                  </Hyperlink>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default RapidResponseReportsPage;
