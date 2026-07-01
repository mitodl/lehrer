import { useQuery } from '@tanstack/react-query';
import { camelCaseObject, getAuthenticatedHttpClient, getSiteConfig } from '@openedx/frontend-base';
import { Collapsible, DataTable, Icon, Skeleton } from '@openedx/paragon';
import { ExpandLess, ExpandMore } from '@openedx/paragon/icons';

// Task states that mean the task has finished — used to stop polling once nothing
// is in flight.
const TERMINAL_STATES = ['SUCCESS', 'FAILURE', 'REVOKED'];

interface CanvasTask {
  taskType?: string;
  taskId?: string;
  requester?: string;
  taskState?: string;
  created?: string;
  status?: string;
  taskMessage?: string;
}

export const canvasTasksQueryKey = (courseId: string) => ['canvasTasks', courseId];

const fetchCanvasTasks = async (courseId: string): Promise<CanvasTask[]> => {
  const baseUrl = `${getSiteConfig().lmsBaseUrl}/courses/${courseId}/canvas/api`;
  const { data } = await getAuthenticatedHttpClient().get(`${baseUrl}/list_canvas_tasks`);
  return camelCaseObject(Array.isArray(data) ? data : data.tasks || []);
};

const formatCreated = (value: string) => {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

/**
 * "Pending Tasks" panel for the Canvas section, mirroring the instructor
 * dashboard's own PendingTasks component (which is not exported, so it is
 * replicated here). Polls list_canvas_tasks while any task is still running and
 * stops once everything reaches a terminal state.
 */
const CanvasPendingTasks = ({ courseId }: { courseId: string }) => {
  const { data: tasks = [], isLoading } = useQuery({
    queryKey: canvasTasksQueryKey(courseId),
    queryFn: () => fetchCanvasTasks(courseId),
    enabled: Boolean(courseId),
    refetchInterval: (query) => {
      const rows = (query.state.data as CanvasTask[] | undefined) ?? [];
      const anyRunning = rows.some(
        (t) => !TERMINAL_STATES.includes((t.taskState ?? '').toUpperCase()),
      );
      return anyRunning ? 5000 : false;
    },
  });

  const columns = [
    { accessor: 'taskType', Header: 'Task Type' },
    { accessor: 'requester', Header: 'Requester' },
    { accessor: 'taskState', Header: 'State' },
    {
      accessor: 'created',
      Header: 'Created',
      Cell: ({ value }: { value: string }) => formatCreated(value),
    },
    { accessor: 'status', Header: 'Status' },
    { accessor: 'taskMessage', Header: 'Message' },
  ];

  const renderContent = () => {
    if (isLoading) {
      return <Skeleton count={2} />;
    }
    if (tasks.length === 0) {
      return <div className="my-3">No pending or recent Canvas tasks.</div>;
    }
    return (
      <DataTable columns={columns} data={tasks} itemCount={tasks.length}>
        <DataTable.Table />
      </DataTable>
    );
  };

  return (
    <Collapsible.Advanced className="mt-4 pt-4 border-top" styling="basic" defaultOpen>
      <Collapsible.Trigger className="collapsible-trigger d-flex border-0 align-items-center text-decoration-none">
        <div className="d-flex">
          <h3 className="text-primary-700 mb-0">Pending Tasks</h3>
        </div>
        <Collapsible.Visible whenClosed>
          <div className="pl-2 d-flex"><Icon className="text-primary-500" src={ExpandMore} /></div>
        </Collapsible.Visible>
        <Collapsible.Visible whenOpen>
          <div className="pl-2 d-flex"><Icon className="text-primary-500" src={ExpandLess} /></div>
        </Collapsible.Visible>
      </Collapsible.Trigger>
      <Collapsible.Body>{renderContent()}</Collapsible.Body>
    </Collapsible.Advanced>
  );
};

export default CanvasPendingTasks;
