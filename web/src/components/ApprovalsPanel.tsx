import type { Approval } from "../api/types";
import { formatDate, gateLabel, statusLabel } from "../i18n";

export function ApprovalsPanel({ advancedUi, approvals }: { advancedUi: boolean; approvals: Approval[] }) {
  return (
    <section className="panel">
      <h2>Подтверждения</h2>
      {approvals.length === 0 ? <div className="empty">Сейчас подтверждения не требуются.</div> : null}
      {approvals.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Этап</th>
                <th>Статус</th>
                <th>Создано</th>
                <th>Решено</th>
                <th>Комментарий</th>
                {advancedUi ? <th>Технические данные</th> : null}
              </tr>
            </thead>
            <tbody>
              {approvals.map((approval) => (
                <tr key={approval.id}>
                  <td>{gateLabel(approval.gate)}</td>
                  <td>{statusLabel(approval.status)}</td>
                  <td>{formatDate(approval.created_at)}</td>
                  <td>{formatDate(approval.resolved_at)}</td>
                  <td>{approval.user_comment || ""}</td>
                  {advancedUi ? (
                    <td>
                      <small>ID: {approval.id}</small>
                      <small>artifact_ids: {approval.artifact_ids.join(", ") || "нет"}</small>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
