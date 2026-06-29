import type { Approval } from "../api/types";
import { formatDate } from "../i18n";

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
              <th>создано</th>
              <th>решено</th>
              <th>комментарий</th>
              <th>артефакты</th>
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
