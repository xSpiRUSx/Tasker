import type { Approval } from "../api/types";

export function ApprovalsPanel({ approvals }: { approvals: Approval[] }) {
  return (
    <section className="panel">
      <h2>Approvals</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>gate</th>
              <th>status</th>
              <th>created_at</th>
              <th>resolved_at</th>
              <th>user_comment</th>
              <th>artifact_ids</th>
            </tr>
          </thead>
          <tbody>
            {approvals.map((approval) => (
              <tr key={approval.id}>
                <td>{approval.gate}</td>
                <td>{approval.status}</td>
                <td>{formatDate(approval.created_at)}</td>
                <td>{formatDate(approval.resolved_at)}</td>
                <td>{approval.user_comment || ""}</td>
                <td>{approval.artifact_ids.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "";
}
